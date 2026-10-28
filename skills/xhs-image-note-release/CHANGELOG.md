# Changelog

All notable changes to this skill are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

### v1.7.2 (2026-10-27)

- **铁律（Docs）**: SKILL.md 新增「发布前必读」提醒与「注意事项」第 15 条——**内容严禁出现任何引流信息**：卡片图片、标题、正文、话题中不得出现「微信搜索」「公众号」「加微信」「扫码」等引流文案，也不得放置二维码图片，否则有封号风险；只允许 `@账号名` 软性署名，靠内容质量与评论区互动自然导流。
- **Meta**: frontmatter 补充 `slug` 与 `displayName`（skillhub.cn 发布硬性要求）。

### v1.7.1 (2026-10-09)

- **Fix (root cause)**: `scripts/publish_note.sh` 修复「登录态过期被误判为已登录」导致报错信息误导的根因。
  - 旧判定 `text.includes('登录') && !text.includes('发布')` 在登录态过期时必然误判：小红书登录页导航里同样含「发布」「上传图文」等字样，脚本却认为已登录，继续往下走到`uploadFile()` 才抛 `ElementResolutionError: input[type="file"][accept*=".png"] not found`，真实原因（401）被完全掩盖，排查绕远路。
  - 改为**双重判据**：① `location.href` 不含 `/login`（登录态过期会 302 到 `/login?source=&redirectReason=401&lastUrl=…`）；② 侧栏存在「笔记管理」或「草稿箱」入口。
  - 失败日志同时输出 `reason`（`redirected_to_login` / `no_manage_entry`）与当前 URL，并提示手动登录路径。
- **Docs**: SKILL.md「注意事项」新增第 13 条——登录检测必须用 URL 判定（含正确判定代码块），第 14 条——用户手动登录会触发「用户接管 task space」硬停止，须等用户回复 continue 后用 `takeOverTaskSpace(spaceId)` 接管，不可自行重试或夺回。
- **验证**：`bash -n` + 提取 nodejs 段 `node --check` 通过；已登录真实页面回归测试新判定为 `true`，与旧判定一致无回归。

### v1.7.0 (2026-08-18)

- **Feature**: 新增 **stage 模式**（`MODE=stage`）。用户要求「准备好页面我自己发布 / 不要暂存离开 / 留在页面就行」时走此模式。
  - 上传图片 + 填标题正文 + 挂话题标签后**原地停下**，不触发 `_onSave()` 也不触发 `_onPublish()`。
  - 页面和 task space **保持开启**（不调 `completeTaskSpace`），用户到 ego-browser 中自行检查后手动点发布。
  - 每次执行 `stage` 模式新开一个独立页面（unique task space name + `Date.now()`），互不干扰。
  - 适用场景：用户不信任草稿箱（草稿存浏览器本地不跨设备）、想亲眼确认内容无误后再点发布。

### v1.6.3 (2026-08-18)

- **Docs**: SKILL.md「注意事项」新增第 11 条——重复发布/存草稿会累积「暂无笔记标题」废草稿，并记录清理方法与确认弹窗的**真实删除按钮**选择器。
  - 小红书创作平台每次进入图文编辑页并发生导航/重渲染，会自动存若干空草稿（标题「暂无笔记标题」）；`draft` 模式重跑多篇后草稿箱会堆积大量废草稿。
  - 清理：草稿箱 → 图文笔记 tab → 每个废草稿点 `.draft-actions` 最后一个 `.btn`（删除）→ 确认弹窗。
  - ⚠️ 确认弹窗删除按钮是真实 `<button class="...model-footer-confirm-btn draft-delete-popconfirm-btn-footer-confirm">删除</button>`；点 footer 容器 `<div class="modal-footer-buttons">`（文本也是「取消 删除」）是空操作，不删。文案含「草稿删除后不可找回」。

### v1.6.2 (2026-08-18)

