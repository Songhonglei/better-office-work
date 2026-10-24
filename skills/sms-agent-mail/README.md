# SMS Agent Mail

Version **1.2.0** · [MIT](LICENSE)

让 Agent 从专用邮箱读取手机转发的短信，核对服务、号码与时间，协助用户授权的网站登录。支持既有原生邮箱工具，或腾讯官方 Agently CLI；不需要 ECS，不发送或删除邮件，不修改宿主 MCP 配置。

需要手机已能自动转发到目标邮箱。包内没有个人邮箱/号码默认值、授权码、token 或真实短信样本。每台设备在首次接入时确认参数并独立授权。

## 下载和安装

下载本目录的完整内容，或克隆仓库。不能只下载 SKILL.md，必须保留 scripts、references 和 tests：

```bash
git clone https://github.com/Songhonglei/better-office-work.git
cd better-office-work/skills/sms-agent-mail
python3 scripts/install.py --host codex
```

- Codex 默认安装到用户主目录 `.agents/skills/sms-agent-mail`。
- 本机已知的 WorkBuddy 结构可用 `--host workbuddy`；其他系统/版本先核实其技能目录，再传 `--skills-dir`。
- 其他 Agent 使用 `--host custom --skills-dir /confirmed/skills/path`，不假定各宿主共用目录。
- 依赖 Python 3.11+；CLI 接入还需 Node.js/npm。脚本不自动安装系统运行时。
- 已有同名技能时安装器更新固定文件，不删除未知文件，也不写数据/凭据目录；版本信息在 SKILL.md 的 metadata.version。需要更旧版本时由用户明确选择对应 Git 提交。

重启或重新加载目标 Agent，确认能发现 sms-agent-mail。宿主安装目录依据和迁移细节见 [迁移](references/migration.md)。

## 首次使用

先确认邮箱、SIM/尾号映射和可信转发发件人，以下全部是需替换的合成示例。优先复用可用原生邮箱连接；使用 CLI 时，在本 Skill 文件夹：

```bash
python3 scripts/onboard.py prepare --profile codex
npm install --prefix "$HOME/.local/share/sms-agent-mail/runtime" @tencent-qqmail/agently-cli@latest
python3 scripts/onboard.py init --profile codex --email agent@example.invalid --cli "$HOME/.local/share/sms-agent-mail/runtime/node_modules/.bin/agently-cli" --route SIM2_1234=1234 --trusted-sender forwarder@example.invalid
python3 scripts/onboard.py verify --profile codex
```

`.invalid` 地址不能直接用于真实验收。原生连接使用 `--backend native`，由目标 Agent 调用真实身份工具验收；命令会明确返回需宿主验收，不伪装 CLI 成功。其他 Agent/第二账号选不同的 profile 名称；profile 不会自动切换 CLI 的授权身份。

没有授权时由 Agent 先更新官方 CLI，再以后台 PTY 运行配置的 CLI `auth login`，原样显示官方链接，由用户核对邮箱与权限并完成。不要把密码、授权码或 token 发进聊天。已有正确身份直接复用，身份不符则停止，不覆盖别的账号。授权后再次 verify，然后执行 [端到端验收](references/end-to-end.md)。

## 存储与升级

- Skill 设置：`~/.local/share/sms-agent-mail/profiles/<profile>.json`；Unix 目录 0700、文件 0600。
- `--data-dir /private/path` 改变 Skill 设置/运行依赖位置，不搬动官方 OAuth；后续操作沿用同一参数。
- macOS CLI 实测按 workspace 分区，常见候选路径是 `~/Library/Application Support/agently-cli/agents/<workspace>/bootstrap_token.enc`，配套密钥由登录钥匙串管理。onboard verify/paths 只报告已观察到的文件，缺证据时不声称已确认。原生连接和其他操作系统的具体存储需各自核实。
- 新版本仍从新下载目录运行 install.py；升级只写技能文件，不触碰外置 profile、OAuth 文件、钥匙串或 CLI 配置，不要求重复授权。

完整参数、错误恢复和权限说明见 [存储与接入](references/storage.md)。

## 验证

不需要邮箱凭据即可运行离线检查：

```bash
python3 -m unittest discover -s tests -v
```

实际端到端由目标机器分别完成：安装 → onboarding → 身份 → 新短信搜索/完整正文 → 可信时间/服务/号码核对 → 在条件具备时完成网站登录 → 升级保留授权。仅有 created_at、缺浏览器或不能安全共享内存时，停止自动填写并记录阻塞，不宣称完整登录通过。

## 交给其他 Agent 的提示词

> 从 Songhonglei/better-office-work 的 skills/sms-agent-mail 下载完整 Skill，读取 README 和 SKILL.md，使用内置安装器安装到你实际使用的技能目录。先告知我配置与凭据实际存在哪里，按 onboarding 引导确认邮箱、SIM/尾号和转发发件人；已有正确授权就复用，没有则给我官方授权链接。运行离线检查，再按 references/end-to-end.md 做真实新短信验收。不要显示验证码、不要复制旧设备凭据、不要改 MCP 配置。分别报告安装、身份、读信、可信时间、浏览器登录和升级保留结果。
