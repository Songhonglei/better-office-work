"""Cross-agent CLI and failure regressions; synthetic credentials, no network."""
import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mail_config as config
import mail_credentials as credentials
import onboard
import qq_mail as bridge
import qq_mail_write as flow
from test_write_flow import FakeMail


class AgentPortabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qq-agent-review-")
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {"QQ_MAIL_HOME": str(self.root / "mail"),
                             "CODEX_HOME": str(self.root / "codex"), "QQ_MAIL_PROFILE": "fixture"})
        self.env.start()
        onboard.configure("test@qq.com", "manage")
        FakeMail.writes = []
        FakeMail.fail_confirmation = False
        FakeMail.in_trash = False

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_confirmation_expiry_is_distinct_from_oauth_expiry(self):
        for payload in ({"error": {"code": 40001, "message": "confirmation token expired"}},
                        {"code": 42801, "message": "CONFIRMATION_REQUIRED"}):
            self.assertFalse(bridge.authentication_failure(payload))
        for payload in ({"error": {"code": 401, "message": "expired"}},
                        {"status": 403}, {"error": "invalid_grant"},
                        {"message": "access token expired"}, {"message": "expired token"}):
            self.assertTrue(bridge.authentication_failure(payload))

    async def test_real_bridge_does_not_poison_auth_on_confirmation_expiry(self):
        mail = bridge.CodexMail(write_tool="DeleteMessage")
        mail.alias_id, mail.thread_id = "alias_fixture", "thread_fixture"
        mail.rpc = AsyncMock(side_effect=[
            {"isError": True, "structuredContent": {"error": {"code": 40001, "message": "token expired"}}},
            {"structuredContent": {"data": [], "pagination": {"has_more": False}}}])
        with patch.object(bridge, "reserve_call_slot", new=AsyncMock()):
            raw = await mail.raw_call("DeleteMessage", {"alias_id": mail.alias_id, "message_id": "msg_fixture"})
            self.assertEqual(bridge.decode_result(raw)["error"]["code"], 40001)
            self.assertFalse(mail.authorization_failed)
            await mail.call("ListMessages", {"alias_id": mail.alias_id})
        self.assertEqual(mail.rpc.await_count, 2)

    async def test_lost_renewal_is_durable_unknown_and_cannot_be_replayed(self):
        batch = await flow.prepare_delete_batch([
            {"message_id": "msg_first", "created_at": "2026-10-20T00:00:00Z"}], client=FakeMail)
        request_id = batch["requests"][0]["request_id"]
        observed = []

        class LostRenewal(FakeMail):
            async def raw_call(inner, tool, arguments):
                observed.append(json.loads(flow.state_path(request_id).read_text())["state"])
                raise asyncio.TimeoutError("synthetic response loss")

        with self.assertRaises(asyncio.TimeoutError):
            await flow.confirm(request_id, client=LostRenewal, renew_delete=True)
        self.assertEqual(observed, ["preparing"])
        self.assertEqual(flow.request_status(request_id)["state"], "unknown")
        with self.assertRaisesRegex(RuntimeError, "unknown outcome"):
            await flow.confirm(request_id, client=LostRenewal, renew_delete=True)
        self.assertEqual(len(observed), 1)

    async def test_receipt_directory_sync_failure_prevents_submission(self):
        arguments = {"to": [{"email": "fixture@example.com"}], "subject": "fixture", "body": "fixture"}
        with patch.object(flow, "sync_directory", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                await flow.execute_authorized("SendMessage", arguments, user_authorized=True, client=FakeMail)
        self.assertEqual(FakeMail.writes, [])

    async def test_request_status_omits_content_and_cannot_submit(self):
        result = await flow.prepare("SendMessage", {"to": [{"email": "fixture@example.com"}],
            "subject": "fixture", "body": "synthetic-private-mail-body"}, client=FakeMail)
        previous = len(FakeMail.writes)
        status = flow.request_status(result["request_id"])
        self.assertEqual(status["state"], "pending")
        self.assertNotIn("synthetic-private-mail-body", json.dumps(status))
        self.assertNotIn("test-one-time-token", json.dumps(status))
        self.assertEqual(len(FakeMail.writes), previous)
        with patch.object(flow, "account", return_value="other@qq.com"):
            with self.assertRaisesRegex(ValueError, "identity"):
                flow.request_status(result["request_id"])

    def test_standard_input_and_malformed_input_do_not_echo_contents(self):
        content = {"body": "synthetic-private-mail-body", "subject": "fixture"}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(content).encode()), encoding="utf-8")
        with patch.object(sys, "stdin", stdin):
            self.assertEqual(flow.read_json_input(Path("-")), content)
        stdin = io.TextIOWrapper(io.BytesIO(b'{"synthetic-private-mail-body":'), encoding="utf-8")
        with patch.object(sys, "stdin", stdin):
            with self.assertRaises(ValueError) as caught:
                flow.read_json_input(Path("-"))
        self.assertNotIn("synthetic-private-mail-body", str(caught.exception))

    def test_millisecond_expiry_is_rejected_instead_of_skipping_refresh(self):
        with self.assertRaisesRegex(credentials.CredentialError, "seconds, not milliseconds"):
            credentials.validate_record({"access_token": "synthetic-token", "expires_at": int(time.time() * 1000)})

    def attachment(self):
        content = b"synthetic PDF bytes"
        return content, {"content": base64.b64encode(content).decode(), "size": len(content),
                         "sha1": hashlib.sha1(content).hexdigest()}

    def download_mail(self, payload):
        async def call(tool, arguments):
            if tool == "GetMessage":
                content, _ = self.attachment()
                return {"message_id": "msg_fixture", "attachments": [{"attachment_id":"att_fixture", "size":len(content)}]}
            return payload
        return type("Mail", (), {"alias_id":"fixture", "call":AsyncMock(side_effect=call)})()

    async def test_download_verifies_private_file_without_exposing_base64(self):
        content, payload = self.attachment()
        mail = self.download_mail(payload)
        output = self.root / "invoice.pdf"
        result = await bridge.download_attachment(mail, "msg_fixture", "att_fixture", output)
        self.assertEqual(output.read_bytes(), content)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(payload["content"], json.dumps(result))
        self.assertFalse(list(self.root.glob(".qq-attachment-*")))
        self.assertEqual(mail.call.call_args.args[1]["alias_id"], "fixture")

    async def test_invalid_attachment_never_creates_output(self):
        _, payload = self.attachment()
        bad = [{**payload, "sha1": "0" * 40}, {**payload, "size": payload["size"] + 1},
               {**payload, "content": "bad-base64!"}, {**payload, "size": 1048577},
               {**payload,"size":None}]
        for number, value in enumerate(bad):
            output = self.root / (str(number) + ".pdf")
            mail = self.download_mail(value)
            with self.assertRaises(ValueError):
                await bridge.download_attachment(mail, "msg_fixture", "att_fixture", output)
            self.assertFalse(output.exists())

    async def test_download_never_overwrites_file_or_link(self):
        _, payload = self.attachment()
        mail = type("Mail", (), {"alias_id": "fixture", "call": AsyncMock(return_value=payload)})()
        output = self.root / "existing.pdf"
        output.write_bytes(b"existing")
        link = self.root / "link.pdf"
        link.symlink_to(output)
        for path in (output, link):
            with self.assertRaisesRegex(ValueError, "already exists"):
                await bridge.download_attachment(mail, "msg_fixture", "att_fixture", path)
        self.assertEqual(output.read_bytes(), b"existing")
        mail.call.assert_not_called()

    async def test_download_race_preserves_winning_output(self):
        _, payload = self.attachment()
        output = self.root / "raced.pdf"

        async def race(tool, _arguments):
            if tool == "GetMessage":
                content, _ = self.attachment()
                return {"message_id": "msg_fixture", "attachments":[{"attachment_id":"att_fixture","size":len(content)}]}
            output.write_bytes(b"other process won")
            return payload

        mail = type("Mail", (), {"alias_id": "fixture", "call": AsyncMock(side_effect=race)})()
        with self.assertRaises(FileExistsError):
            await bridge.download_attachment(mail, "msg_fixture", "att_fixture", output)
        self.assertEqual(output.read_bytes(), b"other process won")
        self.assertFalse(list(self.root.glob(".qq-attachment-*")))


