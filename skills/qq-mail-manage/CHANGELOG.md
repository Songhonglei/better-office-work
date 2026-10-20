# Changelog

## [1.0.1] - 2026-10-20

### Added

- 首次加入 Better Office Work Flow：真实 Codex + 腾讯官方 MCP，支持可配置账号、多 profile、OAuth onboard、查询/搜索/附件、发送/回复/转发及确认后移至垃圾箱。
- 批量删除进度、部分完成回执查询及确认令牌续期。

### Fixed

- 拒绝缺少正向成功字段的写入响应，prepare 前持久化记录，结果未知不自动重试。
- 删除批次在网络调用前预检日期和 ID；阻止继承同名其他 MCP 的认证配置。
- 再初始化保留迁移服务名，明确损坏 profile 的恢复提示，阻止私有数据目录放入技能包。

### Validation

- 29 项离线回归通过；UGLIC 已确认问题修复，skill-release-audit 六模块 PASS。
- 本机真实身份及一封列表查询通过；dot 对话、其他实体电脑和 Linux/WSL 仍需各环境验收。
