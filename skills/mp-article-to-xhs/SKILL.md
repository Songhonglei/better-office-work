---
name: mp-article-to-xhs
description: >
  把微信公众号文章自动转成小红书图文笔记。三条选题路径：指定文章链接、按标题关键词匹配、
  或按公众号后台阅读数出热度候选再随机挑。自动抓取正文与全部配图（含懒加载，硬校验一张不漏），
  裁掉公众号水印，生成「上图下文」3:4 卡片，默认只推送到小红书草稿箱（只有用户明确要求才直接发布）。
  已处理过的文章自动跳过，绝不重发。
  触发词：公众号转小红书、文章生成笔记、生成小红书图文、mp2xhs、把这篇公众号做成卡片。
version: 1.3.0
bins: [node, python3, ego-browser]
python: [Pillow, PIL]
depends_on_skills: [xhs-image-note-release]
metadata:
  openclaw:
    requires:
      bins: [node, python3, ego-browser]
      python: [Pillow, PIL]
    emoji: "📱"
---

# mp-article-to-xhs

公众号长文 → 小红书图文笔记。解决三件事：**选题不靠人肉翻**、**图片一张不漏**、**发过的不重发**。

## 依赖

| 依赖 | 用途 | 必需 |
|---|---|---|
| **ego-browser**（ego-lite） | 抓公众号后台、发布小红书 | ✅ |
| **Python 3.8+** | 编排脚本 | ✅ |
| **Pillow** | 裁掉公众号水印 | ✅ |
| **Chrome / Chromium** | 把 HTML 渲染成卡片 PNG | ✅ |
| **xhs-image-note-release**（skill） | 真正执行发布动作的底座 | ✅ |
| 中文字体（宋体/黑体） | 否则卡片全是方框 | ✅ |

## Dependencies

Python 包（需自装）：`Pillow`
系统命令（需自装）：`ego-browser`、`chrome`/`chromium`、`node`、`python3`
Skill 依赖：`xhs-image-note-release`（发布底座，本 skill 不自带）

## 装到新机器：三步

```bash
# ① 自检，缺什么它直接告诉你，并给安装命令
python3 ~/.workbuddy/skills/mp-article-to-xhs/scripts/doctor.py
```

`doctor.py` 会逐项检查并打印对应安装指引（macOS / Linux / Windows 分别给命令），必需项缺失时退出码 1。

```bash
# ② 按 doctor 的提示补装，典型是这四件
sh ~/.workbuddy/skills/ego-browser/scripts/install.sh     # ego-browser + ego-lite
pip3 install Pillow                                        # 或复用 WorkBuddy 自带 pillow 环境
brew install --cask google-chrome                          # Linux: sudo apt install chromium-browser
# Linux 还要中文字体，否则卡片出方框：
sudo apt install fonts-noto-cjk fonts-wqy-zenhei
```

```bash
# ③ 手动登录一次（脚本无法代劳，也不能代劳）
#   在 ego-lite 浏览器窗口里登录：
#     · mp.weixin.qq.com         公众号后台，抓文章用
#     · creator.xiaohongshu.com  小红书创作平台，发布用
```

> 自检通过后再跑流程。`doctor.py` 里登录态只做提示不做检测——那需要真的开浏览器。

> WorkBuddy 环境需先关闭沙箱，否则 ego-browser 会被系统中断。

> **不要同时跑两篇**：参数文件路径是固定的（ego-browser 的 daemon 不继承环境变量，只能走文件传参），并发会互相覆盖。串行跑，每篇几分钟。

### 缺 xhs-image-note-release 时

本 skill 的发布环节直接调用它的 `~/.workbuddy/skills/xhs-image-note-release/scripts/publish_note.sh`（省得重写一套 `_onPublish`/`_onSave` 的点击逻辑）。获取方式：GitHub `Songhonglei/better-office-work`（`skills/mp-article-to-xhs/`），或在 WorkBuddy 里说「安装 xhs-image-note-release skill」。装完确认这个文件存在：

