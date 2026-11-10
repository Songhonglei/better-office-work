#!/usr/bin/env python3
# 镜像完整性校验：把「漏文件」变成自动报红，而不是靠人眼发现页面不对。
#
#   python3 verify.py                    # 默认 L2：引用逐条探活 + 本地/远端清单比对
#   python3 verify.py --level 1          # L1：只做清单比对（最快）
#   python3 verify.py --level 3          # L3：L2 + 真实浏览器网络录制 + 源站/镜像 DOM 对比
#   python3 verify.py --deep             # --level 3 的旧写法，保持兼容
#
# L1/L2 抓不到「运行时才拼出来的 URL」，L3 能；三者互补，不追求静态保证不漏。
import argparse
import concurrent.futures
import json
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import sync

HERE = pathlib.Path(__file__).parent
STAGING = sync.STAGING
TARGET = sync.TARGET_BASE
TIMEOUT = 15
TEXT_SUFFIX = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".xml")

# 源站本身就没有、或静态镜像必然没有的资源；不算漏文件。
ALLOW_404 = {
    TARGET + "/favicon.ico",                       # 浏览器自动请求，根域没放
    TARGET + "/coding-game/favicon.svg",
    TARGET + "/coding-game/apple-touch-icon.png",
    TARGET + "/power",                             # liquidtime 的动态 API
}
# 浏览器实测：源站页面可能有外链/统计脚本，只比对同源请求。
DEEP_CLICK_IDS = ("courseButton",)                  # 已知交互入口，点一下看会不会再发请求

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制直连，绕开代理


