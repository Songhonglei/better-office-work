// 小红书视频笔记
//
// 跟另外两个平台的根本差异：发布按钮是 Web Component，藏在 closed Shadow DOM 里，
// 常规点击全部失效，只能直接调用宿主元素上的 _onPublish() / _onSave()。
//
// 另一处差异：话题必须从下拉里点选词条才生效，直接粘贴 "#话题" 只是纯文本。
// 而视频号是输入即标签化、抖音是输入后回车，三家三种做法。

const CFG = typeof PARAMS !== 'undefined' ? PARAMS : null
if (!CFG) {
  console.error('缺少 PARAMS。请用 release.sh 调用。')
  process.exit(10)
}

const EXIT = {
  OK: 0, PARAM: 10, DEP: 11, SPACE: 12, AUTH: 20, TAB: 21, UPLOAD: 30,
  FORM: 40, TOPIC: 50, COVER: 60, SUBMIT: 70, VERIFY: 80, INTERNAL: 90,
}

const SEL = {
  videoInput: 'input[type="file"][accept*=".mp4"]',
  titleInput: 'input[placeholder="填写标题会有更多赞哦"]',
  editor: 'div.tiptap',
  editorFallback: '[contenteditable="true"]',
  topicContainer: '#creator-editor-topic-container',
  publishHost: 'xhs-publish-btn',
  coverBox: '.cover',
  coverEditEntry: '.cover-edit-entry',
  coverInput: 'input[type="file"][accept*="image/png"]',
  coverModal: '.d-modal.cover-modal',
  coverGuide: '.pk-cover-guide-tooltip, .pk-cover-guide',
}

let TASK = null
let editorSel = SEL.editor
const t0 = Date.now()

function log(msg) { cliLog('[xhs] ' + msg) }
function elapsed() { return ((Date.now() - t0) / 1000).toFixed(1) + 's' }

async function fail(step, code, exitCode, message, detail, whatNow) {
  const lines = ['', '=== FAILED ===']
  lines.push('platform : 小红书')
  lines.push('step     : ' + step)
  lines.push('code     : ' + code)
  lines.push('exit     : ' + exitCode)
  lines.push('message  : ' + message)
  if (detail) lines.push('detail   : ' + JSON.stringify(detail).slice(0, 500))
  lines.push('what_now :')
  ;(whatNow || []).forEach(function (s, i) { lines.push('  ' + (i + 1) + '. ' + s) })
  if (TASK) {
    lines.push('space    : ' + TASK.id + '（页面已保留）')
    lines.push('takeover : ego-browser nodejs -e "await claimTaskSpace(' + TASK.id + ')"')
    lines.push('cleanup  : ego-browser nodejs -e "await completeTaskSpace(' + TASK.id + ', { keep: false })"')
  }
  lines.push('=== END FAILED ===')
  lines.push('')
  // console.error 走 stderr 且进程被杀时缓冲会丢，加 stdout 直写兜底
  try { process.stdout.write(lines.join('\n') + '\n') } catch (e) { /* ignore */ }
  console.error(lines.join('\n'))
  if (TASK && !CFG.keepOnFail) {
    try { await completeTaskSpace(TASK.id, { keep: false }) } catch (e) { /* ignore */ }
  }
  process.exit(exitCode)
}

async function moveCaretToEnd() {
  await js(`(() => {
    const el = document.querySelector('${editorSel}')
    if (!el) return false
    el.focus()
    const r = document.createRange()
    r.selectNodeContents(el)
    r.collapse(false)
    const s = window.getSelection()
    s.removeAllRanges()
    s.addRange(r)
    return true
  })()`)
  await wait(0.3)
}

