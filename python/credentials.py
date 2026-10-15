"""解析账号粘贴内容，不访问 Google，不输出凭据。"""
import json
from urllib.parse import unquote

from src.services.browser_cookie_utils import (
    extract_session_token_from_cookie_payload,
    normalize_cookie_header_text,
    normalize_cookie_storage_text,
    parse_browser_cookie_payload,
)


def normalize_account_input(st=None, google_cookies=None):
    """返回 (Session Token, 完整 Cookie)，避免把 Cookie 串当成 ST 发给上游。"""
    explicit_st = str(st or "").strip()
    raw = google_cookies if google_cookies is not None else ""
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith(("{", "[")):
            try:
                raw = json.loads(raw)
            except ValueError:
                raise ValueError("Cookie JSON 格式无效，请重新复制完整内容") from None
    if isinstance(raw, dict) and any(k in raw for k in ("st", "google_cookies", "cookies")):
        explicit_st = explicit_st or str(raw.get("st") or "").strip()
        raw = raw.get("google_cookies", raw.get("cookies", ""))
    if isinstance(raw, (dict, list)):
        cookie_text = normalize_cookie_storage_text(raw)
    else:
        cookie_text = normalize_cookie_header_text(str(raw or ""))
        if cookie_text and "=" not in cookie_text:
            explicit_st = explicit_st or cookie_text
            cookie_text = ""
    if cookie_text:
        if chr(10) in cookie_text or chr(13) in cookie_text:
            raise ValueError("请只复制 Cookie 的值，不要粘贴整段请求报文")
        parsed = parse_browser_cookie_payload(cookie_text)
        if not parsed:
            raise ValueError("未识别到 Cookie，请检查复制的是请求标头 Cookie 的值")
        explicit_st = explicit_st or extract_session_token_from_cookie_payload(cookie_text)
    if not explicit_st and not cookie_text:
        raise ValueError("请粘贴 Cookie 或 Session Token")
    return unquote(explicit_st), cookie_text
