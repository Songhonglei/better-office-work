"""Offline checks for the host bridge config validator (no network, no browser)."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'host_bridge'))

from config_check import validate  # noqa: E402


def base_target():
    return {
        'url': 'https://example.com/login',
        'phone': '13800000000',
        'phone_selector': '#phone',
        'send_selector': '#send',
        'code_selector': '#code',
        'submit_selector': '#submit',
        'account_marker': '#account',
    }


def base_config(mail_source='webmail'):
    return {
        'schema': 1,
        'mail_source': mail_source,
        'service': 'baidu',
        'route': 'SIM1_8512',
        'webmail': {'list_url': 'https://agent.qq.com/page/list', 'row_selector': None},
        'imap': {'host': 'imap.qq.com', 'user': 'u@qq.com',
                 'password_file': 'PLACEHOLDER', 'sender': 's@qq.com'},
        'target': base_target(),
    }


class ConfigCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'profiles').mkdir(parents=True)
        secret = self.root / 'imap.secret'
        secret.write_text('dummy', encoding='utf-8')
        secret.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.secret = secret

    def tearDown(self):
        self.tmp.cleanup()

    def test_webmail_minimal_ok(self):
        resolved = validate(base_config(), self.root)
        self.assertEqual(resolved['mail_source'], 'webmail')
        self.assertEqual(resolved['code_wait_seconds'], 240)
        self.assertNotIn('imap', resolved)

    def test_imap_requires_password_file(self):
        cfg = base_config('imap')
        cfg['imap']['password_file'] = ''
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'imap_password_file_missing')

    def test_imap_password_file_permissions_enforced(self):
        cfg = base_config('imap')
        self.secret.chmod(0o644)
        cfg['imap']['password_file'] = str(self.secret)
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'imap_password_file_too_permissive')

    def test_imap_ok_and_never_reads_password(self):
        cfg = base_config('imap')
        cfg['imap']['password_file'] = str(self.secret)
        resolved = validate(cfg, self.root)
        self.assertEqual(resolved['imap']['sender'], 's@qq.com')
        self.assertNotIn('dummy', json.dumps(resolved))

    def test_invalid_mail_source(self):
        cfg = base_config()
        cfg['mail_source'] = 'pop3'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'invalid_mail_source')

    def test_missing_selector_rejected(self):
        cfg = base_config()
        del cfg['target']['code_selector']
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'target_code_selector_missing')

    def test_http_url_rejected(self):
        cfg = base_config()
        cfg['target']['url'] = 'http://example.com/login'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'target_url_not_https')

    def test_wait_window_cannot_exceed_five_minutes(self):
        cfg = base_config()
        cfg['code_wait_seconds'] = 600
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'invalid_code_wait_seconds')

    def test_imap_password_file_not_found_is_distinct(self):
        cfg = base_config('imap')
        cfg['imap']['password_file'] = str(self.root / 'nope.secret')
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'imap_password_file_not_found')

    def test_bool_is_not_accepted_as_wait_seconds(self):
        cfg = base_config()
        cfg['code_wait_seconds'] = True
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'invalid_code_wait_seconds')

    def test_mail_only_does_not_require_target_selectors(self):
        cfg = {
            'schema': 1,
            'mail_source': 'webmail',
            'mail_only': True,
            'service': 'baidu',
            'route': 'SIM1_8512',
            'webmail': {'list_url': 'https://agent.qq.com/page/list'},
        }
        resolved = validate(cfg, self.root)
        self.assertTrue(resolved['mail_only'])
        self.assertIsNone(resolved['target'])

    def test_mail_only_still_validates_mail_source(self):
        cfg = {'schema': 1, 'mail_source': 'imap', 'mail_only': True,
               'service': 'baidu', 'route': 'SIM1_8512'}
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'imap_host_missing')

    def test_service_and_route_are_required(self):
        cfg = base_config()
        cfg.pop('service')
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'service_missing')

        cfg = base_config()
        cfg['route'] = 'SIM9'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'invalid_route')

    def test_short_tail_is_not_a_phone_number(self):
        """phone_routes 的值是四位尾号，不能当完整手机号填入。"""
        cfg = base_config()
        cfg['target']['phone'] = '8512'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'target_phone_not_full_number')

        cfg['target']['phone'] = 'auto'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'target_phone_not_full_number')

    def test_profile_inherits_trusted_sender_for_imap(self):
        profile = {
            'schema': 1, 'expected_email': 'e@agent.qq.com', 'backend': 'native',
            'phone_routes': {'SIM1_8512': '8512'},
            'services': {'baidu': '【百度】'},
            'trusted_senders': ['281568337@qq.com'],
        }
        (self.root / 'profiles' / 'workbuddy.json').write_text(
            json.dumps(profile), encoding='utf-8')
        cfg = base_config('imap')
        cfg['profile'] = 'workbuddy'
        cfg['imap'] = {'host': 'imap.qq.com', 'user': 'u@qq.com',
                       'password_file': str(self.secret)}
        cfg['target']['phone'] = '13800008512'
        resolved = validate(cfg, self.root)
        self.assertEqual(resolved['imap']['sender'], '281568337@qq.com')
        self.assertEqual(resolved['target']['phone'], '13800008512')

    def test_phone_tail_must_match_route(self):
        profile = {
            'schema': 1, 'expected_email': 'e@agent.qq.com', 'backend': 'native',
            'phone_routes': {'SIM1_8512': '8512'},
            'services': {'baidu': '【百度】'},
            'trusted_senders': ['281568337@qq.com'],
        }
        (self.root / 'profiles' / 'workbuddy.json').write_text(
            json.dumps(profile), encoding='utf-8')
        cfg = base_config()
        cfg['profile'] = 'workbuddy'
        cfg['target']['phone'] = '13800001218'  # 尾号与 SIM1_8512 不符
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'target_phone_tail_mismatch')

    def test_regex_fallback_must_be_boolean(self):
        cfg = base_config()
        cfg['webmail']['allow_regex_fallback'] = 'yes'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'webmail_allow_regex_fallback_invalid')

    def test_missing_profile_reported(self):
        cfg = base_config()
        cfg['profile'] = 'nope'
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, self.root)
        self.assertEqual(ctx.exception.args[0], 'profile_not_found')


class BridgeSourceGuardTest(unittest.TestCase):
    """静态守卫：回执不得拼接外部异常/命令输出（可能含验证码）。"""

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        source = (self.root / 'scripts' / 'host_bridge' / 'run.mjs').read_text(encoding='utf-8')
        # 去掉行注释后再扫描，避免注释里提到 stderr 造成误判
        self.code = '\n'.join(line.split('//')[0] for line in source.splitlines())

    def test_no_external_error_text_in_receipt(self):
        for pattern in ('err.message', 'error.message', 'e.message', 'exception.message',
                        'err.stack', 'String(err)'):
            self.assertNotIn(pattern, self.code,
                             f'代码不得读取 {pattern}，可能把验证码带进回执')

    def test_stderr_is_only_discarded(self):
        self.assertEqual(self.code.count('stderr'), 1,
                         'stderr 只允许出现一次（丢弃），其余路径不得引用')
        self.assertIn('child.stderr.on', self.code)

    def test_receipt_uses_fixed_code_whitelist(self):
        self.assertIn('SAFE_CODES', self.code)
        self.assertIn('isSafeCode', self.code)

    def test_no_hardcoded_author_home_path(self):
        self.assertNotIn('/Users/songhonglei', self.code)
        self.assertIn('os.homedir()', self.code)

    def test_every_candidate_goes_through_verifier(self):
        self.assertIn('check_message.py', self.code)
        self.assertIn('gateMessage', self.code)


class InstallManifestTest(unittest.TestCase):
    """新增文件必须进入 install.py 的固定清单，否则升级时会静默丢失。"""

    def test_every_packaged_file_is_listed(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
        import install
        root = Path(__file__).resolve().parent.parent
        packaged = []
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(('.git/', 'runtime/', 'data/')) or '__pycache__' in rel:
                continue
            if rel.endswith(('.pyc', '.DS_Store')):
                continue
            packaged.append(rel)
        missing = sorted(set(packaged) - set(install.FILES))
        self.assertEqual(missing, [], f'未登记到 install.py FILES: {missing}')


if __name__ == '__main__':
    unittest.main()
