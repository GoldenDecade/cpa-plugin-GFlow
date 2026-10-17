"""保持 Cookie 的站点边界，兼容旧版三站复制的登录数据。"""
import json
from urllib.parse import urlparse

SHARED_LOGIN_NAMES = frozenset({
    "SID", "HSID", "SSID", "APISID", "SAPISID", "SIDCC",
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "__Secure-1PSIDRTS", "__Secure-3PSIDRTS",
})
LEGACY_HOSTS = frozenset({"flow.google.com", "www.google.com", "www.recaptcha.net"})

def scoped_personal_cookies(raw_cookie):
    from .browser_cookie_utils import parse_browser_cookie_payload
    cookies = parse_browser_cookie_payload(raw_cookie)
    structured = str(raw_cookie or "").lstrip().startswith(("[", "{"))
    mirrors = {}
    for cookie in cookies:
        if not cookie.get("domain"):
            key = (cookie["name"], cookie["value"], cookie.get("path", "/"))
            mirrors.setdefault(key, set()).add(urlparse(cookie.get("url", "")).hostname)
    result = {}
    for original in cookies:
        cookie = dict(original)
        key = (cookie["name"], cookie["value"], cookie.get("path", "/"))
        legacy = LEGACY_HOSTS.issubset(mirrors.get(key, set())) and not cookie.get("domain")
        if not structured or legacy:
            # 旧版把整个 Flow 请求头复制到三个站点；OSID 等站点 Cookie
            # 不能注入 accounts/www.google.com，否则会触发 CookieMismatch。
            cookie.pop("url", None)
            cookie.pop("domain", None)
            cookie["path"] = "/"
            cookie["secure"] = True
            if cookie["name"] in SHARED_LOGIN_NAMES:
                cookie["domain"] = ".google.com"
            else:
                cookie["url"] = "https://flow.google.com/"
        identity = (cookie["name"], cookie.get("domain") or cookie.get("url"), cookie.get("path", "/"))
        result[identity] = cookie
    normalized = list(result.values())
    parent_logins = {
        (c["name"], c["value"], c.get("path", "/"))
        for c in normalized
        if c["name"] in SHARED_LOGIN_NAMES and c.get("domain") == ".google.com"
    }
    # Browser refresh can export both a legacy Flow host copy and the actual
    # parent login Cookie. Equal values are redundant; differing values retain
    # their original host boundary.
    return [
        c for c in normalized
        if not (
            c["name"] in SHARED_LOGIN_NAMES
            and (urlparse(c.get("url", "")).hostname == "flow.google.com"
                 or str(c.get("domain", "")).lstrip(".") == "flow.google.com")
            and (c["name"], c["value"], c.get("path", "/")) in parent_logins
        )
    ]


def merge_personal_cookie_payloads(base_cookie, browser_cookie_items):
    """先恢复旧请求头的站点边界，再按浏览器真实作用域回填更新值。"""
    from .browser_cookie_utils import merge_browser_cookie_payloads

    # 原始 Cookie 头没有域信息；若直接交给通用合并器，会把所有登录
    # Cookie 当作 Flow 主机副本，与浏览器导出的 .google.com 再存一份。
    previous = scoped_personal_cookies(base_cookie)
    current = scoped_personal_cookies(browser_cookie_items)
    structured = isinstance(base_cookie, (dict, list)) or str(base_cookie or "").lstrip().startswith(("[", "{"))
    if not structured:
        from .browser_cookie_utils import parse_browser_cookie_payload
        raw_pairs = {
            (cookie["name"], cookie["value"], cookie.get("path", "/"))
            for cookie in parse_browser_cookie_payload(base_cookie)
        }

        def flow_host(cookie):
            return (urlparse(cookie.get("url", "")).hostname == "flow.google.com"
                    or str(cookie.get("domain", "")).lstrip(".").lower() == "flow.google.com")

        def reaches_flow(cookie):
            domain = str(cookie.get("domain", "")).lstrip(".").lower()
            return flow_host(cookie) or bool(domain and "flow.google.com".endswith("." + domain))

        # 只有本次仍保留原始头时，才能识别刚注入的无域 Flow 副本。
        # 浏览器另有同名、同路径的真实站点条目时，用其作用域和值；
        # 不对已有结构化数据推断来源，也不跨路径合并合法 Cookie。
        authoritative = {
            (cookie["name"], cookie.get("path", "/"))
            for cookie in current if not flow_host(cookie) and reaches_flow(cookie)
        }
        current = [
            cookie for cookie in current
            if not (flow_host(cookie)
                    and (cookie["name"], cookie["value"], cookie.get("path", "/")) in raw_pairs
                    and (cookie["name"], cookie.get("path", "/")) in authoritative)
        ]
        observed = {(cookie["name"], cookie.get("path", "/"))
                    for cookie in current if reaches_flow(cookie)}
        previous = [cookie for cookie in previous
                    if (cookie["name"], cookie.get("path", "/")) not in observed]
    merged = merge_browser_cookie_payloads(previous, current)
    if not merged:
        return ""
    # 清理同值的旧 Flow 登录镜像；不同主机、路径或值仍保留真实边界。
    return json.dumps(scoped_personal_cookies(merged), ensure_ascii=False, separators=(",", ":"))
