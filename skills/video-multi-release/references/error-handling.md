# 失败处理与错误码对照（video-multi-release）

**加载时机**：脚本返回非零退出码、或 FAILED 块里的 `code` 看不懂时。正常发布不需要读。

主文档 `SKILL.md` 只给「exit → 该干什么」的粗表；这里是完整的 `code ↔ exit ↔ step ↔ 平台` 对照，
以及每个码背后的真实成因。

## 1. 退出码总表

`EXIT` 常量定义在三个 `.mjs` 顶部，各平台略有差异：

| exit | xhs.mjs | channels.mjs | douyin.mjs | 含义 |
|---|---|---|---|---|
| 0 | ✓ | ✓ | ✓ | 成功 |
| 10 | ✓ | ✓ | ✓ | 参数 / 文件校验失败，无副作用 |
| 11 | ✓ | ✓ | ✓ | 依赖缺失（wujie 未渲染、找不到 file input） |
| 12 | ✓ | ✓ | ✓ | 任务空间被占用 / `SPACE_ID` 无效 |
| 20 | ✓ | ✓ | ✓ | 未登录 |
| 21 | ✓ | — | — | 找不到「上传视频」tab（仅小红书） |
| 30 | ✓ | ✓ | ✓ | 上传失败 / 超时 |
| 40 | ✓ | ✓ | ✓ | 填表失败（含**抖音按钮 disabled**） |
| 50 | ✓ | ✓ | ✓ | 话题没挂上 |
| 60 | ✓ | ✓ | ✓ | 封面处理失败（**已降级，通常不阻断**） |
| 70 | ✓ | ✓ | ✓ | 提交按钮点不到（视口外 / 被遮挡） |
| 75 | — | — | ✓ | 需要人工验证（抖音短信） |
| 80 | ✓ | ✓ | ✓ | 提交后未确认（列表里没找到） |
| 90 | ✓ | ✓ | ✓ | 未捕获异常 / 输出丢失 |

**两处易错**：

- **抖音的 `E_PUBLISH_BTN_DISABLED` 走 40，不是 70。** `EXIT.FORM` 被复用为「表单校验没过」，
  而同为提交阶段的 `E_PUBLISH_BTN_OUT_OF_VIEW` 才走 70。别按「都是提交按钮问题」归到一档。
- **`$?` 不可信。** `ego-browser nodejs` 会把子进程退出码统一改写成自己进程的 `1`，
  真实码只打在 stdout 的一行 `ego's nodejs process exited with code NN.` 里。
  `release.sh` 从 FAILED 块的 `exit : NN` 解析真实码并汇总，**看汇总表，别在 shell 里看 `$?`**。

## 2. code → exit → step 完整对照

### 通用（三个平台都有）

| code | exit | step | 成因 / 处置 |
|---|---|---|---|
| `E_SPACE_ID_INVALID` | 10 | task-space | `SPACE_ID` 不是一个存在的空间号。核对后重跑，别硬猜 |
| `E_SPACE_CLAIM_FAILED` | 12 | task-space | 认领失败，常因空间已被别的会话占着。先 `completeTaskSpace(N,{keep:false})` 再跑 |
| `E_SPACE_OWNED` | 12 | task-space | 同名空间还在（上次失败保留了现场）。复用或清理，见主文档「失败之后怎么重跑」 |
| `E_AUTH_EXPIRED` | 20 | auth | 未登录。小红书/视频号扫码后重跑；**抖音必须带 `SPACE_ID` 或 `RESUME=1`**，裸跑会 reload 杀掉刚扫的码 |
| `E_UPLOAD_TIMEOUT` / `E_VIDEO_UPLOAD_TIMEOUT` | 30 | upload | 上传超时。先查体积（见 `release-behavior.md` 的 `MAX_VIDEO_MB`），再查文件能否正常播放 |
| `E_EDITOR_MISSING` | 40 | fill-desc | 找不到正文编辑器（tiptap / wujie 内）。多半是页面没加载完或改版 |
| `E_DESC_NOT_APPLIED` | 40 | fill-desc | 描述写进去了但回读不一致。接管看是否被长度截断 |
| `E_TITLE_NOT_APPLIED` | 40 | fill-title | 标题回读不一致，常见于含非法字符被平台清洗 |
| `E_PUBLISH_UNCONFIRMED` | 80 | verify | **点了发布但列表里没找到。不要立即重发**，接管点「内容管理」重拉列表再决定 |
| `E_UNEXPECTED` | 90 | internal | 未捕获异常。看日志尾部；常见是页面改版或 ego 交权 |

