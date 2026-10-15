# GFlow 登录助手

Chrome / Edge 浏览器扩展，将当前 Google Flow 登录态同步到本机 EasyCPA 的 GFlow 插件。

## 安装一次

1. 下载仓库中的 `downloads/GFlow-browser-extension.zip` 并解压。
2. 打开 `chrome://extensions/`（Edge 用 `edge://extensions/`），开启“开发者模式”。
3. 点击“加载已解压的扩展程序”，选择解压后包含 `manifest.json` 的文件夹。

## 添加账号

1. 在 EasyCPA 打开 **GFlow → 添加账号 → 复制扩展配置**。
2. 打开浏览器中的 **GFlow 登录助手**，粘贴配置，填写当前 Google 邮箱。
3. 在同一个浏览器配置中登录 Google Flow，点击 **保存并同步**，返回 GFlow 刷新列表。

之后只需点击“立即同步”；也可以每 60 分钟自动同步，浏览器需要保持运行。多个账号请使用不同的浏览器配置文件。切换账号后，更新扩展中的邮箱再同步。

扩展和源码免费。Flow 生成积分、订阅、代理或验证码服务费用另计。同步会验证登录态、查询额度，并可能创建项目，不会发起图片或视频生成。

## 数据范围

- 只读取浏览器访问 `https://flow.google.com/projects` 时匹配的 Cookie，不扫描其他网站。
- 只连接 `127.0.0.1` / `localhost` 的 GFlow 同步接口，默认共用端口 8317。
- 连接配置包含内核管理凭据，仅保存在本机扩展的 `chrome.storage.local`，不通过 Chrome 同步。不要分享配置或提交截图。
- 新版 Flow 登录态通常需要完整 Cookie；只拿到旧 Session Token 时，可改用 GFlow 的“手动粘贴”方式，支持范围取决于 Flow 当前登录机制。
- 手动点击同步和定时同步复用同一任务；不自动重试新增请求，避免超时重试造成重复账号。不会自动启用已经停用的账号。

此扩展为 GFlow 独立实现，未复制第三方 Token Updater 的源码。浏览器安装和真实 Google 登录同步尚未进行验收；模拟同步、鉴权与账号更新逻辑有离线测试覆盖。
