---
name: oss-pages-sync
description: 用一份外置 config.json（OSS AK/SK、目标域名、bucket、GitHub Pages / Vercel 源站清单、验真层级、CI 目标 repo 与调度）驱动静态站镜像：本地抓取改写后增量上传到阿里云 OSS 子目录，返回每站同步后的域名路径与结构化结果；同时能把脚本、站点清单、GitHub Actions 工作流与 Secrets 一键部署并维护到指定 repo，支持 ci status/run/update/enable/disable。This skill should be used when 用户要同步/更新静态站镜像、检查 OSS 是否漏文件、按 L1/L2/L3 层级验真、设置或维护某个 GitHub 仓库的自动同步、改定时频率、加删镜像站点，触发词包括：同步静态站、OSS 镜像、镜像同步、检查漏文件、深度验真、L2 检查、L3 验真、指定域名同步、自动同步、CI 同步、oss-pages-sync。
version: 2.0.1
python_optional: ["oss2", "websocket"]
metadata: {"openclaw": {"envVars": [{"name": "OSS_ACCESS_KEY_ID", "required": false, "description": "覆盖配置里的 OSS AK（可选）"}, {"name": "OSS_ACCESS_KEY_SECRET", "required": false, "description": "覆盖配置里的 OSS SK（可选）"}]}}
---

# OSS Pages Sync — 单一配置驱动的静态站镜像 + CI 托管

## 概述

**两份真源**：`~/.workbuddy/oss-pages-sync/config.json` 是唯一配置真源（凭据、域名、bucket、源站清单、CI 目标与调度全在里面）；本 Skill 的 `scripts/` 是唯一代码真源。本地运行和 GitHub Actions 用的是同一份脚本、同一份由 config 渲染出的 `sites.conf`，不再有第二套需要手工维护的脚本。

- **本地**：`run.py` 读 config → 生成运行时 `sites.conf` → 抓 GitHub Pages / Vercel 成品 → 改写绝对链接 → 按 ETag 增量上传 OSS → 验真 → 返回每站镜像 URL 与结构化结果。
- **CI**：`run.py ci setup|update` 把脚本、`sites.conf`、两个 workflow 渲染后推到 `config.ci.repo`，并用 `gh secret set` 写入 AK/SK；`ci status/run/enable/disable` 负责日常维护。改配置后跑一次 `ci update` 即可，不用进仓库改 YAML。
- 中国大陆 / 微信内可直接打开，无需 CDN。默认**只检查不写入**，`--apply` 才真同步。

## 配置（唯一真源）

复制模板到 skill 目录之外（重装 Skill 不会丢），然后按下面填写：

```bash
mkdir -p ~/.workbuddy/oss-pages-sync
cp ~/.workbuddy/skills/oss-pages-sync/config.example.json ~/.workbuddy/oss-pages-sync/config.json
chmod 600 ~/.workbuddy/oss-pages-sync/config.json
```

**这个文件含 AK/SK，必须 `chmod 600`，绝不入库、不进命令回显**；`run.py` 发现权限过宽会自动收紧。

| 字段 | 说明 |
| --- | --- |
| `oss.access_key_id` / `access_key_secret` | OSS 凭据。也可留占位，回落环境变量或 `~/.ossutilconfig`；但 `ci setup` 要求这里填真值才能写 GitHub Secrets |
| `oss.domain` / `bucket` / `endpoint` | 目标已备案域名（只填 host）、OSS bucket 裸名、endpoint |
| `sites[]` | 数组：`name`（OSS 子目录名）、`url`（已发布的源站根 URL，GitHub Pages / Vercel 均可）、可选 `root: true`（源站用 `/v2/…` 这类根绝对路径时需改写前缀） |
| `verify.level` | 默认验真层级 1/2/3 |
| `ci.repo` / `branch` / `dir` | 自动同步部署到哪个仓库、分支、脚本目录 |
| `ci.workflow` / `deep_workflow` | 日常同步与深度验真工作流文件名 |
| `ci.schedule` / `timezone` | cron 表达式（GitHub Actions 按 UTC）与时区标注 |
| `ci.secrets` | 两个 Secret 的名称，通常用默认值即可 |

