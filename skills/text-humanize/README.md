# text-humanize

> 中英文去 AI 味检测 + 改写。自动识别语言**与体裁**，再套用对应的检测模式与改写规则。

## Features

- **双语自动识别** —— 中文、英文各一套模式目录；混排文本按语言块分别审计。
- **体裁闸门** —— 短文本 / 长文 / 文学三档。评论区该删破折号，散文该留破折号；跳过这一步就会给出互相打架的建议。
- **三道机械自检** —— ① 标点层（半角引号数与标点周边空格，纯中文文本应为 0；并做**方向核对**，防止把转录污染当成原文缺陷）；② 抒情同位语结构计数（`X，Y 的 Z` 出现次数、最长连续句数、陈腐喻体与万能形容词词库命中）；③ **SS-CN8 节拍计数**（段尾短句 / 招呼式称谓 / 模糊限定词 / 同构三连排比）。先出数字，再谈文风。
- **改写后的验证闭环** —— 检查层不是只前置的：改写完必须对**改写稿**重跑标点层，FAIL 项不归零不算改完。配套一条命令的 `scripts/preflight-check.py`。
- **六类中文信号** —— 结构 / 开头 / 正文 / 结尾 / 表面（含 SS-CN8）/ 修辞·抒情（R-CN1~R-CN6）。
- **唯一的反向信号 SS-CN8** —— 其余各条抓「太机器」，它抓**「太像人」**：口语标记批量、均匀地撒，形成新节拍。命中时改法是**做减法**，不是加人味。
- **五类英文信号** —— Structural / Opening / Body / Closing / Surface，附 HN、Reddit、Twitter/X、LinkedIn、Dev.to 平台规则。
- **两种模式** —— 只审计（报告 + 绿黄红判定），或审计 + 改写（左右对照，改动分「机械规范化」与「内容改动」两级）。

## 什么场景用它

| 场景 | 体裁判定 |
|---|---|
| HN / Reddit 回帖、即刻、微博、朋友圈、抖音评论区 | 短文本 |
| 公众号正文、知乎长答、博客、署名文章 | 长文 |
| 散文、美文、抒情段落、现代诗短句、小说叙事段落 | 文学 |

## Quick Start

```bash
# Install (clawhub)
clawhub install text-humanize

# Or clone the mono-repo; the skill lives in skills/text-humanize/
git clone https://github.com/Songhonglei/better-office-work-flow.git
```

## Usage

详细规则见 [SKILL.md](./SKILL.md)，信号目录见 [references/](./references/)。

触发示例：

- 「帮我检查一下这段有没有 AI 味」→ 审计模式
- 「把这篇改得像人写的」→ 审计 + 改写模式
- 「这段散文是不是太文艺腔了」→ 文学档 + R 类信号

## 机械自检脚本

`scripts/preflight-check.py`（Python 3 stdlib，无依赖）一条命令输出标点层 / 排版 / 人称 / R 类全部统计项。

```bash
python3 scripts/preflight-check.py draft.md                    # 长文档
python3 scripts/preflight-check.py draft.md --tier literary    # 散文 / 抒情
python3 scripts/preflight-check.py 定稿.md --cut '## 本轮改动'  # 带尾注的定稿，只测正文
python3 scripts/preflight-check.py draft.md --json             # 机器可读
```

> 审计前跑一次记基线，改写后再跑一次做验收。**半角引号不为 0 就不算改完。**

结果分三级，这是脚本的核心设计：

| 级别 | 含义 | 是否决定退出码 |
|---|---|---|
| **FAIL** | 机器残留，必须归零，与文风无关（半角引号 / 半角单引号 / 中文后半角逗号句点 / `...` / 非规范破折号 / 破折号前后空格 / 标点周边空格 / 编号式小标题） | 是（`0` 无 FAIL，`1` 有 FAIL） |
| **WARN** | 文风项，只报数字供作者判断（超长段 / 同位语密度 / 词库命中） | 否（加 `--strict` 才计入） |
| **INFO** | 仅记录（段落数、最长段、人称计数、破折号与省略号总量） | 否 |

超长段落、抒情同位语在**散文 / 抒情档本来就该长**——把它们判 FAIL 会逼作者把流畅的行文剁碎。
机械层和文风层必须分开，否则脚本自己就在制造 AI 味。

**只覆盖中文文本。** 标点层规则是中文专属的（半角引号、`...`、`--` 在英文里本来就是正确写法）。
`--lang auto`（默认）按 CJK 占比判定，不足 50% 就把标点层降级为 INFO 并打出警告；
确需强制按中文判定时传 `--lang zh`。

### 正反样本（同一次事故的两端）

| 样本 | FAIL | WARN | 退出码 |
|---|---|---|---|
| 含机器残留的原文 | 半角双引号 20 / 编号式小标题 6 | 超 70 字段落 14 处（最长 122 字） | 1 |
| 改写后的定稿 | 无 | 超 70 字段落 10 处（最长 111 字） | 0 |

第二行那 10 处超长段是**文风取舍**，不是机器残留——数据段和抒情段本来就该长，硬拆会把行文剁碎。
这也正是脚本要把 FAIL 和 WARN 分开的原因。

## Install in your AI agent

| Agent | Install |
|---|---|
| WorkBuddy | 复制到 `~/.workbuddy/skills/` |
| Claude Code | 复制到 `~/.claude/skills/` |
| Cursor | 复制到 `.cursor/skills/` |
| OpenClaw | `clawhub install text-humanize` |

## License

MIT (see [LICENSE](./LICENSE))

## Author

Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)

## Changelog

See [CHANGELOG.md](./CHANGELOG.md) for the full version history.
