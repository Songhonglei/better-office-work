# 平台规格与踩坑记录

> ⚠️ **本文件截至 2026-11-02。** 其中「上传完成判据」「视频号成功标志」「抖音封面不要自动化」
> 三处结论已被 2026-11-09 / 11-10 的修复推翻，**冲突时一律以 SKILL.md 为准**。
> 只在改选择器、新增平台、排查 DOM 结构时读；日常发布不要读。

全部结论来自 2026-11-02 的实测，不是文档抄的。

## 视频规格

| | 视频号助手 | 抖音创作 | 小红书 |
|---|---|---|---|
| 比例 | 0.33 ~ 3.0（建议 16:9 / 9:16） | 16:9 / 9:16 / 3:4 / 4:3 / 9:19.5 | 9:16 / 3:4 |
| 时长 | 3 秒 ~ 8 小时 | ≤ 1 小时 | 无明确上限 |
| 体积 | ≤ 20GB | ≤ 16GB | — |
| 分辨率 | 建议 1080p+ | 支持 4K | — |
| 码率 | 建议 ≥ 10Mbps | 越高越好 | — |
| 编码 | H.264 最稳（H.265 需 Safari/Windows 装扩展） | H.264 推荐 | H.264 |
| 备注 | — | **> 40 秒建议横版** | — |

我们用 1080×1920 / 30fps / H.264 High / yuv420p / bt709 / AAC 48kHz，两边都吃。

**关于码率**：官方说「建议 ≥10Mbps」是针对实拍视频的。静态卡片用 CRF 16 渲出来只有 3.5Mbps，
这不是压出来的，是内容本身压缩效率高，不需要为了凑码率去放大文件。
真正会出问题的是大面积渐变——测过顶部延伸渐变区 120px 内只跨 2~3 个色阶，
这是源本身平缓，提码率解决不了，要加 dither。目前没做，有需要再说。

## 视频号：wujie 微前端

页面结构：

```
body
└── div.finder-page.MicroPost
    └── wujie-app          ← shadowRoot 在这里
        └── (真实 DOM：.post-desc-box / video / button …)
```

所有查询必须走：

```js
const sr = document.querySelector('wujie-app').shadowRoot
sr.querySelector('.post-desc-box .input-editor')
```

`innerText` 读不到（只有 8 个字符），`textContent` 有 2.8MB（含全部 CSS），
所以判断页面元素要按具体选择器找，别按文本长度猜。

### 关键选择器

| 元素 | 选择器 |
|---|---|
| 描述编辑器 | `.post-desc-box .input-editor`（contenteditable） |
| 话题按钮 | `.quick-btns .finder-tag-wrap`（第一个是 #话题） |
| 话题标签 | `span.topic` |
| 短标题 | `input[placeholder*="短标题"]` |
| 位置 | `input[placeholder="搜索附近位置"]` |
| 合集 | `input[placeholder="有趣的合集标题更容易吸引粉丝"]` |
| 按钮 | `保存草稿` / `手机预览` / `发表`（都是 button） |
| 封面编辑 | `.edit-btn.edit-btn-zIndex` |

### 上传

```js
// uploadFile() 的选择器打不穿 shadow，必须走 CDP
const { root } = await cdp('DOM.getDocument', { depth: -1, pierce: true })
// 递归找 nodeName === 'INPUT' 且 type === 'file' 的 nodeId
await cdp('DOM.setFileInputFiles', { files: [video], nodeId })
```

`pierce: true` 是必须的，否则拿不到 shadowRoot 里的节点。

### 上传完成判定

不能只看 video 有没有 duration。三个条件同时满足才算完：

```js
v.duration > 0 && 有「封面预览」 && 没有「文件上传中」
```

「文件上传中，请等待完成后再发表」这个提示出现时，`发表` 按钮是禁用的，
点了没反应也不要以为按钮坏了。

### 话题

**不需要从下拉里选词条。** 输入 `#人生感悟` 后停留 2 秒左右，自动变成：

```html
<span class="hl topic" data-type="topic">#人生感悟</span>
```

话题之间用空格分隔。加话题前必须把光标移到内容末尾（用 Range + Selection），
否则会插进正文中间。