// 话题：必须从下拉点选，点完 Escape 关掉残留气泡，再补一个空格
async function addTopic(topic) {
  await moveCaretToEnd()
  await cdp('Input.insertText', { text: '#' + topic })

  let found = false
  for (let i = 0; i < 10; i++) {
    await wait(0.8)
    const st = await js(`(() => {
      const c = document.getElementById('creator-editor-topic-container')
      if (!c) return { ok: false }
      const items = [...c.querySelectorAll('.item')]
      return { ok: items.length > 0, count: items.length }
    })()`)
    if (st.ok) { found = true; break }
  }
  if (!found) return { ok: false, reason: 'no_dropdown' }

  const clicked = await js(`((topic) => {
    const c = document.getElementById('creator-editor-topic-container')
    if (!c) return 'NO_CONTAINER'
    const items = [...c.querySelectorAll('.item')]
    if (!items.length) return 'NO_ITEM'
    const exact = items.find(function (el) {
      const n = el.querySelector('.name')
      return n && n.innerText.trim().split(String.fromCharCode(10))[0] === '#' + topic
    })
    const target = exact || items[0]
    const nameEl = target.querySelector('.name')
    ;(nameEl || target).click()
    return (exact ? 'EXACT:' : 'FALLBACK:') + (target.innerText || '').split(String.fromCharCode(10))[0]
  })(${JSON.stringify(topic)})`)

  await wait(1.2)
  const popupOpen = await js(`(() => {
    const t = document.getElementById('tippy-1')
    return !!(t && t.offsetParent)
  })()`)
  if (popupOpen) { await pressKey('Escape'); await wait(0.4) }
  await cdp('Input.insertText', { text: ' ' })
  await wait(0.4)
  return { ok: String(clicked).indexOf('EXACT') === 0 || String(clicked).indexOf('FALLBACK') === 0, clicked: clicked }
}

// 视频封面：hover 缩略图才会渲染出「编辑封面」（平时 boundingRect 是 0×0）
async function setVideoCover(coverPath) {
  await js(`(() => {
    document.querySelectorAll('${SEL.coverGuide}').forEach(function (e) { e.style.display = 'none' })
    return true
  })()`)

  const rect = await js(`(() => {
    const c = document.querySelector('${SEL.coverBox}')
    if (!c) return null
    const r = c.getBoundingClientRect()
    if (r.width < 50) return null
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
  })()`)
  if (!rect) return { ok: false, code: 'E_COVER_AREA_MISSING' }

  const before = await js(`(() => {
    const c = document.querySelector('${SEL.coverBox}')
    return c ? (c.style.backgroundImage || '').slice(0, 120) : ''
  })()`)

  await cdp('Input.dispatchMouseEvent', {
    type: 'mouseMoved', x: rect.x + 65, y: rect.y + Math.round(rect.h / 2), button: 'none',
  })

  let shown = false
  for (let i = 0; i < 8; i++) {
    await wait(0.5)
    const r2 = await js(`(() => {
      const el = document.querySelector('${SEL.coverEditEntry}')
      if (!el) return { ok: false }
      const b = el.getBoundingClientRect()
      return { ok: b.width > 0 && b.height > 0 }
    })()`)
    if (r2.ok) { shown = true; break }
  }
  if (!shown) return { ok: false, code: 'E_COVER_ENTRY_HIDDEN' }

  try {
    await click(SEL.coverEditEntry, { label: 'open cover editor', timeout: 8000 })
  } catch (e) {
    return { ok: false, code: 'E_COVER_EDITOR_NOT_OPEN' }
  }

  let editorReady = false
  for (let i = 0; i < 15; i++) {
    await wait(1)
    if (await js(`!!document.querySelector('${SEL.coverInput}')`)) { editorReady = true; break }
  }
  if (!editorReady) return { ok: false, code: 'E_COVER_EDITOR_NOT_OPEN' }

  await uploadFile(SEL.coverInput, coverPath)
  // 图片要解码后渲进裁剪画布，没有可靠 DOM 信号，给足时间
  await wait(4)

  const doneClicked = await js(`(() => {
    const el = [...document.querySelectorAll('span')].find(function (e) {
      return e.textContent.trim() === '完成' && String(e.className).indexOf('circle-button') >= 0
    })
    if (!el) return false
    el.scrollIntoView({ block: 'center', inline: 'center' })
    el.click()
    return true
  })()`)
  if (!doneClicked) return { ok: false, code: 'E_COVER_DONE_BTN_MISSING' }

  await wait(3)
  const after = await js(`(() => {
    const c = document.querySelector('${SEL.coverBox}')
    return c ? (c.style.backgroundImage || '').slice(0, 120) : ''
  })()`)

  if (before && after && before === after) {
    return { ok: false, code: 'E_COVER_NOT_APPLIED' }
  }
  return { ok: true }
}

