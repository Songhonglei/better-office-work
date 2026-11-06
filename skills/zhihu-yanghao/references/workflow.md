# 工作流与脚本调用（zhihu-yanghao v1.5.0）

## 运行环境要求
- 命令前缀：`ego-browser nodejs`（Bash 工具必须加 `dangerouslyDisableSandbox: true`，且 WorkBuddy 安全中心「沙箱安全」开关临时关闭）。否则 ego-browser 连不上（报 `Failed to connect to ego_cli bootstrap`）。
- ⚠️ **PATH 注意（v1.3.3）**：ego-browser 可能不在 shell PATH（本机实测须用 `~/.local/bin/ego-browser`）；zhihu-cli 通常也不在 PATH（真实路径 `~/Library/Application Support/zhihu-cli/current/zhihu-cli`，verify_via_cli.js 已内置此回退）。
- 所有脚本在 `scripts/` 下，参数通过环境变量或参数文件传入。脚本内部用字符串拼接组装 js 代码，避免 `${}` 被外壳展开。

## 配置 config.json（用户自定义话题与班次）
1. 复制模板：`cp config.example.json config.json`（config.json 不纳入版本库，按你账号改）。
2. 关键字段：
   - `account`：知乎账号 ID（如 `your-account-id`），用于日报/主页验证。
   - **`vertical_focus`**（v1.3.0）：垂直度收敛配置。`primary` = 只养的 2 个领域（当前「趣味历史」+「人文心理」）；`keyword_hints` = 各领域关键词，写作时自然融入 2–3 个帮算法打标签。**🚫 不在 `primary` 之外的话题下写回答**，否则垂直度永远点不亮。
   - `topic_pool`：全局话题池（数组）。三班按「日序号 + 班次偏移」轮转取关键词。历史类与人文类**交替排列**，保证每班取到的 3 个词横跨两个垂直领域。
   - `answer_style`：标准回答字数区间与视角提示（LLM 写回答时参考）。
   - **`deep_answer`**（v1.3.0）：深度版配置。`frequency: "weekly"`；`mode` = `auto`（用户邀请优先 + 每周随机兜底）/ `invite`（仅用户邀请）/ `random`（仅自动随机）；`min_words`/`max_words` = 800–1200；`requirements` = 硬料 + 对比结构 + 可操作结论三项。
   - **`influence`**（v1.3.0）：创作影响力规范。`hook`（反直觉观点拉评论）、`actionable`（清单/框架拉收藏）、`cta`（结尾禁止机械问号收尾，用观点/留白收束；2026-09-09 修订）、`comment_reply`（发布后 24h 内回评论）。**v1.5.0 起去 AI 味是硬门禁，不是自检**——见下方「发布前两道硬门禁」。
   - **`publish_gates`**（v1.5.0）：发布门禁。`humanize.enabled`（默认 true）/ `tier` / `gate_file` / `max_age_hours` / `require_no_fail`；`illustration.ask_user`（默认 true）/ `options`（网络图 / batch-image-gen 生成 / 不配图）/ `max_images`（默认 2）/ `require_user_confirm_before_publish`。**改 `enabled=false` 会跳过门禁并输出 WARN，仅限未安装 text-humanize 的机器。**
   - **`moments`**（v1.3.0）：想法/动态配置。`per_week` = 每周条数（默认 4）；`min_words`/`max_words` = 50–150；`topics` = 内容方向。
   - `shifts`：三个班次，每班含：
     - `enabled`：是否启用该班。
     - `time`：建议触发时间（自动化调度用）。
     - `answer`：该班是否写 1 回答。
     - `interactions`：`{ like, collect, follow, comment }`——`like` 为点赞配置：**整数 `5`（固定 5 个）或对象 `{"pool":10,"min":3,"max":5}`（前 10 个候选随机选 3–5，推荐自然化）**；`collect`/`follow`/`comment` 为开关（comment 默认 false，实验性）。
3. 改完保存即可，run_shift.js 下次运行自动读最新配置。

## 发布前两道硬门禁（v1.5.0，任何发布路径都适用）

### ① 去 AI 味（text-humanize，程序化拦截）

```bash
# 1) 先加载 text-humanize skill（中文模式）改写正文，FAIL 归零后把定稿写入文件
#    知乎回答默认 --tier long（长文档不注入错别字）；文末配图署名行也要一起写进定稿
# 2) 跑门禁（自动定位 ~/.workbuddy/skills/text-humanize/scripts/preflight-check.py）
python3 scripts/humanize_gate.py /abs/answer.txt
#    HUMANIZE_GATE_OK  → 写 /tmp/zhihu_humanize_pass.json
#    HUMANIZE_GATE_FAIL → 删除旧凭证、退出码 1，改稿重跑，禁止绕过
```

