---
name: video-multi-release
description: >
  口播视频的制作与多平台发布工具。用 Qwen TTS 生成有情感的中文配音（成熟女声/男声，
  支持语气指令），按配音时长自动生成卡片视频（音频驱动时间轴），混入背景音乐，
  然后发布到小红书、视频号、抖音三个渠道。支持 stage（只准备不提交）、draft（存草稿）、
  publish（直接发）三种模式。当用户要做口播视频、给卡片视频配音、把视频发到小红书/视频号/抖音时使用。
  前置依赖：ego-browser 已安装且目标平台已登录；ffmpeg；ffprobe。
version: 1.3.0
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

本 skill 不含任何密钥。API Key 只落在**数据目录**的 `.env`（skill 目录之外，升级/镜像覆盖不会清掉，多个 agent 共用）：

```bash
bash ~/.workbuddy/skills/video-multi-release/scripts/onboard.sh --verify
# 写入位置：~/space/skills-data/video-multi-release/.env（权限 600）
```

不带 `--key` 会交互输入（不回显）；`--verify` 会真调一次 TTS 验证 key 可用。

Key 在阿里云百炼控制台 → API-KEY 管理创建。读取优先级：
`环境变量 DASHSCOPE_API_KEY` > `~/space/skills-data/video-multi-release/.env` > 旧位置 skill 根目录 `.env`（兼容）。
根目录可用 `WB_SKILLS_DATA` 覆盖。

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
  --bgm ~/space/skills-data/video-multi-release/music/bgm.mp3 \
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
| `COVER` | 竖版 3:4 封面图路径 | 视频号（唯一封面位）、抖音（3:4 作品封面） |
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
同时把这条时间轴落盘成 JSON（与 index.html 同目录）。
`mix_audio.py` 读的是**同一份**时间轴，所以音画不会各算一遍导致错位——这是配音视频最容易翻车的地方。

时间轴公式：

```
卡片 i 起点 = pre + Σ(前面各段音频时长) + i × gap
卡片 i 可见 = 音频i时长 + gap（中间卡，留给下一卡的转场）
末卡 可见 = 末卡音频 + tail            ← 末卡不再叠 gap
总时长 total = 末卡 start + 末卡音频 + tail
```

默认 `pre=0.5 gap=0.4 tail=1.2`。想更从容就调大 gap。
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

**gsap 外链脚本必须内联（2026-11-03 实测）。** index.html 模板里
`<script src="assets/vendor/gsap.min.js"></script>` 在 hyperframes 渲染时必挂：
报 `SUB_TIMELINE_SCRIPT_FAILURE`，`runtime-error: TypeError: Cannot read properties
of null (reading 'timeline')`——sub-timeline 脚本先于外链库执行，`gsap` 还是 null。
把 gsap.min.js 内容直接内联进 index.html 即可。`rebuild.sh` 第 2 步已自动处理，
手动渲染前记得先内联。

**hyperframes 的 Chrome 要手动指路（2026-11-03 实测）。** hyperframes 默认用
chrome-headless-shell，首次会尝试自动下载，但经常 `All providers failed` 直接渲染失败。
设 `HYPERFRAMES_BROWSER_PATH` 指向本机 Chrome 即可，任何版本的 Chrome 都能走通
screenshot capture 路径：
`export HYPERFRAMES_BROWSER_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`。
`rebuild.sh` 已内置自动回退。

**视频号是 wujie 微前端。** 内容全在 `wujie-app` 的 shadowRoot 里，
`document.querySelector` 一律失效，要 `document.querySelector('wujie-app').shadowRoot.querySelector(...)`。
上传文件用 CDP `DOM.getDocument({pierce:true})` 拿 nodeId 再 `DOM.setFileInputFiles`。

**视频号 JS click 不触发事件。** 沙箱里 `el.click()` 无效，必须 `Input.dispatchMouseEvent`。

