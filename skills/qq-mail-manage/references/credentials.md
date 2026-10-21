# 凭据来源与单次刷新

## 默认先用宿主注入

`auth_mode=env_token` 描述 MCP 的 bearer 认证；`credential_source` 描述从哪里读取；`refresh_policy` 独立描述谁负责续期。profile 只保存非秘密引用和策略，不保存 token。旧版缺这些字段时等同 `env` + `host`；oauth_keyring 保持 Codex 自己管理，不读取/迁移其凭据。

| 来源 | 读取与保存 | 刷新策略 |
|---|---|---|
| env（默认） | 宿主安全注入环境变量；技能不保存秘密 | host：宿主续期、原子保存并重新注入 |
| host_command（推荐自动刷新） | 宿主可信可执行适配器，持久原子 CAS | host 或显式 auto |
| private_file（显式启用） | 当前用户私有目录中的未加密 JSON | host 或显式 auto |

环境变量不等于持久存储。子进程不能修改父宿主的环境，轮换后的 refresh token 不能仅写到 `os.environ`；env 来源不会直接消费 refresh token。自动刷新必须有可持久化 pending 和完整轮换结果的存储。默认仍可用宿主自己刷新后注入的完整 bundle，不强制使用文件。

| 字段 | 默认变量名 | 含义 |
|---|---|---|
| access_token | QQ_MAIL_ACCESS_TOKEN | 官方 MCP bearer；旧版唯一必填项 |
| refresh_token | QQ_MAIL_REFRESH_TOKEN | 原授权的续期凭据；不传给 MCP |
| client_id | QQ_MAIL_CLIENT_ID | 原签发客户端的注册 ID；不猜测 |
| token_type | QQ_MAIL_TOKEN_TYPE | Bearer |
| scope | QQ_MAIL_SCOPE | 空格分隔的已授予范围；仍以 GetMe 核验为准 |
| expires_at | QQ_MAIL_EXPIRES_AT | 正数 UTC Unix 秒；不是 expires_in、毫秒或 ISO 字符串 |
| client_secret | QQ_MAIL_CLIENT_SECRET | 仅原机密客户端需要；不传给 MCP |

`--token-env-var NAME` 保留 access token 自定义变量兼容；其他字段用 `--credential-env refresh_token=YOUR_REFRESH_VAR` 等重复参数，只能传变量名。所有字段变量必须互不重复，不能选 RUST_LOG/PATH/HOME 等运行变量。版本/帮助/登录及宿主适配器子进程剥离登记的 QQ 凭据变量，MCP 子进程仅重新加入所选 access token；日志和回执脱敏 access/refresh/client secret，保留 scope/type 等公开元数据供核验。

## 显式复用带额外删除 scope 的已有凭据

默认 `allow_extra_delete_scope=false`，包括所有旧 profile。仅在用户明确要求复用既有广权限 token 时，可为 `mode=read_send` 启用：

```bash
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --allow-extra-delete-scope --configure-only
python3 scripts/onboard.py --profile cloud doctor
```

该选项只影响 GetMe 凭据范围核验：除 read/send 和原有 alias:read 外，额外允许 mail:delete；未知 scopes、必需权限缺失和账号不符仍拒绝。请求 scopes 仍为 mail:read/mail:send，read_send 模式下 DeleteMessage 的工具暴露、客户端构造和执行均拦截，不切换 manage。read/manage 不允许启用此兼容选项。

**这是接受广权限凭据，不是令牌降权。** 原始 `scope` 字段、刷新返回的 scope 以及 GetMe 原始 `scopes` 均如实保留；status 另列 `requested_scopes`、`accepted_extra_scopes` 和选项值，不能把前者当作 token 的实际权限。既有 token 在技能以外仍拥有删除权限。省略选项保留原配置；`--no-allow-extra-delete-scope` 显式关闭后恢复默认严格拒绝。