def probe(url):
    """OSS 静态网站托管对目录首页的 HEAD 会返回 404（实测），所以一律用 GET。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (oss-verify)",
                                               "Range": "bytes=0-0"})
    try:
        with OPENER.open(req, timeout=TIMEOUT) as resp:
            resp.read(1)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:
        return str(exc)[:70]


def sites():
    only = os.environ.get("ONLY_SITE", "").strip()
    return [(r, u) for r, u in sync.load_sites() if not only or r == only]


def ensure_staging(pairs):
    """单独跑（深度校验 workflow）时 workspace 是干净的，先抓一份 staging。"""
    for repo, url in pairs:
        if not (STAGING / repo).exists() or not list((STAGING / repo).rglob("*")):
            sync.crawl(repo, url)


def collect_refs(pairs):
    """从改写后的 staging 文本里，收集所有指向镜像的本地 URL。"""
    urls = set()
    for repo, _ in pairs:
        root = STAGING / repo
        for f in sorted(root.rglob("*")):
            if not f.is_file() or not f.name.endswith(TEXT_SUFFIX):
                continue
            rel = f.relative_to(root).as_posix()
            text = f.read_text(encoding="utf-8", errors="ignore")
            # ① 已改写成的镜像绝对链接
            for u in re.findall(re.escape(TARGET) + r"/[A-Za-z0-9_./?=&#%-]+", text):
                urls.add(u.split("#")[0].split("?")[0].rstrip("/") or TARGET + "/")
            # ② 属性 / CSS url() / ES module 字面量，统一走抓取器的解析
            is_js = f.suffix.lower() in (".js", ".mjs")
            for ref in sync.extract_refs(text, rel, js_mode=is_js):
                ref = ref.lstrip("/")
                if ref == repo or ref.startswith(repo + "/"):
                    urls.add(TARGET + "/" + ref)          # 已被 rewrite 加过 /<repo> 前缀
                else:
                    urls.add(TARGET + "/" + repo + "/" + ref)
    return sorted(u for u in urls if u.startswith(TARGET + "/"))


def l2_refs(pairs):
    urls = collect_refs(pairs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda u: (u, probe(u)), urls))
    bad = [(u, code) for u, code in results
           if code not in (200, 206) and u not in ALLOW_404 and u + "/" not in ALLOW_404]
    print("=== L2 引用完整性 ===")
    print("检查 %d 个引用 | 正常 %d | 异常 %d" % (len(urls), len(urls) - len(bad), len(bad)))
    for u, code in bad[:20]:
        print("   ✗ %s  %s" % (code, u))
    return len(bad)


def l2_manifest(pairs):
    kid = os.environ.get("OSS_ACCESS_KEY_ID")
    ksec = os.environ.get("OSS_ACCESS_KEY_SECRET")
    if not (kid and ksec):
        print("=== 对象清单比对（L1/L2 共用）===\n跳过（未设置 OSS 凭据）")
        return 0
    import oss2
    auth = oss2.Auth(kid, ksec)
    bucket = oss2.Bucket(auth,
                         os.environ.get("OSS_ENDPOINT") or "https://oss-cn-hangzhou.aliyuncs.com",
                         os.environ.get("OSS_BUCKET") or "YOUR_OSS_BUCKET_NAME")
    prefixes = tuple(r + "/" for r, _ in pairs)
    remote = {o.key: o.size for o in oss2.ObjectIterator(bucket)
              if o.key.startswith(prefixes)}
    local = {}
    for repo, _ in pairs:
        root = STAGING / repo
        for f in root.rglob("*"):
            if f.is_file():
                local[repo + "/" + f.relative_to(root).as_posix()] = f.stat().st_size
    missing = sorted(set(local) - set(remote))
    # ossutil 建的 0 字节目录标记不算脏对象；其余多出来的只告警（不删）
    extra = sorted(k for k in set(remote) - set(local)
                   if not k.endswith("/") and remote[k] > 0)
    print("=== 对象清单比对（L1/L2 共用）===")
    print("本地 %d / 远端 %d | 漏传 %d | 远端多出 %d" % (len(local), len(remote), len(missing), len(extra)))
    for k in missing[:15]:
        print("   ✗ 漏传 %s" % k)
    for k in extra[:10]:
        print("   · 远端多出（旧对象，不自动删） %s" % k)
    return len(missing)


def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


def enumerate_pages(pairs):
    """从 staging 的 HTML 推导「源站页面 URL ↔ 镜像页面 URL」对照。
    index.html 视为目录页（带尾斜杠），其它 .html 视为文件页（不带）。"""
    def make_url(prefix, rel, is_index):
        prefix = prefix.rstrip("/")
        if not rel or rel == ".":
            return prefix + "/"
        return prefix + "/" + rel + ("/" if is_index else "")

    pages = []
    for repo, base in pairs:
        root = STAGING / repo
        for f in sorted(root.rglob("*.html")):
            rel = f.relative_to(root).as_posix()
            if f.name == "main.html":
                continue                      # 目录首页副本，和 index.html 同内容
            is_index = f.name in ("index.html", "index.htm")
            page = posixpath.dirname(rel) if is_index else rel
            pages.append((repo, make_url(base, page, is_index),
                          make_url(TARGET + "/" + repo, page, is_index)))
    seen, out = set(), []
    for p in pages:
        if p[2] not in seen:
            seen.add(p[2]); out.append(p)
    return out


def deep_inspect(chrome, port, url, origin):
    """用 CDP 打开页面：录同源 4xx / 失败请求，取渲染后的 DOM 指标。"""
    import websocket
    base = "http://127.0.0.1:%d" % port
    tab = json.load(urllib.request.urlopen(
        urllib.request.Request(base + "/json/new?about:blank", method="PUT"), timeout=5))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=15)
    seq = [0]
    def send(method, params=None):
        seq[0] += 1
        ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
        return seq[0]
    def evaluate(expr):
        # 主监听循环用 0.3s 短超时；执行表达式时放宽，否则慢页面会抛 WebSocketTimeout
        ws.settimeout(10)
        i = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        try:
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == i:
                    return msg.get("result", {}).get("result", {}).get("value")
        except Exception:
            return None
        finally:
            ws.settimeout(0.3)
    send("Network.enable"); send("Page.enable")
    send("Page.navigate", {"url": url})
    reqs, bad = {}, set()
    ws.settimeout(0.3)
    end = time.time() + 3.5
    while time.time() < end:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            continue
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Network.requestWillBeSent":
            u = p["request"]["url"]
            if u.startswith(origin):
                reqs[p["requestId"]] = u.split("?")[0]
        elif m == "Network.responseReceived" and p["response"]["status"] >= 400:
            rid = p["requestId"]
            if rid in reqs:
                bad.add((p["response"]["status"], reqs[rid]))
        elif m == "Network.loadingFailed" and not p.get("canceled"):
            rid = p["requestId"]
            if rid in reqs:
                bad.add(("FAIL", reqs[rid]))
    metrics = evaluate("""JSON.stringify({
        text: (document.body && document.body.innerText || '').length,
        nodes: document.querySelectorAll('*').length,
        dom: document.documentElement.outerHTML.length
    })""")
    # 已知交互入口点一下，捕捉交互后才发起的请求
    for cid in DEEP_CLICK_IDS:
        evaluate("document.getElementById(%s)?.click()" % json.dumps(cid))
    end2 = time.time() + 0.8
    while time.time() < end2:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            continue
        if msg.get("method") == "Network.responseReceived" and msg["params"]["response"]["status"] >= 400:
            p = msg["params"]
            if p["requestId"] in reqs:
                bad.add((p["response"]["status"], reqs[p["requestId"]]))
    ws.close()
    try:
        urllib.request.urlopen(base + "/json/close/" + tab["id"], timeout=3).read()
    except Exception:
        pass
    return bad, json.loads(metrics or "{}")


def l3_deep(pairs):
    chrome = find_chrome()
    if not chrome:
        print("=== L3 深度验真 ===\n✗ 找不到 Chrome，无法运行")
        return 1
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("=== L3 深度验真 ===\n✗ 缺少 websocket-client，先 pip install websocket-client")
        return 1
    port = 9444
    try:
        proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                                 "--remote-debugging-port=%d" % port, "--remote-allow-origins=*",
                                 "--user-data-dir=/tmp/oss-verify-chrome", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        print("=== L3 深度验真 ===\n✗ 无法启动 Chrome（%s）" % str(exc)[:100])
        return 1
    failures = 0
    try:
        base = "http://127.0.0.1:%d" % port
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/json/version", timeout=1).read()
                break
            except Exception:
                time.sleep(0.25)
        pages = enumerate_pages(pairs)
        print("=== L3 深度验真（源站 vs 镜像）===")
        skipped = 0
        for repo, src, dst in pages:
            try:
                bad, m_mirror = deep_inspect(chrome, port, dst, TARGET)
                _, m_src = deep_inspect(chrome, port, src,
                                        urllib.parse.urlsplit(src).scheme + "://" + urllib.parse.urlsplit(src).netloc)
            except Exception as exc:
                print("  ✗ %-58s 检查异常 %s" % (dst.replace(TARGET + "/", "/"), str(exc)[:60]))
                failures += 1
                continue
            real_bad = sorted((c, u) for c, u in bad if u not in ALLOW_404)
            t_src, t_dst = m_src.get("text", 0), m_mirror.get("text", 0)
            n_src, n_dst = m_src.get("nodes", 0), m_mirror.get("nodes", 0)
            if t_src == 0 or n_src < 5:
                print("  · SKIP %-56s 源站页面不可用" % dst.replace(TARGET + "/", "/"))
                skipped += 1
                continue
            drift_t = abs(t_dst - t_src) / max(t_src, 1)
            drift_n = abs(n_dst - n_src) / max(n_src, 1)
            # 正常差异来自语言版本/链接文本（实测最大约 10%）；真漏文件时文本通常差 >50% 或为 0。
            # 404 是独立的硬指标，所以文本阈值放宽不会放过漏文件。
            ok = not real_bad and drift_t <= 0.15 and drift_n <= 0.15 and t_dst > 0
            print("  %s %-58s 文本 %5d/%5d (%.0f%%) 节点 %4d/%4d 404=%d" %
                  ("✓" if ok else "✗", dst.replace(TARGET + "/", "/"),
                   t_dst, t_src, drift_t * 100, n_dst, n_src, len(real_bad)))
            for c, u in real_bad[:5]:
                print("      404 %s  %s" % (c, u))
            if not ok:
                failures += 1
        print("L3 页面数 %d | 异常 %d | 跳过 %d" % (len(pages), failures, skipped))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true", help="兼容旧用法：等价于 --level 3")
    ap.add_argument("--level", choices=("1", "2", "3"), default=None,
                    help="验真层级 1=清单比对 / 2=+引用探活(默认) / 3=+浏览器深度验真")
    args = ap.parse_args()
    level = 3 if args.deep else int(args.level or 2)
    pairs = sites()
    if not pairs:
        print("没有匹配的站点，检查 ONLY_SITE / sites.conf")
        return 1
    print("验真层级: L%d | 目标域名: %s | 站点: %s" %
          (level, sync.TARGET_DOMAIN, ", ".join(r for r, _ in pairs)))
    ensure_staging(pairs)
    bad = 0
    bad += l2_manifest(pairs)                 # L1：本地 staging ↔ 远端对象清单
    if level >= 2:
        bad += l2_refs(pairs)                 # L2：页面引用逐条 GET 探活
    if level >= 3:
        bad += l3_deep(pairs)                 # L3：Chrome 录 404 + DOM 对比
    print("\n结果: %s" % ("PASS" if bad == 0 else "FAIL (%d 项异常)" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
