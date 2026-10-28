// 抓小红书「笔记管理」列表数据（发布后数据回收）
// 参数文件：/tmp/mp2xhs_stats_params.json {"out":"<path>"}
//
// 指标顺序（以图标形状为准，2026-10 实测）：
//   1 眼睛=观看  2 气泡=评论  3 心=点赞  4 星=收藏  5 箭头=分享
//   注意小红书网页端常见顺序是「点赞在前」，创作者中心不是，别凭常识猜。
//
// 页面行为（实测）：
//   · 一页只渲染 10 条，没有分页器、body 不可滚动，滚动加载无效
//   · 但 URL 的 ?page=N 有效（0 基），所以按页翻
const fs = await import('node:fs')
const P = JSON.parse(fs.readFileSync('/tmp/mp2xhs_stats_params.json', 'utf8'))
const BASE = 'https://creator.xiaohongshu.com/new/note-manager'

await useOrCreateTaskSpace('mp2xhs stats')

const parse = `(() => {
  const num = v => {
    if (v == null) return 0
    const m = String(v).replace(/\\s/g, '').match(/^([\\d.]+)(万|千)?$/)
    if (!m) return 0
    const base = parseFloat(m[1])
    if (m[2] === '万') return Math.round(base * 10000)
    if (m[2] === '千') return Math.round(base * 1000)
    return Math.round(base)
  }
  // 以 .note-card 容器为主体遍历（精确类名：[class*=note-card] 会匹配到
  // note-card__title 等子元素，实测 10 张卡会数成 230 个）
  const out = []
  document.querySelectorAll('.note-card').forEach(card => {
    const titleEl = card.querySelector('.note-card__title')
    if (!titleEl) return
    const timeEl = card.querySelector('.note-card__time')
    const stats = Array.from(card.querySelectorAll('.note-card__stat'))
      .map(s => num((s.innerText || '').trim()))
    const raw = (card.innerText || '').replace(/\\s+/g, ' ')
    out.push({
      title: (titleEl.innerText || '').trim(),
      time: timeEl ? (timeEl.innerText || '').trim() : '',
      state: /审核中/.test(raw) ? 'auditing' : (/未通过/.test(raw) ? 'rejected' : 'published'),
      views: stats[0] || 0,
      comments: stats[1] || 0,
      likes: stats[2] || 0,
      collects: stats[3] || 0,
      shares: stats[4] || 0,
      rawStats: stats
    })
  })
  return out
})()`

// 只取列表第一页：页面一次只渲染 10 条，无分页器、body 不可滚动，
// ?page=N 仅在"全新导航"时生效，而 ego-browser 复用 tab 时拿不到第 2 页
// （reload / about:blank 都试过，无效）。所以本脚本固定回收最新 10 条——
// 对「发布后盯数据」够用，历史笔记的数据抓不到，别指望。
await openOrReuseTab(BASE, { wait: true, timeout: 40 })
await wait(17)

const items = await js(parse)
const total = await js(`(() => {
  const tab = Array.from(document.querySelectorAll('[class*="tab-item"]'))
    .map(e => (e.innerText || '').trim())
    .find(t => /^全部\\s*\\d+/.test(t))
  return tab ? parseInt((tab.match(/\\d+/) || [0])[0], 10) : 0
})()`)

fs.writeFileSync(P.out, JSON.stringify({
  captured_at: new Date().toISOString(),
  total_on_page: total,
  items: items || []
}, null, 1))
console.log('STATS_OK items=' + (items ? items.length : 0) + ' total=' + total + ' out=' + P.out)
;(items || []).slice(0, 3).forEach(i => console.log('  ' + i.title.slice(0, 24) + ' | ' + i.rawStats.join(',')))
