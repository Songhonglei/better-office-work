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
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from qq_mail import WRITE_TOOLS, CodexMail, decode_result, endpoint_error, AuthenticationError, preflight_attachment, MAX_ATTACHMENT_BYTES
from mail_config import account, load_settings, private_dir, select_profile, redact, contains_runtime_secret
from mail_credentials import sync_directory, atomic_record
from verification_rules import VerificationFailure, fail, match_body, match_attachments
import fcntl
import tempfile
import stat

PENDING = None  # Test override; runtime state always lives outside the installed skill.
MAX_RECEIPT_BYTES = 16 * 1024 * 1024


def pending_dir():
    return Path(PENDING).resolve() if PENDING is not None else load_settings().state_dir / "pending"


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
    total = sum(a["size"] for a in attachments)
    if total > 3 * MAX_ATTACHMENT_BYTES:
        raise ValueError("Total attachment size exceeds the verified 3 MiB limit")
    for attachment in attachments:
        preflight_attachment(attachment["size"], attachment["content"])
        data = base64.b64decode(attachment["content"], validate=True)
        if len(data) != attachment["size"] or hashlib.sha1(data).hexdigest() != attachment["sha1"].lower():
            raise ValueError("Attachment size or SHA-1 does not match its content")
        if len(data) > 1048576:
            raise ValueError("Attachment exceeds the verified 1 MiB limit")



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


@contextmanager
def receipt_lock(request_id):
    """Lock a stable inode; receipt JSON may be atomically replaced underneath it."""
    private_dir(pending_dir())
    path = state_path(request_id).with_suffix(".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        info = os.fstat(lock.fileno())
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Unsafe operation lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Operation is already being handled; query the original receipt, never resubmit") from None
        recover_publication(request_id)
        yield lock


def read_private_record(path, *, links=1):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode) or info.st_nlink != links or info.st_size > MAX_RECEIPT_BYTES:
            raise RuntimeError("Unsafe operation receipt")
        try:
            record = json.load(stream)
        except (ValueError, UnicodeError):
            raise RuntimeError("Unreadable operation receipt; reconcile externally without resubmitting") from None
    return record, info


def read_receipt(request_id):
    record, _ = read_private_record(state_path(request_id))
    if not isinstance(record, dict) or record.get("account") != account() or record.get("request_id") != request_id:
        raise ValueError("Invalid operation receipt identity")
    return record


def recovery_identity(record, request_id):
    if not isinstance(record, dict) or record.get("account") != account() or record.get("request_id") != request_id:
        raise RuntimeError("Publication recovery identity mismatch; reconcile without resubmitting")
    if record.get("type") == "delete_batch":
        if not isinstance(record.get("requests"), list) or not record["requests"]:
            raise RuntimeError("Invalid batch publication")
        return
    tool = record.get("tool")
    arguments = record.get("intended", record.get("arguments"))
    validate_arguments(tool, arguments)
    if fingerprint(tool, arguments) != record.get("fingerprint"):
        raise RuntimeError("Publication recovery content mismatch; reconcile without resubmitting")
    if record.get("operation_id") is not None:
        if operation_identity(tool, arguments, record["operation_id"])[1] != request_id:
            raise RuntimeError("Publication recovery operation identity mismatch")


