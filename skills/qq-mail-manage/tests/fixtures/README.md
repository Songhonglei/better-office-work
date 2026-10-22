# Contract fixture provenance

qq-attachment-observed.json 固化 v1.4.2 的已观察附件响应形状：ListAttachments text JSON 数组，DownloadAttachment 无 size/摘要，GetMessage 提供绑定大小。来源为 5cb8210 中 test_attachment_contract.py；字段 ID、内容、时间均为合成值，非真实邮件/认证响应抓包。

它用于发现响应契约变化，不证明在线成功。GetMe、列表/搜索、发送/确认、错误、续期当前只有合成测试，尚无独立发布的真实脱敏样本；后续取得样本时保留来源/日期/脱敏范围，不把模拟响应标成真实抓包。

## 实际脱敏正文对（2026-10-22）

用户从 Ela 云端验收提供 `01-before-send.sanitized.html`（提交前）与 `02-qq-sent.sanitized.html`（QQ 已发送实际读取）。保留字节、空白和 style 段；账号、金额、日期、公司、ID 等替换为脱敏占位，URL/图片改为无外部请求的占位。HTML 只作为文本比较，不执行。唯一变化：`<style>.qmbox .backBtn:hover` → `<style>.qmbox .qmbox .backBtn:hover`。

- 提交前 UTF-8 SHA-256：`ff4f3160a10ab4d83004ce46fd0a73c16d7085e5129eee823ebff3d64e175dc2`
- QQ 实际正文 UTF-8 SHA-256：`07a6f7eb45544f80e47082d7edd57afe8bff919ad9f4924e7e508fd63e27189d`

该对证明这一次已观察的 HTML 变化形状，不证明所有 QQ HTML 的规范化规则。Gmail 的 MIME 变化依用户转述的 Ela 结果实现保守兼容；测试附件字节和连接器观察均为合成值，没有独立原始 Gmail 样本。本地不连接真实邮箱。
