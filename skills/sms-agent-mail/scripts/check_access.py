"""Probe the current CLI identity without reading mail or exporting credentials."""
from __future__ import annotations

import argparse
import json
import subprocess


def check_identity(cli: str, expected_email: str) -> tuple[int, dict]:
    try:
        result = subprocess.run([cli, '+me'], capture_output=True, text=True,
                                timeout=30, check=False)
    except FileNotFoundError:
        return 2, {'ok': False, 'reason': 'cli_not_found'}
    except subprocess.TimeoutExpired:
        return 2, {'ok': False, 'reason': 'cli_timeout'}
    except (OSError, UnicodeError):
        return 2, {'ok': False, 'reason': 'cli_unavailable'}
    if result.returncode:
        return 2, {'ok': False, 'reason': 'cli_identity_failed', 'cli_exit': result.returncode}
    try:
        if len(result.stdout) > 1_000_000:
            raise ValueError('response_too_large')
        envelope = json.loads(result.stdout)
        if not isinstance(envelope, dict) or envelope.get('ok') is not True:
            raise ValueError('invalid_envelope')
        identity = envelope.get('data')
        if not isinstance(identity, dict):
            raise ValueError('invalid_identity')
        aliases, scopes = identity.get('aliases'), identity.get('scopes')
        if not isinstance(aliases, list) or not isinstance(scopes, list):
            raise ValueError('invalid_fields')
        if not all(isinstance(x, dict) and isinstance(x.get('email'), str) for x in aliases):
            raise ValueError('invalid_aliases')
        if not all(isinstance(x, str) for x in scopes):
            raise ValueError('invalid_scopes')
    except (ValueError, TypeError):
        return 2, {'ok': False, 'reason': 'identity_contract_invalid'}
    matches = any(a['email'].lower() == expected_email.lower() for a in aliases)
    readable = 'mail:read' in scopes
    report = {'ok': matches and readable, 'expected_mailbox': expected_email,
              'mailbox_matches': matches, 'mail_read': readable,
              'cloud_read_only_scope': readable and not (set(scopes) - {'mail:read', 'alias:read'}),
              'mail_searched_or_read': False}
    if not matches:
        report['reason'] = 'mailbox_identity_mismatch'
    elif not readable:
        report['reason'] = 'mail_read_scope_missing'
    return (0 if report['ok'] else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-email', required=True)
    parser.add_argument('--cli', default='agently-cli')
    args = parser.parse_args()
    if '@' not in args.expected_email or any(c.isspace() for c in args.expected_email):
        parser.error('expected-email must be a mailbox address')
    status, report = check_identity(args.cli, args.expected_email)
    print(json.dumps(report, ensure_ascii=False))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
