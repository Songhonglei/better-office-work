#!/usr/bin/env python3
"""Send explicitly requested mail directly; retain reviewed confirmation for deletion."""
import mail_config  # Check runtime before importing platform-dependent helpers.
import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from qq_mail import WRITE_TOOLS, CodexMail, decode_result, endpoint_error, AuthenticationError
from mail_config import account, load_settings, private_dir, select_profile, redact, contains_runtime_secret
from mail_credentials import sync_directory
import fcntl

PENDING = None  # Test override; runtime state always lives outside the installed skill.


def pending_dir():
    return PENDING if PENDING is not None else load_settings().state_dir / "pending"


SCHEMAS = json.loads((Path(__file__).parent / "write_schemas.json").read_text())


def validate(schema, value, path="arguments"):
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types and type(value) is not types[kind]:
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if kind == "object":
        properties = schema.get("properties", {})
        if set(value) - set(properties):
            raise ValueError(f"{path}: unknown fields")
        if set(schema.get("required", [])) - set(value):
            raise ValueError(f"{path}: required fields missing")
        for key, item in value.items():
            validate(properties[key], item, f"{path}.{key}")
    if kind == "array":
        for item in value:
            validate(schema.get("items", {}), item, path + "[]")


def validate_arguments(tool, arguments):
    if tool not in WRITE_TOOLS or not isinstance(arguments, dict):
        raise ValueError("Unsupported write operation")
    if set(arguments) & {"confirmation_token", "skip_confirmation", "alias_id", "file_refs"}:
        raise ValueError("Caller-supplied tokens, aliases, skip flags, and file references are forbidden")
    validate(SCHEMAS[tool], arguments)
    if contains_runtime_secret(arguments):
        raise ValueError("Mail arguments must not contain runtime credentials")
    if tool in ("SendMessage", "ForwardMessage") and not arguments.get("to"):
        raise ValueError("At least one recipient is required")
    for field in ("to", "cc", "bcc"):
        for person in arguments.get(field, []):
            address = person["email"]
            if "@" not in address or re.search(r"[\s\r\n]", address):
                raise ValueError("Invalid recipient address")
    if "subject" in arguments and (len(arguments["subject"]) > 998 or re.search(r"[\r\n]", arguments["subject"])):
        raise ValueError("Invalid subject")
    attachments = arguments.get("attachments", [])
    if len(attachments) > 3:
        raise ValueError("Attachment count exceeds the verified service limit")
    total = 0
    for attachment in attachments:
        data = base64.b64decode(attachment["content"], validate=True)
        if len(data) != attachment["size"] or hashlib.sha1(data).hexdigest() != attachment["sha1"].lower():
            raise ValueError("Attachment size or SHA-1 does not match its content")
        if len(data) > 1048576:
            raise ValueError("Attachment exceeds the verified 1 MiB limit")
        total += len(data)
    if total > 3145728:
        raise ValueError("Total attachment size exceeds the verified 3 MiB limit")


