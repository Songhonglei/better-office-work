# 自动读信与登录（1.5.1）

先有手机自动转发、有效 CLI profile 和专用邮箱授权。`read_sms.py` 每次实时检查邮箱身份与 mail:read，不使用 onboarding 历史状态作凭据。profile 的服务、SIM/尾号和可信发件人沿用现有配置。native 后端返回 `native_backend_use_host_workflow`，继续由宿主调用原生工具，见 cli-recipes.md；本入口不桥接原生连接器。

## 先选读信还是登录

只检查新短信：宿主在点击发码之前记录带时区 after，然后运行（占位符替换成本次值）：

```bash
python3 scripts/read_sms.py read --profile codex --service baidu --route SIM2_1234 --after '<本次发送前时间>'
```

它只输出校验状态和码长度，不显示验证码。没有浏览器配置时由用户在自己的手机/邮箱窗口查看并输入，Agent 只读登录结果。

完成登录：用户已明确目标站点和号码，并已在该站点页面填好手机号后：

```bash
python3 scripts/read_sms.py login --profile codex --service baidu --route SIM2_1234 --browser-config '<外置站点JSON路径>'
```

程序按顺序：检查邮箱身份 → 连接唯一目标页 → 检查号码尾号/已有登录态/可选图形验证 → 记录 after 并点击一次发码 → 有限轮询并完整分页 → 按原短信时间选最新且无冲突的验证码 → 内存填写与一次提交 → 等待配置的账号标识可见。验证码不经过聊天或跨工具参数。站点对发送按钮的点击可能不代表短信成功发出，回执 `send_requested` 只表示已尝试，结果不明确也不会重试。回执保留不含验证码的 `attempt_after`；需要继续检查同一条短信时，用 `read --after <attempt_after>`，不能重新运行 login 盲目重发。

after 在点击前按秒记录，匹配手机原短信时间的秒精度；不声称能区分同一秒内的先后。超出有效期即停止。邮箱默认最多等三分钟，最长四分钟；合法的转发延迟允许落在五分钟总有效期内，不另外把两分钟以上延迟一律判坏。原短信与收信仍须在本次窗口，短信更短有效期照常优先。每轮查询冻结自己的 before，翻页保持原条件；新一轮可推进 before。最多 20 页/100 条唯一消息；达到上限或部分读取失败会阻断，不能把局部结果称为最新。

## 浏览器首次连接

浏览器依赖可选，`read` 和原生邮箱流程不需要：

```bash
python3 -m pip install 'playwright>=1.56,<2'
```

连接使用 [Playwright 官方 CDP 接口](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)，只支持 Chromium，不能假定所有宿主浏览器工具都暴露 CDP。只填写已有页面，不自动新建、跳转、退出账号或关闭浏览器。运行时会断开自身驱动连接。

优先使用用户已提供的、无录屏/trace 的本机专用浏览器连接。没有连接时报告限制；只有用户要求准备浏览器时，才启动一个独立调试实例。不要在日常默认 Chrome profile 上开启调试。macOS 的独立实例示例（按真实路径核实浏览器，目录置于 Skill 外；自定义 data-dir 时沿用该目录）：

```bash
umask 077
mkdir -p "$HOME/.local/share/sms-agent-mail/browser-profile"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.local/share/sms-agent-mail/browser-profile"
```

端口只接受 `http://127.0.0.1:<端口>`，不接受远程主机、认证 URL、query 或 WebSocket 路径。不要启用 DEBUG、PWDEBUG、截图、trace、录像或请求正文日志。启动前确保端口未被其他进程占用。专用浏览器 profile 含登录会话，应保留本机私有权限，不打包或跨电脑复制。

## 站点配置只做一次

用户或宿主依据真实页面确认选择器，不能从短信邮件生成配置。配置保存在 Skill 外，例如 `~/.local/share/sms-agent-mail/sites/<站点名>.json`，目录权限 0700、文件 0600。配置不含验证码、完整手机号或凭据。下面是合成示例，URL 和选择器不能用于真实网站：

```json
{
  "cdp_endpoint": "http://127.0.0.1:9222",
  "login_url": "https://example.invalid/login",
  "service": "baidu",
  "route": "SIM2_1234",
  "phone_selector": "#phone",
  "send_selector": "#send-code",
  "code_selector": "#sms-code",
  "submit_selector": "#login",
  "success_selector": "#current-account",
  "captcha_selector": "#visible-captcha",
  "timeout_ms": 10000
}
```

| 配置 | 规则 |
|---|---|
| cdp_endpoint | 必填，本机专用 Chromium 的 HTTP CDP 地址 |
| login_url | 必填，HTTPS 原点与路径定位唯一已有标签页；忽略页内 query/fragment，配置本身不得包含它们。HTTP 仅允许 127.0.0.1 合成验收 |
| service / route | 必填，必须与本次命令、profile 对应 |
| phone_selector | 必填，唯一手机号输入框或确认文本；数字末尾必须匹配本次号码尾号 |
| send_selector / code_selector / submit_selector | 必填，唯一的发码按钮、验证码框和提交按钮；CSS、文本等定位语法由 Playwright 支持 |
| success_selector | 必填，能证明已登录的账号标识；操作前必须不可见，操作后必须可见。不要选普通提示、按钮或可能误判的元素 |
| captcha_selector | 可选，指向当前可见的图形验证；可见时转人工。未配置不代表能自动识别所有验证码控件 |
| timeout_ms | 可选，100–30000，默认 10000；连接和单次浏览器操作上限 |

