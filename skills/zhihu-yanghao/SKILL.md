---
name: zhihu-yanghao
description: Full Zhihu account-nurturing workflow via ego-browser — three daily shifts (each writes, publishes and verifies one answer with like engagement), weekly deep-dives, moments/想法, content-influence rules, and optional collect/follow/comment. Vertical topic pool and schedule are user-configurable. Publishing requires a text-humanize (Chinese) de-AI pass with a hash-bound credential and an explicit illustration choice (web / batch-image-gen / none). Writing must open with a contestable judgment, stay terse, and use evidence-backed analysis over surface sentiment. Every run reports published links and raw ids. Use when the user asks to 知乎养号 / 养知乎号 / 发知乎回答 / 知乎点赞互动 / 知乎浏览 / 三班养号 / 写深度版 / 发想法 / 提升创作分, or wants a portable, risk-controlled Zhihu growth routine.
agent_created: true
---

# 知乎养号（zhihu-yanghao）v1.5.1

> ## ⛔ 文案三条硬要求（v1.5.1，用户明确要求，动笔前必读）
> 1. **观点先行**：首句或首段直接给一个能被反驳的判断，不要背景铺垫、共情、寒暄、「这个问题其实挺复杂」。
> 2. **干净利落**：句子砍短，删净缓冲垫句、重复转述与元叙述，不磨叽、不堆层级。
> 3. **有深度和判断**：不流于表面和情绪；硬料可核查、机制讲透、给可迁移的判断，不站队、不共情、不和稀泥。
> 与第 5 节不冲突：禁的是「先说个反直觉判断」这类**元话语开场白**，不是不让亮观点；hook 仍放中段，开头句式池照旧轮换。完整判据与自检四问见「创作分提升套件」第 6 节。

> ## 📮 每次执行完必须交付链接（v1.4.0，用户明确要求）
> 收尾回复里**必须逐条列出本次新增内容的可点击链接**，不是「已发布」三个字带过：
> - 回答：`https://www.zhihu.com/question/{qid}/answer/{aid}`
> - 文章：`https://zhuanlan.zhihu.com/p/{article_id}`
> - 想法：`https://www.zhihu.com/pin/{pin_id}`
> - 同时给 `aid`/`pin_id` 明文，便于用户自己复查。
> 硬约束：
> 1. **链接必须来自发布后真实跳转的 URL 或 CLI 返回的 id**，禁止用 qid 拼猜 aid。
> 2. **先在 `verify_via_cli.js` 拿到 `OK_NOT_COLLAPSED` 再给链接**；未通过就明确说「发布未确认，链接待复核」，不要给一个可能 404 的地址。
> 3. 一次执行发布多条（如回答 + 想法）就**列多条**，不能只给最后一条。
> 4. 本次只互动/只浏览、没有新增内容时，**明确写「本次无新增内容」**，不能沉默不交代。
> 5. 有折叠、审核未过、发布卡「发布中…」等情况，链接照给但**必须标注当前状态**。

> ## ⛔ 发布前两道硬门禁（v1.5.0，用户明确要求）
> **任何回答在点「发布」之前**（含 `run_shift.js` 三班编排、`write_answer.js`、手工 heredoc 插图发布）必须全部满足：
> 1. **去 AI 味**：加载 `text-humanize` skill（中文模式）改写正文 → 跑 `python3 scripts/humanize_gate.py <正文文件>` 拿到 `HUMANIZE_GATE_OK` → `run_shift.js` 校验凭证（正文 sha256 绑定、6h 有效、preflight fail=0），不过即 `ANSWER_SKIPPED: HUMANIZE_GATE_FAIL` 跳过发布。**只做「自检清单」不算通过，必须有凭证文件。**
> 2. **配图方式问用户**：用 `AskUserQuestion` 让用户三选一 **「网络图 / 用 batch-image-gen 生成 / 不配图」**，不得替用户决定、不得沿用上次选择；选了配图还要在发布前把编辑器截图 + 原图 + 定稿全文给用户做最终确认。
>
> 固定顺序：选题 → 写正文（含文案三条硬要求自检）→ text-humanize 改写 → 门禁凭证 → 问配图 → 填编辑器（dry run 校验）→ 用户最终确认 → 发布 → CLI 验证。详见「发布前强制流程」、第 6 节与 references/illustrations.md。

> ## ⛔ 跑之前先确认账号状态
> 若账号处于限流 / 禁言（`config.account_status.silenced=true`），**只做只读浏览**：
> - 跑 `scripts/browse_only.js`（零互动浏览）；**不要**跑发布 / 点赞 / 收藏 / 关注 / 评论 / 想法。
> - `run_shift.js` 已内置硬护栏（`silenced=true` 时加载配置后立即退出），但不要依赖它兜底。
> - 解除后先只开 morning `answer=true`，1 答/天跑两周再评估是否恢复三班。
> 详见下方「账号受限期模式」章节；账号状态只改 `config.json` 的 `account_status`。

一套依赖 ego-browser 的知乎养号全流程，支持 **垂直领域收敛 + 用户可配置话题池 + 早/中/晚三班节奏 + 深度版回答 + 想法发布 + 影响力规范**：

- **垂直收敛**：账号只养 2 个领域（当前「趣味历史」+「人文心理」），刻意埋关键词帮算法点亮创作垂直度。
- **选题**：全局 `topic_pool`，三班按「日序号 + 班次偏移」自动轮转取关键词（见 references/topic-strategy.md）。
- **每日每班 1 回答**：写 / 发布 / 折叠验证（你已选择三班各写 1 回答 = 3 回答/天，属自定义高风险，见下方⚠️）。
- **深度版**：每周 1 篇 800–1200 字深度回答（用户邀请 or 自动随机），冲内容优质分。
- **想法**：每周若干条短动态，冲关注者亲密度。
- **影响力规范**：每篇回答必须带反直觉 hook + 可操作清单 + 引导互动，并在 24h 内回评论。
- **文案三条硬要求（v1.5.1）**：观点先行 / 干净利落 / 有深度和判断，动笔前必读，详见创作分提升套件第 6 节。
- **点赞互动**：前 10 个回答里随机选 3–5 个点赞（自然化：位置随机，不固定点前 N 个），三班各自独立会话。
- **可选互动**：收藏 / 关注问题 / 评论，按 `config.json` 每班 `interactions` 用户自定义。
- **发布前去 AI 味硬门禁（v1.5.0）**：`text-humanize`（中文模式）改写 + preflight 检查器 FAIL 归零 + `humanize_gate.py` 写入与正文 sha256 绑定的凭证，`run_shift.js` 不验凭证就不发布。
- **配图询问（v1.5.0）**：每次发布回答前用 `AskUserQuestion` 问用户「网络图 / 用 batch-image-gen 生成 / 不配图」，三条路径与插图实现见 references/illustrations.md。

可在任意装了 ego-browser 的机器上独立运行，不依赖本工作区记忆。

## 何时使用
- 用户说「知乎养号」「养知乎号」「今天养号」「发知乎回答」「知乎点赞 / 互动 / 浏览」「三班养号」「按话题养号」。
- 用户说「写深度版 / 这篇写深一点」「发个想法 / 发动态」「提升创作分 / 创作分复盘」「点亮垂直度」。
- 用户要在新机器上跑一套**话题可配置、带三班节奏**的知乎增长 routine。

## 前置依赖（必须）
1. 已安装 ego-browser（ego lite 浏览器 + CLI）。知乎账号在 ego-browser 中已登录（继承系统登录态，无需单独登录）。
2. ⚠️ **沙箱必须关闭**：ego-browser 的 Mach port IPC 会被 WorkBuddy 沙箱拦截。运行所有 `ego-browser nodejs` 命令时：
   - Bash 工具加 `dangerouslyDisableSandbox: true`；
   - 并在 WorkBuddy 安全中心临时关闭「沙箱安全」顶部开关（用完开回），否则报 `Failed to connect to ego_cli bootstrap`。
