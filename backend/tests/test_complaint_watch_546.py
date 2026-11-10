"""546 Saratoga Ave, 2026-11-10: two DOB safety complaints LeveLog never surfaced.

  3A88489  received 11:22 ET  "NO ROOF PROTECTION, NO WINDOW PROTECTION NO DOCS"
  3A88492  received 11:25 ET  "FENCE CONTRARY, HOUSEKEEPING, FIRE EXTINGUISHERS,
                               INFO PANELSUNSAFE CONDITIONS"
  both category 8A (Construction Safety Compliance), priority D, ACTIVE, not
  yet inspected, BIN 3255205 (block 3514 lot 153; the lot's other BIN is
  3423445, "546 REAR").

Root causes measured that day (docs/audits/dob-complaint-546-2026-11-10.md):
  1. The only complaint source, Open Data eabe-havv, is a daily extract; it
     could not hold either complaint until the next afternoon. BIS had both.
  2. classify_complaint scored an open 8A with no disposition "Good", so the
     email path would not have sent it even once ingested.
  3. The assistant's DOB answer read violations only.

The pages under tests/fixtures/bis_complaints/ are the real BIS pages fetched
2026-11-10 19:48 UTC. Every case the operator named is here: the exact two
complaints, late-arriving, duplicate, historical, closed, wrong-property and
first-sync.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib import bis_complaints as bis  # noqa: E402
from lib import complaint_watch as cw  # noqa: E402

FIX = _HERE / "fixtures" / "bis_complaints"
NOW = datetime(2026, 11, 10, 19, 48, tzinfo=timezone.utc)        # first BIS check
PROJECT = {"_id": "p546", "company_id": "co_blueview", "name": "546 Saratoga Ave", "nyc_bin": "3255205"}
BINS_546 = cw.bins_for_project(PROJECT, lot_bins=["3423445"])


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="latin-1")


def bis_record(cn: str) -> dict:
    """List row + detail page, as the watcher merges them."""
    row = next(r for r in bis.parse_complaint_list(page("list_3255205.html")).rows
               if r["complaint_number"] == cn)
    rec = dict(row, bin="3255205")
    det = FIX / f"detail_{cn}.html"
    if det.exists():
        d = bis.parse_complaint_detail(det.read_text(encoding="latin-1"))
        rec.update({k: v for k, v in d.items() if v not in (None, [], "") and k != "found"})
    return rec


class TheTwoRealComplaints(unittest.TestCase):
    def test_bis_lists_both_complaints_open_on_the_546_bin(self):
        p = bis.parse_complaint_list(page("list_3255205.html"))
        self.assertEqual((p.bin, p.block, p.lot, p.total, len(p.rows)), ("3255205", "3514", "153", 16, 16))
        got = {r["complaint_number"]: (r["category"], r["status"], r["date_entered"], r["inspection_date"])
               for r in p.rows[:2]}
        self.assertEqual(got, {"3A88492": ("8A", "ACTIVE", "2026-11-10", None),
                               "3A88489": ("8A", "ACTIVE", "2026-11-10", None)})

    def test_detail_pages_give_the_minute_dob_received_them(self):
        a, b = bis_record("3A88489"), bis_record("3A88492")
        self.assertEqual(a["received_at"], "2026-11-10T11:22:00-05:00")
        self.assertEqual(b["received_at"], "2026-11-10T11:25:00-05:00")
        self.assertEqual(a["description"], "NO ROOF PROTECTION, NO WINDOW PROTECTION NO DOCS")
        self.assertEqual((a["priority"], a["assigned_to"]), ("D", "CONSTRUCTION SAFETY COMPLIANCE"))
        self.assertIsNone(a.get("last_inspection_date"))

    def test_both_alert_at_once_as_safety_complaints(self):
        for cn in ("3A88489", "3A88492"):
            with self.subTest(cn=cn):
                d = cw.alert_decision(bis_record(cn), project_bins=BINS_546, first_sync=False,
                                      already_alerted=False, now=NOW)
                self.assertTrue(d["alert"], d)
                self.assertEqual((d["priority"], d["late"], d["event"]), ("high", False, "new_complaint"))
                self.assertIn("8A", d["reason"])

    def test_a_complaint_is_not_a_violation_in_the_message(self):
        rec = bis_record("3A88489")
        d = cw.alert_decision(rec, project_bins=BINS_546, first_sync=False, already_alerted=False, now=NOW)
        en = cw.render_alert(rec, d, project_name="546 Saratoga Ave")
        es = cw.render_alert(rec, d, project_name="546 Saratoga Ave", lang="es")
        self.assertIn("3A88489", en)
        self.assertIn("Nov 10, 11:22 AM", en)
        self.assertIn("A complaint is not a violation", en)
        self.assertIn("Una queja no es una violación", es)
        self.assertIn("el 10 de nov, 11:22 a. m.", es)
        self.assertIn("complaintno=3A88489", en)


class FirstSync(unittest.TestCase):
    def test_todays_open_complaints_alert_even_on_the_first_sync(self):
        for cn in ("3A88489", "3A88492"):
            d = cw.alert_decision(bis_record(cn), project_bins=BINS_546, first_sync=True,
                                  already_alerted=False, now=NOW)
            self.assertTrue(d["alert"], d)

    def test_history_is_a_silent_baseline_on_the_first_sync(self):
        rows = bis.parse_complaint_list(page("list_3255205.html")).rows
        alerted = [r["complaint_number"] for r in rows
                   if cw.alert_decision(dict(r, bin="3255205"), project_bins=BINS_546, first_sync=True,
                                        already_alerted=False, now=NOW)["alert"]]
        self.assertEqual(sorted(alerted), ["3A88489", "3A88492"])


class Historical(unittest.TestCase):
    def test_a_2025_resolved_complaint_never_alerts(self):
        r = next(x for x in bis.parse_complaint_list(page("list_3255205.html")).rows
                 if x["complaint_number"] == "3A35190")
        d = cw.alert_decision(dict(r, bin="3255205"), project_bins=BINS_546, first_sync=False,
                              already_alerted=False, now=NOW)
        self.assertFalse(d["alert"])
        self.assertEqual(d["reason"], "closed on arrival with no enforcement disposition")


class Closed(unittest.TestCase):
    def test_closed_with_no_enforcement_does_not_alert(self):
        rec = dict(bis_record("3A88489"), status="RESOLVED", disposition_code="I2")
        d = cw.alert_decision(rec, project_bins=BINS_546, first_sync=False, already_alerted=False, now=NOW)
        self.assertFalse(d["alert"])

    def test_closed_into_a_partial_stop_work_order_alerts_as_the_order(self):
        rec = dict(bis_record("3A70077"), received_date="2026-11-10", received_at=None)
        d = cw.alert_decision(rec, project_bins=BINS_546, first_sync=False, already_alerted=False, now=NOW)
        self.assertEqual((d["alert"], d["event"], d["priority"]), (True, "stop_work_order", "critical"))


class Duplicate(unittest.TestCase):
    def test_one_complaint_number_across_sources(self):
        self.assertEqual(bis.normalize_complaint_number(" 3a88489 "), "3A88489")
        open_data_row = {"complaint_number": "3A88489", "bin": "3255205", "status": "ACTIVE",
                         "complaint_category": "8A", "date_entered": "11/10/2026"}
        self.assertEqual(bis.normalize_complaint_number(open_data_row["complaint_number"]),
                         bis_record("3A88489")["complaint_number"])

    def test_already_alerted_never_alerts_twice(self):
        d = cw.alert_decision(bis_record("3A88489"), project_bins=BINS_546, first_sync=False,
                              already_alerted=True, now=NOW)
        self.assertFalse(d["alert"])
        self.assertTrue(d["reason"].startswith("duplicate"))


class LateArriving(unittest.TestCase):
    def test_seen_three_days_late_still_alerts_marked_late(self):
        later = NOW + timedelta(days=3)
        d = cw.alert_decision(bis_record("3A88492"), project_bins=BINS_546, first_sync=False,
                              already_alerted=False, now=later, first_seen_at=later)
        self.assertTrue(d["alert"])
        self.assertTrue(d["late"])
        self.assertIn("Arrived late", cw.render_alert(bis_record("3A88492"), d, project_name="546"))


class WrongProperty(unittest.TestCase):
    def test_a_complaint_on_another_bin_never_attaches(self):
        rec = dict(bis_record("3A88489"), bin="3255362")       # 588 Boyland's old BIN
        d = cw.alert_decision(rec, project_bins=BINS_546, first_sync=False, already_alerted=False, now=NOW)
        self.assertFalse(d["alert"])
        self.assertTrue(d["reason"].startswith("wrong property"))

    def test_the_lots_rear_bin_is_the_same_property(self):
        prof = bis.parse_property_profile(page("property_3255205.html"))
        self.assertEqual(prof["additional_bins"], ["3423445"])
        self.assertEqual((prof["partial_stop_work_order"], prof["stop_work_order"]), (True, False))
        rear = bis.parse_complaint_list(page("list_3423445.html"))
        self.assertEqual((rear.bin, rear.premises), ("3423445", "546 REAR SARATOGA AVENUE BROOKLYN"))
        self.assertIn("3423445", cw.bins_for_project(PROJECT, lot_bins=prof["additional_bins"]))


class Lifecycle(unittest.TestCase):
    def test_complaint_to_order_to_summons_to_hearing_are_distinct_events(self):
        ecb = [{"ecb_violation_number": "39556258Y", "ecb_violation_status": "ACTIVE",
                "hearing_status": "PENDING", "hearing_date": "20270312"}]
        ev = cw.lifecycle_events(bis_record("3A70077"), ecb=ecb)
        self.assertEqual([e["event"] for e in ev],
                         ["received", "inspected", "disposition", "order_issued", "violation_issued",
                          "hearing_scheduled", "closed"])
        self.assertEqual(ev[3]["kind"], "partial_stop_work")
        self.assertEqual(ev[4]["ecb_number"], "39556258Y")
        self.assertEqual(ev[1]["badge"], "3207")

    def test_the_two_new_complaints_have_only_been_received(self):
        self.assertEqual([e["event"] for e in cw.lifecycle_events(bis_record("3A88489"))], ["received"])


class OpenComplaintSeverity(unittest.TestCase):
    """dob_complaint_codes.classify_complaint fell back to the STATUS ('ACTIVE')
    as a disposition code when there was none, scored it MEDIUM, and an 8A
    complaint awaiting inspection came out severity 'Good' -- never emailed."""

    def test_an_open_8a_awaiting_inspection_is_action(self):
        from dob_complaint_codes import classify_complaint
        c = classify_complaint({"complaint_category": "8A", "status": "ACTIVE"})
        self.assertEqual(c["severity"], "Action")
        self.assertNotIn("DOB code: ACTIVE", c["disposition_label"])

    def test_low_risk_categories_and_closed_complaints_are_unchanged(self):
        from dob_complaint_codes import classify_complaint
        self.assertEqual(classify_complaint({"complaint_category": "4S", "status": "ACTIVE"})["severity"], "Good")
        self.assertEqual(classify_complaint({"complaint_category": "8A", "status": "CLOSED",
                                             "disposition_code": "I2"})["severity"], "Good")


class Freshness(unittest.TestCase):
    def test_nothing_checked_live_means_no_claim_of_none(self):
        f = cw.freshness({"sources": {"dob_complaints": {"synced_at": NOW}}}, now=NOW)
        self.assertFalse(f["can_say_no_new_complaints"])
        self.assertIn("once a day", f["note"])

    def test_a_recent_bis_check_can_say_none(self):
        f = cw.freshness({"watch": {"bis_complaints": {"last_success_at": NOW - timedelta(minutes=5),
                                                      "mode": "live"}}}, now=NOW)
        self.assertTrue(f["can_say_no_new_complaints"])

    def test_a_shadow_check_never_claims_none(self):
        """Shadow reads BIS but stores nothing: an empty list beside a fresh
        shadow check would be a false 'none'."""
        f = cw.freshness({"watch": {"bis_complaints": {"last_success_at": NOW - timedelta(minutes=5),
                                                      "mode": "shadow"}}}, now=NOW)
        self.assertFalse(f["can_say_no_new_complaints"])
        self.assertIn("trial mode", f["note"])

    def test_a_failed_bis_check_is_reported_not_hidden(self):
        f = cw.freshness({"watch": {"bis_complaints": {"last_attempt_at": NOW, "last_error": "BIN 3255205: HTTP 503",
                                                      "last_success_at": NOW - timedelta(hours=3)}}}, now=NOW)
        row = f["sources"][0]
        self.assertEqual((row["status"], row["last_error"]), ("stale", "BIN 3255205: HTTP 503"))
        self.assertFalse(f["can_say_no_new_complaints"])


class PagingAndNotFound(unittest.TestCase):
    def test_a_busy_bin_reports_its_next_page(self):
        p = bis.parse_complaint_list(page("list_3000002_page1.html"))
        self.assertEqual((p.total, p.page, p.pages, p.next_allcount, len(p.rows)), (84, 1, 5, "0019", 18))

    def test_not_found_is_not_a_record(self):
        self.assertEqual(bis.parse_complaint_detail(
            "<td>Overview for Complaint #: = </td><b>*** COMPLAINT NUMBER NOT FOUND ****</b>"), {"found": False})


class AssistantNamesComplaints(unittest.TestCase):
    def test_dob_status_lists_open_complaints_and_says_how_fresh(self):
        import server
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        asyncio.run(db.projects.insert_one(dict(PROJECT)))
        for cn in ("3A88489", "3A88492"):
            r = bis_record(cn)
            asyncio.run(db.dob_logs.insert_one({
                "project_id": "p546", "company_id": "co_blueview", "record_type": "complaint",
                "raw_dob_id": cn, "complaint_status": "ACTIVE", "complaint_date": "2026-11-10T00:00:00.000",
                "description": r["description"], "detected_at": NOW, "is_deleted": False}))
        with patch.object(server, "db", db):
            out = asyncio.run(server._handle_dob_status("p546", company_id="co_blueview"))
        self.assertIn("Open DOB complaints (2)", out)
        self.assertIn("3A88489", out)
        self.assertIn("NO ROOF PROTECTION", out)
        self.assertIn("once a day", out)


if __name__ == "__main__":
    unittest.main()
