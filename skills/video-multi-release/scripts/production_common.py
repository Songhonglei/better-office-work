"""Shared production files, validation, hashes and local subprocess helpers."""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def run(cmd):
    p = subprocess.run([str(x) for x in cmd], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError('Command failed: %s\n%s' % (cmd[0], p.stderr[-4000:]))
    return p


def probe(path):
    d = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                        '-of', 'json', path]).stdout)
    d['duration'] = float(d.get('format', {}).get('duration', 0))
    return d


def segments(data):
    rows = data.get('segments', [])
    if not rows:
        raise ValueError('segments must not be empty')
    seen = set()
    for s in rows:
        ident = s.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ident) or ident in seen:
            raise ValueError('Segment id must be unique and filename-safe: ' + repr(ident))
        if not isinstance(s.get('text'), str) or not s['text'].strip():
            raise ValueError('Missing narration text: ' + ident)
        if s.get('visual', {}).get('type', 'card') not in ('card', 'image', 'video'):
            raise ValueError('visual.type must be card, image or video')
        seen.add(ident)
    return rows


def positive(value, name, allow_zero=False):
    n = float(value)
    if not math.isfinite(n) or n < 0 or (n == 0 and not allow_zero):
        raise ValueError(name + ' must be finite and positive')
    return n


def local_config():
    root = Path(os.environ.get('WB_SKILLS_DATA', Path.home() / 'space/skills-data'))
    return root / 'video-multi-release/local-comfy.json'


@contextlib.contextmanager
def project_lock(project):
    import fcntl
    path = Path(project) / '.production.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another production is using this project')
        yield


def record(project, stage, status, **details):
    path = Path(project) / 'production.json'
    data = read_json(path, {'version': 1, 'stages': {}})
    event = dict(stage=stage, status=status, time=time.time(), **details)
    data['stages'][stage] = event
    write_json(path, data)
    with (Path(project) / 'production-events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
