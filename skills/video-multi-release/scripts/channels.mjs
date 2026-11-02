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
  OK: 0, PARAM: 10, DEP: 11, AUTH: 20, TAB: 21, UPLOAD: 30,
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
  console.error(lines.join('\n'))
  if (TASK && !CFG.keepOnFail) {
    try { await completeTaskSpace(TASK.id, { keep: false }) } catch (e) { /* ignore */ }
  }
  process.exit(exitCode)
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
      if ((a.type || '').toLowerCase() === 'file') hits.push(n.nodeId)
    }
    if (n.shadowRoots) n.shadowRoots.forEach(walk)
    if (n.children) n.children.forEach(walk)
  })(root)
  return hits[0] || null
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

async function clickByText(text) {
  // wujie 沙箱里 el.click() 无效，必须 CDP 真实鼠标
  const box = await shadow(`
    const btn = [...sr.querySelectorAll('button')].find(function (b) {
      return (b.innerText || '').trim() === ${JSON.stringify(text)}
    })
    if (!btn) return { __err: 'no_button' }
    btn.scrollIntoView({ block: 'center' })
    const r = btn.getBoundingClientRect()
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), disabled: btn.disabled }
  `)
  if (!box || box.__err) return box && box.__err
  if (box.disabled) return 'disabled'
  await wait(0.5)
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none' })
  await wait(0.2)
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  return 'clicked'
}

// ---------- 主流程 ----------

async function main() {
  log('开始，模式=' + CFG.mode)

  TASK = await useOrCreateTaskSpace('publish channels video')
  log('空间 ' + TASK.id + '  ' + elapsed())

  await openOrReuseTab('https://channels.weixin.qq.com/platform/post/create', { wait: true, timeout: 30 })
  await wait(12)

  const ready = await shadow(`
    return { url: location.href, hasWujie: true }
  `)
  if (!ready || ready.__err) {
    await fail('open-page', 'E_WUJIE_MISSING', EXIT.DEP,
      '页面没有加载出 wujie-app，可能是网络或登录态问题',
      { url: (await pageInfo()).url },
      ['先确认 channels.weixin.qq.com 能正常打开',
       '让用户手动在窗口里确认页面渲染完成',
       '再回复 continue 重跑'])
  }

  // 登录态
  const info = await pageInfo()
  if (/login/i.test(info.url)) {
    await fail('auth', 'E_AUTH_EXPIRED', EXIT.AUTH,
      '视频号未登录', { url: info.url },
      ['让用户在 ego-lite 窗口里用微信扫码登录',
       '登录是用户手动操作，会触发 task space 接管，属正常',
       '用户回复 continue 后用 claimTaskSpace(' + TASK.id + ') 接管再重跑'])
  }

  // 上传视频
  const nodeId = await findFileInputNodeId()
  if (!nodeId) {
    await fail('upload', 'E_NO_FILE_INPUT', EXIT.DEP,
      '找不到文件输入节点', {},
      ['页面结构可能变了，接管截图确认上传区是否正常',
       '若页面还停在登录页，先处理登录'])
  }
  await cdp('DOM.setFileInputFiles', { files: [CFG.video], nodeId: nodeId })
  log('已投递文件 ' + elapsed())

  // 等上传完成：video 有 duration + 封面预览出现 + 没有"文件上传中"
  let uploaded = false
  for (let i = 0; i < 40; i++) {
    await wait(4)
    const st = await shadow(`
      const v = sr.querySelector('video')
      const t = sr.textContent || ''
      return {
        dur: v ? Math.round(v.duration) : 0,
        cover: t.indexOf('封面预览') >= 0,
        uploading: t.indexOf('文件上传中') >= 0,
      }
    `)
    if (st.dur > 0 && st.cover && !st.uploading) { uploaded = true; break }
  }
  if (!uploaded) {
    await fail('upload', 'E_UPLOAD_TIMEOUT', EXIT.UPLOAD,
      '视频上传超时（160 秒）', {},
      ['检查文件是否可正常播放、体积是否过大',
       '重跑一次；若反复卡在 0%，刷新页面后重新上传',
       '注意：删除已上传视频再重传可能卡在 0%，此时只能刷新重来'])
  }
  log('上传完成 ' + elapsed())

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
    const title = CFG.title.slice(0, 16)
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
    const missing = topics.filter(function (t) { return added.indexOf(t) < 0 })
    await fail('add-topics', 'E_TOPIC_NOT_ATTACHED', EXIT.TOPIC,
      '有话题没挂上: ' + missing.join(' '),
      { expected: topics, got: added },
      ['话题缺失不影响发布，但会少曝光',
       '接管手动补，或直接重跑',
       '若反复失败，检查该话题在视频号是否真实存在'])
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
       '确认按钮是否被禁用'])
  }
  await wait(6)

  if (CFG.mode === 'publish') {
    // 发表成功会跳到作品列表页
    let ok = false
    for (let i = 0; i < 10; i++) {
      const info2 = await pageInfo()
      if (info2.url.indexOf('post/create') < 0) { ok = true; break }
      await wait(3)
    }
    if (!ok) {
      await fail('verify', 'E_PUBLISH_UNCONFIRMED', EXIT.VERIFY,
        '点了发表但页面没跳转', {},
        ['不要立即重发，先去作品列表确认是否已经发出',
         '接管检查是否有校验提示（如封面检测未通过）'])
    }
    const info3 = await pageInfo()
    console.log('\n=== OK (published) ===')
    console.log('url      : ' + info3.url)
    console.log('space    : ' + TASK.id)
    return
  }

  // draft：确认出现"已保存"
  const saved = await shadow(`
    const t = sr.textContent || ''
    return { saved: t.indexOf('已保存') >= 0 }
  `)
  console.log('\n=== ' + (saved.saved ? 'OK (draft saved)' : 'OK (draft, unconfirmed)') + ' ===')
  if (!saved.saved) {
    console.log('提示: 没抓到"已保存"字样，去 内容管理 → 草稿箱 手动确认')
  }
  console.log('space    : ' + TASK.id)
}

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
