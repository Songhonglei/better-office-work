#!/usr/bin/env python3
"""字形审计：找出字体里"渲染成实心黑块"的汉字

背景：站酷小薇（ZCOOL XiaoWei）里「回」「圃」这类字的内轮廓绕向与外轮廓相同，
按 nonzero 填充规则孔洞被填满，Chrome 和 Pillow 都会渲染成实心黑方块。
这不是缺字（cmap 有、glyph 也有轮廓），cmap 检查抓不到，只能靠实际渲染。

做法：用 GB2312 一级字（3755 字）逐字渲染，算字形外框内的墨迹占比。
实心黑块占比接近 1，正常汉字一般 0.2~0.6，阈值默认 0.85。

用法：
  python3 font_audit.py ~/.cache/mp2xhs/fonts/*.ttf
  python3 font_audit.py font.ttf --threshold 0.85 --limit 20
  python3 font_audit.py font.ttf --chars "回国圃圈"    # 只查指定字

退出码：0 = 无问题字；1 = 发现问题字
"""
import argparse
import glob
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # noqa: PERF203
    sys.exit("[ERROR] 需要 Pillow：pip3 install Pillow")

SIZE = 96
CANVAS = SIZE + 24
INK_MAX = 128  # 灰度阈值，低于它算墨迹
# 实心黑块的判定：墨迹占比高，且外框本身是个"够大够方"的块。
# 只卡占比会把「一」这种一横填满自身外框的字误判成黑块（它的外框高度只有几像素）。
MIN_W = int(SIZE * 0.25)
MIN_H = int(SIZE * 0.25)
MIN_RATIO = 0.85


def gb2312_level1():
    chars = []
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return chars


def audit(path, chars, threshold):
    font = ImageFont.truetype(path, SIZE)
    bad = []
    for ch in chars:
        im = Image.new("L", (CANVAS, CANVAS), 255)
        ImageDraw.Draw(im).text((12, 6), ch, font=font, fill=0)
        px = im.load()
        # 先找墨迹外框
        xs, ys = [], []
        for y in range(CANVAS):
            for x in range(CANVAS):
                if px[x, y] < INK_MAX:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            continue  # 空白（缺字形），单独统计
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = x1 - x0 + 1, y1 - y0 + 1
        # 「一」「二」这类窄条字外框本身很小，占比必然接近 1，不是黑块
        if w < MIN_W or h < MIN_H:
            continue
        area = w * h
        ink = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if px[x, y] < INK_MAX:
                    ink += 1
        ratio = ink / area
        if ratio >= threshold:
            bad.append((ch, round(ratio, 3)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fonts", nargs="+", help="字体文件（支持通配符）")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--chars", default="", help="只查这些字（默认 GB2312 一级字 3755）")
    ap.add_argument("--limit", type=int, default=15, help="每款字体打印多少样例")
    args = ap.parse_args()

    paths = []
    for p in args.fonts:
        paths.extend(sorted(glob.glob(os.path.expanduser(p))) or [os.path.expanduser(p)])

    chars = list(dict.fromkeys(args.chars)) if args.chars else gb2312_level1()
    print(f"审计 {len(paths)} 款字体 × {len(chars)} 字，阈值 {args.threshold}")
    print(f"{'字体':38s} {'问题字':>6s}  样例")
    print("-" * 90)

    total_bad = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"{os.path.basename(p):38s}  [跳过] 文件不存在")
            continue
        bad = audit(p, chars, args.threshold)
        total_bad += len(bad)
        sample = "".join(c for c, _ in bad[: args.limit])
        print(f"{os.path.basename(p):38s} {len(bad):6d}  {sample}")
        if len(bad) > args.limit:
            print(f"{'':38s} {'':6s}  …共 {len(bad)} 个")

    print("-" * 90)
    if total_bad:
        print(f"⚠️  共 {total_bad} 个问题字会渲染成实心黑块。含这些字的标题请换字或换字体方案。")
    else:
        print("✅ 没有发现黑块字。")
    sys.exit(1 if total_bad else 0)


if __name__ == "__main__":
    main()
