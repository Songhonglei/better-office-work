---
name: video-multi-release
description: >
  口播视频的制作与多平台发布工具。用 Qwen TTS 生成有情感的中文配音（成熟女声/男声，
  支持语气指令），按配音时长自动生成卡片视频（音频驱动时间轴），混入背景音乐，
  然后发布到小红书、视频号、抖音三个渠道。支持 stage（只准备不提交）、draft（存草稿）、
  publish（直接发）三种模式。当用户要做口播视频、给卡片视频配音、把视频发到小红书/视频号/抖音时使用。
  前置依赖：ego-browser 已安装且目标平台已登录；ffmpeg；ffprobe。
version: 1.1.0
bins: [ffmpeg, ffprobe, python3, node, npm, npx]
metadata:
  openclaw:
    requires:
      env:
        - DASHSCOPE_API_KEY
    primaryEnv: DASHSCOPE_API_KEY
---

# video-multi-release

把「一组卡片 + 一段文案」变成「带配音的竖屏视频」，再发到视频号和抖音。

跟 `xhs-image-note-release` 的关系：那个管小红书图文/视频，这个管视频号 + 抖音。
两者共用卡片生成器，但发布流程完全不同，不要互相塞。

## 不适用场景

- **小红书图文笔记**（多图 + 文案）→ 用 `xhs-image-note-release`
- **纯图片轮播视频**（不需要配音、不需要卡片）→ ffmpeg 直接拼，没必要走这套
- **抖音要求全自动发布** → 做不到，短信验证绕不过；只能自动化到「填好停在发布前」

## 硬边界（先看这条）

**抖音不能全自动。** 点「发布」必然触发短信二次验证，是平台级真人校验，脚本绕不过去。
所以抖音默认 `MODE=stage`：把视频传好、标题描述话题填好，停在那里，最后一步由人完成。

**视频号和小红书可以全自动**，前提是已扫码登录。

小红书另有一处结构特殊的：发布按钮是 `<xhs-publish-btn>` Web Component，藏在 closed Shadow DOM 里，
常规点击全失效，只能调宿主元素上的 `_onPublish()` / `_onSave()`。脚本已处理。

## 三个平台的核心差异

| | 小红书 | 视频号 | 抖音 |
|---|---|---|---|
| 登录 | 扫码 | **微信扫码** | 扫码 |
| DOM 结构 | 普通 | **wujie 微前端（shadowRoot）** | 普通 |
| JS click 是否有效 | 是（**发布按钮除外，须调 `_onPublish()`**） | **否，必须 CDP 真实鼠标** | 是（但话题除外） |
| 标题上限 | 20 字 | 短标题 **16 字** | **30 字** |
| 描述上限 | 1000 字 | 1000 字 | 1000 字 |
| 话题机制 | 输入 `#` 选词条 | **输入 `#话题名` 自动标签化** | 输入 `#话题名` + **回车** |
| 封面 | 3:4 单张 | 3:4（默认首帧够用） | 竖 3:4 + 横 4:3 **双封面**（图层式编辑器，脚本不处理） |
| 草稿 | `_onSave()` | 「保存草稿」**云端可见** | 「暂存离开」**不可靠，等于没存** |
| 全自动 | 是 | 是 | **否，卡在短信验证** |

## 首次配置（onboard）

本 skill 不含任何密钥。API Key 只落在 skill 根目录的 `.env`（已被 `.gitignore` 忽略，不会同步出去）：

```bash
bash ~/.workbuddy/skills/video-multi-release/scripts/onboard.sh --verify
```

不带 `--key` 会交互输入（不回显）；`--verify` 会真调一次 TTS 验证 key 可用。

Key 在阿里云百炼控制台 → API-KEY 管理创建。读取优先级：
`环境变量 DASHSCOPE_API_KEY` > `skill根目录/.env`。两者都没有就报错并提示跑 onboard。

模型走 MaaS Token Plan 端点，`token-plan` 就是 `{WorkspaceId}`，不需要单独开通百炼账号。

## 快速开始

