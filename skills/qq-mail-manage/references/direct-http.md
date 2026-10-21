# 直接连接 QQ 官方 HTTP MCP

`backend=codex` 保持默认且兼容旧 profile。显式 `direct_http` 直接连接固定 `https://api.mail.qq.com/mcp`，不启动 Codex，不读取或修改全局配置、沙箱或 daemon。HTTP 内部协议由 `http_protocol` 选择：默认 auto，支持2026-07-28 modern和2025-03-26/2025-06-18/2025-11-25 legacy；失败不自动切换后端。

从未配置的新电脑或其他 Agent 接入时，优先按 [通用接入指南](agent-integration.md) 的最小示例执行；该示例不默认启用广权限兼容选项。

## 配置、依赖与调用

Python3.11+；modern/auto采用 `jsonschema==4.25.1`，请在宿主批准的Python/venv内安装（不修改受保护环境）。Codex和显式legacy仍只需标准库。doctor只检查配置、依赖存在性和历史信息，不联网、不读取凭据内容、不刷新，不能证明账号有效：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --auth-mode env_token --backend direct_http --http-protocol auto \
  --allow-extra-delete-scope --refresh-policy host --configure-only
python3 scripts/onboard.py --profile cloud doctor
```

已有profile省略来源及state_dir会保留原值；本示例显式host刷新策略，用于仅验正常功能，访问令牌临近到期就停止，不执行续期。默认env+host不等于持久存储。凭据和独立状态目录仍按 [凭据与刷新](credentials.md) 显式配置；文件未加密，工作区快照可能包含它，重建不保证保留，不复制Mac凭据。

仅在用户明确复用含额外mail:delete的凭据时启用兼容选项。它不使token降权、不改原scope；read_send的DeleteMessage构造、暴露、执行全部禁止，未知scope、账号不符或缺必需权限仍拒绝。凭据来源不变；env_token跳过浏览器和钥匙串，不支持自动从其他客户端导出授权。

真实验证须另在获授权的目标环境进行：

```bash
python3 scripts/onboard.py --profile cloud verify
python3 scripts/qq_mail.py --profile cloud list --limit 1
```

GetMe验证账号与权限后才允许邮件操作。SendMessage改主题、完整原正文及来源、全部附件的大小/SHA-1、全分页完整性、实际收件时间选择均复用既有路径，见 [操作参考](operations.md) 及 [云端验收](cloud-acceptance.md)。不会为了验证自动发送邮件。

## modern 生命周期与协议选择

实现依据官方 [版本及兼容](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)、[发现](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)、[Streamable HTTP及请求头](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)、[工具/schema参数头](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、[分页](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/pagination)。

- auto首先以2026-07-28发送一次server/discover，严格校验匹配的JSON-RPC id、resultType=complete、supportedVersions及tools capability；在实现版本交集中优先modern，再选已实现legacy。未知/重复/异常声明或发现失败停止，不根据空响应猜版本重试。
- `--http-protocol 2026-07-28` 同样发现并要求服务声明该版本。modern没有initialize/initialized或Mcp-Session-Id；随后直接tools/list全分页、GetMe，再按用户操作tools/call。
- 每个modern请求的params._meta都有io.modelcontextprotocol/protocolVersion、clientInfo及clientCapabilities（当前为空）；MCP-Protocol-Version与_meta一致，Mcp-Method与method一致，tools/call再带Mcp-Name。不依赖前次连接状态，不声明sampling/elicitation等未实现能力。
- 完整结果必须resultType=complete。input_required、任务/延期结果、原始服务端JSON-RPC请求及会话头均停止；不提交inputResponses，不重复工具调用。即使服务用400/-32022要求另一版本，失败操作也不自动重试，写入先核对外部结果。
- tools/list最多100页、总计1000个唯一工具，重复名称（包括被排除的无效定义）、缺必需工具或异常游标均失败。modern空字符串游标有效，原样传递；缺nextCursor或null表示结束，重复游标停止。只有本地允许工具可用，不执行目录中的说明、注解或_hints。

## Schema和参数头

modern在有界worker内使用jsonschema检验目录schema、调用参数及声明outputSchema时的非错误structuredContent。缺依赖时在读取凭据或网络前停止。支持库内已知dialect（默认2020-12），未知dialect、外部$ref/$dynamicRef或无效schema会排除该工具；不联网抓取schema，必需工具被排除则整次连接失败。schema最大深度32、节点10000；检查和调用仍受worker总时限控制。

x-mcp-header只允许properties链静态可达的string/integer/boolean参数；拒绝items、组合关键字、$ref链等不可达注解、无效或重复头名、number及超出安全范围的整数。运行时沿精确路径取值，缺失/null不发头；输出Mcp-Param-NAME。非ASCII、控制字符、边缘空白或base64哨兵形式的字符串用官方base64格式编码；最大64个映射头、总请求元数据头64KiB。工具名用相同编码规则生成Mcp-Name。头值只发官方服务和宿主既定代理，不进入回执；错误只记录固定原因。

## legacy、时限与网络边界

明确需要旧生命周期时，用 `--http-protocol 2025-03-26`（或另两个已实现legacy版本）跳过modern发现，按 [旧版生命周期](https://modelcontextprotocol.io/specification/2025-03-26/basic/lifecycle) initialize、核验协议/工具能力、initialized后使用。显式固定版本不接受服务改为其他版本；auto发现后选择legacy时，只接受已声明且已实现的协商版本。初始化头和body提议一致；session只在内存中保存并加入后续请求。404停止当前连接，不自动重新initialize并重放操作。2025-03-26允许非空、最多1000条JSON/SSE批响应；其他版本拒绝批，所有出站请求保持单条POST。legacy server ping有界应答，modern不处理服务端请求。

JSON和增量UTF-8 SSE均支持，含CR/LF/CRLF、多行data、注释及跨块字符；仅完整事件可成为响应。请求/响应最大8MiB；worker stdin含请求和schema时受同一有界读取约束。单次I/O20秒、worker总时限最多60秒、连接发现及目录共用120秒预算（凭据来源另有既定边界）。校验/保活不能无限延长等待，超时终止worker。不实现旧HTTP+SSE端点、GET长监听、断线续传/Last-Event-ID、MRTR或任务扩展；要求这些能力则明确停止，不假装完成。

固定官方HTTPS，验证证书及主机名，保留宿主代理/no_proxy/默认CA；禁止携带凭据的重定向，不调整网络安全设置。worker只经stdin接收本次access token；legacy如需还接收session，argv和环境不传refresh token/client secret。401/403及工具认证错误停止，同客户端排队调用受共享锁及认证状态保护，不响应式刷新。

## 持久回执与验证事实

请求前在 `$QQ_MAIL_HOME/state/PROFILE/transport/RECEIPT_ID.json` 原子落盘submitting，完成后写completed/failed/unknown；配置、schema、账号等错误也记录固定phase。无参数、schema内容、邮件内容、原始响应/异常、凭据或session。第一次回执失败不发网络；后续fsync/存储失败停止，不凭读回可见值声称持久成功。进程输出丢失时直接查回执；submitting/unknown先查外部状态，不自动重发。transport completed仅证明RPC完成；queued不代表送达，仍核对QQ sent及收件方。

2026-10-21父任务在云端用新有效access-only按modern discovery、tools/list、GetMe诊断成功，旧initialize仍空壳。该证据支持本版选择modern，但不是本发布版功能验收。本机仅合成测试，不读取、续期或导出真实凭据、不收发邮件；发布版真实HTTP验收由父任务继续，当前不验续期。Codex脚本后端保留，Ela最小exec只读文件系统阻断见云端验收；本地CLI/help通过不代表云端可执行或QQ已认证。
