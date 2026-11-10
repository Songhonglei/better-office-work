# Changelog — video-multi-release

本文件存放变更记录与专项复盘细节，
供追溯用；**不影响执行**的规则已提炼回 SKILL.md。

## v1.3.2 (2026-11-10)

第二轮 UGLIC 审计（U/G/L/I/C 五维 + 两个独立审计员交叉复核 + 实测验证）。

**P0（本轮最严重，是 v1.3.1 修复时引入的回归）**

- `release.sh` 的 `if [ -n "$COVER" ]` 缺 `fi`，**整个发布入口无法解析**。`bash -n` 报
  `line 327: syntax error: unexpected end of file`；参数齐全时 `exit 2`，一次都发不出去。
  更隐蔽的是：缺 VIDEO 时会先走到 `usage_fail`，冒烟测试看起来「正常退出」，掩盖了问题。
  已补 `fi`，并重跑 `bash -n` + 三条真实冒烟（E_VIDEO_NOT_FOUND / E_COVER_NOT_FOUND / 完整 stage）。

**其它修复**

| 项 | 问题 | 修法 |
|---|---|---|
| 退出码 | `E_PUBLISH_BTN_DISABLED` 在抖音走 `EXIT.FORM`(40)，文档把 disabled 归到 70 | 表内注明「抖音 disabled 走 40」，补 code↔exit 对照 |
| 转码失败 | ffmpeg 在 `set -e` 下静默退出（退出码 1，表里查不到） | 加 `|| usage_fail E_TRANSCODE_FAILED`，给 what_now 与降级选项 |
| 死路 | `rebuild.sh` exit 11 让用户跑 `assets/music/download.sh`，但已 `cd` 到项目目录 | 改用 `$SKILL_DIR/assets/music/download.sh` |
| 示例跑不通 | step 4 的 BGM 示例写 `music/bgm.mp3`，曲库里没有这个文件 | 改成 `Frost Waltz.mp3`（默认曲目） |
| 默认值打架 | 2a 示例用 `0.5/0.4/1.2`，2b 与 rebuild.sh 是 `0.6/0.45/1.5`，分步跑与一键跑时长不同 | 2a 对齐 0.6/0.45/1.5，并注明「改这三个值要同步改 2b」 |
| 落点说法矛盾 | 一处说 timeline.json「与 index.html 同目录」，另一处说「落在 CWD」 | 统一为 CWD，并让 `build_composition.py` 打印实际绝对路径 |
| 静默覆盖 | `--out` 父目录不存在时直接报错退出（虽不静默，但很常见） | 自动 `makedirs` |
| 判据矛盾 | 「上传完成不能看 video.duration」与「判据只认按钮可用 + duration>0」互相打架 | 统一为「主判据是按钮可用，duration 只作辅助，代码是双条件」 |
| 文档拆分断口 | 「抖音补话题别用退格」「CC-BY 署名」只在 CHANGELOG，主文档没有 | 两条都回写正文（exit 50 的指引正是让人去手动补话题） |
| 目录树过期 | 漏 `onboard.sh`、`replace-published-video.md`、`assets/music/` | 补齐 |
| 幽灵参数 | `release.sh:214` 仍写 `--ratio horizontal`（同文件 35 行刚说不是） | 改 `--cover-h` |
| docstring 过期 | `tts.py` 头部示例还是 `--out-dir audio/female` | 改 `voice`，并注明 rebuild.sh 硬要求这个名字 |
| 标题层级 | `replace-published-video.md` 一级标题后直接跳 `###` | 三个降为 `##` |
| schema 缺键 | `segments[].quote` 代码会读，输入表没写 | 补一行 |
| 密钥进 history | `onboard.sh --key` 会在 shell history / `ps` 留痕，文档没提示 | 补「优先交互输入」 |

**结构瘦身**：SKILL.md 683 → 591 行。日期化章节重组为功能性标题（`## 2026-11-09 新增能力` →
`## 历史题材：卡片与字体`，删去与「快速开始」重复的「一条龙」命令）；「必须知道的坑」138 → 86 行，
按平台分组（渲染 / 视频号 / 抖音 / 小红书 / ego 通用），26 条全部保留、只压缩叙述；
「发布链路加固」表移入本文件；「全检铁律」与「已知限制」合并为一节。
16 个关键技术判据（`SUB_TIMELINE_SCRIPT_FAILURE`、`y=1268`、`qrconnect`、`E_WUJIE_MISSING`、
`weui-desktop-btn_disabled`、`geolocation=2` 等）逐一比对，0 丢失。

**判定为误报、未改**：frontmatter 的 version/slug/displayName/bins/metadata（本机 24 个已安装
skill 多数如此，含用户自己的 invoice-auto-forward；且 `metadata` 声明的 `DASHSCOPE_API_KEY`
在 `tts.py:71/89/98` 确实被读取）；目录里有 CHANGELOG.md（glic-check 自己也带）；
`scripts/__pycache__/`（`.gitignore` 已覆盖）。

## v1.3.1 (2026-11-10)

