"""IMAP reader for the host bridge. Invoked only as a child of run.mjs.

stdout carries JSON with the code; the parent never echoes it. The password is
read from a 0600 file at the path given in WB_BRIDGE_IMAP (no password in argv,
no password in stdout).
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import re
import sys

CODE_RE = re.compile(r'(?<!\d)(\d{4,8})(?!\d)')
STAMP_RE = re.compile(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')
PURPOSE_RE = re.compile(r'验证码|校验码|动态码|verification code|passcode', re.I)


def _text_body(msg) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                parts.append(part.get_payload(decode=True) or b'')
        raw = b'\n'.join(parts)
    else:
        raw = msg.get_payload(decode=True) or b''
    charset = msg.get_content_charset() or 'utf-8'
    return raw.decode(charset, 'replace')


def main() -> int:
    raw = os.environ.get('WB_BRIDGE_IMAP', '')
    if not raw:
        print(json.dumps({'ok': False, 'reason': 'bridge_env_missing'}))
        return 1
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({'ok': False, 'reason': 'bridge_env_invalid'}))
        return 1

    out = {'ok': False, 'reason': None}
    conn = None
    try:
        with open(cfg['password_file'], 'r', encoding='utf-8') as handle:
            password = handle.read().strip()
        conn = imaplib.IMAP4_SSL(cfg['host'], 993)
        conn.login(cfg['user'], password)
        conn.select('INBOX', readonly=True)

        typ, data = conn.search(None, 'ALL')
        if typ != 'OK':
            out['reason'] = 'imap_search_failed'
            print(json.dumps(out))
            return 1

        sender = (cfg.get('sender') or '').lower()
        for mid in reversed(data[0].split()[-int(cfg.get('limit', 5)):]):
            typ, fetched = conn.fetch(mid, '(RFC822)')
            if typ != 'OK' or not fetched or not fetched[0]:
                continue
            msg = email.message_from_bytes(fetched[0][1])
            if sender and sender not in str(msg.get('From', '')).lower():
                continue
            body = _text_body(msg)
            if not PURPOSE_RE.search(body):
                continue
            codes = {m.group(1) for line in body.splitlines()
                     if PURPOSE_RE.search(line) for m in [CODE_RE.search(line)] if m}
            if len(codes) != 1:
                out['reason'] = 'code_ambiguous_or_missing'
                continue
            code = codes.pop()
            out.update(ok=True, code=code, code_length=len(code),
                       has_body_time=bool(STAMP_RE.search(body)))
            break
        if not out['ok'] and not out['reason']:
            out['reason'] = 'no_matching_message'
    except Exception as exc:  # 不回显异常原文，避免正文或凭据进入日志
        out['reason'] = type(exc).__name__
    finally:
        try:
            if conn is not None:
                conn.logout()
        except Exception:
            pass

    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
