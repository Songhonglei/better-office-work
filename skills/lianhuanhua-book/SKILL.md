---
name: lianhuanhua-book
description: 将故事改编成可翻读的连环画、图文书和系列插图。支持分镜、角色定妆、ImageGen 或本机 ComfyUI 逐页出图、跨页细节核对、批注、候选稿对照、单页返工续跑和静态阅读器。用户要求小人书、故事插图、连续角色一致性，或审图与修订既有连环画时使用。
---

# 连环画故事书 v1.5.2

## 工作流程

1. 确定作品范围、输出形式、画风、时代和生成方式；默认成书 12–20 页（含封面），不强迫单张插图任务进入整本流程。保留用户故事的情节和风格意图。
2. 初始化独立项目，避免覆盖已有素材。使用 `python3 <skill>/pipeline/init_project.py <新目录>`，在新目录执行后续命令。使用独立 Python 3 虚拟环境及 `requirements.txt` 安装 Pillow；已有兼容环境可直接复用。
3. 从 `stories/_template.json` 建分镜。传统小人书默认 3:2 横版，生成 1248×832，交付 1536×1024，启用 `output.fit: "strict"`。用户指定其他版式时，让生成与交付比例一致。每页显式指定 `who`，纯景物用空数组。角色锚点写明名字、年龄、脸型、衣饰和视觉差异，通过角色 `reference` 指向 `assets/images/<slug>/cast/` 下的参考图。见 [故事结构](references/story-schema.md)。
4. 选择画风，先锁定定妆与反复出现的道具或场景。写入 `continuity`（共用细节及出现页码）、`checks`（单页易错点）和 `samples`（优先试画的页）。优先审封面、关键手势和双人镜头中实际存在的高风险画面，随后按情节分段出图。见 [逐页跟进](references/continuity.md)。
5. 生成提示词：`python pipeline/make_prompts.py --slug <slug>`；支持 `--page N`。输出 `prompts/NN.txt`。
6. 逐页出图并归档：
   - ImageGen：用本页提示词和该页角色定妆照生成，导出到项目，然后运行 `python pipeline/progress.py --slug <slug> import --page N --file <图片> --backend imagegen`。
   - ComfyUI：已有本机 Qwen-Image-Local 时用 `--preset qwen-q4` / `qwen-q6`，自动选择 0–3 张角色参考图。`--samples` 先做样张，`--pages` 按段串行，`--all` 补缺。使用前干跑或只读探测。已完成的页面可用 `comfyui_edit.py` 局部修订，或以 `--candidate` 提交整页候选。见 [ComfyUI 适配](references/comfyui.md)。
   - 其他模型：导入实际生成的图，记录模型名称；旧版编号原图可用 `post_process.py` 导入。
7. 出一页、审一页。用 `progress.py ... checklist --page N` 对照画面和邻页，记录每项可见证据。新项目通过 `approve --checks-file` 提交全部通过项，返工通过 `reject` 保留问题。核对人物视线对象、肢体方向、道具支点和门槛等空间关系。未观察到的细节记为待核，不因程序校验通过而放行。
   - 整册审图时可开 [工作台](references/review-workbench.md)。首屏导航可直达待审候选和返工队列。点批注选择局部修订或整页重画，局部任务圈选编辑范围；完成后可直接并排看原稿和候选的同一处。待跑任务按优先级排序，ComfyUI 超时后从原任务继续。正式出版前另行选稿和验收。
8. 用户追加要求时，更新对应的共用或单页规则并用 `checklist` 定位受影响页。需要保留机位、背景和人物姿态的细节走 `comfyui_edit.py` 蒙版修订。需要重新安排整页构图或动作链的批注可转返工队列。归档候选后并排复审，检查目标细节和邻页衔接，通过后用 `approve --version <候选> --select` 切换；正式阅读稿由重新建站更新。续作使用 `status` 和对应生成器的 `--resume`。
9. 成书执行 `python pipeline/verify.py --slug <slug> --require-approved`；执行 `python pipeline/build_site.py --require-approved`，成功后使用 `./serve.sh 8788` 本地预览。仅用户明确要求时再发布静态站。程序验收与视觉验收是两回事。

## 文案排版

- 封面通常只排插图和书名，旁白默认隐藏。正文写成完整段落并左对齐，文字区的左右边缘分别从插图边缘向内两个汉字宽，随阅读宽度自然折行。正文内容宜在常规桌面宽度自然显示超过两行。偏短时补充本页动作、环境、人物反应或承接下一页的线索，保留画面事实和故事节奏。
- 书架和阅读页保留作品名称、真实署名与必要来源。省略工具、模型和创作过程署名，除非用户指定展示。交付前在桌面和窄屏各核对排版与翻页。

## 出图要点

- 角色名称与锚点一一对应；两人以上写出年龄、脸型、身高、服装等明显区别。
- 参考图按当页角色选择；纯景物无需人物参考。优先使用定妆照，与画面构图参考分开。
- 动作可画、视线有明确对象、物件数量与持有者清楚、明暗与景别有根据；不强行沿用古代场景或主角素衣限制。
- 横版先审一张有角色参考的样张和一张空镜，确认原图比例与交付一致。检查两侧是否有场景信息和空间层次，避免人物压在画面中央而左右出现成片空带。`strict` 会拒绝比例不符的原图。旧版的方形原图可继续用于旧版画册，横版重制时按原生横幅逐页出图。
- 保留原始生成结果与历史版本，不为小瑕疵重画整本；只重新生成需要修改的页面。
- ComfyUI 保持串行生成。等待出图时可以审核其他已完成页，避免让检查占用生成时间。
- 超时先按已保存的 ComfyUI 编号查看队列或历史并恢复。生成完成、画面审过、已更新阅读稿是三个验收点，分别记录。

## 参考

- [故事结构与规格](references/story-schema.md)
- [逐页跟进与修订](references/continuity.md)
- [整册审图工作台](references/review-workbench.md)
- [出图经验](references/prompt-playbook.md)
- [流水线、续作、发布](references/pipeline.md)
- [本地 ComfyUI](references/comfyui.md)
