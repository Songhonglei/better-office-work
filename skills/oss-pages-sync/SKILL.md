---
name: oss-pages-sync
description: 把 GitHub Pages / Vercel 等已发布的静态站镜像到阿里云 OSS 已备案域名下的子目录，并在同步后自动验真是否漏文件。支持指定目标域名（--domain）、验真层级（--level 1/2/3）、只处理某站（--site）、只检查不写入（默认）或真正同步（--apply）。This skill should be used when 用户要同步/更新静态站镜像、检查 OSS 镜像是否漏文件、验证 evansong.cn 各站点是否正常、按 L2/L3 深度验真、新增或调整镜像站点，触发词包括：同步静态站、OSS 镜像、镜像同步、检查漏文件、深度验真、L2 检查、L3 验真、指定域名同步、evansong.cn 同步、oss-pages-sync。
version: 1.0.0
python_optional: ["oss2", "websocket"]
metadata: {"openclaw": {"envVars": [{"name": "OSS_ACCESS_KEY_ID", "required": false, "description": "OSS AK；不设则读 ~/.ossutilconfig"}, {"name": "OSS_ACCESS_KEY_SECRET", "required": false, "description": "OSS SK；不设则读 ~/.ossutilconfig"}]}}
---

# OSS Pages Sync — 静态站镜像检查与同步

## 概述

源站（GitHub Pages / Vercel 成品）→ 抓取并改写链接 → 阿里云 OSS 子目录（`https://<域名>/<站点名>/`）→ 自动验真。中国大陆 / 微信内可直接打开，无需 CDN。

- **代码真源**：private 仓库 `Songhonglei/evan-file-syn` 的 `oss-pages-sync` 目录。完整使用说明、排障表与已知限制见 https://github.com/Songhonglei/evan-file-syn/blob/main/oss-pages-sync/README.md （需仓库权限）；自动任务在仓库的 GitHub Actions 工作流 `sync-to-oss`，每 3 天北京时间 05:00 跑，源站无变化时自动短路。
- **本 Skill 定位**：对话里的手动入口。统一入口是 `run.py`，支持指定域名与验真层级，执行「检查 + 同步」。
- **脚本来源优先级**：`OSS_PAGES_SYNC_HOME` 环境变量 → 外部配置的 `script_home`（本机仓库真源）→ `scripts/` 内置兜底副本。仓库在就用仓库版，避免两份代码分叉；换机器时内置副本仍可独立跑。显式指定的路径无效会直接报错，不会静默降级到旧副本。改了仓库脚本，内置副本要重新复制一次。公开仓库 better-office-work 里的归档副本已把默认 bucket / 域名占位化，从真源复制脚本时请保留这一差异，别把个人默认值带回公开仓库。

## 意图 → 命令（照此执行）

| 用户说 | 执行 |
| --- | --- |
| 「检查一下镜像 / 有没有漏文件」 | `python3 ~/.workbuddy/skills/oss-pages-sync/run.py --level 2` |
| 「同步 / 更新 / 上线这些站」 | 同上 **加 `--apply`** |
| 「按 L3 深度验一下」 | `run.py --level 3`（要同步就再加 `--apply`） |
| 「只看看 html-golive」 | `run.py --site html-golive --level 2` |
| 「指定域名 other.cn，L3 深度同步」 | `run.py --domain other.cn --level 3 --apply` |
| 「有哪些站」 | `run.py --list` |

默认**不写入 OSS**（dry-run：抓取 + ETag 比对 + 验真）。只有用户明确说同步/更新/上线，才加 `--apply`。这是部署类动作，不需要二次确认，但**必须按下方验真铁律查远端真实状态**。