**滚动之后必须重新取坐标，否则点在屏幕外（2026-11-09 实测）。** 视频号「发表」按钮常在首屏之外
（实测 `y=1268`，视口只有 756）。`btn.scrollIntoView()` 之后**不能立刻** `getBoundingClientRect()`——
页面带 `scroll-behavior: smooth` 时返回的仍是滚动**前**的位置，CDP 于是把鼠标点在了屏幕外。
表现极具迷惑性：点了完全没反应，页面不跳转，`release.sh` 只报 `E_PUBLISH_UNCONFIRMED`（exit 80），
很容易误判成「平台拒发」或「封面没过」。正确顺序：

```
scrollIntoView({block:'center', behavior:'instant'}) → 等 1.2s → 重新取 rect
→ 校验 top>=0 && bottom<=innerHeight → 再鼠标点击
```

`channels.mjs` 的 `clickByText()` 已按此实现，视口外会返回 `out_of_view` 而不是盲点。

**登录页的二维码在 iframe 里，而且要等 9 秒。** 扫码登录失败时最容易被误导的地方：
登录页 DOM 里只有 logo，查不到任何 img/canvas——二维码在 `open.weixin.qq.com/connect/qrconnect`
的 iframe（208×208）。`Page.reload {ignoreCache: true}` 之后 **6 秒截图拿到的是中间带循环箭头的模糊占位**，
看着像「二维码已失效」，其实只是没渲染完；等满 **9 秒**才是可扫的码。点 iframe 中心不会触发刷新，只能整页重载。
取码方法：读 iframe 的 `getBoundingClientRect()` → 整页截图 → 按 rect 裁剪放大 3 倍。

**视频号必须有人在场才能发（2026-11-09 实测）。** 二维码约 5 分钟过期，扫完还要在手机上点
「确认登录」页面才跳 `/platform`。实测排了三次「生成码 → 等 5 分钟」全部超时，用户只是没来得及扫。
所以视频号**不能进无人值守的定时流程**：要么当场盯着人扫，要么这一轮只发小红书 + 抖音。
另外 ego 里的微信号有时会先显示「微信快捷登录」，点了报「加载失败」（缺微信客户端环境），
必须点「使用其他头像、昵称或账号」切回二维码。

**「未登录」必须早于「wujie 缺失」判断。** 登录页本身没有 `wujie-app`，先查 wujie 会把未登录
误报成 `E_WUJIE_MISSING`（exit 11，依赖缺失），`what_now` 跟着指向查网络而不是扫码。
channels.mjs 现在的顺序是：打开 → 等 → **先判 `login` 重定向 → 再查 wujie**。

**上传完成不能看 `video.duration`（2026-11-09 实测）。** 浏览器解码本地文件就能拿到时长，
视频还在传（实测卡在 14% / 90%）时它已经 `>0`，日志会误报「上传完成 18.5s」，接着填文案、
点发表，页面一刷新内容全丢。唯一可靠信号是**「发表」按钮出现且未禁用**——上传中它要么是灰的，
要么压根不渲染。`channels.mjs` 现在只认这个信号，超时也从 160s 提到 240s。

**别用 `sr.textContent` 搜状态词（2026-11-09 实测）。** 两个连环坑：① shadowRoot 的
`textContent` 会把 `<style>` 里的 CSS 一起读进来，CSS 本来就有 `0%` / `100%` / `uploading`
这类字样，正则一命中就恒为「还在上传」；② 视频传完之后页面上本来就有「重新上传」按钮，
把它当失败标记，判据永远不成立。两坑叠加，实测白等 240 秒，而按钮早已可用、视频完整。
正确姿势：判据只认**「发表」按钮可用 + `video.duration > 0`**；要读页面文案就用
`createTreeWalker(sr, NodeFilter.SHOW_TEXT)` 并跳过 `SCRIPT` / `STYLE` 父节点。

**视频号删除视频后重传会卡在上传 0%。** 删 → 确认 → 重传，进度永久停 0%，只能刷新（内容会清空）。
所以必须一次传对文件，没有「传错再换」这条路。

**抖音话题必须回车。** 输入 `#话题名` 后按 `Enter`，下拉首项就是精确匹配。
用 `el.click()` 无效，用 CDP 点坐标会点到隔壁那条（列表会重排）。

