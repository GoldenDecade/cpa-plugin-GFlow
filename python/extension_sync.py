"""GFlow 浏览器同步；只有管理鉴权通过后才能调用。"""
import hashlib
import re
from datetime import datetime

from credentials import normalize_account_input


async def sync_extension_account(service, params):
    email = str(params.get("login_account") or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise ValueError("请在 GFlow 登录助手中填写当前 Google 账号邮箱")
    if not isinstance(params.get("google_cookies"), (str, list, dict)):
        raise ValueError("扩展未提交完整 Cookie，请登录 Google Flow 后重试")
    session_token, cookies = normalize_account_input(None, params["google_cookies"])
    if not cookies or len(cookies.encode("utf-8")) > 262144:
        raise ValueError("Cookie 内容为空或过大，请重新同步")
    from src.services.browser_cookie_utils import validate_flow_cookie_storage
    validate_flow_cookie_storage(cookies)
    await service.initialize()
    try:
        session = await service.flow_client.st_to_at(session_token, google_cookies=cookies)
    except Exception:
        raise ValueError("Google 登录态验证失败，请确认 Flow 已登录、网络正常后重新同步") from None
    observed_email = str((session.get("user") or {}).get("email") or "").strip().lower()
    if observed_email and observed_email != email:
        raise ValueError("扩展填写的邮箱与 Google 当前登录账号不一致")
    existing = await service.db.get_token_by_email(email)
    if existing:
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
        return {"success": True, "action": "updated", "token_id": existing.id, "message": "GFlow 账号登录态已更新；账号原有启停状态保持不变"}
    account = await service.token_manager.add_token(
        st=session_token,
        google_cookies=cookies,
        login_account=email,
        protocol_mode="protocol",
        remark="由 GFlow 登录助手添加",
    )
    return {"success": True, "action": "added", "token_id": account.id, "message": "GFlow 账号已添加，可返回账号列表刷新查看"}
