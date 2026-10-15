# GFlow

在 EasyCPA 的同一个端口使用 Google Flow 图片 / 视频模型，默认端口为 8317。

## 添加账号：推荐浏览器同步

1. 在 GFlow 点击“添加账号”，点击“复制下载地址”，在 Chrome / Edge 地址栏粘贴并回车，下载 **GFlow 登录助手** 并解压。在 Chrome / Edge 扩展管理页开启“开发者模式”，加载解压后的文件夹。
2. 在同一窗口点击“复制扩展配置”。打开浏览器扩展，粘贴配置，填写当前 Google 邮箱。
3. 在该浏览器登录 Google Flow，点击扩展的“保存并同步”，返回 GFlow 刷新账号列表。

EasyCPA 内嵌窗口限制直接下载和新窗口跳转，因此下载和源码入口改为复制地址；下载地址直接使用本机已安装的扩展包，无需访问 GitHub。复制被限制时会显示可手动复制的地址。

之后可一键同步，或每 60 分钟自动同步；自动同步需要浏览器运行。多个 Google 账号请使用不同的浏览器配置文件。

- [扩展 GitHub 与安装说明](https://github.com/daodeqing/cpa-plugin-GFlow/tree/main/browser-extension)
- [直接下载 GFlow 登录助手 ZIP](https://github.com/daodeqing/cpa-plugin-GFlow/raw/refs/heads/main/downloads/GFlow-browser-extension.zip)

## 也可以手动粘贴

GFlow → 添加账号 → “方式二：手动粘贴”。复制完整 Cookie 或 Cookie JSON，也接受 Session Token；新版 Flow 若没有旧 Token 字段，请优先用扩展。展开输入框下方的帮助可查看 F12 获取步骤。

## 首次安装设置

在 EasyCPA 的“插件 → GFlow → 配置”中填写一次内核管理密钥 management_key。它不是客户端 API Key。之后从插件菜单打开 GFlow 即可自动连接，页面不显示密钥输入框。

“复制扩展配置”包含管理凭据，仅粘贴到本机 GFlow 登录助手。扩展使用 chrome.storage.local 保存，不通过 Chrome 同步；清除配置可移除保存的数据。不要公开 Cookie 或扩展连接配置。

## 免费和收费范围

GFlow 与浏览器扩展本身免费。Google Flow 订阅和生成积分、付费打码平台、代理费用另计。本地浏览器打码免平台服务费，但需可用的浏览器环境。

添加 / 同步账号会验证登录态、查询额度，并可能创建项目；不会自动生成图片或视频。同步不会启用已停用的账号。

## 验证范围

已用虚构数据验证扩展 Cookie 范围、同步鉴权、账号新增与更新、重复任务合并及页面连接。真实浏览器扩展安装和真实 Google 账号同步尚未验证；真实图片 / 视频生成尚未验证。

## 来源

GFlow 内嵌的模型适配代码参考 [TheSmallHanCat/flow2api](https://github.com/TheSmallHanCat/flow2api)，保留其 MIT 声明。GFlow 登录助手独立实现，未复制未声明许可证的第三方浏览器扩展源码。
