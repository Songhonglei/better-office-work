"""Synthetic modern QQ transport and failure contracts; no live credentials/I/O."""
import asyncio
import base64
import hashlib
import json
import subprocess
import traceback
import unittest
from unittest.mock import patch

import test_direct_http as legacy
fixtures, config, bridge, flow, http, modern, SESSION = (legacy.fixtures, legacy.config,
    legacy.bridge, legacy.flow, legacy.http, legacy.modern, legacy.SESSION)


class ModernHTTPTests(unittest.IsolatedAsyncioTestCase):
    setUp_legacy = legacy.DirectHTTPTests.setUp
    tearDown = legacy.DirectHTTPTests.tearDown
    records = legacy.DirectHTTPTests.records
    assert_safe_records = legacy.DirectHTTPTests.assert_safe_records

    def setUp(self):
        self.setUp_legacy()
        self.settings=config.settings_from({**self.settings.as_dict(),"http_protocol":"auto"})
        config.write_private(config.profile_path(),self.settings.as_dict())
        self.server.protocol=modern.MODERN; self.server.session=None

    async def test_discover_and_each_request_have_metadata_headers_without_initialize(self):
        async with bridge.CodexMail() as mail:
            self.assertEqual(mail.status["protocol_version"],modern.MODERN)
            self.assertNotIn("DeleteMessage",mail.direct.available_tools)
            await mail.call("ListMessages",{"alias_id":mail.alias_id})
        self.assertEqual([r[0]["method"] for r in self.server.requests],
                         ["server/discover","tools/list","tools/call","tools/call"])
        for message,headers in self.server.requests:
            self.assertEqual(message["params"]["_meta"],modern.metadata())
            self.assertEqual(headers["Mcp-method"],message["method"])
            self.assertEqual(headers["Mcp-protocol-version"],modern.MODERN)
            self.assertNotIn("Mcp-session-id",headers)
            if message["method"]=="tools/call": self.assertEqual(headers["Mcp-name"],message["params"]["name"])
        self.assert_safe_records()

    async def test_explicit_modern_selection_and_legacy_advertisement_negotiation(self):
        config.write_private(config.profile_path(),{**self.settings.as_dict(),"http_protocol":modern.MODERN})
        async with bridge.CodexMail() as mail: self.assertEqual(mail.direct.protocol,modern.MODERN)
        self.server.requests=[];self.server.supported=["2025-03-26"];self.server.protocol="2025-03-26"
        with self.assertRaisesRegex(http.DirectMCPError,"unsupported_protocol"):
            async with bridge.CodexMail(): pass
        self.assertEqual(len(self.server.requests),1)
        config.write_private(config.profile_path(),self.settings.as_dict());self.server.requests=[]
        async with bridge.CodexMail() as mail: self.assertEqual(mail.direct.protocol,"2025-03-26")
        self.assertEqual([r[0]["method"] for r in self.server.requests][:3],
                         ["server/discover","initialize","notifications/initialized"])

    async def test_discovery_version_shapes_and_unknown_versions_stop(self):
        for versions in ([],[modern.MODERN,modern.MODERN],[1],["bad"],["2099-01-01"]):
            self.server.requests=[];self.server.supported=versions
            with self.assertRaises(http.DirectMCPError):
                async with bridge.CodexMail(): pass
            self.assertEqual(len(self.server.requests),1)

    async def test_strict_id_result_type_and_no_session_header(self):
        for case in ("mismatched_id","missing_result_type","bad_result_type","modern_session","rpc_error"):
            self.server.case=case;self.server.requests=[]
            with self.assertRaises(http.DirectMCPError) as error:
                async with bridge.CodexMail(): pass
            self.assertEqual(len(self.server.requests),1)
            trace="".join(traceback.format_exception(error.exception))
            for secret in (fixtures.A,fixtures.R,SESSION): self.assertNotIn(secret,trace)
        self.assert_safe_records()

    async def test_modern_sse_and_empty_cursor_are_supported(self):
        self.server.sse=True;self.server.case="empty_cursor"
        async with bridge.CodexMail(): pass
        pages=[r[0] for r in self.server.requests if r[0]["method"]=="tools/list"]
        self.assertEqual(len(pages),2);self.assertEqual(pages[1]["params"]["cursor"],"")

    async def test_directory_errors_and_missing_required_tools_stop_before_getme(self):
        for case,names in (("bad_catalog",config.READ_TOOLS),("cursor_loop",config.READ_TOOLS),
                           ("ok",["GetMe"]),("ok",[*config.READ_TOOLS,"GetMe"])):
            self.server.case=case;self.server.tools=names;self.server.requests=[]
            with self.assertRaises(http.DirectMCPError):
                async with bridge.CodexMail(): pass
            self.assertFalse(any(m[0]["method"]=="tools/call" for m in self.server.requests))

    async def test_schema_validation_excludes_bad_tools_and_never_fetches_refs(self):
        self.server.schemas["UnknownTool"]={"type":"object","required":"not a list"}
        async with bridge.CodexMail() as mail: self.assertNotIn("UnknownTool",mail.direct.available_tools)
        self.server.schemas["GetMe"]={"type":"object","properties":{"value":{"$ref":"https://synthetic-attacker.example/schema"}}}
        self.server.requests=[]
        with self.assertRaisesRegex(http.DirectMCPError,"required_tools_unavailable"):
            async with bridge.CodexMail(): pass
        self.assertEqual([r[0]["method"] for r in self.server.requests],["server/discover","tools/list"])

    async def test_headers_project_exact_nested_path_and_runtime_schema_blocks_before_network(self):
        self.server.schemas["ListMessages"]={"type":"object","properties":{
            "alias_id":{"type":"string","x-mcp-header":"Alias"},
            "routing":{"type":"object","properties":{"region":{"type":"string","x-mcp-header":"Region"}}}},
            "required":["alias_id","routing"]}
        async with bridge.CodexMail() as mail:
            await mail.call("ListMessages",{"alias_id":mail.alias_id,"routing":{"region":"中文\r\n"}})
            headers=self.server.requests[-1][1]
            self.assertEqual(headers["Mcp-param-alias"],mail.alias_id)
            self.assertEqual(headers["Mcp-param-region"],modern.header_value("中文\r\n"))
            before=len(self.server.requests)
            with self.assertRaisesRegex(http.DirectMCPError,"invalid_tool_arguments"):
                await mail.call("ListMessages",{"alias_id":mail.alias_id})
            self.assertEqual(len(self.server.requests),before)

    async def test_output_schema_rejection_is_durable_and_no_followup_call(self):
        self.server.output_schemas["ListMessages"]={"type":"object","required":["must_exist"]}
        async with bridge.CodexMail() as mail:
            with self.assertRaisesRegex(http.DirectMCPError,"invalid_tool_output"):
                await mail.call("ListMessages",{"alias_id":mail.alias_id})
            count=len(self.server.requests)
            with self.assertRaises(http.DirectMCPError): await mail.call("ListMessages",{"alias_id":mail.alias_id})
            self.assertEqual(len(self.server.requests),count)
        self.assertTrue(any(r.get("reason")=="invalid_tool_output" for r in self.records()))

    async def test_external_output_references_excluded_before_any_tool_call(self):
        for reference in ("$ref","$dynamicRef"):
            self.server.output_schemas["GetMe"]={reference:"https://synthetic-attacker.example/schema"}
            self.server.requests=[]
            with self.assertRaisesRegex(http.DirectMCPError,"required_tools_unavailable"):
                async with bridge.CodexMail(): pass
            self.assertEqual([r[0]["method"] for r in self.server.requests],["server/discover","tools/list"])

    async def test_dangling_local_output_reference_rejected_before_any_tool_call(self):
        for reference in ("#/$defs/missing", "#missing-anchor"):
            self.server.output_schemas["GetMe"]={"$ref":reference}
            self.server.requests=[]
            with self.assertRaisesRegex(http.DirectMCPError,"required_tools_unavailable"):
                async with bridge.CodexMail(): pass
            self.assertEqual([r[0]["method"] for r in self.server.requests],["server/discover","tools/list"])

    async def test_normal_send_uses_modern_headers_and_preserves_body_and_every_attachment(self):
        content=self.server.attach
        attachment={"filename":"invoice.pdf","size":len(content),"sha1":hashlib.sha1(content).hexdigest(),
                    "content":base64.b64encode(content).decode(),"content_type":"application/pdf"}
        args={"to":[{"email":"recipient@example.com"}],"subject":"Item+Invoice+1.00",
              "body":"Complete original body; source synthetic-message; currency CNY","attachments":[attachment]}
        result=await flow.execute_authorized("SendMessage",args,user_authorized=True,operation_id="fixture-"+self.server.case)
        self.assertEqual(result["state"],"accepted")
        sends=[r for r in self.server.requests if r[0].get("params",{}).get("name")=="SendMessage"]
        self.assertEqual(len(sends),1)
        self.assertEqual(sends[0][1]["Mcp-name"],"SendMessage")
        for field in ("subject","body","attachments"): self.assertEqual(sends[0][0]["params"]["arguments"][field],args[field])
        self.assert_safe_records()

    async def test_send_401_timeout_input_required_and_version_rejection_never_replay(self):
        args={"to":[{"email":"recipient@example.com"}],"subject":"synthetic","body":"synthetic"}
        for case in ("send401","send_timeout","input_required","send_version_error"):
            self.server.case=case;self.server.requests=[]
            with patch.object(fixtures.creds,"exchange",side_effect=AssertionError("no reactive refresh")) as exchange:
                with self.assertRaisesRegex(RuntimeError,"unknown"):
                    await flow.execute_authorized("SendMessage",args,user_authorized=True,operation_id="fixture-"+self.server.case)
                exchange.assert_not_called()
            self.assertEqual(sum(r[0].get("params",{}).get("name")=="SendMessage" for r in self.server.requests),1)
        self.assertTrue(any(r.get("tool")=="SendMessage" and r["state"]=="unknown" for r in self.records()))
        self.assert_safe_records()

    async def test_account_scope_and_delete_guards_apply_to_modern(self):
        self.server.account="other@qq.com"
        with self.assertRaises(RuntimeError):
            async with bridge.CodexMail(): pass
        self.server.account="target@qq.com";self.server.scopes.append("unknown")
        with self.assertRaises(RuntimeError):
            async with bridge.CodexMail(): pass
        self.server.scopes.remove("unknown")
        with self.assertRaisesRegex(RuntimeError,"Deletion requires"): bridge.CodexMail(write_tool="DeleteMessage")
        async with bridge.CodexMail() as mail:
            with self.assertRaisesRegex(RuntimeError,"Deletion requires"):
                await mail.raw_call("DeleteMessage",{"alias_id":mail.alias_id})
        self.assertFalse(any(r[0].get("params",{}).get("name")=="DeleteMessage" for r in self.server.requests))

    async def test_worker_deadline_during_discovery_stops_without_handshake_fallback(self):
        self.server.case="worker_timeout"
        with self.assertRaisesRegex(http.DirectMCPError,"request_timeout"):
            async with bridge.CodexMail(): pass
        self.assertEqual([r["method"] for r in self.server.workers],["server/discover"])
        self.assert_safe_records()

    async def test_missing_dependency_stops_before_credentials_or_network(self):
        import builtins
        original=builtins.__import__
        def dependency(name,*args,**kwargs):
            if name=="jsonschema": raise ImportError("synthetic missing dependency")
            return original(name,*args,**kwargs)
        with patch.object(builtins,"__import__",side_effect=dependency),patch.object(http,"token_value") as token:
            with self.assertRaisesRegex(http.DirectMCPError,"modern_dependency_missing"):
                async with bridge.CodexMail(): pass
            token.assert_not_called()
        self.assertFalse(self.server.requests)
        self.assertTrue(any(r.get("phase")=="dependency_check" for r in self.records()))

    def test_configuration_default_doctor_and_explicit_legacy_remain_compatible(self):
        data=self.settings.as_dict();data.pop("http_protocol")
        self.assertEqual(config.settings_from(data).http_protocol,"auto")
        for choice in config.HTTP_PROTOCOLS:
            self.assertEqual(config.settings_from({**data,"http_protocol":choice}).http_protocol,choice)
        with self.assertRaises(ValueError): config.settings_from({**data,"http_protocol":"made-up"})
        with patch.object(fixtures.onboard,"codex_binary",side_effect=AssertionError()):
            self.assertEqual(fixtures.onboard.doctor()["http_protocol"],"auto")


