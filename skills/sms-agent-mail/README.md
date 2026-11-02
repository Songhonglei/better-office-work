# SMS Agent Mail

Version **1.5.1** · [MIT](LICENSE)

让 Agent 从专用邮箱读取手机转发的短信，核对服务、号码与时间，协助用户授权的网站登录。支持既有原生邮箱工具、腾讯官方 Agently CLI，或在没有 CLI 凭据的宿主上用 host bridge 完成同进程交接。

需要手机已能自动转发到目标邮箱。包内没有个人邮箱/号码默认值、授权码、token 或真实短信样本。每台设备在首次接入时确认参数并独立授权。

## 1.5.1 变更（Codex review 修复）

- **校验门**：host bridge 的每条候选消息先交给 `check_message.py`（本次 after/before + 服务 + 路由 + login 用途），只有 `verdict=pass` 才填码。此前两种新邮件源直接正则取数，绕过了发件人白名单、收件人、品牌、路由、用途、时效与正文完整性检查——已修。
- **回执不再拼接外部文本**：错误只输出固定错误码，`stderr` 直接丢弃。此前 `err.message` 可能携带 `page.fill` 的填入值或子进程输出中的验证码——已修，并加静态守卫测试。
- **路径去作者化**：入口从 `os.homedir()` 推导，配置可用 `skill_dir` 覆盖。此前写死作者绝对路径。
- **手机号**：`target.phone` 必须是完整 11 位号码，`phone_routes` 只用于校验尾号。此前 `auto` 会把四位尾号当完整号码填入（旧测试甚至断言了这个错误行为）。
- **frontmatter**：只保留 `name / description / license / metadata`，`version` 回 `metadata.version`、去掉 `python_optional`，通过 Codex skill 校验器；`playwright` 依赖改在正文声明。
- 测试 107 → 116（新增校验门、路径、异常脱敏、号码规则等守卫）。

- 新增 host bridge：解决「有原生连接器、但拿不到 CLI 凭据」的宿主。原生连接器的正文/摘要必然进工具结果，不能用来取码；host bridge 把取码与填码放进同一个进程，回执记 `code_handoff: host-memory`。
- 新增两条邮箱源：`webmail`（宿主浏览器已登录网页版收件箱）与 `imap`（转发件落在有 IMAP 的邮箱；`imap.qq.com` 可用，`agent.qq.com` 无 IMAP/POP）。
- 新增 `scripts/host_bridge/config_check.py`：目标必须 https、五个选择器必填、等待窗口 30–300 秒、IMAP 密码只给文件路径并校验 0600 与非符号链接；校验器不读取密码内容。
- 新增 `scripts/host_bridge/run.mjs`：ego-browser Node 运行时下单进程执行，内含 `self_test`（合成页面验整链）与 `mail_only`（只验取码）两种自检，对外只输出一行脱敏 RESULT。
- **每条候选消息先过 `check_message.py`**（本次 after/before + 服务 + 路由 + login 用途），只有 `verdict=pass` 才填码；发件人、收件人、品牌、路由、用途、时效、正文完整性任一不符即阻断。回执用 `code_source` 区分 `verified` 与 `regex_unverified`。
- 回执只允许固定错误码，不拼接异常文本或 `stderr`（二者可能携带验证码）；`target.phone` 必须是完整手机号，`phone_routes` 只用于校验尾号。
- 路径改为 `os.homedir()` 推导并在配置中可覆盖 `skill_dir`；frontmatter 只保留宿主通用字段，`version` 回 `metadata.version`。
- 新增 24 条离线测试（`tests/test_host_bridge.py`），全套 92 → 116。CLI 与原生流程不变，旧 profile 无需重建。

## 1.4.0 变更

- 新增 `read_sms.py read`：本次身份核对、有限轮询、冻结窗口完整分页、候选去重及最新短信判定，一条命令完成。
- 新增 `read_sms.py login`：连接用户指定的本机 Chromium 页面，核对号码尾号、记录时间并点击一次发码，校验后在同进程内存填写、提交一次并确认登录结果。
- 根据实机观察到的转发延迟，邮箱默认等待三分钟（可配 0–240 秒），保留五分钟总有效期与短信更短有效期；失败回执保留本次起点及脱敏阻断原因。
- 真实消息不写入文件或命令参数；只输出脱敏结果。没有浏览器连接、需要图形验证或登录态未确认时明确阻断。
- 保留 1.3.1 的目标、时效、脱敏与数字边界修复；旧 profile 无需重建。自动化入口只支持 CLI 后端，原生连接继续走宿主工具流程。

## 快速使用

首次仍按下文接入邮箱；已有正确 profile 和授权直接复用。自动化的参数、浏览器首次连接及失败恢复见 [自动读信与登录](references/automation.md)。

```bash
# 读信：after 必须是本次点击发码之前记录的带时区时间，不要照抄历史日期
python3 scripts/read_sms.py read --profile codex --service baidu --route SIM2_1234 --after '<本次发送前时间>'
# 登录：沿用已确认的站点配置；程序负责记录时间、发码、填写和确认结果
python3 scripts/read_sms.py login --profile codex --service baidu --route SIM2_1234 --browser-config '<外置站点配置路径>'
```

`read` 成功只说明消息已校验，`login` 成功才说明配置的登录态标识已出现。自动化不会填写完整手机号、主动打开网页、创建 CDP 端口、购买 ECS 或反复发短信；目标页面和手机号由用户/宿主先准备，首次只需配置一次站点选择器。

