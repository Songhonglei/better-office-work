#!/bin/bash
set -euo pipefail
# ============================================================
# 小红书笔记自动发布脚本（图文 + 视频，自动判断）
# 依赖：ego-browser (ego-lite) 已安装且正在运行，小红书已登录
# 用法：修改下方参数后 bash publish_note.sh
# ============================================================

export PATH="$HOME/.local/bin:$PATH"

# ---- 参数配置（按需修改）----
# 支持两种方式：① 直接修改本文件  ② 通过环境变量传入
MEDIA_DIR="${MEDIA_DIR:-${IMAGE_DIR:-}}"        # 素材所在目录（绝对路径）
MEDIA_FILES="${MEDIA_FILES:-${IMAGES:-}}"       # 文件名，逗号分隔。视频只能 1 个；图文最多 18 个
TITLE="${TITLE:-}"                              # 笔记标题（严禁包含单引号）
BODY="${BODY:-}"                                # 笔记正文（支持 \n 换行；严禁包含反引号和 ${）
TOPICS="${TOPICS:-}"                            # 话题标签，逗号分隔（不要带 #）
MODE="${MODE:-publish}"                         # publish=直接发布；draft=存草稿箱；stage=只准备好停在页面
MEDIA_TYPE="${MEDIA_TYPE:-auto}"                # auto=按扩展名判断；image=强制图文；video=强制视频
COVER_IMAGE="${COVER_IMAGE:-}"                  # 可选：视频封面图片绝对路径。留空=默认取视频第一帧
# ---- 参数配置结束 ----

if [ -z "$MEDIA_DIR" ] || [ -z "$MEDIA_FILES" ] || [ -z "$TITLE" ] || [ -z "$BODY" ]; then
  echo "ERROR: 请先填写 MEDIA_DIR, MEDIA_FILES, TITLE, BODY 四个参数"
  exit 1
fi

if echo "$TOPICS" | grep -q '#'; then
  echo "WARN: TOPICS 不需要带 # 号，已自动忽略不影响发布"
fi

if ! command -v ego-browser &>/dev/null; then
  echo "ERROR: ego-browser 未安装或不在 PATH 中"
  echo "请先安装 ego-lite: sh ~/.workbuddy/skills/ego-browser/scripts/install.sh"
  exit 1
fi

if echo "$TITLE" | grep -q "'"; then
  echo "ERROR: TITLE 含单引号，会导致脚本注入，请移除单引号后重试"
  exit 1
fi

if echo "$BODY" | grep -q '`' || echo "$BODY" | grep -q '${'; then
  echo "ERROR: BODY 含反引号或 \${，会导致脚本注入，请移除后重试"
  exit 1
fi

PARAMS_FILE="/tmp/xhs_publish_params.json"