只能自动填写同一主页面中的单一验证码框；多格码、跨域 iframe、需要跨域 SSO 跳转或未知选择器暂走人工。提交后仍需保持配置原点并出现账号标识，站点必须单独实测。准备期间已登录时保留现状，不主动退出。

## 命令参数

| 参数 | 含义 |
|---|---|
| read / login | 必填子命令，只读校验 / 发码及自动登录 |
| --profile / --data-dir | 必填 profile / 可选原有外置设置目录 |
| --service / --route | 必填本次服务键与 SIM 路由；用途固定 login |
| --after | read 必填，本次点击前的带时区时间，距当前不超过五分钟；login 禁止传，程序自行记录 |
| --browser-config | login 必填的私有外置 JSON；read 禁止传 |
| --wait-seconds | 默认 180，0–240；0 只做一次有界扫描（最多 15 秒），不进入等待；身份与浏览器准备/提交有各自超时，未包含在邮箱等待预算中 |
| --interval | 默认 3，0.1–30 秒；仅本任务内轮询，不创建定时任务 |
| --body-offset-hours | 默认 8，手机原始短信时间无时区时的偏移，范围 -23 与 23 之间，按手机实际时区设置 |

退出码：0=所选动作通过（read 不表示 login 通过），1=校验/运行阻断，2=命令参数错误。未知异常只输出脱敏原因，不输出异常原文。等待超过 30 秒时，stderr 定期输出只含阶段与轮询次数的进度，stdout 保留单份最终 JSON；调用方应分别捕获。`workflow_errors.py` 是内部错误类型，不单独运行。

## 结果和恢复

只读通过：`state=message_verified`、`message_verdict=pass`、`code_handoff=manual`、`login_passed=false`。
自动登录通过：`state=login_verified`、`code_handoff=browser_memory`、`login_passed=true`。
阻断：`state=blocked`，以 blocker 为准；消息通过与登录失败可以同时出现。`new_sms_full_body_read` 和 `pagination_complete` 只表示本轮读信，不表示已经找到目标码。不要输出原始 CLI 响应或异常。

| blocker | 下一步 |
|---|---|
| mail_cli_runtime_not_found | 当前执行环境找不到 CLI 所需运行时；先确认此环境的 Node.js 在 PATH 中，不需要重做 OAuth |
| mail_identity_not_verified | 用 onboard verify 检查身份；不覆盖其他账号。缺授权再走官方授权 |
| native_backend_use_host_workflow | 用宿主原生邮箱工具，见 cli-recipes.md |
| new_sms_not_found_before_deadline | 查手机拦截箱与转发状态；确认后再开始新的任务窗口，不连发 |
| mail_* / latest_* / target_message_time_invalid | 保留脱敏状态，核对接口契约、分页、正文原始时间或候选冲突；不选旧码兜底 |
| browser_playwright_not_installed | 按上文装可选依赖，或改人工输入 |
| browser_disable_debug_logging | 关闭当前进程的 DEBUG/PWDEBUG 后再准备浏览器 |
| browser_target_tab_missing_or_ambiguous | 打开或保留唯一的目标页，核对 URL |
| browser_phone_suffix_mismatch / browser_target_mismatch | 核对手机号、站点配置和本次 SIM 路由 |
| browser_captcha_requires_user | 用户先处理图形验证，再根据页面状态决定后续，不自动重发 |
| browser_send_result_uncertain_do_not_retry | 先核对倒计时和邮箱，不能因超时再点一次发码 |
| browser_login_not_verified_do_not_resubmit | 用户查看页面错误或人工验证；先确认是否已经成功，不能盲目再提交 |
| browser_already_logged_in | 保留当前登录态，报告已有登录；本次自动短信登录记为未执行 |
| browser_code_expired_do_not_submit | 验证码在等待页面期间过期，停止提交并检查当前页面；不自动重发 |
| browser_page_changed | 回到用户指定的正确页面，重新确认任务，不能把码填到另一页 |

安装器会复制 read_sms.py、browser_handoff.py、workflow_errors.py 和本说明，不覆盖站点设置。自动化不调用邮箱写入 API；CLI 自身的读信标记行为取决于供应商，不将它称为云端独立只读授权。

## 本地验收

标准库回归：`python3 -m unittest discover -s tests -v`。
浏览器合成链路另需 Chromium：`python3 -m playwright install chromium`，然后 `python3 tests/browser_smoke.py`。
测试启动隔离的本机 Chromium、本地网页和合成邮箱 CLI，验证命令入口、发码/提交次数、成功标识、错号、已有登录态和重复标签页；无真实短信或网站。合成测试通过不代表用户真实链路已通过。
