"""Verify one message against the saved profile; never print the code itself."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
import sys
from pathlib import Path

from onboard import data_directory, load_profile, profile_path

# Any verification code found here is reduced to a length in the report. The
# full body is external data: it is parsed, never executed or echoed.
CODE_PATTERNS = (re.compile(r'验证码[：:\s]*([0-9]{4,8})'), re.compile(r'[Cc]ode[：:\s]*([0-9]{4,8})'))
BODY_TIME = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
ROUTE_TOKEN = re.compile(r'SIM[1-9]_[0-9]{4}')
TRUNCATION_MARKERS = ('…', '...', '［截断］', '[truncated]', '<truncated>')
MAX_BODY = 2_000_000


def _addresses(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get('email'), str):
            result.append(item['email'].strip().lower())
        elif isinstance(item, str) and '@' in item:
            result.append(item.strip().lower())
    return result


def _text(body: str) -> str:
    stripped = re.sub(r'<[^>]{1,200}>', ' ', body)
    return re.sub(r'\s+', ' ', stripped).strip()


def _instant(value: str, default_offset_hours: float) -> datetime | None:
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        try:
            parsed = datetime.strptime(raw, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone(timedelta(hours=default_offset_hours)))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=default_offset_hours)))
    return parsed


def verify_message(settings: dict, message: dict, *, after: str | None = None,
                   before: str | None = None, body_offset_hours: float = 8.0,
                   max_skew: int = 120) -> dict:
    checks: dict[str, dict] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    sender = (_addresses(message.get('from')) or [''])[0]
    recipients = _addresses(message.get('to'))
    subject = str(message.get('subject') or '')
    body = str(message.get('body') or '')
    if len(body) > MAX_BODY:
        return {'ok': False, 'verdict': 'blocked', 'checks': {}, 'warnings': [],
                'blockers': ['message_too_large']}
    text = _text(body)

    trusted = [value.lower() for value in settings.get('trusted_senders') or []]
    if not trusted:
        checks['sender_trusted'] = {'pass': False, 'reason': 'trusted_senders_not_configured'}
        blockers.append('trusted_senders_not_configured')
    else:
        matched = sender in trusted
        checks['sender_trusted'] = {'pass': matched, 'sender': sender}
        if not matched:
            blockers.append('sender_not_trusted')

    expected = str(settings.get('expected_email') or '').lower()
    received = expected in recipients
    extra = [value for value in recipients if value != expected]
    checks['recipient_matched'] = {'pass': received, 'expected': expected,
                                   'extra_recipients': extra}
    if not received:
        blockers.append('expected_recipient_missing')
    if extra:
        warnings.append('extra_recipient:' + ','.join(extra))

    services = settings.get('services') or {}
    hit = next((name for name, tag in services.items() if isinstance(tag, str) and tag and tag in text), None)
    if not services:
        checks['service_matched'] = {'pass': False, 'reason': 'services_not_configured'}
        blockers.append('services_not_configured')
    else:
        checks['service_matched'] = {'pass': hit is not None, 'service': hit,
                                     'declared': sorted(services)}
        if hit is None:
            blockers.append('service_tag_not_found')

    routes = settings.get('phone_routes') or {}
    pattern = str(settings.get('subject_pattern') or '')
    route = suffix = None
    try:
        match = re.fullmatch(pattern, subject) if pattern else None
    except re.error:
        match = None
        checks['route_subject'] = {'pass': False, 'reason': 'subject_pattern_invalid'}
        blockers.append('subject_pattern_invalid')
    if 'route_subject' not in checks:
        if match is None:
            checks['route_subject'] = {'pass': False, 'reason': 'subject_route_unparsed',
                                       'subject': subject}
            blockers.append('subject_route_unparsed')
        else:
            route, suffix = match.group(1), match.group(2)
            if not routes:
                checks['route_subject'] = {'pass': False, 'reason': 'phone_routes_not_configured',
                                           'route': route}
                blockers.append('phone_routes_not_configured')
            elif route not in routes:
                checks['route_subject'] = {'pass': False, 'reason': 'route_not_registered',
                                           'route': route, 'declared': sorted(routes)}
                blockers.append('route_not_registered')
            elif routes[route] != suffix:
                checks['route_subject'] = {'pass': False, 'reason': 'route_suffix_mismatch',
                                           'route': route}
                blockers.append('route_suffix_mismatch')
            else:
                body_routes = set(ROUTE_TOKEN.findall(text))
                conflicts = sorted(body_routes - {route})
                checks['route_subject'] = {'pass': not conflicts, 'route': route,
                                           'body_routes': sorted(body_routes)}
                if conflicts:
                    blockers.append('route_subject_body_conflict')
                elif route not in body_routes:
                    checks['route_subject'] = {'pass': False, 'reason': 'route_absent_in_body',
                                               'route': route}
                    blockers.append('route_absent_in_body')

    complete = len(text) >= 20 and not text.endswith(TRUNCATION_MARKERS)
    checks['body_complete'] = {'pass': complete, 'characters': len(text),
                               'format': message.get('body_format') or 'unknown'}
    if not complete:
        blockers.append('body_incomplete_or_truncated')

    created = _instant(str(message.get('created_at') or ''), body_offset_hours)
    window_after = _instant(after, body_offset_hours) if after else None
    window_before = _instant(before, body_offset_hours) if before else None
    if created is None:
        checks['time'] = {'pass': False, 'reason': 'created_at_missing_or_unparsed'}
        blockers.append('created_at_missing')
    elif (window_after and created < window_after) or (window_before and created > window_before):
        checks['time'] = {'pass': False, 'reason': 'created_at_outside_window',
                          'field': 'created_at', 'created_at': created.isoformat()}
        blockers.append('created_at_outside_window')
    else:
        body_stamp = BODY_TIME.search(text)
        if body_stamp is None:
            checks['time'] = {'pass': False, 'reason': 'body_time_missing',
                              'field': 'created_at', 'created_at': created.isoformat(),
                              'created_at_only': True}
            blockers.append('body_time_missing')
        else:
            stated = _instant(body_stamp.group(1), body_offset_hours)
            skew = int((created - stated).total_seconds())
            within = abs(skew) <= max_skew
            checks['time'] = {'pass': within, 'field': 'body_timestamp+created_at',
                              'body_timestamp': stated.isoformat(),
                              'created_at': created.isoformat(), 'skew_seconds': skew}
            if not within:
                blockers.append('created_at_body_time_skew')

    found = {value for pattern_item in CODE_PATTERNS
             for value in pattern_item.findall(text)}
    lead = re.match(r'[0-9]{8,}', text)
    if not found:
        checks['code'] = {'pass': False, 'reason': 'code_not_found'}
        blockers.append('code_not_found')
    elif len(found) > 1:
        checks['code'] = {'pass': False, 'reason': 'code_ambiguous', 'candidates': len(found)}
        blockers.append('code_ambiguous')
    else:
        only = next(iter(found))
        checks['code'] = {'pass': True, 'length': len(only)}
        if lead and only in lead.group(0):
            checks['code'] = {'pass': False, 'reason': 'code_matches_sms_port',
                              'length': len(only)}
            blockers.append('code_matches_sms_port')

    verdict = 'pass' if not blockers else 'blocked'
    return {'ok': verdict == 'pass', 'verdict': verdict, 'checks': checks,
            'warnings': warnings, 'blockers': sorted(set(blockers))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--data-dir')
    parser.add_argument('--message-json', help='Read the message from this file instead of stdin')
    parser.add_argument('--after', help='Inclusive lower bound, ISO 8601 with timezone')
    parser.add_argument('--before', help='Inclusive upper bound, ISO 8601 with timezone')
    parser.add_argument('--body-offset-hours', type=float, default=8.0,
                        help='Timezone of body timestamps when they carry no offset')
    parser.add_argument('--max-skew', type=int, default=120)
    args = parser.parse_args()
    try:
        settings = load_profile(profile_path(data_directory(args.data_dir), args.profile))
    except (OSError, ValueError, TypeError):
        print(json.dumps({'ok': False, 'verdict': 'error', 'reason': 'profile_missing_or_unreadable'}))
        return 2
    try:
        raw = Path(args.message_json).expanduser().read_text(encoding='utf-8') if args.message_json \
            else sys.stdin.read()
        message = json.loads(raw)
    except (OSError, ValueError):
        print(json.dumps({'ok': False, 'verdict': 'error', 'reason': 'message_unreadable'}))
        return 2
    if not isinstance(message, dict):
        print(json.dumps({'ok': False, 'verdict': 'error', 'reason': 'message_not_an_object'}))
        return 2
    report = verify_message(settings, message, after=args.after, before=args.before,
                            body_offset_hours=args.body_offset_hours, max_skew=args.max_skew)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