# 判断媒体类型 + 写参数 JSON，并把最终类型打印给 shell
RESOLVED_TYPE=$(python3 - "$MEDIA_DIR" "$MEDIA_FILES" "$TITLE" "$BODY" "$TOPICS" "$MODE" "$MEDIA_TYPE" "$COVER_IMAGE" "$PARAMS_FILE" <<'PYEOF'
import json, os, sys

(media_dir, files_str, title, body, topics_str,
 mode, forced_type, cover_image, path) = sys.argv[1:10]

VIDEO_EXT = {'.mp4', '.mov', '.flv', '.f4v', '.mkv', '.rm', '.rmvb', '.m4v', '.mpg', '.mpeg', '.ts'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.heic', '.bmp'}

files = [s.strip() for s in files_str.split(',') if s.strip()]
mode = (mode or 'publish').strip().lower()
if mode not in ('publish', 'draft', 'stage'):
    mode = 'publish'

exts = [os.path.splitext(f)[1].lower() for f in files]
forced_type = (forced_type or 'auto').strip().lower()

if forced_type in ('image', 'video'):
    media_type = forced_type
elif exts and all(e in VIDEO_EXT for e in exts):
    media_type = 'video'
elif exts and all(e in IMAGE_EXT for e in exts):
    media_type = 'image'
else:
    media_type = 'unknown'

err = None
if media_type == 'unknown':
    err = '无法从扩展名判断类型，请显式设置 MEDIA_TYPE=image 或 MEDIA_TYPE=video'
elif media_type == 'video' and len(files) != 1:
    err = '视频笔记一次只能发 1 个文件，当前 %d 个' % len(files)
elif media_type == 'image' and len(files) > 18:
    err = '图文笔记最多 18 张，当前 %d 张' % len(files)

# 封面图：仅视频笔记使用；图文笔记静默忽略
cover = (cover_image or '').strip()
if cover:
    if not os.path.isfile(cover):
        err = 'COVER_IMAGE 文件不存在: %s' % cover
    elif os.path.splitext(cover)[1].lower() not in IMAGE_EXT:
        err = 'COVER_IMAGE 必须是图片（支持 %s），当前: %s' % (
            '/'.join(sorted(IMAGE_EXT)), cover)
    elif media_type != 'video':
        cover = ''   # 图文笔记没有封面概念，忽略即可

params = {
    "mediaDir": media_dir,
    "files": files,
    "mediaType": media_type,
    "title": title,
    "body": body,
    "topics": [t.strip().lstrip('#') for t in topics_str.split(',') if t.strip()],
    "mode": mode,
    "coverImage": cover,
    "error": err,
}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(params, f, ensure_ascii=False)

print(media_type)
PYEOF
)

if [ "$RESOLVED_TYPE" = "unknown" ]; then
  echo "ERROR: 无法判断素材类型。视频支持 mp4/mov/flv/mkv 等，图片支持 png/jpg/webp 等"
  echo "       也可显式指定 MEDIA_TYPE=image 或 MEDIA_TYPE=video"
  exit 1
fi

IFS=',' read -ra FILE_ARRAY <<< "$MEDIA_FILES"

echo "=========================================="
echo "小红书笔记自动发布"
if [ "$RESOLVED_TYPE" = "video" ]; then
  echo "  类型: video（视频笔记）"
else
  echo "  类型: image（图文笔记）"
fi
echo "  素材目录: $MEDIA_DIR"
echo "  文件数量: ${#FILE_ARRAY[@]}"
echo "  标题: $TITLE"
[ -n "$TOPICS" ] && echo "  话题: $TOPICS"
if [ "$RESOLVED_TYPE" = "video" ]; then
  if [ -n "$COVER_IMAGE" ]; then
    echo "  封面: $COVER_IMAGE"
  else
    echo "  封面: 默认（视频第一帧）"
  fi
elif [ -n "$COVER_IMAGE" ]; then
  echo "  封面: 忽略（COVER_IMAGE 仅对视频笔记生效）"
fi
echo "  模式: $MODE"
echo "=========================================="
echo ""

# 使用 <<'EOF' 阻止 shell 展开，参数从 JSON 文件读取
ego-browser nodejs <<'EOF'
import fs from 'fs'
const params = JSON.parse(fs.readFileSync('/tmp/xhs_publish_params.json', 'utf8'))

if (params.error) {
  cliLog('ERROR: ' + params.error)
  process.exit(1)
}

const isVideo = params.mediaType === 'video'
const mediaDir = params.mediaDir
const filePaths = params.files.map(f => mediaDir + '/' + f)
const title = params.title
const bodyText = (params.body || '').replace(/\\n/g, '\n')
const topics = params.topics
const MODE = params.mode || 'publish'

// 视频页与图文页的 file input 用 accept 区分
const VIDEO_SEL = 'input[type="file"][accept*=".mp4"]'
const IMAGE_SEL = 'input[type="file"][accept*=".png"]'
const UPLOAD_SEL = isVideo ? VIDEO_SEL : IMAGE_SEL
const TAB_TEXT = isVideo ? '上传视频' : '上传图文'
const coverImage = params.coverImage || ''

// 设置视频自定义封面：hover 缩略图 → 点「编辑封面」→ 上传图片 → 点「完成」
// 「编辑封面」按钮平时 boundingRect 为 0×0，只有鼠标真的悬停在封面缩略图上才渲染出来，
// 所以必须用 CDP 派发 mouseMoved，用 el.click() 或 scrollIntoView 都不行。
async function setVideoCover(coverPath) {
  // 「PK封面」引导气泡会在首屏自动弹出并可能盖住封面区域，先隐藏掉（纯视觉层，不影响数据）
  await js(`(() => {
    document.querySelectorAll('.pk-cover-guide-tooltip, .pk-cover-guide').forEach(e => { e.style.display = 'none' })
    return true
  })()`)

  const rect = await js(`(() => {
    const c = document.querySelector('.cover')
    if (!c) return null
    const r = c.getBoundingClientRect()
    if (r.width < 50) return null
    return {
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height)
    }
  })()`)
  if (!rect) return 'NO_COVER_AREA'
  cliLog('cover area: ' + JSON.stringify(rect))

  // 悬停在缩略图（左侧约 130px 宽）中部，右侧是「智能推荐封面」不响应 hover
  await cdp('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x: rect.x + 65,
    y: rect.y + Math.round(rect.h / 2),
    button: 'none'
  })
  await wait(1.5)

  const entryShown = await js(`(() => {
    const el = document.querySelector('.cover-edit-entry')
    if (!el) return false
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  })()`)
  if (!entryShown) return 'EDIT_ENTRY_NOT_SHOWN'

  await click('.cover-edit-entry', { label: 'open cover editor', timeout: 8000 })
  await wait(4)

  // 封面编辑器打开后，页面会多出一个 accept 含 image 的 file input
  const editorReady = await js(`!!document.querySelector('input[type="file"][accept*="image/png"]')`)
  if (!editorReady) return 'EDITOR_NOT_OPEN'

  await uploadFile('input[type="file"][accept*="image/png"]', coverPath)
  await wait(5)

  // 「完成」按钮在视口外右侧（innerWidth 900 时 x≈1128），必须先 scrollIntoView 再点
  const doneClicked = await js(`(() => {
    const el = [...document.querySelectorAll('span')].find(e =>
      e.textContent.trim() === '完成' && String(e.className).includes('circle-button'))
    if (!el) return false
    el.scrollIntoView({ block: 'center', inline: 'center' })
    el.click()
    return true
  })()`)
  if (!doneClicked) return 'NO_DONE_BUTTON'
  await wait(4)

  const closed = await js(`(() => {
    const m = document.querySelector('.d-modal.cover-modal')
    return !m || m.offsetParent === null
  })()`)
  return closed ? 'OK' : 'MODAL_STILL_OPEN'
}

