"""Durable operation identity and evidence states; all credentials/mail are synthetic."""
import asyncio
import base64
import copy
from dataclasses import replace
import hashlib
import json
import io
from contextlib import redirect_stdout
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mail_config as config
import mail_credentials as credentials
import onboard
import qq_mail as bridge
import qq_mail_write as flow
from test_write_flow import FakeMail

ROOT = Path(__file__).resolve().parents[1]


class OperationReceiptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {"QQ_MAIL_HOME": str(self.root / "mail"), "QQ_MAIL_PROFILE": "delivery"})
        self.env.start()
        onboard.configure("test@qq.com", "read_send", auth_mode="env_token", backend="direct_http")
        self.args = {"to": [{"email": "fixture@gmail.com"}], "subject": "fixture invoice", "body": "fixture body"}
        FakeMail.writes, FakeMail.fail_confirmation = [], False

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    async def send(self, operation_id="invoice-job-1", **kw):
        return await flow.execute_authorized("SendMessage", self.args, user_authorized=True,
                                             operation_id=operation_id, client=FakeMail, **kw)

    async def test_same_operation_returns_original_receipt_without_connecting(self):
        first = await self.send()
        with patch.object(FakeMail, "__aenter__", side_effect=AssertionError("must not reconnect")):
            again = await self.send()
        self.assertEqual(first, again)
        self.assertEqual(len(FakeMail.writes), 1)
        self.assertEqual(first["state"], "accepted")
        self.assertEqual(first["verification"], {"qq_accepted": True, "sent_verified": False, "recipient_verified": False})

    async def test_legacy_python_content_identity_is_stable(self):
        await self.send(operation_id=None)
        await self.send(operation_id=None)
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_changed_content_or_tool_reusing_operation_is_rejected(self):
        await self.send()
        self.args["subject"] = "changed"
        with self.assertRaisesRegex(ValueError, "already bound"):
            await self.send()
        with self.assertRaisesRegex(ValueError, "already bound"):
            await flow.execute_authorized("ForwardMessage", {"message_id": "msg_source", "to": self.args["to"], "body": "fixture body"},
                                         operation_id="invoice-job-1", user_authorized=True, client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_explicit_different_job_can_intentionally_send_same_content(self):
        await self.send("job-one")
        await self.send("job-two")
        self.assertEqual(len(FakeMail.writes), 2)

    async def test_unknown_is_replayed_as_receipt_without_a_second_write(self):
        FakeMail.fail_confirmation = True
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            await self.send()
        FakeMail.fail_confirmation = False
        self.assertEqual((await self.send())["state"], "unknown")
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_prepare_and_direct_send_share_the_same_operation(self):
        prepared = await flow.prepare("SendMessage", self.args, client=FakeMail, operation_id="invoice-job-1")
        direct = await self.send()
        self.assertEqual(prepared["request_id"], direct["request_id"])
        self.assertEqual(direct["state"], "awaiting_user_confirmation")
        result = await flow.confirm(direct["request_id"], client=FakeMail)
        self.assertEqual(result["state"], "accepted")
        self.assertEqual((await self.send())["state"], "accepted")
        self.assertEqual(len(FakeMail.writes), 2)  # challenge then approved submission

    async def test_corrupt_receipt_stops_instead_of_resending(self):
        result = await self.send()
        flow.state_path(result["request_id"]).write_text('{"truncated"')
        with self.assertRaisesRegex(RuntimeError, "Unreadable"):
            await self.send()
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_atomic_replace_failure_keeps_valid_json_and_blocks_resend(self):
        replace = credentials.os.replace
        attempts = []
        def fail_once(source, target):
            attempts.append(json.loads(Path(target).read_text())["state"])
            if len(attempts) == 1:
                raise OSError("synthetic pre-rename interruption")
            return replace(source, target)
        with patch.object(credentials.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                await self.send()
        result = await self.send()
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(attempts, ["submitting", "submitting"])
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_lock_survives_atomic_json_replacement(self):
        result = await self.send()
        rid = result["request_id"]
        with flow.receipt_lock(rid) as lock:
            record = flow.read_receipt(rid)
            inode = flow.state_path(rid).stat().st_ino
            flow.update_locked(lock, record)
            self.assertNotEqual(inode, flow.state_path(rid).stat().st_ino)
            with self.assertRaisesRegex(RuntimeError, "already being handled"):
                with flow.receipt_lock(rid):
                    self.fail("a replaced receipt must not release the operation lock")

    def observation(self, stage="sent"):
        return {"stage": stage, "provider": "qq" if stage == "sent" else "gmail", "message_id": "observed-message",
                "source_reference": "synthetic-tool-run:read-1", "folder": "sent" if stage == "sent" else "inbox",
                "account": "test@qq.com" if stage == "sent" else "fixture@gmail.com", "from": "test@qq.com",
                "observed_mail_at": datetime.now(timezone.utc).isoformat(), "time_basis": "qq_sent_at" if stage == "sent" else "mailbox_received_at", **copy.deepcopy(self.args),
                "body_format": "PLAIN", "attachments": copy.deepcopy(self.args.get("attachments", []))}

    async def test_sent_and_recipient_are_separate_verified_evidence_stages(self):
        result = await self.send()
        rid = result["request_id"]
        sent = flow.record_verification(rid, self.observation())
        self.assertEqual(sent["state"], "sent_verified")
        self.assertFalse(sent["verification"]["recipient_verified"])
        recipient = flow.record_verification(rid, self.observation("recipient"))
        self.assertEqual(recipient["state"], "recipient_verified")
        self.assertTrue(recipient["verification"]["sent_verified"])
        self.assertEqual(recipient["evidence"]["recipient"]["source"], "host_independent_observation")
        self.assertNotIn("fixture body", json.dumps(recipient))
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_mismatched_partial_stale_or_nonindependent_evidence_cannot_promote(self):
        rid = (await self.send())["request_id"]
        cases = [{"body": "wrong"}, {"subject": "wrong"}, {"from": "other@qq.com"}, {"attachments": None},
                 {"source_reference": ""}, {"folder": "inbox"}, {"observed_mail_at": "2020-01-01T00:00:00Z"},
                 {"observed_mail_at": "not-a-time"}, {"time_basis": "created_at"}, {"to": [{"email": "other@gmail.com"}]}]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    flow.record_verification(rid, {**self.observation(), **case})
        with self.assertRaises(ValueError):
            flow.record_verification(rid, {**self.observation("recipient"), "provider": "qq"})
        self.assertEqual(flow.request_status(rid)["state"], "accepted")

    async def test_unknown_can_be_reconciled_with_evidence_without_resend(self):
        FakeMail.fail_confirmation = True
        with self.assertRaises(RuntimeError): await self.send()
        FakeMail.fail_confirmation = False
        rid = (await self.send())["request_id"]
        self.assertEqual(flow.record_verification(rid, self.observation())["state"], "sent_verified")
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_attachment_evidence_requires_every_byte_and_matching_metadata(self):
        data = b"synthetic invoice"
        a = {"filename": "fixture.pdf", "content_type": "application/pdf", "size": len(data),
             "sha1": hashlib.sha1(data).hexdigest(), "content": base64.b64encode(data).decode()}
        self.args["attachments"] = [a]
        rid = (await self.send())["request_id"]
        with self.assertRaises(ValueError):flow.record_verification(rid, {**self.observation(), "attachments": []})
        self.assertEqual(flow.record_verification(rid, self.observation())["state"], "sent_verified")

    async def test_legacy_completed_is_not_assumed_verified(self):
        rid = (await self.send())["request_id"]
        with flow.receipt_lock(rid) as lock:
            record = flow.read_receipt(rid)
            record["state"] = "completed"
            flow.update_locked(lock, record)
        self.assertEqual(flow.request_status(rid)["state"], "legacy_unverified")

    async def test_manual_pages_publish_and_reuse_identical_window_without_receipt_guess(self):
        calls=[]
        class Mail:
            alias_id="fixture"
            async def __aenter__(self): return self
            async def __aexit__(self,*_): pass
            async def call(self,tool,args):
                calls.append(dict(args))
                return {"data":[{"message_id":"candidate", "created_at":"2026-10-20T00:00:00Z"}],
                        "pagination":{"has_more":len(calls)==1,"next_cursor":"opaque" if len(calls)==1 else None}}
        first=io.StringIO()
        with patch.object(bridge,"CodexMail",Mail),patch.object(sys,"argv",["qq_mail.py","list"]),redirect_stdout(first):
            await bridge.main()
        result=json.loads(first.getvalue())
        window=result["query_window"]
        self.assertEqual(result["selection"]["status"],"candidates")
        self.assertFalse(result["selection"]["received_at_available"])
        with patch.object(bridge,"CodexMail",Mail),patch.object(sys,"argv",["qq_mail.py","list","--cursor","opaque", "--after",window["after"],"--before",window["before"]]),redirect_stdout(io.StringIO()):
            await bridge.main()
        self.assertEqual(calls[0]["after"],calls[1]["after"])
        self.assertEqual(calls[0]["before"],calls[1]["before"])
        self.assertEqual(calls[1]["cursor"],"opaque")


PROCESS = r'''
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import qq_mail_write as flow
class Mail:
    def __init__(self,**kw): self.alias_id='fixture'
    async def __aenter__(self): return self
    async def __aexit__(self,*_): pass
    async def raw_call(self,*_):
        with Path(sys.argv[2]).open('a') as f: f.write('send\n')
        time.sleep(.3)
        return {'structuredContent':{'queued':True}}
try:
    result=asyncio.run(flow.execute_authorized('SendMessage',{'to':[{'email':'fixture@gmail.com'}],'subject':'fixture','body':'fixture'},
        user_authorized=True,operation_id='durable-host-job',client=Mail))
    print(json.dumps(result))
except RuntimeError as e:
    print(str(e));sys.exit(3)
'''


class ProcessAndOnboardTests(unittest.TestCase):
    def test_concurrent_process_and_restart_make_only_one_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, QQ_MAIL_HOME=str(Path(temporary).resolve()/"mail"), QQ_MAIL_PROFILE="fixture")
            with patch.dict(os.environ, env):onboard.configure("test@qq.com", "read_send", auth_mode="env_token", backend="direct_http")
            log = Path(temporary)/"submissions"
            cmd = [sys.executable, "-c", PROCESS, str(ROOT/"scripts"), str(log)]
            one = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            two = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            outputs = [one.communicate(timeout=15), two.communicate(timeout=15)]
            self.assertIn(0, (one.returncode, two.returncode), outputs)
            self.assertTrue(all(code in (0,3) for code in (one.returncode,two.returncode)), outputs)
            restarted = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15, check=True)
            self.assertEqual(json.loads(restarted.stdout)["state"], "accepted")
            self.assertEqual(log.read_text().splitlines(), ["send"])

    def test_hard_process_kill_leaves_barrier_and_restart_cannot_send(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, QQ_MAIL_HOME=str(Path(temporary).resolve()/"mail"), QQ_MAIL_PROFILE="fixture")
            with patch.dict(os.environ, env):onboard.configure("test@qq.com", "read_send", auth_mode="env_token", backend="direct_http")
            log=Path(temporary)/"submissions"
            cmd=[sys.executable,"-c",PROCESS.replace("time.sleep(.3)","time.sleep(30)"),str(ROOT/"scripts"),str(log)]
            process=subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+10
                while not log.exists() and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue(log.exists(),"child must reach simulated submission")
                process.kill()
                process.communicate(timeout=10)
            finally:
                if process.poll() is None:process.kill();process.communicate(timeout=10)
            restarted=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=10,check=True)
            self.assertEqual(json.loads(restarted.stdout)["state"],"submitting")
            self.assertEqual(log.read_text().splitlines(),["send"])

    def test_cursor_without_fixed_bounds_fails_before_any_mail_access(self):
        r = subprocess.run([sys.executable, str(ROOT/"scripts/qq_mail.py"), "list", "--cursor", "opaque"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode,2)
        self.assertIn("original --after and --before", r.stderr)

    def test_single_next_step_preserves_the_selected_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, QQ_MAIL_HOME=str(Path(temporary).resolve()/"mail"), QQ_MAIL_ACCESS_TOKEN="synthetic-onboard-token")
            r = subprocess.run([sys.executable,str(ROOT/"scripts/onboard.py"),"--profile","ela","init", "--account","test@qq.com",
                "--backend","direct_http","--auth-mode","env_token","--configure-only"],env=env,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(r.stdout)["next"], "python3 scripts/onboard.py --profile ela verify")
            env["QQ_MAIL_ACCESS_TOKEN"]=""
            r=subprocess.run([sys.executable,str(ROOT/"scripts/onboard.py"),"--profile","ela","init", "--account","test@qq.com",
                "--backend","direct_http","--auth-mode","env_token","--configure-only"],env=env,capture_output=True,text=True,check=True)
            next_action=json.loads(r.stdout)["next"]
            self.assertIn("Securely inject",next_action)
            self.assertIn("--profile ela",next_action)
            self.assertNotIn(" verify",next_action)

    def test_credential_diagnostic_does_not_expose_tokens_or_refresh_unknown_store(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"QQ_MAIL_HOME": str(Path(temporary).resolve()/"mail"),
                "QQ_MAIL_PROFILE":"diagnostic", "QQ_MAIL_ACCESS_TOKEN":"synthetic-secret", "QQ_MAIL_EXPIRES_AT":str(time.time()-1)}):
            settings=onboard.configure("test@qq.com",auth_mode="env_token",backend="direct_http")
            with patch.object(credentials,"exchange",side_effect=AssertionError("must not refresh")):
                result=onboard.credential_summary(settings,inspect_store=True)
            self.assertEqual(result["status"],"expired")
            self.assertEqual(set(result),{"status","expires_at","refresh_owner","recovery"})
            self.assertNotIn("synthetic-secret",json.dumps(result))
            self.assertIn("--profile diagnostic verify",result["recovery"])

    def test_unknown_credential_state_returns_safe_recovery_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"QQ_MAIL_HOME": str(Path(temporary).resolve()/"mail"), "QQ_MAIL_PROFILE":"unknown"}):
            settings=onboard.configure("test@qq.com",auth_mode="env_token",backend="direct_http")
            settings=replace(settings,credential_source="host_command",credential_command="/synthetic/adapter")
            with patch.object(credentials,"HostStore") as store, patch.object(credentials,"exchange",side_effect=AssertionError("no refresh")):
                store.return_value.load.return_value={"access_token":"synthetic-secret", "refresh_state":"pending", "expires_at":time.time()+300}
                result=onboard.credential_summary(settings,inspect_store=True)
                self.assertEqual(store.return_value.load.call_count,1)
            self.assertEqual(result["status"],"blocked_unknown")
            self.assertIsNone(result["expires_at"])
            self.assertNotIn("synthetic-secret",json.dumps(result))
            self.assertIn("do not retry",result["recovery"])


if __name__ == "__main__":unittest.main()
