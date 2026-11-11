// verify_via_cli.js — 折叠状态权威验证（v1.3.3）
// 用途：serverFetch(/api/v4/answers/{aid}) 自 2026-08-26 起恒 403，验证一律走官方 CLI。
// 用法：AID=<answer id> ego-browser nodejs < scripts/verify_via_cli.js
//   或参数文件 /tmp/zhihu_verify_params.json：{ "aid": "2078xxxxx", "type": "answer|pin" }
// 判定：CLI me contents 中该 aid 的 Summary 非空 = 未折叠；Summary 为空 = 已折叠。
// 注意：刚发布索引可能滞后 1-2 分钟（Item 缺失 ≠ 折叠，等一会再跑一次）。
// ⚠️ 本脚本由 ego-browser nodejs 运行（继承登录态 task space），但 CLI 调用走本机 child_process。

(async () => {
  const fs = require('fs')
  const cp = require('child_process')
  const path = require('path')

  let aid = process.env.AID || ''
  let type = process.env.TYPE || 'answer'
  try {
    const f = JSON.parse(fs.readFileSync('/tmp/zhihu_verify_params.json', 'utf8'))
    if (!aid && f.aid) aid = String(f.aid)
    if (f.type) type = String(f.type)
  } catch (e) {}

  if (!aid) { cliLog('ERROR: no AID (env AID=xxx or params file .aid)'); return }
  if (!['answer', 'pin'].includes(type)) type = 'answer'

  // 定位 zhihu-cli：PATH 优先，回退 macOS 默认安装路径
  let cli = 'zhihu-cli'
  try { cp.execSync('command -v zhihu-cli', { stdio: 'ignore' }) } catch (e) {
    const fallback = path.join(process.env.HOME || '', 'Library', 'Application Support', 'zhihu-cli', 'current', 'zhihu-cli')
    if (fs.existsSync(fallback)) cli = fallback
    else { cliLog('ERROR: zhihu-cli not found in PATH nor at ' + fallback); return }
  }

  let out = ''
  try {
    out = cp.execFileSync(cli, ['me', 'contents', '--type', type, '--limit', '20'], { encoding: 'utf8' })
  } catch (e) {
    cliLog('CLI_ERR: ' + (e && e.message ? e.message : String(e)))
    return
  }

  let data = null
  try { data = JSON.parse(out) } catch (e) { cliLog('CLI_BAD_JSON: ' + out.slice(0, 200)); return }
  const items = (data.Data && data.Data.Items) || []
  const hit = items.filter(function (x) { return String(x.Url || '').indexOf(aid) >= 0 })[0]
  if (!hit) {
    cliLog('VERIFY_RESULT: NOT_FOUND_YET aid=' + aid + ' (index lag, retry in 1-2 min; NOT evidence of collapse)')
    return
  }
  const summary = String(hit.Summary || '').trim()
  const result = summary.length > 0 ? 'OK_NOT_COLLAPSED' : 'COLLAPSED'
  cliLog('VERIFY_RESULT: ' + result + ' aid=' + aid)
  cliLog('SUMMARY_HEAD: ' + summary.slice(0, 80).replace(/\n/g, ' '))
  cliLog('TOTALS: ' + ((data.Data && data.Data.Totals) != null ? data.Data.Totals : '?'))
})()
