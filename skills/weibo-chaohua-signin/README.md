# weibo-chaohua-signin

每天自动给微博超话签到（默认张韶涵超话），并报告连续签到天数。基于 ego-browser 中已存在的微博登录态调用官方 PC 端签到接口，cookie 不落盘、不导出。

## 特性

- **官方接口签到**：`POST https://weibo.com/ajax_proxy/chaohua/page/checkin`
- **幂等**：`382004 今天已签到` 视为达成，不重试、不重复打卡
- **连续签到天数**：页面文案优先；页面未提供时按本地日志逐日回溯，是下限时用 `+` 标注
- **登录态失效**：`100003` 返回退出码 2，提示重新扫码，绝不自动重试
- **定时通知**：`run-daily.sh` 包装器签到成功弹桌面通知（含连续天数），当天已签到则静默

## 安装

```bash
git clone https://github.com/Songhonglei/better-office-work.git
cp -r better-office-work/skills/weibo-chaohua-signin ~/.workbuddy/skills/
```

依赖 `ego-browser`（ego-lite），并在其中登录微博账号（登录态是 profile 级，只存在浏览器里）。

## 用法

```bash
bash ~/.workbuddy/skills/weibo-chaohua-signin/scripts/checkin.sh
```

输出示例：

```
STATUS=ok  张韶涵超话 签到成功 连续签到 32 天+
```

退出码：`0` 成功或已签到 · `1` 失败/风控 · `2` 登录失效 · `3` 浏览器不可用

## 换超话

```bash
WEIBO_PAGE_ID=<page_id> WEIBO_TOPIC_NAME=<name> \
  bash scripts/checkin.sh
```

`page_id` 取自超话主页 URL：`https://weibo.com/page/<page_id>`。

## 数据位置

签到日志写在 `~/.skill-data/weibo-chaohua-signin/logs/`，位于 skill 目录之外，更新或重装 skill 不会丢失历史记录，连续天数得以延续。

## 定时任务

`scripts/run-daily.sh` 是 launchd 包装器，配套 plist 见 `SKILL.md`「定时任务」一节。

## License

MIT © 2026 Evan Song
