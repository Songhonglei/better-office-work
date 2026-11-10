---
name: video-multi-release
description: >
  口播视频的制作与多平台发布工具。用 Qwen TTS 生成有情感的中文配音（成熟女声/男声，
  支持语气指令），按配音时长自动生成卡片视频（音频驱动时间轴），混入背景音乐，
  然后发布到小红书、视频号、抖音三个渠道。支持 stage（只准备不提交）、draft（存草稿）、
  publish（直接发）三种模式。当用户要做口播视频、给卡片视频配音、把视频发到小红书/视频号/抖音时使用。
  前置依赖：ego-browser 已安装且目标平台已登录；ffmpeg；ffprobe。
version: 1.3.2
slug: video-multi-release
displayName: 口播视频制作与多平台发布
bins: [ffmpeg, ffprobe, python3, node, npm, npx, ego-browser]
metadata:
  openclaw:
    requires:
      env:
        - DASHSCOPE_API_KEY
    primaryEnv: DASHSCOPE_API_KEY
---

# video-multi-release

把「一组卡片 + 一段文案」变成「带配音的竖屏视频」，再发到视频号和抖音。

跟 `xhs-image-note-release` 的关系：那个管**单条**小红书图文/视频笔记，这个管**多平台同发**（视频号 + 抖音，也含小红书）。
两者共用卡片生成器，但发布流程完全不同，不要互相塞；只有一条小红书笔记时走那个，别为了发一条笔记拉起三平台编排。

## 不适用场景

- **小红书图文笔记**（多图 + 文案）→ 用 `xhs-image-note-release`
- **纯图片轮播视频**（不需要配音、不需要卡片）→ ffmpeg 直接拼，没必要走这套
- **抖音要求全自动发布** → 做不到，短信验证绕不过；只能自动化到「填好停在发布前」

## 硬边界（先看这条）

**抖音大多能全自动，但短信验证是概率性触发。** 2026-11-07 起实测可直接发布成功；
一旦命中短信二次验证（平台级真人校验，任何自动化都绕不过），会以 exit 75 中止并保留现场。
所以抖音默认 `MODE=stage`：把视频传好、标题描述话题填好停在那里，先人工确认再发。

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
| 全自动 | 是 | 是 | 多为是；短信验证概率性触发（命中即 exit 75） |

## 首次配置（onboard）

本 skill 不含任何密钥。API Key 只落在**数据目录**的 `.env`（skill 目录之外，升级/镜像覆盖不会清掉，多个 agent 共用）：

```bash
bash ~/.workbuddy/skills/video-multi-release/scripts/onboard.sh --verify
# 写入位置：~/space/skills-data/video-multi-release/.env（权限 600）
```

不带 `--key` 会交互输入（不回显）；`--verify` 会真调一次 TTS 验证 key 可用。
**优先用交互输入**——`--key sk-xxx` 会把密钥留在 shell history 和 `ps` 输出里。

Key 在阿里云百炼控制台 → API-KEY 管理创建。读取优先级：
`环境变量 DASHSCOPE_API_KEY` > `~/space/skills-data/video-multi-release/.env` > 旧位置 skill 根目录 `.env`（兼容）。
根目录可用 `WB_SKILLS_DATA` 覆盖。

模型走 MaaS Token Plan 端点，`token-plan` 就是 `{WorkspaceId}`，不需要单独开通百炼账号。

## 快速开始

**唯一输入是 `voice_script.json`**，先有它再谈后面：

```json
{
  "segments": [
    {"id": "s01", "text": "旁白第一段……", "lines": ["坑儒？", "压根没有"]},
    {"id": "s02", "text": "旁白第二段……", "lines": ["公元前219年", "琅琊遇方士"], "text_pos": "top"}
  ]
}
```