- **Fix (root cause)**: `scripts/publish_note.sh` 修复图片上传「只留空占位符、计数有但图不进编辑器」的根因。
  - 实测发现：即便 v1.6.1 已补 `change` 事件，批量 `DOM.setFileInputFiles`（含逐个串行 CDP `setFileInputFiles`）仍只产生「图片编辑 N/18」的假计数，**编辑器内 `img` 数为 0**，CDN 无真实上传。
  - 真因：小红书上传组件对批量文件输入做特殊拦截，只有走浏览器原生文件选择（`uploadFile()` 单文件循环，每个文件独立触发一次选择）才会真正起传。
  - 改写上传块为 `uploadFile('input[type="file"][accept*=".png"]', fp)` **逐张循环**，每传一张 `wait(6)`；最终 `wait(10)` 等 CDN 回源。实测计数稳定 1,2,3… 递增，发布后 `editCount=10`、`imgCount=11`（10 图 + 加图位）。
  - 选择器统一收敛为 `input[type="file"][accept*=".png"]`（原 `input.upload-input` 偶不命中）。
- **Fix**: 上传校验 + 草稿箱校验改用 `document.body.innerText.split('\n')` 逐行匹配（非正则），`js()` Runtime.evaluate 不支持正则字面量 `/…/`，会抛 "Invalid regular expression: missing /"。通过解析 `图片编辑 N/18` 行取 `editCount`、`草稿箱(N)` 行取草稿数；失败 `ERROR` 退出。
- **Fix**: 全部失败分支 `completeTaskSpace(task.id, { keep: true })` 改为 `{ keep: false }`，避免失败 task space 残留占用；task space 名改为 `'publish xhs note ' + Date.now()` 防用户接管冲突。
- **Docs**: SKILL.md「上传图片」章节重写，明确 `uploadFile()` 单文件循环（替代旧 CDP 批量 + change 事件思路），并把「批量 `DOM.setFileInputFiles` 只留空占位符」列为最高优先级坑点 #9；校验改用 `editCount`（N）+ `xhscdn.com`/`spectrum/` 预览计数。`references/publish-method.md` 同步。
- **Docs**: 修正 v1.6.1 条目中关于「补 change 事件即可修复上传」的表述——实测不充分，v1.6.2 才是真因修复。

### v1.6.1 (2026-08-18)

- **Fix**: `scripts/publish_note.sh` 修复图片上传只留空占位符的问题。
  - `DOM.setFileInputFiles` 设置文件后新增手动触发 `input` + `change` 事件，否则 Vue 不会开始实际上传。
  - 新增上传校验：等待 12 秒后统计 `xhscdn.com` / `spectrum/` 预览图数量，若小于上传张数则报错退出并保留 task space 供排查。
- **Docs**: SKILL.md「上传图片」章节重写，明确 CDP 批量上传必须触发 change 事件并校验 CDN 预览图；注意事项新增「图片上传必须校验」条目。
- **Docs**: 注意事项中进一步强调 draft 模式草稿存于当前浏览器本地、不跨浏览器/设备，只有发布后的笔记才进入账号云端。

### v1.6.0 (2026-08-18)

- **Feature**: 新增**存草稿模式**（draft）。用户要求「存草稿 / 推到草稿箱 / 自己点发布」时走此模式。
  - `scripts/publish_note.sh` 新增 `MODE` 参数：`publish`（默认，直接发布）/` draft`（存草稿箱）。
  - 收尾步骤按 `MODE` 分支：发布调 `host._onPublish()`，存草稿调 `host._onSave()`。
  - 存草稿校验改为「草稿箱(N)」计数 +1（正则 `草稿箱\((\d+)\)`），因为草稿模式页面不跳转。
- **Fix / Pitfall**: 固化已验证坑点——小红书**没有「存草稿」按钮**，发布页右下角文字是「暂存离开」，且同样藏在 `<xhs-publish-btn>` 闭渲染组件内，DOM/坐标/`snapshotText` 全部抓不到；必须直接调实例方法 `_onSave()`。SKILL.md 第 6、7 步与 `references/publish-method.md` 第 7b 节同步记录原理与失败方案对比表。

### v1.5.2 (2026-08-02)

- **Fix**: `card_generator.py` 的 `image-text` 布局 footer 不再固定 `height * 0.82`，而是根据文字块实际底部动态计算，避免账号署名和装饰横线与正文最后一行重叠。
- **Fix**: 卡片底部署名统一为 `@雨夜心灯` 格式。

### v1.5.1 (2026-08-02)

