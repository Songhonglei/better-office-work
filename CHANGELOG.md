# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — text-humanize v1.5.0（2026-10-17）

- 定位改为中英文清晰表达与风格润色，保留诊断、对照改写、体裁适配、修辞和排版；保留事实、引用、链接和必要披露。
- 移除来源评分、审核预测、伪装真人、故意错字、假犹豫、强制站队、虚构亲历及模糊日期/编造出处规则。下方 v1.4.0 及更早的 text-humanize 记录仅为历史，旧行为与阈值已废弃，不能作为当前指令。
- 三份参考改名并同步四份参考内容；脚本支持保护代码、URL、引用与英文片段，段落按空行解析，统一语言边界为 CJK >50%。
- 默认仅提示；严格模式只约束显式 `--check` 的格式项，R 类、SS-CN8、词频和句长不决定退出码。新增自动化回归测试与单独登记的模型行为验收用例。
- 发布范围为 GitHub 仓库更新，不包含 ClawHub 发布或平台申诉；不代表账号恢复或审核通过。

### Added
- **qq-mail-manage** v1.0.1 — QQ 邮箱管理：真实 Codex + 腾讯官方 MCP，可配置账号与多 profile，OAuth 初始化、邮件及附件读写、确认后移至垃圾箱；包含写入状态持久化、结果未知不重试、删除续期与 29 项离线回归测试。首版加入本仓库（2026-10-20）。
- **macos-power-control** v1.0.0 — macOS 合盖与电源设置：一句话需求解析、执行前确认、目标 Mac 环境检查、临时防休眠电源范围匹配、管理员密码交接、验证和恢复流程。首版公开发布（2026-10-13）。
- **text-humanize** v1.4.0 — 新增 **SS-CN8「节拍化人味」**（目录里唯一的**反向**信号：其余各条抓「太机器」，这条抓**「太像人」**），并为 **SS-CN7 补录「基线方向核对」**。
  - SS-CN8 五条子信号：8a 段尾俏皮句节拍化 / 8b 每节必收束 / 8c 招呼式称谓过载 / 8d 同构三连排比 / 8e 模糊限定词过载；**仅长文与文学档生效**（短文本本来就该塞语气词）。
  - `preflight-check.py` 新增 `[SS-CN8]` 区块（`long` / `literary` 自动输出）；新增 `全角引号 “ ”` 计数行与 `baseline_note()` —— 命中「全角 0 且半角非 0」时提示**转录污染**，避免把 0 缺陷原文报成 N 处 FAIL。
  - 8a **故意不设阈值**（标定发现阈值造出来的只是假精确：改得更好的稿子占比反而从 24% 涨到 35%），8b 不做机械计数；8c/8d/8e 限 5/8/8。
  - 来源：两篇同作者公众号历史科普长文（《拿破仑帽子》《佛像》）复盘 —— 共同症候是「人味太规律」，v1.3.1 五类全部漏判。
- **imagegen-batch** v1.3.3 — 批量生图 skill：三道防覆盖机制（唯一前缀 + 默认顺序发 + 生成后立刻改名）、量水印而非猜、相框感靠 `add_frame.py` 后期加白边、人物「标识包」防塌脸，附 `白纸速写`/`水墨文艺风` 两套命名风格配方。首版公开发布。
  - 本版新增「想把某物画小 / 画远，要改**形状**而不是给**数值**」——连写三版尺度数值模型照画竖长石板，改成「矮胖方块墩子 + 底盘 + 负面排除」才生效；同条规则也适用于材质（只写「夯土」仍画砖缝）。
  - 同版修正 `paper-sketch` 里一条被证伪的结论：原文称「素白无字的空白物件是好材料」，实际反馈是「像无字碑」，已改写为「竖长物件慎用素白无字，形状定调」。
  - v1.3.2 起批量策略由「并行」改为**默认顺序发**（并行撞 `read ECONNRESET`，实测 4 张挂 1、3 张全挂）。
