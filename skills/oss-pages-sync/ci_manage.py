#!/usr/bin/env python3
"""把 Skill 托管的脚本 / 站点 / workflow / 密钥部署到 config.ci.repo。

架构：config.json 是唯一配置真源，skill 包 scripts/ 是唯一代码真源。
`ci setup|update` 把两者渲染成目标 repo 里的运行时文件并推送，CI 不再有
一份需要手工维护的独立脚本。所有写入都按验真铁律回查远端真实内容。
"""
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).parent
SCRIPTS = HERE / "scripts"
TPL = HERE / "ci"
SCRIPT_FILES = ("sync.py", "ci_sync.py", "verify.py")


def die(msg):
    print("错误: " + msg)
    raise SystemExit(1)


def render_sites_conf(cfg):
    """把 config.sites 渲染成 sync.py 认得的 sites.conf 文本。"""
    lines = [
        "# 由 oss-pages-sync Skill 从 config.json 的 sites 生成，勿手工改。",
        "# 改站点请改本机 ~/.workbuddy/oss-pages-sync/config.json，再跑 run.py ci update。",
        "# 目录名 | 已发布的站点根 URL | 可选 root=1",
    ]
    for item in cfg.get("sites") or []:
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url:
            die("config.json 的 sites 里有空 name / url")
        lines.append("%s|%s%s" % (name, url, "|root=1" if item.get("root") else ""))
    if len(lines) == 3:
        die("config.json 的 sites 为空，没有可同步的站点")
    return "\n".join(lines) + "\n"


def render_workflow(name, cfg):
    """模板占位符故意用 __X__，避开 GitHub Actions 的 ${{ ... }} 表达式。"""
    path = TPL / name
    if not path.is_file():
        die("缺 workflow 模板 %s" % path)
    oss, ci = cfg["oss"], cfg["ci"]
    sec = ci.get("secrets") or {}
    domain = str(oss.get("domain") or "").replace("https://", "").replace("http://", "").split("/")[0]
    mapping = {
        "__CRON__": ci.get("schedule") or "0 21 */3 * *",
        "__DIR__": ci.get("dir") or "oss-pages-sync",
        "__DOMAIN__": domain,
        "__BUCKET__": oss.get("bucket") or "",
        "__ENDPOINT__": oss.get("endpoint") or "",
        "__SECRET_ID__": sec.get("access_key_id") or "OSS_ACCESS_KEY_ID",
        "__SECRET_KEY__": sec.get("access_key_secret") or "OSS_ACCESS_KEY_SECRET",
    }
    text = path.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace(key, str(value))
    return text


def run_cmd(argv, stdin=None, check=True, text=True, timeout=240):
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=text, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        die("执行 %s 失败（%s）" % (argv[0], exc))
    if check and r.returncode != 0:
        err = r.stderr if text else r.stderr.decode("utf-8", "ignore")
        out = r.stdout if text else r.stdout.decode("utf-8", "ignore")
        die("%s %s 失败（exit %d）：%s" % (argv[0], " ".join(argv[1:3]), r.returncode,
                                          (err or out or "").strip()[:400]))
    return r


def gh(args, stdin=None, check=True):
    return run_cmd(["gh"] + args, stdin=stdin, check=check)


def git(args, check=True, text=True):
    return run_cmd(["git"] + args, check=check, text=text)


def validate_ci(cfg):
    ci = cfg.get("ci") or {}
    oss = cfg.get("oss") or {}
    repo = str(ci.get("repo") or "")
    if "/" not in repo or repo.startswith("OWNER/"):
        die("config.ci.repo 不是有效仓库（当前 %r），请填 OWNER/REPO" % repo)
    for key in ("domain", "bucket", "endpoint"):
        value = str(oss.get(key) or "")
        if not value or value.startswith("YOUR_") or value == "your-domain.cn":
            die("config.oss.%s 未填（当前 %r）" % (key, value))
    return ci


def set_secrets(cfg):
    """AK/SK 只经 stdin 传给 gh，绝不出现在命令行、日志或仓库文件里。"""
    ci, oss = cfg["ci"], cfg["oss"]
    repo = ci["repo"]
    sec = ci.get("secrets") or {}
    pairs = (("access_key_id", sec.get("access_key_id") or "OSS_ACCESS_KEY_ID"),
             ("access_key_secret", sec.get("access_key_secret") or "OSS_ACCESS_KEY_SECRET"))
    for key, name in pairs:
        value = str(oss.get(key) or "").strip()
        if not value or value.startswith("YOUR_"):
            die("config.oss.%s 未填（还是占位值），无法设置 GitHub Secret %s" % (key, name))
        gh(["secret", "set", name, "-R", repo], stdin=value + "\n")
        print("  ✓ secret %s -> %s" % (name, repo))


