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

回执用私有 600 文件、临时文件+fsync+原子发布/替换+目录 fsync；独立 .lock 文件保持锁 inode 稳定。中断只能留下旧或新完整快照；状态 preparing/submitting/unknown、损坏/不安全回执都不能触发重发。并发占用时返回“正在处理”，应查询同一原回执。状态查询可能看到正在提交的完整旧快照，不代表请求失败。

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

附件必须提供完整实际字节及 `filename/content_type/size/sha1/content(Base64)`，用下载的实际字节计算 size/SHA-1；不把预期发送附件直接冒充下载结果。没有附件也须显式 `[]`。脚本比对发件账号、收件集合、主题、正文、格式、每份附件元数据及摘要，并验证观察邮件的带时区时间不早于操作；QQ 已受理返回消息 ID 时还核对 ID。缺字段、BCC 信息不可核实、正文被转换后无法精确匹配、时间语义不明、附件缺失时不升级。

时间语义必须经实际接口或宿主契约证实：已发送用 `time_basis=qq_sent_at`，收件方用 `mailbox_received_at`；不能用 created_at/发件人 Date 猜测，缺少可信语义则不升级。

收件方证据用 `stage=recipient`、实际独立 provider（例如 gmail）、收件账号及实际文件夹，不能使用 provider=qq；收件账号必须属于原任务收件人。BCC 通常不可见，收件方核验不要求可见 BCC，但保留 to/cc 与全部内容核验。

回执注明 source=host_independent_observation，保留 provider/message_id/读取引用及时间；该命令只匹配宿主提交的观察，不自行认证连接器来源或代替实际独立读取。只有 SendMessage 具有完整已知内容可自动匹配；原生 ReplyMessage/ForwardMessage 的最终引用正文和主题不能推断，保持 accepted，需外部核验并报告限制，不伪造可匹配内容。结果未知的 SendMessage 可以凭独立证据对账，整个过程无发送调用。