### 小红书（xhs.mjs）

| code | exit | step | 成因 / 处置 |
|---|---|---|---|
| `E_VIDEO_TAB_NOT_FOUND` | 21 | ensure-tab | 上传视频 tab 没出现，或 file input 一直不来。接管手动点 tab |
| `E_BODY_NOT_APPLIED` | 40 | fill-desc | 正文写入失败（小红书用的 code，语义同视频号的 `E_DESC_NOT_APPLIED`）。重跑；反复失败接管手填 |
| `E_NO_PUBLISH_HOST` | 70 | submit | 找不到 `<xhs-publish-btn>` 宿主元素。页面改版时更新 `SEL.publishHost` |
| `E_NO_ONSAVE` / `E_NO_ONPUBLISH` | 70 | submit | 宿主要在，但内部方法没了。组件升级导致，需重新探方法名 |
| `E_SAVE_DISABLED` / `E_SUBMIT_DISABLED` | 70 | submit | 组件自身置了 `save-disabled` / `submit-disabled`。**先查表单校验红字**，别查网络 |
| `E_COVER_AREA_MISSING` | — | set-cover | `.cover` 缩略图不存在或宽 < 50px（图片没渲染完） |
| `E_COVER_ENTRY_HIDDEN` | — | set-cover | `.cover-edit-entry` 悬停 8 次仍 `0×0`。**这是改版后的常态**，不是 bug |
| `E_COVER_EDITOR_NOT_OPEN` | — | set-cover | 点了「编辑封面」但 15 秒内没出 file input |
| `E_COVER_DONE_BTN_MISSING` | — | set-cover | 找不到「完成」按钮（`.circle-button` + 文本「完成」） |
| `E_COVER_NOT_APPLIED` | — | set-cover | 前后 `backgroundImage` 完全相同，图没真正替换 |

> **`E_COVER_*` 现在都不返回退出码。** `xhs.mjs:378` 起只要 `cv.ok === false` 就打一行
> `⚠ 自定义封面没设上（CODE），保留平台自动封面，继续发布`，然后照常提交。
> 早期版本会 `exit 60` 中止——那行为已经废弃，看到 exit 60 说明是旧脚本或别的平台。

### 视频号（channels.mjs）

| code | exit | step | 成因 / 处置 |
|---|---|---|---|
| `E_WUJIE_MISSING` | 11 | open-page | 页面里没有 `wujie-app`。**注意「未登录」必须先判**——登录页本身就没有 wujie，顺序错了会把未登录误报成依赖问题 |
| `E_NO_FILE_INPUT` | 11 | upload | 上传区找不到 file input（需 CDP `pierce:true` 穿透 shadowRoot） |
| `E_SHORT_TITLE_MISSING` | 40 | fill-title | 找不到短标题输入框。短标题上限 **16 字**，见主文档平台差异表 |
| `E_SUBMIT_BUTTON` | 70 | submit | 「发表」点不到。多为视口外（实测 `y=1268`），`clickByText()` 会返回 `out_of_view` 而不是盲点 |

> **视频号 `E_PUBLISH_UNCONFIRMED` 只告警不判失败。** 列表不一定展示短标题，
> 查不到时 OK 块输出 `verified: manual`，仍需人工确认。

