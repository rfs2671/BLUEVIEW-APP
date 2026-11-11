"""Third pass on fix/dob-complaint-discovery (at 4b7bbe9f): complaints, ECB/OATH
summonses and actual stop-work orders stay DISTINCT, and switching the watch
from shadow to live never replays history.

Measured in production 2026-11-10 (read-only): the only two dob_logs rows typed
'swo' are ECB summonses, 39550534Y and 39543624M, retyped by the Open Data scan
because their text cites a stop-work order. The BIS watch stores the same
summons as a violation, so its type depended on which path saw it first.

The shadow -> live replay is pinned on a real database in
tests/test_dob_status_real_mongo.py and here, over the fake one, so CI runs it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from lib import complaint_watch, dob_alert_gate, report_regulatory, wa_alerts  # noqa: E402
from tests.test_bis_complaint_watch_flow import NOW, _BIS, _run, _seed  # noqa: E402

# 39543624M, as the ECB dataset (6bgk-3dad) returns it: DOB's own words.
SUMMONS_CITING_SWO = {
    "ecb_violation_number": "39543624M", "isn_dob_bis_extract": "1", "bin": "3255205",
    "issue_date": "20260601", "ecb_violation_status": "ACTIVE", "violation_type": "Construction",
    "severity": "CLASS - 1", "infraction_code1": "B21",
    "violation_description": ("AT TIME OF INSPECTION, OBSERVED BUILDING AT EXPOSURE 3 COMPLETED TO 7TH "
                              "FLOOR; PRIOR INSPECTION PHOTOS SHOW 5TH FLOOR. SWO PROHIBITED ALL WORK AT "
                              "EXPOSURE 3; HEIGHT INCREASE CONFIRMS CONTINUED WORK CONTRARY TO SWO"),
}
# A stop-work order as the stop-work dataset (3usq-5cid) returns one.
STOP_WORK_ORDER = {"stop_work_order_number": "SWO-2020-1", "bin": "3255205", "issue_date": "2020-05-01",
                   "street": "SARATOGA AVENUE", "house_number": "546", "description": "FULL STOP WORK ORDER"}


class _Resp:
    def __init__(self, payload):
        self.status_code, self._p = 200, payload

    def json(self):
        return self._p


class _OpenData:
    async def get(self, url, params=None, **kw):
        if "6bgk-3dad" in url and (params or {}).get("bin"):
            return _Resp([dict(SUMMONS_CITING_SWO)])
        if "3usq-5cid" in url and (params or {}).get("bin"):
            return _Resp([dict(STOP_WORK_ORDER)])
        return _Resp([])


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def _query():
    with patch("server.ServerHttpClient", lambda *a, **k: _Ctx(_OpenData())):
        return asyncio.run(server._query_dob_apis("3255205", "546 SARATOGA AVENUE, Brooklyn, NY", {}))


class ASummonsIsNeverAStopWorkOrder(unittest.TestCase):
    def test_ingestion_keeps_a_summons_a_violation_and_an_order_an_order(self):
        recs = _query()
        by = {r.get("ecb_violation_number") or r.get("stop_work_order_number"): r for r in recs}
        self.assertEqual(by["39543624M"]["_record_type"], "violation")
        self.assertEqual(by["SWO-2020-1"]["_record_type"], "swo")

    def test_classification(self):
        self.assertEqual(server._classify_violation_subtype(dict(SUMMONS_CITING_SWO)), "ECB")
        self.assertEqual(server._classify_violation_subtype(dict(STOP_WORK_ORDER, _record_type="swo")), "SWO_FULL")

    def test_the_stored_summons_is_not_an_order_anywhere_it_is_read(self):
        stored = {"record_type": "violation", "dataset": "6bgk-3dad", "raw_dob_id": "39543624M",
                  "violation_number": "39543624M", "current_status": "ACTIVE",
                  "description": SUMMONS_CITING_SWO["violation_description"],
                  "violation_subtype": server._classify_violation_subtype(dict(SUMMONS_CITING_SWO))}
        self.assertIsNone(dob_alert_gate.order_in_force(stored))
        self.assertFalse(wa_alerts.is_critical({"kind": "violation", "rec": stored}))
        self.assertNotEqual(report_regulatory._kind_label(stored), "Stop Work Order")
        # The same summons stored by the BIS watch first.
        watch = {"record_type": "violation", "dataset": "bis-ecb", "raw_dob_id": "39543624M",
                 "ecb_violation_number": "39543624M", "current_status": "ACTIVE",
                 "description": "ECB/OATH summons 39543624M (CLASS - 1), CONSTRUCTION SAFETY COMPLIANCE"}
        self.assertIsNone(dob_alert_gate.order_in_force(watch))

    def test_actual_orders_are_still_orders(self):
        self.assertEqual(dob_alert_gate.order_in_force(
            {"record_type": "swo", "stop_work_order_number": "SWO-2020-1", "current_status": "ACTIVE"}), "swo")
        # 3A70077: DOB disposed the complaint L1 -- a partial stop-work order.
        self.assertEqual(dob_alert_gate.order_in_force(
            {"record_type": "complaint", "raw_dob_id": "3A70077", "disposition_code": "L1",
             "complaint_status": "ACTIVE"}), "swo")

    def test_a_new_summons_from_open_data_is_emailed_as_a_summons(self):
        from tests import test_whatsapp_gc_alerts_dob_dot as h
        db = h._world(source_sync_state=[])
        sent = AsyncMock()
        rec = dict(SUMMONS_CITING_SWO, _id_field="ecb_violation_number", _record_type="violation",
                   _dataset="6bgk-3dad", issue_date=NOW.strftime("%Y%m%d"))

        async def query(nyc_bin, address="", answered=None):
            if answered is not None:
                for k in ("violation", "swo", "complaint", "permit", "ds:6bgk-3dad"):
                    answered[k] = True
            return [dict(rec)]
        with h._Ctx(db=db), patch.object(server, "_query_dob_apis", query), \
                patch.object(server, "_send_critical_dob_alert_throttled", sent):
            h._run(server.run_dob_sync_for_project(dict(h.DobWaitsForTheFirstSync.PROJECT)))
        row = next(r for r in db.dob_logs.rows if r.get("raw_dob_id") == "39543624M")
        self.assertEqual(row["record_type"], "violation")
        self.assertEqual(row["violation_subtype"], "ECB")
        self.assertNotIn("swo", [c.kwargs.get("event") for c in sent.await_args_list])


class TheComplaintAlertNamesWhatDobDid(unittest.TestCase):
    REC = {"complaint_number": "3A99999", "category": "86", "description": "WORK CONTINUING DESPITE SWO",
           "received_at": NOW.isoformat(), "status": "ACTIVE", "bin": "3255205"}

    def test_a_complaint_whose_text_cites_an_order_is_urgent_but_not_an_order(self):
        d = complaint_watch.alert_decision(dict(self.REC), project_bins={"3255205"}, first_sync=False,
                                           already_alerted=False, now=NOW)
        self.assertEqual(d["event"], "new_complaint")
        self.assertEqual(d["priority"], "critical")
        en = complaint_watch.render_alert(self.REC, d, project_name="546")
        es = complaint_watch.render_alert(self.REC, d, project_name="546", lang="es")
        self.assertNotIn("STOP-WORK ORDER", en)
        self.assertIn("Urgent DOB complaint", en)
        self.assertNotIn("ORDEN DE PARAR TRABAJO", es)
        self.assertEqual(server._BIS_EMAIL_EVENT[d["event"]], "new")

    def test_a_complaint_dob_disposed_with_an_order_is_an_order(self):
        rec = dict(self.REC, disposition_code="L1")
        d = complaint_watch.alert_decision(rec, project_bins={"3255205"}, first_sync=False,
                                           already_alerted=False, now=NOW)
        self.assertEqual(d["event"], "stop_work_order")
        self.assertIn("STOP-WORK ORDER", complaint_watch.render_alert(rec, d, project_name="546"))
        self.assertEqual(server._BIS_EMAIL_EVENT[d["event"]], "swo")


class ShadowThenLiveReplaysNoHistory(unittest.TestCase):
    """Over the fake database (CI); the same sequence runs on a real mongod in
    tests/test_dob_status_real_mongo.py."""

    def test_live_after_shadow_emails_exactly_the_two_new_complaints(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        _run(db, _BIS(), "live", now=NOW + timedelta(minutes=30), emails=emails)
        self.assertEqual(sorted(e[0] for e in emails), ["3A88489", "3A88492"])

    def test_shadow_keeps_its_own_first_sync_baseline(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        watch = db.source_sync_state.docs[0]["watch"]
        self.assertNotIn("bins_first_synced", watch["bis_complaints"])
        self.assertNotIn("bins_first_synced", watch.get("bis_ecb", {}))
        self.assertEqual(sorted(watch["bis_complaints"]["shadow_bins_first_synced"]), ["3255205", "3423445"])

    def test_311_rows_are_not_dob_complaints_by_any_writer(self):
        self.assertTrue(complaint_watch.is_311({"complaint_source": "311 Complaint", "raw_dob_id": "123"}))
        self.assertTrue(complaint_watch.is_311({"complaint_source": "311", "raw_dob_id": "311:1"}))
        self.assertFalse(complaint_watch.is_311({"complaint_source": "DOB Complaint", "raw_dob_id": "3A88489"}))


class TheComplaintSourceWriters(unittest.TestCase):
    """The assistant's query excludes 311 rows by complaint_source IN THE
    DATABASE. That holds only while every complaint writer sets the field."""

    def test_every_complaint_row_builder_writes_complaint_source(self):
        project = {"_id": "p546", "company_id": "co_blueview", "nyc_bin": "3255205"}
        doc311 = server._build_311_doc({"unique_key": "70000001", "complaint_type": "Noise",
                                        "status": "In Progress", "created_date": "2026-11-10T08:00:00.000"},
                                       project, NOW)
        self.assertEqual(doc311["complaint_source"], "311")
        self.assertEqual(server._extract_complaint_fields(
            {"_dataset": "eabe-havv", "complaint_number": "3A88489", "status": "ACTIVE"})["complaint_source"],
            "DOB Complaint")
        self.assertEqual(server._extract_complaint_fields(
            {"_dataset": "erm2-nwe9", "unique_key": "1"})["complaint_source"], "311 Complaint")
        bis = server._bis_row_to_dob_log({"complaint_number": "3A88489", "status": "ACTIVE", "category": "8A"},
                                         project, "3255205", {"alert": True}, False, NOW)
        self.assertEqual(bis["complaint_source"], "DOB Complaint")


if __name__ == "__main__":
    unittest.main()