cliLog('Media type: ' + params.mediaType + ' | files: ' + filePaths.length)

// ===== 第1步：创建/复用 task space =====
const task = await useOrCreateTaskSpace('publish xhs note ' + Date.now())
cliLog('task space: ' + task.id)

// ===== 第2步：打开小红书创作平台 =====
await openOrReuseTab('https://creator.xiaohongshu.com/publish/publish', { wait: true, timeout: 25 })
cliLog('waiting for SPA to render...')
await wait(15)

// 登录判定：以 URL 为准，避免登录页导航文案（含「发布」字样）造成误判
const loginCheck = await js(`(() => {
  const href = location.href || ''
  if (href.includes('/login')) {
    return { loggedIn: false, reason: 'redirected_to_login', url: href }
  }
  const text = document.body ? document.body.innerText : ''
  if (!text.includes('笔记管理') && !text.includes('草稿箱')) {
    return { loggedIn: false, reason: 'no_manage_entry', url: href }
  }
  return { loggedIn: true, url: href }
})()`)
cliLog('Login status: ' + JSON.stringify(loginCheck))

if (!loginCheck.loggedIn) {
  cliLog('ERROR: 未登录小红书（原因: ' + loginCheck.reason + '）')
  cliLog('当前 URL: ' + loginCheck.url)
  cliLog('请在 ego-lite 浏览器窗口手动登录 creator.xiaohongshu.com 后重试')
  await completeTaskSpace(task.id, { keep: false })
  process.exit(1)
}

