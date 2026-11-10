# oss-pages-sync

把 GitHub Pages / Vercel 上已发布的静态站，镜像到已备案域名下的阿里云 OSS 子目录，并在同步后自动验真有没有漏文件。中国大陆、微信内可直接打开，不需要 CDN。

版本：1.0.0 · 许可证：[MIT](LICENSE) · 执行入口：[SKILL.md](SKILL.md)

## 能做什么

- 抓取源站成品（HTML/CSS/JS/MJS、响应式图、动态 `import()` 模块），把写死的绝对链接改写为目标域名，补齐 OSS 子目录首页所需的 `main.html`。
- 按 MD5 与 OSS ETag 增量上传，内容一致就跳过；跑完自动做引用探活、清单比对，可选无头 Chrome 深度验真。
- 支持指定目标域名（`--domain`）、验真层级（`--level 1/2/3`）、只处理某站（`--site`）、抓取深度（`--depth`）。
- **默认只检查不写入**，说「同步 / 更新」才加 `--apply`；跑完逐个 GET 线上首页打印真实状态码，不拿退出码当成功。

## 使用前提

| 前提 | 说明 |
| --- | --- |
| 阿里云 OSS + 已备案域名 | bucket 开静态网站托管，`IndexDocument.Suffix=main.html`、`SupportSubDir=true`；域名绑定到 bucket |
| 凭据 | 环境变量 `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`，或本机 `~/.ossutilconfig` 的 `[default]` 段 |
| Python 3.8+ | `oss2`、`websocket-client`（仅 L3，import 名为 `websocket`） |
| L3 额外 | 本机 Chrome / Chromium |
| 定时任务（可选） | 独立 GitHub Actions，真源在私有仓库 `Songhonglei/evan-file-syn` 的 `oss-pages-sync/`；本仓库只归档 Skill 本体 |

**归档版已去个人化**：`config.example.json` 与脚本里的 bucket 名、默认域名都是占位符（`YOUR_OSS_BUCKET_NAME` / `your-domain.cn`），运行时一律由外部配置或命令行注入。私有仓库里的定时任务脚本内置了作者自己的默认值，两边差异仅此一项。凭据、bucket 名、本机绝对路径都不要写进仓库。

## 安装

```bash
git clone https://github.com/Songhonglei/better-office-work.git
cd better-office-work
mkdir -p ~/.workbuddy/skills
cp -R skills/oss-pages-sync ~/.workbuddy/skills/
```

其他 Agent 用其实际的 skills 目录（`~/.agents/skills/`、`~/.claude/skills/` 等）。已有同名安装时先比较并保留本地改动，不要直接覆盖唯一副本。

## 配置（一次性）

```bash
mkdir -p ~/.workbuddy/oss-pages-sync
cp ~/.workbuddy/skills/oss-pages-sync/config.example.json ~/.workbuddy/oss-pages-sync/config.json
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --install-deps
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --list
```

编辑外部 `config.json`：填 `domain`（目标域名）、`bucket`（OSS bucket 裸名）、`endpoint`；`script_home` 可指向本机私有仓库里的真源脚本，留空则用包内 `scripts/` 兜底副本。外部配置放在 skill 目录之外，重装 Skill 不会丢，仓库根 `.gitignore` 也已忽略 `skills/**/config.json`。

凭据只读环境变量或 `~/.ossutilconfig`，Skill 本身不写凭据文件。依赖装到 `~/.workbuddy/oss-pages-sync/.deps`，不污染系统 Python。

## 调用示例

> 检查一下镜像有没有漏文件

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --level 2
```

> 把这些站同步到 other.cn，按 L3 深度验真

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --domain other.cn --level 3 --apply
```

> 只体检 html-golive

```bash
python3 ~/.workbuddy/skills/oss-pages-sync/run.py --site html-golive --level 2
```

`--apply` 是部署动作，跑完看输出里的 `L2/L3: PASS` 与 `线上首页异常: 0`；`changed=false`（源站没变、上传 0 个）是正常结果，不是失败。定时任务侧另用 `gh run list -R <私有仓库> --workflow=sync-to-oss.yml` 查真实 run 结论。

## 验真层级

| 层级 | 内容 | 用途 |
| --- | --- | --- |
| L1 | staging ↔ OSS 对象清单比对 | 秒级体检 |
| L2 | L1 + 页面引用逐条 GET 探活 | 默认；有变化的同步后必跑 |
| L3 | L2 + 无头 Chrome 录同源 404、点交互入口、源站/镜像 DOM 对比 | 加新站 / 源站大改 / 怀疑漏文件，约 3-4 分钟 |

爬取式镜像无法保证不漏文件，策略是让漏自动报红。完整参数、排障表与已知限制见 [SKILL.md](SKILL.md)。

## 边界

- 只增不删：删站只停止同步，OSS 上的旧对象不会自动清理。
- 静态镜像覆盖不了登录态、运行时拼接的 URL、SSR / API / RSC；源站本身 404 的资源需加进 `verify.py` 的 `ALLOW_404`。
- `--depth` 仅用于快速体检，正式同步必须保持 0（不限）。
- 本 Skill 只归档到 GitHub，不发布到 clawhub / skillhub.cn。

## 文件导航

- [SKILL.md](SKILL.md)：执行入口、参数、环境变量、验真层级、排障与已知限制。
- [config.example.json](config.example.json)：外部配置模板（占位值，需自行填写）。
- `run.py`：统一入口，默认 dry-run，`--apply` 才写 OSS。
- `scripts/`：`sync.py`（抓取改写）、`ci_sync.py`（增量上传）、`verify.py`（L1/L2/L3）、`sites.conf`（站点清单）的兜底副本。改了私有仓库真源后重新复制这四个文件，但保留本归档版的占位默认值。