**抖音刷新即清空。** 内容没提交前刷新页面，标题描述话题全没，得重填。

**抖音「暂存离开」不保存。** 点完回上传页，内容管理和首页都找不到草稿。
别拿它当草稿用。

**抖音封面编辑器是图层式。** 上传的图会进时间轴但画布不切换，`完成` 按钮要等有效封面才可点。
脚本不处理，让人手动设。

**抖音登录态撑不过 reload，用连续会话现场驱动（2026-11-07 实测）。** ego 任务空间
存储隔离，抖音 passport 登录后页面一刷新就掉回登录页——所以 release.sh 开头的
`Page.reload` 每次都会杀掉刚扫的码。解法：用户扫码后**不要重跑 release.sh**，
在同空间开连续会话现场驱动全程零刷新：
`taskSpace('publish douyin video')` 挂载 → `uploadFile('input[type=file]')` →
`fillInput(TITLE_SEL)` → 编辑器 `Input.insertText` 描述 → `caretToEnd` + `#话题` +
`pressKey('Enter')` 逐个挂话题。注意 `caretToEnd` 是 douyin.mjs 内部函数需内联，
`fillInput/uploadFile/pressKey` 是 ego 全局可直接用。
实测发布不再触发短信验证（2026-11-07，此前 stage 模式 assumed 必有）。

**小红书发布按钮在 closed Shadow DOM 里。** `<xhs-publish-btn>` 内部拿不到，
常规 `click()` 全部失效，只能 `host._onPublish()` / `host._onSave()`，
调用前先查 `submit-disabled` / `save-disabled` 属性判断是否可用。

**小红书自定义封面失败不再阻断发布（2026-11-09 实测）。** 平台改版后「编辑封面」入口会消失
（`E_COVER_ENTRY_HIDDEN`），旧逻辑直接 exit 60 中断，等于为一个封面放弃整条发布。
现在降级为警告，改用平台自动生成的三张 PK 封面试选候选帧——效果反而更贴视频本身。

**小红书话题必须从下拉点选。** 直接插入 `#话题名` 只是纯文本，不算挂载。
流程是：输入 `#话题` → 等 `#creator-editor-topic-container` 出现 `.item` → 点 `.name` → Escape。

**视频号短标题字符白名单（2026-11-07 实测）。** 短标题含逗号（，）等非法符号时，
**保存草稿/手机预览/发表三个按钮全部静默禁用**（`weui-desktop-btn_disabled` class），
无任何可见报错。官方规则：符号仅支持书名号、引号、冒号、加号、问号、百分号、
摄氏度，**逗号用空格代替**。
`channels.mjs` 的 TITLE 预处理必须先把 `，` 换成空格。

**排障铁律：按钮整行禁用 → 先查校验，别查网络。** 遇到「点了没反应/按钮灰」，
第一动作是把整页（含滚出视口的区域）的校验红字、必填提示全找出来
（`sr.textContent` 搜「不支持/仅支持/超出/请输入/错误」），
其次才是查网络请求和状态机。本次在网络层空转了一小时，实际是表单校验不过。

**ego 排障必须用脚本同款空间名。** `claimTaskSpace(N)` 之后要
`taskSpace('publish channels video')`（脚本里的 acquireSpace 同名空间）
才能连到脚本那个 tab——挂到自己的调试空间看到的是别的 tab，
会得出「表单丢了/内容清空」的错误结论。

**ego 任务空间存储隔离，登录必须发生在脚本要用的那个空间里。**
在空间 A 里扫码登录 → 清理 A → 新开空间 B，登录态随 A 销毁。
跨空间复用登录态不可行；重跑失败发布时**不要清理脚本空间**，
直接同名 acquireSpace 复用（脚本自带 reload 会重载页面但登录还在）。

