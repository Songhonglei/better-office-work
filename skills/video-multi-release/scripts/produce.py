#!/usr/bin/env python3
"""Resumable local production. Publishing remains a separate, existing command."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from comfy_assets import generate
from production_common import (digest, file_hash, local_config, probe, project_lock,
                               read_json, record, segments, write_json)
from quality_check import check
from render_mixed import render
from subtitle_track import burn

SCRIPTS = Path(__file__).resolve().parent
STAGES = ['assets', 'voice', 'cards', 'render', 'mix', 'subtitles', 'qa']


def invoke(script, args, project):
    subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                   cwd=project, check=True)


def produce(a):
    project = Path(a.project).expanduser().resolve()
    data = read_json(project / 'voice_script.json')
    rows = segments(data)
    start = STAGES.index(a.from_stage)
    with project_lock(project):
        for stage in STAGES[start:]:
            record(project, stage, 'running')
            try:
                if stage == 'assets':
                    generate(project, a.comfy_config, timeout=a.timeout, resubmit=a.resubmit)
                elif stage == 'voice':
                    if a.use_existing_voice:
                        for row in rows:
                            audio = project / 'voice' / (row['id'] + '.mp3')
                            if probe(audio)['duration'] <= 0:
                                raise ValueError('Invalid supplied narration')
                    else:
                        invoke('tts.py', ['--script', 'voice_script.json', '--out-dir', 'voice',
                                         '--preset', a.preset, '--rate', a.rate], project)
                elif stage == 'cards':
                    if any(r.get('visual', {}).get('type', 'card') == 'card' for r in rows):
                        args = ['--script', 'voice_script.json', '--out-dir', 'assets', '--cache',
                                '--content-type', a.content_type]
                        if a.images:
                            args += ['--images', a.images]
                        if a.theme:
                            args += ['--theme', a.theme]
                        invoke('gen_cards.py', args, project)
                elif stage == 'render':
                    render(project, a.width, a.height, a.fps, a.pre, a.gap, a.tail, a.canvas)
                elif stage == 'mix':
                    out = project / 'out/final.mp4'
                    tl = project / 'timeline.json'
                    deps = [tl, project / 'out/silent.mp4'] + [project / 'voice' / (r['id'] + '.mp3') for r in rows]
                    if a.bgm:
                        deps.append(Path(a.bgm).expanduser().resolve())
                    key = digest({'inputs': [(str(p), file_hash(p)) for p in deps],
                                  'script': file_hash(SCRIPTS / 'mix_audio.py')})
                    receipt_path = project / '.cache/mix.json'
                    old = read_json(receipt_path, {})
                    if not (out.is_file() and old.get('key') == key and old.get('sha256') == file_hash(out)):
                        args = ['--timeline', 'timeline.json', '--silent', 'out/silent.mp4', '--out', 'out/final.mp4']
                        if a.bgm:
                            args += ['--bgm', str(deps[-1])]
                        invoke('mix_audio.py', args, project)
                        write_json(receipt_path, {'key': key, 'sha256': file_hash(out)})
                elif stage == 'subtitles':
                    burn(project / 'out/final.mp4', project / 'timeline.json')
                    # A completed burn is the current output of the same mix recipe.
                    receipt_path = project / '.cache/mix.json'
                    receipt = read_json(receipt_path, {})
                    if receipt:
                        receipt['sha256'] = file_hash(project / 'out/final.mp4')
                        write_json(receipt_path, receipt)
                elif stage == 'qa':
                    report = check(project / 'out/final.mp4', project / 'timeline.json',
                                   project / 'out/quality_report.json', target=a.target,
                                   target_tolerance=a.target_tolerance)
                    if not report['passed']:
                        raise ValueError('Quality gate failed: ' + ', '.join(report['blockers']))
                    if os.environ.get('VERIFY', '1') != '0':
                        invoke('verify_sync.py', ['--timeline', 'timeline.json', '--video', 'out/final.mp4',
                                                 '--out-dir', 'out/sync_check'], project)
                record(project, stage, 'completed')
            except Exception as e:
                record(project, stage, 'failed', error=str(e))
                raise
        print('READY %s (quality gate passed; publishing is separate)' % (project / 'out/final.mp4'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', default='.')
    ap.add_argument('--status', action='store_true', help='Read project/scene receipts without running production')
    ap.add_argument('--from-stage', choices=STAGES, default='assets')
    ap.add_argument('--comfy-config', default=str(local_config()))
    ap.add_argument('--timeout', type=float, default=1800)
    ap.add_argument('--resubmit', action='store_true')
    ap.add_argument('--use-existing-voice', action='store_true', help='Reuse supplied voice/<id>.mp3 instead of calling TTS')
    ap.add_argument('--preset', default='female')
    ap.add_argument('--rate', type=float, default=1.12)
    ap.add_argument('--bgm', help='Optional BGM; omitted means narration only')
    ap.add_argument('--images')
    ap.add_argument('--theme')
    ap.add_argument('--content-type', choices=['general', 'history'], default='general')
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1920)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--pre', type=float, default=.6)
    ap.add_argument('--gap', type=float, default=.45)
    ap.add_argument('--tail', type=float, default=1.5)
    ap.add_argument('--canvas', default='#0a0806')
    ap.add_argument('--target', type=float)
    ap.add_argument('--target-tolerance', type=float, default=1.0)
    a = ap.parse_args()
    if a.status:
        import json
        project = Path(a.project)
        print(json.dumps({'production': read_json(project / 'production.json', {}),
                          'assets': read_json(project / 'asset_manifest.json', {}),
                          'quality': read_json(project / 'out/quality_report.json', {})}, ensure_ascii=False, indent=2))
    else:
        produce(a)


if __name__ == '__main__':
    main()
