"""DOB ALERTS NEVER CALL AN OLD RECORD "NEW" (operator rulings, 2026-10-22).

THE INCIDENT. At 18:15 UTC on 2026-10-22, sixteen minutes after the first
deploy that ran #829's site-BIN fetch, the customer for 588 Thomas S Boyland got
a "New complaint" email for 3A78809 -- entered by DOB 09/02/2026, CLOSED the
same day, filed under the job site's second BIN (3430621), which the sync had
never asked about. The project's first scan was months old, so nothing treated
the second BIN's records as the backfill they were.

THE RULES (lib/dob_alert_gate):
  1. Email only for a record NEW to Levelog with a DOB date in the last 2 days.
  2. An update never emails -- except one that issues a SWO or vacate order.
  3. The first sync of a newly added BIN is silent (per project AND per BIN).
  4. A closed or resolved record never emails as new; "RESOLVE" is resolved.
  5. The email shows "Received by DOB: <date>" and the current status.

These drive the REAL run_dob_sync_for_project and the REAL throttled wrapper
(its first-scan and 24h gates included) against an in-memory db. Only the
network (the records each BIN answers with), the clock (today = 2026-10-22,
New York) and the final email sender are replaced.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

import server  # noqa: E402
from tests import test_dob_status_refresh as _base  # noqa: E402


class _Col(_base._Col):
    """The shared fake ignores `upsert`; the first-scan marks and the 24h
    throttle rows are upserts, so here they persist as they do in Mongo."""

    async def update_one(self, flt, update, upsert=False, **kw):
        res = await super().update_one(flt, update, upsert=upsert, **kw)
        if upsert and not res.matched_count:
            doc = {k: v for k, v in (flt or {}).items() if not k.startswith("$")}
            doc.update(update.get("$setOnInsert") or {})
            doc.update(update.get("$set") or {})
            await self.insert_one(doc)
        return res


class _DB(_base._DB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Col(name)
        return self._c[name]

OWN, SECOND = "3255362", "3430621"
TODAY = "2026-10-22"
JOB = "B00012345"


def _project():
    return {"_id": "p588", "company_id": "c1", "nyc_bin": OWN, "name": "588 Thomas S Boyland",
            "address": "588 Thomas S Boyland St, Brooklyn, NY"}


def _permit(bin_, suffix):
    return {"_id_field": "job_filing_number", "job_filing_number": f"{JOB}-{suffix}",
            "_collapsed_permit_id": f"{JOB}-{suffix}", "_record_type": "permit",
            "_dataset": "rbx6-tga4", "bin": bin_, "permit_status": "ISSUED",
            "work_type": "GC", "expired_date": "2030-01-01T00:00:00.000"}


def _complaint(num, entered, status="ACTIVE", disposition="", category="45", bin_=OWN):
    return {"_id_field": "complaint_number", "complaint_number": num,
            "_record_type": "complaint", "_dataset": "eabe-havv", "bin": bin_,
            "status": status, "date_entered": entered, "complaint_category": category,
            "disposition_code": disposition, "house_number": "588",
            "house_street": "THOMAS BOYLAND STREET",
            **({"disposition_date": entered} if status == "CLOSED" else {})}


def _ecb(num, status, issued="20260902", bin_=SECOND):
    return {"_id_field": "ecb_violation_number", "ecb_violation_number": num,
            "_record_type": "violation", "_dataset": "6bgk-3dad", "bin": bin_,
            "ecb_violation_status": status, "issue_date": issued, "severity": "CLASS - 2"}


def _dob_violation(isn, issued, bin_=OWN):
    return {"_id_field": "isn_dob_bis_viol", "isn_dob_bis_viol": isn,
            "_record_type": "violation", "_dataset": "3h2n-5cm9", "bin": bin_,
            "number": f"V{isn}", "violation_category": "V-DOB VIOLATION - ACTIVE",
            "issue_date": issued, "description": "Work without permit"}


#: What NYC Open Data holds under BIN 3430621 for the real job, as published:
#: the shared job's permit, the closed complaint and the two ECB violations.
SECOND_BIN = [_permit(SECOND, "S1"),
              _complaint("3A78809", "09/02/2026", status="CLOSED", disposition="A8",
                         category="8A", bin_=SECOND),
              _ecb("39558662P", "ACTIVE"), _ecb("39558663R", "RESOLVE")]


class _Sync:
    """A project that has been scanned for months (its legacy per-project
    first-scan key is set); `answers` is what each BIN returns."""

    def __init__(self, answers):
        self.db = _DB()
        self.db.system_config.docs.append({"key": "initial_scan_done:dob:p588"})
        self.answers = answers
        self.sent = AsyncMock()

    def run(self):
        async def query(bin_, address="", answered=None):
            return [dict(r) for r in self.answers.get(bin_, [])]
        with patch.object(server, "db", self.db), \
                patch.object(server, "_query_dob_apis", side_effect=query), \
                patch.object(server, "eastern_today", lambda: TODAY), \
                patch.object(server, "_send_critical_dob_alert", self.sent):
            asyncio.run(server.run_dob_sync_for_project(_project()))
        return self

    @property
    def events(self):
        return [c.kwargs.get("event") for c in self.sent.await_args_list]

    def stored(self, raw_id):
        return [d for d in self.db.dob_logs.docs if d.get("raw_dob_id") == raw_id]


class TheIncident(unittest.TestCase):

    def test_a_newly_added_bin_sends_nothing_and_stores_everything(self):
        """3A78809 / 39558662P / 39558663R through a new BIN of a project that
        is already scanned: 0 emails, all three stored."""
        s = _Sync({OWN: [_permit(OWN, "I1"), _permit(SECOND, "S1")],
                   SECOND: SECOND_BIN}).run()
        self.assertEqual(s.events, [])
        for rid in ("3A78809", "39558662P", "39558663R"):
            self.assertEqual(len(s.stored(rid)), 1, f"{rid} must be stored")
        keys = {d["key"] for d in s.db.system_config.docs}
        self.assertIn(f"initial_scan_done:dob:p588:{SECOND}", keys,
                      "the second BIN's first pass is recorded")

    def test_the_rows_say_which_bin_and_that_it_was_its_first_pass(self):
        """What the WhatsApp group alerts read: silent first pass, and the
        one summary for the newly added BIN (lib/dob_alert_gate)."""
        s = _Sync({OWN: [_permit(OWN, "I1"), _permit(SECOND, "S1")],
                   SECOND: SECOND_BIN}).run()
        for rid in ("3A78809", "39558662P", "39558663R"):
            (row,) = s.stored(rid)
            self.assertEqual(row.get("site_bin"), SECOND)
            self.assertTrue(row.get("bin_first_pass"))

    def test_the_same_records_stay_silent_on_the_next_sync_too(self):
        s = _Sync({OWN: [_permit(OWN, "I1"), _permit(SECOND, "S1")], SECOND: SECOND_BIN})
        s.run().run()
        self.assertEqual(s.events, [])

    def test_even_with_its_bin_already_scanned_none_of_them_is_new(self):
        """Rules 1 and 4 alone: closed (3A78809), resolved (39558663R) and seven
        weeks old (all three) -- each refused on its own."""
        s = _Sync({OWN: [_permit(OWN, "I1"), _permit(SECOND, "S1")], SECOND: SECOND_BIN})
        s.db.system_config.docs.append({"key": f"initial_scan_done:dob:p588:{SECOND}"})
        self.assertEqual(s.run().events, [])

    def test_resolve_without_a_d_counts_as_resolved(self):
        rec = _ecb("39558663R", "RESOLVE")
        self.assertEqual(server._classify_resolution_state(rec), "resolved")
        self.assertEqual(server._determine_severity(rec, "violation"), "Good")
        self.assertEqual(server._classify_resolution_state(_ecb("39558662P", "ACTIVE")), "open")


class NewRecordsOnAnExistingBin(unittest.TestCase):

    def test_a_record_entered_today_sends_one_email(self):
        s = _Sync({OWN: [_dob_violation("901", "20261022")]}).run()
        self.assertEqual(s.events, ["new"])
        (row,) = s.stored("901")
        self.assertNotIn("site_bin", row, "the project's own BIN")
        self.assertFalse(row.get("bin_first_pass"), "its BIN was scanned long ago")

    def test_a_record_entered_five_days_ago_first_seen_today_sends_nothing(self):
        s = _Sync({OWN: [_dob_violation("902", "20261017")]}).run()
        self.assertEqual(s.events, [])
        self.assertEqual(len(s.stored("902")), 1, "stored, just not emailed")


class Updates(unittest.TestCase):
    """A complaint first seen 5 days after DOB entered it (no email), then
    changed on the next sync."""

    def _changed(self, before, after):
        """Store `before`, then sync `after`; only the UPDATE's sends count
        (the first sighting's own rule is tested above)."""
        s = _Sync({OWN: [before]}).run()
        s.sent.reset_mock()
        # The update arrives days later: no 24h throttle row is still live to
        # hide what the update path itself decides.
        s.db.system_config.docs[:] = [d for d in s.db.system_config.docs
                                      if not str(d.get("key", "")).startswith("dob_alert_sent:")]
        s.answers = {OWN: [after]}
        return s.run()

    def test_a_status_update_sends_nothing(self):
        # ACTIVE -> CLOSED with A8 "ECB Violation Served": the status changed
        # and the record is still 'Action' (A8 rates HIGH, as on 3A78809), so
        # before this change it emailed -- titled "New complaint".
        s = self._changed(_complaint("3B00001", "10/17/2026"),
                          _complaint("3B00001", "10/17/2026", status="CLOSED", disposition="A8"))
        self.assertEqual(s.events, [])

    def test_a_disposition_update_sends_nothing(self):
        s = self._changed(_complaint("3B00005", "10/17/2026"),
                          _complaint("3B00005", "10/17/2026", disposition="A1"))
        self.assertEqual(s.events, [])

    def test_an_update_that_issues_a_stop_work_order_sends_one(self):
        # A3 "Full Stop Work Order Served".
        s = self._changed(_complaint("3B00002", "10/17/2026", disposition="A1"),
                          _complaint("3B00002", "10/17/2026", disposition="A3"))
        self.assertEqual(s.events, ["swo"])
        (row,) = s.stored("3B00002")
        self.assertEqual(row["order_issued"]["kind"], "swo",
                         "stamped for the group alert's one post")

    def test_an_update_that_issues_a_vacate_order_sends_one(self):
        # Y1 "Full Vacate Order Issued".
        s = self._changed(_complaint("3B00003", "10/17/2026", disposition="A1"),
                          _complaint("3B00003", "10/17/2026", disposition="Y1"))
        self.assertEqual(s.events, ["vacate"])

    def test_a_rescinded_order_is_not_an_order(self):
        # L2 "Stop Work Order Fully Rescinded".
        s = self._changed(_complaint("3B00004", "10/17/2026", disposition="A3"),
                          _complaint("3B00004", "10/17/2026", disposition="L2"))
        self.assertEqual(s.events, [])


class TheEmail(unittest.TestCase):

    def _render(self, event, row):
        sent = AsyncMock()
        with patch.object(server, "RESEND_API_KEY", "k"), \
                patch.object(server, "_critical_dob_alert_recipients",
                             AsyncMock(return_value=["pm@x.test"])), \
                patch("lib.notifications.send_notification", sent):
            asyncio.run(server._send_critical_dob_alert(
                {"_id": "p588", "company_id": "c1", "name": "588 Thomas"}, row, event=event))
        return sent.await_args.kwargs

    ROW = {"record_type": "complaint", "complaint_number": "3A78809", "raw_dob_id": "3A78809",
           "complaint_date": "2026-10-22T00:00:00.000", "complaint_status": "ACTIVE",
           "current_status": "ACTIVE", "ai_summary": "s", "next_action": "n"}

    def test_it_shows_when_dob_received_it_and_its_status_in_both_languages(self):
        kw = self._render("new", self.ROW)
        for body in (kw["text"], kw["html"]):
            self.assertIn("3A78809 · Received by DOB: Oct 22, 2026 · Status: ACTIVE", body)
            self.assertIn("Recibido por el DOB: 22 oct 2026 · Estado: ACTIVE", body)
        self.assertTrue(kw["subject"].startswith("New "))

    def test_an_order_is_never_titled_new(self):
        kw = self._render("swo", {**self.ROW, "disposition_code": "A3"})
        self.assertEqual(kw["subject"], "Stop Work Order on 588 Thomas")
        self.assertIn("El DOB emitió una orden de suspensión de obra", kw["text"])
        self.assertNotIn("New ", kw["subject"])

    def test_the_event_must_be_named(self):
        with self.assertRaises(TypeError):
            asyncio.run(server._send_critical_dob_alert({"name": "x"}, self.ROW))


if __name__ == "__main__":
    unittest.main()