加站、删站、改域名、改频率**都只改这一个文件**，然后本地跑一次体检、CI 侧跑一次 `ci update`。包内 `scripts/sites.conf` 只是示例与旧版兜底，不是真源。

## 本地同步

| 用户说 | 执行 |
| --- | --- |
| 「检查一下镜像 / 有没有漏文件」 | `python3 run.py` |
| 「同步 / 更新 / 上线这些站」 | `python3 run.py --apply` |
| 「返回域名路径和结果」 | `python3 run.py --json`（纯 JSON，可直接解析） |
| 「按 L3 深度验一下」 | `run.py --level 3`（要同步再加 `--apply`） |
| 「只看看 html-golive」 | `run.py --site html-golive` |
| 「指定域名 other.cn」 | `run.py --domain other.cn`（同时确认 bucket/endpoint） |
| 「有哪些站」 | `run.py --list` |

`--json` 输出含 `ok / mode / domain / level / changed / uploaded / crawl_errors / verify / warnings / sites[]`，每个站点带 `url`（`https://<域名>/<站点名>/`）、`home_status`（真实 GET 状态码）、`ok`。**stdout 恒为一个 JSON 对象**：失败时返回 `{"ok": false, "error": "...", "log": "..."}`，不会只剩退出码和空输出；所有提示性文字走 stderr。详细日志只在 `--json` 模式写入 `~/.workbuddy/oss-pages-sync/runtime/last-run.log`，普通模式日志直接打印到终端、不落文件。`crawl_errors=true` 会进 `warnings`（常见瞬时 TLS/DNS 抖动，建议重跑确认）。

其余参数：`--level 1|2|3`、`--site`、`--depth N`（正式同步必须 0）、`--bucket` / `--endpoint`（覆盖配置）、`--check-only`、`--install-deps`。

## CI 托管（指定 repo 的自动同步）

| 命令 | 作用 |
| --- | --- |
| `run.py ci setup` | 首次部署：写 2 个 GitHub Secrets（AK/SK 只经 stdin 传），把 3 个脚本 + `sites.conf` + `.gitignore` + 一份「本目录由 Skill 托管」的说明文件 + 2 个 workflow 推到 `ci.repo`，按铁律回查远端 commit 与逐文件内容 |
| `run.py ci update` | 配置改动后重渲染并推送；内容一致时**不产生空提交**（幂等） |
| `run.py ci status` | 查 workflow 列表、最近 5 次运行、secrets 名单、cron |
| `run.py ci run` | 触发一次 `workflow_dispatch`，只认「触发前不存在」的新 run id 并等结论；`--no-wait` 只触发 |
| `run.py ci disable` / `enable` | 停用 / 恢复定时同步 |

`setup` 生成的 workflow 会把 `OSS_TARGET_DOMAIN / OSS_BUCKET / OSS_ENDPOINT` 作为普通 env 注入（占位版脚本不再内置个人默认值），AK/SK 只走 `${{ secrets.* }}`。日常同步在无变化时会短路跳过 L2；手动触发强制验真。`ci run` 不靠 CLI 退出码判成败，会解析远端 run 的 `conclusion` 与每个步骤的结论。

需要 `gh` CLI 且已登录、对目标 repo 有写权限与 Secrets 权限。commit 署名固定 `Evan Song <Songhonglei@users.noreply.github.com>`。

## 依赖

- **Python 3.8+**；`oss2`（上传 / 清单比对）、`websocket-client`（仅 L3，import 名为 `websocket`）。frontmatter 的 `python_optional` 用 import 名，pip 包名是 `websocket-client`。
- 首次安装：`python3 run.py --install-deps`，装到配置目录的 `.deps/`（不污染系统 Python、重装 Skill 不丢）。等价命令：`python3 -m pip install oss2 websocket-client`。
- **CI 管理另需 `gh` CLI**（已登录）；L3 另需本机 Chrome / Chromium。
- 复跑 `skill-release-audit` 时带 `PYTHONPATH=~/.workbuddy/oss-pages-sync/.deps`，否则审计器看不到私有依赖会误报未安装。