3. **配置话题与班次**（用户自定义）：`mkdir -p ~/space/skills-data/zhihu-yanghao && cp config.example.json ~/space/skills-data/zhihu-yanghao/config.json`，按你的账号/话题/互动修改。**配置放数据目录（skill 目录外）**，升级或整目录镜像覆盖都不会丢，多个 agent 共用同一份（详见 references/workflow.md 的「配置 config.json」）。
   - ⚠️ **配置已不在 skill 目录内**：包里只有 `config.example.json`。每班看 `CONFIG_LOADED` 输出，正常应指向 `~/space/skills-data/zhihu-yanghao/config.json`；若指向 `config.example.json` 立即停手——模板 `shifts` 三班 `answer` 全 `true`，会突破 1 回答/天红线。
4. **`text-humanize` skill（v1.5.0 起发布必需）**：`~/.workbuddy/skills/text-humanize/scripts/preflight-check.py`。`humanize_gate.py` 会自动定位它；装在别处用 `--preflight` 或环境变量 `TEXT_HUMANIZE_PREFLIGHT` 指定。缺了它，门禁会拦下发布（fail-safe）。
5. **配图按需依赖**：选「网络图」→ 能访问 Wikimedia Commons 并下载图片；选「用 batch-image-gen 生成」→ 批量生图 skill（本机名为 `imagegen-batch`）+ ImageGen 能力；选「不配图」→ 无额外依赖。

## 依赖
- **Python**：仅 `scripts/humanize_gate.py` 使用 **Python 3.8+ 标准库**（`argparse` / `hashlib` / `json` / `subprocess` / `pathlib`），**无需 pip install**。
- **Node / ego-browser**：`scripts/*.js` 由 `ego-browser nodejs` 运行时执行（`require('fs')` / `require('path')` / `require('crypto')` 均为内建），不需要本地 `npm install`。
- **外部 skill**：`text-humanize`（发布门禁必需）、`imagegen-batch` + ImageGen（仅当用户选「用 batch-image-gen 生成」配图时）。
- **系统命令**：`python3`；下载网络配图时 `curl`；`zhihu-cli`（可选，热榜扫描与折叠验证）。
- 凭证与临时文件一律写在 `/tmp/` 或用户指定路径，**不在 skill 目录内写数据**（skill 更新会被覆盖）。

## ⚠️ 三班各写 1 回答（自定义高风险，你必须知道）
你选择「三班各写 1 回答」= **3 回答/天**，超出 skill 默认保守的「1 回答/天」红线。实现上每班是**独立会话、间隔数小时**，满足「单次任务 ≤ 1 回答」「1 分钟内不连发」，但**日总量更高**：
- 7/27 限流根因是「1 分钟内连发 + 秒赞」，不是日总量；但日总量过高仍会增加画像风险。
- **若账号再次被限流**：先把 `config.json` 的三班 `answer` 改回仅 `morning: true`、其余 `false`（降回 1 回答/天），等风控释放。
- 评论（`comment`）默认关闭——知乎评论触发审核敏感，最易翻车，未验证前不要开。

## 风控红线（最高优先级，必读）
加载并严格遵守 references/risk-control.md。7/27 因连发 / 秒赞被临时限制 7 天，以下为硬约束：
- 🚫 1 分钟内连发 > 1 条创作内容（回答）；**单班任务 ≤ 1 回答**（三班 = 3 个独立任务）。
- 🚫 点赞 / 评论间隔 < 30 秒（知乎）；< 8 秒绝对禁止（全局）。
- 🚫 单任务操作密度 > 15 次 / 20 分钟。
- ⚠️ 任务前后各闲逛 3–5 分钟（热榜 / 推荐 / 关注）混入自然流量；发布前模拟阅读 5 分钟 + 发布前等 60 秒。
- ⚠️ 三班跨任务间隔 ≥ 2 小时（早 7:50 / 午 12:30 / 晚 20:00 天然满足）。

## 🔒 发布前强制流程（v1.5.0，两道硬门禁）

**顺序不可调换**：选题 → 写正文（过文案三条硬要求自检）→ text-humanize 改写 → 门禁凭证 → 问配图 → 填编辑器（dry run 校验）→ 用户最终确认 → 发布 → CLI 验证。
适用于所有发布路径：`run_shift.js` / `write_answer.js` / 手工 heredoc（插图必须走手工路径）。
写作阶段自检是门禁 1 的前置条件：正文没亮观点、堆了情绪铺垫，先改稿再跑 `humanize_gate.py`（凭证绑定正文 sha256，改字即失效，别反过来）。

### 门禁 1：text-humanize 去 AI 味（程序化拦截，不可跳过）

用户明确要求「发布前必须过 text-humanize 去 AI 味儿」，**不是**列个自检清单打勾：

```bash
# ① 先用 Skill 工具加载 text-humanize（中文模式）改写正文：
#    知乎回答默认按 long 档（不注入错别字，去模板骨架 + 节奏错落 + 第一人称真实经历）
#    改到无 FAIL 为止；定稿写入 /abs/answer.txt（含文末配图署名行，如有）
# ② 跑门禁（自动调用 ~/.workbuddy/skills/text-humanize/scripts/preflight-check.py，参数 --tier long --lang zh --json）
python3 scripts/humanize_gate.py /abs/answer.txt
#    → HUMANIZE_GATE_OK: tier=long fail=0 warn=N ... 且写入 /tmp/zhihu_humanize_pass.json
#    → HUMANIZE_GATE_FAIL 时旧凭证被删除、退出码 1，必须改稿重跑，禁止绕过
```

- 凭证字段：`contentFile` / `sha256`（正文全文）/ `length` / `tier` / `fail=0` / `checkedAt` / `maxAgeHours`。**正文改一个字，凭证即失效**。
- `run_shift.js` 在字数护栏之后、打开编辑器之前校验凭证：`ok=true` + sha256 一致 + contentFile 一致 + `fail=0` + 未超 6h；任一不过输出 `ANSWER_SKIPPED: HUMANIZE_GATE_FAIL`，**点赞/互动照常收尾但绝不发布**。日志 `HUMANIZE_GATE_OK` 是放行信号。
- 手工 heredoc 发布（含插图）时脚本没有内建校验 → agent 必须自己先跑 `humanize_gate.py` 并确认 `HUMANIZE_GATE_OK`，且在日报里记一行 `HUMANIZE_GATE_OK`。**别拿「我看了一遍没有 AI 味」当通过。**
- `WARN` 默认不阻断（只记录），`--strict` 可让 WARN 也拦；FAIL 永远阻断。
- `config.publish_gates.humanize.enabled=false` 可显式关闭（仅限未安装 text-humanize 的机器，会输出 `WARN: HUMANIZE_GATE_DISABLED`）——本机必须保持 `true`。**旧配置里没有 `publish_gates` 块时默认强制开启**（fail-safe），不会因缺配置而静默放行。
- 门禁管的是「发布」，不管「写作」：想法 / 动态（`post_moment.js`）不受此门禁约束，但仍按 `influence` 规范写。

### 门禁 2：配图方式必须问用户（每次发布都问）

正文定稿、门禁通过后、填编辑器之前，用 `AskUserQuestion` 问且只问一次：

| 选项 | agent 后续动作 |
|---|---|
| **网络图** | 找可自由使用的实拍/史料图（Wikimedia Commons API）→ 查授权 → 下载本地 → `ViewImage` 验画面 → 上传知乎图床 → 文末署名 |
| **用 batch-image-gen 生成** | 加载批量生图 skill（本机实名 `imagegen-batch`；用户口中的 batch-image-gen 即它）→ 唯一前缀 + 顺序发 + 裁 AI 水印 → 文末标注「配图为 AI 生成」 |
| **不配图** | 纯文字发布，正文不留图片占位行 |

