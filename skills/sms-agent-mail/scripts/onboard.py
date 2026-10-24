"""Keep onboarding settings outside the skill; leave OAuth storage to Agently."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

from check_access import check_identity

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path.home() / '.local/share/sms-agent-mail'


def overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def data_directory(value=None) -> Path:
    raw = Path(value).expanduser() if value else DEFAULT_DATA_DIR
    if raw.is_symlink():
        raise ValueError('data_directory_is_symlink')
    root = raw.resolve()
    if overlaps(root, SKILL_ROOT):
        raise ValueError('data_directory_must_be_separate_from_skill')
    protected = (Path.home() / '.agently-cli', Path.home() / 'Library/Application Support/agently-cli',
                 Path.home() / 'Library/Keychains')
    if any(overlaps(root, p) for p in protected):
        raise ValueError('data_directory_overlaps_provider_storage')
    return root


def profile_path(root: Path, profile: str) -> Path:
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', profile):
        raise ValueError('invalid_profile_name')
    return root / 'profiles' / (profile + '.json')


def _private_directory(path: Path):
    if path.is_symlink():
        raise ValueError('state_directory_is_symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('state_directory_must_be_private')


def load_profile(path: Path) -> dict:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('profile_is_symlink')
    info = path.stat()
    if info.st_size > 16_384:
        raise ValueError('profile_too_large')
    if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('profile_must_be_private')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('backend') not in ('cli', 'native'):
        raise ValueError('invalid_profile')
    email = value.get('expected_email')
    if not isinstance(email, str) or '@' not in email or any(c.isspace() for c in email):
        raise ValueError('invalid_profile_email')
    if not isinstance(value.get('cli'), str) or not value['cli']:
        raise ValueError('invalid_cli')
    return value


def write_json(path: Path, value: dict, *, exclusive=False):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        return
    fd, name = tempfile.mkstemp(prefix='.profile-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _valid_routes(routes) -> bool:
    return isinstance(routes, dict) and all(
        isinstance(k, str) and isinstance(v, str) and re.fullmatch(r'SIM[1-9]_([0-9]{4})', k)
        and k.split('_')[1] == v for k, v in routes.items())


def _valid_senders(senders) -> bool:
    return isinstance(senders, list) and all(
        isinstance(v, str) and '@' in v and not any(c.isspace() for c in v) for v in senders)


def _valid_services(services) -> bool:
    return isinstance(services, dict) and all(
        isinstance(k, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,23}', k)
        and isinstance(v, str) and 0 < len(v) <= 24 and '\n' not in v and v.strip() == v
        for k, v in services.items())


def _valid_subject_pattern(pattern) -> bool:
    if not isinstance(pattern, str) or len(pattern) > 200:
        return False
    try:
        return re.compile(pattern).groups >= 2
    except re.error:
        return False


def init_profile(root: Path, profile: str, email: str | None, backend='cli', cli='agently-cli', *,
                 routes=None, trusted_senders=None, services=None,
                 subject_pattern=None) -> dict:
    path = profile_path(root, profile)
    if email is None and path.exists():
        email = load_profile(path)['expected_email']
    if email is None:
        raise ValueError('initial_email_required')
    if not isinstance(email, str) or '@' not in email or any(c.isspace() for c in email):
        raise ValueError('invalid_email')
    if backend not in ('cli', 'native') or not cli:
        raise ValueError('invalid_backend_or_cli')
    if routes is not None and not _valid_routes(routes):
        raise ValueError('invalid_phone_routes')
    if trusted_senders is not None and not _valid_senders(trusted_senders):
        raise ValueError('invalid_trusted_senders')
    if services is not None and not _valid_services(services):
        raise ValueError('invalid_services')
    if subject_pattern is not None and not _valid_subject_pattern(subject_pattern):
        raise ValueError('invalid_subject_pattern')
    _private_directory(root)
    _private_directory(path.parent)
    settings = {'schema': 1, 'expected_email': email.lower(), 'backend': backend,
                'cli': cli, 'verification': 'not_verified', 'phone_routes': dict(routes or {}),
                'subject_pattern': subject_pattern or r'^(SIM[1-9]_([0-9]{4}))的短信验证码$',
                'services': dict(services) if services is not None
                            else {'baidu': '【百度】', 'toutiao': '【今日头条】'},
                'trusted_senders': [v.lower() for v in trusted_senders or []]}
    try:
        write_json(path, settings, exclusive=True)
        return {'ok': True, 'state': 'configured_not_verified', 'profile_file': str(path)}
    except FileExistsError:
        previous = load_profile(path)
        if any(previous.get(k) != settings[k] for k in ('expected_email', 'backend', 'cli')):
            raise ValueError('existing_profile_differs_not_overwritten')
        if (routes is not None and previous.get('phone_routes') != routes) or (
                trusted_senders is not None and previous.get('trusted_senders') != settings['trusted_senders']) or (
                services is not None and previous.get('services') != settings['services']) or (
                subject_pattern is not None and previous.get('subject_pattern') != subject_pattern):
            raise ValueError('existing_profile_differs_not_overwritten')
        return {'ok': True, 'state': 'existing_profile_preserved', 'profile_file': str(path)}


def set_rules(root: Path, profile: str, *, routes=None, trusted_senders=None, services=None,
              subject_pattern=None) -> dict:
    """Change parsing rules only, keeping a private copy of the previous file."""
    if routes is None and trusted_senders is None and services is None and subject_pattern is None:
        raise ValueError('no_rules_supplied')
    path = profile_path(root, profile)
    _private_directory(root)
    _private_directory(path.parent)
    settings = load_profile(path)
    if routes is not None:
        if not _valid_routes(routes):
            raise ValueError('invalid_phone_routes')
    if trusted_senders is not None and not _valid_senders(trusted_senders):
        raise ValueError('invalid_trusted_senders')
    if services is not None and not _valid_services(services):
        raise ValueError('invalid_services')
    if subject_pattern is not None and not _valid_subject_pattern(subject_pattern):
        raise ValueError('invalid_subject_pattern')
    backup = path.with_suffix('.json.bak')
    if backup.is_symlink():
        raise ValueError('profile_is_symlink')
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(path.read_bytes())
    changed = []
    if routes is not None:
        settings['phone_routes'] = dict(routes)
        changed.append('phone_routes')
    if trusted_senders is not None:
        settings['trusted_senders'] = [v.lower() for v in trusted_senders]
        changed.append('trusted_senders')
    if services is not None:
        settings['services'] = dict(services)
        changed.append('services')
    if subject_pattern is not None:
        settings['subject_pattern'] = subject_pattern
        changed.append('subject_pattern')
    write_json(path, settings)
    return {'ok': True, 'state': 'rules_updated', 'changed': changed,
            'previous_copy': str(backup), 'profile_file': str(path),
            'identity_unchanged': {'expected_email': settings['expected_email'],
                                   'backend': settings['backend'], 'cli': settings['cli']}}


def confirm_identity(root: Path, profile: str, evidence: str) -> dict:
    """Record a host-side identity check for the native backend only."""
    path = profile_path(root, profile)
    _private_directory(root)
    _private_directory(path.parent)
    settings = load_profile(path)
    if settings['backend'] != 'native':
        raise ValueError('confirm_only_for_native_backend')
    value = (evidence or '').strip()
    if not 8 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_host_evidence')
    settings['verification'] = 'identity_verified_by_host'
    settings['checked_at'] = datetime.now(timezone.utc).isoformat()
    settings['host_evidence'] = value
    write_json(path, settings)
    return {'ok': True, 'state': 'identity_verified_by_host',
            'expected_email': settings['expected_email'], 'host_evidence': value,
            'profile_file': str(path)}


def local_workspace(cli: str) -> str | None:
    """Read only the CLI's local workspace label, never its token values."""
    try:
        p = subprocess.run([cli, 'auth', 'status'], capture_output=True, text=True,
                           timeout=10, check=False)
        if len(p.stdout) > 1_000_000:
            return None
        document = json.loads(p.stdout)
        data = document.get('data') if isinstance(document, dict) else None
        label = data.get('workspace') if isinstance(data, dict) else None
        return label if isinstance(label, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}', label) else None
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        return None