- **Fix**: 话题标签改为从下拉列表真实选中，而非直接粘贴纯文本 `#话题`。
  - `scripts/publish_note.sh` 新增 `TOPICS` 参数（逗号分隔，不带 `#`）。
  - 发布流程：输入正文 → 逐个输入 `#话题` 触发建议下拉 → 点击匹配项（优先精确匹配，否则选首个）→ 完成真正的话题挂载。
  - SKILL.md 同步更新「填写正文与话题标签」章节，说明为什么不能直接粘贴 `#话题`。

### v1.5.0 (2026-08-01)

- **Feature**: 新增**照片背景卡片**功能——支持满幅照片作为底图，文字压在图片上，带暗色遮罩、模糊、降饱和、胶片颗粒等效果。
- **3 个照片氛围主题**：`cinematic`（暗色电影感）、`film`（胶片颗粒）、`journal`（书页氛围）。每个主题预设遮罩强度、颜色、颗粒和降饱和参数。
- **New CLI args**:
  - `--background PATH` — 满幅背景照片路径（`.png`/`.jpg`/`.webp`），自动 center-crop 铺满
  - `--scrim FLOAT` — 暗色遮罩强度 `0–0.92`（默认取主题预设）
  - `--blur FLOAT` — 背景高斯模糊半径（默认 `0`）
  - `--desaturate [FLOAT]` — 背景降饱和 `0–1`；不带值时取 `0.65`
  - `--grain FLOAT` — 胶片颗粒强度 `0–0.4`
- **Auto bright-text reversal**: 非照片主题传入 `--background` 时，文字/辅助色自动反转为亮色，无需手动切换主题。
- **Photo layer stack**: SVG 底层新增 defs（滤镜 + 渐变）→ 照片 image → 暗色渐变遮罩 → 可选颗粒 → 前景投影组。背景图 base64 内嵌，与插画加载逻辑一致。
- **Text shadow filter**: 照片背景下整组前景元素统一加 `feDropShadow` 投影，保证任意画面上文字清晰可读。
- **Scrim gradient**: 暗色遮罩使用线性渐变（上下两端更重），保护顶部标签和底部页脚在亮区照片上仍可读。
- **Total themes**: **28**（25 纯色/渐变 + 3 照片背景）。
- **Docs**: SKILL.md 新增「照片背景卡片」完整章节：工作原理图解、三种主题对比表、CLI 用法示例、Agent 工作流模板。

### v1.4.0 (2026-08-01)

- **Feature**: 新增「图文卡片」布局（`--layout image-text`），与现有「纯文字」布局（`--layout text`，默认）并列可选。
- **Image-text layout**: 顶部插画 + 窄列居中文字（默认宽度 65%）+ 底部署名短横线 + 账号，整体延续温暖简笔哲思风。
- **New theme**: `warm_illust`（温暖简笔哲思），配色与截图示例一致：米白底 `#FAF7F2`、黑线稿、琥珀色 `#D4A84B` 点缀。
- **New CLI args**:
  - `--layout {text,image-text}` — 切换布局
  - `--illustration PATH` — image-text 布局的插画文件（支持 `.svg` / `.png` / `.jpg`）
  - `--image-text-width RATIO` — 文字区宽度占比（0.5–0.8，默认 0.65）
- **SVG illustration handling**: 自动提取 SVG 第一个 `<g>` 元素，移除原 `transform` 后居中放置，避免与卡片坐标叠加偏移。
- **Raster illustration handling**: PNG/JPG 转 base64 data URI，按最大 55% 宽度 / 32% 高度等比缩放（`preserveAspectRatio="xMidYMid meet"`）。
- **Docs**: SKILL.md 与 README 主题画廊更新为 25 种主题，新增图文布局用法示例。

### v1.3.3 (2026-08-01)