```bash
SKILL=~/.workbuddy/skills/video-multi-release

# 0) 批量生成卡片（引用 xhs-image-note-release 的生成器渲染）
#    背景/金句对齐方式三选一：segments[].image 字段 > --mapping JSON > --images 目录按 mtime 排序
python3 $SKILL/scripts/gen_cards.py \
  --script voice_script.json \
  --images images/ \
  --theme journal --tag "古人情话" --account "@雨夜心灯" \
  --out-dir assets

# 1) 生成配音（分段，按卡片对齐）
python3 $SKILL/scripts/tts.py \
  --script voice_script.json \
  --preset female \
  --out-dir audio/female

# 2) 生成音频驱动的时间轴
python3 $SKILL/scripts/build_composition.py \
  --script voice_script.json \
  --voice-dir audio/female \
  --pre 0.5 --gap 0.4 --tail 1.2

# 2) 一键重建：时间轴 + 内联 gsap + 渲染 + 混 BGM → out/final.mp4
#    （等于下面 3)(4) 两步；改了卡片或配音后重跑它即可，时间轴自动重算）
bash $SKILL/scripts/rebuild.sh /path/to/project
#    可选：BGM=/path/to.mp3 PRE=0.6 GAP=0.45 TAIL=1.5 bash rebuild.sh ...

# 3)（rebuild.sh 的分解视图）无声画面（HyperFrames 项目里）
npx hyperframes@0.9.1 render --output /tmp/silent.mp4

# 4)（rebuild.sh 的分解视图）混音成片
python3 $SKILL/scripts/mix_audio.py \
  --silent /tmp/silent.mp4 \
  --bgm assets/music/bgm.mp3 \
  --out out/final.mp4

# 5) 发布
PLATFORMS=xhs,channels,douyin \
VIDEO=$PWD/out/final.mp4 \
TITLE="四十岁以后，我不再跑那么快了" \
DESC="$(cat desc.txt)" \
TOPICS="人生感悟,人到中年,独处,读书" \
MODE=stage \
  bash $SKILL/scripts/release.sh
```

先跑 `MODE=stage` 确认内容无误，再跑 `MODE=publish`。

## 配音：音色预设

内置四套，都在 `scripts/tts.py` 的 `PRESETS` 里：

| preset | 音色 | 年龄/特质 | 适用 |
|---|---|---|---|
| `female` | 龙蝶霜鸾 `longdieshuangluan` | 40 岁 电台质感 | 哲思随笔、深夜电台感 |
| `female-warm` | 龙昕筝荷 `longxinzhenghe` | 42 岁 温柔坚韧 | 情感向、叙事 |
| `male` | 龙朗涟玥 `longlanglianyue` | 55 岁 浑厚沉稳 | 有声书感、沉稳讲述 |
| `male-narrative` | 龙荷松蕊 `longhesongrui` | 44 岁 叙事沉浸 | 讲故事 |

**模型只能用 `qwen-audio-3.0-tts-plus`。** 3.1 系列在 token-plan 端点返回 404 `Model not exist`。
音色必须属于该模型的基础音色，跨模型混用报 `[cosyvoice:]Engine error [411]`。

选音色别只看名字，用官方年龄 + 特质两列筛，`docs.bailian.console.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list`。
系统音色里女性最大只有 25-30 岁，要「岁月沉淀感」必须从 597 个基础音色里挑。

## 配音时长是怎么变成视频时长的

`build_composition.py` 读每段音频的真实时长，算出每张卡的 `data-start` / `data-duration`，
同时把这条时间轴落盘成 JSON（与 index.html 同目录）。
`mix_audio.py` 读的是**同一份**时间轴，所以音画不会各算一遍导致错位——这是配音视频最容易翻车的地方。

时间轴公式：

```
卡片 i 起点 = pre + Σ(前面各段音频时长) + i × gap
卡片 i 可见 = 音频i时长 + gap（最后一张再 + tail）
```

默认 `pre=0.5 gap=0.4 tail=1.2`。想更从容就调大 gap。

## 时长失控的头号原因

**`rate < 1.0` 再叠加指令里写「语速偏慢」，两者会叠加放大。**

实测同一句 30 字：

| 配置 | 时长 |
|---|---|
| rate 0.9 + 「语速偏慢」 | 10.34s |
| rate 1.0 + 「语速偏慢」 | 8.66s |
| rate 1.0 + 「语速自然」 | 9.07s |
| **rate 1.15 + 「语速自然」** | **7.68s** |

所以默认 `rate=1.12`，并且指令里**只说语气、不说快慢**。
6 段 150 字左右，配出来约 36-40 秒；想要 30 秒内必须砍字，不是调参数能解决的。

## 失败时怎么办