| 键 | 必填 | 作用 |
|---|---|---|
| `segments` | 是 | 段落数组；一段 = 一张卡片 = 一个 mp3 |
| `segments[].id` | 是 | 决定配音文件名（`<id>.mp3`），`build_composition.py` 按它找音频，**必须唯一** |
| `segments[].text` | 是 | 旁白原文，TTS 读它；字数决定该卡时长 |
| `segments[].lines` | 否 | 卡片上的大字（建议手写 2 行）；缺省自动从 `text` 拆 |
| `segments[].quote` | 否 | 备选拆行来源：没写 `lines` 时优先拿它拆行，再退回 `text` |
| `segments[].text_pos` | 否 | 文字位置覆盖，优先级最高（见「文字位置：三级优先」） |
| `segments[].font_main` | 否 | 该卡单独换字体 |
| `segments[].image` | 否 | 单独指定背景图，默认按序号取 `images/img_NN.png` |

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
  --out-dir voice

# 2a) 生成音频驱动的时间轴（分步复跑时才需要）
#     默认值与 rebuild.sh 对齐；改这三个值必须同步改 2b 的 PRE/GAP/TAIL，
#     否则分步跑和一键跑会得到不同时长，音画对齐表就对不上。
python3 $SKILL/scripts/build_composition.py \
  --script voice_script.json \
  --voice-dir voice \
  --pre 0.6 --gap 0.45 --tail 1.5

# 2b) 一键重建：时间轴 + 内联 gsap + 渲染 + 混 BGM → out/final.mp4
#    （等于下面 3)(4) 两步；改了卡片或配音后重跑它即可，时间轴自动重算）
bash $SKILL/scripts/rebuild.sh /path/to/project
#    可选：BGM=/path/to.mp3 PRE=0.6 GAP=0.45 TAIL=1.5 bash rebuild.sh ...

# 3)（rebuild.sh 的分解视图）无声画面（HyperFrames 项目里）
#    注意先内联 gsap：build_composition.py 产出的 index.html 引的是外链
#    assets/vendor/gsap.min.js，只有 rebuild.sh 第 2 步会把它内联进 HTML。
#    跳过这步直接 render，会命中 SUB_TIMELINE_SCRIPT_FAILURE。
npx hyperframes@0.9.1 render --output /tmp/silent.mp4

# 4)（rebuild.sh 的分解视图）混音成片
python3 $SKILL/scripts/mix_audio.py \
  --silent /tmp/silent.mp4 \
  --bgm "$HOME/space/skills-data/video-multi-release/music/Frost Waltz.mp3" \
  --out out/final.mp4

# 5) 发布
PLATFORMS=xhs,channels,douyin \
VIDEO=$PWD/out/final.mp4 \
TITLE="四十岁以后，我不再跑那么快了" \
DESC="$(cat desc.txt)" \
TOPICS="人生感悟,人到中年,独处,读书" \
COVER=$PWD/assets/card_01.png \
HOT_TOPICS=auto \
MODE=stage \
  bash $SKILL/scripts/release.sh
```

先跑 `MODE=stage` 确认内容无误，再跑 `MODE=publish`。

## 封面：自定义封面 + 竖横双版

三个参数，都可选：

| 参数 | 说明 | 谁在用 |
|---|---|---|
| `COVER` | 竖版 3:4 封面图路径 | 三平台通用；抖音为尽力而为（失败只告警，人工可补） |
| `COVER_HORIZONTAL` | 横版 16:9 封面图路径 | 留空时自动探测 `VIDEO` 同目录的 `../assets/card_01_h.png` |
| — | 不传则用平台自动截帧封面 | 全部 |

**生成横版封面**（同款古风样式，用第一段金句）：

```bash
python3 $SKILL/scripts/gen_cards.py --script voice_script.json --images images/ \
  --tag 古人情话 --account @雨夜心灯 --cover-h        # → assets/card_01_h.png (1920x1080)
