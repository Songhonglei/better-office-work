# Better Office Work

> AI 驱动的办公提效仓库 —— **Skills** 让你的 Agent 会干活，**Tools** 让你自己用得爽，**Small Joys** 给工作添点小乐趣。
>
> 覆盖发票处理、Token 用量分析、小红书发布、文本润色等高频办公场景，也收集皮肤、虚拟宠物、放松小游戏和趣味插件。

## Small Joys · 工作小乐趣

[smalljoys](./smalljoys/) 收集工作间隙的小乐趣：换个皮肤、养只宠物、玩一局小游戏，或装个好玩的小插件。

首批收录自制虚拟宠物，提供动画预览、完整精灵图和独立素材包。前往 [宠物小窝](./smalljoys/pets/) 挑一只。

## Tools

| Tool | Description |
|---|---|
| [Pomodoro Timer](./tools/Pomodoro%20Timer/) | 星环番茄钟：星空/破晓双主题、艺术椭圆进度环、瀑布背景、打断追踪、完成彩蛋；提供 [GitHub Pages 在线版](https://songhonglei.github.io/better-office-work/)、macOS 原生 App 与单文件 HTML 三种形态 |

## Skills

| Skill | Description |
|---|---|
| [sms-agent-mail](./skills/sms-agent-mail/) | 手机短信邮件读取：原生邮箱工具或 Agently CLI，首次接入配置邮箱与 SIM/尾号，外置设置与凭据升级保留，附跨 Agent 端到端验收（v1.2.0） |
| [qq-mail-manage](./skills/qq-mail-manage/) | QQ 邮箱管理：Python HTTP 直连无需 Codex，兼容 Codex OAuth；支持现代无初始化 MCP、账号与权限隔离、附件 CLI、发送及确认后移至垃圾箱；可审计核验兼容及中断恢复（v1.5.1） |
| [macos-power-control](./skills/macos-power-control/) | macOS 合盖与电源设置：一句话需求解析，设置前确认，区分电池/接电、临时防休眠与持久策略，附验证和恢复流程 |
| [invoice-auto-forward](./skills/invoice-auto-forward/) | 邮箱发票自动转发：IMAP 扫描 + 发票解析（PDF/OFD/XML）+ SMTP 转发，支持 QQ/163/126 多邮箱、链接型发票下载、抬头白名单与定时无人值守 |
| [wb-token-analyzer](./skills/wb-token-analyzer/) | WorkBuddy Token/Credit 使用量分析：按天/模型汇总、Top N 消耗任务排名、6 类优化建议、自定义模型支持、Neon Dashboard 可视化报告 |
| [xhs-image-note-release](./skills/xhs-image-note-release/) | 小红书图文笔记自动发布：ego-browser 驱动全流程，CDP 批量上传图片，穿透 closed Shadow DOM 调用 `_onPublish()` 发布 |
| [text-humanize](./skills/text-humanize/) | 中英文清晰表达与风格润色：改善冗余、结构、语气、节奏与排版，保留事实、引用及必要披露；不判断作者来源或以规避检测为目标（v1.5.0） |
| [zhihu-yanghao](./skills/zhihu-yanghao/) | 知乎养号：三线选题模型 + 每日1回答（写→发布→折叠验证）+ 点赞互动（计数差值自校正防误 toggle），依赖 ego-browser |
| [imagegen-batch](./skills/imagegen-batch/) | 批量生图：防同名覆盖 + 量水印而非猜 + 相框感后期加白边 + 人物「标识包」防塌脸；附 `白纸速写`/`水墨文艺风` 两套命名风格配方 |
| [mp-article-to-xhs](./skills/mp-article-to-xhs/) | 公众号长文转小红书图文：三条选题路径（URL/标题/热度候选）+ 配图滚动懒加载硬校验一张不漏 + 水印自动裁 + 8 套字体方案 + 默认只推草稿箱，发过的自动跳过（v1.3.0） |

## Quick Start

每个 skill 独立可用，详见各自目录下的 `SKILL.md`。

```bash
# 克隆本仓库
git clone https://github.com/Songhonglei/better-office-work.git

# 将需要的 skill 复制到你的 agent skills 目录
cp -r skills/invoice-auto-forward ~/.workbuddy/skills/
cp -r skills/wb-token-analyzer ~/.workbuddy/skills/
cp -r skills/xhs-image-note-release ~/.workbuddy/skills/
cp -r skills/text-humanize ~/.workbuddy/skills/
cp -r skills/zhihu-yanghao ~/.workbuddy/skills/
cp -r skills/imagegen-batch ~/.workbuddy/skills/
cp -r skills/macos-power-control ~/.workbuddy/skills/
cp -r skills/mp-article-to-xhs ~/.workbuddy/skills/
# 公众号转小红书依赖 ego-browser 与 xhs-image-note-release，装完跑自检：
python3 ~/.workbuddy/skills/mp-article-to-xhs/scripts/doctor.py
# 短信邮件助手用受限安装器保护外置设置，首次使用按 README 完成 onboarding
python3 skills/sms-agent-mail/scripts/install.py --host codex
# WorkBuddy 使用 --host workbuddy；其他 Agent 使用 --host custom --skills-dir <已确认的技能目录>
# 或 ~/.claude/skills/ / ~/.cursor/skills/ 等

# QQ 邮箱管理依赖真实 Codex CLI，复制完整技能目录
mkdir -p ~/.agents/skills
cp -r skills/qq-mail-manage ~/.agents/skills/
```

Tools 无需安装，直接使用：

- **Pomodoro Timer**：浏览器打开 [在线版](https://songhonglei.github.io/better-office-work/)，或把 `tools/Pomodoro Timer/dist/番茄钟.app` 拷贝到「应用程序」；也可在仓库内 `./tools/Pomodoro\ Timer/build.sh` 重新构建。

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