- **不得替用户决定、不得沿用上次选择**；用户可自填（如给本地图片路径），按共用插图流程走。
- **无人值守例外**：定时任务自动触发、当前会话无法向用户提问时，**默认按「不配图」发布**（最保守、不改变正文），并在日报写 `ILLUSTRATION: 不配图（无人值守默认）`；不要在无人值守时自行选网络图或生成图。交互式任务一律照常询问。
- 默认 1–2 张（上限 `config.publish_gates.illustration.max_images`，默认 2）。
- 选了配图 → 用新版 `taskSpace()/page()` + `setInputFiles('input[accept*="image"]', path)` 分段插图，先 dry run 校验「图片全部加载成功 + 顺序正确 + 截图给用户」，再 `AskUserQuestion` 拿**最终发布同意**。完整代码骨架、授权查询、坑清单见 references/illustrations.md。
- ⚠️ 账号处于解封观察期 / 近期被贴「内容疑似 AI 生成」标签时，AI 生成图要慎用（平台有专项治理），优先网络图或不配图，并在日报里记录用户选择。
- 对用户发布动作的铁律不变：**对外发布前必须把内容给用户确认，拿到明确同意才能点发布**。

### 禁止事项
- 🚫 跳过 `humanize_gate.py` 直接发布，或用旧凭证发新稿。
- 🚫 配图方式不问用户就自己选图 / 沿用上次。
- 🚫 用 `【图1】` 占位文字代替真实图片发布（编辑器不渲染，会字面残留）。
- 🚫 无授权 / 带水印 / 含文字 Logo 的网络图；AI 生成图不标注。

## 运行模式（推荐：三班编排）
用 `scripts/run_shift.js` 一把跑完一个班的「选题(可轮转) → 点赞 → 写回答 → 验证 → 可选收藏/关注/评论」，配置全在 `config.json`：
> ⚠️ **环境变量注意（本机实测关键）**：部分 ego-browser 构建的 `nodejs` 子命令**不继承 shell 环境变量**（`CONFIG`/`SHIFT` 会被丢弃，且进程 `cwd` 锁死为 `/`）。因此 `CONFIG=... SHIFT=... ego-browser nodejs < script` 在本机跑不起来。可靠写法见下方 heredoc。

```bash
ego-browser nodejs <<'EOF'
const fs = require('fs');
const path = require('path');
// ⚠️ 驻留进程 env 粘滞（2026-09-12 本机实测）：ego-browser nodejs 的 process.env 跨调用残留，
// 上次设过的 SHIFT/QID/CONTENT_FILE 会一直活着，导致 loadParams 判 p.shift 为真、跳过参数文件，
// deep 等仅存在于参数文件的字段永远读不到。启动器必须显式 delete。
delete process.env.SHIFT;
delete process.env.QID;
delete process.env.CONTENT_FILE;
delete process.env.CONTENT;
delete process.env.CONFIG;   // 配置已外置，缺省读 ~/space/skills-data/zhihu-yanghao/config.json；同样防 env 粘滞
process.env.SHIFT = 'morning';
const keep = setInterval(function () {}, 1000);
const src = fs.readFileSync(path.join(process.env.HOME, '.workbuddy', 'skills', 'zhihu-yanghao', 'scripts', 'run_shift.js'), 'utf8');
Promise.resolve(eval(src)).then(
  function () { clearInterval(keep); cliLog('=== SHIFT_DONE_OK ==='); },
  function (e) { clearInterval(keep); cliLog('=== SHIFT_ERROR: ' + (e && e.message) + ' ==='); }
);
EOF
```

> ⚠️ **上面这个启动器有三条硬约束，改动前先看（2026-09-05 实测踩坑）**：
> ① **heredoc 里不能出现顶层 `await`**——`require` 与顶层 `await` 同时存在会触发 node 模块格式自动探测冲突，直接报 `ReferenceError: Cannot determine intended module format`。这不是本机环境问题，**所有机器都一样**。
> ② **`eval(src)` 返回的 Promise 必须有人接管**（上面的 `.then`）。脚本主体是 `(async () => {...})()`，若写成 `(function(){ eval(src); })()`，运行时会认为同步代码已跑完并结束会话，异步流程被丢弃——症状是「跑了三四分钟、零输出、什么都没做」。
> ③ `setInterval` 保活，防止进程在等待浏览器 I/O 时提前退出。
> 备选：确实需要顶层 await 时改用 `import fs from 'node:fs'`（ESM 模式），但 eval 进来的脚本内部若有 `require` 会挂。
> 📌 另注：`cliLog` 输出走 **stderr**，且**延迟到进程结束才 flush**；后台运行时中途看不到日志是正常现象，不要误判为卡死。

三班只需改 `process.env.SHIFT` 为 `noon` / `evening`；指定问题覆盖时额外 `process.env.QID = '...'` + `process.env.CONTENT_FILE = '/tmp/answer.txt'`。

> 📌 **本机保留修正（勿在下次 GitHub 更新时回退）**：① 点赞选择器用 `button[aria-label*=赞同]`（新版知乎 `VoteButton` 已失效）；② 写回答用 `ClipboardEvent` 粘贴注入（Draft.js 不认 `fillInput`）；③ 上方 heredoc 注入 env + `.then` 接管 Promise（覆盖 `CONFIG=...` 写法与裸 `eval` 写法）；④ 关注问题按钮按 `FollowButton` class 匹配（页面文案是「关注」/「已关注」，**从不存在**「关注问题」四个字，旧写法永远返回 `no_button`）。前三条是本机 8/11–8/16 实测结论，第 ④ 条为 9/5 实测。脚本内部已含「已答过跳过 + 已赞跳过 + 随机选赞（前10随机3-5） + 发布卡死即停 + is_collapsed 验证带 retry(3-5次/10-15s)」。详细 env 与配置见 references/workflow.md。

## 创作分提升套件（v1.3.0 四件套，v1.3.7 增第 5 节去指纹化规范，v1.5.1 增第 6 节文案三条硬要求）
针对知乎创作分六维体系（创作活跃度 / 创作垂直度 / 内容优质分 / 创作影响力 / 关注者亲密度 / 社区成就分）的定向优化，全部由 `config.json` 驱动：

### 1. 垂直度收敛（`vertical_focus`）
账号只养 **2 个领域**，不再横跨多领域。当前锁定 **「趣味历史」+「人文心理」**（见 `config.vertical_focus.primary`）。
- 每篇回答**刻意自然融入 2–3 个本领域关键词**（见 `keyword_hints`），帮算法识别并点亮创作垂直度。
- `topic_pool` 按历史类 / 人文类**交替排列**，保证轮转取到的 3 个关键词横跨两个领域，既集中又不单一。
- 🚫 不在垂直领域外的话题下写回答（产品 / 财务 / 职场 / 社会热点一律不写），否则垂直度永远点不亮。

### 2. 深度版回答（`deep_answer`，每周 1 篇）
内容优质分是**周更**维度，靠"被算法识别为优质内容"涨分，标准回答（250–800 字）拉不动。每周至少 1 篇深度版：
- **触发方式**（`config.deep_answer.mode`）：
  - `auto`（默认）：用户说「深度版 / 写深一点」即 **invite 触发**；否则每周**随机挑 1 班**自动走深度版。
  - `invite`：仅用户显式邀请时写。
  - `random`：仅按周自动随机，不接受指定。
- **字数**：800–1200 字（普通回答是 250–800）。
- **硬性三项要求**（`config.deep_answer.requirements`）：① 1 处可核查的史料原文 / 数据 / 案例；② 1 组对比结构（分层或表格化）；③ 1 段可操作的判断框架或结论。
- 深度版同样走 `run_shift.js` 发布流程，只是正文按深度规范生成，**流程无差别**。

### 3. 想法 / 动态（`moments`）
关注者亲密度是**月更**维度，且是提升性价比最高的一项——想法（知乎动态）短、频、轻，不需要深度。
- 频率：`config.moments.per_week`（默认 4 条 / 周），长度 50–150 字。
- 内容方向见 `config.moments.topics`（读史笔记 / 历史冷知识 / 生活心理观察 / 读书摘录+点评）。
- **已自动化**：`scripts/post_moment.js`（2026-08-31 实测选择器 + dryRun 验证通过）：
  ```
  echo '{"contentFile":"/abs/moment.txt","dryRun":true}' > /tmp/zhihu_moment_params.json
  ego-browser nodejs < scripts/post_moment.js
  ```
  建议新机器首次跑先带 `dryRun: true`（只填不发布），确认无异常再写 `"dryRun": false` 实发。
  ⚠️ **默认 fail-safe**：不设置 `dryRun` 时一律只填不发布，实发必须显式写 `"dryRun": false`。