// 复用/新建任务空间。上次失败保留的现场归属会回到 user，
// useOrCreateTaskSpace 按设计不会擅自接管，这里给明确出路而不是落到 E_UNEXPECTED。
async function acquireSpace(name) {
  if (CFG.spaceId) {
    const id = Number(CFG.spaceId)
    if (!id) {
      await fail('task-space', 'E_SPACE_ID_INVALID', EXIT.PARAM,
        'SPACE_ID 不是数字: ' + CFG.spaceId, {}, ['传数字，例如 SPACE_ID=65'])
    }
    try {
      TASK = await claimTaskSpace(id)
      log('接管空间 ' + id + '  ' + elapsed())
      return TASK
    } catch (e) {
      await fail('task-space', 'E_SPACE_CLAIM_FAILED', EXIT.SPACE,
        'SPACE_ID=' + id + ' 接管失败：' + e.message, {},
        ['确认这个 id 是否正确、空间是否已被关闭',
         '不确定就不传 SPACE_ID，让脚本新建一个（旧空间需先关掉）'])
    }
  }

  try {
    TASK = await useOrCreateTaskSpace(name)
    log('空间 ' + TASK.id + '  ' + elapsed())
    return TASK
  } catch (e) {
    const m = /id (\d+)/.exec(e.message || '')
    const oldId = m ? m[1] : '<id>'
    await fail('task-space', 'E_SPACE_OWNED', EXIT.SPACE,
      '同名任务空间已存在且归属用户，未擅自接管（通常是上次失败保留的现场）',
      { message: e.message, existingSpace: oldId },
      ['复用那个现场（页面还在、内容也在）：命令前加 SPACE_ID=' + oldId + ' 重跑',
       '丢弃旧现场：ego-browser nodejs -e "await completeTaskSpace(' + oldId + ', { keep: false })"',
       '两个都不做会一直卡在这一步'])
  }
}