def build_files(cfg):
    ci = cfg["ci"]
    directory = ci.get("dir") or "oss-pages-sync"
    files = {}
    for name in SCRIPT_FILES:
        path = SCRIPTS / name
        if not path.is_file():
            die("缺脚本真源 %s" % path)
        files["%s/%s" % (directory, name)] = path.read_bytes()
    files["%s/sites.conf" % directory] = render_sites_conf(cfg).encode("utf-8")
    files["%s/.gitignore" % directory] = b"staging/\n__pycache__/\n*.pyc\n*.log\n"
    files["%s/README.md" % directory] = """# oss-pages-sync（由 Skill 托管，勿手工修改）

本目录的文件由 `oss-pages-sync` Skill 的 `run.py ci setup|update` 从配置渲染生成，
下次执行会覆盖手工改动。不要再在此仓库里直接改脚本或 workflow。

- **唯一配置真源**：`~/.workbuddy/oss-pages-sync/config.json`（OSS 凭据、域名、bucket、
  源站清单、验真层级、CI 目标 repo 与 cron）。含 AK/SK，`chmod 600`，不入库。
- **唯一代码真源**：Skill 安装目录下的 `scripts/`。本地同步与这里的 CI 用同一份代码。
- 加站 / 删站 / 改域名 / 改调度：改 config 后跑 `python3 run.py ci update`。
- 本地同步与体检：`python3 run.py --apply --json` / `python3 run.py --level 3`。
- CI 维护：`run.py ci status` / `ci run` / `ci disable` / `ci enable`。
- 完整说明见 Skill 的 `SKILL.md` 与 GitHub 仓库 `better-office-work/skills/oss-pages-sync/README.md`。

目录内文件：`sync.py`（抓取改写）、`ci_sync.py`（ETag 增量上传）、`verify.py`（L1/L2/L3）、
`sites.conf`（由 config.sites 渲染）、`.gitignore`。
""".encode("utf-8")
    files[".github/workflows/%s" % ci.get("workflow", "sync-to-oss.yml")] = \
        render_workflow("sync-workflow.yml.tpl", cfg).encode("utf-8")
    files[".github/workflows/%s" % ci.get("deep_workflow", "verify-oss-deep.yml")] = \
        render_workflow("deep-workflow.yml.tpl", cfg).encode("utf-8")
    return files


def verify_remote(local, branch, files):
    """铁律：push 后 fetch 回远端，比对 commit 与每个文件的字节内容。"""
    git(["-C", str(local), "fetch", "origin", branch, "--quiet"])
    head = git(["-C", str(local), "rev-parse", "FETCH_HEAD"]).stdout.strip()
    ls = git(["-C", str(local), "ls-remote", "origin", "refs/heads/" + branch]).stdout.strip().split()
    if not ls or ls[0] != head:
        die("远端 HEAD 与 fetch 结果不一致：ls-remote=%s fetch=%s" %
            (ls[0] if ls else "(空)", head))
    bad = []
    for rel, data in files.items():
        r = git(["-C", str(local), "show", "FETCH_HEAD:" + rel], check=False, text=False)
        if r.returncode != 0 or r.stdout != data:
            bad.append(rel)
    if bad:
        die("远端文件内容不一致：" + ", ".join(bad))
    print("远端验真: commit %s | %d 个文件逐字节一致" % (head[:7], len(files)))


