"""Exercise the deterministic message verifier with synthetic, non-real data."""
import json
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_message as verifier

CODE = '015980'
BODY = ('106809281150240 【百度】验证码：' + CODE +
        '（有效期30分钟）。您正在使用短信验证码登录功能，请勿转发或泄漏。 '
        'SIM2_1218 SubId：9 2026-10-24 23:52:31 song p70')
AFTER = '2026-10-24T15:52:21Z'
BEFORE = '2026-10-24T15:52:45Z'


def settings(**changes):
    value = {'schema': 1, 'expected_email': 'fixture@example.invalid', 'backend': 'native',
             'cli': 'agently-cli', 'verification': 'not_verified',
             'phone_routes': {'SIM1_0001': '0001', 'SIM2_1218': '1218'},
             'subject_pattern': r'^(SIM[1-9]_([0-9]{4}))的短信验证码$',
             'services': {'baidu': '【百度】', 'toutiao': '【今日头条】'},
             'trusted_senders': ['forwarder@example.invalid']}
    value.update(changes)
    return value


def message(**changes):
    value = {'from': {'email': 'forwarder@example.invalid'}, 'subject': 'SIM2_1218的短信验证码',
             'to': [{'email': 'fixture@example.invalid'}], 'body': BODY,
             'body_format': 'HTML', 'created_at': '2026-10-24T15:52:33Z'}
    value.update(changes)
    return value


class MessageVerdicts(unittest.TestCase):
    def check(self, msg=None, **kw):
        return verifier.verify_message(settings(), msg or message(),
                                       after=kw.pop('after', AFTER),
                                       before=kw.pop('before', BEFORE), **kw)

    def test_complete_message_passes(self):
        report = self.check()
        self.assertTrue(report['ok'], report['blockers'])
        self.assertEqual(report['verdict'], 'pass')
        self.assertEqual(report['checks']['service_matched']['service'], 'baidu')
        self.assertEqual(report['checks']['route_subject']['route'], 'SIM2_1218')
        self.assertEqual(report['checks']['time']['skew_seconds'], 2)
        self.assertEqual(report['checks']['code'], {'pass': True, 'length': 6})

    def test_code_is_never_reported(self):
        for report in (self.check(),
                       self.check(message(body=BODY + ' 备用 ' + CODE)),
                       self.check(message(**{'from': {'email': 'stranger@example.invalid'}}))):
            self.assertNotIn(CODE, json.dumps(report, ensure_ascii=False))

    def test_untrusted_sender_blocks(self):
        report = self.check(message(**{'from': {'email': 'stranger@example.invalid'}}))
        self.assertIn('sender_not_trusted', report['blockers'])

    def test_missing_sender_configuration_blocks(self):
        report = verifier.verify_message(settings(trusted_senders=[]), message(),
                                         after=AFTER, before=BEFORE)
        self.assertIn('trusted_senders_not_configured', report['blockers'])

    def test_extra_recipient_is_a_warning_not_a_block(self):
        report = self.check(message(to=[{'email': 'fixture@example.invalid'},
                                        {'email': 'copy@example.invalid'}]))
        self.assertTrue(report['ok'], report['blockers'])
        self.assertIn('extra_recipient:copy@example.invalid', report['warnings'])

    def test_missing_expected_recipient_blocks(self):
        report = self.check(message(to=[{'email': 'copy@example.invalid'}]))
        self.assertIn('expected_recipient_missing', report['blockers'])

    def test_route_suffix_mismatch_blocks(self):
        report = verifier.verify_message(settings(phone_routes={'SIM2_1218': '9999'}),
                                         message(), after=AFTER, before=BEFORE)
        self.assertIn('route_suffix_mismatch', report['blockers'])

    def test_route_not_registered_blocks(self):
        report = self.check(message(subject='SIM3_1218的短信验证码'))
        self.assertIn('route_not_registered', report['blockers'])

    def test_subject_and_body_route_conflict_blocks(self):
        report = self.check(message(body=BODY.replace('SIM2_1218', 'SIM1_0001')))
        self.assertIn('route_subject_body_conflict', report['blockers'])

    def test_route_missing_from_body_blocks(self):
        report = self.check(message(body=BODY.replace('SIM2_1218', '')))
        self.assertIn('route_absent_in_body', report['blockers'])

    def test_unparsed_subject_blocks(self):
        report = self.check(message(subject='您的验证码'))
        self.assertIn('subject_route_unparsed', report['blockers'])

    def test_unknown_service_tag_blocks(self):
        report = self.check(message(body=BODY.replace('【百度】', '【某站】')))
        self.assertIn('service_tag_not_found', report['blockers'])

    def test_unconfigured_services_blocks(self):
        report = verifier.verify_message(settings(services={}), message(),
                                         after=AFTER, before=BEFORE)
        self.assertIn('services_not_configured', report['blockers'])

    def test_ambiguous_code_blocks(self):
        report = self.check(message(body=BODY + ' 备用验证码：778899'))
        self.assertIn('code_ambiguous', report['blockers'])

    def test_missing_code_blocks(self):
        report = self.check(message(body=BODY.replace('验证码：' + CODE, '验证码：稍后发送')))
        self.assertIn('code_not_found', report['blockers'])

    def test_code_taken_from_sms_port_blocks(self):
        report = self.check(message(body='10680928115 【百度】验证码：10680928 '
                                        'SIM2_1218 2026-10-24 23:52:31'))
        self.assertIn('code_matches_sms_port', report['blockers'])

    def test_outside_window_blocks(self):
        report = self.check(after='2026-10-24T15:53:00Z')
        self.assertIn('created_at_outside_window', report['blockers'])

    def test_created_at_without_body_time_is_blocked(self):
        report = self.check(message(body=BODY.replace('2026-10-24 23:52:31', '')))
        self.assertIn('body_time_missing', report['blockers'])
        self.assertTrue(report['checks']['time']['created_at_only'])

    def test_clock_skew_beyond_limit_blocks(self):
        report = self.check(message(body=BODY.replace('2026-10-24 23:52:31',
                                                      '2026-10-24 23:40:00')))
        self.assertIn('created_at_body_time_skew', report['blockers'])

    def test_truncated_body_blocks(self):
        report = self.check(message(body=BODY + '…'))
        self.assertIn('body_incomplete_or_truncated', report['blockers'])

    def test_plain_text_fields_are_accepted(self):
        report = self.check({'from': 'forwarder@example.invalid', 'to': ['fixture@example.invalid'],
                             'subject': 'SIM2_1218的短信验证码', 'body': BODY,
                             'created_at': '2026-10-24T15:52:33Z'})
        self.assertTrue(report['ok'], report['blockers'])

    def test_oversized_body_is_rejected(self):
        report = self.check(message(body='x' * 2_000_001))
        self.assertEqual(report['blockers'], ['message_too_large'])


class CommandBehaviour(unittest.TestCase):
    def test_missing_profile_exits_two(self):
        import subprocess
        result = subprocess.run([sys.executable, str(SCRIPTS / 'check_message.py'),
                                 '--profile', 'absent', '--data-dir',
                                 '/nonexistent-sms-agent-mail-data', '--message-json', '/dev/null'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('profile_missing_or_unreadable', result.stdout)


if __name__ == '__main__':
    unittest.main()
