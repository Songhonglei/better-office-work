# 本地 ComfyUI 适配

依赖 ComfyUI 已运行并安装所需模型、节点，默认 http://127.0.0.1:8188。采用本机 API /system_stats、/upload/image、/prompt、/history/{id}、/view。参考官方 [API workflow 示例](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py)。不安装或自动启动模型。

## 1. 准备工作流

在 ComfyUI 用已安装的 checkpoint/工作流生成一张样图；从菜单导出 API 格式 JSON（节点 ID 到 class_type 和 inputs 的映射，而不是画布普通 JSON）。将实际对应节点的输入值替换为以下完整字符串：

| 占位符 | 实际值 |
|---|---|
| `{{prompt}}` | 本页完整正向提示词（必须存在） |
| `{{negative}}` | 故事自定义负面提示词，可选 |
| `{{seed}}` | 基础 seed + 页号，数值 |
| `{{width}}` / `{{height}}` | 输出画幅，数值 |
| `{{output_prefix}}` | 按书和页区分的输出名称 |
| `{{reference_1}}` / `{{reference_2}}` / `{{reference_3}}` | 该页已声明 reference 的角色图，按 cast 顺序；调用 upload/image 后填入 LoadImage 输入 |

工作流必须自行包含有效的参考图条件节点（例如已测试过的模型专用编辑或参考条件图节点）。仅上传人物图并不能自动保证模型使用参考图。text-to-image 工作流不应放 reference 占位符；多人物与纯风景场景可选择不同工作流。请使用 batch_size=1 并选择实际 SaveImage 输出节点。示例 workflows/example.api.json 仅说明格式，不假定你安装了其中的 checkpoint。

## 2. 干跑与单页

针对 Qwen-Image-Local 的现有 Q4_K_M 和 Q6_K 量化工作流，内置八个 API 预设（每种 0、1、2、3 张人物参考图），从已安装的节点及工作流配置转换而来。无需手工准备 API 导出文件：

```bash
python pipeline/comfyui.py --slug my-book --page 0 --preset qwen-q4 --dry-run
python pipeline/comfyui.py --slug my-book --page 0 --preset qwen-q4 --probe
python pipeline/comfyui.py --slug my-book --page 0 --preset qwen-q4
python pipeline/comfyui.py --slug my-book --page 1 --preset qwen-q6
```

预设根据该页角色声明的 reference 自动选择工作流，输出节点为 8，参考图按 cast 顺序与角色名字绑定。新模板的 `output.fit: "strict"` 让有参考图和无参考图的页都按 `generation` 的宽高采样。人物参考由视觉编码器读取，独立采样画布保持分镜指定的横幅。生成宽和高须为 32 的倍数。旧的补边模式仍沿用 992 的参考分辨率和第一张参考图的比例。

如仅需验证接口，可在新项目中复制 `stories/_smoke.example.json` 为 `stories/smoke-book.json`，按上方命令将 slug 改为 smoke-book，先测试第 0 页。它是开发用两页草稿，并非完整成书。

本机已有 qwenctl 时，先用 `qwenctl status` 看服务情况。全部受管模型都停止时可用 `qwenctl start image`。有其他模型在运行时，由用户决定是否切换。横版先按新模板用 Q4 跑 1248×832 的单页，检查出图尺寸、左右构图及手部动作，再逐页推进。自定义工作流需要把采样画布绑定实际宽高，严格模式会检查下载原图的比例。

```bash
python pipeline/comfyui.py --slug my-book --page 0 --workflow workflows/my.api.json --output-node 9 --dry-run
python pipeline/comfyui.py --slug my-book --page 0 --workflow workflows/my.api.json --output-node 9
```

dry-run 只解析工作流和校验占位符。probe 从运行中的服务读取节点定义，检查模型及采样器等候选值和数值范围。完整的工作流校验由 ComfyUI 在提交时执行。probe 不上传参考图或排队。自定义工作流须填写实际输出节点 ID。端口非 8188 时传 --server http://127.0.0.1:PORT。

## 3. 批量与续作

```bash
python pipeline/comfyui.py --slug my-book --preset qwen-q4 --samples
python pipeline/comfyui.py --slug my-book --preset qwen-q4 --pages 4 5 6
python pipeline/comfyui.py --slug my-book --all --workflow workflows/my.api.json --output-node 9
# 提交后超时、暂停或电脑休眠时
python pipeline/comfyui.py --slug my-book --page 3 --workflow workflows/my.api.json --output-node 9 --resume
```

批量只处理缺失页，逐页串行，跳过已有图与尚未恢复的任务。整页返工用 `--page N --candidate`，在 `progress checklist` 中可找到候选。任务提交前记录 UUID prompt ID、工作流指纹、seed、参考图槽及上下文；接收输出时记录服务器给出的排队和执行时间。`--resume` 只查原任务 ID。旧服务若自行生成不同 ID，则在收到响应后记录服务器 ID；响应丢失时应先检查队列。任务已确认失败且服务器不再运行时，用 `progress forget-job --page N --note "原因"` 保留异常记录并允许重试。

## 4. 局部修订

按归档原图的尺寸画灰度 PNG 蒙版，白色表示编辑，黑色表示保留。工具在蒙版外取少量上下文，裁图后交给 ComfyUI，随后合回原来的画幅。`--reference` 可补一张匹配帽沿等局部的参考裁图。`--check` 可重复指定本页的视觉规则，自动加入修订提示。例如：

```bash
python pipeline/comfyui_edit.py --slug my-book --page 3 --preset qwen-q6 \
  --from-version <id> --mask umbrella-mask.png --check umbrella \
  --instruction '让伞尖落在石板，保持伞杆与弯柄相连' --probe
# 实际运行时移除 --probe。遇到超时，使用以下命令恢复同一次任务。
python pipeline/comfyui_edit.py --slug my-book --page 3 --resume
```

`--size` 控制工作图长边，默认 512。`--padding` 控制自动裁图的背景范围，或用 `--crop LEFT TOP RIGHT BOTTOM` 指定覆盖蒙版的原图坐标。运行会保存裁图、蒙版、工作流及模型结果，并验证合成原图的蒙版外像素一致。通过 `checklist` 审局部候选并选用。局部端点、手、眼等需要放大确认，符合像素边界仍可能画错。 [逐页跟进](continuity.md)

Apple Silicon 48GB：沿用已验证的本机模型，batch_size=1，先单页样图；不要同时启动高内存占用 LLM 和图像模型。分辨率以模型能力为准，生成与交付规格分开配置。不同工作流可能需要模型特定分辨率与参考图条件设计。本适配不自动修改现有 ComfyUI 工作流、模型或显存设置。
