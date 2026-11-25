# workbuddy-checkin-daemon

> WorkBuddy「Buddy 加油站」每日签到 + 派猫猫旅行全自动闭环 —— **token 不落地**，跨 Windows / macOS / Linux。

路径：`skills/workbuddy-checkin-daemon` ｜ 版本：v1.0.2 ｜ 许可：MIT

## Features

- **签到**：查状态 → 未签则领取，接口幂等，重复运行不会重复发积分
- **派猫猫旅行**：`arrived` 自动领旅行积分、`idle` 自动选地点派遣（含每日上限判断）
- **零凭据**：不读、不解密、不传输任何 token；走客户端 wbipc 本地通道，由守护进程代发请求
- **零依赖**：纯 Python 标准库（3.8+），不需要 `pip install`
- **跨平台**：Windows 命名管道 / macOS / Linux Unix socket 同一份代码
- **可定时**：配合 WorkBuddy 自带自动化，每天 09:00 无人值守

## Why

「Buddy 加油站」每日签到本质是一次带登录态的 HTTP 请求，与旧版签到技能的差别：
**不读取本地登录态 token**，而是通过 WorkBuddy 守护进程的 wbipc 命名管道让守护进程代发
官方接口请求，token 全程只存在于守护进程内存中。兼容新版 WorkBuddy（登录态为
`$wbEncrypted` 加密信封格式的版本），旧版明文 token 机器同样可用。

## 安装

三种方式，任选其一：

| 方式 | 操作 | 适合 |
|---|---|---|
| 技能市场 | 在 WorkBuddy 里说「安装 workbuddy-checkin-daemon」，或【技能管理 / 推荐市场】搜「签到助手」 | 普通用户，一键装 |
| 手动拷贝 | 把 `workbuddy-checkin-daemon/` 整个目录放进 `~/.workbuddy/skills/`（Windows：`%USERPROFILE%\.workbuddy\skills\`） | 内网 / 离线机器 |
| Git 克隆 | `git clone <仓库地址> ~/.workbuddy/skills/workbuddy-checkin-daemon` | 需要跟踪更新 |

放置后路径必须是 `~/.workbuddy/skills/workbuddy-checkin-daemon/SKILL.md`（多套一层目录会导致识别不到），
然后重启客户端或新开会话。

**环境自检**（装完先确认这一条）：

```bash
ls ~/.workbuddy/wbipc/endpoint.json              # macOS / Linux
dir %USERPROFILE%\.workbuddy\wbipc\endpoint.json # Windows
```

- 存在 → 客户端支持 wbipc，本技能可用。
- 不存在 → 客户端版本过旧（无本地守护进程通道），本技能不适用，请升级 WorkBuddy。

> 每台机器各自运行、各自用本机登录态。不需要、也不应该把任何凭据或 `endpoint.json` 拷给别人——
> 拷过去也没用，ticket 绑定本机实例，重启即失效。

## 快速开始

```bash
# 签到 + 派猫猫旅行全自动闭环（默认）
python3 ~/.workbuddy/skills/workbuddy-checkin-daemon/scripts/wb_checkin_daemon.py