def fingerprint(tool, arguments):
    encoded = json.dumps([account(), tool, arguments], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def nodes(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def confirmation(payload):
    objects = [x for x in nodes(payload) if isinstance(x, dict)]
    marker = any(str(x.get("code", x.get("error_code", ""))) == "42801" for x in objects)
    marker = marker or any(x == "CONFIRMATION_REQUIRED" for x in nodes(payload) if isinstance(x, str))
    tokens = [x["confirmation_token"] for x in objects if isinstance(x.get("confirmation_token"), str)]
    summaries = [x["operation_summary"] for x in objects if x.get("operation_summary") is not None]
    if not marker or len(set(tokens)) != 1 or not summaries:
        return None
    return tokens[0], summaries[0]


def state_path(request_id):
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("Invalid request ID")
    return pending_dir() / (request_id + ".json")


def save_new(record):
    private_dir(pending_dir())
    fd = os.open(state_path(record["request_id"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(redact(record), stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(pending_dir())


def update_locked(stream, record):
    stream.seek(0)
    json.dump(redact(record), stream, ensure_ascii=False)
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def acknowledged(tool, arguments, payload):
    """Require positive endpoint evidence, never infer success from absence of errors."""
    if not isinstance(payload, dict):
        return False
    if tool == "DeleteMessage":
        return payload.get("deleted") is True and payload.get("message_id") == arguments["message_id"]
    if "queued" in payload:
        return payload["queued"] is True
    return isinstance(payload.get("message_id"), str) and bool(payload["message_id"])


def progress(phase, index, total, request_id):
    print(json.dumps({"phase": phase, "index": index, "total": total, "request_id": request_id}), file=sys.stderr, flush=True)


def public_prepared(record):
    return {"state": "awaiting_user_confirmation", "request_id": record["request_id"], "preview": record["preview"],
            "operation_summary": record["operation_summary"],
            "instructions": "Show this summary and the exact content to the user; call confirm only after their explicit approval."}


async def prepare_on_client(mail, tool, arguments, preview):
    """Persist intent before a prepare RPC, which could itself lose its response."""
    request_id = uuid.uuid4().hex
    record = {"request_id": request_id, "state": "preparing", "account": account(), "tool": tool,
              "arguments": arguments, "fingerprint": fingerprint(tool, arguments), "preview": preview, "created_at": time.time()}
    save_new(record)
    with state_path(request_id).open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            wire = {**arguments, "alias_id": mail.alias_id}
            if tool != "DeleteMessage":
                wire["skip_confirmation"] = False
            raw = await mail.raw_call(tool, wire)
            challenge = confirmation(decode_result(raw))
            if not challenge:
                raise RuntimeError("No expected confirmation challenge")
            record.update({"state": "pending", "confirmation_token": challenge[0], "operation_summary": challenge[1], "created_at": time.time()})
            update_locked(stream, record)
            return public_prepared(record)
        except BaseException as error:
            if record["state"] == "preparing":
                record["state"] = "unknown"
            update_locked(stream, record)
            suffix = "; authorization rejected: securely update authorization and verify first" if isinstance(error, AuthenticationError) else ""
            raise RuntimeError(f"Preparation outcome is {record['state']} (request {request_id}); reconcile mailbox state, do not automatically retry" + suffix) from None


async def execute_authorized(tool, arguments, *, user_authorized=False, client=CodexMail):
    if not user_authorized or tool not in ("SendMessage", "ReplyMessage", "ForwardMessage"):
        raise ValueError("An explicit user send/reply/forward instruction is required")
    validate_arguments(tool, arguments)
    arguments = dict(arguments)
    arguments.setdefault("body_format", "PLAIN")
    if tool == "ReplyMessage":
        arguments.setdefault("reply_all", False)
    if tool == "ForwardMessage":
        arguments.setdefault("include_attachments", False)
    async with client(write_tool=tool, user_authorized_send=True) as mail:
        request_id = uuid.uuid4().hex
        record = {"request_id": request_id, "mode": "user_authorized_send", "state": "submitting", "account": account(),
                  "tool": tool, "arguments": arguments, "fingerprint": fingerprint(tool, arguments), "created_at": time.time()}
        save_new(record)
        with state_path(request_id).open("r+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                raw = await mail.raw_call(tool, {**arguments, "alias_id": mail.alias_id, "skip_confirmation": True})
                payload = decode_result(raw)
                challenge = confirmation(payload)
                if challenge:
                    # A server-forced challenge is not consent from the assistant.
                    record.update({"state": "pending", "confirmation_token": challenge[0], "operation_summary": challenge[1]})
                    update_locked(stream, record)
                    return {"state": "awaiting_user_confirmation", "request_id": request_id, "operation_summary": challenge[1]}
                if raw.get("isError") or endpoint_error(payload):
                    record["state"] = "failed"
                    raise RuntimeError("Tencent rejected the write; inspect the mailbox before another attempt")
                if not acknowledged(tool, arguments, payload):
                    raise RuntimeError("No positive write acknowledgment; reconcile mailbox state")
                record["state"] = "completed"
                record["result"] = payload
                record.pop("arguments", None)
                update_locked(stream, record)
                return {"state": "completed", "request_id": request_id, "result": payload}
            except BaseException as error:
                if record["state"] == "submitting":
                    record["state"] = "unknown"
                update_locked(stream, record)
                suffix = "; authorization rejected: securely update authorization and verify first" if isinstance(error, AuthenticationError) else ""
                raise RuntimeError(f"Write outcome is {record['state']} (request {request_id}); do not automatically retry" + suffix) from None


async def prepare(tool, arguments, client=CodexMail):
    validate_arguments(tool, arguments)
    arguments = dict(arguments)
    if tool == "ReplyMessage":
        arguments.setdefault("reply_all", False)
    if tool == "ForwardMessage":
        arguments.setdefault("include_attachments", False)
    if tool != "DeleteMessage":
        arguments.setdefault("body_format", "PLAIN")
    async with client(write_tool=tool) as mail:
        preview = {"account": account(), "tool": tool}
        if arguments.get("message_id"):
            original = await mail.call("GetMessage", {"alias_id": mail.alias_id, "message_id": arguments["message_id"]})
            preview.update({"original_subject": original.get("subject"), "original_sender": original.get("from"), "original_date": original.get("created_at")})
        preview.update({k: arguments[k] for k in ("to", "cc", "bcc", "subject", "reply_all", "include_attachments") if k in arguments})
        preview["attachments"] = [{k: a[k] for k in ("filename", "content_type", "size", "sha1")} for a in arguments.get("attachments", [])]
        return await prepare_on_client(mail, tool, arguments, preview)


def remember_challenge(tool, arguments, raw, preview):
    payload = decode_result(raw)
    challenge = confirmation(payload)
    if not challenge:
        # Never replay a request if the service did not return its expected challenge.
        raise RuntimeError("No Tencent confirmation challenge received. Do not retry; inspect mailbox state first.")
    token, summary = challenge
    request_id = uuid.uuid4().hex
    record = {"request_id": request_id, "state": "pending", "account": account(), "tool": tool, "arguments": arguments,
              "fingerprint": fingerprint(tool, arguments), "confirmation_token": token, "operation_summary": summary,
              "preview": preview, "created_at": time.time()}
    save_new(record)
    return {"state": "awaiting_user_confirmation", "request_id": request_id, "preview": preview, "operation_summary": summary,
            "instructions": "Show this summary and the exact content to the user; call confirm only after their explicit approval."}


async def prepare_delete_batch(messages, client=CodexMail):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 50:
        raise ValueError("A review batch must contain 1..50 messages")
    for item in messages:
        if not isinstance(item, dict) or not isinstance(item.get("message_id"), str) or not item["message_id"]:
            raise ValueError("Each reviewed message requires its exact nonempty message_id")
        validate_arguments("DeleteMessage", {"message_id": item["message_id"]})
        created = item.get("created_at")
        if not isinstance(created, str):
            raise ValueError("Each reviewed message requires created_at with a timezone before preparing deletion")
        try:
            date = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid reviewed created_at; use ISO 8601 with a timezone") from error
        if date.tzinfo is None:
            raise ValueError("Reviewed created_at requires a timezone")
    ids = [x["message_id"] for x in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate message in the reviewed batch")
    prepared = []
    async with client(write_tool="DeleteMessage") as mail:
        for index, item in enumerate(messages, 1):
            arguments = {"message_id": item["message_id"]}
            validate_arguments("DeleteMessage", arguments)
            preview = {"account": account(), "tool": "DeleteMessage", "original_subject": item.get("subject"),
                       "original_sender": item.get("from"), "original_date": item.get("created_at")}
            prepared.append(await prepare_on_client(mail, "DeleteMessage", arguments, preview))
            progress("prepared", index, len(messages), prepared[-1]["request_id"])
    batch_id = uuid.uuid4().hex
    save_new({"request_id": batch_id, "type": "delete_batch", "account": account(),
              "requests": prepared, "created_at": time.time()})
    return {"state": "awaiting_user_confirmation", "batch_id": batch_id, "count": len(prepared), "requests": prepared}


async def confirm_delete_batch(batch_id, indices=None, client=CodexMail):
    batch = json.loads(state_path(batch_id).read_text())
    if batch.get("type") != "delete_batch" or batch.get("account") != account():
        raise ValueError("Invalid deletion batch")
    requests = batch["requests"]
    indices = list(range(1, len(requests) + 1)) if indices is None else indices
    if not indices or len(indices) != len(set(indices)) or any(type(i) is not int or not 1 <= i <= len(requests) for i in indices):
        raise ValueError("Invalid selected indices")
    selected = [requests[i - 1] for i in indices]
    for item in selected:
        record = json.loads(state_path(item["request_id"]).read_text())
        if record.get("tool") != "DeleteMessage" or record.get("preview") != item["preview"] or record.get("operation_summary") != item["operation_summary"]:
            raise RuntimeError("Deletion batch no longer matches the reviewed summary")
        if record.get("state") != "pending" and not (record.get("state") == "failed" and record.get("failure_code") == "40001"):
            raise RuntimeError("A selected request was used or has an unknown outcome; reconcile before retrying")
    results = []
    async with client(write_tool="DeleteMessage") as mail:
        @asynccontextmanager
        async def reuse(write_tool=None):
            if write_tool != "DeleteMessage":
                raise ValueError("Only the reviewed deletions are allowed")
            yield mail
        for index, item in enumerate(selected, 1):
            # Prepare immediately before commit; a long review/batch outlives Tencent tokens.
            progress("confirming", index, len(selected), item["request_id"])
            try:
                results.append(await confirm(item["request_id"], client=reuse, renew_delete=True))
            except BaseException:
                progress("stopped_reconcile_required", index, len(selected), item["request_id"])
                raise
            progress("completed", index, len(selected), item["request_id"])
    return {"state": "completed", "batch_id": batch_id, "count": len(results), "results": results}


def batch_status(batch_id):
    """Read local receipts only; does not renew, retry, or contact the mailbox."""
    batch = json.loads(state_path(batch_id).read_text())
    if batch.get("type") != "delete_batch" or batch.get("account") != account():
        raise ValueError("Invalid deletion batch")
    entries = []
    for index, item in enumerate(batch["requests"], 1):
        record = json.loads(state_path(item["request_id"]).read_text())
        if record.get("account") != account() or record.get("request_id") != item["request_id"]:
            raise RuntimeError("Batch receipt identity mismatch")
        entries.append({"index": index, "request_id": item["request_id"], "state": record.get("state"), "preview": item["preview"]})
    return {"batch_id": batch_id, "requests": entries, "completed": sum(x["state"] == "completed" for x in entries), "count": len(entries)}


def request_status(request_id):
    """Read a single local receipt without exposing mail arguments or confirmation tokens."""
    record = json.loads(state_path(request_id).read_text())
    if (record.get("account") != account() or record.get("request_id") != request_id or
            record.get("tool") not in WRITE_TOOLS):
        raise ValueError("Invalid operation receipt identity")
    return {key: record.get(key) for key in ("request_id", "state", "account", "tool", "created_at", "failure_code")}


def read_json_input(path):
    """Accept UTF-8 JSON from a file or stdin; do not echo malformed input."""
    try:
        if str(path) == "-":
            content = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("Mail JSON input exceeds 8 MiB")
            return json.loads(content.decode("utf-8"))
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Mail input must be valid UTF-8 JSON; contents omitted") from None


async def locate_delete_target(mail, record):
    """Reconcile only the approved exact ID in a narrow original-date window."""
    created = record.get("preview", {}).get("original_date")
    if not created:
        raise RuntimeError("Cannot safely renew: original date missing; reconcile this message before another attempt")
    date = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Reviewed message date needs a timezone")
    for folder in ("trash", "inbox", "spam", "sent"):
        cursor = None
        for _ in range(20):
            args = {"alias_id": mail.alias_id, "dir": folder, "limit": 50,
                    "after": (date - timedelta(seconds=1)).isoformat(), "before": (date + timedelta(seconds=1)).isoformat()}
            if cursor:
                args["cursor"] = cursor
            page = await mail.call("ListMessages", args)
            if any(x.get("message_id") == record["arguments"]["message_id"] for x in page.get("data", [])):
                return folder
            pagination = page.get("pagination", {})
            next_cursor = pagination.get("next_cursor")
            if not pagination.get("has_more"):
                break
            if not next_cursor or next_cursor == cursor:
                raise RuntimeError("Unexpected pagination while reconciling deletion")
            cursor = next_cursor
        else:
            raise RuntimeError("Reconciliation exceeded the bounded page limit")
    raise RuntimeError("Approved message was not located; stop instead of guessing or retrying")


async def renew_delete_challenge(mail, record, stream):
    folder = await locate_delete_target(mail, record)
    if folder == "trash":
        record.update({"state": "completed", "result": {"verified_in_trash": True, "already_in_trash": True}})
        record.pop("arguments", None)
        record.pop("confirmation_token", None)
        update_locked(stream, record)
        return False
    record["state"] = "preparing"
    update_locked(stream, record)
    try:
        raw = await mail.raw_call("DeleteMessage", {**record["arguments"], "alias_id": mail.alias_id})
        fresh = confirmation(decode_result(raw))
        if not fresh or fresh[1] != record["operation_summary"]:
            raise RuntimeError("Renewed deletion does not match the approved summary; do not submit")
        record.update({"state": "pending", "confirmation_token": fresh[0], "created_at": time.time()})
        record.pop("failure_code", None)
        update_locked(stream, record)
    except BaseException:
        record["state"] = "unknown"
        update_locked(stream, record)
        raise
    return True


async def confirm(request_id, client=CodexMail, renew_delete=False):
    fd = os.open(state_path(request_id), os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("This request is already being handled")
        try:
            record = json.load(stream)
        except (ValueError, OSError) as error:
            raise RuntimeError("Cannot read the prepared operation; reconcile mailbox state before proceeding") from error
        if record.get("account") != account() or record.get("request_id") != request_id:
            raise RuntimeError("Request identity mismatch")
        known_expiry = record.get("tool") == "DeleteMessage" and record.get("state") == "failed" and record.get("failure_code") == "40001"
        if record.get("state") != "pending" and not known_expiry:
            raise RuntimeError("Request already used or has an unknown outcome; do not retry")
        expired = time.time() - record["created_at"] > 600
        if expired and record["tool"] != "DeleteMessage":
            raise RuntimeError("Local confirmation expired; prepare a new request for review")
        tool, arguments = record["tool"], record["arguments"]
        validate_arguments(tool, arguments)
        if fingerprint(tool, arguments) != record["fingerprint"]:
            raise RuntimeError("Prepared arguments changed; do not submit")
        async with client(write_tool=tool) as mail:
            if tool == "DeleteMessage" and (renew_delete or expired or known_expiry):
                if not await renew_delete_challenge(mail, record, stream):
                    return {"state": "completed", "request_id": request_id, "result": record["result"]}
            wire = {**arguments, "alias_id": mail.alias_id, "confirmation_token": record["confirmation_token"]}
            if tool != "DeleteMessage":
                wire["skip_confirmation"] = False
            record["state"] = "submitting"
            update_locked(stream, record)
            try:
                raw = await mail.raw_call(tool, wire)
                payload = decode_result(raw)
                if raw.get("isError") or confirmation(payload) or endpoint_error(payload):
                    record["state"] = "failed"
                    if tool == "DeleteMessage" and any(str(x.get("code", x.get("error_code", ""))) == "40001" for x in nodes(payload) if isinstance(x, dict)):
                        record["failure_code"] = "40001"
                    raise RuntimeError("Tencent did not confirm completion; inspect the mailbox before preparing another request")
                if not acknowledged(tool, arguments, payload):
                    raise RuntimeError("No positive write acknowledgment; reconcile mailbox state")
                record["state"] = "completed"
                record["result"] = payload
            except BaseException:
                if record["state"] == "submitting":
                    record["state"] = "unknown"
                update_locked(stream, record)
                raise
            record.pop("confirmation_token", None)
            record.pop("arguments", None)
            update_locked(stream, record)
            return {"state": "completed", "request_id": request_id, "result": payload}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Configured mailbox profile")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--tool", choices=WRITE_TOOLS, required=True)
    p.add_argument("--arguments-file", type=Path, required=True, help="Private JSON file, or - to read UTF-8 JSON from stdin")
    p = sub.add_parser("execute-authorized")
    p.add_argument("--tool", choices=("SendMessage", "ReplyMessage", "ForwardMessage"), required=True)
    p.add_argument("--arguments-file", type=Path, required=True, help="Private JSON file, or - to read UTF-8 JSON from stdin")
    p.add_argument("--user-authorized", action="store_true", required=True, help="Use when the human explicitly requested this exact mail operation; no extra confirmation prompt")
    p = sub.add_parser("confirm")
    p.add_argument("--request-id", required=True)
    p.add_argument("--user-approved", action="store_true", required=True, help="Use only after the human approves the displayed operation")
    p.add_argument("--renew-confirmation", action="store_true", help="Deletion only: reconcile target and refresh the identical approved summary")
    p = sub.add_parser("prepare-delete-batch")
    p.add_argument("--review-file", type=Path, required=True, help="JSON array of reviewed message metadata; - reads stdin")
    p = sub.add_parser("confirm-delete-batch")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--indices", help="Comma-separated 1-based indices; omit only when the human approved the entire batch")
    p.add_argument("--user-approved", action="store_true", required=True)
    p = sub.add_parser("batch-status", help="Read local per-message receipts after a partial or interrupted batch; never resubmits")
    p.add_argument("--batch-id", required=True)
    p = sub.add_parser("request-status", help="Read one local write receipt without contacting mail or resubmitting")
    p.add_argument("--request-id", required=True)
    args = parser.parse_args()
    if args.profile:
        select_profile(args.profile)
    if args.command == "prepare":
        result = await prepare(args.tool, read_json_input(args.arguments_file))
    elif args.command == "execute-authorized":
        result = await execute_authorized(args.tool, read_json_input(args.arguments_file), user_authorized=args.user_authorized)
    elif args.command == "confirm":
        result = await confirm(args.request_id, renew_delete=args.renew_confirmation)
    elif args.command == "prepare-delete-batch":
        result = await prepare_delete_batch(read_json_input(args.review_file))
    elif args.command == "batch-status":
        result = batch_status(args.batch_id)
    elif args.command == "request-status":
        result = request_status(args.request_id)
    else:
        indices = [int(i) for i in args.indices.split(",")] if args.indices else None
        result = await confirm_delete_batch(args.batch_id, indices=indices)
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, ValueError, OSError, asyncio.TimeoutError) as error:
        print(redact(str(error)), file=sys.stderr)
        sys.exit(1)
