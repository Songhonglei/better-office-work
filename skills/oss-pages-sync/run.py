#!/usr/bin/env python3
"""oss-pages-sync 统一入口：一份 config.json 驱动本地同步与指定 repo 的 CI。

    python3 run.py                          # 默认：只检查（dry-run）+ L2
    python3 run.py --apply                  # 真同步到 OSS + L2
    python3 run.py --json                   # 输出结构化结果（逐站 URL + 结论）
    python3 run.py --list                   # 列出 config.sites
    python3 run.py ci setup                 # 部署脚本/站点/workflow/secrets 到 ci.repo
    python3 run.py ci update                # 配置改动后重新渲染并推送
    python3 run.py ci status                # 查 workflow / run / secrets
    python3 run.py ci run                   # 触发一次并等结论
    python3 run.py ci disable|enable        # 停用 / 启用定时同步

配置真源：~/.workbuddy/oss-pages-sync/config.json（含 AK/SK，chmod 600，绝不入库）。
代码真源：本 skill 的 scripts/；本地运行时把 sites.conf 与 staging 放到配置目录的
runtime/ 下，CI 部署时把同一份脚本与渲染后的 sites.conf 推到目标 repo。
"""
import argparse
import configparser
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

import ci_manage

HERE = pathlib.Path(__file__).parent
CFG_DIR = pathlib.Path.home() / ".workbuddy" / "oss-pages-sync"
CONFIG = CFG_DIR / "config.json"
EXAMPLE = HERE / "config.example.json"
SCRIPTS = HERE / "scripts"
DEPS = CFG_DIR / ".deps"
RUNTIME = CFG_DIR / "runtime"
LOG_PATH = RUNTIME / "last-run.log"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制直连，绕开本机代理
JSON_MODE = False   # --json 时 stdout 只允许出现一个 JSON 对象，失败也不例外


def die(msg):
    """失败也要守 JSON 契约：调用方能拿到 error 与日志位置，而不是空 stdout。"""
    if JSON_MODE:
        print(json.dumps({"ok": False, "error": msg, "log": str(LOG_PATH)},
                         ensure_ascii=False, indent=2))
    else:
        print("错误: " + msg)
    raise SystemExit(1)


def note(msg, quiet=False):
    """非结果性提示：json 模式写 stderr，保证 stdout 是纯 JSON。"""
    print("⚠ " + msg, file=sys.stderr if quiet else sys.stdout)


def load_config(quiet=False):
    override = os.environ.get("OSS_PAGES_SYNC_CONFIG")
    path = pathlib.Path(override).expanduser() if override else CONFIG
    if not path.is_file():
        if not quiet:
            print("配置: 内置模板（占位值，只能离线试跑）: %s" % EXAMPLE)
        path = EXAMPLE
    elif not quiet:
        print("配置: %s" % path)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die("读取配置失败：%s" % exc)
    if "oss" not in cfg or "sites" not in cfg:
        die("配置是旧格式（扁平 domain/bucket/level）。请按 %s 升级为 oss/sites/verify/ci 四段结构"
            % EXAMPLE)
    cfg.setdefault("verify", {"level": 2})
    cfg.setdefault("ci", {})
    if path != EXAMPLE:
        ensure_config_perm(path, quiet=quiet)
    return cfg, path


def ensure_config_perm(path, quiet=False):
    """含 AK/SK 的配置文件必须 600；发现过宽则收紧并明示。"""
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            path.chmod(0o600)
            if not quiet:
                print("安全: 已把配置权限 %o 收紧为 600" % mode)
    except OSError as exc:
        if not quiet:
            print("警告: 无法检查配置权限（%s）" % exc)


def clean_domain(value):
    raw = str(value or "").strip().replace("https://", "").replace("http://", "")
    return raw.split("/")[0] or "your-domain.cn"


def credentials(cfg):
    """config.oss 的 AK/SK 优先；回落环境变量、~/.ossutilconfig。密钥绝不写进仓库。"""
    oss = cfg.get("oss") or {}
    kid = str(oss.get("access_key_id") or "").strip()
    ksec = str(oss.get("access_key_secret") or "").strip()
    if kid and ksec and not kid.startswith("YOUR_") and not ksec.startswith("YOUR_"):
        return kid, ksec, "config.json"
    kid, ksec = os.environ.get("OSS_ACCESS_KEY_ID"), os.environ.get("OSS_ACCESS_KEY_SECRET")
    if kid and ksec:
        return kid, ksec, "环境变量"
    path = pathlib.Path.home() / ".ossutilconfig"
    try:
        if path.is_file():
            cp = configparser.RawConfigParser()
            cp.read(str(path))
            sec = "default" if cp.has_section("default") else (cp.sections() or [None])[0]
            if sec and cp.has_option(sec, "accessKeyID") and cp.has_option(sec, "accessKeySecret"):
                return cp.get(sec, "accessKeyID"), cp.get(sec, "accessKeySecret"), "~/.ossutilconfig"
    except (OSError, configparser.Error) as exc:
        note("读取 ~/.ossutilconfig 失败（%s）" % exc, JSON_MODE)
    return None, None, "未配置"


