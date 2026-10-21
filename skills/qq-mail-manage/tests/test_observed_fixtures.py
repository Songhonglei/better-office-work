"""Replay observed provider structure with public synthetic bytes, never live mail."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import qq_mail as bridge


class ObservedFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_observed_attachment_shapes_replay_through_production_decoder_and_download(self):
        fixture=json.loads((Path(__file__).parent/"fixtures/qq-attachment-observed.json").read_text())
        mail=object.__new__(bridge.CodexMail)
        mail.alias_id="alias_fixture"
        async def raw(tool,arguments):return fixture[tool]
        mail.raw_call=AsyncMock(side_effect=raw)
        listed=await mail.call("ListAttachments",{"alias_id":mail.alias_id,"message_id":"msg_fixture"})
        self.assertEqual(listed["attachments"][0]["attachment_id"],"att_fixture")
        with tempfile.TemporaryDirectory() as temporary:
            result=await bridge.download_attachment(mail,"msg_fixture","att_fixture",Path(temporary).resolve()/"fixture.pdf")
            self.assertEqual(result["verification"]["level"],"metadata_size_and_local_digest")
            self.assertEqual(result["verification"]["server_digests_verified"],[])
            self.assertEqual(result["verification"]["sha1_source"],"local_computed")
            self.assertEqual(Path(result["path"]).read_bytes(),b"synthetic observed contract\n")
            self.assertNotIn("received_at",fixture["GetMessage"]["structuredContent"])


if __name__=="__main__":unittest.main()
