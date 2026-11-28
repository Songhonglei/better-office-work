#!/usr/bin/env python3
"""把 stories/*.json + assets/images 构建成静态站。

用法：
    python3 pipeline/build_site.py
    python3 pipeline/build_site.py --clean      # 先清空 site/
"""
import argparse
import html
import json
import pathlib
import shutil
import tempfile
import hashlib
import uuid

from PIL import Image
from common import load_story, file_sha
from verify import check

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORIES = ROOT / "stories"
TEMPLATES = ROOT / "templates"
IMAGES = ROOT / "assets" / "images"
SITE = ROOT / "site"

# 系列配置：stories/_series.json（可选）。缺省时用下面的兜底值。
SERIES_FILE = STORIES / "_series.json"
SERIES = {
    "title": "故事小人书",
    "subtitle": "一页一景 · 上图下文 · 说书人的旁白",
    "note": "每篇 12—20 页，一页一个情节瞬间，3—5 分钟读完一篇。",
    "footer": "",
    "planned": [],
}
if SERIES_FILE.exists():
    SERIES.update(json.loads(SERIES_FILE.read_text(encoding="utf-8")))
PLANNED = SERIES.get("planned") or []

CN = "零一二三四五六七八九十"


def cn_num(n: int) -> str:
    if n <= 10:
        return "十" if n == 10 else CN[n]
    if n < 20:
        return "十" + CN[n - 10]
    if n < 100:
        t, u = divmod(n, 10)
        return CN[t] + "十" + (CN[u] if u else "")
    return str(n)


def page_label(no: int) -> str:
    return "序" if no == 0 else cn_num(no)


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def book_credit(story):
    return " · ".join(part.strip() for part in (story["book"], story.get("author", "")) if part.strip())


def caption_html(page, colophon=""):
    caption = "\n".join(page["caption_lines"]) if "caption_lines" in page else page["caption"]
    if not caption.strip():
        return ""
    legacy_lines = " caption-lines" if "caption_lines" in page else ""
    extra = f'\n      <p class="colophon">{esc(colophon)}</p>' if colophon.strip() else ""
    return f'''\n    <figcaption class="caption">
      <p class="caption-body{legacy_lines}">{esc(caption.strip())}</p>{extra}
    </figcaption>'''


def asset_ver() -> str:
    """静态资源内容哈希。"""
    h = hashlib.sha256()
    for f in ("style.css", "reader.js"):
        p = TEMPLATES / f
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def read_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8").replace("__VER__", asset_ver())


def img_ver(p: pathlib.Path) -> str:
    """图片内容指纹（mtime×size），拼到 URL 上避免浏览器缓存旧图。"""
    if not p.exists():
        return "0"
    return file_sha(p)[:16]


def build_read(story: dict) -> str:
    slug = story["slug"]
    img_dir = IMAGES / slug
    spreads, missing = [], []

    pages = story["pages"]
    total_pages = len(pages) - 1
    author = story.get("author", "").strip()
    cover_credit = f'\n    <div class="sub">{esc(author)}</div>' if author else ""

    for p in pages:
        no = p["no"]
        img = img_dir / f"{no:03d}.jpg"
        if not img.exists():
            missing.append(img.name)
        rel = f"../../assets/{slug}/{no:03d}.jpg?v={img_ver(img)}"
        alt = esc(f"{story['title']}·{p['title']}：{p['scene'][:36]}")
        lazy = "" if no == 0 else ' loading="lazy"'

        # 用真实尺寸写 width/height，避免图片加载后页面跳动
        if img.exists():
            with Image.open(img) as _im:
                iw, ih = _im.size
        else:
            iw, ih = 1536, 944

        frame = f'<div class="frame"><img src="{rel}" alt="{alt}" width="{iw}" height="{ih}"{lazy} decoding="async"></div>'
        if p["kind"] == "cover":
            caption = caption_html(p) if p.get("show_caption") else ""
            spreads.append(
                f'''<section class="spread cover" data-no="{no}" id="p{no}">
  <figure class="illustration">
    {frame}{caption}
  </figure>
  <div class="cover-title">
    <h2>{esc(story['title'])}</h2>{cover_credit}
  </div>
</section>'''
            )
        else:
            colophon = story.get("colophon", "") if no == total_pages else ""
            spreads.append(
                f'''<section class="spread" data-no="{no}" id="p{no}">
  <div class="pno">第 {page_label(no)} 页</div>
  <figure class="illustration">
    {frame}{caption_html(p, colophon)}
  </figure>
</section>'''
            )

    tpl = read_template("read.html")
    out = (
        tpl.replace("__TITLE__", esc(story["title"]))
        .replace("__BOOK__", esc(story["book"]))
        .replace("__SUMMARY__", esc(story.get("summary", "")))
        .replace("__SPREADS__", "\n\n".join(spreads))
        .replace("__COUNT__", f"序 / {page_label(total_pages)}")
    )

    out_dir = SITE / "read" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(out, encoding="utf-8")
    return slug if not missing else f"{slug}（缺图：{'、'.join(missing)}）"