- **Audit Fix**: UGLIC + skill-release-audit 两轮审计发现的全部 ERR/WARN 修复。
- **Fix (I1/U1)**: SKILL.md body 版本号 `1.3.0` 与 frontmatter `1.3.2` 不一致 → 统一为 `1.3.3`。
- **Fix (L1/C1)**: 删除 `NODE_BIN`/`NODE_PATH` 死代码（硬编码的用户级绝对路径，全文件无引用）。
- **Fix (L2)**: 清理 `build_svg()` 中废弃的 `gradient_defs`/`gradient_id` 逻辑（SVG 侧渐变从未生效，实际由 CSS 处理）。
- **Fix (U2)**: 删除 4 个 `--show-*` 无操作 CLI 标志（`action="store_true", default=True` 永远为 True），只保留 `--hide-*`。
- **Fix (U3)**: Dependencies 表新增 Google Chrome / Chromium 依赖声明。
- **Fix (I2)**: 删除过期审计报告 `AUDIT-2026-07-31.md`（引用 v1.1.0，未被 SKILL.md 引用）。
- **Fix (I3)**: 删除 `__pycache__/` 构建产物。
- **Fix (C2)**: `render_png()` 改用 `try/finally` 确保临时 HTML 文件在 Chrome 崩溃时也能清理。
- **Fix (audit 模块6)**: 本地 skill 目录补齐 `README.md` 和 `LICENSE`（从 GitHub 仓库同步）。
- **Known**: I4 frontmatter 额外字段 (`version`/`bins`/`metadata`) 保留——ClawHub 发布需要，strict YAML 解析器可能报 warning 但不影响功能。

### v1.3.2 (2026-07-31)

- **Fix**: `doodle` theme font now uses **ZCOOL KuaiLe** (站酷快乐体) from Google Fonts — a playful, rounded Chinese display font that matches the hand-drawn doodle decorations. Previously Caveat/Permanent Marker are Latin-only and silently fell back to system Songti/PingFang, which broke the playful style.
- **Fix**: `steampunk` theme font now uses **Rye** (Western vintage slab) + **Noto Serif SC** from Google Fonts. Previously PingFang SC/Georgia looked too clean and modern for the dark brass/gear aesthetic; the new combination gives a vintage print feel consistent with steampunk.
- **Docs**: README theme preview images regenerated for doodle and steampunk to reflect the new typography.

### v1.3.1 (2026-07-31)

- **Fix**: XiaoHongShu style now has **two distinct modes** as originally documented in `text-to-elegant-image` repo: `xhs` = clean/formal mode, `xhs_rich` = lively/rich mode. Previously only the clean variant was implemented.
- **Mode A (`xhs`)**: white background + faint 45° red pinstripes + minimal dot accents — high breathing room for knowledge notes.
- **Mode B (`xhs_rich`)**: warm-pink gradient + hand-account dot pattern + glassmorphism blobs + three-segment gradient wave line — playful life-guide feel.
- **Total themes**: **24** (18 repo styles, with xhs split into A/B + 4 young-people + 1 warm original).
- **CLI**: added `--list-themes` to print all 24 themes and their display names.
- **Docs**: SKILL.md theme table updated to reflect all 24 themes and xhs/xhs_rich distinction.

### v1.3.0 (2026-07-31)

- **Breaking**: Port ALL 18 styles from `text-to-elegant-image` repo into the unified card generator. Total themes: **23** (18 repo + 4 young-people + 1 warm original).
- **Themes added**: cyberpunk, elegant, apple, cowork, newspaper, bloomberg, ink, steampunk, xhs, morandi (upgraded), glass, palace (upgraded), fresh, earthy, dreamy, macaron, carbon, vivid.
- **Each theme** extracts original repo's color palette, font stack, Google Fonts declaration, and decorative elements — all adapted to the unified layout (tag + centered text + footer).
- **Decorations**: 15 unique decoration styles (grid lines, scan lines, ink splashes, gears, glass blobs, leaves, sparkles, dots, etc.) — each theme has its own visual signature.
- **Google Fonts**: Themes requiring special fonts (palace: Ma Shan Zheng + ZCOOL XiaoWei; morandi/glass/fresh/earthy/dreamy/macaron/carbon/vivid: Inter; doodle: Caveat + Permanent Marker) all load via multi-mirror CDN fallback.

### v1.2.7 (2026-07-31)

- **Fix**: Remove the horizontal line above subtitle text in all themes. Subtitle now displays as `— 副标题 —` without the extra separator line above it, matching the user's reference screenshot style more closely.

### v1.2.6 (2026-07-31)

