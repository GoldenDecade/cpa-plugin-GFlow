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

## 扩展同步失败时

扩展最新版为 **1.3.4**。从“添加账号”重新下载并覆盖原扩展文件夹，在 Chrome / Edge 扩展管理页点击“重新加载”；原连接配置会保留。仓库更新不会自动更新浏览器里另外解压的旧文件夹。

1.3.4 新增 `webRequest` 权限，只在本次同步创建的 Flow 标签里读取额度请求实际携带的 Cookie，并查询一次额度；同步结束即移除监听、关闭临时标签。更新后需重新加载扩展。浏览器与后台分别校验，只有后台通过且账号保存成功才显示成功。

错误提示和日志区分本机连接、Google 认证、超时、接口变化及项目准备失败；不会输出 Cookie 或密钥。真实账号同步和保存后的后台额度查询已在本机验证通过；真实生成尚未验证。

## 支持的模型与调用方式

提供 **7 个核心基础模型（客户端模型列表仅显示这 7 个）**，彻底避免数十个变体堆满客户端下拉列表。客户端在界面上选择功能参数时，后台**自动调配**到底层笛卡尔积模型：

### 1. 客户端选择的核心模型（严格展示 7 个）
- **图片模型 (3 个)**：
  - `gflow-nano-banana-pro`：Nano Banana Pro（GEM_PIX_2，支持 1:1, 16:9, 9:16, 4:3, 3:4 与 1K/2K/4K 自动调配）
  - `gflow-nano-banana-2-lite`：Nano Banana 2 Lite（HARBOR_SEAL，支持 5 种比例与 1K/2K/4K 自动调配）
  - `gflow-nano-banana-2.1`：Nano Banana 2.1（BELUGA，支持 5 种比例与 1K/2K/4K 自动调配）
- **视频模型 (4 个)**：
  - `gflow-omni-1.1-flash`：Omni 1.1 Flash（支持 4s/6s/8s/10s 时长与横/竖屏自动调配，原生支持多张参考图）
  - `gflow-veo-3.1-lite`：Veo 3.1 - Lite（支持 4s/6s/8s 时长与横/竖屏自动调配）
  - `gflow-veo-3.1-fast`：Veo 3.1 - Fast（支持 4s/6s/8s 时长与横/竖屏自动调配）
  - `gflow-veo-3.1-quality`：Veo 3.1 - Quality（支持 4s/6s/8s 时长与横/竖屏自动调配）

### 2. 功能选择自动调配 (Auto-dispatch)
当客户端选择上述 7 个模型时，后台会自动根据请求携带的参数解析调配：
- **图片调配**：根据客户端选择的 `aspectRatio`（1:1、16:9、9:16、4:3、3:4）或 OpenAI `size`（如 1024x1024、1792x1024 等），以及分辨率 `imageSize`（1K、2K、4K）或 OpenAI `quality`（standard、medium、hd、high），自动调配到底层 45 个组合之一。未指定时默认使用 16:9 标准 1K。
- **视频调配**：根据客户端选择的时长（4s、6s、8s、10s）与方向（16:9 landscape、9:16 portrait），以及是否有附带参考图（自动走 I2V/R2V），自动调配到底层 26 个视频组合之一。未指定时默认使用 8s 16:9 横屏。

### 3. 底层保留的笛卡尔积变体（支持直接调用与函数调用）
底层完整保留所有排列组合，若第三方客户端或智能体直接传具体变体名或调用函数，后台依然直接匹配执行：
- **图片变体（3 基础 × 5 比例 × 3 分辨率 = 45 种）**：
  - 例如：`gflow-nano-banana-2.1-square-4k`（1:1 4K）、`gflow-nano-banana-pro-portrait-2k`（9:16 2K）、`gflow-nano-banana-2-lite-four-three`（4:3 1K）等。
- **视频变体（Veo 3 族 × 3 时长 × 2 方向 + Omni 4 时长 × 2 方向 = 26 种）**：
  - 例如：`gflow-veo-3.1-fast-4s-portrait`（4s 竖屏）、`gflow-omni-1.1-flash-10s-landscape`（10s 横屏）等。
- 后台同时兼容带历史 Gemini 别名（如 `gflow-gemini-3.1-flash-image-square`）以及数字比例命名（如 `-16-9`、`-1-1`）。

## 也可以手动粘贴

GFlow → 添加账号 → “方式二：手动粘贴”。复制完整 Cookie 或 Cookie JSON，也接受 Session Token；新版 Flow 若没有旧 Token 字段，请优先用扩展。展开输入框下方的帮助可查看 F12 获取步骤。

## 首次安装设置

在 EasyCPA 的“插件 → GFlow → 配置”中填写一次内核管理密钥 management_key。它不是客户端 API Key。之后从插件菜单打开 GFlow 即可自动连接，页面不显示密钥输入框。

“复制扩展配置”包含管理凭据，仅粘贴到本机 GFlow 登录助手。扩展使用 chrome.storage.local 保存，不通过 Chrome 同步；清除配置可移除保存的数据。不要公开 Cookie 或扩展连接配置。

## 免费和收费范围

GFlow 与浏览器扩展本身免费。Google Flow 订阅和生成积分、付费打码平台、代理费用另计。本地浏览器打码免平台服务费，但需可用的浏览器环境。

添加 / 同步账号会验证登录态、查询额度，并可能创建项目；不会自动生成图片或视频。同步不会启用已停用的账号。

## 验证范围

已用虚构数据验证扩展 Cookie 范围、同步鉴权、账号新增与更新、重复任务合并及页面连接。已在本机安装扩展并核对文件版本。2026 年 10 月 16 日本机验证：登录助手 1.3.4 真实同步成功，账号已保存并启用；后台使用已保存登录态独立查询额度成功。真实图片 / 视频生成尚未验证。

## 来源

GFlow 内嵌的模型适配代码参考 [TheSmallHanCat/flow2api](https://github.com/TheSmallHanCat/flow2api)，保留其 MIT 声明。GFlow 登录助手独立实现，未复制未声明许可证的第三方浏览器扩展源码。


### Generation lifecycle repair

Generation requests are attempted once and have bounded CAPTCHA/overall timeouts. Windows clients can stop their own request through a request-specific named pipe; queued cancellation cannot close the active browser. The dedicated browser runs headless and is reclaimed after the task. Python requires psutil for process ownership checks.

Cookie injection preserves explicit site scopes and handles legacy three-site mirrors without copying Flow-only OSID cookies to Google Accounts. Account sync and quota checks do not verify CAPTCHA readiness. Current local preflight reaches the signed-in Flow projects page, but reCAPTCHA script readiness still times out; real GFlow generation is not verified by this repair.