def recover_publication(request_id):
    """Only under the stable lock: finish a proven interrupted initial publication.

    No provider connection and no state transition authorizing another send.
    Ambiguous, partial, foreign or externally hard-linked records remain blocked.
    """
    path = state_path(request_id)
    named = list(pending_dir().glob(f".operation-{request_id}-*"))
    if os.path.lexists(path):
        info = path.lstat()
        if info.st_nlink == 1:
            if named:
                raise RuntimeError("Ambiguous publication temporary files; reconcile without resubmitting")
            return
        record, info = read_private_record(path, links=2)
        recovery_identity(record, request_id)
        aliases = []
        for candidate in pending_dir().glob(".operation-*"):
            try:
                candidate_info = candidate.lstat()
            except FileNotFoundError:
                continue  # Another operation can finish publishing concurrently.
            if (candidate_info.st_dev, candidate_info.st_ino) == (info.st_dev, info.st_ino):
                aliases.append(candidate)
        if len(aliases) != 1 or any(p != aliases[0] for p in named):
            raise RuntimeError("Unproven receipt hard link; reconcile without resubmitting")
        temporary = aliases[0]
        _, alias_info = read_private_record(temporary, links=2)
    else:
        if not named:
            return
        if len(named) != 1:
            raise RuntimeError("Ambiguous initial receipt; reconcile without resubmitting")
        temporary = named[0]
        record, info = read_private_record(temporary)
        recovery_identity(record, request_id)
        # Preserve the original conservative barrier even when no RPC took place.
        os.link(temporary, path, follow_symlinks=False)
        sync_directory(pending_dir())
        alias_info = temporary.lstat()
    current = path.lstat()
    alias = temporary.lstat()
    if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
            or (alias.st_dev, alias.st_ino) != (info.st_dev, info.st_ino)
            or alias_info.st_ino != info.st_ino or current.st_nlink != 2 or alias.st_nlink != 2
            or not stat.S_ISREG(alias.st_mode)):
        raise RuntimeError("Publication changed during recovery; reconcile without resubmitting")
    temporary.unlink()  # Only the proven second name for this exact inode.
    sync_directory(pending_dir())
    read_receipt(request_id)  # Recheck ownership/mode/identity and sole remaining link.
    record["receipt_recovery"] = {"code": "initial_publication_completed", "at": time.time(), "state_unchanged": True}
    atomic_record(path, receipt_payload(record))


def receipt_payload(record):
    payload = redact(record)
    # atomic_record uses ASCII escapes; preflight that representation as well.
    if len(json.dumps(payload).encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise RuntimeError("Receipt size exceeds 16 MiB; previous evidence retained, reconcile without resubmitting")
    return payload


def save_new(record):
    payload = receipt_payload(record)
    private_dir(pending_dir())
    fd, temporary = tempfile.mkstemp(prefix=f".operation-{record['request_id']}-", dir=pending_dir())
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, state_path(record["request_id"]))
        sync_directory(pending_dir())
    finally:
        if os.path.lexists(state_path(record["request_id"])):
            Path(temporary).unlink(missing_ok=True)
            sync_directory(pending_dir())


def update_locked(stream, record):
    # Caller holds the separate .lock inode, not the replaced JSON inode.
    atomic_record(state_path(record["request_id"]), receipt_payload(record))


def operation_identity(tool, arguments, operation_id=None):
    digest = fingerprint(tool, arguments)
    # Legacy Python callers remain safe: identical normalized content gets a
    # stable identity. CLI callers must provide the host's durable job ID.
    operation_id = "content-" + digest if operation_id is None else operation_id
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", operation_id):
        raise ValueError("operation_id must be 1..128 ASCII letters/digits or _ . : -")
    if contains_runtime_secret(operation_id):
        raise ValueError("operation_id must not contain credentials")
    request_id = hashlib.sha256(json.dumps([load_settings().profile, account(), operation_id]).encode()).hexdigest()[:32]
    return operation_id, request_id, digest


def original_operation(request_id, operation_id, digest, tool):
    if not os.path.lexists(state_path(request_id)):
        return None
    record = read_receipt(request_id)
    if record.get("operation_id") != operation_id or record.get("fingerprint") != digest or record.get("tool") != tool:
        raise ValueError("operation_id is already bound to different mail content/tool; do not reuse it")
    return public_receipt(record)


def public_receipt(record):
    result = {key: record.get(key) for key in ("request_id", "operation_id", "state", "account", "tool", "created_at", "failure_code", "verification", "evidence", "selection", "receipt_recovery", "last_verification_attempt")}
    if record.get("state") == "pending":
        result.update(state="awaiting_user_confirmation", operation_summary=record.get("operation_summary"))
    if "result" in record:
        result["result"] = record["result"]
    if record.get("state") == "completed" and record.get("tool") != "DeleteMessage":
        result.update(state="legacy_unverified", verification={"qq_accepted": "unknown", "sent_verified": False, "recipient_verified": False})
    return result


def accepted_receipt(record, payload):
    record.update(state="accepted", result=payload,
        verification={"qq_accepted": True, "sent_verified": False, "recipient_verified": False})
    # Keep the intended content privately for evidence matching, not in public status.
    record["intended"] = record.pop("arguments")
    record.pop("confirmation_token", None)


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
    return {"state": "awaiting_user_confirmation", "request_id": record["request_id"], "operation_id": record.get("operation_id"), "preview": record["preview"],
            "operation_summary": record["operation_summary"],
            "instructions": "Show this summary and the exact content to the user; call confirm only after their explicit approval."}


