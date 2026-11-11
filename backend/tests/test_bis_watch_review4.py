"""Independent review of the combined branch (892e350d): the findings fixed
here, each pinned. Records are the real 546 Saratoga BIS pages unless a
finding needs a state those pages do not show (then the edit is named).

D1  rows the watch inserts counted closed items as open (no resolution_state;
    BIS "RESOLVED" where /dob-summary looks for "closed").
D2  a stop-work order lifted in full was never alerted once BIS saw it first.
D3  a complaint's TEXT ("work contrary to stop work order") counted as an order
    in force, so DOB's real A3 later was never alerted.
D4  disposition sets: H3/H4/V3 (violations FOR disobeying an SWO) read as new
    orders; A4 read as a lift; L2/Y2 (the real full rescinds) missing; a vacate
    order was emailed as a stop-work order.
D5  the two production rows an older scan typed 'swo' (ECB summonses) still
    read as stop-work orders.
D6  a summons the watch stored dropped out of /dob-summary on Open Data's
    first refresh (no status history -> "seed transition").
D7  a summons shadow judged new, stored silently by Open Data before live,
    was never alerted.
D9  the assistant printed "Open DOB complaints (5)" for any number over 5.
And a malformed BIS issue date no longer aborts the pass.
"""

from __future__ import annotations

import asyncio
import copy
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

import server  # noqa: E402
from lib import complaint_watch as cw, dob_alert_gate, report_regulatory, wa_alerts  # noqa: E402
from tests.test_bis_complaint_watch_flow import NOW, PROJECT, _BIS, _Resp, _run, _seed  # noqa: E402


class _ListEdit(_BIS):
    """The real list page for BIN 3255205 with ONE cell of one row changed,
    and (when given) the same change on that complaint's real detail page."""
    def __init__(self, cn, old, new, detail=None):
        super().__init__()
        self.cn, self.old, self.new, self.detail = cn, old, new, detail

    async def get(self, url, **kw):
        r = await super().get(url, **kw)
        if "ComplaintsByAddressServlet" in url and "allbin=3255205" in url:
            head, tail = r.text.split(f">{self.cn}</a></td>", 1)
            return _Resp(200, head + f">{self.cn}</a></td>" + tail.replace(self.old, self.new, 1))
        if self.detail and "OverviewForComplaintServlet" in url and f"complaintno={self.cn}" in url:
            return _Resp(200, r.text.replace(*self.detail))
        return r


class D1RowsCountTheirRealState(unittest.TestCase):
    def test_live_inserts_count_only_the_two_open_summonses_and_two_open_complaints(self):
        db, emails = _seed(), []
        db.dob_logs.docs[:] = []            # nothing stored: every BIS row is inserted
        _run(db, _BIS(), "live", emails=emails)
        ecb = [d for d in db.dob_logs.docs if d.get("dataset") == "bis-ecb"]
        self.assertEqual(len(ecb), 20)
        self.assertEqual(sorted(r["raw_dob_id"] for r in wa_alerts.open_dob_violations(ecb)),
                         ["39556258Y", "39556260N"])
        comp = [d for d in db.dob_logs.docs if d.get("record_type") == "complaint"]
        self.assertEqual(sorted(d["raw_dob_id"] for d in comp if not wa_alerts.is_closed(d)),
                         ["3A88489", "3A88492"])
        self.assertTrue(all(d["complaint_status"] in ("ACTIVE", "CLOSED") for d in comp))
        # 35716973H, rear BIN, "CURE ACCEPTED": resolved.
        rear = next(d for d in ecb if d["nyc_bin"] == "3423445")
        self.assertIn(rear["resolution_state"], wa_alerts.RESOLVED_STATES)


