# 直接连接 QQ 官方 HTTP MCP

`backend=codex` 是兼容默认值。宿主不能启动嵌套 Codex 时，可显式选择 `direct_http`，由技能直接连接固定 `https://api.mail.qq.com/mcp`。此模式不启动 Codex、不读取全局 Codex 配置、不修改沙箱或 daemon socket；需要 Python 3.11+、网络和显式 env_token 凭据来源，无第三方 Python 包。不会在任一后端失败后自动切换。

## 配置与调用

已有 cloud profile 可只更新非秘密后端选项，保留原凭据来源、state_dir、刷新及原签发客户端认证方法：

```bash
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --auth-mode env_token --backend direct_http --allow-extra-delete-scope --configure-only
python3 scripts/onboard.py --profile cloud doctor
```

仅在用户明确复用含额外 mail:delete 的 token 时启用上述兼容选项。它只放宽该 scope 的凭据核验，不给 token 降权，不改写元数据；DeleteMessage 在 read_send 的构造、暴露、执行仍全部禁止。未知 scopes 及账号不符仍拒绝。新 profile 默认 env + host；环境变量不等于持久存储，完整凭据、私有文件及独立状态目录配置见 [凭据与刷新](credentials.md)。此模式拒绝 oauth_keyring，不从本机其他客户端导出授权。恢复原后端需用户显式 `--backend codex`。

凭据由宿主另行准备并取得真实验收授权后：

```bash
python3 scripts/onboard.py --profile cloud verify
python3 scripts/qq_mail.py --profile cloud list --limit 1
```

doctor 仅检查配置，不连接、刷新或读取凭据内容；输出 codex=null、backend=direct_http、currently_verified=false。verify 先按既有 provider 规则刷新（如需且显式启用），再通过 GetMe 验证账号及所需权限。邮件操作命令与 [操作参考](operations.md) 完全相同，包括 SendMessage 修改主题、保留来源和完整原正文、全部附件的字节数及 SHA-1 校验、分页完整性和按实际收件时间选取；不得用此后端绕过验收步骤。

## 协议及边界