此设置不读取、导出或迁移凭据，`--configure-only` 不触发续期或邮件操作。来源/刷新配置省略时保留原值；需要真实 verify 时仍先完成目标宿主的凭据及运行入口准备。启动器只读报错不改变仓库外私有可写存储的要求，也不允许改受保护目录或回退 /tmp。

## 自动刷新配置

宿主须先安装可信适配器并提供官方完整凭据，示例路径需替换：

```bash
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --auth-mode env_token --credential-source host_command \
  --credential-command /absolute/path/to/host-credential-adapter \
  --refresh-policy auto --client-auth-method none --configure-only
python3 scripts/onboard.py --profile cloud doctor
# 取得用户对真实凭据保存/验证的确认后，在目标环境执行：
python3 scripts/onboard.py --profile cloud verify
```

`none` 仅适用于原注册为 public client 的客户端。原机密客户端必须显式选择 `client_secret_basic` 或 `client_secret_post`，并由来源提供原 client_secret；不得从失败反推、自动尝试其他方法或改 client_id。QQ 公开元数据没有声明所有客户端共用的认证方式，必须依据原授权/注册记录确定。

`refresh_policy=auto` 默认在 expires_at 前 120 秒刷新；`--refresh-skew 0..3600` 可调。不允许 env + auto 或缺少显式 client_auth_method。doctor 支持上述同名参数，可核对路径元数据/Git 分类、非秘密配置、变量存在性和 Codex 能力，不读取凭据内容、不刷新；verify 才会走凭据与 GetMe。

宿主暂不支持适配器时，可显式启用文件：

```bash
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --auth-mode env_token --credential-source private_file \
  --credential-file /absolute/private-directory/qq-credentials.json \
  --refresh-policy auto --client-auth-method none --configure-only
```

该文件**未加密，生命周期不保证**。宿主负责在技能和任何 Git 仓库外安全创建完整记录，不通过聊天或 shell 参数传真实值。直接父目录必须为当前用户所有、权限严格 700；文件为当前用户所有、严格 600、单硬链接；拒绝符号链接（包括路径祖先）、不自动 chmod 修复不安全文件。不支持自动从环境变量落盘，不探测 Mac 钥匙串或其他客户端凭据。`credential-file` 路径旁创建同为 600 的 `.lock`；最终提交期间另有不含秘密、权限 600 的 `.pending` 持久标记，出现时阻止读取凭据继续操作。其他写入者也必须遵守同一锁、标记与 CAS。不要配置到会被清理的 /tmp 或临时容器层。

### 显式独立状态目录与空 Git 占位

默认未设置 `credential_state_dir` 时，仍拒绝所有祖先 `.git` 标记，包括空目录。部分沙箱把空的只读 `.git` 挂载作为占位，Git 本身并不认为它是仓库。此时可由用户明确选择**独立、绝对、当前用户所有**的状态根，再配置 `--credential-state-dir`；该路径不得在技能代码内，也不得包含技能代码目录。凭据文件必须严格位于该根内，根到文件父目录每级都须为 700，已有文件须为 600、单硬链接；目录需由宿主在获授权的可写位置预先准备，脚本不自动创建凭据目录、不修复权限。

示例路径须替换为用户批准的位置；只准备目录和非秘密配置，不在 shell 中传入真实 token：

```bash
install -d -m 700 /absolute/private-state /absolute/private-state/credentials /absolute/private-state/runtime
QQ_MAIL_HOME=/absolute/private-state/runtime python3 scripts/onboard.py --profile cloud init \
  --account YOUR@qq.com --mode read_send --auth-mode env_token \
  --credential-source private_file \
  --credential-state-dir /absolute/private-state \
  --credential-file /absolute/private-state/credentials/bundle.json \
  --configure-only
```

QQ_MAIL_HOME 是非秘密 profile/邮件回执位置，credential_state_dir 是凭据文件的边界，两者都与技能代码分开；后续命令继续使用同一个 QQ_MAIL_HOME。已配置的原客户端认证及刷新策略在来源不变时保留；新配置默认 host，由宿主续期，自动刷新仍需明确原客户端方法及 auto，不能猜测。