```

**平台实情（2026-11-07 实测）**：
- **视频号只有一个 3:4 封面**，个人主页和分享卡片共用，没有独立的横版位。
  脚本会自动走完「编辑 → 上传封面 → 确认」；`COVER_HORIZONTAL` 对视频号会被忽略并打提示。
- **抖音封面编辑器是图层式**，脚本做尽力而为的上传尝试（设置封面 → 上传封面 → 完成），
  失败只告警不阻断，发布前人工可补。
- 封面设置失败**不会**中断发布（自动降级为平台自动封面）。

## 热点话题：自动关联

`HOT_TOPICS=auto` 会拉抖音热榜（iesdouyin 公开接口，无需鉴权），按 `DESC` 与
`TOPICS` 关键词的相关度挑最多 `HOT_TOPICS_MAX`（默认 2）个热榜词，追加为附加话题。

```bash
HOT_TOPICS=auto bash release.sh              # 自动挑
HOT_TOPICS="立冬吃什么,初雪" bash release.sh   # 手动指定
HOT_TOPICS_MAX=3 bash release.sh             # 自动挑 3 个
```

匹配用字符 bigram 重合度，且**至少命中 2 个描述片段或 1 个关键词**才算相关——
这是为了防止「热点」「话题」这类泛词把所有热榜词都拉进来（实测踩过：历史内容
被挂上「S16 淘汰赛」）。无相关热点时静默跳过，不会硬凑。

单独调试匹配效果：

```bash
python3 $SKILL/scripts/hot_topics.py --desc "今天立冬，聊聊立冬吃什么" --keywords "节气" --pick 3
```

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
同时把这条时间轴落盘成 `./timeline.json`（**当前工作目录 CWD**，不随 `--out` 变化——所以必须在项目目录执行）。
`mix_audio.py` 读的是**同一份**时间轴，所以音画不会各算一遍导致错位——这是配音视频最容易翻车的地方。

时间轴公式：

```
卡片 i 起点 = pre + Σ(前面各段音频时长) + i × gap
卡片 i 可见 = 音频i时长 + gap（中间卡，留给下一卡的转场）
末卡 可见 = 末卡音频 + tail            ← 末卡不再叠 gap
总时长 total = 末卡 start + 末卡音频 + tail
```

默认 `pre=0.6 gap=0.45 tail=1.5`（与 `rebuild.sh` 一致；`build_composition.py` 单独调用时 gap 默认 0.5，以 rebuild.sh 为准）。想更从容就调大 gap。
末卡原先也叠了 gap，导致末卡结束比 root 的 `total` 晚 `gap` 秒（GSAP 尾巴越界），
2026-11-10 审计后修掉，现在末卡结束与 `total` 严格相等。

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

## 发布后必须核验（别只信退出码）

脚本打印 `=== OK (published) ===` 只代表按钮点下去了、URL 变了，**不代表作品真的存在**。
2026-11-09 实测：两个平台都返回 published，后台列表却是空的；还遇到过点发表后页面跳回空白
上传页、内容被清空，脚本却报成功。发完必须回创作后台按标题核验一遍。

| 平台 | 核验地址 | 判断方式 |
|---|---|---|
| 小红书 | `creator.xiaohongshu.com/new/note-manager` | `document.body.innerText.includes(标题)` |
| 抖音 | `creator.douyin.com/creator-micro/content/manage` | 同上 |
| 视频号 | `channels.weixin.qq.com/platform/post/list` | 递归取 `wujie-app.shadowRoot.textContent`，`body.innerText` 只有「视频号 · 助手」6 个字 |

两个容易误判的地方：

1. `document.body.innerText.slice(0, N)` 常常只截到导航栏，列表在后面——`includes` 判断要读全文。
2. 视频号后台列表展示的是**描述开头**，不是短标题。搜标题搜不到时改搜描述首句。

## 失败时怎么办

失败会打结构化块，照着 `what_now` 做：

```
=== FAILED ===
platform : 视频号
step     : upload
code     : E_UPLOAD_TIMEOUT
exit     : 30
message  : 视频上传超时（240 秒）
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
| 20 | 未登录 | 小红书/视频号：扫码后重跑。**抖音：必须带 `SPACE_ID=<id>` 或 `RESUME=1` 重跑**，裸跑会 `Page.reload` 杀掉刚扫的码 |
| 21 | 找不到「上传视频」入口（小红书） | 接管手动点一下 tab，或页面改版需更新选择器 |
| 30 | 上传失败/超时 | 重跑；卡 0% 就刷新 |
| 40 | 填表失败 | 接管看页面，可能改版 |
| 50 | 话题没挂上 | 接管手动补 |
| 60 | 封面处理失败（已降级，通常不阻断） | 看 what_now；抖音封面失败只告警 |
| 70 | 提交按钮点不到（视口外 / 被遮挡） | 接管检查按钮位置，别急着当「平台拒发」。**抖音的 `E_PUBLISH_BTN_DISABLED` 走 40 不是 70** |
| 75 | 需要人工验证（抖音短信） | 让用户输验证码 |
| 80 | 发布未确认（点了但列表里没找到） | **不要立即重发**，接管点「内容管理」重拉列表确认 |
| 90 | 未捕获异常 / 输出丢失 | 看日志尾部；通常是页面改版或 ego 交权 |

