// 抓取单篇公众号文章：标题 / 正文 / 全部图片（含懒加载），并下载原图
// 参数文件：/tmp/mp2xhs_fetch_params.json  {"url":"...","out_dir":"...","crop":"none"}
const fs = await import('node:fs')
const P = JSON.parse(fs.readFileSync('/tmp/mp2xhs_fetch_params.json', 'utf8'))
const outDir = P.out_dir

await useOrCreateTaskSpace('mp2xhs fetch')
await openOrReuseTab(P.url, { wait: true, timeout: 40 })
await wait(6)

// 反复滚动触发懒加载，直到图片数量稳定（关键：不滚动会漏掉未进入视口的图）
// 注意：不能把整个滚动流程塞进一个 async js() 表达式——会触发 Runtime.evaluate 超时
let prevCount = -1
for (let round = 0; round < 2; round++) {
  const h = await js('document.body.scrollHeight')
  for (let y = 0; y < h; y += 1200) {
    await js(`(() => { window.scrollTo(0, ${y}); return 1 })()`)
    await wait(0.25)
  }
  await js('(() => { window.scrollTo(0, document.body.scrollHeight); return 1 })()')
  await wait(1.5)
  const c = await js(`document.querySelectorAll('#js_content img').length`)
  console.log('round ' + round + ': imgs=' + c + ' scrollHeight=' + h)
  if (c === prevCount) break
  prevCount = c
}
await js('(() => { window.scrollTo(0, 0); return 1 })()')
await wait(1)
console.log('img count final: ' + await js(`document.querySelectorAll('#js_content img').length`))

const meta = await js(`(() => {
  const root = document.querySelector('#js_content') || document.querySelector('.rich_media_content') || document.body
  const imgs = Array.from(root.querySelectorAll('img'))
  const titleEl = document.querySelector('#activity-name') || document.querySelector('h1')
  const list = imgs.map((im, i) => {
    const src = (im.getAttribute('data-src') || im.getAttribute('src') || '').split('#')[0]
    // 找图片之前最近的文字块，用于判断这张图属于哪个小节
    let prev = ''
    let p = im.parentElement
    for (let k = 0; k < 10 && p; k++) {
      const t = (p.innerText || '').trim()
      if (t && t.length > 4) { prev = t.slice(0, 60).replace(/\\n/g, ' '); break }
      p = p.previousElementSibling
    }
    return {
      index: i, src,
      w: im.getAttribute('data-w') || '',
      ratio: im.getAttribute('data-ratio') || '',
      prev
    }
  })
  return {
    title: titleEl ? titleEl.innerText.trim() : document.title.trim(),
    body: (root.innerText || '').trim(),
    imgTotal: imgs.length,
    imgs: list
  }
})()`)

fs.mkdirSync(outDir, { recursive: true })

// 下载：/640 换成 /0 取原尺寸，必须带 Referer（微信图床防盗链）
let ok = 0
const failed = []
for (const im of meta.imgs) {
  if (!im.src) { failed.push({ index: im.index, reason: 'no_src' }); continue }
  const big = im.src.replace(/\/640(\?|$)/, '/0$1').replace(/\/640$/, '/0')
  let buf = null
  try {
    const res = await fetch(big, {
      headers: { Referer: 'https://mp.weixin.qq.com/', 'User-Agent': 'Mozilla/5.0' }
    })
    if (res.ok) buf = Buffer.from(await res.arrayBuffer())
  } catch (e) {
    console.log('fetch failed idx=' + im.index + ' ' + e.message)
  }
  if (!buf || buf.length < 2000) { failed.push({ index: im.index, reason: 'download_failed' }); continue }
  const file = outDir + '/img' + im.index + '.jpg'
  fs.writeFileSync(file, buf)
  im.file = file
  im.bytes = buf.length
  ok++
}

meta.url = P.url
meta.imgDownloaded = ok
meta.imgFailed = failed
meta.fetchedAt = new Date().toISOString()
fs.writeFileSync(outDir + '/article.json', JSON.stringify(meta, null, 1))

console.log('FETCH_OK title=' + meta.title)
console.log('IMG_CHECK total=' + meta.imgTotal + ' downloaded=' + ok + ' failed=' + failed.length)
console.log('BODY_LEN=' + meta.body.length)
if (meta.imgTotal !== ok) {
  console.log('WARN: 图片数量不一致，缺失: ' + JSON.stringify(failed))
}
