"""All credentials and MCP responses here are synthetic; no real mail is contacted."""
import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mail_config as config
import onboard
import qq_mail as bridge
import qq_mail_write as flow

TOKEN = "synthetic-qq-mcp-access-token-DO-NOT-USE"
OTHER_TOKEN = "synthetic-other-profile-token-DO-NOT-USE"
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
name = os.environ.get("FIXTURE_TOKEN_NAME", "QQ_MAIL_ACCESS_TOKEN")
secret = os.environ.get(name, "")
other = os.environ.get("OTHER_QQ_TOKEN", "")
case = os.environ.get("FIXTURE_CASE", "ok")
def event(kind, **values):
    with Path(os.environ["FIXTURE_EVENTS"]).open("a") as f:
        f.write(json.dumps({"kind":kind, **values})+"\n")
if args == ["--version"] or args[:2] == ["app-server", "--help"]:
    assert not secret and not other, "Credential reached an unrelated helper"
    event("helper")
    print("codex-cli fixture" if args == ["--version"] else "--listen stdio://")
elif args[:2] == ["mcp", "login"]:
    assert os.environ.get("FIXTURE_AUTH") == "oauth_keyring", "Unexpected OAuth/keyring access"
    assert not secret and not other
    event("oauth")
elif args[:1] == ["app-server"]:
    auth = os.environ.get("FIXTURE_AUTH", "env_token")
    if auth == "env_token":
        assert secret and not other
        assert any('.bearer_token_env_var='+json.dumps(name) in a for a in args)
        assert not any('mcp_oauth_credentials_store=' in a for a in args)
        assert 'cli_auth_credentials_store="ephemeral"' in args
        assert secret not in json.dumps(args)
    else:
        assert not secret and not other
        assert 'mcp_oauth_credentials_store="keyring"' in args
    event("app", token_present=bool(secret), other_present=bool(other))
    for line in sys.stdin:
        assert not secret or secret not in line, "Token leaked into RPC arguments"
        msg=json.loads(line)
        if "id" not in msg: continue
        method=msg["method"]
        if method == "initialize": result={}
        elif method == "thread/start": result={"thread":{"id":"fixture-thread"}}
        elif method == "mcpServer/tool/call":
            tool=msg["params"]["tool"]
            event("tool", tool=tool)
            if case == "rpc401":
                print(json.dumps({"id":msg["id"],"error":{"message":"HTTP 401 Bearer "+secret}}),flush=True)
                continue
            fail = case in ("401", "expired", "revoked") or (case == "send401" and tool == "SendMessage")
            if fail:
                result={"isError":True,"structuredContent":{"error":{"code":401,"message":case+" token "+secret}}}
            elif tool == "GetMe":
                scopes=["mail:read", "mail:send"] if os.environ.get("FIXTURE_MODE", "read_send") == "read_send" else ["mail:read"]
                if case == "missing": scopes=["mail:read"]
                if case == "wide": scopes += ["mail:delete"]
                account="wrong@qq.com" if case == "wrong" else "target@qq.com"
                result={"structuredContent":{"scopes":scopes,"aliases":[{"email":account,"alias_id":"fixture-alias","is_primary":False}],"_hints":{"echo":secret}}}
            elif tool == "SendMessage":
                if case == "send_timeout": sys.exit(0)
                result={"structuredContent":{"queued":True,"_hints":{"echo":secret}}}
            else:
                result={"structuredContent":{"data":[],"pagination":{"has_more":False},"_hints":{"echo":secret}}}
        else: raise AssertionError(method)
        print(json.dumps({"id":msg["id"],"result":result}),flush=True)