### 发表

- `发表` 的 JS `click()` **无效**，必须 `Input.dispatchMouseEvent` 真实鼠标
- 先 `scrollIntoView({block:'center'})` 拿坐标，因为按钮在视口外
- 成功标志：URL 跳到 `/platform/post/list`
- 存草稿成功标志：页面顶部出现「✓ 已保存」，且草稿箱能看到

验真时读 `wujie-app`.shadowRoot 的 `textContent`，**按描述首句比对比按短标题可靠**：
列表卡片只渲染描述，短标题不一定进 DOM，拿标题判会误判成没发出去。

### 视频号踩过的坑

**删视频重传会卡 0%。** 点「删除」→ 确认弹窗「删除后需重新上传」→ 点确认 → 重新上传，
进度条永久停在 0%，等 2 分钟不动。只能刷新页面重来（内容全清空）。
**所以一次传对，不要有换文件的流程。**

**换视频后文案会保留。** 这跟上面的坑不冲突：如果没卡住，换视频后描述/话题/短标题都还在。
卡住才需要刷新。

**封面是 3:4（个人主页和分享卡片）。** 默认取视频首帧，够用。

## 抖音

普通 DOM，选择器正常。但有几处必须注意。

### 关键选择器

| 元素 | 选择器 |
|---|---|
| 标题 | `input[placeholder="填写作品标题，为作品获得更多流量"]` |
| 描述编辑器 | `.zone-container.editor-kit-container` 内部的 `[contenteditable="true"]` |
| 话题标签 | `span[style*="rgba(1, 118, 247"]`（蓝底） |
| 话题联想面板 | `.mention-suggest-mount-dom` |
| 发布按钮 | `button` 文本为「发布」 |
| 暂存 | `button` 文本为「暂存离开」 |
| 封面入口 | `.title-wA45Xd` 文本为「选择封面」（两个：竖 3:4 / 横 4:3） |
| 二次验证遮罩 | `.second-verify-mask` |

### 话题：必须回车

输入 `#人生感悟` 后下拉弹出，首项就是精确匹配。然后：

```js
await pressKey('Enter')   // 只有这条路可靠
```

试过三种，只有回车对：
- `item.click()` → 无效，话题保持纯文本
- CDP 点坐标 → 点到隔壁那条（`#人生感悟生活`），因为列表会重排
- 完整事件序列 `mouseover/mousedown/mouseup/click` → 选择器匹配不到（层级太深）

### 封面：不要自动化

抖音封面是图层式编辑器：打开后中间是画布，底部是时间轴（视频帧 + 上传的图片都进时间轴），
左侧是工具栏（AI封面/模板/贴纸/标题文字/滤镜）。

上传的图片会进时间轴但**画布不切换**，`完成` 按钮保持禁用直到有有效封面。
弹窗的关闭按钮是 `svg`，`click` 不是函数，`Escape` 也关不掉。

实测（2026-11-03）：`DOM.setFileInputFiles` 能把图喂进 `input[type=file]`，
二级「设置封面」小窗里能看到图 + 3:4 虚线裁剪框，看起来像成功；
但点「保存」后裁剪区回空白，封面没有持久化——连试两次都一样。
说明这家编辑器要的是内部裁剪状态，不是文件本身。这条路确定走不通，别再试。

结论：封面让人手动设，脚本只负责把其他都填好。

### 发布：卡在短信验证

点「发布」后弹：

```
接收短信验证码
为确保是本人操作抖音账号，请输入当前手机号 189*****12 收到的短信验证码
```

`second-verify-mask` 遮住整个页面，按钮点击一律被拦截（`elementFromPoint` 返回遮罩）。

这是平台级真人验证，脚本绕不过。skill 遇到时退出码 75，
提示用户去窗口里输验证码并点「验证」。

### 抖音踩过的坑

**「暂存离开」等于没存。** 点完 URL 回到 `/content/upload?enter_from=publish`，
但内容管理 `/content/manage` 显示「没有更多作品」，首页也没有「继续编辑」。
跟视频号的云端草稿箱完全不同。

**页面刷新即清空。** 未提交前刷新，标题/描述/话题全没。