## 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--domain` | 外部配置的 `domain`（模板为 `your-domain.cn`） | 目标镜像域名；只取 host 部分，协议和路径会被剥掉，保证与链接改写目标一致。影响绝对链接改写与验真目标；换域名若 bucket 不同，同时给 `--bucket` / `--endpoint` |
| `--level 1\|2\|3` | 外部配置的 `level`（2） | 验真深度层级，见下表 |
| `--site` | 空 = 全部 6 站 | 只处理 `sites.conf` 里某个站 |
| `--depth N` | `0`（不限） | 抓取 BFS 层数；仅快速体检用，**正式同步必须 0**。`--level 3` 会自动强制为 0 |
| `--apply` | 关 | 真正写 OSS；不加则 `SYNC_DRY_RUN=1` |
| `--check-only` | — | 显式声明只检查（与默认相同，用于语义清晰） |
| `--bucket` / `--endpoint` | 外部配置 | 覆盖 OSS 目标 |
| `--list` / `--install-deps` | — | 列站点 / 首次装依赖 |

## 依赖

- **Python 3.8+**；必需包 `oss2`（上传 / 清单比对）、`websocket-client`（仅 L3，import 名是 `websocket`）。frontmatter 的 `python_optional` 按 import 名声明，pip 包名是 `websocket-client`。
- 首次安装：`python3 ~/.workbuddy/skills/oss-pages-sync/run.py --install-deps`，装到 skill **目录之外**的 `~/.workbuddy/oss-pages-sync/.deps`，不污染系统 Python，重装 skill 也不会丢。等价手工命令：`python3 -m pip install oss2 websocket-client`。
- L3 另需本机 Chrome / Chromium；旧路径 `sync.py --push` 另需 `ossutil`；查 CI 结论需 `gh`。
- 依赖装在外部目录，所以复跑 `skill-release-audit` 时要带 `PYTHONPATH=~/.workbuddy/oss-pages-sync/.deps`，否则审计器看不到，会误报「包未安装」。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 无 | 上传与清单比对凭据；不设则读 `~/.ossutilconfig`，再缺则只做离线 dry-run |
| `OSS_PAGES_SYNC_CONFIG` | `~/.workbuddy/oss-pages-sync/config.json` | 覆盖外部配置文件路径 |
| `OSS_PAGES_SYNC_HOME` | 无 | 覆盖脚本目录（须含 sync.py / ci_sync.py） |
| `OSS_TARGET_DOMAIN` | 由 `--domain` 注入 | 链接改写与验真的目标域名 |
| `OSS_BUCKET` / `OSS_ENDPOINT` | 外部配置 | OSS bucket 裸名 / endpoint |
| `ONLY_SITE` | 由 `--site` 注入 | 只处理某站 |
| `OSS_MAX_DEPTH` | 由 `--depth` 注入 | 抓取层数，0 = 不限 |
| `SYNC_DRY_RUN` / `REQUIRE_UPLOAD` | 由 `--apply` 注入 | 只比对不写入 / 缺凭据必须报红 |
| `GITHUB_OUTPUT` | CI 注入 | 同步脚本写 `changed` / `crawl_errors` / `uploaded` / `source_404` 供 workflow 判断 |

这些变量都有默认值或仅在 GitHub Actions 中注入，不是必填项，因此不在 frontmatter 声明为 required。完整字段说明见仓库使用说明。

## 验真层级（`--level`）

| 层级 | 内容 | 用途 |
| --- | --- | --- |
| L1 | 本地 staging ↔ OSS 对象清单比对，查漏传 | 秒级体检 |
| L2 | L1 + 页面引用逐条 GET 探活（约 130 条） | **默认**，有变化的同步后必跑 |
| L3 | L2 + 无头 Chrome 录同源 404、点交互入口、源站/镜像 DOM 对比 | 源站大改 / 加新站 / 怀疑漏文件，约 3-4 分钟 |

爬取式镜像**无法保证不漏文件**，策略是让漏自动报红。L3 需要 `websocket-client` 与本机 Chrome。CI 侧对应手动工作流 `verify-oss-deep`（仅 workflow_dispatch，无 schedule）。

## 首次使用（一次性）

