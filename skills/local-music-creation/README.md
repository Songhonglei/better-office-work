# Local Music Creation · 本地音乐创作

在 Apple Silicon Mac 上调用独立的 YuE2 MLX 环境，按歌词与风格生成音乐，保存音频、ABC 乐谱和可复现结果。也支持制谱后渲染、回放、串行批量以及可选的转写、cover 和 RealAudio 对照。

**本 Skill 仅通过本 GitHub 仓库提供，未发布到 skillhub.cn 或 clawhub.ai。** 同步仓库不会自动更新已部署的模型或环境。

## 安装与调用

```sh
git clone https://github.com/Songhonglei/better-office-work.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R better-office-work/skills/local-music-creation "${CODEX_HOME:-$HOME/.codex}/skills/"
```

若目标目录已存在，先比较差异和备份，再决定更新，不直接覆盖现有 Skill。其他支持文件系统 Skills 的 Agent 可复制完整目录到其技能位置；这些宿主的自动发现和模型调用能力尚未逐一验证。

在 Agent 中使用：

> 使用 $local-music-creation，先检查本地环境，再按我的歌词和风格生成一首中文歌，保留音频、乐谱和结果。

Skill 是调用和迁移工具，模型权重及 Python 环境需单独准备。目标机器必须可执行本地命令；仅把目录复制到不连接该 Mac 的云端 Agent，不能直接调用 Mac 的 GPU。

## 配置

```sh
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/local-music-creation"
"$SKILL_DIR/scripts/music" init-config --root "$HOME/AI-Lab/YuE2-MLX"
"$SKILL_DIR/scripts/music" show-config
"$SKILL_DIR/scripts/music" preflight
"$SKILL_DIR/scripts/music" doctor
"$SKILL_DIR/scripts/music" test short --precision 8bit
```

默认配置位于 `${XDG_CONFIG_HOME:-$HOME/.config}/local-music-creation/config.json`。`init-config` 拒绝覆盖已有文件。也可用 `LOCAL_MUSIC_CONFIG` 或放在命令前的 `--config` 选择其他配置。

完整示例见 [config.example.json](assets/config.example.json)。源码、Python、模型、VAE、缓存、输出和可选环境路径均可配置；支持 `~`、环境变量、`{root}`、`{skill}` 及相对配置文件的路径。精度、内存预算、AC 电源要求、磁盘阈值和超时也由配置控制。不会读取或上传另一台电脑的私有配置。

默认使用 AR 8bit、NAR BF16、VAE FP32，串行离线生成；切换 AR 精度用 `--precision bf16`，修改本 Skill 的默认值用 `precision bf16`。这不修改原部署的 `settings.json`，也不自动下载、转换或替换模型。

## 迁移与能力边界

- 控制脚本仅使用 Python 3.9+ 标准库；MLX 环境使用 Python 3.12，核心依赖与源码固定在已验证基线。新 Mac 必须重新检查兼容性，不复制旧 `.venv`。
- 迁移步骤见 [migration.md](references/migration.md)：支持连接已有环境，或在新的独立目录执行显式 setup、按固定快照下载/复制权重、校验并整理独立 generator/VAE 目录。
- 转写、cover、RealAudio 使用单独 extras 环境和附加权重；附加模型及其许可不能视为与核心相同。版本清单和 SHA-256 清单均已附带，不包含实际模型文件。
- 每个任务创建新目录，保留输入、日志、资源和结果回执；不覆盖旧输出，不自动停止 Qwen/ComfyUI，不自动升级现有环境。
- ComfyUI 桥接属于后续独立任务；本 Skill 的成功不等于 ComfyUI 节点已联调通过。纯伴奏与 BPM 遵循属于软控制，不保证绝对无人声或严格速度。

原始验收机器为 M5 Pro、48 GiB、macOS 26.5.1。历史封装验收包含 8 个实际任务、17 项迁移/隔离检查和 13 场景请求试运行；既有 batch/cover/RealAudio 等产物另做了校验。这些历史记录不代表本次 GitHub 同步重跑了全部推理，也不代表第二台实体 Mac、所有 Agent 宿主或 ComfyUI 已验收。短测试故意限长，主观音乐质量仍需试听。

## 文档与许可

- [SKILL.md](SKILL.md)：Agent 入口和运行约束。
- [configuration.md](references/configuration.md)：配置字段与回执契约。
- [workflows.md](references/workflows.md)：生成、制谱、批量和评估命令。
- [provenance.md](references/provenance.md)：固定基线、上游问题和验证边界。

本仓库自有包装脚本与说明按仓库根目录 [MIT License](../../LICENSE) 提供。`assets/frozen/` 中随附的上游项目元数据和锁文件保留 [Apache-2.0 许可](assets/frozen/LICENSE)；推理引擎及模型遵循各自上游许可，不能将仓库的 MIT 许可推广到模型权重。
