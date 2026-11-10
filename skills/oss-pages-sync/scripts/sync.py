#!/usr/bin/env python3
# 把「已发布」的 GitHub Pages / Vercel 站点抓下来，改写链接后落到 staging/。
# 抓取只依赖 Python 标准库；正式上传走同目录 ci_sync.py（oss2 + ETag 增量），
# 旧版 sync.py --push 路径才用本机 ossutil。从线上成品抓取，不关心源仓库怎么构建。
#
#   python3 sync.py                # 默认 dry-run：抓取到 staging/ 并打印清单，不上传
#   python3 sync.py --push         # 真正上传到 OSS
#   python3 sync.py --push --site html-golive   # 只同步一个站点
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
# 站点清单与抓取产物都可由外部注入：Skill 用 config.json 生成 sites.conf 到
# ~/.workbuddy/oss-pages-sync/runtime/，CI 部署时则写在仓库的脚本目录里。
# 两者共用同一份脚本，运行时数据不落进 skill 包。
CONF = pathlib.Path(os.environ.get("OSS_SITES_CONF") or (HERE / "sites.conf"))
STAGING = pathlib.Path(os.environ.get("OSS_STAGING_DIR") or (HERE / "staging"))


def _clean_domain(value):
    d = (value or "your-domain.cn").strip()
    d = d.replace("https://", "").replace("http://", "").strip("/")
    return d.split("/")[0] or "your-domain.cn"


# 目标镜像域名可用 OSS_TARGET_DOMAIN 覆盖（Skill 的 --domain 就是写它）。
# 只影响「写死绝对链接的改写目标」和验真时的目标 URL，源站仍在 sites.conf 里配。
TARGET_DOMAIN = _clean_domain(os.environ.get("OSS_TARGET_DOMAIN"))
TARGET_BASE = "https://" + TARGET_DOMAIN
# 0 = 不限制抓取层级；>0 时只跟随 N 层相对引用（快速体检用，正式同步必须保持 0）
MAX_DEPTH = int(os.environ.get("OSS_MAX_DEPTH") or 0)
OSS_BUCKET = os.environ.get("OSS_UTIL_BUCKET") or "oss://YOUR_OSS_BUCKET_NAME"
GH_BASE = "https://songhonglei.github.io"
REWRITE_ABSOLUTE = True   # 把 HTML 里指回 github.io 的绝对链接改写成新域名
CLEAN_URLS = True         # OSS 已开「子目录首页」(SupportSubDir=true)，目录链接可直接用 /<repo>/
                          # 若回滚到未开状态，改回 False 会让脚本自动给目录链接补 index.html
TIMEOUT = 20
TEXT_EXT = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".xml")
ROOT_PATH_SITES = set()   # sites.conf 第三列写 root=1 的站点：把 /xxx 改写成 /<repo>/xxx


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (oss-pages-sync)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def rewrite_root_paths(text, repo):
    """Vite/Next/Vercel 站点常用根绝对路径（/v2/…、/_next/…），
    放进 OSS 子目录后必须补 /<repo> 前缀，否则会打到站点根域。"""
    prefix = "/" + repo

    def fix_attr(m):
        attr, quote, path = m.group(1), m.group(2), m.group(3)
        if path.startswith("//") or path.startswith(prefix + "/") or path == prefix:
            return m.group(0)
        return "%s=%s%s%s%s" % (attr, quote, prefix, path, quote)

    text = re.sub(r"""\b(src|href)\s*=\s*(["'])(/[^"']*)\2""", fix_attr, text, flags=re.I)
    text = re.sub(r"""url\(\s*(["']?)(/[^)"']+)\1\s*\)""",
                  lambda m: "url(%s%s%s%s)" % (m.group(1), prefix, m.group(2), m.group(1)), text)
    return text