class D2ALiftIsAlerted(unittest.TestCase):
    def test_l1_to_l2_on_bis_emails_the_lift_once(self):
        db, emails = _seed(), []
        row = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A70077")
        row.update(complaint_status="ACTIVE", current_status="ACTIVE", disposition_code="L1")
        # BIS: 3A70077 RESOLVED with L2 ("Stop Work Order Fully Rescinded").
        client = _ListEdit("3A70077", "<td class=\"content\" align=\"center\" bgcolor='red'>L1</td>",
                           '<td class="content" align="center">L2</td>',
                           detail=("L1 - PARTIAL STOP WORK ORDER", "L2 - STOP WORK ORDER FULLY RESCINDED"))
        _run(db, client, "live", emails=emails)
        self.assertIn(("3A70077", "bis", "swo_lifted"), emails)
        self.assertIsNotNone(row.get("order_lifted"))
        emails2 = []
        _run(db, client, "live", now=NOW + timedelta(minutes=10), emails=emails2)
        self.assertNotIn(("3A70077", "bis", "swo_lifted"), emails2)


class D3AComplaintIsAnOrderOnlyByItsDisposition(unittest.TestCase):
    BEFORE = {"record_type": "complaint", "raw_dob_id": "3A99999", "complaint_status": "ACTIVE",
              "description": "WORK CONTRARY TO STOP WORK ORDER", "category_label": "Work Contrary to Stop Work Order"}

    def test_the_text_is_not_an_order_and_dobs_a3_is(self):
        self.assertIsNone(dob_alert_gate.order_in_force(self.BEFORE))
        self.assertEqual(dob_alert_gate.update_issues_order(
            self.BEFORE, dict(self.BEFORE, disposition_code="A3")), "swo")
        self.assertFalse(wa_alerts.is_critical({"kind": "complaint", "rec": self.BEFORE}))
        self.assertTrue(wa_alerts.is_critical({"kind": "complaint", "rec": dict(self.BEFORE, disposition_code="A3")}))


class D4DispositionsReadAsDobLabelsThem(unittest.TestCase):
    def _d(self, code, status="CLOSED"):
        return cw.alert_decision({"complaint_number": "3A99999", "bin": "3255205", "status": status,
                                  "disposition_code": code, "received_at": NOW.isoformat()},
                                 project_bins={"3255205"}, first_sync=False, already_alerted=False, now=NOW)

    def test_violations_for_disobeying_an_swo_are_violations(self):
        for code in ("H3", "H4", "V3", "A4", "A1", "A5", "A9"):
            with self.subTest(code=code):
                d = self._d(code)
                self.assertEqual((d["alert"], d["event"], d["priority"]), (True, "violation_served", "high"))
                self.assertIsNone(dob_alert_gate.order_in_force(
                    {"record_type": "complaint", "disposition_code": code}))

    def test_orders(self):
        self.assertEqual(self._d("A3")["event"], "stop_work_order")
        self.assertEqual(self._d("L1", "ACTIVE")["event"], "stop_work_order")
        d = self._d("Y1")
        self.assertEqual(d["event"], "vacate_order")
        self.assertEqual(server._BIS_EMAIL_EVENT[d["event"]], "vacate")
        self.assertIn("VACATE ORDER", cw.render_alert({"complaint_number": "3A99999"}, d, project_name="x"))
        self.assertEqual(dob_alert_gate.order_in_force({"record_type": "complaint", "disposition_code": "Y3"}),
                         "vacate")

    def test_full_rescinds_are_lifts_and_not_alerted_as_new(self):
        for code in ("L2", "Y2"):
            self.assertEqual(cw.disposition_class(code), "order_lifted")
            self.assertFalse(self._d(code)["alert"])
        self.assertEqual(dob_alert_gate.update_lifts_order(
            {"record_type": "complaint", "disposition_code": "L1", "complaint_status": "ACTIVE"},
            {"record_type": "complaint", "disposition_code": "L2", "complaint_status": "CLOSED"}), "swo")

    def test_padlock_and_emergency_are_urgent_but_not_stop_work(self):
        d = self._d("P3")
        self.assertEqual((d["alert"], d["event"], d["priority"]), (True, "new_complaint", "critical"))


