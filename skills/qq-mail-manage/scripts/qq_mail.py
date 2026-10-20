#!/usr/bin/env python3
"""Manage a configured QQ mailbox through real Codex and its official OAuth store."""
import argparse
import asyncio
import json
import os
import fcntl
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mail_config import (READ_TOOLS as TOOLS, WRITE_TOOLS, load_settings, codex_binary,
                         overrides, private_dir, data_home, select_profile)


class ToolError(RuntimeError):
    def __init__(self, payload):
        self.payload = payload
        super().__init__("QQ Mail tool returned an error")


class CodexMail:
    def __init__(self, write_tool=None, user_authorized_send=False):
        if write_tool is not None and write_tool not in WRITE_TOOLS:
            raise ValueError("Unsupported write tool")
        if user_authorized_send and write_tool not in ("SendMessage", "ReplyMessage", "ForwardMessage"):
            raise ValueError("Direct authorization mode is only supported for sending mail")
        self.settings = load_settings()
        self.account = self.settings.account
        if write_tool and self.settings.mode != "manage":
            raise RuntimeError("Read-only profile; onboard this profile in manage mode before writing")
        self.write_tool = write_tool
        self.user_authorized_send = user_authorized_send
        self.allowed_tools = TOOLS + ((write_tool,) if write_tool else ())
        self.last_call = 0

    async def __aenter__(self):
        args = [codex_binary(), "app-server", "--listen", "stdio://"]
        args += overrides(self.settings, self.allowed_tools, automatic=True)
        private_dir(self.settings.state_dir)
        self.process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=8 * 1024 * 1024,
            cwd=self.settings.state_dir,
        )
        self.sequence = 0
        try:
            await self.rpc("initialize", {
                "clientInfo": {"name": "qq_mail_manage_bridge", "title": "QQ Mail Manage Bridge", "version": "1.0.0"},
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
        if "mail:read" not in scopes or set(scopes) - {*self.settings.scopes, "alias:read"}:
            raise RuntimeError("OAuth scopes exceed the configured mode or omit mail:read; review authorization")
        required = "mail:delete" if self.write_tool == "DeleteMessage" else "mail:send"
        if self.write_tool and required not in scopes:
            raise RuntimeError("Required write permission has not been granted")
        aliases = [a for a in context.get("aliases", []) if a.get("email", "").lower() == self.account]
        if len(aliases) != 1 or not aliases[0].get("alias_id"):
            raise RuntimeError("Authorized account does not contain the configured mailbox; stop, do not choose the primary alias")
        self.alias_id = aliases[0]["alias_id"]
        self.status = {"profile": self.settings.profile, "account": self.account, "mode": self.settings.mode,
                       "scopes": scopes, "is_primary_alias": aliases[0].get("is_primary"),
                       "missing_scopes": sorted(set(self.settings.scopes) - set(scopes)),
                       "route": "local real Codex -> official QQ Mail MCP"}

    async def __aexit__(self, *_):
        if self.process.returncode is None:
            self.process.terminate()
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
                    raise RuntimeError("Codex app-server exited before completing the request")
                message = json.loads(line)
                if "method" in message and "id" in message:
                    raise RuntimeError("Interactive approval required; stop and use the supported UI")
                if message.get("id") == request_id:
                    if "error" in message:
                        # Server error text may echo request bodies or secret fields.
                        raise RuntimeError("Codex RPC rejected " + method + "; check CLI compatibility and official OAuth without replaying writes")
                    return message["result"]

    async def raw_call(self, tool, arguments):
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
        return await self.rpc("mcpServer/tool/call", {
            "threadId": self.thread_id, "server": self.settings.server, "tool": tool, "arguments": arguments,
        })

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
        if not isinstance(data["data"], list) or not isinstance(data["pagination"], dict):
            raise RuntimeError("Invalid mail list or pagination response")
    elif tool in ("ListMessages", "SearchMessages") and not endpoint_error(data):
        raise RuntimeError("Mail list response has no pagination; do not assume an empty page")
    return data

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
        if name == "search":
            p.add_argument("--query", required=True)
            p.add_argument("--from", dest="sender")
            p.add_argument("--subject-only", action="store_true")
    p = sub.add_parser("read")
    p.add_argument("--message-id", required=True)
    options = parser.parse_args()
    if options.profile:
        select_profile(options.profile)
    async with CodexMail() as mail:
        if options.command == "status":
            result = mail.status
        elif options.command == "read":
            result = await mail.call("GetMessage", {"alias_id": mail.alias_id, "message_id": options.message_id})
        else:
            now = datetime.now(timezone.utc)
            after = options.after or (now - timedelta(days=7)).isoformat()
            before = options.before or now.isoformat()
            dates = [datetime.fromisoformat(s.replace("Z", "+00:00")) for s in (after, before)]
            if any(d.tzinfo is None for d in dates) or dates[0] >= dates[1]:
                parser.error("Use ordered ISO 8601 dates with explicit timezones")
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
            result = await mail.call(tool, arguments)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, ValueError, OSError, asyncio.TimeoutError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