> code 与 exit 的对应：`E_PUBLISH_BTN_OUT_OF_VIEW`=70，`E_PUBLISH_BTN_DISABLED`=**40**（抖音按表单校验未过处理）。
> 拿不准就看 FAILED 块里的 `code` 去 `references/error-handling.md` 查，别只看数字。

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

按平台分组。每条只留「判据 + 为什么」，完整推演见 [CHANGELOG.md](CHANGELOG.md)。

### 渲染（hyperframes）

- **gsap 外链必须内联。** 模板里的 `<script src="assets/vendor/gsap.min.js">` 在 hyperframes 渲染时必挂：
  `SUB_TIMELINE_SCRIPT_FAILURE` + `TypeError: Cannot read properties of null (reading 'timeline')`——
  sub-timeline 脚本先于外链库执行。`rebuild.sh` 第 2 步已自动内联，手动渲染前要自己做。
- **Chrome 路径要显式指。** 默认的 chrome-headless-shell 常报 `All providers failed`。
  设 `HYPERFRAMES_BROWSER_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`，
  任意版本 Chrome 都能走 screenshot capture。`rebuild.sh` 已内置回退。

### 视频号（wujie 微前端，坑最多）

- **内容全在 `wujie-app` 的 shadowRoot 里**，`document.querySelector` 一律失效。上传文件走
  CDP `DOM.getDocument({pierce:true})` 拿 nodeId 再 `DOM.setFileInputFiles`。
- **`el.click()` 不触发事件**，必须 `Input.dispatchMouseEvent` 派发真实鼠标事件。
- **滚动后必须重新取坐标。** 「发表」常在首屏外（实测 `y=1268`，视口 756）。
  `scrollIntoView()` 之后不能立刻 `getBoundingClientRect()`——`scroll-behavior: smooth` 下拿到的还是滚动**前**的位置，
  CDP 就点在了屏幕外。表现极具迷惑性：点了没反应、页面不跳，只报 `E_PUBLISH_UNCONFIRMED`(80)，
  容易误判成「平台拒发」。正确顺序：`scrollIntoView({block:'center',behavior:'instant'})` → 等 1.2s
  → 重取 rect → 校验 `top>=0 && bottom<=innerHeight` → 再点。`channels.mjs` 的 `clickByText()` 已实现，
  视口外返回 `out_of_view` 而非盲点。
- **二维码在 iframe 里，且要等 9 秒。** 登录页 DOM 只有 logo，码在
  `open.weixin.qq.com/connect/qrconnect` 的 iframe（208×208）。`Page.reload {ignoreCache:true}` 后
  **6 秒截图是带循环箭头的模糊占位**，看着像失效，其实没渲染完；等满 9 秒才可扫。
  点 iframe 中心不会刷新，只能整页重载。
- **必须有人在場。** 码约 5 分钟过期，扫完还要在手机上点「确认登录」。实测三次「生成码 → 等 5 分钟」全部超时。
  所以视频号**不能进无人值守的定时流程**。另外 ego 里微信号有时先显示「微信快捷登录」，
  点了报「加载失败」（缺微信客户端），要点「使用其他头像、昵称或账号」切回二维码。
