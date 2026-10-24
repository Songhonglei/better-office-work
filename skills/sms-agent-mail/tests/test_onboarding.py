"""Exercise private onboarding state and upgrade boundaries with synthetic data."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import onboard
spec = importlib.util.spec_from_file_location('sms_skill_installer', SCRIPTS / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SkillOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / 'private-data'

    def init(self, **kw):
        return onboard.init_profile(self.data, 'codex', 'fixture@example.invalid', **kw)

    def test_private_state_and_idempotent_init_preserve_custom_settings(self):
        self.init()
        path = onboard.profile_path(self.data, 'codex')
        settings = json.loads(path.read_text())
        settings['custom_routes'] = {'SIM2_1234': '1234'}
        onboard.write_json(path, settings)
        before = path.read_bytes()
        self.assertEqual(self.init()['state'], 'existing_profile_preserved')
        self.assertEqual(path.read_bytes(), before)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_conflicting_identity_not_overwritten(self):
        self.init()
        path = onboard.profile_path(self.data, 'codex')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            onboard.init_profile(self.data, 'codex', 'other@example.invalid')
        self.assertEqual(path.read_bytes(), before)

    def test_new_profile_requires_explicit_email(self):
        with self.assertRaisesRegex(ValueError, 'initial_email_required'):
            onboard.init_profile(self.data, 'codex', None)
        self.assertFalse(self.data.exists())

    def test_existing_email_and_custom_config_survive_reinit_without_email(self):
        self.init(routes={'SIM2_1234':'1234'}, trusted_senders=['sender@example.invalid'])
        path = onboard.profile_path(self.data, 'codex')
        before = path.read_bytes()
        onboard.init_profile(self.data, 'codex', None)
        self.assertEqual(path.read_bytes(), before)

    def test_custom_agent_profile_and_explicit_routes(self):
        onboard.init_profile(self.data, 'other-agent', 'fixture@example.invalid',
                             routes={'SIM2_1234':'1234'}, trusted_senders=['sender@example.invalid'])
        profile = onboard.load_profile(self.data / 'profiles/other-agent.json')
        self.assertEqual(profile['phone_routes'], {'SIM2_1234':'1234'})
        self.assertEqual(profile['trusted_senders'], ['sender@example.invalid'])

    def test_conflicting_routes_do_not_overwrite(self):
        self.init(routes={'SIM2_1234':'1234'})
        path = self.data / 'profiles/codex.json'
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.init(routes={'SIM1_5678':'5678'})
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_route_or_sender_rejected_before_writing(self):
        for values in ({'routes':{'SIM2_1234':'5678'}}, {'routes':{'../unsafe':'1234'}},
                       {'trusted_senders':['not an address']}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.init(**values)
        self.assertFalse(self.data.exists())

    def test_skill_data_overlap_rejected(self):
        with self.assertRaises(ValueError):
            onboard.data_directory(onboard.SKILL_ROOT / 'credentials')

    def test_onboard_cannot_write_into_provider_credential_storage(self):
        with self.assertRaises(ValueError):
            onboard.data_directory(Path.home() / 'Library/Application Support/agently-cli/profiles')

    def test_profile_traversal_and_symlink_rejected(self):
        self.init()
        with self.assertRaises(ValueError):
            onboard.profile_path(self.data, '../outside')
        path = self.data / 'profiles/workbuddy.json'
        path.symlink_to(self.data / 'profiles/codex.json')
        with self.assertRaises(ValueError):
            onboard.load_profile(path)

    def test_native_backend_never_invokes_cli(self):
        self.init(backend='native')
        with patch.object(onboard, 'check_identity') as identity:
            status, report = onboard.verify_profile(self.data, 'codex')
        identity.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(report['storage']['oauth_storage_owner'], 'Host native mail connector')

    def test_cli_verify_only_updates_settings_not_provider_credentials(self):
        self.init()
        secret = self.root / 'provider-token.enc'
        secret.write_bytes(b'synthetic-encrypted-fixture')
        before = secret.read_bytes()
        with patch.object(onboard, 'check_identity', return_value=(0, {'ok': True})), \
             patch.object(onboard, 'local_workspace', return_value='codex'):
            status, report = onboard.verify_profile(self.data, 'codex')
        self.assertEqual(status, 0)
        self.assertEqual(secret.read_bytes(), before)
        self.assertEqual(onboard.load_profile(self.data / 'profiles/codex.json')['verification'], 'identity_verified')
        self.assertFalse(report['storage']['oauth_relocated_or_exported'])

    def test_wrong_identity_does_not_request_credential_overwrite(self):
        self.init()
        with patch.object(onboard, 'check_identity', return_value=(1, {'ok': False, 'reason': 'mailbox_identity_mismatch'})), \
             patch.object(onboard, 'local_workspace', return_value='codex'):
            status, report = onboard.verify_profile(self.data, 'codex')
        self.assertEqual(status, 1)
        self.assertEqual(report['authorization_next_step'], 'identity_mismatch_stop_do_not_overwrite')

    def test_upgrade_preserves_profiles_provider_files_and_unknown_target_files(self):
        self.init()
        profile = self.data / 'profiles/codex.json'
        provider = self.root / 'provider-credentials'
        provider.mkdir()
        token = provider / 'bootstrap_token.enc'
        token.write_bytes(b'synthetic-encrypted-fixture')
        target = self.root / 'user-skills/sms-agent-mail'
        installer.install_skill(onboard.SKILL_ROOT, target, [self.data, provider])
        extra = target / 'user-note.txt'
        extra.write_text('preserve existing file')
        before = profile.read_bytes(), token.read_bytes(), extra.read_bytes()
        installer.install_skill(onboard.SKILL_ROOT, target, [self.data, provider])
        self.assertEqual((profile.read_bytes(), token.read_bytes(), extra.read_bytes()), before)
        self.assertFalse((target / 'profiles').exists())

    def test_upgrade_rejects_credential_directory_target(self):
        protected = self.root / 'private'
        with self.assertRaises(ValueError):
            installer.install_skill(onboard.SKILL_ROOT, protected / 'sms-agent-mail', [protected])

    def test_installer_does_not_package_unknown_secret_or_follow_resource_symlink(self):
        source = self.root / 'package'
        shutil.copytree(onboard.SKILL_ROOT, source, ignore=shutil.ignore_patterns('__pycache__'))
        (source / 'credential.token').write_bytes(b'synthetic-token-never-copy')
        target = self.root / 'skills/sms-agent-mail'
        installer.install_skill(source, target, [self.data])
        self.assertFalse((target / 'credential.token').exists())
        original = source / 'scripts/check_access.py'
        original.unlink()
        original.symlink_to(SCRIPTS / 'check_access.py')
        with self.assertRaises(ValueError):
            installer.install_skill(source, target, [self.data])

    def test_workspace_path_traversal_not_reported_as_oauth_path(self):
        report = onboard.storage_paths(self.data, 'codex', workspace='../../outside')
        self.assertIsNone(report['workspace'])
        self.assertIsNone(report['oauth_file'])

    def test_custom_services_and_subject_pattern_are_stored(self):
        report = onboard.init_profile(self.data, 'codex', 'fixture@example.invalid',
                                      routes={'SIM2_1218': '1218'},
                                      trusted_senders=['forwarder@example.invalid'],
                                      services={'zhihu': '【知乎】'},
                                      subject_pattern=r'^(SIM[1-9]_([0-9]{4}))\s*验证码$')
        self.assertEqual(report['state'], 'configured_not_verified')
        settings = json.loads(onboard.profile_path(self.data, 'codex').read_text())
        self.assertEqual(settings['services'], {'zhihu': '【知乎】'})
        self.assertEqual(settings['subject_pattern'], r'^(SIM[1-9]_([0-9]{4}))\s*验证码$')

    def test_invalid_service_or_pattern_rejected_before_writing(self):
        for kwargs in ({'services': {'Zhihu!': '【知乎】'}},
                       {'services': {'zhihu': '  【知乎】'}},
                       {'services': {'zhihu': ''}},
                       {'subject_pattern': r'no-groups-here'},
                       {'subject_pattern': r'(unclosed'}):
            with self.assertRaises(ValueError):
                onboard.init_profile(self.data, 'codex', 'fixture@example.invalid', **kwargs)
        self.assertFalse(onboard.profile_path(self.data, 'codex').exists())

    def test_set_rules_keeps_identity_and_writes_private_copy(self):
        onboard.init_profile(self.data, 'codex', 'fixture@example.invalid',
                             routes={'SIM2_1218': '1218'}, trusted_senders=['A@Example.Invalid'],
                             services={'baidu': '【百度】'})
        path = onboard.profile_path(self.data, 'codex')
        before = json.loads(path.read_text())
        report = onboard.set_rules(self.data, 'codex',
                                   services={'baidu': '【百度】', 'zhihu': '【知乎】'},
                                   routes={'SIM1_0001': '0001', 'SIM2_1218': '1218'})
        after = json.loads(path.read_text())
        self.assertEqual(report['changed'], ['phone_routes', 'services'])
        self.assertEqual(after['expected_email'], before['expected_email'])
        self.assertEqual(after['backend'], before['backend'])
        self.assertEqual(after['trusted_senders'], before['trusted_senders'])
        self.assertEqual(after['services']['zhihu'], '【知乎】')
        backup = path.with_suffix('.json.bak')
        self.assertEqual(json.loads(backup.read_text()), before)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_set_rules_rejects_empty_call_and_bad_values(self):
        onboard.init_profile(self.data, 'codex', 'fixture@example.invalid')
        with self.assertRaises(ValueError):
            onboard.set_rules(self.data, 'codex')
        with self.assertRaises(ValueError):
            onboard.set_rules(self.data, 'codex', trusted_senders=['not-an-address'])
        with self.assertRaises(ValueError):
            onboard.set_rules(self.data, 'codex', services={'bad key': '【X】'})

    def test_confirm_only_records_native_host_checks(self):
        onboard.init_profile(self.data, 'codex', 'fixture@example.invalid')
        with self.assertRaises(ValueError):
            onboard.confirm_identity(self.data, 'codex', 'host tool reported a match')
        onboard.init_profile(self.data, 'native', 'fixture@example.invalid', backend='native')
        with self.assertRaises(ValueError):
            onboard.confirm_identity(self.data, 'native', 'short')
        with self.assertRaises(ValueError):
            onboard.confirm_identity(self.data, 'native', 'line\nbreak evidence')
        report = onboard.confirm_identity(self.data, 'native', 'host GetMe matched alias')
        self.assertEqual(report['state'], 'identity_verified_by_host')
        settings = json.loads(onboard.profile_path(self.data, 'native').read_text())
        self.assertEqual(settings['verification'], 'identity_verified_by_host')
        self.assertEqual(settings['host_evidence'], 'host GetMe matched alias')


if __name__ == '__main__':
    unittest.main()
