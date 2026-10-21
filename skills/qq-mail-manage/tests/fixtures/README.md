# Contract fixture provenance

qq-attachment-observed.json 固化 v1.4.2 的已观察附件响应形状：ListAttachments text JSON 数组，DownloadAttachment 无 size/摘要，GetMessage 提供绑定大小。来源为 5cb8210 中 test_attachment_contract.py；字段 ID、内容、时间均为合成值，非真实邮件/认证响应抓包。

它用于发现响应契约变化，不证明在线成功。GetMe、列表/搜索、发送/确认、错误、续期当前只有合成测试，尚无独立发布的真实脱敏样本；后续取得样本时保留来源/日期/脱敏范围，不把模拟响应标成真实抓包。