可选参数：`--tier short|long|literary`、`--strict`（WARN 也拦）、`--preflight <path>` / 环境变量 `TEXT_HUMANIZE_PREFLIGHT`、`--gate-file <path>`、`--max-age-hours 6`。

凭证 schema（与正文绑定，改一个字即失效）：
```json
{ "ok": true, "contentFile": "/abs/answer.txt", "sha256": "...", "length": 762,
  "tier": "long", "fail": 0, "warn": 1, "strict": false,
  "maxAgeHours": 6.0, "checkedAt": 1793962106, "preflight": "/abs/preflight-check.py" }
```

- `run_shift.js`：字数护栏之后校验 `ok` / sha256 / contentFile / `fail=0` / 6h 时效 → 通过输出 `HUMANIZE_GATE_OK`，不通过输出 `ANSWER_SKIPPED: HUMANIZE_GATE_FAIL`（不打开编辑器，点赞/互动照常收尾）。
- 手工 heredoc（含插图）没有内建校验：agent 必须自己先跑门禁，在日报记一行 `HUMANIZE_GATE_OK`。即使用 `CONTENT` 字符串直接传正文，也要先把定稿落盘成文件跑一遍门禁（凭证需要 `contentFile` + sha256）。
- 旧配置没有 `publish_gates` 块时门禁**默认强制开启**（fail-safe）；只有显式 `enabled=false` 才放行并输出 WARN。
- `config.publish_gates.humanize.enabled=false` 会输出 `WARN: HUMANIZE_GATE_DISABLED` 并放行（仅限无 text-humanize 的机器），本机保持 true。

### ② 配图方式问用户

正文定稿 + 门禁通过后、填编辑器之前，用 `AskUserQuestion` 三选一：**网络图 / 用 batch-image-gen 生成 / 不配图**。不得替用户决定或沿用上次。选配图的完整执行路径（Commons 授权查证、`imagegen-batch` 要点、新版 `taskSpace()/page()/setInputFiles` 分段插图、dry run 校验、发布前最终确认）见 `references/illustrations.md`。

要点：
- `run_shift.js` / `write_answer.js` **不支持插图**；配图必须走手工 heredoc 的新版 API 路径。
- 填完编辑器先 dry run（图片 `complete && naturalWidth>0` + src 落知乎图床 + 截图验顺序），把截图/原图/定稿给用户，拿到明确同意才点发布。
- 日报记两行：`HUMANIZE_GATE_OK: ...` 与 `ILLUSTRATION: 网络图(2, 已署名) / batch-image-gen(2, 已标注) / 不配图`。

## 深度版怎么触发（v1.3.0）
深度版**不需要额外脚本**，走的是同一套 `run_shift.js` 流程，区别只在正文生成规范：

| 触发方式 | 怎么发生 | 处理 |
|---|---|---|
| **invite（用户邀请）** | 用户说「写深度版」「这篇写深一点」「来篇长的」 | 本班按 `deep_answer` 规范生成 800–1200 字正文，再跑 run_shift.js |
| **random（每周随机）** | 用户没提，本周还没出过深度版 | 本周随机挑 1 班，按深度版规范写 |
| **mode 取值** | `auto`（两者结合，默认）/ `invite`（只认邀请）/ `random`（只认自动） | 改 `config.deep_answer.mode` |

**执行要点**：
- 深度版同样受红线约束（单班 ≤ 1 回答、发布前 90s 模拟阅读 + 60s 等待）。
- 每周不超过 1 篇深度版即可——宁缺毋滥，硬凑的深度版反而拉低优质分。
- 深度版发布后**必须 24h 内回评论**（`config.influence.comment_reply`），否则浪费了内容质量带来的互动窗口。

## 发想法 / 动态（v1.3.0，已自动化 ✅）
想法是提升**关注者亲密度**（月更维度）性价比最高的动作：短、频、轻，不需要深度。

```
# 1) 写正文（50-150 字）+ 参数文件
echo '想法正文' > /tmp/moment.txt
cat > /tmp/zhihu_moment_params.json <<'EOF'
{ "contentFile": "/tmp/moment.txt", "dryRun": true }
EOF

# 2) 跑（dryRun=true 只填不发布，建议新机器首次先这样验证）
ego-browser nodejs < scripts/post_moment.js
```