def rewrite(data, repo, path, src_base=None):
    if not REWRITE_ABSOLUTE or not path.endswith(TEXT_EXT):
        return data
    text = data.decode("utf-8", errors="ignore")
    src = src_base or (GH_BASE + "/" + repo + "/")
    dst = TARGET_BASE + "/" + repo + "/"
    if not CLEAN_URLS:
        # 目录型绝对链接后面紧跟引号/尖括号 -> 补 index.html，否则会回落到根域主页
        text = re.sub(re.escape(src) + r"(?=[\"'<>\s)])", dst + "index.html", text)
    text = text.replace(src, dst)
    if not CLEAN_URLS:
        # 改写后仍是「以 / 结尾」的新域名绝对链接，以及相对目录链接，都要补 index.html
        text = re.sub(r"(" + re.escape(TARGET_BASE) + r"/[A-Za-z0-9_./-]+/)(?=[\"'<>\s)])", r"\1index.html", text)
        text = re.sub(r"""(\bhref\s*=\s*["'])([A-Za-z0-9_./-]+/)(["'])""",
                      r"\1\2index.html\3", text)
    if repo in ROOT_PATH_SITES:
        text = rewrite_root_paths(text, repo)
    return text.encode("utf-8")


def extract_refs(text, current_path, js_mode=False):
    """从 HTML/CSS/JS 里抽出本地相对引用，返回规范化后的路径。
    js_mode=True 时跳过 HTML 属性解析（避免把 JS 里的 innerHTML 模板误当资源），
    但仍扫描 ES module 的动态 import / 静态 from 模块字面量。"""
    refs = []
    if not js_mode:
        for raw in re.findall(r"""(?:src|href|data-src|data-href)\s*=\s*["']([^"']+)["']""", text, re.I):
            refs.append(raw)
        # srcset 的响应式候选："a.webp 800w, b.webp 3200w"，浏览器按视口挑一张，
        # 只抓 src 会在窄屏下 404；每段逗号分隔，取第一个 token（去掉 800w / 2x 描述符）。
        for raw in re.findall(r"""\b(?:srcset|imagesrcset|data-srcset)\s*=\s*["']([^"']+)["']""", text, re.I):
            for item in raw.split(","):
                candidate = item.strip().split()[0] if item.strip() else ""
                if candidate:
                    refs.append(candidate)
    for raw in re.findall(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", text):
        refs.append(raw)
    # ES module：import(moduleURL('./x.mjs'))、import x from './y.mjs' 等。
    # 这类模块由 JS 运行时动态加载，HTML 里没有 src/href，必须单独跟进，
    # 否则页面骨架能显示但所有内容与交互都会失效。
    for raw in re.findall(
            r"""["']((?:\./|\.\./|/)[A-Za-z0-9_./-]+\.(?:mjs|js|json|css|svg|png|jpe?g|woff2?|ttf))["']""",
            text):
        refs.append(raw)
    out = []
    for raw in refs:
        u = raw.strip()
        if not u or u.startswith(("#", "mailto:", "tel:", "data:", "javascript:", "//")):
            continue
        if "${" in u or "(" in u or ")" in u:
            continue  # CSS 里的 JS 模板字符串（url(${...toDataURL()})）不是静态资源
        u = u.split("#")[0].split("?")[0]
        if not u:
            continue
        if u.lower().startswith(("http://", "https://")):
            continue  # 外链不抓
        if u.startswith("#") or u.startswith("%23"):
            continue
        joined = urllib.parse.urljoin(current_path, u)
        joined = urllib.parse.unquote(joined).lstrip("/")
        if not joined or ".." in joined.split("/") or "#" in joined or "?" in joined:
            continue
        out.append(joined)
    return out


def crawl(repo, base_url):
    src_base = base_url.rstrip("/") + "/"
    dest = STAGING / repo
    if dest.exists():
        import shutil
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    queue, seen, saved, files, failed = [("", 0)], set(), set(), [], []
    while queue:
        path, depth = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        url = base_url.rstrip("/") + "/" + path
        try:
            data, ctype = fetch(url)
        except Exception as exc:
            failed.append((path or "/", str(exc)[:60]))
            continue
        # 目录请求落到 index.html
        save_path = path.rstrip("/") + "/index.html" if (path == "" or path.endswith("/")) else path
        save_path = save_path.lstrip("/")
        if save_path.endswith("/"):
            save_path += "index.html"
        if not save_path:
            save_path = "index.html"
        # 无扩展名但返回 HTML（如 Vercel 的 /v2）→ 当作目录，落到 index.html
        if "html" in ctype.lower() and not save_path.endswith((".html", ".htm")):
            save_path = save_path.rstrip("/") + "/index.html"
        if save_path in saved:
            continue
        saved.add(save_path)
        target = dest / save_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = rewrite(data, repo, save_path, src_base)
        target.write_bytes(payload)
        files.append((save_path, len(payload)))
        # bucket 默认首页名是 main.html：每个含 index.html 的目录都放同内容副本，
        # 开启 OSS「子目录首页」后 /<repo>/、/<repo>/en/ 这类目录链接才不会回落根主页。
        if save_path.endswith("index.html"):
            twin = dest / (save_path[: -len("index.html")] + "main.html")
            twin.parent.mkdir(parents=True, exist_ok=True)
            twin.write_bytes(payload)
            files.append((str(twin.relative_to(dest)), len(payload)))
        is_html = "html" in ctype.lower() or save_path.endswith((".html", ".htm"))
        is_js = save_path.endswith((".js", ".mjs"))
        if (is_html or save_path.endswith(".css") or is_js) and not (MAX_DEPTH and depth >= MAX_DEPTH):
            text = data.decode("utf-8", errors="ignore")
            for ref in extract_refs(text, save_path, js_mode=is_js):
                if ref not in seen:
                    queue.append((ref, depth + 1))
    return files, failed


def load_sites():
    """解析 sites.conf：名称|源站根 URL|[root=1]
    第三列 root=1 表示该站用根绝对路径，需要补 /<repo> 前缀。"""
    sites = []
    ROOT_PATH_SITES.clear()
    if not CONF.is_file():
        raise RuntimeError("找不到站点清单 %s；请用 run.py 从 config.json 生成，或设置 OSS_SITES_CONF" % CONF)
    for line in CONF.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parts = [p.strip() for p in line.split("|")]
            repo = parts[0]
            url = parts[1] if len(parts) > 1 else GH_BASE + "/" + repo + "/"
            if len(parts) > 2 and parts[2].lower().startswith("root=1"):
                ROOT_PATH_SITES.add(repo)
            sites.append((repo, url))
    return sites


def main():
    args = sys.argv[1:]
    push = "--push" in args
    only = args[args.index("--site") + 1] if "--site" in args else None
    sites = load_sites()
    total, total_bytes = 0, 0
    for repo, url in sites:
        if only and repo != only:
            continue
        print("\n=== %s  <-  %s ===" % (repo, url))
        files, failed = crawl(repo, url)
        for name, size in sorted(files):
            print("   %-58s %8d B" % (name, size))
        print("   小计: %d 个文件, %.1f KB" % (len(files), sum(s for _, s in files) / 1024))
        if failed:
            print("   ⚠ 抓取失败(需手工补): " + ", ".join("%s(%s)" % f for f in failed))
        total += len(files)
        total_bytes += sum(s for _, s in files)
        if push:
            cmd = ["ossutil", "cp", "-r", "-u", str(STAGING / repo) + "/", OSS_BUCKET + "/" + repo + "/"]
            print("   -> " + " ".join(cmd))
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except OSError as exc:
                print("   ❌ 无法执行 ossutil（%s）；请确认 ossutil 已安装并在 PATH 中" % str(exc)[:100])
                return 1
            print("   " + (r.stdout or r.stderr).strip()[-400:])
            if r.returncode != 0:
                print("   ❌ 上传失败，停止后续站点")
                return 1
            print("   ✅ 已上传 -> %s/%s/index.html" % (TARGET_BASE, repo))
    print("\n合计 %d 个文件 / %.1f KB；模式: %s" % (total, total_bytes / 1024, "上传" if push else "DRY-RUN（未上传）"))
    if not push:
        print("确认清单无误后加 --push 才会真正写入 OSS。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
