// 视频号发表 —— 无界微前端（wujie）版本
//
// 三个跟普通站点不同的地方，全都在这里处理：
// 1. 整个页面在 wujie-app 的 shadowRoot 里，document.querySelector 全部失效
// 2. JS 的 el.click() 在沙箱里不触发事件，必须用 CDP 真实鼠标
// 3. 上传文件要 CDP 穿透 shadow 拿 nodeId，uploadFile() 选择器失效
//
// 参数从 /tmp/video_release_params.json 读（ego-browser 不继承 shell 环境变量）

// 参数由 release.sh 前置拼进来（const PARAMS = {...}），
// ego-browser 的 nodejs 环境不继承 shell 环境变量，也不允许 fetch file://
const CFG = typeof PARAMS !== 'undefined' ? PARAMS : null
if (!CFG) {
  console.error('缺少 PARAMS。请用 release.sh 调用，不要直接执行本文件。')
  process.exit(10)
}

const EXIT = {
  OK: 0, PARAM: 10, DEP: 11, SPACE: 12, AUTH: 20, TAB: 21, UPLOAD: 30,
  FORM: 40, TOPIC: 50, COVER: 60, SUBMIT: 70, VERIFY: 80, INTERNAL: 90,
}

let TASK = null
const t0 = Date.now()

function log(msg) {
  cliLog('[channels] ' + msg)
}

function elapsed() {
  return ((Date.now() - t0) / 1000).toFixed(1) + 's'
}