### 4. 创作影响力要求（`influence`）
影响力 ≠ 点赞数。**收藏、评论、分享的权重高于赞同**——自动点赞只贡献赞同，必须靠内容质量拉动收藏与评论。每篇回答必须满足：
- **hook**：中段抛 1 个反直觉 / 反常识观点，让人产生想反驳或补充的冲动（拉评论）。⚠️ 2026-09-14 起禁止放开头第一句——「先说个反直觉判断」系开头是折叠的高风险特征（详见下方第 5 节去指纹化规范）。
- **actionable**：至少 1 个可操作清单 / 判断框架 / 步骤（如「判断 X 的 3 步法」）（拉收藏）。
- **cta**：结尾**禁止机械问号收尾**（如「你觉得…？」「你遇到过类似情况吗？」——典型 AI 味收尾，2026-09-09 用户明确反馈）。用观点 / 判断 / 留白自然收束；互动引导靠观点本身的争议性，不在结尾向读者提问。
- **去 AI 味（v1.5.0 起为发布硬门禁，不是自检清单）**：必须加载 `text-humanize` skill（中文模式）改写 → preflight 检查器 FAIL 归零 → `python3 scripts/humanize_gate.py <正文文件>` 拿到 `HUMANIZE_GATE_OK` 凭证；`run_shift.js` 校验凭证后才允许发布（完整流程见「发布前强制流程」）。机械检查之外，人工复核仍按六项：① 结尾无问号互动收尾；② 编号列表尽量融进叙述（纯文本「1.」仅在清单天然成立时用）；③ 破折号「——」≤1 处；④ 至少 1–2 个语气词（吧 / 嘛 / 说白了 / 讲真 / 还挺）；⑤ 节奏参差，别句句等长；⑥ 长文档不注入错别字（短文本档才留「的/地/得」类小瑕疵）。
- **评论回复**：发布后 24h 内回复全部评论（`config.influence.comment_reply`），互动率直接影响影响力分。**由 agent 执行（无脚本）**：agent 应在下一次养号任务开始时，先用 CLI 查上一班回答的评论并回复，或提醒用户手动回复。⚠️ **已知限制（2026-09-14 实测）**：ego-browser 里评论弹窗点击「N 条评论」后**始终卡在 ModalLoading**（15s+ 不加载列表，「回复」按钮不渲染），自动化回复不可行；全元素扫描 + hover 事件派发均无效。替代：① 用户手动回；② 试 Kimi WebBridge（真浏览器扩展环境）。⚠️ 别在 ego-browser 反复重试评论弹窗——同页反复加载有操作密度风险。

### 5. 内容去指纹化写作规范（2026-09-14，应对知乎「隐藏机制」批量折叠）
背景：2026-09-14 实测 87 篇回答中 51 篇被折叠（59%），折叠按时间窗成批出现（平台分批审核，疑似针对模板化内容的专项治理）；内容模板特征是次级嫌疑（有反例，但带指纹特征的折叠率显著偏高）。写作时执行：
- 🚫 **开头禁用「先说个反直觉判断」系模板**（含「先泼冷水 / 先抛结论 / 说个不太好听的判断 / 反直觉的是」等变体）——已用 12 次的头号指纹。反直觉 hook 一律放中段。
- **开头句式池（10 种，轮换使用）**：
  1. 场景切入：先讲一个小场景或一段对话，再引出问题
  2. 时间锚点：「某某年，某地……」直接把时代背景铺开
  3. 材料先行：先给史料原文 / 数据 / 报道，再解读
  4. 人物视角：从当事人（小人物尤佳）的处境讲起
  5. 疑问承接：把问题里的关键词接过来现场拆字 / 拆词
  6. 类比引入：拿一件完全无关的小事打比方
  7. 反面案例：先讲一个做错的 / 翻车的真实例子
  8. 朴素直陈：不用钩子，平铺直叙给背景（最像人写的）
  9. 引用他人：书里 / 前人的一句话起头（受掉书袋限额约束）
  10. 反差细节：一个具体的冷知识 / 细节切入（是细节不是观点判断，与被禁模板划清界限）

  轮换规则：同一周内开头句式不重复；同一句式连续使用不超过 2 次。每次生成正文前，先回顾近 5 篇用过的句式再挑。
- **分层拆解降频**：「第一层 / 第二层 / 三步法 / 一、二、」类显性分层结构每周 ≤1 篇，其余回答把层次融进叙述。
- **术语词降频**：「心理机制 / 视角拆解 / 从 X 角度看」类分析腔每周 ≤2 篇，能用口语替换就用口语。
- **真实经验优先（2026-09-15 起强制）**：每篇至少 1 处第一人称真实经历 / 具体场景细节；禁止"资料整理型通稿"（背景→原因→影响→总结 的通用科普骨架）。禁言整改要求即"分享真实知识、经验和见解"，宁可少写。
- **掉书袋限额**：引用（书名 / 人名 / 原文）每篇 ≤1 处、每周 ≤2 篇；引用必须服务于论点而非装饰。

> **配置分工（重要，勿误解）**：`vertical_focus` / `deep_answer` / `influence` 三个配置块是**给 agent 的写作规范**——`vertical_focus`/`influence` 不被脚本读取；`deep_answer.min_words/max_words` 在参数文件写 `"deep": true` 时被 `run_shift.js` 用于字数护栏；各班 `shifts.*.interactions` 被 `run_shift.js` 读取执行。
> **字数护栏（v1.3.3）**：`run_shift.js` 发布前校验 contentFile 字符数——标准区间 `answer_style.min/max_words`（250–800）、深度版（参数 `"deep": true`）区间 `deep_answer.min/max_words`（800–1200）。**超区间输出 `ANSWER_SKIPPED: WORD_COUNT_EXCEEDED` 并跳过发布**（点赞/互动照常收尾），压缩或扩写正文后重跑即可（已赞自动跳过）。

### 6. 文案三条硬要求（2026-11-11，用户明确要求；动笔前必读）

三条原话：**要有明确观点且观点先行 / 不要磨磨唧唧，要干净利落 / 不要流于表面和情绪，要有深度和判断**。适用于全部回答（标准版 / 深度版）；想法（50–150 字）只按 ①② 收紧——首句给判断、句子短、不铺垫，③ 不要求硬料与对比结构（第 3 节明确「想法不需要深度」），但仍得有一个明确判断、不靠情绪词撑着。与第 5 节去指纹化、第 2 节深度版硬料、门禁 1 去 AI 味同时生效。

**① 观点先行**
- 首句或首段直接给一个**能被反驳的判断句**（有主谓、有立场），不是背景、共情、寒暄、复述问题、「这个问题其实挺复杂」。
- 判断要具体到能被反驳：写「改名解决的是户口本，不是教室」「最不顶用的动作是赶紧去改名」，不写「值得深思」「要理性看待」这类零信息量表态。
- 正例即 2026-11-11 晚班定稿首句「改名解决的是户口本，不是教室」——一句定立场，后面所有硬料都给它作证。
- ⚠️ **与第 5 节不冲突**：第 5 节禁的是「先说个反直觉判断 / 先泼冷水 / 反直觉的是」这类**元话语开场白**（先宣告「我要抛观点了」再说观点），不是不让亮观点。观点先行＝直接说判断本身；元话语仍禁。反直觉 hook 依旧放中段，不占首句。
- 开头句式池 10 种照旧轮换，但**无论用哪种句式，首段内必须落判断**（场景切入 / 材料先行也要在首段末尾给判断，不许拖到中段）。
- `influence.actionable` 的判断框架不能代替立场：清单是工具，观点是取舍，两样都要有。

