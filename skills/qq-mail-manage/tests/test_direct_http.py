"""Official MCP framing with fake HTTP workers; never contact a mail service."""
import asyncio
import base64
import hashlib
import io
import json
import os
import ssl
import subprocess
import sys
import traceback
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from urllib.request import getproxies_environment, proxy_bypass_environment
from urllib.response import addinfourl

import test_refresh as fixtures
import qq_mail_write as flow
import direct_http as http

config, onboard, bridge = fixtures.config, fixtures.onboard, fixtures.bridge
SESSION = "synthetic-mcp-session-DO-NOT-USE"


class Response:
    def __init__(self, value=None, *, status=200, kind="application/json", session=None, body=None, chunk=None):
        self.status = status
        self.headers = {"Content-Type": kind}
        if session is not None: self.headers["MCP-Session-Id"] = session
        self.stream = io.BytesIO(body if body is not None else json.dumps(value).encode())
        self.chunk = chunk
    def read(self, count): return self.stream.read(count)
    def read1(self, count): return self.stream.read(min(count, self.chunk or count))
    def __enter__(self): return self
    def __exit__(self, *_): self.stream.close()


class FakeServer:
    def __init__(self):
        self.requests = []
        self.workers = []
        self.case = "ok"
        self.sse = False
        self.protocol = http.VERSIONS[0]
        self.session = SESSION
        self.pages = False
        self.tools = [*config.READ_TOOLS, *config.WRITE_TOOLS, "UnknownTool"]
        self.scopes = ["mail:read", "mail:send", "mail:delete"]
        self.account = "target@qq.com"
        self.attach = b"synthetic invoice bytes"
    def open(self, request, timeout):
        assert request.full_url == config.ENDPOINT
        assert timeout == http.IO_SECONDS
        assert request.get_header("Authorization") in ("Bearer "+fixtures.A, "Bearer "+fixtures.N)
        message = json.loads(request.data)
        self.requests.append((message, dict(request.header_items())))
        method = message.get("method")
        if method != "initialize":
            assert request.get_header("Mcp-protocol-version") == self.protocol
            if self.session: assert request.get_header("Mcp-session-id") == self.session
        if self.case == "redirect" or (self.case == "send401" and message.get("params",{}).get("name") == "SendMessage"):
            status = 307 if self.case == "redirect" else 401
            raise HTTPError(config.ENDPOINT, status, fixtures.A+SESSION, {"Location":"https://synthetic-attacker.example"}, io.BytesIO(fixtures.R.encode()))
        if method == "initialize":
            result = {"protocolVersion":self.protocol, "capabilities":{"tools":{}}, "serverInfo":{"name":"synthetic","version":"1"}}
        elif method == "notifications/initialized":
            return Response(status=202, body=b"")
        elif method == "tools/list":
            cursor = message.get("params",{}).get("cursor")
            names = self.tools[:3] if self.pages and not cursor else self.tools[3:] if self.pages else self.tools
            result = {"tools":[{"name":name,"inputSchema":{"type":"object"}} for name in names]}
            if self.pages and not cursor: result["nextCursor"] = "synthetic-cursor"
            if self.case == "cursor_loop": result["nextCursor"] = "synthetic-cursor"
            if self.case == "bad_catalog": result = {"tools":None}
        elif method == "tools/call":
            tool = message["params"]["name"]
            if self.case == "send_timeout" and tool == "SendMessage": raise TimeoutError(fixtures.A+SESSION)
            if self.case == "session404" and tool != "GetMe":
                raise HTTPError(config.ENDPOINT,404,SESSION,{},io.BytesIO())
            if tool == "GetMe":
                data = {"scopes":self.scopes, "aliases":[{"email":self.account,"alias_id":"synthetic-alias"}],"_hints":{"echo":fixtures.A+SESSION}}
            elif tool == "SendMessage": data = {"queued":True,"_hints":{"echo":fixtures.A+SESSION}}
            elif tool == "DownloadAttachment":
                data = {"content":base64.b64encode(self.attach).decode(),"size":len(self.attach),"sha1":hashlib.sha1(self.attach).hexdigest()}
            elif tool == "ListAttachments": data = {"attachments":[{"filename":"invoice.pdf","size":len(self.attach),"sha1":hashlib.sha1(self.attach).hexdigest()}]}
            else: data = {"data":[],"pagination":{"has_more":False}}
            result = {"structuredContent":data}
            if self.case == "tool401" and tool != "GetMe":
                result = {"isError":True,"structuredContent":{"error":{"code":401,"message":fixtures.A}}}
        elif "result" in message: return Response(status=202,body=b"")
        else: raise AssertionError(method)
        envelope = {"jsonrpc":"2.0","id":message["id"],"result":result}
        if self.case == "rpc_error": envelope = {"jsonrpc":"2.0","id":message["id"],"error":{"code":-32000,"message":fixtures.A+SESSION}}
        if self.case == "mismatched_id": envelope["id"] = "wrong"
        if self.sse:
            notifications = ': keepalive\r\nid: synthetic-event\r\ndata:\r\n\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"ignored":"text"}}\r\n\r\n'
            return Response(kind="text/event-stream",session=self.session if method=="initialize" else None,
                body=(notifications+'event: message\r\ndata: '+json.dumps(envelope)+'\r\n\r\n').encode(),chunk=7)
        return Response(envelope,session=self.session if method=="initialize" else None)
    def worker(self, command, **kwargs):
        assert command[-1] == "--http-worker"
        assert "codex" not in command
        assert "QQ_MAIL_ACCESS_TOKEN" not in kwargs["env"]
        assert "QQ_MAIL_REFRESH_TOKEN" not in kwargs["env"]
        assert fixtures.A not in json.dumps(command) and SESSION not in json.dumps(command)
        assert kwargs["timeout"] <= http.WORKER_SECONDS
        payload = json.loads(kwargs["input"])
        self.workers.append(payload["message"])
        if self.case == "worker_timeout": raise subprocess.TimeoutExpired(command, 60, output=fixtures.A, stderr=SESSION)
        try:
            with patch.object(http,"build_opener") as build:
                build.return_value.open.side_effect = self.open
                reply = http.wire(payload)
                self.last_handlers = build.call_args.args
        except http.WireFailure as error:
            reply = {"ok":False,"reason":error.reason,"status":error.status,"code":error.code}
        except BaseException:
            reply = {"ok":False,"reason":"network_or_protocol_failure"}
        return subprocess.CompletedProcess(command,0,json.dumps(reply),fixtures.R+SESSION)


class DirectHTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = fixtures.RefreshTests(); self.fixture.setUp()
        self.settings = self.fixture.changed(backend="direct_http",allow_extra_delete_scope=True,
            credential_source="env",credential_file=None,refresh_policy="host",client_auth_method=None)
        config.write_private(config.profile_path(),self.settings.as_dict())
        os.environ.update(QQ_MAIL_ACCESS_TOKEN=fixtures.A,QQ_MAIL_REFRESH_TOKEN=fixtures.R)
        self.server = FakeServer()
        self.worker = patch.object(http.subprocess,"run",side_effect=self.server.worker); self.worker.start()
        self.pacing = patch.object(bridge,"reserve_call_slot",new=AsyncMock()); self.pacing.start()
    def tearDown(self):
        self.pacing.stop(); self.worker.stop(); self.fixture.tearDown()
    def records(self):
        return [json.loads(path.read_text()) for path in self.settings.state_dir.glob("transport/*.json")]
    def assert_safe_records(self):
        for path in self.settings.state_dir.rglob("*.json"):
            text = path.read_text()
            for secret in (fixtures.A,fixtures.R,SESSION): self.assertNotIn(secret,text)
        for record in self.records():
            self.assertFalse(set(record)&{"arguments","result","headers","token","session","response"})
    async def test_json_handshake_session_headers_and_no_codex(self):
        with patch.object(bridge,"codex_binary",side_effect=AssertionError("No Codex")),patch.object(bridge,"overrides",side_effect=AssertionError("No config")):
            async with bridge.CodexMail() as mail:
                self.assertEqual(mail.status["backend"],"direct_http")
                self.assertEqual(mail.status["scopes"],self.server.scopes)
                self.assertNotIn("DeleteMessage",mail.direct.available_tools)
                self.assertNotIn("UnknownTool",mail.direct.available_tools)
        methods = [entry[0].get("method") for entry in self.server.requests]
        self.assertEqual(methods,["initialize","notifications/initialized","tools/list","tools/call"])
        self.assertTrue(any(isinstance(x,http.NoRedirect) for x in self.server.last_handlers))
        self.assert_safe_records()
    async def test_sse_comments_empty_events_chunk_boundaries_and_response(self):
        self.server.sse=True
        async with bridge.CodexMail() as mail: self.assertEqual(mail.alias_id,"synthetic-alias")
        self.assert_safe_records()
    async def test_protocol_version_negotiation_supported_versions(self):
        for version in http.VERSIONS:
            self.server.protocol=version
            async with bridge.CodexMail() as mail: self.assertEqual(mail.direct.protocol,version)
    async def test_missing_session_header_is_supported(self):
        self.server.session=None
        async with bridge.CodexMail() as mail: self.assertIsNone(mail.direct.session)
    async def test_unsupported_version_stops_before_tools(self):
        self.server.protocol="1900-01-01"
        with self.assertRaisesRegex(http.DirectMCPError,"unsupported_protocol"):
            async with bridge.CodexMail(): pass
        self.assertEqual(len(self.server.requests),1)
        self.assertTrue(any(r.get("phase")=="capability_negotiation" for r in self.records()))
    async def test_tools_list_pagination_and_incomplete_catalog_rejection(self):
        self.server.pages=True
        async with bridge.CodexMail(): pass
        pages = [x[0] for x in self.server.requests if x[0].get("method")=="tools/list"]
        self.assertEqual(len(pages),2); self.assertEqual(pages[1]["params"]["cursor"],"synthetic-cursor")
        for case in ("cursor_loop","bad_catalog"):
            self.server.case=case
            with self.assertRaisesRegex(http.DirectMCPError,"incomplete_tool_catalog"):
                async with bridge.CodexMail(): pass
    async def test_wrong_account_and_unknown_scope_are_durably_rejected(self):
        self.server.account="other@qq.com"
        with self.assertRaises(RuntimeError):
            async with bridge.CodexMail(): pass
        self.server.account="target@qq.com"; self.server.scopes.append("unknown")
        with self.assertRaises(RuntimeError):
            async with bridge.CodexMail(): pass
        self.assertTrue(any(r.get("phase")=="account_scope_verification" for r in self.records()))
    async def test_read_send_delete_construction_exposure_and_execution_blocked(self):
        with self.assertRaisesRegex(RuntimeError,"Deletion requires"): bridge.CodexMail(write_tool="DeleteMessage")
        async with bridge.CodexMail() as mail:
            with self.assertRaisesRegex(RuntimeError,"Deletion requires"):
                await mail.raw_call("DeleteMessage",{"alias_id":mail.alias_id,"message_id":"synthetic"})
            with self.assertRaises(http.DirectMCPError): mail.direct.call_tool("DeleteMessage",{})
        self.assertFalse(any(x[0].get("params",{}).get("name")=="DeleteMessage" for x in self.server.requests))
    async def test_send_preserves_changed_subject_source_body_and_all_attachment_validation(self):
        content=self.server.attach
        args={"to":[{"email":"recipient@example.com"}],"subject":"Item+Invoice+1.00","body":"original body; source message synthetic-source; CNY",
              "attachments":[{"filename":"invoice.pdf","content_type":"application/pdf","size":len(content),
                              "sha1":hashlib.sha1(content).hexdigest(),"content":base64.b64encode(content).decode()}]}
        result=await flow.execute_authorized("SendMessage",args,user_authorized=True)
        self.assertEqual(result["state"],"completed")
        calls=[m[0]["params"] for m in self.server.requests if m[0].get("params",{}).get("name")=="SendMessage"]
        self.assertEqual(len(calls),1)
        for key in ("subject","body","attachments"): self.assertEqual(calls[0]["arguments"][key],args[key])
        bad={**args,"attachments":[{**args["attachments"][0],"sha1":"0"*40}]}
        previous=len(self.server.requests)
        with self.assertRaisesRegex(ValueError,"SHA-1"): await flow.execute_authorized("SendMessage",bad,user_authorized=True)
        self.assertEqual(len(self.server.requests),previous)
        self.assert_safe_records()
    async def test_timeout_or_401_send_is_unknown_and_not_replayed(self):
        args={"to":[{"email":"recipient@example.com"}],"subject":"synthetic","body":"synthetic"}
        for case in ("send_timeout","send401"):
            self.server.requests=[]; self.server.case=case
            with self.assertRaisesRegex(RuntimeError,"unknown"):
                await flow.execute_authorized("SendMessage",args,user_authorized=True)
            self.assertEqual(sum(x[0].get("params",{}).get("name")=="SendMessage" for x in self.server.requests),1)
        self.assertTrue(any(r.get("tool")=="SendMessage" and r["state"]=="unknown" for r in self.records()))
        self.assert_safe_records()
    async def test_404_does_not_reinitialize_or_replay_in_failing_operation(self):
        self.server.case="session404"
        async with bridge.CodexMail() as mail:
            with self.assertRaisesRegex(http.DirectMCPError,"session_expired"):
                await mail.call("ListMessages",{"alias_id":mail.alias_id})
            count=len(self.server.requests)
            with self.assertRaises(http.DirectMCPError): await mail.call("ListMessages",{"alias_id":mail.alias_id})
            self.assertEqual(len(self.server.requests),count)
        self.assertEqual(sum(x[0].get("method")=="initialize" for x in self.server.requests),1)
    async def test_queued_concurrent_call_observes_tool_authorization_failure(self):
        async with bridge.CodexMail() as mail:
            self.server.case="tool401"
            entered, release = asyncio.Event(), asyncio.Event()
            async def pause():
                entered.set(); await release.wait()
            with patch.object(bridge,"reserve_call_slot",side_effect=pause):
                first=asyncio.create_task(mail.call("ListMessages",{"alias_id":mail.alias_id}))
                await entered.wait()
                second=asyncio.create_task(mail.call("ListMessages",{"alias_id":mail.alias_id}))
                await asyncio.sleep(0)
                release.set()
                results=await asyncio.gather(first,second,return_exceptions=True)
            self.assertTrue(all(isinstance(result,bridge.AuthenticationError) for result in results))
        self.assertEqual(sum(x[0].get("params",{}).get("name")=="ListMessages" for x in self.server.requests),1)
        self.assert_safe_records()
    async def test_missing_required_tool_and_duplicate_catalog_stop(self):
        for names in (["GetMe"],[*config.READ_TOOLS,"GetMe"]):
            self.server.tools=names
            with self.assertRaises(http.DirectMCPError):
                async with bridge.CodexMail(): pass
        self.assertFalse(any(x[0].get("method")=="tools/call" for x in self.server.requests))
    async def test_malformed_rpc_or_rejection_has_no_raw_exception_or_response(self):
        for case in ("rpc_error","mismatched_id","redirect","worker_timeout"):
            self.server.case=case
            with self.assertRaises(http.DirectMCPError) as caught:
                async with bridge.CodexMail(): pass
            trace="".join(traceback.format_exception(caught.exception))
            for secret in (fixtures.A,fixtures.R,SESSION): self.assertNotIn(secret,trace)
        self.assert_safe_records()
    async def test_receipt_persistence_failure_forbids_network(self):
        with patch.object(http,"atomic_record",side_effect=OSError("synthetic disk error")):
            with self.assertRaisesRegex(http.DirectMCPError,"receipt_persistence_failed"):
                async with bridge.CodexMail(): pass
        self.assertFalse(self.server.requests)
    async def test_credential_failure_is_durable_without_network(self):
        os.environ.pop("QQ_MAIL_ACCESS_TOKEN")
        with self.assertRaisesRegex(http.DirectMCPError,"credential_unavailable"):
            async with bridge.CodexMail(): pass
        self.assertTrue(any(r.get("phase")=="credential_unavailable" for r in self.records()))
        self.assertFalse(self.server.requests)
    async def test_private_provider_refreshes_once_then_checks_account_before_mail(self):
        self.settings=self.fixture.changed(backend="direct_http",allow_extra_delete_scope=True)
        config.write_private(config.profile_path(),self.settings.as_dict())
        self.server.account="other@qq.com"
        with patch.object(fixtures.creds,"exchange",return_value=self.fixture.reply) as exchange:
            with self.assertRaises(RuntimeError):
                async with bridge.CodexMail(): pass
            self.server.account="target@qq.com"
            async with bridge.CodexMail() as mail:
                await mail.call("ListMessages",{"alias_id":mail.alias_id})
            exchange.assert_called_once()
        self.assertEqual(self.fixture.load()["refresh_token"],fixtures.RN)
        tools=[m[0]["params"]["name"] for m in self.server.requests if m[0].get("method")=="tools/call"]
        self.assertEqual(tools,["GetMe","GetMe","ListMessages"])
        for _,headers in self.server.requests: self.assertEqual(headers["Authorization"],"Bearer "+fixtures.N)
    async def test_final_receipt_fsync_failure_stops_even_when_record_is_visible(self):
        original=http.atomic_record
        def failed(path,record):
            original(path,record)
            if record["state"]=="completed": raise OSError("synthetic directory fsync failure")
        with patch.object(http,"atomic_record",side_effect=failed):
            with self.assertRaisesRegex(http.DirectMCPError,"receipt_persistence_failed"):
                async with bridge.CodexMail(): pass
        self.assertEqual(len(self.server.requests),1)
        self.assertTrue(any(r.get("reason")=="receipt_persistence_failed" for r in self.records()))
    def test_doctor_and_configure_require_no_codex_or_global_config(self):
        with patch.object(onboard,"codex_binary",side_effect=AssertionError()),patch.object(onboard,"overrides",side_effect=AssertionError()):
            result=onboard.doctor(); self.assertIsNone(result["codex"])
            self.assertEqual(result["transport"],"streamable_http")
            self.assertFalse(result["currently_verified"])
            self.assertEqual(onboard.configure("target@qq.com","read_send").backend,"direct_http")
        legacy=self.settings.as_dict(); legacy.pop("backend")
        self.assertEqual(config.settings_from(legacy).backend,"codex")
        with self.assertRaises(ValueError): config.settings_from({**self.settings.as_dict(),"auth_mode":"oauth_keyring","token_env_var":None})


