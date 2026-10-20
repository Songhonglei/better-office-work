# Better Office Work Flow

> AI Agent Skill Suite — 办公自动化技能套件，覆盖发票处理、Token 用量分析、小红书发布、文本润色等高频办公场景。

## Skills

| Skill | Description |
|---|---|
| [qq-mail-manage](./skills/qq-mail-manage/) | QQ 邮箱管理：真实 Codex + 腾讯官方 MCP，可配置账号/多 profile、OAuth onboard、邮件与附件读写，确认后移至垃圾箱；支持具备本地执行能力的 dot/Codex（v1.0.1） |
| [macos-power-control](./skills/macos-power-control/) | macOS 合盖与电源设置：一句话需求解析，设置前确认，区分电池/接电、临时防休眠与持久策略，附验证和恢复流程 |
| [invoice-auto-forward](./skills/invoice-auto-forward/) | 邮箱发票自动转发：IMAP 扫描 + 发票解析（PDF/OFD/XML）+ SMTP 转发，支持 QQ/163/126 多邮箱、链接型发票下载、抬头白名单与定时无人值守 |
| [wb-token-analyzer](./skills/wb-token-analyzer/) | WorkBuddy Token/Credit 使用量分析：按天/模型汇总、Top N 消耗任务排名、6 类优化建议、自定义模型支持、Neon Dashboard 可视化报告 |
| [xhs-image-note-release](./skills/xhs-image-note-release/) | 小红书图文笔记自动发布：ego-browser 驱动全流程，CDP 批量上传图片，穿透 closed Shadow DOM 调用 `_onPublish()` 发布 |
| [text-humanize](./skills/text-humanize/) | 中英文清晰表达与风格润色：改善冗余、结构、语气、节奏与排版，保留事实、引用及必要披露；不判断作者来源或以规避检测为目标（v1.5.0） |
| [zhihu-yanghao](./skills/zhihu-yanghao/) | 知乎养号：三线选题模型 + 每日1回答（写→发布→折叠验证）+ 点赞互动（计数差值自校正防误 toggle），依赖 ego-browser |
| [imagegen-batch](./skills/imagegen-batch/) | 批量生图：防同名覆盖 + 量水印而非猜 + 相框感后期加白边 + 人物「标识包」防塌脸；附 `白纸速写`/`水墨文艺风` 两套命名风格配方 |

## Quick Start

每个 skill 独立可用，详见各自目录下的 `SKILL.md`。

```bash
# 克隆本仓库
git clone https://github.com/Songhonglei/better-office-work-flow.git

# 将需要的 skill 复制到你的 agent skills 目录
cp -r skills/invoice-auto-forward ~/.workbuddy/skills/
cp -r skills/wb-token-analyzer ~/.workbuddy/skills/
cp -r skills/xhs-image-note-release ~/.workbuddy/skills/
cp -r skills/text-humanize ~/.workbuddy/skills/
cp -r skills/zhihu-yanghao ~/.workbuddy/skills/
cp -r skills/imagegen-batch ~/.workbuddy/skills/
cp -r skills/macos-power-control ~/.workbuddy/skills/
# 或 ~/.claude/skills/ / ~/.cursor/skills/ 等

# QQ 邮箱管理依赖真实 Codex CLI，复制完整技能目录
mkdir -p ~/.agents/skills
cp -r skills/qq-mail-manage ~/.agents/skills/
```

## Install via Agent Platforms

| Platform | Install |
|---|---|
| Codex | Manual: copy to `~/.agents/skills/`；QQ 邮箱首次使用需运行 onboard |
| OpenClaw | `clawhub install <skill-name>` |
| Claude Code | Manual: copy to `~/.claude/skills/` |
| Cursor | Manual: copy to `.cursor/skills/` |
| WorkBuddy | Manual: copy to `~/.workbuddy/skills/` |

## License

MIT (see [LICENSE](./LICENSE))

## Author

Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
