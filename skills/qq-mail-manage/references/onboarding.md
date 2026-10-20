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

用户在官方腾讯页面完成登录和权限确认。服务地址固定 `https://api.mail.qq.com/mcp`，不接受任意第三方代理地址，不伪装其他客户端。账号应能在授权后 `GetMe.aliases` 中唯一匹配，支持配置 QQ/Foxmail 邮箱别名；最终可用性以服务实际接受及 GetMe 为准。其他账号的真实授权尚未在本环境完成，不承诺所有账号都有同样能力。

read 仅允许 mail:read；read_send 允许 mail:read、mail:send；manage 允许 mail:read、mail:send、mail:delete。OAuth 按所选模式请求范围，env_token 核对已有 token 的实际范围，不为其降权。实际权限超出所选模式则中止；服务不给所需权限也不称为完成初始化。

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

## env_token：临时云端模式

通过 --auth-mode env_token 和 --token-env-var VARIABLE_NAME 选择认证，默认变量名 QQ_MAIL_ACCESS_TOKEN。变量名按 shell 环境变量规则校验，不能使用 PATH/HOME 等运行时配置变量。profile 只保存 auth_mode 和 token_env_var，不保存值；旧 profile 缺 auth_mode 时按 oauth_keyring 处理。

真实值必须由用户认可的官方令牌取得途径及云端 secret manager/运行时注入提供，另行确认，不在聊天、命令行、参数 JSON、.env 或仓库中传递。这里需要 QQ 官方 MCP access token，不是邮箱密码、IMAP 授权码或 refresh token。不要读取或导出 Mac 钥匙串，不借用其他客户端身份或令牌。

```bash
python3 scripts/onboard.py --profile cloud doctor --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud verify
```

init 自动跳过 codex mcp login，verify 实际执行 GetMe；不把变量存在视为认证成功。--configure-only 仅写非秘密配置，仍为 configured_not_verified。login 子命令在 env_token 下明确拒绝启动 OAuth，提示安全更新变量后 verify。

doctor 支持 --auth-mode/--token-env-var 诊断未初始化的环境。输出 token_variable_present/nonempty 和 auth_mode，不输出值；credential_status 为 unverified 或 previously_verified，last_verified_at 仅是历史实测，currently_verified 始终 false。只有本次 verify 成功才表示本次服务端身份/权限已验证；doctor 不探测钥匙串。

仅真正调用 MCP 的 app-server 子进程接收所选变量。版本检查、帮助、OAuth 登录等子进程移除登记的 QQ 令牌变量；配置中只传 bearer_token_env_var 变量名，不构造 Authorization 头；env_token 子进程将无关的 CLI 登录缓存设为 ephemeral，不读取系统登录凭据库。MCP 凭据由显式 bearer 变量提供，而非缓存或文件回退。沿用官方固定端点和同名配置冲突检查，仅允许与当前 profile 完全一致的 bearer_token_env_var；拒绝其他变量、静态认证头和 env_http_headers。

变量缺失、空值或非法值时在 app-server 启动前失败。服务返回 401、过期或撤销则终止当前客户端，不刷新、不切换 OAuth/文件/匿名身份、不重新提交写操作。若无法从底层错误判断原因，报告未验证并让宿主检查授权；不要因通用传输错误就重发。

QQ_MAIL_HOME 的配置和操作回执必须在私有位置，不放在技能目录或仓库。临时云环境重建可能同时丢失变量与回执；本功能不提供持久 secret 存储或刷新。发送结果不明时，先核对 QQ 已发送和收件方，不能在重建后新建请求直接重发。

变量存在但 scopes 过宽（例如 read_send token 含 mail:delete）会失败；应由官方授权供应方提供符合范围的新 token，不能靠选择只读模式伪称降权。

Codex 官方配置定义：[bearer_token_env_var 与认证顺序](https://developers.openai.com/codex/config-reference)。底层客户端版本和目标云环境仍须按 [云端验收](cloud-acceptance.md) 单独确认。
