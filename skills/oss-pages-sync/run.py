#!/usr/bin/env python3
# oss-pages-sync Skill 的统一入口：解析「域名 + 验真层级」，跑同步/检查并做远端验真。
#
#   python3 run.py --list
#   python3 run.py                                   # 只比对 + L2 检查（不写入 OSS）
#   python3 run.py --apply                          # 真同步 + L2
#   python3 run.py --domain other.cn --level 3 --apply --site html-golive
#   python3 run.py --install-deps                   # 首次：把依赖装进 skill 自己的 .deps/
import argparse
import configparser
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).parent
# 用户配置放在 skill 目录之外：skill 重装/升级时不会被覆盖或删除。
CONFIG = pathlib.Path.home() / ".workbuddy" / "oss-pages-sync" / "config.json"
EXAMPLE = HERE / "config.example.json"
BUNDLED = HERE / "scripts"
# 依赖也放 skill 目录之外：属于可重建的运行时产物，不该进 skill 包，
# 也不会被审计器当成「skill 目录内的数据文件」或构建残留。
DEPS = pathlib.Path.home() / ".workbuddy" / "oss-pages-sync" / ".deps"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制直连，绕开本机代理


def load_config():
    """外部用户配置 → 内置模板；显式指定的路径无效时报错，不静默降级。"""
    override = os.environ.get("OSS_PAGES_SYNC_CONFIG")
    if override:
        p = pathlib.Path(override).expanduser()
        if not p.is_file():
            print("OSS_PAGES_SYNC_CONFIG 指向的配置文件不存在：%s" % p)
            sys.exit(1)
        print("配置: %s（环境变量）" % p)
        return json.loads(p.read_text(encoding="utf-8"))
    if CONFIG.is_file():
        print("配置: %s（用户配置）" % CONFIG)
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    if EXAMPLE.is_file():
        print("配置: %s（内置模板；建议复制到 %s 后按本机情况修改）" % (EXAMPLE, CONFIG))
        return json.loads(EXAMPLE.read_text(encoding="utf-8"))
    print("找不到配置文件；请把 config.example.json 复制到 %s" % CONFIG)
    sys.exit(1)


def resolve_home(cfg):
    """环境变量 → 配置里的仓库真源 → skill 内置副本。显式路径无效必须报错。"""
    override = os.environ.get("OSS_PAGES_SYNC_HOME")
    if override:
        p = pathlib.Path(override).expanduser()
        if not ((p / "sync.py").is_file() and (p / "ci_sync.py").is_file()):
            print("OSS_PAGES_SYNC_HOME 不是有效脚本目录（缺 sync.py / ci_sync.py）：%s" % p)
            sys.exit(1)
        return p.resolve(), "OSS_PAGES_SYNC_HOME"
    for raw, label in ((cfg.get("script_home"), "配置 script_home"),
                       (str(BUNDLED), "内置副本")):
        if raw:
            p = pathlib.Path(raw).expanduser()
            if (p / "sync.py").is_file() and (p / "ci_sync.py").is_file():
                return p.resolve(), label
    print("找不到脚本目录（sync.py / ci_sync.py），检查配置的 script_home")
    sys.exit(1)


def credentials():
    """密钥只从环境变量或本机 ~/.ossutilconfig 读，绝不写进 skill 文件。"""
    kid = os.environ.get("OSS_ACCESS_KEY_ID")
    ksec = os.environ.get("OSS_ACCESS_KEY_SECRET")
    if kid and ksec:
        return kid, ksec, "环境变量"
    path = pathlib.Path.home() / ".ossutilconfig"
    if path.is_file():
        cp = configparser.RawConfigParser()
        cp.read(str(path))
        sec = "default" if cp.has_section("default") else (cp.sections() or [None])[0]
        if sec and cp.has_option(sec, "accessKeyID") and cp.has_option(sec, "accessKeySecret"):
            return cp.get(sec, "accessKeyID"), cp.get(sec, "accessKeySecret"), "~/.ossutilconfig"
    return None, None, "未配置"


def make_env(cfg, deps_ok=True):
    env = os.environ.copy()
    parts = [str(DEPS)] if deps_ok and DEPS.is_dir() else []
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def check_deps(env, level):
    mods = ["oss2"] + (["websocket"] if level >= 3 else [])
    code = "import " + ", ".join(mods)
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    return r.returncode == 0, ", ".join(mods)


def install_deps():
    DEPS.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
           "--target", str(DEPS), "oss2", "websocket-client"]
    print("安装依赖到 %s ..." % DEPS)
    r = subprocess.run(cmd)
    if r.returncode == 0:
        print("完成：oss2 / websocket-client 已装进 skill 私有目录，不污染系统 Python。")
    return r.returncode


def list_sites(home):
    conf = home / "sites.conf"
    print("=== sites.conf（%s）===" % home)
    for line in conf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            print("  " + line)


def sites_of(home, only):
    out = []
    for line in (home / "sites.conf").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name = line.split("|")[0].strip()
            if not only or name == only:
                out.append(name)
    return out