class D5OldSummonsTypedSwo(unittest.TestCase):
    ROW = {"record_type": "swo", "dataset": "6bgk-3dad", "raw_dob_id": "39550534Y", "current_status": None,
           "violation_subtype": "ECB",
           "description": "AT TIME OF INSPECTION OBSERVED: COLD FORM STEEL FRAMEWORK COMPLETED AT BULKHEAD LEVEL"}

    def test_it_reads_as_a_summons_everywhere(self):
        self.assertTrue(wa_alerts.is_summons(self.ROW))
        self.assertIsNone(dob_alert_gate.order_in_force(self.ROW))
        self.assertFalse(wa_alerts.is_critical({"kind": "swo", "rec": self.ROW}))
        self.assertNotEqual(report_regulatory._kind_label(self.ROW), "Stop Work Order")

    def test_a_stop_work_dataset_row_is_still_an_order(self):
        sw = {"record_type": "swo", "stop_work_order_number": "SWO-1", "dataset": "3usq-5cid",
              "current_status": "ACTIVE"}
        self.assertFalse(wa_alerts.is_summons(sw))
        self.assertEqual(dob_alert_gate.order_in_force(sw), "swo")
        self.assertEqual(report_regulatory._kind_label(sw), "Stop Work Order")


class D6TheRefreshIsNoChange(unittest.TestCase):
    def test_open_datas_row_for_a_watch_stored_summons_changes_nothing(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        row = next(d for d in db.dob_logs.docs if d.get("raw_dob_id") == "39556258Y")
        # Open Data (6bgk-3dad) for 39556258Y on 2026-11-10: ACTIVE, no certification status.
        od = dict(row, current_status=None, status=None, dataset="6bgk-3dad")
        _, changed, legacy = server._plan_in_place_refresh(row, od, NOW + timedelta(days=1))
        self.assertFalse(legacy)
        self.assertFalse(changed)


class D7OwedFromShadow(unittest.TestCase):
    """Shadow on 2026-07-08, the day after both July summonses were issued, so
    shadow judges them new. Open Data then stores them silently. Live on 07-13
    tells someone once."""
    def test_a_summons_shadow_judged_new_and_open_data_stored_silently_is_alerted_once(self):
        db = _seed()
        shadow_now = datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)
        _run(db, _BIS(), "shadow", now=shadow_now, emails=[])
        would = sorted(r["violation_number"] for r in db.complaint_watch_ledger.docs
                       if r.get("mode") == "shadow" and r.get("status") == "would_alert" and r.get("violation_number"))
        self.assertEqual(would, ["39556258Y", "39556260N"])
        for num in would:
            db.dob_logs.docs.append({"_id": f"od_{num}", "project_id": "p546", "company_id": "co_blueview",
                                     "record_type": "violation", "raw_dob_id": num, "dataset": "6bgk-3dad",
                                     "violation_number": num, "nyc_bin": "3255205", "is_deleted": False,
                                     "detected_at": datetime(2026, 7, 11, tzinfo=timezone.utc)})
        emails = []
        _run(db, _BIS(), "live", now=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc), emails=emails)
        self.assertEqual(sorted(e for e in emails if e[0].startswith("3955")),
                         [("39556258Y", "bis", "new"), ("39556260N", "bis", "new")])
        again = []
        _run(db, _BIS(), "live", now=datetime(2026, 7, 13, 14, 10, tzinfo=timezone.utc), emails=again)
        self.assertEqual([e for e in again if e[0].startswith("3955")], [])

    def test_already_emailed_by_open_data_is_not_owed(self):
        db = _seed()
        _run(db, _BIS(), "shadow", now=datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc), emails=[])
        for num in ("39556258Y", "39556260N"):
            db.dob_logs.docs.append({"_id": f"od_{num}", "project_id": "p546", "company_id": "co_blueview",
                                     "record_type": "violation", "raw_dob_id": num, "dataset": "6bgk-3dad",
                                     "nyc_bin": "3255205", "is_deleted": False,
                                     "detected_at": datetime(2026, 7, 9, tzinfo=timezone.utc)})
            db.system_config.docs.append({"key": server._dob_alert_key("p546", num) + ":new"})
        emails = []
        _run(db, _BIS(), "live", now=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc), emails=emails)
        self.assertEqual([e for e in emails if e[0].startswith("3955")], [])


class D9TheCountIsTheCount(unittest.TestCase):
    def test_seven_open_complaints_say_seven(self):
        db = _seed()
        db.projects.docs.append(dict(PROJECT))
        for i in range(7):
            db.dob_logs.docs.append({"_id": f"o{i}", "project_id": "p546", "company_id": "co_blueview",
                                     "record_type": "complaint", "raw_dob_id": f"3A9000{i}",
                                     "complaint_status": "ACTIVE", "complaint_source": "DOB Complaint",
                                     "detected_at": NOW - timedelta(hours=i), "is_deleted": False})
        with patch.object(server, "db", db):
            out = asyncio.run(server._handle_dob_status("p546", company_id="co_blueview"))
        self.assertIn("Open DOB complaints (7), the 5 newest:", out)