**② 干净利落**
- 一句一个意思，长句拆短；删净缓冲垫句：「其实」「说实话」「不得不说」「在一定程度上」「我们可以看到」「值得注意的是」「说到这里」「先共情一下」「我理解…但是」。
- 不写共情铺垫、不写两段以上元叙述（「前排讲得很透我就不重复了」最多一句过渡）；不靠「背景→原因→影响→总结」的通用科普骨架撑字数。
- 每段只有一个功能：亮判断 → 给硬料 → 做对比 → 给判断框架 → 收束。回头数段：某段删掉不影响判断链，就删。
- 分层拆解仍受第 5 节「每周 ≤1 篇」限额，别用层级制造「看起来有结构」。
- 段落间不留连续空行（用户 2026-11-07 明确批评）：正文文件用单换行分段，编辑器 dry run 的 `doubleBlank` / `extraBlank` 必须都为 false（块内 `\n\n` 会在 Draft.js 生成空段落，2026-11-11 实测）。

**③ 有深度和判断**
- 不流于表面和情绪：不站队、不评判新闻当事人、不靠「太让人心疼了」「细思极恐」推进，不把前排高赞的共情 / 介入路线换个说法重讲。
- 深度＝至少 1 处**可核查硬料**（史料原文 / 法条 / 数据 / 真实案例）＋ 1 组**对比结构**（旧制 vs 今制、法律层 vs 生活层、名字归谁管 vs 谁在喊）＋ 把**机制**讲出来（为什么这动作解决不了问题、梗会迁移到哪个新载体）。前两项是深度版硬性要求（第 2 节）；标准版至少把机制讲透、给判断，不写空泛感慨。
- 判断＝给可迁移的原则或取舍，不是留白式感慨。11/11 稿落点「一个字段一天被调用几十次，出了问题先想改字段，其实该查的是调用它的那几个环节」即从个案抽到可复用框架。
- 反例：资料整理型通稿（第 5 节已禁）、「各有各的道理」式和稀泥、结尾抛问号把判断交还读者（cta 已禁）、情绪升华式收尾。
- 结尾用判断收束（「改名字是父母能办的事，不再被这样喊不是。」），不用情绪。

**自检四问（写完后、跑门禁前）**
1. 首句是不是一个能被反驳的判断？把第一段删掉，观点还在不在？
2. 有没有整句能删掉而不影响判断链？有就删。
3. 深度版的硬料能不能查到出处？有没有讲「为什么」，而不只是「是什么」？
4. 最后一段是判断 / 场景，还是情绪 / 问号 / 和稀泥？
任一不过先改稿，再跑 `humanize_gate.py`——凭证绑定正文 sha256，改一个字就要重跑，别反过来先跑门禁再改。

> **优先级**：三条与第 5 节、深度版三项硬料、门禁 1 同时生效。冲突时以「观点先行 + 不模板化」为准：不能拿「避免模板」当理由把判断藏到中段，也不能为了观点先行复用「先说个反直觉判断」系开头。

### 辅助脚本（含 v1.5.0 门禁）
- `scripts/humanize_gate.py`（**v1.5.0 发布前必跑**）：调 `text-humanize` 的 preflight，FAIL 归零才写 `/tmp/zhihu_humanize_pass.json`（绑定正文 sha256）；`--tier long` 默认、`--strict` 让 WARN 也拦、`--preflight` 指定检查器路径。输出 `HUMANIZE_GATE_OK` / `HUMANIZE_GATE_FAIL`。
- `scripts/like_top5.js`：对指定问题在前 10 个回答里随机选 3–5 个点赞（env: `QID`，可选 `POOL`/`LIKE_MIN`/`LIKE_MAX` 覆盖默认）。
- `scripts/write_answer.js`：写回答 + 发布（env: `QID` + `CONTENT_FILE`/`CONTENT`）。
- `scripts/verify_via_cli.js`：折叠状态权威验证（参数文件 `/tmp/zhihu_verify_params.json`：`aid`/`type`，或 env `AID`/`TYPE`）。自动定位 zhihu-cli（PATH → macOS 默认路径），Summary 非空=未折叠。**替代已删除的 verify_fold.js**（其 serverFetch API 8/26 起恒 403）。
- `scripts/pick_question.js`：扫热榜按关键词过滤输出候选 qid（env: `KW`、`LIMIT`）。⚠️ 本机 env 不透传，需把 `kwRaw` 改成硬编码或复制到 /tmp 修改后运行。
- `scripts/post_moment.js`：发想法 / 动态（参数文件 `/tmp/zhihu_moment_params.json`，支持 `dryRun`）。
- `scripts/edit_answer.js`：修改已发布回答（参数文件 `/tmp/zhihu_edit_params.json`：`aid`/`qid`/`contentFile`/`stripMarkdown`/`dryRun`）。⚠️ 已知限制：内容替换可行，但「提交修改」点击可能不生效（脚本会安全停止并提示人工确认）。
- `scripts/fold_audit.js`：折叠巡检（2026-09-14 新增）。滚动抓取创作者中心全部内容的「被折叠」标签，与基线 `~/space/skills-data/zhihu-yanghao/fold-baseline.json` 比对输出 `NEW_FOLDED` / `RECOVERED`。可选参数文件 `/tmp/zhihu_fold_params.json`（`{"update": true}` 写回基线，带防残缺护栏）。**每班开跑先跑一次**；基线在数据目录，换机器不用改代码（`ZHIHU_FOLD_BASELINE` 可覆盖）。
  ⚠️ 基线文件是**本机状态**（记录你账号的历史折叠快照），不随开源包分发；新机器首次跑会输出 `NO_BASELINE` 并只列全量状态，之后带 `{"update": true}` 跑一次即建立基线。
- `scripts/browse_only.js`：禁言期只读浏览（2026-09-15 新增）。热榜 → 按垂直领域词挑问题 → 逐页滚动停留 → 首页信息流，**零点击互动**（输出 `BROWSE_DONE ... interactions=0` 可验证）。可选参数文件 `/tmp/zhihu_browse_params.json`（`{"minutes": 6, "pages": 4, "keywords": [...]}`）。

DOM 选择器、按钮点击要点见 references/selectors.md。

## 账号受限期模式（`account_status.silenced`，v1.3.8）
账号被限流 / 禁言时（常见 7–30 天），养号必须降级为**只读浏览**——禁言期的任何写动作（回答/点赞/收藏/关注/评论/想法）不仅无效，还可能被判定为异常行为而加重处罚。

- **开关**：`config.json` 的 `account_status`（`silenced` / `silenced_from` / `silenced_until` / `reason`）。`silenced: true` 时：
  - `run_shift.js` 在配置加载后**立即退出**（`SILENCED_MODE` / `SHIFT_SKIPPED` 日志），不打开编辑器、不点赞、不互动——即使定时任务照常触发，也不可能误发内容。
  - 同时把三班 `answer` 置 `false`、`interactions.like.min/max` 置 `0`（双击保险，防误开）。
  - 日常动作改用 `scripts/browse_only.js`（只读：热榜 → 按垂直领域词挑问题 → 逐页滚动停留 → 首页信息流；`BROWSE_DONE interactions=0` 可验证零互动）。
- **受限期该做什么**：① 每天 1–2 次只读浏览（维持真实活跃度）；② 复盘存量内容与写作规范（见第 5 节）；③ **不要**批量删除/修改旧回答（会触发复审，可能加重处罚）；④ **不要**反复申诉。
- **解除后恢复节奏**：先把 `silenced` 改回 `false`，**只开 morning `answer=true`** 跑 1–2 周，观察新篇是否被贴「内容疑似 AI 生成」标签或被折叠，再决定是否恢复三班。
- **写作侧同步收紧**：平台对 AI 辅助创作的治理要求通常是"分享真实的知识、经验和见解"——恢复后每篇至少 1 处**第一人称真实经历或具体场景细节**，避免"资料整理型通稿"；宁可少写，不写结构工整的通用科普。