- **Feature**: Multi-mirror Google Fonts fallback for China network — `build_html()` now generates `<link>` tags for 3 CDN sources simultaneously: `fonts.loli.net` (community mirror), `fonts.googleapis.cn` (Google official China mirror), `fonts.googleapis.com` (original). Browser uses whichever loads first.
- **Feature**: JS-based font loading detection — after 3s timeout, checks `document.fonts.check()` for each declared font; if not loaded, dynamically injects mirror CSS as last resort
- **Why**: Google Fonts CDN (`fonts.googleapis.com`) is frequently blocked or extremely slow in mainland China, causing Chrome headless to fall back to system fonts and ruin theme-specific typography (e.g., palace theme falling back to Songti instead of Ma Shan Zheng calligraphy)

### v1.2.5 (2026-07-31)

- **Feature**: Google Fonts CDN loading in `build_html()` — themes declare `google_fonts` list, HTML auto-generates `<link>` tags to load fonts from `fonts.googleapis.com` regardless of local installation
- **Feature**: Add `palace` theme (故宫金红) — uses Ma Shan Zheng + ZCOOL XiaoWei calligraphic fonts from Google Fonts, gold-on-dark-red palette, corner ornaments and seal stamp decoration
- **Feature**: Add `morandi` theme (莫兰迪灰) — uses Inter from Google Fonts, desaturated muted palette
- **Improvement**: `doodle` theme now loads Caveat + Permanent Marker from Google Fonts for authentic hand-drawn feel
- **Fix**: Chrome `--virtual-time-budget=10000` added to ensure web fonts are fully loaded before screenshot capture
- **Architecture**: Every theme has `google_fonts` field (empty list = system fonts only), preventing silent fallback to wrong fonts

### v1.2.4 (2026-07-31)

- **Fix**: Card generator now auto-scales font size based on text length and line count to prevent overflow/cropping
- **Improvement**: Theme-specific font stacks for better style matching
  - `warm`/`minimal`: Songti SC serif (elegant/warm)
  - `y2k`: geometric sans-serif (tech/cool)
  - `doodle`: Chalkduster/Bradley Hand/Marker Felt with Kaiti fallback (hand-drawn feel)
  - `pop`: bold sans-serif (energetic)

### v1.2.3 (2026-07-31)

- **Feature**: Add built-in card generator (`references/card-generator/card_generator.py`) with 5 themes
  - `warm`（温暖哲思）、`minimal`（极简日系）、`y2k`（Y2K 千禧潮酷）、`doodle`（手绘涂鸦）、`pop`（渐变波普）
- **Feature**: Unified card layout matching classic XHS quote card style: top tag + quote marks, centered large text, bottom divider, page number and account
- **Feature**: Customizable footer parameters: `--hide-page-number`, `--hide-account`, `--hide-tag`, `--hide-subtitle`, `--page-number`, `--total-pages`, `--account`
- **Documentation**: Add card generation usage to SKILL.md

### v1.2.2 (2026-07-31)

- **Fix**: Support both UI entry points for entering image note page — try top "上传图文" tab first, fall back to "发布笔记" dropdown menu. Uses `input.upload-input` presence as the success check.
- **Fix**: Correct v1.2.0 changelog — both top tab and dropdown menu are valid, not a UI deprecation

### v1.2.1 (2026-07-31)

- **Fix**: Frontmatter dependency declaration for skill-release-audit
  - Add `bins: [ego-browser, node]`
  - Move env vars to `metadata.openclaw.requires.env`

### v1.2.0 (2026-07-31)

- **Fix**: Add support for top "上传图文" tab as an alternative entry point (both tab and dropdown menu work)
- **Fix**: Update publish success verification to also recognize `published=true` URL parameter
- **Fix**: Increase post-upload wait from 8s to 10s for more reliable image processing

### v1.1.0 (2026-07-31)

- **Security**: Fix shell variable injection risk in `publish_note.sh` — all user parameters now passed via `process.env` instead of shell heredoc expansion
- **Documentation**: Add formal Dependencies section with installation instructions and verification steps
- **Documentation**: Add reference load timing guidance for `references/publish-method.md`
- **Documentation**: Strengthen guardrail statements (advisory → mandatory)
- **Documentation**: Update Repository URL to multi-skill repo `better-office-work-flow`
- **Documentation**: Add input validation for TITLE (no single quotes) and BODY (no backticks/`${`)

### v1.0.0 (2026-07-31)

- Initial open-source release
