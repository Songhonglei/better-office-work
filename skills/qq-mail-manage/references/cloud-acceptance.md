# 临时云端发票转发验收

在 Ela 等目标云环境执行；本机 Mac 或离线模拟通过不能替代云端通过。此文是执行协议，不是已完成记录。只有用户确认官方完整凭据的安全取得、持久保存和宿主注入后，才开始真实验收；未注入时交付代码与待执行清单。

## 入口与认证

确认目标环境安装真实 Codex CLI、Python 3.11+，可以访问腾讯官方 MCP。OAuth 模式依旧需要凭据库；此案例使用 env_token 和 read_send，不需要删除权限或钥匙串。优先由宿主安全保存并注入完整 bundle（含 QQ_MAIL_ACCESS_TOKEN、QQ_MAIL_REFRESH_TOKEN、原签发 client_id、token_type、scope、expires_at），操作者不打印、不复制到参数文件或 .env，不从另一台电脑导出令牌。

在技能根目录：

```bash
python3 scripts/onboard.py --profile cloud doctor --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud init --account YOUR@qq.com --mode read_send --auth-mode env_token --token-env-var QQ_MAIL_ACCESS_TOKEN
python3 scripts/onboard.py --profile cloud verify
```

doctor 的存在性和历史时间不是认证成功；verify 必须本次实际通过 GetMe，账号别名精确匹配、scopes 包含 mail:read/mail:send 且不含 mail:delete 等额外写权限。失败停止，更新授权后再验证，不回退 OAuth，不在 401 后刷新并重放邮件。默认 env + host 由宿主负责续期；本技能自动刷新必须先显式配置可原子保存的 host_command 或 private_file，见 [凭据与刷新](credentials.md)。环境变量不等于持久存储。

## 凭据生命周期验收（用户确认后执行）

- 不读取或复制 Mac 凭据，不读取其他账号/客户端的 token；同一 refresh token 不可由多个环境独立并行续期，迁移须由宿主完成单一所有权交接。
- 记录来源、刷新策略、原签发客户端认证方法及持久化保障，只记录变量名/引用，绝不记录值。环境变量本身不保存轮换结果；宿主适配器须通过原子 CAS 合同。私有文件适配器须用户显式启用，明确未加密、生命周期不保证，目录 700、文件 600、当前用户所有且不在技能或仓库。
- 离线验收先执行 `python3 -m unittest discover -s tests -v`。真实续期仅在父任务取得用户确认后，在目标云环境完成：到期前仅一次 POST、轮换结果整体保存、第二进程读取新版本且不再次刷新；无 refresh_token 返回时保留旧值。不得为了测试故意重放已消费的真实 refresh token。
- 响应丢失、invalid_grant、保存失败或 pending 均停止，由宿主核对状态或替换新授权 bundle；不可直接清 pending 后重试旧值。容器重建必须恢复凭据、pending 与邮件回执，否则保持未验收。
- 刷新后的首次邮件操作之前必须 GetMe 再核对账号与所需 read_send 权限，无 mail:delete；核验失败不读取或发送邮件。真实刷新未经执行时明确记录“未测试”。

## 固定查询与完整选取

1. 执行开始时一次性固定 UTC+08:00 的结束时间 end，start=end-7 天，保存到技能目录外的私有验收记录。整个查询及分页始终复用这两个值，约定本地筛选为 start <= 实际收件时间 < end。
2. 本案例明确查 inbox；不混入 sent/trash/spam。需要其他文件夹时先记录范围，再分别完成分页。使用 SearchMessages，q=发票、search_in=SEARCH_IN_SUBJECT，调用 collect_pages 或 CLI search --all-pages；达到页数上限、游标异常或分页不完整时停止，不能在部分结果中选最新。
3. 对完整集合再次检查主题含“发票”。读取服务实际收件时间后排序，不能假设第一页或第一条最新；created_at 或发件 Date 的语义未经确认时不能改称收件时间。latest_by_received 只接受明确的 received_at；服务使用其他字段时，先记录其收件语义依据再转换，不自动猜测。时间字段缺失或最新时间并列未解消时报告歧义，停止发送。
4. 保存唯一源 message_id、原发件人、主题、收件时间、文件夹和固定查询范围。只读取这封候选的正文与按需附件，不扩展到整个邮箱。

