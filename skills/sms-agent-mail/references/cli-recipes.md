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
