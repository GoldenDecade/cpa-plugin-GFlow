# GFlow 项目控制协议 v1（插件 0.1.12）

项目控制复用普通生成 API Key 的 `POST /v1/chat/completions`，无需管理密钥。专用模型 `gflow-project-control` 只执行控制操作，不进入图片/视频生成器。现有七种媒体模型及第三方未绑定请求继续使用原行为；客户端应从媒体选择器排除该控制模型。

请求必须 `stream: false`，包含一条 user 消息，content 为 JSON 字符串：

```json
{
  "model": "gflow-project-control",
  "stream": false,
  "messages": [{
    "role": "user",
    "content": "{\"version\":1,\"op\":\"capabilities\",\"workspaceId\":\"11111111-1111-4111-8111-111111111111\"}"
  }]
}
```

控制 JSON：

- `version: 1`、`op`、`workspaceId` 必须提供；工作区与项目标识为 UUID。
- `capabilities` 无需账号，返回 `models`、服务实例和 `projectBinding` 能力。没有账号时仍有基础 1K 目录；该响应不表示已经登录或可以成功生成。
- `projects.list` 返回该工作区登记的项目，不扫描整个 Google 账号或其他工作区。
- `projects.get` 需要本地 `projectId`，返回 `project` 及所属账号档位允许的模型参数。可附 `flowProjectId`（null 或 UUID）作诊断；UUID 必须与保存的绑定匹配，不参与路由。
- `projects.create` 另需 `projectId`、`operationId`、`name`（1–128 字符）；可选 `preferredModel` 为七种基础媒体模型之一，默认 `gflow-nano-banana-2-lite`。选择账号后立即调用 Google Flow 的创建项目 RPC，不生成媒体。

成功响应采用标准 chat completion；解析 `choices[0].message.content` 内 JSON：

```json
{
  "version": 1,
  "instanceId": "服务持久化UUID",
  "workspaceId": "客户端工作区UUID",
  "projectBinding": true,
  "capabilities": {"projectBinding": true},
  "project": {
    "id": "CutFlow本地项目UUID",
    "name": "项目名",
    "flowProjectId": "Google Flow项目UUID",
    "state": "ready",
    "accountLabel": "a***@example.invalid",
    "instanceId": "服务持久化UUID"
  },
  "models": [{
    "id": "gflow-nano-banana-2-lite",
    "kind": "image",
    "maxReferences": 3,
    "aspects": ["1:1", "16:9", "9:16", "4:3", "3:4"],
    "imageSizes": ["1K"],
    "durations": []
  }]
}
```

控制协议校验、项目查找和绑定冲突错误仍返回标准 chat completion，content JSON 为 `{version:1,projectBinding:true,error:{code,message,status_code}}`；客户端必须先检查 error，再验证成功响应实例字段。这样兼容当前宿主把 executor 异常统一为 plugin_error 的 ABI。传输中断仍以 HTTP/宿主错误处理，不能据此自动重建项目。

list 使用 `projects` 数组；create/get 使用单个 `project`。项目 state 为 `creating|ready|failed|creation_unknown`，失败可含 `error:{code,message}`，不会返回 Cookie、密钥、账号内部 ID 或原始邮箱。2K 需要 Pro，4K 需要 Ult；参数目录反映已知账号档位，真实生成仍需平台验证与额度。

项目内生成仍用原媒体模型，在标准请求顶层同时附带：

```json
{
  "gflow_workspace_id": "客户端工作区UUID",
  "gflow_project_id": "真实Google Flow项目UUID",
  "gflow_instance_id": "服务持久化UUID"
}
```

`gflow_project_id` 是 `flowProjectId`，不是本地项目 ID。三个字段必须全部存在且与服务记录匹配。项目账号停用、移除、身份变化、档位不足或验证路由不可用时失败，禁止换账号、项目池回退或创建替代项目。图片与视频、流式与非流式共享该规则，异常和取消后清理请求上下文。账号刷新返回新对象后重新验证启用开关与档位；固定请求总会执行非阻塞并发预检，这一步不额外占用上游槽位。额度是否足够仍以 Google Flow 实际响应为准，平台额度错误不会触发换账号。连续改图由客户端显式提供选中图的参考图片，项目绑定不会把其他会话历史自动作为参考。

同工作区 operationId 与项目请求内容持久化幂等；完全相同的重复请求返回原记录，参数冲突拒绝。RPC 已开始后若超时、取消或丢失回执，状态是 creation_unknown，不自动重建，避免产生重复云端项目。服务重启把未完成 creating 转为 creation_unknown。已确认的失败记录也不会自动重试；需要用户核查后新建项目。云端重命名、删除、迁移及扫描恢复不在协议 v1 中。

SQLite 在原 flow.db 增加元数据与 CutFlow 项目表；旧 projects 记录 purpose 默认 pool，新专属项目为 cutflow，轮询客户端只能看到 pool。上游 27 个固定源码文件及 Google RPC 实现保持原哈希。

权限边界：普通 API Key 代表该 EasyCPA 实例的生成访问权限；工作区 UUID 用于数据分组，不构成额外用户认证，不能将此协议描述为多租户安全隔离。现有 /v0/management 路由仍需独立管理认证。真实宿主路由、真实账号创建及真实媒体生成应单独验收，离线测试不证明它们已验证。
