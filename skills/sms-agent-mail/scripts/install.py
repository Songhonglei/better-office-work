"""Install only packaged skill files; never write onboarding or OAuth directories."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from onboard import DEFAULT_DATA_DIR, SKILL_ROOT, data_directory, overlaps

# Copy resources first and publish the updated instructions last. Unknown files,
# runtime state and credentials are never copied from the extracted directory.
FILES = ('scripts/check_access.py', 'scripts/check_message.py', 'scripts/onboard.py',
         'scripts/install.py', 'references/migration.md', 'references/cli-recipes.md',
         'references/storage.md', 'references/end-to-end.md',
         'tests/test_access.py', 'tests/test_onboarding.py', 'tests/test_message.py',
         'README.md', 'LICENSE', '.gitignore', 'SKILL.md')


def install_skill(source: Path, target: Path, protected: list[Path]) -> dict:
    source, target = source.resolve(), target.expanduser().absolute()
    if target.name != 'sms-agent-mail' or target.is_symlink():
        raise ValueError('invalid_skill_target')
    target = target.resolve()
    if overlaps(source, target) or any(overlaps(target, p) for p in protected):
        raise ValueError('skill_target_overlaps_protected_storage')
    payload = {}
    for relative in FILES:
        original = source / relative
        if original.is_symlink() or source not in original.resolve().parents or not original.is_file() or original.stat().st_size > 512_000:
            raise ValueError('invalid_packaged_file')
        payload[relative] = original.read_bytes()
        destination = target / relative
        for part in (destination, *destination.parents):
            if part == target.parent:
                break
            if part.is_symlink():
                raise ValueError('symlink_in_skill_target')
    target.mkdir(parents=True, exist_ok=True)
    for relative, data in payload.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.skill-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.chmod(temporary, 0o644)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {'ok': True, 'skill_directory': str(target), 'copied_files': len(payload),
            'onboarding_and_oauth_directories_written': False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', choices=('codex', 'workbuddy', 'custom'), required=True)
    p.add_argument('--skills-dir', help='Confirmed host skill directory, if not the default')
    p.add_argument('--data-dir', help='Same onboarding directory used by this installation')
    args = p.parse_args()
    if args.host == 'custom' and not args.skills_dir:
        p.error('--host custom requires --skills-dir confirmed by the target Agent')
    try:
        data = data_directory(args.data_dir)
        parent = Path(args.skills_dir).expanduser() if args.skills_dir else (
            Path.home() / ('.agents/skills' if args.host == 'codex' else '.workbuddy/skills'))
        protected = [data, DEFAULT_DATA_DIR, Path.home() / '.agently-cli',
                     Path.home() / 'Library/Application Support/agently-cli',
                     Path.home() / 'Library/Keychains']
        result = install_skill(SKILL_ROOT, parent / 'sms-agent-mail', protected)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError):
        print(json.dumps({'ok': False, 'reason': 'install_failed_invalid_paths_or_files'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