**位置权限弹窗会让 ego 静默交出控制权（2026-11-05 实测）。** 小红书创作平台
请求 geolocation，Chrome 弹授权框 → ego 判定需要用户 → 脚本所有浏览器命令
被拒、挂起后被杀（exit 90，缓冲输出全丢）。根治：完全退出 ego-lite 后写
`Default/Preferences`（default geolocation=2 + `creator.xiaohongshu.com:443,*`
例外 block）再重启。另外 stdout 走管道是缓冲的，进程被杀全丢——
排障探针必须用 `process.stdout.write` 直写，别用 console.log。
下拉没出来时重试一次，常见于刚打完字或网络慢。

**小红书点编辑区会被发布按钮挡住。** `click('div.tiptap')` 会报
`<xhs-publish-btn> intercepts pointer events`，要用 `el.focus()`，不要 click。

**小红书草稿只在本地。** 「草稿箱」面板改版后入口挪到右上角且点不开，
要验证内容得直读 IndexedDB `draft-database-v1` 的 `video-draft` / `image-draft`，
按 `timeStamp` 倒序取最新（不能取数组末尾，主键是 draftId 字符串）。

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

## 2026-11-09 新增能力（历史题材 + 发布链路加固）

### 一条龙：历史题材口播视频

```bash
SKILL=~/.workbuddy/skills/video-multi-release
PROJ=/path/to/project

# 0) 先估时长，别等配完音才发现超时（原稿 1036 字 ≈ 245s，目标 180s 只能砍字）
python3 $SKILL/scripts/estimate.py --script voice_script.json --target 180

# 1) 古风卡片（自动套 history 主题 + 自动留白定位）
python3 $SKILL/scripts/gen_cards.py --script voice_script.json --images images/ \
  --content-type history --out-dir assets

# 2) 配音（会自动先打印一次时长预估）
python3 $SKILL/scripts/tts.py --script voice_script.json --preset male-narrative --out-dir voice

# 3) 渲染 + 混音（历史暗色主题必须带 CANVAS，否则米白画布出白框）
CANVAS_BG=#0a0806 CANVAS_STOPS='#0b0806,#0a0806,#100c08,#080604' \
  bash $SKILL/scripts/rebuild.sh $PROJ
```

`rebuild.sh` 现在会自动产出 `out/sync_check/contact_sheet.png`（音画同步联系表，
`VERIFY=0` 可跳过），并在混音后删掉 `out/silent.mp4`（`KEEP_SILENT=1` 保留）。

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

### 发布链路加固

| 项 | 行为 |
|---|---|
| 体积 | `release.sh` 检测视频超过 `MAX_VIDEO_MB`（默认 40），自动转 `final_web.mp4`（crf24/2600k）再发；`MAX_VIDEO_MB=0` 关闭。**源文件比压缩版新就重转**，避免换片后复用旧压缩版 |
| 抖音上传 | 轮询到 `上传中 / 正在上传 / 取消上传 / xx%` 全部消失、且至少过了 4 轮才允许点发布；出现「上传失败」立即报错；等不到报 `E_UPLOAD_NOT_FINISHED` |
| 抖音发布后 | 回作品列表确认标题出现 + 读作品数，查不到报 `E_PUBLISH_UNCONFIRMED`（**不再只看 URL 跳转**） |
| 视频号发布后 | 回列表 shadowRoot 查标题，查不到只告警（列表不一定显示短标题），OK 块输出 `verified: yes/manual`；45 秒没跳转**不再兜底重复点发表** |
| 三平台话题 | 挂不上的都只告警、继续发布，输出 `topics_missing`；抖音话题循环幂等且 `RESUME` 时只核对不重插 |
| 现场复用 | `SPACE_ID=…` 或 `RESUME=1` 时跳过 `Page.reload`，且已在编辑页就跳过上传和重复填表；**`MODE=publish` 会强制忽略 `SPACE_ID`**，防止拿旧现场重发造成双发 |
| draft | 抖音无可靠草稿箱接口，`MODE=draft` 退化为 stage（只准备不提交）；小红书/视频号走各自草稿 |
| 汇总 | 每个平台显示 `published/stage`、URL、`verified`、缺失话题。**必须有 `=== OK (...) ===` 块才算成功**；`CONTINUE_ON_FAIL=1` 时退出码保留第一个失败平台的码 |
| BGM | 比成片短时自动 `-stream_loop -1`（`Frost Waltz` 135.5s 曾让 158s 片尾静音） |
| 配置 | 默认值在数据目录 `config.json`：`account` / `tag` / `topics` / `hot_topics` / `bgm` / `canvas_*` |

