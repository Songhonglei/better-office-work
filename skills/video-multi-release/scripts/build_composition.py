#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按配音时长生成 HyperFrames composition。

核心：卡片时长不再写死，由每段配音的真实时长驱动。
改文案 → 重新 TTS → 重跑本脚本 → 时间轴自动重算。

用法:
  python3 build_composition.py --script voice_script.json --voice-dir assets/voice
"""

import argparse
import json
import os
import subprocess
import sys


def probe_duration(path):
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'csv=p=0', path,
        ]).decode().strip()
    except FileNotFoundError:
        sys.exit('找不到 ffprobe，请先安装 ffmpeg')
    except subprocess.CalledProcessError:
        sys.exit('ffprobe 读取失败: %s' % path)
    return float(out)


TEMPLATE = '''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0;
        width: {width}px;
        height: {height}px;
        overflow: hidden;
        background: {canvas_bg};
      }}
      #root {{
        position: relative;
        width: {width}px;
        height: {height}px;
        background: {canvas_gradient};
      }}
      .card {{
        position: absolute;
        left: 0;
        top: {card_top}px;
        width: {width}px;
        height: {card_h}px;
        object-fit: cover;
        will-change: transform, opacity;
      }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total:.3f}"
      data-width="{width}"
      data-height="{height}"
    >
{imgs}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});

{timeline}

      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
'''


LIGHT_BG = '#faf7f2'
LIGHT_STOPS = ['#fbf9f5', '#faf7f2', '#ede5d7', '#eae0d1']


def canvas_css(bg, stops):
    """画布配色。暗色主题必须传进来，否则米白留白会在近黑卡片外形成刺眼白框。"""
    if bg is None:
        bg, ss = LIGHT_BG, LIGHT_STOPS
    elif stops:
        ss = stops
    else:
        ss = [bg] * 4            # 只给了底色 → 渐变四段同色，不再冒出默认米白
    return bg, ('linear-gradient(to bottom, %s 0%%, %s 12.5%%, %s 87.5%%, %s 100%%)'
                % tuple(ss))


def build(script_path, voice_dir, out_path,
          pre=0.6, gap=0.5, tail=1.5, in_dur=0.9, exit_dur=0.7,
          width=1080, height=1920, card_h=1440,
          canvas_bg=None, canvas_stops=None):

    try:
        with open(script_path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit('文案文件不存在: %s' % script_path)
    except json.JSONDecodeError as e:
        sys.exit('文案 JSON 解析失败: %s' % e)
    segs = data['segments']

    clips = []
    t = pre
    for seg in segs:
        p = os.path.join(voice_dir, seg['id'] + '.mp3')
        if not os.path.exists(p):
            sys.exit('缺少配音文件: ' + p)
        d = probe_duration(p)
        clips.append({'seg': seg, 'audio': d, 'start': t})
        t += d + gap

    n = len(clips)
    total = clips[-1]['start'] + clips[-1]['audio'] + tail
    for i, c in enumerate(clips):
        is_last = (i == n - 1)
        # 中间卡的 gap 是留给下一卡起点之前的转场；末卡后面没有下一卡，
        # 再叠一个 gap 会让末卡结束时间比 root 的 total 晚 gap 秒（GSAP 尾巴越界）。
        c['visible'] = c['audio'] + (tail if is_last else gap)

    for c in clips:
        if in_dur + exit_dur > c['visible']:
            sys.exit('卡片 %s 可见 %.2fs 小于进+退 %.2fs，请调小 --gap / --tail'
                     % (c['seg']['id'], c['visible'], in_dur + exit_dur))

    img_lines = []
    for i, c in enumerate(clips):
        img_lines.append(
            '      <img class="card clip" id="c{d}" src="assets/card_{n:02d}.png" '
            'data-start="{s:.3f}" data-duration="{v:.3f}" data-track-index="0" '
            'style="z-index:{z}" />'.format(
                d=i + 1, n=i + 1, s=c['start'], v=c['visible'], z=i + 1)
        )

    tl_lines = []
    for i, c in enumerate(clips):
        sel = '#c%d' % (i + 1)
        s, vis = c['start'], c['visible']
        is_first, is_last = (i == 0), (i == n - 1)
        hold_end = vis if is_last else vis - exit_dur

        from_props = ('{ opacity: 1, y: 40, scale: 1.06 }' if is_first
                      else '{ opacity: 0, y: 64, scale: 1.05 }')
        tl_lines.append(
            '        tl.fromTo(\n'
            "          '{sel}',\n"
            '          {fp},\n'
            '          {{ opacity: 1, y: 0, scale: 1, duration: {ind:.3f}, ease: "power3.out" }},\n'
            '          {s:.3f}\n'
            '        );'.format(sel=sel, fp=from_props, ind=in_dur, s=s)
        )
        tl_lines.append(
            "        tl.to('{sel}', {{ scale: 1.012, duration: {d:.3f}, ease: \"none\" }}, {at:.3f});"
            .format(sel=sel, d=max(hold_end - in_dur, 0.1), at=s + in_dur)
        )
        if not is_last:
            tl_lines.append(
                "        tl.to('{sel}', {{ opacity: 0, y: -42, duration: {d:.3f}, ease: \"power2.in\" }}, {at:.3f});"
                .format(sel=sel, d=exit_dur, at=s + vis - exit_dur)
            )

    bg, gradient = canvas_css(canvas_bg, canvas_stops)
    html = TEMPLATE.format(
        width=width,
        height=height,
        card_h=card_h,
        card_top=(height - card_h) // 2,
        total=total,
        canvas_bg=bg,
        canvas_gradient=gradient,
        imgs='\n'.join(img_lines),
        timeline='\n'.join(tl_lines),
    )
    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)
    except OSError as e:
        sys.exit('写入 %s 失败: %s' % (out_path, e))

    # 时间轴落盘，混音脚本读它，避免两处各算一遍导致音画不同步
    timeline = {
        'total': total,
        'pre': pre, 'gap': gap, 'tail': tail,
        'clips': [
            {
                'id': c['seg']['id'],
                'audio_file': os.path.join(voice_dir, c['seg']['id'] + '.mp3'),
                'audio_dur': c['audio'],
                'start': c['start'],
                'visible': c['visible'],
                'text': c['seg']['text'],
            }
            for c in clips
        ],
    }
    try:
        with open('timeline.json', 'w', encoding='utf-8') as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
    except OSError as e:
        sys.exit('写入 timeline.json 失败: %s' % e)

    print('总时长 %.2fs（%d 张卡片）' % (total, n))
    for c in clips:
        print('  %-6s 音频 %5.2fs  卡片 %5.2fs  起于 %5.2fs  %s'
              % (c['seg']['id'], c['audio'], c['visible'], c['start'],
                 c['seg']['text'][:18]))
    return total, clips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script', default='voice_script.json')
    ap.add_argument('--voice-dir', default='assets/voice')
    ap.add_argument('--out', default='index.html')
    ap.add_argument('--pre', type=float, default=0.6, help='开头静止留白')
    ap.add_argument('--gap', type=float, default=0.5, help='段间留白')
    ap.add_argument('--tail', type=float, default=1.5, help='结尾停留')
    ap.add_argument('--in-dur', type=float, default=0.9, help='进场时长')
    ap.add_argument('--exit-dur', type=float, default=0.7, help='退场时长')
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1920)
    ap.add_argument('--card-h', type=int, default=1440,
                    help='卡片高度，默认 1440（居中留上下各 240px）；传 1920 可满幅')
    ap.add_argument('--canvas-bg', default=None,
                    help='画布底色，暗色主题务必传（如 #0a0806）；默认米白 #faf7f2')
    ap.add_argument('--canvas-stops', default=None,
                    help='画布渐变四段色，逗号分隔；只传 --canvas-bg 时四段同色')
    a = ap.parse_args()

    stops = [s.strip() for s in a.canvas_stops.split(',')] if a.canvas_stops else None
    if stops and len(stops) != 4:
        sys.exit('--canvas-stops 必须是 4 个颜色，逗号分隔')

    build(a.script, a.voice_dir, a.out, pre=a.pre, gap=a.gap, tail=a.tail,
          in_dur=a.in_dur, exit_dur=a.exit_dur,
          width=a.width, height=a.height, card_h=a.card_h,
          canvas_bg=a.canvas_bg, canvas_stops=stops)
    print('已写入', a.out)


if __name__ == '__main__':
    main()