# 只签到，跳过旅行
python3 ~/.workbuddy/skills/workbuddy-checkin-daemon/scripts/wb_checkin_daemon.py --no-travel
```

Windows 把 `python3` 换成 `python`、路径换成 `%USERPROFILE%\.workbuddy\...`。
系统没有 Python 时，可用客户端托管解释器：
macOS / Linux `~/.workbuddy/binaries/python/versions/*/bin/python3`，
Windows `%USERPROFILE%\.workbuddy\binaries\python\versions\*\python.exe`。

脚本只依赖 Python 标准库（3.8+），输出单行 JSON，退出码：成功 0 / 失败 1。

## 输出字段

| 字段 | 说明 |
|---|---|
| `status` | `ok` / `error` |
| `action` | `clicked`（本次领取） / `skip_already_signed`（今日已签，幂等跳过） |
| `credit_gained` | 本次领取的积分 |
| `streak_days` | 连续签到天数 |
| `balance` | 当前积分余额（接口返回时才有） |
| `travel.state` | `idle` 空闲 / `traveling` 旅行中 / `arrived` 已到达待领取 |
| `travel.auto_log` | 本次旅行闭环实际动作（领取 / 派遣 / 跳过原因） |

## 每日 9 点自动签到（WorkBuddy 自带自动化）

在 WorkBuddy 中创建 recurring 自动化（不要用 crontab / 系统计划任务），提示词模板：

```text
请使用 Bash 工具运行以下命令，完成 WorkBuddy 每日自动签到 + 派猫猫旅行闭环
（通过 WorkBuddy 守护进程 wbipc 管道代理请求，token 不落地）：

python ~/.workbuddy/skills/workbuddy-checkin-daemon/scripts/wb_checkin_daemon.py

脚本输出单行 JSON，按以下规则用 2-4 句话向用户汇报：
1. action=clicked：签到成功，领取 credit_gained 积分，连续签到 streak_days 天；
   balance 非 null 时附「当前积分余额：X」。
2. action=skip_already_signed：今日已签到，自动跳过（附余额与连续天数）。
3. status=error：如实报告 msg 中的失败原因，不得谎报成功。
4. 再读 travel 字段补一句旅行情况：traveling → Buddy 正在 location_name 旅行，
   约 remaining_text 后到达；arrived → 已到达，auto_log 显示领取结果；
   auto_log 逐条照实转述；travel.available=false → 只说「旅行状态未能获取」。

硬性约束：严禁打印或猜测任何 token/ticket 凭据；不要重试超过 1 次；
不要修改脚本或 ~/.workbuddy 下任何登录态/密钥文件；汇报用中文，简洁。
```

rrule：`FREQ=DAILY;BYHOUR=9;BYMINUTE=0`

> Windows 用户把提示词里的 `python ~/.workbuddy/...` 换成
> `python %USERPROFILE%\.workbuddy\skills\workbuddy-checkin-daemon\scripts\wb_checkin_daemon.py`。
> 自动化必须建在 WorkBuddy 自带的自动化里（调度与执行都在本机），云端 / crontab / 计划任务都不可行。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| `wbipc frame timeout` / `cannot open pipe` | WorkBuddy 客户端未运行或刚重启（endpoint 已轮换）。打开客户端后重跑。 |
| `wb.request pipe 不可见` | 客户端未登录或守护进程会话不可用，登录后重试。 |
| `code=10001` | 今日已签到，属幂等安全返回，不是错误。 |
| `旅行：今日派遣次数已用完` | 服务端每日限额，次日自动恢复，不是故障。 |
| 桌面脚本偶发被杀（SIGTERM） | 本机安全策略干扰，重跑即可。 |
| 客户端重启后 `E_REVOKED` | endpoint/ticket 已轮换，重新读取 endpoint.json 重连。 |

## 安全设计

- 零凭据读取：不打开、不解析、不传输登录态文件；ticket 只用于本机管道握手，不产生网络外发。
- 只调用 5 个已验证端点（签到状态 / 领取 / 旅行状态 / 旅行领取 / 旅行派遣），不触碰兑换、抽奖等接口。
- 签到接口幂等，重复运行不会重复发积分。
- 纯 Python 标准库，无第三方依赖，无遥测。

## 版本

见 [CHANGELOG.md](./CHANGELOG.md)（当前 v1.0.2）。

> 从技能市场安装的副本会带一个 `_skillhub_meta.json`（市场安装元数据）；从本仓库拷贝的目录不含该文件，属正常现象。

## 已知限制

- `travel.state == "arrived"` 的那次运行里，领完旅行积分不再重查状态，因此「到达 → 领取」这一次不会顺带派遣，下一次运行才派出。多跑一次即可，积分不会丢。
- 依赖客户端版本：需要客户端提供 wbipc 通道（`~/.workbuddy/wbipc/endpoint.json` 存在）。客户端大版本升级若改动协议，脚本需跟着适配。
- 仅 PC 客户端可用，网页版无签到入口。

## 适用范围与致谢

- 仅支持 PC 客户端签到（网页版无签到入口）。
- 签到接口与旅行闭环设计参考社区技能 totorosir-workbuddy-checkin（作者：龙猫科技说），
  本技能在其接口约定基础上改用守护进程代理方案，兼容新版加密登录态。
- wbipc 协议细节见 `references/wbipc-protocol.md`。
