# 配图决策与插图执行（zhihu-yanghao v1.5.0）

> 2026-11-06 首次跑通「回答内嵌多图」，本文件把决策与实现固化下来。

## 0. 硬规则：每次发布回答前必须先问用户

**配图方式由用户决定，agent 不得替用户选、也不得默认沿用上一次。**
在正文定稿、去 AI 味门禁通过之后、填入编辑器之前，用 `AskUserQuestion` 问一次：

| 选项 | 说明 |
|---|---|
| **网络图** | 找可自由使用的实拍/史料图（Wikimedia Commons 等），下载到本地后上传知乎图床，文末署名 |
| **用 batch-image-gen 生成** | 走批量生图 skill（本机实名为 `imagegen-batch`），按用户风格生成配图，文末标注 AI 生成 |
| **不配图** | 纯文字发布，正文不留「【图1】」之类占位 |

- 三选项之外用户可自填（例如「用我给的图片，路径 …」），按用户给的路径走共用插图流程。
- **无人值守例外**：定时任务自动触发、无法向用户提问时，默认按「不配图」发布（最保守），日报记 `ILLUSTRATION: 不配图（无人值守默认）`；不要在无人值守时自行选网络图或生成图。
- 询问时把**正文主题 + 建议张数**说清楚（默认 1–2 张，上限 2 张，`config.publish_gates.illustration.max_images`）。
- 用户选了配图之后，**发布前还要再确认一次**：把编辑器截图 + 两张原图 + 定稿全文一起 `present_files` 给用户，`AskUserQuestion` 拿明确同意才点发布（对外发布铁律）。
- 想法 / 动态（`post_moment.js`）不走本流程——本文件只针对回答。

## 1. 三条执行路径

### A. 网络图（史料 / 古迹 / 器物类首选）

1. **找图**：优先 Wikimedia Commons API，按主题分类列文件 + 取授权信息。
   ```bash
   curl -s 'https://commons.wikimedia.org/w/api.php?action=query&generator=categorymembers&gcmtitle=Category:Cloud%20Platform%20at%20Juyongguan&gcmtype=file&gcmlimit=20&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth=1200&format=json' \
     | python3 -c "import sys,json; d=json.load(sys.stdin); [print(p['title'], p.get('imageinfo',[{}])[0].get('thumburl')) for p in d.get('query',{}).get('pages',{}).values()]"
   ```
   个别缩略图走 `thumb.wikimedia.org`，`upload.wikimedia.org/.../thumb/...` 取不到时换域名或取原图 `url`。
2. **查授权**：`extmetadata` 里 `LicenseShortName` + `Artist`；只取 **CC BY / CC BY-SA / Public Domain** 等允许再使用的，记下作者与协议。
3. **验画面**：下载后用 `ViewImage` 逐张看，确认拍的是正文里说的东西（2026-11-06 实测：文件名看着对、实际画面未必对，有一张是券洞外观不是刻文特写）。不要用没看过的图。
4. **存本地**：统一放 `/tmp/zhihu_imgs/` 一类的临时目录，**必须下载到本地文件**再上传，不要给知乎热链外站 URL。
5. **文末署名**：正文最后一段写清来源，例：
   `配图来自 Wikimedia Commons，摄影 BabelStone，CC BY-SA 3.0。`
   这一段计入正文字数，去 AI 味门禁要连它一起检查。

⚠️ 授权不清、带水印、含文字/Logo 的图一律不用。署名行不是可选项。

### B. batch-image-gen 生成（抽象概念 / 心理类，或找不到合适实拍图时）

用户口中的 `batch-image-gen`，本机对应 skill **`imagegen-batch`**（`~/.workbuddy/skills/imagegen-batch/`）。加载该 skill 后按其规范执行，要点：

- **提示词开头加唯一前缀**（场景词或「图01」「图02」），防同秒生成互相覆盖；**顺序发**，不要并行（并行 3 张以上易 `ECONNRESET`）。
- 中文提示词直接写中文，不用 `\uXXXX` 转义拼。
- 右下角留白避让 AI 水印，但**不要假设指令生效**——按 skill 的「量水印 → 按量裁」流程裁掉，交付前核对图片数量。
- 用户默认风格：历史类 = **水墨历史写实**（造型写实 + 水墨晕染 + 宣纸底纹、暖橙天光作唯一暖色锚点，无文字/印章/落款）；非历史类 = **温暖简笔哲思风**（黑白线稿、大量留白、淡黄淡橙点缀）。风格统一后缀照抄 `imagegen-batch/references/style-library.md` 与用户偏好。
- 文末标注 `配图为 AI 生成。`，与网络图的署名区分开。
- ⚠️ **账号风险**：知乎对「内容疑似 AI 生成」有专项治理（见 SKILL.md 关键陷阱）。账号处于解封观察期、近期被贴过 AI 标签或成批折叠时，**优先选网络图或不配图**；确需生成图，正文更要过第 5 节去指纹化规范（第一人称真实经历、开头句式轮换）。

