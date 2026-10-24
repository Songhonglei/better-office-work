# 存储、首次接入与升级

## 存储位置

首次使用先告诉用户以下位置，OAuth 由其所有者管理，不将配置目录说成已经迁入 token 的目录：

| 内容 | 位置/管理者 |
|---|---|
| 本 Skill 的邮箱、CLI 路径、路由、来源、验收状态 | 默认用户主目录 `.local/share/sms-agent-mail/profiles/<profile>.json` |
| 独立 CLI 运行依赖 | 采用独立安装时为数据目录中的 `runtime/` |
| CLI 自身配置 | 用户主目录 `.agently-cli/config.json`，不是 token 文件 |
| macOS CLI OAuth 候选路径 | `~/Library/Application Support/agently-cli/agents/<workspace>/bootstrap_token.enc` |
| macOS 配套密钥 | 登录钥匙串；已核实分区采用 service `agently-cli/agents/<workspace>`，account `master.key` |
| 原生邮箱连接器 | 宿主管理；未核实具体位置时说明未知，不声称它使用 CLI 目录 |

`workspace` 来自 CLI 本次真实 `auth status`，不伪造宿主环境变量。verify/paths 仅在实际观察到候选文件时将其报告为 OAuth 文件，否则显示候选路径和未观察状态。钥匙串数据库 `~/Library/Keychains/login.keychain-db` 还含其他应用数据，不复制它。供应商根目录其他历史文件保持原样，不猜测或清理。

其他操作系统的供应商存储需要当地核实，不套用 Mac 路径。Windows 的目录权限还需要 NTFS ACL 验收；本项目没有将 Unix mode 当成 Windows 安全证明。

## 首次接入

1. 一次性确认期望邮箱、手机主题的 SIM/尾号映射、手机转发配置中的可信发件邮箱。默认服务品牌包含百度/今日头条，其他服务由用户明确目标后配置。先检查目标宿主是否已有专用邮箱原生工具，不能从缓存或个人 QQ 连接推断已授权。
2. 选择接入后端，先向用户说明数据与凭据位置。CLI 路径需要 Python 3.11+、Node.js/npm；原生后端只需 Python 用于本 Skill 的设置与安装工具。
3. 已有稳定 CLI 可复用其路径；准备新授权前先更新腾讯官方 CLI。独立安装示例见 README：prepare 私有数据目录 → npm 安装 runtime → init。必须先选定 CLI 路径再 init，避免创建指向临时任务目录的长期配置。
4. `init` 首次创建 profile 必须显式 --email，可同时指定 --route 和 --trusted-sender。示例地址和号码都需替换。尚未配置路由/来源时可做身份验收，但不能自动选择验证码；之后由用户确认参数，保留旧配置副本再编辑外置 JSON，不用重跑 init 强制覆盖。
5. CLI 用 verify 核对实际邮箱和 mail:read；原生后端会要求目标 Agent 调用本次真实身份工具，不调用 CLI。正确身份复用，错误身份停止，不能通过 --to 过滤冒充切换授权。
6. 没有授权时先更新 CLI，再后台 PTY 运行所配置 CLI 的 `auth login`。原样显示它输出的原始官方 URL，单独放代码块，提示“请点击或复制以下链接在浏览器中完成授权：”。用户在官方页面核对邮箱与权限后完成；失败/超时不自动重试，不索要密码或 token。完成后再 verify，最后按 [真实验收](end-to-end.md) 检查新短信。

## 命令参数

所有路径都可传绝对路径，`--data-dir` 支持用户目录展开。profile 为 1–32 位小写字母/数字/连字符，首位须字母；CLI 执行不使用 shell 字符串拼接。

| 命令/参数 | 行为 |
|---|---|
| onboard.py prepare --profile NAME | 只创建外置私有数据目录，不创建邮箱配置或授权 |
| init --profile NAME --email ADDRESS | 首次必需明确邮箱；已有 profile 时省略 email 沿用原值，其他参数仍须与已有配置一致 |
| --backend cli / native | init 默认 cli；native 由宿主真实工具验收 |
| --cli PATH | 默认 agently-cli；可指定稳定绝对路径，不自动修改全局 PATH |
| --route SIM2_1234=1234 | 可重复，显式确认号码路由；未给出时新配置为空，不猜测真实号码 |
| --trusted-sender ADDRESS | 可重复，来源须由用户的手机转发配置确认；未给出时新配置为空 |
| status --profile NAME | 只读外置设置，不联网，不执行 CLI；验证状态仅是历史记录 |
| paths --profile NAME | 显示配置与已记录/观察到的凭据位置，不读 token 内容 |
| verify --profile NAME | CLI 调用 +me 和本地 auth status，更新外置验收元数据，不读取短信 |
| --data-dir PATH | 各 onboard 命令和安装器均支持；改变 Skill 数据目录，不改变供应商 OAuth 存储 |
| check_access.py --expected-email ADDRESS [--cli PATH] | 只核对 CLI 身份/权限，不读取短信或写设置 |
| install.py --host codex/workbuddy/custom | 从新下载目录安装/升级，custom 必须配 --skills-dir |
| install.py --skills-dir PATH | 经目标 Agent 核实的技能父目录；最终子目录为 sms-agent-mail |

profile JSON 的 schema=1，expected_email/cli/backend 是身份与运行配置；phone_routes/subject_pattern/services/trusted_senders 是用户确认的解析规则；verification/checked_at/reported_workspace 是历史身份检查元数据。status 不是实时授权证明，执行读信前仍做身份调用。

## 失败恢复

- 未找到 CLI/依赖：安装官方依赖或恢复原来配置的稳定路径，再 verify；不删除凭据。
- initial_email_required/invalid_email：提供真实目标邮箱，不用示例地址或复制其他账号授权。
- existing_profile_differs_not_overwritten：保留原配置；核对是否用错 profile/路径。确需改参数时先保留副本，再由用户授权编辑外置配置。
- 私有目录/文件权限错误：Unix 确认属于当前用户，目录 0700、profile 0600；拒绝符号链接、与 Skill 或供应商存储重叠的数据路径。不要通过放宽凭据权限绕过。
- 身份不符：停止，确认目标宿主和账号；不登出、不自动覆盖现有授权。
- native 验收返回非零：由 Agent 使用宿主真实身份工具核对，不重新走 CLI 冒充成功。
- 安装器 invalid paths/files：检查源文件是否齐全、是否从新下载目录执行及目标是否与受保护目录重叠；修正后再运行，不删除配置。

退出码：onboard init/prepare/status/paths 成功为 0；verify 的身份或原生验收未通过为 1，执行/配置错误为 2（上游检查可能透传 2）。check_access 成功为 0，身份/权限不匹配为 1，CLI/契约失败为 2。安装器成功为 0，参数、路径或文件错误为 2。

## 升级保护

新版本仍从新下载目录运行 install.py。它只更新固定清单的技能文件，逐文件原子替换，不写外置 profile、供应商 OAuth、钥匙串、CLI 配置，不删除未知文件，不 logout，不重跑 init。升级无需重复授权；授权失效时才重新走接入流程。

自定义 --data-dir 只移动本 Skill 的设置/依赖位置，不解密或搬动 OAuth，不修改 HOME 来伪装目录切换。既有外置配置的邮箱、路由等在升级后保留。