- **「未登录」必须早于「wujie 缺失」判断。** 登录页本身没有 `wujie-app`，先查 wujie 会把未登录
  误报成 `E_WUJIE_MISSING`(11)，`what_now` 跟着指向查网络。现在的顺序是：打开 → 等 → 先判 `login` 重定向 → 再查 wujie。
- **上传完成判定：`发表`按钮可用 && `video.duration > 0`，两个都要。** 单看 duration 会误判——
  浏览器解码本地文件立刻就有值，实测卡在 14%/90% 时已经 `>0`，日志报「上传完成 18.5s」，
  接着填文案点发表，一刷新内容全丢。单看「重新上传」也不行，那是传完之后的正常按钮。
- **别用 `sr.textContent` 搜状态词。** shadowRoot 的 textContent 会把 `<style>` 里的 CSS 一起读进来，
  CSS 本来就有 `0%` / `uploading` 字样，正则恒命中。要读文案就用
  `createTreeWalker(sr, NodeFilter.SHOW_TEXT)` 并跳过 `SCRIPT`/`STYLE` 父节点。
- **删除后重传会卡 0%。** 删 → 确认 → 重传，进度永久停 0%，只能刷新（内容清空）。没有「传错再换」这条路。
- **短标题有字符白名单。** 含逗号（，）等非法符号时，**保存草稿/手机预览/发表三个按钮全部静默禁用**
  （`weui-desktop-btn_disabled`），无任何报错。官方只支持书名号、引号、冒号、加号、问号、百分号、摄氏度；
  **逗号用空格代替**，`channels.mjs` 预处理会替换。

### 抖音

- **话题必须回车。** 输入 `#话题名` 后 `Enter`，下拉首项就是精确匹配。`el.click()` 无效，
  CDP 点坐标会点到隔壁（列表会重排）。**补挂失败别用退格**——标签是整体单元，连按会把已挂的一起删
  （实测误删 `#历史真相`），宁可留成纯文本。
- **刷新即清空。** 内容没提交前刷新，标题描述话题全没。
- **「暂存离开」不保存。** 点完回上传页，内容管理和首页都找不到草稿，别当草稿用。
- **封面编辑器是图层式。** 上传的图会进时间轴但画布不切换，「完成」要等有效封面才可点。脚本不处理，让人手动设。
- **登录态撑不过 reload（2026-11-07 实测）。** ego 任务空间存储隔离，passport 登录后一刷新就掉回登录页，
  所以 `release.sh` 开头的 `Page.reload` 每次都会杀掉刚扫的码。用户扫码后**不要重跑 release.sh**，
  在同空间开连续会话现场驱动（`uploadFile` → `fillInput` → `Input.insertText` →
  `caretToEnd` + `#话题` + `pressKey('Enter')`）。`caretToEnd` 是 douyin.mjs 内部函数需内联，
  `fillInput/uploadFile/pressKey` 是 ego 全局可直接用。短信验证是概率性触发，命中即 exit 75。

### 小红书

- **发布按钮在 closed Shadow DOM。** `<xhs-publish-btn>` 内部拿不到，`click()` 全部失效，
  只能 `host._onPublish()` / `host._onSave()`，调用前先查 `submit-disabled` / `save-disabled`。
- **自定义封面失败不再阻断（2026-11-09 实测）。** 平台改版后「编辑封面」入口会消失
  （`E_COVER_ENTRY_HIDDEN`），旧逻辑直接 exit 60，等于为一个封面放弃整条发布。现在降级为警告，
  改用平台自动生成的三张 PK 封面试选——效果反而更贴视频本身。
- **话题必须从下拉点选。** 直接插入 `#话题名` 只是纯文本。流程：输 `#话题` → 等
  `#creator-editor-topic-container` 出现 `.item` → 点 `.name` → Escape。下拉没出来重试一次（刚打完字或网络慢常见）。
