// run_shift.js — 知乎养号三班编排脚本（zhihu-yanghao v1.1.0）
// 用法（Bash 必须 dangerouslyDisableSandbox:true，且关闭沙箱开关）：
//   先把参数写到 /tmp/zhihu_shift_params.json（见底部 schema），再：
//   ego-browser nodejs < scripts/run_shift.js
//   兼容旧式 env 传参（其他机器若 ego-browser 透传 env 仍可用）：
//   SHIFT=morning QID=xxx CONTENT_FILE=xxx ego-browser nodejs < scripts/run_shift.js
//
// 行为：读配置 → 按 班次+日序号 轮转话题池取关键词 → 选未答过问题(QID 可覆盖)
//        → 前10候选随机选3-5点赞(自然化) → 若 answer=true 校验去AI味门禁(v1.5.0) → 写/发布/验证1回答
//        → 按 interactions 做可选收藏/关注/评论
// v1.5.0: 发布前必须已跑 scripts/humanize_gate.py，凭证与正文 sha256 绑定；不过则跳过发布。
//
// 参数优先级：env（SHIFT/CONFIG/QID/CONTENT/CONTENT_FILE/KW/LIMIT/COMMENT_TEXT/ALLOW_EXAMPLE_CONFIG）> /tmp/zhihu_shift_params.json
// 注：部分 ego-browser 构建不向 nodejs 运行时透传 shell env，故参数文件为可靠路径。
// 2026-11-11：回退到 config.example.json 时不直接退出，改为输出警告 + 等用户明确确认（见 1.1 节）。

