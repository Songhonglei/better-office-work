import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mail_config import load_settings, overrides, profile_path, select_profile
from onboard import configure
from qq_mail import CodexMail


class OnboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"QQ_MAIL_HOME": self.temp.name + "/mail", "CODEX_HOME": self.temp.name + "/codex", "QQ_MAIL_PROFILE": "default"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_fresh_install_requires_onboarding(self):
        with self.assertRaisesRegex(RuntimeError, "No mailbox profile"):
            load_settings()

    def test_multiple_profiles_keep_accounts_scopes_and_state_separate(self):
        first = configure("first@qq.com")
        select_profile("work")
        second = configure("second@foxmail.com", "manage")
        self.assertNotEqual(first.server, second.server)
        self.assertNotEqual(first.state_dir, second.state_dir)
        self.assertEqual(first.scopes, ("mail:read",))
        self.assertIn("mail:send", second.scopes)
        self.assertEqual(load_settings(), second)
        self.assertEqual(profile_path().stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, "cannot be rebound"):
            configure("different@qq.com", "manage")

    def test_wrong_primary_alias_is_never_selected(self):
        configure("target@qq.com")
        client = CodexMail()
        client.verify_context({"scopes": ["mail:read"], "aliases": [
            {"email": "primary@qq.com", "alias_id": "wrong", "is_primary": True},
            {"email": "target@qq.com", "alias_id": "correct", "is_primary": False}]})
        self.assertEqual(client.alias_id, "correct")
        with self.assertRaisesRegex(RuntimeError, "configured mailbox"):
            client.verify_context({"scopes": ["mail:read"], "aliases": [{"email": "primary@qq.com", "alias_id": "wrong"}]})

    def test_read_profile_blocks_writes_and_excess_scope(self):
        configure("target@qq.com")
        with self.assertRaisesRegex(RuntimeError, "Read-only"):
            CodexMail(write_tool="SendMessage")
        with self.assertRaisesRegex(RuntimeError, "scopes"):
            CodexMail().verify_context({"scopes": ["mail:read", "mail:send"], "aliases": []})

    def test_child_server_settings_disable_others_without_editing_global_config(self):
        home = Path(os.environ["CODEX_HOME"])
        home.mkdir()
        path = home / "config.toml"
        original = '[mcp_servers.other]\nurl="https://example.com/mcp"\n'
        path.write_text(original)
        settings = configure("target@qq.com")
        arguments = overrides(settings)
        self.assertIn('mcp_servers.other.enabled=false', arguments)
        self.assertIn('mcp_oauth_credentials_store="keyring"', arguments)
        self.assertEqual(path.read_text(), original)
        self.assertNotIn("PermanentDeleteMessage", json.dumps(arguments))

    def test_profile_traversal_and_credential_reuse_are_rejected(self):
        for name in ("../bad", "a.b", "CAPS"):
            with self.assertRaises(ValueError):
                select_profile(name)
        configure("one@qq.com", server="qq-mail")
        select_profile("other")
        with self.assertRaisesRegex(ValueError, "own MCP server"):
            configure("two@qq.com", server="qq-mail")

    def test_reinit_preserves_migrated_server_when_omitted(self):
        configure("one@qq.com", "read", server="existing-qq-mail")
        upgraded = configure("one@qq.com", "manage")
        self.assertEqual(upgraded.server, "existing-qq-mail")
        self.assertEqual(upgraded.mode, "manage")

    def test_malformed_profile_has_actionable_errors(self):
        configure("one@qq.com")
        for data in ({}, [], {"profile": 42}, {"profile": "default", "account": None, "mode": "read", "server": "qq-mail"}):
            profile_path().write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "profile fields"):
                load_settings()
        profile_path().write_text("{")
        with self.assertRaisesRegex(RuntimeError, "repair its JSON"):
            load_settings()

    def test_conflicting_server_auth_never_reaches_oauth_or_profile_save(self):
        home = Path(os.environ["CODEX_HOME"])
        home.mkdir()
        for body in ('url="https://unrelated.example/mcp"',
                     'url="https://api.mail.qq.com/mcp"\nbearer_token_env_var="UNRELATED_TOKEN"',
                     'url="https://api.mail.qq.com/mcp"\nhttp_headers={Authorization="fixture-not-a-secret"}'):
            (home / "config.toml").write_text('[mcp_servers.qq-mail-default]\n' + body + '\n')
            with self.assertRaisesRegex(RuntimeError, "conflicts"):
                configure("one@qq.com")
            self.assertFalse(profile_path().exists())

    def test_runtime_data_cannot_be_placed_inside_skill(self):
        from mail_config import data_home
        skill = Path(__file__).resolve().parents[1]
        with patch.dict(os.environ, {"QQ_MAIL_HOME": str(skill / "private-mail")}):
            with self.assertRaisesRegex(ValueError, "outside the installed skill"):
                data_home()


if __name__ == "__main__":
    unittest.main()
