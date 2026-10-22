# Changelog

## [1.5.1] - 2026-10-22

### Fixed

- 核验默认严格匹配；显式允许 QQ 已发送 HTML 在受支持平坦 CSS 选择器前增加一层 `.qmbox `，或 Gmail 将 PDF/XML MIME 显示为 application/octet-stream。正文其他字节、附件数量、名称、大小、完整字节及提供的摘要仍必须一致。
- 回执保留预期与实际正文、前后 SHA-256、规则及 MIME 差异；结构化失败码不会覆盖既有核验结果。新增用户候选选择记录，不伪造 received_at。
- 初次硬链接发布中断后，在稳定锁内验证同 inode、当前用户、600 权限及身份/内容指纹；仅完成可证明安全的发布，保留原状态。不完整或不明临时文件继续阻断，不删除回执或重发。

### Validation boundary

- 纳入用户于 2026-10-22 提供的实际脱敏 HTML 对；附件 MIME 变化来自 Ela 的验收反馈，附件字节回归使用合成值，无独立 Gmail 原始抓包样本。
- 离线测试覆盖内容篡改、兼容开关、失败证据与 SIGKILL 后重启；测试数量以发布报告及 CI 为准。无真实凭据、收发或云端复验；发布后用原消息、原 operation_id 和既有回执补录核验，不为修复状态发送新邮件。

## [1.5.0] - 2026-10-21

### Changed

- 发送/回复/转发 CLI 必须持久复用 operation_id；同 ID 返回原回执，不同内容拒绝，跨进程锁与原子 JSON 更新防止重复和回执截断。旧 Python 调用按内容稳定去重，显式 ID 为推荐方式。
- queued/消息 ID 仅记 accepted，独立区分 sent_verified/recipient_verified；支持用宿主独立观察的正文/附件证据匹配 SendMessage，未知结果仅对账不重发，旧 completed 不推断核验。
- onboard next 保留 profile；增加无续期/无秘密的 credential-status。手动游标强制固定日期，并输出 query_window 与候选语义。
- 上传/下载统一大小预检；固化 v1.4.2 已观察结构的合成附件 fixture 及来源，其他接口无真实脱敏样本，不声称在线契约已验证。README 移除滞后测试数量，统一可选服务端摘要和本地摘要说明。

### Migration and limits

- 调用方需新增 --operation-id 并识别 accepted/核验状态；不要混跑旧/新写入进程。去重依赖共享且保留的状态目录，不是服务端 exactly-once，不支持丢失状态后自动补发。
- 核验证据来自宿主实际独立读取，脚本只做内容匹配；原生 Reply/Forward 最终内容未知时不升级。无真实 QQ 收发、刷新或云端验收。

## [1.4.2] - 2026-10-21

### Fixed

- 仅为 ListAttachments 兼容官方 MCP text 内 JSON 数组，严格验证唯一附件 ID、整数大小和可选字段后规范化为 attachments 对象；保留已有对象形状和其他工具的对象检查，错误或未知形状不当作空列表。
- 兼容 DownloadAttachment 只返回 Base64、filename、content_type 的实际响应；下载前用 GetMessage 精确核对 message_id、attachment_id 与元数据 size，再校验解码长度及所有已提供的摘要。
- 缺少服务端摘要时计算本地 SHA-1，回执明确摘要来源及校验级别，不伪称服务端摘要核验；严格 Base64、1 MiB、600 文件、原子不覆盖及 fsync 失败停止继续保留。

### Validation boundary

- 全部 210 项离线回归通过（192 项原测试 + 18 项附件兼容测试），并扩充 modern/legacy 独立 CLI 首次初始化、列表和下载路径。新增真实响应形状的合成字节回归，包含摘要缺失/冲突、ID/大小绑定、边界、路径、写盘失败及发送附件字段验证；无真实邮件或凭据读取、刷新、收发。
- 官方公开工具目录未提供附件 outputSchema；有凭据的发布版验收由云端另行执行。仅 created_at 而无实际收件时间语义依据时继续停止选择最新邮件。

## [1.4.1] - 2026-10-21

### Integration

- 基于 4faac83 保留 MCP 2026-07-28 无状态生命周期、auto 发现、schema/header 校验和 jsonschema/referencing 依赖。
- CI 安装 requirements.txt；独立 Agent 命令行回归同时覆盖默认 modern 与显式 legacy 路径。

### Fixed

- 修复网络安全测试对 Python 3.11 TLS 延迟初始化的错误假设；通过真实 HTTPSConnection 构造器（不联网）验证宿主 CA、证书及主机名校验，保留重定向与代理断言。

- 区分 40001 删除确认令牌过期与 OAuth 401/403，避免把仍有效的授权误判为失效。
- 删除确认挑战续期前持久化 preparing，丢响应/中断落 unknown，禁止复用旧 pending；写入意图同步目录后才提交。
- 拒绝误传为毫秒的超范围 expires_at，避免跳过应有刷新；不支持的 Python/原生 Windows 提前给出可执行错误提示。

### Added

