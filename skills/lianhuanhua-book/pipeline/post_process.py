#!/usr/bin/env python3
"""裁掉 AI 水印并转 Web 用 JPEG。

输入：assets/images/<slug>/_raw/NN-*.png （文件名序号即页序，出图后手工改名）
输出：assets/images/<slug>/NNN.jpg           （三位置零，构建脚本直接取用）

约定：序号 00（封面）不裁底——封面水印已用局部修补清掉，且人物脚部贴近下沿，
      再裁 80px 会削到鞋；其余页统一裁底部 80px 去掉水印。

用法：
    python3 pipeline/post_process.py --slug liaozhai-laoshan-daoshi
    python3 pipeline/post_process.py --slug liaozhai-laoshan-daoshi --cut 90
"""
import argparse
import pathlib
import re
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGES = ROOT / "assets" / "images"
TARGET_W = 1536


def process(src: pathlib.Path, dst: pathlib.Path, cut: int, quality: int) -> tuple:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if cut > 0:
        if h - cut < 200:
            raise ValueError(f"裁剪量过大：{src.name} {w}x{h} cut={cut}")
        im = im.crop((0, 0, w, h - cut))
    if im.width != TARGET_W:
        nh = round(im.height * TARGET_W / im.width)
        im = im.resize((TARGET_W, nh), Image.LANCZOS)
    im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
    return im.size, dst.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--cut", type=int, default=80, help="裁掉底部像素，默认 80")
    ap.add_argument("--quality", type=int, default=82)
    args = ap.parse_args()

    raw_dir = IMAGES / args.slug / "_raw"
    if not raw_dir.exists():
        print(f"缺目录：{raw_dir}", file=sys.stderr)
        return 1

    out_dir = IMAGES / args.slug
    done, missing = [], []
    for src in sorted(raw_dir.glob("*.png")):
        m = re.match(r"^(\d{2})", src.name)
        if not m:
            missing.append(src.name)
            continue
        dst = out_dir / f"{int(m.group(1)):03d}.jpg"
        cut_n = 0 if m.group(1) == "00" else args.cut   # 封面不裁底
        size, nbytes = process(src, dst, cut_n, args.quality)
        done.append(dst.name)
        print(f"{src.name:28s} -> {dst.name}  {size[0]}x{size[1]}  {nbytes/1024:.0f} KB")

    print(f"\n完成 {len(done)} 张")
    if missing:
        print("以下文件缺序号前缀，已跳过：" + "、".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
