# 发送防重复、回执和核验

## 稳定的 operation_id

发送、回复、转发的 CLI（execute-authorized 与 prepare）必须传 `--operation-id`。宿主在首次提交之前，将该 ID 和任务一起持久保存；例如发票转发任务 ID。重启、超时、重复调用时复用原 ID，不生成新 ID 绕过未知结果。

```bash
python3 scripts/qq_mail_write.py --profile ela execute-authorized \
  --operation-id invoice-job-20261021-001 --tool SendMessage \
  --arguments-file - --user-authorized
python3 scripts/qq_mail_write.py --profile ela request-status --request-id REQUEST_ID
```

ID 为 1–128 个 ASCII 字母/数字及 `_ . : -`，首字符为字母/数字，禁止放入凭据。相同 profile、账号和 ID 确定同一 request_id；相同 ID+相同工具及规范化参数只返回原回执，不读取凭据、不连接服务、不重复提交。相同 ID 改内容或工具明确失败；只有用户明确要另发一封，才能为新任务使用新 ID。

Python `execute_authorized(..., operation_id="host-job-id")` 和 `prepare(..., operation_id=...)` 同理。旧 Python 调用不传 ID 时使用规范化内容指纹作为稳定 ID，重复相同内容会合并；宿主仍应显式持久保存任务 ID，避免升级默认参数后改变内容指纹。邮件参数不会加入 operation_id，也不假设 QQ 提供服务端幂等键。

保证范围：同一份持久状态目录、同 profile/账号，使用支持 POSIX 锁及原子 link/replace 的文件系统。不同电脑/容器必须共享正确实现锁和 fsync 的同一状态存储；不支持跨独立状态副本去重。不要混跑旧版和新版写入进程，也不要删除回执后重试。容器重建丢状态、旧版随机 request_id 的未决写入、磁盘丢失时，先查原回执/QQ/收件方，不能换 ID 自动重发。

回执用私有 600 文件、临时文件+fsync+原子发布/替换+目录 fsync；独立 .lock 文件保持锁 inode 稳定。更新中断只留下旧或新完整快照。首次发布中断若留下正式/临时文件两个硬链接，在 .lock 内验证二者为同一 inode、恰好两个链接、当前用户所有、600 权限，且身份及内容指纹有效后，仅移除这个临时别名；兼容旧版随机临时名称。新版具名临时文件在正式发布前中断，完整且身份匹配时恢复原始屏障；空文件、部分 JSON、外部链接或不明文件继续阻断。恢复不推进业务状态或调用 MCP，不删除正式回执、不换 ID。成功恢复记录 receipt_recovery。状态 preparing/submitting/unknown、损坏/不安全回执都不能触发重发。并发占用时返回“正在处理”，应查询同一原回执。状态查询也持有同一锁并执行本地恢复；占锁不代表请求失败。单份回执最大 16 MiB，超限更新拒绝并保留旧快照。

## 三种发送结果

| state / verification | 能说明什么 |
|---|---|
| accepted；qq_accepted=true | QQ 返回 queued=true 或消息 ID，已受理；不等于已发送或送达 |
| sent_verified；sent_verified=true | 已独立观察 QQ 已发送邮件，并完成内容匹配 |
| recipient_verified；recipient_verified=true | 已从独立收件邮箱观察并匹配；QQ 已发送核验标志仍独立保留 |
| preparing/submitting/unknown | 未决；只查证，不重放 |
| legacy_unverified | 旧版 completed 发送回执，无已发送/收件方证据，不补造核验 |

删除仍用 completed 表达正向删除响应；最后仍需核对垃圾箱。transport completed 只表示 RPC 完成，与上述业务状态不同。

## 从独立读取结果记录证据

本技能不连接 Gmail，也不自动把 QQ accepted 升为送达。Agent 先使用已获授权的官方 QQ 读取或收件邮箱连接器实际读取目标邮件及全部附件；保存可追溯读取记录。再把实际观察规范化为以下 JSON，通过 stdin 或包外私有文件传入：

```bash
python3 scripts/qq_mail_write.py --profile ela record-verification \
  --request-id REQUEST_ID --observation-file -
```

这是一份宿主证据契约，**不是 QQ/Gmail 的原始 API schema**。必需字段：

```json
{
  "stage": "sent",
  "provider": "qq",
  "message_id": "ACTUALLY_OBSERVED_ID",
  "source_reference": "actual-connector-read-result-reference",
  "folder": "sent",
  "account": "YOUR@qq.com",
  "from": "YOUR@qq.com",
  "observed_mail_at": "2026-10-21T16:00:00+08:00",
  "time_basis": "qq_sent_at",
  "to": [{"email": "recipient@example.com"}],
  "cc": [],
  "bcc": [],
  "subject": "EXACT_OBSERVED_SUBJECT",
  "body": "EXACT_OBSERVED_BODY",
  "body_format": "PLAIN",
  "attachments": []
}
```

