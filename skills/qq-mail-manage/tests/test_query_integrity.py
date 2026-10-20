import base64
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qq_mail import collect_pages, latest_by_received, query_window
from qq_mail_write import validate_arguments

AFTER = "2026-10-13T15:00:00+08:00"
BEFORE = "2026-10-20T15:00:00+08:00"


def invoice(mid, received):
    return {"message_id": mid, "subject": "电子发票", "received_at": received}


class Pages:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    async def call(self, tool, arguments):
        self.calls.append((tool, dict(arguments)))
        return self.pages.pop(0)


class QueryIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_pages_preserve_window_folder_and_select_latest_receipt(self):
        first = invoice("msg_old", "2026-10-15T08:00:00+08:00")
        latest = invoice("msg_new", "2026-10-19T21:30:00+08:00")
        mail = Pages([{"data": [first], "pagination": {"has_more": True, "next_cursor": "next"}},
                      {"data": [latest], "pagination": {"has_more": False}}])
        args = {"alias_id": "fixture", "dir": "inbox", "q": "发票", "search_in": "SEARCH_IN_SUBJECT", "after": AFTER, "before": BEFORE, "limit": 5}
        result = await collect_pages(mail, "SearchMessages", args)
        self.assertTrue(result["complete"])
        self.assertEqual(result["pages"], 2)
        self.assertEqual(latest_by_received(result["data"], AFTER, BEFORE, "发票")["message_id"], "msg_new")
        self.assertEqual(mail.calls[0][1], args)
        self.assertEqual(mail.calls[1][1], {**args, "cursor": "next"})

    async def test_pagination_cycle_stops_instead_of_forwarding_partial_results(self):
        mail = Pages([{"data": [], "pagination": {"has_more": True, "next_cursor": "same"}}] * 2)
        with self.assertRaisesRegex(RuntimeError, "repeated pagination"):
            await collect_pages(mail, "SearchMessages", {"dir": "inbox", "after": AFTER, "before": BEFORE})

    async def test_page_cap_and_intermediate_start_are_not_full_results(self):
        mail = Pages([{"data": [], "pagination": {"has_more": True, "next_cursor": "next"}}])
        args = {"dir": "inbox", "after": AFTER, "before": BEFORE}
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            await collect_pages(mail, "ListMessages", args, max_pages=1)
        with self.assertRaises(ValueError):
            await collect_pages(mail, "ListMessages", {**args, "cursor": "middle"})

    def test_fixed_offset_window_is_exactly_seven_days(self):
        start, end = query_window(before=BEFORE)
        self.assertEqual(start, AFTER)
        self.assertEqual(end, BEFORE)

    def test_naive_reversed_or_empty_interval_is_rejected(self):
        for after, before in (("2026-10-13T15:00:00", BEFORE), (BEFORE, AFTER), (BEFORE, BEFORE)):
            with self.assertRaises(ValueError): query_window(after, before)

    def test_date_boundaries_are_half_open_and_subject_is_rechecked(self):
        rows = [invoice("at_start", AFTER), invoice("at_end", BEFORE),
                {**invoice("not_invoice", "2026-10-19T10:00:00+08:00"), "subject": "普通通知"}]
        self.assertEqual(latest_by_received(rows, AFTER, BEFORE, "发票")["message_id"], "at_start")

    def test_receipt_time_must_not_be_guessed_and_ties_are_reported(self):
        with self.assertRaisesRegex(RuntimeError, "Actual receipt time"):
            latest_by_received([{"message_id": "msg", "subject": "发票", "created_at": AFTER}], AFTER, BEFORE, "发票")
        with self.assertRaisesRegex(RuntimeError, "tied"):
            latest_by_received([invoice("one", AFTER), invoice("two", AFTER)], AFTER, BEFORE, "发票")

    def attachment(self, data=b"synthetic PDF attachment"):
        return {"filename": "fixture.pdf", "content_type": "application/pdf", "content": base64.b64encode(data).decode(),
                "size": len(data), "sha1": hashlib.sha1(data).hexdigest()}

    def test_attachment_integrity_is_checked_before_submission(self):
        args = {"to": [{"email": "recipient@example.com"}], "subject": "fixture", "body": "fixture"}
        good = self.attachment()
        validate_arguments("SendMessage", {**args, "attachments": [good]})
        for bad in ({**good, "sha1": "0" * 40}, {**good, "size": good["size"] + 1}, {**good, "content": "not-base64!"}):
            with self.assertRaises(ValueError): validate_arguments("SendMessage", {**args, "attachments": [bad]})

    def test_attachment_count_size_and_combined_bounds(self):
        args = {"to": [{"email": "recipient@example.com"}], "subject": "fixture", "body": "fixture"}
        with self.assertRaises(ValueError):
            validate_arguments("SendMessage", {**args, "attachments": [self.attachment()] * 4})
        with self.assertRaises(ValueError):
            validate_arguments("SendMessage", {**args, "attachments": [self.attachment(b"x" * (1048576 + 1))]})
        validate_arguments("SendMessage", {**args, "attachments": [self.attachment(b"x" * 1048576)] * 3})


if __name__ == "__main__":
    unittest.main()
