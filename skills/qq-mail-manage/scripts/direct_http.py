"""Fixed-endpoint MCP Streamable HTTP, bounded workers and secret-free receipts.

Protocol and limitations: references/direct-http.md. Never print HTTP exceptions.
"""
import codecs
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from mail_config import ENDPOINT, _runtime_secrets, private_dir, redact, subprocess_env, token_value
from mail_credentials import NoRedirect, atomic_record

# QQ's observed server/discover contract advertises 2025-03-26 and 2026-07-28.
# Prefer the implemented legacy version. 2026 is a different lifecycle, not an
# alternative version string for initialize; never negotiate it here.
VERSIONS = ("2025-03-26", "2025-11-25", "2025-06-18")
MAX_BYTES = 8 * 1024 * 1024
WORKER_SECONDS = 60
IO_SECONDS = 20
STARTUP_SECONDS = 120


class DirectMCPError(RuntimeError):
    def __init__(self, reason, receipt_id=None):
        self.reason = reason
        self.receipt_id = receipt_id
        super().__init__("Direct QQ MCP stopped: " + reason +
                         (" (transport receipt " + receipt_id + ")" if receipt_id else "") +
                         "; reconcile external state; no automatic retry or backend fallback")


class WireFailure(Exception):
    def __init__(self, reason, status=None, code=None):
        self.reason, self.status, self.code = reason, status, code


def strict_json(value):
    def invalid(*_):
        raise WireFailure("invalid_jsonrpc")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                invalid()
            result[key] = value
        return result
    return json.loads(value, parse_constant=invalid, object_pairs_hook=pairs)


def rpc_response(message, expected):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise WireFailure("invalid_jsonrpc")
    if "method" in message:
        if not isinstance(message["method"], str):
            raise WireFailure("invalid_jsonrpc")
        if "id" in message:
            if message["method"] == "ping" and type(message["id"]) in (str, int):
                return "ping"
            raise WireFailure("unsupported_server_request")
        if not message["method"].startswith("notifications/"):
            raise WireFailure("invalid_notification")
        if message["method"] == "notifications/tools/list_changed":
            raise WireFailure("catalog_changed")
        return "notification"
    if type(message.get("id")) is not type(expected) or message.get("id") != expected:
        raise WireFailure("response_id_mismatch")
    if ("result" in message) == ("error" in message):
        raise WireFailure("invalid_jsonrpc")
    if "error" in message:
        error = message["error"]
        if not isinstance(error, dict) or type(error.get("code")) is not int:
            raise WireFailure("invalid_jsonrpc")
        raise WireFailure("rpc_rejected", code=error["code"])
    if not isinstance(message["result"], dict):
        raise WireFailure("invalid_result")
    return "response"


def sse_messages(response):
    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    buffer, data, size, skip_lf = "", [], 0, False
    while True:
        chunk = response.read1(65536)
        size += len(chunk)
        if size > MAX_BYTES:
            raise WireFailure("response_too_large")
        buffer += decoder.decode(chunk, final=not chunk)
        if skip_lf and buffer:
            if buffer.startswith("\n"):
                buffer = buffer[1:]
            skip_lf = False
        while True:
            ending = re.search(r"\r\n|\r|\n", buffer)
            if ending is None:
                break
            skip_lf = ending.group() == "\r" and ending.end() == len(buffer)
            line, buffer = buffer[:ending.start()], buffer[ending.end():]
            if not line:
                if data:
                    text, data = "\n".join(data), []
                    if text:
                        yield strict_json(text)
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                data.append(value)
            # id/retry/event do not authorize redirects, reconnects or new calls.
        if not chunk:
            # SSE requires a blank line to dispatch; incomplete events are lost.
            return