async def prepare_on_client(mail, tool, arguments, preview, operation_id=None):
    """Persist intent before a prepare RPC, which could itself lose its response."""
    op, request_id, digest = operation_identity(tool, arguments, operation_id) if tool != "DeleteMessage" else (None, uuid.uuid4().hex, fingerprint(tool, arguments))
    record = {"request_id": request_id, "operation_id": op, "state": "preparing", "account": account(), "tool": tool,
              "arguments": arguments, "fingerprint": fingerprint(tool, arguments), "preview": preview, "created_at": time.time()}
    with receipt_lock(request_id) as stream:
        if op is not None:
            prior = original_operation(request_id, op, digest, tool)
            if prior is not None:
                return prior
        save_new(record)
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


async def execute_authorized(tool, arguments, *, user_authorized=False, client=CodexMail, operation_id=None):
    if not user_authorized or tool not in ("SendMessage", "ReplyMessage", "ForwardMessage"):
        raise ValueError("An explicit user send/reply/forward instruction is required")
    validate_arguments(tool, arguments)
    arguments = dict(arguments)
    arguments.setdefault("body_format", "PLAIN")
    if tool == "ReplyMessage":
        arguments.setdefault("reply_all", False)
    if tool == "ForwardMessage":
        arguments.setdefault("include_attachments", False)
    operation_id, request_id, digest = operation_identity(tool, arguments, operation_id)
    with receipt_lock(request_id) as stream:
        prior = original_operation(request_id, operation_id, digest, tool)
        if prior is not None:
            return prior  # No credential read, client connection or mail RPC.
        record = {"request_id": request_id, "operation_id": operation_id, "mode": "user_authorized_send",
                  "state": "submitting", "account": account(), "tool": tool, "arguments": arguments,
                  "fingerprint": digest, "created_at": time.time()}
        save_new(record)
        try:
            async with client(write_tool=tool, user_authorized_send=True) as mail:
                raw = await mail.raw_call(tool, {**arguments, "alias_id": mail.alias_id, "skip_confirmation": True})
                payload = decode_result(raw)
                challenge = confirmation(payload)
                if challenge:
                    record.update(state="pending", confirmation_token=challenge[0], operation_summary=challenge[1])
                else:
                    if raw.get("isError") or endpoint_error(payload):
                        record["state"] = "failed"
                        raise RuntimeError("Tencent rejected the write")
                    if not acknowledged(tool, arguments, payload):
                        raise RuntimeError("No positive write acknowledgment")
                    accepted_receipt(record, payload)
                update_locked(stream, record)
                return public_receipt(record)
        except BaseException as error:
            if record["state"] in ("submitting", "accepted"):
                record["state"] = "unknown"
            update_locked(stream, record)
            suffix = "; authorization rejected: securely update authorization and verify first" if isinstance(error, AuthenticationError) else ""
            raise RuntimeError(f"Write outcome is {record['state']} (request {request_id}); do not automatically retry" + suffix) from None