(async () => {
  const fs = require('fs')
  const path = require('path')

  // ---------- 0. 参数加载（env 优先，回退参数文件） ----------
  function loadParams() {
    const p = {}
    if (process.env.SHIFT) p.shift = process.env.SHIFT
    if (process.env.CONFIG) p.configPath = process.env.CONFIG
    if (process.env.QID) p.qid = process.env.QID
    if (process.env.CONTENT) p.content = process.env.CONTENT
    if (process.env.CONTENT_FILE) p.contentFile = process.env.CONTENT_FILE
    if (process.env.KW) p.kw = process.env.KW
    if (process.env.LIMIT) p.limit = process.env.LIMIT
    if (process.env.COMMENT_TEXT) p.commentText = process.env.COMMENT_TEXT
    if (process.env.ALLOW_EXAMPLE_CONFIG) p.allowExampleConfig = process.env.ALLOW_EXAMPLE_CONFIG
    const file = '/tmp/zhihu_shift_params.json'
    if (!p.shift) {
      try {
        const f = JSON.parse(fs.readFileSync(file, 'utf8'))
        for (const k of ['shift', 'configPath', 'qid', 'content', 'contentFile', 'kw', 'limit', 'commentText', 'deep']) {
          if (f[k] != null && p[k] == null) p[k] = f[k]
        }
        cliLog('PARAMS_FROM_FILE: ' + file)
      } catch (e) {
        cliLog('PARAMS_FILE_MISSING: ' + file + ' (' + e.message + ')')
      }
    }
    // 模板确认参数独立于 shift 读取：env 粘滞时参数文件的 shift 会被跳过，这两个字段不能一起丢
    try {
      const cf = JSON.parse(fs.readFileSync(file, 'utf8'))
      if (cf.allowExampleConfig != null && p.allowExampleConfig == null) p.allowExampleConfig = cf.allowExampleConfig
      if (cf.exampleConfirmTimeoutSec != null && p.exampleConfirmTimeoutSec == null) p.exampleConfirmTimeoutSec = cf.exampleConfirmTimeoutSec
    } catch (e) {}
    return p
  }
  const P = loadParams()

  // ---------- 1. 加载配置 ----------
  // 配置属运行时数据，放在 skill 目录之外：$WB_SKILLS_DATA/<skill>/（默认 ~/space/skills-data）。
  // 这样 skill 目录被升级/镜像全量覆盖也不会动到配置，且多个 agent 共用同一份。
  const SKILLS_DATA = process.env.WB_SKILLS_DATA ||
    path.join(process.env.HOME || '', 'space', 'skills-data')
  const DATA_DIR = path.join(SKILLS_DATA, 'zhihu-yanghao')
  // 旧位置（数据外置之前配置放在 skill 目录内），仅作一次性兼容回退
  const LEGACY_CONFIG = path.join(process.env.HOME || '', '.workbuddy', 'skills', 'zhihu-yanghao')

  function loadConfig() {
    const candidates = []
    if (P.configPath) candidates.push(P.configPath)
    if (process.env.CONFIG) candidates.push(process.env.CONFIG)
    candidates.push(path.join(DATA_DIR, 'config.json'))
    candidates.push('/tmp/zhihu_config.json')
    candidates.push(path.join(process.cwd(), 'config.json'))
    candidates.push(path.join(process.cwd(), 'config.example.json'))
    candidates.push(path.join(LEGACY_CONFIG, 'config.json'))
    candidates.push(path.join(LEGACY_CONFIG, 'config.example.json'))
    for (const c of candidates) {
      if (!c) continue
      try { return { path: c, data: JSON.parse(fs.readFileSync(c, 'utf8')) } } catch (e) {}
    }
    return null
  }
  const cfg = loadConfig()
  if (!cfg) { cliLog('ERROR: no config.json found'); return }
  cliLog('CONFIG_LOADED: ' + cfg.path)
  if (cfg.path.indexOf('/tmp/') === 0) {
    cliLog('WARN: 正在使用 /tmp 影子配置（' + cfg.path + '）——临时副本会顶替数据目录的正式配置，且可能缺少 account_status 禁言护栏。确认是刻意临时覆盖，否则删除该文件。')
  }

  // ---------- 1.1 模板配置保护：醒目警告 + 用户明确确认（不直接退出） ----------
  // 配置外置后包里只剩模板，数据目录 config.json 丢失时回退链末端就会落到它。
  // 用户明确要求：不做一刀切 fail-safe 退出，给警告、给人确认机会，确认后照常继续。
  const isExample = /config\.example\.json$/.test(cfg.path) || cfg.data.account === '你的知乎账号ID'
  if (isExample) {
    cliLog('⚠️ CONFIG_EXAMPLE_WARNING: 本次选中了模板配置 ' + cfg.path)
    cliLog('⚠️ 风险 1：account=' + (cfg.data.account || '?') + ' 是占位符，account_status 没有真实的禁言/恢复历史')
    cliLog('⚠️ 风险 2：模板 shifts 三班 answer 全为 true —— 三班连跑会突破 1 回答/天红线')
    cliLog('⚠️ 风险 3：话题池 / 垂直领域 / 发布门禁都是示例值，不代表你账号的策略')
    cliLog('⚠️ 建议：先 cp config.example.json ' + path.join(DATA_DIR, 'config.json') + ' 改成自己的配置再跑')
    const preApproved = P.allowExampleConfig === true ||
      ['1', 'true', 'yes'].indexOf(String(P.allowExampleConfig).toLowerCase()) >= 0
    if (preApproved) {
      cliLog('CONFIG_EXAMPLE_CONFIRMED: 已显式 allowExampleConfig（书面同意），继续按模板配置执行，其余门禁照常生效')
    } else {
      const confirmToken = require('crypto').randomBytes(6).toString('hex')
      const confirmFile = '/tmp/zhihu_example_confirm.flag'
      const requestFile = '/tmp/zhihu_example_confirm_request.json'
      try { fs.unlinkSync(confirmFile) } catch (e) {}
      try {
        fs.writeFileSync(requestFile, JSON.stringify({
          token: confirmToken, confirmFile: confirmFile, config: cfg.path, reason: 'CONFIG_EXAMPLE'
        }, null, 1))
      } catch (e) {}
      const timeoutSec = Number(P.exampleConfirmTimeoutSec) > 0 ? Number(P.exampleConfirmTimeoutSec) : 300
      const rounds = Math.ceil(timeoutSec / 5)
      cliLog('CONFIG_EXAMPLE_CONFIRM_REQUIRED: 需要用户明确确认才能继续（等待 ' + timeoutSec + 's）')
      cliLog('CONFIG_EXAMPLE_CONFIRM_HINT: agent 必须用 AskUserQuestion 问用户；同意后把 token=' + confirmToken +
        ' 写入 ' + confirmFile + '（或 JSON {"allow":true,"token":"..."}）；不得自行写入')
      // ego-browser nodejs 长等待需保活，否则进程可能被回收
      const keep = setInterval(function () {}, 1000)
      let confirmed = false
      for (let i = 0; i < rounds; i++) {
        await new Promise(function (r) { setTimeout(r, 5000) })
        try {
          const v = fs.readFileSync(confirmFile, 'utf8').trim()
          let ok = (v === confirmToken)
          try { const j = JSON.parse(v); if (j.allow === true && j.token === confirmToken) ok = true } catch (e) {}
          if (ok) { confirmed = true; break }
        } catch (e) {}
        if (i % 6 === 5) cliLog('CONFIG_EXAMPLE_WAITING: 已等 ' + ((i + 1) * 5) + 's / ' + timeoutSec + 's，仍未获确认')
      }
      clearInterval(keep)
      if (!confirmed) {
        cliLog('SHIFT_SKIPPED: ' + (P.shift || '?') + ' (example config not confirmed) — no answer / no like / no collect / no follow / no comment')
        cliLog('SHIFT_DONE: ' + (P.shift || '?') + ' qid=none aid=NONE (example config not confirmed)')
        return
      }
      cliLog('CONFIG_EXAMPLE_CONFIRMED: 用户已明确同意，继续按模板配置执行（风险自负，其余门禁照常生效）')
    }
  }

  // ---------- 0. 账号受限期护栏（fail-safe，优先于一切动作） ----------
  const acct = cfg.data.account_status || {}
  if (acct.silenced === true) {
    cliLog('SILENCED_MODE: 账号处禁言期（' + (acct.silenced_from || '?') + ' → ' + (acct.silenced_until || '?') + '）：本脚本不做任何写操作，直接退出')
    cliLog('SILENCED_HINT: 只读浏览请跑 scripts/browse_only.js；禁言解除后把 config.account_status.silenced 改为 false')
    cliLog('SHIFT_SKIPPED: ' + (P.shift || '?') + ' (silenced) — no answer / no like / no collect / no follow / no comment')
    cliLog('SHIFT_DONE: ' + (P.shift || '?') + ' qid=none aid=NONE (silenced)')
    return
  }

  const SHIFT = (P.shift || '').toLowerCase()
  if (!['morning', 'noon', 'evening'].includes(SHIFT)) {
    cliLog('ERROR: set SHIFT=morning|noon|evening (or shift in params file)'); return
  }
  const shiftCfg = (cfg.data.shifts || {})[SHIFT]
  if (!shiftCfg || shiftCfg.enabled === false) {
    cliLog('SHIFT_DISABLED: ' + SHIFT + ' (set enabled:true in config to run)'); return
  }
  cliLog('SHIFT: ' + SHIFT + ' answer=' + !!shiftCfg.answer)

  // ---------- 2. 话题轮转（全局池 + 日序号偏移） ----------
  function dayOfYear(d) {
    const start = new Date(d.getFullYear(), 0, 0)
    const diff = d - start
    return Math.floor(diff / 86400000)
  }
  const pool = (cfg.data.topic_pool || []).filter(Boolean)
  let kw = P.kw
  if (!kw && pool.length) {
    const offsets = { morning: 0, noon: 1, evening: 2 }
    const n = pool.length
    const base = dayOfYear(new Date()) + offsets[SHIFT]
    const pick = [pool[base % n], pool[(base + 1) % n], pool[(base + 2) % n]].filter(Boolean)
    kw = pick.join(',')
  }
  cliLog('ROTATED_KW: ' + kw)

  // ---------- 3. 选题（QID 未指定时自动选） ----------
  async function pickQuestion(keywords, limit) {
    const space = 'zhihu-pick'
    const task = await useOrCreateTaskSpace(space)
    await openOrReuseTab('https://www.zhihu.com/hot', { wait: true, timeout: 20 })
    await wait(5)
    const kws = keywords.split(',').map(function (s) { return s.trim() }).filter(Boolean)
    const hot = await js('(() => {'
      + ' const items = Array.from(document.querySelectorAll(".HotItem"));'
      + ' const out = [];'
      + ' for (let i = 0; i < items.length && i < ' + limit + '; i++) {'
      + '   const el = items[i];'
      + '   const a = el.querySelector("a");'
      + '   const titleEl = el.querySelector(".HotItem-title") || a;'
      + '   const metrics = el.querySelector(".HotItem-metrics");'
      + '   out.push({ i: i, title: titleEl ? titleEl.innerText.trim() : "", href: a ? a.getAttribute("href") : "", metrics: metrics ? metrics.innerText.trim() : "" });'
      + ' }'
      + ' return out.filter(function (x) { return x.title; });'
      + '})()')
    const hit = hot.filter(function (x) { return kws.some(function (k) { return x.title.indexOf(k) >= 0; }); })
    cliLog('HOT_TOTAL: ' + hot.length + ' KEYWORD_HITS: ' + hit.length)
    cliLog('HITS: ' + JSON.stringify(hit.map(function (x) { return x.title + ' [' + x.metrics + ']'; }), null, 2))
    let chosen = null
    for (let i = 0; i < hit.length; i++) {
      const m = (hit[i].href || '').match(/question\/(\d+)/)
      if (m) { chosen = { qid: m[1], title: hit[i].title }; break }
    }
    if (!chosen) {
      for (let i = 0; i < hot.length; i++) {
        const m = (hot[i].href || '').match(/question\/(\d+)/)
        if (m) { chosen = { qid: m[1], title: hot[i].title }; break }
      }
    }
    await completeTaskSpace(space, { keep: false })
    return chosen
  }

  let qid = P.qid
  let chosenTitle = ''
  if (!qid) {
    const limit = parseInt(P.limit || '25', 10)
    const c = await pickQuestion(kw, limit)
    if (!c) { cliLog('ERROR: no candidate question found for KW=' + kw); return }
    qid = c.qid; chosenTitle = c.title
    cliLog('PICKED qid=' + qid + ' title=' + chosenTitle)
  } else {
    cliLog('QID_OVERRIDE: ' + qid)
  }

  const space = 'zhihu-shift-' + SHIFT + '-' + qid
  const task = await useOrCreateTaskSpace(space)
  const url = 'https://www.zhihu.com/question/' + qid
  await openOrReuseTab(url, { wait: true, timeout: 20 })
  await wait(4)

  // ---------- 4. 已答过跳过 ----------
  const answered = await js('(() => {'
    + ' const btns = Array.from(document.querySelectorAll("button"));'
    + ' return btns.some(function (b) { return b.innerText.indexOf("查看我的回答") >= 0; });'
    + '})()')
  cliLog('already-answered: ' + answered)
  if (answered) {
    cliLog('SKIP: question already answered, pick another')
    await completeTaskSpace(space, { keep: false })
    return
  }

  // ---------- 5. 点赞：前 pool 个候选里随机选 min~max 个（自然化，避免每次固定点赞前 N 被风控） ----------
  cliLog('simulating read 90s (human pace)...')
  await wait(90)
  const interactions = shiftCfg.interactions || {}

  // like spec 兼容：旧式整数 N（=固定 N 个） / 新式对象 {pool,min,max}
  function parseLikeSpec(raw) {
    if (raw == null) return null
    if (typeof raw === 'number') return { pool: raw, min: raw, max: raw }
    if (typeof raw === 'object') {
      const pool = parseInt(raw.pool, 10)
      let min = parseInt(raw.min, 10)
      let max = parseInt(raw.max, 10)
      if (isNaN(pool)) return null
      if (isNaN(min)) min = pool
      if (isNaN(max)) max = pool
      if (min > max) { const t = min; min = max; max = t }
      return { pool: pool, min: min, max: max }
    }
    return null
  }
  const likeSpec = parseLikeSpec(interactions.like)

  if (likeSpec) {
    const before = await js('(() => {'
      + ' const seen = new Set(); const arr = [];'
      + ' const nodes = document.querySelectorAll("[data-zop]");'
      + ' for (let i = 0; i < nodes.length; i++) {'
      + '   let zop; try { zop = JSON.parse(nodes[i].getAttribute("data-zop")); } catch (e) { continue; }'
      + '   if (!zop.itemId || seen.has(zop.itemId)) continue;'
      + '   seen.add(zop.itemId);'
      + '   if (arr.length >= ' + likeSpec.pool + ') break;'
      + '   const b = nodes[i].querySelector("button[aria-label*=赞同]");'
      + '   arr.push({ itemId: zop.itemId, voteText: b ? b.innerText.trim() : "" });'
      + ' }'
      + ' return arr;'
      + '})()')
    cliLog('CANDIDATE_POOL(' + likeSpec.pool + '): ' + before.length + ' answers collected')
    const n = before.length
    const minC = Math.min(likeSpec.min, n)
    const maxC = Math.min(likeSpec.max, n)
    const count = n === 0 ? 0 : (minC + Math.floor(Math.random() * (maxC - minC + 1)))
    cliLog('RANDOM_LIKE_COUNT: ' + count + ' (min=' + likeSpec.min + ' max=' + likeSpec.max + ' avail=' + n + ')')
    const shuffled = before.slice()
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      const t = shuffled[i]; shuffled[i] = shuffled[j]; shuffled[j] = t
    }
    const picks = shuffled.slice(0, count)
    cliLog('PICKED_ITEMIDS: ' + JSON.stringify(picks.map(function (x) { return x.itemId; })))
    const results = []
    for (let i = 0; i < picks.length; i++) {
      const itemId = picks[i].itemId
      const vt = picks[i].voteText
      if (vt.indexOf('已赞同') >= 0) { results.push({ itemId: itemId, action: 'skip_already_liked' }); cliLog('skip already-liked ' + itemId); continue }
      const clicked = await js('((id) => {'
        + ' const nodes = document.querySelectorAll("[data-zop]");'
        + ' for (let i = 0; i < nodes.length; i++) {'
        + '   let zop; try { zop = JSON.parse(nodes[i].getAttribute("data-zop")); } catch (e) { continue; }'
        + '   if (zop.itemId === id) {'
        + '     const b = nodes[i].querySelector("button[aria-label*=赞同]");'
        + '     if (b) { b.click(); return b.innerText.trim(); }'
        + '   }'
        + ' }'
        + ' return null;'
        + '})(' + JSON.stringify(itemId) + ')')
      results.push({ itemId: itemId, after: clicked })
      cliLog('liked ' + itemId + ' -> ' + clicked)
      if (i < picks.length - 1) { const gap = 35 + Math.floor(Math.random() * 45); await wait(gap) }
    }
    cliLog('LIKE_RESULT: ' + JSON.stringify(results))
  } else {
    cliLog('like disabled for this shift (interactions.like = 0/null)')
  }

  // ---------- 6.0 去 AI 味硬门禁（v1.5.0，默认强制） ----------
  // 与 scripts/humanize_gate.py 配套：凭证绑定正文 sha256，正文改一个字即失效。
  // 不通过 → ANSWER_SKIPPED: HUMANIZE_GATE_FAIL，点赞/互动照常收尾但绝不打开编辑器。
  function checkHumanizeGate(txt) {
    const hg = (cfg.data.publish_gates || {}).humanize || {}
    if (hg.enabled === false) {
      cliLog('WARN: HUMANIZE_GATE_DISABLED — config.publish_gates.humanize.enabled=false（仅限未安装 text-humanize 的机器）')
      return { pass: true, skipped: true }
    }
    const gateFile = hg.gate_file || '/tmp/zhihu_humanize_pass.json'
    const maxHours = Number(hg.max_age_hours || 6)
    let g
    try { g = JSON.parse(fs.readFileSync(gateFile, 'utf8')) }
    catch (e) { return { pass: false, reason: '凭证缺失或损坏 (' + gateFile + '): ' + e.message } }
    let sha
    try { sha = require('crypto').createHash('sha256').update(txt, 'utf8').digest('hex') }
    catch (e) { return { pass: false, reason: 'sha256 计算失败: ' + e.message } }
    if (g.ok !== true) return { pass: false, reason: '凭证 ok != true' }
    if (g.sha256 !== sha) return { pass: false, reason: '正文 sha256 不匹配（正文改过，需重跑 humanize_gate.py）' }
    if (g.contentFile && P.contentFile && path.resolve(g.contentFile) !== path.resolve(P.contentFile)) {
      return { pass: false, reason: 'contentFile 不匹配（检查的是另一份稿）' }
    }
    if (Number(g.fail) !== 0) return { pass: false, reason: 'preflight fail=' + g.fail }
    if (!g.checkedAt || (Date.now() - Number(g.checkedAt) * 1000) > maxHours * 3600 * 1000) {
      return { pass: false, reason: '凭证超过 ' + maxHours + ' 小时有效期，需重跑 humanize_gate.py' }
    }
    return { pass: true, sha: sha, warn: Number(g.warn || 0), tier: g.tier || '?' }
  }

  // ---------- 6. 写回答（answer=true 时） ----------
  let aid = null
  let publishFailed = false
  if (shiftCfg.answer) {
    let content = P.content || ''
    if (P.contentFile) content = fs.readFileSync(P.contentFile, 'utf8')
    if (!content.trim()) {
      cliLog('ANSWER_SKIPPED: no content — do NOT publish empty')
    } else {
      // 字数护栏：超区间一律跳过发布（deep=true 用深度版区间，否则标准区间）
      const isDeep = P.deep === true || P.deep === 'true'
      const style = isDeep ? (cfg.data.deep_answer || {}) : (cfg.data.answer_style || {})
      const minW = style.min_words || (isDeep ? 800 : 250)
      const maxW = style.max_words || (isDeep ? 1200 : 800)
      const charCount = content.length
      const gate = checkHumanizeGate(content)
      if (!gate.pass) {
        cliLog('ANSWER_SKIPPED: HUMANIZE_GATE_FAIL — ' + gate.reason)
        cliLog('HUMANIZE_GATE_HINT: python3 scripts/humanize_gate.py <正文文件> 跑通后再重跑本班（点赞/互动照常收尾；同页禁止重试发布）')
      } else if (charCount < minW || charCount > maxW) {
        cliLog('ANSWER_SKIPPED: WORD_COUNT_EXCEEDED ' + charCount + ' chars, allowed ' + minW + '-' + maxW + (isDeep ? ' (deep)' : ' (standard)') + ' — compress/expand content then rerun')
      } else {
      cliLog('WORD_COUNT_OK: ' + charCount + ' chars (' + minW + '-' + maxW + (isDeep ? ' deep' : ' standard') + ')')
      if (!gate.skipped) cliLog('HUMANIZE_GATE_OK: tier=' + gate.tier + ' fail=0 warn=' + gate.warn + ' sha256=' + gate.sha.slice(0, 12))
      const opened = await js('(() => {'
        + ' const btns = Array.from(document.querySelectorAll("button"));'
        + ' const b = btns.find(function (x) { return x.innerText.indexOf("写回答") >= 0; });'
        + ' if (b) { b.click(); return true; }'
        + ' return false;'
        + '})()')
      cliLog('editor-opened: ' + opened)
      await wait(3)
      await js('((text) => {'
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
      await wait(2)
      cliLog('human-pace pause 60s before publish...')
      await wait(60)
      const pub = await js('(() => {'
        + ' const clean = function (s) { return (s || "").replace(/[\\u200b\\s]+/g, ""); };'
        + ' const btns = Array.from(document.querySelectorAll("button"));'
        + ' const pre = ["发布回答", "提交回答"];'
        + ' const b1 = btns.find(function (x) { return pre.indexOf(clean(x.innerText)) >= 0 && !x.disabled; });'
        + ' if (b1) { b1.click(); return clean(b1.innerText); }'
        + ' if (!document.querySelector(".public-DraftEditor-content")) return false;'
        + ' const b2 = btns.find(function (x) { return clean(x.innerText) === "发布" && !x.disabled; });'
        + ' if (b2) { b2.click(); return "发布"; }'
        + ' return false;'
        + '})()')
      cliLog('publish-clicked: ' + pub)
      if (pub === false) publishFailed = true
      await wait(8)
      const info = await pageInfo()
      cliLog('after-publish-url: ' + info.url)
      const m = info.url.match(/answer\/(\d+)/)
      if (m) {
        aid = m[1]
        cliLog('PUBLISHED aid=' + aid)
      } else {
        publishFailed = true
        cliLog('WARN: url did not jump to /answer/{aid} — possible publish stuck (see risk-control: do NOT retry)')
      }
      }
    }
  } else {
    cliLog('answer disabled for this shift')
  }

  // ---------- 7. 折叠验证（走官方 CLI，serverFetch API 已于 8/26 起恒 403，不再重试） ----------
  if (aid) {
    cliLog('VERIFY_VIA_CLI: zhihu-cli me contents --type answer --limit 3 (or run scripts/verify_via_cli.js with AID=' + aid + ')')
    cliLog('VERIFY_RULE: summary non-empty = NOT collapsed; empty summary = collapsed (index may lag 1-2 min)')
  }

  // ---------- 8. 可选互动：收藏 / 关注问题 / 评论 ----------
  if (interactions.collect) {
    const done = await js('(() => {'
      + ' const btns = Array.from(document.querySelectorAll("button"));'
      + ' const b = btns.find(function (x) { return x.innerText.indexOf("收藏") >= 0; });'
      + ' if (!b) return "no_button";'
      + ' if (b.innerText.indexOf("已收藏") >= 0) return "already";'
      + ' b.click(); return "clicked";'
      + '})()')
    cliLog('COLLECT: ' + done)
    await wait(3)
  }
  if (interactions.follow) {
    const done = await js('(() => {'
      + ' const btns = Array.from(document.querySelectorAll("button"));'
      + ' const hit = function (x) { const t = x.innerText.trim(); return t === "关注" || t === "已关注"; };'
      + ' const b = btns.find(function (x) { return String(x.className || "").indexOf("FollowButton") >= 0; })'
      + '   || btns.find(hit);'
      + ' if (!b) return "no_button";'
      + ' if (b.innerText.trim().indexOf("已关注") >= 0) return "already";'
      + ' b.click(); return "clicked";'
      + '})()')
    cliLog('FOLLOW_QUESTION: ' + done)
    await wait(3)
  }
  if (interactions.comment) {
    const opened = await js('(() => {'
      + ' const btns = Array.from(document.querySelectorAll("button"));'
      + ' const b = btns.find(function (x) { return x.innerText.indexOf("添加评论") >= 0; });'
      + ' if (b) { b.click(); return true; }'
      + ' return false;'
      + '})()')
    cliLog('COMMENT_EDITOR_OPENED: ' + opened)
    if (opened) {
      await wait(3)
      const txt = P.commentText || ''
      if (txt) {
        let filled = 'no_text'
        try {
          await fillInput('.CommentEditor-input, [contenteditable="true"][data-placeholder*="评论"]', txt)
          filled = true
        } catch (e) { filled = 'fill_failed:' + e.message }
        cliLog('COMMENT_FILLED: ' + filled)
        if (filled === true) {
          const sent = await js('(() => {'
            + ' const btns = Array.from(document.querySelectorAll("button"));'
            + ' const b = btns.find(function (x) { return x.innerText.trim() === "发布" || x.innerText.trim() === "发送"; });'
            + ' if (b) { b.click(); return true; }'
            + ' return false;'
            + '})()')
          cliLog('COMMENT_SENT: ' + sent)
          await wait(3)
        }
      } else {
        cliLog('COMMENT_SKIP: no commentText provided')
      }
    }
  }

  if (publishFailed) {
    cliLog('SHIFT_PARTIAL_FAIL: publish — 正文未发布（正文文件已保留，可修正后重跑；同页勿连续重试，等 1–2 小时）')
  }
  cliLog('SHIFT_DONE: ' + SHIFT + ' qid=' + qid + (aid ? ' aid=' + aid : ' aid=NONE'))
  await completeTaskSpace(space, { keep: false })
})()

// 参数文件 schema（/tmp/zhihu_shift_params.json）：
// {
//   "shift": "morning|noon|evening",
//   "qid": "2070982459156424668",          // 可选，跳过自动选题
//   "contentFile": "/abs/answer.txt",       // answer=true 时必填其一
//   "content": "回答正文...",                // 或直接内联
//   "configPath": "/abs/config.json",       // 可选
//   "kw": "历史,神话",                       // 可选，覆盖轮转
//   "limit": 25,                            // 可选
//   "commentText": "评论内容"               // 可选，comment=true 时
// }