这不是跳过仓库保护的开关。仅接受真实目录形式、可读取且确认为空的 `.git`，并扫描**所有祖先**，拒绝实际仓库、worktree 的 `.git` 文件、bare/不完整 Git 结构、非空或链接标记。随后使用 Git 做隔离、只读的 rev-parse 探测，仅接受明确“不是 Git 仓库”的正常诊断；缺 Git、超时、权限或其他错误、无法分类的输出均停止，不能把任意失败当作非仓库。探测前后复查标记，配置、读取、加锁和写入应用相同策略，不能用空标记遮住上层真实仓库。不会修改沙箱设置、挂载、Git 配置或 `.git` 内容。

显式模式需要 Git。路径元数据和 Git 分类可能在 configure/doctor 时检查，但不会打开凭据内容；不存在的 bundle 可等待宿主安全导入。状态目录/文件的链接、越界与权限检查在实际操作时复核，原有锁、CAS、fsync 和 pending 屏障保持有效。

独立路径可避免技能代码升级覆盖，**不代表工作区秘密隔离或持久存储保证**：文件未加密，宿主工作区快照可能包含它，云环境重建/清理可能丢失它及 pending、操作回执。必须向用户披露并取得其对所选位置的同意；未知发送结果仍不能因重建而重发。没有自动 /tmp 回退；真实仓库或只读错误不授权修改受保护目录。新 profile 可不设置此字段继续使用默认严格模式；切换到其他来源时清除该字段。

文件与宿主记录使用相同 JSON 数据结构（仅占位示例，真实值由宿主提供）：

```json
{
  "revision": "unique-store-revision",
  "refresh_state": "ready",
  "access_token": "<host supplied>",
  "refresh_token": "<host supplied>",
  "client_id": "<original issuing client>",
  "token_type": "Bearer",
  "scope": "mail:read mail:send",
  "expires_at": 2000000000
}
```

原机密客户端另有 client_secret。revision 每次写入必须变化；不得回滚历史凭据备份。来源切换需显式 `--credential-source`，重新初始化自动清除不适用的旧来源引用和刷新策略；省略时保留原配置。不会删除原存储或其中的秘密。

## 宿主适配器协议 v1

这是可选宿主集成接口，不是额外平台服务。配置一个绝对路径可执行程序，无 shell、无隐式参数；宿主可在其受控配置中选择固定凭据记录。秘密通过标准输入/输出传递，不通过 argv。适配器不得自行触发刷新、打印日志中的凭据、访问其他邮箱，或在 CAS 内改变传入的完整记录。退出非零、非 JSON 或显式存储错误均停止，stderr 不转发。仅最终 CAS 的超时（20 秒）作为“确认丢失”候选，可通过宿主 durable load 核实；普通 OSError/磁盘失败不得走此恢复。

- stdin `{"protocol":1,"operation":"load"}` → stdout `{"record":{...}}`。
- stdin `{"protocol":1,"operation":"compare_and_swap","expected_revision":"OLD","record":{...}}` → stdout `{"saved":true}` 或 `{"saved":false}`。
- CAS 必须在**持久存储端原子**比较 revision，并整体保存新记录；`saved=true` 必须表示 durable commit 已完成。冲突返回 false，不得覆盖更新值。load 必须只返回已确认持久化的最新记录，不能返回仅当前可见、尚未 fsync/commit 成功的值；适配器须自行从安全存储认证，不能依赖本技能剥离的 QQ refresh/access/client secret 环境变量。
- 同一适配器和存储必须由单一凭据所有者管理。若同一程序服务不同记录，应提供各自固定包装程序；不要靠当前工作目录猜选账号。

