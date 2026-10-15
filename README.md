# GFlow (cpa-plugin-GFlow)

Google Flow (Veo 3.1 & Nano Banana) model and account pool plugin for EasyCLIProxyAPI


## 安装配置与页面自动连接

首次添加插件时，在 EasyCPA 的“插件 → GFlow → 配置”中填写一次 `management_key`（内核管理密钥），不是客户端 API Key。现有本机安装已经配置完成。之后从 EasyCPA 的 GFlow 插件菜单打开页面即可自动连接，业务页面不再显示密钥输入框。

管理密钥保存在内核的插件配置中，不写入公开 HTML、URL 或浏览器 localStorage。插件菜单通过受管理鉴权保护的元数据传递随机启动票据，页面校验票据后连接；票据从页面地址中立即移除。浏览器使用 HttpOnly、SameSite=Strict 的插件会话 Cookie 支持刷新。普通未授权访问不会获得管理凭据；重启内核后应从插件菜单重新打开。管理密钥发生变化时，在插件配置中同步更新即可。

## 获取 Google Flow Cookie

添加账号弹窗中已内置完整步骤：

1. 在 Chrome / Edge 打开 https://flow.google.com/，登录你有权使用的账号。
2. 按 F12，进入 Network / 网络，刷新页面。
3. 选中当前 Flow 网站的请求，在 Headers / 标头 → Request Headers / 请求标头中复制 Cookie 的值。不要复制响应中的 Set-Cookie，也不要粘贴整段 HTTP 请求。
4. 将完整 Cookie 粘贴到添加账号输入框。也支持 Cookie 对象数组 JSON，以及包含 st / google_cookies 的 JSON。
5. 如果浏览器的 Application / Cookies 中存在 __Secure-next-auth.session-token 或 next-auth.session-token，可单独复制其 Value。新版 Flow 若没有该字段，使用完整 Cookie，不要用其他任意字段替代。

插件会分别解析 Session Token 和完整 Cookie，完整 Cookie 不会被当成 ST 原样发送。Cookie 相当于登录凭据，不应贴到聊天、截图或 GitHub；过期后需在浏览器重新登录并重新复制。添加账号会验证登录态、查询额度，并可能创建项目，不会自动执行图片或视频生成。

离线回归：`python -B tests/test_management_ui.py`、`python -B tests/test_bootstrap.py`（先构建动态库），Cookie 测试在安装依赖的 Python 环境运行 `python -B tests/test_credentials.py`。测试只使用虚构凭据；真实生成尚未验证。