- **点编辑区会被发布按钮挡住。** `click('div.tiptap')` 报 `<xhs-publish-btn> intercepts pointer events`，
  要用 `el.focus()`。
- **草稿只在本地。** 草稿箱面板改版后入口挪到右上角且点不开，验证要直读 IndexedDB
  `draft-database-v1` 的 `video-draft`/`image-draft`，按 `timeStamp` 倒序取最新
  （不能取数组末尾，主键是 draftId 字符串）。

### ego 通用

- **排障铁律：按钮整行禁用 → 先查校验，别查网络。** 第一动作是把整页（含视口外）的校验红字、必填提示
  全找出来，其次才查网络。本次曾在网络层空转一小时，实际是表单校验不过。
- **排障必须用脚本同款空间名。** `claimTaskSpace(N)` 之后要 `taskSpace('publish channels video')`
  （与脚本 acquireSpace 同名）才能连到那个 tab；挂到自己的调试空间看到的是别的 tab，会得出「内容丢了」的错误结论。
- **任务空间存储隔离。** 在空间 A 扫码登录 → 清理 A → 新开 B，登录态随 A 销毁。跨空间复用不可行；
  重跑失败发布**不要清理脚本空间**，直接同名 acquireSpace 复用。
- **位置权限弹窗会让 ego 静默交权（2026-11-05 实测）。** 小红书请求 geolocation → Chrome 弹框 →
  ego 判定需要用户 → 命令被拒、挂起后被杀（exit 90，缓冲输出全丢）。根治：退出 ego-lite 后写
  `Default/Preferences`（geolocation=2 + `creator.xiaohongshu.com:443,*` 例外 block）再重启。
  排障探针要用 `process.stdout.write` 直写，`console.log` 的缓冲在被杀时会全丢。

## 目录

```
scripts/
├── gen_cards.py           批量生成卡片（含 --cover-h；古风主题/字体透传/自动留白定位）
├── find_safe_area.py      自动留白检测（ffmpeg 灰度滑窗 + 置信度，找适合叠字的暗部）
├── cards_contact_sheet.py 卡片全检联系表（强制逐张目视复核，禁止抽样）
├── estimate.py            TTS 前时长预估（字/秒 → 需砍多少字）
├── verify_sync.py         按时间轴抽帧，生成音画同步联系表
├── hot_topics.py          抖音热榜拉取 + 描述相关度筛选（HOT_TOPICS=auto）
├── rebuild.sh             一键重建：时间轴 + 内联 gsap + 渲染 + 混音（改素材后重跑即可）
├── tts.py                 分段配音（Qwen TTS + 音色预设）
├── build_composition.py   音频驱动时间轴 → 产出 index.html 与时间轴数据
├── mix_audio.py           人声铺设 + BGM 垫底 + limiter
├── release.sh             发布入口（参数校验/编排/日志/退出码）
├── onboard.sh             首次配置：写 .env（权限 600）+ --verify 真调一次 TTS
├── xhs.mjs                小红书流程
├── channels.mjs           视频号流程
└── douyin.mjs             抖音流程
references/
├── platform-specs.md      平台规格细节与完整踩坑记录（改选择器/排查 DOM 时才读）
└── replace-published-video.md  三平台删旧发新的入口与实测坑（只在替换线上内容时读）
assets/music/
├── README.md              曲目清单 + CC-BY 署名要求
└── download.sh            曲库下载脚本（87MB，不入 git）
```

**什么时候读 `references/platform-specs.md`（373 行，只做参考，改动后可能已过期）**：改选择器、新增平台、排查 DOM 结构时读；
日常发布**不要读**。注意该文件截至 2026-11-02，其中的上传完成判据、视频号成功标志、
抖音封面结论**已被 11-09/11-10 的修复推翻**，冲突时一律以本文件为准。

## 依赖

> **曲库全部是 CC-BY 4.0**（`assets/music/README.md`）。用了曲库 BGM 的成片，对外发布时
> **简介里必须署上原作者**（如 `Music: Kevin MacLeod (CC-BY 4.0)`）。`release.sh` 运行时会打印提醒，
> 但那时 `DESC` 往往已经写好了——**写 DESC 的当下就要带上**，别等警告。

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