- 其他 Agent 无 Codex 的 direct_http 接入指南，明确凭据取得前提、安装发现及标准输入/输出契约；发票转发降为按需案例。
- attachments/download 命令及完整性/大小校验、600 文件和原子不覆盖保存；写入 JSON 可通过 stdin 传入，request-status 离线查询单次回执。
- 加入 13 项通用性合成回归，与远端 179 项合并为 192 项。配置 Ubuntu/macOS 离线 CI，不声称已运行。

### Validation boundary

- 本轮仅离线合成凭据/模拟服务测试；没有真实 QQ 收发、凭据读取或刷新。其他宿主/云端真实验收仍须分别执行；原生 Windows 与独立 OAuth 注册/扫码未提供。

## [1.4.0] - 2026-10-21

### Added

- 正式实现2026-07-28无initialize生命周期；direct_http默认auto通过server/discover选共同版本，优先modern，显式http_protocol可固定modern或legacy；Codex后端保留，不在写调用失败后换协议或重放。
- 每个modern请求携带完整_meta与MCP-Protocol-Version/Mcp-Method，tools/call带Mcp-Name；严格ID/resultType/目录与分页校验，支持空字符串游标，拒绝会话头、批响应及未声明的服务端交互。
- modern采用jsonschema4.25.1校验目录/参数/结构化输出，禁止外部schema抓取；实现properties-only参数头映射、安全整数、ASCII/base64编码和大小限制，全部重计算仍受worker总超时约束。Codex及显式legacy仍无第三方依赖。
- 复用原凭据、state_dir、read_send禁删、GetMe账号权限门槛、完整正文附件与持久回执。401、输入补充请求、版本拒绝及未知发送结果停止，不触发刷新、自动重试或后台回退。

### Validation

- 全部179项假token离线回归通过（原159项+新增20项）；正常合成发送仅检验结构、来源正文和全部附件，不发送真实邮件。无本机凭据读取/续期/导出，也无真实收发。
- 父任务已在云端用有效access-only诊断通过modern discovery、tools/list和GetMe；这是协议证据，不等于本发布版功能验收。本发布版真实HTTP验收由父任务继续；Codex云端执行环境阻断仍单独记录。

## [1.3.1] - 2026-10-21

### Fixed

- QQ 官方公开 server/discover 当次声明支持 2025-03-26、2026-07-28；initialize 优先请求本客户端已实现的 2025-03-26，initialize 版本头与请求体一致，供双协议路由；仍校验协议和能力，拒绝空 result/error 外壳与未实现的2026生命周期，不自动重试。
- 补齐2025-03-26允许的 JSON/SSE 入站批响应，限制非空及1000条，拒绝重复响应、嵌套批与错误id；出站邮件仍单条请求，保留未知结果不重发及持久脱敏回执。
- 保留 Codex 后端，区分宿主原生工具、CLI 和脚本新 app-server；记录 Ela 最小 Codex 任务的只读文件系统实测阻断，不修改平台限制或本机配置。

### Validation

- 159项合成离线回归通过（原154项+新增5项）；本机真实无凭据 server/discover 通过，仅证明协议声明。认证 initialize、GetMe、续期及收发未在本机测试，目标云端账号验收由父任务继续；不将合成测试记为QQ账号实测。

## [1.3.0] - 2026-10-21

### Added

- 显式 direct_http 后端直接连接固定 QQ 官方 MCP，无需嵌套 Codex；默认及旧配置保持 codex，失败不自动切换。实现 initialize/initialized、协商协议与 session 头、完整工具分页、JSON/增量 SSE 和有界 Python worker。
- 复用完整凭据刷新及状态保障、GetMe 账号/权限门槛、read_send 删除拦截及原有发送/附件/分页流程；遵循宿主代理与 CA，验证 TLS，禁止重定向及自动重放。
- 请求前后持久化不含秘密的 transport 回执，记录固定错误码，不依赖进程输出；同客户端调用串行，认证失败阻止后续排队调用。

### Validation

- 原有 126 项与新增 28 项离线测试全部通过，共 154 项；包含协议、JSON/SSE、会话、分页、并发认证失败、未知发送、脱敏和配置兼容。未读取真实凭据、真实续期、云端 QQ 握手、收发或 Gmail 验收。

## [1.2.3] - 2026-10-21

### Fixed

- 新增显式独立 credential_state_dir，默认仍严格拒绝祖先 .git；仅在私有绝对状态根内，经空标记结构检查及只读 Git 非仓库核验后兼容沙箱空占位。
- 配置与 FileStore 读写/加锁共用位置策略；拒绝技能目录、实际仓库/worktree/bare、非空或未知标记、链接、越界、不安全权限及 Git 检查异常，不提供跳过保护或 /tmp 回退。
- 保留锁、CAS、fsync 和 pending，说明状态与代码分离可避免升级覆盖，但未加密工作区文件可能进入宿主快照，重建不保证保留。

### Validation

- 原有 111 项及新增 15 项离线测试全部通过，共 126 项；覆盖空占位、真实 Git/worktree/bare、异常与权限、位置变化、代码升级分离、CLI 兼容及持久化故障。无真实凭据、续期或收发测试。