async def prepare(tool, arguments, client=CodexMail, operation_id=None):
    validate_arguments(tool, arguments)
    arguments = dict(arguments)
    if tool == "ReplyMessage":
        arguments.setdefault("reply_all", False)
    if tool == "ForwardMessage":
        arguments.setdefault("include_attachments", False)
    if tool != "DeleteMessage":
        arguments.setdefault("body_format", "PLAIN")
    if tool != "DeleteMessage":
        op, request_id, digest = operation_identity(tool, arguments, operation_id)
        with receipt_lock(request_id):
            prior = original_operation(request_id, op, digest, tool)
            if prior is not None:
                return prior
    async with client(write_tool=tool) as mail:
        preview = {"account": account(), "tool": tool}
        if arguments.get("message_id"):
            original = await mail.call("GetMessage", {"alias_id": mail.alias_id, "message_id": arguments["message_id"]})
            preview.update({"original_subject": original.get("subject"), "original_sender": original.get("from"), "original_date": original.get("created_at")})
        preview.update({k: arguments[k] for k in ("to", "cc", "bcc", "subject", "reply_all", "include_attachments") if k in arguments})
        preview["attachments"] = [{k: a[k] for k in ("filename", "content_type", "size", "sha1")} for a in arguments.get("attachments", [])]
        return await prepare_on_client(mail, tool, arguments, preview, operation_id=operation_id)


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
    with receipt_lock(batch_id):
        batch = read_receipt(batch_id)
    if batch.get("type") != "delete_batch" or batch.get("account") != account():
        raise ValueError("Invalid deletion batch")
    requests = batch["requests"]
    indices = list(range(1, len(requests) + 1)) if indices is None else indices
    if not indices or len(indices) != len(set(indices)) or any(type(i) is not int or not 1 <= i <= len(requests) for i in indices):
        raise ValueError("Invalid selected indices")
    selected = [requests[i - 1] for i in indices]
    for item in selected:
        with receipt_lock(item["request_id"]):
            record = read_receipt(item["request_id"])
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
    with receipt_lock(batch_id):
        batch = read_receipt(batch_id)
    if batch.get("type") != "delete_batch" or batch.get("account") != account():
        raise ValueError("Invalid deletion batch")
    entries = []
    for index, item in enumerate(batch["requests"], 1):
        with receipt_lock(item["request_id"]):
            record = read_receipt(item["request_id"])
        if record.get("account") != account() or record.get("request_id") != item["request_id"]:
            raise RuntimeError("Batch receipt identity mismatch")
        entries.append({"index": index, "request_id": item["request_id"], "state": record.get("state"), "preview": item["preview"]})
    return {"batch_id": batch_id, "requests": entries, "completed": sum(x["state"] == "completed" for x in entries), "count": len(entries)}


def status_record(record):
    if record.get("tool") not in WRITE_TOOLS:
        raise ValueError("Invalid operation receipt identity")
    result = {key: record.get(key) for key in ("request_id", "operation_id", "state", "account", "tool", "created_at", "failure_code", "verification", "evidence", "selection", "receipt_recovery", "last_verification_attempt")}
    if record.get("state") == "completed" and record["tool"] != "DeleteMessage":
        result.update(state="legacy_unverified", verification={"qq_accepted": "unknown", "sent_verified": False, "recipient_verified": False})
    return result


def request_status(request_id):
    """Recover publication and read locally under lock; no provider RPC or resend."""
    with receipt_lock(request_id):
        return status_record(read_receipt(request_id))


def observation_match(record, observation, *, allow_qq_style_scope=False, allow_gmail_octet_stream=False):
    stage = observation["stage"]
    intended = record.get("intended", record.get("arguments"))
    def addresses(items):
        if not isinstance(items, list) or any(not isinstance(p, dict) or not isinstance(p.get("email"), str) for p in items):
            fail("recipient_evidence_missing", "Verification recipients are incomplete")
        return sorted(p["email"].casefold() for p in items)
    if observation.get("from") != record["account"]:
        fail("sender_changed", "Verification sender differs from the intended QQ account")
    recipients = sum((addresses(intended.get(field, [])) for field in ("to", "cc", "bcc")), [])
    if stage == "sent":
        if observation["provider"] != "qq" or observation["folder"] != "sent" or observation["account"].casefold() != record["account"]:
            fail("source_not_independent", "Sent evidence must come from this QQ account's sent folder")
    elif observation["provider"].casefold() == "qq" or observation["account"].casefold() not in recipients:
        fail("source_not_independent", "Recipient evidence must come from an independent recipient mailbox")
    for field in ("to", "cc", "bcc") if stage == "sent" else ("to", "cc"):
        if addresses(observation.get(field, [])) != addresses(intended.get(field, [])):
            fail("recipients_changed", "Verification recipients differ from the intended mail")
    if observation.get("subject") != intended.get("subject"):
        fail("subject_changed", "Verification subject differs or is incomplete")
    body = match_body(intended, observation, allow_qq_style_scope=allow_qq_style_scope)
    attachments = match_attachments(intended, observation, allow_gmail_octet_stream=allow_gmail_octet_stream)
    if observation.get("time_basis") != ("qq_sent_at" if stage == "sent" else "mailbox_received_at"):
        fail("time_basis_missing", "An established mailbox timestamp basis is required; created_at is not receipt time")
    try:
        timestamp = datetime.fromisoformat(observation.get("observed_mail_at").replace("Z", "+00:00"))
        if timestamp.tzinfo is None or not record["created_at"]-5 <= timestamp.timestamp() <= time.time()+60:
            raise ValueError("unbound observation time")
    except (AttributeError, TypeError, ValueError, OverflowError):
        fail("mail_timestamp_invalid", "A timezone-aware mail timestamp tied to this operation is required")
    acknowledged_id = record.get("result", {}).get("message_id")
    if stage == "sent" and acknowledged_id and observation["message_id"] != acknowledged_id:
        fail("message_id_changed", "Sent evidence differs from the acknowledged message ID")
    return body, attachments