### C. 不配图

- 正文文件里不要留图片占位行；直接走 `run_shift.js` / `write_answer.js` 纯文本路径。
- 不配图不影响去 AI 味门禁，两道门禁照走。

## 2. 共用插图流程（2026-11-06 实测可用）

`run_shift.js` 的纯文本路径**不支持插图**——插图必须用新版 ego-browser API 手工编排（一次性 heredoc，不发布）：

```js
const fs = await import('node:fs/promises');
const t = await taskSpace('zhihu-publish-YYYYMMDD');   // 新版 API：taskSpace() / t.page()
const p = t.page('p1');
await p.goto('https://www.zhihu.com/question/' + qid);

// 开编辑器
await p.evaluate(() => {
  const b = Array.from(document.querySelectorAll('button'))
    .find(x => (x.innerText || '').includes('写回答'));
  if (b) b.click();
});
await p.waitForSelector('.public-DraftEditor-content', { state: 'visible', timeout: 20000 });

// 分段粘贴（ClipboardEvent，Draft.js 只认这个）
async function pasteText(txt) {
  return await p.evaluate(function (s) {
    const ed = document.querySelector('.public-DraftEditor-content');
    ed.focus();
    const r = document.createRange(); r.selectNodeContents(ed); r.collapse(false);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    const dt = new DataTransfer(); dt.setData('text/plain', s);
    ed.dispatchEvent(new ClipboardEvent('paste',
      { clipboardData: dt, bubbles: true, cancelable: true, composed: true }));
    return ed.innerText.length;
  }, txt);
}

// 关键：编辑器里有隐藏的图片上传控件，不必点界面按钮
await p.setInputFiles('input[accept*="image"]', '/tmp/zhihu_imgs/图1.jpg');
await p.waitForTimeout(9000);   // 等上传完成，短了会拿到未完成的 img
```

- **顺序**：`段1 → 上传图1 → 段2 → 上传图2 → 剩余段落（含文末署名）`。每段粘贴后 `waitForTimeout(1200~1500)`，每次上传后等 8–10 秒。
- **🚫 禁止连续空行（11/7 + 11/11 两次实测）**：图后 / 署名前粘贴下一块时**直接 `pasteText(paras[i])`，不带 `'\n\n' +` 前缀**（图片是独立 block，光标已在新段落位置，补 `\n\n` 会多生成一个空段落）。同一粘贴块内部也一律用**单换行** `paras.join('\n')`——11/11 dry run 用 `join('\n\n')` 出现 `extraBlank=true`，改单换行后 `doubleBlank=false / extraBlank=false` 全绿。块与块之间一律裸贴。dry run 必须校验 `doubleBlank` / `extraBlank` 都为 false，否则不进入发布确认。
- **隐藏 input**：`input[accept*="image"]`，即使工具栏的图片按钮没点过也存在（2026-11-06 探针确认）。
- **旧版 API**（`useOrCreateTaskSpace` + `js()`）能开编辑器，但**没有 `setInputFiles`**，插图必须走新版 `taskSpace()/page()`。
- **正文禁止 Markdown**（`**` / `- ` 会字面残留）；段落用**单换行** `\n` 切分后逐段粘贴（文案三条硬要求的「干净利落」含排版：段间不留连续空行）。

### 发布前 dry run 校验（必做，任一不过不发布）

```js
const s = await p.evaluate(() => {
  const ed = document.querySelector('.public-DraftEditor-content');
  const imgs = Array.from(ed.querySelectorAll('img'))
    .map(i => ({ ok: i.complete && i.naturalWidth > 0, host: (i.src || '').split('/')[2] }));
  return { imgs, len: ed.innerText.length, head: ed.innerText.slice(0, 40) };
});
await p.screenshot({ path: '/tmp/zhihu_editor_preview.png' });
```

判定标准：
1. `imgs.length === 张数` 且**每张 `ok === true`**；
2. `src` 已落到知乎图床（`pic-private.zhihu.com` / `pic*.zhimg.com`），不是 blob / 外站直链；
3. 截图里**段落与图片顺序正确**、无上传失败弹窗；用 `ViewImage` 看过截图再给用户确认；
4. 编辑器字数与定稿文件字数对得上（含文末署名）；
5. **排版紧凑校验（11/7 新增）**：`ed.innerText` 中**不得出现 `\n\n\n`（连续空行）**——出现即说明有空段落，用户会在知乎看到超大段间距。检查方式：

