// 抖音投稿
//
// 与视频号的关键差异：
// - 普通 DOM，没有微前端，选择器正常可用
// - 话题必须从下拉里选，可靠做法是「输入 #话题名 后按 Enter」（下拉首项即精确匹配）
// - 「暂存离开」不可靠：点完回上传页，内容管理和首页都找不到草稿，等于没存
// - 发布时会触发短信二次验证，这是平台级真人验证，脚本无法越过
//
// 所以默认 MODE=stage：填好一切并停住，最后由用户点发布 + 输验证码。

const CFG = typeof PARAMS !== 'undefined' ? PARAMS : null
if (!CFG) {
  console.error('缺少 PARAMS。请用 release.sh 调用。')
  process.exit(10)
}

const EXIT = {
  OK: 0, PARAM: 10, DEP: 11, SPACE: 12, AUTH: 20, UPLOAD: 30,
  FORM: 40, TOPIC: 50, COVER: 60, SUBMIT: 70, HUMAN: 75, VERIFY: 80, INTERNAL: 90,
}

let TASK = null
const t0 = Date.now()

function log(msg) { cliLog('[douyin] ' + msg) }
function elapsed() { return ((Date.now() - t0) / 1000).toFixed(1) + 's' }

async function fail(step, code, exitCode, message, detail, whatNow) {
  const lines = ['', '=== FAILED ===']
  lines.push('platform : 抖音')
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

const TITLE_SEL = 'input[placeholder="填写作品标题，为作品获得更多流量"]'
const EDITOR_SEL = '.zone-container.editor-kit-container'

// ── 封面（尽力而为）：找 image 文件输入 → 投递 → 点完成；任一步失败返回原因不抛错 ──
async function findImageInputNodeId() {
  const { root } = await cdp('DOM.getDocument', { depth: -1, pierce: true })
  const hits = []
  ;(function walk(n) {
    if (!n) return
    if (n.nodeName === 'INPUT' && n.attributes) {
      const a = {}
      for (let i = 0; i < n.attributes.length; i += 2) a[n.attributes[i]] = n.attributes[i + 1]
      if ((a.type || '').toLowerCase() === 'file') hits.push({ nodeId: n.nodeId, accept: a.accept || '' })
    }
    if (n.shadowRoots) n.shadowRoots.forEach(walk)
    if (n.children) n.children.forEach(walk)
  })(root)
  return hits.find(function (x) { return /image/i.test(x.accept) }) || null
}

async function clickTextAny(texts) {
  const box = await js(`(() => {
    const want = ${JSON.stringify(texts)}
    const cands = [...document.querySelectorAll('button, div, span, a')].filter(function (e) {
      const t = (e.innerText || '').trim()
      return want.indexOf(t) >= 0 && e.getBoundingClientRect().width > 0
    })
    if (!cands.length) return { __err: 'not_found' }
    const el = cands[cands.length - 1]
    el.scrollIntoView({ block: 'center' })
    const r = el.getBoundingClientRect()
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
  })()`)
  if (!box || box.__err) return false
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' })
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  return true
}

async function setDouyinCover(filePath) {
  let imgInput = await findImageInputNodeId()
  if (!imgInput) {
    if (!await clickTextAny(['设置封面', '编辑封面', '更换封面'])) return 'no_cover_entry'
    await wait(2.5)
    if (!await clickTextAny(['上传封面', '上传图片', '本地上传'])) return 'no_upload_entry'
    await wait(2)
    imgInput = await findImageInputNodeId()
  }
  if (!imgInput) return 'no_image_input'
  try {
    await cdp('DOM.setFileInputFiles', { files: [filePath], nodeId: imgInput.nodeId })
  } catch (e) {
    return 'upload_error:' + (e && e.message || '')
  }
  await wait(4)
  if (!await clickTextAny(['完成', '确定', '确认'])) return 'no_confirm_btn'
  await wait(2)
  return 'ok'
}

async function caretToEnd() {
  return js(`(() => {
    const z = document.querySelector('${EDITOR_SEL}')
    if (!z) return { __err: 'no_editor' }
    const inner = z.querySelector('[contenteditable="true"]') || z
    inner.focus()
    const r = document.createRange()
    r.selectNodeContents(inner)
    r.collapse(false)
    const s = window.getSelection()
    s.removeAllRanges()
    s.addRange(r)
    return { ok: true }
  })()`)
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

  TASK = await acquireSpace('publish douyin video')
  // SPACE_ID / resume 复用现场时，绝不 Page.reload：抖音 passport 登录态撑不过刷新，
  // 且刷新会清空已填好的标题/描述/话题。
  const RESUMED = !!(CFG.spaceId || CFG.resume)

  await openOrReuseTab('https://creator.douyin.com/creator-micro/content/upload', { wait: true, timeout: 35 })
  if (!RESUMED) {
    await cdp('Page.reload', { ignoreCache: false })
    await wait(12)
  } else {
    log('复用现场：跳过 Page.reload')
    await wait(2)
  }

  const info = await pageInfo()
  if (/login|passport/i.test(info.url)) {
    await fail('auth', 'E_AUTH_EXPIRED', EXIT.AUTH, '抖音未登录', { url: info.url },
      ['让用户在 ego-lite 窗口里扫码登录抖音',
       '登录是用户操作，会触发 task space 接管',
       '用户回复 continue 后 claimTaskSpace(' + TASK.id + ') 接管再重跑'])
  }

  // 上传。复用现场时若已在编辑页，跳过投递，避免重复上传撞 E_UPLOAD_TIMEOUT。
  let skipFill = false
  if (RESUMED) {
    const inEditor = await js(`!!document.querySelector('${TITLE_SEL}')`)
    if (inEditor) {
      skipFill = true
      log('复用现场：编辑页内容已在，跳过上传与重复填表')
      await wait(2)
    }
  }

  if (!skipFill) {
    const hasInput = await js(`!!document.querySelector('input[type="file"]')`)
    if (!hasInput) {
      await fail('upload', 'E_NO_FILE_INPUT', EXIT.DEP, '上传页没有文件输入', {},
        ['接管确认页面是否停在投稿页', '若已登录仍无输入框，可能改版，需更新选择器'])
    }
    await uploadFile('input[type="file"]', CFG.video)
    log('已投递文件 ' + elapsed())

    let editorReady = false
    for (let i = 0; i < 20; i++) {
      await wait(5)
      if (await js(`!!document.querySelector('${TITLE_SEL}')`)) { editorReady = true; break }
    }
    if (!editorReady) {
      await fail('upload', 'E_EDITOR_TIMEOUT', EXIT.UPLOAD, '上传后没进编辑页（100 秒）', {},
        ['检查视频格式与体积', '重跑一次'])
    }
    await wait(5)
    log('进入编辑页 ' + elapsed())
  }

  // ── 编辑页出现 ≠ 上传完成（2026-11-09 实测） ──────────────────
  // 78MB 原件时编辑页 24 秒就渲染出来，但页面仍显示「已上传 15MB/23MB」。
  // 此时点发布会跳到 content/manage?enter_from=publish，看着像成功，
  // 实际作品数纹丝不动。必须等到「取消上传 / 已上传 xx MB」全部消失。
  // 判据按 2026-11-09 实测成功的脚本对齐：页面里「上传中/正在上传/取消上传/xx%」
  // 全部消失即完成。旧版要求同时出现「重新上传」且 busy 只认「已上传：」（带冒号），
  // 而真实文案是「已上传 15MB/23MB」（空格、无冒号），会永久等不到信号。
  let uploadDone = false
  for (let i = 0; i < 40; i++) {
    const st = await js(`(() => {
      const b = document.body.innerText || ''
      const busy = /上传中|正在上传|取消上传|\\d+%/.test(b)
      const failed = /上传失败|上传出错|上传异常/.test(b)
      const m = b.match(/[^\\n]{0,12}(上传|转码)[^\\n]{0,12}/g)
      return { busy: busy, failed: failed, progress: m ? m.slice(0, 3).join(' | ') : null }
    })()`)
    if (st.failed) {
      await fail('upload', 'E_UPLOAD_FAILED', EXIT.UPLOAD,
        '页面报上传失败，不要继续点发布', { progress: st.progress },
        ['检查视频格式与体积', '压到 25MB 以内再重跑'])
    }
    // 至少轮询 4 轮：刚投递完页面可能还没渲染出「上传中」，第一轮就判完成会重现假成功。
    if (!st.busy && i >= 3) {
      uploadDone = true
      log('上传提示已消失，判定上传完成 ' + elapsed())
      break
    }
    if (i % 5 === 0) log('等待上传完成… ' + (st.progress || '页面中'))
    await wait(3)
  }
  if (!uploadDone) {
    await fail('upload', 'E_UPLOAD_NOT_FINISHED', EXIT.UPLOAD,
      '等不到上传完成信号，此时点发布会「假成功」', {},
      ['不要点发布；确认页面里已无「已上传 xx/xx MB」「取消上传」',
       '视频过大先压到 25MB 以内再重跑（视频号也一样）'])
  }

  // 标题（30 字上限）
  const title = (CFG.title || '').slice(0, 30)
  if (title.length < (CFG.title || '').length) log('⚠ 标题超 30 字，已截断')
  if (title && !skipFill) {
    await fillInput(TITLE_SEL, title)
    await wait(1.2)
    const got = await js(`(() => {
      const el = document.querySelector('${TITLE_SEL}')
      return el ? el.value : null
    })()`)
    if (got !== title) {
      await fail('fill-title', 'E_TITLE_NOT_APPLIED', EXIT.FORM, '标题写入不一致',
        { expected: title, got: got }, ['重跑；反复失败则接管手填'])
    }
    log('标题: ' + title)
  }

  // 描述
  if (CFG.desc && !skipFill) {
    const f = await js(`(() => {
      const z = document.querySelector('${EDITOR_SEL}')
      if (!z) return false
      z.click()
      const inner = z.querySelector('[contenteditable="true"]') || z
      inner.focus()
      return true
    })()`)
    if (!f) {
      await fail('fill-desc', 'E_EDITOR_MISSING', EXIT.FORM, '找不到作品描述编辑器', {},
        ['页面可能改版，接管确认'])
    }
    await cdp('Input.insertText', { text: CFG.desc })
    await wait(1.5)
    const len = await js(`(() => {
      const z = document.querySelector('${EDITOR_SEL}')
      return z ? (z.innerText || '').length : 0
    })()`)
    if (len < 10) {
      await fail('fill-desc', 'E_DESC_NOT_APPLIED', EXIT.FORM, '描述写入失败', { len: len }, ['重跑'])
    }
    log('描述 ' + len + ' 字')
  }

  // 话题：输入 #话题 后按 Enter，下拉首项即精确匹配
  // 用 el.click() 或 CDP 点坐标都会选错（沙箱/坐标偏移），Enter 是唯一可靠方式
  const topics = CFG.topics || []
  const added = []
  const getTags = async () => await js(`(() => [...document.querySelectorAll('span[style*="rgba(1, 118, 247"]')].map(function (e) { return e.innerText }))()`)
  // 复用现场时只核对已挂标签，绝不往描述末尾再插一次（会追加纯文本/换行）
  if (skipFill) {
    const have = (await getTags()) || []
    for (const t of topics) { if (have.indexOf('#' + t) >= 0) added.push(t) }
  }
  for (const topic of (skipFill ? [] : topics)) {
    // 幂等：复用现场时已挂上的话题直接跳过，避免重复插入纯文本
    const before = await getTags()
    if (before && before.indexOf('#' + topic) >= 0) { added.push(topic); continue }
    await caretToEnd()
    await wait(0.4)
    await cdp('Input.insertText', { text: ' #' + topic })
    await wait(3)
    await pressKey('Enter')
    await wait(1.3)
    const after = await getTags()
    if (after && after.indexOf('#' + topic) >= 0) added.push(topic)
  }
  const missing = topics.filter(function (t) { return added.indexOf(t) < 0 })
  log('话题 ' + added.length + '/' + topics.length + (added.length ? ': ' + added.join(' ') : ''))
  if (missing.length) {
    // 话题挂不上只少一个流量入口，不该让整条发布失败。
    // 实测「课本没教的事」在抖音下拉里没有精确匹配，Enter 后只留纯文本。
    // 注意别用退格去清它：编辑器里标签是整体一个单元，退格会连已挂标签一起删。
    log('⚠ 未挂上的话题（降级继续发布）: ' + missing.join(' '))
    console.log('topics_missing: ' + missing.join(' '))
  }

  // 封面：抖音封面编辑器是图层式，这里做「尽力而为」的上传尝试，
  // 任一步失败只告警不阻断（人工可补），成功与否都会打印结果。
  if (CFG.coverVertical) {
    const r = await setDouyinCover(CFG.coverVertical)
    log('封面: ' + r + (r === 'ok' ? '' : '（未生效，发布前可人工设置）'))
  } else if (CFG.coverHorizontal) {
    log('⚠ 抖音只用竖版封面（3:4），已忽略 coverHorizontal')
  }

  if (CFG.mode === 'stage' || CFG.mode === 'draft') {
    // release.sh 承诺「draft 在抖音退化为 stage」。旧实现没这个分支，
    // 会一路走到底真的点「发布」——草稿模式发出正片是最危险的静默行为。
    if (CFG.mode === 'draft') {
      log('⚠ 抖音没有可靠的草稿箱接口，MODE=draft 按 stage 处理，未提交')
    }
    console.log('\n=== OK (stage) ===')
    console.log('内容已就绪，未提交。')
    console.log('space    : ' + TASK.id)
    console.log('takeover : ego-browser nodejs -e "await claimTaskSpace(' + TASK.id + ')"')
    console.log('')
    console.log('下一步由人完成：')
    console.log('  1. 滚到页面底部点「发布」')
    console.log('  2. 会弹出短信验证码，输入手机收到的 6 位数字')
    console.log('  3. 点「验证」完成发布')
    console.log('  ⚠ 不要刷新页面，抖音一刷新内容就清空')
    return
  }

  // mode=publish：尝试点发布，遇到验证就交给用户
  await js(`(() => { window.scrollTo(0, document.body.scrollHeight); return true })()`)
  await wait(1.5)
  const box = await js(`(() => {
    const btn = [...document.querySelectorAll('button')].find(function (b) {
      return (b.innerText || '').trim() === '发布' && b.getBoundingClientRect().width > 0
    })
    if (!btn) return null
    const r = btn.getBoundingClientRect()
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
  })()`)
  if (!box) {
    await fail('submit', 'E_NO_PUBLISH_BTN', EXIT.SUBMIT, '找不到发布按钮', {},
      ['接管滚到底部确认'])
  }
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' })
  await wait(0.2)
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  await wait(6)

  const verify = await js(`(() => {
    const m = document.querySelector('.second-verify-mask')
    return { needVerify: !!m && m.offsetParent !== null, text: m ? (m.innerText || '').slice(0, 100) : null }
  })()`)

  if (verify.needVerify) {
    await fail('submit', 'E_HUMAN_VERIFY_REQUIRED', EXIT.HUMAN,
      '抖音要求短信二次验证，脚本无法越过', { dialog: verify.text },
      ['让用户在 ego-lite 窗口里输入手机收到的验证码并点「验证」',
       '这是平台级真人验证，任何自动化都绕不过',
       '验证完成后在作品列表确认是否发出'])
  }

  const info2 = await pageInfo()
  if (info2.url.indexOf('post/video') >= 0) {
    await fail('verify', 'E_PUBLISH_UNCONFIRMED', EXIT.VERIFY,
      '点了发布但页面没跳转，也没看到验证弹窗', {},
      ['不要立即重发，先去作品列表确认',
       '接管截图看是否有其他校验提示（封面检测、必填项）'])
  }

  // ── 发布后核验：URL 跳到 manage 页 ≠ 真的发出去 ──────────────
  // 实测会跳到 content/manage?enter_from=publish，但作品数纹丝不动。
  // 必须回列表确认标题出现（列表有延迟，最多轮询 16 秒）。
  const want = (CFG.title || '').slice(0, 12)
  let confirmed = false
  let count = null
  for (let i = 0; i < 8; i++) {
    await wait(2)
    const r = await js(`(() => {
      const b = document.body.innerText || ''
      const m = b.match(/作品[^0-9]{0,4}[(]([0-9]+)[)]/)
      return { has: b.indexOf(${JSON.stringify(want)}) >= 0,
               count: m ? Number(m[1]) : null, url: location.href }
    })()`)
    count = r.count
    if (r.has) {
      confirmed = true
      log('作品列表已出现《' + want + '》，作品数 ' + r.count)
      break
    }
  }
  if (!confirmed) {
    await fail('verify', 'E_PUBLISH_UNCONFIRMED', EXIT.VERIFY,
      '页面已跳转但作品列表里没找到新作品（多半是上传没完成就点了发布）',
      { workCount: count },
      ['不要立即重发，先刷新作品列表确认',
       '若确实没发出，用 25MB 以内的压缩版重跑',
       '现场已保留，可接管继续补'])
  }

  console.log('\n=== OK (published) ===')
  console.log('url      : ' + info2.url)
  console.log('work_count: ' + count)
  console.log('space    : ' + TASK.id)
  if (missing.length) console.log('topics_missing: ' + missing.join(' '))
  return
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