失败会打结构化块，照着 `what_now` 做：

```
=== FAILED ===
platform : 视频号
step     : upload
code     : E_UPLOAD_TIMEOUT
exit     : 30
message  : 视频上传超时（160 秒）
what_now :
  1. 检查文件是否可正常播放、体积是否过大
  2. 重跑一次；若反复卡在 0%，刷新页面后重新上传
space    : 12（页面已保留）
takeover : ego-browser nodejs -e "await claimTaskSpace(12)"
cleanup  : ego-browser nodejs -e "await completeTaskSpace(12, { keep: false })"
=== END FAILED ===
```

| exit | 含义 | 下一步 |
|---|---|---|
| 0 | 成功 | — |
| 10 | 参数/文件校验 | 改参数重跑，无副作用 |
| 11 | 依赖缺失（缺 mjs、缺 ffmpeg） | 补依赖 |
| 12 | 任务空间被占用 / SPACE_ID 无效 | 见下方「失败之后怎么重跑」 |
| 20 | 未登录 | 让用户扫码，回复 continue 后重跑 |
| 21 | 找不到「上传视频」入口（小红书） | 接管手动点一下 tab，或页面改版需更新选择器 |
| 30 | 上传失败/超时 | 重跑；卡 0% 就刷新 |
| 40 | 填表失败 | 接管看页面，可能改版 |
| 50 | 话题没挂上 | 接管手动补 |
| 60 | 提交失败 | 看 what_now |
| 70 | 提交后没跳转 | **不要立即重发**，先去作品列表确认 |
| 75 | 需要人工验证（抖音短信） | 让用户输验证码 |

失败默认保留浏览器现场（`KEEP_ON_FAIL=1`）。接管用 `claimTaskSpace`，
**不是** `takeOverTaskSpace`——保留现场后 ownership 变成 user。

多平台一起发时，**默认第一个失败就停**，避免带着问题继续发下一个（否则可能三个平台状态各不相同，
排查成本翻倍）。想「能发的先发、失败的稍后补」，设 `CONTINUE_ON_FAIL=1`，脚本会依次尝试并在末尾汇总结果。

### 失败之后怎么重跑

失败保留的现场会一直占着同名任务空间，直接重跑可能撞 `E_SPACE_OWNED`（exit 12）。两条路：

```bash
# A. 丢弃旧现场，新建空间重跑（最常用）
ego-browser nodejs -e "await completeTaskSpace(66, { keep: false })"
# 然后照原命令重跑

# B. 复用那个空间（省一次弹窗，适用于「空间里还停在登录页」这种空白现场）
SPACE_ID=66 PLATFORMS=channels MODE=stage ... bash release.sh
```

⚠ `SPACE_ID` 是**在旧空间里重跑全流程**，不是「接着填」。如果旧页面里已经上传过视频/填过内容，
再投递文件会撞 `E_UPLOAD_TIMEOUT`（exit 30）——这种情况必须用 A，别用 B。

**退出码不可信 `$?`。** `ego-browser nodejs` 会把子进程退出码统一改写成自己进程的 `1`，
真实码只打在 stdout 的一行 `ego's nodejs process exited with code NN.` 里。
`release.sh` 已经改成从 FAILED 块的 `exit : NN` 解析真实码（兜底解析那行日志，再兜底用管道码），
所以**看汇总表的退出码，不要直接看 shell 的 `$?`**。手工调 `ego-browser nodejs` 时同理。


## 必须知道的坑

**视频号是 wujie 微前端。** 内容全在 `wujie-app` 的 shadowRoot 里，
`document.querySelector` 一律失效，要 `document.querySelector('wujie-app').shadowRoot.querySelector(...)`。
上传文件用 CDP `DOM.getDocument({pierce:true})` 拿 nodeId 再 `DOM.setFileInputFiles`。

**视频号 JS click 不触发事件。** 沙箱里 `el.click()` 无效，必须 `Input.dispatchMouseEvent`。

**登录页的二维码在 iframe 里，而且要等 9 秒。** 扫码登录失败时最容易被误导的地方：
登录页 DOM 里只有 logo，查不到任何 img/canvas——二维码在 `open.weixin.qq.com/connect/qrconnect`
的 iframe（208×208）。`Page.reload {ignoreCache: true}` 之后 **6 秒截图拿到的是中间带循环箭头的模糊占位**，
看着像「二维码已失效」，其实只是没渲染完；等满 **9 秒**才是可扫的码。点 iframe 中心不会触发刷新，只能整页重载。
取码方法：读 iframe 的 `getBoundingClientRect()` → 整页截图 → 按 rect 裁剪放大 3 倍。