```bash
ls ~/.workbuddy/skills/xhs-image-note-release/scripts/publish_note.sh
```

## 五步流程

`<slug>` 是每篇的工作目录名，统一取「标题去掉标点后的前 12 个汉字」，如 `三星堆在象牙上画眼睛`。同一篇必须始终用同一个 slug——后续 `--reuse`、卡片图片引用都靠它对齐。

```bash
SK=~/.workbuddy/skills/mp-article-to-xhs

# ① 选题（三选一）
python3 $SK/scripts/pipeline.py pick --mode hot  --top 8          # 按阅读数出候选池
python3 $SK/scripts/pipeline.py pick --mode title --value 象牙      # 标题关键词模糊匹配
python3 $SK/scripts/pipeline.py pick --mode url --value https://mp.weixin.qq.com/s/xxx

# ② 抓正文 + 全部配图（自动裁水印）
python3 $SK/scripts/pipeline.py fetch --url "<URL>" --out ./<slug>

# ③ 写 cards.json（这一步由 AI 完成，见「卡片规范」）
# ④ 校验图片完整性（不通过会非零退出，必须拦住）
python3 $SK/scripts/pipeline.py check --out ./<slug> --cards ./<slug>/cards.json [--exclude clean/img2.jpg]

# ⑤ 渲染 → 推草稿箱（默认，不对外发布）
python3 $SK/scripts/pipeline.py render --cards ./<slug>/cards.json --out ./<slug>/cards --typeface modern
bash $SK/scripts/publish.sh --dir ./<slug>/cards --title "<≤20字>" \
     --body-file ./<slug>/body.txt --topics "历史冷知识,三星堆"   # 直接发布才加 --publish
python3 $SK/scripts/pipeline.py mark --url "<URL>" --title "<标题>" --status drafted --cards 7 --images 6
```

### 脚本清单

| 文件 | 干什么 | 谁调用 |
|---|---|---|
| `scripts/list_articles.js` | 拉公众号「发表记录」，出标题/URL/阅读数/时间 | `pick` 子命令经 ego-browser 执行 |
| `scripts/fetch_article.js` | 打开单篇，滚动触发懒加载，抓正文 + 下载全部配图 | `fetch` 子命令经 ego-browser 执行 |
| `scripts/pipeline.py` | 编排：选题 / 抓取 / 校验 / 渲染 / 登记状态 | 直接跑 |
| `scripts/mp2xhs_card.py` | 按 `<slug>/cards.json` 渲染 1080×1440 卡片 PNG | `render` 子命令调用 |
| `scripts/publish.sh` | 发布包装，**默认草稿箱**，仅 `--publish` 才直发 | 直接跑 |
| `scripts/doctor.py` | 依赖自检，缺什么给安装命令 | 部署后先跑一次 |

两个 `.js` 不能单独跑，必须经 `ego-browser nodejs` 喂进去——它们依赖 ego-browser 注入的 `js()` / `openOrReuseTab()` / `wait()` 等 API。

### 退出码

脚本用退出码区分失败原因，别把所有非零都当成"再跑一次"：

| 退出码 | 来源 | 含义 | 怎么处理 |
|---|---|---|---|
| 1 | 任意 | 参数错误 / 依赖缺失 / 前置未满足 | 看 stderr，补参数或装依赖 |
| 2 | `fetch` | 图片下载不全（页面有 N 张，只下到 M 张） | **不要往下走**，查 `<slug>/article.json` 的 `imgFailed`，必要时手工滚动重抓 |
| 3 | `check` | 图片完整性校验没过（漏图 / 重复 / 引用了不存在的文件） | 按 `problems` 逐条改 `<slug>/cards.json`；合规剔除要显式 `--exclude` |

### pick 三种模式

| 模式 | 行为 | 适用 |
|---|---|---|
| `hot` | 拉后台发表记录，按**阅读数降序**出前 `--top` 篇候选（已处理的自动剔除），并给一个随机 `suggest` | 「随便挑一篇热度高的」 |
| `title` | 标题包含关键词即命中；若命中的全都做过，返回 `blocked` | 用户明确点名某篇 |
| `url` | 直接用给定链接；做过则返回 `blocked` | 用户给了链接 |