def wire(payload, *, ping_budget=8):
    """Worker-only network I/O. Parent kills the worker at the total deadline."""
    message = payload["message"]
    body = json.dumps(message, ensure_ascii=False, allow_nan=False).encode()
    if len(body) > MAX_BYTES:
        raise WireFailure("request_too_large")
    headers = {"Authorization": "Bearer " + payload["token"], "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", "Accept-Encoding": "identity"}
    if payload.get("session"):
        headers["MCP-Session-Id"] = payload["session"]
    protocol = payload.get("protocol")
    if message.get("method") == "initialize":
        # Dual-era HTTP servers need the requested legacy version for routing
        # before they inspect the body. It must match initialize's proposal.
        protocol = message.get("params", {}).get("protocolVersion")
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    request = Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        # Keep default host proxy/CA, certificate and hostname verification.
        with build_opener(NoRedirect()).open(request, timeout=IO_SECONDS) as response:
            session = response.headers.get("MCP-Session-Id")
            if session is not None and (not session or len(session) > 4096 or any(not 0x21 <= ord(c) <= 0x7e for c in session)):
                raise WireFailure("invalid_session_header")
            if message.get("method") != "initialize" and session not in (None, payload.get("session")):
                raise WireFailure("unexpected_session_change")
            is_request = "id" in message and "method" in message
            if not is_request:
                if response.status != 202 or response.read(1):
                    raise WireFailure("invalid_notification_ack")
                return {"ok": True, "message": None, "session": session}
            if response.status != 200:
                raise WireFailure("unexpected_http_status", status=response.status)
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise WireFailure("unsupported_content_encoding")
            kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if kind == "application/json":
                body = response.read(MAX_BYTES+1)
                if len(body) > MAX_BYTES:
                    raise WireFailure("response_too_large")
                messages = [strict_json(body)]
            elif kind == "text/event-stream":
                messages = sse_messages(response)
            else:
                raise WireFailure("unsupported_content_type")
            for frame in messages:
                # 2025-03-26 permits response batches even for one request.
                # Later implemented revisions removed batching. Outbound mail
                # requests remain one per POST, with no retry on parse errors.
                version = payload.get("protocol") or message.get("params", {}).get("protocolVersion")
                if isinstance(frame, list):
                    if version != "2025-03-26" or not 1 <= len(frame) <= 1000:
                        raise WireFailure("invalid_jsonrpc")
                    incoming_messages = frame
                else:
                    incoming_messages = [frame]
                actions = [rpc_response(incoming, message["id"]) for incoming in incoming_messages]
                if actions.count("response") > 1:
                    raise WireFailure("invalid_jsonrpc")
                result = None
                for incoming, action in zip(incoming_messages, actions):
                    if action == "response":
                        result = incoming
                    if action == "ping":
                        if ping_budget <= 0:
                            raise WireFailure("too_many_server_requests")
                        ping_budget -= 1
                        wire({**payload, "session": session or payload.get("session"), "protocol": protocol,
                              "message": {"jsonrpc": "2.0", "id": incoming["id"], "result": {}}}, ping_budget=0)
                if result is not None:
                    return {"ok": True, "message": result, "session": session}
            raise WireFailure("response_lost")
    except HTTPError as error:
        try:
            reason = "authorization_rejected" if error.code in (401, 403) else "session_expired" if error.code == 404 and payload.get("session") else "http_rejected"
            raise WireFailure(reason, status=error.code) from None
        finally:
            error.close()  # Never consume/log error bodies, redirect targets or headers.


