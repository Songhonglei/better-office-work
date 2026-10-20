# 邮件操作参考

## 参数与私有数据

以技能根目录执行；--profile 放在子命令之前。Python 集成可将本技能 scripts 目录加入 sys.path 后导入 `CodexMail`；从 mail_config.load_settings().state_dir 获取该 profile 的私有数据路径。多 profile 的 Python 调用应使用独立进程或在建立客户端前选择 profile，不在同一进程并发切换环境变量。

`scripts/write_schemas.json` 为实际发现的四个写工具参数。外部参数文件仅放技能目录外的私有目录，权限 600，不含 alias_id、confirmation_token、skip_confirmation、file_refs；由桥接层生成身份和授权字段。不要输出参数中的附件 Base64、pending 中的确认令牌或任何 OAuth 凭据。

新发参数示例（仅示意，不代表授权）：

```json
{"to":[{"email":"recipient@example.com"}],"subject":"用户指定的主题","body":"用户指定的正文","body_format":"PLAIN"}
```

```bash
python3 scripts/qq_mail_write.py execute-authorized --tool SendMessage --arguments-file /private/path/draft.json --user-authorized
```

ReplyMessage：message_id、body，默认 reply_all=false。ForwardMessage：message_id、to、body，默认 include_attachments=false。确认是否包含原附件需依据用户指令；用户已要求带原附件时直接包含，不重复问。原生 ForwardMessage 不支持新主题，定制主题时用 SendMessage 发送用户指定的原正文和附件。

附件字段：filename、content_type、size、sha1、content（Base64）。核验返回的大小/SHA-1，再校验实际发送字节。当前已验证限制：最多 3 个，单个 1 MiB、合计 3 MiB；超限停止说明，不擅自上传第三方链接或删附件。

## 用户主动要求发前预览

```bash
python3 scripts/qq_mail_write.py prepare --tool SendMessage --arguments-file /private/path/draft.json
python3 scripts/qq_mail_write.py confirm --request-id REQUEST_ID --user-approved
```

prepare 使用官方 42801 确认流程，展示实际 operation_summary、收件人、主题、正文和附件后，按用户批准执行 confirm。未得到预期挑战时先查外部状态，不重复提交。普通已明确授权的发送用直接入口，不默认走这一轮。

## 批量广告清理

限定用户指定时间范围，保持 after/before 不变分页。列表每页最多 50 封；广告类别不明确则保留，账单、安全通知等不因为包含品牌名就当作广告。保存本次具体候选元数据：

```json
[{"message_id":"从接口取得的 ID","subject":"实际主题","from":{"email":"实际发件人"},"created_at":"2026-10-01T10:00:00Z"}]
```

```bash
python3 scripts/qq_mail_write.py prepare-delete-batch --review-file /private/path/review.json
```

完整展示日期、发件人、主题、总数、移至垃圾箱的动作；用户可以批准全部或编号。仅批准后运行：

```bash
python3 scripts/qq_mail_write.py confirm-delete-batch --batch-id BATCH_ID --user-approved
python3 scripts/qq_mail_write.py confirm-delete-batch --batch-id BATCH_ID --indices 1,3 --user-approved
```

两条命令是替代示例，不是依次执行。不要在执行一部分后重放整个批次。每次调用保留返回 request_id；成功项会标记 completed，重复提交被拒绝。

## 删除令牌续期

批量审阅耗时可能超过腾讯一次性确认令牌期限。本地 TTL 为 10 分钟，腾讯可能更短。批量 confirm 对每封邮件在原日期前后各 1 秒内，按确切 ID 检查垃圾箱及原文件夹，再即时获取新挑战，比对原先已展示的 operation_summary 后提交。已在垃圾箱则跳过且不再写入。

单封已批准删除可用 `confirm --request-id ID --user-approved --renew-confirmation` 执行同样流程。没有原始日期时不能续期；先获取目标的确切当前状态和日期，重新准备绑定同一目标的操作。

令牌明确返回 40001 时，记录 failed/failure_code=40001，完成状态核对后可再次用同一个请求执行上述续期，不必让用户重新批准未变的清单。网络丢响应、超时、中断或 unknown/submitting 不属于明确过期，禁止自动重试；先核对邮箱，并报告哪些完成、哪些待处理。新旧摘要不一致、目标找不到则停止，不能替换成相似主题的新邮件。

## 写入后核验与状态

发送/回复/转发：在 sent 中按收件人、主题和提交时间查到对应邮件，再报告已发送；queued=true 只代表入队，不能说送达或已读。

删除：在 trash 中按批准的确切 message_id 核验，报告已验证数量。不能仅凭 API 返回成功就宣称所有目标均在垃圾箱。桥接命令的 completed 表示服务返回成功；最终对用户的完成结论仍需文件夹核验。

状态保存在 data_home/state/PROFILE/pending，目录 700、文件 600。提交前写 submitting、绑定账号及参数哈希，成功后去除原参数与确认令牌。待确认/结果未知记录可能含正文和附件，仅保留本机；不得装进技能包。更新技能不会删除这些记录。

prepare 同样先写 preparing 再发请求；缺少预期挑战、丢响应或异常时落为 unknown，并返回 request_id。未知响应不等于失败或成功，不自动再次 prepare/confirm。发送必须有 queued=true 或消息 ID，删除必须有匹配 ID 的 deleted=true 才记录 completed；文件夹核验仍按前述步骤执行。

批次会在 stderr 输出逐封准备、确认、完成或停止阶段，stdout 保留最终 JSON。部分完成或中断后只读查询本地状态：

```bash
python3 scripts/qq_mail_write.py batch-status --batch-id BATCH_ID
```

输出编号、request_id、预览和状态，不输出令牌或正文/附件。此命令不访问邮箱也不重新提交；先核对 completed 的回执、unknown/submitting/preparing 的外部实际状态，再针对尚未执行且仍在原批准范围内的 pending 项选择 --indices。结果未知项即使当时尚未在垃圾箱显示，也不能直接当作未执行而自动重试。