### 新增踩坑（2026-11-09 实测）

**抖音「编辑页就绪」≠「上传完成」，跳到管理页 ≠ 发布成功。**
78MB 原件时编辑页 24 秒就出来，页面仍显示「已上传 15MB/23MB」；
此时点发布会跳到 `content/manage?enter_from=publish`，看着像成功，
**作品数纹丝不动**。同一文件压到 25MB 后 18 秒传完才真发出去。
判定发布成功一律以「作品列表里出现标题」为准。

**视频号上传 78MB 必然超时。** 160 秒死线，同文件小红书 83 秒能过。
压到 25MB（crf 24 / maxrate 2600k）后 18.6 秒完成，抽帧看画质无差。
结论：视频号先压再传，别反复重试。

**`SPACE_ID` 复用时不能无条件 `Page.reload`。** 抖音 passport 登录态撑不过刷新，
刷新还会清空已填的标题/描述/话题 —— 用户刚扫完码，一重跑全没了。

**抖音手工补话题别用退格。** 编辑器里话题标签是整体一个单元，
连按退格会连已挂上的标签一起删（实测误删 `#历史真相`）。
挂不上的宁可留成纯文本，也别去清。

**暗色主题的画布底色必须显式传。** `build_composition.py` 原本写死米白
`#faf7f2`，近黑卡片外面会套一圈刺眼白框；且 `rebuild.sh` 每次重生成
`index.html`，手工 patch 会被覆盖。现在走 `--canvas-bg` / `--canvas-stops`。

**TTS 之前先估时长，不要靠压 `rate`。** 实测 `male-narrative` rate=1.12
约 3.7 字/秒，1036 字 → 245s。`estimate.py` 会直接算出「需砍多少字」；
`tts.py` 也会在每段标出 >10s / <5s 的节奏不均段落。

---

## 2026-11-10 全检复盘：视觉质量不能抽样

### 教训

18 张卡片做完只抽查 6 张（02/06/10/14/15/18），得出「5/6 完全避开人物头部」，
对外报成合格。**全检后发现第 01 张（钩子卡，最重要）文字正好压在秦始皇额头/眉眼上** ——
抽的 6 张恰好漏掉了最糟的一张。另有 02/13/15 压住车驾、宫殿飞檐、长城墙体。

**铁律：卡片生成后必须全检所有张，不能抽样。** `gen_cards.py` 现在生成完会自动调用
`cards_contact_sheet.py`，产出 `<out-dir>/_check/group_*.png`（每组 6 张，3x2，360px 宽）
和 `all.png`（全部缩略总览）；`--no-proof` 可关闭，但不建议。
逐组看完再进渲染，重点看「白字有没有压住人物头部 / 面部」。

### 为什么算法会漏（根因，非调参能解）

打分明细：img_01 全幅暗调，最优窗口 53.5 分、次优 53.6 分，**差 0.1**。
暗色人脸和暗背景在灰度上几乎不可分，算法其实没有信号，只是险胜选了 top，
把文字推到额头。06/13/18 这类「主体集中在下半部」的图，top 分数明显最低，反而很准。

三个结构问题（已修）：
1. 检测窗口 40 行（33% 画高）比实际文字块（约 22%）大一半，
   窗口里空的部分替有脸的部分「背书」→ 改为 28 行、步长 6。
2. 评分用整行 90px 全宽，左右暗角会稀释五官边缘信号
   → 改为只评文字覆盖区（x ∈ 10%~90%），结构梯度权重 6 → 8。
3. 18 张里 12 张都选 top，全挤在标签（y=130）下方，节奏单调
   → 对 y_ratio < 0.30 加轻微惩罚。

### 置信度机制（关键）

`find_safe_area.py` 现在输出 `confidence` 与 `gap`（**次优 − 最优**的分数差，恒为正）：

