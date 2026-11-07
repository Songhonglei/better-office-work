// fold_audit.js — 创作者中心折叠巡检（只读滚动抓取 + 基线比对）
// 用法：ego-browser nodejs < scripts/fold_audit.js
// 可选参数文件 /tmp/zhihu_fold_params.json：
//   { "update": true }          把本次最新状态写回基线（带防残缺护栏：抓取条数 < 基线条数则拒绝写回）
//   { "baseline": "/abs/path" } 覆盖默认基线路径（换机器时用）
// 输出：
//   TOTAL_ITEMS / ANSWERS / FOLDED 总数
//   FOLD_STAT <FOLD|OK  > <date> <title>        全量状态
//   NEW_FOLDED <title>   相对基线新被折叠的（重点！）
//   RECOVERED <title>    基线被折叠但现已恢复的（申诉成功 / 解除）
// 注意：只读操作（滚动自己的创作者中心），限速内置；基线默认读
//       $WB_SKILLS_DATA/zhihu-yanghao/fold-baseline.json（默认 ~/space/skills-data），
//       换机器不用改代码，参数 baseline / 环境变量 ZHIHU_FOLD_BASELINE 可覆盖。
(async () => {
  const fs = require('fs')
  const path = require('path')
  // 基线是累积的运行时数据，放 skill 目录之外，skill 升级/镜像覆盖都不会丢
  const SKILLS_DATA = process.env.WB_SKILLS_DATA ||
    path.join(process.env.HOME || '', 'space', 'skills-data')
  const BASELINE = process.env.ZHIHU_FOLD_BASELINE ||
    path.join(SKILLS_DATA, 'zhihu-yanghao', 'fold-baseline.json')
  let params = {}
  try { params = JSON.parse(fs.readFileSync('/tmp/zhihu_fold_params.json', 'utf8')) } catch (e) {}
  const baselinePath = params.baseline || BASELINE

  const space = 'zhihu-fold-audit'
  const task = await useOrCreateTaskSpace(space)
  await openOrReuseTab('https://www.zhihu.com/creator/manage/creation/all', { wait: true, timeout: 25 })
  await wait(6)

  // 滚动加载 + 快照累积去重（虚拟滚动，无翻页按钮）
  const seen = {}
  let stableRounds = 0
  for (let step = 0; step < 60; step++) {
    const text = await js('document.body.innerText')
    if (text) {
      let cur = null
      for (const raw of text.split('\n')) {
        const line = raw.replace(/\u200b/g, '').trim()
        let type = null
        if (line.indexOf('回答') === 0 && line.length > 6) type = '回答'
        else if (line.indexOf('想法') === 0 && line.length > 4) type = '想法'
        else if (line.indexOf('文章') === 0 && line.length > 4) type = '文章'
        else if (line.indexOf('提问') === 0 && line.length > 4) type = '提问'
        if (type) {
          cur = { type: type, title: line.slice(2).trim(), folded: false, date: '' }
          const key = type + '|' + cur.title
          if (!seen[key]) seen[key] = cur
          continue
        }
        if (!cur) continue
        const key = cur.type + '|' + cur.title
        if (line === '被折叠' || (line.indexOf('被折叠') >= 0 && line.length < 10)) { seen[key].folded = true; continue }
        if (line.indexOf('发布于') === 0) { seen[key].date = line.slice(3).trim(); continue }
      }
    }
    const before = Object.keys(seen).length
    cliLog('STEP ' + step + ' unique_total=' + before)
    await js('window.scrollTo(0, document.body.scrollHeight)')
    await wait(3)
    const atEnd = await js('(() => { return (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 50); })()')
    if (atEnd && Object.keys(seen).length === before) { stableRounds++ } else { stableRounds = 0 }
    if (stableRounds >= 3) { cliLog('SCROLL_STABLE at step ' + step); break }
  }

  const answers = Object.keys(seen).map(k => seen[k]).filter(x => x.type === '回答')
  cliLog('TOTAL_ITEMS=' + Object.keys(seen).length + ' ANSWERS=' + answers.length + ' FOLDED=' + answers.filter(x => x.folded).length)
  for (const a of answers) cliLog('FOLD_STAT ' + (a.folded ? 'FOLD' : 'OK  ') + ' ' + (a.date || '?') + ' ' + a.title.slice(0, 55))

  // 基线比对
  let baseline = null
  try { baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf8')) } catch (e) {}
  if (baseline && baseline.length) {
    const bMap = {}
    for (const b of baseline) bMap[b.title] = b.folded
    let newFolded = 0, recovered = 0
    for (const a of answers) {
      const prev = bMap[a.title]
      if (a.folded && prev === false) { cliLog('NEW_FOLDED ' + a.title); newFolded++ }
      else if (a.folded && prev === undefined) { cliLog('UNTRACKED_FOLDED ' + a.title + '（基线中无此条，可能从未记录过或标题变动）') }
      else if (!a.folded && prev === true) { cliLog('RECOVERED ' + a.title); recovered++ }
    }
    cliLog('DIFF_SUMMARY new_folded=' + newFolded + ' recovered=' + recovered)
  } else {
    cliLog('NO_BASELINE (path=' + baselinePath + ')，本次仅输出全量状态')
  }

  // 写回基线（带护栏：抓取条数不得少于基线，防滚动不完整污染基线）
  if (params.update) {
    if (baseline && baseline.length && answers.length < baseline.length) {
      cliLog('UPDATE_SKIPPED: answers(' + answers.length + ') < baseline(' + baseline.length + ')，疑似滚动不完整，拒绝覆盖基线')
    } else {
      const snapshot = answers.map(a => ({ date: a.date || '', title: a.title, folded: a.folded }))
      fs.writeFileSync(baselinePath, JSON.stringify(snapshot, null, 1))
      cliLog('BASELINE_UPDATED path=' + baselinePath + ' items=' + snapshot.length)
    }
  }
  await completeTaskSpace(space, { keep: false })
})().catch(function (e) { cliLog('FOLD_AUDIT_ERROR: ' + (e && e.message)) })
