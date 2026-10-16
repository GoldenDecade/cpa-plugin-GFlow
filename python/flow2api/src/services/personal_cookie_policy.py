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
