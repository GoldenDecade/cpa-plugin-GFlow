# GFlow 登录助手

将当前 Chrome / Edge 的 Google Flow 登录态同步到本机 EasyCPA。

## 安装与使用

1. 下载 [扩展 ZIP](https://github.com/daodeqing/cpa-plugin-GFlow/raw/main/downloads/GFlow-browser-extension.zip) 并解压。在 `chrome://extensions/`（Edge 用 `edge://extensions/`）开启开发者模式，加载已解压的扩展。
2. 在 EasyCPA 的 GFlow → 添加账号中点击“复制扩展配置”，粘贴到助手的快捷导入框，填写当前 Google 邮箱。
3. 在同一浏览器配置中登录 [Google Flow](https://flow.google.com/projects)，点击“保存并立即同步”。

首次保存后会沿用本机连接配置，无需反复粘贴或填写凭据。每 60 分钟自动同步需要浏览器保持运行。多个 Google 账号建议使用独立的浏览器配置文件。

## 费用与数据

- GFlow 扩展和源码免费，无需另行注册 GFlow 账号。
- Google Flow 需要 Google 账号；可用免费额度、地区条件、订阅和积分以 Google 页面为准。付费订阅不会被此扩展自动购买。
- 第三方验证码服务通常需要注册、充值并填写 API Key；本地浏览器方式无需购买验证码服务。代理可能有额外费用。
- 同步会验证登录、查询额度，并可能准备项目；不会发起图片或视频生成。
- 扩展仅在同步时观察自己新开的 Flow 标签，读取只读额度请求实际携带的 Cookie，随后立即移除监听并关闭标签；不会观察其他标签。登录凭据只提交到配置中的本机 GFlow 接口，默认共用端口 8317。
- 配对凭据只存在当前扩展的本机存储；不会通过 Chrome 同步。页面关闭后不会显示已保存的完整凭据。日志隐藏邮箱和凭据。

## 更新与故障排查

当前版本 **1.3.4**。覆盖原扩展目录的程序文件后，在扩展管理页点击“重新加载”。已有连接配置仍可使用。

1.3.4 新增 webRequest 权限以读取本次额度请求实际携带的 Cookie；更新后需重新加载扩展。浏览器额度检查结果只用于定位，后台仍须独立验证通过才会保存账号。

同步失败会显示红色提示；“查看同步日志”可看到经过筛选的错误阶段、RPC 和状态码。“Cookie 提取成功”仅表示读取完成，只有 Google 验证且账号保存成功才显示同步成功。

源码：[GFlow](https://github.com/daodeqing/cpa-plugin-GFlow/tree/main/browser-extension)。接口处理参考 Flow2API；GFlow 是独立适配，不代表 Google 或 EasyCPA 官方背书。真实账号同步仍在排查，真实图片和视频生成尚未验证。
