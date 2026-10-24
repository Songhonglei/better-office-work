# 目标 Agent 端到端验收

每台机器独立执行，使用用户授权的网站和号码。不要因其他设备或离线测试成功就标记本机通过。只记录脱敏回执，不把真实邮件、验证码、授权 URL 中的设备码或 token 提交到 Git/Issue。

## 1. 安装和离线检查

下载完整目录，用 install.py 安装到目标 Agent 实际技能目录；重新加载后确认可选 sms-agent-mail，metadata.version=1.2.0。然后在该技能目录执行：

```bash
python3 -m unittest discover -s tests -v
```

通过只说明离线行为可用，不是邮箱授权或网站登录成功。

## 2. 首次接入和身份

按 storage.md 说明位置、确认邮箱、SIM/尾号与可信转发发件人，选择原生或 CLI 后端，完成 onboarding。缺授权时由用户在官方页面操作。真实身份响应须包含期望邮箱并具备 mail:read；不能使用缓存、别的账号或只改 --to 条件。

## 3. 新短信完整读取

1. 在用户指定的网站选择短信登录，确认目标号码，点击发送前记录 after；若网站已登录，先报告现状，不擅自退出用户账号。图形验证交由用户完成。
2. 用户确认手机收到后，冻结 before；按品牌、目标邮箱、inbox 和窗口搜索，保留条件完成分页。
3. 读取候选完整正文，只在内存核对服务与登录用途、已确认来源、目标收件人、SIM/尾号与时间；不下载附件、不打印验证码。
4. 记录主题路由是否符合配置、正文是否完整、具体时间字段名及可信依据。只有 created_at 且没有独立语义证据时，时间项标为 blocked；可以确认收信/读信链路，不能标记自动登录通过。

## 4. 条件具备时完成登录

只有时间、服务、号码与来源均通过，并且目标 Agent 能安全在内存中将验证码交给当前网页时才填入。不能安全交接、没有浏览器、遇到人工验证未完成时报告具体阻塞，不通过聊天显示真实码。完成后检查页面实际登录状态；没有跳转或登录态证据就不能写 login_passed=true。

## 5. 升级不丢授权

从同一仓库的新下载目录执行 install.py，沿用原 --data-dir。比较外置配置和供应商凭据元数据，核对没有被安装器改动；再做身份验证。身份读取本身可能合法刷新供应商凭据，须区分安装器变更和供应商刷新，不能靠禁止正常刷新掩盖失效。

## 脱敏回执

```json
{
  "skill_version":"1.2.0",
  "install_passed":true,
  "offline_tests_passed":true,
  "identity_matched":true,
  "new_sms_full_body_read":false,
  "service_route_sender_matched":false,
  "receipt_time_verified":false,
  "login_passed":false,
  "upgrade_preserved_state":false,
  "blocker":"示例：等待真实新短信；未执行项必须保留 false"
}
```

这里的 JSON 是回执格式示例，不能复制它作为验收结果。请填本机实际证据，并明确区分“未执行”“失败”“已通过”。