else: raise AssertionError(args)
'''


class EnvAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qq-env-test-")
        self.root = Path(self.temp.name)
        binary = self.root / "bin/codex"
        binary.parent.mkdir()
        binary.write_text(FAKE_CODEX)
        binary.chmod(0o700)
        self.events = self.root / "events.jsonl"
        self.env = patch.dict(os.environ, {
            "CODEX_HOME": str(self.root / "codex"), "QQ_MAIL_HOME": str(self.root / "mail"), "QQ_MAIL_PROFILE": "cloud",
            "QQ_MAIL_ACCESS_TOKEN": TOKEN, "OTHER_QQ_TOKEN": OTHER_TOKEN,
            "FIXTURE_EVENTS": str(self.events), "FIXTURE_AUTH": "env_token", "FIXTURE_MODE": "read_send", "FIXTURE_CASE": "ok",
            "FIXTURE_TOKEN_NAME": "QQ_MAIL_ACCESS_TOKEN", "PATH": str(binary.parent) + os.pathsep + os.environ.get("PATH", "")})
        self.env.start()
        config.validate_token_env_var("OTHER_QQ_TOKEN")
        config.select_profile("other")
        onboard.configure("other@qq.com", "read", auth_mode="env_token", token_env_var="OTHER_QQ_TOKEN")
        config.select_profile("cloud")
        self.pacing = patch.object(bridge, "reserve_call_slot", new=AsyncMock())
        self.pacing.start()
        self.arguments = {"to": [{"email": "recipient@example.com"}], "subject": "fixture", "body": "fixture body"}

    def tearDown(self):
        self.pacing.stop()
        self.env.stop()
        self.temp.cleanup()

    def configure(self, mode="read_send", **kwargs):
        return onboard.configure("target@qq.com", mode, auth_mode="env_token", **kwargs)

    def events_read(self):
        return [json.loads(s) for s in self.events.read_text().splitlines()] if self.events.exists() else []

    def assert_no_secret_files(self):
        for path in self.root.rglob("*"):
            if path.is_file() and path.name != "codex":
                self.assertNotIn(TOKEN, path.read_text(), str(path))
                self.assertNotIn(OTHER_TOKEN, path.read_text(), str(path))

    def test_legacy_profile_defaults_to_original_oauth(self):
        legacy = {"version": 1, "profile": "cloud", "account": "target@qq.com", "server": "qq-mail-cloud", "mode": "read"}
        config.write_private(config.profile_path(), legacy)
        settings = config.load_settings()
        self.assertEqual(settings.auth_mode, "oauth_keyring")
        self.assertIsNone(settings.token_env_var)
        self.assertIn('mcp_oauth_credentials_store="keyring"', config.overrides(settings))

    def test_variable_names_and_value_only_in_mcp_environment(self):
        settings = self.configure()
        args = config.overrides(settings)
        self.assertIn('mcp_servers.qq-mail-cloud.bearer_token_env_var="QQ_MAIL_ACCESS_TOKEN"', args)
        self.assertNotIn(TOKEN, json.dumps(args))
        self.assertNotIn("QQ_MAIL_ACCESS_TOKEN", config.subprocess_env(settings))
        actual = config.subprocess_env(settings, for_mcp=True)
        self.assertEqual(actual["QQ_MAIL_ACCESS_TOKEN"], TOKEN)
        self.assertNotIn("OTHER_QQ_TOKEN", actual)
        self.assertEqual(json.loads(config.profile_path().read_text())["token_env_var"], "QQ_MAIL_ACCESS_TOKEN")
        self.assert_no_secret_files()

    async def test_missing_or_empty_variable_fails_before_child_start(self):
        self.configure()
        for value in (None, "", "   ", "bad\nheader"):
            if value is None: os.environ.pop("QQ_MAIL_ACCESS_TOKEN", None)
            else: os.environ["QQ_MAIL_ACCESS_TOKEN"] = value
            with self.assertRaisesRegex(RuntimeError, "missing, empty or invalid"):
                async with bridge.CodexMail(): pass
        self.assertFalse(self.events.exists())

    def test_illegal_variable_names_fail_without_recording_values(self):
        for name in ("", "1TOKEN", "BAD-NAME", "BAD NAME", "X\nTOKEN", "PATH", TOKEN):
            with self.assertRaisesRegex(ValueError, "Invalid token environment") as caught:
                self.configure(token_env_var=name)
            self.assertNotIn(TOKEN, str(caught.exception))
        self.assertFalse(config.profile_path().exists())

    async def test_runtime_logging_variable_is_rejected_before_profile_or_child(self):
        # The MCP child forces RUST_LOG=off; accepting it would replace the bearer.
        with patch.dict(os.environ, {"RUST_LOG": TOKEN}):
            with self.assertRaisesRegex(ValueError, "Invalid token environment"):
                self.configure(token_env_var="RUST_LOG")
            self.assertFalse(config.profile_path().exists())
            # Loading a manually edited profile must reject the same collision.
            config.write_private(config.profile_path(), {
                "profile": "cloud", "account": "target@qq.com", "server": "qq-mail-cloud",
                "mode": "read_send", "auth_mode": "env_token", "token_env_var": "RUST_LOG"})
            with self.assertRaisesRegex(ValueError, "Invalid token environment"):
                async with bridge.CodexMail():
                    self.fail("A reserved credential variable must not start a client")
            self.assertFalse(self.events.exists())
            self.assert_no_secret_files()

    def test_matching_auth_variable_only_and_no_arbitrary_headers(self):
        path = config.codex_home() / "config.toml"
        path.parent.mkdir()
        canonical = '[mcp_servers.qq-mail-cloud]\nurl="https://api.mail.qq.com/mcp"\n'
        for addition in ('bearer_token_env_var="OTHER_QQ_TOKEN"', 'http_headers={Authorization="fixture"}', 'env_http_headers={Authorization="QQ_MAIL_ACCESS_TOKEN"}'):
            path.write_text(canonical + addition)
            with self.assertRaisesRegex(RuntimeError, "conflicts"):
                self.configure()
        path.write_text(canonical + 'bearer_token_env_var="QQ_MAIL_ACCESS_TOKEN"')
        self.configure()
        self.assert_no_secret_files()

    def test_env_mode_cannot_start_oauth_login(self):
        settings = self.configure()
        with patch.object(onboard.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "never starts OAuth"):
                onboard.login(settings)
            run.assert_not_called()

    def test_doctor_is_not_authorization_and_helpers_have_no_token(self):
        settings = self.configure()
        result = onboard.doctor(settings)
        self.assertEqual(result["auth_mode"], "env_token")
        self.assertTrue(result["token_variable_present"])
        self.assertTrue(result["token_variable_nonempty"])
        self.assertEqual(result["credential_status"], "unverified")
        self.assertFalse(result["currently_verified"])
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertEqual([e["kind"] for e in self.events_read()], ["helper", "helper"])

    async def test_env_verify_calls_real_adapter_getme_without_oauth_or_keyring(self):
        self.configure()
        result = await onboard.verify()
        self.assertEqual(result["state"], "verified")
        events = self.events_read()
        self.assertTrue(any(e.get("tool") == "GetMe" for e in events))
        self.assertFalse(any(e["kind"] == "oauth" for e in events))
        self.assert_no_secret_files()

    def test_env_init_separate_process_skips_login(self):
        script = Path(__file__).resolve().parents[1] / "scripts/onboard.py"
        result = subprocess.run([sys.executable, str(script), "init", "--account", "target@qq.com", "--mode", "read_send",
                                 "--auth-mode", "env_token", "--token-env-var", "QQ_MAIL_ACCESS_TOKEN"],
                                env=dict(os.environ), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"state": "verified"', result.stdout)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertFalse(any(e["kind"] == "oauth" for e in self.events_read()))
        self.assert_no_secret_files()

    async def test_wrong_account_insufficient_and_excess_scopes_stop(self):
        self.configure()
        for case in ("wrong", "missing", "wide"):
            os.environ["FIXTURE_CASE"] = case
            with self.assertRaises(RuntimeError) as caught:
                async with bridge.CodexMail(): pass
            self.assertNotIn(TOKEN, str(caught.exception))
        self.assertTrue(all(e.get("tool", "GetMe") == "GetMe" for e in self.events_read()))

    async def test_expired_revoked_401_and_http_errors_are_redacted(self):
        self.configure()
        for case in ("401", "expired", "revoked", "rpc401"):
            os.environ["FIXTURE_CASE"] = case
            with self.assertRaisesRegex(bridge.AuthenticationError, "update authorization") as caught:
                async with bridge.CodexMail(): pass
            self.assertNotIn(TOKEN, str(caught.exception))
        self.assert_no_secret_files()

    async def test_read_send_sends_once_and_forbids_delete(self):
        self.configure()
        result = await flow.execute_authorized("SendMessage", self.arguments, user_authorized=True)
        self.assertEqual(result["state"], "accepted")
        self.assertNotIn(TOKEN, json.dumps(result))
        with self.assertRaisesRegex(RuntimeError, "Deletion requires"):
            bridge.CodexMail(write_tool="DeleteMessage")
        self.assertEqual(sum(e.get("tool") == "SendMessage" for e in self.events_read()), 1)
        self.assert_no_secret_files()

    async def test_send_auth_failure_does_not_trigger_refresh_or_resend(self):
        self.configure()
        os.environ["FIXTURE_CASE"] = "send401"
        async with bridge.CodexMail(write_tool="SendMessage", user_authorized_send=True) as mail:
            args = {**self.arguments, "alias_id": mail.alias_id, "skip_confirmation": True}
            for _ in range(2):
                with self.assertRaises(bridge.AuthenticationError): await mail.raw_call("SendMessage", args)
        self.assertEqual(sum(e.get("tool") == "SendMessage" for e in self.events_read()), 1)

    async def test_send_response_loss_is_unknown_and_not_repeated(self):
        self.configure()
        os.environ["FIXTURE_CASE"] = "send_timeout"
        with self.assertRaisesRegex(RuntimeError, "unknown") as caught:
            await flow.execute_authorized("SendMessage", self.arguments, user_authorized=True)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(sum(e.get("tool") == "SendMessage" for e in self.events_read()), 1)
        receipts = list(config.load_settings().state_dir.glob("pending/*.json"))
        self.assertEqual(json.loads(receipts[0].read_text())["state"], "unknown")
        self.assert_no_secret_files()

    async def test_echoed_secret_not_in_raw_result_exception_or_receipts(self):
        self.configure()
        async with bridge.CodexMail() as mail:
            raw = await mail.raw_call("ListMessages", {"alias_id": mail.alias_id})
        self.assertNotIn(TOKEN, json.dumps(raw))
        self.assertNotIn(TOKEN, json.dumps(bridge.ToolError({"error": TOKEN}).payload))
        with self.assertRaises(ValueError): flow.validate_arguments("SendMessage", {**self.arguments, "body": TOKEN})
        self.assert_no_secret_files()

    async def test_oauth_mode_keeps_keyring_flow_and_strips_env_token(self):
        os.environ["FIXTURE_AUTH"] = "oauth_keyring"
        os.environ["FIXTURE_MODE"] = "read"
        settings = onboard.configure("target@qq.com", "read")
        onboard.login(settings)
        async with bridge.CodexMail() as mail:
            self.assertEqual(mail.status["auth_mode"], "oauth_keyring")
        self.assertEqual(sum(e["kind"] == "oauth" for e in self.events_read()), 1)
        self.assertFalse(next(e for e in self.events_read() if e["kind"] == "app")["token_present"])

    async def test_custom_token_name_reaches_only_the_mcp_child(self):
        os.environ["CLOUD_QQ_TOKEN"] = TOKEN
        os.environ["FIXTURE_TOKEN_NAME"] = "CLOUD_QQ_TOKEN"
        self.configure(token_env_var="CLOUD_QQ_TOKEN")
        self.assertTrue(onboard.doctor()["token_variable_present"])
        async with bridge.CodexMail() as mail:
            self.assertEqual(mail.status["auth_mode"], "env_token")
        self.assert_no_secret_files()

    async def test_previous_verification_does_not_claim_current_token_validity(self):
        self.configure()
        await onboard.verify()
        os.environ["QQ_MAIL_ACCESS_TOKEN"] = ""
        result = onboard.doctor()
        self.assertEqual(result["credential_status"], "previously_verified")
        self.assertFalse(result["currently_verified"])
        self.assertFalse(result["token_variable_nonempty"])

    async def test_missing_token_never_reads_fallback_auth_files(self):
        self.configure()
        os.environ.pop("QQ_MAIL_ACCESS_TOKEN")
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if path.name in ("auth.json", "mcp_auth.json", "credentials.json"):
                raise AssertionError("No OAuth/keyring/file fallback is permitted")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", guarded):
            with self.assertRaisesRegex(RuntimeError, "no authentication fallback"):
                async with bridge.CodexMail(): pass
        self.assertFalse(self.events.exists())


if __name__ == "__main__":
    unittest.main()
