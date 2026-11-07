# DOM 选择器与 ego-browser API 速查（zhihu-yanghao）

## 知乎关键选择器 / 按钮
| 目标 | 选择器 / 判定 | 说明 |
|---|---|---|
| 赞同按钮 | `button[aria-label*="赞同"]` | **⚠️ 8/11 实测旧 `button.VoteButton:not(.VoteButton--down)` / `button.VoteButton--up` 已失效**（知乎改版）；aria-label 形如 `"已赞同 1020 "` / `"赞同 307"`（**含尾空格必须 `trim()`**）；`.click()` 触发点赞 |
| 已赞同判定 | `b.classList.contains('is-active')`（class 含 `VoteButton is-active`） | 再点会**取消**点赞（toggle 行为）；点赞前必须判此跳过，否则把已赞取消。innerText 含「已赞同」也可但不如 class 稳 |
| ⚠️ 按钮 innerText 零宽字符 | `/赞同/.test(b.innerText)` 可命中，但 `b.innerText.trim()==='赞同 87'` 命中 0 | **8/12 实测**：innerText 实际为 `"\u200b 已赞同 87"`（前导零宽字符 `\u200b` + 空格）；**一律用 `aria-label` + `trim()` 做精确匹配**，绝不依赖 innerText 等值 |
| 回答容器 | `[data-zop]` | 每个含 `itemId`（JSON.parse 取），用于去重遍历前 10 个作为随机选赞候选池 |
| Draft.js 编辑器 | `.public-DraftEditor-content` | 正文注入目标。**v1.3.2 起新回答/想法用 ClipboardEvent 粘贴注入**（`fillInput` 在 Draft.js 上不稳，Draft.js 不认）；`\n\n` 分段 |
| 正文粘贴注入（v1.3.2） | `ed.focus(); const dt=new DataTransfer(); dt.setData("text/plain", text); ed.dispatchEvent(new ClipboardEvent("paste", {clipboardData: dt, bubbles:true, cancelable:true, composed:true}))` | 实测 9/5 深度版 1147 字注入成功；修改已发布回答另用 `insertHTML`（见下节） |
| 「写回答」按钮 | `button` 且 `innerText.includes('写回答')` | 文本前有零宽字符 `\u200b`，**不能**用 `===` |
| 「查看我的回答」按钮 | `button` 且 innerText 含「查看我的回答」 | 出现 = 该问题已答过，5 天内避开 |
| 「发布回答」按钮 | `button` 且 **清洗零宽字符后**文本 ∈ `["发布回答","提交回答"]`（`replace(/[\u200b\s]+/g,'')`），回退候选「发布」仅在存在 `.public-DraftEditor-content` 时启用 | 用 js click 才稳（8/7 实测 `Button--blue` 不稳定）。**⚠️ v1.3.7 修正**：旧写法 `innerText.trim() === '发布回答'` **不可用**——`trim()` 不去 `\u200b`，按钮带零宽字符时静默 `publish-clicked: false`（正文已填、URL 不跳转、无报错；2026-09-15 实测踩坑） |
| 发布成功标志 | URL 跳转 `/question/{qid}/answer/{aid}` | 约 5 秒后跳转；按钮变 disabled +「发布中…」 |
| 「编辑回答」按钮 | 回答页 `button` 含「编辑回答」 | 存在 = 回答已发布且可见 |
| 按时间排序菜单 | 找 `b.innerText.trim() === '默认排序'` 按钮，再点「按时间排序」 | 新回答默认排序靠后，验证可见性需切此 |
| 历史类话题 ID | `19551077`（机器学习是 `19559450`，别搞混） | 话题页入口 |
| 精华区 URL | `/topic/19551077/top-answers` | 带连字符；`/top_answers` 是 404 |
| 折叠验证 | **权威（v1.3.7 修正）：创作者中心列表的「被折叠」标签**——用 `scripts/fold_audit.js` 巡检（滚动抓全量 + 与 `~/space/skills-data/zhihu-yanghao/fold-baseline.json` 比对）；CLI `scripts/verify_via_cli.js`（输出 `VERIFY_RESULT: OK_NOT_COLLAPSED`）**仅作辅助** | ⚠️ **2026-09 新「隐藏机制」下 CLI Summary 失明**：被折叠回答的 Summary 仍非空，CLI 会把已折叠判成未折叠。`serverFetch('/api/v4/answers/{aid}')` 自 8/26 起恒 403（verify_fold.js 已删）。fold_audit 为唯一可靠信号 |

### 想法 / 动态（2026-08-31 实测）
| 目标 | 选择器 / 判定 | 说明 |
|---|---|---|
| 「发想法」入口 | `button` 且 `innerText.includes('发想法')` | 首页顶部（知乎首页 URL 不变，弹窗形式） |
| 想法编辑器 | `.public-DraftEditor-content` | **与回答编辑器同一个类**，fillInput 直接复用 |
| 「发布」按钮 | 从编辑器向上遍历祖先（≤10 层），取 `innerText.trim() === '发布'` 的 button | 注意是「发布」**不是**「发布回答」 |
| 发布成功标志 | **浏览器侧不可信**：弹窗会重置为空白编辑器（`editorRemaining` 恒为 1，假阴性） | 权威校验：CLI `me contents --type pin --limit 3` |

