# Changelog

All notable changes to this skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.2] - 2026-11-25

### Changed
- 运行命令改为跨平台写法（macOS / Linux 用 `python3`，Windows 用 `python` + `%USERPROFILE%`），补充"系统无 Python 时用客户端托管解释器"的探测路径；原文只写了 `python.exe`，非 Windows 用户无法照抄
- 新增「安装」章节：市场 / 手动拷贝 / Git 克隆三条路径，附 `wbipc/endpoint.json` 环境自检
- 地点 id 不再硬编码（原文写死 1–4 号地点，实测已出现第 5 个地点），改为运行时从 `travel/config` 现取

### Fixed
- `references/wbipc-protocol.md` 中 `travel/depart` 的 body 写成 `{}`，与 v1.0.1 实现（`{"location_id": N}`）不一致，照文档排查会误判

## [1.0.1] - 2026-10-31

### Fixed
- 派遣一直返回 `code=400 invalid request`：`travel/depart` 必须携带 `{"location_id": N}`，改为派遣前先 `GET /activity/growth/buddy/travel/config` 取地点列表再随机选一个，实测派遣成功

## [1.0.0] - 2026-09-26

### Added
- 初版：通过客户端 wbipc 守护进程代理请求完成每日签到（token 不落地，兼容 `$wbEncrypted` 加密登录态）
- 签到状态查询（幂等防重复）、领取签到、派猫猫旅行闭环（查状态 / 领旅行积分 / 派遣 Buddy）
- 输出单行 JSON，含 `streak_days`、`credit_gained`、`balance` 与旅行状态