- **zhihu-yanghao** v1.0.0 — 知乎养号 skill：三线选题模型 + 每日1回答（写→发布→折叠验证）+ 点赞互动（计数差值自校正防误 toggle），依赖 ego-browser
- **invoice-auto-forward** v1.0.1 → v1.0.8 补登（此前仓库只登记了初始的 v1.0.0，中间 7 个版本的演进一直没记录）：
  - v1.0.1 修复销售方（seller）提取为空（正则 `销\s*名称` → `销售方\s*名称`）。
  - v1.0.2 修复 `scan` 干跑预览漏报发票号重复（`_nos` 去重集合被关在 `do_send` 分支内，预览与实跑不一致）。
  - v1.0.3 多邮箱 provider 预设（qq/163/126/yeah）+ 发送节奏参数（防反垃圾风控）；修 `__version__` 与包版本不一致。
  - v1.0.4 修复 163/126 `Unsafe Login`（登录后发 IMAP `ID` 自报身份）；凭证支持 `MAIL_USER`/`MAIL_AUTH_CODE` 环境变量回退。
  - v1.0.5 新增 `setup` 一键配置子命令（验证通过才写 secrets，chmod 600 原子创建）。
  - v1.0.6 链接型发票自动下载（如腾讯云 COS 预签名 URL）；新增 `fetch_links`/`link_domains` 等配置与安全闸门。
  - v1.0.7 发票格式从 PDF 扩展到 **PDF / OFD / XML** 三种（OFD/XML 用 Python 标准库，零额外依赖）；链接下载同步泛化。
  - v1.0.8 转发抄送（CC）支持，默认关闭。

### Changed
- **zhihu-yanghao** v1.2.0 — 基于 2026-08-04~08-12 实战校验的重大修正：
  - 🐛 **点赞 selector 死路径修复**：旧 `button.VoteButton:not(.VoteButton--down)` / `button.VoteButton--up` 在新版知乎已失效，改为 `button[aria-label*="赞同"]`（aria-label 形如 `"已赞同 1020 "`，含尾空格必须 trim）。
  - 🐛 **已赞判定修正**：由 innerText 含「已赞同」改为 `classList.contains('is-active')`（class 含 `VoteButton is-active`），避免重复点赞取消。
  - ⚠️ **innerText 零宽字符坑**：实测点赞按钮 innerText 为 `"\u200b 已赞同 87"`（前导零宽字符），不能用 `===`/`startsWith` 精确匹配，一律走 aria-label + trim。
  - ✅ **发布验证强化**：`run_shift.js` 验证步骤加 `updated_time` + content 乱码检测，对应「发布中…」卡 UI 假象（8/5 验证）。
  - ✅ **连续发文错峰**：补充「同主线不同子方向也要错峰」（8/11 父子→8/12 中年女性实证），写入风控与选题策略。
- **invoice-auto-forward** v1.0.9 — 文档增强与勘误（无功能变更，脚本行为与 v1.0.8 一致）：
  - 新增「输出解读」章节：明确「跳过」= 抬头白名单不命中（正确过滤，**不是漏发**），与「无发票」（解析/下载失败）是两条独立分支；排查漏发应看后者。此前该语义只存在于源码中。
  - 新增「定时任务（无人值守）」章节：⚠️ 脚本与配置必须落在持久目录（记录了自制脚本放 `output/` 被清理、导致定时任务连续静默失败 25 天的事故）；提供 WorkBuddy automation prompt 参考模板与 crontab 行。
  - 补充每日报告文件说明（`~/.workbuddy/invoice-forward/报告_YYYYMMDD.md`，此前文档未提）。
  - 术语修正：「无PDF」→「无发票待人工」（脚本自 v1.0.7 起已支持 OFD/XML）。
  - 修正 v1.0.7 条目中「GitHub/clawhub 仍停 v1.0.3（待发布）」的过时陈述。

## [1.0.0] - 2026-07-22

### Added
- **invoice-auto-forward** v1.0.0 — 邮箱发票自动转发 skill（IMAP 扫描 + PDF 解析 + SMTP 转发）
