# 替换已发布的视频：三平台删旧发新

改版后要替换已发布的视频时，删除没有现成脚本，下面是实测可用的定位方式。

## 删除入口

| 平台 | 管理页 | 删除入口 | 确认弹窗 |
|---|---|---|---|
| 小红书 | `creator.xiaohongshu.com/new/note-manager` | hover 卡片后 `.note-card__action-btn--del` | `.d-modal`，文本「删除后将无法恢复，确定要删除《标题》」 |
| 视频号 | `channels.weixin.qq.com/platform/post/list` | **内容在 `wujie-app` 的 shadowRoot 里**；hover 行后 `.opr-item-wrap` 内的 `.opr-item`（图标，不是下方 `.action-content` 文字） | `.weui-desktop-dialog`，文本「删除视频」 |
| 抖音 | `creator.douyin.com/creator-micro/content/manage` | 目标行内「删除作品」 | `.semi-modal`，文本「确定要移除此作品吗」 |

四条实测经验：

1. **视频号点文字没反应，必须点图标**。`.action-content`（文字「删除」）点击不触发，事件绑在 `.opr-item`（32×32 图标）上，且要先 hover 到行上让操作区出现。
2. **视频号页面里有多个 `.weui-desktop-dialog`**，第一个可能是「切换视频号」。必须按「删除视频」文本挑，否则会点错或判定成「弹窗不在」。
3. **抖音用 DOM `el.click()` 比坐标点击可靠**。坐标点击后弹窗消失但作品没删（连 toast 都没有）；`el.click()` 立即出现「删除成功」。
4. **抖音作品数标签有缓存**。删除后标题已从列表消失、toast 报「删除成功」，顶部「作品 (N)」仍是旧数字。**核验以列表里标题消失为准，别信数字。**

删完要逐平台核验：小红书看总数是否 -1 + toast，视频号看 `.post-feed-item` 行数 -1，抖音看标题从列表消失。

## 抖音发布失败的两个真实原因

用 `release.sh` 发抖音报 `E_PUBLISH_UNCONFIRMED`（URL 已跳到 `manage?enter_from=publish`，
但作品数没变、列表没新作品），接管后确认**确实没发出去**；改手动流程重发一次即成功
（作品数 4→5）。对比两次差异，补了两处防护：

- **发布按钮可点性没校验**：旧实现只 `window.scrollTo(bottom)` 后取坐标，不 `scrollIntoView`、
  不检查 `disabled`、不校验坐标是否在视口内。按钮被浮层挡住或在视口外时，CDP 点击会静默失效
  （或命中别的元素），页面照样跳转，制造「假成功」。现在先 `scrollIntoView({block:'center'})`，
  再检查 `disabled` 与视口范围，分别报 `E_PUBLISH_BTN_DISABLED` / `E_PUBLISH_BTN_OUT_OF_VIEW`。
- **核验前没有重拉列表**：跳转过来的 manage 页可能带旧缓存，直接读 `body.innerText` 会读不到
  刚发的作品。现在先站内点一次「内容管理」重拉（不刷新、不掉登录态），轮询从 16 秒延到 30 秒。

另一个观察：**话题挂不上时会在描述末尾留纯文本**（如 ` #课本没教的事`）。它不阻断发布，
但发布前值得看一眼描述区是否干净。本项目第二次发布去掉该话题后一次成功。

## 视频号的 `verified: manual` 是正常现象

视频号作品列表**显示描述首句，不是短标题**。`channels.mjs` 拿短标题前 10 字去查自然查不到。
看到 `verified : manual` 不代表没发出，去列表按发布时间确认即可（本项目 01:59 那条就是新版）。