DIRECT_CLI_FIXTURE = r'''
import base64,json,os,runpy,subprocess,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import direct_http as h
import qq_mail as bridge
from unittest.mock import AsyncMock
bridge.reserve_call_slot=AsyncMock()
def worker(command,**kw):
    assert command[-1]=='--http-worker', 'Unexpected Codex/credential subprocess'
    assert 'QQ_MAIL_ACCESS_TOKEN' not in kw['env']
    payload=json.loads(kw['input']); message=payload['message']; method=message['method']
    modern=payload.get('protocol')==h.MODERN
    extra={}
    if method=='notifications/initialized': response=None
    else:
        if method=='server/discover': value={'supportedVersions':[h.MODERN,'2025-03-26'],'capabilities':{'tools':{}}}
        elif method=='initialize': value={'protocolVersion':'2025-03-26','capabilities':{'tools':{}}}
        elif method=='tools/list':
            import mail_config
            value={'tools':[{'name':n,'inputSchema':{'type':'object'}} for n in (*mail_config.READ_TOOLS,'SendMessage')]}
            if modern: extra['catalog_names']=[t['name'] for t in value['tools']]
        elif method=='tools/call':
            name=message['params']['name']
            if name=='GetMe': data={'scopes':['mail:read','mail:send'],'aliases':[{'email':'fixture@qq.com','alias_id':'fixture-alias'}]}
            elif name=='SendMessage':
                args=message['params']['arguments']
                assert args['body']=='fixture body' and args['alias_id']=='fixture-alias' and args['skip_confirmation'] is True
                with Path(os.environ['FIXTURE_SENDS']).open('a') as f:f.write('send\n')
                data={'queued':True}
            elif name in ('GetMessage','ListAttachments','DownloadAttachment'):
                args=message['params']['arguments']
                assert args['message_id']=='msg_fixture' and args['alias_id']=='fixture-alias'
                content=b'synthetic attachment bytes'
                items=[{'attachment_id':'att_fixture','filename':'fixture.pdf','content_type':'application/pdf','size':len(content)}]
                if name=='GetMessage': data={'message_id':'msg_fixture','attachments':items,'attachment_count':1}
                elif name=='ListAttachments': data=items
                else:
                    assert args['attachment_id']=='att_fixture'
                    data={'filename':'fixture.pdf','content_type':'application/pdf','content':base64.b64encode(content).decode()}
            else: raise AssertionError(name)
            value={'content':[{'type':'text','text':json.dumps(data)}]} if name=='ListAttachments' else {'structuredContent':data}
        else: raise AssertionError(method)
        if modern: value={'resultType':'complete',**value}
        response={'jsonrpc':'2.0','id':message['id'],'result':value}
    return subprocess.CompletedProcess(command,0,json.dumps({'ok':True,'message':response,'session':None,**extra}), '')
h.subprocess.run=worker
entry=sys.argv[2];sys.argv=[entry,*sys.argv[3:]]
runpy.run_path(entry,run_name='__main__')
'''


