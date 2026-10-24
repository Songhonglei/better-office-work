# 目标 Agent 端到端验收

每台机器独立执行，使用用户授权的网站和号码。不要因其他设备或离线测试成功就标记本机通过。只记录脱敏回执，不把真实邮件、验证码、授权 URL 中的设备码或 token 提交到 Git/Issue。

## 1. 安装和离线检查

下载完整目录，用 install.py 安装到目标 Agent 实际技能目录；重新加载后确认可选 sms-agent-mail，metadata.version=1.3.0。然后在该技能目录执行：

```bash
python3 -m unittest discover -s tests -v
```

通过只说明离线行为可用，不是邮箱授权或网站登录成功。

## 2. 首次接入和身份

按 storage.md 说明位置、确认邮箱、SIM/尾号与可信转发发件人，选择原生或 CLI 后端，完成 onboarding。缺授权时由用户在官方页面操作。真实身份响应须包含期望邮箱并具备 mail:read；不能使用缓存、别的账号或只改 --to 条件。

## 3. 新短信完整读取

1. 在用户指定的网站选择短信登录，确认目标号码。触发发送的按钮常不是「发送验证码」本身（例如先填号码再点「下一步」或「验证码登录」），倒计时出现即表示已发出；**记录 after 与点击必须在同一次执行内完成**，先点后补记会引入不可信的窗口起点。若网站已登录，先报告现状，不擅自退出用户账号。图形验证交由用户完成。
2. 用户确认手机收到后，冻结 before；按品牌、目标邮箱、inbox 和窗口搜索，保留条件完成分页。
3. 读取候选完整正文，只在内存核对服务与登录用途、已确认来源、目标收件人、SIM/尾号与时间；不下载附件、不打印验证码。把消息 JSON 交给校验器做确定性判定：

   ```bash
   python3 scripts/check_message.py --profile <本机profile> \
     --message-json <消息JSON> --after <after> --before <before>
   ```

   它按 profile 的 `phone_routes`、`subject_pattern`、`services`、`trusted_senders` 逐项判定，输出 `verdict`、`blockers`、`warnings` 与验证码**长度**（不含验证码本身）。已知会拦截的情况：来源不在白名单、收件人不符、品牌标签缺失、主题路由未注册或尾号不符、主题与正文路由冲突、正文截断、`created_at` 落在窗口外、正文无原始时间只有 `created_at`、`created_at` 与正文时间偏差超限、验证码缺失或出现多个候选、候选码实为短信端口片段。`warnings` 里的 `extra_recipient:` 表示这封短信还投给了别的地址，属于验证码外泄面，应当告知用户。
4. 记录主题路由是否符合配置、正文是否完整、具体时间字段名及可信依据。正文通常为固定骨架：短信端口号 / 品牌与内容 / 路由（如 `SIM2_1218`）/ `SubId` / 原始短信时间 / 设备名——首行的长数字是端口，不是验证码。只有 `created_at` 且没有独立语义证据时，时间项标为 blocked（校验器会返回 `body_time_missing`）；可以确认收信/读信链路，不能标记自动登录通过。

### 未收到转发件时先查手机，不要怀疑链路

短信"接口成功、倒计时正常、手机没提示"最常见的原因是被手机系统拦进**拦截箱/骚扰拦截**，而转发应用通常只转发收件箱——于是手机上有、邮箱里没有。排查顺序：

1. 让用户翻短信的拦截/垃圾分类，确认这条是否在其中；
2. 若在，请用户把该发送方加入白名单（或关闭对该类短信的拦截），并检查转发应用是否有"包含拦截短信"选项；
3. 放行后最多重发一次，重新记录 after；仍无转发件才考虑运营商或站点侧风控，并在回执中写明。
4. 不要连续多次重发，也不要因为手机收到过就假定邮箱已收到——判定只认邮箱里的消息。

## 4. 条件具备时完成登录

只有当校验器返回 `pass`（时间、服务、号码、来源、正文完整性均通过）时，才继续登录。验证码交给页面：

- **默认路径是人工交接**：把当前窗口交给用户（浏览器控制方通常提供 handoff/takeOver 语义），由用户自己输入 6 位码，Agent 只读取交接后的页面状态。
- 只有在同一进程内可安全共享内存时才程序化填入。任何需要把真实码写进工具参数、命令、终端、文件、截图或调试日志的方式，都算不能安全交接，应当交接并记录 `code_handoff: manual`。
- 图形验证、滑块、人脸等一律交给用户完成。

完成后检查页面实际登录状态（跳转后的 URL、账号标识等）；没有跳转或登录态证据就不能写 `login_passed=true`。不能安全交接、没有浏览器、遇到未完成的人工验证时，报告具体阻塞，不通过聊天显示真实码。

## 5. 升级不丢授权

从同一仓库的新下载目录执行 install.py，沿用原 --data-dir。比较外置配置和供应商凭据元数据，核对没有被安装器改动；再做身份验证。身份读取本身可能合法刷新供应商凭据，须区分安装器变更和供应商刷新，不能靠禁止正常刷新掩盖失效。原生后端在升级后用宿主真实身份工具复核，再用 `onboard.py confirm --profile <name> --evidence <依据>` 留下本次检查记录；`profiles/*.json.bak` 是 `set-rules` 的正常备份产物，不属于安装器写入。

## 脱敏回执

```json
{
  "skill_version":"1.3.0",
  "install_passed":true,
  "offline_tests_passed":true,
  "identity_matched":true,
  "new_sms_full_body_read":false,
  "service_route_sender_matched":false,
  "receipt_time_verified":false,
  "message_verdict":"blocked",
  "code_handoff":"manual",
  "login_passed":false,
  "upgrade_preserved_state":false,
  "blocker":"示例：等待真实新短信；未执行项必须保留 false"
}
```

`message_verdict` 取校验器结论（pass/blocked/未执行），`code_handoff` 记录验证码交给页面的方式（manual/host-memory）。这里的 JSON 是回执格式示例，不能复制它作为验收结果。请填本机实际证据，并明确区分"未执行""失败""已通过"。
