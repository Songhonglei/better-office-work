# lianhuanhua-book v1.5.2

把故事做成可翻读的系列插图与图文连环画。默认成人和儿童均可阅读的通用故事结构，面向传统白描及其他原创画风。

## 快速开始

```bash
python3 pipeline/init_project.py /path/to/new-book
cd /path/to/new-book
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp stories/_template.json stories/example-story.json
cp stories/_series.example.json stories/_series.json
# 按故事补全分镜
python pipeline/make_prompts.py --slug example-story
# 生成图片后逐页导入
python pipeline/progress.py --slug example-story import --page 0 --file cover.png --backend imagegen
python pipeline/progress.py --slug example-story status
# 看图逐项写入审核记录后选用
python pipeline/progress.py --slug example-story checklist --page 0
python pipeline/progress.py --slug example-story approve --page 0 --note "画面复核通过" --checks-file review-00.json
python pipeline/verify.py --slug example-story --require-approved
python pipeline/build_site.py --require-approved
./serve.sh 8788
```

ComfyUI 本地适配见 [references/comfyui.md](references/comfyui.md)。已有模型和工作流优先，不要求额外安装模型。另支持 ImageGen 和其他模型导入。

新模板采用 3:2 横版。默认从 1248×832 原图等比例输出 1536×1024，并在导入时检查原图比例。旧作品可继续按原有画幅验收。

已有 Qwen-Image-Local Q4/Q6 及对应 GGUF、文本编码器、VAE 的环境，可直接使用内置预设：

```bash
python pipeline/comfyui.py --slug example-story --page 0 --preset qwen-q4 --dry-run
python pipeline/comfyui.py --slug example-story --page 0 --preset qwen-q4 --probe
# 服务已就绪时再生成
python pipeline/comfyui.py --slug example-story --page 0 --preset qwen-q4
```

## v1.1–v1.3

- 严格分镜与图片验收，缺图、错尺寸、多余页码、损坏文件拒绝交付；建站失败保留旧站。
- 每页原图、成品、提示词及上下文指纹、模型来源、审核状态独立归档，支持续作和回退。
- 六种内置风格、自定义角色参考、可配置画幅及压缩。
- ComfyUI API 格式工作流、干跑、单页或串行批量、任务 ID 持久化和恢复。
- 静态资源真实内容哈希，完整构建避免旧页面残留。

详细工作流程见 [SKILL.md](SKILL.md)，完整接口和迁移见 [references/pipeline.md](references/pipeline.md)。原始 29 条实测经验保留于 [references/prompt-playbook.md](references/prompt-playbook.md)。

细节规则和验收记录见 [逐页跟进](references/continuity.md)。整册审图、批注与前后稿比较见 [审图工作台](references/review-workbench.md)，其余计划见 [路线图](ROADMAP.md)。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用合成图片和模拟 ComfyUI 服务，不消耗生成额度。真实模型质量需要独立样张验证。

本阶段已在完整画册的副本上通过浏览器检查逐页批注、跨页道具和新旧稿切换。单页返工实测覆盖优先级、超时后接回同一 ComfyUI 任务、仅归档指定页候选及阅读稿保留。整页候选仍需检查构图是否漂移。

v1.5.2 已在 [390 px 手机视口](references/mobile-local-check.md) 实测批注圈选、ComfyUI Q6 局部修订、候选直达和正式单页替换。

MIT © 2026 Evan Song
