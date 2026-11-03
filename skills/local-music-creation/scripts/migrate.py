#!/usr/bin/env python3
"""Explicit fresh setup and pinned snapshot staging; never upgrade an existing source."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from music import ASSETS, capture, digest, load_config, read, save


def setup(c, p, root):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('Fresh setup requires native arm64 macOS')
    uv = shutil.which('uv')
    if not uv or capture([uv, '--version']).split()[1] != read(ASSETS / 'frozen/manifest.json')['uv']:
        raise ValueError('Install the verified uv version in a user-managed location first; see migration.md')
    if p['source'].exists():
        raise FileExistsError('Existing source preserved. Fresh setup only; do not use for local updates.')
    if not shutil.which('git'):
        raise ValueError('Git/Command Line Tools missing; no system installer will be run automatically')
    root.mkdir(parents=True, exist_ok=True)
    manifest = read(ASSETS / 'frozen/manifest.json')
    if c['expected_commit'] != manifest['source_commit']:
        raise ValueError('Configuration does not select the bundled verified source')
    for name, sha in manifest['files'].items():
        if digest(ASSETS / 'frozen' / name) != sha:
            raise ValueError('Bundled frozen file failed integrity check: ' + name)
    p['source'].parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(key, None)
    if p['python'].parent.name != 'bin' or p['python'].name != 'python':
        raise ValueError('Fresh setup expects paths.python=<venv>/bin/python')
    venv = p['python'].parent.parent
    if venv.exists():
        raise FileExistsError('Existing configured virtual environment preserved: ' + str(venv))
    env.update(UV_CACHE_DIR=str(p['cache'] / 'uv'),
               UV_PYTHON_INSTALL_DIR=str(root / 'runtime/python'), UV_PROJECT_ENVIRONMENT=str(venv))
    steps = [(['git', 'clone', manifest['source_repository'], str(p['source'])], root),
             (['git', 'checkout', '--detach', manifest['source_commit']], p['source'])]
    for command, cwd in steps:
        subprocess.run(command, cwd=cwd, env=env, check=True)
    for name in manifest['files']:
        shutil.copy2(ASSETS / 'frozen' / name, p['source'] / name)
    subprocess.run([uv, 'python', 'install', manifest['python']], env=env, check=True)
    subprocess.run([uv, 'sync', '--frozen', '--no-dev', '--python', manifest['python']],
                   cwd=p['source'], env=env, check=True)
    version = capture([p['python'], '-c', 'import sys; print(".".join(map(str,sys.version_info[:3])))'])
    save(root / 'migration-setup.json', {'source_commit': manifest['source_commit'],
         'python': version, 'dependency_files': manifest['files'], 'result': 'installed; doctor still required'})


def safe_member(base, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe manifest member: ' + name)
    candidate = base / relative
    if os.path.commonpath([candidate.resolve(), base.resolve()]) != str(base.resolve()):
        raise ValueError('Manifest member escapes snapshot: ' + name)
    return candidate


def verify_snapshot(p):
    manifest = read(ASSETS / 'model-manifest.json')
    files = []
    for record in manifest['files']:
        file = safe_member(p['snapshot'], record['file'])
        ok = file.is_file() and file.stat().st_size == record['bytes'] and digest(file) == record['sha256']
        files.append({'file': record['file'], 'verified': ok})
        if not ok:
            raise ValueError('Pinned snapshot hash/size mismatch: ' + record['file'])
    return {'repo': manifest['repo'], 'revision': manifest['revision'], 'files': files, 'all_verified': True}


def stage(p, root, copy=False):
    receipt = verify_snapshot(p)
    conversion = read(p['snapshot'] / 'conversion.json')
    targets = [(name, p['model'] / name) for name in [*conversion['files'], 'conversion.json', 'README.md']]
    targets += [(record['file'], p['vae'] / record['file'][4:])
                for record in read(ASSETS / 'model-manifest.json')['files'] if record['file'].startswith('vae/')]
    # Check every conflict before writing any runtime tree.
    for name, target in targets:
        source = safe_member(p['snapshot'], name)
        if target.exists() and digest(target) != digest(source):
            raise FileExistsError('Existing runtime file differs; preserved: ' + str(target))
        if not copy and target.parent.exists() and source.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError('Different filesystems: pass --copy to allocate a separate runtime tree')
    for name, target in targets:
        source = safe_member(p['snapshot'], name)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy:
            shutil.copy2(source, target)
        else:
            os.link(source, target)
    save(root / 'migration-model-verification.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('setup')
    sub.add_parser('download-models')
    sub.add_parser('verify-models')
    sub.add_parser('verify-extras')
    a = sub.add_parser('stage-models'); a.add_argument('--copy', action='store_true')
    args = parser.parse_args()
    c, p, config, root = load_config(args.config)
    if args.command == 'setup':
        setup(c, p, root); return
    if args.command == 'verify-extras':
        results = []
        for entry in read(ASSETS / 'optional-model-manifest.json')[:2]:
            base = p['sheetsage'] if entry['repo'] == 'm-a-p/SheetSage2' else p['mert']
            for row in entry['files']:
                file = safe_member(base, row['file'])
                if not file.is_file() or file.stat().st_size != row['bytes'] or digest(file) != row['sha256']:
                    raise ValueError('Optional checkpoint hash/size mismatch: ' + str(file))
            results.append({'repo': entry['repo'], 'revision': entry['revision'], 'verified': True})
        if p['realaudio'].is_dir():
            for row in read(ASSETS / 'realaudio-converted-manifest.json')['files']:
                file = safe_member(p['realaudio'], row['file'])
                if not file.is_file() or file.stat().st_size != row['bytes'] or digest(file) != row['sha256']:
                    raise ValueError('Converted RealAudio hash/size mismatch: ' + str(file))
            results.append({'realaudio_converted': True, 'verified': True})
        print(json.dumps(results, indent=2)); return
    if args.command == 'download-models':
        manifest = read(ASSETS / 'model-manifest.json')
        # Uses only the configured core runtime; credentials remain in the user's Hub environment.
        code = ('from huggingface_hub import snapshot_download; import sys; '
                'snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3], '
                'allow_patterns=sys.argv[4:])')
        env = os.environ.copy()
        for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
            env.pop(key, None)
        env['HF_HOME'] = str(p['cache'] / 'huggingface')
        subprocess.run([p['python'], '-c', code, manifest['repo'], manifest['revision'], str(p['snapshot']),
                        *[record['file'] for record in manifest['files']]], env=env, check=True)
    result = stage(p, root, getattr(args, 'copy', False)) if args.command == 'stage-models' else verify_snapshot(p)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
