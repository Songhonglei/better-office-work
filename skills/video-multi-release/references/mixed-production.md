# 自动素材、混剪与交付检查

## 一次性本机配置

先盘点真实文件与运行节点；UI JSON 只供界面编辑，API 调用必须使用 API prompt JSON。

```bash
python3 scripts/comfy_assets.py inspect --root /path/to/ComfyUI \
  --workflows /path/to/api-workflows --out /path/to/comfy-inventory.json
```

盘点包括模型文件路径／大小、用户工作流及节点、在线节点可用性。文件存在不等于硬件适用、
视频模型已安装或视觉质量通过。检查额外模型目录时，另加实际目录，不扫描依赖缓存或整个 Home。

本机数据配置：`${WB_SKILLS_DATA:-~/space/skills-data}/video-multi-release/local-comfy.json`。
它与 Skill 分开保存；无密钥，可按本机路径维护：

```json
{
  "url": "http://127.0.0.1:8188",
  "comfy_root": "/path/to/ComfyUI",
  "raster_python": "/path/to/python-with-Pillow",
  "profiles": {
    "my-image": {
      "workflow": "/path/to/t2i.api.json",
      "output_node": "8",
      "output_kind": "image",
      "bindings": {
        "prompt": ["4", "prompt"],
        "seed": ["6", "seed"],
        "steps": ["6", "steps"]
      },
      "values": {"steps": 8}
    }
  }
}
```

bindings 是明确的 `[节点ID, 输入名]`，不能猜测或把正向提示改进负向输入。
现有本机 Qwen profiles：`qwen-q4-t2i`、`qwen-q6-t2i`，引用已有工作流，不携带权重。
实际检查记录在工作区 `artifacts/comfy-inventory.json`；该报告是时间点快照。
当前本机只有 Qwen-Image 2.1 图像模型，没有已验证的视频模型。

ComfyUI 不在线时脚本报错，不自动启动／停止其他模型。本机可先看 `qwenctl status`；
全部停止时使用 `qwenctl start image`。沿用现有 CPU FP32 VAE 的启动配置，不能为此任务升级 ComfyUI。

## 输入与制作

```json
{
  "segments": [
    {
      "id": "s01",
      "text": "雨后，庭院的颜色变得更加清晰。",
      "lines": ["雨后的庭院", "一盏清茶"],
      "visual": {
        "type": "card",
        "generate": {
          "profile": "qwen-q4-t2i",
          "prompt": "A quiet garden after rain, a teapot on a wooden table, no text",
          "seed": 20261110
        }
      }
    },
    {
      "id": "s02",
      "text": "镜头记录细节，字幕说明内容。",
      "visual": {
        "type": "video",
        "source": "assets/garden.mp4",
        "short": "loop",
        "fit": "cover",
        "source_offset": 0
      }
    }
  ]
}
```

`id` 必须唯一，只含字母、数字、下划线、连字符。

| 字段 | 行为 |
|---|---|
| 缺省 visual / `type: card` | 保留卡片排版；背景取旧 `image`、`visual.source` 或生成结果 |
| `type: image` | 直接使用图片，不叠原有卡片大字；完整字幕仍会叠加 |
| `type: video` | 读取视频；原视频声音默认丢弃，人声来自 voice，BGM 独立指定 |
| `visual.source` | 本地已有素材，路径相对于项目目录 |
| `visual.card` | 可指定已做好的卡片路径（跳过 cards 阶段时使用） |
| `visual.generate` | 自动运行指定 Comfy profile／API workflow，结果写入素材清单 |
| `visual.short` | 视频短于旁白时：`loop` 循环（默认）、`freeze` 末帧停留、`error` 报错 |
| `visual.fit` | `cover` 裁切填满或 `contain` 完整显示并补底色；卡片默认 contain，其余默认 cover |
| `visual.source_offset` | 从源视频的指定秒数开始 |

旧 `--images` 目录模式仍可用；混剪建议用段落显式路径，避免顺序歧义。

```bash
python3 scripts/produce.py --project /path/to/project --preset male-narrative
# 不调用 TTS，使用已有 voice/<id>.mp3；也可不提供 BGM：
python3 scripts/produce.py --project /path/to/project --use-existing-voice
# 指定音乐、输出、交付目标时长：
python3 scripts/produce.py --project /path/to/project --bgm /path/to/music.mp3 \
  --width 1080 --height 1920 --target 60 --target-tolerance 1
```

顺序：assets → voice → cards → render → mix → subtitles → qa。
图片和视频按旁白真实时长对齐。新混剪使用 FFmpeg 规范化片段和硬切；卡片原有字体、图片排版可复用，
不承诺复制旧 HyperFrames 的进退场动画。未启用混剪的旧 `rebuild.sh` 仍使用 HyperFrames 动画。
`rebuild.sh` 遇到混剪／生成字段自动转新路径并复用已有配音，也可用 `RENDER_MODE=mixed` 显式指定。
新入口默认只有人声；旧 rebuild 的 BGM 默认值保持原行为。