def deploy(cfg, action):
    ci = validate_ci(cfg)
    repo = ci["repo"]
    branch = ci.get("branch") or "main"
    files = build_files(cfg)
    print("=== CI %s -> %s (%s) ===" % (action, repo, branch))
    print("调度: cron '%s'（GitHub Actions 按 UTC，配置标注 %s）" %
          (ci.get("schedule"), ci.get("timezone")))
    print("站点: %s" % ", ".join(str(s["name"]) for s in cfg["sites"]))
    set_secrets(cfg)
    with tempfile.TemporaryDirectory(prefix="oss-ci-") as tmp:
        local = pathlib.Path(tmp) / "repo"
        gh(["repo", "clone", repo, str(local), "--", "--depth", "1"])
        cur = git(["-C", str(local), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if cur != branch:
            git(["-C", str(local), "checkout", branch])
        changed = []
        for rel, data in files.items():
            path = local / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.read_bytes() == data:
                continue
            path.write_bytes(data)
            changed.append(rel)
        if not changed:
            print("目标仓库已是最新（%d 个文件全部一致），无需提交。" % len(files))
        else:
            git(["-C", str(local), "add", "--"] + changed)
            msg = "chore(oss-pages-sync): %s by Skill (%d files)" % (action, len(changed))
            git(["-C", str(local), "-c", "user.name=Evan Song", "-c",
                 "user.email=Songhonglei@users.noreply.github.com", "commit", "-m", msg])
            git(["-C", str(local), "push", "origin", "HEAD:%s" % branch])
            print("已推送 %d 个文件：%s" % (len(changed), ", ".join(changed)))
        verify_remote(local, branch, files)
    url = "https://github.com/%s/actions/workflows/%s" % (repo, ci.get("workflow"))
    print("工作流: %s" % url)
    print("镜像域名: https://%s/<站点名>/" % cfg["oss"]["domain"])
    return 0


def status(cfg):
    ci = validate_ci(cfg)
    repo = ci["repo"]
    print("=== CI 状态: %s ===" % repo)
    print("调度: cron '%s'（%s，UTC）" % (ci.get("schedule"), ci.get("timezone")))
    print("-- workflows --")
    print(gh(["workflow", "list", "-R", repo], check=False).stdout.strip())
    print("-- 最近 5 次运行 --")
    print(gh(["run", "list", "-R", repo, "--workflow", ci.get("workflow"),
              "-L", "5"], check=False).stdout.strip())
    print("-- secrets（只列名，不读值）--")
    print(gh(["secret", "list", "-R", repo], check=False).stdout.strip())
    return 0


def trigger(cfg, wait):
    ci = validate_ci(cfg)
    repo, wf = ci["repo"], ci.get("workflow")
    print("触发 %s / %s ..." % (repo, wf))
    gh(["workflow", "run", wf, "-R", repo])
    rid = ""
    # 异步创建 run，短轮询等待它出现（不是重试失败命令）
    for _ in range(8):
        r = gh(["run", "list", "-R", repo, "--workflow", wf, "-L", "1",
                "--json", "databaseId", "--jq", ".[0].databaseId"], check=False)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            rid = r.stdout.strip()
            break
        time.sleep(2)
    if not rid:
        die("已触发但没查到 run id，稍后用 run.py ci status 查看")
    print("run id: %s" % rid)
    watch_ok = True
    if wait:
        r = gh(["run", "watch", rid, "-R", repo, "--exit-status", "--interval", "10"], check=False)
        watch_ok = r.returncode == 0
        tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
        if tail:
            print(tail)
    # 铁律：退出码 0 只代表命令跑完；必须回查远端 run 的业务级 conclusion 与步骤结论。
    v = gh(["run", "view", rid, "-R", repo, "--json", "conclusion",
            "--jq", ".conclusion"], check=False)
    conclusion = (v.stdout or "").strip()
    steps = gh(["run", "view", rid, "-R", repo, "--json", "jobs",
                "--jq", ".jobs[].steps[] | [.name,.conclusion] | @tsv"], check=False)
    print("远端结论: %s" % (conclusion or "(未知)"))
    if steps.stdout.strip():
        print("步骤:\n" + steps.stdout.strip())
    if not wait:
        return 0
    return 0 if watch_ok and conclusion == "success" else 1


def toggle(cfg, enable):
    ci = validate_ci(cfg)
    gh(["workflow", "enable" if enable else "disable", ci.get("workflow"), "-R", ci["repo"]])
    print("%s %s" % ("已启用" if enable else "已停用", ci.get("workflow")))
    return 0


def dispatch(action, cfg, wait=True):
    if action in ("setup", "update"):
        return deploy(cfg, action)
    if action == "status":
        return status(cfg)
    if action == "run":
        return trigger(cfg, wait)
    if action in ("enable", "disable"):
        return toggle(cfg, action == "enable")
    die("未知 ci 动作：%s" % action)
    return 1