**选择器（2026-08-31 实测）**：
| 元素 | 选择器 |
|---|---|
| 入口按钮 | `button` 文本含 **发想法**（首页顶部，class 动态） |
| 编辑器 | **`.public-DraftEditor-content`**（与回答编辑器同一类，fillInput 直接复用） |
| 发布按钮 | 从编辑器向上遍历祖先，取 `innerText.trim() === '发布'` 的 button |

**参数**（`/tmp/zhihu_moment_params.json`，env 可传 `CONTENT` / `CONTENT_FILE` / `DRY_RUN`）：
- `content`：正文字符串；`contentFile`：正文文件绝对路径（二者取一，优先 `content`）。
- `configPath`：可选，用于读 `moments` 字数区间做长度提示（超出只 WARN 不阻断）。
- `dryRun`：**默认 true（fail-safe，只填不发布）**；实发必须显式写 `"dryRun": false`。新机器或首次使用建议先用默认跑一遍确认。

**风控**：想法属创作内容，两条之间**间隔 ≥ 5 分钟**；单次任务只发 1 条。脚本内置发布前 30s 等待。

**失败处理**：
- `PUBLISH_CLICK` 不是 `clicked` → **不要重试**（避免累积卡死草稿），人工检查。
- `FILL_FAILED` 报 `Element not found` → 先查登录态（页面是否出现「登录/注册」）。

**⚠️ 校验必须用 CLI，不能信浏览器侧**（2026-08-31 实测）：
发布成功后弹窗会**重置为空白编辑器**，脚本里的 `VERIFY_PAGE_ONLY` 仍会报 `editorRemaining: 1`——这是**假阴性**，据此判定失败会误判。
权威校验：
```
zhihu-cli me contents --type pin --limit 3
```
注意想法在 API 里的内容类型是 **`pin`**（不是 moment）。`--type` 只支持 `all / answer / article / zvideo / pin / question`。


## 修改已发布回答（v1.3.1，scripts/edit_answer.js）

```
# 1) 新正文写入文件（🚫 禁止 Markdown：** 和行首 "- " 会字面残留；用 1./·/破折号排版）
#    或让脚本自动清洗：stripMarkdown: true
cat > /tmp/zhihu_edit_params.json <<'EOF'
{ "aid": "2078057751377360832", "qid": "520978750",
  "contentFile": "/abs/new-text.txt", "dryRun": true }
EOF

# 2) 跑（默认 dryRun：只替换编辑器草稿不提交，浏览器人工确认后再实提）
ego-browser nodejs < scripts/edit_answer.js
```

**已验证的替换方法**（2026-09-01 实测）：`selectAll + delete` 清空后，**唯一可行**的注入方式是
`document.execCommand('insertHTML', false, '<p>段落…</p>…')`——fillInput 在清空后的 Draft.js 上失效（innerText 长度=1）。

**已知限制（如实告知）**：内容替换 ✅ 可行；但点击「提交修改」后**提交可能不被响应**（无弹窗、无报错、编辑态不退出，疑似需 mousedown/mouseup 事件序列）。脚本会轮询编辑态退出 5 次（20s），期间检测组合词确认弹窗（排除「提交修改」「发布设置」自身）；仍未退出则输出 `SUBMIT_NOT_EFFECTIVE` 并**停止**——不重试点击，转人工在 ego lite 确认（编辑器里已是新内容，手动点提交即可）。

**护栏**（任一不过即停，绝不提交坏内容）：
- 长度校验：编辑器 innerText 长度需在期望值 ±15% 内
- 符号校验：编辑器内不得有 `**` 残留
- 按钮精确匹配：`innerText.trim() === '提交修改'`（真名，非「发布修改」）

**风控提示**：知乎对 ~30 分钟内第二次修改不更新 `updated_time`；修改完成后用 CLI `me contents --type answer` 做权威复核（注意索引可能滞后几分钟）。

## 两种调用方式
方式一（推荐，文件直读）：把脚本内容喂给 ego-browser：
```
QID=2021300214389043782 ego-browser nodejs < scripts/like_top5.js
```
方式二（heredoc，最稳）：打开脚本文件，把其内容粘贴进 `ego-browser nodejs <<'EOF' ... EOF'`：
```
QID=2021300214389043782 ego-browser nodejs <<'EOF'
<此处粘贴 scripts/like_top5.js 的全文>
EOF
```