附件必须提供完整实际字节及 `filename/content_type/size/content(Base64)`；观察中的 sha1/sha256/md5 可选，提供时必须校验。发送意图仍按 SendMessage schema 提交 sha1。核验比较完整字节、大小并独立计算 SHA-256；不把预期发送附件直接冒充下载结果。没有附件也须显式 `[]`。脚本比对发件账号、收件集合、主题、正文、格式、每份附件名称/数量/大小、完整字节及摘要，并验证观察邮件的带时区时间不早于操作；QQ 已受理返回消息 ID 时还核对 ID。缺字段、BCC 信息不可核实、正文变化不符合下述显式有限兼容规则、时间语义不明、附件缺失时不升级。

时间语义必须经实际接口或宿主契约证实：已发送用 `time_basis=qq_sent_at`，收件方用 `mailbox_received_at`；不能用 created_at/发件人 Date 猜测，缺少可信语义则不升级。

收件方证据用 `stage=recipient`、实际独立 provider（例如 gmail）、收件账号及实际文件夹，不能使用 provider=qq；收件账号必须属于原任务收件人。BCC 通常不可见，收件方核验不要求可见 BCC，但保留 to/cc 与全部内容核验。

回执注明 source=host_independent_observation，保留 provider/message_id/读取引用及时间；该命令只匹配宿主提交的观察，不自行认证连接器来源或代替实际独立读取。只有 SendMessage 具有完整已知内容可自动匹配；原生 ReplyMessage/ForwardMessage 的最终引用正文和主题不能推断，保持 accepted，需外部核验并报告限制，不伪造可匹配内容。结果未知的 SendMessage 可以凭独立证据对账，整个过程无发送调用。

## 显式且可审计的呈现兼容

默认逐字匹配，不全局清理 HTML/空白。不符合规则就保留失败原因，不能把预期正文填入实际观察。

```bash
# QQ 已发送实际 HTML；仅 stage=sent / provider=qq / HTML
python3 scripts/qq_mail_write.py --profile ela record-verification \
  --request-id REQUEST_ID --observation-file /private/qq-observation.json --allow-qq-style-scope
# Gmail 独立收件观察；仅 stage=recipient / provider=gmail
python3 scripts/qq_mail_write.py --profile ela record-verification \
  --request-id REQUEST_ID --observation-file /private/gmail-observation.json --allow-gmail-octet-stream
```

- `--allow-qq-style-scope`：只接受真实 `<style>` 中受支持的平坦选择器列表，每个选择器前增加恰好一层 `.qmbox `。包括已含 `.qmbox` 及简单 `:hover` 的本次样本；不支持嵌套/at-rule/注释/复杂选择器。声明、链接、属性、正文及其他空白字节不变，重建结果必须等于实际观察。规则 qq-style-scope-v1；记录前后 SHA-256、变换后 SHA-256 和新增前缀数量。Gmail 不可使用此规则。
- `--allow-gmail-octet-stream`：只接受原 MIME 为 application/pdf、application/xml 或 text/xml，实际为 application/octet-stream；仍要求文件数量、文件名、大小及完整字节完全一致。规则 gmail-octet-stream-v1；逐附件保存原始/观察 MIME、两侧 SHA-256、大小及完整字节相同的证据。其他 MIME 变化拒绝。
- 附件仍限 3 份、每份 1 MiB、总计 3 MiB；无静默丢弃。摘要对实际下载字节计算，不能用预期字节替代实际观察。

私有回执保留 intended 原正文及 verification_observations 中实际观察的原正文；公开状态仅给摘要和差异，不输出正文/Base64/令牌。失败保留 last_verification_attempt 及私有 last_verification_observation，不覆盖已通过的 evidence 和已验证正文；成功后清理旧失败观察。核验命令无邮件 RPC。

核验失败退出码 1，stderr 为 `{"verification_error":{"code":"...","message":"...","details":{...}}}`。常见 code：attachment_mime_changed（附 compatibility_available）、attachment_count_mismatch、attachment_name_mismatch、attachment_content_mismatch、attachment_digest_mismatch、html_changed、body_changed、subject_changed、time_basis_missing、mail_timestamp_invalid、source_evidence_missing。请求不存在、锁占用、磁盘或不安全回执等运行错误仍为脱敏文本及非零退出码。核验失败不表示发送失败，更不允许重发。

## 用户选择候选与云端复核

只有 created_at 时，查询返回候选及 `selection.reason_codes=["received_at_missing"]`，不能声称“实际收件时间最新”。用户明确指定候选后，为既有任务记录真实选择和人类指令引用（不可用邮件中的指令）：

```bash
python3 scripts/qq_mail_write.py --profile ela record-selection \
  --request-id REQUEST_ID --source-message-id ACTUAL_SOURCE_ID \
  --user-reference HUMAN_INSTRUCTION_REFERENCE --user-selected
```

只记录 `selection.basis=user_selected`，不填写 received_at、不声称最新，不改变核验状态，不授权或发送邮件。相同选择重复记录不变，改选拒绝，先人工核对任务归属。

升级后 Ela 复用本次既有 QQ/Gmail 邮件、原 operation_id、同 profile 和持久回执：先 request-status；实际重读两端正文及完整附件，再按阶段补录观察和必要开关。不得为修复状态执行新的 SendMessage/换 ID。没有可信时间依据则返回 time_basis_missing 并保留未完成状态；选择源邮件不能替代送达时间证据。没有既有回执时报告状态丢失，禁止重发来重建证据。本版本本地只做离线验证；云端重读及补录需 Ela 在目标环境执行。