def make_env():
    env = os.environ.copy()
    parts = [str(DEPS)] if DEPS.is_dir() else []
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def check_deps(env, level):
    mods = ["oss2"] + (["websocket"] if level >= 3 else [])
    try:
        r = subprocess.run([sys.executable, "-c", "import " + ", ".join(mods)],
                           env=env, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, ", ".join(mods)
    except (OSError, subprocess.SubprocessError) as exc:
        print("依赖检查失败：%s" % exc)
        return False, ", ".join(mods)


def install_deps():
    DEPS.mkdir(parents=True, exist_ok=True)
    print("安装依赖到 %s ..." % DEPS)
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
                            "--target", str(DEPS), "oss2", "websocket-client"])
    except (OSError, subprocess.SubprocessError) as exc:
        die("安装依赖失败：%s" % exc)
    if r.returncode == 0:
        print("完成：oss2 / websocket-client 已装进配置目录，不污染系统 Python。")
    return r.returncode


def list_sites(cfg):
    print("=== config.sites（%d 站）===" % len(cfg["sites"]))
    for item in cfg["sites"]:
        print("  %-24s %s%s" % (item["name"], item["url"], "  [root=1]" if item.get("root") else ""))


def selected(cfg, only):
    return [s for s in cfg["sites"] if not only or s["name"] == only]


def post_check(domain, items, quiet=False):
    """验真铁律：同步后逐个真实 GET 线上首页，不能只信退出码。"""
    if not quiet:
        print("\n=== 线上首页探活（真实远端请求）===")
    rows = []
    for item in items:
        url = "https://%s/%s/" % (domain, item["name"])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (oss-skill)",
                                                   "Range": "bytes=0-0"})
        try:
            with OPENER.open(req, timeout=12) as resp:
                code = resp.status
                resp.read(1)
        except urllib.error.HTTPError as exc:
            code = exc.code
        except Exception as exc:
            code = str(exc)[:60]
        ok = code in (200, 206)
        if not quiet:
            print("  %s %-56s %s" % ("✓" if ok else "✗", url, code))
        rows.append({"name": item["name"], "url": url, "home_status": code, "ok": ok})
    return rows