### 1.3.1 修复

- 校验器必须绑定本次服务、SIM 路由和 login 用途；多服务混杂或用途不符即阻断。
- 必须提供带时区的 after/before（最长五分钟），同时检查原短信时间、收信时间、当前时间与短信更短有效期；非法日期与窗口返回明确失败。
- 4–8 位码按完整数字识别，不截取长数字；报告不再输出原始主题或地址。
- 旧 profile 无需重建；调用 check_message.py 时必须新增 --service、--route、--purpose login，缺参数会明确报错。

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

先确认邮箱、SIM/尾号映射和可信转发发件人，以下全部是需替换的合成示例。优先复用可用原生邮箱连接；使用 CLI 时，在本 Skill 文件夹。其他 Agent 或第二账号用不同 profile 名称；profile 不会自动切换 CLI 的授权身份：

```bash
python3 scripts/onboard.py prepare --profile codex
npm install --prefix "$HOME/.local/share/sms-agent-mail/runtime" @tencent-qqmail/agently-cli@latest
python3 scripts/onboard.py init --profile codex --email agent@example.invalid --cli "$HOME/.local/share/sms-agent-mail/runtime/node_modules/.bin/agently-cli" --route SIM2_1234=1234 --trusted-sender forwarder@example.invalid --service baidu=【百度】
python3 scripts/onboard.py verify --profile codex
```

服务品牌与主题模板都可显式配置：`--service zhihu=【知乎】` 可重复，`--subject-pattern` 给含两个捕获组（路由、尾号）的正则。要改这些规则而保留身份，用 `set-rules`；它会把上一份配置存成 `<profile>.json.bak`：

```bash
python3 scripts/onboard.py set-rules --profile codex --service baidu=【百度】 --service zhihu=【知乎】
```

`.invalid` 地址不能直接用于真实验收。原生连接使用 `--backend native`，由目标 Agent 调用真实身份工具验收；`verify` 对 native 后端会明确返回"需宿主验收"（exit 1），宿主核对后用它留痕：

```bash
python3 scripts/onboard.py confirm --profile codex --evidence "host GetMe matched alias, mail:read present"
```

没有授权时由 Agent 先更新官方 CLI，再以后台 PTY 运行配置的 CLI `auth login`，原样显示官方链接，由用户核对邮箱与权限并完成。不要把密码、授权码或 token 发进聊天。已有正确身份直接复用，身份不符则停止，不覆盖别的账号。授权后再次 verify，然后执行 [端到端验收](references/end-to-end.md)。

## 存储与升级

- Skill 设置：`~/.local/share/sms-agent-mail/profiles/<profile>.json`；Unix 目录 0700、文件 0600。
- `--data-dir /private/path` 改变 Skill 设置/运行依赖位置，不搬动官方 OAuth；后续操作沿用同一参数。
- macOS CLI 实测按 workspace 分区，常见候选路径是 `~/Library/Application Support/agently-cli/agents/<workspace>/bootstrap_token.enc`，配套密钥由登录钥匙串管理。onboard verify/paths 只报告已观察到的文件，缺证据时不声称已确认。原生连接和其他操作系统的具体存储需各自核实。
- 新版本仍从新下载目录运行 install.py；升级只写技能文件，不触碰外置 profile、OAuth 文件、钥匙串或 CLI 配置，不要求重复授权。

完整参数、错误恢复和权限说明见 [存储与接入](references/storage.md)。

## 验证

不需要邮箱凭据即可运行离线检查（覆盖身份契约、接入边界、安装器保护、消息判定与自动读信）：

```bash
python3 -m unittest discover -s tests -v
```

合成消息可用文件做确定性判定，真实邮件只通过内存管道输入；输出只有脱敏判定与验证码长度：

```bash
python3 scripts/check_message.py --profile codex --message-json message.json --after 2026-01-01T00:00:00Z --before 2026-01-01T00:05:00Z --service baidu --route SIM2_1234 --purpose login
```

实际端到端由目标机器分别完成：安装 → onboarding → 身份 → 新短信搜索/完整正文 → 可信时间/服务/号码核对 → 在条件具备时完成网站登录 → 升级保留授权。只有 created_at 而无正文时间、缺浏览器、或不能安全共享内存时，停止自动填写并记录阻塞（default 走人工交接），不宣称完整登录通过。手机有短信但邮箱没有转发件时，先查手机拦截箱。

## 交给其他 Agent 的提示词

> 从 Songhonglei/better-office-work 的 skills/sms-agent-mail 下载完整 Skill，读取 README 和 SKILL.md，使用内置安装器安装到你实际使用的技能目录。先告知我配置与凭据实际存在哪里，按 onboarding 引导确认邮箱、SIM/尾号和转发发件人；已有正确授权就复用，没有则给我官方授权链接。运行离线检查，再按 references/end-to-end.md 做真实新短信验收。不要显示验证码、不要复制旧设备凭据、不要改 MCP 配置。分别报告安装、身份、读信、可信时间、浏览器登录和升级保留结果。

浏览器验收单独执行（Python Playwright 1.56.0 + Chromium）：

```bash
python3 tests/browser_smoke.py
```

该测试使用真实浏览器、本地页面和合成邮箱 CLI，不能替代真实手机/邮箱/网站验收；依赖准备见 [自动化说明](references/automation.md)。