1. 把配置模板复制到 skill 目录**之外**（重装 skill 不会丢）：
   ```
   mkdir -p ~/.workbuddy/oss-pages-sync
   cp ~/.workbuddy/skills/oss-pages-sync/config.example.json ~/.workbuddy/oss-pages-sync/config.json
   ```
   再把 `script_home` 改成本机 `evan-file-syn` 仓库内 `oss-pages-sync` 目录的绝对路径，留空则用内置副本。
2. `python3 ~/.workbuddy/skills/oss-pages-sync/run.py --install-deps` 装依赖。
3. 凭据二选一：环境变量 `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`，或本机 `~/.ossutilconfig` 的 `[default]` 段。Skill 只读不写，**任何密钥都不得写进配置文件、SKILL.md、命令回显或仓库**。
4. `run.py --list` 看站点清单，`run.py --level 2` 跑一次 dry-run 体检。

## 验真铁律（每次 `--apply` 后必做）

`run.py` 已内置：跑 `ci_sync.py` → `verify.py --level N` → **逐个 GET 线上站点首页打印真实状态码**（强制直连，绕开本机代理），最后汇总 `changed / uploaded / crawl_errors / L%s / 首页异常数`。退出码 0 不代表内容到了远端，必须看这段结论：

- `L2/L3: PASS` 且 `线上首页异常: 0` 才算成功；异常时按输出里报红的 URL 去 `curl` 复核，别只看 `changed`。
- `changed=false` 表示源站与 OSS 完全一致、上传 0 个，属正常，不是失败。
- 定时任务侧用 `gh run list -R Songhonglei/evan-file-syn --workflow=sync-to-oss.yml -L 5` 与 `gh run view <id> --log` 查真实 run 结论。
- 代码改动 push 后要 `git ls-remote origin refs/heads/main` + `git fetch` 后 `git show origin/main:<path>` 比对远端文件，不能只信本地和 CLI 退出码。

## 加站 / 改域名 / 改脚本

加站在仓库 `oss-pages-sync` 目录的 `sites.conf` 加一行 `目录名|源站根 URL|[root=1]`（`root=1` 用于 `/v2/…` 这类根绝对路径站点），先 `run.py --site <新站> --level 2` 体检，再 `--apply`，最后 `--level 3` 深度验。删站只停止同步，远端旧对象不自动删。改域名用 `--domain`，或改外部配置的 `domain` 作为默认值。完整字段说明、排障表、已知限制见 https://github.com/Songhonglei/evan-file-syn/blob/main/oss-pages-sync/README.md 。
包内 `scripts/` 是兜底副本：改了仓库真源的 `sync.py` / `ci_sync.py` / `verify.py` / `sites.conf` 后，重新复制这 4 个文件到 `scripts/`，否则换机器时会跑旧代码。

## 排障速查

| 现象 | 处理 |
| --- | --- |
| 缺少依赖提示 | `run.py --install-deps`；复跑审计要带 `PYTHONPATH=~/.workbuddy/oss-pages-sync/.deps` |
| 配置丢失 / 脚本来源不符 | 检查 `~/.workbuddy/oss-pages-sync/config.json` 的 `script_home`；显式设置了无效路径会直接报错 |
| `/<站名>/` 回落主页或 404 | OSS 需 `main.html` + `SupportSubDir=true`；脚本会自动补 `main.html` |
| 页面骨架在、交互失效 | 动态 `import()` 的 `.mjs` 漏抓 / MIME 不对，L3 能抓到同源 404 |
| L2 报 404 但源站也 404 | 加进 `verify.py` 的 `ALLOW_404`，不要直接放行 |
| 一直 `changed=true` | 源站每次构建字节在变（时间戳/hash），正常增量上传 |
| 定时任务不跑了 | private 仓库 60 天无仓库活动会停用 schedule，手动跑一次或 push 一次 |
| 凭据缺失却 `--apply` | 直接拒绝执行；先配环境变量或 `~/.ossutilconfig` |

已知限制：登录态 / 运行时拼接 URL / SSR / API / RSC 无法静态镜像；Next.js 站未纳入；脚本只增不删；`liquidtime` 的 `/power` 是动态 API，静态 OSS 必然 404（已豁免）。
