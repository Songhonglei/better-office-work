---
name: workbuddy-checkin-daemon
description: >
  WorkBuddy「Buddy 加油站」每日签到 + 派猫猫旅行的自动化闭环。通过客户端 wbipc 守护进程
  代理发请求，不读取、不解密、不传输任何 token，兼容新版 $wbEncrypted 加密登录态，
  跨 Windows / macOS / Linux，纯 Python 标准库零依赖。触发词：每日签到、自动签到、
  WorkBuddy 打卡、Buddy 加油站、领积分、派猫猫旅行、猫猫旅行、旅行积分、旅行奖励、还有多久回来
---

# workbuddy-checkin-daemon

- **Version**: 1.0.2
- **License**: MIT (see [LICENSE](./LICENSE))
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-office-work
- **Upstream**: WorkBuddy 技能市场 `workbuddy-checkin-daemon`（原作者 huakui）；本仓库版本修复了派遣必须带 location_id 的问题
- **Changelog**: [CHANGELOG.md](./CHANGELOG.md)

WorkBuddy「Buddy 加油站」每日签到本质是一次带登录态的 HTTP 接口请求，**不需要**模拟点击
GUI，也**不需要**读取本地登录态文件。本技能通过 WorkBuddy 守护进程内置的 wbipc 命名管道，
让守护进程**代为携带登录态**发起官方接口请求——本机脚本接触不到 token，且天然兼容新版
客户端（accessToken 为 `$wbEncrypted` 加密信封，直接读文件会拿到密文）。

> 旧版客户端（明文 token）同样适用本方案。社区版 totorosir-workbuddy-checkin 走的是「直接读
> 登录态明文 token」，新版客户端 accessToken 已是 `$wbEncrypted` 加密信封，读出来是 dict 会直接
> 报错，**不要在新版客户端上使用**。

## 核心逻辑

自带脚本 `scripts/wb_checkin_daemon.py`（纯 Python 标准库，零第三方依赖）：

1. 读取 `~/.workbuddy/wbipc/endpoint.json`（管道地址 + 会话票据，由客户端自动生成）。
2. 与守护进程完成 HMAC 挑战-应答握手（协议细节见 `references/wbipc-protocol.md`）。
3. 通过 `wb.request/http.fetch` 让守护进程代发请求（headers 由守护进程注入，脚本接触不到 token）：
   - `POST /v2/billing/meter/checkin-activity-status` 查询签到状态；
   - 若今日未签 → `POST /v2/billing/meter/daily-checkin` 领取（幂等，已签返回 code=10001）；
   - 派猫猫旅行闭环：`GET /activity/growth/buddy/travel/status` → `arrived` 则 `travel/claim` 领取 →
     `idle` 且未达每日上限则先 `GET /activity/growth/buddy/travel/config` 取可用地点，
     再 `travel/depart` 带 `{"location_id": N}` 派遣（达上限一个写请求都不发）。
4. 输出单行 JSON 结果，全程不打印任何凭据。退出码：成功 0 / 失败 1。

## 安装到其他机器（三种方式，任选其一）

