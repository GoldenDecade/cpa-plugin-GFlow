"""只展示已知的账号健康证据，不把启用开关或缓存余额当作可用证明。"""
from collections.abc import Mapping
from datetime import datetime, timezone
import time


def _value(token, name, default=None):
    return token.get(name, default) if isinstance(token, Mapping) else getattr(token, name, default)


def _as_utc(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def account_health(token, *, now=None, recent_validation_expires=0.0,
                   monotonic_now=None, validation_failure=None):
    """从账号快照及当前进程的成功校验 TTL 构造不含凭据的展示状态。

    at_expires 是下次校验时间，不代表 Google Cookie 确认过期。
    只有持久化的明确 session_expired 原因显示登录态失效；网络、浏览器、
    风控和普通刷新失败均保留为需校验，绝不自动推断账号过期。
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    tick = time.monotonic() if monotonic_now is None else monotonic_now
    ban = str(_value(token, "ban_reason", "") or "").strip()
    enabled = bool(_value(token, "is_active", False)) and not ban
    checked = _as_utc(_value(token, "last_st_refresh_at"))

    def state(code, label, level, detail, verified=False):
        return {
            "code": code, "label": label, "level": level, "detail": detail,
            "enabled": enabled, "verified": verified,
            "checked_at": checked.isoformat() if checked else None,
        }

    if ban == "session_expired":
        return state("session_expired", "登录态失效", "danger",
                     "Google 已明确拒绝保存的登录态，请通过登录助手重新同步。")
    if ban:
        label = "请求限流" if ban == "429_rate_limit" else "账号已禁用"
        return state("rate_limited" if ban == "429_rate_limit" else "blocked",
                     label, "danger", "后台已禁用此账号，请查看请求错误与禁用原因。")
    if not enabled:
        return state("disabled", "已手动停用", "warning", "账号开关已关闭。")

    # 调用者传入的最新校验失败会覆盖旧 TTL，但不暴露原始错误中的 Cookie/URL。
    if validation_failure:
        return state("refresh_failed", "需重新校验", "warning",
                     "最近登录校验或刷新失败；请重试并查看请求错误，尚不能据此判断账号过期。")
    try:
        recently_verified = float(recent_validation_expires or 0) > float(tick)
    except (TypeError, ValueError):
        recently_verified = False
    if recently_verified:
        return state("verified", "登录已验证", "success",
                     "最近已通过 Google 登录校验；生成仍取决于额度、验证码与上游响应。", True)

    refresh_result = str(_value(token, "last_st_refresh_result", "") or "").strip()
    if refresh_result and refresh_result.lower() not in {"success", "ok", "成功"}:
        return state("refresh_failed", "需重新校验", "warning",
                     "最近登录校验或刷新失败；请重试并查看请求错误，尚不能据此判断账号过期。")
    expires = _as_utc(_value(token, "at_expires"))
    if expires and expires <= now:
        return state("verification_due", "待重新校验", "warning",
                     "已到登录态重新校验时间；尚未确认失效，缓存积分不代表可用。")
    return state("unverified", "已启用 · 未校验", "warning",
                 "账号已启用，但当前没有近期校验成功记录；缓存积分不代表可用。")


def summarize_account_health(tokens, health_by_id=None):
    """汇总已启用数、近期校验通过数与缓存积分，保持兼容字段语义明确。"""
    health_by_id = health_by_id or {}
    tokens = list(tokens)
    enabled = verified = cached_credits = 0
    for token in tokens:
        health = health_by_id.get(_value(token, "id")) or account_health(token)
        enabled += int(bool(health["enabled"]))
        verified += int(bool(health["verified"]))
        if health["enabled"]:
            try:
                cached_credits += max(0, int(_value(token, "credits", 0) or 0))
            except (TypeError, ValueError):
                pass
    return {
        "total_tokens": len(tokens), "enabled_tokens": enabled,
        "verified_tokens": verified, "active_tokens": verified,
        "cached_credits": cached_credits, "total_credits": cached_credits,
        "credits_are_cached": True,
    }