本地按来源加 POSIX 文件锁并在锁内重读；宿主 CAS 额外保护不同进程/数据目录的冲突。将同一 refresh token 复制到不同记录、机器或环境后**不可独立并行续期**。环境迁移需由宿主暂停旧消费者并交接单一存储及状态；单机锁不能协调两个独立副本。多个独立授权可以各自管理，不得将复制 token 当作独立授权。

## 刷新、故障和恢复

1. 锁内重读完整记录，拒绝 pending/未知状态。未临近到期不刷新；host 策略临近到期则要求宿主更新。
2. auto 将完整记录原子改为新 revision + pending，保存成功后才发一次 POST；CAS 冲突只安全重读，不重试 POST。此屏障不能丢失或手工清除。
3. 仅向固定 `https://wx.mail.qq.com/oauth/token` 发 refresh_token grant，不请求扩大 scope、不重定向、不自动重试。网络沿用 Python/宿主既定代理（包含 https_proxy/HTTPS_PROXY、no_proxy/NO_PROXY）与默认 CA/TLS 信任配置（如 SSL_CERT_FILE/SSL_CERT_DIR）；不强制直连，不改代理、安全配置或证书验证，保留证书及主机名校验。认证方法取显式原客户端配置。
4. 成功响应必须有有效 access_token、Bearer token_type、正数 expires_in；到期时间保守取请求开始时间加 expires_in。整体保存新 access token、到期时间、新 revision、ready 状态，以及轮换 refresh token。未返回 refresh_token 时保留旧值；返回空值则失败。未返回 scope 按 OAuth 语义保留原范围。
5. 仅宿主最终 CAS 超时确认丢失时，读取宿主明确已持久提交的记录，核对与新记录完全相同，不重做刷新。文件 fsync/磁盘错误、宿主非零退出或显式错误一律停止，不能凭读回可见值判成功。文件在最终 rename 前先持久化 `.pending` 标记，最终文件及目录 fsync 成功后才移除并同步标记；失败或中断遗留标记则阻止下次使用。之后启动 MCP，先 GetMe 校验准确账号、别名及所需范围（默认 read_send 不得含 mail:delete；明确启用上述兼容选项时只接受凭据中的该额外 scope，仍不允许删除），再操作邮件。长连接中 401 不触发刷新重放。

超时、响应丢失、无效成功响应、invalid_grant、拒绝或进程中断可能留下 pending。宿主须核对官方/自身存储，若已保存新记录就恢复最新完整记录；若无法证明结果，取得新授权并原子替换完整 bundle/新 revision 后 verify。**不能简单把 pending 改 ready 后重试旧 refresh token**；丢失轮换响应可能无法恢复，应更换授权而非盲试。失败不输出请求、响应正文、异常里的凭据，不回退浏览器登录。

私有文件在保存轮换期间中断可能保留旧的 pending 或当前可见的新记录；`.pending` 标记未完成清理时，当前可见不代表持久化成功。标记存在会阻止重启后继续使用，临时文件也不代表提交完成。凭据所有者须先解决磁盘/同步故障，确保持久化完整有效的新 bundle（无法核实则换授权）并重新核对，才能显式清理标记；不得仅删除标记重试旧 refresh token。磁盘故障/容器回滚无法由代码保证恢复，状态不可靠时停止。凭据、pending、邮件未知结果回执都要由宿主持久保存；发送结果未知仍须核对外部状态，不得重发。

核实依据（2026-10-20，无凭据只读 GET）：[QQ 官方授权服务器元数据](https://api.mail.qq.com/.well-known/oauth-authorization-server) 返回 issuer `https://wx.mail.qq.com`、token_endpoint `https://wx.mail.qq.com/oauth/token`、grant_types_supported 含 refresh_token。[OAuth 2.0 §6](https://www.rfc-editor.org/rfc/rfc6749#section-6) 规定可省略轮换 refresh token，返回时须替换旧值；[§2.3.1](https://www.rfc-editor.org/rfc/rfc6749#section-2.3.1) 规定机密客户端认证。元数据核实不代表已完成真实续期；本次开发全用假 token。
