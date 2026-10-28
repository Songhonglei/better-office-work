# mp-article-to-xhs

> 把微信公众号长文自动转成小红书图文笔记：抓正文与全部配图（一张不漏）→ 裁水印 → 生成「上图下文」3:4 卡片 → 推草稿箱。默认只推草稿，不对外发布。

## 解决的问题

写公众号和发小红书是两套体力活。这篇文章在公众号发过之后，还要人工截图、排版、配文、上传到小红书。本 skill 把这条链路做成可复现的五步流水线，并且只解决三个真正的痛点：

- **选题不靠人肉翻**：指定链接、按标题关键词匹配、或按公众号后台阅读数出热度候选池
- **图片一张不漏**：滚动触发懒加载 + 集合比对硬校验，漏一张就非零退出
- **发过的不重发**：本地台账按 URL + 规范化标题双重排除

## Features

- **三条选题路径**：`--mode url` / `--mode title` / `--mode hot`（热度候选池，不替你硬选）
- **图片完整性硬校验**：`check` 子命令做集合比对，退出码 2 = 下载不全、3 = 校验失败；唯一豁免是合规风险图需显式 `--exclude` 声明
- **公众号水印自动裁掉**：右下角「公众号 · 账号名」属小红书站外引流违禁词，按图高 20%（下限 200px、上限 30%）裁底
- **8 套字体方案**：宋体文气 / 黑体标题 / 柔和文艺 / 古风站酷小薇 / 粗圆庆科黄油 / 毛笔行楷 / 杂志编辑 / 纸本卷宗，按内容气质选
- **发布后数据回收**：`stats` 子命令读创作者中心笔记管理页，抓观看/评论/点赞/收藏/分享，写回台账并算互动率（只覆盖最新 10 条）
- **默认草稿箱**：`publish.sh` 把 `MODE="draft"` 写死为代码默认，直接发布必须显式 `--publish`
- **发布前预检**：标题英文单引号、正文反引号或 `${`、超过 18 张图，全部在传图之前拦下（否则白等两分钟才失败）

## 五步流程

```bash
SK=~/.workbuddy/skills/mp-article-to-xhs

# ① 选题（三选一）
python3 $SK/scripts/pipeline.py pick --mode hot  --top 8
python3 $SK/scripts/pipeline.py pick --mode title --value 象牙
python3 $SK/scripts/pipeline.py pick --mode url --value https://mp.weixin.qq.com/s/xxx

# ② 抓正文 + 全部配图（自动裁水印）
python3 $SK/scripts/pipeline.py fetch --url "<URL>" --out ./<slug>

# ③ 写 cards.json（由 AI 依「卡片规范」完成）
# ④ 校验图片完整性（不通过会非零退出）
python3 $SK/scripts/pipeline.py check --out ./<slug> --cards ./<slug>/cards.json

# ⑤ 渲染 → 推草稿箱
python3 $SK/scripts/pipeline.py render --cards ./<slug>/cards.json --out ./<slug>/cards --typeface gufeng
bash $SK/scripts/publish.sh --dir ./<slug>/cards --title "<≤20字>" \
     --body-file ./<slug>/body.txt --topics "历史冷知识,三星堆"
python3 $SK/scripts/pipeline.py mark --url "<URL>" --title "<标题>" --status drafted --cards 7 --images 6
```

发布之后回收数据（看哪类选题在你号上真能带互动）：

```bash
python3 $SK/scripts/pipeline.py stats             # 抓最新 10 条，打表 + 写回台账
python3 $SK/scripts/pipeline.py stats --link "公众号标题=小红书标题"   # 标题改过时钉死映射
python3 $SK/scripts/pipeline.py status            # 台账 + 每条最新数据
```

指标顺序按图标读：眼睛=观看、气泡=评论、心=点赞、星=收藏、箭头=分享（和小红书网页端顺序不同）。

## 字体方案（8 套）

靠「字族 + 字重 + 字距」区分气质，颜色主题与字体方案正交。

| 方案 | 标题 | 正文 | 适合的内容 |
|---|---|---|---|
| `classic` | 宋体 600 | 宋体 | 历史、人文、旧事、考据 |
| `modern` | 黑体 600 | 宋体 | 知识科普、考古、人物、清单 |
| `soft` | 细宋 300 | 黑体 | 随笔、感悟、生活、情绪 |
| `gufeng`（默认） | 站酷小薇 400 | 宋体 | 文化、古建、器物、旧朝 |
| `qingke` | 站酷庆科黄油 400 | 宋体 | 清单、器物、知识点、标签式标题 |
| `brush` | 马善政毛笔行楷 | 宋体 | 短标题（≤10 字）、金句页 |
| `mags` | Playfair + 思源宋 300 | 思源宋 | 年份、人名、西文多的篇目 |
| `dossier` | 思源宋 700 | 思源宋 | 考据、数据、年代考 |

有性格的中文字体**首次使用自动下载并缓存**到 `~/.cache/mp2xhs/fonts/`，之后直接引用本地文件（离线可渲染）；其余字体走 `fonts.font.im` 按需子集，断网自动回落系统宋体，不会出方框。

## 依赖

| 依赖 | 用途 | 必需 |
|---|---|---|
| **ego-browser**（ego-lite） | 抓公众号后台、发布小红书 | ✅ |
| **Python 3.8+** | 编排脚本 | ✅ |
| **Pillow** | 裁掉公众号水印 | ✅ |
| **Chrome / Chromium** | 把 HTML 渲染成卡片 PNG | ✅ |
| **xhs-image-note-release**（skill） | 真正执行发布动作的底座 | ✅ |
| 中文字体（宋体/黑体） | 否则卡片全是方框 | ✅ |
| 网络（fonts.font.im / jsDelivr） | 首次拉取特色字体 | 可选，断了只影响字体气质 |

装到新机器的三步（自检 → 补装 → 手动登录）见 [SKILL.md](./SKILL.md#装到新机器三步)。

## 硬规矩

1. **图片一张不能漏**：漏图比丑图严重，宁可停下问
2. **发过的不重发**：台账排除，重发前必须用户明确同意
3. **默认草稿，发布要用户点头**：`publish.sh` 不带 `--publish` 一律进草稿箱
4. **小红书合规红线**：不写微信/公众号引流文案、不出现二维码、不保留公众号水印

## 已知坑

- ego-browser 的 daemon 不继承环境变量、CWD 为 `/`，参数一律走 JSON 文件传递
- `js()` 不能直接返回 DOM 元素，所有 DOM 操作包在 IIFE 里返回原始值
- 抓图必须反复滚动到底再枚举 `#js_content img`，否则懒加载图片会漏
- Chrome 渲染不能加 `--user-data-dir` / `--disk-cache-dir`：前者抢 profile 单例锁、后者不出图
- 中文 webfont 别用 600 字重做区分——与系统宋体 600 肉眼无差别，要靠 300 或 700

## License

MIT © 2026 Evan Song