**标题 30 字，计数显示在「作品描述」右上角（14/30）。** 填进标题框后，
标题会作为描述区第一行显示，但提交时是分开的字段。

## 小红书

入口：`https://creator.xiaohongshu.com/publish/publish`，SPA，必须等 15 秒。

### 结构特殊之处

发布按钮是自定义元素 `<xhs-publish-btn>`，内部实现在 **closed Shadow DOM** 里，
外部拿不到，常规点击、`el.click()`、CDP 点坐标全部失效。只能调宿主上的方法：

```js
const host = document.querySelector('xhs-publish-btn')
if (host.getAttribute('submit-disabled') === 'true') { /* 必填项没填完 */ }
host._onPublish()   // 发布
host._onSave()      // 存草稿
```

### 关键选择器

| 元素 | 选择器 |
|---|---|
| 视频输入 | `input[type="file"][accept*=".mp4"]` |
| 标题 | `input[placeholder="填写标题会有更多赞哦"]`（20 字） |
| 正文编辑器 | `div.tiptap`（ProseMirror） |
| 话题容器 | `#creator-editor-topic-container`，选项是 `.item`，文字在 `.name` |
| 发布宿主 | `xhs-publish-btn` |
| 封面缩略图 | `.cover` |
| 编辑封面 | `.cover-edit-entry` |
| 封面编辑器 | `.d-modal.cover-modal` |
| 封面上传 | `input[type="file"][accept*="image/png"]` |

### 话题：必须点选词条

直接插入 `#话题名` 只是纯文本。正确流程：

1. 光标移到正文末尾（Range + Selection，不能用 `Control+End`，tiptap 不认）
2. 输入 `#话题名`
3. 等 `#creator-editor-topic-container` 里出现 `.item`
4. 找 `.name` 文本等于 `#话题名` 的项，点击
5. 若 `#tippy-1` 气泡还开着，按 Escape
6. 补一个空格，避免下一个话题粘连

下拉没出来时重试一次即可（刚打完字或网络慢会延迟）。

### 正文编辑器

别用 `click('div.tiptap')` —— 会被 `<xhs-publish-btn>` 拦截指针事件，
报 `intercepts pointer events`。用 `el.focus()` 再 `Input.insertText`。

### 视频封面

`.cover-edit-entry`（「编辑封面」）平时 `boundingRect` 是 `0×0`，只有真实 hover 才渲染。
必须 `cdp('Input.dispatchMouseEvent', {type:'mouseMoved', x, y, button:'none'})`
把鼠标移到 `.cover` 左侧（x 约 +65），等 1.5 秒后才点得到。

「完成」按钮在视口外右侧，要先 `scrollIntoView`。
首屏的 `.pk-cover-guide-tooltip` 会遮挡，先 `display:none`。

成功判定用**封面缩略图的 CDN URL 是否变化**，不要看弹窗有没有关闭——
固定 `wait()` 换成弱轮询条件会导致图片没渲染完就点完成，弹窗关了但封面还是旧的。

### 草稿只在浏览器本地

「草稿箱」面板改版后入口挪到右上角且点不开（`click`、CDP 鼠标事件都无效）。
验证内容要直读 IndexedDB：

```
indexedDB: draft-database-v1
  ├─ article-draft
  ├─ audio-draft
  ├─ image-draft     ← 图文
  └─ video-draft     ← 视频
```

读法：`getAll()` → 按 `timeStamp` **倒序**取最新 → 递归遍历 `content` 找 key 含 `title` 的字符串。
不能取数组最后一项，主键是 draftId 字符串不是时间。

### 发布后怎么验真

`published=true` 只是前端跳转，不等于平台收了。真验要进笔记管理：

- 正确路径 `https://creator.xiaohongshu.com/new/note-manager`（少个 `r` 就是 404）
- 直接访问会被路由守卫踢走，必须从发布页点左侧「笔记管理」菜单（普通文本节点，坐标点击即可）
- 列表第一条应出现标题 + 「审核中」/「已发布」

`creator.xiaohongshu.com/` 根路径即使已登录也会跳 `/login`，别误判成掉线；
判断登录态看 `/publish/publish` 是否留在原地。