`hot` 每次要开 2-3 次后台列表页（每页等 5 秒），`--count 40` 整体约 30-40 秒，属正常，别以为卡住了。

`hot` 输出的是**候选池**，最终选哪篇由 agent 判断——纯随机容易撞上「上海徐汇滨江的日常」这类日常随笔，不适合做知识卡片。

选题时排除：
- 伪史论话题（用户已明确停做）
- 时事政治、涉政人物
- 阅读数极低（< 500）且无信息增量的日常随笔

### fetch 做了什么

1. 打开文章，**反复滚动到底触发懒加载**（步长 1200px，滚动 2 轮直到图片数稳定）——不滚动会漏掉未进视口的图
2. 枚举 `#js_content img`，记录 `data-src` / `data-w` / `data-ratio` / 每张图前一段文字（用于判断配图归属）
3. `/640` 换成 `/0` 取原尺寸，**必须带 `Referer: https://mp.weixin.qq.com/`**（图床防盗链）
4. 裁掉底部 25%：公众号图片右下角有「公众号 · 账号名」水印，**这是小红书明令的站外引流词**，必须清除
5. 输出 `<slug>/article.json`，含 `imgTotal` / `imgDownloaded` / `imgFailed`

默认按 `max(200px, 图片高度 20%)` 裁（实测 3:2 图只需 140px、横幅图要 200px，用固定百分比会把 3:2 图的人物切狠）。发现水印没裁净，用 `--crop-pct 0.28` 加大；构图被切太多则调小。

调样式时加 `--reuse` 跳过重抓——它会校验 `<slug>/article.json` 里的 URL 与本次是否一致，防止拿 A 篇的图配 B 篇的卡。

## 卡片规范（AI 提炼这一步）

产物是 `<slug>/cards.json`，直接喂给 `mp2xhs_card.py`：

```json
{
  "account": "@雨夜心灯",
  "tag": "历史冷知识",
  "seal": "夜",
  "typeface": "classic",
  "pages": [
    {"kicker": "", "title": ["行1","行2"], "note": ["说明1","说明2"],
     "image": "clean/img1.jpg", "pic_h": 640}
  ]
}
```

- `image` 相对 `<slug>/cards.json` 所在目录；省略即纯文字页
- `pic_h` 图区高度，默认 640；横幅头图建议 560，避免裁掉两侧主体

提炼要求：

| 位置 | 作用 | 字数 |
|---|---|---|
| `title` | 每页的核心论点，2 行 | 每行 ≤ 9 字（模板按最长行自动缩字号，超过 10 字会明显变小） |
| `note` | 解释/细节，2 行 | 每行 ≤ 16 字 |
| `kicker` | 页码式小标题，如 `01 · 帽子` | ≤ 8 字 |

排版节奏（实测有效）：

- **封面**：用全文最抓人的一张图（常是文章头图），标题是**反常识钩子**，不写总结
- **中间页**：每页只讲一个点，论点在大字、解释在 `note`
- **结尾**：用文章的收束句，别再抛新信息
- 7 页左右最舒服；6 图 7 页时留 1 页纯文字调节节奏，避免连续两页都是纯文字
- **硬上限 18 张图**（小红书图文上限），`publish.sh` 会拦；想放更多内容就合并页，别硬超
- 页与页之间图/文交替，不要连着 3 页同构

### 字体方案（按内容气质选，别一套用到底）

八套 preset，靠「字族 + 字重 + 字距」区分气质。前三套纯系统字体，后面几套用 webfont 加性格：