| gap | confidence | 处理 |
|---|---|---|
| ≥ 10 | high | 直接用 |
| 3~10 | medium | 可用，日志标 `[medium]` |
| < 3 | **low** | 打警告，**必须人工复核并写段级 `text_pos` 固化** |

低置信段落会在 `gen_cards.py` 末尾汇总列出。本项目 5 张 low（s02/s10/s12/s14/s16）
全部人工确认后写进 `voice_script.json` 的 `text_pos`，加上另外两张人工判断更优的
（s01 改 bottom 露脸、s09 改 top 避开城墙），共固化 7 张，剩下 11 张交给算法。
固化后重跑 **0 张 low 告警**，算法也不会再漂移。

⚠️ 滑窗步长 6 / 窗高 28，相邻窗口重叠约 79%，所以 `gap` 的分差系统性偏小：
本项目 18 张实测分布是 `high 1 / medium 12 / low 5`，`high` 本就少见。
这不是 bug —— 5 张 `low` 恰好就是人工复核后判定「必须覆盖」的那 5 张，
判据与人工结论吻合。别照着「≥10 才算有信号」去调阈值，
要改判据就得把全部卡片重新全检一遍。

### 最根本的解法：生图时就给文字留位置

事后找留白永远受「暗色人物 ≈ 暗背景」限制。源头是提示词只写了
「画面暗部留白便于叠加文字」，AI 照样把人脸放正中。
数据目录 `config.json` 的 `image_prompt_presets.history_dark` 已固化硬约束：

> 构图硬约束：主要人物与建筑主体全部置于画面下三分之一；
> 画面上方 40% 保持大面积纯暗留白，不要出现面部、五官或任何高对比细节；
> 两行白色大字将叠加在上方留白区。

下次生图直接拼 `style + composition + 场景描述`。这批 18 张图已定，
源头模板对它们不生效，所以才需要 7 张人工兜底。

### 本次全检结论（最终版 18 张）

| 判定 | 卡片 |
|---|---|
| ✅ 完全避开人物头部与主体 | 01、02、04、05、06、08、09、10、11、12、14、16、17、18 |
| ⚠ 压住非人物主体（无脸，可接受） | 03 船队、07 竹简、13 宫殿飞檐、15 长城山体 |
| ❌ 压住人物头部 | 无（原 01 已修） |

13 / 15 是插画本身没有大片留白，且不涉及人物，按「不能挡头部 + 尽量放空区」
的规则可接受；若要求更严，只能重生成这两张配图。

---

## 2026-11-10 二次审计：修复清单与已知限制

改动推 GitHub 前做了一轮 GLIC（G/L/I/C）审计 + 两个独立审计员交叉复核 + 实测验证。
**审计发现里有误报，复核后没盲改**：置信度 gap「机制失效」被真实 18 张分布推翻
（low 5 张恰是人工确认要覆盖的 5 张）；`config.json` 的 `account`/`tag`/`font_main`
等键被报「无人读取」，实际 `gen_cards.py` 都在读；`rebuild.sh` 前置检查跳过
`index.html` 也是刻意的（它是第 1 步生成的产物，不是输入）。

### 已修（都是可复现问题）

