# Changelog — video-multi-release

本文件只记录**版本变更本身**（改了什么、为什么改）。

执行时要用的规则、判据、排障指引一律不在这里，而在：

| 内容 | 位置 |
|---|---|
| 执行步骤与硬规则 | `SKILL.md` |
| 发布链路实际行为（体积转码 / 上传判据 / 现场复用 / 汇总 / 配置键） | `references/release-behavior.md` |
| 完整错误码对照与故障判断顺序 | `references/error-handling.md` |
| 卡片叠字定位、全检判据、算法根因 | `references/card-text-safety.md` |

> v1.3.2 之前有几节「发布链路行为清单」「新增踩坑」「全检复盘细节」曾被放在本文件里，
> 属于误置——它们是执行指引，不是版本记录。已迁出，见上面的表。

## v1.3.3 (2026-11-10)

**文档归位**：把误置在 CHANGELOG 里的执行内容迁到 references，并修掉一处断链。

| 原在本文件的内容 | 现位置 |
|---|---|
| 发布链路行为清单（体积转码、上传判据、现场复用、汇总、BGM、配置键） | `references/release-behavior.md`（新建） |
| 错误码碎片、常见故障判断 | `references/error-handling.md`（新建） |
| 全检复盘、confidence 判据、算法根因、生图提示词 | `references/card-text-safety.md`（新建） |

- **Fix（断链）**：SKILL.md 让排障时去 `references/error-handling.md` 查 code，但该文件从来没建过。
  已补齐，含全部 47 个 `E_*` 码的 `code ↔ exit ↔ step ↔ 平台` 对照。
- **Fix（文档与引用）**：「必须知道的坑」开头原写「完整推演见 CHANGELOG.md」——把排障推演指向版本记录，
  已改为指向 `references/error-handling.md` 与 `release-behavior.md`。
- **Add**：SKILL.md 回填 5 处只在本文件存在的执行信息——`MAX_VIDEO_MB` 自动转码、抖音上传完成判据、
  `MODE=draft` 在抖音退化为 stage、`=== OK ===` 块判据、`RESUME`/`publish` 的 `SPACE_ID` 语义。
- **Chore**：CHANGELOG 214 → 144 行；SKILL.md 591 → 617 行（新增 3 个 references 索引 + 上列回填）。

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
| 转码失败 | ffmpeg 在 `set -e` 下静默退出（退出码 1，表里查不到） | 加 `\|\| usage_fail E_TRANSCODE_FAILED`，给 what_now 与降级选项 |
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
| `rebuild.sh` | 只有 `set -e`，`\| tail` 吞掉渲染/混音失败码，拿旧 `final.mp4` 误报成功 | 加 `set -o pipefail`；**不要**在混音前 `rm -f` 旧成片（会触发沙箱批量删除保护、把混音整个拦下），靠 ffmpeg `-y` 覆盖即可 |
| `tts.py` | 时长预估 `except Exception` 全吞，`--target` 静默失效 | 传了 `--target` 且预估失败时直接退出 |
| `find_safe_area.py` | `axis=both` 的左右评分用整行（含暗角），与 vertical 口径不一致 | 统一用 `X0..X1` 文字覆盖区 |
| `card_generator.py` | 极端 `x_ratio` + `anchor` 文字溢出画面；安全区上下界交叉时整段跳过 clamp | 起点 clamp 进可行域；交叉时至少从安全区顶部起排 |
| 两侧文档 | xhs 主题数 28→29、照片主题 3→4；版本 `2.0.1→2.0.2` / `1.2.1→1.3.0`；gap 符号写反；时间轴公式 | 已同步，CHANGELOG 补 v2.0.2 条目 |

### 踩坑记录（2026-11-09 实测）

本期暴露的六个问题。**操作口径已写入对应 reference，这里只记现象与结论**：

| 现象 | 结论 | 现行规则在哪 |
|---|---|---|
| 抖音编辑页 24 秒就出来但仍在传，点发布跳管理页、作品数不动 | 编辑页就绪 ≠ 上传完成；78MB 压到 25MB 后 18 秒才真传完 | `release-behavior.md` §2 |
| 视频号 78MB 上传 160 秒超时（同文件小红书 83 秒能过） | 先压再传，已做成 `MAX_VIDEO_MB` 自动转码 | `release-behavior.md` §1 |
| `SPACE_ID` 复用仍无条件 reload，杀掉刚扫的码、清空已填内容 | 复用现场必须跳过 reload | `release-behavior.md` §5 |
| 抖音补话题按退格，误删已挂的 `#历史真相` | 标签是整体单元，挂不上宁可留纯文本 | `SKILL.md` 抖音节 |
| 近黑卡片外套一圈米白画布 | 画布底色必须显式传（`--canvas-bg`/`--canvas-stops`） | `SKILL.md` 历史题材节 |
| 1036 字按 rate=1.12 配出 245s，超目标 65s | 先估时长再砍字，别靠压 rate | `SKILL.md` 时长章节 |

### 卡片全检复盘（2026-11-10）

抽样 6 张报「5/6 合格」，全检后发现第 01 张（钩子卡）正压在秦始皇额头上——抽的恰好漏掉最糟那张。
据此定了全检铁律、`confidence`/`gap` 判据、算法根因与生图提示词硬约束，
**这些属于执行指引，已整体移入 `references/card-text-safety.md`**。最终 18 张判定：

| 判定 | 卡片 |
|---|---|
| ✅ 避开人物头部与主体 | 01、02、04、05、06、08、09、10、11、12、14、16、17、18 |
| ⚠ 压住非人物主体（无脸，可接受） | 03 船队、07 竹简、13 宫殿飞檐、15 长城山体 |
| ❌ 压住人物头部 | 无（原 01 已修） |

13/15 插画本身没有大片留白且不涉人物，按「不挡头部 + 尽量放空区」可接受；要求更严只能重生成这两张。