UGLIC 审计修复（以可用性维度为主）。

- **Fix（假成功）**：`release.sh` 缺 mjs 分支用 `continue` 跳过失败累计，汇总写「失败(11)」却 `exit 0`。改为累计 `FIRST_FAIL_RC`。
- **Fix（误导排障）**：退出码表与代码 `EXIT` 常量错位——60 写成「提交失败」（实为 COVER）、70 写成「提交后没跳转」（实为 SUBMIT），80/90 整行缺失。已按常量重排。
- **Fix（照抄必失败）**：快速开始用 `audio/female`，但 `rebuild.sh` 强制 `voice/`，第二步直接 exit 10。已统一为 `voice/`。
- **Fix（照抄必失败）**：分解视图缺 gsap 内联步骤，跳过必命中 `SUB_TIMELINE_SCRIPT_FAILURE`。
- **Fix（三处互斥）**：抖音「能否全自动」在硬边界/平台对比表/坑位正文里说法不同。统一为「多为可直发；短信验证概率性触发，命中即 exit 75」。
- **Fix（会成循环）**：exit 20 指引「扫码后重跑」与抖音「勿重跑（reload 杀登录）」冲突。已按平台拆开，抖音要求 `SPACE_ID`/`RESUME`。
- **Fix（五处互斥）**：`COVER` 归属说法不一。统一为「三平台通用，抖音尽力而为、失败只告警」。
- **Fix**：时间轴默认值四处不一致（0.5/0.4/1.2、0.6/0.5/1.5、0.6/0.45/1.5）。以 `rebuild.sh` 的 0.6/0.45/1.5 为唯一口径。
- **Fix**：排障铁律让用 `sr.textContent` 搜校验提示，与「别用 textContent」自相矛盾。改 `createTreeWalker` 并跳过 SCRIPT/STYLE。
- **Fix**：`release.sh` 注释里的幽灵变量 `COVER_VERTICAL`（设了静默无效）与不存在的 `--ratio horizontal`。
- **Add**：`voice_script.json` 结构说明——首条命令就依赖它，原文只在章节里给过一个片段。
- **Add**：`platform-specs.md` 加过期声明与加载时机；`release.sh` 对 CC-BY 曲库 BGM 打印署名提醒（只提醒，不擅自改用户 DESC）。
- **Add**：frontmatter 补 `slug` / `displayName`，`bins` 补 `ego-browser`。
- **Chore**：SKILL.md 784 → 662 行。纯记录（19 项修复表、全检复盘细节）移入本文件，低频操作移到
  `references/replace-published-video.md`，主文档只留规则与索引。


### 发布链路行为清单（原 SKILL.md 表格）

从主文档移出，属功能说明而非执行步骤。


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


## v1.3.0 (2026-11-10)

### 已修（19 项，逐条可复现）
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

### 全检复盘细节

#### 教训

18 张卡片做完只抽查 6 张（02/06/10/14/15/18），得出「5/6 完全避开人物头部」，
对外报成合格。**全检后发现第 01 张（钩子卡，最重要）文字正好压在秦始皇额头/眉眼上** ——
抽的 6 张恰好漏掉了最糟的一张。另有 02/13/15 压住车驾、宫殿飞檐、长城墙体。

**铁律：卡片生成后必须全检所有张，不能抽样。** `gen_cards.py` 现在生成完会自动调用
`cards_contact_sheet.py`，产出 `<out-dir>/_check/group_*.png`（每组 6 张，3x2，360px 宽）
和 `all.png`（全部缩略总览）；`--no-proof` 可关闭，但不建议。
逐组看完再进渲染，重点看「白字有没有压住人物头部 / 面部」。

#### 为什么算法会漏（根因，非调参能解）

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

#### 置信度机制（关键）

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

#### 最根本的解法：生图时就给文字留位置

事后找留白永远受「暗色人物 ≈ 暗背景」限制。源头是提示词只写了
「画面暗部留白便于叠加文字」，AI 照样把人脸放正中。
数据目录 `config.json` 的 `image_prompt_presets.history_dark` 已固化硬约束：

> 构图硬约束：主要人物与建筑主体全部置于画面下三分之一；
> 画面上方 40% 保持大面积纯暗留白，不要出现面部、五官或任何高对比细节；
> 两行白色大字将叠加在上方留白区。

下次生图直接拼 `style + composition + 场景描述`。这批 18 张图已定，
源头模板对它们不生效，所以才需要 7 张人工兜底。

#### 本次全检结论（最终版 18 张）

| 判定 | 卡片 |
|---|---|
| ✅ 完全避开人物头部与主体 | 01、02、04、05、06、08、09、10、11、12、14、16、17、18 |
| ⚠ 压住非人物主体（无脸，可接受） | 03 船队、07 竹简、13 宫殿飞檐、15 长城山体 |
| ❌ 压住人物头部 | 无（原 01 已修） |

13 / 15 是插画本身没有大片留白，且不涉及人物，按「不能挡头部 + 尽量放空区」
的规则可接受；若要求更严，只能重生成这两张配图。

---