class FinalReviewOfTheFixes(unittest.TestCase):
    """Second reviewer, on 1a79ba4b."""

    def test_an_owed_complaint_now_under_an_order_emails_the_order_once_and_writes_it(self):
        db = _seed()
        _run(db, _BIS(), "shadow", now=NOW, emails=[])
        # Open Data stored 3A88489 silently, no disposition yet (eabe-havv is days stale).
        db.dob_logs.docs.append({"_id": "od_3A88489", "project_id": "p546", "company_id": "co_blueview",
                                 "record_type": "complaint", "raw_dob_id": "3A88489", "complaint_number": "3A88489",
                                 "complaint_status": "ACTIVE", "current_status": "ACTIVE",
                                 "complaint_source": "DOB Complaint", "nyc_bin": "3255205", "is_deleted": False,
                                 "detected_at": NOW + timedelta(days=1)})
        # BIS three days on: DOB disposed 3A88489 A3 (full stop-work order).
        client = _ListEdit("3A88489", '<td class="content" align="center"></td>',
                           '<td class="content" align="center">A3</td>')
        emails = []
        _run(db, client, "live", now=NOW + timedelta(days=3), emails=emails)
        self.assertEqual([e for e in emails if e[0] == "3A88489"], [("3A88489", "bis", "swo")])
        row = next(d for d in db.dob_logs.docs if d["_id"] == "od_3A88489")
        self.assertEqual(row["disposition_code"], "A3")
        self.assertIsNotNone(row.get("order_issued"))
        again = []
        _run(db, client, "live", now=NOW + timedelta(days=3, minutes=10), emails=again)
        self.assertEqual([e for e in again if e[0] == "3A88489"], [])

    def test_v3_is_a_violation_served_per_the_operator_ruling(self):
        # Ruled 2026-11-11: wording never makes an order; V3 is what DOB labels
        # it (tests/test_an_order_is_issued_not_worded.py has the full case).
        self.assertIsNone(dob_alert_gate.order_in_force({"record_type": "complaint", "disposition_code": "V3"}))

    def test_a_partial_rescind_leaves_the_order_so_the_full_lift_alerts(self):
        a3 = {"record_type": "complaint", "disposition_code": "A3", "complaint_status": "ACTIVE"}
        l3 = dict(a3, disposition_code="L3")
        l2 = dict(a3, disposition_code="L2", complaint_status="CLOSED")
        self.assertIsNone(dob_alert_gate.update_issues_order(a3, l3))
        self.assertIsNone(dob_alert_gate.update_lifts_order(a3, l3))
        self.assertEqual(dob_alert_gate.update_lifts_order(l3, l2), "swo")

    def test_the_brief_does_not_call_an_old_summons_a_stop_work_order(self):
        from lib import wa_brief
        row = {"_id": "r1", "project_id": "p1", "record_type": "swo", "dataset": "6bgk-3dad",
               "raw_dob_id": "39550534Y", "violation_number": "39550534Y", "violation_date": "20260601",
               "current_status": None, "violation_subtype": "ECB"}
        line = " ".join(wa_brief.open_items([row], [], NOW.date()))
        self.assertIn("39550534Y", line)
        self.assertNotIn("Stop-work order", line)
        self.assertEqual(report_regulatory._kind_label(dict(row, violation_subtype="VACATE_FULL")),
                         "DOB violation")


class AMalformedIssueDateNeverAbortsThePass(unittest.TestCase):
    def test_undated_summons_is_decided_not_raised(self):
        d = cw.summons_decision({"ecb_number": "39500000X", "active": True, "issue_date": "0000-00-00",
                                 "severity": "CLASS - 1"}, bin_="3255205", project_bins={"3255205"},
                                first_sync=True, already_alerted=False, now=NOW)
        self.assertFalse(d["alert"])


if __name__ == "__main__":
    unittest.main()