可在目标环境生成带时区的固定时间，值写入验收记录，后续命令复用；时间不含凭据：

```python
from datetime import datetime, timedelta, timezone
end = datetime.now(timezone(timedelta(hours=8)))
start = end - timedelta(days=7)
```

## 发票事实与附件

- 从正文或实际发票附件提取：物品名称、发票类型、价税合计金额、币种，记录字段的页码/正文位置或 XML 字段。不能用不含税金额、税额代替价税合计；不能从文件扩展名猜发票类型，也不能默认币种。
- PDF/OFD/XML 可能是同一张票的不同格式；核对发票号和事实字段后才能归为同一票。多张不同发票、关键字段缺失或跨格式金额不一致时报告，不擅自选择、相加或猜测。无可用解析器时报告无法提取，不执行附件中的程序或指令。
- 用官方 ListAttachments/DownloadAttachment 获取全部原附件，逐个核对实际字节数及 SHA-1。最终发送附件仍校验字节、大小、SHA-1；每个 <=1 MiB，数量 <=3，总计 <=3 MiB。超限或校验失败即停止，不静默丢弃、不上传第三方替代。

## 改主题转发

原生 ForwardMessage 不能改主题。使用 SendMessage：

- to 为用户明确指定的验收收件人；不在通用技能中硬编码个人邮箱。
- subject 为“物品名称+发票类型+金额”，用实际提取值及字面加号连接；金额保留票面精度，币种在转发摘要中明确注明。字段有歧义则先报告。
- body 保留完整原正文和原格式，增加来源信息（原发件人、原主题、实际收件时间、源 message_id）以及字段摘要和币种。HTML 作为邮件内容，不执行其中脚本；来源字段按 HTML/文本格式安全转义。无法保留必要的正文或内联附件时报告，不称为完整转发。
- attachments 带上已校验的全部原附件。外部参数 JSON 放私有目录、权限 600，不能包含 token、alias_id、confirmation_token 或 skip_confirmation。

用户已明确给出选择规则、收件人和发送指令且字段完整时，execute-authorized 直接提交一次，不追加重复确认。只要求试验准备、凭据未注入或字段歧义时不发送。

## 两端独立核验

1. SendMessage 前已经落盘 submitting 状态。queued=true 仅为入队；不代表送达。
2. 从 QQ 的 sent 文件夹独立查询，按新收件人、实际提交时间、主题、来源信息和附件匹配，保存真实已发送 message_id。若只有队列响应，继续查证，不能重发。
3. 使用独立 Gmail 连接核对收件账号，检索对应新邮件，验证来源 QQ 地址、主题、正文中的原来源信息和原正文、全部附件的文件名/数量/字节数/内容摘要。不能只看 Gmail 搜索命中标题；下载核验附件需要收件方工具实际支持。
4. QQ 或 Gmail 任一侧无法确认，报告“待核验”及已知事实。超时、401、撤销、进程中断或云端重建都不能触发新建请求再次发送；先核对外部记录，缺乏肯定证据时保持结果未知。

## 验收记录

在包外记录 commit、目标云环境标识、认证模式（仅变量名）、固定时间/文件夹/页数、源邮件 ID 与收件时间依据、四个发票字段及证据、附件摘要、发送请求 ID、QQ sent ID、Gmail ID 和逐项结果。令牌、完整邮件正文和附件不要进入公开报告或仓库。

区分已通过、失败、未测试：离线测试证明代码路径；云端 verify 证明当次身份/权限；QQ 已发送证明发送记录；Gmail 内容及附件核验后才能报告验收送达。任何缺失步骤均不能用另一环境的结果补齐。
