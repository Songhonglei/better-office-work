import asyncio
import json
import tempfile
import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import qq_mail_write as flow


class FakeMail:
    writes = []
    fail_confirmation = False
    in_trash = False

    def __init__(self, write_tool=None, user_authorized_send=False):
        self.alias_id = "alias_test"
        self.user_authorized_send = user_authorized_send

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def call(self, tool, arguments):
        if tool == "ListMessages":
            folder = "trash" if self.in_trash else "inbox"
            return {"data": [{"message_id": "msg_first"}, {"message_id": "msg_second"}] if arguments["dir"] == folder else [], "pagination": {"has_more": False}}
        return {"subject": "test message", "from": {"email": "test@example.com"}}

    async def raw_call(self, tool, arguments):
        self.writes.append((tool, dict(arguments)))
        if arguments.get("skip_confirmation"):
            if not self.user_authorized_send:
                raise RuntimeError("No direct authorization")
            if self.fail_confirmation:
                raise asyncio.TimeoutError("simulated response loss")
            return {"content": [{"type": "text", "text": json.dumps({"data": {"queued": True}})}]}
        if "confirmation_token" not in arguments:
            payload = {"error": {"code": 42801, "confirmation_token": "test-one-time-token", "operation_summary": {"action": tool}}}
            return {"isError": True, "content": [{"type": "text", "text": json.dumps(payload)}]}
        if self.fail_confirmation:
            raise asyncio.TimeoutError("simulated response loss")
        if tool == "DeleteMessage":
            return {"structuredContent": {"message_id": arguments["message_id"], "deleted": True}}
        return {"content": [{"type": "text", "text": json.dumps({"data": {"message_id": "msg_test_result"}})}]}


class WriteFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_env = patch.dict(os.environ, {"QQ_MAIL_HOME": self.temp.name, "QQ_MAIL_PROFILE": "test"})
        self.config_env.start()
        from onboard import configure
        configure("test@qq.com", "manage")
        self.original_pending = flow.PENDING
        flow.PENDING = Path(self.temp.name) / "pending"
        FakeMail.writes = []
        FakeMail.fail_confirmation = False
        FakeMail.in_trash = False
        self.arguments = {"to": [{"email": "test@example.com"}], "subject": "test", "body": "test body"}

    def tearDown(self):
        flow.PENDING = self.original_pending
        self.config_env.stop()
        self.temp.cleanup()

    async def test_challenge_then_exact_commit_and_no_replay(self):
        prepared = await flow.prepare("SendMessage", self.arguments, client=FakeMail)
        self.assertNotIn("test-one-time-token", json.dumps(prepared))
        self.assertNotIn("confirmation_token", FakeMail.writes[0][1])
        self.assertFalse(FakeMail.writes[0][1]["skip_confirmation"])
        result = await flow.confirm(prepared["request_id"], client=FakeMail)
        self.assertEqual(result["state"], "accepted")
        self.assertEqual(FakeMail.writes[1][1]["confirmation_token"], "test-one-time-token")
        for key, value in FakeMail.writes[0][1].items():
            self.assertEqual(FakeMail.writes[1][1][key], value)
        record = json.loads(flow.state_path(prepared["request_id"]).read_text())
        self.assertNotIn("arguments", record)
        self.assertNotIn("confirmation_token", record)
        replay = await flow.confirm(prepared["request_id"], client=FakeMail)
        self.assertEqual(replay["state"], "accepted")
        self.assertEqual(len(FakeMail.writes), 2)

    async def test_changed_payload_cannot_be_submitted(self):
        prepared = await flow.prepare("SendMessage", self.arguments, client=FakeMail)
        path = flow.state_path(prepared["request_id"])
        record = json.loads(path.read_text())
        record["arguments"]["to"] = [{"email": "different@example.com"}]
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await flow.confirm(prepared["request_id"], client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_lost_response_is_not_retried(self):
        prepared = await flow.prepare("SendMessage", self.arguments, client=FakeMail)
        FakeMail.fail_confirmation = True
        with self.assertRaises(asyncio.TimeoutError):
            await flow.confirm(prepared["request_id"], client=FakeMail)
        record = json.loads(flow.state_path(prepared["request_id"]).read_text())
        self.assertEqual(record["state"], "unknown")
        replay = await flow.confirm(prepared["request_id"], client=FakeMail)
        self.assertEqual(replay["state"], "unknown")
        self.assertEqual(len(FakeMail.writes), 2)

    async def test_injected_authorization_fields_rejected_before_network(self):
        for key, value in [("skip_confirmation", True), ("confirmation_token", "invented"), ("alias_id", "another")]:
            with self.assertRaises(ValueError):
                await flow.prepare("SendMessage", {**self.arguments, key: value}, client=FakeMail)
        self.assertEqual(FakeMail.writes, [])

    async def test_irreversible_delete_not_supported(self):
        for tool in ("PermanentDeleteMessage", "ClearTrash"):
            with self.assertRaises(ValueError):
                await flow.prepare(tool, {"message_id": "msg_test"}, client=FakeMail)
        self.assertEqual(FakeMail.writes, [])

    async def test_batch_only_commits_the_approved_indices(self):
        messages = [{"message_id": "msg_first", "subject": "First ad", "created_at": "2026-10-20T00:00:00Z"}, {"message_id": "msg_second", "subject": "Second ad", "created_at": "2026-10-20T00:00:00Z"}]
        prepared = await flow.prepare_delete_batch(messages, client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 2)
        self.assertTrue(all("confirmation_token" not in args for _, args in FakeMail.writes))
        result = await flow.confirm_delete_batch(prepared["batch_id"], indices=[2], client=FakeMail)
        self.assertEqual(result["count"], 1)
        self.assertEqual(FakeMail.writes[-1][1]["message_id"], "msg_second")
        first = json.loads(flow.state_path(prepared["requests"][0]["request_id"]).read_text())
        self.assertEqual(first["state"], "pending")
        status = flow.batch_status(prepared["batch_id"])
        self.assertEqual(status["completed"], 1)
        self.assertEqual([x["state"] for x in status["requests"]], ["pending", "completed"])
        self.assertNotIn("confirmation_token", json.dumps(status))

    async def test_changed_batch_summary_is_rejected(self):
        prepared = await flow.prepare_delete_batch([{"message_id": "msg_first", "subject": "First ad", "created_at": "2026-10-20T00:00:00Z"}], client=FakeMail)
        record_path = flow.state_path(prepared["requests"][0]["request_id"])
        record = json.loads(record_path.read_text())
        record["preview"]["original_subject"] = "Unreviewed mail"
        record_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(RuntimeError, "reviewed summary"):
            await flow.confirm_delete_batch(prepared["batch_id"], client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_explicitly_requested_send_uses_direct_mode_once(self):
        result = await flow.execute_authorized("SendMessage", self.arguments, user_authorized=True, client=FakeMail)
        self.assertEqual(result["state"], "accepted")
        self.assertEqual(len(FakeMail.writes), 1)
        self.assertTrue(FakeMail.writes[0][1]["skip_confirmation"])
        self.assertNotIn("confirmation_token", FakeMail.writes[0][1])

    async def test_direct_mode_does_not_cover_unapproved_or_delete_requests(self):
        with self.assertRaises(ValueError):
            await flow.execute_authorized("SendMessage", self.arguments, client=FakeMail)
        with self.assertRaises(ValueError):
            await flow.execute_authorized("DeleteMessage", {"message_id": "msg_test"}, user_authorized=True, client=FakeMail)
        self.assertEqual(FakeMail.writes, [])

    async def test_direct_mode_lost_response_stops_without_retry(self):
        FakeMail.fail_confirmation = True
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            await flow.execute_authorized("SendMessage", self.arguments, user_authorized=True, client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 1)
        records = list(flow.PENDING.glob("*.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["state"], "unknown")


    async def test_expired_delete_renews_identical_approval(self):
        prepared = await flow.prepare_delete_batch([{"message_id": "msg_first", "created_at": "2026-10-20T00:00:00Z"}], client=FakeMail)
        path = flow.state_path(prepared["requests"][0]["request_id"])
        record = json.loads(path.read_text())
        record["created_at"] = 0
        path.write_text(json.dumps(record))
        result = await flow.confirm_delete_batch(prepared["batch_id"], client=FakeMail)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(FakeMail.writes), 3)  # old preview, fresh challenge, exact commit

    async def test_already_trashed_delete_does_not_replay(self):
        prepared = await flow.prepare_delete_batch([{"message_id": "msg_first", "created_at": "2026-10-20T00:00:00Z"}], client=FakeMail)
        FakeMail.in_trash = True
        result = await flow.confirm_delete_batch(prepared["batch_id"], client=FakeMail)
        self.assertTrue(result["results"][0]["result"]["already_in_trash"])
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_account_changed_between_prepare_and_commit_is_rejected(self):
        prepared = await flow.prepare("SendMessage", self.arguments, client=FakeMail)
        with patch.object(flow, "account", return_value="another@qq.com"):
            with self.assertRaisesRegex(RuntimeError, "identity"):
                await flow.confirm(prepared["request_id"], client=FakeMail)
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_empty_or_negative_send_acknowledgment_stays_unknown(self):
        for payload in ({}, None, {"queued": False}, []):
            class Unacknowledged(FakeMail):
                async def raw_call(self, tool, arguments):
                    self.writes.append((tool, dict(arguments)))
                    return {"structuredContent": payload}
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                await flow.execute_authorized("SendMessage", self.arguments, user_authorized=True, client=Unacknowledged, operation_id="bad-"+str(len(FakeMail.writes)))
        records = [json.loads(p.read_text()) for p in flow.PENDING.glob("*.json")]
        self.assertEqual(len(records), 4)
        self.assertTrue(all(r["state"] == "unknown" for r in records))
        self.assertEqual(len(FakeMail.writes), 4)

    async def test_negative_delete_acknowledgment_is_not_completed(self):
        prepared = await flow.prepare("DeleteMessage", {"message_id": "msg_first"}, client=FakeMail)
        class NoDeleteAck(FakeMail):
            async def raw_call(self, tool, arguments):
                return {"structuredContent": {"message_id": "msg_first", "deleted": False}}
        with self.assertRaisesRegex(RuntimeError, "acknowledgment"):
            await flow.confirm(prepared["request_id"], client=NoDeleteAck)
        self.assertEqual(json.loads(flow.state_path(prepared["request_id"]).read_text())["state"], "unknown")

    async def test_prepare_response_loss_has_durable_unknown_receipt(self):
        class LostPrepare(FakeMail):
            async def raw_call(self, tool, arguments):
                self.writes.append((tool, dict(arguments)))
                raise asyncio.TimeoutError("lost response with sensitive request data")
        with self.assertRaisesRegex(RuntimeError, "Preparation outcome is unknown") as caught:
            await flow.prepare("SendMessage", self.arguments, client=LostPrepare)
        self.assertNotIn("sensitive", str(caught.exception))
        paths = list(flow.PENDING.glob("*.json"))
        self.assertEqual(len(paths), 1)
        record = json.loads(paths[0].read_text())
        self.assertEqual(record["state"], "unknown")
        self.assertIn(record["request_id"], str(caught.exception))
        replay = await flow.confirm(record["request_id"], client=FakeMail)
        self.assertEqual(replay["state"], "unknown")
        self.assertEqual(len(FakeMail.writes), 1)

    async def test_missing_or_invalid_batch_date_is_rejected_before_network(self):
        for item in ({"message_id": "msg_first"}, {"message_id": "msg_first", "created_at": "bad"},
                     {"message_id": "msg_first", "created_at": "2026-10-20"}, {}, "bad item"):
            with self.assertRaises(ValueError):
                await flow.prepare_delete_batch([item], client=FakeMail)
        self.assertEqual(FakeMail.writes, [])
        self.assertFalse(flow.PENDING.exists())

    async def test_read_endpoint_error_does_not_return_a_success_payload(self):
        from qq_mail import CodexMail, ToolError
        from unittest.mock import AsyncMock
        mail = CodexMail()
        mail.raw_call = AsyncMock(return_value={"structuredContent": {"code": 403, "error": "denied"}})
        with self.assertRaises(ToolError):
            await mail.call("ListMessages", {})


if __name__ == "__main__":
    unittest.main()
