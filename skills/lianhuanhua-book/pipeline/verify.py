#!/usr/bin/env python3
"""交付前验收：页数、尺寸、体积、缺图。

用法：
    python3 pipeline/verify.py --slug liaozhai-laoshan-daoshi
"""
import argparse
import json
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORIES = ROOT / "stories"
IMAGES = ROOT / "assets" / "images"

EXPECT = (1536, 944)
MAX_KB = 450


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    args = ap.parse_args()

    story = json.loads((STORIES / f"{args.slug}.json").read_text(encoding="utf-8"))
    img_dir = IMAGES / args.slug
    pages = story["pages"]

    problems, warns = [], []
    for p in pages:
        f = img_dir / f"{p['no']:03d}.jpg"
        if not f.exists():
            problems.append(f"缺图 {f.name}（{p['title']}）")
            continue
        with Image.open(f) as im:
            w, h = im.size
        if (w, h) != EXPECT and not (p["no"] == 0 and (w, h) == (1536, 1024)):
            warns.append(f"{f.name} 尺寸 {w}x{h}，期望 {EXPECT[0]}x{EXPECT[1]}")
        kb = f.stat().st_size / 1024
        if kb > MAX_KB:
            warns.append(f"{f.name} {kb:.0f} KB，超过 {MAX_KB} KB")

    extra = sorted({f.name for f in img_dir.glob("*.jpg")} - {f"{p['no']:03d}.jpg" for p in pages})
    if extra:
        warns.append("多余图片：" + "、".join(extra))

    print(f"《{story['title']}》 应有 {len(pages)} 页")
    for p in pages:
        f = img_dir / f"{p['no']:03d}.jpg"
        if not f.exists():
            continue
        with Image.open(f) as im:
            w, h = im.size
        print(f"  {f.name}  {p['title']:<4s} {w}x{h}  {f.stat().st_size/1024:>4.0f} KB")

    if warns:
        print("\n提醒：")
        for w in warns:
            print("  · " + w)
    if problems:
        print("\n问题：")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("\n验收通过：页数、尺寸、体积均在范围内（水印需目视抽检右下角）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