**「未登录」必须早于「wujie 缺失」判断。** 登录页本身没有 `wujie-app`，先查 wujie 会把未登录
误报成 `E_WUJIE_MISSING`（exit 11，依赖缺失），`what_now` 跟着指向查网络而不是扫码。
channels.mjs 现在的顺序是：打开 → 等 → **先判 `login` 重定向 → 再查 wujie**。

**视频号删除视频后重传会卡在上传 0%。** 删 → 确认 → 重传，进度永久停 0%，只能刷新（内容会清空）。
所以必须一次传对文件，没有「传错再换」这条路。

**抖音话题必须回车。** 输入 `#话题名` 后按 `Enter`，下拉首项就是精确匹配。
用 `el.click()` 无效，用 CDP 点坐标会点到隔壁那条（列表会重排）。

**抖音刷新即清空。** 内容没提交前刷新页面，标题描述话题全没，得重填。

**抖音「暂存离开」不保存。** 点完回上传页，内容管理和首页都找不到草稿。
别拿它当草稿用。

**抖音封面编辑器是图层式。** 上传的图会进时间轴但画布不切换，`完成` 按钮要等有效封面才可点。
脚本不处理，让人手动设。

**小红书发布按钮在 closed Shadow DOM 里。** `<xhs-publish-btn>` 内部拿不到，
常规 `click()` 全部失效，只能 `host._onPublish()` / `host._onSave()`，
调用前先查 `submit-disabled` / `save-disabled` 属性判断是否可用。

**小红书话题必须从下拉点选。** 直接插入 `#话题名` 只是纯文本，不算挂载。
流程是：输入 `#话题` → 等 `#creator-editor-topic-container` 出现 `.item` → 点 `.name` → Escape。
下拉没出来时重试一次，常见于刚打完字或网络慢。

**小红书点编辑区会被发布按钮挡住。** `click('div.tiptap')` 会报
`<xhs-publish-btn> intercepts pointer events`，要用 `el.focus()`，不要 click。

**小红书草稿只在本地。** 「草稿箱」面板改版后入口挪到右上角且点不开，
要验证内容得直读 IndexedDB `draft-database-v1` 的 `video-draft` / `image-draft`，
按 `timeStamp` 倒序取最新（不能取数组末尾，主键是 draftId 字符串）。

## 目录

```
scripts/
├── gen_cards.py           批量生成卡片（薄封装，引用 xhs-image-note-release 的生成器；段数校验）
├── rebuild.sh             一键重建：时间轴 + 内联 gsap + 渲染 + 混音（改素材后重跑即可）
├── tts.py                 分段配音（Qwen TTS + 音色预设）
├── build_composition.py   音频驱动时间轴 → 产出 index.html 与时间轴数据
├── mix_audio.py           人声铺设 + BGM 垫底 + limiter
├── release.sh             发布入口（参数校验/编排/日志/退出码）
├── xhs.mjs                小红书流程
├── channels.mjs           视频号流程
└── douyin.mjs             抖音流程
references/
└── platform-specs.md      平台规格细节与完整踩坑记录
```

## 依赖

- `ego-browser`（浏览器自动化，两个平台需已登录）
- `ffmpeg` / `ffprobe`（混音、探时长）
- `hyperframes`（渲染卡片视频，仅做视频时需要）
- Python 3（标准库即可，无第三方依赖）
- 卡片生成（gen_cards.py）：依赖 `xhs-image-note-release` skill 的 `references/card-generator/card_generator.py` 与 Google Chrome headless；缺失时启动即报错，可用 `--generator` 指定其他路径

## 卡片生成约定

- 输出 `card_01.png ~ card_NN.png`，按 segments 数组顺序编号，与 `build_composition.py` 的读取约定严格对齐。
- **段数与背景图数必须一致**，不一致直接报错退出（防止视频卡片静默错位）。
- 金句分行：优先用 segments 里的 `"lines": ["上句", "下句"]`；没写就按第一个逗号自动拆两行；整句无逗号则单行。
- 卡片规格默认 1080x1440（3:4），与 `--card-h 1440` 默认值匹配，一般不用动。
