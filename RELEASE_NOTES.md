# GFlow v0.1.19

修复 Google Flow 已完成生成、CutFlow 却长时间等待或无法解析结果的问题。

- 修复 CPA 宿主流队列背压：executor 先返回响应头，后台线程再持续发送阶段及最终原图。
- 修正转发格式：将 worker SSE 解为 JSON 后交给宿主，由宿主统一添加 SSE 外层及结束标记，避免重复 data: 前缀。
- 保留最终 finish_reason，校验宿主回执；插件关闭时清理流与工作线程。
- 使用标准 OpenAI 媒体响应，兼容 CutFlow 0.6.1；保留固定项目、所属账号和 2K/4K 缓存文件回传。
- 免费能力查询的流式包装复用真实控制协议与实际分发路径，无需发起媒体生成。
- v0.1.15 至 v0.1.18 为排查中的过渡版本，请使用本版。

Windows 下载 gflow_0.1.19_windows_amd64.zip，解压得到 gflow.dll。该插件安装在 EasyCLIProxyAPI 中；退出代理后替换 DLL，保留 gflow-data 目录，再重新打开代理。

运行中的旧请求不会因升级自动补回。已找回原图的 CutFlow 任务，请完整退出并重新打开 CutFlow，再进入原会话选择“只重试下载结果”。此操作不会重新生成。