### 抖音（douyin.mjs）

| code | exit | step | 成因 / 处置 |
|---|---|---|---|
| `E_EDITOR_TIMEOUT` | 30 | upload | 上传页编辑器迟迟不出来 |
| `E_UPLOAD_FAILED` | 30 | upload | 页面出现「上传失败」，立即报错（不等到超时） |
| `E_UPLOAD_NOT_FINISHED` | 30 | upload | 轮询耗尽仍看到「上传中 / xx%」 |
| `E_NO_PUBLISH_BTN` | 70 | submit | 找不到发布按钮 |
| `E_PUBLISH_BTN_DISABLED` | **40** | submit | 按钮 disabled，按表单校验未过处理 |
| `E_PUBLISH_BTN_OUT_OF_VIEW` | 70 | submit | `scrollIntoView` 后仍不在视口内 |
| `E_HUMAN_VERIFY_REQUIRED` | 75 | submit | 命中短信二次验证。**任何自动化都绕不过**，让用户输码 |

### 入口层（release.sh）

这些在启动浏览器之前就返回，`exit 10`，零副作用：

| code | 触发条件 |
|---|---|
| `E_PARAM_VIDEO` | 没传 `VIDEO` |
| `E_VIDEO_NOT_FOUND` | `VIDEO` 路径不存在 |
| `E_VIDEO_FORMAT` | 扩展名不在视频白名单 |
| `E_COVER_NOT_FOUND` | `COVER` 路径不存在 |
| `E_PARAM_TITLE` | 没传 `TITLE` |
| `E_DESC_TOO_LONG` | `DESC` 超 1000 字 |
| `E_PARAM_MODE` | `MODE` 不是 `stage`/`draft`/`publish` |
| `E_PARAM_PLATFORMS` | `PLATFORMS` 含未知平台 |
| `E_UNKNOWN_PLATFORM` | 同上，另一条分支 |
| `E_TRANSCODE_FAILED` | 体积超阈值后 ffmpeg 转码失败（`what_now` 给手动命令与跳过开关） |

## 3. 常见故障的判断顺序

**按钮整行禁用 → 先查校验，别查网络。** 这是踩过的最大弯路：曾在网络层空转一小时，
实际只是表单校验没过。第一动作是把整页（含视口外）的校验红字、必填提示全找出来。

| 现象 | 先查 | 别急着做的 |
|---|---|---|
| 按钮灰 / 点不动 | 表单必填项、短标题非法字符（视频号逗号）、封面是否就绪 | 换网络、重装依赖 |
| 上传卡 0% | 文件体积（视频号 78MB 必超时）、文件能否本地播放 | 反复重试（删后重传会永久卡 0%） |
| 点了发布没反应 | 按钮是否在视口内、`scrollIntoView` 后是否重取坐标 | 判定「平台拒发」 |
| 报未登录但其实刚扫码 | 是否裸跑（无 `SPACE_ID`/`RESUME`）触发 `Page.reload` | 再次重跑（login 态撑不过 reload） |
| 内容填了又没了 | 是否在提交前刷新过页面（抖音刷新即清空） | 反复重填 |

## 4. 手工接管与清理

失败默认 `KEEP_ON_FAIL=1`，空间不销毁、页面留着。但 ownership 会回到 user，
所以接管必须 `claimTaskSpace`，**不是** `takeOverTaskSpace`（后者只适用于 ownership 仍是 agent 的空间）。

```bash
# 接管
ego-browser nodejs -e "await claimTaskSpace(12)"
# 排障必须用脚本同款空间名，否则连到的是别的 tab
ego-browser nodejs -e "await claimTaskSpace(12); await taskSpace('publish channels video')"

# 用完清理
ego-browser nodejs -e "await completeTaskSpace(12, { keep: false })"
```

清理后**不要再清一次**——空间没了登录态一起没，得重新扫码。