## 推荐：三班编排（run_shift.js）
一个命令跑完一个班的全部动作，配置全在 config.json。本环境用**参数文件**方式（ego-browser 不透传 env）：
```
# 1) 写参数文件（shift/qid/contentFile/configPath 等），见下方 schema
cat > /tmp/zhihu_shift_params.json <<'EOF'
{ "shift": "morning", "qid": "2070982459156424668",
  "contentFile": "/abs/answer.txt",
  "configPath": "/abs/config.json" }
EOF

# 2) 跑（不带 env，脚本自动读参数文件）
ego-browser nodejs < scripts/run_shift.js
```
env 写法（其他机器若透传 env 可用）：`SHIFT=morning CONFIG=/abs/config.json ego-browser nodejs < scripts/run_shift.js`。
`run_shift.js` 参数（**env 优先，回退参数文件**）：
- **env 方式**（部分 ego-browser 构建不透传 shell env，见下）：`CONFIG` / `SHIFT` / `QID` / `CONTENT` / `CONTENT_FILE` / `KW` / `LIMIT` / `COMMENT_TEXT`。
- **参数文件方式（推荐，env 不可用时）**：把下列 JSON 写到 `/tmp/zhihu_shift_params.json`，再 `ego-browser nodejs < scripts/run_shift.js`（不传 env）：
  ```json
  {
    "shift": "morning|noon|evening",
    "qid": "2070982459156424668",
    "contentFile": "/abs/answer.txt",
    "configPath": "/abs/config.json",
    "deep": false,
    "kw": "历史,神话",
    "limit": 25,
    "commentText": "评论内容"
  }
  ```

> ⚠️ **字数护栏（v1.3.3）**：`run_shift.js` 发布前按 config 校验 contentFile 字符数——`"deep"` 缺省/false 用 `answer_style`（250–800），`"deep": true` 用 `deep_answer`（800–1200）。超区间输出 `ANSWER_SKIPPED: WORD_COUNT_EXCEEDED` 并跳过发布（点赞/互动照常收尾），改正文后重跑（已赞自动跳过）。

> ⚠️ **折叠验证（v1.3.3）**：`run_shift.js` 发布后**不再做** API 验证（serverFetch 8/26 起恒 403，旧版 retry 纯属白耗），只输出 `VERIFY_VIA_CLI` 提示——随后跑：
> ```
> echo '{"aid":"<aid>","type":"answer"}' > /tmp/zhihu_verify_params.json
> ego-browser nodejs < scripts/verify_via_cli.js
> ```
> `VERIFY_RESULT: OK_NOT_COLLAPSED` = 未折叠；`NOT_FOUND_YET` = 索引滞后（1–2 分钟后重跑，不是折叠）。

> ⚠️ **本机实测（macOS / ego-browser nodejs）不向运行时透传 shell 环境变量**——`process.env.*` 全为 `UNDEF`，故 heredoc/env 内联写法在本环境会失败。统一用「参数文件 `/tmp/zhihu_shift_params.json` + 不带 env 的 `ego-browser nodejs < scripts/run_shift.js`」最稳。脚本已同时兼容 env（其他机器若透传仍可用）。

脚本流程：读配置 → 轮转取关键词 → 选未答过问题（或 QID 覆盖）→ 前10随机选3-5点赞（自然化）→ 字数护栏校验 → **去 AI 味门禁校验（v1.5.0，不过即跳过发布）** → 写/发布1回答 → 按 interactions 做可选收藏/关注/评论。已内置「已答过跳过 + 已赞跳过 + 随机选赞 + 发布卡死即停 + 字数护栏 + humanize 凭证校验」。折叠验证见上方 verify_via_cli.js。
> ⚠️ **配图询问是 agent 侧动作，不在脚本里**：agent 在跑本脚本前必须先问用户配图方式；选了配图时不要用 `run_shift.js` 发布（它不支持插图），改走 `references/illustrations.md` 的手工路径。

> **v1.3.7 起：班次前置步骤 = 折叠巡检**（`scripts/fold_audit.js`）——每班开跑先与基线比对，抓 `NEW_FOLDED`（新被折叠）/`RECOVERED`；发现新增折叠要在日报记录并在写作时收紧去指纹化规范。**折叠权威信号 = 创作者中心「被折叠」标签**，CLI Summary 在新「隐藏机制」下失明（详见 selectors.md 折叠验证行）。
>
> **发布失败处置（v1.3.7）**：`run_shift.js` 现在会在发布未成功时输出 `SHIFT_PARTIAL_FAIL: publish`（此前只在日志里留 WARN 却照常报 `SHIFT_DONE`，无人值守会误判成功）。看到该行＝正文未发布，同问题页**最多重试 1 次**，再失败停 1–2 小时或换班次（同页 15 分钟内连续开编辑器会触发「写回答」不挂载编辑器的密度信号）。

