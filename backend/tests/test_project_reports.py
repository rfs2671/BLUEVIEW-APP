"""Project reports -- the delivery (what the report says is
tests/test_progress_report.py).

  * No phone numbers; record numbers print as filed.
  * Scheduled: bi-weekly Monday 8 AM (even ISO weeks) / monthly 1st 8 AM,
    New York; sent once per recipient; held over Shabbos; retried on the
    shared schedule when WhatsApp fails.
  * DM phrasings: "send me a report for 588 for the last 2 weeks", "monthly
    report 588", "report all jobs September".
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import project_report as R, wa_dm  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _Harness, _optin  # noqa: E402
from tests.test_whatsapp_morning_brief import _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx, _Wire, _run  # noqa: E402

NY = R.NY
NOW = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)      # Wed 4 PM New York


class NoPhones(unittest.TestCase):

    def test_phones_go_record_numbers_stay(self):
        for phone in ("718-555-0100", "(718) 555 0100", "+1 718 555 0100", "7185550100",
                      "+44 20 7946 0958"):
            self.assertEqual(R.no_phone(f"Call {phone} now"), "Call [number] now", phone)
        for record in ("35123456", "1234567", "V*071519LL1234", "B00123456-I1", "321456789"):
            self.assertEqual(R.no_phone(f"Record {record}"), f"Record {record}", record)


class WhenScheduled(unittest.TestCase):

    def ny(self, y, mo, d, h, mi=5):
        return datetime(y, mo, d, h, mi, tzinfo=NY).astimezone(timezone.utc)

    def test_biweekly_monday_8am_every_second_week(self):
        self.assertEqual(R.due_periods("biweekly", self.ny(2026, 10, 12, 8))[0][:2],
                         (date(2026, 9, 28), date(2026, 10, 11)))
        self.assertEqual(R.due_periods("biweekly", self.ny(2026, 10, 19, 8)), [])    # the other Monday
        self.assertEqual(R.due_periods("biweekly", self.ny(2026, 10, 12, 7)), [])    # before 8 AM
        self.assertEqual(R.due_periods("biweekly", self.ny(2026, 10, 13, 8))[0][2],
                         date(2026, 10, 12))                                          # the catch-up window

    def test_monthly_first_8am(self):
        self.assertEqual(R.due_periods("monthly", self.ny(2026, 11, 1, 8))[0][:2],
                         (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(R.due_periods("monthly", self.ny(2026, 11, 8, 8)), [])
        self.assertEqual(R.due_periods("off", self.ny(2026, 11, 1, 8)), [])


class _Reports:

    def setUp(self):
        self.media = []
        self.pdfs = 0

    def patches(self):
        async def media(chat, doc, caption=""):
            self.media.append((chat, doc["_id"], caption))
            return True

        def pdf(html_text):
            self.pdfs += 1
            return b"%PDF-fake"
        return [patch.object(server, "_send_report_media", media),
                patch.object(server, "_report_pdf", pdf),
                patch.object(server, "_upload_to_r2", lambda data, key, ct="": f"https://r2/{key}")]


class TheSchedule(_Reports, unittest.TestCase):

    def world(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        db[server.PROJECT_REPORT_SETTINGS].rows.append(
            {"_id": THOMAS, "company_id": CO_A, "schedule": "biweekly", "pm_ids": []})
        return db

    def tick(self, c, at, *ps):
        with patch.object(server, "_send_report_media", self.patches()[0].new), \
                patch.object(server, "_report_pdf", self.patches()[1].new), \
                patch.object(server, "_upload_to_r2", self.patches()[2].new):
            return _run(server._report_schedule_tick(at))

    def test_sent_once_to_the_admin(self):
        db = self.world()
        at = datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)
        with _Ctx(db) as c:
            r1 = self.tick(c, at)
            r2 = self.tick(c, at + timedelta(minutes=15))
        self.assertEqual((r1["built"], r1["sent"]), (1, 1))
        self.assertEqual(r2["sent"], 0)
        self.assertEqual(self.pdfs, 1)                         # built once, reused
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 1)
        self.assertIn("Sep 28 – Oct 11", msgs[0])
        self.assertTrue(msgs[0].endswith("Full report (PDF) attached."), msgs[0])
        self.assertNotIn("https://", msgs[0])                  # the PDF goes, not its link
        self.assertEqual(len(self.media), 1)

    def test_when_the_pdf_cannot_go_the_link_does(self):
        db = self.world()
        at = datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)

        async def no_media(chat, doc, caption=""):
            return False
        with _Ctx(db) as c, patch.object(server, "_send_report_media", no_media), \
                patch.object(server, "_report_pdf", self.patches()[1].new), \
                patch.object(server, "_upload_to_r2", self.patches()[2].new):
            _run(server._report_schedule_tick(at))
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 2, msgs)
        self.assertTrue(msgs[1].startswith("The PDF didn't attach. Full report (PDF): https://"), msgs[1])

    def test_over_shabbos_it_waits(self):
        db = self.world()
        db[server.PROJECT_REPORT_SETTINGS].rows[0]["schedule"] = "monthly"
        sat = datetime(2026, 8, 1, 8, 5, tzinfo=NY).astimezone(timezone.utc)   # Saturday the 1st
        with _Ctx(db) as c:
            r = self.tick(c, sat)
        self.assertEqual((r["queued"], r["sent"]), (1, 0))
        self.assertEqual([p for p in c.wire.calls if "message" in p], [])
        self.assertEqual(db[server.WA_QUIET_QUEUE].rows[0]["send"]["via"], "report_dm")
        # After Shabbos the queue delivers it: the hold is lifted first, so the
        # DM's own claim is not refused as a duplicate (Codex on #795).
        sun = datetime(2026, 8, 2, 9, 0, tzinfo=NY).astimezone(timezone.utc)
        with _Ctx(db) as c, patch.object(server, "_send_report_media", self.patches()[0].new):
            _run(server._quiet_queue_tick(sun))
        msgs = [p["message"] for p in c.wire.calls if "message" in p]
        self.assertEqual(len(msgs), 1, c.wire.calls)
        self.assertIn("Jul 1–31", msgs[0])
        self.assertEqual(len(self.media), 1)
        led = db[server.WA_LEDGER].rows
        self.assertEqual([r["status"] for r in led], ["sent"])

    def test_a_whatsapp_failure_is_retried(self):
        db = self.world()
        at = datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)
        with _Ctx(db, wire=_Wire([(500, {}, None)] * wa_dm.DM_SEND_ATTEMPTS)):
            r = self.tick(None, at)
        self.assertEqual(r["retrying"], 1)
        row = db[server.WA_QUIET_QUEUE].rows[0]
        self.assertEqual((row["retry"], row["send"]["via"]), (True, "report_dm"))


class WhatIsRead(_Reports, unittest.TestCase):

    def test_the_report_reads_no_chat_commitments_or_punch(self):
        # The GC's internal operation -- group chat, model-extracted
        # commitments, punch assignments -- is not report material (and chat
        # no longer goes to a language model). Proven by making every one of
        # those collections explode: the rows still come back.
        db = _world()
        project = next(p for p in db.projects.rows if p["_id"] == THOMAS)

        def boom(*a, **k):
            raise AssertionError("an internal collection was read")
        with _Ctx(db), patch.object(db.whatsapp_messages, "find", boom), \
                patch.object(db.attention_items, "find", boom), patch.object(db.punch_items, "find", boom):
            rows = _run(server._report_rows(project, CO_A, date(2026, 10, 1), date(2026, 10, 14), NOW))
        for key in ("chat", "commitments", "punch_items"):
            self.assertNotIn(key, rows)

    def test_a_failed_read_makes_no_report(self):
        # Codex on #795: an unreadable source is never "no records".
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)

        def boom(*a, **k):
            raise RuntimeError("mongo down")
        project = next(p for p in db.projects.rows if p["_id"] == THOMAS)
        with _Ctx(db), patch.object(db.checkins, "find", boom):
            with self.assertRaises(server.ReportSourceUnavailable):
                _run(server.build_project_report(CO_A, [project], date(2026, 10, 1),
                                                 date(2026, 10, 14), now=NOW))
            r = None
            with patch.object(server, "_report_pdf", self.patches()[1].new):
                db[server.PROJECT_REPORT_SETTINGS].rows.append(
                    {"_id": THOMAS, "company_id": CO_A, "schedule": "biweekly", "pm_ids": []})
                r = _run(server._report_schedule_tick(
                    datetime(2026, 10, 12, 8, 5, tzinfo=NY).astimezone(timezone.utc)))
        self.assertEqual(db[server.PROJECT_REPORTS].rows, [])
        self.assertEqual((r["unavailable"], r["sent"]), (1, 0))
        self.assertEqual(self.pdfs, 0)


class ReportPhotoBytes(unittest.TestCase):

    def test_an_inline_only_photo_is_read(self):
        # Codex on #803: a filed photo with only its inline copy is used.
        import base64
        raw = b"\xff\xd8jpeg-bytes"
        c = {"key": "inline:l1:0:0", "photo": {"base64": "data:image/jpeg;base64,"
                                                         + base64.b64encode(raw).decode()}}
        with patch.object(server, "_r2_fetch", lambda k: (None, "no r2")):
            self.assertEqual(server._report_photo_bytes(c), raw)

    def test_r2_first_when_it_has_one(self):
        c = {"key": "k", "photo": {"enhanced_r2_key": "k", "base64": "QUJD"}}
        with patch.object(server, "_r2_fetch", lambda k: (b"from-r2", None)):
            self.assertEqual(server._report_photo_bytes(c), b"from-r2")

    def test_the_longest_period_reads_every_filed_log(self):
        # Codex on #803: 401 days may be asked for; the read is not capped
        # under it.
        import inspect
        src = inspect.getsource(server._report_rows)
        self.assertIn("2 * length + 200", src)


class WhoSetsTheSchedule(unittest.TestCase):

    def test_admins_and_full_access_pms(self):
        # Codex on #795: a PM with "Same as admin" sets it, as the screen shows.
        allowed = server.is_company_admin
        self.assertTrue(allowed({"role": "admin"}))
        self.assertTrue(allowed({"role": "pm", "pm_access": "full"}))
        self.assertFalse(allowed({"role": "pm"}))
        import inspect
        src = inspect.getsource(server.put_project_report_settings)
        self.assertIn("is_company_admin(current_user)", src)


class InTheDm(_Reports, _Harness, unittest.TestCase):

    def setUp(self):
        _Reports.setUp(self)
        _Harness.setUp(self)

    def ask(self, text):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c:
                reply = self._send(c, f"{ADMIN_PHONE}@c.us", text)
        finally:
            for p in reversed(ps):
                p.stop()
        return reply, db

    def test_unreadable_records_say_so(self):
        db = _world()
        _optin(db, "u_admin", ADMIN_PHONE)

        def boom(*a, **k):
            raise RuntimeError("mongo down")
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            with _Ctx(db) as c, patch.object(db.checkins, "find", boom):
                reply = self._send(c, f"{ADMIN_PHONE}@c.us", "report for 588")
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(reply, server.REPORT_UNAVAILABLE)
        self.assertEqual(db[server.PROJECT_REPORTS].rows, [])

    def test_send_me_a_report_for_588_for_the_last_2_weeks(self):
        reply, db = self.ask("send me a report for 588 for the last 2 weeks")
        # The PDF goes, with the short message on it; no text, no link.
        self.assertIsNone(reply)
        self.assertEqual(len(self.media), 1)
        caption = self.media[0][2]
        self.assertTrue(caption.startswith("588 Thomas S Boyland · "), caption)
        self.assertEqual(caption.splitlines()[1][:8], "- Site: ")
        self.assertTrue(caption.endswith("Full report (PDF) attached."), caption)
        self.assertIsNone(re.search(r"man-?days|%|https?://", caption), caption)
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(doc["project_ids"], [THOMAS])
        self.assertEqual((date.fromisoformat(doc["end"]) - date.fromisoformat(doc["start"])).days, 13)
        self.assertEqual(self.agent_calls, [])

    def test_monthly_report_588(self):
        reply, db = self.ask("monthly report 588")
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(date.fromisoformat(doc["start"]).day, 1)

    def test_report_all_jobs_september(self):
        reply, db = self.ask("report all jobs September")
        doc = db[server.PROJECT_REPORTS].rows[0]
        self.assertEqual(sorted(doc["project_ids"]), sorted([THOMAS, WALWORTH]))
        self.assertEqual(doc["start"][5:], "09-01")
        self.assertTrue(doc["title"].startswith("Progress report — 2 jobs —"))

    def test_an_unknown_job_with_a_date_range_is_not_every_job(self):
        # THE BUG: "report for 99 Nowhere St for the last 2 weeks" fell through
        # to a report on ALL jobs because a date range was in the sentence.
        for text in ("send me a report for 99 Nowhere St for the last 2 weeks",
                     "report for the Atlantic Ave job since Oct 1"):
            reply, db = self.ask(text)
            self.assertIn("I don't see that job", reply or "", text)
            self.assertEqual(db[server.PROJECT_REPORTS].rows, [], text)
            self.assertEqual(self.media, [], text)

    def test_a_date_range_alone_still_means_every_job(self):
        reply, db = self.ask("send me a report for the last 2 weeks")
        self.assertEqual(sorted(db[server.PROJECT_REPORTS].rows[0]["project_ids"]), sorted([THOMAS, WALWORTH]))

    def test_names_a_job(self):
        for text, named in (("report for 588 last 30 days", True), ("monthly report", False),
                            ("report for September", False), ("report 12/3 to 12/10", False),
                            ("give me the weekly report from Oct 1 to Oct 9", False),
                            ("report for Atlantic Ave last week", True)):
            self.assertEqual(R.names_a_job(text), named, text)

    def test_not_a_report_request(self):
        for t in ("daily report for 588", "what did the report say"):
            self.assertFalse(R.is_request(t), t)


if __name__ == "__main__":
    unittest.main()
