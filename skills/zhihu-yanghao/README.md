# zhihu-yanghao

一套依赖 ego-browser 的知乎养号（account-nurturing）全流程 skill：**垂直领域收敛 + 三班节奏（早/午/晚）+ 深度版回答 + 想法发布 + 创作影响力规范**，内嵌 7/27 风控事故后总结的红线与陷阱。可在任意装了 ego-browser 的机器上独立运行，不依赖任何工作区记忆。

## 功能总览（v1.3.9）

- **发布链路健壮性**（v1.3.9）：`write_answer.js` 发布按钮匹配已同步零宽字符修复（`[\u200b\s]+` 清洗 + 双候选 + 「发布」回退 + 跳过 disabled），失败显式输出 `WRITE_ANSWER_PARTIAL_FAIL`。

- **三班编排**：早 07:50 / 午 12:30 / 晚 20:00，每班独立会话跑完「折叠巡检 → 轮转选题 → 随机点赞 → 写回答 → 发布 → 折叠验证 → 可选收藏/关注/评论」。
- **折叠巡检**（v1.3.7）：`fold_audit.js` 抓创作者中心「被折叠」标签并与本机基线比对，输出 `NEW_FOLDED`/`RECOVERED`——知乎「隐藏机制」批量折叠下，这是唯一可靠信号（CLI Summary 已失明）。
- **去指纹化写作规范**（v1.3.7）：禁「先说个反直觉判断」系开头（hook 移中段），开头句式池 10 种轮换；分层拆解每周 ≤1 篇、分析术语每周 ≤2 篇、掉书袋每篇 ≤1 处——让内容读起来更像真人手写，减少模板化痕迹。
- **垂直度收敛**：`vertical_focus` 只养 2 个领域（默认「趣味历史」+「人文心理」），每篇埋 2-3 个领域关键词帮算法点亮创作垂直度。
- **深度版回答**：每周 1 篇 800–1200 字（用户邀请 `invite` / 随机 `random` / 两者 `auto`），硬性要求 = 可核查硬料 + 对比结构 + 可操作结论。
- **想法发布**：`post_moment.js` 全自动发想法/动态（默认 dryRun 只填不发），冲关注者亲密度。
- **影响力规范**：每篇必带反直觉 hook（中段）+ 可操作判断 + 自然收束（禁问号互动收尾）。
- **自然化互动**：前 10 候选随机选 3–5 个点赞（不固定前 N）、已答/已赞自动跳过、差值自校正。
- **失败可见**：发布未成功时输出 `SHIFT_PARTIAL_FAIL: publish`（不再伪装成正常收尾）。
- **账号受限期降级**（v1.3.8）：`config.account_status.silenced=true` 时 `run_shift.js` 立即退出（零写操作），改用 `browse_only.js` 只读浏览维持活跃度；解除后先恢复 morning 单班 1 答/天。

## 前置依赖

- 已安装 ego-browser（ego lite 浏览器 + CLI），知乎账号已登录（ego-browser 继承系统登录态）。
- ⚠️ 运行 `ego-browser nodejs` 需关闭 WorkBuddy 沙箱（详见 SKILL.md「前置依赖」）。
- （可选）zhihu-cli + 知乎开放平台 Access Secret，用于热榜扫描与发布结果权威校验。

## 安装

- 方式一：拷贝本目录到 `~/.workbuddy/skills/zhihu-yanghao/`（用户级，跨项目可用）。
- 方式二：从 clawhub / skillhub 一键安装。
- 方式三：clone 本仓库，取 `skills/zhihu-yanghao/` 子目录。

## 快速使用（推荐：三班编排）

```bash
# 1) 配置：复制模板并按你的账号/话题/班次修改（config.json 不入库）
cp config.example.json config.json

# 2) 写参数文件（ego-browser 不透传 shell env，参数文件是可靠路径）
cat > /tmp/zhihu_shift_params.json <<'EOF'
{ "shift": "morning", "configPath": "/abs/path/config.json" }
EOF

# 3) 跑一个班（自动轮转选题 + 点赞 + 写/发布/验证 1 回答）
ego-browser nodejs < scripts/run_shift.js
```

发想法（默认 dryRun 只填不发，实发须显式 `"dryRun": false`）：

```bash
echo '想法正文（50-150 字）' > /tmp/moment.txt
cat > /tmp/zhihu_moment_params.json <<'EOF'
{ "contentFile": "/tmp/moment.txt", "dryRun": true }
EOF
ego-browser nodejs < scripts/post_moment.js
```

## 目录结构

- `SKILL.md` — 主流程、触发条件、创作分提升套件（含去指纹化写作规范）
- `config.json` / `config.example.json` — 账号、垂直领域、话题池、班次、深度版/想法/影响力配置
- `references/risk-control.md` — 风控红线（必读）
- `references/selectors.md` — DOM 选择器 + ego-browser API 速查
- `references/topic-strategy.md` — 垂直收敛、话题池轮转、深度版与影响力写作规范
- `references/workflow.md` — 配置说明、脚本调用、参数文件 schema
- `scripts/` — run_shift.js（三班编排）/ fold_audit.js（折叠巡检，本机基线 `references/fold-baseline.json` 不分发）/ browse_only.js（禁言期只读浏览）/ post_moment.js（发想法）/ like_top5.js / write_answer.js / verify_via_cli.js（辅助验证）/ pick_question.js / edit_answer.js

## License

MIT — Evan Song