### 编辑已发布回答（2026-09-01 实测）
| 目标 | 选择器 / 判定 | 说明 |
|---|---|---|
| 「编辑回答」按钮 | 回答页 `button` 且 `innerText.includes('编辑回答')` | 存在 = 回答已发布且可见 |
| 提交按钮 | `button` 且 `innerText.trim() === '提交修改'` | ⚠️ 真名是「提交修改」**不是**「发布修改」；另有「保存草稿并离开」「发布设置」易混淆 |
| 清空编辑器 | `ed.focus(); document.execCommand('selectAll'); document.execCommand('delete')` | fillInput 在清空后的 Draft.js 上**失效**（innerText 长度=1） |
| 注入新内容 | `document.execCommand('insertHTML', false, '<p>…</p>…')` | **唯一已验证可行**的替换方法；`\n\n` → 段落 `<p>`，段内 `\n` → `<br>` |
| 提交效果判定 | 轮询「提交修改」按钮是否消失（编辑态退出） | ⚠️ **已知问题**：点击后提交可能不被响应（无弹窗无报错），疑似需 mousedown/mouseup 序列；未退出即停，转人工 |

## ego-browser nodejs API 速查
> 这些全局函数在 `ego-browser nodejs` 运行时可用（无需 import）。

| API | 作用 |
|---|---|
| `useOrCreateTaskSpace(name)` | 创建 / 复用任务空间，返回 `{ id }` |
| `claimTaskSpace(id)` | **取回被人工接管的任务空间**（8/31 实测：报 `The user has taken control of this task space` 时禁止重试/自行夺回，等用户放行后用此恢复；space id 规则 `zhihu-shift-{shift}-{qid}`） |
| `openOrReuseTab(url, { wait, timeout })` | 打开或复用标签页 |
| `wait(sec)` | 等待秒数（用于阅读模拟、点赞间隔、发布前等） |
| `js(codeString)` | 在页面执行 JS，返回结果（code 为字符串，建议字符串拼接避免模板插值） |
| `fillInput(selector, text)` | 向输入框 / 编辑器填值（直接 UTF-8 字符串） |
| `scrollBy(px)` | 滚动触发懒加载 |
| `pageInfo()` | 返回 `{ url, title }` |
| `serverFetch(url, headers?)` | 带 ego-browser 登录态的 fetch（可拿登录态 API） |
| `completeTaskSpace(name, { keep })` | 关闭任务空间（`keep:false` 清理） |
| `listTabs()` / `closeTab(id)` | 标签页管理 |
| `cliLog(str)` | 向 ego-browser 日志输出（脚本内用） |
| `taskSpace(name)` → `{ spaceId, page('p1'), finish() }` | **新版 API**（v1.5.0 插图必需）：`const t = await taskSpace('xxx'); const p = t.page('p1')`。旧版 `useOrCreateTaskSpace` 没有 `setInputFiles`，插图必须走新版 |
| `p.setInputFiles(selector, localPath)` | 上传本地文件到隐藏 input；知乎编辑器用 `input[accept*="image"]`（2026-11-06 实测，工具栏图片按钮不用点） |
| `p.evaluate(fn)` / `p.waitForSelector(sel,{state,timeout})` / `p.waitForTimeout(ms)` / `p.goto(url)` / `p.waitForFunction(fn)` / `p.screenshot({path})` / `p.title()` / `p.url()` | 新版 page API，等价于旧版 `js()` / `wait()` / `openOrReuseTab()` 等，支持上传与截图 |
| `t.finish({ keep: [] })` | 新版关闭任务空间（11/06 实测：`keep:false` 参数报错，`keep: []` 通过；旧版 `completeTaskSpace(name,{keep:false})` 仍可用于旧 API 会话） |

### 配图 / 插图（2026-11-06 实测，详见 references/illustrations.md）
| 目标 | 选择器 / 判定 | 说明 |
|---|---|---|
| 图片上传控件 | `input[accept*="image"]` | 编辑器打开后即存在的隐藏 input，**不必点工具栏图片按钮**；用 `p.setInputFiles()` 塞本地绝对路径 |
| 上传完成判定 | `img.complete && img.naturalWidth > 0` 且 `src` 落在 `pic-private.zhihu.com` / `pic*.zhimg.com` | 只看 `imgs.length` 会拿到白图；每次上传后等 8–10 秒 |
| 正文分段 | `raw.trim().split(/\n\s*\n/)` → 逐段 `ClipboardEvent` 粘贴 | 顺序「段1 → 上传图1 → 段2 → 上传图2 → 剩余段落（含文末署名）」，不要先粘全文再批量传图 |
| 发布前 dry run | `p.screenshot({ path: '/tmp/zhihu_editor_preview.png' })` + `ViewImage` 验段落/图片顺序 | 图片全 OK + 顺序对 + 用户确认后才点发布 |
| 配图发布成功的辅助信号 | CLI `me contents --type answer --limit 3` 最新一条 Summary 含 `[图片]` | 仍是辅助；折叠权威信号看 `fold_audit.js` |
| 发布按钮（手工路径） | `[\u200b\s]+` 清洗后 ∈ `["发布回答","提交回答"]`，回退「发布」仅在编辑器存在时 | 一次点击，`waitForFunction(() => /\/answer\/[0-9]+/.test(location.href))` 等真实跳转，卡住即停不重试 |

## js 代码字符串写法建议
- 脚本文件（scripts/）内用**字符串拼接**组装 js 代码（避免 `${}` 被外壳展开）：
  ```js
  // ✅ 用当前有效选择器（aria-label + trim），旧 VoteButton 系列已失效勿用
  const r = await js('(() => {'
    + ' const b = Array.from(document.querySelectorAll("button[aria-label*=\"赞同\"]"))[0];'
    + ' return b ? (b.getAttribute("aria-label") || "").trim() : "";'
    + '})()')
  ```
- 若直接写 `ego-browser nodejs <<'EOF' ... EOF'`（单引号 EOF），可用模板字符串与 `${JSON.stringify(x)}` 注入参数。