## 关键陷阱（务必先看）
- 🚨 **折叠 / AI 标签是账号级信号，不是单篇问题**（2026-09 实测）：完整前兆链条＝公开「内容疑似 AI 生成」标签 → 按时间窗批次折叠历史回答 → 账号限流 / 禁言。**结论：一旦出现 AI 标签或成批折叠，立刻当全账号事件处理**——停写整改（切受限期模式）、复盘写作规范，而不是继续试探。
- 🚨 **临时配置副本可能绕过禁言护栏**（2026-09-15 实测；配置外置后优先级已变）：`run_shift.js` 的 config 查找顺序是 参数文件 `configPath` → `CONFIG` env → `$WB_SKILLS_DATA/zhihu-yanghao/config.json`（默认 `~/space/skills-data`）→ `/tmp/zhihu_config.json` → 工作目录 `config.json` / `config.example.json` → 旧 skill 目录 `config.json` / `config.example.json`（兼容回退）。**配置数据外置后，正式配置排在 `/tmp/zhihu_config.json` 之前**，遗留的临时副本不再能悄悄顶替它；但显式传 `configPath` 或设 `CONFIG` env 仍排最前，一次性改字数用的副本若缺 `account_status`，护栏照样失效。防护：脚本选中 `/tmp/` 路径时输出 `WARN: 正在使用 /tmp 影子配置`；别用临时副本，改数据目录里的配置更稳，用完务必删。
- ⚠️ **发布按钮零宽字符导致静默不发布**（2026-09-15 修复）：原 `innerText.trim() === "发布回答"` 匹配——`trim()` **不去 `\u200b`**，按钮带零宽字符时静默 `publish-clicked: false`（正文已填、URL 不跳转、不报错）。已改为 `[\u200b\s]+` 清洗 + 主候选 `["发布回答","提交回答"]` + 回退「发布」（仅编辑器存在时）+ 跳过 disabled，并在未发布时输出 `SHIFT_PARTIAL_FAIL: publish`。
- ⚠️ **单问题重复操作密度**（2026-09-15 实测教训）：同一问题页 15 分钟内连续开编辑器 / 补发 3 次后，点「写回答」**不再挂载编辑器**（`.public-DraftEditor-content` 数=0，且非登录态问题——消息/私信仍在），属密度风控信号。规则：同页发布失败最多重试 1 次；再失败即停，等 1–2 小时或换班次重试；禁止在同一问题上连环试。
- ⚠️ **知乎「隐藏机制」批量折叠（2026-09 发现）**：平台按时间窗分批折叠历史回答（实测 87 篇中 51 篇被折，宽松期 / 收紧期交替 = 分批处理特征）。CLI Summary 验证对新机制**失明**（被折叠回答 Summary 仍非空），折叠的唯一权威信号是创作者中心列表的「被折叠」标签 → **每班开跑先跑 `scripts/fold_audit.js` 与基线比对**。另注意：新回答未被折 ≠ 安全，可能只是审核批次还没推进到，不能当作写作规范没问题的证据。
- ⚠️ **ego-browser nodejs 驻留进程 env 粘滞**（2026-09-12 实测）：`process.env` 跨调用残留——上次 heredoc 里设过的 `SHIFT`/`QID`/`CONTENT_FILE` 在后续所有调用中依然存活。`run_shift.js` 的 loadParams 只在 `p.shift` 为空时才读参数文件，因此 deep 等仅存在于 `/tmp/zhihu_shift_params.json` 的字段会被静默丢弃（症状：深度版正文被按标准区间 250-800 拦下报 `WORD_COUNT_EXCEEDED (standard)`，且日志里没有 `PARAMS_FROM_FILE`）。修复：启动器里 `delete process.env.SHIFT/QID/CONTENT_FILE/CONTENT` 再设新值；判别特征＝输出缺 `PARAMS_FROM_FILE` 这一行。
- ⚠️ **同一条 shell 命令串跑两个 ego-browser 脚本 → 第二个静默空跑**（2026-09-23 实测）：`A.js ; B.js` 串在一条命令里时，第二个调用可能什么都不执行——零日志、无错误、退出码 0（`cliLog` 无输出，连 `BROWSE_START`/`SILENCED_MODE` 这类首行标记都没有）。规则：**一个脚本一条命令**；任何脚本若缺少首行标记日志，一律判为"没跑"并单独重跑，不要凭退出码认为成功。
- ⛔ **去 AI 味凭证与正文 sha256 绑定（v1.5.0）**：先检查 A 稿、后来改了一个字直接发 B 稿，`run_shift.js` 会判 `HUMANIZE_GATE_FAIL` 并跳过发布。文末加配图署名行也要重跑门禁。别手改凭证、别复用旧凭证。
- ⚠️ **插图只能用新版 ego-browser API（11/06 实测）**：`run_shift.js` / `write_answer.js` 的纯文本路径不支持插图；插图走 `taskSpace()` → `t.page()` → `p.setInputFiles('input[accept*="image"]', path)`，编辑器里这个隐藏 input 一直存在，不必点工具栏图片按钮。旧版 `useOrCreateTaskSpace` + `js()` 没有 `setInputFiles`。
- ⚠️ **上传完成不能只看 img 数量**：`img` 节点先插入、图片还在上传时是白图；必须判 `i.complete && i.naturalWidth > 0` + src 已落到知乎图床，并给编辑器截图人工确认段落与图片顺序（见 references/illustrations.md）。
- ⚠️ **AI 生成配图的账号级风险**：平台对「内容疑似 AI 生成」有专项治理，解封观察期尤其慎用；用生成图必须文末标注，正文更要过第 5 节去指纹化规范。网络图必须查授权 + 署名，禁止热链外站。
- 🚫 **生成回答禁止输出 Markdown**（9/1）：编辑器不渲染，`**` / `- ` 按字面残留。纯文本排版用「1.」「· 」、破折号强调。配图占位文字（如「【图1】」）同样会字面残留，正文文件里不要写。
- 🚫 **永远不要对中文用 `String.raw`**（8/4 乱码事故）：`fillInput` 直接传 UTF-8 字符串。
- ✅ **点赞按钮（8/11 实测修正）**：旧 `button.VoteButton:not(.VoteButton--down)` / `button.VoteButton--up` 在新版知乎**已失效**；改用 `button[aria-label*="赞同"]`，aria-label 形如 `"已赞同 1020 "` / `"赞同 307"`（**含尾空格必须 trim**），已赞判定用 `classList.contains('is-active')`（class 含 `VoteButton is-active`）。
- ⚠️ **点赞按钮 innerText 含前导零宽字符 `\u200b`**（实测为 `"\u200b 已赞同 87"`），**不能用 `===` / `startsWith('赞同')` 精确匹配**；一律用 aria-label + trim（8/12 实测：innerText 精确匹配命中 0，aria-label 精确匹配命中）。
- ✅ 「写回答」按钮文本前有零宽字符 `\u200b`，用 `.includes('写回答')`；「发布回答」按钮**必须清洗零宽字符后再匹配**（`replace(/[\u200b\s]+/g,'')` ∈ `["发布回答","提交回答"]`）——见上方 2026-09-15 条目，旧 `trim()` 等值写法已废。
- 🚫 **发布卡「发布中…」disabled 即停**：不要重复点 / 重试（会在云端累积卡死草稿）。等待账号风控释放或手动在浏览器发布。
- ⚠️ **验证发布/修改成功一律用官方 CLI**：`zhihu-cli me contents --type answer --limit 3`（摘要完整=未折叠；想法用 `--type pin`）。`serverFetch('/api/v4/answers/{aid}')` 自 8/26 起持续 403 已失效——v1.3.3 起 `run_shift.js` 已**移除** API 验证死路，改用 `scripts/verify_via_cli.js`；页面摘要/浏览器侧信号均有假阴性。

