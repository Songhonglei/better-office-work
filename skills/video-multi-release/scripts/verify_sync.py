#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音画同步校验：按 timeline.json 每段中点抽帧，拼一张联系表供人工复核。

时间轴由 build_composition.py 生成、mix_audio.py 读同一份，理论上是同步的；
但渲染换过素材、或手工改过 index.html 之后仍可能错位，出片前扫一眼最稳。

用法:
  python3 verify_sync.py --timeline timeline.json --video out/final.mp4
  python3 verify_sync.py --timeline timeline.json --video out/final.mp4 --out-dir out/sync_check
产出:
  <out-dir>/contact_sheet.png   抽帧联系表（每行 6 张）
  <out-dir>/report.json         每段的时间点 / 对应卡片 / 音频区间
"""

import argparse
import json
import os
import subprocess
import sys

COLS = 6
THUMB_W, THUMB_H = 180, 320


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit('ffmpeg 失败: %s' % p.stderr[-800:])
    return p


def main():
    ap = argparse.ArgumentParser(description='按时间轴抽帧，生成音画同步复核联系表')
    ap.add_argument('--timeline', default='timeline.json')
    ap.add_argument('--video', required=True)
    ap.add_argument('--out-dir', default='out/sync_check')
    ap.add_argument('--cols', type=int, default=COLS)
    a = ap.parse_args()

    if not os.path.exists(a.timeline):
        sys.exit('找不到时间轴: %s（先跑 build_composition.py）' % a.timeline)
    if not os.path.exists(a.video):
        sys.exit('找不到成片: %s' % a.video)
    with open(a.timeline, encoding='utf-8') as f:
        tl = json.load(f)
    clips = tl.get('clips') or []
    if not clips:
        sys.exit('时间轴里没有 clips')

    os.makedirs(a.out_dir, exist_ok=True)
    frames = []
    report = []
    for i, c in enumerate(clips, 1):
        t = c['start'] + c['audio_dur'] / 2
        p = os.path.join(a.out_dir, 'frame_%02d.png' % i)
        run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', '%.3f' % t,
             '-i', a.video, '-frames:v', '1',
             '-vf', 'scale=%d:%d' % (THUMB_W, THUMB_H), p])
        frames.append(p)
        report.append({'seg': c['id'], 'card': 'card_%02d.png' % i,
                       'at': round(t, 2), 'audio': [round(c['start'], 2),
                                                    round(c['start'] + c['audio_dur'], 2)],
                       'text': c.get('text', '')[:24]})

    # 拼联系表：按 cols 分行，最后一行不足补黑帧
    cols = max(1, a.cols)
    rows = (len(frames) + cols - 1) // cols
    blank = os.path.join(a.out_dir, '_blank.png')
    run(['ffmpeg', '-y', '-loglevel', 'error',
         '-f', 'lavfi', '-i', 'color=c=0x101010:s=%dx%d:d=1' % (THUMB_W, THUMB_H),
         '-frames:v', '1', blank])
    while len(frames) < rows * cols:
        frames.append(blank)

    cmd = ['ffmpeg', '-y', '-loglevel', 'error']
    for p in frames:
        cmd += ['-i', p]
    labels = ['[r%d]' % r for r in range(rows)]
    parts = []
    for r in range(rows):
        ins = ''.join('[%d:v]' % (r * cols + j) for j in range(cols))
        parts.append(ins + ('hstack=inputs=%d[r%d]' % (cols, r) if cols > 1 else 'null[r%d]' % r))
    stack = (''.join(labels) + 'vstack=inputs=%d[out]' % rows if rows > 1 else '[r0]null[out]')
    cmd += ['-filter_complex', ';'.join(parts) + ';' + stack,
            '-map', '[out]', os.path.join(a.out_dir, 'contact_sheet.png')]
    run(cmd)

    with open(os.path.join(a.out_dir, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump({'video': os.path.abspath(a.video), 'total': tl.get('total'),
                   'clips': report}, f, ensure_ascii=False, indent=2)

    print('已抽 %d 帧 → %s/contact_sheet.png' % (len(clips), a.out_dir))
    print('报告: %s/report.json（成片 %.2fs）' % (a.out_dir, tl.get('total', 0)))


if __name__ == '__main__':
    main()