class WireTests(unittest.TestCase):
    def payload(self):
        return {"message":{"jsonrpc":"2.0","id":"synthetic-id","method":"initialize","params":{}},
                "token":fixtures.A,"protocol":None,"session":None}
    def test_sse_utf8_multiline_and_carriage_return_line_endings(self):
        raw='\ufeff: comment\rdata: {"jsonrpc":"2.0",\rdata: "id":"synthetic-id","result":{"value":"中文"}}\r\r'
        messages=list(http.sse_messages(Response(body=raw.encode(),chunk=1)))
        self.assertEqual(messages[0]["result"]["value"],"中文")
    def test_partial_sse_event_is_not_a_response(self):
        self.assertEqual(list(http.sse_messages(Response(body=b'data: {"result":{}}'))),[])
    def test_complete_cr_event_returns_while_stream_remains_open(self):
        class OpenStream:
            def __init__(self): self.reads=0
            def read1(self, _):
                self.reads+=1
                if self.reads>1: raise TimeoutError("must dispatch before next read")
                return b'data: {"result":{}}\r\r'
        self.assertEqual(next(http.sse_messages(OpenStream())),{"result":{}})
    def test_invalid_session_content_type_id_batch_and_response_size(self):
        cases=[Response({"jsonrpc":"2.0","id":"synthetic-id","result":{}},session="bad\nheader"),
               Response({},kind="text/plain"),Response([],kind="application/json"),
               Response({"jsonrpc":"2.0","id":"other","result":{}}),Response(body=b"x"*2048)]
        reasons=["invalid_session_header","unsupported_content_type","invalid_jsonrpc","response_id_mismatch","response_too_large"]
        for response, reason in zip(cases,reasons):
            with patch.object(http,"build_opener") as build,patch.object(http,"MAX_BYTES",1024):
                build.return_value.open.return_value=response
                with self.assertRaises(http.WireFailure) as error: http.wire(self.payload())
                self.assertEqual(error.exception.reason,reason)
    def test_notification_ack_and_unsupported_server_request_rejected(self):
        for response, payload, reason in (
            (Response(status=200,body=b""),{**self.payload(),"message":{"jsonrpc":"2.0","method":"notifications/initialized"}},"invalid_notification_ack"),
            (Response({"jsonrpc":"2.0","id":"server","method":"sampling/createMessage"}),self.payload(),"unsupported_server_request"),
            (Response(kind="text/event-stream",body=b"data: "+b"x"*2048),self.payload(),"response_too_large")):
            with patch.object(http,"build_opener") as build,patch.object(http,"MAX_BYTES",1024):
                build.return_value.open.return_value=response
                with self.assertRaises(http.WireFailure) as error: http.wire(payload)
                self.assertEqual(error.exception.reason,reason)
    def test_sse_notifications_and_ping_response_use_new_post(self):
        body='data: {"jsonrpc":"2.0","id":"server-ping","method":"ping"}\n\ndata: {"jsonrpc":"2.0","id":"synthetic-id","result":{}}\n\n'
        with patch.object(http,"build_opener") as build:
            build.return_value.open.side_effect=[Response(kind="text/event-stream",body=body.encode(),session=SESSION),Response(status=202,body=b"")]
            result=http.wire(self.payload())
            self.assertTrue(result["ok"])
            self.assertEqual(build.return_value.open.call_count,2)
            ping=json.loads(build.return_value.open.call_args.args[0].data)
            self.assertEqual(ping,{"jsonrpc":"2.0","id":"server-ping","result":{}})
    def test_json_nonfinite_and_duplicate_keys_are_rejected(self):
        for raw in ('{"x":NaN}','{"x":1,"x":2}'):
            with self.assertRaises(http.WireFailure): http.strict_json(raw)
    def test_real_worker_handles_invalid_input_without_tracebacks(self):
        result=subprocess.run([sys.executable,str(Path(http.__file__)),"--http-worker"],input="not JSON",
            text=True,capture_output=True,timeout=5,env={"PATH":os.defpath})
        self.assertEqual(result.returncode,0); self.assertEqual(result.stderr,"")
        self.assertEqual(json.loads(result.stdout),{"ok":False,"reason":"network_or_protocol_failure"})
    def test_real_opener_uses_host_proxy_ca_and_blocks_all_redirects(self):
        calls=[]
        factory=ssl._create_default_https_context
        seen=[]
        def context(*args,**kwargs):
            seen.append(os.environ.get("SSL_CERT_FILE")); return factory(*args,**kwargs)
        def transport(handler,request):
            calls.append((request.host,getattr(request,"_tunnel_host",None),request.full_url,handler._context))
            body=json.dumps({"jsonrpc":"2.0","id":"synthetic-id","result":{}}).encode()
            response=addinfourl(io.BytesIO(body),{"Content-Type":"application/json","Location":"https://synthetic-attacker.example"},request.full_url,status)
            response.msg="synthetic"; return response
        with patch.dict(os.environ,{},clear=True),patch("urllib.request.getproxies",side_effect=getproxies_environment), \
             patch("urllib.request.proxy_bypass",side_effect=proxy_bypass_environment), \
             patch("urllib.request.HTTPSHandler.https_open",transport), \
             patch.object(ssl,"_create_default_https_context",side_effect=context):
            status=200
            self.assertTrue(http.wire(self.payload())["ok"])
            self.assertEqual(calls[-1][:2],("api.mail.qq.com",None))
            with patch.dict(os.environ,{"https_proxy":"http://synthetic-proxy.example:8443","SSL_CERT_FILE":"/synthetic/ca.pem"}):
                self.assertTrue(http.wire(self.payload())["ok"])
                self.assertEqual(calls[-1][:2],("synthetic-proxy.example:8443","api.mail.qq.com"))
                self.assertEqual(seen[-1],"/synthetic/ca.pem")
                self.assertEqual(calls[-1][3].verify_mode,ssl.CERT_REQUIRED)
                self.assertTrue(calls[-1][3].check_hostname)
                for status in (301,302,303,307,308):
                    count=len(calls)
                    with self.assertRaises(http.WireFailure): http.wire(self.payload())
                    self.assertEqual(len(calls),count+1)
                    self.assertEqual(calls[-1][2],config.ENDPOINT)


if __name__ == "__main__": unittest.main()