async function fail(step, code, exitCode, message, detail, whatNow) {
  const lines = []
  lines.push('')
  lines.push('=== FAILED ===')
  lines.push('platform : 视频号')
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

// 复用/新建任务空间。
// 上次 KEEP_ON_FAIL 留下的现场归属会回到 user，此时 useOrCreateTaskSpace 按设计
// 拒绝擅自接管，直接抛异常。不捕获就会落到 E_UNEXPECTED，用户看不到出路。
async function acquireSpace(name) {
  if (CFG.spaceId) {
    const id = Number(CFG.spaceId)
    if (!id) {
      await fail('task-space', 'E_SPACE_ID_INVALID', EXIT.PARAM,
        'SPACE_ID 不是数字: ' + CFG.spaceId, {},
        ['传数字，例如 SPACE_ID=65'])
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

// ---------- shadow 辅助 ----------

async function shadow(fnBody) {
  return js(`(() => {
    const w = document.querySelector('wujie-app')
    if (!w || !w.shadowRoot) return { __err: 'no_shadow' }
    const sr = w.shadowRoot
    ${fnBody}
  })()`)
}

async function findFileInputNodeId() {
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
  return hits
}

// ── 封面上传（2026-11-07 实测流程），失败只告警不阻断发布 ──
// 视频号只有一个 3:4 封面（个人主页 + 分享卡片共用），实测顺序：
//   点「编辑」开面板 → 点「上传封面」(DIV) → 投递 image 文件 → 点「确认」(BUTTON)
// 注意：确认按钮文字是「确认」不是「确定」；上传封面是 DIV 不是 button；
//      未点「编辑」前「上传封面」不可见。
async function clickBox(box) {
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' })
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 })
}

async function findTextBox(texts, within) {
  const scope = within || 'sr'
  const pick = `
    const scope = ${scope}
    const want = ${JSON.stringify(texts)}
    const els = [...scope.querySelectorAll('*')].filter(function (e) {
      const t = (e.innerText || '').trim()
      return want.indexOf(t) >= 0 && e.children.length === 0 && e.getBoundingClientRect().width > 0
    })
    if (!els.length) return { __err: 'not_found' }
    const el = els[els.length - 1]
  `
  const rolled = await shadow(pick + `el.scrollIntoView({ block: 'center', behavior: 'instant' }); return { ok: true }`)
  if (!rolled || rolled.__err) return rolled
  await wait(1.2)
  return shadow(pick + `
    const r = el.getBoundingClientRect()
    return {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      inView: r.top >= 0 && r.bottom <= window.innerHeight,
    }
  `)
}

async function setCover(filePath) {
  if (!filePath) return 'skip'

  // 1) 点「编辑」打开封面面板
  const editBox = await findTextBox(['编辑'])
  if (!editBox || editBox.__err) { log('⚠ 找不到封面「编辑」按钮，保留自动封面'); return 'no_edit_btn' }
  await clickBox(editBox)
  await wait(2)

  // 2) 点「上传封面」（DIV）—— 复用 findTextBox 的「滚动→等待→重取坐标」
  const upBox = await findTextBox(['上传封面'], `(sr.querySelector('.cover-set-wrap') || sr)`)
  if (!upBox || upBox.__err) { log('⚠ 封面面板里没有「上传封面」'); return 'no_upload_btn' }
  await clickBox(upBox)
  await wait(2)

  // 3) 投递到 accept 含 image 的 file input（视频的 input 是 video/*，别投错）
  const inputs = await findFileInputNodeId()
  const imgInput = inputs.find(function (x) { return /image/i.test(x.accept) })
  if (!imgInput) { log('⚠ 找不到封面的图片输入框，保留自动封面'); return 'no_image_input' }
  try {
    await cdp('DOM.setFileInputFiles', { files: [filePath], nodeId: imgInput.nodeId })
  } catch (e) {
    log('⚠ 封面投递失败: ' + (e && e.message))
    return 'upload_error'
  }
  log('封面已投递: ' + filePath.split('/').pop())
  await wait(4)

  // 4) 点「确认」—— 同样要先滚动、等稳定、再取坐标（smooth scroll 会返回旧位置）
  const okRolled = await shadow(`
    const btns = [...sr.querySelectorAll('button')].filter(function (b) {
      const t = (b.innerText || '').trim()
      return (t === '确认' || t === '确定') && b.getBoundingClientRect().width > 0
    })
    if (!btns.length) return { __err: 'no_confirm' }
    btns[0].scrollIntoView({ block: 'center', behavior: 'instant' })
    return { ok: true }
  `)
  if (!okRolled || okRolled.__err) { log('⚠ 封面面板没有「确认」按钮'); return 'no_confirm' }
  await wait(1.2)
  const okBox = await shadow(`
    const btns = [...sr.querySelectorAll('button')].filter(function (b) {
      const t = (b.innerText || '').trim()
      return (t === '确认' || t === '确定') && b.getBoundingClientRect().width > 0
    })
    if (!btns.length) return { __err: 'no_confirm' }
    const r = btns[0].getBoundingClientRect()
    return {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      inView: r.top >= 0 && r.bottom <= window.innerHeight,
    }
  `)
  if (!okBox || okBox.__err) { log('⚠ 封面面板没有「确认」按钮'); return 'no_confirm' }
  if (!okBox.inView) { log('⚠ 封面「确认」按钮在视口外，跳过自定义封面'); return 'out_of_view' }
  await clickBox(okBox)
  await wait(3)
  log('封面设置完成')
  return 'ok'
}

async function caretToEnd() {
  return shadow(`
    const el = sr.querySelector('.post-desc-box .input-editor')
    if (!el) return { __err: 'no_editor' }
    el.focus()
    const r = document.createRange()
    r.selectNodeContents(el)
    r.collapse(false)
    const s = window.getSelection()
    s.removeAllRanges()
    s.addRange(r)
    return { ok: true }
  `)
}

// 只取坐标，不滚动。inView 交给调用方判断，避免把点打在视口外。
async function boxByText(text) {
  return shadow(`
    const btn = [...sr.querySelectorAll('button')].find(function (b) {
      return (b.innerText || '').trim() === ${JSON.stringify(text)}
    })
    if (!btn) return { __err: 'no_button' }
    const r = btn.getBoundingClientRect()
    return {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      disabled: !!btn.disabled,
      inView: r.top >= 0 && r.bottom <= window.innerHeight && r.width > 0,
      top: Math.round(r.top),
      vh: window.innerHeight,
    }
  `)
}

async function scrollByText(text) {
  return shadow(`
    const btn = [...sr.querySelectorAll('button')].find(function (b) {
      return (b.innerText || '').trim() === ${JSON.stringify(text)}
    })
    if (!btn) return { __err: 'no_button' }
    btn.scrollIntoView({ block: 'center', behavior: 'instant' })
    return { ok: true }
  `)
}

async function clickByText(text) {
  // wujie 沙箱里 el.click() 无效，必须 CDP 真实鼠标。
  // 关键坑：scrollIntoView 之后不能立刻 getBoundingClientRect —— 页面带
  // scroll-behavior:smooth 时拿到的是滚动「前」的位置。曾把「发表」算成 y=1268，
  // 而视口只有 756 高，点全打在屏幕外，表现就是「点了没反应 / 页面没跳转」。
  // 流程必须是：滚动 → 等滚动稳定 → 重新取坐标 → 校验在视口内 → 再点。
  const r0 = await scrollByText(text)
  if (!r0 || r0.__err) return (r0 && r0.__err) || 'no_button'
  await wait(1.2)

  let box = await boxByText(text)
  if (!box || box.__err) return (box && box.__err) || 'no_button'
  if (!box.inView) {
    await scrollByText(text)
    await wait(1.2)
    box = await boxByText(text)
    if (!box || box.__err) return (box && box.__err) || 'no_button'
    if (!box.inView) return 'out_of_view(top=' + box.top + ',vh=' + box.vh + ')'
  }
  if (box.disabled) return 'disabled'

  await clickBox(box)
  return 'clicked'
}

// ---------- 主流程 ----------

async function main() {
  log('开始，模式=' + CFG.mode)

  TASK = await acquireSpace('publish channels video')

  await openOrReuseTab('https://channels.weixin.qq.com/platform/post/create', { wait: true, timeout: 30 })
  // 复用同名任务空间时，openOrReuseTab 会命中上一次留下的 tab 而不再加载，
  // 页面里还留着上次的视频和文案 —— 再投一次文件会卡在 0%（E_UPLOAD_TIMEOUT）。
  // 无条件重载一次，用几秒换一个干净页面。
  await cdp('Page.reload', { ignoreCache: false })
  await wait(14)

  // 先判登录态再查 wujie。登录页本身没有 wujie-app，顺序反了会把「未登录」
  // 误报成「依赖缺失」（E_WUJIE_MISSING / exit 11），what_now 也会指向查网络而非扫码。
  const info = await pageInfo()
  if (/login/i.test(info.url)) {
    await fail('auth', 'E_AUTH_EXPIRED', EXIT.AUTH,
      '视频号未登录（页面被重定向到登录页）', { url: info.url },
      ['让用户在 ego 窗口里用微信扫码登录（二维码在右侧 iframe 里，强刷后约需 9 秒才生成，别急着判定失效）',
       '登录是用户手动操作，会触发 task space 接管，属正常',
       '用户回复 continue 后重跑；若旧空间仍占着，用 SPACE_ID=' + (TASK ? TASK.id : '<id>') + ' 复用'])
  }

  const ready = await shadow(`
    return { url: location.href, hasWujie: true }
  `)
  if (!ready || ready.__err) {
    await fail('open-page', 'E_WUJIE_MISSING', EXIT.DEP,
      '已不在登录页，但仍没有加载出 wujie-app（页面未渲染完或被拦截）',
      { url: info.url },
      ['再等一会儿重跑（Vue 微前端首屏有时较慢）',
       '让用户手动在窗口里确认页面渲染完成',
       '确认本机能正常打开 channels.weixin.qq.com'])
  }

  // 上传视频
  const fileInputs = await findFileInputNodeId()
  const videoInput = fileInputs.find(function (x) { return !/image/i.test(x.accept) }) || fileInputs[0]
  if (!videoInput) {
    await fail('upload', 'E_NO_FILE_INPUT', EXIT.DEP,
      '找不到文件输入节点', {},
      ['页面结构可能变了，接管截图确认上传区是否正常',
       '若页面还停在登录页，先处理登录'])
  }
  await cdp('DOM.setFileInputFiles', { files: [CFG.video], nodeId: videoInput.nodeId })
  log('已投递文件 ' + elapsed())

  // 等上传完成。别拿 video.duration 当判据：浏览器解码本地文件就能拿到时长，
  // 视频还在传（实测卡在 14% / 90%）时它已经 >0，会误判成「上传完成 18.5s」。
  // 唯一可靠的信号是「发表」按钮出现且未禁用 —— 上传中它是灰的或压根不渲染。
  // 也别用 sr.textContent 搜「上传中」：它会把 <style> 里的 CSS 一起读进来，
  // CSS 里有 0%/100%/uploading 之类字样，正则永远命中，判据直接失效（实测误伤 240s）。
  // 只取真实文本节点，且只认「上传失败 / 重新上传」这种明确的错误文案。
  let uploaded = false
  let lastState = ''
  for (let i = 0; i < 60; i++) {
    await wait(4)
    const st = await shadow(`
      const v = sr.querySelector('video')
      const btn = [...sr.querySelectorAll('button')].find(function (b) {
        return (b.innerText || '').trim() === '发表'
      })
      let txt = ''
      const walker = document.createTreeWalker(sr, NodeFilter.SHOW_TEXT)
      let n
      while ((n = walker.nextNode())) {
        const p = n.parentElement
        if (p && /^(SCRIPT|STYLE)$/.test(p.tagName)) continue
        txt += n.nodeValue
      }
      return {
        dur: v ? Math.round(v.duration) : 0,
        cover: txt.indexOf('封面预览') >= 0,
        btnReady: !!(btn && !btn.disabled),
        failed: /上传失败/.test(txt),
      }
    `)
    lastState = JSON.stringify(st)
    // 判据只认「发表按钮可用 + 拿到时长」。不看「重新上传」——那是传完之后的正常按钮，
    // 拿它当错误标记会永远判失败（实测白等 240 秒）。failed 只留作排障信息。
    if (st.btnReady && st.dur > 0) { uploaded = true; break }
  }
  if (!uploaded) {
    await fail('upload', 'E_UPLOAD_TIMEOUT', EXIT.UPLOAD,
      '视频上传超时（240 秒）', { last: lastState },
      ['检查文件是否可正常播放、体积是否过大',
       '重跑一次；若反复卡在 0%，刷新页面后重新上传',
       '注意：删除已上传视频再重传可能卡在 0%，此时只能刷新重来',
       '实测 54MB / 103 秒的成片偶发卡在 14% 或 90%，属上传通道抖动，重试通常就过'])
  }
  log('上传完成 ' + elapsed())

  // 封面（可选）：视频号只有一个 3:4 封面（个人主页+分享卡片共用）。
  // 传了 coverVertical 就换成自定义图；只有 coverHorizontal 时提示不支持。
  if (CFG.coverVertical) {
    const cv = await setCover(CFG.coverVertical)
    log('封面结果: ' + cv)
  } else if (CFG.coverHorizontal) {
    log('⚠ 视频号只支持 3:4 单封面（个人主页+分享卡片共用），已忽略 coverHorizontal')
  }

  // 描述
  const desc = CFG.desc || ''
  if (desc) {
    const f = await shadow(`
      const el = sr.querySelector('.post-desc-box .input-editor')
      if (!el) return { __err: 'no_editor' }
      el.focus()
      return { ok: true }
    `)
    if (f && f.__err) {
      await fail('fill-desc', 'E_EDITOR_MISSING', EXIT.FORM,
        '找不到描述编辑器', {}, ['接管看页面是否还停在发布页'])
    }
    await cdp('Input.insertText', { text: desc })
    await wait(1.2)
    const chk = await shadow(`
      const el = sr.querySelector('.post-desc-box .input-editor')
      return { len: el ? (el.innerText || '').length : 0 }
    `)
    if (chk.len < 10) {
      await fail('fill-desc', 'E_DESC_NOT_APPLIED', EXIT.FORM,
        '描述写入失败', chk, ['重跑；若仍失败，接管后手动确认编辑器状态'])
    }
    log('描述 ' + chk.len + ' 字')
  }

  // 短标题（16 字上限）
  if (CFG.title) {
    // 短标题字符白名单：符号仅支持书名号/引号/冒号/加号/问号/百分号/摄氏度，
    // 逗号非法（会导致发表/保存草稿/手机预览整行按钮静默禁用），统一换空格
    const title = CFG.title.replace(/[，,]/g, ' ').slice(0, 16)
    if (title.length < CFG.title.length) {
      log('⚠ 短标题超 16 字，已截断为: ' + title)
    }
    const ff = await shadow(`
      const t = [...sr.querySelectorAll('input')].find(function (i) {
        return (i.placeholder || '').indexOf('短标题') >= 0
      })
      if (!t) return { __err: 'no_short_title' }
      t.focus()
      return { ok: true }
    `)
    if (ff && ff.__err) {
      await fail('fill-title', 'E_SHORT_TITLE_MISSING', EXIT.FORM,
        '找不到短标题输入框', {}, ['短标题只在描述超过 16 字后出现，确认描述已填写'])
    }
    await cdp('Input.insertText', { text: title })
    await wait(1)
    log('短标题: ' + title)
  }

  // 话题：视频号不需要选词条，输入 #话题名 自动变成 span.topic
  const topics = CFG.topics || []
  const added = []
  for (const topic of topics) {
    await caretToEnd()
    await wait(0.4)
    await cdp('Input.insertText', { text: ' #' + topic })
    await wait(2.2)
    const st = await shadow(`
      const el = sr.querySelector('.post-desc-box .input-editor')
      const tags = el ? [...el.querySelectorAll('span.topic')].map(function (x) { return x.innerText }) : []
      return { tags: tags }
    `)
    if (st.tags && st.tags.indexOf('#' + topic) >= 0) added.push(topic)
  }
  log('话题 ' + added.length + '/' + topics.length + (added.length ? ': ' + added.join(' ') : ''))

  if (topics.length && added.length < topics.length) {
    // 话题缺失只少曝光，不该让整条已填好的内容发不出去（与 douyin/xhs 一致）
    const missing = topics.filter(function (t) { return added.indexOf(t) < 0 })
    log('⚠ 未挂上的话题（降级继续发布）: ' + missing.join(' '))
    console.log('topics_missing: ' + missing.join(' '))
  }

  // 收尾
  if (CFG.mode === 'stage') {
    log('stage 模式：内容已就绪，不做提交')
    console.log('\n=== OK (stage) ===')
    console.log('space    : ' + TASK.id + '（页面已保留，可手动检查后发表）')
    console.log('takeover : ego-browser nodejs -e "await claimTaskSpace(' + TASK.id + ')"')
    return
  }

  const target = CFG.mode === 'draft' ? '保存草稿' : '发表'
  const clickResult = await clickByText(target)
  if (clickResult !== 'clicked') {
    await fail('submit', 'E_SUBMIT_BUTTON', EXIT.SUBMIT,
      '点不到「' + target + '」按钮: ' + clickResult, {},
      ['接管看页面底部是否有"文件上传中"提示（说明上传没真的完成）',
       '确认按钮是否被禁用（短标题含逗号等非法字符会整行静默禁用）',
       'out_of_view 表示按钮始终在视口外，通常是页面高度变了，重跑一次会自动重新定位'])
  }
  await wait(6)

  if (CFG.mode === 'publish') {
    // 发表成功会跳到作品列表页
    const waitLeaveCreate = async () => {
      for (let i = 0; i < 15; i++) {
        const p = await pageInfo()
        if (p.url.indexOf('post/create') < 0) return true
        await wait(3)
      }
      return false
    }
    let ok = await waitLeaveCreate()
    if (!ok) {
      // 不再「兜底再点一次」：第一下其实已提交、只是 wujie 的 history 更新滞后时，
      // 第二下会造成同一条内容双发，代价远大于重试失败。交给列表核验判断。
      log('⚠ 45 秒内没跳转，不重复点发表；先去作品列表确认是否已发出')
    }
    if (!ok) {
      await fail('verify', 'E_PUBLISH_UNCONFIRMED', EXIT.VERIFY,
        '点了发表但页面 45 秒内没跳转（可能是已提交但路由更新滞后）', {},
        ['不要重跑发布脚本，先去作品列表 /platform/post/list 确认是否已发出',
         '列表里已有就直接当成功，别重复发',
         '接管截图看是否有校验提示（封面 / 原创声明 / 内容检测）'])
    }
    const info3 = await pageInfo()

    // ── 发布后核验：回到作品列表确认，别只信 URL 跳转 ──
    // 视频号列表在 wujie 的 shadowRoot 里；列表渲染有时较慢，且不一定显示短标题，
    // 所以查不到只告警、不判失败，交给人工确认（抖音那边则会严格判失败）。
    const want = (CFG.title || '').slice(0, 10)
    let verified = false
    for (let i = 0; i < 8; i++) {
      await wait(2)
      const r = await shadow('return { has: (sr.textContent || "").indexOf(' +
                             JSON.stringify(want) + ') >= 0 }')
      if (r && r.has) { verified = true; break }
    }
    if (verified) log('作品列表已确认《' + want + '》')
    else {
      log('⚠ 作品列表暂未检索到《' + want + '》，列表可能还没刷新，请人工确认')
      console.log('verify_warning: 作品列表未检索到标题，需人工确认')
    }

    console.log('\n=== OK (published) ===')
    console.log('url      : ' + info3.url)
    console.log('verified : ' + (verified ? 'yes' : 'manual'))
    console.log('space    : ' + TASK.id)
    return
  }

  // draft：确认出现"已保存"。toast 有 1-3 秒延迟，点完立刻查必然查不到
  // （实测会误报 unconfirmed），改成轮询 8 秒。
  let saved = { saved: false }
  for (let i = 0; i < 8; i++) {
    await wait(1)
    saved = await shadow(`
      const t = sr.textContent || ''
      return { saved: t.indexOf('已保存') >= 0 || t.indexOf('草稿箱') >= 0 }
    `)
    if (saved.saved) break
  }
  console.log('\n=== ' + (saved.saved ? 'OK (draft saved)' : 'OK (draft, unconfirmed)') + ' ===')
  if (!saved.saved) {
    console.log('提示: 没抓到"已保存"字样，去 内容管理 → 草稿箱 手动确认')
  }
  console.log('space    : ' + TASK.id)
}

// ego-browser 的 stdin 走 node:internal/vm，不支持顶层 await（会报 SyntaxError
// 且被包装成 exit 90、一行输出都没有）。必须用 IIFE 包装，正常完成路径显式退出。
;(async () => {
  try {
    await main()
  } catch (e) {
    await fail('internal', 'E_UNEXPECTED', EXIT.INTERNAL,
      String((e && e.message) || e),
      { stack: String((e && e.stack) || '').split('\n').slice(0, 3).join(' | ').slice(0, 300) },
      ['这是未预期异常，通常是页面改版或浏览器连接中断',
       '接管截图看当前页面',
       '确认页面正常后重跑'])
  }
  process.exit(0)
})()
