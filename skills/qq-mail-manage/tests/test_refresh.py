"""Synthetic credentials and mocked HTTPS only; no real mail or refresh requests."""
import base64
import contextlib
import io
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mail_config as config
import mail_credentials as creds
import onboard
import qq_mail as bridge
from test_env_auth import FAKE_CODEX
A, R, N, RN, S = ["synthetic-"+x+"-DO-NOT-USE" for x in ("old-access", "old-refresh", "new-access", "new-refresh", "client-secret")]

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="qq-refresh-test-")
        self.root=Path(self.temp.name).resolve(); self.private=self.root/"private"; self.private.mkdir(mode=0o700)
        self.path=self.private/"bundle.json"
        self.env=patch.dict(os.environ, {"PATH":os.defpath,"CODEX_HOME":str(self.root/"codex"),"QQ_MAIL_HOME":str(self.root/"mail"),"QQ_MAIL_PROFILE":"cloud"},clear=True); self.env.start()
        self.bundle={"access_token":A,"refresh_token":R,"client_id":"synthetic-client","token_type":"Bearer","scope":"mail:read mail:send","expires_at":time.time()-1,"revision":"initial","refresh_state":"ready"}
        self.save(self.bundle)
        self.settings=config.settings_from({"profile":"cloud","account":"target@qq.com","server":"qq-cloud","mode":"read_send","auth_mode":"env_token","credential_source":"private_file","credential_file":str(self.path),"refresh_policy":"auto","client_auth_method":"none"})
        self.reply={"access_token":N,"refresh_token":RN,"expires_in":3600,"token_type":"Bearer"}
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def save(self,record): creds.atomic_record(self.path,record)
    def load(self): return json.loads(self.path.read_text())
    def changed(self,**kw): return config.settings_from({**self.settings.as_dict(),**kw})
    def test_unexpired_no_refresh(self):
        self.save({**self.bundle,"expires_at":time.time()+10000})
        with patch.object(creds,"exchange") as exchange:
            self.assertEqual(creds.access_token(self.settings),A); exchange.assert_not_called()
    def test_near_expiry_single_rotation_atomic_bundle(self):
        self.save({**self.bundle,"expires_at":time.time()+60})
        with patch.object(creds,"exchange",return_value=self.reply) as exchange:
            self.assertEqual(creds.access_token(self.settings),N); self.assertEqual(creds.access_token(self.settings),N); exchange.assert_called_once()
        saved=self.load(); self.assertEqual(saved["refresh_token"],RN); self.assertEqual(saved["access_token"],N)
        self.assertGreater(saved["expires_at"],time.time()+3500); self.assertEqual(saved["refresh_state"],"ready")
        self.assertEqual(saved["client_id"],self.bundle["client_id"]); self.assertNotEqual(saved["revision"],"initial")
        self.assertEqual(self.path.stat().st_mode&0o777,0o600); self.assertFalse(list(self.private.glob(".credential-*")))
    def test_no_rotation_preserves_refresh_and_scope(self):
        payload={k:v for k,v in self.reply.items() if k!="refresh_token"}
        with patch.object(creds,"exchange",return_value=payload): creds.access_token(self.settings)
        self.assertEqual(self.load()["refresh_token"],R); self.assertEqual(self.load()["scope"],self.bundle["scope"])
    def test_rejection_timeout_loss_barrier_no_retry(self):
        for reason in ("invalid_grant","HTTP 401","timeout unknown","response lost"):
            self.save(self.bundle)
            with patch.object(creds,"exchange",side_effect=creds.CredentialError(reason)) as exchange:
                with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
                with self.assertRaisesRegex(creds.CredentialError,"pending"): creds.access_token(self.settings)
                exchange.assert_called_once()
            self.assertEqual(self.load()["refresh_state"],"pending")
    def test_rotation_interruption_blocks_restart(self):
        with patch.object(creds,"exchange",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): creds.access_token(self.settings)
        with patch.object(creds,"exchange") as exchange:
            with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
            exchange.assert_not_called()
    def test_final_save_failure_keeps_pending(self):
        original=creds.FileStore.cas
        def broken(store,old,new):
            if new["refresh_state"]=="ready": raise OSError("disk full")
            return original(store,old,new)
        with patch.object(creds.FileStore,"cas",broken),patch.object(creds,"exchange",return_value=self.reply):
            with self.assertRaisesRegex(OSError,"disk full"): creds.access_token(self.settings)
        self.assertEqual(self.load()["refresh_state"],"pending")
    def test_file_error_after_visible_save_is_not_ack_recovered(self):
        original=creds.FileStore.cas
        def lost(store,old,new):
            original(store,old,new)
            if new["refresh_state"]=="ready": raise OSError("lost ack")
            return True
        with patch.object(creds.FileStore,"cas",lost),patch.object(creds,"exchange",return_value=self.reply) as exchange:
            with self.assertRaisesRegex(OSError,"lost ack"): creds.access_token(self.settings)
            exchange.assert_called_once()
    def test_claim_save_failure_no_network(self):
        with patch.object(creds.FileStore,"cas",side_effect=OSError("disk full")),patch.object(creds,"exchange") as exchange:
            with self.assertRaises(OSError): creds.access_token(self.settings)
            exchange.assert_not_called()
    def test_stale_values_cannot_overwrite_newer(self):
        self.save({**self.bundle,"revision":"newer"})
        with self.assertRaisesRegex(creds.CredentialError,"overwrite newer"): creds.FileStore(self.path).cas(self.bundle,self.bundle)
        self.assertEqual(self.load()["revision"],"newer")
    def test_reread_inside_lock(self):
        @contextlib.contextmanager
        def winner(store):
            self.save({**self.bundle,"access_token":N,"expires_at":time.time()+10000,"revision":"winner"}); yield
        with patch.object(creds,"store_lock",winner),patch.object(creds,"exchange") as exchange:
            self.assertEqual(creds.access_token(self.settings),N); exchange.assert_not_called()
    def test_two_independent_processes_refresh_once(self):
        worker='''import json,sys,time
sys.path.insert(0,sys.argv[1])
import mail_credentials as c,mail_config as m
from pathlib import Path
settings=m.settings_from(json.loads(sys.argv[2]))
def exchange(record,method):
 p=Path(sys.argv[3]);p.write_text(p.read_text()+"call\\n" if p.exists() else "call\\n");time.sleep(.2)
 return {"access_token":"synthetic-new-access-DO-NOT-USE","refresh_token":"synthetic-new-refresh-DO-NOT-USE","token_type":"Bearer","expires_in":3600}
c.exchange=exchange
assert c.access_token(settings)=="synthetic-new-access-DO-NOT-USE"
print("ok")
'''
        counter=self.private/"calls"; command=[sys.executable,"-c",worker,str(Path(config.__file__).parent),json.dumps(self.settings.as_dict()),str(counter)]
        processes=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        for proc in processes:
            out,err=proc.communicate(timeout=15); self.assertEqual(proc.returncode,0,err); self.assertEqual(out.strip(),"ok")
        self.assertEqual(counter.read_text(),"call\n"); self.assertEqual(self.load()["refresh_token"],RN)
    def test_private_file_and_directory_permissions(self):
        for mode in (0o644,0o660):
            self.path.chmod(mode)
            with patch.object(creds,"exchange") as exchange:
                with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
                exchange.assert_not_called()
        self.path.chmod(0o600); self.private.chmod(0o755)
        with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
        self.private.chmod(0o700)
    def test_symlink_and_hardlink_rejected(self):
        real=self.private/"original"; self.path.rename(real); self.path.symlink_to(real)
        with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
        self.path.unlink(); os.link(real,self.path)
        with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
    def test_wrong_owner_rejected(self):
        info=self.path.stat()
        fake=type("Info",(),{"st_uid":os.getuid()+1,"st_mode":info.st_mode,"st_nlink":1})()
        with patch.object(Path,"lstat",return_value=fake),patch.object(Path,"resolve",return_value=self.path):
            with self.assertRaises(creds.CredentialError): creds.private_path(self.path)
    def test_lock_permissions_and_symlink_rejected(self):
        lock=self.path.with_name(self.path.name+".lock"); lock.write_text(""); lock.chmod(0o644)
        with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
        lock.unlink(); lock.symlink_to(self.path)
        with self.assertRaises(OSError): creds.access_token(self.settings)
    def test_invalid_bundles_no_network(self):
        for key,val in (("expires_at",float("nan")),("expires_at",True),("expires_at",-1),("refresh_token",""),("client_id",""),("scope",""),("token_type","MAC"),("revision","")):
            self.save({**self.bundle,key:val})
            with patch.object(creds,"exchange") as exchange:
                with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
                exchange.assert_not_called()
    def test_bad_success_payload_remains_pending(self):
        for change in ({"access_token":""},{"expires_in":"3600"},{"expires_in":float("inf")},{"expires_in":True},{"token_type":"MAC"},{"scope":""},{"refresh_token":""}):
            self.save(self.bundle)
            with patch.object(creds,"exchange",return_value={**self.reply,**change}):
                with self.assertRaises(creds.CredentialError): creds.access_token(self.settings)
            self.assertEqual(self.load()["refresh_state"],"pending")
    def test_env_full_bundle_host_refresh_responsibility(self):
        settings=self.changed(credential_source="env",credential_file=None,refresh_policy="host",client_auth_method=None)
        values={creds.ENV_FIELDS[k]:str(v) for k,v in self.bundle.items() if k in creds.ENV_FIELDS}
        with patch.dict(os.environ,values),patch.object(creds,"exchange") as exchange:
            self.assertEqual(creds.env_record(settings)["refresh_token"],R)
            with self.assertRaisesRegex(creds.CredentialError,"host must atomically"): creds.access_token(settings)
            os.environ["QQ_MAIL_EXPIRES_AT"]=str(time.time()+10000); self.assertEqual(creds.access_token(settings),A); exchange.assert_not_called()
    def test_public_metadata_is_not_redacted_from_getme(self):
        settings=self.changed(credential_source="env",credential_file=None,refresh_policy="host",client_auth_method=None,
                              credential_env_vars={"scope":"CUSTOM_SCOPE"})
        config.write_private(config.profile_path(),settings.as_dict())
        with patch.dict(os.environ,{"QQ_MAIL_ACCESS_TOKEN":A,"QQ_MAIL_REFRESH_TOKEN":R,
                                   "CUSTOM_SCOPE":"mail:read","QQ_MAIL_TOKEN_TYPE":"Bearer","QQ_MAIL_CLIENT_ID":"synthetic-client"}):
            context={"scopes":["mail:read"],"token_type":"Bearer","client_id":"synthetic-client"}
            self.assertEqual(config.redact(context),context)
            self.assertEqual(config.redact(R),"[REDACTED]")
    def test_source_switch_clears_inapplicable_old_refresh_config(self):
        config.write_private(config.profile_path(),self.settings.as_dict())
        changed=onboard.configure("target@qq.com","read_send",credential_source="env")
        self.assertEqual(changed.credential_source,"env"); self.assertIsNone(changed.credential_file)
        self.assertEqual(changed.refresh_policy,"host"); self.assertIsNone(changed.client_auth_method)
    def test_broken_unrelated_profile_does_not_break_redaction_or_isolation(self):
        config.write_private(config.profile_path("unrelated"),{"token_env_var":[],
            "credential_env_vars":{"refresh_token":[],"client_secret":{}}})
        self.assertEqual(config.redact({"state":"ok"}),{"state":"ok"})
        with patch.dict(os.environ,{"QQ_MAIL_REFRESH_TOKEN":R}):
            self.assertNotIn("QQ_MAIL_REFRESH_TOKEN",config.subprocess_env())
            self.assertEqual(config.redact(R),"[REDACTED]")
    def test_custom_secret_names_stripped_and_redacted(self):
        settings=self.changed(credential_source="env",credential_file=None,refresh_policy="host",client_auth_method=None,credential_env_vars={"refresh_token":"CUSTOM_REFRESH","client_secret":"CUSTOM_SECRET"})
        config.write_private(config.profile_path(),settings.as_dict())
        with patch.dict(os.environ,{"QQ_MAIL_ACCESS_TOKEN":A,"CUSTOM_REFRESH":R,"CUSTOM_SECRET":S}):
            child=config.subprocess_env(settings,for_mcp=True); self.assertEqual(child["QQ_MAIL_ACCESS_TOKEN"],A)
            for key in ("CUSTOM_REFRESH","CUSTOM_SECRET"): self.assertNotIn(key,child)
            self.assertNotIn("QQ_MAIL_ACCESS_TOKEN",config.subprocess_env())
            for secret in (A,R,S): self.assertNotIn(secret,config.redact(secret))
    def test_file_secret_not_in_profile_or_helper(self):
        creds.remember({**self.bundle,"client_secret":S}); config.write_private(config.profile_path(),self.settings.as_dict())
        with patch.object(creds,"exchange",return_value=self.reply): child=config.subprocess_env(self.settings,for_mcp=True)
        self.assertEqual(child["QQ_MAIL_ACCESS_TOKEN"],N); self.assertNotIn("QQ_MAIL_REFRESH_TOKEN",child)
        self.assertNotIn("QQ_MAIL_ACCESS_TOKEN",config.subprocess_env(self.settings))
        for secret in (A,R,N,RN,S):
            self.assertNotIn(secret,config.profile_path().read_text()); self.assertNotIn(secret,json.dumps(config.redact({"error":secret})))
    def test_original_auth_methods_and_pinned_https_request(self):
        owner=self
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,limit): return json.dumps(owner.reply).encode()
        for method in creds.CLIENT_AUTH:
            with patch.object(creds,"build_opener") as build:
                build.return_value.open.return_value=Response(); creds.exchange({**self.bundle,"client_secret":S},method)
                request=build.return_value.open.call_args.args[0]; self.assertEqual(request.full_url,creds.TOKEN_ENDPOINT); self.assertEqual(request.method,"POST")
                self.assertEqual(build.return_value.open.call_args.kwargs["timeout"],20); fields=parse_qs(request.data.decode())
                self.assertEqual(fields["refresh_token"],[R]); self.assertNotIn("access_token",fields); self.assertNotIn("scope",fields)
                if method=="client_secret_basic":
                    self.assertEqual(base64.b64decode(request.get_header("Authorization")[6:]).decode(),"synthetic-client:"+S); self.assertNotIn("client_secret",fields)
                else:
                    self.assertEqual(fields["client_id"],["synthetic-client"]); self.assertEqual("client_secret" in fields,method=="client_secret_post")
                self.assertTrue(any(isinstance(arg,creds.NoRedirect) for arg in build.call_args.args))
    def test_redirect_rejection_invalid_grant_timeout_redacted_no_retry(self):
        self.assertIsNone(creds.NoRedirect().redirect_request(None,None,302,"",{},"https://example.com"))
        for error in (TimeoutError(R),http.client.IncompleteRead(R.encode()),HTTPError(creds.TOKEN_ENDPOINT,307,R,{},io.BytesIO(b"")),HTTPError(creds.TOKEN_ENDPOINT,400,S,{},io.BytesIO(json.dumps({"error":"invalid_grant","description":R}).encode()))):
            with patch.object(creds,"build_opener") as build:
                build.return_value.open.side_effect=error
                with self.assertRaises(creds.CredentialError) as caught: creds.exchange(self.bundle,"none")
                self.assertNotIn(R,str(caught.exception)); self.assertNotIn(S,str(caught.exception)); build.return_value.open.assert_called_once()
    def test_basic_auth_form_encoding_special_characters(self):
        with patch.object(creds,"build_opener") as build:
            build.return_value.open.side_effect=TimeoutError()
            with self.assertRaises(creds.CredentialError):
                creds.exchange({**self.bundle,"client_id":"client +:","client_secret":"secret +:"},"client_secret_basic")
            request=build.return_value.open.call_args.args[0]
            self.assertEqual(base64.b64decode(request.get_header("Authorization")[6:]).decode(),"client+%2B%3A:secret+%2B%3A")
    def test_legacy_compatibility_and_reconfigure_preserves_source(self):
        old={"profile":"cloud","account":"target@qq.com","server":"qq-cloud","mode":"read_send"}; self.assertEqual(config.settings_from(old).auth_mode,"oauth_keyring")
        old.update(auth_mode="env_token",token_env_var="LEGACY_ACCESS"); settings=config.settings_from(old); self.assertEqual(settings.credential_source,"env")
        with patch.dict(os.environ,{"LEGACY_ACCESS":A}): self.assertEqual(creds.access_token(settings),A)
        options={k:v for k,v in self.settings.as_dict().items() if k in ("credential_source","credential_file","refresh_policy","client_auth_method")}
        configured=onboard.configure("target@qq.com","read_send",auth_mode="env_token",**options)
        self.assertEqual(onboard.configure("target@qq.com","read_send"),configured)
    def test_auto_needs_durable_store_explicit_original_method(self):
        for change in ({"client_auth_method":None},{"credential_source":"env","credential_file":None},{"credential_file":None},{"client_auth_method":"guess"},{"refresh_skew":True},{"credential_env_vars":{"refresh_token":"QQ_MAIL_ACCESS_TOKEN"}},{"credential_env_vars":{"refresh_token":"RUST_LOG"}}):
            with self.assertRaises(ValueError): self.changed(**change)
    def test_repository_file_rejected(self):
        with self.assertRaisesRegex(ValueError,"outside the skill"): self.changed(credential_file=str(Path(__file__).resolve().parents[1]/"unsafe.json"))
    def test_host_cas_protocol_and_sanitized_errors(self):
        command=self.root/"adapter"; command.write_text('''#!/usr/bin/env python3
import fcntl,json,os,sys
from pathlib import Path
assert all(k not in os.environ for k in ("QQ_MAIL_ACCESS_TOKEN","QQ_MAIL_REFRESH_TOKEN","QQ_MAIL_CLIENT_SECRET"))
p=Path(os.environ["FIXTURE_STORE"]); request=json.load(sys.stdin)
with (p.parent/"host.lock").open("w") as lock:
 fcntl.flock(lock,fcntl.LOCK_EX); record=json.loads(p.read_text())
 if request["operation"]=="load": print(json.dumps({"record":record}))
 else:
  saved=record["revision"]==request["expected_revision"]
  if saved: p.write_text(json.dumps(request["record"]))
  print(json.dumps({"saved":saved}))
'''); command.chmod(0o700)
        settings=self.changed(credential_source="host_command",credential_file=None,credential_command=str(command))
        with patch.dict(os.environ,{"PATH":str(Path(sys.executable).parent)+os.pathsep+os.defpath,"FIXTURE_STORE":str(self.path),"QQ_MAIL_ACCESS_TOKEN":A,"QQ_MAIL_REFRESH_TOKEN":R,"QQ_MAIL_CLIENT_SECRET":S}):
            with patch.object(creds,"exchange",return_value=self.reply): self.assertEqual(creds.access_token(settings),N)
            store=creds.HostStore(str(command)); self.assertFalse(store.cas(self.bundle,self.bundle))
            with patch.object(creds.subprocess,"run",side_effect=subprocess.CalledProcessError(1,[str(command)],output=R,stderr=S)):
                with self.assertRaises(creds.CredentialError) as caught: store.load()
                self.assertNotIn(R,str(caught.exception)); self.assertNotIn(S,str(caught.exception))
    def test_host_cas_conflict_no_network(self):
        settings=self.changed(credential_source="host_command",credential_file=None,credential_command="/synthetic/adapter")
        with patch.object(creds.HostStore,"load",return_value=self.bundle),patch.object(creds.HostStore,"cas",return_value=False),patch.object(creds,"exchange") as exchange:
            with self.assertRaisesRegex(creds.CredentialError,"Concurrent"): creds.access_token(settings)
            exchange.assert_not_called()

class RefreshIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_injected_read_bundle_allows_verified_read(self):
        fixture=RefreshTests(); fixture.setUp()
        try:
            binary=fixture.root/"bin/codex"; binary.parent.mkdir(); binary.write_text(FAKE_CODEX); binary.chmod(0o700)
            events=fixture.root/"events"
            settings=config.settings_from({**fixture.settings.as_dict(),"mode":"read","credential_source":"env",
                "credential_file":None,"refresh_policy":"host","client_auth_method":None})
            config.write_private(config.profile_path(),settings.as_dict())
            values={"PATH":str(binary.parent)+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+os.defpath,
                "FIXTURE_EVENTS":str(events),"FIXTURE_MODE":"read","FIXTURE_AUTH":"env_token",
                "QQ_MAIL_ACCESS_TOKEN":A,"QQ_MAIL_REFRESH_TOKEN":R,"QQ_MAIL_CLIENT_ID":"synthetic-client",
                "QQ_MAIL_TOKEN_TYPE":"Bearer","QQ_MAIL_SCOPE":"mail:read","QQ_MAIL_EXPIRES_AT":str(time.time()+10000)}
            with patch.dict(os.environ,values),patch.object(bridge,"reserve_call_slot",new=AsyncMock()),patch.object(creds,"exchange") as exchange:
                async with bridge.CodexMail() as mail:
                    self.assertEqual(mail.status["scopes"],["mail:read"])
                    result=await mail.call("ListMessages",{"alias_id":mail.alias_id})
                    self.assertEqual(result["data"],[])
                exchange.assert_not_called()
        finally: fixture.tearDown()
    async def test_refreshed_getme_must_match_account_and_scopes(self):
        fixture=RefreshTests(); fixture.setUp()
        try:
            binary=fixture.root/"bin/codex"; binary.parent.mkdir(); binary.write_text(FAKE_CODEX); binary.chmod(0o700); events=fixture.root/"events"
            with patch.dict(os.environ,{"PATH":str(binary.parent)+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+os.defpath,"FIXTURE_EVENTS":str(events),"FIXTURE_MODE":"read_send","FIXTURE_AUTH":"env_token"}),patch.object(bridge,"reserve_call_slot",new=AsyncMock()):
                config.write_private(config.profile_path(),fixture.settings.as_dict())
                with patch.object(creds,"exchange",return_value=fixture.reply) as exchange:
                    for case in ("wrong","missing","wide"):
                        os.environ["FIXTURE_CASE"]=case
                        with self.assertRaises(RuntimeError):
                            async with bridge.CodexMail(): self.fail("Unverified mail workflow")
                    exchange.assert_called_once()
                self.assertTrue(all(e.get("tool","GetMe")=="GetMe" for e in [json.loads(line) for line in events.read_text().splitlines()]))
                self.assertEqual(fixture.load()["access_token"],N); os.environ["FIXTURE_CASE"]="ok"
                result=onboard.doctor(fixture.settings); self.assertEqual(result["credential_source"],"private_file")
                for key in ("store_inspected","refresh_attempted","currently_verified"): self.assertFalse(result[key])
        finally: fixture.tearDown()

if __name__=="__main__": unittest.main()
