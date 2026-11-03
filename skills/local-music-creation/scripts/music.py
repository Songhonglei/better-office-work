#!/usr/bin/env python3
"""Configurable, offline, serial YuE2 MLX runner. Controller needs stdlib only."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / 'assets'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def config_path(argument=None):
    return Path(argument or os.environ.get('LOCAL_MUSIC_CONFIG') or
                (Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) /
                 'local-music-creation/config.json')).expanduser().resolve()


def expand(value, base, root=None):
    value = os.path.expandvars(str(value)).replace('{skill}', str(SKILL))
    if root is not None:
        value = value.replace('{root}', str(root))
    if '{' in value or '}' in value or re.search(r'\$[A-Za-z_{]', value):
        raise ValueError('Unresolved path variable: ' + value)
    p = Path(value).expanduser()
    # Keep venv interpreter symlinks: resolving them would silently bypass the venv.
    return Path(os.path.abspath(base / p if not p.is_absolute() else p))


def load_config(argument=None):
    path = config_path(argument)
    if not path.is_file():
        raise ValueError('Configuration missing. Run init-config first: ' + str(path))
    c = read(path)
    if c.get('schema') != 1:
        raise ValueError('Unsupported configuration schema')
    root = expand(c['root'], path.parent)
    paths = {k: expand(v, path.parent, root) for k, v in c['paths'].items()}
    runtime = c['runtime']
    if runtime['precision'] not in ('8bit', 'bf16'):
        raise ValueError('Only verified 8bit and bf16 profiles are supported')
    if type(runtime['require_ac']) is not bool:
        raise ValueError('require_ac must be a JSON boolean')
    for k in ('memory_budget_gib', 'vae_core_frames', 'timeout_seconds'):
        if not isinstance(runtime[k], (int, float)) or isinstance(runtime[k], bool) or runtime[k] <= 0:
            raise ValueError(k + ' must be positive')
    if not isinstance(runtime['min_free_disk_gib'], (int, float)) or runtime['min_free_disk_gib'] < 0:
        raise ValueError('min_free_disk_gib must be nonnegative')
    return c, paths, path, root


def environment(paths):
    env = os.environ.copy()
    for k in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(k, None)
    env.update(MLX_ENABLE_TF32='0', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HOME=str(paths['cache'] / 'huggingface'), XDG_CACHE_HOME=str(paths['cache']),
               UV_CACHE_DIR=str(paths['cache'] / 'uv'))
    if paths.get('ffmpeg_bin', Path('/nonexistent')).is_dir():
        env['PATH'] = str(paths['ffmpeg_bin']) + os.pathsep + env.get('PATH', '')
    return env


def capture(argv, **kwargs):
    r = subprocess.run([str(a) for a in argv], text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=kwargs.pop('timeout', 60), **kwargs)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-2000:] or r.stdout.strip()[-2000:])
    return r.stdout.strip()


def preflight(c, p, root, strict=True, extras=False):
    errors = []
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        errors.append('Requires native arm64 macOS, not Rosetta or another OS')
    python = p['extras_python'] if extras else p['python']
    for k in ('source', 'model', 'vae'):
        if not p[k].is_dir():
            errors.append('Missing ' + k + ': ' + str(p[k]))
    if not python.is_file():
        errors.append('Missing runtime Python: ' + str(python))
    git_head = None
    if p['source'].is_dir():
        try:
            git_head = capture(['git', '-C', p['source'], 'rev-parse', 'HEAD'])
            if git_head != c['expected_commit']:
                errors.append('Source revision differs from configured baseline; review before use')
            changed = capture(['git', '-C', p['source'], 'diff', 'HEAD', '--name-only']).splitlines()
            unexpected = [name for name in changed if name not in ('pyproject.toml', 'uv.lock')]
            if unexpected:
                errors.append('Unreviewed source modifications: ' + ', '.join(unexpected))
            manifest = read(ASSETS / 'frozen/manifest.json')
            if c['expected_commit'] == manifest['source_commit']:
                for name, expected in manifest['files'].items():
                    if digest(p['source'] / name) != expected:
                        errors.append('Frozen dependency file differs: ' + name)
        except Exception as e:
            errors.append('Source check: ' + str(e))
    ancestor = p['output']
    while not ancestor.exists():
        ancestor = ancestor.parent
    free = shutil.disk_usage(ancestor).free / 2**30
    if free < c['runtime']['min_free_disk_gib']:
        errors.append('Insufficient disk space for configured minimum')
    power = capture(['pmset', '-g', 'batt']) if platform.system() == 'Darwin' else 'unavailable'
    if strict and c['runtime']['require_ac'] and "'AC Power'" not in power:
        errors.append('Connect AC power, or explicitly configure require_ac=false')
    pressure = None
    if platform.system() == 'Darwin':
        try:
            pressure = int(capture(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level']))
            if strict and pressure > 1:
                errors.append('System memory pressure is elevated; no job started')
        except (RuntimeError, ValueError):
            pass
    if python.is_file():
        try:
            version = capture([python, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'])
            if version != '3.12':
                errors.append('Runtime must use Python 3.12')
        except Exception as e:
            errors.append('Python check: ' + str(e))
    result = {'errors': errors, 'ok': not errors, 'architecture': platform.machine(),
              'macos': platform.mac_ver()[0], 'free_disk_gib': free, 'power': power,
              'memory_pressure': pressure, 'source_commit': git_head,
              'runtime_python': str(python), 'qwen_stop_actions': []}
    return result


@contextlib.contextmanager
def serial_lock(root):
    folder = root / 'locks'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'local-music-creation.lock').open('a+') as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another music job holds this deployment lock')
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def terminate_owned(process):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def check_result(c, p, folder, action, natural):
    interpreter = p['extras_python'] if action in ('transcribe', 'cover', 'realaudio') else p['python']
    if action == 'batch':
        receipts = read(folder / 'batch.json')
        rows = receipts.get('results', [])
        checked = [json.loads(capture([interpreter, SKILL / 'scripts/inspect_result.py',
                   'generate', folder / row['id'], str(natural).lower()], env=environment(p))) for row in rows]
        return {'passed': len(rows) == receipts.get('expected') and bool(checked) and
                all(row.get('status') == 'complete' for row in rows) and
                all(x['passed'] for x in checked), 'songs': checked}
    return json.loads(capture([interpreter, SKILL / 'scripts/inspect_result.py', action,
                               folder, str(natural).lower()], env=environment(p)))


def run_job(c, p, root, action, source=None, precision=None, name=None, dry=False,
            natural=False, audio=None, task='melody-full', stage='decode'):
    precision = precision or c['runtime']['precision']
    if precision not in ('8bit', 'bf16'):
        raise ValueError('Invalid precision')
    extras = action in ('transcribe', 'cover', 'realaudio')
    pf = preflight(c, p, root, strict=True, extras=extras)
    if not pf['ok']:
        raise RuntimeError(json.dumps(pf, ensure_ascii=False))
    if source is not None:
        source = Path(source).expanduser().resolve()
        if not source.exists():
            raise ValueError('Input missing: ' + str(source))
    if audio is not None:
        audio = Path(audio).expanduser().resolve()
        if not audio.is_file():
            raise ValueError('Audio input missing: ' + str(audio))
    request = None
    if action in ('generate', 'plan', 'cover'):
        request = read(source)
        if not isinstance(request, dict):
            raise ValueError('Request must be a JSON object')
        if request.get('abc_path') is not None:
            if request.get('abc') is not None:
                raise ValueError('Use abc or abc_path, not both')
            request['abc'] = (source.parent / request.pop('abc_path')).read_text()
        if action == 'cover' and request.get('abc') is not None:
            raise ValueError('Cover request must omit abc/abc_path; the source audio provides the score')
    if extras:
        for key in ('sheetsage', 'mert') if action != 'realaudio' else ('realaudio',):
            if not p[key].is_dir():
                raise ValueError('Optional model missing: ' + key + '; see references/migration.md')
    if name is None:
        name = action + '-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', name):
        raise ValueError('Output name must be a simple ASCII label (letters, digits, - or _)')
    job = p['output'] / name
    if job.exists():
        raise FileExistsError('Will not overwrite an existing job: ' + str(job))
    folder = job / 'artifacts'
    common = ['--model', str(p['model']), '--vae', str(p['vae']), '--precision', precision,
              '--offline', '--memory-budget-gib', str(c['runtime']['memory_budget_gib']),
              '--vae-core-frames', str(c['runtime']['vae_core_frames'])]
    if c['runtime']['require_ac']:
        common += ['--require-ac']
    native = [action]
    if action == 'doctor':
        native += ['--model', str(p['model']), '--vae', str(p['vae']), '--verify-hashes',
                   '--output', str(job / 'doctor.json')]
    elif action == 'transcribe':
        native += [str(source), '--output', str(folder), '--model', str(p['sheetsage']),
                   '--base-model', str(p['mert']), '--cache-dir', str(p['hf_cache']),
                   '--offline', '--task', task, '--memory-budget-gib', str(c['runtime']['memory_budget_gib'])]
    elif action == 'realaudio':
        native += ['compare', str(source), '--output', str(folder), '--model', str(p['model']),
                   '--vae', str(p['vae']), '--realaudio-dir', str(p['realaudio']),
                   '--precision', precision, '--memory-budget-gib', str(c['runtime']['memory_budget_gib'])]
    else:
        native += (['--input', str(source)] if action == 'batch' else [str(source)])
        native += common + ['--output', str(folder)]
        if action == 'replay':
            native += ['--stage', stage]
        if action == 'cover':
            native += ['--audio', str(audio), '--task', task, '--transcription-model', str(p['sheetsage']),
                       '--base-model', str(p['mert']), '--cache-dir', str(p['hf_cache'])]
    interpreter = p['extras_python'] if extras else p['python']
    command = [str(interpreter), str(SKILL / 'scripts/guarded_cli.py'),
               str(job / 'resources.json'), str(c['runtime']['require_ac']).lower(), *native]
    if dry:
        return {'dry_run': True, 'argv': command, 'job': str(job), 'preflight': pf}
    with serial_lock(root):
        job.mkdir(parents=True, exist_ok=False)
        # Store the requested data, not a mutable external pointer. Resolve ABC relative to its source.
        if action in ('generate', 'plan', 'cover'):
            save(job / 'input.json', request)
            command[command.index(str(source))] = str(job / 'input.json')
        elif source and source.is_file() and action == 'batch':
            shutil.copy2(source, job / 'input.jsonl')
            command[command.index(str(source))] = str(job / 'input.jsonl')
        receipt = {'schema': 1, 'action': action, 'job': str(job), 'artifacts': str(folder),
                   'source': str(source) if source else None, 'precision': precision,
                   'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'preflight': pf, 'argv': command, 'qwen_stop_actions': [], 'status': 'running'}
        save(job / 'execution.json', receipt)
        started = time.perf_counter()
        process = None
        interrupted = []
        def stop(signum, frame):
            interrupted.append(signum)
            raise KeyboardInterrupt
        old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            with (job / 'run.log').open('x') as stream:
                process = subprocess.Popen(command, cwd=p['source'], env=environment(p),
                                           stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                receipt['pid'] = process.pid
                save(job / 'execution.json', receipt)
                code = process.wait(timeout=c['runtime']['timeout_seconds'])
            receipt['exit_code'] = code
            if code == 0:
                receipt['verification'] = ({'passed': read(job / 'doctor.json').get('status') == 'pass'}
                                           if action == 'doctor' else check_result(c, p, folder, action, natural))
                receipt['status'] = 'passed' if receipt['verification']['passed'] else 'needs_review'
            else:
                receipt['status'] = 'failed'
        except (KeyboardInterrupt, subprocess.TimeoutExpired) as e:
            if process:
                terminate_owned(process)
            receipt.update(status='cancelled' if isinstance(e, KeyboardInterrupt) else 'timed_out',
                           exit_code=process.returncode if process else None, signals=interrupted)
        except Exception as e:
            if process:
                terminate_owned(process)
            receipt.update(status='failed', error=type(e).__name__ + ': ' + str(e))
        finally:
            for sig, previous in old_handlers.items():
                signal.signal(sig, previous)
            receipt['wall_seconds'] = time.perf_counter() - started
            if (job / 'resources.json').exists():
                resource = read(job / 'resources.json')
                receipt['memory_peak_bytes'] = resource.get('sampled_maxima', {})
                receipt['monitor_error'] = resource.get('monitor_error')
                receipt['pressure_levels'] = sorted({s['system_memory_pressure_level'] for s in
                      resource.get('samples', []) if s.get('system_memory_pressure_level') is not None})
                samples = resource.get('samples', [])
                if samples:
                    receipt['new_swapout_bytes'] = samples[-1].get('system_swap_out_bytes', 0) - samples[0].get('system_swap_out_bytes', 0)
            audio_seconds = receipt.get('verification', {}).get('audio_seconds')
            if audio_seconds:
                receipt['rtf_wall'] = receipt['wall_seconds'] / audio_seconds
            save(job / 'execution.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('init-config'); a.add_argument('--root'); a.add_argument('--target')
    sub.add_parser('show-config'); sub.add_parser('preflight')
    a = sub.add_parser('precision'); a.add_argument('value', choices=['8bit', 'bf16'])
    for action in ('doctor', 'generate', 'plan', 'render-plan', 'replay', 'batch', 'cover', 'transcribe', 'realaudio', 'test'):
        a = sub.add_parser(action)
        if action == 'test':
            a.add_argument('source', choices=['short', 'chinese-full', 'smoke', 'expanded'])
        elif action != 'doctor':
            a.add_argument('source')
        a.add_argument('--precision', choices=['8bit', 'bf16'])
        a.add_argument('--name'); a.add_argument('--dry-run', action='store_true')
        a.add_argument('--require-natural', action='store_true')
        if action == 'cover':
            a.add_argument('--audio', required=True)
        if action in ('cover', 'transcribe'):
            a.add_argument('--task', choices=['full', 'melody-full', 'melody-vocal'], default='melody-full')
        if action == 'replay':
            a.add_argument('--stage', choices=['decode', 'synthesize'], default='decode')
    args = parser.parse_args()
    if args.command == 'init-config':
        target = config_path(args.target or args.config)
        if target.exists():
            raise FileExistsError('Existing config preserved: ' + str(target))
        c = read(ASSETS / 'config.example.json')
        if args.root:
            c['root'] = args.root
        save(target, c)
        print(json.dumps({'config': str(target), 'root': c['root']})); return 0
    c, p, config, root = load_config(args.config)
    if args.command == 'show-config':
        print(json.dumps({'config': str(config), 'root': str(root), 'paths': {k: str(v) for k, v in p.items()},
                          'runtime': c['runtime']}, ensure_ascii=False, indent=2)); return 0
    if args.command == 'preflight':
        result = preflight(c, p, root, strict=False)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result['ok'] else 1
    if args.command == 'precision':
        c['runtime']['precision'] = args.value; save(config, c)
        print(json.dumps({'default_precision': args.value, 'config': str(config)})); return 0
    options = dict(precision=args.precision, name=args.name, dry=args.dry_run,
                   natural=args.require_natural, audio=getattr(args, 'audio', None),
                   task=getattr(args, 'task', 'melody-full'), stage=getattr(args, 'stage', 'decode'))
    if args.command != 'test':
        result = run_job(c, p, root, args.command, getattr(args, 'source', None), **options)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('dry_run') or result['status'] == 'passed' else 1
    if args.source in ('short', 'chinese-full'):
        cases = [{'key': args.source, 'request': 'requests/' + args.source + '.json',
                  'precision': args.precision or c['runtime']['precision'], 'action': 'generate',
                  'diagnostic': args.source == 'short'}]
    else:
        cases = read(ASSETS / 'matrix.json')['cases']
        if args.source == 'smoke':
            cases = [case for case in cases if case['key'] in ('piano-control', 'bf16-complete')]
    results = []
    prefix = args.name or ('suite-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4])
    for case in cases:
        opts = dict(options, name=prefix + '-' + case['key'], precision=args.precision or case['precision'],
                    natural=not case.get('diagnostic', False))
        action = 'plan' if case['action'] == 'plan-render' else 'generate'
        result = run_job(c, p, root, action, ASSETS / case['request'], **opts)
        results.append(result)
        if not args.dry_run and result['status'] != 'passed':
            break
        if action == 'plan' and not args.dry_run:
            opts['name'] += '-render'
            result = run_job(c, p, root, 'render-plan', result['artifacts'], **opts)
            results.append(result)
            if result['status'] != 'passed':
                break
        if result.get('pressure_levels') and max(result['pressure_levels']) > 1:
            break
    expected = sum(2 if case['action'] == 'plan-render' and not args.dry_run else 1 for case in cases)
    passed = len(results) == expected and all(r.get('dry_run') or r['status'] == 'passed' for r in results)
    result = {'schema': 1, 'suite': args.source, 'passed': passed, 'expected_jobs': expected, 'completed_jobs': len(results), 'results': results,
              'subjective_quality': 'unrated; human listening required'}
    if not args.dry_run:
        save(p['output'] / (prefix + '.suite.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