async function main() {
  log('开始，模式=' + CFG.mode)

  TASK = await acquireSpace('publish xhs video')

  await openOrReuseTab('https://creator.xiaohongshu.com/publish/publish', { wait: true, timeout: 30 })
  // 复用同名任务空间时会命中上次的 tab，编辑器里还留着上次的正文和封面，
  // 再填一遍正文会翻倍、封面入口变隐藏。无条件重载，换干净页面。
  await cdp('Page.reload', { ignoreCache: false })
  await wait(16)

  const info = await pageInfo()
  if (/login/i.test(info.url)) {
    await fail('auth', 'E_AUTH_EXPIRED', EXIT.AUTH, '小红书未登录', { url: info.url },
      ['让用户在 ego-lite 窗口里扫码登录', '回复 continue 后 claimTaskSpace(' + TASK.id + ') 接管再重跑'])
  }

  // 确保在「上传视频」页：有 mp4 输入框就说明对了
  let hasVideoInput = await js(`!!document.querySelector('${SEL.videoInput}')`)
  if (!hasVideoInput) {
    await js(`(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null)
      let n
      while (n = walker.nextNode()) {
        if ((n.textContent || '').trim() === '上传视频') {
          const el = n.parentElement
          if (el) { el.click(); return true }
        }
      }
      return false
    })()`)
    await wait(4)
    hasVideoInput = await js(`!!document.querySelector('${SEL.videoInput}')`)
  }
  if (!hasVideoInput) {
    await fail('ensure-tab', 'E_VIDEO_TAB_NOT_FOUND', EXIT.TAB, '找不到「上传视频」入口', {},
      ['页面可能改版，接管确认上传页结构', '或手动点「上传视频」后重跑'])
  }

  // 上传
  await uploadFile(SEL.videoInput, CFG.video)
  log('已投递文件 ' + elapsed())

  let uploaded = false
  for (let i = 0; i < 30; i++) {
    await wait(4)
    const st = await js(`(() => {
      const v = document.querySelector('video')
      const t = document.body.innerText || ''
      return { dur: v ? Math.round(v.duration) : 0, hasReupload: t.indexOf('重新上传') >= 0 }
    })()`)
    if (st.dur > 0 && st.hasReupload) { uploaded = true; break }
  }
  if (!uploaded) {
    await fail('upload', 'E_VIDEO_UPLOAD_TIMEOUT', EXIT.UPLOAD, '视频上传/转码超时（120 秒）', {},
      ['检查文件可正常播放、体积是否过大', '重跑一次'])
  }
  log('上传完成 ' + elapsed())

  // 编辑器：先试 div.tiptap，没有就退回通用 contenteditable
  const tiptapExists = await js(`!!document.querySelector('${SEL.editor}')`)
  if (!tiptapExists) {
    editorSel = SEL.editorFallback
    log('⚠ 没找到 div.tiptap，退回通用 contenteditable')
  }

  // 标题（20 字）
  const title = (CFG.title || '').slice(0, 20)
  if (title.length < (CFG.title || '').length) log('⚠ 标题超 20 字，已截断')
  if (title) {
    await fillInput(SEL.titleInput, title)
    await wait(1.2)
    const got = await js(`(() => {
      const el = document.querySelector('${SEL.titleInput}')
      return el ? el.value : null
    })()`)
    if (got !== title) {
      await fail('fill-title', 'E_TITLE_NOT_APPLIED', EXIT.FORM, '标题写入失败',
        { expected: title, got: got }, ['重跑；反复失败则接管手填'])
    }
    log('标题: ' + title)
  }

  // 描述
  if (CFG.desc) {
    const focused = await js(`(() => {
      const el = document.querySelector('${editorSel}')
      if (!el) return false
      el.focus()
      return true
    })()`)
    if (!focused) {
      await fail('fill-desc', 'E_EDITOR_MISSING', EXIT.FORM, '找不到正文编辑器', {},
        ['页面可能改版，接管确认'])
    }
    await cdp('Input.insertText', { text: CFG.desc })
    await wait(1.5)
    const len = await js(`(() => {
      const el = document.querySelector('${editorSel}')
      return el ? (el.innerText || '').length : 0
    })()`)
    if (len < 10) {
      await fail('fill-desc', 'E_BODY_NOT_APPLIED', EXIT.FORM, '正文写入失败', { len: len }, ['重跑'])
    }
    log('正文 ' + len + ' 字')
  }

  // 话题
  const topics = CFG.topics || []
  const failed = []
  if (topics.length) {
    await moveCaretToEnd()
    await cdp('Input.insertText', { text: '\n\n' })
    await wait(0.5)
    for (const topic of topics) {
      let r = await addTopic(topic)
      if (!r.ok) {
        await pressKey('Escape')
        await wait(0.8)
        r = await addTopic(topic)
      }
      if (r.ok) log('话题 ok: ' + r.clicked)
      else failed.push({ topic: topic, reason: r.reason })
    }
  }
  if (failed.length) {
    await fail('add-topics', 'E_TOPIC_NOT_ATTACHED', EXIT.TOPIC,
      failed.length + '/' + topics.length + ' 个话题未挂载', { failed: failed },
      ['话题缺失不影响发布，只是少流量入口',
       '接管手动补打 #话题 并从下拉选中'])
  }
  await pressKey('Escape')
  await wait(0.4)

  // 封面（可选）
  if (CFG.coverVertical) {
    const cv = await setVideoCover(CFG.coverVertical)
    if (!cv.ok) {
      await fail('set-cover', cv.code, EXIT.COVER, '自定义封面设置失败', cv,
        ['重跑一次通常就能成功', '连续失败就先不传封面，用默认第一帧'])
    }
    log('自定义封面已应用')
  }

  if (CFG.mode === 'stage') {
    console.log('\n=== OK (stage) ===')
    console.log('内容已就绪，未提交。')
    console.log('space    : ' + TASK.id)
    console.log('takeover : ego-browser nodejs -e "await claimTaskSpace(' + TASK.id + ')"')
    return
  }

  // 提交：穿透 closed Shadow DOM 直接调宿主方法
  const action = CFG.mode === 'draft' ? '_onSave' : '_onPublish'
  const r = await js(`((mode) => {
    const host = document.querySelector('${SEL.publishHost}')
    if (!host) return { error: 'E_NO_PUBLISH_HOST' }
    if (mode === 'draft') {
      if (typeof host._onSave !== 'function') return { error: 'E_NO_ONSAVE' }
      if (host.getAttribute('save-disabled') === 'true') return { error: 'E_SAVE_DISABLED' }
      host._onSave()
      return { triggered: true }
    }
    if (typeof host._onPublish !== 'function') return { error: 'E_NO_ONPUBLISH' }
    if (host.getAttribute('submit-disabled') === 'true') return { error: 'E_SUBMIT_DISABLED' }
    host._onPublish()
    return { triggered: true }
  })(${JSON.stringify(CFG.mode)})`)

  if (r.error) {
    await fail('submit', r.error, EXIT.SUBMIT, '提交按钮不可用', r,
      ['按钮 disabled 通常是必填项没填完（标题/正文/封面）',
       '接管后看哪个字段标红，修好后可直接在该页手动点发布'])
  }
  log('已触发 ' + action + '() ' + elapsed())
  await wait(6)

  if (CFG.mode === 'draft') {
    const cnt = await js(`(() => {
      const m = (document.body.innerText || '').match(/草稿箱\\((\\d+)\\)/)
      return m ? m[1] : 'n/a'
    })()`)
    console.log('\n=== ' + (cnt === 'n/a' ? 'OK (draft, 未确认)' : 'OK (draft saved)') + ' ===')
    console.log('草稿计数: ' + cnt)
    if (cnt === 'n/a') {
      console.log('提示: 读不到草稿计数，去创作平台右上角「草稿箱」确认')
    }
    console.log('space    : ' + TASK.id)
    return
  }

  let ok = false
  for (let i = 0; i < 12; i++) {
    await wait(2)
    const i2 = await pageInfo()
    if (i2.url.indexOf('published=true') >= 0 || i2.url.indexOf('note-manage') >= 0) { ok = true; break }
  }
  if (!ok) {
    await fail('verify', 'E_PUBLISH_UNCONFIRMED', EXIT.VERIFY, '点了发布但页面没跳转', {},
      ['不要立即重发，先去笔记管理确认是否已发出', '接管看是否有校验提示'])
  }
  console.log('\n=== OK (published) ===')
  console.log('url      : ' + (await pageInfo()).url)
  console.log('space    : ' + TASK.id)
}

// ego-browser 的 stdin 走 node:internal/vm，不支持顶层 await（会报 SyntaxError
// 且被包装成 exit 90、一行输出都没有）。必须用 IIFE 包装，正常完成路径显式退出。
;(async () => {
  try {
    await main()
  } catch (e) {
    await fail('internal', 'E_UNEXPECTED', EXIT.INTERNAL, String((e && e.message) || e),
      { stack: String((e && e.stack) || '').split('\n').slice(0, 3).join(' | ').slice(0, 300) },
      ['未预期异常，通常是页面改版或连接中断', '接管截图确认'])
  }
  process.exit(0)
})()
