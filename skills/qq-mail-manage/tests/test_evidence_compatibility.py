"""Actual sanitized HTML pair and synthetic evidence. Never connects to real mail."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import onboard
import mail_config as config
import qq_mail_write as flow
import verification_rules as rules
from test_operation_receipts import OperationReceiptTests
from test_write_flow import FakeMail
FIXTURES=Path(__file__).parent/"fixtures"
ROOT=Path(__file__).resolve().parents[1]


def attachment(name="invoice.pdf",mime="application/pdf",data=b"%PDF-synthetic-invoice"):
    return {"filename":name,"content_type":mime,"content":base64.b64encode(data).decode(),
            "size":len(data),"sha1":hashlib.sha1(data).hexdigest()}


class BodyContractTests(unittest.TestCase):
    def setUp(self):
        self.before=(FIXTURES/"01-before-send.sanitized.html").read_text()
        self.after=(FIXTURES/"02-qq-sent.sanitized.html").read_text()
        self.intent={"body":self.before,"body_format":"HTML"}
        self.obs={"stage":"sent","provider":"qq","body_format":"HTML","body":self.after}

    def test_fixture_hashes_and_only_observed_prefix(self):
        self.assertEqual(rules.sha256(self.before),"ff4f3160a10ab4d83004ce46fd0a73c16d7085e5129eee823ebff3d64e175dc2")
        self.assertEqual(rules.sha256(self.after),"07a6f7eb45544f80e47082d7edd57afe8bff919ad9f4924e7e508fd63e27189d")
        self.assertEqual(self.before.replace("<style>.qmbox ","<style>.qmbox .qmbox ",1),self.after)

    def test_strict_default_rejects_css_difference(self):
        with self.assertRaises(rules.VerificationFailure) as e:rules.match_body(self.intent,self.obs)
        self.assertEqual(e.exception.code,"html_changed")

    def test_exact_and_explicit_qq_scope_audited(self):
        self.assertEqual(rules.match_body(self.intent,{**self.obs,"body":self.before})["rule"],"exact")
        result=rules.match_body(self.intent,self.obs,allow_qq_style_scope=True)
        self.assertEqual(result["rule"],"qq-style-scope-v1")
        self.assertEqual(result["selector_prefixes_added"],1)
        self.assertEqual(result["normalized_expected_sha256"],result["observed_sha256"])
        self.assertNotEqual(result["expected_sha256"],result["observed_sha256"])

    def test_wrong_source_format_or_extra_scope_cannot_use_rule(self):
        for changes in ({"stage":"recipient","provider":"gmail"},{"provider":"other"},{"body_format":"PLAIN"},
                        {"body":self.after.replace(".qmbox .qmbox ",".qmbox .qmbox .qmbox ")}):
            with self.subTest(changes=list(changes)),self.assertRaises(rules.VerificationFailure):
                rules.match_body(self.intent,{**self.obs,**changes},allow_qq_style_scope=True)

    def test_amount_link_declaration_whitespace_and_html_changes_fail(self):
        for actual in (self.after.replace("[金额已脱敏]","123.45"),self.after.replace("#redacted-link","https://example.invalid/changed",1),
                       self.after.replace("#fff","#000",1),self.after.replace("<table"," <table",1),
                       self.after.replace("</table>","</table><img src='data:,'>",1)):
            self.assertNotEqual(actual,self.after)
            with self.assertRaises(rules.VerificationFailure):rules.match_body(self.intent,{**self.obs,"body":actual},allow_qq_style_scope=True)

    def test_real_style_only_and_conservative_selector_syntax(self):
        for body in ("<!-- <style>a{color:red}</style> -->","<style>@media screen{a{color:red}}</style>",
                     "<style>a:visited{color:red}</style>","<style>a{color:red}","<style>/* comment */ a{color:red}</style>"):
            self.assertIsNone(rules.qq_scoped_html(body))
        self.assertEqual(rules.qq_scoped_html("x\r\ny\v<style>a:hover { color:red; }</style>z")[0],
                         "x\r\ny\v<style>.qmbox a:hover { color:red; }</style>z")


class AttachmentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.intent={"attachments":[attachment(),attachment("invoice.xml","application/xml",b"<invoice>123</invoice>")]}
        self.obs={"stage":"recipient","provider":"gmail","attachments":copy.deepcopy(self.intent["attachments"])}

    def test_exact_complete_bytes_and_sha256(self):
        self.obs["attachments"].reverse()
        result=rules.match_attachments(self.intent,self.obs)
        self.assertTrue(all(x["rule"]=="exact" and x["complete_bytes_equal"] and len(x["observed_sha256"])==64 for x in result))

    def test_default_rejects_mime_and_explicit_fallback_keeps_both(self):
        for a in self.obs["attachments"]:a["content_type"]="application/octet-stream"
        with self.assertRaises(rules.VerificationFailure) as e:rules.match_attachments(self.intent,self.obs)
        self.assertEqual(e.exception.code,"attachment_mime_changed")
        result=rules.match_attachments(self.intent,self.obs,allow_gmail_octet_stream=True)
        self.assertTrue(all(x["rule"]=="gmail-octet-stream-v1" for x in result))
        self.assertEqual({x["expected_mime"] for x in result},{"application/pdf","application/xml"})
        self.assertEqual({x["observed_mime"] for x in result},{"application/octet-stream"})

    def test_only_supported_gmail_recipient_mime(self):
        for original,observed,stage,provider in (("image/png","application/octet-stream","recipient","gmail"),
                ("application/pdf","text/plain","recipient","gmail"),("application/pdf","application/octet-stream","sent","qq"),
                ("application/pdf","application/octet-stream","recipient","other")):
            with self.subTest(provider=provider,stage=stage),self.assertRaises(rules.VerificationFailure):
                rules.match_attachments({"attachments":[attachment(mime=original)]},
                    {"stage":stage,"provider":provider,"attachments":[attachment(mime=observed)]},allow_gmail_octet_stream=True)

    def test_missing_extra_renamed_or_changed_byte_fail(self):
        for attachments in (self.obs["attachments"][:1],self.obs["attachments"]+[attachment("extra.pdf")],
                            [attachment("renamed.pdf"),self.obs["attachments"][1]],
                            [attachment(data=b"%PDF-synthetic-invoicX"),self.obs["attachments"][1]]):
            with self.assertRaises(rules.VerificationFailure):
                rules.match_attachments(self.intent,{**self.obs,"attachments":attachments},allow_gmail_octet_stream=True)

    def test_invalid_digest_encoding_size_and_limit_fail(self):
        for update in ({"sha1":"0"*40},{"sha256":"0"*64},{"size":-1},{"size":True},{"size":1048577},{"content":"!bad"},{"content":""}):
            with self.subTest(update=update),self.assertRaises(rules.VerificationFailure):rules.decode_attachment({**attachment(),**update})
        rules.decode_attachment(attachment(data=b"a"*1048576))

    def test_repeated_names_mixed_exact_and_fallback_pair_by_content(self):
        intent={"attachments":[attachment(mime="application/pdf"),attachment(mime="application/xml")]}
        obs={"stage":"recipient","provider":"gmail","attachments":[attachment(mime="application/pdf"),attachment(mime="application/octet-stream")]}
        result=rules.match_attachments(intent,obs,allow_gmail_octet_stream=True)
        self.assertEqual(sorted(x["rule"] for x in result),["exact","gmail-octet-stream-v1"])

    def test_digests_optional_bytes_required(self):
        self.obs["attachments"][0].pop("sha1")
        self.obs["attachments"][1]["sha256"]=rules.sha256(b"<invoice>123</invoice>")
        rules.match_attachments(self.intent,self.obs)
        self.obs["attachments"][0].pop("content")
        with self.assertRaises(rules.VerificationFailure):rules.match_attachments(self.intent,self.obs)


class ReceiptEvidenceTests(unittest.IsolatedAsyncioTestCase):
    _fixture_set_up=OperationReceiptTests.setUp

    def setUp(self):
        # Prior auth tests intentionally remember short synthetic secrets. Isolate
        # that process-global registry from the independently supplied HTML pair.
        secret_registry=patch.object(config,"_runtime_secrets",set())
        secret_registry.start();self.addCleanup(secret_registry.stop)
        self._fixture_set_up()

    tearDown=OperationReceiptTests.tearDown
    send=OperationReceiptTests.send
    observation=OperationReceiptTests.observation

    async def test_qq_body_gmail_mime_preserve_actual_bodies_and_diff(self):
        before=(FIXTURES/"01-before-send.sanitized.html").read_text()
        after=(FIXTURES/"02-qq-sent.sanitized.html").read_text()
        self.args.update(body=before,body_format="HTML",attachments=[attachment()])
        rid=(await self.send())["request_id"]
        sent={**self.observation(),"body":after,"body_format":"HTML"}
        with self.assertRaises(rules.VerificationFailure):flow.record_verification(rid,sent)
        self.assertEqual(flow.request_status(rid)["last_verification_attempt"]["code"],"html_changed")
        flow.record_verification(rid,sent,allow_qq_style_scope=True)
        recipient={**self.observation("recipient"),"body_format":"HTML"}
        recipient["attachments"][0]["content_type"]="application/octet-stream"
        flow.record_verification(rid,recipient,allow_gmail_octet_stream=True)
        raw=flow.read_receipt(rid)
        self.assertEqual(raw["intended"]["body"],before)
        self.assertEqual(raw["verification_observations"]["sent"]["body"],after)
        self.assertEqual(raw["verification_observations"]["recipient"]["body"],before)
        public=flow.request_status(rid)
        self.assertNotIn(before,json.dumps(public));self.assertNotIn(after,json.dumps(public))
        self.assertEqual(public["state"],"recipient_verified")
        self.assertEqual(public["evidence"]["sent"]["body"]["rule"],"qq-style-scope-v1")
        self.assertEqual(public["evidence"]["recipient"]["attachments"][0]["rule"],"gmail-octet-stream-v1")
        self.assertEqual(len(FakeMail.writes),1)

    async def test_failure_cannot_erase_verified_evidence(self):
        rid=(await self.send())["request_id"]
        good=flow.record_verification(rid,self.observation())
        with self.assertRaises(rules.VerificationFailure):flow.record_verification(rid,{**self.observation(),"body":"wrong"})
        later=flow.request_status(rid)
        self.assertEqual(later["state"],"sent_verified");self.assertEqual(later["evidence"],good["evidence"])
        self.assertEqual(later["last_verification_attempt"]["code"],"body_changed")
        self.assertEqual(flow.read_receipt(rid)["verification_observations"]["sent"]["body"],"fixture body")

    async def test_time_reason_and_user_choice_do_not_invent_received_at(self):
        rid=(await self.send())["request_id"]
        with self.assertRaises(rules.VerificationFailure) as e:flow.record_verification(rid,{**self.observation(),"time_basis":"created_at"})
        self.assertEqual(e.exception.code,"time_basis_missing")
        result=flow.record_selection(rid,"source-invoice","human-choice:turn-1",user_selected=True)
        self.assertEqual(result["selection"]["basis"],"user_selected")
        self.assertNotIn("received_at",json.dumps(result["selection"]));self.assertEqual(result["state"],"accepted")
        with self.assertRaises(rules.VerificationFailure):flow.record_selection(rid,"other","human-choice:turn-2",user_selected=True)
        self.assertEqual((await self.send())["selection"],result["selection"]);self.assertEqual(len(FakeMail.writes),1)

    async def test_no_credentials_saved(self):
        rid=(await self.send())["request_id"]
        with patch.dict(os.environ,{"QQ_MAIL_ACCESS_TOKEN":"synthetic-secret-must-not-leak"}):
            with self.assertRaises(rules.VerificationFailure):flow.record_verification(rid,{**self.observation(),"body":"synthetic-secret-must-not-leak"})
        self.assertNotIn("synthetic-secret-must-not-leak",flow.state_path(rid).read_text())

    async def test_legacy_double_link_recovered_replayed_no_connection(self):
        rid=(await self.send())["request_id"];path=flow.state_path(rid)
        temporary=path.parent/".operation-legacy-name";os.link(path,temporary)
        with patch.object(FakeMail,"__aenter__",side_effect=AssertionError("must not connect")):result=await self.send()
        self.assertEqual(result["state"],"accepted");self.assertTrue(result["receipt_recovery"]["state_unchanged"])
        self.assertFalse(temporary.exists());self.assertEqual(path.stat().st_nlink,1);self.assertEqual(len(FakeMail.writes),1)
        self.args["subject"]="changed"
        with self.assertRaises(ValueError):await self.send()

    async def test_recovery_rejects_changed_fingerprint_and_unsafe_permissions(self):
        rid=(await self.send())["request_id"];path=flow.state_path(rid)
        temporary=path.parent/".operation-legacy-name";os.link(path,temporary)
        record=json.loads(path.read_text());record["fingerprint"]="0"*64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(RuntimeError,"content mismatch"):flow.request_status(rid)
        self.assertTrue(temporary.exists())
        record["fingerprint"]=flow.fingerprint("SendMessage",record["intended"])
        path.write_text(json.dumps(record));path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,"Unsafe"):flow.request_status(rid)
        self.assertTrue(temporary.exists());self.assertEqual(len(FakeMail.writes),1)

    async def test_receipt_size_failure_preserves_original_readable_status(self):
        rid=(await self.send())["request_id"]
        before=flow.state_path(rid).read_bytes()
        with flow.receipt_lock(rid) as lock:
            record=flow.read_receipt(rid);record["oversized"]="x"*1000
            with patch.object(flow,"MAX_RECEIPT_BYTES",len(before)+50):
                with self.assertRaisesRegex(RuntimeError,"Receipt size"):flow.update_locked(lock,record)
        self.assertEqual(flow.state_path(rid).read_bytes(),before)
        self.assertEqual(flow.request_status(rid)["state"],"accepted")

    async def test_unicode_receipt_limit_matches_atomic_serialization(self):
        with patch.object(flow,"MAX_RECEIPT_BYTES",30):
            with self.assertRaisesRegex(RuntimeError,"Receipt size"):flow.receipt_payload({"body":"发票金额"*3})

    async def test_cli_structured_failure_has_no_body_or_traceback(self):
        rid=(await self.send())["request_id"]
        observation={**self.observation(),"body":"untrusted-html-do-not-print"}
        run=subprocess.run([sys.executable,str(ROOT/"scripts/qq_mail_write.py"),"--profile","delivery","record-verification",
            "--request-id",rid,"--observation-file","-"],input=json.dumps(observation),capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,1)
        self.assertEqual(json.loads(run.stderr)["verification_error"]["code"],"body_changed")
        self.assertNotIn("untrusted-html-do-not-print",run.stderr+run.stdout)
        self.assertNotIn("Traceback",run.stderr)

    async def test_external_extra_or_symlink_alias_blocked(self):
        rid=(await self.send())["request_id"];path=flow.state_path(rid)
        for kind in ("external","three","symlink"):
            aliases=[]
            try:
                if kind=="external":aliases=[self.root/"outside"];os.link(path,aliases[0])
                elif kind=="three":
                    aliases=[path.parent/".operation-a",path.parent/".operation-b"]
                    for alias in aliases:os.link(path,alias)
                else:
                    aliases=[path.parent/".operation-symlink",self.root/"outside"]
                    aliases[0].symlink_to(path);os.link(path,aliases[1])
                with self.assertRaises(RuntimeError):flow.request_status(rid)
            finally:
                for alias in aliases:alias.unlink(missing_ok=True)
        self.assertEqual(len(FakeMail.writes),1)


KILL_PROCESS=r'''
import asyncio,json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import qq_mail_write as f
stage,marker,log=sys.argv[2:]
def stop():
    Path(marker).write_text('ready');time.sleep(60)
if stage=='created':
    original=f.tempfile.mkstemp
    def created(*a,**kw):
        value=original(*a,**kw);stop();return value
    f.tempfile.mkstemp=created
elif stage=='partial':
    def partial(record,stream,**kw):stream.write('{');stream.flush();stop()
    f.json.dump=partial
elif stage=='file_synced':
    original=f.os.fsync
    def synced(fd):original(fd);stop()
    f.os.fsync=synced
elif stage in ('before_link','after_link'):
    original=f.os.link
    def linked(*a,**kw):
        if stage=='before_link':stop()
        result=original(*a,**kw)
        if stage=='after_link':stop()
        return result
    f.os.link=linked
elif stage in ('published_synced','unlinked_synced'):
    original=f.sync_directory;calls=0
    def synced(path):
        global calls
        original(path);calls+=1
        if calls==(1 if stage=='published_synced' else 2):stop()
    f.sync_directory=synced
elif stage=='unlinked':
    original=Path.unlink
    def unlinked(path,*a,**kw):
        value=original(path,*a,**kw)
        if path.name.startswith('.operation-'):stop()
        return value
    Path.unlink=unlinked
class Mail:
    alias_id='synthetic'
    def __init__(self,**kw):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    async def raw_call(self,*a):
        Path(log).write_text('send\n')
        if stage=='submitted':stop()
        return {'structuredContent':{'queued':True}}
args={'to':[{'email':'fixture@gmail.com'}],'subject':'synthetic','body':'synthetic'}
try:
    result=asyncio.run(f.execute_authorized('SendMessage',args,user_authorized=True,operation_id='crash-job',client=Mail))
    print(json.dumps(result))
except (RuntimeError,ValueError,OSError) as e:
    print(str(e),file=sys.stderr);sys.exit(3)
'''


class InitialPublicationProcessTests(unittest.TestCase):
    def test_sigkill_each_creation_phase_never_resubmits(self):
        for stage in ("created","partial","file_synced","before_link","after_link","published_synced","unlinked","unlinked_synced","submitted"):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();env=dict(os.environ,QQ_MAIL_HOME=str(root/"mail"),QQ_MAIL_PROFILE="fixture")
                with patch.dict(os.environ,env):onboard.configure("test@qq.com","read_send",auth_mode="env_token",backend="direct_http")
                marker,log=root/"marker",root/"submissions"
                base=[sys.executable,"-c",KILL_PROCESS,str(ROOT/"scripts")]
                child=subprocess.Popen(base+[stage,str(marker),str(log)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    deadline=time.monotonic()+10
                    while not marker.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue(marker.exists(),child.communicate(timeout=1) if child.poll() is not None else stage)
                    child.kill();child.communicate(timeout=5)
                finally:
                    if child.poll() is None:child.kill();child.communicate(timeout=5)
                restart=subprocess.run(base+["restart",str(marker),str(log)],env=env,capture_output=True,text=True,timeout=10)
                if stage in ("created","partial"):
                    self.assertEqual(restart.returncode,3,restart.stdout+restart.stderr);self.assertIn("Unreadable",restart.stderr)
                else:
                    self.assertEqual(restart.returncode,0,restart.stderr)
                    result=json.loads(restart.stdout);self.assertEqual(result["state"],"submitting");self.assertFalse(result.get("verification"))
                self.assertEqual(log.read_text().splitlines() if log.exists() else [],["send"] if stage=="submitted" else [])
                second=subprocess.run(base+["restart",str(marker),str(log)],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(second.returncode,restart.returncode)
                self.assertEqual(log.read_text().splitlines() if log.exists() else [],["send"] if stage=="submitted" else [])


del OperationReceiptTests  # Do not collect imported TestCase twice.
if __name__=="__main__":unittest.main()
