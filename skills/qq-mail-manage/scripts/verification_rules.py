"""Offline evidence matching. Strict by default; two explicit presentation rules.

No provider connection, credentials, HTML execution, or guessed message content.
"""
import base64
import binascii
import hashlib
import re
from html.parser import HTMLParser

from qq_mail import MAX_ATTACHMENT_BYTES, attachment_integrity, preflight_attachment


class VerificationFailure(ValueError):
    def __init__(self, code, message, **details):
        self.code, self.details = code, details
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "message": str(self), "details": self.details}


def fail(code, message, **details):
    raise VerificationFailure(code, message, **details)


def sha256(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


class StyleRanges(HTMLParser):
    """Locate real style contents without serializing or normalizing HTML."""
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.offsets, offset = [], 0
        for line in source.split("\n")[:-1]:
            self.offsets.append(offset)
            offset += len(line) + 1
        self.offsets.append(offset)
        self.active, self.ranges = None, []

    def source_offset(self):
        line, column = self.getpos()
        return self.offsets[line-1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self.active = self.source_offset() + len(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "style" and self.active is not None:
            self.ranges.append((self.active, self.source_offset()))
            self.active = None


def scope_css(css):
    """Only flat basic selector lists. No comments, strings, at-rules or nesting."""
    result, end, count = [], 0, 0
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if css[end:rule.start()].strip():
            return None
        selector, declaration = rule.group(1), rule.group(2)
        # Declaration bytes stay exactly unchanged, including URLs and amounts.
        # Reject complex syntax whose selector boundaries need a CSS parser.
        if "/*" in selector or "@" in selector:
            return None
        parts = []
        for part in selector.split(","):
            leading = re.match(r"\s*", part).group()
            rest = part[len(leading):]
            # Only a single simple :hover pseudo-class is supported by the supplied sample.
            simple = rest.replace(":hover", "")
            if not rest.strip() or rest.count(":hover") > 1 or not re.fullmatch(r"[A-Za-z0-9_.*#>+~ \t\r\n-]+", simple):
                return None
            parts.append(leading + ".qmbox " + rest)
            count += 1
        result.append(",".join(parts) + "{" + declaration + "}")
        end = rule.end()
    if not count or css[end:].strip():
        return None
    return "".join(result) + css[end:], count


def qq_scoped_html(source):
    parser = StyleRanges(source)
    try:
        parser.feed(source)
        parser.close()
    except (ValueError, AssertionError, RecursionError):
        return None
    if parser.active is not None or not 1 <= len(parser.ranges) <= 16:
        return None
    transformed, selectors = source, 0
    for start, end in reversed(parser.ranges):
        scoped = scope_css(source[start:end])
        if scoped is None:
            return None
        css, count = scoped
        transformed = transformed[:start] + css + transformed[end:]
        selectors += count
    return transformed, selectors


def match_body(intended, observation, *, allow_qq_style_scope=False):
    original, actual = intended.get("body"), observation.get("body")
    if not isinstance(original, str) or not isinstance(actual, str):
        fail("body_evidence_missing", "Actual observed body is required")
    before, after = sha256(original), sha256(actual)
    evidence = {"expected_sha256": before, "observed_sha256": after, "rule": "exact"}
    if intended.get("body_format", "PLAIN") != observation.get("body_format"):
        fail("body_format_changed", "Observed body format differs", **evidence)
    if original == actual:
        return evidence
    eligible = observation.get("stage") == "sent" and observation.get("provider") == "qq" and observation.get("body_format") == "HTML"
    if allow_qq_style_scope and eligible:
        transformed = qq_scoped_html(original)
        if transformed is not None and transformed[0] == actual:
            return {**evidence, "rule": "qq-style-scope-v1", "normalized_expected_sha256": sha256(transformed[0]),
                    "selector_prefixes_added": transformed[1]}
    fail("html_changed" if observation.get("body_format") == "HTML" else "body_changed",
         "Observed body differs; only exact content or the explicitly enabled QQ style rule is accepted",
         qq_style_rule_eligible=eligible, **evidence)


def decode_attachment(item):
    if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in ("filename", "content_type")):
        fail("attachment_evidence_missing", "Attachment name and MIME are required")
    try:
        preflight_attachment(item.get("size"), item.get("content"))
        if not isinstance(item.get("content"), str):
            raise ValueError("missing bytes")
        data = base64.b64decode(item["content"], validate=True)
        if len(data) != item["size"] or base64.b64encode(data).decode("ascii") != item["content"]:
            raise ValueError("size or encoding")
        digests = attachment_integrity(item)
    except (ValueError, TypeError, binascii.Error):
        fail("attachment_evidence_invalid", "Attachment size, Base64 or digest metadata is invalid")
    for algorithm, expected in digests.items():
        if hashlib.new(algorithm, data, usedforsecurity=False).hexdigest() != expected:
            fail("attachment_digest_mismatch", "Observed attachment digest does not match its actual bytes")
    return {"filename": item["filename"], "mime": item["content_type"], "size": len(data), "sha256": sha256(data), "bytes": data}


def match_attachments(intended, observation, *, allow_gmail_octet_stream=False):
    expected, observed = intended.get("attachments", []), observation.get("attachments")
    if not isinstance(expected, list) or not isinstance(observed, list):
        fail("attachment_evidence_missing", "All actual attachment bytes, or explicit [], are required")
    if len(expected) != len(observed) or len(observed) > 3:
        fail("attachment_count_mismatch", "Attachment counts differ", expected_count=len(expected), observed_count=len(observed))
    left, right = [decode_attachment(x) for x in expected], [decode_attachment(x) for x in observed]
    if any(sum(x["size"] for x in side) > 3 * MAX_ATTACHMENT_BYTES for side in (left, right)):
        fail("attachment_evidence_invalid", "Total attachment size exceeds 3 MiB")
    if sorted(x["filename"] for x in left) != sorted(x["filename"] for x in right):
        fail("attachment_name_mismatch", "Attachment filenames differ")
    key = lambda x: (x["filename"], x["size"], x["sha256"], x["mime"].casefold())
    left.sort(key=key)
    right.sort(key=key)
    evidence = []
    for before in left:
        # Pair repeated names by actual content, preferring exact MIME matches.
        # Sorting MIME strings alone mispairs a valid mixed exact/fallback set.
        candidates = [x for x in right if x["filename"] == before["filename"] and x["bytes"] == before["bytes"]]
        exact = [x for x in candidates if x["mime"].casefold() == before["mime"].casefold()]
        after = (exact or candidates or [x for x in right if x["filename"] == before["filename"]])[0]
        right.remove(after)
        details = {"filename": before["filename"], "expected_mime": before["mime"], "observed_mime": after["mime"],
                   "expected_sha256": before["sha256"], "observed_sha256": after["sha256"], "size": before["size"]}
        if before["size"] != after["size"] or before["bytes"] != after["bytes"]:
            fail("attachment_content_mismatch", "Attachment sizes or complete bytes differ", **details)
        same = before["mime"].casefold() == after["mime"].casefold()
        eligible = (observation.get("stage") == "recipient" and observation.get("provider", "").casefold() == "gmail"
                    and before["mime"].casefold() in ("application/pdf", "application/xml", "text/xml")
                    and after["mime"].casefold() == "application/octet-stream")
        if not same and not (allow_gmail_octet_stream and eligible):
            fail("attachment_mime_changed", "Attachment bytes match but MIME differs", compatibility_available=eligible, **details)
        evidence.append({**details, "rule": "exact" if same else "gmail-octet-stream-v1", "complete_bytes_equal": True})
    return evidence
