"""An officially issued stop-work order is distinct from a violation that
references or alleges stop-work conditions (operator ruling 2026-11-11).

Wording never makes an order. An order is:
  * a record of the stop-work dataset (3usq-5cid, stop_work_order_number), or
  * a complaint DOB DISPOSED with an order code (A3 full, L1 partial, H5, K4,
    K6; vacate Y1/Y3), as BIS or Open Data reports the disposition.

Everything else keeps DOB's own classification:
  * V3 "Stop Work Order Violation Served for Non-Compliant After Hours Work"
    is a violation served (DOB's label), alerted high, never "STOP-WORK ORDER".
  * 2820774, measured in production 2026-11-11: a "V-DOB VIOLATION - ACTIVE"
    whose text reads "BOROUGH COMMISSIONER HAS ORDERED ALL WORK STOPPED" was
    given subtype SWO_FULL from those words. It is a DOB violation.
DOB's exact disposition words and their source (DOB BIS) stay on the row and
in the alert.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from lib import complaint_watch as cw, dob_alert_gate, report_regulatory, wa_alerts  # noqa: E402
from tests.test_bis_complaint_watch_flow import NOW  # noqa: E402

# 2820774 as the DOB violations dataset (3h2n-5cm9) returns it.
COMMISSIONER = {"isn_dob_bis_viol": "2820774", "number": "2820774", "bin": "3255205",
                "violation_type": "C-CONSTRUCTION                                                    OTHER   OPTIONAL",
                "violation_category": "V-DOB VIOLATION - ACTIVE", "issue_date": "20260511",
                "description": ("BOROUGH COMMISSIONER HAS ORDERED ALL WORK STOPPED UNDERPERMIT#                  "
                                "B01325801-I1 ON 3/6/26. CONTRACTOR WITHDRAWAL")}
STOP_WORK_DATASET = {"stop_work_order_number": "SWO-2020-1", "bin": "3255205", "issue_date": "2020-05-01",
                     "description": "FULL STOP WORK ORDER"}


class _Resp:
    def __init__(self, payload):
        self.status_code, self._p = 200, payload

    def json(self):
        return self._p


class _OpenData:
    async def get(self, url, params=None, **kw):
        if "3h2n-5cm9" in url and (params or {}).get("bin"):
            return _Resp([dict(COMMISSIONER)])
        if "3usq-5cid" in url and (params or {}).get("bin"):
            return _Resp([dict(STOP_WORK_DATASET)])
        return _Resp([])


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


class AViolationThatReferencesAnOrderIsAViolation(unittest.TestCase):
    def test_ingestion_types_by_source_not_wording(self):
        with patch("server.ServerHttpClient", lambda *a, **k: _Ctx(_OpenData())):
            recs = asyncio.run(server._query_dob_apis("3255205", "546 SARATOGA AVENUE, Brooklyn, NY", {}))
        by = {r.get("isn_dob_bis_viol") or r.get("stop_work_order_number"): r for r in recs}
        self.assertEqual(by["2820774"]["_record_type"], "violation")
        self.assertEqual(by["SWO-2020-1"]["_record_type"], "swo")

    def test_2820774_keeps_dobs_classification_everywhere(self):
        sub = server._classify_violation_subtype(dict(COMMISSIONER, _record_type="violation"))
        self.assertEqual(sub, "COMM_ORDER")
        row = {"record_type": "violation", "dataset": "3h2n-5cm9", "raw_dob_id": "2820774",
               "violation_number": "2820774", "violation_subtype": sub,
               "violation_type": COMMISSIONER["violation_type"],
               "violation_category": "V-DOB VIOLATION - ACTIVE", "current_status": "V-DOB VIOLATION - ACTIVE",
               "description": COMMISSIONER["description"], "resolution_state": "open"}
        self.assertIsNone(dob_alert_gate.order_in_force(row))
        self.assertFalse(wa_alerts.is_critical({"kind": "violation", "rec": row}))
        self.assertEqual(report_regulatory._kind_label(row), "DOB violation")
        # Still OPEN, still on the open-violations list, DOB's words intact.
        self.assertEqual([r["raw_dob_id"] for r in wa_alerts.open_dob_violations([row])], ["2820774"])

    def test_an_issued_order_is_still_an_order(self):
        self.assertEqual(server._classify_violation_subtype(dict(STOP_WORK_DATASET, _record_type="swo")),
                         "SWO_FULL")
        self.assertEqual(dob_alert_gate.order_in_force(
            {"record_type": "swo", "stop_work_order_number": "SWO-2020-1", "current_status": "ACTIVE"}), "swo")
        for code, kind in (("A3", "swo"), ("L1", "swo"), ("Y1", "vacate")):
            self.assertEqual(dob_alert_gate.order_in_force(
                {"record_type": "complaint", "disposition_code": code}), kind)


class V3IsWhatDobSaysItIs(unittest.TestCase):
    REC = {"complaint_number": "3A99999", "bin": "3255205", "status": "CLOSED", "category": "8A",
           "disposition_code": "V3", "received_at": NOW.isoformat(),
           "disposition_desc": "STOP WORK ORDER VIOLATION SERVED FOR NON-COMPLIANT AFTER HOURS WORK",
           "description": "WORKING AFTER HOURS"}

    def test_v3_is_a_violation_served_not_an_order(self):
        d = cw.alert_decision(dict(self.REC), project_bins={"3255205"}, first_sync=False,
                              already_alerted=False, now=NOW)
        self.assertEqual((d["alert"], d["event"], d["priority"]), (True, "violation_served", "high"))
        self.assertEqual(server._BIS_EMAIL_EVENT[d["event"]], "new")
        self.assertIsNone(dob_alert_gate.order_in_force({"record_type": "complaint", "disposition_code": "V3"}))
        self.assertFalse(wa_alerts.is_critical({"kind": "complaint", "rec": {"disposition_code": "V3"}}))

    def test_the_alert_carries_dobs_exact_words_and_source(self):
        d = cw.alert_decision(dict(self.REC), project_bins={"3255205"}, first_sync=False,
                              already_alerted=False, now=NOW)
        en = cw.render_alert(self.REC, d, project_name="546")
        es = cw.render_alert(self.REC, d, project_name="546", lang="es")
        self.assertNotIn("STOP-WORK ORDER —", en)
        self.assertIn("DOB disposition (BIS): V3 - STOP WORK ORDER VIOLATION SERVED FOR NON-COMPLIANT "
                      "AFTER HOURS WORK.", en)
        self.assertIn("Disposición del DOB (BIS): V3 - STOP WORK ORDER VIOLATION SERVED", es)
        self.assertNotIn("ORDEN DE PARAR TRABAJO —", es)

    def test_the_stored_row_keeps_dobs_words_and_source(self):
        doc = server._bis_row_to_dob_log(dict(self.REC), {"_id": "p546", "company_id": "c"}, "3255205",
                                         {"alert": True}, False, NOW)
        self.assertEqual(doc["disposition_code"], "V3")
        self.assertEqual(doc["disposition_label"],
                         "V3 - STOP WORK ORDER VIOLATION SERVED FOR NON-COMPLIANT AFTER HOURS WORK")
        self.assertEqual(doc["disposition_source"], "DOB BIS")
        self.assertIn("V3 - STOP WORK ORDER VIOLATION SERVED", doc["ai_summary"])

    def test_without_bis_words_the_code_tables_label_is_used(self):
        self.assertEqual(cw.disposition_words({"disposition_code": "V3"}),
                         "V3 - Stop Work Order Violation Served for Non-Compliant After Hours Work")
        self.assertIsNone(cw.disposition_words({"disposition_code": None}))


if __name__ == "__main__":
    unittest.main()
