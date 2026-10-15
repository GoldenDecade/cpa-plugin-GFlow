# GFlow 登录助手

Chrome / Edge 浏览器扩展，用于将当前浏览器的 Google Flow 登录态安全同步到本机 EasyCPA 的 GFlow 插件。

## 一键安装步骤

1. 下载 [GFlow-browser-extension.zip](https://github.com/daodeqing/cpa-plugin-GFlow/raw/main/downloads/GFlow-browser-extension.zip) 并解压到本地文件夹。
2. 打开 Chrome 地址栏输入并访问：`chrome://extensions/`（Edge 访问 `edge://extensions/`）。
3. 开启页面右上角的**“开发者模式”**开关。
4. 点击**“加载已解压的扩展程序”**，选择解压后的 `GFlow-browser-extension` 文件夹即可。

## 配置与同步（极简 3 步）

1. **登录 Flow**：在当前 Chrome 浏览器中打开并登录 `https://flow.google.com`，确认能进入创作或项目页。
2. **复制配置**：在 EasyCPA GFlow 管理页点击【复制扩展配置】。
3. **一键同步**：点击浏览器右上角 GFlow 助手图标，将配置粘贴至“快捷导入”框（自动填入接口与凭据），核对 Google 邮箱后点击【保存并立即同步】。

## 核心特性

- **后台智能激活**：同步时在后台激活 `flow.google.com/projects` 会话，无需手动 F12 抓包或拼装 Cookie。
- **完整会话保护**：精确提取 Flow 与 Google 账号会话 Cookie，保留域名、路径及安全属性。
- **实时日志看板**：内置【📋 查看同步日志】页面，清晰呈现每步操作与上游诊断，排查问题一目了然。
- **定时自动刷新**：默认每 60 分钟自动同步一次，确保后台模型调用凭据持续有效。
- **安全隔离**：配置仅保存在本机浏览器的 `chrome.storage.local`，仅允许连接本机 `127.0.0.1`，不泄露任何凭据。

## 开源项目与支持

- GitHub 源码：[https://github.com/daodeqing/cpa-plugin-GFlow](https://github.com/daodeqing/cpa-plugin-GFlow)
- 配合 EasyCPA 内核共用端口 `8317`，开箱即用。