```js
const s = await p.evaluate(() => {
  const ed = document.querySelector('.public-DraftEditor-content');
  return { extraBlank: /\n\n\n/.test(ed.innerText), tail: ed.innerText.slice(-90) };
});
// extraBlank === true 时：粘贴块还差空行处理，禁止进入发布确认
```

### 发布（一次性，不重试）

- 发布前按风控等 60 秒；按钮匹配用 `[\u200b\s]+` 清洗后 ∈ `["发布回答","提交回答"]`，回退「发布」仅在编辑器存在时。
- 只点一次；用 `waitForFunction(() => /\/answer\/[0-9]+/.test(location.href))` 等真实 URL 跳转，卡住即停不重试。
- 发布后跑 `verify_via_cli.js` + `fold_audit.js`；CLI `me contents` 最新一条 Summary 里出现 `[图片]` 可佐证配图确实带上了。

## 3. 坑清单

| 坑 | 处理 |
|---|---|
| 缩略图 URL 404 / 下载到 HTML | 换 `thumb.wikimedia.org` 域名或取 `imageinfo.url` 原图；`file` 命令验 JPEG |
| 图片文件名对、画面不对 | 必须 `ViewImage` 逐张验，不靠文件名 |
| 上传后 `img` 存在但白图 | 等 9 秒 + 判 `naturalWidth > 0`，别只看 `imgs.length` |
| 编辑器里图片顺序错乱 | 严格「粘一段 → 等 → 传一张 → 等」，不要先粘完全文再批量传图 |
| 编辑器已开过（人工接管后） | 重跑时 `写回答` 按钮可能已消失；复用现有编辑器，发布后用 CLI 逐字核对正文防污染 |
| 同页反复上传 / 补发 | 计入操作密度风控；同一问题页失败最多重试 1 次，再失败等 1–2 小时 |
| 配图后正文字数变化 | 文末署名行计入正文，字数护栏与去 AI 味门禁都要用**最终正文文件**跑 |

## 4. 风控不变

配图不改变任何红线：单班 ≤ 1 回答、发布前闲逛 5 分钟 + 等 60 秒、零互动或按 config 互动、发布后慢节奏离开。上传图片属于页面操作，别为试错在同页反复开编辑器。

## 5. 编辑**已发布**回答配图（2026-11-07 实测，血泪版）

给旧回答补图与写新回答是**两套完全不同的物理规则**，不要混用上面的流程。

**能做的**
1. 文章页点「编辑回答」进编辑态（`#write` 后缀不会自动开编辑器，必须点按钮）。
2. `input[accept*="image"][type=file]` 直接 `setInputFiles` 可上传并插入图片，约 12–13 秒完成，`src` 落到 `pic-private.zhihu.com`。
3. 图片注释 = 点 `FIGCAPTION.Image-caption` 唤出**无 class 的 textarea**；必须 `p.keyboard.type(文字)` 真实键入，**失焦（blur）后才提交生效**；用 native setter + `input` 事件写 value 不触发 React onChange，页面仍显示占位文案。
4. 「提交修改」按钮文案固定为「提交修改」（不是「发布修改」），常态 `disabled:false`。

**做不到的（别再试，实测全部失败）**
| 想做的事 | 结果 |
|---|---|
| 把图插到指定段落中间 | ❌ 位置固定（本次实测=正文最前面），设光标/面板上传/先粘后插都改不了 |
| DOM 清空编辑器重排全文 | ❌ `selectNodeContents` + `delete` 只清 DOM，Draft.js `editorState` 未变；下一次 `insertText`/`paste` 会把原文整段渲染回来 |
| 清空后 `ClipboardEvent` 粘贴 | ❌ 无效（chars 恒 0），与 9/1 结论一致 |
| 剪贴板移动图片块 | ❌ `Meta+x` 对 atomic block 无效，`Meta+v` 还会写入脏字符 |
| 「保存草稿并离开」清脏草稿 | ❌ 保存的是上一次自动备份，脏内容仍在 |

**撤销栈污染（最危险）**：删除残留块 + 撤销 + 粘贴混用后，**早先删掉的幽灵内容会被重新渲染出来**（本次出现过重复段落、「测试乙」）。一旦发现编辑器内容与预期不符，立刻停手，别继续删/撤。

**唯一的复位手段（记牢）**
`草稿备份` → 选 **「…发布过的版本」** → `恢复此版本` → 编辑器回到干净已发布正文（本次恢复到 617 字 / 0 图 / 无幽灵）。这是清掉脏草稿唯一可靠入口。

**结论性建议**：编辑已发布回答配图，自动化只做到「上传 2 张 + 写图注 + 截图核对」，**位置调整交给用户人工拖**；不要在编辑态做任何删除/撤销/清空实验。
