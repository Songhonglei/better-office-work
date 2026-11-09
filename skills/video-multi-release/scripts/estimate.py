#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配音时长预估 —— 在跑 TTS 之前先算一遍，避免「配完才发现超时」。

实测基准（qwen-audio-3.0-tts-plus, rate=1.12, male-narrative）：
  约 3.4~4.2 字/秒，整片平均取 3.7 字/秒。
  原稿 1036 字 / 3.7 ≈ 245s，而目标 180s —— 只能砍字，调 rate 救不了。

用法:
  python3 estimate.py --script voice_script.json --target 180
  python3 estimate.py --script voice_script.json --json
  from estimate import estimate_script   # tts.py 前置调用
"""

import argparse
import json
import os
import re
import sys

DEFAULT_CPS = 3.7
PUNCT = re.compile(r'[，。？；：、！—…《》「」『』（）()"\'\s]')


def count_chars(text):
    return len(PUNCT.sub('', text))


def estimate_script(script_path, cps=DEFAULT_CPS, target=None,
                    pre=0.6, gap=0.45, tail=1.5):
    with open(script_path, encoding='utf-8') as f:
        data = json.load(f)
    segs = data.get('segments') or []
    rows = []
    for s in segs:
        n = count_chars(s.get('text', ''))
        rows.append({'id': s.get('id', ''), 'chars': n,
                     'est': round(n / cps, 2), 'text': s.get('text', '')[:20]})
    voice = sum(r['est'] for r in rows)
    n = len(rows)
    total = voice + max(n - 1, 0) * gap + pre + tail
    out = {
        'segments': rows,
        'count': n,
        'chars': sum(r['chars'] for r in rows),
        'cps': cps,
        'voice_seconds': round(voice, 1),
        'total_seconds': round(total, 1),
        'target': target,
    }
    if target:
        out['delta_seconds'] = round(total - target, 1)
        out['cut_chars'] = max(0, int((total - target) * cps))
    return out


def print_report(r):
    print('字数 %d，%d 段，按 %.1f 字/秒估算' % (r['chars'], r['count'], r['cps']))
    for x in r['segments']:
        flag = '  ⚠ 单段偏长' if x['est'] > 10 else ('  ⚠ 单段偏短' if x['est'] < 5 else '')
        print('  %-6s %3d字  %5.1fs%s   %s' % (x['id'], x['chars'], x['est'], flag, x['text']))
    print('纯语音 %.1fs → 含留白成片约 %.1fs（%.0f 分 %.0f 秒）'
          % (r['voice_seconds'], r['total_seconds'],
             r['total_seconds'] // 60, r['total_seconds'] % 60))
    if r.get('target'):
        d = r['delta_seconds']
        if d > 0:
            print('⚠ 超出目标 %.1fs，约需砍 %d 字（调 rate 救不了这么多，只能砍文案）'
                  % (d, r['cut_chars']))
        else:
            print('✓ 在目标 %ds 以内，余量 %.1fs' % (r['target'], -d))
    slow = [x for x in r['segments'] if x['est'] > 10 or x['est'] < 5]
    if slow:
        print('节奏提示：%d 段超 10s 或短于 5s，卡片会忽快忽慢，建议拆/合并：%s'
              % (len(slow), ', '.join(x['id'] for x in slow)))


def main():
    ap = argparse.ArgumentParser(description='配音时长预估（TTS 之前跑）')
    ap.add_argument('--script', default='voice_script.json')
    ap.add_argument('--cps', type=float, default=DEFAULT_CPS, help='字/秒，默认 3.7')
    ap.add_argument('--target', type=float, help='目标成片时长（秒）')
    ap.add_argument('--pre', type=float, default=0.6)
    ap.add_argument('--gap', type=float, default=0.45)
    ap.add_argument('--tail', type=float, default=1.5)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if not os.path.exists(a.script):
        sys.exit('文案文件不存在: %s' % a.script)
    r = estimate_script(a.script, a.cps, a.target, a.pre, a.gap, a.tail)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else '')
    if not a.json:
        print_report(r)


if __name__ == '__main__':
    main()
