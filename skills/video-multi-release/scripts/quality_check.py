#!/usr/bin/env python3
"""Failing delivery gate: duration, black frames, silence and rendered subtitles.

Subtitle coverage checks supplied text/times and samples each burned cue against
its clean-frame composite. It does not transcribe speech or judge semantic fit.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from production_common import file_hash, probe, read_json, run, write_json


def intervals(log, kind, duration):
    if kind == 'black':
        return [(float(a), float(b)) for a, b in re.findall(
            r'black_start:([\d.]+) black_end:([\d.]+)', log)]
    result, start = [], None
    for match in re.finditer(r'silence_(start|end):\s*([\d.eE+-]+)', log):
        if match[1] == 'start':
            start = max(0, float(match[2]))
        elif start is not None:
            result.append((start, float(match[2])))
            start = None
    if start is not None:
        result.append((start, duration))
    return result


def detect(path, kind, duration):
    filt = 'blackdetect=d=0.35:pic_th=0.98:pix_th=0.08' if kind == 'black' else 'silencedetect=noise=-45dB:d=0.4'
    flag = '-vf' if kind == 'black' else '-af'
    p = run(['ffmpeg', '-hide_banner', '-nostats', '-i', path, flag, filt, '-f', 'null', '-'])
    return intervals(p.stderr, kind, duration)


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def covered(interval, spans):
    pieces = sorted((max(interval[0], a), min(interval[1], b)) for a, b in spans
                    if overlap(interval, (a, b)) > 0)
    total, end = 0, interval[0]
    for a, b in pieces:
        total += max(0, b - max(a, end))
        end = max(end, b)
    return total


def normalized(text):
    return ''.join(c for c in text if c.isalnum())


def pixels(path, at=None, bbox=None, rgba=False):
    cmd = ['ffmpeg', '-v', 'error']
    if at is not None:
        cmd += ['-ss', '%.6f' % at]
    cmd += ['-i', str(path), '-frames:v', '1']
    if bbox:
        x, y, w, h = bbox
        # Convert before cropping: YUV420 otherwise rounds odd subtitle box
        # dimensions, while the PNG reference retains the exact rectangle.
        cmd += ['-vf', 'format=%s,crop=%d:%d:%d:%d:exact=1' %
                ('rgba' if rgba else 'rgb24', w, h, x, y)]
    cmd += ['-f', 'rawvideo', '-pix_fmt', 'rgba' if rgba else 'rgb24', '-']
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode or not p.stdout:
        raise RuntimeError('Subtitle sample decode failed: ' + p.stderr.decode()[-500:])
    return p.stdout


def subtitle_sample(video, clean, cue):
    bbox, t = cue['bbox'], (cue['start'] + cue['end']) / 2
    final = pixels(video, t, bbox)
    before = pixels(clean, t, bbox)
    overlay = pixels(cue['overlay'], bbox=bbox, rgba=True)
    if len(final) != len(before) or len(overlay) // 4 != len(final) // 3:
        raise ValueError('Subtitle sample geometry mismatch')
    error, change, count = 0., 0., 0
    # Sample every fourth pixel; compare expected alpha composite to decoded frame.
    for i in range(0, len(final) // 3, 4):
        j, k = i * 3, i * 4
        alpha = overlay[k + 3] / 255
        if alpha < .1:
            continue
        expected = [overlay[k+c] * alpha + before[j+c] * (1-alpha) for c in range(3)]
        error += sum(abs(final[j+c] - expected[c]) for c in range(3)) / 3
        change += sum(abs(before[j+c] - expected[c]) for c in range(3)) / 3
        count += 1
    mean_error, expected_change = error / max(1, count), change / max(1, count)
    return {'at': t, 'mean_composite_error': round(mean_error, 2),
            'expected_visible_change': round(expected_change, 2),
            'passed': count > 0 and mean_error < 28 and expected_change > 3}


def check(video, timeline_path, report_path, receipt_path=None, target=None,
          target_tolerance=1.0, allow_no_subtitles=False):
    video, timeline_path = Path(video).resolve(), Path(timeline_path).resolve()
    timeline = read_json(timeline_path)
    blockers, checks = [], {}
    script_path = timeline_path.parent / 'voice_script.json'
    script = read_json(script_path, {})
    if script:
        expected_rows = [(s['id'], s['text']) for s in script.get('segments', [])]
        actual_rows = [(c['id'], c['text']) for c in timeline['clips']]
        if expected_rows != actual_rows:
            blockers.append('script_timeline_mismatch')
    info = probe(video)
    expected, actual = float(timeline['total']), info['duration']
    tolerance = max(.15, len(timeline['clips']) / float(timeline.get('fps', 30)) + .05)
    checks['duration'] = {'expected': expected, 'actual': actual, 'tolerance': tolerance}
    if abs(actual - expected) > tolerance:
        blockers.append('duration_mismatch')
    if target is not None:
        checks['target_duration'] = {'target': target, 'actual': actual, 'tolerance': target_tolerance}
        if abs(actual - target) > target_tolerance:
            blockers.append('target_duration_mismatch')
    vs = [s for s in info['streams'] if s['codec_type'] == 'video']
    aud = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if not vs:
        blockers.append('missing_video_stream')
    if not aud:
        blockers.append('missing_audio_stream')
    # Stream duration catches long audio tails masked by format-level duration.
    for s in vs + aud:
        if s.get('duration') and abs(float(s['duration']) - expected) > tolerance:
            blockers.append('stream_duration_mismatch')
    if vs:
        checks['black_intervals'] = detect(video, 'black', actual)
        if checks['black_intervals']:
            blockers.append('black_frames')
    narration = [(float(c['start']), float(c['start']) + float(c['audio_dur'])) for c in timeline['clips']]
    if aud:
        silent = detect(video, 'silence', actual)
        bad = [s for s in silent if any(overlap(s, n) >= .4 for n in narration)]
        checks['final_silence'] = {'all': silent, 'during_narration': bad}
        if bad:
            blockers.append('silent_narration_in_final')
    # Inspect individual narration files: BGM can hide completely missing speech.
    checks['narration_sources'] = []
    for clip in timeline['clips']:
        path = Path(clip['audio_file'])
        if not path.is_absolute():
            path = timeline_path.parent / path
        try:
            src = probe(path)
            silence = detect(path, 'silence', src['duration'])
            amount = covered((0, src['duration']), silence)
            fraction = amount / max(src['duration'], .001)
            valid = abs(src['duration'] - clip['audio_dur']) <= .1 and fraction < .65
            checks['narration_sources'].append({'id': clip['id'], 'silence_fraction': fraction,
                                                'duration': src['duration'], 'passed': valid})
            if not valid:
                blockers.append('silent_or_changed_narration_source:' + clip['id'])
        except (ValueError, OSError, RuntimeError) as e:
            blockers.append('invalid_narration_source:' + clip['id'])
            checks['narration_sources'].append({'id': clip['id'], 'error': str(e)})
    receipt_path = Path(receipt_path or video.parent / 'subtitles/render_receipt.json')
    receipt = read_json(receipt_path, {})
    if not receipt:
        checks['subtitles'] = {'status': 'absent', 'required': not allow_no_subtitles}
        if not allow_no_subtitles:
            blockers.append('missing_subtitle_render_receipt')
    else:
        errors = []
        cues = receipt.get('cues', [])
        if receipt.get('video_sha256') != file_hash(video):
            errors.append('video_changed_after_subtitle_render')
        if receipt.get('timeline_sha256') != file_hash(timeline_path):
            errors.append('timeline_changed_after_subtitle_render')
        clean = Path(receipt.get('clean_video', ''))
        clean_valid = clean.is_file() and file_hash(clean) == receipt.get('clean_sha256')
        if not clean_valid:
            errors.append('missing_or_changed_clean_reference')
        checks['subtitles'] = {'segments': [], 'samples': [], 'limitations':
            'Text/time coverage and one rendered midpoint sample per cue; no ASR/OCR or frame-by-frame semantic guarantee.'}
        for clip in timeline['clips']:
            selected = sorted((c for c in cues if c.get('segment_id') == clip['id']), key=lambda c: c['start'])
            interval = (clip['start'], clip['start'] + clip['audio_dur'])
            duration = covered(interval, [(c['start'], c['end']) for c in selected])
            ratio = duration / clip['audio_dur']
            text_match = normalized(''.join(c['text'] for c in selected)) == normalized(clip['text'])
            valid = ratio >= .98 and text_match
            checks['subtitles']['segments'].append({'id': clip['id'], 'time_coverage': ratio,
                                                    'text_match': text_match, 'passed': valid})
            if not valid:
                errors.append('subtitle_coverage:' + clip['id'])
        for i, cue in enumerate(cues):
            try:
                if not (0 <= cue['start'] < cue['end'] <= actual + .05):
                    raise ValueError('cue_outside_video')
                x, y, w, h = cue['bbox']
                if not (0 <= x < x+w <= vs[0]['width'] and 0 <= y < y+h <= vs[0]['height']):
                    raise ValueError('subtitle_outside_frame')
                if file_hash(cue['overlay']) != cue['overlay_sha256']:
                    raise ValueError('subtitle_overlay_changed')
                if clean_valid:
                    sample = subtitle_sample(video, clean, cue)
                    checks['subtitles']['samples'].append(dict(cue=i, **sample))
                    if not sample['passed']:
                        errors.append('subtitle_not_visibly_rendered:' + str(i))
            except (OSError, ValueError, KeyError, RuntimeError) as e:
                errors.append('subtitle_sample:%d:%s' % (i, e))
        if not cues:
            errors.append('empty_subtitle_cues')
        blockers.extend(errors)
    report = {'passed': not blockers, 'video': str(video), 'video_sha256': file_hash(video),
              'timeline_sha256': file_hash(timeline_path), 'blockers': sorted(set(blockers)), 'checks': checks}
    if script_path.is_file():
        report['script_sha256'] = file_hash(script_path)
    write_json(report_path, report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--video', default='out/final.mp4')
    ap.add_argument('--timeline', default='timeline.json')
    ap.add_argument('--report', default='out/quality_report.json')
    ap.add_argument('--receipt')
    ap.add_argument('--target', type=float)
    ap.add_argument('--target-tolerance', type=float, default=1.0)
    ap.add_argument('--allow-no-subtitles', action='store_true', help='Explicit exception, recorded in report')
    a = ap.parse_args()
    report = check(a.video, a.timeline, a.report, a.receipt, a.target, a.target_tolerance, a.allow_no_subtitles)
    print(json.dumps({'passed': report['passed'], 'blockers': report['blockers'], 'report': a.report}, ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 2)


if __name__ == '__main__':
    main()
