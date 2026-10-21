"""Explicit broad-credential acceptance never enables delete; synthetic tokens only."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_refresh as fixtures

config, onboard, bridge = fixtures.config, fixtures.onboard, fixtures.bridge
creds = fixtures.creds
import qq_mail_write as flow


class ScopeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = fixtures.RefreshTests()
        self.fixture.setUp()  # Clear environment and use isolated, fake credential/config paths.
        self.settings = self.fixture.changed(credential_source="env", credential_file=None,
            refresh_policy="host", client_auth_method=None)
        self.context = {"scopes": ["mail:read", "mail:send", "mail:delete"],
                        "aliases": [{"email": "target@qq.com", "alias_id": "synthetic-alias"}]}
        binary = self.fixture.root / "bin/codex"
        binary.parent.mkdir()
        binary.write_text(fixtures.FAKE_CODEX)
        binary.chmod(0o700)
        self.events = self.fixture.root / "events"
        os.environ.update(PATH=str(binary.parent) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            QQ_MAIL_ACCESS_TOKEN=fixtures.A, FIXTURE_EVENTS=str(self.events), FIXTURE_CASE="wide",
            FIXTURE_MODE="read_send", FIXTURE_AUTH="env_token")
        self.pacing = patch.object(bridge, "reserve_call_slot", new=AsyncMock())
        self.pacing.start()
        self.save(False)

    def tearDown(self):
        self.pacing.stop()
        self.fixture.tearDown()

    def save(self, enabled):
        self.settings = config.settings_from({**self.settings.as_dict(), "allow_extra_delete_scope": enabled})
        config.write_private(config.profile_path(), self.settings.as_dict())

    def test_default_and_legacy_profile_reject_extra_delete_scope(self):
        data = self.settings.as_dict()
        data.pop("allow_extra_delete_scope")
        legacy = config.settings_from(data)
        self.assertFalse(legacy.allow_extra_delete_scope)
        with self.assertRaisesRegex(RuntimeError, "scopes"):
            bridge.CodexMail().verify_context(self.context)

    def test_explicit_acceptance_keeps_actual_scopes_and_read_send_requests(self):
        self.save(True)
        original = json.loads(json.dumps(self.context))
        mail = bridge.CodexMail()
        mail.verify_context(self.context)
        self.assertEqual(self.context, original)
        self.assertEqual(mail.status["scopes"], original["scopes"])
        self.assertEqual(mail.status["accepted_extra_scopes"], ["mail:delete"])
        self.assertEqual(mail.status["requested_scopes"], ["mail:read", "mail:send"])
        self.assertEqual(mail.settings.mode, "read_send")
        args = config.overrides(mail.settings, mail.allowed_tools)
        self.assertIn('mcp_servers.qq-cloud.scopes=["mail:read", "mail:send"]', args)
        self.assertNotIn("DeleteMessage", json.dumps(args))

    def test_unknown_scopes_still_rejected_with_option(self):
        self.save(True)
        for unknown in ("mail:unknown", "mail:delete:all", "admin", "offline_access"):
            with self.subTest(scope=unknown):
                with self.assertRaisesRegex(RuntimeError, "scopes"):
                    bridge.CodexMail().verify_context({**self.context, "scopes": [*self.context["scopes"], unknown]})

    def test_required_scopes_and_account_still_verified(self):
        self.save(True)
        with self.assertRaisesRegex(RuntimeError, "Required permissions"):
            bridge.CodexMail().verify_context({**self.context, "scopes": ["mail:read", "mail:delete"]})
        with self.assertRaisesRegex(RuntimeError, "configured mailbox"):
            bridge.CodexMail().verify_context({**self.context, "aliases": [{"email": "other@qq.com", "alias_id": "other"}]})

    def test_option_is_strict_boolean_and_read_send_only(self):
        for value in ("true", 1, None, [], {}):
            with self.assertRaisesRegex(ValueError, "boolean"):
                config.settings_from({**self.settings.as_dict(), "allow_extra_delete_scope": value})
        for mode in ("read", "manage"):
            with self.assertRaisesRegex(ValueError, "read_send"):
                config.settings_from({**self.settings.as_dict(), "mode": mode, "allow_extra_delete_scope": True})

    async def test_delete_exposure_construction_and_execution_stay_blocked(self):
        self.save(True)
        with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
            bridge.CodexMail(write_tool="DeleteMessage")
        with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
            config.overrides(self.settings, (*config.READ_TOOLS, "DeleteMessage"))
        with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
            await flow.prepare("DeleteMessage", {"message_id": "synthetic-message"})
        mail = bridge.CodexMail()
        mail.verify_context(self.context)
        # The execution guard remains effective even if a caller corrupts its local tool list.
        mail.allowed_tools += ("DeleteMessage",)
        mail.rpc = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
            await mail.raw_call("DeleteMessage", {"alias_id": mail.alias_id, "message_id": "synthetic-message"})
        mail.rpc.assert_not_called()
        self.assertFalse(self.events.exists())

    async def test_broad_credential_can_read_and_send_but_never_delete(self):
        self.save(True)
        async with bridge.CodexMail() as mail:
            result = await mail.call("ListMessages", {"alias_id": mail.alias_id})
            self.assertEqual(result["data"], [])
            with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
                await mail.raw_call("DeleteMessage", {"alias_id": mail.alias_id, "message_id": "synthetic-message"})
        result = await flow.execute_authorized("SendMessage", {"to": [{"email": "recipient@example.com"}],
            "subject": "synthetic", "body": "synthetic"}, user_authorized=True)
        self.assertEqual(result["state"], "completed")
        events = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual(sum(item.get("tool") == "SendMessage" for item in events), 1)
        self.assertFalse(any(item.get("tool") == "DeleteMessage" for item in events))
        self.assertTrue(json.loads(config.profile_path().read_text())["allow_extra_delete_scope"])

    def test_cli_enable_preserve_doctor_and_explicit_disable(self):
        script = Path(onboard.__file__)
        base = [sys.executable, str(script), "--profile", "cloud", "init", "--account", "target@qq.com", "--mode", "read_send"]
        result = subprocess.run([*base, "--allow-extra-delete-scope"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["state"], "verified")
        self.assertEqual(data["scopes"], self.context["scopes"])
        self.assertEqual(data["requested_scopes"], ["mail:read", "mail:send"])
        self.assertTrue(onboard.configure("target@qq.com", "read_send").allow_extra_delete_scope)
        self.assertTrue(onboard.doctor()["allow_extra_delete_scope"])
        result = subprocess.run([*base, "--no-allow-extra-delete-scope", "--configure-only"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(config.load_settings().allow_extra_delete_scope)
        with self.assertRaisesRegex(RuntimeError, "scopes"):
            bridge.CodexMail().verify_context(self.context)

    async def test_refresh_keeps_original_broad_scope_metadata(self):
        settings = config.settings_from({**self.fixture.settings.as_dict(), "allow_extra_delete_scope": True})
        bundle = {**self.fixture.bundle, "scope": "mail:read mail:send mail:delete"}
        self.fixture.save(bundle)
        config.write_private(config.profile_path(), settings.as_dict())
        with patch.object(creds, "exchange", return_value=self.fixture.reply) as exchange:
            async with bridge.CodexMail() as mail:
                self.assertEqual(mail.status["scopes"], self.context["scopes"])
                self.assertEqual(mail.settings.scopes, ("mail:read", "mail:send"))
            exchange.assert_called_once()
        self.assertEqual(self.fixture.load()["scope"], bundle["scope"])
        self.assertNotIn("DeleteMessage", json.dumps(config.overrides(settings)))


if __name__ == "__main__":
    unittest.main()