| 方案 | 标题 | 正文 | 气质 | 适合的内容 |
|---|---|---|---|---|
| `classic` | 宋体 600 | 宋体 | 古雅、书卷 | 历史、人文、旧事、考据 |
| `modern` | 黑体 600 | 宋体 | 清楚、现代 | 知识科普、考古、人物、清单 |
| `soft` | 细宋 300 | 黑体 | 轻、留白、抒情 | 随笔、感悟、生活、情绪 |
| `gufeng` ⭐默认 | 站酷小薇 400 | 宋体 | 圆润古意、器物感 | 文化、古建、器物、旧朝 |
| `qingke` | 站酷庆科黄油 400 | 宋体 | 粗圆黑、旧海报 | 清单、器物、知识点、标签式标题 |
| `brush` | 马善政毛笔行楷 | 宋体 | 手写题字、笔锋 | 短标题（≤10 字）、金句页 |
| `mags` | Playfair + 思源宋 300 | 思源宋 | 细瘦编辑感、西文出彩 | 年份/人名/西文多的篇目 |
| `dossier` | 思源宋 700 | 思源宋 | 厚重、卷宗档案 | 考据、数据、年代考 |

- 优先级：命令行 `--typeface` > `<slug>/cards.json` 顶层 `"typeface"` > 颜色主题默认（ink/gold → `gufeng`）
- 判断口径：偏叙事怀旧 → `classic`/`gufeng`；偏讲清楚一个知识点 → `modern`；偏情绪和留白 → `soft`；标题短又有书法味 → `brush`
- 前三套纯系统字体，字体栈写了跨平台 fallback（macOS 宋体/苹方 → Linux 思源/Noto → Windows 雅黑/宋体），换机器不会直接崩
- **中文字体本地缓存**（v1.3.0）：`gufeng` / `qingke` / `brush` 用到的站酷小薇、庆科黄油、马善政首次渲染时自动下载到 `~/.cache/mp2xhs/fonts/`（jsDelivr 源，OFL 授权），之后直接内嵌 `@font-face` 指本机文件——**离线也能渲染**，单页约 10s
- `mags` / `dossier` 用到的思源宋、Playfair、IBM Plex Mono 字重多、体积大，走 `https://fonts.font.im` 按需子集；CDN 挂掉自动落到本地宋体/黑体，不糊版
- 下载失败不会中断出图：`ensure_local_font()` 打一行提示就回落到 CDN，两处都断则用系统字体
- 标题字数 ≤10 再考虑 `brush`：行楷连笔，长句会糊成一片

实测教训（改字体前先读）：
- **mags 的中文别用 600 字重**：思源宋 600 和宋体 600 肉眼几乎无差别，必须靠 300（细）或 700（粗）才拉得开反差
- **Chrome 别加 `--user-data-dir` / `--disk-cache-dir`**：前者会让第二次渲染抢 profile 单例锁、后者直接不出图，两个参数都实测挂死。字体缓存由脚本自己做（见上），不要再交给 Chrome
- **本地字体要用 `--allow-file-access-from-files`**：`file://` 页面加载 `file://` 字体属跨源，不加这个 flag 会被 CORS 拦掉，标题静默回落成宋体
- **别用 Yuanti/圆体做标题**：简体汉字覆盖不全，很容易整行 fallback 成混排

想换成别的字体（霞鹜文楷、思源宋体等）：改 `scripts/mp2xhs_card.py` 顶部的 `SERIF_STACK` / `SANS_STACK` 常量，或新增一条 `TYPEFACES` 条目（带 `font_css` 就会自动 `@import`，带 `mono` 会让页脚页码用等宽字）。

## 四条硬规矩

### 1. 图片一张不能漏

`check` 会把「抓到的图」与「卡片里用上的图」做集合比对：

- 下载数 ≠ 页面图数 → 报错
- 有图没进卡片且未声明剔除 → 报错（退出码 3）
- 同一张图重复用在多页 → 报错

**只有一种情况可以不用图**：内容有合规风险（涉性、血腥、族群刻板印象），此时必须显式 `--exclude clean/imgN.jpg` 声明，并在汇报里说明原因。这样「漏图」是主动决策而非疏忽。

### 2. 发过的不重发

状态库：`state/published.json`。`pick` 时按 **URL 或规范化标题** 双重排除，命中即 `blocked`。

`mark` 必须真正执行，否则下次会重复：
- 推了草稿 → `--status drafted`
- 发布了 → `--status published`
- 主动跳过 → `--status skipped`