### 古风字体：历史题材优先（2026-11-09 起原生支持）

**生成器已原生支持字体参数，不需要再复制 `card_generator_gufeng.py` 到项目里。**
`xhs-image-note-release` 的 `card_generator.py` 现已新增 `history` 主题与 `--font-main`。

历史 / 古风 / 传统文化题材直接：

```bash
python3 $SKILL/scripts/gen_cards.py --script voice_script.json --images images/ \
  --content-type history --out-dir assets      # 自动套 history 主题
```

字体优先级（显式指定 > 默认）：
`segments[i].font_main` > `--font-main` > `config.font_main` > 主题自带字体。
小字（标签 / 页码 / 署名）仍用主题 `font_tag`，避免隶书小字号糊成一团。

macOS 自带、可直接用的古风字体（在 `AssetsV2/com_apple_MobileAsset_Font8/*/AssetData/`，需已下载）：

| CSS 字体名 | 字体 | 观感 | 适用 |
|---|---|---|---|
| `Baoli SC` | 报隶 | 隶书、横扁厚重、碑刻感 | **history 默认**，秦汉史 / 翻案解说最贴 |
| `Weibei SC Bold` | 魏碑-简 粗体 | 方笔峻利、金石味 | 碑刻、考古、制度史 |
| `Xingkai SC` | 华文行楷 | 连笔飘逸、字重轻 | 古装剧片头感，抒情/诗词向 |
| `Libian SC` | 隶变 | 隶书偏细 | 古意弱于报隶，作 fallback |
| `Kaiti SC` | 楷体 | 规整清正，最易读 | 长句、信息量大的段落 |

> 旧文档写「系统没有魏碑（Weibei）」是错的：`WeibeiSC-Bold.otf` / `WeibeiTC-Bold.otf` 实测都在，
> CSS 名用 `Weibei SC Bold`。之前大概是查了简体 Regular 没查到 Bold。

**为什么默认报隶而不是行楷（2026-11-09 同图对比实测）**：行楷笔画细、连笔飘，
在暗底上像古装剧片头，压不住「翻案 / 考证」这类严肃叙述；报隶横扁厚重，
既古朴又清晰，冲击力更强。诗词抒情向内容可用
`--font-main "'Xingkai SC', 'Songti SC', serif"` 切回行楷。

行楷字重轻，背景一亮字就糊：遇到大面积天空 / 浅色底图，先
`Brightness(0.55) + Contrast(1.12)` 压暗再进卡片，比调 scrim 更保画面层次。

---

## 历史题材：卡片与字体

### 历史题材的两处差异

快速开始那套命令原样可用，只需替换两个点：

```bash
--content-type history                                    # gen_cards.py：自动套暗色古风主题 + 留白定位
CANVAS_BG=#0a0806 CANVAS_STOPS='#0b0806,#0a0806,#100c08,#080604' bash .../rebuild.sh $PROJ
```

后者必带：`history` 是近黑卡片，画布默认米白，不传会在卡片外圈出一圈刺眼白框。
`rebuild.sh` 还会顺带产出 `out/sync_check/contact_sheet.png`（音画同步联系表，`VERIFY=0` 跳过）
并清理 `out/silent.mp4`（`KEEP_SILENT=1` 保留）。

### 文字位置：三级优先，别再压住人物头部

`card_generator.py` 原本把文字**硬编码垂直居中**（`start_y=(height-text_block_h)/2-20`），
而 AI 历史插画的主体也常落在中部 —— 实测 6 张卡片有 3 张压住人物头部。
现在按以下优先级决定位置：

