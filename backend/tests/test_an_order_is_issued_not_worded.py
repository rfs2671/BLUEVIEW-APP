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


class DobsWordsSurviveTheOpenDataRefresh(unittest.TestCase):
    """Final review: Open Data's midnight extract wrote yesterday's state and
    Levelog's own label over what BIS printed, with the source tag still
    'DOB BIS'. While the watch is live and fresh, BIS owns those fields."""

    BIS_ROW = {"_id": "bisc", "project_id": "proj_a", "record_type": "complaint", "raw_dob_id": "3A70077",
               "complaint_number": "3A70077", "complaint_type": "8A", "complaint_status": "CLOSED",
               "current_status": "CLOSED", "disposition_code": "L1", "disposition_date": "2026-07-07",
               "disposition_label": "L1 - PARTIAL STOP WORK ORDER", "disposition_source": "DOB BIS",
               "complaint_source": "DOB Complaint", "dataset": "bis", "nyc_bin": "3012345", "is_deleted": False}
    # eabe-havv, a day behind: still ACTIVE, not yet disposed.
    OD = {"_id_field": "complaint_number", "_record_type": "complaint", "_dataset": "eabe-havv",
          "complaint_number": "3A70077", "status": "ACTIVE", "complaint_category": "8A",
          "date_entered": "07/07/2026", "bin": "3012345", "house_number": "1", "house_street": "MAIN ST"}

    BIS = {"status": "RESOLVED", "disposition_code": "L1", "disposition_date": "2026-07-07",
           "disposition_desc": "PARTIAL STOP WORK ORDER"}

    def _sync(self, mode, fresh_minutes, *, seen_minutes=5, top=None, od=None, bis=True):
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        from tests import test_bis_watch_review2 as r2
        h, db = r2._gc_world()
        now = _dt.now(_tz.utc)
        row = dict(self.BIS_ROW, company_id=h.CO_A, detected_at=now - _td(days=2),
                   bis_first_seen_at=now - _td(days=2),
                   status_history=[{"status": "CLOSED", "at": now - _td(days=2), "source": "bis"}])
        if bis:
            row.update(bis=dict(self.BIS), bis_last_seen_at=now - _td(minutes=seen_minutes))
        row.update(top or {})
        db.dob_logs.rows.append(row)
        db.source_sync_state.rows.append({"_id": "proj_a", "watch": {"bis_complaints": {
            "mode": "live", "last_error": None, "last_success_at": now - _td(minutes=fresh_minutes)}}})
        with h._Ctx(db=db), patch.object(server, "_bis_watch_mode", lambda: mode):
            events = r2._open_data_sync(h, db, [dict(od or self.OD)])
        return next(r for r in db.dob_logs.rows if r["raw_dob_id"] == "3A70077"), events

    def test_live_and_fresh_keeps_dobs_state_words_and_source(self):
        row, _ = self._sync("live", 10)
        self.assertEqual((row["complaint_status"], row["disposition_code"]), ("CLOSED", "L1"))
        self.assertEqual(row["disposition_label"], "L1 - PARTIAL STOP WORK ORDER")
        self.assertEqual(row["disposition_source"], "DOB BIS")
        self.assertEqual(len(row["status_history"]), 1)          # no flip recorded

    def test_a_row_an_older_refresh_overwrote_is_repaired_not_frozen(self):
        # What the pre-fix refresh left on the row: ACTIVE, no disposition,
        # Levelog's label. BIS's own record still says RESOLVED / L1.
        row, _ = self._sync("live", 10, top={"complaint_status": "ACTIVE", "current_status": "ACTIVE",
                                             "disposition_code": None,
                                             "disposition_label": "Open: awaiting DOB inspection"})
        self.assertEqual((row["complaint_status"], row["disposition_code"]), ("CLOSED", "L1"))
        self.assertEqual(row["disposition_label"], "L1 - PARTIAL STOP WORK ORDER")

    def test_off_shadow_stale_or_not_listed_lets_open_data_refresh_as_before(self):
        for mode, minutes, seen in (("off", 10, 5), ("shadow", 10, 5), ("live", 180, 5), ("live", 10, 180)):
            with self.subTest(mode=mode, project_read_minutes=minutes, row_listed_minutes=seen):
                row, _ = self._sync(mode, minutes, seen_minutes=seen)
                self.assertEqual(row["complaint_status"], "ACTIVE")

    def test_a_stop_work_disposition_bis_did_not_list_still_alerts_from_open_data(self):
        # Watch live and fresh, but this complaint has no BIS record (an older
        # page / another BIN): Open Data's A3 is news, and it emails.
        row, events = self._sync("live", 10, bis=False,
                                 top={"complaint_status": "ACTIVE", "current_status": "ACTIVE",
                                      "disposition_code": None},
                                 od=dict(self.OD, disposition_code="A3", disposition_date="11/09/2026"))
        self.assertEqual(row["disposition_code"], "A3")
        self.assertIn("swo", events)

    def test_the_live_watch_stamps_what_it_listed_and_shadow_does_not(self):
        from datetime import timedelta as _td
        from tests.test_bis_complaint_watch_flow import _BIS, _run, _seed
        db = _seed()
        _run(db, _BIS(), "live", emails=[])
        _run(db, _BIS(), "live", now=NOW + _td(minutes=30), emails=[])
        r = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489")
        self.assertEqual(r["bis_last_seen_at"], NOW + _td(minutes=30))
        _run(db, _BIS(), "shadow", now=NOW + _td(minutes=40), emails=[])
        r = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489")
        self.assertEqual(r["bis_last_seen_at"], NOW + _td(minutes=30))


class NoStopWorkWordsWithoutAnOrder(unittest.TestCase):
    def test_a_violation_typed_with_stop_work_words_gets_violation_advice(self):
        advice = server._generate_next_action({"violation_type": "SWO VIOLATION - AFTER HOURS"},
                                              "violation", "Action")
        self.assertNotIn("STOP ALL WORK", advice)
        self.assertIn("STOP ALL WORK", server._generate_next_action({"stop_work_order_number": "1"},
                                                                    "swo", "Action"))

    def test_a_complaints_stop_work_text_is_not_named_an_issued_order(self):
        sa = cw.safety_assessment({"description": "WORK CONTINUING DESPITE SWO", "category": "86"})
        self.assertIn("text mentions a stop-work order (not an issued order)", " ".join(sa["reasons"]))
        self.assertIn("an issued order", " ".join(cw.safety_assessment({"disposition_code": "A3"})["reasons"]))

    def test_the_source_says_where_the_words_came_from(self):
        self.assertEqual(cw.disposition_source({"disposition_code": "V3", "disposition_desc": "X"}), "DOB BIS")
        self.assertEqual(cw.disposition_source({"disposition_code": "V3"}),
                         "DOB BIS (code); label from DOB's code table")
        self.assertIsNone(cw.disposition_source({}))


if __name__ == "__main__":
    unittest.main()
