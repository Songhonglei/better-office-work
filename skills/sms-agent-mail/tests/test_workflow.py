"""Synthetic mailbox, selection and browser contract regression cases."""
from datetime import timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import read_sms as workflow
from browser_handoff import validate_config
from workflow_errors import WorkflowError
import test_message as fixture


def settings():
    return fixture.settings(backend='cli')


def message(**kw):
    return fixture.message(**{'message_id': 'msg_fixture', 'dir': {'dir_id': 1, 'dir_name': 'inbox'}, **kw})


class Source:
    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = []

    def snapshot(self, *args):
        self.calls.append(args)
        return self.rounds.pop(0) if self.rounds else []


class Browser:
    def __init__(self):
        self.events = []

    def prepare(self, *args):
        self.events.append('prepare')

    def request_code(self):
        self.events.append('request')

    def finish(self, code, *, valid_until):
        if code != fixture.CODE:
            raise AssertionError('wrong synthetic code')
        self.events.append('finish')


class Workflows(unittest.TestCase):
    def run_flow(self, source=None, **kw):
        return workflow.run_workflow(settings(), service='baidu', route='SIM2_1218',
            after=kw.pop('after', fixture.AFTER), mailbox=source or Source([message()]),
            clock=kw.pop('clock', lambda: fixture.NOW), wait_seconds=kw.pop('wait_seconds', 0),
            identity_check=kw.pop('identity_check', lambda *_: (0, {})), **kw)

    def test_read_pass_is_not_login_pass(self):
        report = self.run_flow()
        self.assertTrue(report['ok'])
        self.assertFalse(report['login_passed'])
        self.assertEqual(report['code_handoff'], 'manual')
        self.assertEqual(workflow._instant(report['attempt_after']), workflow._instant(fixture.AFTER))
        self.assertNotIn(fixture.CODE, json.dumps(report))

    def test_browser_trigger_and_memory_handoff(self):
        browser = Browser()
        clock = iter([fixture.NOW - timedelta(seconds=20), fixture.NOW, fixture.NOW,
                      fixture.NOW, fixture.NOW])
        report = self.run_flow(browser=browser, after=None, clock=lambda: next(clock))
        self.assertTrue(report['login_passed'], report)
        self.assertEqual(browser.events, ['prepare', 'request', 'finish'])
        self.assertNotIn(fixture.CODE, json.dumps(report))

    def test_identity_failure_never_sends(self):
        browser = Browser()
        report = self.run_flow(browser=browser, identity_check=lambda *_: (1, {}))
        self.assertFalse(report['ok'])
        self.assertEqual(browser.events, [])

    def test_send_uncertain_is_not_retried(self):
        browser = Browser()
        def fail():
            browser.events.append('request')
            raise WorkflowError('browser_send_result_uncertain_do_not_retry')
        browser.request_code = fail
        report = self.run_flow(browser=browser, after=None)
        self.assertTrue(report['send_requested'])
        self.assertEqual(browser.events, ['prepare', 'request'])

    def test_missing_cli_runtime_never_sends(self):
        browser = Browser()
        result = self.run_flow(browser=browser, identity_check=lambda *_: (2, {'reason': 'cli_runtime_not_found'}))
        self.assertEqual(result['blocker'], 'mail_cli_runtime_not_found')
        self.assertEqual(browser.events, [])

    def test_empty_snapshot_stops(self):
        report = self.run_flow(Source([]))
        self.assertEqual(report['blocker'], 'new_sms_not_found_before_deadline')

    def test_expired_attempt_never_searches(self):
        source = Source([])
        report = self.run_flow(source, after='2026-10-24T15:40:00Z')
        self.assertEqual(report['blocker'], 'attempt_time_invalid')
        self.assertEqual(source.calls, [])

    def test_newer_invalid_code_cannot_fall_back_to_older_one(self):
        old = message(body=fixture.BODY.replace('23:52:31', '23:52:25'))
        new = message(body=fixture.BODY.replace(fixture.CODE, '123456789'))
        report = self.run_flow(Source([old, new]))
        self.assertEqual(report['blocker'], 'latest_target_message_blocked')
        self.assertIn('code_not_found', report['message_blockers'])

    def test_same_time_different_codes_block(self):
        report = self.run_flow(Source([message(), message(body=fixture.BODY.replace(fixture.CODE, '223344'))]))
        self.assertEqual(report['blocker'], 'latest_message_conflict')

    def test_duplicate_messages_with_same_code_pass(self):
        self.assertTrue(self.run_flow(Source([message(), message()]))['ok'])

    def test_delayed_prior_attempt_is_ignored(self):
        report = self.run_flow(Source([message(body=fixture.BODY.replace('23:52:31', '23:51:31'))]))
        self.assertEqual(report['blocker'], 'new_sms_not_found_before_deadline')

    def test_incomplete_profile_never_triggers_browser(self):
        browser = Browser()
        config = settings()
        config['trusted_senders'] = []
        report = workflow.run_workflow(config, service='baidu', route='SIM2_1218', after=None,
                                       browser=browser)
        self.assertEqual(report['blocker'], 'profile_rules_incomplete_or_invalid')
        self.assertEqual(browser.events, [])

    def test_unexpected_browser_error_preserves_send_attempt(self):
        browser = Browser()
        browser.request_code = lambda: (_ for _ in ()).throw(RuntimeError('upstream secret'))
        report = self.run_flow(browser=browser, after=None)
        self.assertTrue(report['send_requested'])
        self.assertIn('attempt_after', report)
        self.assertEqual(report['blocker'], 'unexpected_runtime_failure')
        self.assertNotIn('secret', json.dumps(report))

    def test_native_is_explicit_host_fallback(self):
        result = workflow.run_workflow(fixture.settings(), service='baidu', route='SIM2_1218', after=fixture.AFTER)
        self.assertEqual(result['blocker'], 'native_backend_use_host_workflow')

    def test_poll_waits_then_rechecks_frozen_round(self):
        source = Source([], [message()])
        monotonic = iter([0, 0, 1, 1])
        sleeps = []
        report = self.run_flow(source, wait_seconds=5, monotonic=lambda: next(monotonic), sleep=sleeps.append)
        self.assertTrue(report['ok'], report)
        self.assertEqual(len(source.calls), 2)
        self.assertEqual(sleeps, [3])