实现依据 MCP 官方 [2025-03-26 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)、[2025-03-26 生命周期](https://modelcontextprotocol.io/specification/2025-03-26/basic/lifecycle)、[工具](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)、[分页](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/pagination) 和 [SSE 解析](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation)：

- 单条 JSON-RPC 2.0 POST；initialize 优先请求 QQ 已声明支持且本客户端已实现的 2025-03-26，接受服务按旧版协商选择的 2025-03-26、2025-11-25 或 2025-06-18，核对 tools capability 后发送 notifications/initialized。通知及 server ping 的响应 POST 要求空的 HTTP 202。
- initialize 的 MCP-Protocol-Version 头与请求体中的提议版本一致，供双协议时代服务器在解析请求体前路由；所有后续 POST 带协商的 MCP-Protocol-Version；initialize 若返回 MCP-Session-Id，则校验可见 ASCII 后仅在内存中保存，并加入后续请求。session 不进入回执或日志。404 停止当前连接和操作；下一次显式建立连接重新 initialize，绝不自动重放失败请求。
- Accept 同时声明 application/json 与 text/event-stream，解析 JSON 或增量 UTF-8 SSE，支持 CR/LF/CRLF、多行 data、注释和跨块字符；仅完整空行终止事件可成为响应，核对请求 id。服务 ping 单独响应，最多 8 次；不提供 sampling/elicitation，未知服务请求拒绝。
- 2025-03-26 允许 JSON 或 SSE 事件中的入站批响应；仅该版本接受非空、最多 1000 条的批。逐条核验 JSON-RPC、id、通知与 ping，重复最终响应、空/嵌套批或不匹配 id 均拒绝。后续已实现版本不接受批；所有出站邮件请求仍单条 POST。
- tools/list 完整分页后才启用本地允许的工具；最多 100 页、1000 个唯一工具，重复工具、异常/重复游标、必需工具缺失或列表变化均停止，未知工具不暴露。
- 单次网络读写超时 20 秒；每个 HTTP worker 总时限最多 60 秒，初始化及工具发现共享 120 秒预算（原凭据适配器另有既定超时），单次请求/响应最多 8 MiB。独立 Python worker 被超时机制终止，避免持续 SSE 保活造成无限等待；stdin 仅传本次 access token/session，环境和 argv 不传 refresh token/client secret。
- 这是 Streamable HTTP 的有界请求实现，不支持旧版 HTTP+SSE 端点、GET 长连接、断线续传/Last-Event-ID、自动重连或自动协商重试。服务要求这些扩展时安全停止并报告未兼容，不宣称 QQ 云端已实测。

TLS 证书/主机名验证开启，遵循宿主已有代理、no_proxy、默认 CA 配置；不关闭验证、不调整网络安全设置、不跟随重定向。HTTP 401/403、RPC/工具认证错误均停止；后续同客户端调用被阻止，不触发响应式刷新或写操作重放。同一客户端调用串行完成认证检查、提交及结果解码。

## QQ 协议契约与真实验证边界

2026-10-21，本机一次不带 Authorization、不读取凭据的官方 server/discover 返回 HTTP200 application/json，合法 result 声明 supportedVersions=[2025-03-26,2026-07-28] 及 tools capability；与目标云环境的发现结果一致。该公开探针只证明当次服务协议声明，不能证明用户账号、GetMe 或邮件操作可用。

v1.3.0 优先请求的 2025-11-25 不在这份服务声明中；目标云端 initialize 实测只返回 jsonrpc/id，既无 result 也无 error。此类空壳继续按错误处理，不当作成功，不自动重试另一版本。v1.3.1 改为优先请求已声明的 2025-03-26，并补齐该版允许的入站批响应；仍须在目标云端实际核验握手和账号。

[2026-07-28 server/discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover) 属于取消 initialize 的新生命周期。本后端没有实现该业务生命周期，不会只改版本字符串就宣称兼容；server/discover 的公开调查也不等于运行时自动发现或自动回退。若服务 initialize 选择 2026-07-28 或其他未实现版本，停止并报告。

Codex 后端保留兼容：它通过新 app-server 调用 QQ，不自动复用当前会话的原生工具。只有宿主已加载并暴露 QQ MCP 时，当前 Codex 才有原生调用条件；仅安装 skill 或 CLI 不会产生工具。原生调用也不会自动获得 Python 的 read_send、附件及持久写入回执保护，不能绕过既有受保护流程。云端 Codex 启动前置检查及失败记录见 [云端验收](cloud-acceptance.md)。

## 持久错误记录与未知结果

每个请求发出前，在 `QQ_MAIL_HOME/state/PROFILE/transport/RECEIPT_ID.json` 原子写入 submitting，完成后落盘 completed/failed/unknown；实际 QQ_MAIL_HOME 由宿主选择，文件与目录为当前用户私有。凭据、账号范围及工具响应解析错误也记录固定 phase，异常只显示固定错误码和回执 ID。记录仅含请求 ID、固定方法/工具名、时间、状态、固定原因及数字 HTTP/RPC code，无参数、邮件内容、原始响应/异常、令牌或 session。

操作者可在上述目录读取 JSON 回执，不依赖进程输出是否保留。进程被杀或最终 fsync 失败时可能只保留 submitting；这代表未知，必须核对外部状态。首次回执无法持久化则不发网络请求；后续持久化失败则停止，不能把读回可见值当作落盘成功。

transport 的 completed 仅证明 RPC 响应处理完成。邮件发送结果继续由原写入回执及 QQ sent/收件方共同核验；queued 不代表送达。tools/call 的超时、丢响应、401、中断或未知结果不重发。没有自动重试或 Codex 回退，人工重新执行命令也不能替代先查证。需要在重建后恢复凭据、pending 和全部回执；工作区快照与重建风险见凭据说明。
