# 原生连接器宿主：host bridge（1.5.1）

适用于**只有宿主原生邮箱连接器、拿不到 CLI 凭据**的 Agent。典型症状：
`onboard.py verify` 恒失败，或 `auth login` 被服务端以「已存在智能体邮箱」拒绝。

## 为什么不能直接用原生工具读码

原生连接器的 `GetMessage` / `SearchMessages` / `ListMessages` 都会把
`body` 或 `snippet` 放进工具结果。短信正文很短，snippet 就是正文——
调用一次，验证码就永久留在对话上下文里，违反 `SKILL.md` 的
「验证码不跨工具传递」。

**结论：原生工具可以用来验身份（`+me` 等价物），不可用来取码。**

## 架构

```
目标站登录页 ──┐
               ├─ 同一个进程（ego-browser 的 Node 运行时）
邮箱收件箱 ────┤        │
               │        ├─ 候选消息 → check_message.py（本次 after/before/服务/路由/用途）
               │        │       └─ 不 pass 就不填
               └────────┴─ 只输出一行 RESULT（code_length，无验证码）
```

读码、校验、填码共处一个进程，验证码不经过聊天、工具参数、终端或文件。
回执记 `code_handoff: "host-memory"`（`end-to-end.md:77` 认可的第三档）。

## 校验门（不可绕过）

每条候选消息，无论来自哪个源，**先**交给 `scripts/check_message.py`，
参数为本次 `--after/--before`、`--service`、`--route`、`--purpose login`。
只有 `verdict=pass` 才提取验证码并填入；`blocked` 只把 `blockers` 写进
`warnings`，不填、不提交。

这意味着以下情况都会阻断，而不是靠全文正则兜底：
发件人不在白名单、收件人不符、品牌标签缺失、主题路由未注册或尾号不符、
用途不是登录（重置密码/支付/注册等）、正文被截断、原短信时间或收信时间落在窗口外、
`created_at` 与正文时间偏差超限、验证码缺失或出现多个候选、候选码实为短信端口片段。

`code_source` 说明本次码的可信度：

| 值 | 含义 |
|---|---|
| `verified` | 走了校验门且 pass |
| `regex_unverified` | webmail 详情不可得，按配置降级为正则兜底（**未校验**） |

`regex_unverified` 会同时写 `warnings: ["message_unverified_regex_fallback"]`。
不想要这条降级路径就把 `webmail.allow_regex_fallback` 设为 `false`。

## 两条邮箱源

| 源 | 前提 | 稳定度 |
|---|---|---|
| `webmail` | 该浏览器已登录 agent.qq.com 网页版；详情页可解析出 from/to/正文/时间 | 依赖页面结构，改版会失效 |
| `imap` | 转发件落在有 IMAP 的邮箱；`imap.qq.com` 可用，`agent.qq.com` **无 IMAP/POP** | 稳定，无 UI 依赖 |

IMAP 侧按 `FROM <可信发件人> SINCE <after-1d>` 搜索后取全部候选，逐条过校验门；
适配器自身不做终判。

## 配置

固定路径：`~/.local/share/sms-agent-mail/bridge/config.json`（建议 0600）。
样例见 `scripts/host_bridge/config.example.json`。

| 字段 | 说明 |
|---|---|
| `mail_source` | `webmail` / `imap` |
| `profile` | 校验门使用的 profile；`trusted_senders` / `phone_routes` / `services` 都从这里取 |
| `service` | 服务键，必须是 profile `services` 里的键（如 `baidu`） |
| `route` | SIM 路由，形如 `SIM1_8512`，必须是 profile `phone_routes` 的键 |
| `skill_dir` | 可选；默认 `~/.workbuddy/skills/sms-agent-mail`，自定义安装位置时必填 |
| `code_wait_seconds` | 轮询上限，30–300，默认 240（验证码一般 5 分钟有效） |
| `poll_interval_seconds` | 轮询间隔，2–30，默认 4 |
| `webmail.list_url` / `row_selector` / `allow_regex_fallback` | 收件箱地址、行选择器、降级开关 |
| `imap.host/user/password_file/sender/limit` | 密码只给文件路径，校验 0600 且非符号链接 |
| `target.*` | 登录页 URL 与五个选择器，外加可选 `agree_selector` |

