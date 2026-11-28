#!/usr/bin/env python3
"""Serve a local, version-aware review workspace for one book."""
import argparse
import functools
import http.server
import io
import json
import mimetypes
import subprocess
import sys
import threading
import urllib.parse
import uuid

from PIL import Image

from common import ROOT, atomic_json, detail_rules, file_sha, get_page, load_story, read_json
from progress import book_dir, entry, find_version, locked, manifest, now, version_dir
from rework import ACTIVE, change_task, enqueue, queue_view


WORKBENCH = {
    "/": "review.html",
    "/workbench.css": "review.css",
    "/workbench.js": "review.js",
}


def state_file(story):
    return book_dir(story) / "workbench.json"


def review_state(story):
    path = state_file(story)
    return read_json(path) if path.is_file() else {"schema": 1, "choices": {}, "notes": {}}


def active_version(row, choice):
    return (find_version(row, choice) if choice else None) or find_version(row)


def book_view(story):
    ledger = manifest(story)
    state = review_state(story)
    pages, details = [], {}
    for page in story["pages"]:
        number = page["no"]
        row = entry(ledger, number)
        choice = active_version(row, state["choices"].get(str(number)))
        versions = []
        for v in row["versions"]:
            meta = v.get("metadata", {})
            models = meta.get("models", [])
            model = meta.get("model") or (models[0] if models else "")
            versions.append(dict(id=v["id"], created=v["created"], review=v["review"], model=model,
                                 digest=v["image_sha256"], note=v.get("review_note", "")))
        rules = detail_rules(story, page)
        for key, rule in rules.items():
            shared = story.get("continuity", {}).get(key)
            label = shared.get("label", key) if isinstance(shared, dict) else key
            common_rule = shared["rule"] if isinstance(shared, dict) else shared
            detail = details.setdefault(key, dict(id=key, label=label, rule=common_rule, pages=[]))
            page_rule = page.get("track", {}).get(key, "") if shared else rule
            detail["pages"].append(dict(no=number, rule=page_rule, has_crop=key in page.get("review_focus", {})))
        pages.append(dict(no=number, title=page["title"], caption=page["caption"] if number else "",
                          selected=choice["id"] if choice else None, baseline=row["selected"],
                          versions=versions, notes=state["notes"].get(str(number), []), details=list(rules)))
    reader = f"/read/{story['slug']}/" if (ROOT / "site/read" / story["slug"] / "index.html").is_file() else None
    return dict(title=story["title"], reader=reader, pages=pages,
                details=[detail for detail in details.values() if len(detail["pages"]) > 1])


def archive_lookup(story, number, version_id):
    page = get_page(story, number)
    row = entry(manifest(story), number)
    version = find_version(row, version_id)
    if version is None or not isinstance(version_id, str):
        raise ValueError("找不到这一页的图片版本")
    return page, version


def image_bytes(story, page, version, detail=None, thumbnail=False):
    path = version_dir(story, page["no"], version) / "render.jpg"
    if not path.is_file() or file_sha(path) != version["image_sha256"]:
        raise FileNotFoundError("归档图片缺失或有变动")
    if detail is None and not thumbnail:
        return path.read_bytes()
    box = page.get("review_focus", {}).get(detail)
    with Image.open(path) as source:
        image = source.convert("RGB")
        if box:
            l, t, r, b = box
            image = image.crop((int(l * image.width), int(t * image.height),
                                max(int(l * image.width) + 1, round(r * image.width)),
                                max(int(t * image.height) + 1, round(b * image.height))))
        image.thumbnail((300, 208) if thumbnail else (800, 600), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, "JPEG", quality=85)
        return output.getvalue()


