#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量生成口播视频卡片 —— 薄封装（引用外部生成器）。

自身不做任何渲染。读取 voice_script.json 的 segments，逐段调用
xhs-image-note-release skill 的 card_generator.py（Chrome headless CSS 渲染，
Songti SC 衬线字体栈），按数组顺序输出 card_01.png ~ card_NN.png，
命名与 build_composition.py 的读取约定严格对齐。

背景图与段落的对应关系，按优先级：
  1. segments[i].image      —— 段内显式写背景图路径（最稳，推荐）
  2. --mapping map.json     —— {"s1": "images/xxx.png", ...}
  3. --images <dir>         —— 目录内图片按文件修改时间排序对齐（打印映射表供核对）

用法:
  python3 gen_cards.py --script voice_script.json --mapping map.json --out-dir assets
  python3 gen_cards.py --script voice_script.json --images images/ --dry-run

段数与背景图数不一致时直接报错退出（防止视频卡片静默错位）。
生成完成后提示跑 build_composition.py 重建时间轴。

依赖:
  - xhs-image-note-release skill（card_generator.py）
  - Google Chrome（card_generator.py 用 headless 渲染）
"""

import argparse
import json
import os
import subprocess
import sys
import time

DEFAULT_GENERATOR = os.path.expanduser(
    '~/.workbuddy/skills/xhs-image-note-release/references/card-generator/card_generator.py')

IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp')


def split_quote(text):
    """把金句自动拆成上下两行：按第一个逗号切；无逗号则整句一行。

    想完全自定义分行，在 segment 里写 "lines": ["上句", "下句"]。
    """
    for sep in ('，', ','):
        idx = text.find(sep)
        if idx > 0:
            return [text[:idx], text[idx + 1:]]
    return [text]


def resolve_images(segs, args):
    """返回与 segments 等长的背景图路径列表。任一环节对不齐就退出。"""
    n = len(segs)

    # 1) 段内显式 image 字段
    if all('image' in s for s in segs):
        paths = [s['image'] for s in segs]
        for p in paths:
            if not os.path.exists(p):
                sys.exit('背景图不存在: %s' % p)
        return paths

    # 2) --mapping JSON
    if args.mapping:
        try:
            with open(args.mapping, encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            sys.exit('mapping 文件读取失败: %s' % e)
        missing = [s['id'] for s in segs if s['id'] not in m]
        if missing:
            sys.exit('mapping 缺少段落: %s' % ', '.join(missing))
        paths = [m[s['id']] for s in segs]
        for p in paths:
            if not os.path.exists(p):
                sys.exit('背景图不存在: %s' % p)
        return paths

    # 3) --images 目录，按 mtime 排序
    if args.images:
        files = sorted(
            (os.path.join(args.images, f) for f in os.listdir(args.images)
             if f.lower().endswith(IMG_EXTS)),
            key=lambda p: os.path.getmtime(p))
        if len(files) != n:
            sys.exit('背景图数量(%d)与段落数(%d)不一致，请改用 image 字段或 --mapping 显式对齐'
                     % (len(files), n))
        return files

    sys.exit('未指定背景图来源：请在 segments 里写 image 字段，或传 --mapping / --images')


def main():
    ap = argparse.ArgumentParser(description='批量生成口播视频卡片（引用 xhs-image-note-release 生成器）')
    ap.add_argument('--script', required=True, help='voice_script.json 路径')
    ap.add_argument('--mapping', help='段落 id -> 背景图路径 的 JSON 文件')
    ap.add_argument('--images', help='背景图目录（按文件修改时间对齐段落顺序）')
    ap.add_argument('--out-dir', default='assets', help='卡片输出目录（默认 assets/）')
    ap.add_argument('--theme', default='journal', help='卡片主题（默认 journal 书页氛围）')
    ap.add_argument('--tag', default=None, help='顶部标签（默认不显示）')
    ap.add_argument('--account', default=None, help='署名（如 @雨夜心灯，默认不显示）')
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1440,
                    help='卡片高度，默认 1440（build_composition 的 card_h）')
    ap.add_argument('--generator', default=DEFAULT_GENERATOR,
                    help='card_generator.py 路径（默认引用 xhs-image-note-release）')
    ap.add_argument('--scrim', type=float, default=None, help='背景遮罩强度 0-0.92')
    ap.add_argument('--blur', type=int, default=None, help='背景高斯模糊半径')
    ap.add_argument('--cover-h', action='store_true',
                    help='只生成横屏封面 card_01_h.png（1920x1080，用第一段金句），'
                         '供视频号/抖音横屏封面使用；不与竖版卡片一起跑')
    ap.add_argument('--cover-h-size', default='1920x1080',
                    help='横屏封面尺寸，默认 1920x1080')
    ap.add_argument('--dry-run', action='store_true', help='只打印将执行的命令，不实际生成')
    a = ap.parse_args()

    if not os.path.exists(a.generator):
        sys.exit('找不到卡片生成器: %s\n  它属于 xhs-image-note-release skill，'
                 '请先安装，或用 --generator 指定路径' % a.generator)

    try:
        with open(a.script, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.exit('文案 JSON 读取失败: %s' % e)
    segs = data.get('segments') or []
    if not segs:
        sys.exit('文案里没有 segments')

    paths = resolve_images(segs, a)
    n = len(segs)

    os.makedirs(a.out_dir, exist_ok=True)

    # ── 横屏封面模式：只用首段金句，出一张 16:9 ──
    if a.cover_h:
        try:
            cw, chh = [int(x) for x in a.cover_h_size.lower().split('x')]
        except ValueError:
            sys.exit('--cover-h-size 格式应为 宽x高，例如 1920x1080')
        seg0 = segs[0]
        lines0 = seg0.get('lines') or split_quote(seg0.get('quote') or seg0['text'])
        out = os.path.join(a.out_dir, 'card_01_h.png')
        cmd = ['python3', a.generator,
               '--theme', a.theme,
               '--background', paths[0],
               '--lines', '\\n'.join(lines0),
               '--width', str(cw),
               '--height', str(chh),
               '--hide-page-number',
               '--output', out]
        if a.tag:
            cmd += ['--tag', a.tag]
        if a.account:
            cmd += ['--account', a.account]
        if a.scrim is not None:
            cmd += ['--scrim', str(a.scrim)]
        print('横屏封面 %dx%d <- %s | %s'
              % (cw, chh, os.path.basename(paths[0]), ' / '.join(lines0)))
        if a.dry_run:
            print('    (dry-run) %s' % ' '.join(cmd))
            return
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            sys.exit('横屏封面生成异常: %s' % e)
        if r.returncode != 0 or not os.path.exists(out):
            sys.exit('横屏封面生成失败:\n%s\n%s' % (r.stdout[-400:], r.stderr[-400:]))
        print('已生成 %s。发布时 COVER_HORIZONTAL 留空即会自动探测该文件。' % out)
        return

    print('段落 %d 个，背景图 %d 张，主题 %s，输出 %s/'
          % (n, len(paths), a.theme, a.out_dir))

    failures = 0
    for i, (seg, img) in enumerate(zip(segs, paths), 1):
        lines = seg.get('lines') or split_quote(seg.get('quote') or seg['text'])
        out = os.path.join(a.out_dir, 'card_%02d.png' % i)
        cmd = ['python3', a.generator,
               '--theme', a.theme,
               '--background', img,
               '--lines', '\\n'.join(lines),
               '--page-number', str(i),
               '--total-pages', str(n),
               '--width', str(a.width),
               '--height', str(a.height),
               '--output', out]
        if a.tag:
            cmd += ['--tag', a.tag]
        if a.account:
            cmd += ['--account', a.account]
        if a.scrim is not None:
            cmd += ['--scrim', str(a.scrim)]
        if a.blur is not None:
            cmd += ['--blur', str(a.blur)]

        print('  card_%02d <- %s | %s' % (i, os.path.basename(img), ' / '.join(lines)))
        if a.dry_run:
            print('    (dry-run) %s' % ' '.join(cmd))
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            failures += 1
            print('    ✗ 生成异常: %s' % e)
            continue
        if r.returncode != 0 or not os.path.exists(out):
            failures += 1
            print('    ✗ 生成失败:\n%s\n%s' % (r.stdout[-400:], r.stderr[-400:]))
        else:
            time.sleep(0.2)

    if a.dry_run:
        print('dry-run 完成，未写入任何文件')
        return
    if failures:
        sys.exit('%d 张卡片生成失败，请检查上方错误' % failures)
    print('已生成 %d 张卡片到 %s/。下一步：跑 build_composition.py 重建时间轴后渲染。'
          % (n, a.out_dir))


if __name__ == '__main__':
    main()
