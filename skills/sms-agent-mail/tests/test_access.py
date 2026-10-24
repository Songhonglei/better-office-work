"""Identity and redaction checks, with no real mail or credentials."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_access as access

class IdentityChecks(unittest.TestCase):
    def reply(self, aliases=None, scopes=None):
        return subprocess.CompletedProcess(['cli', '+me'], 0, json.dumps({'ok': True, 'data': {
            'aliases': aliases if aliases is not None else [{'email': 'fixture@example.invalid'}],
            'scopes': scopes if scopes is not None else ['mail:read']}}), '')

    def test_matching_identity(self):
        with patch.object(access.subprocess, 'run', return_value=self.reply()):
            code, report = access.check_identity('cli', 'fixture@example.invalid')
        self.assertEqual(code, 0)
        self.assertTrue(report['cloud_read_only_scope'])
        self.assertFalse(report['mail_searched_or_read'])

    def test_wrong_identity_stops(self):
        with patch.object(access.subprocess, 'run', return_value=self.reply()):
            code, report = access.check_identity('cli', 'other@example.invalid')
        self.assertEqual(code, 1)
        self.assertEqual(report['reason'], 'mailbox_identity_mismatch')
        self.assertNotIn('aliases', report)

    def test_missing_read_scope(self):
        with patch.object(access.subprocess, 'run', return_value=self.reply(scopes=['mail:send'])):
            code, report = access.check_identity('cli', 'fixture@example.invalid')
        self.assertEqual(code, 1)
        self.assertFalse(report['cloud_read_only_scope'])

    def test_broad_scope_not_cloud_read_only(self):
        with patch.object(access.subprocess, 'run', return_value=self.reply(scopes=['mail:read', 'mail:delete'])):
            code, report = access.check_identity('cli', 'fixture@example.invalid')
        self.assertEqual(code, 0)
        self.assertFalse(report['cloud_read_only_scope'])

    def test_failed_cli_output_is_not_exported(self):
        result = subprocess.CompletedProcess(['cli'], 3, 'SYNTHETIC_PRIVATE_OUTPUT', 'SYNTHETIC_PRIVATE_OUTPUT')
        with patch.object(access.subprocess, 'run', return_value=result):
            code, report = access.check_identity('cli', 'fixture@example.invalid')
        self.assertEqual(code, 2)
        self.assertNotIn('SYNTHETIC', json.dumps(report))

    def test_invalid_contracts(self):
        for text in ['not json', '[]', '{"ok":true,"data":null}',
                     '{"ok":true,"data":{"aliases":[],"scopes":"mail:read"}}']:
            with self.subTest(text=text), patch.object(access.subprocess, 'run',
                    return_value=subprocess.CompletedProcess(['cli'], 0, text, '')):
                code, _ = access.check_identity('cli', 'fixture@example.invalid')
                self.assertEqual(code, 2)

    def test_missing_cli_and_timeout(self):
        for error in [FileNotFoundError(), subprocess.TimeoutExpired('cli', 30)]:
            with self.subTest(error=type(error).__name__), patch.object(access.subprocess, 'run', side_effect=error):
                code, _ = access.check_identity('cli', 'fixture@example.invalid')
                self.assertEqual(code, 2)

    def test_probe_only_invokes_identity_command(self):
        with patch.object(access.subprocess, 'run', return_value=self.reply()) as call:
            access.check_identity('cli', 'fixture@example.invalid')
        self.assertEqual(call.call_args.args[0], ['cli', '+me'])

if __name__ == '__main__':
    unittest.main()