def storage_paths(root: Path, profile: str, *, workspace=None, backend='cli') -> dict:
    if not isinstance(workspace, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', workspace):
        workspace = None
    report = {'skill_directory': str(SKILL_ROOT), 'settings_directory': str(root),
              'profile_file': str(profile_path(root, profile)),
              'cli_config_directory': str(Path.home() / '.agently-cli'),
              'oauth_storage_owner': 'Agently CLI / OS credential store',
              'workspace': workspace, 'oauth_directory': None,
              'oauth_file': None, 'keychain_service': None,
              'oauth_relocated_or_exported': False}
    if backend == 'native':
        report.update(cli_config_directory=None, oauth_storage_owner='Host native mail connector',
                      workspace=None, provider_storage_note='The host manages its credentials; verify its actual local storage separately.')
        return report
    if sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support/agently-cli'
        report['provider_storage_base'] = str(base)
        if workspace:
            directory = base / 'agents' / workspace
            credential = directory / 'bootstrap_token.enc'
            report['provider_path_candidate'] = str(credential)
            report['provider_path_observed'] = credential.is_file()
            if credential.is_file():
                report.update(oauth_directory=str(directory), oauth_file=str(credential),
                              keychain_service='agently-cli/agents/' + workspace,
                              keychain_account='master.key')
        report['other_provider_files_note'] = 'Existing base-directory files are preserved; do not copy or delete them.'
    else:
        report['provider_storage_note'] = 'Provider paths on this OS require local verification; no macOS path is assumed.'
    return report


def verify_profile(root: Path, profile: str) -> tuple[int, dict]:
    path = profile_path(root, profile)
    _private_directory(root)
    _private_directory(path.parent)
    settings = load_profile(path)
    if settings['backend'] == 'native':
        return 1, {'ok': False, 'reason': 'verify_with_host_native_identity_tool',
                   'expected_mailbox': settings['expected_email'], 'profile_file': str(path),
                   'record_after_host_check': 'onboard.py confirm --profile <name> --evidence <how>',
                   'storage': storage_paths(root, profile, backend='native')}
    code, report = check_identity(settings['cli'], settings['expected_email'])
    workspace = local_workspace(settings['cli'])
    settings['verification'] = 'identity_verified' if code == 0 else 'identity_check_failed'
    settings['checked_at'] = datetime.now(timezone.utc).isoformat()
    settings['reported_workspace'] = workspace
    write_json(path, settings)
    report['storage'] = storage_paths(root, profile, workspace=workspace)
    report['authorization_next_step'] = None if code == 0 else (
        'identity_mismatch_stop_do_not_overwrite' if report.get('reason') == 'mailbox_identity_mismatch'
        else 'follow_onboarding_reference_do_not_send_secrets_to_chat')
    return code, report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'init', 'status', 'paths', 'verify',
                                      'set-rules', 'confirm'))
    p.add_argument('--profile', required=True, help='Local name: lowercase letters, digits and hyphens, up to 32 characters')
    p.add_argument('--data-dir')
    p.add_argument('--email')
    p.add_argument('--backend', choices=('cli', 'native'), default='cli')
    p.add_argument('--cli', default='agently-cli')
    p.add_argument('--route', action='append', help='Confirmed SIM route, e.g. SIM2_1234=1234; repeat for each SIM')
    p.add_argument('--trusted-sender', action='append', help='Forwarder address confirmed from phone setup; repeat if needed')
    p.add_argument('--service', action='append', metavar='NAME=TAG',
                   help='Service key and body tag, e.g. baidu=【百度】; repeat for each service')
    p.add_argument('--subject-pattern', help='Subject regex with two groups: route and suffix')
    p.add_argument('--evidence', help='How the host verified identity, e.g. host GetMe alias match')
    args = p.parse_args()
    try:
        root = data_directory(args.data_dir)
        code = 0
        services = None
        if args.service is not None:
            services = {}
            for value in args.service:
                key, separator, tag = value.partition('=')
                if not separator or key in services:
                    raise ValueError('invalid_services')
                services[key.strip()] = tag.strip()
        if args.action == 'prepare':
            _private_directory(root)
            report = {'ok': True, 'state': 'private_directory_ready',
                      'storage': storage_paths(root, args.profile, backend=args.backend)}
        elif args.action == 'init':
            routes = None
            if args.route is not None:
                routes = {}
                for value in args.route:
                    key, separator, suffix = value.partition('=')
                    if not separator or key in routes:
                        raise ValueError('invalid_phone_routes')
                    routes[key] = suffix
            report = init_profile(root, args.profile, args.email, args.backend, args.cli,
                                  routes=routes, trusted_senders=args.trusted_sender,
                                  services=services, subject_pattern=args.subject_pattern)
            workspace = local_workspace(args.cli) if args.backend == 'cli' else None
            report['storage'] = storage_paths(root, args.profile, workspace=workspace, backend=args.backend)
            report['next_step'] = 'verify_existing_identity_then_authorize_if_needed'
        elif args.action == 'set-rules':
            routes = None
            if args.route is not None:
                routes = {}
                for value in args.route:
                    key, separator, suffix = value.partition('=')
                    if not separator or key in routes:
                        raise ValueError('invalid_phone_routes')
                    routes[key] = suffix
            report = set_rules(root, args.profile, routes=routes,
                               trusted_senders=args.trusted_sender, services=services,
                               subject_pattern=args.subject_pattern)
        elif args.action == 'confirm':
            report = confirm_identity(root, args.profile, args.evidence)
        elif args.action == 'verify':
            code, report = verify_profile(root, args.profile)
        else:
            path = profile_path(root, args.profile)
            settings = load_profile(path) if path.exists() else None
            workspace = settings.get('reported_workspace') if settings else None
            report = {'ok': True, 'configured': settings is not None,
                      'verification': settings.get('verification') if settings else 'not_configured',
                      'storage': storage_paths(root, args.profile, workspace=workspace,
                                               backend=settings['backend'] if settings else args.backend)}
            if settings:
                report.update({key: settings.get(key) for key in (
                    'expected_email', 'backend', 'cli', 'phone_routes', 'subject_pattern', 'services', 'trusted_senders')})
        print(json.dumps(report, ensure_ascii=False))
        return code
    except (OSError, ValueError, TypeError) as error:
        # Never echo exception text: it may contain contents of an invalid file.
        known = {'data_directory_is_symlink', 'data_directory_must_be_separate_from_skill',
                 'data_directory_overlaps_provider_storage',
                 'invalid_profile_name', 'state_directory_is_symlink', 'state_directory_must_be_private',
                 'profile_is_symlink', 'profile_too_large', 'profile_must_be_private',
                 'invalid_profile', 'invalid_profile_email', 'invalid_cli', 'invalid_email',
                 'invalid_phone_routes', 'invalid_trusted_senders',
                 'invalid_services', 'invalid_subject_pattern', 'no_rules_supplied',
                 'confirm_only_for_native_backend', 'invalid_host_evidence',
                 'initial_email_required',
                 'invalid_backend_or_cli', 'existing_profile_differs_not_overwritten'}
        reason = error.args[0] if error.args and isinstance(error.args[0], str) and error.args[0] in known else 'profile_missing_or_unreadable'
        print(json.dumps({'ok': False, 'reason': reason}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