def record_verification(request_id, observation, *, allow_qq_style_scope=False, allow_gmail_octet_stream=False):
    """Match actual host observations; compatibility is explicit and provider-bound."""
    if not isinstance(observation, dict):
        fail("observation_missing", "Verification requires an independent normalized observation")
    stage = observation.get("stage")
    if stage not in ("sent", "recipient"):
        fail("stage_invalid", "Verification stage must be sent or recipient")
    for key in ("provider", "message_id", "source_reference", "folder", "account"):
        if not isinstance(observation.get(key), str) or not observation[key].strip():
            fail("source_evidence_missing", "Verification observation lacks source identity/reference")
    if contains_runtime_secret(observation):
        fail("credentials_forbidden", "Verification must not contain runtime credentials")
    with receipt_lock(request_id) as stream:
        record = read_receipt(request_id)
        if record.get("tool") != "SendMessage" or "intended" not in record and "arguments" not in record:
            fail("intent_unavailable", "Retained SendMessage intent is required; do not infer reply/forward content")
        if record.get("state") not in ("accepted", "sent_verified", "recipient_verified", "unknown", "submitting"):
            fail("state_ineligible", "This operation is not eligible for evidence reconciliation")
        # Preserve actual body independently, never copy intent into observation.
        # Attachment bytes are compared in memory; only their digests are retained.
        snapshot = {key: observation[key] for key in ("provider", "message_id", "source_reference", "folder", "account", "body", "body_format", "subject", "observed_mail_at", "time_basis") if key in observation}
        attempt = {"at": time.time(), "stage": stage, "status": "failed"}
        try:
            body, attachments = observation_match(record, observation,
                allow_qq_style_scope=allow_qq_style_scope, allow_gmail_octet_stream=allow_gmail_octet_stream)
        except VerificationFailure as error:
            # Do not overwrite any previously verified observation/evidence.
            record["last_verification_attempt"] = {**attempt, **error.as_dict()}
            record["last_verification_observation"] = snapshot
            update_locked(stream, record)
            raise
        verification = record.setdefault("verification", {"qq_accepted": False, "sent_verified": False, "recipient_verified": False})
        verification["qq_accepted"] = True
        verification[stage+"_verified"] = True
        record.setdefault("verification_observations", {})[stage] = snapshot
        record.setdefault("evidence", {})[stage] = {key: observation[key] for key in ("provider", "message_id", "source_reference", "folder", "account", "observed_mail_at", "time_basis")}
        record["evidence"][stage].update(verified_at=time.time(), source="host_independent_observation", body=body, attachments=attachments)
        record["last_verification_attempt"] = {**attempt, "status": "passed", "code": "matched"}
        record.pop("last_verification_observation", None)
        record["state"] = "recipient_verified" if verification["recipient_verified"] else "sent_verified"
        record["intended"] = record.get("intended", record.get("arguments"))
        record.pop("arguments", None)
        record.pop("confirmation_token", None)
        update_locked(stream, record)
        return status_record(record)


def record_selection(request_id, source_message_id, user_reference, *, user_selected=False):
    """Record an explicit human candidate selection without asserting receipt time."""
    if not user_selected or any(not isinstance(x, str) or not x.strip() for x in (source_message_id, user_reference)):
        fail("user_selection_required", "An explicit user choice, source message ID and human instruction reference are required")
    selection = {"basis": "user_selected", "source_message_id": source_message_id, "user_reference": user_reference}
    if contains_runtime_secret(selection):
        fail("credentials_forbidden", "Selection must not contain credentials")
    with receipt_lock(request_id) as stream:
        record = read_receipt(request_id)
        if record.get("tool") not in ("SendMessage", "ReplyMessage", "ForwardMessage"):
            fail("state_ineligible", "Candidate selection only applies to a sending operation")
        if record.get("selection") and record["selection"] != selection:
            fail("selection_changed", "This operation already records a different user selection")
        record["selection"] = selection
        update_locked(stream, record)
        return status_record(record)