class ModernHeaderTests(unittest.TestCase):
    def test_encoding_injection_unicode_sentinel_and_primitive_values(self):
        for value in ("中文","trailing ","\r\nInjected: value","=?base64?literal?="):
            encoded=modern.header_value(value)
            self.assertEqual(base64.b64decode(encoded[9:-2]).decode(),value)
            self.assertNotIn("\r",encoded);self.assertNotIn("\n",encoded)
        schema={"type":"object","properties":{"flag":{"type":"boolean","x-mcp-header":"Flag"},
                "nested":{"type":"object","properties":{"count":{"type":"integer","x-mcp-header":"Count"}}}}}
        specs=modern.header_specs(schema)
        self.assertEqual(modern.parameter_headers(specs,{"flag":False,"nested":{"count":1}}),{"Mcp-Param-Flag":"false","Mcp-Param-Count":"1"})
        self.assertEqual(modern.parameter_headers(specs,{"flag":None}),{})
        for value in (True,2**53,"1"):
            with self.assertRaises(ValueError): modern.parameter_headers(specs,{"nested":{"count":value}})

    def test_invalid_or_unreachable_annotations_exclude_definition(self):
        nodes=[{"type":"string","x-mcp-header":"bad\r\nname"},
               {"type":"number","x-mcp-header":"Number"},
               {"type":"string","x-mcp-header":""}]
        for node in nodes:
            with self.assertRaises(ValueError): modern.header_specs({"type":"object","properties":{"v":node}})
        invalid=[{"type":"object","items":{"type":"string","x-mcp-header":"Hidden"}},
                 {"type":"object","allOf":[{"type":"object","properties":{"v":{"type":"string","x-mcp-header":"Hidden"}}}]},
                 {"type":"object","properties":{"a":{"type":"string","x-mcp-header":"Same"},"b":{"type":"string","x-mcp-header":"same"}}}]
        for schema in invalid:
            with self.assertRaises(ValueError): modern.header_specs(schema)

    def test_validated_schema_dialect_local_refs_and_no_remote_retrieval(self):
        schema={"type":"object","$defs":{"text":{"type":"string"}},"properties":{"v":{"$ref":"#/$defs/text"}}}
        modern.schema_validator(schema).validate({"v":"value"})
        for schema in ({"$schema":"https://synthetic-attacker.example/dialect","type":"object"},
                       {"type":"object","required":"bad"}):
            with self.assertRaises(Exception): modern.schema_validator(schema)


if __name__ == "__main__": unittest.main()
