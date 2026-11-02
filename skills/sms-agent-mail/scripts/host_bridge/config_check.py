"""Validate and resolve host-bridge config for native-connector hosts (schema 1).

Pure standard library. No network, no secrets printed: the IMAP password is only
ever referenced by file path and checked for permissions, never read here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

SCHEMA = 1
MAIL_SOURCES = ('webmail', 'imap')
ROUTE_RE = re.compile(r'SIM[1-9]_[0-9]{4}')
PHONE_RE = re.compile(r'1[3-9][0-9]{9}')
TARGET_KEYS = ('url', 'phone', 'phone_selector', 'send_selector',
               'code_selector', 'submit_selector', 'account_marker')
DEFAULT_DATA_DIR = Path.home() / '.local' / 'share' / 'sms-agent-mail'


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != '' and '\n' not in value


def _read_profile(data_dir: Path, name: str) -> dict:
    path = data_dir / 'profiles' / f'{name}.json'
    if not path.exists():
        raise ValueError('profile_not_found')
    if path.is_symlink():
        raise ValueError('profile_is_symlink')
    settings = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(settings, dict) or settings.get('schema') != SCHEMA:
        raise ValueError('profile_schema_invalid')
    return settings


def _check_password_file(raw: str) -> str:
    path = Path(os.path.expanduser(raw))
    if path.is_symlink():
        raise ValueError('imap_password_file_is_symlink')
    if not path.exists():
        raise ValueError('imap_password_file_not_found')
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError('imap_password_file_too_permissive')
    if path.stat().st_size > 4096:
        raise ValueError('imap_password_file_oversized')
    return str(path)


def validate(config: dict, data_dir: Path) -> dict:
    """Return the resolved config or raise ValueError(reason)."""
    if not isinstance(config, dict):
        raise ValueError('config_not_object')
    if config.get('schema') != SCHEMA:
        raise ValueError('config_schema_invalid')

    resolved = {
        'schema': SCHEMA,
        'task_space': config.get('task_space') or 'workbuddy sms login',
        'mail_source': config.get('mail_source'),
        'code_wait_seconds': config.get('code_wait_seconds', 240),
        'poll_interval_seconds': config.get('poll_interval_seconds', 4),
        'body_offset_hours': config.get('body_offset_hours', 8),
    }
    if resolved['mail_source'] not in MAIL_SOURCES:
        raise ValueError('invalid_mail_source')
    for key, low, high in (('code_wait_seconds', 30, 300),
                           ('poll_interval_seconds', 2, 30),
                           ('body_offset_hours', -23, 23)):
        value = resolved[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f'invalid_{key}')

    profile_settings = _resolve_profile(config, resolved, data_dir)
    _resolve_target_identity(config, resolved, profile_settings)

    target = config.get('target') or {}
    if not isinstance(target, dict):
        raise ValueError('target_not_object')
    # mail_only 只验证取码通道，不操作目标站，因此不强制要求选择器
    if config.get('mail_only') is True and not target:
        resolved['mail_only'] = True
        resolved['target'] = None
        _resolve_mail_source(config, resolved, profile_settings)
        return resolved

    resolved_target = {}
    for key in TARGET_KEYS:
        if not _nonempty_str(target.get(key)):
            raise ValueError(f'target_{key}_missing')
        resolved_target[key] = target[key]
    if not resolved_target['url'].startswith('https://'):
        raise ValueError('target_url_not_https')
    agree = target.get('agree_selector')
    if agree is not None and not _nonempty_str(agree):
        raise ValueError('target_agree_selector_invalid')
    if agree:
        resolved_target['agree_selector'] = agree

    resolved_target['phone'] = _resolve_phone(resolved_target['phone'], resolved, profile_settings)

    _resolve_mail_source(config, resolved, profile_settings)
    resolved['target'] = resolved_target
    return resolved


def _resolve_target_identity(config: dict, resolved: dict, profile_settings) -> None:
    """服务与路由是校验器的必填输入，缺了就不许自动选码。"""
    service = config.get('service')
    if not _nonempty_str(service):
        raise ValueError('service_missing')
    services = (profile_settings or {}).get('services') or {}
    if profile_settings and service not in services:
        raise ValueError('service_not_in_profile')
    resolved['service'] = service
    resolved['service_tag'] = services.get(service)

    route = config.get('route')
    if not _nonempty_str(route) or not ROUTE_RE.fullmatch(route):
        raise ValueError('invalid_route')
    rows = (profile_settings or {}).get('phone_routes') or {}
    if profile_settings and route not in rows:
        raise ValueError('route_not_in_profile')
    resolved['route'] = route


def _resolve_phone(phone: str, resolved: dict, profile_settings) -> str:
    """只接受完整手机号；尾号无法反推完整号码，因此不做任何补猜。"""
    if not PHONE_RE.fullmatch(phone or ''):
        raise ValueError('target_phone_not_full_number')
    expected_tail = ((profile_settings or {}).get('phone_routes') or {}).get(resolved['route'])
    if expected_tail and not phone.endswith(expected_tail):
        raise ValueError('target_phone_tail_mismatch')
    return phone


def _resolve_profile(config: dict, resolved: dict, data_dir: Path):
    profile_name = config.get('profile')
    if not profile_name:
        return None
    if not isinstance(profile_name, str) or not profile_name.replace('-', '').isalnum():
        raise ValueError('invalid_profile_name')
    settings = _read_profile(data_dir, profile_name)
    resolved['profile'] = profile_name
    resolved['expected_email'] = settings.get('expected_email')
    return settings


def _resolve_mail_source(config: dict, resolved: dict, profile_settings) -> None:
    if resolved['mail_source'] == 'imap':
        imap = config.get('imap') or {}
        if not isinstance(imap, dict):
            raise ValueError('imap_not_object')
        if not _nonempty_str(imap.get('host')):
            raise ValueError('imap_host_missing')
        if not _nonempty_str(imap.get('user')):
            raise ValueError('imap_user_missing')
        if not _nonempty_str(imap.get('password_file')):
            raise ValueError('imap_password_file_missing')
        sender = imap.get('sender')
        if not _nonempty_str(sender) and profile_settings:
            trusted = profile_settings.get('trusted_senders') or []
            sender = trusted[0] if len(trusted) == 1 else None
        if not _nonempty_str(sender):
            raise ValueError('imap_sender_missing')
        resolved['imap'] = {
            'host': imap['host'],
            'user': imap['user'],
            'password_file': _check_password_file(imap['password_file']),
            'sender': sender,
            'limit': int(imap.get('limit', 5)),
        }
    else:
        webmail = config.get('webmail') or {}
        if not isinstance(webmail, dict):
            raise ValueError('webmail_not_object')
        if not _nonempty_str(webmail.get('list_url')):
            raise ValueError('webmail_list_url_missing')
        if not webmail['list_url'].startswith('https://'):
            raise ValueError('webmail_list_url_not_https')
        row = webmail.get('row_selector')
        if row is not None and not _nonempty_str(row):
            raise ValueError('webmail_row_selector_invalid')
        fallback = webmail.get('allow_regex_fallback', True)
        if not isinstance(fallback, bool):
            raise ValueError('webmail_allow_regex_fallback_invalid')
        resolved['webmail'] = {
            'list_url': webmail['list_url'],
            'row_selector': row,
            'subject_selector': webmail.get('subject_selector') or '.mail-item-subject',
            'header_selector': webmail.get('header_selector') or '.botmail-mail-reader-body-basic',
            'body_selector': webmail.get('body_selector') or '.botmail-mail-reader-body-content',
            'allow_regex_fallback': fallback,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--data-dir')
    args = parser.parse_args()

    data_dir = Path(os.path.expanduser(args.data_dir)) if args.data_dir else DEFAULT_DATA_DIR
    try:
        config = json.loads(Path(os.path.expanduser(args.config)).read_text(encoding='utf-8'))
        resolved = validate(config, data_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        reason = error.args[0] if isinstance(error, ValueError) and error.args else type(error).__name__
        print(json.dumps({'ok': False, 'reason': str(reason)}))
        return 1
    print(json.dumps({'ok': True, 'resolved': resolved}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