### 自定义视频工作流及参考图

在 profile 中使用 `output_kind: video` 并指定返回视频文件的 `output_node`。
支持历史输出 `videos`／`gifs`／`images` 中的 MP4、MOV、WebM、MKV，要求正好一个选定类型输出。
没有安装节点、模型或输出为图片时，视频场景明确失败，不能静默改为图片。
工作流提供者负责尺寸、帧数、模型及输出格式；绑定按该工作流实际输入填写。

`generate` 可覆盖 `workflow`、`output_node`、`output_kind`、`bindings`、`values`。
如果工作流含 LoadImage，增加 `bindings.reference: ["节点ID", "image"]`，再指定
`upload_images: {"reference": "images/reference.png"}`。上传按文件内容命名，改变参考图会改变缓存标识。
只调用本地生成节点；发现 `api_node` 会拒绝，不自动转付费服务。

## 缓存、恢复与状态

- `asset_manifest.json`：段落到生成任务／素材的映射，含工作流、参数、任务 ID、输出哈希与本地计算说明。
- `.cache/comfy/`：提交前保存回执；超时后重新运行查询同一任务。缓存损坏先尝试下载同一输出。
- `voice/.tts-cache.json`：文案、音色、语速、模型与音频哈希匹配时跳过 TTS；修改一段只合成该段。
- `assets/.cards-cache.json` / `.cache/scenes/`：卡片与规范化镜头缓存，修改一个镜头不会重编码其他镜头。
- `production.json` / `production-events.jsonl`：每阶段当前状态与追加历史。
- `out/publish_log.jsonl`：发布入口记录每个平台的模式、状态、退出码、URL、实际上传文件哈希。

```bash
python3 scripts/produce.py --project /path/to/project --status
python3 scripts/produce.py --project /path/to/project --from-stage render --use-existing-voice
python3 scripts/tts.py --script voice_script.json --out-dir voice --preset male-narrative --segment-id s02
```

从某阶段继续时，其前置素材必须仍与当前文案匹配。更改文案通常直接重新跑完整入口，让缓存判定依赖。
提交响应丢失时回执为 `submission_unknown`；先查服务器历史／队列，禁止自动再次 POST。
已确认失败或确认服务器没有接收后，才由用户显式决定使用 `--resubmit`。
进程锁防止同一个项目的入口并发运行。不同项目各有状态，不承诺跨项目去重。

## 字幕与质量检查

默认把完整旁白分成短句，按字数分配到该段音频时长，烧录到画面底部并输出 SRT。
也可在段落写 `subtitles: [{"start":0,"end":1.5,"text":"句子"}, ...]`，时间相对本段人声起点。
自定义字幕必须覆盖完整旁白与至少 98% 人声时间。字幕是完整旁白；`lines` 仍是卡片金句，两者不同。

```bash
python3 scripts/quality_check.py --video out/final.mp4 --timeline timeline.json \
  --report out/quality_report.json
```

| 检查 | 默认判据与边界 |
|---|---|
| 时长 | 对照时间轴与音视频流，允许帧率量化／编码误差；可另设目标时长 |
| 黑帧 | 画面约 98% 接近黑色并持续 ≥0.35 秒；暗场可能需要人工判读 |
| 静音 | -45dB 以下持续 ≥0.4 秒，检查是否落在人声区间；单独检查配音源，防止 BGM 掩盖缺声 |
| 字幕覆盖 | 每段完整文字、时间覆盖 ≥98%、时间与边界合法、每条字幕中点与实际叠加像素比对 |

字幕像素核验需要 `.cache/qa` 中的干净参考视频及字幕 PNG；检查通过前不要删除。
一条字幕只检查中点，不等于逐帧 OCR；无语音识别，不能保证音频说的就是脚本文字，
也不能发现被人工移出时间轴的语义问题。视觉检查图和人工全片复核仍保留。
静音算法允许少量停顿；不会断言每一段声音都是正确语音。检查失败返回非零并写 blockers。

`VERIFY=0` 仅跳过旧检查图。CLI 的 `--allow-no-subtitles` 是给明确无字幕交付的人工例外，
默认制作入口没有这个开关；报告会写明字幕未要求，不能冒充字幕检查通过。

## 发布与回退

继续使用原 `release.sh` 和原三平台脚本。存在质量报告时必须通过且哈希匹配；
新 production 项目没有质量报告也会被阻止。独立旧视频仍可按原方式发布。
体积压缩、stage／draft／publish、平台确认与人工验证行为保持。
质检通过只允许进入原有发布流程，不代表用户已授权发布。

回退前保留新项目与数据目录；恢复升级前的 Skill 快照即可，模型、ComfyUI 与三平台账户未被迁移。
