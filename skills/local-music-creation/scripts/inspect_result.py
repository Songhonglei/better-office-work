"""Verify native immutable artifacts and audio in the selected runtime."""
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
from lyra.artifacts import load_artifacts, load_plan_artifacts

action, folder, natural = sys.argv[1:]
p = Path(folder)
checks = {}
details = {}
if action == 'realaudio':
    result = json.loads((p / 'comparison_report.json').read_text())
    rows = result.get('runs', [])
    checks['three_reconstruction_runs'] = len(rows) == 3
    token_count = result.get('tokenization', {}).get('token_count', 0)
    checks['same_positive_token_count'] = token_count > 0 and all(row.get('tokens_count') == token_count for row in rows)
    audios = []
    for index, row in enumerate(rows):
        file = p / row['audio_file']
        audio, sr = sf.read(file, dtype='float32', always_2d=True)
        finite = bool(np.isfinite(audio).all())
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if finite else None
        checks['audio_' + str(index)] = (finite and bool(rms and rms > 1e-6) and
            sr == 48000 and audio.shape[1] == 2 and abs(len(audio) / sr - row['audio_seconds']) <= 1 / sr)
        audios.append({'file': str(file), 'audio_seconds': len(audio) / sr, 'rms': rms})
    print(json.dumps({'passed': all(checks.values()), 'checks': checks, 'audio': audios,
                      'subjective_quality': 'unrated; human listening required'}, allow_nan=False))
    raise SystemExit(0)
elif action == 'plan':
    load_plan_artifacts(p)
    checks['plan_hashes'] = True
    result = json.loads((p / 'plan.json').read_text())
    truncated = result.get('truncated', {})
elif action == 'transcribe':
    result = json.loads((p / 'result.json').read_text())
    checks['transcription_status'] = result.get('status') == 'complete'
    checks['score_exists'] = (p / 'score.abc').is_file()
    truncated = result.get('truncated', {})
    details['transcription_result'] = result
else:
    if action == 'cover':
        p = p / 'song'
    load_artifacts(p)
    checks['artifact_hashes'] = True
    result = json.loads((p / 'result.json').read_text())
    audio, sr = sf.read(p / 'audio.flac', dtype='float32', always_2d=True)
    finite = bool(np.isfinite(audio).all())
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if finite else None
    seconds = len(audio) / sr
    checks.update(finite_audio=finite, non_silent=bool(rms and rms > 1e-6),
                  stereo_48khz=sr == 48000 and audio.shape[1] == 2,
                  duration_matches=abs(seconds - result['audio_seconds']) <= 1 / sr)
    details.update(audio_seconds=seconds, sample_rate=sr, channels=audio.shape[1],
                   rms=rms, peak=float(np.abs(audio).max()) if finite else None,
                   audio=str(p / 'audio.flac'), abc=str(p / 'score.abc'),
                   timing=result.get('timing'), identity=result.get('identity'))
    truncated = result.get('truncated', {})
if isinstance(truncated, dict):
    ended = not any(truncated.values())
else:
    ended = not bool(truncated)
if natural == 'true':
    checks['natural_end'] = ended
print(json.dumps({'checks': checks, 'passed': all(checks.values()),
                  'truncated': truncated, 'natural_end': ended,
                  'subjective_quality': 'unrated; human listening required', **details},
                 ensure_ascii=False, allow_nan=False))
