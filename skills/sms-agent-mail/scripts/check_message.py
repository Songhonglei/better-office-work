"""Validate a message for one login attempt; return only a redacted verdict."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
import sys
from pathlib import Path

from onboard import (data_directory, load_profile, profile_path, _valid_routes,
                     _valid_senders, _valid_services, _valid_subject_pattern)

CODE_PATTERNS = (re.compile(r'验证码[：:\s]*([0-9]{4,8})(?!\d)'),
                 re.compile(r'\bcode[：:\s]*([0-9]{4,8})(?!\d)', re.I))
BODY_TIME = re.compile(r'(?<!\d)(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?!\d)')
ROUTE_TOKEN = re.compile(r'SIM[1-9]_[0-9]{4}(?!\d)')
TRUNCATION_MARKERS = ('…', '...', '［截断］', '[truncated]', '<truncated>')
EXPIRY_BEFORE = re.compile(r'([0-9]+)\s*(秒|分钟|分鐘|分)(?:内|內)?有效')
MAX_BODY = 2_000_000
LOGIN = re.compile(r'登录|登錄|\blog\s*in\b|\bsign\s*in\b', re.I)
OTHER_PURPOSE = re.compile(r'重置|找回|修改密码|支付|转账|注册|註冊|\breset\b|\bpayment\b|\bregister\b', re.I)
EXPIRY = re.compile(r'有效(?:期)?(?:为|為)?\s*([0-9]+)\s*(秒|分钟|分鐘|分)|'
                    r'\bvalid\s+(?:for\s+)?([0-9]+)\s*(seconds?|minutes?)', re.I)


def _addresses(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        address = item.get('email') if isinstance(item, dict) else item
        if isinstance(address, str) and '@' in address:
            result.append(address.strip().lower())
    return result


def _text(body: str) -> str:
    stripped = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', body,
                      flags=re.I | re.S)
    stripped = re.sub(r'<!--.*?-->', '', stripped, flags=re.S)
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]{1,200}>', ' ', stripped))).strip()


def _instant(value: str, default_offset_hours: float | None = None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            if default_offset_hours is None:
                return None
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=default_offset_hours)))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def extract_code(body: str) -> str | None:
    """Return an unambiguous code in memory; callers must never serialize it."""
    found = {v for p in CODE_PATTERNS for v in p.findall(_text(body))}
    return next(iter(found)) if len(found) == 1 else None


def verify_message(settings: dict, message: dict, *, after: str | None = None,
                   before: str | None = None, expected_service: str | None = None,
                   expected_route: str | None = None, purpose: str | None = None,
                   now: datetime | None = None, body_offset_hours: float = 8.0,
                   max_skew: int = 300, max_age: int = 300) -> dict:
    """Fail closed without a timezone-aware window and a registered target.

    now is an injectable UTC clock for offline replay; CLI always uses real time.
    max_age can only shorten the five-minute ceiling. No input text is reported.
    """
    checks, blockers, warnings = {}, [], []

    def record(name, passed, reason, **details):
        checks[name] = {'pass': bool(passed), **details}
        if not passed:
            blockers.append(reason)

    def result():
        return {'ok': not blockers, 'verdict': 'blocked' if blockers else 'pass',
                'checks': checks, 'warnings': warnings, 'blockers': sorted(set(blockers))}

    if not isinstance(settings, dict) or not isinstance(message, dict):
        blockers.append('invalid_input')
        return result()
    routes, services = settings.get('phone_routes'), settings.get('services')
    trusted, pattern = settings.get('trusted_senders'), settings.get('subject_pattern')
    if not (_valid_routes(routes) and _valid_services(services) and _valid_senders(trusted)
            and _valid_subject_pattern(pattern)):
        blockers.append('profile_rules_invalid')
        return result()
    if (not isinstance(max_age, int) or not 1 <= max_age <= 300
            or not isinstance(max_skew, int) or not 0 <= max_skew <= 300
            or not isinstance(body_offset_hours, (float, int)) or not -23 < body_offset_hours < 23):
        blockers.append('invalid_time_policy')
        return result()
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        blockers.append('invalid_clock')
        return result()
    lower, upper = _instant(after), _instant(before)
    valid_window = (lower is not None and upper is not None and lower <= upper <= current
                    and (upper - lower).total_seconds() <= max_age)
    record('window', valid_window, 'query_window_missing_or_invalid')
    record('target', expected_service in services and expected_route in routes and purpose == 'login',
           'target_missing_or_unregistered')
    body, subject = message.get('body'), message.get('subject')
    if not isinstance(body, str) or not isinstance(subject, str):
        blockers.append('message_fields_invalid')
        return result()
    if len(body) > MAX_BODY or len(subject) > 4096:
        blockers.append('message_too_large')
        return result()
    text = _text(body)
    senders = _addresses(message.get('from'))
    record('sender_trusted', len(senders) == 1 and senders[0] in [v.lower() for v in trusted],
           'sender_not_trusted' if trusted else 'trusted_senders_not_configured')
    recipients = _addresses(message.get('to'))
    expected = str(settings.get('expected_email') or '').lower()
    record('recipient_matched', bool(expected) and expected in recipients, 'expected_recipient_missing')
    extra = len([v for v in recipients if v != expected])
    if extra:
        warnings.append('extra_recipients_present')
    checks['recipient_matched']['extra_recipient_count'] = extra
    hits = [name for name, tag in services.items() if tag in text]
    record('service_matched', hits == [expected_service],
           'service_target_mismatch' if services else 'services_not_configured',
           service=expected_service if expected_service in services else None)
    record('purpose', purpose == 'login' and LOGIN.search(text) and not OTHER_PURPOSE.search(text),
           'login_purpose_not_confirmed')
    match = re.fullmatch(pattern, subject)
    route, suffix = match.group(1, 2) if match else (None, None)
    body_routes = set(ROUTE_TOKEN.findall(text))
    if match is None:
        reason = 'subject_route_unparsed'
    elif route not in routes:
        reason = 'route_not_registered'
    elif routes[route] != suffix:
        reason = 'route_suffix_mismatch'
    elif route != expected_route:
        reason = 'route_target_mismatch'
    elif body_routes - {route}:
        reason = 'route_subject_body_conflict'
    else:
        reason = 'route_absent_in_body'
    route_ok = (match is not None and route in routes and routes[route] == suffix
                and route == expected_route and body_routes == {route})
    record('route_subject', route_ok, reason,
           route=expected_route if expected_route in routes else None)
    complete = (len(text) >= 20 and not text.endswith(TRUNCATION_MARKERS)
                and not body.rstrip().endswith(TRUNCATION_MARKERS)
                and not message.get('truncated') and message.get('body_complete') is not False)
    record('body_complete', complete, 'body_incomplete_or_truncated', characters=len(text))
    created = _instant(message.get('created_at'))
    stamps = BODY_TIME.findall(text)
    stated = _instant(stamps[0], body_offset_hours) if len(stamps) == 1 else None
    ttl = max_age
    for found in [*EXPIRY.finditer(text), *EXPIRY_BEFORE.finditer(text)]:
        number, unit = (found.group(1), found.group(2)) if found.group(1) else (found.group(3), found.group(4))
        seconds = (int(number) if len(number) <= 6 else 1_000_000) * (60 if unit.startswith(('分', 'min')) else 1)
        ttl = min(ttl, seconds)
    if created is None:
        record('time', False, 'created_at_missing_or_unparsed')
    elif stated is None:
        record('time', False, 'body_time_missing_or_invalid')
    elif not valid_window:
        record('time', False, 'query_window_missing_or_invalid')
    elif not lower <= created <= upper:
        record('time', False, 'created_at_outside_window')
    elif not lower <= stated <= upper:
        record('time', False, 'body_time_outside_window')
    elif not 0 <= (current - stated).total_seconds() <= ttl:
        record('time', False, 'code_expired_or_future')
    else:
        skew = (created - stated).total_seconds()
        record('time', 0 <= skew <= max_skew, 'created_at_body_time_skew',
               field='body_timestamp+created_at', skew_seconds=skew, ttl_seconds=ttl)
    found = {v for p in CODE_PATTERNS for v in p.findall(text)}
    lead = re.match(r'[0-9]{8,}', text)
    if not found:
        record('code', False, 'code_not_found')
    elif len(found) > 1:
        record('code', False, 'code_ambiguous', candidates=len(found))
    else:
        code = next(iter(found))
        record('code', not (lead and code in lead.group(0)), 'code_matches_sms_port', length=len(code))
    return result()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--data-dir')
    parser.add_argument('--message-json', help='Synthetic test input file; live mail must use stdin memory pipe')
    parser.add_argument('--after', required=True, help='Inclusive lower bound, ISO 8601 with timezone')
    parser.add_argument('--before', required=True, help='Inclusive upper bound, ISO 8601 with timezone')
    parser.add_argument('--service', required=True, help='Target service key from profile')
    parser.add_argument('--route', required=True, help='Target SIM route from profile')
    parser.add_argument('--purpose', required=True, choices=('login',))
    parser.add_argument('--body-offset-hours', type=float, default=8.0)
    parser.add_argument('--max-skew', type=int, default=300)
    parser.add_argument('--max-age', type=int, default=300)
    args = parser.parse_args()
    try:
        settings = load_profile(profile_path(data_directory(args.data_dir), args.profile))
        raw = Path(args.message_json).expanduser().read_text(encoding='utf-8') if args.message_json else sys.stdin.read(MAX_BODY + 100_000)
        message = json.loads(raw)
        report = verify_message(settings, message, after=args.after, before=args.before,
                                expected_service=args.service, expected_route=args.route,
                                purpose=args.purpose, body_offset_hours=args.body_offset_hours,
                                max_skew=args.max_skew, max_age=args.max_age)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        print(json.dumps({'ok': False, 'verdict': 'error', 'reason': 'profile_or_message_invalid'}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
