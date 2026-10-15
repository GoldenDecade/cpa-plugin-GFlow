# GFlow (cpa-plugin-GFlow)

Google Flow (Veo 3.1 & Nano Banana) model and account pool plugin for EasyCLIProxyAPI


## 管理页面连接

插件资源页与 EasyCPA 桌面程序不共享管理凭据。打开 GFlow 后，从 EasyCPA 首页的“管理密钥”处复制密钥，在页面顶部输入并点击“连接并加载”。这里使用内核管理密钥，不是客户端 API Key、Google Cookie 或付费打码平台的 API Key。

密钥只保留在当前页面内存，连接后清空输入框；不会写入 URL、localStorage 或 sessionStorage。刷新、关闭页面或点击“断开连接”后，需要重新连接。HTTP 401/403 表示管理鉴权失败，不能据此判断 Python 离线。首次连接成功且账号池为空时，应显示 0 个账号和“暂无 GFlow 账号”。

配置未成功读取时禁止保存，以免用页面默认值覆盖实际配置。账号与状态管理不执行图片或视频生成。
