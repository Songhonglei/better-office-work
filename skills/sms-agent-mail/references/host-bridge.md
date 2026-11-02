# 原生连接器宿主：host bridge（1.5.0）

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
邮箱收件箱 ────┘        │
                        └─ 只输出一行 RESULT（含 code_length，无验证码）
```

读码与填码共处一个进程，验证码不经过聊天、工具参数、终端或文件。
回执里记 `code_handoff: "host-memory"`（`end-to-end.md:77` 认可的第三档）。

## 两条邮箱源

| 源 | 前提 | 稳定度 |
|---|---|---|
| `webmail` | 该浏览器已登录 agent.qq.com 网页版；DOM 可解析 | 依赖页面结构，改版会失效 |
| `imap` | 转发件落在有 IMAP 的邮箱；`imap.qq.com` 可用，`agent.qq.com` **无 IMAP/POP** | 稳定，无 UI 依赖 |

`imap` 需要在手机转发应用里把收件地址增加一份到 IMAP 邮箱，或在该邮箱配收信规则。

## 配置

固定路径：`~/.local/share/sms-agent-mail/bridge/config.json`（建议 0600）。
样例见 `scripts/host_bridge/config.example.json`。

| 字段 | 说明 |
|---|---|
| `mail_source` | `webmail` / `imap` |
| `profile` | 可选，继承该 profile 的 `trusted_senders` 与唯一号码 |
| `code_wait_seconds` | 轮询上限，30–300，默认 240（验证码一般 5 分钟有效） |
| `poll_interval_seconds` | 轮询间隔，2–30，默认 4 |
| `webmail.list_url` / `row_selector` | 收件箱地址；选择器缺失时退化为全文匹配 |
| `imap.host/user/password_file/sender` | 密码只给文件路径，校验 0600 且非符号链接 |
| `target.*` | 登录页 URL 与五个选择器，外加可选 `agree_selector` |

`config_check.py` 在校验前会拒绝：非 https 目标、缺选择器、无效枚举、
密码文件权限过宽、等待窗口超过 300 秒。它**不读取密码内容**。

`WB_BRIDGE_IMAP` 是 `run.mjs` 注入给 `mail_imap.py` 的内部变量，用户无需设置；
缺失时脚本返回 `bridge_env_missing` 而不是崩溃。

## 运行

```bash
ego-browser nodejs < ~/.workbuddy/skills/sms-agent-mail/scripts/host_bridge/run.mjs
```

- `{"self_test": true}`：用合成页面验证「读→填→提交→验登录态」整链，不联网、不碰真实邮箱
- `{"mail_only": true}`：只验证能否在本进程内取到码，不操作目标站；此模式不要求 `target` 选择器，但邮件源仍按完整规则校验
- 正常运行：发码一次 → 轮询邮箱 → 填码 → 提交 → 等账号标识

## 回执

```json
{"code_handoff":"host-memory","mail_source":"webmail","code_read":true,
 "code_length":6,"polls":3,"send_requested":true,"submit_attempted":true,
 "login_state":"verified","blocker":null}
```

`login_state=verified` 需要目标页出现 `account_marker`；没等到就是 `not_verified`。
`code_read=false` 且 `blocker` 指向具体原因时，不得宣称登录成功。

## 失败分支

| blocker | 含义 | 处置 |
|---|---|---|
| `webmail_not_logged_in` | 浏览器未登录邮箱 | 停止，请用户在该浏览器登录 |
| `webmail_multiple_candidates` | 一页出现多个不同候选 | 补 `row_selector` 精确定位，别放宽规则 |
| `code_not_found_before_deadline` | 超时未取到 | 先查手机拦截箱；不连续重发 |
| `imap_no_matching_message` | 没有可信来源的转发件 | 核对 `sender` 与转发是否真的到达该邮箱 |
| `config_invalid:*` | 配置不合规 | 按原因修正，不放宽校验 |

## 安全边界

- 验证码只在该进程内存；用完立即置空
- 不 print 正文/主题/发件人；错误只抛固定标识
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
