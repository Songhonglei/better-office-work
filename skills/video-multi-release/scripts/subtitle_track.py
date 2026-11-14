#!/usr/bin/env python3
"""Build narration-covering subtitle cues and burn them using transparent PNGs.

Pillow is needed only to rasterize Chinese text. No libass FFmpeg build required.
Timing is proportional to characters unless explicit relative cue times are supplied;
this is not forced word alignment or speech recognition.
"""
import argparse
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from production_common import (digest, file_hash, local_config, positive, probe,
                               read_json, run, write_json)


def cues_for(timeline):
    result = []
    for clip in timeline['clips']:
        text = clip['text']
        custom = clip.get('subtitles')
        if custom is not None:
            for cue in custom:
                start, end = float(cue['start']), float(cue['end'])
                if not (0 <= start < end <= clip['audio_dur'] + 0.001):
                    raise ValueError('Subtitle times must be relative to narration and within audio_dur')
                result.append(dict(segment_id=clip['id'], text=cue['text'],
                                   start=clip['start'] + start, end=clip['start'] + end))
            continue
        parts = re.findall(r'.{1,18}(?:[，。！？；、,.!?;]|$)|.{1,18}', text)
        parts = [s.strip() for s in parts if s.strip()]
        length = sum(len(s) for s in parts)
        t = clip['start']
        for part in parts:
            end = t + clip['audio_dur'] * len(part) / length
            result.append(dict(segment_id=clip['id'], text=part, start=t, end=end))
            t = end
    return result