class StandaloneCLITests(unittest.TestCase):
    def test_relocated_direct_cli_onboards_verifies_and_sends_without_codex(self):
        for protocol in ("auto", "2025-03-26"):
            with self.subTest(protocol=protocol):
                self.check_standalone_protocol(protocol)

    def check_standalone_protocol(self, protocol):
        with tempfile.TemporaryDirectory(prefix="standalone mail ") as temporary:
            root = Path(temporary).resolve()
            installed = root / "skills with spaces" / "qq-mail-manage"
            shutil.copytree(Path(__file__).resolve().parents[1], installed, ignore=shutil.ignore_patterns("__pycache__"))
            scripts = installed / "scripts"
            env = {"HOME": str(root / "home"), "CODEX_HOME": str(root / "unused-codex"),
                   "QQ_MAIL_HOME": str(root / "private-mail"), "QQ_MAIL_PROFILE": "standalone", "PATH": "",
                   "QQ_MAIL_ACCESS_TOKEN": "synthetic-standalone-access-token", "FIXTURE_SENDS": str(root / "sends")}

            def run(entry, *arguments, simulated=False, content=None):
                command = [sys.executable]
                if simulated:
                    command += ["-c", DIRECT_CLI_FIXTURE, str(scripts), str(scripts / entry)]
                else:
                    command += [str(scripts / entry)]
                result = subprocess.run([*command, "--profile", "standalone", *arguments], env=env,
                                        cwd=root, input=content, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(env["QQ_MAIL_ACCESS_TOKEN"], result.stdout + result.stderr)
                return json.loads(result.stdout)

            initial = run("onboard.py", "init", "--account", "fixture@qq.com", "--mode", "read_send",
                          "--backend", "direct_http", "--auth-mode", "env_token", "--http-protocol", protocol, "--configure-only")
            self.assertEqual(initial["state"], "configured_not_verified")
            diagnostic = run("onboard.py", "doctor")
            self.assertIsNone(diagnostic["codex"])
            self.assertEqual(diagnostic["backend"], "direct_http")
            self.assertEqual(diagnostic["http_protocol"], protocol)
            verified = run("onboard.py", "verify", simulated=True)
            self.assertEqual(verified["state"], "verified")
            listed = run("qq_mail.py", "attachments", "--message-id", "msg_fixture", simulated=True)
            self.assertEqual(listed["attachments"][0]["attachment_id"], "att_fixture")
            downloaded = run("qq_mail.py", "download", "--message-id", "msg_fixture",
                             "--attachment-id", "att_fixture", "--output", str(root / "fixture.pdf"), simulated=True)
            self.assertEqual((root / "fixture.pdf").read_bytes(), b"synthetic attachment bytes")
            self.assertEqual(downloaded["verification"]["metadata_source"], "GetMessage")
            self.assertEqual(downloaded["verification"]["level"], "metadata_size_and_local_digest")
            arguments = {"to": [{"email": "fixture@example.com"}], "subject": "fixture", "body": "fixture body"}
            sent = run("qq_mail_write.py", "execute-authorized", "--tool", "SendMessage",
                       "--arguments-file", "-", "--user-authorized", simulated=True, content=json.dumps(arguments))
            self.assertEqual(sent["state"], "completed")
            status = run("qq_mail_write.py", "request-status", "--request-id", sent["request_id"])
            self.assertEqual(status["state"], "completed")
            self.assertEqual((root / "sends").read_text(), "send\n")
            self.assertFalse((root / "unused-codex" / "config.toml").exists())
            self.assertFalse((installed / "profiles").exists())

    def test_old_python_and_native_windows_fail_with_actionable_message(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        for entry in ("onboard.py", "qq_mail.py", "qq_mail_write.py"):
            for setup, message in (("sys.version_info=(3,10,0)", "Python 3.11+"), ("os.name='nt'", "WSL")):
                command = [sys.executable, "-c", "import os,sys,runpy;sys.path.insert(0,sys.argv[1]);" + setup + ";runpy.run_path(sys.argv[2],run_name='__main__')",
                           str(scripts), str(scripts / entry)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
