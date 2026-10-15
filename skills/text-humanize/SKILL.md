---
name: text-humanize
description: >
  Audit and de-AI text — bilingual (English + 中文), across genres. Auto-detects language and genre,
  then detects AI-generated patterns: structural tells, opening/closing clichés, surface signals,
  rhetorical/lyrical tells (appositive stacking, clichéd imagery, filler adjectives), and
  platform-specific red flags. Rewrites text to sound like a real human wrote it. Use when checking
  text for "AI smell" before posting to HN, Twitter/X, Reddit, Facebook, LinkedIn, Dev.to,
  微信公众号, 知乎, 小红书, 即刻, 微博, 抖音, B站, or any public forum — and for prose: 散文、美文、
  文艺腔、抒情段落、现代诗短句、小说叙事段落、长篇稿件。亦用于 去AI味、去文艺腔、查AI痕迹、humanize。
---

- **Version**: 1.4.0
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-office-work-flow/tree/main/skills/text-humanize

# Text Humanize — 中英文去 AI 味检测 + 改写

Bilingual AI-smell auditor and humanizer. Auto-detects whether input is English or Chinese **and which genre it belongs to**, then applies the right detection patterns and rewrite rules. Built from real flagged data on English platforms (HN, Reddit), Chinese platforms (公众号, 知乎, 小红书), and real prose revisions (散文、小说叙事段落).

## Language Auto-Detection

Before starting any audit, detect the input language:

1. Count CJK characters (Unicode range U+4E00–U+9FFF, U+3400–U+4DBF, U+F900–U+FAFF).
2. Count Latin characters (a-z, A-Z).
3. **Rule:** If CJK characters > 50% of total letters → **Chinese mode**. Otherwise → **English mode**.
4. If the user explicitly says 「用中文优化」 or 「用英文优化」, override auto-detection.
5. For mixed text (e.g., Chinese with English code blocks), detect based on the natural-language portions only, ignoring code.

## Genre Gate — Run Before Choosing Rules

语言决定**用哪本目录**；体裁决定**用目录里的哪几条规则**。同一门语言、相反的建议：评论区该删破折号，散文该留破折号。跳过这一步，就会输出互相打架的意见。

| 档位 | 识别特征 | 适用信号 | 改写规则 |
|---|---|---|---|
| **短文本** Short-form | 评论、即刻/微博/朋友圈、知乎评论区、论坛回帖；几十到几百字 | 五类全查（**SS-CN8 不适用**） | 全量：加语气词、留 1-2 个错字、压成 1-2 段、删破折号 |
| **长文** Long-form | 公众号正文、知乎长答、博客、署名文章；1500 字以上 | 五类（SS-CN1 零错别字、SS-CN5 破折号两条信号不适用）+ **SS-CN8 节拍化人味** | 降级：去模板骨架（01/02/03、首先其次最后、写在最后）；**不写错别字、不压段**；人味靠语气词 + 节奏错落 + 一次刻意重复或自我打断。**若命中 SS-CN8，突破口是把撒得过匀的口语标记做减法**，而不是再加人味 |
| **文学** Literary | 散文、小说叙事、美文、现代诗短句、随笔 | 五类（SS-CN5 破折号信号除外）+ **第六类 R-CN1~R-CN6** + **SS-CN8 节拍化人味** | 只做减法与还原：删堆砌、拆同位语、换私人化意象。**不注入错字、不注入语气词、不碰标点风格**；破折号保留，只做控量与规范化 |

三条裁决规则：

1. 拿不准就按**长文**处理（最保守）。**唯一例外：** 文本一旦呈现抒情特征——意象堆叠、`X，Y 的 Z` 同位语高频、通篇泛化抒情——就按**文学**档处理；这些特征本身就是文学档的判据，不属「拿不准」。
2. 体裁与平台冲突时，**体裁优先**。例：公众号里的一段散文，按文学档走，不按长文档走。
3. 用户明确说「按评论区风格改」时，用用户指令覆盖体裁判定。

