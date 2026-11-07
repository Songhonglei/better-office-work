// post_moment.js — 知乎发想法 / 动态（zhihu-yanghao v1.3.0）
// 用法（Bash 必须 dangerouslyDisableSandbox:true，且关闭沙箱开关）：
//   先把参数写到 /tmp/zhihu_moment_params.json（见底部 schema），再：
//   ego-browser nodejs < scripts/post_moment.js
//   兼容 env：CONTENT / CONTENT_FILE / DRY_RUN
//
// 行为：打开知乎首页 → 点「发想法」→ 填正文 → （dryRun 则停）→ 等风控 → 点「发布」→ 校验弹窗关闭
//
// 选择器（2026-08-31 实测）：
//   入口按钮   button 文本含「发想法」（首页顶部，class 动态如 css-usknaz）
//   编辑器     .public-DraftEditor-content   ← 与回答编辑器同一个类
//   发布按钮   从编辑器向上找祖先，取 innerText.trim() === '发布' 的 button
//
// ⚠️ 风控：想法属创作内容，两条之间间隔 ≥5 分钟；单次任务只发 1 条。

(async () => {
  const fs = require('fs')
  const path = require('path')

  // ---------- 0. 参数加载（env 优先，回退参数文件） ----------
  function loadParams() {
    const p = {}
    if (process.env.CONTENT) p.content = process.env.CONTENT
    if (process.env.CONTENT_FILE) p.contentFile = process.env.CONTENT_FILE
    if (process.env.DRY_RUN) p.dryRun = (process.env.DRY_RUN === '1' || process.env.DRY_RUN === 'true')
    const file = '/tmp/zhihu_moment_params.json'
    try {
      const f = JSON.parse(fs.readFileSync(file, 'utf8'))
      for (const k of ['content', 'contentFile', 'configPath', 'dryRun']) {
        if (f[k] != null && p[k] == null) p[k] = f[k]
      }
      cliLog('PARAMS_FROM_FILE: ' + file)
    } catch (e) {
      cliLog('PARAMS_FILE_MISSING: ' + file + ' (' + e.message + ')')
    }
    return p
  }
  const P = loadParams()

  // ---------- 1. 加载配置（取 moments 字数区间做提示） ----------
  // 同 run_shift.js：配置放 skill 目录外，skill 升级不覆盖
  const SKILLS_DATA = process.env.WB_SKILLS_DATA ||
    path.join(process.env.HOME || '', 'space', 'skills-data')
  const DATA_DIR = path.join(SKILLS_DATA, 'zhihu-yanghao')
  const LEGACY_CONFIG = path.join(process.env.HOME || '', '.workbuddy', 'skills', 'zhihu-yanghao')

  function loadConfig() {
    const candidates = []
    if (P.configPath) candidates.push(P.configPath)
    candidates.push(path.join(DATA_DIR, 'config.json'))
    candidates.push(path.join(process.cwd(), 'config.json'))
    candidates.push(path.join(LEGACY_CONFIG, 'config.json'))
    for (const c of candidates) {
      if (!c) continue
      try { return { path: c, data: JSON.parse(fs.readFileSync(c, 'utf8')) } } catch (e) {}
    }
    return null
  }
  const cfg = loadConfig()
  const mCfg = (cfg && cfg.data && cfg.data.moments) || {}
  const minW = mCfg.min_words || 50
  const maxW = mCfg.max_words || 150
  if (cfg) cliLog('CONFIG_LOADED: ' + cfg.path)

  // ---------- 2. 正文 ----------
  let content = P.content || ''
  if (!content && P.contentFile) {
    try { content = fs.readFileSync(P.contentFile, 'utf8') } catch (e) {
      cliLog('ERROR: cannot read contentFile ' + P.contentFile + ' (' + e.message + ')'); return
    }
    cliLog('CONTENT_FROM_FILE: ' + P.contentFile)
  }
  content = (content || '').trim()
  if (!content) { cliLog('ERROR: no content (set content or contentFile)'); return }
  const w = content.length
  cliLog('CONTENT_LEN: ' + w + ' (config range ' + minW + '-' + maxW + ')')
  if (w < minW || w > maxW) cliLog('WARN: length outside configured moments range — publishing anyway')

  // Fail-safe（GLIC C2）：想法是不可逆的公开发布动作，未显式 dryRun=false 时一律只填不发布
  const dryRun = P.dryRun !== false
  if (P.dryRun == null) cliLog('DRY_RUN_DEFAULT: 未显式设置 dryRun，默认只填不发布（实发请在参数文件写 "dryRun": false）')
  cliLog('DRY_RUN: ' + dryRun + (dryRun ? ' (fill only, will NOT publish)' : ''))

  // ---------- 3. 打开发想法 ----------
  const space = 'zhihu-moment'
  const task = await useOrCreateTaskSpace(space)
  await openOrReuseTab('https://www.zhihu.com', { wait: true, timeout: 25 })
  await wait(6)

  const opened = await js('(() => {'
    + ' const btns = Array.from(document.querySelectorAll("button, a, div[role=button]"));'
    + ' for (let i = 0; i < btns.length; i++) {'
    + '   const t = (btns[i].innerText || "").trim();'
    + '   if (t.indexOf("发想法") >= 0) { btns[i].click(); return "clicked:" + t; }'
    + ' }'
    + ' return "no_entry";'
    + '})()')
  cliLog('EDITOR_OPEN: ' + opened)
  if (opened === 'no_entry') {
    cliLog('ERROR: 未找到「发想法」入口，可能未登录或页面结构变化')
    await completeTaskSpace(space, { keep: false })
    return
  }
  await wait(6)

  // ---------- 4. 填正文 ----------
  try {
    const ok = await js('((text) => {'
      + ' const editor = document.querySelector(".public-DraftEditor-content");'
      + ' if (!editor) return false;'
      + ' editor.focus();'
      + ' const range = document.createRange();'
      + ' range.selectNodeContents(editor);'
      + ' range.collapse(false);'
      + ' const sel = window.getSelection();'
      + ' sel.removeAllRanges();'
      + ' sel.addRange(range);'
      + ' const dt = new DataTransfer();'
      + ' dt.setData("text/plain", text);'
      + ' editor.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true, composed: true }));'
      + ' return true;'
      + '})(' + JSON.stringify(content) + ')')
    if (!ok) throw new Error('DraftEditor not found, 想法内容未注入')
    cliLog('FILLED: ok')
  } catch (e) {
    cliLog('FILL_FAILED: ' + e.message + ' — 若报 Element not found，先查登录态（页面是否「登录/注册」）')
    await completeTaskSpace(space, { keep: false })
    return
  }
  await wait(3)

  if (dryRun) {
    cliLog('DRY_RUN_STOP: 已填内容，按要求不发布。确认无误后去掉 dryRun 再跑一次。')
    await completeTaskSpace(space, { keep: false })
    return
  }

  // ---------- 5. 风控等待后发布 ----------
  cliLog('risk-control wait 30s before publish...')
  await wait(30)

  const pub = await js('(() => {'
    + ' const ed = document.querySelector(".public-DraftEditor-content");'
    + ' if (!ed) return "no_editor";'
    + ' let root = ed;'
    + ' for (let i = 0; i < 10 && root; i++) {'
    + '   const bs = Array.from(root.querySelectorAll("button"));'
    + '   const b = bs.find(function (x) { return (x.innerText || "").trim() === "发布"; });'
    + '   if (b) { b.click(); return "clicked"; }'
    + '   root = root.parentElement;'
    + ' }'
    + ' return "no_publish_button";'
    + '})()')
  cliLog('PUBLISH_CLICK: ' + pub)
  if (pub !== 'clicked') {
    cliLog('ERROR: 发布失败 — ' + pub + '。不要重试（避免累积卡死草稿），人工检查。')
    await completeTaskSpace(space, { keep: false })
    return
  }
  await wait(12)

  // ---------- 6. 校验 ----------
  // ⚠️ 浏览器侧校验不可靠（2026-08-31 实测）：发布成功后弹窗会重置为空白编辑器，
  //    editorRemaining 仍为 1，属假阴性，不能据此判定失败。
  //    权威校验请用官方 CLI：zhihu-cli me contents --type pin --limit 3
  //    （想法在 API 里的内容类型是 pin，不是 moment）
  const verify = await js('(() => {'
    + ' const still = document.querySelectorAll(".public-DraftEditor-content").length;'
    + ' return JSON.stringify({ editorRemaining: still, url: location.href });'
    + '})()')
  cliLog('VERIFY_PAGE_ONLY(unreliable): ' + verify)
  cliLog('VERIFY_HINT: 用 `zhihu-cli me contents --type pin --limit 3` 做权威校验（想法类型=pin）')
  cliLog('MOMENT_DONE' + (dryRun ? ' (dry run)' : ''))

  await completeTaskSpace(space, { keep: false })
})()

// 参数文件 schema（/tmp/zhihu_moment_params.json）：
// {
//   "content": "想法正文（50-150 字）",
//   "contentFile": "/abs/moment.txt",   // 与 content 二选一，优先 content
//   "configPath": "/abs/config.json",   // 可选，用于读取 moments 字数区间
//   "dryRun": false                     // 默认 true（fail-safe 只填不发布）；实发必须显式写 false
// }