def cmd_sync(args, cfg):
    oss = cfg["oss"]
    domain = clean_domain(args.domain or oss.get("domain"))
    if domain == "your-domain.cn":
        note("目标域名还是占位值，请检查 config.oss.domain", args.json)
    bucket = args.bucket or oss.get("bucket") or "YOUR_OSS_BUCKET_NAME"
    endpoint = args.endpoint or oss.get("endpoint") or "https://oss-cn-hangzhou.aliyuncs.com"
    level = int(args.level or (cfg.get("verify") or {}).get("level") or 2)
    depth = args.depth
    if level >= 3 and depth > 0:
        note("L3 需要全量抓取才能比对 DOM，已强制 --depth 0", args.json)
        depth = 0
    apply = args.apply and not args.check_only
    items = selected(cfg, args.site)
    if not items:
        die("没有匹配的站点，检查 --site / config.sites")
    kid, ksec, cred_from = credentials(cfg)
    env = make_env()
    ok, mods = check_deps(env, level)
    if not ok:
        die("缺少依赖 %s；先执行：python3 %s --install-deps" % (mods, pathlib.Path(__file__).resolve()))
    if not (kid and ksec):
        if apply:
            die("没有 OSS 凭据却要求 --apply；请填 config.oss.access_key_id / access_key_secret")
        note("未找到 OSS 凭据，本次只做离线抓取 + 引用探活，清单比对会被跳过。", args.json)

    RUNTIME.mkdir(parents=True, exist_ok=True)
    sites_conf = RUNTIME / "sites.conf"
    sites_conf.write_text(ci_manage.render_sites_conf(cfg), encoding="utf-8")
    staging = RUNTIME / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    names = [s["name"] for s in items]

    if not args.json:
        print("=== oss-pages-sync ===")
        print("模式: %s | 域名: %s | 验真: L%d | 抓取深度: %s" %
              ("同步（写入 OSS）" if apply else "检查（不写入）", domain, level,
               "不限" if not depth else depth))
        print("站点: %s" % ", ".join(names))
        print("配置: oss=%s | 脚本=%s | 凭据=%s" % (bucket, SCRIPTS, cred_from))
        sys.stdout.flush()

    env.update({
        "OSS_SITES_CONF": str(sites_conf),
        "OSS_STAGING_DIR": str(staging),
        "OSS_TARGET_DOMAIN": domain,
        "OSS_BUCKET": bucket,
        "OSS_ENDPOINT": endpoint,
        "ONLY_SITE": args.site,
        "OSS_MAX_DEPTH": str(depth),
        "SYNC_DRY_RUN": "0" if apply else "1",
        "REQUIRE_UPLOAD": "1" if apply else "0",
        # 按 pid 隔离：并发跑两次不会互相 unlink / 覆盖对方的 changed 输出
        "GITHUB_OUTPUT": str(RUNTIME / ("github-output-%d.txt" % os.getpid())),
    })
    out_file = pathlib.Path(env["GITHUB_OUTPUT"])
    out_file.unlink(missing_ok=True)
    if kid and ksec:
        env["OSS_ACCESS_KEY_ID"] = kid
        env["OSS_ACCESS_KEY_SECRET"] = ksec

    log = None
    if args.json:
        log = open(LOG_PATH, "w", encoding="utf-8")
        sink = dict(stdout=log, stderr=subprocess.STDOUT)
    else:
        sink = {}
    try:
        if not args.json:
            print("\n--- 抓取 / 比对 / 上传 ---", flush=True)
        try:
            r1 = subprocess.run([sys.executable, "ci_sync.py"], cwd=str(SCRIPTS), env=env, **sink).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            die("ci_sync.py 执行失败：%s" % exc)
        outputs = {}
        if out_file.is_file():
            for line in out_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    outputs[key] = value
        if r1 != 0:
            if args.json:
                print(json.dumps({"ok": False,
                                  "error": "ci_sync.py 退出码 %d，已中止（未继续验真）" % r1,
                                  "verify": "NOT_RUN", "log": str(LOG_PATH)},
                                 ensure_ascii=False, indent=2))
            else:
                print("\n结果: FAIL（ci_sync.py 退出码 %d），未继续验真。" % r1)
            return 1
        if not args.json:
            print("\n--- 验真 L%d ---" % level, flush=True)
        try:
            r2 = subprocess.run([sys.executable, "verify.py", "--level", str(level)],
                                cwd=str(SCRIPTS), env=env, **sink).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            die("verify.py 执行失败：%s" % exc)
    finally:
        if log:
            log.close()

    rows = post_check(domain, items, quiet=args.json)
    bad = sum(1 for r in rows if not r["ok"])
    verify = "PASS" if r2 == 0 else "FAIL"
    warnings = []
    if outputs.get("crawl_errors") == "true":
        warnings.append("抓取阶段有失败（常见为瞬时 TLS/DNS 抖动）；L2 清单与引用探活仍通过，建议重跑确认")
    result = {
        "ok": r2 == 0 and bad == 0,
        "warnings": warnings,
        "mode": "apply" if apply else "check",
        "domain": domain,
        "level": level,
        "changed": outputs.get("changed", "?"),
        "uploaded": outputs.get("uploaded", "?"),
        "crawl_errors": outputs.get("crawl_errors", "?"),
        "verify": verify,
        "home_bad": bad,
        "sites": rows,
        "log": str(LOG_PATH),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n=== 同步后的镜像地址 ===")
        for row in rows:
            print("  %-24s %-56s %s" % (row["name"], row["url"], row["home_status"]))
        print("\n=== 结论 ===")
        print("变化: %s | 上传对象: %s | 抓取故障: %s | L%d: %s | 线上首页异常: %d" %
              (result["changed"], result["uploaded"], result["crawl_errors"],
               level, verify, bad))
        for warning in warnings:
            print("⚠ " + warning)
        if not apply:
            print("本次未写入 OSS；要真正同步请加 --apply。")
    return 0 if result["ok"] else 1


def main():
    ap = argparse.ArgumentParser(description="静态站 OSS 镜像：检查 / 同步 / CI 托管")
    ap.add_argument("--domain", help="覆盖 config.oss.domain")
    ap.add_argument("--level", choices=("1", "2", "3"), help="验真层级（默认 config.verify.level）")
    ap.add_argument("--site", default="", help="只处理某个站点，留空 = 全部")
    ap.add_argument("--depth", type=int, default=0, help="抓取 BFS 层数，0 = 不限（正式同步必须 0）")
    ap.add_argument("--apply", action="store_true", help="真正写入 OSS；不加则只比对 + 检查")
    ap.add_argument("--check-only", action="store_true", help="显式声明只检查（与默认相同）")
    ap.add_argument("--bucket", help="覆盖 config.oss.bucket")
    ap.add_argument("--endpoint", help="覆盖 config.oss.endpoint")
    ap.add_argument("--json", action="store_true", help="只输出结构化 JSON 结果，日志写入 runtime/last-run.log")
    ap.add_argument("--list", action="store_true", help="列出 config.sites 后退出")
    ap.add_argument("--install-deps", action="store_true", help="首次安装依赖后退出")
    sub = ap.add_subparsers(dest="cmd")
    ci = sub.add_parser("ci", help="设置与维护指定 repo 的自动同步")
    ci.add_argument("action", choices=("setup", "update", "status", "run", "enable", "disable"))
    ci.add_argument("--no-wait", action="store_true", help="ci run 只触发不等待结论")
    args = ap.parse_args()

    global JSON_MODE
    JSON_MODE = bool(args.json)   # 必须在任何 die()/note() 之前设置

    if args.install_deps:
        return install_deps()
    try:
        cfg, _ = load_config(quiet=args.json)
    except SystemExit:
        raise
    if args.cmd == "ci":
        return ci_manage.dispatch(args.action, cfg, wait=not args.no_wait)
    if args.list:
        list_sites(cfg)
        return 0
    return cmd_sync(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
