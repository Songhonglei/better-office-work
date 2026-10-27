// 拉取公众号「发表记录」列表（标题 / URL / 阅读数 / 时间）
// 参数文件：/tmp/mp2xhs_list_params.json  {"out":"<path>","count":30,"pages":3}
const fs = await import('node:fs')
const P = JSON.parse(fs.readFileSync('/tmp/mp2xhs_list_params.json', 'utf8'))
const want = P.count || 30
const maxPages = P.pages || 3

await useOrCreateTaskSpace('mp2xhs list')
await openOrReuseTab('https://mp.weixin.qq.com/', { wait: true, timeout: 30 })
await wait(5)

const token = await js(`(() => {
  const a = Array.from(document.querySelectorAll('a')).find(x => /token=\\d+/.test(x.href))
  const m = a ? a.href.match(/token=(\\d+)/) : null
  return m ? m[1] : ''
})()`)

if (!token) {
  console.error('ERROR: 未取到 token，公众号后台可能未登录')
  fs.writeFileSync(P.out, JSON.stringify({ error: 'no_token' }))
  process.exit(1)
}

const parsePage = `(() => {
  const out = []
  document.querySelectorAll('.publish_hover_content').forEach(card => {
    const a = card.querySelector('a.weui-desktop-mass-appmsg__title')
    if (!a) return
    const href = (a.getAttribute('href') || '').split('#')[0]
    if (!/mp\\.weixin\\.qq\\.com\\/s/.test(href)) return
    const title = (a.innerText || '').trim().split('\\n')[0].replace(/原创|已修改/g, '').trim()
    const nums = Array.from(card.querySelectorAll('.weui-desktop-mass-media__data__inner'))
      .map(e => (e.textContent || '').trim())
    const read = nums.length ? (parseInt(nums[0].replace(/[^\\d]/g, ''), 10) || 0) : 0
    const t = card.innerText || ''
    const m = t.match(/(\\d{1,2}月\\d{1,2}日|\\d{4}年\\d{1,2}月\\d{1,2}日|昨天|前天|今天)\\s*\\d{1,2}:\\d{2}/)
    out.push({ title, url: href, read, time: m ? m[0] : '' })
  })
  return out
})()`

let all = []
let begin = 0
for (let page = 0; page < maxPages && all.length < want; page++) {
  const url = 'https://mp.weixin.qq.com/cgi-bin/appmsgpublish?sub=list&begin=' + begin +
              '&count=20&token=' + token + '&lang=zh_CN'
  await openOrReuseTab(url, { wait: true, timeout: 30 })
  await wait(5)
  const items = await js(parsePage)
  if (!items || !items.length) break
  all = all.concat(items)
  begin += 20
}

// 按 URL 去重（同一篇可能因"替换详情"等重复出现）
const seen = new Set()
const uniq = []
for (const a of all) {
  if (seen.has(a.url)) continue
  seen.add(a.url)
  uniq.push(a)
}

fs.writeFileSync(P.out, JSON.stringify(uniq.slice(0, want), null, 1))
console.log('LIST_OK total=' + uniq.length + ' out=' + P.out)
