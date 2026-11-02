"""IMAP reader for the host bridge. Invoked only as a child of run.mjs.

Emits the FULL normalized message (from/to/subject/body/created_at) plus the
extracted code. stdout is captured by the parent via a pipe and never echoed;
the parent passes the message to the skill's own verifier before any fill.

Password comes from a 0600 file named in WB_BRIDGE_IMAP (path, never content).
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import re
import sys
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

CODE_RE = re.compile(r'(?<!\d)(\d{4,8})(?!\d)')
PURPOSE_RE = re.compile(r'验证码|校验码|动态码|verification code|passcode', re.I)
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def _text_body(msg) -> str:
    if msg.is_multipart():
        chunks = [part.get_payload(decode=True) or b'' for part in msg.walk()
                  if part.get_content_type() == 'text/plain']
        raw = b'\n'.join(chunks)
    else:
        raw = msg.get_payload(decode=True) or b''
    return raw.decode(msg.get_content_charset() or 'utf-8', 'replace')


def _header(msg, name: str) -> str:
    raw = msg.get(name, '')
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _created_at(msg) -> str | None:
    raw = msg.get('Date')
    if not raw:
        return None
    try:
        return parsedate_to_datetime(str(raw)).isoformat()
    except Exception:
        return None


def _since_clause(after: str) -> str:
    """IMAP SINCE 只到日粒度；回退一天，精确窗口仍由校验器判定。"""
    try:
        day = date.fromisoformat((after or '')[:10])
    except ValueError:
        return ''
    earlier = day - timedelta(days=1)
    return f'SINCE {earlier.day:02d}-{MONTHS[earlier.month - 1]}-{earlier.year}'


def main() -> int:
    raw_env = os.environ.get('WB_BRIDGE_IMAP', '')
    if not raw_env:
        print(json.dumps({'ok': False, 'reason': 'bridge_env_missing'}))
        return 1
    try:
        cfg = json.loads(raw_env)
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

        sender = cfg.get('sender', '')
        criteria = f'(FROM "{sender}")'
        since = _since_clause(cfg.get('after', ''))
        if since:
            criteria = f'(FROM "{sender}" {since})'
        typ, data = conn.search(None, criteria)
        if typ != 'OK':
            out['reason'] = 'imap_search_failed'
            print(json.dumps(out))
            return 1

        candidates = []
        for mid in data[0].split()[-int(cfg.get('limit', 10)):]:
            typ, fetched = conn.fetch(mid, '(RFC822)')
            if typ != 'OK' or not fetched or not fetched[0]:
                continue
            msg = email.message_from_bytes(fetched[0][1])
            body = _text_body(msg)
            if not PURPOSE_RE.search(body):
                continue
            candidates.append({
                'message_id': mid.decode() if isinstance(mid, bytes) else str(mid),
                'from': _header(msg, 'From'),
                'to': _header(msg, 'To'),
                'subject': _header(msg, 'Subject'),
                'body': body,
                'body_format': 'text',
                'created_at': _created_at(msg),
            })

        if not candidates:
            out['reason'] = 'no_matching_message'
            print(json.dumps(out))
            return 1

        # 多条候选全部交给上层校验器挑选，适配器不做终判
        out.update(ok=True, messages=candidates)
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