`target.phone` 必须是**完整手机号**（`1[3-9]` 开头的 11 位）。`phone_routes`
里的值只是四位尾号，**不能反推完整号码**，因此不做任何补猜；给了 `profile` 时
会校验号码尾号与 `route` 一致，不一致直接报 `target_phone_tail_mismatch`。

`config_check.py` 在校验前会拒绝：非 https 目标、缺选择器或 `service`/`route`、
路由格式非法、号码非完整手机号、密码文件权限过宽、等待窗口超过 300 秒。
它**不读取密码内容**。

`WB_BRIDGE_IMAP` 是 `run.mjs` 注入给 `mail_imap.py` 的内部变量，用户无需设置；
缺失时脚本返回 `bridge_env_missing` 而不是崩溃。

## 运行

```bash
ego-browser nodejs < ~/.workbuddy/skills/sms-agent-mail/scripts/host_bridge/run.mjs
```

- `{"self_test": true}`：用合成页面验证「读→填→提交→验登录态」整链，不联网、不碰真实邮箱
- `{"mail_only": true}`：只验证能否在本进程内取到码并过校验门，不操作目标站；此模式不要求 `target` 选择器，但邮件源与校验门照常
- 正常运行：发码一次 → 轮询邮箱 → 校验门 → 填码 → 提交 → 等账号标识

## 回执

```json
{"code_handoff":"host-memory","mail_source":"imap","code_source":"verified",
 "message_verified":true,"code_read":true,"code_length":6,"polls":2,
 "send_requested":true,"submit_attempted":true,"login_state":"verified",
 "warnings":[],"blocker":null}
```

`login_state=verified` 需要目标页出现 `account_marker`；没等到就是 `not_verified`。
`blocker` 只可能是固定错误码，**不会**拼接外部异常文本、`stderr` 或命令输出——
那些内容可能携带验证码。

## 失败分支

| blocker | 含义 | 处置 |
|---|---|---|
| `webmail_not_logged_in` | 浏览器未登录邮箱 | 停止，请用户在该浏览器登录 |
| `webmail_detail_unavailable` | 取不到详情且未允许降级 | 补 `row_selector` 或开 `allow_regex_fallback` |
| `gate_rejected` | 有候选但全部未通过校验门 | 看 `warnings` 里的 blockers，核对来源/窗口/用途 |
| `code_not_found_before_deadline` | 窗口内没有候选 | 先查手机拦截箱；不连续重发 |
| `mail_command_failed` / `mail_payload_invalid` | 子进程失败或输出异常 | 查 IMAP 配置与网络，不回显原始错误 |
| `fill_or_submit_failed` | 填码或提交失败 | **不回显异常文本**（可能含填入值），人工查看页面 |
| `config_invalid:<reason>` | 配置不合规 | 按 reason 修正，不放宽校验 |

## 安全边界

- 验证码只在该进程内存；用完立即置空
- 回执只用固定错误码；不 print 正文/主题/发件人；`stderr` 直接丢弃
- 一次任务最多点一次发码；超时不自动重发
- 不下载附件、不访问邮件里的链接
- 图形验证、滑块、人脸一律交人工

## 选择器怎么确认

先跑结构诊断（只取计数与布尔），不要 dump 正文：

```js
const d = await page.evaluate(() => ({
  rows: document.querySelectorAll('[class*=mail]').length,
  hasLogin: /扫码登录|请登录/.test(document.body.innerText)
}));
```

确认是登录态、且列表有行之后，再定 `row_selector`。注意页面文案里
常出现「验证码」字样（产品介绍、帮助链接），全文正则会把它们当候选——
所以 `row_selector` 一旦能定位，就不要省略。