## [1.2.2] - 2026-10-21

### Fixed

- 新增默认关闭的 allow_extra_delete_scope / --allow-extra-delete-scope，仅 read_send 可显式接受现有凭据额外的 mail:delete；--no-allow-extra-delete-scope 恢复默认严格核验。
- mode 及请求 scopes 保持 read_send/read+send，DeleteMessage 暴露、客户端构造和执行全部拦截；未知 scope、账号不符与必需权限缺失仍拒绝。
- 保留原始凭据 scope 和 GetMe scopes，明确接受广权限凭据不代表令牌降权；status/doctor 显示兼容选项，保留来源、刷新、仓库外存储及未知结果不重发保障。

### Validation

- 原有 102 项及新增 9 项离线回归全部通过，总计 111 项；覆盖默认拒绝、显式接受、未知 scope、删除拦截、CLI 开关与配置兼容、原 scope 保真及假 token 刷新后验证。未读取本机真实凭据，未执行真实续期或收发。

## [1.2.1] - 2026-10-20

### Fixed

- 刷新遵循宿主既定代理、no_proxy 和默认 CA/TLS 信任配置，移除强制直连；仍固定 QQ 官方端点、验证证书与主机名、拒绝携带凭据的重定向。
- 区分宿主 CAS 超时确认丢失与明确存储错误；文件或目录 fsync/磁盘失败不得凭读回新值继续。最终文件提交使用非秘密持久 `.pending` 标记，阻止 rename 后同步失败或中断被后续进程误判为成功。
- 保持仓库外凭据存储检查，不增加 /tmp 回退；更新网络策略与持久化恢复说明。

### Validation

- 保留原有 91 项并新增 11 项离线测试，总计 102 项；覆盖代理/无代理、CA/TLS、恶意重定向、异常脱敏、文件及目录 fsync 故障、宿主 ACK 丢失与显式拒绝。无真实凭据、续期或收发测试。

## [1.2.0] - 2026-10-20

### Added

- 独立凭据来源与刷新策略，完整 bundle 的宿主环境变量注入、宿主原子 CAS 适配器及显式私有文件适配器；旧配置兼容。环境变量不等于持久存储，私有文件未加密、生命周期不保证。
- 官方固定端点单次刷新、原签发客户端认证、锁内重读、pending 屏障及完整轮换原子保存；响应未返回 refresh token 时按 OAuth 协议保留旧值。
- 响应丢失、invalid_grant、轮换中断和保存未知时停止，防止并发重复刷新和旧值覆盖；refresh token/client secret 不进入 MCP 子进程。
- 更新 onboard、doctor、凭据恢复与云端验收说明；刷新后先 GetMe 核对账号和权限，保留 read_send、分页、附件校验及未知发送不重发保障。

### Validation boundary

- 91 项假 token 离线测试（原有 58 项 + 新增 33 项）；未读取真实凭据，未做真实刷新或收发。真实云端保存、刷新及送达验收留待用户确认后执行。

## [1.1.1] - 2026-10-20

### Fixed

- GLIC 复核修复 RUST_LOG 认证变量与子进程日志设置冲突；初始化及加载已有配置时均提前拒绝，避免令牌被覆盖。
- 新增该冲突的离线回归；总计 58 项（原有 57 项保留），真实云端验收仍未执行。

## [1.1.0] - 2026-10-20

### Added

- oauth_keyring / env_token 双认证；旧 profile 默认 OAuth，环境变量模式跳过登录和钥匙串要求，profile 只保存变量名。
- read_send 权限模式，按实际能力允许发送并禁止删除，仍核对 GetMe 实际账号与范围。
- 固定时间范围的完整分页、收件时间排序及云端发票改主题转发验收协议。
- 运行时令牌隔离、输出/异常/回执脱敏，401/撤销/过期后停止，不刷新或重发。
- 新增 28 项离线回归，原有 29 项保持通过；总计 57 项，全程使用假令牌及模拟服务。

### Validation boundary

- 真实 token 尚未注入 Ela 云端；本版本交付代码与待执行验收包，云端 GetMe、QQ 发送和 Gmail 收件验证未执行。

## [1.0.1] - 2026-10-20

### Added

- 首次加入 Better Office Work Flow：真实 Codex + 腾讯官方 MCP，支持可配置账号、多 profile、OAuth onboard、查询/搜索/附件、发送/回复/转发及确认后移至垃圾箱。
- 批量删除进度、部分完成回执查询及确认令牌续期。

### Fixed

- 拒绝缺少正向成功字段的写入响应，prepare 前持久化记录，结果未知不自动重试。
- 删除批次在网络调用前预检日期和 ID；阻止继承同名其他 MCP 的认证配置。
- 再初始化保留迁移服务名，明确损坏 profile 的恢复提示，阻止私有数据目录放入技能包。

### Validation

- 29 项离线回归通过；UGLIC 已确认问题修复，skill-release-audit 六模块 PASS。
- 本机真实身份及一封列表查询通过；dot 对话、其他实体电脑和 Linux/WSL 仍需各环境验收。