| 文件 | 问题 | 修法 |
|---|---|---|
| `release.sh` | 转码产物 `final_web.mp4` 存在即复用，换了源视频会**发错片** | 源文件比压缩版新（`-nt`）就重转 |
| `release.sh` | `CONTINUE_ON_FAIL=1` 时 `EXIT_CODE` 被下一平台重置，整体 exit 0 掩盖失败 | 循环外累计 `FIRST_FAIL_RC` |
| `release.sh` | 没有 OK 块 / `stage` / `draft` 都被汇总成「✅ 成功」；`P_STATE` 只认纯小写 | 成功必须有 `=== OK (...) ===`，正则放宽 `[^)]*`，兜底改「已确认」 |
| `release.sh` | `publish` + `SPACE_ID` 会拿旧现场重新上传提交，造成双发 | publish 强制忽略 `SPACE_ID` |
| `release.sh` / `rebuild.sh` | `read_cfg` 的 `2>/dev/null` 配合 `set -e` 让配置损坏时无诊断退出 | 保留报错并打告警，回退空值 |
| `douyin.mjs` | 上传完成判据要同时出现「重新上传」、且 busy 只认「已上传：」，与真实文案「已上传 15MB/23MB」不符 → **永久等不到信号** | 改为「上传中/正在上传/取消上传/xx% 全消失且至少 4 轮」，补上传失败立即报错；与 11-09 实测成功脚本口径一致 |
| `douyin.mjs` | `MODE=draft` 没有分支，会一路走到真的点「发布」 | draft 退化为 stage |
| `douyin.mjs` | `RESUME` 时话题循环仍会往描述末尾重复插文本 | 只核对已挂标签，不重插 |
| `xhs.mjs` / `channels.mjs` | 注释写「话题缺失不影响发布」，实现却 `fail(EXIT.TOPIC)` 整条终止 | 降级为 `topics_missing` 告警并继续发布 |
| `channels.mjs` | 30 秒没跳转就「兜底再点一次发表」，第一下其实已提交时会双发 | 去掉重复提交，等待延到 45 秒，交给列表核验 |
| `build_composition.py` | 末卡也叠 gap，结束时间比 `total` 晚 `gap` 秒（实测 158.984 vs 158.484） | 末卡 `visible = audio + tail` |
| `cards_contact_sheet.py` | 补黑帧写死 4:3，卡片非 1080×1440 时 hstack 报错、全检表缺失 | 按首张卡片真实宽高算尺寸，缩略图统一 pad |
| `gen_cards.py` | 全检联系表失败被静默降级、仍以成功收尾（违反「全检铁律」） | 打印 stderr 并非 0 退出 |
| `rebuild.sh` | 只有 `set -e`，`| tail` 吞掉渲染/混音失败码，拿旧 `final.mp4` 误报成功 | 加 `set -o pipefail`；**不要**在混音前 `rm -f` 旧成片（会触发沙箱批量删除保护、把混音整个拦下），靠 ffmpeg `-y` 覆盖即可 |
| `tts.py` | 时长预估 `except Exception` 全吞，`--target` 静默失效 | 传了 `--target` 且预估失败时直接退出 |
| `find_safe_area.py` | `axis=both` 的左右评分用整行（含暗角），与 vertical 口径不一致 | 统一用 `X0..X1` 文字覆盖区 |
| `card_generator.py` | 极端 `x_ratio` + `anchor` 文字溢出画面；安全区上下界交叉时整段跳过 clamp | 起点 clamp 进可行域；交叉时至少从安全区顶部起排 |
| 两侧文档 | xhs 主题数 28→29、照片主题 3→4；版本 `2.0.1→2.0.2` / `1.2.1→1.3.0`；gap 符号写反；时间轴公式 | 已同步，CHANGELOG 补 v2.0.2 条目 |

### 已知限制（有意未改，别当 bug 重复报）

- **`--text-x-ratio` / `--text-anchor` 在自动留白检测开启时被覆盖**：自动检测只给 `y`，
  默认 `axis=vertical` 恒返回 `x=0.5 / middle`。要改水平位置先加 `--no-auto-safe-area`。
  同理，这三个位置参数只对生成器的 `text` 布局生效，`image-text` 布局仍固定居中。
- **发布后核验「重跑同标题可能误判」**：三个平台都靠「列表里出现标题」判定，
  没有记录发表前的作品数。删旧稿重发时旧作品已不存在、判据可靠；
  但若只是原地重跑，列表里的旧作品会直接命中。发布后仍应人工比对作品数 +1。
- **`config.json` 里 `topics_history_extra` / `image_prompt_presets` / `_canvas_dark_preset`
  没有脚本消费者**：前两个是给生图提示词用的模板，第三个是手动环境变量的备忘，
  都是「文档即用途」，不要指望配了就自动生效。
- **`timeline.json` 落在 CWD**（`--out` 改的是 `index.html` 路径）；`hot_topics.py` 的
  `STOP` 是死代码；这两处属 INFO，未改动。