查看清单：`python3 $SK/scripts/pipeline.py status`

### 3. 默认发草稿，发布要用户明确点头

`publish.sh` 不传 `--publish` 就是草稿箱。**任何情况下不要自己替用户决定直接发布**——公众号转小红书是对外动作，错发一条要删、还可能影响账号权重。

- 用户说「发小红书」「做成笔记」「推草稿箱」→ 草稿
- 用户说「直接发布」「发出去」「不用存草稿」→ 才加 `--publish`
- 拿不准就问一句，别猜

### 4. 小红书合规红线

- 图片里的「公众号 · 账号名」水印必须裁掉
- 标题/正文/话题里不得出现「微信搜索」「公众号」「加微信」「扫码」
- 只允许 `@账号名` 软性署名
- 标题 ≤ 20 字，正文 ≤ 1000 字，包含 `#话题` 时正文里不要再手写话题（发布脚本会逐个从下拉词条挂载）
- 话题 6-8 个为宜

## 发布

**默认走草稿箱。** 只有用户明确说「直接发布 / 发出去 / 不用草稿了」，才加 `--publish`。

```bash
bash $SK/scripts/publish.sh \
  --dir ./<slug>/cards \
  --title "<≤20字标题>" \
  --body-file ./<slug>/body.txt \
  --topics "历史冷知识,三星堆,考古" \
  # 可选：--images 01.png,02.png  省略则自动收集目录下全部 png 按名排序
  # 可选：--publish                仅当用户明确要求直接发布时才加
```

包装脚本把 `MODE` 写死默认为 `draft`，并在跑之前回显模式、图片数、标题字数、正文字数，先核对再发。正文里的换行会自动转成字面 `\n`（`~/.workbuddy/skills/xhs-image-note-release/scripts/publish_note.sh` 内部还原），段落之间留一个空行。

看成功不看退出码，看这四项：`editCount` 等于图数、`cdnImages` ≥ 图数、话题全部 `clicked:true`、`草稿箱(N)` 计数 +1（draft）或 URL 含 `published=true`（publish）。

> 草稿存在**当前浏览器本地**（小红书页面原话："草稿存储于当前使用的浏览器本地，在清除浏览器数据时会被删除"），不跨设备、手机上更看不到。推完要提醒用户趁现在去草稿箱点发布，别以为已经进账号云端了。

## 已知坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 只抓到 4 张，实际 5 张 | 懒加载未触发 | fetch 已内置滚动；仍缺则手工滚动确认 |
| `Runtime.evaluate timed out` | 把整个滚动循环塞进一个 async `js()` 表达式 | 拆成多次短调用，不要写长 async |
| 图下载回来是 0 字节 | 缺 Referer | 微信图床必须带 referer |
| `cannot write mode RGBA as JPEG` | 图片带透明通道 | 保存前 `convert("RGB")` |
| 环境变量传不进 `ego-browser nodejs` | daemon 不继承 env | 参数走 JSON 文件（`/tmp/mp2xhs_*_params.json`） |
| 草稿箱里出现「暂无笔记标题」废草稿 | 反复进出编辑页自动产生 | 手动清理，勿在短时间反复跑同一篇 |
| 个别字变成实心黑方块（「回」「圃」等） | 站酷小薇（ZCOOL XiaoWei）字形缺陷：内轮廓绕向与外轮廓相同，按填充规则被整块填满——Chrome 与 Pillow 表现一致，不是渲染或缓存问题 | 换掉该字，或把方案改成 `brush`/`classic`。**`gufeng` 出图必须逐页看图**，黑块在缩略图上很明显 |

## 产物结构

```
<slug>/
├── article.json      # 标题/正文/图片清单/抓取校验
├── imgN.jpg          # 原图（带水印）
├── clean/imgN.jpg    # 裁掉水印，卡片实际用这个
├── cards.json        # 卡片内容（AI 提炼产物，可改后重渲染）
└── cards/01.png...   # 最终卡片 1080×1440
```
