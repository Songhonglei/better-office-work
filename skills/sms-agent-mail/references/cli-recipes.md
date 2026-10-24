# 只读调用约定

先 onboard status 读取外置设置，使用其中的 cli、expected_email、路由、主题模式和可信来源。没有 profile 时先完成 [接入](storage.md)。原生工具名称/schema 以目标 Agent 本次真实清单为准，不硬编码缓存命名空间。

以下仅为调用形状。搜索/读取 stdout、stderr 可能含真实验证码，应由同一执行环境通过子进程管道在内存捕获 JSON；检查退出码和 ok，只输出脱敏状态。不要把原始结果直接回显到工具文本、终端或聊天，不开启 HTTP 调试。

```text
<配置的CLI> +me
<配置的CLI> message +search --q <服务品牌> --search-in SEARCH_IN_CONTENT --to <目标邮箱> --dir inbox --after <带时区起始时间> --before <冻结结束时间> --limit 5
<配置的CLI> message +read --id <候选消息ID>
```

`--to` 是过滤条件，不切换身份。分页追加 cursor 时保留完整原条件和冻结结束时间；未完整分页不宣称找到最新短信。Agently CLI 1.0.18 的已观察形状：

- 身份在 data.aliases、data.scopes。
- 搜索 data.data 为列表，data.pagination.has_more/next_cursor 控制翻页。
- 正文 data.body，另有 body_format、subject、from.email、to[].email、created_at。
- inbox 实测 dir 为 `{"dir_id":1,"dir_name":"inbox"}`，不能当作字符串；字段冲突拒绝。

读完整正文后核对目标品牌、登录用途、可信来源、收件人、主题/正文 SIM 与号码。时间语义未确认、多个候选冲突或正文被截断时停止自动选码。正常浏览器填写也必须在可安全共享内存的执行环境中完成；不能把验证码打印出来作为跨工具传参方式。浏览器工具或可信收信时间缺失时，按 [验收](end-to-end.md) 记录具体阻塞。

## 两种后端共用的确定性判定

不管消息来自 CLI 还是宿主原生工具，都归一成同一份 JSON 再交给 `scripts/check_message.py`，避免每个 Agent 各自解释规则：

```json
{"from":{"email":"<发件人>"},"to":[{"email":"<收件人>"}],"subject":"<主题>",
 "body":"<完整正文>","body_format":"HTML","created_at":"<ISO8601>"}
```

`from`/`to` 也接受纯字符串。校验器只在输出里报告验证码长度，不回显验证码；`blockers` 为空即 pass。原生后端的身份验收不走 CLI，由宿主真实工具核对后用 `onboard.py confirm` 留痕。

## 正文骨架

实测的转发正文是固定结构，解析时按位置理解而不是靠猜：

```text
<短信端口号>
<【品牌】内容，含验证码与用途>
<路由，如 SIM2_1218>
SubId：<SIM 槽位>
<原始短信时间 YYYY-MM-DD HH:MM:SS>
<设备名>
```

首行的长数字（如 15 位）是端口号，形似号码但不能当验证码；校验器会把"候选码是端口片段"直接判 blocked。
