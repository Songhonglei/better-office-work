"""Bounded, read-only SMS mailbox workflow with optional in-memory login handoff."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import time

from check_access import check_identity
from check_message import BODY_TIME, _instant, _text, extract_code, verify_message
from onboard import (data_directory, load_profile, profile_path, _valid_routes,
                     _valid_services, _valid_senders, _valid_subject_pattern)
from workflow_errors import WorkflowError

VERSION = '1.5.3'
MAX_PAGES, MAX_MESSAGES, MAX_OUTPUT = 20, 100, 3_000_000


def cli_json(cli: str, args: list[str], timeout: float) -> dict:
    try:
        result = subprocess.run([cli, *args], capture_output=True, text=True,
                                timeout=max(0.1, timeout), check=False)
        if result.returncode or len(result.stdout) > MAX_OUTPUT:
            raise WorkflowError('mail_command_failed_or_oversized')
        envelope = json.loads(result.stdout)
        if not isinstance(envelope, dict) or envelope.get('ok') is not True or not isinstance(envelope.get('data'), dict):
            raise WorkflowError('mail_response_contract_invalid')
        return envelope['data']
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired, RecursionError):
        raise WorkflowError('mail_command_unavailable_or_invalid') from None


class CliMailbox:
    def __init__(self, settings: dict, deadline: float):
        self.settings, self.deadline = settings, deadline

    def command(self, args: list[str]) -> dict:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise WorkflowError('mail_deadline_reached')
        return cli_json(self.settings['cli'], args, min(15.0, remaining))

    def snapshot(self, service: str, after: str, before: str) -> list[dict]:
        """Exhaust a frozen search window before reading unique message bodies."""
        common = ['message', '+search', '--q', self.settings['services'][service],
                  '--search-in', 'SEARCH_IN_CONTENT', '--to', self.settings['expected_email'],
                  '--dir', 'inbox', '--after', after, '--before', before, '--limit', '50']
        cursor, cursors, identifiers = None, set(), set()
        for _ in range(MAX_PAGES):
            page = self.command(common + (['--cursor', cursor] if cursor else []))
            rows, pagination = page.get('data'), page.get('pagination')
            if not isinstance(rows, list) or not isinstance(pagination, dict):
                raise WorkflowError('mail_search_contract_invalid')
            for row in rows:
                mid = row.get('message_id') if isinstance(row, dict) else None
                if not isinstance(mid, str) or not mid.startswith('msg_') or len(mid) > 256:
                    raise WorkflowError('mail_message_id_invalid')
                identifiers.add(mid)
            if len(identifiers) > MAX_MESSAGES:
                raise WorkflowError('mail_candidate_limit')
            if pagination.get('has_more') is False:
                break
            cursor = pagination.get('next_cursor')
            if pagination.get('has_more') is not True or not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in cursors:
                raise WorkflowError('mail_pagination_incomplete')
            cursors.add(cursor)
        else:
            raise WorkflowError('mail_page_limit')
        messages = []
        for mid in sorted(identifiers):
            mail = self.command(['message', '+read', '--id', mid])
            folder = mail.get('dir')
            inbox = (folder == 'inbox' or (isinstance(folder, dict)
                     and folder.get('dir_id') == 1 and folder.get('dir_name') == 'inbox'))
            if mail.get('message_id') != mid or not inbox:
                raise WorkflowError('mail_read_identity_or_folder_mismatch')
            if not isinstance(mail.get('body'), str) or mail.get('truncated') or mail.get('body_complete') is False:
                raise WorkflowError('mail_body_incomplete')
            messages.append(mail)
        return messages


def select_message(settings, messages, *, service, route, after, before, now,
                   body_offset_hours=8.0):
    """Select latest original SMS, reject same-time conflicts and newer invalid candidates."""
    evaluated = []
    for message in messages:
        verdict = verify_message(settings, message, after=after, before=before,
                                 expected_service=service, expected_route=route, purpose='login',
                                 now=now, body_offset_hours=body_offset_hours)
        checks = verdict['checks']
        relevant = all(checks.get(name, {}).get('pass') for name in
                       ('sender_trusted', 'recipient_matched', 'service_matched', 'route_subject', 'purpose'))
        if not relevant:
            continue
        stamps = BODY_TIME.findall(_text(message['body']))
        stamp = _instant(stamps[0], body_offset_hours) if len(stamps) == 1 else None
        if stamp is None:
            raise WorkflowError('target_message_time_invalid')
        # Old messages outside this attempt are irrelevant, even if delivery was delayed.
        if stamp < _instant(after):
            continue
        evaluated.append((stamp, message, verdict))
    if not evaluated:
        return None
    latest_time = max(entry[0] for entry in evaluated)
    latest = [entry for entry in evaluated if entry[0] == latest_time]
    if any(not entry[2]['ok'] for entry in latest):
        raise WorkflowError('latest_target_message_blocked', blockers=[
            reason for entry in latest for reason in entry[2]['blockers']])
    codes = {extract_code(entry[1]['body']) for entry in latest}
    if None in codes or len(codes) != 1:
        raise WorkflowError('latest_message_conflict')
    return latest[0][1], latest[0][2]


def run_workflow(settings: dict, *, service: str, route: str, after: str | None,
                 wait_seconds: float = 180, interval: float = 3, body_offset_hours: float = 8,
                 browser=None, mailbox=None, clock=None, monotonic=None, sleep=None,
                 identity_check=None, progress=None) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    monotonic, sleep = monotonic or time.monotonic, sleep or time.sleep
    identity_check = identity_check or check_identity
    report = {'skill_version': VERSION, 'ok': False, 'identity_matched': False,
              'new_sms_full_body_read': False, 'pagination_complete': False,
              'message_verdict': 'not_run', 'login_passed': False,
              'code_handoff': 'none', 'send_requested': False, 'polls': 0}
    try:
        if settings.get('backend') != 'cli':
            raise WorkflowError('native_backend_use_host_workflow')
        if (service not in (settings.get('services') or {}) or route not in (settings.get('phone_routes') or {})
                or not 0 <= wait_seconds <= 240 or not 0.1 <= interval <= 30
                or not -23 < body_offset_hours < 23):
            raise WorkflowError('target_or_poll_policy_invalid')
        if not (_valid_routes(settings.get('phone_routes')) and _valid_services(settings.get('services'))
                and _valid_senders(settings.get('trusted_senders')) and settings.get('trusted_senders')
                and _valid_subject_pattern(settings.get('subject_pattern'))):
            raise WorkflowError('profile_rules_incomplete_or_invalid')
        code, identity = identity_check(settings['cli'], settings['expected_email'])
        if code:
            reason = 'mail_cli_runtime_not_found' if identity.get('reason') == 'cli_runtime_not_found' else 'mail_identity_not_verified'
            raise WorkflowError(reason)
        report['identity_matched'] = True
        if browser is not None:
            browser.prepare(service, route, settings['phone_routes'][route])
            # Timestamp and the only send click happen in this same process.
            after = clock().replace(microsecond=0).isoformat()
            report['attempt_after'] = after
            report['send_requested'] = True  # click may have reached site even if it times out
            browser.request_code()
        start = _instant(after)
        current = clock()
        if start is None or not 0 <= (current - start).total_seconds() <= 300:
            raise WorkflowError('attempt_time_invalid')
        report['attempt_after'] = start.isoformat()
        deadline = monotonic() + min(wait_seconds, 300 - (current - start).total_seconds())
        source = mailbox or CliMailbox(settings, deadline if wait_seconds else monotonic() + 15)
        progress_at = monotonic() if progress else None
        while True:
            if report['polls'] and monotonic() >= deadline:
                raise WorkflowError('new_sms_not_found_before_deadline')
            now = clock()
            if (now - start).total_seconds() > 300:
                raise WorkflowError('attempt_expired')
            before = now.isoformat()
            messages = source.snapshot(service, after, before)
            report['polls'] += 1
            report['pagination_complete'] = True
            report['new_sms_full_body_read'] = bool(messages)
            selected = select_message(settings, messages, service=service, route=route,
                                      after=after, before=before, now=clock(),
                                      body_offset_hours=body_offset_hours)
            if selected is not None:
                message, verdict = selected
                report.update(message_verdict='pass', code_length=verdict['checks']['code']['length'],
                              warnings=verdict['warnings'])
                if browser is None:
                    report.update(ok=True, state='message_verified', code_handoff='manual',
                                  next_step='user_enters_code_or_run_login_with_browser_config')
                    return report
                # Recheck expiry immediately before crossing into browser memory.
                current = clock()
                fresh = verify_message(settings, message, after=after, before=current.isoformat(),
                                       expected_service=service, expected_route=route, purpose='login',
                                       now=current, body_offset_hours=body_offset_hours)
                if not fresh['ok']:
                    raise WorkflowError('code_expired_before_handoff')
                report['code_handoff'] = 'browser_memory'
                stamp = _instant(BODY_TIME.findall(_text(message['body']))[0], body_offset_hours)
                valid_until = stamp + timedelta(seconds=fresh['checks']['time']['ttl_seconds'])
                browser.finish(extract_code(message['body']), valid_until=valid_until)
                report.update(ok=True, state='login_verified', login_passed=True)
                return report
            if progress and monotonic() - progress_at >= 30:
                progress({'state': 'waiting_for_sms', 'polls': report['polls'],
                          'send_requested': report['send_requested']})
                progress_at = monotonic()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise WorkflowError('new_sms_not_found_before_deadline')
            sleep(min(interval, remaining))
    except WorkflowError as error:
        # Our exceptions contain fixed reason identifiers only; upstream exceptions are wrapped.
        report.update(state='blocked', blocker=error.args[0])
        if error.blockers:
            report['message_blockers'] = error.blockers
        return report
    except Exception:
        report.update(state='blocked', blocker='unexpected_runtime_failure')
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'login'))
    parser.add_argument('--profile', required=True)
    parser.add_argument('--data-dir')
    parser.add_argument('--service', required=True)
    parser.add_argument('--route', required=True)
    parser.add_argument('--after', help='read: timestamp recorded before this attempt sent its SMS')
    parser.add_argument('--wait-seconds', type=float, default=180)
    parser.add_argument('--interval', type=float, default=3)
    parser.add_argument('--body-offset-hours', type=float, default=8)
    parser.add_argument('--browser-config', help='login: private external JSON configuration')
    args = parser.parse_args()
    if (args.action == 'read' and (not args.after or args.browser_config)) or (
            args.action == 'login' and (not args.browser_config or args.after)):
        parser.error('read requires --after; login requires --browser-config and records its own after')
    browser = None
    try:
        settings = load_profile(profile_path(data_directory(args.data_dir), args.profile))
        if args.action == 'login':
            from browser_handoff import BrowserSession, load_browser_config
            browser = BrowserSession(load_browser_config(args.browser_config))
        report = run_workflow(settings, service=args.service, route=args.route, after=args.after,
                              wait_seconds=args.wait_seconds, interval=args.interval,
                              body_offset_hours=args.body_offset_hours, browser=browser,
                              progress=lambda item: print(json.dumps(item), file=sys.stderr, flush=True))
    except (OSError, ValueError, TypeError, RecursionError, WorkflowError):
        report = {'ok': False, 'state': 'blocked', 'blocker': 'configuration_or_runtime_invalid'}
    except Exception:
        # Provider/browser exceptions can contain mail contents or locators. Never print them.
        report = {'ok': False, 'state': 'blocked', 'blocker': 'unexpected_runtime_failure'}
    finally:
        if browser is not None:
            browser.disconnect()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