| 级别 | 来源 | 用法 |
|---|---|---|
| 1（最高） | `segments[i].text_pos` | 枚举或坐标对象，个别卡片人工覆盖 |
| 2 | 自动留白检测 | 默认开启，`find_safe_area.py` 滑窗找「暗 + 平 + 无轮廓」的区带 |
| 3 | 全局 `--text-y-ratio` | `--no-auto-safe-area` 关闭自动后生效，一刀切上移（如 0.35） |
| 4 | 居中 0.5 | 以上都没给 |

`text_pos` 枚举：`top` / `center` / `bottom` / `left` / `right` /
`top-left` / `top-right` / `bottom-left` / `bottom-right`；
也可写坐标对象 `{"y":0.28,"x":0.08,"anchor":"start"}`。

```json
{"id":"s06", "text":"…", "lines":["坑的是方士","不是儒生"],
 "text_pos":"top-left", "font_main":"'Kaiti SC', serif"}
```

生成器新增 `--text-y-ratio` / `--text-x-ratio` / `--text-anchor`，
并会把文字块 clamp 在顶部标签与底部页码之间的安全区。
`--safe-axis both` 会让自动检测顺便选更空的左/右半边，但卡片间文字左右跳动，
节奏要求高时建议只用默认 `vertical`。

**算法局限**：亮度/方差/梯度只是「主体」的代理量，暗色人影仍可能被判成留白
（实测 img_02 误选底部岩石）。所以段级 `text_pos` 必须保留作人工兜底。

## 视觉与配置的已知边界

卡片生成后**必须全检所有张**，不能抽查：`gen_cards.py` 会自动产出 `<out-dir>/_check/group_*.png`
（每组 6 张）与 `all.png`，`--no-proof` 可关但不建议。重点看「白字有没有压住人物头部 / 面部」。
抽样翻过车——18 张只抽 6 张、报了「5/6 没问题」，漏掉的第 01 张（钩子卡）正压在秦始皇额头上。
`find_safe_area.py` 会输出 `confidence`，判 `low` 的必须人工复核并用段级 `text_pos` 固化；
根治办法是生图就用 `config.json` 的 `image_prompt_presets.history_dark` 硬约束
（主体放下三分之一、上方 40% 纯暗留白、不出现面部五官）。

以下几条是**有意保留**的行为边界，别当 bug 重复报（19 项修复清单见 [CHANGELOG.md](CHANGELOG.md)）：

- **`--text-x-ratio` / `--text-anchor` 在自动留白检测开启时被覆盖**：自动检测只给 `y`，
  默认 `axis=vertical` 恒返回 `x=0.5 / middle`。要改水平位置先加 `--no-auto-safe-area`。
  同理，这三个位置参数只对 `text` 布局生效，`image-text` 布局仍固定居中。
- **发布后核验「同标题重跑可能误判」**：三平台都靠「列表里出现标题」判定，没记发表前的作品数。
  删旧稿重发时旧作品已不在、判据可靠；原地重跑会直接命中旧作品。**发布后仍应人工比对作品数 +1**。
- **`config.json` 的 `topics_history_extra` / `image_prompt_presets` / `_canvas_dark_preset` 没有脚本消费者**：
  前两个是生图提示词模板，第三个是环境变量备忘，属「文档即用途」，配了不会自动生效。
- **`timeline.json` 落在 CWD**（`--out` 只改 `index.html` 路径，脚本会打印实际落点）；
  `hot_topics.py` 的 `STOP` 是死代码。两处属 INFO，未改。

---

## 替换已发布的视频（删旧发新）

改版后要替换线上视频时：先在三个平台后台删旧稿，再用 `release.sh` 重发。
完整入口与实测坑见 [references/replace-published-video.md](references/replace-published-video.md)，
**只在真的要替换线上内容时加载**。

三条最容易翻车的：视频号删除要点**图标** `.opr-item`，且弹窗要按「删除视频」文本挑
（页面里有多个同类 `.weui-desktop-dialog`，第一个可能是「切换视频号」）；抖音删除用 DOM
`el.click()`，作品数标签有缓存、以标题消失为准；`release.sh` 报 `E_PUBLISH_UNCONFIRMED`
时必须接管、点「内容管理」重拉列表再决定是否重发。
