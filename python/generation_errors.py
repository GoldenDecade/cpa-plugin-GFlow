"""Public generation failures shared by JSON and streaming worker responses."""
import json


def generation_error(payload):
    """Return a worker error envelope without treating failed SSE as success."""
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("data:"):
            text = text[5:].strip()
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict) or not payload.get("error"):
        return None
    raw = payload["error"]
    error = dict(raw) if isinstance(raw, dict) else {"message": str(raw)}
    message = str(error.get("message") or "Google Flow 生成失败")
    status = error.get("status_code", 502)
    try:
        status = int(status)
    except (ValueError, TypeError):
        status = 502
    if not 400 <= status <= 599:
        status = 502
    code = error.get("code") or "gflow_generation_failed"
    if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in message:
        code, status = "gflow_unusual_activity", 403
        message = ("Google Flow 拒绝了本次请求（异常活动，PUBLIC_ERROR_UNUSUAL_ACTIVITY）。"
                   "请在已登录的 Flow 网页确认账号状态；程序未自动重试。")
    elif any(marker in message for marker in ("Google Cookie 已失效", "Flow 登录已失效", "gflow_session_expired")):
        code, status = "gflow_session_expired", 401
        message = "GFlow 的 Google 登录态已失效，请在正常登录的 Flow 浏览器中通过登录助手重新同步 Cookie；仅修改 EasyCPA 地址或密钥无法恢复。"
    return {"message": message, "status_code": status,
            "type": error.get("type") or "generation_error", "code": code}


def account_pool_error(tokens):
    """Keep an empty pool separate from a disabled or expired account."""
    if not tokens:
        return {"message": "没有 GFlow 账号，请先在 GFlow 插件控制台添加或同步 Google Flow 账号",
                "type": "no_active_tokens", "code": "gflow_empty_account_pool", "status_code": 503}
    if any(getattr(t, "ban_reason", None) == "session_expired" for t in tokens):
        return generation_error({"error": {"message": "gflow_session_expired"}})
    return {"message": "GFlow 账号当前已停用。请在插件控制台查看账号状态；登录失效时需重新同步 Google Cookie，手动停用时需启用账号。",
            "type": "no_active_tokens", "code": "gflow_accounts_disabled", "status_code": 503}
