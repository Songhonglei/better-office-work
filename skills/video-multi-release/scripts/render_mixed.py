#!/usr/bin/env python3
"""Render cards/images/videos to one silent timeline; cache each normalized scene."""
import argparse
from pathlib import Path
import re

from production_common import (digest, file_hash, positive, probe, read_json, run,
                               segments, write_json)


def resolve_visual(project, seg, index, manifest):
    visual = dict(seg.get('visual', {}))
    kind = visual.get('type', 'card')
    if kind == 'card':
        path = visual.get('card') or 'assets/card_%02d.png' % index
    else:
        path = visual.get('source')
        if not path and visual.get('generate'):
            path = manifest.get('assets', {}).get(seg['id'], {}).get('path')
    if not path:
        raise ValueError('Missing visual source for ' + seg['id'])
    source = Path(path).expanduser()
    if not source.is_absolute():
        source = project / source
    if not source.is_file():
        raise ValueError('Visual not found: ' + str(source))
    return kind, source.resolve(), visual


def render(project, width=1080, height=1920, fps=30, pre=.6, gap=.45,
           tail=1.5, canvas='#0a0806'):
    project = Path(project).resolve()
    rows = segments(read_json(project / 'voice_script.json'))
    if width < 64 or height < 64 or width % 2 or height % 2 or fps < 1 or fps > 120:
        raise ValueError('Use even dimensions >=64 and fps between 1 and 120')
    pre, gap, tail = (positive(v, k, True) for v, k in ((pre, 'pre'), (gap, 'gap'), (tail, 'tail')))
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', canvas):
        raise ValueError('canvas must be #RRGGBB')
    manifest = read_json(project / 'asset_manifest.json', {'assets': {}})
    cache = project / '.cache/scenes'
    cache.mkdir(parents=True, exist_ok=True)
    clips, rendered, t = [], [], pre
    for index, seg in enumerate(rows, 1):
        audio = project / 'voice' / (seg['id'] + '.mp3')
        audio_info = probe(audio)
        if not any(s['codec_type'] == 'audio' for s in audio_info['streams']):
            raise ValueError('Narration has no audio: ' + str(audio))
        duration = positive(audio_info['duration'], 'audio duration')
        visible = duration + (tail if index == len(rows) else gap)
        start_frame = round((t if index > 1 else 0) * fps)
        end_frame = round((t + visible) * fps)
        frames = end_frame - start_frame
        if frames < 1:
            raise ValueError('Scene is shorter than one output frame')
        # Quantize absolute boundaries, avoiding accumulated drift across scenes.
        kind, source, visual = resolve_visual(project, seg, index, manifest)
        clip = {'id': seg['id'], 'audio_file': str(audio), 'audio_dur': duration,
                'start': t, 'visible': visible, 'text': seg['text'], 'visual_type': kind,
                'visual_file': str(source), 'subtitles': seg.get('subtitles'),
                'render_start': start_frame / fps,
                'render_duration': frames / fps}
        if clip['subtitles'] is None:
            clip.pop('subtitles')
        clips.append(clip)
        t += duration + gap
        params = {'source': file_hash(source), 'visual': visual, 'kind': kind,
                  'frames': frames, 'size': [width, height], 'fps': fps, 'canvas': canvas,
                  'engine_sha256': file_hash(__file__), 'v': 2}
        key = digest(params)
        dest = cache / (key + '.mp4')
        receipt = read_json(dest.with_suffix('.json'), {})
        if dest.exists() and receipt.get('sha256') == file_hash(dest):
            print('CACHE scene ' + seg['id'], flush=True)
            rendered.append(dest)
            continue
        cmd = ['ffmpeg', '-y', '-v', 'error']
        if kind == 'video':
            src_info = probe(source)
            if not any(s['codec_type'] == 'video' for s in src_info['streams']):
                raise ValueError('Source has no video stream')
            offset = positive(visual.get('source_offset', 0), 'source_offset', True)
            available = src_info['duration'] - offset
            if available <= 0:
                raise ValueError('source_offset exceeds video duration')
            policy = visual.get('short', 'loop')
            if policy not in ('loop', 'freeze', 'error'):
                raise ValueError('visual.short must be loop, freeze or error')
            if available < frames / fps and policy == 'error':
                raise ValueError('Video shorter than required scene: ' + seg['id'])
            if policy == 'loop':
                cmd += ['-stream_loop', '-1']
            cmd += ['-ss', offset, '-i', source]
        else:
            cmd += ['-loop', '1', '-framerate', fps, '-i', source]
        fit = visual.get('fit', 'contain' if kind == 'card' else 'cover')
        if fit not in ('cover', 'contain'):
            raise ValueError('visual.fit must be cover or contain')
        vf = ['setpts=PTS-STARTPTS', 'fps=%d' % fps]
        if fit == 'cover':
            vf += ['scale=%d:%d:force_original_aspect_ratio=increase' % (width, height),
                   'crop=%d:%d' % (width, height)]
        else:
            vf += ['scale=%d:%d:force_original_aspect_ratio=decrease' % (width, height),
                   'pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s' % (width, height, canvas.replace('#', '0x'))]
        if kind == 'video' and visual.get('short') == 'freeze':
            vf += ['tpad=stop_mode=clone:stop_duration=%.6f' % (frames / fps)]
        vf += ['setsar=1', 'format=yuv420p']
        temp = dest.with_name(dest.stem + '.tmp.mp4')
        cmd += ['-vf', ','.join(vf), '-frames:v', frames, '-an', '-c:v', 'libx264',
                '-preset', 'veryfast', '-crf', '20', '-movflags', '+faststart', temp]
        run(cmd)
        actual = probe(temp)['duration']
        if abs(actual - frames / fps) > 2 / fps:
            raise ValueError('Scene duration mismatch: ' + seg['id'])
        temp.replace(dest)
        write_json(dest.with_suffix('.json'), {'sha256': file_hash(dest), 'parameters': params})
        rendered.append(dest)
        print('RENDER scene ' + seg['id'], flush=True)
    total = clips[-1]['start'] + clips[-1]['audio_dur'] + tail
    timeline = {'version': 2, 'total': total, 'pre': pre, 'gap': gap, 'tail': tail,
                'width': width, 'height': height, 'fps': fps, 'clips': clips}
    write_json(project / 'timeline.json', timeline)
    listing = cache / 'concat.txt'
    listing.write_text(''.join("file '%s'\n" % str(p).replace("'", "'\\''") for p in rendered))
    out = project / 'out/silent.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing,
         '-c', 'copy', '-movflags', '+faststart', out])
    return timeline


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', default='.')
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1920)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--pre', type=float, default=.6)
    ap.add_argument('--gap', type=float, default=.45)
    ap.add_argument('--tail', type=float, default=1.5)
    ap.add_argument('--canvas', default='#0a0806')
    a = ap.parse_args()
    from production_common import project_lock
    with project_lock(a.project):
        render(a.project, a.width, a.height, a.fps, a.pre, a.gap, a.tail, a.canvas)


if __name__ == '__main__':
    main()
