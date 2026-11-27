#!/usr/bin/env python3
"""本地预览用的静态服务器。

和 `python3 -m http.server` 的唯一区别：所有响应带 `Cache-Control: no-cache`，
浏览器每次都会带 If-Modified-Since 回来校验，改完图/改完脚本刷新即见，
不会再出现「文件已经换了、浏览器还在显示旧图」。

用法：
    python3 pipeline/serve.py [端口]       # 默认 8788，只监听 127.0.0.1
"""
import functools
import http.server
import pathlib
import socketserver
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "site"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # no-cache = 可以缓存，但每次必须先校验；内容没变才回 304
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        # 只报 4xx/5xx，正常请求不刷屏
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
    if not (ROOT / "index.html").exists():
        print("站点尚未构建，先跑：python3 pipeline/build_site.py", file=sys.stderr)
        return 1
    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"小人书预览 http://127.0.0.1:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