## 验证发布成功
> 前置：发布前日志里应有 `HUMANIZE_GATE_OK`（或手工路径已在日报记 `HUMANIZE_GATE_OK`），且配图方式已由用户明确选择、发布内容已获用户确认。
1. 发布后 URL 跳转 `/question/{qid}/answer/{aid}`。
2. **权威校验**：`echo '{"aid":"<aid>","type":"answer"}' > /tmp/zhihu_verify_params.json && ego-browser nodejs < scripts/verify_via_cli.js` —— 输出 `VERIFY_RESULT: OK_NOT_COLLAPSED` 即成功（折叠则 `COLLAPSED`；`NOT_FOUND_YET` 是索引滞后，等 1–2 分钟重跑）。等价手工命令：`zhihu-cli me contents --type answer --limit 3` 看最新一条摘要是否完整。
3. **回报链接**（v1.4.0 起为强制收尾动作）：把 `https://www.zhihu.com/question/{qid}/answer/{aid}` 写进给用户的最终回复，同时给出 `aid`。见顶部「每次执行完必须交付链接」。

## 部署注意（本机 macOS 实测）
- ego-browser 可能不在 shell PATH：用绝对路径 `~/.local/bin/ego-browser`。
- zhihu-cli 通常不在 PATH：真实路径 `~/Library/Application Support/zhihu-cli/current/zhihu-cli`（verify_via_cli.js 已内置此回退）。

## 文件产出建议
- 日报：`output/zhihu/YYYY-MM-DD-{shift}.md`（shift: morning / noon / evening）。
- 日报里固定记一行 `URL: https://www.zhihu.com/question/{qid}/answer/{aid}`（文章 `/p/{id}`、想法 `/pin/{id}`），便于日后回查。
- 日报另记两行：`HUMANIZE_GATE_OK: tier=long fail=0 warn=N sha256=前12位` 与 `ILLUSTRATION: 网络图(2, 已署名) / batch-image-gen(2, 已标注) / 不配图`——便于复盘哪篇用了什么配图与是否过门禁。
- 任务空间用完 `completeTaskSpace(name, { keep: false })` 关闭。

## 参考资料
- references/risk-control.md — 风控红线与全局原则（必读）
- references/selectors.md — DOM 选择器 + ego-browser API 速查
- references/topic-strategy.md — 全局话题池、心智定位、三班轮转、写作规范（含文案三条硬要求指针）
- references/workflow.md — config.json 配置、脚本调用方式、env 变量、示例命令
- references/illustrations.md — 配图决策（网络图 / batch-image-gen / 不配图）+ 插图执行与 dry run 校验（v1.5.0）

## 版本变更
- **v1.5.1（2026-11-11）**：文案三条硬要求（用户明确要求，写作规范修订，脚本无改动）：
  1. **观点先行**：首句 / 首段给能被反驳的判断，禁铺垫、共情、寒暄；明确与第 5 节的边界——禁的是「先说个反直觉判断」系**元话语开场白**，不是不让亮观点，hook 仍放中段，开头句式池照旧轮换但首段内必须落判断。
  2. **干净利落**：句子砍短、删净缓冲垫句与元叙述、每段单功能；段落间不留连续空行（正文文件单换行分段，dry run 的 `doubleBlank` / `extraBlank` 必须为 false——2026-11-11 实测块内 `\n\n` 会生成空段落）。
  3. **有深度和判断**：不流于表面和情绪，硬料可核查 + 对比结构 + 机制讲透 + 可迁移判断，不站队、不和稀泥、不用情绪收尾。
  4. 新增「创作分提升套件」第 6 节（判据 / 正例 / 反例 / 自检四问）+ 顶部硬约束块；发布流程加「文案三条硬要求自检」前置；`answer_style.writing_rules` 配置块（脚本不读取）；统一 `influence.hook` 与第 5 节的冲突表述为「中段 hook、开头直接给判断」；README / topic-strategy / workflow 同步。正例取自 2026-11-11 晚班定稿（未折叠）。
- **v1.5.0（2026-11-06）**：发布前两道硬门禁（用户明确要求）——去 AI 味 + 配图询问：
  1. **text-humanize 从「自检清单」升级为程序化硬门禁**：新增 `scripts/humanize_gate.py`（调 `~/.workbuddy/skills/text-humanize/scripts/preflight-check.py`，参数 `--tier long --lang zh --json`，FAIL 归零才写凭证；凭证绑定正文 sha256 + contentFile + 6h 时效）；`run_shift.js` 在字数护栏后、打开编辑器前校验，不过输出 `ANSWER_SKIPPED: HUMANIZE_GATE_FAIL` 并跳过发布（点赞/互动照常收尾）。失败时删除旧凭证，杜绝「检查 A 稿发 B 稿」。`config.publish_gates.humanize.enabled` 默认 true；`false` 仅限无 text-humanize 的机器并输出 WARN。
  2. **配图方式必须问用户**：每次发布回答前用 `AskUserQuestion` 三选一「网络图 / 用 batch-image-gen 生成 / 不配图」，不得替用户决定或沿用上次；新增 `references/illustrations.md`（Commons 授权查证、`imagegen-batch` 生成要点、新版 `taskSpace()/page()/setInputFiles` 插图流程、dry run 校验、发布前最终确认、坑清单）。
  3. `config` 新增 `publish_gates` 块（humanize + illustration）；SKILL.md 新增「发布前强制流程」章节、关键陷阱 4 条、日报两行记录；README / workflow / topic-strategy / risk-control / selectors 同步。
  4. 实测：门禁通过态（`HUMANIZE_GATE_OK fail=0 warn=1`）、FAIL 拦截态（fail=3，旧凭证被删）、ego-browser 运行时 `crypto` sha256 与凭证一致；插图流程来自 2026-11-06 首篇含 2 图回答（aid 2102105727993124823，未折叠）的实操。
- **v1.4.0（2026-11-03）**：新增「交付链接」硬规则（用户明确要求）——每次执行完的收尾回复必须逐条列出本次新增内容的可点击链接（回答 `/question/{qid}/answer/{aid}`、文章 `/p/{id}`、想法 `/pin/{id}`）+ 明文 id；链接只能来自真实跳转 URL 或 CLI 返回 id，禁止用 qid 拼猜；须先 `OK_NOT_COLLAPSED` 再给链接，未确认要标注状态；无新增内容须显式说明。同步写入「验证发布成功」第 3 步与 references/workflow.md。
- **v1.3.9（2026-10-19）**：`write_answer.js` 发布按钮零宽字符修复（同步 run_shift.js v1.3.7 已验证逻辑）：
  1. 旧 `innerText.trim() === "发布回答"` 不去 `\u200b`——按钮带零宽字符时静默 `publish-clicked: false`（正文已填、URL 不跳转、不报错）。2026-10-19 实测复现该坑后修复。
  2. 改为 `[\u200b\s]+` 清洗 + 主候选 `["发布回答","提交回答"]` + 回退「发布」（仅编辑器存在时）+ 跳过 `disabled`，失败时输出 `WRITE_ANSWER_PARTIAL_FAIL: publish`（同页禁止重试）。
  3. 已实测发布成功（37 字短回答，CLI 验证 `OK_NOT_COLLAPSED`）。
- **v1.3.8（2026-09-15）**：账号受限期（限流 / 禁言）降级能力与写作整改：
  1. **禁言期模式**：`config.account_status.silenced` 开关 + `run_shift.js` 配置加载后立即退出的硬护栏（`SILENCED_MODE`/`SHIFT_SKIPPED`）；三班 `answer=false`、`interactions.like.min/max=0` 双击保险。
  2. **新增 `scripts/browse_only.js`**：只读浏览（热榜 → 垂直领域问题 → 滚动停留 → 首页流），零点击互动，用于禁言期维持活跃度。
  3. **新增影子配置告警**：`/tmp/zhihu_config.json` 会覆盖正式 config 并绕过 `account_status` 护栏 → 选中 `/tmp/` 路径时输出 WARN（实测 9/15 曾因此绕过护栏）。〔配置数据外置后已订正：正式配置优先于 `/tmp`，现行顺序见「关键陷阱」；本条保留为 v1.3.8 当时实现的历史记录。〕
  4. **陷阱新增账号级风险链路**：AI 标签 → 批次折叠 → 账号限流/禁言；折叠与 AI 标签一律按账号级事件处理，不再当单篇问题。
  5. 新增「受限期该做什么 / 解除后恢复节奏」：解除后先只开 morning 1 答/天跑两周；写作侧要求每篇至少 1 处第一人称真实经历，避免资料整理型通稿。
  6. 本机 `config.json` 的 `account_status` 记录真实处罚窗口；**开源文档只描述通用机制，不含具体账号的处罚细节**。