1. **技能市场安装**：在 WorkBuddy 里说「安装 workbuddy-checkin-daemon」，或到【技能管理 / 推荐市场】搜「签到助手」。
2. **手动拷贝**：把整个 `workbuddy-checkin-daemon/` 目录放到
   `~/.workbuddy/skills/`（Windows 为 `%USERPROFILE%\.workbuddy\skills\`），
   确保最终路径形如 `~/.workbuddy/skills/workbuddy-checkin-daemon/SKILL.md`。
   放置后重启 WorkBuddy 或新开一个会话，技能即被识别。
3. **Git 克隆**：`git clone <仓库地址> ~/.workbuddy/skills/workbuddy-checkin-daemon`，后续 `git pull` 即可升级。

装完先自检环境（两条都要成立，否则说明客户端版本过旧或不支持 wbipc）：

```bash
ls ~/.workbuddy/wbipc/endpoint.json          # macOS / Linux
dir %USERPROFILE%\.workbuddy\wbipc\endpoint.json   # Windows
```

- 文件存在 → 支持本方案，直接跑脚本验证。
- 文件不存在 → 客户端过旧（无 wbipc 通道），本技能不可用，需升级 WorkBuddy。

> 每台机器各自独立运行、各自用本机登录态，不需要也不应该共享任何凭据；
> 不要把 `~/.workbuddy/` 下任何登录态文件或 `endpoint.json` 拷给别人。

## 调用本 Skill 时的搭建流程

1. **运行脚本验证**（纯标准库，任意 Python 3.8+ 均可，无第三方依赖）：

   ```bash
   # macOS / Linux
   python3 ~/.workbuddy/skills/workbuddy-checkin-daemon/scripts/wb_checkin_daemon.py

   # Windows（PowerShell / cmd）
   python %USERPROFILE%\.workbuddy\skills\workbuddy-checkin-daemon\scripts\wb_checkin_daemon.py
   ```

   加上 `--no-travel` 则只签到、跳过派猫猫旅行流程。

   - 若系统 `python3` / `python` 不存在，退回 WorkBuddy 托管解释器：
     macOS / Linux 为 `~/.workbuddy/binaries/python/versions/*/bin/python3`，
     Windows 为 `%USERPROFILE%\.workbuddy\binaries\python\versions\*\python.exe`（取最新版本目录）。
   - **零依赖，无需 pip install**；也不需要设置任何环境变量或配置 token。
   - 前提：WorkBuddy 客户端正在运行且已登录（守护进程随客户端启动）。
   - 客户端刚重启过属正常：endpoint/ticket 会轮换，重跑即可。

2. **解读 JSON 结果并汇报**：
   - `action=clicked`：签到成功，领取 `credit_gained` 积分，连续 `streak_days` 天；
     `balance` 非 null 时附「当前积分余额：X」。
   - `action=skip_already_signed`：今日已签到，幂等跳过（附余额与连续天数）。
   - `status=error`：如实报告 `msg` 失败原因（常见：客户端未运行/未登录/未联网），不得谎报成功。
   - `travel` 字段：`traveling` → 正在 `location_name` 旅行，约 `remaining_text` 后到达；
     `arrived` → 已到达，`auto_log` 显示领取结果；`auto_log` 逐条照实转述；
     `travel.available=false` → 只说「旅行状态未能获取」，不要编造状态。

3. **创建每日定时（WorkBuddy 自带自动化，不要用 crontab / 系统计划任务）**：
   用 `automation_update`（mode=create）创建 recurring 自动化：
   - name：`WorkBuddy签到助手 · 每日自动签到`
   - rrule：`FREQ=DAILY;BYHOUR=9;BYMINUTE=0`
   - status：`ACTIVE`
   - prompt 模板与完整约束见 `README.md`「每日 9 点自动签到」一节；要点：运行上述脚本、
     按 JSON 字段汇报、严禁打印任何 token/ticket 凭据、重试不超过 1 次、失败如实报告。

## 排错速查

- `cannot open pipe` / `wbipc frame timeout`：客户端未运行或刚重启（endpoint 已轮换），打开客户端后重跑。
- `wb.request pipe 不可见`：客户端未登录或会话不可用，登录后重试。
- `code=10001`：今日已签到，幂等安全返回，不是错误。
- 「今日派遣次数已用完」：服务端每日限额，次日自动恢复，不是故障。
- `code=400` / `location not available`：`travel/depart` **必须**带 body `{"location_id": N}`，
  空 body 会一律 400 invalid request。地点 id 一律从
  `/activity/growth/buddy/travel/config` 的 `data.locations[].id` 现取（`sort` 字段为展示顺序），
  不要硬编码地点 id —— 官方会随时新增地点。
- 脚本偶发被外部 SIGTERM 杀掉：本机安全策略干扰，重跑即可。
- 客户端重启后 `E_REVOKED`：endpoint/ticket 已轮换，重新读 endpoint.json 重连。

## 安全约束（务必遵守）

- 只读取 `wbipc/endpoint.json`；**绝不**打开登录态文件 `workbuddy-desktop.info`，
  绝不修改或删除其内容，任何输出不得包含 token / ticket / 推送凭据。
- 写操作仅限已验证的 3 个端点：`daily-checkin`、`travel/claim`、`travel/depart`；
  不调用兑换、抽奖等未经验证的接口，不为推送额外引入依赖。
- 不修改 `wb_checkin_daemon.py` 以外的任何 WorkBuddy 配置；不做无限重试（内部最多 1 次）。
- 不要在网页版尝试签到（网页版无签到入口，仅 PC 客户端专属）。