## 环境变量（都是可选覆盖）

| 变量 | 说明 |
| --- | --- |
| `OSS_PAGES_SYNC_CONFIG` | 覆盖配置文件路径 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 覆盖配置里的凭据 |
| `OSS_SITES_CONF` / `OSS_STAGING_DIR` | 由 `run.py` 自动注入，指向配置目录下的 `runtime/`；手工直接跑脚本时才需要自己设 |
| `OSS_TARGET_DOMAIN` / `OSS_BUCKET` / `OSS_ENDPOINT` / `ONLY_SITE` / `OSS_MAX_DEPTH` | 由 `run.py` 或 workflow 注入 |
| `SYNC_DRY_RUN` / `REQUIRE_UPLOAD` / `GITHUB_OUTPUT` | 控制只比对 / 缺凭据报红 / CI 输出 `changed` 等 |

## 验真层级

| 层级 | 内容 | 用途 |
| --- | --- | --- |
| L1 | staging ↔ OSS 对象清单比对，查漏传 | 秒级体检 |
| L2 | L1 + 页面引用逐条 GET 探活（约 130 条） | **默认**，同步后必跑 |
| L3 | L2 + 无头 Chrome 录同源 404、点交互入口、源站/镜像 DOM 对比 | 源站大改 / 加新站，约 3-4 分钟 |

爬取式镜像无法保证不漏文件，策略是让漏自动报红。CI 侧另有 `ci.deep_workflow`（仅手动触发）等价 L3。

## 验真铁律（每次 `--apply` 或 `ci setup` 后）

`run.py` 已内置：跑 `ci_sync.py` → `verify.py --level N` → **逐个 GET 线上站点首页打印真实状态码**（强制直连绕开本机代理）→ 汇总。`ci setup` 还会 `git fetch` 后比对远端 commit 与全部部署文件的字节内容；`ci run` 回查远端 run 结论与步骤。退出码 0 不代表内容真的到了远端，必须看这些业务级输出：`verify=PASS`、`home_bad=0`、run `conclusion=success`。`changed=false`（源站没变、上传 0 个）是正常结果，不是失败。

## 排障速查

| 现象 | 处理 |
| --- | --- |
| 缺依赖 / 找不到 gh | `run.py --install-deps`；CI 命令需 `gh auth login` |
| 配置是旧格式 | 按 `config.example.json` 升级为 `oss / sites / verify / ci` 四段 |
| `crawl_errors=true` 但 L2 PASS | 多为瞬时 TLS/DNS 抖动；`curl` 复测目标 URL 后重跑一次 |
| `/<站名>/` 回落主页或 404 | OSS 需 `main.html` + `SupportSubDir=true`；脚本自动补 `main.html` |
| 页面骨架在、交互失效 | 动态 `import()` 的 `.mjs` 漏抓 / MIME 不对，L3 能抓到同源 404 |
| L2 报 404 但源站也 404 | 加进 `verify.py` 的 `ALLOW_404`，不要直接放行 |
| 定时任务不跑了 | 私有仓库 60 天无活动会停用 schedule；`ci status` 看状态，push 一次或 `ci enable` |
| `ci setup` 报缺凭据 | 填 `oss.access_key_id` / `access_key_secret`，或改用环境变量 + 手工写 Secrets |

已知限制：登录态 / 运行时拼接 URL / SSR / API / RSC 无法静态镜像；Next.js 站未纳入；脚本只增不删（删站后远端旧对象不自动清理）；`cron` 的 `*/3` 在每月 1 号会重置节奏，要严格等间隔需改外部调度；`liquidtime` 的 `/power` 是动态 API，静态 OSS 必然 404（已豁免）。
