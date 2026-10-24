# 下载、迁移与安装

下载整个 `skills/sms-agent-mail` 目录。Code ZIP 包含仓库所有文件，解压后进入此子目录；或使用 Git 克隆。只有 SKILL.md 不足以执行接入和升级脚本。

```bash
python3 scripts/install.py --host codex
```

WorkBuddy 用 `--host workbuddy`；自定义宿主用 `--host custom --skills-dir /confirmed/skills/path`。目标版本路径不同先核实再传 --skills-dir，不能猜测 Windows 的技能目录。Codex 用户目录 `.agents/skills` 依据 [OpenAI 官方文档](https://learn.chatgpt.com/docs/build-skills)；WorkBuddy 默认目录来自本机既有 `.workbuddy/skills` 结构，不代表所有系统已测试。

安装器只拷贝固定清单中的文档、脚本和离线测试，先更新资源，最后更新 SKILL.md；逐文件原子替换。发生错误返回非零，可在排除路径/权限问题后重新运行同一版本。它不删除未知旧文件，不能把安装成功等同于内容完全清理或降级成功。不要在已经安装的同一目录对自身运行安装器；升级从新下载目录执行。

默认数据在 `~/.local/share/sms-agent-mail`。自定义数据目录时安装和之后的 onboard 命令继续加原 `--data-dir`。不复制旧设备钥匙串、Cookie、token 或整份宿主配置；安装本 Skill 不自动向宿主注册 MCP。

安装后重新加载或重启宿主，确认能选择 sms-agent-mail；然后执行 [首次接入](storage.md)。手机已经转发到同一个目标邮箱时，不必因电脑变化重配手机；换目标邮箱时由用户另行配置转发。

对目标 Agent 可以说：

> 下载完整 sms-agent-mail，使用内置安装器安装或升级，不写外置数据和凭据目录。首次接入先告知存储位置、确认邮箱与 SIM/尾号及来源，再引导授权和真实验收。不要把示例值当成我的账号。