def post_check(domain, names):
    """验真铁律：同步后必须真发一次请求看线上响应，不能只信退出码。"""
    print("\n=== 线上首页探活（真实远端请求）===")
    bad = 0
    for repo in names:
        url = "https://%s/%s/" % (domain, repo)
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
        print("  %s %-58s %s" % ("✓" if ok else "✗", url, code))
        if not ok:
            bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser(description="静态站 OSS 镜像：检查 / 同步 / 验真")
    ap.add_argument("--domain", help="目标镜像域名（默认取 config.json，如 your-domain.cn）")
    ap.add_argument("--level", choices=("1", "2", "3"), help="验真层级 1/2/3（默认取 config.json）")
    ap.add_argument("--site", default="", help="只处理某个站点，留空 = 全部")
    ap.add_argument("--depth", type=int, default=0, help="抓取 BFS 层数，0 = 不限（正式同步必须 0）")
    ap.add_argument("--apply", action="store_true", help="真正写入 OSS；不加则只比对 + 检查")
    ap.add_argument("--check-only", action="store_true", help="显式声明只检查（与默认行为一致）")
    ap.add_argument("--bucket", help="覆盖 OSS bucket 裸名")
    ap.add_argument("--endpoint", help="覆盖 OSS endpoint")
    ap.add_argument("--list", action="store_true", help="列出 sites.conf 的站点后退出")
    ap.add_argument("--install-deps", action="store_true", help="首次安装依赖到 skill/.deps 后退出")
    args = ap.parse_args()

    if args.install_deps:
        return install_deps()
    cfg = load_config()
    home, source = resolve_home(cfg)
    if args.list:
        list_sites(home)
        return 0

    # 与 sync.py 的 _clean_domain 保持一致：只取 host，否则 --domain x.cn/foo
    # 会让「改写目标」用 x.cn、「验真/探活目标」用 x.cn/foo，静默验错对象。
    raw_domain = (args.domain or cfg.get("domain") or "your-domain.cn").strip()
    raw_domain = raw_domain.replace("https://", "").replace("http://", "")
    domain = raw_domain.split("/")[0] or "your-domain.cn"
    level = int(args.level or cfg.get("level") or 2)
    depth = args.depth
    if level >= 3 and depth > 0:
        print("⚠ L3 需要全量抓取才能比对 DOM，已强制 --depth 0")
        depth = 0
    apply = args.apply and not args.check_only
    kid, ksec, cred_from = credentials()

    env = make_env(cfg)
    ok, mods = check_deps(env, level)
    if not ok:
        print("缺少依赖 %s；先执行：python3 %s --install-deps" % (mods, pathlib.Path(__file__).resolve()))
        return 1
    if not (kid and ksec):
        if apply:
            print("拒绝执行：没有 OSS 凭据却要求 --apply。请设置环境变量或在 ~/.ossutilconfig 配置。")
            return 1
        print("⚠ 未找到 OSS 凭据，本次只做离线抓取 + 引用探活，清单比对会被跳过。")

    names = sites_of(home, args.site)
    if not names:
        print("没有匹配的站点，检查 --site / sites.conf")
        return 1

    print("=== oss-pages-sync ===")
    print("模式: %s | 域名: %s | 验真: L%d | 抓取深度: %s" %
          ("同步（写入 OSS）" if apply else "检查（不写入）", domain, level, "不限" if not depth else depth))
    print("站点: %s" % (", ".join(names)))
    print("脚本: %s（来源 %s）| 凭据: %s" % (home, source, cred_from))
    sys.stdout.flush()  # 子进程输出会直接写 tty，先冲掉父进程缓冲区，保证计划行在最前面

    env["OSS_TARGET_DOMAIN"] = domain
    env["OSS_BUCKET"] = args.bucket or cfg.get("bucket") or "YOUR_OSS_BUCKET_NAME"
    env["OSS_ENDPOINT"] = args.endpoint or cfg.get("endpoint") or "https://oss-cn-hangzhou.aliyuncs.com"
    env["ONLY_SITE"] = args.site
    env["OSS_MAX_DEPTH"] = str(depth)
    env["SYNC_DRY_RUN"] = "0" if apply else "1"
    env["REQUIRE_UPLOAD"] = "1" if apply else "0"
    out_file = pathlib.Path(tempfile.gettempdir()) / "oss-pages-sync-output.txt"
    out_file.unlink(missing_ok=True)
    env["GITHUB_OUTPUT"] = str(out_file)
    if kid and ksec:
        env["OSS_ACCESS_KEY_ID"] = kid
        env["OSS_ACCESS_KEY_SECRET"] = ksec

    print("\n--- 抓取 / 比对 / 上传 ---", flush=True)
    r1 = subprocess.run([sys.executable, "ci_sync.py"], cwd=str(home), env=env).returncode
    outputs = {}
    if out_file.is_file():
        for line in out_file.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                outputs[k] = v
    if r1 != 0:
        print("\n结果: FAIL（ci_sync.py 退出码 %d），未继续验真。" % r1)
        return 1

    print("\n--- 验真 L%d ---" % level, flush=True)
    r2 = subprocess.run([sys.executable, "verify.py", "--level", str(level)],
                        cwd=str(home), env=env).returncode
    bad = post_check(domain, names)
    sys.stdout.flush()

    print("\n=== 结论 ===")
    print("变化: %s | 上传对象: %s | 抓取故障: %s | L%d: %s | 线上首页异常: %d" %
          (outputs.get("changed", "?"), outputs.get("uploaded", "?"),
           outputs.get("crawl_errors", "?"), level,
           "PASS" if r2 == 0 else "FAIL", bad))
    if not apply:
        print("本次未写入 OSS；要真正同步请加 --apply。")
    return 0 if (r2 == 0 and bad == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
