# QQ Mail Manage

Version: **1.0.1** · License: [MIT](LICENSE)

通过真实 Codex CLI 和腾讯官方 MCP 管理 QQ 邮箱，账号可配置。支持多 profile、OAuth 初始化、列表/搜索/正文/附件，以及按用户具体指令发送、回复、转发；删除需先确认具体清单，执行移至垃圾箱。

## Install

从本仓库复制整个 `skills/qq-mail-manage` 文件夹到 Codex 可发现的技能目录，例如 `~/.agents/skills/qq-mail-manage`，或该机器已使用的 `~/.codex/skills/qq-mail-manage`。不要只复制 SKILL.md；启动新会话后调用 `$qq-mail-manage`。

依赖：Python 3.11+、真实 Codex CLI、网络和可用的系统安全凭据库，无第三方 Python 包。macOS 已实测；Linux/WSL 须配置安全凭据库并另行验收，原生 Windows 不支持。

## Onboard

进入已安装的技能根目录：

```bash
python3 scripts/onboard.py doctor
python3 scripts/onboard.py init --account YOUR@qq.com --mode read
python3 scripts/onboard.py verify
python3 scripts/qq_mail.py list --limit 1
```

需要管理权限且用户授权后，使用 `--mode manage`。多账号使用子命令前的 `--profile NAME`；每台新电脑独立完成腾讯官方 OAuth，不复制令牌。dot 必须具备在已连接电脑上发现并执行这些本地脚本的能力；同机验证不等于 dot 或另一台电脑已验收。

## Operations

- [技能指令](SKILL.md)：工作流与用户授权边界。
- [初始化与跨机使用](references/onboarding.md)：权限、profile、复用本机授权及恢复。
- [操作参考](references/operations.md)：发送/回复/转发、批量删除、续期及写后核验。
- [版本记录](CHANGELOG.md)。

OAuth 只由真实 Codex 保存到安全凭据库。账号配置、邮件、附件和操作回执放在技能目录外，不随本包分发。不支持恢复、永久删除或清空垃圾箱。`queued=true` 仅代表入队；空响应、超时或结果未知时不自动重试。

## Validation

```bash
python3 -m unittest discover -s tests -v
```

29 项离线回归涵盖账号隔离、别名校验、授权范围、单次写入、未知结果不重试、删除续期和独立进程 onboard。不会自动发送或删除真实测试邮件。实际腾讯账号可获得的范围、完整历史、刷新和撤销行为仍需分别验收。
