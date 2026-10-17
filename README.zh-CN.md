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

## 支持的模型与调用方式

提供 **7 个核心基础模型（基础函数）** 以及与 **5 种比例（16:9、9:16、1:1、4:3、3:4）、3 种分辨率（1K、2K、4K）、视频时长（4s、6s、8s、10s）笛卡尔积排列组合** 的预置模型，方便客户端在下拉菜单中直接选择：

### 1. 基础模型（支持参数自适应 / 默认横屏）
调用基础模型时，可通过客户端请求参数（如 `aspectRatio: "1:1"`、`imageSize: "2k"`、OpenAI `size: "1024x1024"`）灵活控制输出，未指定时默认使用 16:9 横屏：
- **图片**：
  - `gflow-nano-banana-pro`（Nano Banana Pro，对应 GEM_PIX_2）
  - `gflow-nano-banana-2-lite`（Nano Banana 2 Lite，对应 HARBOR_SEAL）
  - `gflow-nano-banana-2.1`（Nano Banana 2.1，对应 BELUGA）
- **视频**：
  - `gflow-omni-1.1-flash`（Omni 1.1 Flash，支持文生视频与多参考图）
  - `gflow-veo-3.1-lite`（Veo 3.1 - Lite）
  - `gflow-veo-3.1-fast`（Veo 3.1 - Fast）
  - `gflow-veo-3.1-quality`（Veo 3.1 - Quality）

### 2. 笛卡尔积预置模型（客户端下拉菜单直接选择）
对于无法在客户端界面输入高级参数的工具（如 Chatbox、NextChat 等），可直接在下拉模型列表中选择具体比例、分辨率或时长的模型标识：
- **图片（3 基础模型 × 5 比例 × 3 分辨率 = 45 变体）**：
  - 格式：`gflow-{模型}-{比例}{画质}`
  - 示例：
    - `gflow-nano-banana-2.1-square`（1:1 方图）
    - `gflow-nano-banana-2.1-square-2k`（1:1 方图 2K 放大）
    - `gflow-nano-banana-2.1-square-4k`（1:1 方图 4K 放大）
    - `gflow-nano-banana-2.1-landscape`（16:9 横屏）
    - `gflow-nano-banana-2.1-portrait`（9:16 竖屏）
    - `gflow-nano-banana-2.1-four-three`（4:3 横屏）
    - `gflow-nano-banana-2.1-three-four`（3:4 竖屏）
    - Nano Banana Pro、Nano Banana 2 Lite 命名规则完全一致。
- **视频（Veo 系列 3 档 × 3 时长 × 2 比例 + Omni 4 时长 × 2 比例 = 26 变体）**：
  - 格式：`gflow-{模型}-{时长}s-{比例}`
  - 示例：
    - `gflow-veo-3.1-fast-4s-landscape`（4秒 16:9 横屏）
    - `gflow-veo-3.1-fast-4s-portrait`（4秒 9:16 竖屏）
    - `gflow-veo-3.1-fast-8s-landscape`（8秒 16:9 横屏）
    - `gflow-omni-1.1-flash-10s-portrait`（10秒 9:16 竖屏）

后台同时兼容 `gflow-gemini-3.1-flash-image-square` 等历史调用名称及数字比例（如 `-16-9`、`-1-1`）。

## 也可以手动粘贴

GFlow → 添加账号 → “方式二：手动粘贴”。复制完整 Cookie 或 Cookie JSON，也接受 Session Token；新版 Flow 若没有旧 Token 字段，请优先用扩展。展开输入框下方的帮助可查看 F12 获取步骤。

## 首次安装设置

从插件商店安装后，打开 GFlow 即可使用。发行包将 Python 运行时、后台代码和依赖内嵌在插件动态库中，无需单独安装 Python。

管理页面复用同源管理中心的登录；无法读取宿主登录时，可展开连接设置临时输入管理密钥，密钥只保存在页面内存中。旧版 management_key 和 python_path 插件配置不再使用。

数据库、媒体缓存、日志和版本化后台默认保存在已安装动态库旁的 gflow-data。迁移旧账号时先备份原目录，再通过 data_dir 指向已有数据。不会自动读取其他安装的账号。

“复制扩展配置”包含管理凭据，仅粘贴到本机 GFlow 登录助手。扩展使用 chrome.storage.local 保存，不通过 Chrome 同步；清除配置可移除保存的数据。不要公开 Cookie 或扩展连接配置。

## 免费和收费范围

GFlow 与浏览器扩展本身免费。Google Flow 订阅和生成积分、付费打码平台、代理费用另计。本地浏览器打码免平台服务费，但需可用的浏览器环境。

添加 / 同步账号会验证登录态、查询额度，并可能创建项目；不会自动生成图片或视频。同步不会启用已停用的账号。

## 验证范围

已用虚构数据验证扩展 Cookie 范围、同步鉴权、账号新增与更新、重复任务合并及页面连接。真实浏览器扩展安装和真实 Google 账号同步尚未验证；真实图片 / 视频生成尚未验证。

## 来源

GFlow 内嵌的模型适配代码参考 [TheSmallHanCat/flow2api](https://github.com/TheSmallHanCat/flow2api)，保留其 MIT 声明。GFlow 登录助手独立实现，未复制未声明许可证的第三方浏览器扩展源码。


## Flow2API 源码版本

GFlow 0.1.6 直接采用 [TheSmallHanCat/flow2api](https://github.com/TheSmallHanCat/flow2api) 提交 60e673b05fe2630189f49e6dd3b275c2c8599158 的请求、RPC、图片/视频调用与模型解析。python/flow2api/upstream.json 记录 27 个原版模块和对应哈希；保留上游 MIT 许可证。GFlow 的模型别名、参数选择和宿主生命周期位于插件适配层，账号管理及浏览器生命周期的既有集成差异单独列入清单。

云端回归测试不访问真实 Google 生成接口；源码一致、连接成功、余额可查分别对应不同验证范围，均不保证生成请求会被 Google 接受。