def read_json_input(path):
    """Accept UTF-8 JSON from a file or stdin; do not echo malformed input."""
    try:
        if str(path) == "-":
            content = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        else:
            with path.open("rb") as stream:
                content = stream.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("Mail JSON input exceeds 8 MiB")
        return json.loads(content.decode("utf-8"))
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
    with receipt_lock(request_id) as stream:
        try:
            record = read_receipt(request_id)
        except ValueError:
            raise RuntimeError("Request identity mismatch") from None
        if record.get("tool") not in WRITE_TOOLS:
            raise RuntimeError("Unsupported operation receipt")
        if record.get("tool") != "DeleteMessage" and record.get("state") not in ("pending",):
            return public_receipt(record)
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
                if tool == "DeleteMessage":
                    record.update(state="completed", result=payload)
                else:
                    accepted_receipt(record, payload)
            except BaseException:
                if record["state"] == "submitting":
                    record["state"] = "unknown"
                update_locked(stream, record)
                raise
            record.pop("confirmation_token", None)
            record.pop("arguments", None)
            update_locked(stream, record)
            return public_receipt(record)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Configured mailbox profile")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--operation-id", help="Durable host job ID; required for sending/reply/forward")
    p.add_argument("--tool", choices=WRITE_TOOLS, required=True)
    p.add_argument("--arguments-file", type=Path, required=True, help="Private JSON file, or - to read UTF-8 JSON from stdin")
    p = sub.add_parser("execute-authorized")
    p.add_argument("--operation-id", required=True, help="Reuse this durable ID for every retry of the same mail")
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
    p = sub.add_parser("record-verification", help="Match an independent host observation against retained SendMessage intent; no mail RPC")
    p.add_argument("--request-id", required=True)
    p.add_argument("--observation-file", type=Path, required=True, help="Private normalized observation JSON; - reads stdin")
    p.add_argument("--allow-qq-style-scope", action="store_true", help="QQ sent HTML only: permit one extra .qmbox prefix per supported CSS selector")
    p.add_argument("--allow-gmail-octet-stream", action="store_true", help="Gmail recipient only: permit PDF/XML MIME fallback with identical filenames and full bytes")
    p = sub.add_parser("record-selection", help="Record an explicit human candidate choice; no receipt-time claim or mail RPC")
    p.add_argument("--request-id", required=True)
    p.add_argument("--source-message-id", required=True)
    p.add_argument("--user-reference", required=True, help="Reference to the human choice, never a mail-body instruction")
    p.add_argument("--user-selected", action="store_true", required=True)
    p = sub.add_parser("request-status", help="Read one local write receipt without contacting mail or resubmitting")
    p.add_argument("--request-id", required=True)
    args = parser.parse_args()
    if args.profile:
        select_profile(args.profile)
    if args.command == "prepare":
        if args.tool != "DeleteMessage" and not args.operation_id:
            parser.error("--operation-id is required for sending/reply/forward preparation")
        result = await prepare(args.tool, read_json_input(args.arguments_file), operation_id=args.operation_id)
    elif args.command == "execute-authorized":
        result = await execute_authorized(args.tool, read_json_input(args.arguments_file), user_authorized=args.user_authorized, operation_id=args.operation_id)
    elif args.command == "confirm":
        result = await confirm(args.request_id, renew_delete=args.renew_confirmation)
    elif args.command == "prepare-delete-batch":
        result = await prepare_delete_batch(read_json_input(args.review_file))
    elif args.command == "batch-status":
        result = batch_status(args.batch_id)
    elif args.command == "record-verification":
        result = record_verification(args.request_id, read_json_input(args.observation_file),
            allow_qq_style_scope=args.allow_qq_style_scope, allow_gmail_octet_stream=args.allow_gmail_octet_stream)
    elif args.command == "record-selection":
        result = record_selection(args.request_id, args.source_message_id, args.user_reference, user_selected=args.user_selected)
    elif args.command == "request-status":
        result = request_status(args.request_id)
    else:
        indices = [int(i) for i in args.indices.split(",")] if args.indices else None
        result = await confirm_delete_batch(args.batch_id, indices=indices)
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except VerificationFailure as error:
        print(json.dumps(redact({"verification_error": error.as_dict()}), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, ValueError, OSError, asyncio.TimeoutError) as error:
        print(redact(str(error)), file=sys.stderr)
        sys.exit(1)
