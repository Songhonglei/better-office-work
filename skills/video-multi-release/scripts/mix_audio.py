#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按 timeline.json 把分段配音铺到时间轴上，叠加压低后的 BGM，混出成片音轨。

timeline.json 由 build_composition.py 生成，保证音画用的是同一份时间轴，
不会出现两边各算一遍导致对不上的情况。

用法:
  python3 mix_audio.py --silent /tmp/voice_silent.mp4 \
      --bgm assets/music/piano-reflections.mp3 \
      --out ../../voice-version.mp4
"""

import argparse
import json
import os
import subprocess
import sys


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('找不到 ffmpeg，请先安装')
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-3000:])
        sys.exit('ffmpeg 失败')
    return p


def measure_lufs(path):
    try:
        p = subprocess.run([
            'ffmpeg', '-hide_banner', '-nostats', '-i', path,
            '-af', 'ebur128', '-f', 'null', '-',
        ], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    lufs = None
    for line in p.stderr.splitlines():
        s = line.strip()
        if s.startswith('I:') and 'LUFS' in s:
            lufs = float(s.split()[1])
    return lufs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeline', default='timeline.json')
    ap.add_argument('--silent', required=True, help='无声画面 mp4')
    ap.add_argument('--bgm', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--bgm-offset', type=float, default=14.0,
                    help='BGM 相对人声压低多少 dB（默认 -14）')
    ap.add_argument('--voice-gain', type=float, default=0.0,
                    help='人声增益 dB')
    a = ap.parse_args()

    try:
        with open(a.timeline, encoding='utf-8') as f:
            tl = json.load(f)
    except FileNotFoundError:
        sys.exit('找不到 %s，请先跑 build_composition.py' % a.timeline)
    except json.JSONDecodeError as e:
        sys.exit('timeline.json 解析失败: %s' % e)
    total = tl['total']
    clips = tl['clips']

    inputs = ['-i', a.silent]
    filters = []
    voice_labels = []

    for i, c in enumerate(clips, start=1):
        inputs += ['-i', c['audio_file']]
        ms = int(round(c['start'] * 1000))
        filters.append(
            '[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
            'adelay=%d|%d,volume=%.1fdB[v%d]' % (i, ms, ms, a.voice_gain, i)
        )
        voice_labels.append('[v%d]' % i)

    filters.append('%samix=inputs=%d:normalize=0:dropout_transition=0[voice]'
                   % (''.join(voice_labels), len(voice_labels)))

    bgm_idx = len(clips) + 1
    inputs += ['-i', a.bgm]
    filters.append(
        '[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
        'atrim=0:%.3f,volume=%.1fdB,'
        'afade=t=in:st=0:d=2,afade=t=out:st=%.3f:d=2.5[bgm]'
        % (bgm_idx, total, -a.bgm_offset, max(total - 2.5, 0))
    )

    filters.append('[voice][bgm]amix=inputs=2:normalize=0:dropout_transition=0,'
                   'alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11[aout]')

    cmd = ['ffmpeg', '-y', '-hide_banner'] + inputs + [
        '-filter_complex', ';'.join(filters),
        '-map', '0:v', '-map', '[aout]',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-movflags', '+faststart', a.out,
    ]
    run(cmd)

    print('成片:', a.out)
    print('总时长: %.2fs  BGM 压低: -%.0fdB' % (total, a.bgm_offset))
    lufs = measure_lufs(a.out)
    print('整合响度: %s LUFS' % lufs)
    for c in clips:
        print('  %s 人声起于 %.2fs  %.2fs' % (c['id'], c['start'], c['audio_dur']))


if __name__ == '__main__':
    main()