def make_thumb(src: pathlib.Path, dst: pathlib.Path, width: int = 560) -> None:
    from PIL import Image

    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    im = Image.open(src).convert("RGB")
    h = round(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(
        dst, "JPEG", quality=78, optimize=True, progressive=True
    )


def build_index(stories: list) -> None:
    by_book = {}
    for s in stories:
        by_book.setdefault(s["book"], []).append(s)

    cards = []
    for book, items in by_book.items():
        for s in items:
            pages = len(s["pages"])
            body = pages - 1
            thumb_file = SITE / "assets" / s["slug"] / "thumb.jpg"
            thumb = f"assets/{s['slug']}/thumb.jpg?v={img_ver(thumb_file)}"
            cards.append(
                f'''    <a class="card" href="read/{s['slug']}/index.html">
      <img src="{thumb}" alt="{esc(s['title'])} 封面" loading="lazy">
      <div class="card-body">
        <div class="card-book">{esc(book_credit(s))}</div>
        <h3>{esc(s['title'])}</h3>
        <p>{esc(s.get('summary', ''))}</p>
        <div class="card-meta">共 {pages} 页 · 约 {max(3, round(body * 0.35))} 分钟</div>
      </div>
    </a>'''
            )

    for book in PLANNED:
        if book in by_book:
            continue
        cards.append(
            f'''    <div class="card dim">
      <div class="card-blank">筹备中</div>
      <div class="card-body">
        <div class="card-book">待开工</div>
        <h3>{esc(book)}</h3>
        <p>选篇与边界审查中。</p>
        <div class="card-meta">—</div>
      </div>
    </div>'''
        )

    out = (
        read_template("index.html")
        .replace("__SHELF__", "\n".join(cards))
        .replace("__SERIES__", esc(SERIES["title"]))
        .replace("__SERIES_SUB__", esc(SERIES["subtitle"]))
        .replace("__SERIES_NOTE__", esc(SERIES["note"]))
        .replace("__FOOT__", f'<footer class="foot">{esc(SERIES["footer"])}</footer>' if SERIES["footer"].strip() else "")
    )
    (SITE / "index.html").write_text(out, encoding="utf-8")


def construct(stories):
    SITE.mkdir(parents=True, exist_ok=True)

    static = SITE / "static"
    static.mkdir(exist_ok=True)
    for f in ("style.css", "reader.js"):
        shutil.copy2(TEMPLATES / f, static / f)

    # 先把图片与缩略图同步进 site/，再构建 HTML（HTML 需要读图片指纹）
    for story in stories:
        src = IMAGES / story["slug"]
        dst = SITE / "assets" / story["slug"]
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for img in sorted(src.glob("*.jpg")):
            shutil.copy2(img, dst / img.name)
            n += 1
        cover = src / "000.jpg"
        if cover.exists():
            make_thumb(cover, dst / "thumb.jpg")
        print(f"复制图片 {story['slug']}：{n} 张")

    for story in stories:
        print(f"构建 {build_read(story)}")

    build_index(stories)


def main() -> int:
    global SITE
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="Compatibility flag; every build is clean")
    ap.add_argument("--require-approved", action="store_true", help="Require visual review before publishing")
    args = ap.parse_args()
    try:
        stories = [load_story(p.stem) for p in sorted(STORIES.glob("*.json")) if not p.name.startswith("_")]
        if not stories:
            raise ValueError("No stories found")
        problems = [(s["slug"], check(s, args.require_approved)) for s in stories]
        if any(issues for _, issues in problems):
            for slug, issues in problems:
                if issues:
                    print(slug + ": " + "; ".join(issues))
            return 1
    except (ValueError, OSError) as e:
        print(f"Build rejected: {e}")
        return 1
    final = SITE
    # New and old sites live side by side until the new build succeeds.
    with tempfile.TemporaryDirectory(prefix=".site-build-", dir=ROOT) as work:
        stage = pathlib.Path(work) / "new"
        # Keep the old site outside the temporary directory so a failed restore
        # (or process interruption) never deletes the last successful build.
        backup = ROOT / (".site-backup-" + uuid.uuid4().hex)
        try:
            SITE = stage
            construct(stories)
            if final.exists():
                final.rename(backup)
            try:
                stage.rename(final)
            except OSError:
                if backup.exists():
                    try:
                        backup.rename(final)
                    except OSError as exc:
                        raise RuntimeError(f"Previous site preserved at {backup}; restore it manually") from exc
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            SITE = final
    print(f"\n站点已生成：{SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
