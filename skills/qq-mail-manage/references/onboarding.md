# 初始化与跨机使用

## 安装包与依赖

将整个 `qq-mail-manage` 文件夹复制到目标机器 Codex 能发现的 skills 目录，例如 `~/.agents/skills/qq-mail-manage`，或该机器已使用的 `~/.codex/skills/qq-mail-manage`。不要只复制 SKILL.md。安装后在新会话中调用 `$qq-mail-manage`；如客户端尚未发现新技能，刷新技能或重开会话。

包内仅包含技能指令、运行脚本、参数 schema 和离线测试，不应包含 profiles、pending、reviews、邮箱正文、附件或任何 OAuth 凭据。

依赖 Python 3.11+ 和真实 Codex CLI；无需安装 Python 包。安装 Codex 后先确认 `codex --version`、`codex app-server --help` 可用。oauth_keyring：macOS 需允许 Codex 使用系统钥匙串，Linux/WSL 需先有可用安全凭据库服务；不可用时停止，不自动改用明文存储。env_token：不要求钥匙串，使用宿主安全注入的官方 MCP access token。

以下命令均以技能根目录为工作目录。路径有空格时使用 shell 引号，或由执行工具显式指定 workdir。

## Onboard

```bash
python3 scripts/onboard.py doctor
python3 scripts/onboard.py --profile personal init --account YOUR@qq.com --mode read
```

init 将非秘密配置写到 `${QQ_MAIL_HOME:-${CODEX_HOME:-~/.codex}/qq-mail-manage}/profiles/personal.json`，默认 MCP 名为 qq-mail-personal。使用真实 `codex mcp login` 和配置覆盖项进行 OAuth，不修改全局 Codex config.toml；该连接供本技能子进程使用，不代表添加了云端 ChatGPT 连接或其他会话的原生 MCP 工具。

再次初始化同一 profile 时，省略 --server 会保留原服务名，便于升级权限。新 profile 若与全局已有 MCP 名冲突（不是官方邮箱地址，或带有额外传输／认证字段），会在写配置和发起 OAuth 前停止；选新的 profile/server 名即可，不改动其他服务。QQ_MAIL_HOME 不能位于本技能目录内部，以免升级或分发时混入私有数据。

用户在官方腾讯页面完成登录和权限确认。服务地址固定 `https://api.mail.qq.com/mcp`，不接受任意第三方 MCP 端点，不伪装其他客户端；网络代理与 CA 信任遵循宿主既定配置，不强制直连或关闭 TLS 验证。账号应能在授权后 `GetMe.aliases` 中唯一匹配，支持配置 QQ/Foxmail 邮箱别名；最终可用性以服务实际接受及 GetMe 为准。其他账号的真实授权尚未在本环境完成，不承诺所有账号都有同样能力。

read 仅允许 mail:read；read_send 允许 mail:read、mail:send；manage 允许 mail:read、mail:send、mail:delete。OAuth 按所选模式请求范围，env_token 核对已有 token 的实际范围，不为其降权。默认实际权限超出所选模式则中止；仅 read_send 可在用户明确要求复用现有广权限凭据时启用 `--allow-extra-delete-scope`，只额外接受 mail:delete，仍禁止删除工具及未知 scopes。服务不给所需权限也不称为完成初始化。

```bash
python3 scripts/onboard.py --profile personal verify
python3 scripts/qq_mail.py --profile personal status
python3 scripts/qq_mail.py --profile personal list --limit 1
```

verify 只读取身份和范围，不读取邮件正文；成功输出 state=verified。列表成功后再读取用户指定的测试邮件，按需测无敏感内容附件。写操作不在初始化中自动测试。

只保存配置而暂不授权：init 加 `--configure-only`，结果是 configured_not_verified，之后运行同 profile 的 `onboard.py login`（OAuth）或 `verify`（env_token）。权限失效、升级 manage 或重新扫码用 login；升级时用原账号重跑 init --mode read_send 或 manage，省略 --server 会沿用原名。不要为升级权限删除其他 profile 或复制现有令牌。

## 复用已有授权

仅适用于当前机器、当前系统用户、真实 Codex 已完成的官方授权：

```bash
python3 scripts/onboard.py init --account YOUR@qq.com --mode manage --server qq-mail --reuse-auth
```

仍运行 GetMe 验证；不读取或迁移凭据。复用失败则让用户完成官方登录。已有 profile 不允许静默换账号或 server；使用新 profile。每个 profile 需独立 MCP 名，不能让两个账号配置隐式共用一个身份。

## dot 与另一台电脑

- 同机其他 Codex：安装目录可发现、同系统用户、相同 CODEX_HOME/QQ_MAIL_HOME，即可使用该机已校验 profile。不同 CODEX_HOME 默认使用不同配置和凭据环境。
- dot：确认 dot 的任务确实落到已连接且在线的目标电脑，技能文件可发现、Python/Codex 在执行环境可用。让该任务执行 doctor、verify 和一封列表查询。不能把本地成功等同于 dot 云端原生 MCP 注册成功。
- 新电脑：复制无凭据技能包，在目标机器运行 init，用户重新扫码；再按上述验收。同一邮箱可配置在多台机器，但每机令牌刷新和撤销影响必须实测。
- 远端无桌面或凭据库：先解决该环境的官方 OAuth 和安全存储能力；不复制另一台电脑、WorkBuddy 或 Claude 的令牌绕过。

