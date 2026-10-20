#!/usr/bin/env python3
"""Manage a configured QQ mailbox through real Codex and its official OAuth store."""
import argparse
import asyncio
import json
import os
import fcntl
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mail_config import (READ_TOOLS as TOOLS, WRITE_TOOLS, load_settings, codex_binary,
                         overrides, private_dir, data_home, select_profile, subprocess_env,
                         redact, contains_runtime_secret)


class AuthenticationError(RuntimeError):
    def __init__(self):
        super().__init__("Official QQ MCP authorization failed or expired/revoked; securely update authorization and run verify; no refresh or automatic resend")


def authentication_failure(payload):
    """Only call for an error channel, never scan normal email bodies as instructions."""
    text = json.dumps(payload, ensure_ascii=False)
    return bool(re.search(r"\b401\b|unauthori[sz]ed|invalid[_ -]?(?:token|grant)|\bexpired\b|\brevoked\b|token[_ -]?(?:expired|revoked)", text, re.I))


class ToolError(RuntimeError):
    def __init__(self, payload):
        self.payload = redact(payload)
        super().__init__("QQ Mail tool returned an error")


class CodexMail:
    def __init__(self, write_tool=None, user_authorized_send=False):
        if write_tool is not None and write_tool not in WRITE_TOOLS:
            raise ValueError("Unsupported write tool")
        if user_authorized_send and write_tool not in ("SendMessage", "ReplyMessage", "ForwardMessage"):
            raise ValueError("Direct authorization mode is only supported for sending mail")
        self.settings = load_settings()
        self.account = self.settings.account
        required = "mail:delete" if write_tool == "DeleteMessage" else "mail:send"
        if write_tool and required not in self.settings.scopes:
            raise RuntimeError("Read-only profile; use read_send/manage for sending" if self.settings.mode == "read" else "Deletion requires mail:delete and manage mode")
        self.write_tool = write_tool
        self.user_authorized_send = user_authorized_send
        self.allowed_tools = TOOLS + ((write_tool,) if write_tool else ())
        self.last_call = 0
        self.authorization_failed = False

    async def __aenter__(self):
        # Only the genuine MCP-calling child receives the chosen token variable.
        child_env = subprocess_env(self.settings, for_mcp=True)
        if self.settings.auth_mode == "env_token":
            child_env["RUST_LOG"] = "off"
        args = [codex_binary(), "app-server", "--listen", "stdio://"]
        args += overrides(self.settings, self.allowed_tools, automatic=True)
        private_dir(self.settings.state_dir)
        self.process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=8 * 1024 * 1024,
            cwd=self.settings.state_dir,
            env=child_env,
        )
        self.sequence = 0
        try:
            await self.rpc("initialize", {
                "clientInfo": {"name": "qq_mail_manage_bridge", "title": "QQ Mail Manage Bridge", "version": "1.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            await self.send({"method": "initialized", "params": {}})
            result = await self.rpc("thread/start", {
                "ephemeral": True, "cwd": str(self.settings.state_dir),
                "approvalPolicy": "never", "sandbox": "read-only",
            })
            self.thread_id = result["thread"]["id"]
            context = await self.call("GetMe", {})
            self.verify_context(context)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    def verify_context(self, context):
        scopes = context.get("scopes", [])
        if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes) or "mail:read" not in scopes or set(scopes) - {*self.settings.scopes, "alias:read"}:
            raise RuntimeError("Authorization scopes exceed the configured mode or omit mail:read; review authorization")
        if set(self.settings.scopes) - set(scopes):
            raise RuntimeError("Required permissions were not fully granted; select a matching capability mode or update authorization")
        required = "mail:delete" if self.write_tool == "DeleteMessage" else "mail:send"
        if self.write_tool and required not in scopes:
            raise RuntimeError("Required write permission has not been granted")
        available = context.get("aliases", [])
        if not isinstance(available, list) or any(not isinstance(a, dict) or not isinstance(a.get("email"), str) for a in available):
            raise RuntimeError("Cannot verify mailbox aliases from the service response")
        aliases = [a for a in available if a["email"].lower() == self.account]
        if len(aliases) != 1 or not aliases[0].get("alias_id"):
            raise RuntimeError("Authorized account does not contain the configured mailbox; stop, do not choose the primary alias")
        self.alias_id = aliases[0]["alias_id"]
        self.status = {"profile": self.settings.profile, "account": self.account, "mode": self.settings.mode,
                       "auth_mode": self.settings.auth_mode,
                       "scopes": scopes, "is_primary_alias": aliases[0].get("is_primary"),
                       "missing_scopes": sorted(set(self.settings.scopes) - set(scopes)),
                       "route": "local real Codex -> official QQ Mail MCP"}

    async def __aexit__(self, *_):
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                await self.process.wait()
                return
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def rpc(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        await self.send({"id": request_id, "method": method, "params": params})
        async with asyncio.timeout(60):
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Codex app-server exited before completion; check runtime/authorization and update the access-token variable if expired; do not resend writes")
                try:
                    message = redact(json.loads(line))
                except (ValueError, TypeError):
                    raise RuntimeError("Invalid Codex response; inspect authorization/runtime without replaying writes") from None
                if "method" in message and "id" in message:
                    raise RuntimeError("Interactive approval required; stop and use the supported UI")
                if message.get("id") == request_id:
                    if "error" in message:
                        if authentication_failure(message["error"]):
                            self.authorization_failed = True
                            raise AuthenticationError()
                        # Server error text may echo request bodies or secret fields.
                        raise RuntimeError("Codex RPC rejected " + method + "; check CLI compatibility and official OAuth without replaying writes")
                    return message["result"]

    async def raw_call(self, tool, arguments):
        if self.authorization_failed:
            raise AuthenticationError()
        if contains_runtime_secret(arguments):
            raise RuntimeError("Mail request contains runtime credentials; refusing to transmit them as mail arguments")
        if tool not in self.allowed_tools:
            raise RuntimeError("Tool is not enabled for this operation")
        if "alias_id" in arguments and arguments["alias_id"] != getattr(self, "alias_id", None):
            raise RuntimeError("Mail request targets an unverified mailbox alias")
        if tool != "GetMe" and not arguments.get("alias_id"):
            raise RuntimeError("Explicit verified mailbox alias is required")
        if tool in WRITE_TOOLS:
            if arguments.get("alias_id") != self.alias_id:
                raise RuntimeError("Write account does not match the verified mailbox")
            if arguments.get("skip_confirmation") and not self.user_authorized_send:
                raise RuntimeError("Direct sending requires an explicit user instruction")
        # Coordinate the advertised 10/min limit across local bridge processes.
        await reserve_call_slot()
        raw = redact(await self.rpc("mcpServer/tool/call", {
            "threadId": self.thread_id, "server": self.settings.server, "tool": tool, "arguments": arguments,
        }))
        payload = decode_result(raw)
        if (raw.get("isError") or endpoint_error(payload)) and authentication_failure(payload):
            self.authorization_failed = True
            raise AuthenticationError()
        return raw

    async def call(self, tool, arguments):
        if tool not in TOOLS:
            raise RuntimeError("Use qq_mail_write.py for write operations")
        result = await self.raw_call(tool, arguments)
        payload = decode_result(result, tool)
        if result.get("isError") or endpoint_error(payload):
            raise ToolError(result)
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected QQ Mail response shape; do not treat this as an empty success")
        return payload


async def reserve_call_slot():
    private_dir(data_home())
    fd = os.open(data_home() / ".rate.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.1)
        try:
            previous = float(stream.read() or "0")
            delay = 6.2 - (time.time() - previous)
            if delay > 0:
                await asyncio.sleep(min(delay, 6.2))
            stream.seek(0)
            stream.write(str(time.time()))
            stream.truncate()
            stream.flush()
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def endpoint_error(payload):
    return isinstance(payload, dict) and (bool(payload.get("error")) or any(payload.get(k, 0) not in (0, "0", None) for k in ("code", "error_code")))


def decode_result(result, tool=None):
    result = redact(result)
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected MCP response shape")
    if "structuredContent" in result:
        data = result["structuredContent"]
    else:
        texts = [x["text"] for x in result.get("content", []) if x.get("type") == "text"]
        if len(texts) != 1:
            raise RuntimeError("Unexpected MCP response shape")
        data = json.loads(texts[0])
    # Tencent wraps endpoint payloads under two data envelopes.
    while isinstance(data, dict) and "data" in data and set(data) <= {"data", "rsp_headers", "_hints"}:
        data = data["data"]
    if tool in ("ListMessages", "SearchMessages") and isinstance(data, dict) and "pagination" in data and not endpoint_error(data):
        # The official endpoint omits the data field for an empty page.
        data.setdefault("data", [])
        if not isinstance(data["data"], list) or not isinstance(data["pagination"], dict) or type(data["pagination"].get("has_more")) is not bool:
            raise RuntimeError("Invalid mail list or pagination response")
    elif tool in ("ListMessages", "SearchMessages") and not endpoint_error(data):
        raise RuntimeError("Mail list response has no pagination; do not assume an empty page")
    return redact(data)


def query_window(after=None, before=None):
    """Freeze the default endpoint once; accept only ordered, timezone-aware bounds."""
    end = before or datetime.now(timezone.utc).isoformat()
    finish = datetime.fromisoformat(end.replace("Z", "+00:00"))
    start = after or (finish - timedelta(days=7)).isoformat()
    begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if begin.tzinfo is None or finish.tzinfo is None or begin >= finish:
        raise ValueError("Use ordered ISO 8601 dates with explicit timezones")
    return start, end


async def collect_pages(mail, tool, arguments, max_pages=100):
    """Bounded full pagination with immutable filters; never return a partial success."""
    if tool not in ("ListMessages", "SearchMessages") or "cursor" in arguments:
        raise ValueError("Full pagination requires a list/search starting at the first page")
    if not 1 <= max_pages <= 1000:
        raise ValueError("max_pages must be 1..1000")
    query_window(arguments.get("after"), arguments.get("before"))
    if not arguments.get("after") or not arguments.get("before") or arguments.get("dir") not in ("inbox", "sent", "trash", "spam"):
        raise ValueError("Full pagination requires explicit folder and fixed date bounds")
    items, seen, cursor = {}, set(), None
    for number in range(1, max_pages + 1):
        params = dict(arguments)
        if cursor:
            params["cursor"] = cursor
        page = await mail.call(tool, params)
        for item in page["data"]:
            message_id = item.get("message_id")
            if not isinstance(message_id, str) or not message_id:
                raise RuntimeError("Message ID missing from paginated result")
            if message_id in items and items[message_id] != item:
                raise RuntimeError("A message changed across pages; stop and reconcile the fixed query")
            items[message_id] = item
        pagination = page["pagination"]
        if pagination.get("has_more") is False:
            return {"data": list(items.values()), "pages": number, "complete": True,
                    "folder": arguments["dir"], "after": arguments["after"], "before": arguments["before"]}
        next_cursor = pagination.get("next_cursor")
        if pagination.get("has_more") is not True or not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise RuntimeError("Invalid or repeated pagination cursor; result is incomplete")
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError("Pagination limit reached; result is incomplete, do not select or forward from it")


def latest_by_received(messages, after, before, subject_contains):
    """Require an actual received_at value; never guess it from sender Date/ordering."""
    query_window(after, before)
    start, end = [datetime.fromisoformat(s.replace("Z", "+00:00")) for s in (after, before)]
    candidates = []
    for item in messages:
        if subject_contains not in item.get("subject", ""):
            continue
        received = item.get("received_at")
        if not isinstance(received, str):
            raise RuntimeError("Actual receipt time is not established; resolve service metadata instead of guessing from created_at or sender Date")
        date = datetime.fromisoformat(received.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise RuntimeError("Receipt timestamp needs an explicit timezone")
        if start <= date < end:
            candidates.append((date, item))
    if not candidates:
        raise RuntimeError("No matching subject within the fixed receipt-time window")
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise RuntimeError("Latest receipt timestamp is tied; resolve the ambiguity before forwarding")
    return candidates[0][1]

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Configured mailbox profile; default: QQ_MAIL_PROFILE or default")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("list", "search"):
        p = sub.add_parser(name)
        p.add_argument("--limit", type=int, choices=range(1, 6), default=3, metavar="1..5")
        p.add_argument("--after", help="ISO 8601; defaults to the last 7 days")
        p.add_argument("--before", help="ISO 8601; defaults to now")
        p.add_argument("--cursor")
        p.add_argument("--folder", choices=("inbox", "sent", "trash", "spam"), default="inbox")
        p.add_argument("--all-pages", action="store_true", help="Traverse the complete fixed query; never combine with --cursor")
        p.add_argument("--max-pages", type=int, default=100, help="Safety cap for --all-pages; hitting it is an error, not success")
        if name == "search":
            p.add_argument("--query", required=True)
            p.add_argument("--from", dest="sender")
            p.add_argument("--subject-only", action="store_true")
    p = sub.add_parser("read")
    p.add_argument("--message-id", required=True)
    options = parser.parse_args()
    if options.profile:
        select_profile(options.profile)
    if options.command in ("list", "search"):
        after, before = query_window(options.after, options.before)
        if options.all_pages and options.cursor:
            parser.error("--all-pages cannot start at an intermediate cursor")
    async with CodexMail() as mail:
        if options.command == "status":
            result = mail.status
        elif options.command == "read":
            result = await mail.call("GetMessage", {"alias_id": mail.alias_id, "message_id": options.message_id})
        else:
            arguments = {"alias_id": mail.alias_id, "limit": options.limit, "dir": options.folder, "after": after, "before": before}
            if options.cursor:
                arguments["cursor"] = options.cursor
            tool = "ListMessages"
            if options.command == "search":
                tool = "SearchMessages"
                arguments["q"] = options.query
                if options.sender:
                    arguments["from"] = options.sender
                if options.subject_only:
                    arguments["search_in"] = "SEARCH_IN_SUBJECT"
            result = await collect_pages(mail, tool, arguments, options.max_pages) if options.all_pages else await mail.call(tool, arguments)
        print(json.dumps(redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, ValueError, OSError, asyncio.TimeoutError) as error:
        print(redact(str(error)), file=sys.stderr)
        sys.exit(1)