def worker_main():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES+16385)
        if len(raw) > MAX_BYTES+16384:
            raise WireFailure("request_too_large")
        result = wire(json.loads(raw))
    except WireFailure as error:
        result = {"ok": False, "reason": error.reason, "status": error.status, "code": error.code}
    except BaseException:
        result = {"ok": False, "reason": "network_or_protocol_failure"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


class DirectMCP:
    def __init__(self, settings, allowed_tools):
        self.settings, self.allowed_tools = settings, frozenset(allowed_tools)
        self.token = self.session = self.protocol = None
        self.closed = False
        self.available_tools = frozenset()
        self.lock = threading.Lock()
        self.last_receipt_id = None
        self.deadline = None

    def receipt(self, record):
        try:
            directory = private_dir(self.settings.state_dir / "transport")
            atomic_record(directory / (record["receipt_id"] + ".json"), redact(record))
        except (OSError, RuntimeError, ValueError):
            raise DirectMCPError("receipt_persistence_failed", record["receipt_id"]) from None

    def record_failure(self, phase):
        # Callers pass fixed phase names only, never exception text or responses.
        record = {"receipt_id": uuid.uuid4().hex, "backend": "direct_http", "phase": phase,
                  "state": "failed", "time": time.time()}
        self.receipt(record)
        return record["receipt_id"]

    def request(self, method, params=None, *, notification=False):
        if self.closed:
            raise DirectMCPError("client_closed", self.last_receipt_id)
        request_id = uuid.uuid4().hex
        self.last_receipt_id = request_id
        record = {"receipt_id": request_id, "backend": "direct_http", "method": method,
                  "state": "submitting", "time": time.time()}
        if method == "tools/call":
            record["tool"] = params["name"]
        try:
            self.receipt(record)  # A failed initial save forbids the network request.
        except DirectMCPError:
            self.closed = True
            raise
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            message["id"] = request_id
        try:
            payload = {"message": message, "token": self.token, "session": self.session, "protocol": self.protocol}
            timeout = min(WORKER_SECONDS, self.deadline-time.monotonic()) if self.deadline else WORKER_SECONDS
            if timeout <= 0:
                raise DirectMCPError("startup_timeout")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--http-worker"],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=timeout,
                check=True, env=subprocess_env(self.settings))
            reply = json.loads(result.stdout)
            if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
                raise DirectMCPError("invalid_worker_result")
            if reply.get("session"):
                _runtime_secrets.add(reply["session"])
            if not reply["ok"]:
                # The worker only emits fixed reason codes, numeric status/code.
                reason = reply.get("reason")
                if reason not in {"invalid_jsonrpc", "unsupported_server_request", "invalid_notification", "catalog_changed",
                    "response_id_mismatch", "rpc_rejected", "invalid_result", "response_too_large", "request_too_large",
                    "invalid_session_header", "unexpected_session_change", "invalid_notification_ack", "unexpected_http_status",
                    "unsupported_content_encoding", "unsupported_content_type", "too_many_server_requests", "response_lost",
                    "authorization_rejected", "session_expired", "http_rejected", "network_or_protocol_failure"}:
                    reason = "invalid_worker_result"
                for key in ("status", "code"):
                    if type(reply.get(key)) is int:
                        record[key] = reply[key]
                raise DirectMCPError(reason)
            if method == "initialize":
                self.session = reply.get("session")
            value = reply["message"]
            if not notification:
                if rpc_response(value, request_id) != "response":
                    raise DirectMCPError("invalid_worker_result")
                value = redact(value["result"])
            record["state"] = "completed"  # RPC receipt, not a mail-delivery claim.
            self.receipt(record)
            return value
        except BaseException as error:
            self.closed = True
            record.update(state="unknown" if method == "tools/call" else "failed",
                          reason=error.reason if isinstance(error, DirectMCPError) else
                          "request_timeout" if isinstance(error, subprocess.TimeoutExpired) else "backend_failure")
            self.receipt(record)
            raise DirectMCPError(record["reason"], request_id) from None

    def connect(self):
        self.deadline = time.monotonic() + STARTUP_SECONDS
        try:
            self.token = token_value(self.settings)  # Refresh once, before any MCP session.
        except BaseException:
            identifier = self.record_failure("credential_unavailable")
            self.closed = True
            raise DirectMCPError("credential_unavailable", identifier) from None
        result = self.request("initialize", {"protocolVersion": VERSIONS[0], "capabilities": {},
            "clientInfo": {"name": "qq_mail_manage_direct", "version": "1.3.1"}})
        version = result.get("protocolVersion")
        if version not in VERSIONS or not isinstance(result.get("capabilities"), dict) or not isinstance(result["capabilities"].get("tools"), dict):
            self.closed = True
            raise DirectMCPError("unsupported_protocol_or_tools", self.record_failure("capability_negotiation"))
        self.protocol = version
        self.request("notifications/initialized", notification=True)
        seen, names, cursor = set(), set(), None
        for _ in range(100):
            page = self.request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(page.get("tools"), list) or len(page["tools"]) > 1000:
                break
            for tool in page["tools"]:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or tool["name"] in names or not isinstance(tool.get("inputSchema"), dict):
                    raise DirectMCPError("invalid_tool_catalog", self.record_failure("tool_discovery"))
                names.add(tool["name"])
            if len(names) > 1000:
                break
            if "nextCursor" not in page:
                self.available_tools = frozenset(names & self.allowed_tools)
                if "GetMe" in self.available_tools and self.allowed_tools <= self.available_tools:
                    self.deadline = None
                    return
                raise DirectMCPError("required_tools_unavailable", self.record_failure("tool_discovery"))
            cursor = page["nextCursor"]
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                break
            seen.add(cursor)
        raise DirectMCPError("incomplete_tool_catalog", self.record_failure("tool_discovery"))

    def call_tool(self, name, arguments):
        with self.lock:
            if name not in self.allowed_tools or name not in self.available_tools or (name == "DeleteMessage" and "mail:delete" not in self.settings.scopes):
                raise DirectMCPError("tool_not_enabled")
            return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        self.closed = True
        self.token = self.session = None


if __name__ == "__main__" and sys.argv[1:] == ["--http-worker"]:
    worker_main()