def change_review(story, command):
    if not isinstance(command, dict):
        raise ValueError("批注请求格式有误")
    number = command.get("page")
    version_id = command.get("version")
    action = command.get("action")
    with locked(story):
        page, version = archive_lookup(story, number, version_id)
        state = review_state(story)
        if action == "select":
            image_bytes(story, page, version)
            state["choices"][str(number)] = version_id
        elif action == "annotate":
            message = command.get("message")
            detail = command.get("detail")
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                raise ValueError("请输入一条不超过 2000 字的批注")
            if detail is not None and (not isinstance(detail, str) or detail not in detail_rules(story, page)):
                raise ValueError("此细节不在当前页的检查清单里")
            pin = command.get("pin")
            if pin is not None and (not isinstance(pin, list) or len(pin) != 2
                                    or any(type(n) not in (float, int) or not 0 <= n <= 1 for n in pin)):
                raise ValueError("请在当前画面内定位批注")
            notes = state["notes"].setdefault(str(number), [])
            notes.append(dict(id=uuid.uuid4().hex, version=version_id, text=message.strip(),
                              detail=detail, pin=pin, resolved=False, created=now()))
        elif action == "resolve":
            note = next((item for item in state["notes"].get(str(number), [])
                         if item["id"] == command.get("note") and item["version"] == version_id), None)
            if note is None or type(command.get("resolved")) is not bool:
                raise ValueError("找不到要更新的批注")
            note["resolved"] = command["resolved"]
        else:
            raise ValueError("未知的审图操作")
        atomic_json(state_file(story), state)


def change_queue(story, command):
    if not isinstance(command, dict):
        raise ValueError("返工请求格式有误")
    action = command.get("action")
    if action == "enqueue":
        enqueue(story, command.get("page"), command.get("version"), command.get("note"), command.get("priority", 3))
    elif action == "priority":
        change_task(story, command.get("task"), rank=command.get("priority"))
    elif action == "cancel":
        change_task(story, command.get("task"), cancel=True)
    elif action == "run":
        queue = queue_view(story)
        if not queue["worker_active"] and any(task["status"] in ACTIVE | {"queued"} for task in queue["tasks"]):
            child = subprocess.Popen([sys.executable, "-B", str(ROOT / "pipeline/rework.py"), "--slug", story["slug"], "run"],
                                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            threading.Thread(target=child.wait, daemon=True).start()
    else:
        raise ValueError("未知的返工操作")
    return queue_view(story)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, slug, **kwargs):
        self.slug = slug
        super().__init__(*args, directory=ROOT / "site", **kwargs)

    def same_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def reply(self, body, mime, code=200):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, code=200):
        return self.reply(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def do_GET(self):
        if not self.same_host():
            return self.json({"error": "请使用本机工作台地址"}, 403)
        request = urllib.parse.urlsplit(self.path)
        if request.path in WORKBENCH:
            template = ROOT / "templates" / WORKBENCH[request.path]
            mime = mimetypes.guess_type(template.name)[0]
            return self.reply(template.read_bytes(), f"{mime}; charset=utf-8")
        if request.path == "/index.html" or request.path.startswith(("/read/", "/assets/", "/static/")):
            return super().do_GET()
        try:
            if request.path == "/api/book":
                return self.json(book_view(load_story(self.slug, complete=False)))
            if request.path == "/api/rework":
                return self.json(queue_view(load_story(self.slug, complete=False)))
            if request.path == "/api/image":
                params = dict(urllib.parse.parse_qsl(request.query))
                story = load_story(self.slug, complete=False)
                page, version = archive_lookup(story, int(params.get("page", "-1")), params.get("version"))
                data = image_bytes(story, page, version, params.get("detail"), params.get("thumb") == "1")
                return self.reply(data, "image/jpeg")
        except (ValueError, FileNotFoundError) as exc:
            return self.json({"error": str(exc)}, 404)
        return self.json({"error": "找不到该页面"}, 404)

    def do_POST(self):
        if self.path not in ("/api/review", "/api/rework") or not self.same_host() or self.headers.get("Origin") != "http://" + self.headers.get("Host", ""):
            return self.json({"error": "请从本机工作台保存"}, 403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 16384 or self.headers.get_content_type() != "application/json":
                raise ValueError("批注请求格式有误")
            command = json.loads(self.rfile.read(length))
            story = load_story(self.slug, complete=False)
            if self.path == "/api/rework":
                return self.json(change_queue(story, command))
            change_review(story, command)
            return self.json(book_view(story))
        except (ValueError, FileNotFoundError) as exc:
            return self.json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--port", type=int, default=8789)
    args = parser.parse_args()
    load_story(args.slug, complete=False)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Handler, slug=args.slug)) as server:
        print(f"整册审图工作台 http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
