# QQ Mail Manage

Version: **1.3.1** · License: [MIT](LICENSE)

通过真实 Codex CLI 或显式直接 HTTP 后端和腾讯官方 MCP 管理 QQ 邮箱，账号可配置。支持多 profile、OAuth/keyring 或环境变量认证初始化、列表/搜索/正文/附件，以及按用户具体指令发送、回复、转发；删除需先确认具体清单，执行移至垃圾箱。

## Install

从本仓库复制整个 `skills/qq-mail-manage` 文件夹到 Codex 可发现的技能目录，例如 `~/.agents/skills/qq-mail-manage`，或该机器已使用的 `~/.codex/skills/qq-mail-manage`。不要只复制 SKILL.md；启动新会话后调用 `$qq-mail-manage`。

依赖：Python 3.11+ 和网络，默认 codex 后端另需真实 Codex CLI；OAuth 需要系统安全凭据库，env_token 需要宿主安全注入官方 MCP access token，无第三方 Python 包。macOS 已实测；Linux/WSL 需按所选认证模式配置并另行验收，原生 Windows 不支持。

## Onboard

进入已安装的技能根目录：

```bash
python3 scripts/onboard.py doctor
python3 scripts/onboard.py init --account YOUR@qq.com --mode read
python3 scripts/onboard.py verify
python3 scripts/qq_mail.py list --limit 1
```

仅发信使用 `--mode read_send`，需要删除且用户授权后使用 `--mode manage`。多账号使用子命令前的 `--profile NAME`；oauth_keyring 在新电脑独立完成腾讯官方 OAuth，不复制令牌。dot 必须具备在已连接电脑上发现并执行这些本地脚本的能力；同机验证不等于 dot 或另一台电脑已验收。

## Temporary cloud authentication

先由用户或宿主另行确认官方 MCP access token 的安全取得和注入；以下只填写变量名，不填写值：

```bash
python3 scripts/onboard.py --profile cloud doctor --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud verify
```

env_token 跳过浏览器登录和钥匙串。默认宿主注入完整凭据：`QQ_MAIL_ACCESS_TOKEN`、`QQ_MAIL_REFRESH_TOKEN`、`QQ_MAIL_CLIENT_ID`、`QQ_MAIL_TOKEN_TYPE`、`QQ_MAIL_SCOPE`、`QQ_MAIL_EXPIRES_AT`（UTC Unix 秒），机密客户端另有 `QQ_MAIL_CLIENT_SECRET`。旧版仅 access token 配置仍兼容；已知临近到期则停止，由宿主刷新并重新注入。环境变量不等于持久存储，也不能把轮换结果只保存在当前进程环境中。

需要本技能自动刷新时，优先选择宿主 `host_command` 原子存储适配器，显式设置 `--refresh-policy auto --client-auth-method METHOD`。无宿主适配能力时可显式选择 `private_file`；它未加密，生命周期不保证，目录 700、文件 600、当前用户所有，必须在技能及仓库外。沙箱空 `.git` 占位可用显式独立 `--credential-state-dir` 核实，默认仍严格拒绝；实际仓库/链接/不安全权限始终拒绝，需要 Git。独立状态不会被代码目录升级覆盖，但未加密文件可能进入工作区快照，重建后不保证保留。具体配置、宿主协议和中断恢复见 [凭据与刷新](references/credentials.md)。同一 refresh token 不可由多个环境独立并行续期；不要从 Mac 导出凭据。

单次刷新仅向已核实的 QQ 官方端点，遵循宿主既定代理与 CA/TLS 配置，不跟随重定向，按原签发客户端认证；轮换结果整体原子保存。响应丢失、invalid_grant 或中断会保留 pending 屏障，交给凭据所有者核对，禁止重试旧 refresh token。刷新后 GetMe 必须核对邮箱和权限；refresh token 不传给 MCP 子进程。邮件发送超时或结果未知仍不重发。

已有 token 含 `mail:delete` 且用户明确要求复用时，可在现有 profile 上运行以下非秘密配置更新（省略凭据来源参数会保留原配置）：

```bash
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send \
  --allow-extra-delete-scope --configure-only
```

默认关闭；用 `--no-allow-extra-delete-scope` 显式关闭。这里只接受已有凭据额外的 mail:delete，不会降低 token 本身权限或改写原始 scope；GetMe 仍核对账号、必需权限和未知 scopes。mode 和请求 scopes 保持 read_send/read+send，删除工具始终禁止。真实 verify 仍由目标环境在授权范围内执行。

无法启动嵌套 Codex 的宿主可显式配置 `--backend direct_http --auth-mode env_token`，无需 Codex CLI，不更改平台限制，不自动回退。完整协议、配置命令、时限及持久错误回执见 [直接 HTTP MCP](references/direct-http.md)。

## Operations

- [技能指令](SKILL.md)：工作流与用户授权边界。
- [初始化与跨机使用](references/onboarding.md)：权限、profile、复用本机授权及恢复。
- [凭据与刷新](references/credentials.md)：来源、续期、并发及故障恢复。
- [操作参考](references/operations.md)：发送/回复/转发、批量删除、续期及写后核验。
- [云端发票转发验收](references/cloud-acceptance.md)：固定七天范围、全分页、实际收件时间、发票字段及 QQ/Gmail 双端核验。
- [版本记录](CHANGELOG.md)。

原 OAuth 仍由真实 Codex 保存到安全凭据库；env_token 通过显式选择的来源读取，不自动寻找本机凭据。账号配置、邮件、附件和操作回执放在技能目录外，不随本包分发。不支持恢复、永久删除或清空垃圾箱。`queued=true` 仅代表入队；空响应、超时或结果未知时不自动重试。

## Validation

```bash
python3 -m unittest discover -s tests -v
```

159 项离线回归（保留原有 154 项）涵盖账号隔离、别名校验、授权范围、单次写入、未知结果不重试、删除续期和独立进程 onboard。不会自动发送或删除真实测试邮件。实际腾讯账号可获得的范围、完整历史、真实刷新和撤销行为仍需分别验收。
