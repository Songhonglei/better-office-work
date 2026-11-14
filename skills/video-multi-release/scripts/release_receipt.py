#!/usr/bin/env python3
"""Validate a production quality receipt / append a platform publish receipt."""
import argparse
import json
from pathlib import Path
import time
from production_common import file_hash, read_json


def validate(video, report=None):
    video = Path(video).resolve()
    path = Path(report) if report else video.parent / 'quality_report.json'
    production = video.parent.parent / 'production.json'
    state = read_json(production, {})
    if any(s.get('status') in ('running', 'failed') for s in state.get('stages', {}).values()):
        raise ValueError('Production has a running or failed stage; complete it before release')
    if not path.exists():
        if report or production.exists():
            raise ValueError('Production quality report missing; run quality_check.py before release')
        return  # Standalone pre-existing videos remain supported.
    data = read_json(path)
    if not data.get('passed') or data.get('video_sha256') != file_hash(video):
        raise ValueError('Quality report failed or video changed; rerun production QA')
    timeline = video.parent.parent / 'timeline.json'
    if timeline.exists() and data.get('timeline_sha256') != file_hash(timeline):
        raise ValueError('Timeline changed after quality verification')
    script = video.parent.parent / 'voice_script.json'
    if script.exists() and data.get('script_sha256') != file_hash(script):
        raise ValueError('Script changed after quality verification')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['validate', 'record'])
    ap.add_argument('--video', required=True)
    ap.add_argument('--report')
    ap.add_argument('--platform')
    ap.add_argument('--mode')
    ap.add_argument('--state')
    ap.add_argument('--exit', type=int, default=0)
    ap.add_argument('--url', default='')
    a = ap.parse_args()
    if a.command == 'validate':
        validate(a.video, a.report)
    else:
        video = Path(a.video).resolve()
        row = {'time': time.time(), 'platform': a.platform, 'mode': a.mode,
               'state': a.state, 'exit': a.exit, 'url': a.url,
               'video': str(video), 'video_sha256': file_hash(video)}
        with (video.parent / 'publish_log.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