- **v1.3.7（2026-09-15）**：应对知乎「隐藏机制」批量折叠 + 发布链路两处修复：
  1. **新增「内容去指纹化写作规范」**（第 5 节）：禁「先说个反直觉判断」系开头（hook 移中段）；开头句式池 10 种轮换（场景切入 / 时间锚点 / 材料先行 / 人物视角 / 疑问承接 / 类比引入 / 反面案例 / 朴素直陈 / 引用他人 / 反差细节），同周不重复、同句式连用 ≤2；分层拆解每周 ≤1 篇、分析术语每周 ≤2 篇、掉书袋每篇 ≤1 处且每周 ≤2 篇。
  2. **新增 `scripts/fold_audit.js`**：折叠巡检（滚动抓创作者中心「被折叠」标签 + 基线比对 `NEW_FOLDED`/`RECOVERED`），每班开跑先跑；「关键陷阱」新增折叠机制条目（CLI Summary 对新机制失明，唯一权威信号=创作者中心标签）。
  3. **`run_shift.js` 发布按钮匹配修复**：原 `innerText.trim() === "发布回答"` 不去零宽字符 `\u200b`，带零宽字符的按钮会静默 `publish-clicked: false`（正文已填、URL 不跳转、不报错）；改为 `[\u200b\s]+` 清洗 + 候选 `["发布回答","发布"]` + 跳过 `disabled`。
  4. **新增两条陷阱**：发布按钮零宽字符；同问题页重复操作密度（15 分钟内连续补发 3 次后「写回答」不再挂载编辑器，登录态正常）→ 规则：同页发布失败最多重试 1 次，再失败停 1–2 小时或换班次。
  5. **评论回复已知限制**：ego-browser 里评论弹窗恒卡 `ModalLoading`（回复按钮不渲染），自动化不可行 → 人工或 Kimi WebBridge。
- **v1.3.6（2026-09-12）**：修复驻留进程 env 粘滞导致的 deep 标志静默失效（文档修正，脚本无改动）：
  1. **启动器模板增加显式 delete**：ego-browser nodejs 为驻留进程，`process.env` 跨调用残留——上次 heredoc 设过的 `SHIFT`/`QID`/`CONTENT_FILE` 会让 `run_shift.js` 的 loadParams 跳过参数文件，`deep` 等仅存在于 `/tmp/zhihu_shift_params.json` 的字段被静默丢弃（深度版正文被按标准区间拦下，日志缺 `PARAMS_FROM_FILE` 行为判别特征）。模板现在先 `delete process.env.SHIFT/QID/CONTENT_FILE/CONTENT` 再设新值。
  2. 「关键陷阱」新增该条目，含症状与判别方法。2026-09-12 午班实测：同稿三轮被拦，清理残留 env 后第四轮 `WORD_COUNT_OK (deep)` 一次通过。
- **v1.3.5（2026-09-09）**：内容去 AI 味与选题错峰（写作规范修订，脚本无改动）：
  1. **cta 禁止机械问号收尾**：「你觉得…？」「你遇到过类似情况吗？」这类结尾是典型 AI 味收尾（读者已免疫），改为观点/判断/留白收束，互动引导靠观点本身的争议性。同步修订 config `influence.cta`、topic-strategy、workflow。
  2. **发布前去 AI 味自检（必做，接 text-humanize skill 中文模式）**：结尾无问号互动收尾；编号列表尽量融进叙述；破折号「——」≤1；语气词 1–2 个（吧/嘛/说白了/讲真/还挺）；节奏参差；可留 1 处「的/地/得」类小瑕疵。
  3. **轮转重叠顺延**：本班轮转词与当日已答班次题材同域同主方向时（如午班刚写西游记、晚班轮转又给神话），agent 选题顺延到 pool 下一词，优先保证跨班领域交替，防单一人设指纹。
- **v1.3.4（2026-09-05）**：补齐两个「写了但从未真正生效」的实测修复（均经同一页面对照实证验证）：
  1. **关注问题按钮选择器**（`run_shift.js`）：旧写法按 innerText 匹配 `"关注问题"`，但知乎页面上该控件文案只有「关注」/「已关注」（class `FollowButton`），字符串 `"关注问题"` 从未出现过，故永远返回 `no_button`。改为**先按 `FollowButton` class 匹配、回退按文案精确匹配**；命中「已关注」判为 `already`，避免误点成取消关注。实证：同一页面旧写法 `no_button` → 新写法 `already`。
  2. **启动器必须接管 Promise**（`SKILL.md` 运行模式）：原示例 `(function(){ eval(src); })()` 中，`(async () => {...})()` 返回的 Promise 无人接管，运行时判定同步代码已跑完即结束会话，异步流程被整体丢弃——症状是「跑了三四分钟、零输出、什么都没做」。改为 `Promise.resolve(eval(src)).then(ok, err)` + `setInterval` 保活，并固化三条硬约束：heredoc 内禁用顶层 await（`require` 与顶层 await 并存会触发 node 模块格式自动探测冲突，报 `Cannot determine intended module format`，**非本机特例，所有机器同理**）、Promise 必须有人接管、保活定时器。另补充 `cliLog` 走 stderr 且延迟到进程结束才 flush 的提示（避免后台运行时误判卡死）。
- **v1.3.3（2026-09-05）**：健康度清理与护栏增强（核心行为不变，删死路 + 护栏 + 文档同步）：
  1. **移除 API_VERIFY 403 死路**：`run_shift.js` 不再对恒 403 的 serverFetch API 做 5 次重试（每班白耗约 60s + 报错噪音）。
  2. **新增 `scripts/verify_via_cli.js`**：折叠权威验证脚本化（自动定位 zhihu-cli，含 macOS 默认路径回退），实测通过。
  3. **删除 `scripts/verify_fold.js`**：整个脚本建立在已失效 API 上。
  4. **字数护栏**：发布前按 config 区间校验字数，超限跳过发布（`ANSWER_SKIPPED: WORD_COUNT_EXCEEDED`）。
  5. **references/ 文档全量同步** v1.3.2/v1.3.3 变更。
- **v1.3.2（2026-09-05）**：在 v1.3.1 基础上合入本机（macOS + 特定 ego-browser 构建）实测必需的三处兼容性修正，避免纯覆盖 v1.3.1 后在本机养号失败：
  1. **点赞选择器**：`button.VoteButton:not(.VoteButton--down)`（v1.3.1，已失效）→ `button[aria-label*=赞同]`（无引号写法，规避 `js()` 二次求值引号错配）。影响 `run_shift.js`。
  2. **写回答注入**：`fillInput('.public-DraftEditor-content')`（v1.3.1，Draft.js 不认）→ `ClipboardEvent` 粘贴注入。影响 `run_shift.js` + `write_answer.js`。
  3. **想法正文注入**：`post_moment.js` 同 `fillInput` 坑，一并改为 `ClipboardEvent` 粘贴注入。
  4. **运行示例**：v1.3.1 的 `CONFIG=... SHIFT=... ego-browser nodejs < script` 在本机不继承 shell 环境变量（cwd 锁死 `/`、CONFIG/SHIFT 被丢弃），改为 heredoc 内联 `process.env.X` + `fs.readFileSync` + `eval(主脚本)` 的可靠写法（见「运行模式」）。
  - 注：以上修正仅针对本机环境；在其他正常继承 env 的机器上，`CONFIG=...` 前缀写法仍可工作。个人 `config.json` 不上传，请复制 `config.example.json` 自建。