class MailContracts(unittest.TestCase):
    def source(self):
        import time
        return workflow.CliMailbox(settings(), time.monotonic() + 60)

    def test_all_pages_keep_filters_and_read_each_unique_message_once(self):
        calls = []
        def command(args):
            calls.append(args)
            if args[1] == '+read':
                return message()
            return {'data': [{'message_id': 'msg_fixture'}], 'pagination': {
                'has_more': '--cursor' not in args, 'next_cursor': 'page2'}}
        source = self.source()
        source.command = command
        self.assertEqual(len(source.snapshot('baidu', fixture.AFTER, fixture.BEFORE)), 1)
        self.assertEqual(calls[1][:-2], calls[0])
        self.assertEqual(calls[2], ['message', '+read', '--id', 'msg_fixture'])

    def test_repeated_cursor_never_uses_partial_result(self):
        source = self.source()
        source.command = lambda _: {'data': [], 'pagination': {'has_more': True, 'next_cursor': 'loop'}}
        with self.assertRaisesRegex(WorkflowError, 'mail_pagination_incomplete'):
            source.snapshot('baidu', fixture.AFTER, fixture.BEFORE)

    def test_read_folder_conflict_blocks(self):
        source = self.source()
        source.command = lambda args: ({'data': [{'message_id': 'msg_fixture'}], 'pagination': {'has_more': False}}
                                      if args[1] == '+search' else message(dir='sent'))
        with self.assertRaisesRegex(WorkflowError, 'mail_read_identity_or_folder_mismatch'):
            source.snapshot('baidu', fixture.AFTER, fixture.BEFORE)

    def test_cli_error_does_not_leak_upstream_output(self):
        import subprocess
        with patch.object(workflow.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, fixture.CODE, fixture.CODE)):
            with self.assertRaisesRegex(WorkflowError, 'mail_command_failed_or_oversized') as caught:
                workflow.cli_json('cli', [], 1)
        self.assertNotIn(fixture.CODE, str(caught.exception))

    def test_missing_pagination_is_not_complete(self):
        source = self.source()
        source.command = lambda _: {'data': []}
        with self.assertRaisesRegex(WorkflowError, 'mail_search_contract_invalid'):
            source.snapshot('baidu', fixture.AFTER, fixture.BEFORE)


class BrowserConfig(unittest.TestCase):
    def config(self, **kw):
        value = {'cdp_endpoint': 'http://127.0.0.1:9222', 'login_url': 'https://example.invalid/login',
                 'service': 'baidu', 'route': 'SIM2_1218', 'phone_selector': '#phone',
                 'send_selector': '#send', 'code_selector': '#code', 'submit_selector': '#login',
                 'success_selector': '#account'}
        return {**value, **kw}

    def test_only_explicit_loopback_browser_is_allowed(self):
        self.assertEqual(validate_config(self.config())['timeout_ms'], 10000)
        for endpoint in ('http://example.invalid:9222', 'http://127.0.0.1:9222/?token=secret',
                         'http://u:p@127.0.0.1:9222', 'ws://127.0.0.1:9222/path'):
            with self.subTest(endpoint=endpoint), self.assertRaises(WorkflowError):
                validate_config(self.config(cdp_endpoint=endpoint))

    def test_plaintext_remote_login_is_rejected(self):
        with self.assertRaises(WorkflowError):
            validate_config(self.config(login_url='http://example.invalid/login'))

    def test_unknown_browser_config_keys_are_rejected(self):
        with self.assertRaises(WorkflowError):
            validate_config(self.config(trace_path='secret.zip'))
