"""GFlow 浏览器同步；仅返回可公开的诊断，不包含 Cookie 或连接密钥。"""
import asyncio
import hashlib
import re
from datetime import datetime

from credentials import normalize_account_input


class ExtensionSyncError(ValueError):
    def __init__(self, message, *, code, status_code=400, stage="input"):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.stage = stage

    def result(self):
        return {
            "success": False,
            "status_code": self.status_code,
            "error": {"code": self.code, "message": str(self), "stage": self.stage},
        }


def classify_sync_failure(error, stage="session"):
    """只按已知错误特征分类；不把上游响应、Cookie 或异常原文返回浏览器。"""
    text = str(error).lower()
    curl_code = getattr(error, "code", None)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)) or curl_code == 28 or "timed out" in text:
        return ExtensionSyncError(
            "连接 Google Flow 超时，请检查 GFlow 的代理设置后重试。",
            code="gflow_upstream_timeout", status_code=504, stage=stage,
        )
    if any(term in text for term in ("code=401", "code=403", "public_error_user_not_authenticated", "登录认证失败")):
        return ExtensionSyncError(
            "Google 未接受当前登录态。请在同一浏览器打开 Flow，确认能进入项目页，刷新网页后再点“立即同步”；多个 Google 账号请使用独立浏览器配置。",
            code="gflow_google_auth_rejected", status_code=422, stage=stage,
        )
    if any(term in text for term in ("bootstrap metadata", "returned no payload")):
        return ExtensionSyncError(
            "Flow 返回了无法识别的页面或接口响应。请先打开 Flow 项目页完成登录或欢迎页；若仍失败，需要更新 GFlow 的网页接口适配。",
            code="gflow_upstream_protocol", status_code=502, stage=stage,
        )
    if curl_code in (5, 6, 7, 35, 60) or any(term in text for term in ("could not resolve", "failed to connect", "proxy connection", "ssl connect")):
        return ExtensionSyncError(
            "GFlow 后台无法连接 Google Flow，请检查 GFlow 设置中的代理地址与端口。",
            code="gflow_upstream_network", status_code=502, stage=stage,
        )
    if stage == "prepare":
        return ExtensionSyncError(
            "登录态已验证，但准备 Flow 项目失败，账号尚未完成添加。请确认网页可以创建项目后重试。",
            code="gflow_project_prepare_failed", status_code=502, stage=stage,
        )
    if stage in ("initialize", "save"):
        return ExtensionSyncError(
            "GFlow 本地账号数据未能保存，请重启插件后重试。",
            code="gflow_local_storage_failed", status_code=500, stage=stage,
        )
    return ExtensionSyncError(
        "Google 登录态验证失败，请在同一浏览器确认 Flow 项目页可正常打开后重试。",
        code="gflow_session_validation_failed", status_code=502, stage=stage,
    )


async def sync_extension_account(service, params):
    email = str(params.get("login_account") or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise ExtensionSyncError("请在 GFlow 登录助手中填写当前 Google 账号邮箱", code="gflow_invalid_email")
    if not isinstance(params.get("google_cookies"), (str, list, dict)):
        raise ExtensionSyncError("扩展未提交完整 Cookie，请登录 Google Flow 后重试", code="gflow_missing_cookies")
    try:
        session_token, cookies = normalize_account_input(None, params["google_cookies"])
        if not cookies or len(cookies.encode("utf-8")) > 262144:
            raise ValueError("Cookie 内容为空或过大")
        from src.services.browser_cookie_utils import validate_flow_cookie_storage
        validate_flow_cookie_storage(cookies)
    except ValueError:
        raise ExtensionSyncError(
            "未获取到完整 Flow 登录态，请先在同一浏览器登录 flow.google.com 后再同步。",
            code="gflow_incomplete_cookies",
        ) from None
    try:
        await service.initialize()
    except Exception as error:
        raise classify_sync_failure(error, "initialize") from None
    try:
        session = await service.flow_client.st_to_at(session_token, google_cookies=cookies)
    except Exception as error:
        raise classify_sync_failure(error) from None
    observed_email = str((session.get("user") or {}).get("email") or "").strip().lower()
    if observed_email and observed_email != email:
        raise ExtensionSyncError(
            "扩展填写的邮箱与 Google 当前登录账号不一致",
            code="gflow_account_mismatch", status_code=409, stage="session",
        )
    try:
        existing = await service.db.get_token_by_email(email)
    except Exception as error:
        raise classify_sync_failure(error, "save") from None
    if existing:
        try:
            expires = session.get("expires")
            expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None
            await service.db.update_token(
                existing.id,
                google_cookies=cookies,
                st=session_token or "frontend-" + hashlib.sha256(cookies.encode()).hexdigest()[:32],
                at=session["access_token"],
                at_expires=expires_at,
                login_account=email,
                protocol_mode="protocol",
                **({"credits": session["credits"]} if "credits" in session else {}),
            )
        except Exception as error:
            raise classify_sync_failure(error, "save") from None
        return {"success": True, "action": "updated", "token_id": existing.id, "message": "GFlow 账号登录态已更新；账号原有启停状态保持不变"}
    try:
        account = await service.token_manager.add_token(
            st=session_token,
            google_cookies=cookies,
            login_account=email,
            protocol_mode="protocol",
            remark="由 GFlow 登录助手添加",
            validated_session=session,
        )
    except Exception as error:
        raise classify_sync_failure(error, "prepare") from None
    return {"success": True, "action": "added", "token_id": account.id, "message": "GFlow 账号已添加，可返回账号列表刷新查看"}