官方说明：[Codex MCP](https://developers.openai.com/codex/mcp)、[技能安装发现](https://developers.openai.com/codex/skills)、[App Server](https://developers.openai.com/codex/app-server)。本包直接调用实验性 app-server 协议，doctor 的 help 检查不代替 verify 的真实协议/身份验收。

入口退出码：0 表示命令已返回结果，仍须查看 state 是 verified、configured_not_verified 或 awaiting_user_confirmation；1 表示运行失败，2 表示命令参数有误。profile 字段损坏时会提示修复非秘密 JSON 或新建 profile，不读取其他客户端凭据。操作结果未知时保留原记录，按操作参考核对邮箱后再决定下一步。

## env_token：宿主凭据与刷新

默认 `--auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN` 兼容旧配置，不启动 `codex mcp login`、不读取钥匙串。首次运行先由宿主安全取得官方凭据并注入，不在聊天、命令行、参数 JSON、.env 或仓库中传值。refresh token 是续期凭据，不能作为 MCP access token；原签发 client_id 和客户端认证方式必须来自原始授权/注册记录，不猜测或借用其他客户端。

```bash
python3 scripts/onboard.py --profile cloud doctor --auth-mode env_token
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send --auth-mode env_token
python3 scripts/onboard.py --profile cloud verify
```

init 默认 env + host：宿主负责轮换、原子保存完整 bundle 并重新注入；本技能不在不可持久保存的环境变量上直接消费 refresh token。环境变量不等于持久存储，不保证跨进程或容器重建保留；仅更新当前进程 `os.environ` 无法保证下次启动读到新令牌。

若需要本技能自动刷新，选择明确的原子存储来源。推荐宿主 `host_command`；可显式启用未加密、生命周期不保证的 `private_file`（目录 700、文件 600、当前用户所有、包与仓库外）。沙箱空 .git 占位时可显式设置独立绝对 `--credential-state-dir`（需 Git），只对已核实空占位兼容；真实仓库、链接和不安全权限仍拒绝。目录须预先存在并为当前用户所有、700，bundle 在其内部且为 600；独立工作区状态可能被快照捕获或在重建后丢失，需用户同意，代码升级不会覆盖它。全部字段、命令、权限和恢复流程见 [凭据与刷新](credentials.md)。profile 只存来源引用、变量名与非秘密刷新策略；旧 profile 缺 auth_mode 时仍按 oauth_keyring 处理，再初始化会保留已有来源与刷新配置。

doctor 支持与 init 相同的凭据来源/刷新参数，只显示变量名、存在性、策略和历史时间；可校验路径元数据和 Git 分类，但不会读取凭据内容、调用宿主适配器或刷新。`currently_verified=false`，`store_inspected=false`；变量存在或历史 verified_at 均不能证明本次身份有效。`--configure-only` 只保存非秘密配置，之后仍须 verify。

仅真正调用 MCP 的 app-server 接收 access token。版本检查、帮助、OAuth 登录和宿主凭据适配器均移除登记的 QQ 凭据变量，包括 refresh token/client secret；refresh token 不进入 MCP。环境变量名须专用，RUST_LOG/PATH/HOME 等运行时变量被拒绝；RUST_LOG 在 MCP 子进程固定关闭。仅固定官方 MCP 端点、通过 bearer_token_env_var 引用 access token，拒绝同名 server 中冲突认证配置，不修改 Codex 配置。

单次连接在使用 token 前按到期时间刷新一次，锁内重读并持久化 pending；临近到期默认 120 秒。成功后整体原子保存新 access token、到期时间及轮换 refresh token；GetMe 精确校验账号及 read_send 权限后才可操作邮件。连接期间出现 401、撤销或超时不会触发响应式刷新或邮件重放。refresh 结果未知及 pending 恢复由凭据所有者处理，不重试旧 refresh token、不回退浏览器。

QQ_MAIL_HOME 的配置和操作回执须在包与仓库外的私有持久位置。云端重建可能同时丢失凭据、pending 屏障和邮件回执；先恢复可靠状态再运行。发送结果不明时核对 QQ 已发送和收件方，不能重建后新建请求重发。默认实际 scopes 超过 read_send（例如包含 mail:delete）也停止。用户明确复用已有广权限 token 时，可用 `init --mode read_send --allow-extra-delete-scope --configure-only` 更新非秘密 profile；省略原来源参数会保留存储配置，用 `--no-allow-extra-delete-scope` 关闭。此项仅接受额外 mail:delete，不启用删除或接受未知 scope；配置模式不会给高权限 token 降权，原始 scope 保留。

目标环境按 [云端验收](cloud-acceptance.md) 单独确认；本地测试不代替真实身份、轮换或送达验收。
