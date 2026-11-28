---
name: weibo-chaohua-signin
version: 1.0.0
description: 每天自动给指定微博超话签到（默认张韶涵超话），基于 ego-browser 中已存在的微博登录态调用官方 PC 端签到接口，并报告连续签到天数。触发词：微博超话签到、签张韶涵超话、超话打卡、weibo checkin。
---

# 微博超话自动签到

用 ego-browser 打开微博超话页，在页面上下文里调用微博自己的签到接口完成打卡。cookie 只存在于 ego-browser 的 profile 中，不落盘、不导出。

## 签到接口（已实测固化）

```
POST https://weibo.com/ajax_proxy/chaohua/page/checkin
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

body:
  scene_id=pc_checkin
  page_id=<超话 page_id，形如 100808...>
  timezone=<Intl 时区>
  lang=zh-cn
  plat=<navigator.platform>
  ua=<navigator.userAgent>
```

响应 code 含义：

| code | 含义 | 脚本退出码 |
|---|---|---|
| 100000 | 签到成功（返回 title / sub_title） | 0 |
| 382004 | 今天已签到（幂等，视为达成） | 0 |
| 100003 | 请先登录 —— cookie 过期，需重新登录 | 2 |
| 其他 | 失败 / 风控拦截 | 1 |

已知超话 page_id：张韶涵 `1008083da293788e69d1df81b6832c26b94d34`。

## 连续签到天数

签到后输出「连续签到 N 天」，数据源按优先级取：

1. **页面**：读 `document.documentElement.textContent`，匹配 `连续签到 N 天`；命中则 `src=page`。
2. **本地日志**：页面没给出时，按 `~/.skill-data/weibo-chaohua-signin/logs/*.log` 从今天逐日回溯，某天有 `code=100000` 或 `382004` 即计一天，`src=log`。

实测（2026-11-18）：PC 超话页只有「已签到」「今日签到 N 人」，签到接口只回 `code/msg`，`/ajax_proxy/chaohua/page/checkin/info`、`/checkin/status`、`/level`、`/score` 等查询接口全部 404。所以页面口径目前拿不到，实际走日志回溯。

日志回溯是**下限**：回溯到日志最早一天仍连续时输出带 `+`（如 `连续签到 32 天+`），表示真实天数只会更多。本 skill 日志从 2026-10-18 起记录，更早的天数覆盖不到。

## 依赖

- `ego-browser`（ego-lite）—— 提供已登录微博的浏览器环境，需在 PATH 中
- 系统命令：`bash`、`grep`、`date`（macOS 自带，`date -j -v` 与 GNU `date -d` 均已兼容）

## 前置条件

ego-browser 里微博必须是登录态。首次配置流程：

1. `useOrCreateTaskSpace` 建一个 space，打开 `https://weibo.com/page/<page_id>`
2. 点右上角「登录」，`handOffTaskSpace` 把控制权交给用户扫码
3. 用户确认登录后 `takeOverTaskSpace`，验证页面出现「已关注 / 已签到」

登录态是 **profile 级** 的（已实测：新建 task space 同样继承登录态），所以不依赖某个窗口存活，也不依赖 task space 是否关闭。

## 用法

```bash
bash ~/.workbuddy/skills/weibo-chaohua-signin/scripts/checkin.sh
```

输出形如：

```
STATUS=ok  张韶涵超话 签到成功 连续签到 32 天+
```

可选环境变量：

- `WEIBO_PAGE_ID` — 换超话时覆盖，默认张韶涵
- `WEIBO_TOPIC_NAME` — 日志里显示的名字，默认张韶涵
- `WEIBO_EGO_SPACE` — ego-browser task space 名，默认 `weibo daily signin`
- `WEIBO_LOG_DIR` — 日志目录，默认 `~/.skill-data/weibo-chaohua-signin/logs`（skill 目录外，更新或重装不丢历史记录）

日志按天写在 `~/.skill-data/weibo-chaohua-signin/logs/YYYY-MM-DD.log`，每行含 `code`、`msg`、`streak`、`src`：

```
[2026-11-18 20:56:16] 张韶涵 code=382004 msg=今天已签到 streak=32 src=log
```

## 定时任务

`scripts/run-daily.sh` 是 launchd 包装器：调用 `checkin.sh`，签到成功时弹桌面通知（含连续签到天数），当天已签到则静默不打扰。

```bash
launchctl load ~/Library/LaunchAgents/com.songhonglei.weibo-chaohua-signin.plist
```

默认每天 11:30 触发。plist 里必须显式写 `PATH`（含 `~/.local/bin`）和 `HOME`，否则 launchd 找不到 `ego-browser`。

## 设计约定

- 脚本复用固定的 task space 且**跑完不关闭**，让浏览器指纹和会话保持连续，行为更接近真人，降低风控概率。
- 每天只调用一次，不要循环重试。签到接口幂等，重复调用只返回「今天已签到」。
- 返回退出码 2（登录失效）时不要自动重试，交给用户重新扫码登录。
- 连续天数不额外发请求，只读页面文案与本地日志，避免多余调用加重风控。

## 换超话 / 加超话

拿 page_id：在 ego-browser 里打开该超话主页，URL 形如 `https://weibo.com/page/<page_id>`，或看页面请求 `https://weibo.com/ajax_proxy/chaohua/page?flowId=<page_id>`。
