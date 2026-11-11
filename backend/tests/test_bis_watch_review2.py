"""Second independent review of fix/dob-complaint-discovery (at bd4355d1):
five confirmed defects, each pinned here.

1. Switching shadow -> live: decisions shadow had recorded made live skip the
   same items forever (the ledger keys and the "already decided" check ignored
   the mode).
2. An ECB summons the watch stored first (record_type 'violation') was refreshed
   by Open Data as 'swo' (its text names a stop-work order); the order check
   compared a text-judged BEFORE with a status-judged AFTER and emailed a false
   "Stop Work Order".
3. The same for a complaint: the watch stores DOB's free text, Open Data the
   category label (86 = "Work Contrary to Stop Work Order").
4. The morning brief reads violation_number, which watch-stored summonses lacked.
5. The assistant read 80 rows and dropped 311 rows after the limit, and judged a
   complaint by any row instead of its newest.
And the report's "dob_complete" ignored a failing dataset.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from tests.test_bis_complaint_watch_flow import NOW, PROJECT, _BIS, _run, _seed  # noqa: E402


class ShadowThenLive(unittest.TestCase):
    def test_what_shadow_saw_is_still_stored_and_emailed_by_live(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        self.assertEqual(emails, [])
        _run(db, _BIS(), "live", now=NOW + timedelta(minutes=30), emails=emails)
        stored = sorted(d["raw_dob_id"] for d in db.dob_logs.docs if d["raw_dob_id"] in ("3A88489", "3A88492"))
        self.assertEqual(stored, ["3A88489", "3A88492"])
        self.assertEqual(sorted(e[0] for e in emails if e[0].startswith("3A884")), ["3A88489", "3A88492"])

    def test_summonses_shadow_saw_are_still_stored_by_live(self):
        db, emails = _seed(), []
        db.source_sync_state.docs[0]["watch"] = {"bis_ecb": {"bins_first_synced": ["3255205", "3423445"]}}
        _run(db, _BIS(), "shadow", emails=emails)
        _run(db, _BIS(), "live", now=NOW + timedelta(minutes=30), emails=emails)
        ecb = [d["raw_dob_id"] for d in db.dob_logs.docs if d.get("dataset") == "bis-ecb"]
        self.assertEqual(len(ecb), 20)


def _gc_world():
    from tests import test_whatsapp_gc_alerts_dob_dot as h
    return h, h._world(source_sync_state=[])


def _open_data_sync(h, db, records):
    sent = AsyncMock()

    async def query(nyc_bin, address="", answered=None):
        if answered is not None:
            for k in ("violation", "swo", "complaint", "permit", "ds:6bgk-3dad", "ds:eabe-havv"):
                answered[k] = True
        return [dict(r) for r in records]
    with patch.object(server, "_query_dob_apis", query), \
            patch.object(server, "_send_critical_dob_alert_throttled", sent):
        h._run(server.run_dob_sync_for_project(dict(h.DobWaitsForTheFirstSync.PROJECT)))
    return [c.kwargs.get("event") for c in sent.await_args_list]


class NoFalseOrderFromAWatchStoredRow(unittest.TestCase):
    def test_an_ecb_summons_naming_a_stop_work_order_is_not_a_new_order(self):
        h, db = _gc_world()
        db.dob_logs.rows.append({
            "_id": "bisrow", "project_id": "proj_a", "company_id": h.CO_A, "record_type": "violation",
            "raw_dob_id": "39550001Y", "ecb_violation_number": "39550001Y", "violation_number": "39550001Y",
            "current_status": "ACTIVE", "ecb_violation_status": "ACTIVE", "dataset": "bis-ecb",
            "description": "ECB/OATH summons 39550001Y (CLASS - 1), CONSTRUCTION SAFETY COMPLIANCE", "bis_first_seen_at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
            "violation_date": "20261110", "nyc_bin": "3012345", "is_deleted": False,
            "detected_at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
            "status_history": [{"status": "ACTIVE", "at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
                                "source": "bis"}]})
        od = {"_id_field": "ecb_violation_number", "_record_type": "swo", "_dataset": "6bgk-3dad",
              "ecb_violation_number": "39550001Y", "issue_date": "20261110", "ecb_violation_status": "ACTIVE",
              "violation_description": "FAILURE TO OBEY STOP WORK ORDER", "violation_type": "Construction",
              "bin": "3012345"}
        with h._Ctx(db=db):
            first = _open_data_sync(h, db, [od])
            second = _open_data_sync(h, db, [od])
        self.assertNotIn("swo", first + second)

    def test_a_complaint_whose_category_names_a_stop_work_order_is_not_a_new_order(self):
        h, db = _gc_world()
        db.dob_logs.rows.append({
            "_id": "bisc", "project_id": "proj_a", "company_id": h.CO_A, "record_type": "complaint",
            "raw_dob_id": "3A99999", "complaint_number": "3A99999", "complaint_type": "86",
            "current_status": "ACTIVE", "complaint_status": "ACTIVE", "dataset": "bis",
            "description": "WORK BEING DONE AT REAR OF LOT", "complaint_date": "2026-11-10T00:00:00.000", "bis_first_seen_at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
            "nyc_bin": "3012345", "is_deleted": False,
            "detected_at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
            "status_history": [{"status": "ACTIVE", "at": datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
                                "source": "bis"}]})
        od = {"_id_field": "complaint_number", "_record_type": "complaint", "_dataset": "eabe-havv",
              "complaint_number": "3A99999", "status": "ACTIVE", "complaint_category": "86",
              "date_entered": "11/10/2026", "bin": "3012345", "house_number": "1", "house_street": "MAIN ST"}
        with h._Ctx(db=db):
            events = _open_data_sync(h, db, [od]) + _open_data_sync(h, db, [od])
        self.assertNotIn("swo", events)


class TheBriefCanNameAWatchStoredSummons(unittest.TestCase):
    def test_bis_ecb_rows_carry_violation_number(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        rows = [d for d in db.dob_logs.docs if d.get("dataset") == "bis-ecb"]
        self.assertTrue(rows)
        self.assertTrue(all(d["violation_number"] == d["raw_dob_id"] for d in rows))


class AssistantJudgesEachComplaintByItsNewestRow(unittest.TestCase):
    def _status(self, db):
        with patch.object(server, "db", db):
            return asyncio.run(server._handle_dob_status("p546", company_id="co_blueview"))

    def test_an_open_dob_complaint_behind_many_311_rows_is_still_listed(self):
        db = _seed()
        db.projects.docs.append(dict(PROJECT))
        base = NOW - timedelta(days=3)
        db.dob_logs.docs.append({"_id": "dobc", "project_id": "p546", "company_id": "co_blueview",
                                 "record_type": "complaint", "raw_dob_id": "3A88489", "complaint_status": "ACTIVE",
                                 "complaint_date": "2026-11-10T00:00:00.000", "description": "NO ROOF PROTECTION",
                                 "detected_at": base, "is_deleted": False})
        for i in range(150):
            db.dob_logs.docs.append({"_id": f"311_{i}", "project_id": "p546", "company_id": "co_blueview",
                                     "record_type": "complaint", "raw_dob_id": f"311:{i}", "source": "311",
                                     "complaint_status": "Open", "detected_at": base + timedelta(hours=1, minutes=i),
                                     "is_deleted": False})
        out = self._status(db)
        self.assertIn("3A88489", out)

    def test_a_complaint_whose_newest_row_is_closed_is_not_listed_open(self):
        db = _seed()
        db.projects.docs.append(dict(PROJECT))
        db.dob_logs.docs += [
            {"_id": "c_old", "project_id": "p546", "company_id": "co_blueview", "record_type": "complaint",
             "raw_dob_id": "3A88492", "complaint_status": "ACTIVE", "detected_at": NOW - timedelta(days=2),
             "is_deleted": False},
            {"_id": "c_new", "project_id": "p546", "company_id": "co_blueview", "record_type": "complaint",
             "raw_dob_id": "3A88492", "complaint_status": "CLOSED", "detected_at": NOW - timedelta(days=1),
             "is_deleted": False}]
        out = self._status(db)
        self.assertNotIn("3A88492", out)


class ReportCompleteMeansNoFailingDataset(unittest.TestCase):
    def test_a_failing_violation_dataset_is_not_complete(self):
        ok = {"synced_at": NOW}
        state = {"sources": {"dob_violations": ok, "dob_complaints": ok, "dob_permits": ok},
                 "datasets": {"6bgk-3dad": {"last_error_at": NOW}}}
        self.assertFalse(server._report_sync({"track_dob_status": True}, state)["dob_complete"])
        state["datasets"] = {"6bgk-3dad": {"first_synced_at": NOW, "synced_at": NOW}}
        self.assertTrue(server._report_sync({"track_dob_status": True}, state)["dob_complete"])


if __name__ == "__main__":
    unittest.main()