### 小红书踩过的坑

**上传必须逐个文件调用 `uploadFile()`。** 批量 `DOM.setFileInputFiles` 只会创建空占位，
编辑器显示「图片编辑 10/18」但缩略图是空白。视频是单文件，不受影响。

**`input.files.length` 判不了上传成功。** 小红书接收文件后立刻清空 `files`，永远读到 0。

**草稿换浏览器就没了。** 只有真正发布过的笔记才进云端。

## Qwen TTS

### 端点

MaaS Token Plan，跟 `token-plan` 的 key 同域，不需要单独开百炼账号：

```
POST https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
Authorization: Bearer <sk-sp-...>
```

`{WorkspaceId}` 就是 `token-plan`。

### 可用模型

`/compatible-mode/v1/models` 列出 21 个，其中语音相关的：

- `qwen-audio-3.0-tts-plus` ✅ 可用
- `qwen-audio-3.0-realtime-plus`（WebSocket 实时）
- `qwen-audio-3.0-asr-flash`（语音识别）
- `qwen-audio-3.1-tts-plus` / `3.1-tts-flash` ❌ 404 `Model not exist`

### 用不了的调用方式

这些全试过，全部失败：

| 尝试 | 结果 |
|---|---|
| `/compatible-mode/v1/chat/completions` + `modalities:["audio"]` | 500 `InternalError: UNKNOWN` |
| 同上 + `stream:true` / content 数组 / voice 放顶层 | 500 同上 |
| `/audio/speech`、`/audio/tts`、`/audio/generations` | 400 `url error`（路径不存在） |
| DashScope 原生 `/api/v1/services/aigc/multimodal-generation/...` | 400 同上 |

只有 `/api/v1/services/audio/tts/SpeechSynthesizer` 这一个入口。

### 参数

```json
{
  "model": "qwen-audio-3.0-tts-plus",
  "input": {
    "text": "...",
    "voice": "qwen-audio-3.0-tts-plus-longdieshuangluan",
    "format": "mp3",
    "sample_rate": 48000,
    "rate": 1.12,
    "instruction": "用成熟女性的声音朗读…"
  }
}
```

- `rate` 范围 0.5 ~ 2.0，默认 1.0
- `instruction` 控制情感/语气/方言，越具体效果越明显
- 返回 `output.audio.url`（24 小时有效，要立刻下载）
- 单次 `text` 上限 600 字符

### 音色怎么挑

官方音色表有两部分：

**系统音色**（3.0-tts-plus）只有两个：
- `longanlingxin` 龙安灵心 · 知心温暖音 · 25 岁 · 女
- `longanlufeng` 龙安鲁风 · 明亮开朗音 · 25 岁 · 男

**基础音色** 597 个，命名 `qwen-audio-3.0-tts-plus-{后缀}`，
官方给了 Excel（含性别/年龄/特质/场景四列）和试听音频包。

要「年长 + 岁月沉淀」，按年龄降序筛女性：
72 岁（神秘术士）、60 岁（慈祥祖母）、54 岁（自信从容）、43 岁、42 岁×3、40 岁（电台质感）、38 岁×2、36 岁（成熟沉稳）。

实际好用的是 36-42 岁那批，再老就偏「祖母音」了。

## 环境约束

**ego-browser 的 nodejs 环境不继承 shell 环境变量**，也不允许 `fetch('file://...')`。
所以 release.sh 采用「把参数拼成 `const PARAMS = {...}` 前置到 mjs 前面再管道输入」的方式：

```bash
{ printf 'const PARAMS = %s;\n' "$JSON"; cat script.mjs; } | ego-browser nodejs
```

**每次调用都要先选定空间**，否则报 `Task space not selected`：

```js
await taskSpace(24)      // 或 useOrCreateTaskSpace() / takeOverTaskSpace()
```

**`js()` 模板字符串里的 `\n` 会被转成真换行**，正则 `/\n+/g` 会失效。
要写 `\\n`，或者用 `String.fromCharCode(10)`。

**不要用 `js()` 返回 DOM 元素**，结构化克隆会失败。
所有 DOM 操作包在 IIFE 里返回原始值。
