"""TLS 握手兼容处理；只有证明正文尚未发送时才允许一次协议重连。"""
import asyncio
import time
from urllib.parse import urlsplit

from curl_cffi.const import CurlHttpVersion, CurlInfo
from curl_cffi.requests.exceptions import RequestException


def unsent_tls_handshake(error):
    """未知回执、已上传正文、收到响应或发生重定向时一律不重发。"""
    if not isinstance(error, RequestException) or int(error.code or 0) != 35:
        return False
    response = error.response
    if response is None or response.status_code != 0:
        return False
    info = getattr(response, "infos", {})
    required = (CurlInfo.SIZE_UPLOAD_T, CurlInfo.SIZE_DOWNLOAD_T, CurlInfo.REDIRECT_COUNT)
    return all(key in info and info[key] == 0 for key in required)


async def request_with_tls_recovery(session_factory, method, url, **kwargs):
    """保持同一代理、凭据及证书校验；不重试已提交生成或业务错误。"""
    deadline = time.monotonic() + float(kwargs["timeout"])
    options = dict(kwargs)
    infos = [CurlInfo.SIZE_UPLOAD_T, CurlInfo.SIZE_DOWNLOAD_T, CurlInfo.REDIRECT_COUNT]
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError("GFlow transport deadline exceeded")
        options["timeout"] = remaining
        try:
            async with session_factory(trust_env=False, curl_infos=infos) as session:
                send = session.get if method.upper() == "GET" else session.post
                return await send(url, **options)
        except RequestException as error:
            can_reconnect = (
                attempt == 0 and urlsplit(url).scheme == "https"
                and options.get("http_version") != CurlHttpVersion.V1_1
                and unsent_tls_handshake(error)
            )
            if not can_reconnect:
                raise
            # 仅改变传输协议，不关闭 TLS 校验、不换代理、不增加生成重试预算。
            options["http_version"] = CurlHttpVersion.V1_1
