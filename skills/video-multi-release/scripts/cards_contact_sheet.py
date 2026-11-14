#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卡片全检联系表 —— 把生成的全部卡片拼成分组图，强制逐张目视复核。

为什么要这个工具（2026-11-10 教训）：做完 18 张卡片只抽查了 6 张，
得出「5/6 完全避开人物头部」的结论，结果抽的 6 张恰好漏掉了最严重的
第 01 张（文字压在秦始皇额头上）。抽样在视觉质量上不成立，必须全检。

产出：
  <out-dir>/group_01.png ... 每组 6 张（3 列 x 2 行），可放大看细节
  <out-dir>/all.png          全部缩略总览（3 列 x N 行），看整体节奏
  <out-dir>/report.json      卡片数、分组、每张路径

用法:
  python3 cards_contact_sheet.py --assets assets --out-dir assets/_check
  gen_cards.py 生成完会自动调用本脚本（--no-proof 可关闭）
"""

import argparse
import glob
import json
import os
import subprocess
import sys

COLS = 3
ROWS_PER_GROUP = 2
THUMB_W = 360          # 分组图每张宽
ALL_W = 220            # 总览图每张宽


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit('ffmpeg 失败: %s' % p.stderr[-600:])


def make_blank(path, w, h):
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'color=c=0x101010:s=%dx%d:d=1' % (w, h), '-frames:v', '1', path])


def card_size(path):
    """读第一张卡片的真实宽高，算缩略图高度。

    原来写死 4:3：gen_cards.py 支持 --width/--height，一旦不是 1080x1440，
    缩略图与补黑帧高度不等，ffmpeg hstack 直接报错、全检表缺失。
    """
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path],
                       capture_output=True, text=True)
    try:
        w, h = [int(x) for x in p.stdout.strip().split(',')[:2]]
        return w, h
    except (ValueError, AttributeError):
        return 3, 4


def fit(w, h):
    """等比缩到 w×h，不足处补黑，保证同批图尺寸完全一致。"""
    return ('scale=%d:%d:force_original_aspect_ratio=decrease,'
            'pad=%d:%d:(ow-iw)/2:(oh-ih)/2' % (w, h, w, h))


def stack(paths, out, cols, rows, w, h):
    """按 cols 列拼成 rows 行；路径不足时补黑帧。"""
    blank = os.path.join(os.path.dirname(out), '_blank.png')
    make_blank(blank, w, h)
    work = list(paths) + [blank] * (cols * rows - len(paths))
    work = work[:cols * rows]

    cmd = ['ffmpeg', '-y', '-loglevel', 'error']
    for p in work:
        cmd += ['-i', p]
    parts, labels = [], []
    for r in range(rows):
        ins = ''.join('[%d:v]' % (r * cols + j) for j in range(cols))
        parts.append(ins + ('hstack=inputs=%d[r%d]' % (cols, r) if cols > 1 else 'null[r%d]' % r))
        labels.append('[r%d]' % r)
    stack_filter = ''.join(labels) + 'vstack=inputs=%d[out]' % rows if rows > 1 else '[r0]null[out]'
    cmd += ['-filter_complex', ';'.join(parts) + ';' + stack_filter,
            '-map', '[out]', out]
    run(cmd)


def main():
    ap = argparse.ArgumentParser(description='生成卡片全检联系表，强制逐张复核')
    ap.add_argument('--assets', required=True, help='卡片目录（card_*.png）')
    ap.add_argument('--out-dir', default=None, help='输出目录，默认 <assets>/_check')
    a = ap.parse_args()

    cards = sorted(glob.glob(os.path.join(a.assets, 'card_[0-9][0-9].png')))
    if not cards:
        sys.exit('没找到 card_*.png: %s' % a.assets)
    out_dir = a.out_dir or os.path.join(a.assets, '_check')
    os.makedirs(out_dir, exist_ok=True)

    cw, ch = card_size(cards[0])
    thumb_h = max(1, round(THUMB_W * ch / cw))
    small_h = max(1, round(ALL_W * ch / cw))

    thumbs = []
    for i, p in enumerate(cards, 1):
        t = os.path.join(out_dir, 'thumb_%02d.png' % i)
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', p,
             '-vf', fit(THUMB_W, thumb_h), '-frames:v', '1', t])
        thumbs.append(t)

    per = COLS * ROWS_PER_GROUP
    groups = []
    for g in range(0, len(thumbs), per):
        name = os.path.join(out_dir, 'group_%02d.png' % (g // per + 1))
        stack(thumbs[g:g + per], name, COLS, ROWS_PER_GROUP, THUMB_W, thumb_h)
        groups.append(name)

    # 总览：3 列 x N 行，用更小的缩略图
    small = []
    for i, p in enumerate(cards, 1):
        t = os.path.join(out_dir, 'small_%02d.png' % i)
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', p,
             '-vf', fit(ALL_W, small_h), '-frames:v', '1', t])
        small.append(t)
    rows = (len(small) + COLS - 1) // COLS
    stack(small, os.path.join(out_dir, 'all.png'), COLS, rows, ALL_W, small_h)

    report = {'count': len(cards), 'cards': cards,
              'groups': groups, 'all': os.path.join(out_dir, 'all.png')}
    with open(os.path.join(out_dir, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print('全检联系表：%d 张 → %d 组，见 %s/' % (len(cards), len(groups), out_dir))
    print('  ⚠ 必须逐张看 group_*.png，不要抽样；重点看文字有没有压住人物头部。')


if __name__ == '__main__':
    main()