英文侧同理：HN / Reddit 评论 = 短文本，Dev.to 文章 = 长文，Substack / 个人随笔 = 文学。

## How It Works — Two Modes

Both modes work identically for English and Chinese; just the pattern catalog differs.

### Mode A: Audit Only (trigger: 「check」, 「audit」, 「检查」, 「看看」)

1. Auto-detect language.
2. Auto-detect genre (see Genre Gate above).
3. Load the appropriate reference: `references/ai-smells-en.md` for English, `references/ai-smells-cn.md` for Chinese. For the **文学** tier（或任何呈现抒情特征的文本，含抒情短句）, also load `references/ai-smells-r-cn.md` and `references/lyrical-appositive.md`.
4. Run the mechanical checks the tier calls for **first** — 标点层（含方向核对，见检查一）for all Chinese text, R 类结构计数 for 抒情/文学, **SS-CN8 节拍计数 for 长文/文学** — and report the raw numbers up front.
5. Scan the text against the smell categories applicable to that tier: the 5 categories, plus R-CN1~R-CN6 for the 文学 tier / 抒情文本, plus SS-CN8 for 长文 / 文学.
6. Produce a concise audit report listing every detected smell with:
   - The smell code (e.g., S1, O-CN1, B-CN3, SS-CN1, R-CN3, SS-CN8)
   - The specific phrase/pattern triggering it
   - A 1-line fix suggestion (in the text's language)
7. Give an overall verdict:
   - **短文本 / 长文 — 用 smell 计数：**
     - **🟢 Green (1-2 smells):** Looks human. Minor suggestions only.
     - **🟡 Yellow (3-5 smells):** Some AI patterns. Consider fixes.
     - **🔴 Red (6+ smells):** High risk of flagging. Strongly recommend rewriting.
     - **SS-CN8 的计法：** 长文里 SS-CN8 是**一整条 smell**（不按子信号逐条累加），命中即计入上面 1-2-3 的计数。
       但它是一条**特殊**的 smell —— 命中的是「人味太规律」而不是「没人味」，所以审计报告里要单独说明，
       别把它混进「AI 味重」的总评里（详见 `references/ai-smells-cn.md` 的 SS-CN8）。
   - **文学 — 用条件式，不看总数：** 命中「文学体裁快速筛查」5 条中的**任意 3 条**即 🔴；命中 **1-2 条**为 🟡，逐条用机械自检数字与例句库三问判定复核；**0 条**为 🟢。这类文本单点致命，计数式会漏判。文学档命中 SS-CN8 时，按 🟡 处理并逐条复核。

### Mode B: Audit + Rewrite (trigger: 「humanize」, 「rewrite」, 「fix」, 「优化」, 「改一下」, 「去AI味」)

1. Run the full audit (Mode A).
2. Produce a rewritten version using **only the rewrite rules for the detected tier** (see Genre Gate). 短文本才注入语气词与错别字；长文、文学档一律不注入。
3. Show the original and rewrite side-by-side with a brief summary of what changed, marking each change as 标点/空格规范化（机械） or 内容改动（需作者判断）. **长文（公众号正文、署名文章）建议直接产出定稿文件**（标题 + 正文 + 分隔线后的「本轮改动」清单），不要把 2000 字贴在对话里 —— 用户发布时复制正文即可。
4. Ask the user which version to use (or if they want further tweaks).
5. **Re-run the mechanical checks on the rewrite（强制，不可跳过，不得口头声称「已检查」）.**
   - 对**改写稿**重跑检查一（标点层），文学 / 抒情档再跑检查二（R 类）。
     有 `scripts/preflight-check.py` 就直接跑，没有就逐项计数。
   - **把复测数字写进回复**，例如：`复测：半角引号 0 / 破折号 0 / 编号小标题 0`。
   - 任一 FAIL 项不归零 → 回到 step 2 修，**修到归零才交付**。
   - **重点点名 SS-CN7：改写稿的半角引号计数必须为 0。** 这条最容易漏 —— 「顺手换」通常只换掉一部分，
     残留量与原文同量级，肉眼不可辨。**原文有多少处，改写后就按多少处去数，不要凭印象。**
   - 用户只要「只审计不改写」时，step 5 换成：把复测命令给用户，让他自己跑。

---

## Chinese Mode: Run These Two Mechanical Checks First

在评价文风之前，先跑两项**纯统计**。数字比感觉可靠，也让审计可复现、改完可复测。**（「改完可复测」这半句是本流程的强制项，见 Mode B 第 5 步）**

### 检查一 · 标点层（所有体裁，跑两次）

Before auditing style, audit **punctuation**. In Chinese text, half-width quotes (`"`) and spaces around punctuation are the single most reliable machine fingerprint — more reliable than any style tell, and fixable mechanically without touching the writing:

- Count `"` in the text. **Pure Chinese text should be 0.** Non-zero = machine typesetting residue.
- Treat this as a separate tier: **标点/空格规范化** (mechanical, no meaning change) vs **内容改动** (needs the author's judgment). Report them separately so the author can skim the mechanical part and focus on the real edits.

Full rule: SS-CN7 in `references/ai-smells-cn.md`.

- **跑两次，不是一次。** 审计前跑一遍（定基线、报原始数字），**改写后必须再跑一遍（验收）**。
  第二次 `"` 计数不为 0，就是没改完——不管改写时你觉得自己换得多干净。
- **先核对方向，再谈数字（SS-CN7 双向自检）。** 中文稿的正常形态是**全角引号多、半角引号 0**；
  反过来（全角 0 / 半角 N）几乎只有一个成因：**原文被转录/写盘时，工具把 `“ ”` 落成了 `"`**。
  这时候 N 处 FAIL 是**假 FAIL**，照着「修」还会修出一批假改动。
  跑脚本时看 **`全角引号 “ ”`** 这一行就能判：全角 0 + 半角 N → 先把成对的 `"` 还原成 `“”` 再定基线；
  两种并存 → 半角那部分才是真残留。脚本已内置提示（表头 `!! 基线核对（SS-CN7）：…`）。
- **长文请用脚本数，不要用眼睛数。** 2000 字以上的稿子，半角引号、破折号、超长段落靠肉眼必然漏。
  用 `scripts/preflight-check.py draft.md`，一条命令出全部数字。
  该脚本**只覆盖中文文本**（CJK 占比 ≥ 50%）：拿英文稿跑，半角引号、`...`、`--` 这些在英文里本来就正确的写法
  不会被误判成硬伤，标点层自动降级为只报数字。确需强制按中文判定时传 `--lang zh`。
- **复测只喂正文，不要把「本轮改动」清单一起统计。** 清单里的编号小标题、引号、破折号会被算成 FAIL
  （实测：正文 0 FAIL，带清单 2 FAIL）。用 `--cut '## 本轮改动'` 截断，或先手工分段。

### 检查二 · 抒情同位语结构（仅抒情 / 文学档）

当体裁闸门判定为**文学**档（含裁决规则 1 的抒情特征例外，九字短句同样适用）时，加跑这一项。三项都只报**原始数字**，不下结论：

- `X，Y 的 Z` 形态的出现次数；**最长连续句数**；**单段峰值**
- 陈腐喻体词库命中数（信使 / 信笺 / 叹息 / 诗篇 / 守望者 / 耳语 / 序章 / 独白 / 回响）
- 万能抒情形容词库命中数（温柔 / 沉默 / 浪漫 / 治愈 / 漫长 / 细碎）

报告样例：`同位语 14 处 / 最长连续 4 句 / 单段峰值 3 / 词库命中 9（温柔×3、信使×2）`

完整规则与词库：R-CN1~R-CN6 in `references/ai-smells-r-cn.md`；正反对照例句库：`references/lyrical-appositive.md`。

### 检查三 · SS-CN8 节拍化人味（仅长文 / 文学档）

当体裁闸门判定为**长文或文学**档时，加跑这一项。它抓的是**反向模式**——不是「太机器」，而是**「人味被当成开关在用」**：本该随机的口语标记以固定间隔复现，读者读到第三段就能预判下一句要抖包袱。

这类稿子单看每一句都是好句子，只有**连着读**才露馅，所以最容易被漏掉。三项里两项可计数：

- **段尾短句**：段落末句 ≤20 字的处数 / 段落数 + 占比 → **只报数字，不设阈值**（实测标不出来，见下）
- **招呼式称谓**：「咱们 / 大伙儿 / 人家」合计（WARN 限 5）
- **模糊限定词**：「确实 / 自然 / 实在 / 其实 / 恐怕 / 大概」合计（WARN 限 8）
- **同构三连排比**：`A，B，C。`（三短句、语法同构）（WARN 限 8；计数会虚高约三成，「掏钱、干活」这类顿号词组也算进去了，看数字要回原文核）

**「每节必收束」不做机械计数** —— 「节末收束」与「正文本来就短」在数字上无法区分，硬做只会造出假精确。按人工判据核：有 ≥3 个小标题节、且每节末尾都落一记独立成段的收束金句，就是命中。

报告样例：`段尾短句 24/56 = 43% / 招呼式称谓 8 / 模糊限定词 7 / 同构三连 15 / 小标题 6 节`

脚本已内置这一区块（`long` / `literary` 档自动输出 `[SS-CN8]`）。完整判据、改法、两篇实测记录：SS-CN8 in `references/ai-smells-cn.md`。

---

## English Mode

Refer to `references/ai-smells-en.md` for the complete English pattern catalog. Summary of categories:

| Category | Code | Key Signals |
|----------|------|-------------|
| Structural | S1-S3 | 4+ paragraphs, numbered lists, quote-then-respond |
| Opening | O1-O3 | "This resonates...", "From building X...", "As someone who..." |
| Body | B1-B6 | Balanced argumentation, feature listing, insight formula, example cascading, collective "we", formal connectors |
| Closing | C1-C3 | Polished conclusion, "Curious what others think", forced positivity |
| Surface | SS1-SS5 | Zero typos, em-dashes, no filler words, uniform sentence length, semantic punctuation |

Genre tiers apply on the English side too (see Genre Gate): HN / Reddit / social **comments** = 短文本（full catalog）；Dev.to / blog **articles** = 长文（skip the SS1-SS3 injection fixes — no typo or filler injection, em-dashes are fine；focus on structural smells）；Substack / personal **essays** = 文学（subtraction only，什么都不注入）. Per-tier details: 「Genre Adjustments」 at the end of `references/ai-smells-en.md`.

### English Rewriting Principles

1. **Structure killer.** Destroy essay structure. 1-2 paragraphs max. No intro-body-conclusion.
2. **Opinion injector.** Take a side. "i think X is wrong" beats "X has merits but also drawbacks."
3. **Human fingerprint**（仅短文本档）. Add at least: 1 typo (missing apostrophe), 1 filler word, 1 moment of uncertainty. 长文与文学档不注入 —— 改用节奏错落与结构性修改，见 Genre Adjustments（`references/ai-smells-en.md`）。
4. **Experience, not features.** Express a specific struggle, not a feature list.
5. **Stop early.** End with uncertainty or trail off. No polished conclusion.

### English Platform Rules

| Platform | Max Length | Tone | Special Rules |
|----------|-----------|------|---------------|
| **HN** | 1-3 paragraphs, 5-6 lines | Technical, opinionated, humble | Strictest AI detection. No self-linking. Self-deprecation is currency. |
| **Twitter/X** | 1-2 sentences or punchy thread | Punchy, informal, voice-driven | Numbered threads (1/9) = AI flag. Each tweet stands alone. |
| **Reddit** | 1-3 paragraphs | Smart-friend-chat | Subreddit-dependent. r/programming ≈ HN. |
| **Facebook** | 1-2 short paragraphs | Casual, personal | Tech groups: HN rules. Personal feed: be human. |
| **LinkedIn** | 1-2 paragraphs | Casual professional | Avoid "thought leader" tone. |
| **Dev.to** | 2-3 paragraphs | Technical but conversational | Slightly more length-tolerant than HN. |

If no English platform is specified, default to HN rules (strictest baseline).

---

## 中文模式 (Chinese Mode)

Refer to `references/ai-smells-cn.md` for the complete Chinese pattern catalog. Summary of categories:

| 类别 | 代码 | 关键信号 |
|------|------|----------|
| 结构 | S-CN1~S-CN4 | 议论文三段式、「首先其次最后」、编号列表、引用原文再回复 |
| 开头 | O-CN1~O-CN3 | 「这个问题很有启发性…」、「作为一个…」、「有道理但是…」 |
| 正文 | B-CN1~B-CN7 | 书面连接词过频、对称辩证、金句提炼、举例论证、「我们」滥用、中英混杂、功能罗列 |
| 结尾 | C-CN1~C-CN3 | 升华式收尾、开放式互动、正能量用力过猛 |
| 表面 | SS-CN1~SS-CN8 | 零错别字、句式工整、缺少语气词、句号强迫症、破折号泛滥（仅短文本）、翻译腔、**半角标点/标点空格（优先级最高）**、**节拍化人味（长文/文学档的反向模式）** |
| 修辞 · 抒情 | R-CN1~R-CN6 | 同位语过密、句式僵化无变体、陈腐喻体词库、万能形容词冗余、意象不统一、抒情无落点（**仅抒情/文学档，且改用条件式判定**） |

> **体裁差异集中在四条：** R 类只在**文学档与抒情文本**（含短文本里的抒情短句）生效，规则独立成 `references/ai-smells-r-cn.md`，按需加载；SS-CN5（破折号）只在**短文本**生效；SS-CN1（零错别字）在**长文与文学档不作检测信号、也不注入错字**；**SS-CN8 只在长文与文学档生效**（短文本本来就该塞语气词，「节拍」无从谈起）。入口见上方 Genre Gate。

> **SS-CN8 是唯一的「反向」信号：** 其余条都在抓「太机器」，它抓**「太像人」** —— 口语标记批量、均匀地撒，形成新节拍。
> 命中它的时候，审计结论不要说成「AI 味重」，要说「**人味太规律**」，改法也不是加人味，而是**做减法**。

### 中文改写黄金规则

> **档位说明：** 下列规则默认面向**短文本**档。**长文**档见 `references/ai-smells-cn.md` 末尾的降级说明；**文学**档只取第 5、6、7 条，外加第 9 条。体裁判定见上方 Genre Gate。

1. **结构打碎。** 不要开头-中间-结尾。1-2 段，直接亮态度。*（短文本；长文改为去模板骨架）*
2. **加语气词。** 至少 1-2 个：吧、嘛、呢、啊、就、还挺、讲真、说实话。*（短文本、长文可用；文学档不注入）*
3. **加 1-2 个「错」。** 的/地/得混用，或在/再混用。不要太刻意，2 个就够了。*（仅短文本；长文与文学档一律不写错别字）*
4. **短句为主，偶尔混长句。** 节奏参差不齐才像人。
5. **有态度。** 敢说「我觉得不对」「试过就知道坑」。不要和稀泥。
6. **结尾不升华。** 用不确定感收尾或戛然而止。不要「值得深思」。
7. **个人经验 > 通用道理。** 讲自己踩过的坑，不讲放之四海而皆准的道理。
8. **宁可碎一点。** 半句话、反问句、语气词结尾都行，不要追求「完整」。*（短文本）*
9. **文学档只做减法。** 删堆砌、拆同位语、把公共意象换成私人意象；**不要用新喻体替换旧喻体**，也不要为了「人味」加错字或语气词。例句库见 `references/lyrical-appositive.md`。

### 中文平台特定规则

| 平台 | 长度限制 | 语气 | 特别注意 |
|------|---------|------|----------|
| **微信公众号** | 正文 500-1500 字；评论 1-3 句 | 可稍正式但有个性 | AI 检测最严。致命伤：标题党 + 三段式 + 升华结尾 |
| **知乎** | 回答不限；评论 2-5 句 | 有态度，不怕杠 | 致命伤：「谢邀」开头 + 分点论述 + 「以上」结尾 |
| **小红书** | 正文 50-200 字；评论 1-3 句 | 轻松、口语化 | 善用 emoji 但别每句都加。标签区和正文分开 |
| **即刻** | 1-3 句 | 极随意 | 语气词决定生死。不要长篇大论 |
| **微博** | 1-3 句 | 直接、有梗 | 可用网络用语，但不堆砌 |
| **B站评论区** | 1-3 句 | 弹幕风格 | 语气词 + emoji 友好 |
| **抖音评论区** | 1 句，最多 2 句 | 极短 | 超过 3 句 = 直接判 AI |
| **朋友圈** | 1-3 句 | 熟人聊天感 | 不要「通知」语气，不要排比句 |

如果没有指定中文平台，默认按**知乎评论区**规则处理（适中长度 + 有态度的口语）。

---

## Edge Cases

- **Very short text (under 20 words / 30 字):** Almost certainly human. Only check surface smells. Don't over-audit. **例外：抒情 / 唯美短句** —— 九个字的 `黄昏，大地温柔的信使` 正是第六类要抓的形态。**短 ≠ 人味**，这类文本不看长度，照跑 R 类检查。
- **文学 / 散文 / 诗体输入:** Route through the Genre Gate to the **文学** tier. Suppress typo and 语气词 injection entirely; work by subtraction — delete stacking, break appositives, swap public imagery for private. 例句库见 `references/lyrical-appositive.md`。
- **Technical code-heavy text:** Code blocks are exempt. Only audit the natural language portions.
- **User wants formal tone:** Skip typo/错别字 injection. Still de-structure and remove academic openers.
- **Text already has human markers:** If 3+ human fingerprints already present, focus on structural smells only. Don't over-humanize. **但先跑 SS-CN8** —— 人味标记「多」有两种：散落各处（好），和均匀铺满（节拍化，坏）。这一条的判据不是「有没有人称语气词」，是「**能不能预判下一段末尾要抖包袱**」。
- **把原文写进草稿文件之后（转录污染）:** 写盘这一步本身可能改标点 —— 实测 Write 工具会把 `“ ”` 落成 `"`，让一篇标点层全 0 的原文变成 12 处 FAIL。**定基线前先核对方向**（全角引号数一并看），别把转录污染当原文缺陷，更别顺着「修」出一批假改动。见检查一的第二颗子弹。
- **Mixed EN/CN content:** Audit each language block separately against its own catalog. If truly bilingual, note it and ask the user which language to prioritize.
- **Quoted text / retweets:** Only audit the user's own added text. Quoted/retweeted content is exempt.
- **中英混排的空格例外:** SS-CN7 只针对**标点周边**的半角标点与空格；中英文之间、中文与数字之间的一个空格是排版惯例（`用 CDP 上传`、`第 3 步`），不要清掉。
- **边界 — 平台侧检查不在本 skill 范围：** 创作度、原创增量、同质化、搬运拼凑、低价值 AIGC 判定等**平台合规类检查**请用对应的平台检查工具；本 skill 只管**文本层**的 AI 特征（句法、标点、套路、意象）检测与去 AI 味改写。
- **事实层不由本 skill 处理，但改写时要顺手做两件事：** ① **不改动事实本身**（数字、人名、时间、引语一律照写），存疑处标注出来交给作者；② 遇到**作者无法自证出处**的细节，**不要删、也不要用别的说法替换**，而是加「据说」或交代来源（「记不清是在哪篇报道里……」），把判断权留给作者。两个高频动作：**日期模糊化**（精确到日的改成「月 / 季节」级，但关键锚点年份保留）、**无出处的数字加「据说」**。