## 模式 C：禁言期只读浏览（v1.3.8，账号受限时唯一允许的动作）
```bash
# 可选参数：/tmp/zhihu_browse_params.json = {"minutes":6,"pages":4,"keywords":["历史","心理"]}
ego-browser nodejs < scripts/browse_only.js
```
- 行为：热榜滚动 → 按垂直领域关键词挑问题 → 逐页滚动停留（40–90s/页）→ 首页信息流；**全程零点击互动**，日志 `BROWSE_DONE ... interactions=0` 可验证。
- `run_shift.js` 在 `config.account_status.silenced=true` 时会直接退出（`SILENCED_MODE`），不会写任何内容；**不要**靠它兜底，禁言期就只跑本模式。
- 频率：每天 1–2 次即可（维持真实活跃痕迹），无需三班。
- ⚠️ **每个 ego-browser 脚本必须单独一条命令跑**（2026-09-23 实测）：把 `fold_audit.js` 和 `browse_only.js` 用 `;` 串在同一条 shell 命令里时，**第二个调用会静默空跑**——连 `BROWSE_START` 都不输出、也不报 `BROWSE_ERROR`，退出码照旧为 0。判别法：**日志里没有 `BROWSE_START` / `BROWSE_DONE` 就等于这次没跑**，必须重新单独执行（只读脚本空跑无副作用，但会被误记成"今天浏览过了"）。

## 模式 A：每日养号完整一轮（旧版单脚本，仍可用）
1. 闲逛热榜找选题：
```
KW='历史,神话,唐僧,西游记' ego-browser nodejs < scripts/pick_question.js
```
   从 KEYWORD_HITS / ALL_TITLES 选一个中热度、未答过的问题，记下 qid。
2. 验证未答过并点赞（前10随机选3-5，脚本内含「已答过跳过 + 已赞跳过 + 随机选赞」）：
```
QID=<qid> ego-browser nodejs < scripts/like_top5.js
```
3. 写回答（**发布前两步不可省**：① `python3 scripts/humanize_gate.py /tmp/zhihu-answer.txt` 拿 `HUMANIZE_GATE_OK`；② `AskUserQuestion` 问配图方式「网络图 / batch-image-gen 生成 / 不配图」。详见上方「发布前两道硬门禁」）：
```
QID=<qid> CONTENT_FILE=/tmp/zhihu-answer.txt ego-browser nodejs < scripts/write_answer.js
```
   脚本会：打开编辑器 → 粘贴注入正文（ClipboardEvent，v1.3.2）→ 等 60s → 点「发布回答」→ 输出 aid。
4. 验证未折叠（v1.3.3 起用 CLI 脚本，verify_fold.js 已删除——其 API 8/26 起恒 403）：
```
echo '{"aid":"<上一步输出的aid>","type":"answer"}' > /tmp/zhihu_verify_params.json
ego-browser nodejs < scripts/verify_via_cli.js
```
   看到 `VERIFY_RESULT: OK_NOT_COLLAPSED` 即成功。
5. **回报链接（v1.4.0 起必做）**：把 `https://www.zhihu.com/question/<qid>/answer/<aid>` 和 `aid` 写进给用户的最终回复；文章用 `https://zhuanlan.zhihu.com/p/<id>`，想法用 `https://www.zhihu.com/pin/<id>`。链接只能取自发布后真实跳转的 URL 或 CLI 返回 id，**不要用 qid 拼猜 aid**；未拿到 `OK_NOT_COLLAPSED` 时照给但标注「发布未确认」。本次无新增内容要明说，不能略过。

## 模式 B：纯互动（只点赞）
```
QID=<qid> ego-browser nodejs < scripts/like_top5.js
```

## 写回答正文怎么给
- 长回答：先把正文写进文件（如 `/tmp/zhihu-answer.txt`，用空行分段），再 `CONTENT_FILE=/tmp/zhihu-answer.txt`。
- 短回答：直接 `CONTENT='你的回答正文'`。
- 若你的 ego-browser 构建不支持 `require('fs')`，改为把正文直接嵌进 heredoc 的 JS 字符串（同 write_answer.js 主体，仅把 content 来源改成字面量）。

## 风控提醒（详见 references/risk-control.md）
- 点赞间隔脚本已内置 35–80s 随机；不要人为加速。
- 发布卡「发布中…」立刻停，不要重试（详见风控文档）。
- 任务前后自己加 3–5 分钟闲逛（开热榜 / 推荐页 wait 即可）。