// ===== 第3步：确保停在正确的上传 tab =====
// /publish/publish 默认是「上传视频」页。图文要切「上传图文」；视频通常无需切换，
// 但上一轮若停在图文页，需要切回来。
let uploadReady = await js(`!!document.querySelector('${UPLOAD_SEL}')`)

if (!uploadReady) {
  cliLog('Not on ' + TAB_TEXT + ' page, switching...')
  const tabClicked = await js(`((want) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false)
    let node
    while (node = walker.nextNode()) {
      if (node.textContent.trim() === want) {
        let el = node.parentElement
        for (let i = 0; i < 4; i++) {
          if (!el) break
          el.click()
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
          el = el.parentElement
        }
        return true
      }
    }
    return false
  })('${TAB_TEXT}')`)
  cliLog('tab click: ' + tabClicked)
  await wait(3)

  uploadReady = await js(`!!document.querySelector('${UPLOAD_SEL}')`)

  // 回退：走「发布笔记」下拉菜单
  if (!uploadReady) {
    cliLog('Tab click failed, trying 发布笔记 dropdown...')
    const pageText = await snapshotText()
    const m1 = pageText.match(/发布笔记.*?\[ref=(\d+)/)
    if (m1) {
      await click('@' + m1[1], { label: 'click 发布笔记 dropdown' })
      await wait(2)
      const t2 = await snapshotText()
      const m2 = t2.match(new RegExp(TAB_TEXT + '.*?\\\\[ref=(\\\\d+)'))
      if (m2) {
        await click('@' + m2[1], { label: 'click ' + TAB_TEXT })
        await waitForNetworkIdle(5)
        await wait(3)
      }
    }
    uploadReady = await js(`!!document.querySelector('${UPLOAD_SEL}')`)
  }
}

if (!uploadReady) {
  cliLog('ERROR: 未能进入 ' + TAB_TEXT + ' 页（找不到 ' + UPLOAD_SEL + '）')
  await completeTaskSpace(task.id, { keep: false })
  process.exit(1)
}
cliLog('Upload page ready: ' + TAB_TEXT)

// ===== 第4步：上传素材 =====
if (isVideo) {
  // 视频：单文件，上传后需要转码，不能只看瞬时状态
  cliLog('Uploading video: ' + filePaths[0])
  await uploadFile(UPLOAD_SEL, filePaths[0])
  await wait(5)

  let videoOk = false
  let last = {}
  for (let attempt = 0; attempt < 40; attempt++) {
    await wait(3)
    last = await js(`(() => {
      const text = document.body ? document.body.innerText : ''
      const hasReupload = text.includes('重新上传')
      const hasTitleInput = !!document.querySelector('input[placeholder="填写标题会有更多赞哦"]')
      const hasSetCover = text.includes('设置封面')
      const videoCount = document.querySelectorAll('video').length
      let readyState = 0
      try {
        readyState = Math.max(0, ...[...document.querySelectorAll('video')].map(v => v.readyState || 0))
      } catch (e) {}
      return { hasReupload, hasTitleInput, hasSetCover, videoCount, readyState }
    })()`)
    cliLog('video verify ' + attempt + ': ' + JSON.stringify(last))
    if (last.hasReupload && last.hasTitleInput) { videoOk = true; break }
  }

  if (!videoOk) {
    cliLog('ERROR: 视频上传/转码未在预期时间内完成: ' + JSON.stringify(last))
    await completeTaskSpace(task.id, { keep: false })
    process.exit(1)
  }
  cliLog('Video uploaded and transcoded')

  // 可选：设置自定义封面。留空则保留小红书默认的第一帧，不做任何操作
  if (coverImage) {
    cliLog('Setting custom cover: ' + coverImage)
    const coverResult = await setVideoCover(coverImage)
    cliLog('Cover result: ' + coverResult)
    if (coverResult !== 'OK') {
      cliLog('ERROR: 封面设置失败（' + coverResult + '），中止以免发出封面错误的笔记')
      await completeTaskSpace(task.id, { keep: false })
      process.exit(1)
    }
    cliLog('Custom cover applied')
  } else {
    cliLog('Cover: keep default first frame')
  }
} else {
  // 图文：小红书对批量 setFileInputFiles 只建空占位，必须逐个 uploadFile
  cliLog('Uploading ' + filePaths.length + ' images one by one...')
  for (let i = 0; i < filePaths.length; i++) {
    cliLog('Uploading ' + (i + 1) + '/' + filePaths.length + ': ' + filePaths[i])
    await uploadFile(UPLOAD_SEL, filePaths[i])
    await wait(6)
  }
  cliLog('All files selected, waiting for CDN processing...')
  await wait(10)

  let uploadOk = false
  let lastVerify = {}
  for (let attempt = 0; attempt < 10; attempt++) {
    await wait(3)
    const v = await js(`(() => {
      const imgs = [...document.querySelectorAll('img')]
      const cdn = imgs.filter(i => {
        const s = i.src || ''
        return s.includes('xhscdn.com') || s.includes('spectrum/')
      }).length
      let editCount = 'n/a'
      for (const l of document.body.innerText.split('\\n')) {
        if (l.includes('图片编辑')) {
          editCount = l.split('/')[0].split('').filter(c => c >= '0' && c <= '9').join('')
          break
        }
      }
      return { cdnImages: cdn, editCount: editCount }
    })()`)
    lastVerify = v
    cliLog('image verify ' + attempt + ': ' + JSON.stringify(v))
    if (parseInt(v.cdnImages || 0) >= filePaths.length || parseInt(v.editCount || 0) >= filePaths.length) {
      uploadOk = true
      break
    }
  }

  if (!uploadOk) {
    cliLog('ERROR: 图片没有正确上传到小红书: ' + JSON.stringify(lastVerify))
    await completeTaskSpace(task.id, { keep: false })
    process.exit(1)
  }
}

// ===== 第5步：标题 =====
cliLog('Filling title...')
await fillInput('css:input[placeholder="填写标题会有更多赞哦"]', title, { label: 'fill title' })
await wait(1)

// ===== 第6步：正文 + 话题 =====
// 编辑器可能是 contenteditable 富文本（图文页）或 tiptap ProseMirror（视频页），
// 统一按 contenteditable 定位后用 typeText 输入。
cliLog('Filling body text...')
const editorSel = await js(`(() => {
  if (document.querySelector('div.tiptap')) return 'div.tiptap'
  if (document.querySelector('[contenteditable="true"]')) return '[contenteditable="true"]'
  return ''
})()`)
if (!editorSel) {
  cliLog('ERROR: 找不到正文编辑器')
  await completeTaskSpace(task.id, { keep: false })
  process.exit(1)
}
cliLog('editor selector: ' + editorSel)

await js(`document.querySelector('${editorSel}')?.focus()`)
await wait(0.5)
await typeText(bodyText, { label: 'type body text' })
await wait(1)

// tiptap 不认 Control+End，用 Selection API 把光标落到末尾，
// 否则话题会被插进正文中间
const moveCaretToEnd = async () => {
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

if (topics.length > 0) {
  cliLog('Inserting ' + topics.length + ' topics from dropdown...')
  await moveCaretToEnd()
  await typeText('\n\n', { label: 'newline before topics' })
  await wait(0.5)

  for (const topic of topics) {
    cliLog('Adding topic: #' + topic)
    await moveCaretToEnd()

    await typeText('#' + topic, { label: 'type topic #' + topic })
    await wait(4)

    const topicResult = await js(`((topic) => {
      const container = document.getElementById('creator-editor-topic-container')
      if (!container) return { error: 'topic container not found' }
      const items = [...container.querySelectorAll('.item')]
      if (!items.length) return { error: 'no topic items' }
      const exact = items.find(el => {
        const n = el.querySelector('.name')
        return n && n.innerText.trim().split('\\n')[0] === '#' + topic
      })
      const target = exact || items[0]
      const nameEl = target.querySelector('.name')
      ;(nameEl || target).click()
      return {
        clicked: true,
        exact: !!exact,
        text: (target.innerText || '').split('\\n')[0]
      }
    })('${topic.replace(/'/g, "\\'")}')`)

    cliLog('Topic click: ' + JSON.stringify(topicResult))
    await wait(1.5)

    const popupStillOpen = await js(`!!document.getElementById('tippy-1')?.offsetParent`)
    if (popupStillOpen) {
      await pressKey('Escape')
      await wait(0.5)
    }

    await typeText(' ', { label: 'space after topic' })
    await wait(0.5)
  }
}

await pressKey('Escape')
await wait(0.5)

// ===== 第7步：收尾 =====
if (MODE === 'stage') {
  cliLog('STAGE MODE: 内容已准备好，页面保持不动，等待用户自行检查并发布')
  cliLog('  - 类型: ' + params.mediaType)
  cliLog('  - 素材: ' + filePaths.length + ' 个')
  cliLog('  - 标题: ' + title)
  cliLog('  - 正文长度: ' + bodyText.length + ' 字')
  cliLog('  - 话题: ' + (topics.length > 0 ? topics.join(', ') : '无'))
  const stageShot = await captureScreenshot()
  cliLog('Stage screenshot: ' + stageShot)
  cliLog('SUCCESS: 页面已准备好，task space 保持开启')
} else {
  cliLog('Triggering ' + MODE + ' via ' + (MODE === 'draft' ? '_onSave()' : '_onPublish()') + '...')
  const publishResult = await js(`((mode) => {
    const host = document.querySelector('xhs-publish-btn')
    if (!host) return { error: 'no xhs-publish-btn found' }

    if (mode === 'draft') {
      if (typeof host._onSave !== 'function') return { error: 'no _onSave method' }
      const saveDisabled = host.getAttribute('save-disabled')
      if (saveDisabled === 'true') return { error: 'save-draft button is disabled', saveDisabled }
      host._onSave()
      return { triggered: true, action: 'draft', saveDisabled }
    }

    if (typeof host._onPublish !== 'function') return { error: 'no _onPublish method' }
    const submitDisabled = host.getAttribute('submit-disabled')
    const submitLoading = host.getAttribute('submit-loading')
    if (submitDisabled === 'true') {
      return { error: 'publish button is disabled', submitDisabled, submitLoading }
    }
    host._onPublish()
    return { triggered: true, action: 'publish', submitDisabled, submitLoading }
  })('${MODE}')`)
  cliLog('Result: ' + JSON.stringify(publishResult, null, 2))

  if (publishResult.error) {
    cliLog('ERROR: ' + publishResult.error)
    await completeTaskSpace(task.id, { keep: false })
    process.exit(1)
  }

  const readDraftCount = () => js(`(() => {
    const m = document.body.innerText.match(/草稿箱\\((\\d+)\\)/)
    return m ? m[1] : 'n/a'
  })()`)

  if (MODE === 'draft') {
    cliLog('Waiting for draft save...')
    await wait(6)
    cliLog('草稿箱 count after save: ' + await readDraftCount())
    cliLog('SUCCESS: 已存入草稿箱（请到小红书「草稿箱」自行点发布；不会自动发布）')
  } else {
    cliLog('Waiting for publish to complete...')
    await wait(10)
    const info = await pageInfo()
    cliLog('URL after publish: ' + info.url)
    if (info.url.includes('published=true') || info.url.includes('note-manage')) {
      cliLog('SUCCESS: 笔记发布成功！')
    } else {
      await wait(5)
      const info2 = await pageInfo()
      if (info2.url.includes('published=true') || info2.url.includes('note-manage')) {
        cliLog('SUCCESS: 笔记发布成功！')
      } else {
        cliLog('WARNING: 发布状态不确定，请手动检查小红书笔记管理页')
      }
    }
  }

  const shot = await captureScreenshot()
  cliLog('Final screenshot: ' + shot)

  await completeTaskSpace(task.id, { keep: false })
  cliLog('Task completed, space cleaned up')
}
EOF

rm -f "$PARAMS_FILE"

echo ""
echo "=========================================="
echo "发布流程结束"
echo "=========================================="
