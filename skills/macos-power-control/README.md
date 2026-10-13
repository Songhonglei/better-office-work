# macOS 合盖与电源设置

通过一句话需求查询或调整 Mac 电源行为，先展示具体方案，取得用户确认后再设置。

## 能做什么

- 分别处理系统空闲睡眠、屏幕熄灭、合盖运行和电池/接电策略。
- 按需求选择临时 `caffeinate` 会话或持久 `pmset` 设置。
- 保存原值，提供验证与恢复方法；管理员密码由用户在本机输入。

普通防休眠不保证合盖后仍运行。无外接屏或电池供电的合盖需求，需要核实机器和可用工具支持，实际合盖效果单独验证。

## 安装到 Codex

```bash
git clone https://github.com/Songhonglei/better-office-work-flow.git
mkdir -p ~/.codex/skills
cp -R better-office-work-flow/skills/macos-power-control ~/.codex/skills/
```

已有同名技能时先备份并比较差异，再决定是否更新。其他支持 Agent Skills 的工具可将该目录复制到其技能目录。

## 使用

例如对 Agent 说：

- “接电时电脑不休眠，屏幕可以熄灭。”
- “下载期间保持清醒两小时，电池和接电都生效。”
- “合盖后继续跑任务，先看看我的机器能不能做到。”
- “恢复刚才改过的电源设置。”

也可显式调用 `$macos-power-control`。Agent 先检查目标 Mac、显示方案，再等待确认；没有本机访问能力时提供手动操作与回查步骤。

## 环境要求

查询和设置在目标 Mac 上执行，使用 macOS 自带命令，无第三方包依赖。持久设置通常需要管理员认证。临时防休眠会话在进程结束或重启后失效；技能不会自动添加开机启动项。

详细规则见 [SKILL.md](./SKILL.md)，版本记录见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证与作者

MIT，见 [LICENSE](./LICENSE)。Evan Song · [GitHub](https://github.com/Songhonglei)。

本技能是 [Better Office Work Flow](https://github.com/Songhonglei/better-office-work-flow) 的一员。
