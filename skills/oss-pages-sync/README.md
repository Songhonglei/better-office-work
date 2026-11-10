# oss-pages-sync

把 GitHub Pages / Vercel 上已发布的静态站镜像到已备案域名下的阿里云 OSS 子目录，同步后自动验真漏文件；同一个 Skill 还能设置和维护**指定 GitHub repo** 的自动同步。中国大陆、微信内可直接打开，不需要 CDN。

版本：2.0.1 · 许可证：[MIT](LICENSE) · 执行入口：[SKILL.md](SKILL.md)

## 能做什么

- **一份配置驱动全部**：`~/.workbuddy/oss-pages-sync/config.json` 收齐 OSS 凭据、目标域名 / bucket / endpoint、GitHub Pages 与 Vercel 源站清单、验真层级、CI 目标 repo 与 cron。加站、改域名、改频率只改这一个文件。
- **本地同步**：抓取成品（HTML/CSS/JS/MJS、响应式图、动态 `import()`）→ 改写绝对链接 → 按 MD5/ETag 增量上传 → L1/L2/L3 验真 → 返回每站镜像 URL 与结构化结果（`--json` 输出纯 JSON）。默认只检查不写入，`--apply` 才写 OSS。
- **CI 托管**：`run.py ci setup` 把脚本、由 config 渲染的 `sites.conf`、两个 GitHub Actions workflow 与一份「本目录由 Skill 托管」的说明推到 `ci.repo`，并用 `gh secret set` 写入 AK/SK；`ci update/status/run/enable/disable` 负责维护。本地与 CI 共用同一份代码和站点配置，不再有第二套要手工同步的脚本。
- 每次 `--apply` 后逐个真实 GET 线上首页打印状态码；`ci setup` 回查远端 commit 与文件字节；`ci run` 解析远端 run 的业务结论，不拿退出码当成功。

## 使用前提

| 前提 | 说明 |
| --- | --- |
| 阿里云 OSS + 已备案域名 | bucket 开静态网站托管，`IndexDocument.Suffix=main.html`、`SupportSubDir=true` |
| 凭据 | 写进外置 `config.json` 的 `oss.access_key_id` / `access_key_secret`；`ci setup` 会把它们写入目标 repo 的 GitHub Secrets |
| Python 3.8+ | `oss2`、`websocket-client`（仅 L3，import 名 `websocket`） |
| CI 管理 | `gh` CLI 已登录、对目标 repo 有写权限与 Secrets 权限 |
| L3 额外 | 本机 Chrome / Chromium |

**安全边界**：含 AK/SK 的 `config.json` 放在 skill 目录之外、`chmod 600`、绝不入库；`run.py` 发现权限过宽会自动收紧。AK/SK 只经 stdin 传给 `gh secret set`，不出现在命令行、日志、workflow 或任何仓库文件里。本仓库归档版只有 `config.example.json` 占位模板与不含个人值的 workflow 模板。

## 安装与配置

```bash
git clone https://github.com/Songhonglei/better-office-work.git
cd better-office-work
mkdir -p ~/.workbuddy/skills ~/.workbuddy/oss-pages-sync
cp -R skills/oss-pages-sync ~/.workbuddy/skills/
cp ~/.workbuddy/skills/oss-pages-sync/config.example.json ~/.workbuddy/oss-pages-sync/config.json
chmod 600 ~/.workbuddy/oss-pages-sync/config.json
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --install-deps
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --list
```

编辑 `config.json` 四个段：`oss`（凭据 / 域名 / bucket / endpoint）、`sites`（`name` / `url` / 可选 `root`）、`verify.level`、`ci`（`repo` / `branch` / `dir` / `workflow` / `deep_workflow` / `schedule` / `timezone` / `secrets`）。字段含义见 [SKILL.md](SKILL.md) 的配置表。

## 调用示例

> 检查一下镜像有没有漏文件，把结果给我

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --json
```

输出示例（节选，省略部分字段与站点）。失败时同样返回一个 JSON 对象（`ok=false` + `error` + `log`），提示性文字走 stderr：

```json
{
  "ok": true,
  "mode": "check",
  "domain": "evansong.cn",
  "changed": "false",
  "uploaded": "0",
  "verify": "PASS",
  "home_bad": 0,
  "sites": [{"name": "html-golive", "url": "https://evansong.cn/html-golive/", "home_status": 206, "ok": true}]
}
```

> 把这些站真同步一次

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --apply --json
```

> 在指定 repo 上设置每 3 天的自动同步，并立刻跑一次

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py ci setup
python3 ~/.workbuddy/skills/oss-pages-sync/run.py ci run
python3 ~/.workbuddy/skills/oss-pages-sync/run.py ci status
```

改了 `sites` 或 `ci.schedule` 后跑 `ci update`；内容没变时它不会制造空提交。`changed=false`（源站与 OSS 一致、上传 0 个）是正常结果。

## 验真层级

| 层级 | 内容 | 用途 |
| --- | --- | --- |
| L1 | staging ↔ OSS 对象清单比对 | 秒级体检 |
| L2 | L1 + 页面引用逐条 GET 探活 | 默认；同步后必跑 |
| L3 | L2 + 无头 Chrome 录同源 404、点交互入口、源站/镜像 DOM 对比 | 加新站 / 源站大改，约 3-4 分钟 |

爬取式镜像无法保证不漏文件，策略是让漏自动报红。完整参数、排障表与已知限制见 [SKILL.md](SKILL.md)。

## 边界

- 只增不删：删站只停止同步，OSS 上的旧对象不会自动清理。
- 静态镜像覆盖不了登录态、运行时拼接的 URL、SSR / API / RSC。
- `--depth` 仅用于快速体检，正式同步必须保持 0（不限）。
- `cron` 的 `*/3` 每月 1 号会重置节奏；要严格等间隔需外部调度。
- 本 Skill 只归档到 GitHub，不发布到 clawhub / skillhub.cn。

## 文件导航

- [SKILL.md](SKILL.md)：执行入口、配置字段、本地命令、CI 命令、验真层级、排障与已知限制。
- [config.example.json](config.example.json)：唯一配置的模板（占位值）。
- `run.py`：本地同步统一入口，含 `--json` 结构化结果与 `ci` 子命令分发。
- `ci_manage.py`：CI 部署、验真、状态、触发、启停的实现。
- `ci/*.tpl`：两个 GitHub Actions workflow 模板，`__X__` 占位符由 config 渲染。
- `scripts/`：`sync.py`（抓取改写）、`ci_sync.py`（增量上传）、`verify.py`（L1/L2/L3）；`sites.conf` 仅为示例，真源是 config 的 `sites`。