def timestamp(t):
    ms = round(t * 1000)
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def rasterize(text, out, width, height, font_path=None):
    from PIL import Image, ImageDraw, ImageFont
    choices = [font_path, '/System/Library/Fonts/STHeiti Medium.ttc',
               '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    selected = next((p for p in choices if p and Path(p).is_file()), None)
    if selected is None:
        raise ValueError('Provide a CJK font via --font / VIDEO_SUBTITLE_FONT')
    size = max(16, round(width * 0.043))
    font = ImageFont.truetype(selected, size)
    stroke = max(1, round(size / 18))
    margin = round(width * .07)
    lines, line = [], ''
    scratch = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    for char in text:
        if char == '\n' or (line and scratch.textlength(line + char, font=font) > width - margin * 2):
            lines.append(line)
            line = '' if char == '\n' else char
        else:
            line += char
    if line:
        lines.append(line)
    if not lines or len(lines) > 3:
        raise ValueError('Subtitle needs 1–3 lines; split the cue')
    line_height = round(size * 1.4)
    box_h = line_height * len(lines) + size // 2
    if box_h > height * .3:
        raise ValueError('Subtitle box exceeds safe screen height')
    top = height - round(height * .12) - box_h
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((margin // 2, top, width - margin // 2, top + box_h),
                           radius=size // 3, fill=(0, 0, 0, 200))
    for i, line in enumerate(lines):
        draw.text((width // 2, top + size // 4 + i * line_height), line,
                  font=font, anchor='mt', fill='white', stroke_width=stroke, stroke_fill='black')
    image.save(out)
    return [margin // 2, top, width - margin, box_h]


def raster_python():
    cfg = read_json(local_config(), {})
    choices = [os.environ.get('VIDEO_RASTER_PYTHON'), cfg.get('raster_python'), sys.executable]
    for exe in choices:
        if exe and subprocess.run([exe, '-c', 'import PIL'], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
            return exe
    raise RuntimeError('Chinese subtitle rasterization needs Pillow. Set VIDEO_RASTER_PYTHON to an existing Pillow environment.')


def burn(video, timeline_path, out_dir=None, font=None):
    video, timeline_path = Path(video).resolve(), Path(timeline_path).resolve()
    project = timeline_path.parent
    timeline = read_json(timeline_path)
    info = probe(video)
    stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    width, height = stream['width'], stream['height']
    cues = cues_for(timeline)
    if not cues:
        raise ValueError('No subtitle cues')
    dest = Path(out_dir or project / 'out/subtitles').resolve()
    dest.mkdir(parents=True, exist_ok=True)
    baseline = project / '.cache/qa' / (file_hash(video) + '.mp4')
    baseline.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = dest / 'render_receipt.json'
    previous = read_json(receipt_path, {})
    settings = {'timeline': timeline, 'font': font, 'size': [width, height],
                'engine_sha256': file_hash(__file__), 'version': 1}
    key = digest(settings)
    if previous.get('key') == key and previous.get('video_sha256') == file_hash(video):
        print('CACHE subtitles')
        return previous
    # Reburn from the original clean render if only captions have changed.
    if previous.get('video_sha256') == file_hash(video) and Path(previous.get('clean_video', '')).is_file():
        baseline = Path(previous['clean_video'])
    elif not baseline.exists():
        shutil.copy2(video, baseline)
    exe = raster_python()
    for i, cue in enumerate(cues):
        png = dest / ('cue-%04d.png' % i)
        meta = png.with_suffix('.json')
        command = [exe, Path(__file__), 'raster', '--text', cue['text'],
                   '--out', png, '--width', width, '--height', height, '--meta', meta]
        if font:
            command += ['--font', font]
        run(command)
        cue.update(overlay=str(png), bbox=read_json(meta)['bbox'], overlay_sha256=file_hash(png))
    # Bound input count by processing batches, with identical pixel geometry.
    # Inputs are static PNGs; overlay repeats their last frame through each cue.
    source = baseline
    intermediates = []
    for batch_start in range(0, len(cues), 24):
        batch = cues[batch_start:batch_start + 24]
        target = dest / ('batch-%04d.mp4' % batch_start)
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', source]
        for cue in batch:
            cmd += ['-i', cue['overlay']]
        filters = []
        label = '[0:v]'
        for i, cue in enumerate(batch, 1):
            nxt = '[v%d]' % i
            filters.append("%s[%d:v]overlay=0:0:enable='gte(t,%.6f)*lt(t,%.6f)'%s" %
                           (label, i, cue['start'], cue['end'], nxt))
            label = nxt
        cmd += ['-filter_complex', ';'.join(filters), '-map', label, '-map', '0:a?',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'copy', '-movflags', '+faststart', target]
        run(cmd)
        source = target
        intermediates.append(target)
    tmp = video.with_name(video.stem + '.subtitled.tmp.mp4')
    shutil.copy2(source, tmp)
    tmp.replace(video)
    srt = '\n\n'.join('%d\n%s --> %s\n%s' % (i + 1, timestamp(c['start']),
                      timestamp(c['end']), c['text']) for i, c in enumerate(cues)) + '\n'
    (dest / 'captions.srt').write_text(srt, encoding='utf-8')
    receipt = {'key': key, 'timing_method': 'supplied-relative-cues-or-character-proportional',
               'video': str(video), 'video_sha256': file_hash(video),
               'timeline_sha256': file_hash(timeline_path), 'clean_video': str(baseline),
               'clean_sha256': file_hash(baseline), 'cues': cues, 'width': width, 'height': height}
    write_json(receipt_path, receipt)
    for p in intermediates:
        p.unlink()
    print('Burned %d subtitle cues → %s' % (len(cues), video))
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    b = sub.add_parser('burn')
    b.add_argument('--video', required=True)
    b.add_argument('--timeline', default='timeline.json')
    b.add_argument('--out-dir')
    b.add_argument('--font', default=os.environ.get('VIDEO_SUBTITLE_FONT'))
    r = sub.add_parser('raster')
    r.add_argument('--text', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--meta', required=True)
    r.add_argument('--width', type=int, required=True)
    r.add_argument('--height', type=int, required=True)
    r.add_argument('--font')
    a = ap.parse_args()
    if a.command == 'burn':
        burn(a.video, a.timeline, a.out_dir, a.font)
    else:
        write_json(a.meta, {'bbox': rasterize(a.text, a.out, a.width, a.height, a.font)})


if __name__ == '__main__':
    main()
