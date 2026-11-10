"""The BIS complaint watch, end to end over the real 546 Saratoga BIS pages.

server.run_bis_complaint_watch_for_project with a fake Mongo and an HTTP stub
that serves tests/fixtures/bis_complaints/ (fetched 2026-11-10 19:48 UTC). The
project is seeded with what the Open Data scan had actually stored for 546 that
day (history, none of the two new complaints).

Pins: shadow writes no record and sends nothing; live stores the two new
complaints once and emails each once; a second pass changes nothing; the
Open Data row that arrives the next day refreshes the same row; a BIS outage
is recorded as a failure, never as "no complaints".
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
from lib import bis_complaints as bis  # noqa: E402
from lib import complaint_watch as cw  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, matches  # noqa: E402

FIX = _HERE / "fixtures" / "bis_complaints"
NOW = datetime(2026, 11, 10, 19, 48, tzinfo=timezone.utc)
PROJECT = {"_id": "p546", "company_id": "co_blueview", "name": "546 Saratoga Ave", "nyc_bin": "3255205",
           "track_dob_status": True}


class _Coll(AsyncFakeCollection):
    async def insert_one(self, doc, **kw):
        if "_id" in doc and any(d.get("_id") == doc["_id"] for d in self.docs):
            raise RuntimeError("E11000 duplicate key")
        return await super().insert_one(doc, **kw)

    async def delete_one(self, flt, **kw):
        for i, d in enumerate(self.docs):
            if matches(d, flt):
                del self.docs[i]
                break

    async def distinct(self, key, flt=None):
        return sorted({d.get(key) for d in self.docs if matches(d, flt) and d.get(key) is not None})

    async def update_one(self, flt, update, upsert=False, **kw):
        self.__dict__.setdefault("updates", []).append(copy.deepcopy(update))
        hit = [d for d in self.docs if matches(d, flt)]
        if not hit and upsert:
            self.docs.append({k: v for k, v in flt.items() if not isinstance(v, dict)})
        for d in [x for x in self.docs if matches(x, flt)][:1]:
            for k, spec in (update.get("$addToSet") or {}).items():
                cur, parts = d, k.split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                lst = cur.setdefault(parts[-1], [])
                for v in (spec.get("$each") if isinstance(spec, dict) else [spec]):
                    if v not in lst:
                        lst.append(v)
        return await super().update_one(flt, {k: v for k, v in update.items() if k != "$addToSet"})


class _DB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Coll(name)
        return self._c[name]


class _Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


class _BIS:
    """Serves the real pages by URL; `down` makes every call a 503."""
    def __init__(self, down=False):
        self.down, self.urls = down, []

    async def get(self, url, **kw):
        self.urls.append(url)
        if self.down:
            return _Resp(503, "Service Unavailable")
        if "PropertyProfileOverviewServlet" in url and "bin=3255205" in url:
            return _Resp(200, (FIX / "property_3255205.html").read_text(encoding="latin-1"))
        if "ComplaintsByAddressServlet" in url and "allbin=3255205" in url:
            return _Resp(200, (FIX / "list_3255205.html").read_text(encoding="latin-1"))
        if "ECBQueryByLocationServlet" in url:
            b = url.split("allbin=")[1][:7]
            return _Resp(200, (FIX / f"ecb_{b}.html").read_text(encoding="latin-1"))
        if "ComplaintsByAddressServlet" in url and "allbin=3423445" in url:
            return _Resp(200, (FIX / "list_3423445.html").read_text(encoding="latin-1"))
        if "OverviewForComplaintServlet" in url:
            cn = url.split("complaintno=")[1].split("&")[0]
            f = FIX / f"detail_{cn}.html"
            if f.exists():
                return _Resp(200, f.read_text(encoding="latin-1"))
            return _Resp(200, "Overview for Complaint #: = *** COMPLAINT NUMBER NOT FOUND ****")
        return _Resp(404, "")


def _seed() -> _DB:
    db = _DB()
    db.projects.docs.append(copy.deepcopy(PROJECT))
    # What the Open Data scan had stored for 546 on 2026-11-10 (by number/status).
    for cn, st, disp, day in (("3A70078", "CLOSED", "A8", "2026-07-07"), ("3A70077", "CLOSED", "L1", "2026-07-07"),
                              ("3A68500", "CLOSED", "A8", "2026-06-25"), ("3A48317", "CLOSED", "I2", "2026-02-11"),
                              ("3A35232", "CLOSED", "L2", "2025-10-30"), ("3A35190", "CLOSED", "L2", "2025-10-30"),
                              ("3A35075", "CLOSED", "L2", "2025-10-29")):
        db.dob_logs.docs.append({"_id": f"od_{cn}", "project_id": "p546", "company_id": "co_blueview",
                                 "record_type": "complaint", "raw_dob_id": cn, "complaint_number": cn,
                                 "complaint_status": st, "current_status": st, "disposition_code": disp,
                                 "complaint_date": f"{day}T00:00:00.000", "nyc_bin": "3255205",
                                 "detected_at": datetime(2026, 10, 13, 15, 47, tzinfo=timezone.utc),
                                 "is_deleted": False})
    db.source_sync_state.docs.append({"_id": "p546", "company_id": "co_blueview", "sources": {
        "dob_complaints": {"first_synced_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
                           "synced_at": NOW - timedelta(minutes=14)}}})
    return db


def _run(db, client, mode, now=NOW, emails=None, bodies=None):
    async def fake_send(project, doc, source="dob", *, event):
        from lib import dob_alert_gate
        assert event in dob_alert_gate.EVENTS, event          # the email's own vocabulary
        emails.append((doc.get("raw_dob_id"), source, event))
        if bodies is not None:
            bodies.append(doc.get("ai_summary") or "")
        return True
    with patch.object(server, "db", db), \
            patch.object(server, "_send_critical_dob_alert_throttled", fake_send):
        return asyncio.run(server.run_bis_complaint_watch_for_project(
            copy.deepcopy(PROJECT), client, mode=mode, now=now))


class Shadow(unittest.TestCase):
    def test_shadow_records_decisions_and_writes_no_record(self):
        db, emails = _seed(), []
        s = _run(db, _BIS(), "shadow", emails=emails)
        self.assertEqual(emails, [])
        self.assertFalse([d for d in db.dob_logs.docs if d["raw_dob_id"] in ("3A88489", "3A88492")])
        led = {d["complaint_number"]: d for d in db.complaint_watch_ledger.docs if "complaint_number" in d}
        self.assertEqual((led["3A88489"]["status"], led["3A88492"]["status"]), ("would_alert", "would_alert"))
        self.assertEqual(led["3A88489"]["priority"], "high")
        self.assertEqual(sorted(b["bin"] for b in s["bins"]), ["3255205", "3423445"])
        w = db.source_sync_state.docs[0]["watch"]["bis_complaints"]
        self.assertEqual((w["last_success_at"], w["last_error"]), (NOW, None))


def _details(client) -> int:
    return sum("OverviewForComplaintServlet" in u for u in client.urls)


class FetchBudget(unittest.TestCase):
    """BIS says RESOLVED where Open Data says CLOSED. Without treating them as
    one state every stored history row looks changed and is re-fetched."""

    def test_first_pass_fetches_details_only_for_rows_open_data_had_not_stored(self):
        db, emails, client = _seed(), [], _BIS()
        _run(db, client, "live", emails=emails)
        # 16 rows on BIN 3255205 + 1 on 3423445, minus the 7 Open Data had stored unchanged
        self.assertEqual(_details(client), 10, client.urls)

    def test_shadow_does_not_refetch_what_it_already_decided(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        again = _BIS()
        _run(db, again, "shadow", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual(_details(again), 0, again.urls)


class Live(unittest.TestCase):
    def test_live_stores_each_new_complaint_once_and_emails_each_once(self):
        db, emails, bodies = _seed(), [], []
        _run(db, _BIS(), "live", emails=emails, bodies=bodies)
        new = [d for d in db.dob_logs.docs if d["raw_dob_id"] in ("3A88489", "3A88492")]
        self.assertEqual(sorted(d["raw_dob_id"] for d in new), ["3A88489", "3A88492"])
        for d in new:
            self.assertEqual((d["dataset"], d["severity"], d["bin_first_pass"], d["current_status"]),
                             ("bis", "Action", False, "ACTIVE"))
            self.assertEqual(d["complaint_date"], "2026-11-10T00:00:00.000")
        self.assertEqual(sorted(emails), [("3A88489", "bis", "new"), ("3A88492", "bis", "new")])
        body = next(b for b in bodies if "3A88489" in b)
        self.assertIn("NO ROOF PROTECTION", body)
        self.assertIn("A complaint is not a violation", body)
        # history that Open Data already stored was not duplicated
        for cn in ("3A70078", "3A35190"):
            self.assertEqual(len([d for d in db.dob_logs.docs if d["raw_dob_id"] == cn]), 1)

    def test_a_second_pass_changes_nothing_and_sends_nothing(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        n_rows, n_led = len(db.dob_logs.docs), len(db.complaint_watch_ledger.docs)
        emails.clear()
        client = _BIS()
        _run(db, client, "live", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual((len(db.dob_logs.docs), len(db.complaint_watch_ledger.docs), emails), (n_rows, n_led, []))
        # a quiet pass: one property page, one complaint list and one ECB list
        # per BIN -- no detail fetches
        self.assertEqual(len(client.urls), 5, client.urls)

    def test_the_open_data_row_next_day_refreshes_the_same_row(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        row = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489")
        # what the Open Data path builds for the same complaint the next day
        od = {"project_id": "p546", "record_type": "complaint", "raw_dob_id": "3A88489",
              "current_status": "ACTIVE", "complaint_status": "ACTIVE", "detected_at": NOW + timedelta(days=1),
              "severity": "Action", "dataset": "eabe-havv"}
        update, changed, _ = server._plan_in_place_refresh(row, od, NOW + timedelta(days=1))
        self.assertNotIn("detected_at", update, "detection time must stay the BIS time")
        self.assertNotIn("bis", update)
        self.assertFalse(changed)


class Outage(unittest.TestCase):
    def test_a_bis_outage_is_a_recorded_failure_not_an_absence(self):
        db, emails = _seed(), []
        s = _run(db, _BIS(down=True), "live", emails=emails)
        self.assertTrue(s["errors"])
        self.assertEqual(s["decisions"], [])
        w = db.source_sync_state.docs[0]["watch"]["bis_complaints"]
        self.assertNotIn("last_success_at", w)
        self.assertIn("HTTP 503", w["last_error"])
        f = cw.freshness(db.source_sync_state.docs[0], now=NOW)
        self.assertFalse(f["can_say_no_new_complaints"])
        self.assertEqual(f["sources"][0]["status"], "failing")


class Off(unittest.TestCase):
    def test_off_is_the_default_and_does_nothing(self):
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": ""}):
            self.assertEqual(server._bis_watch_mode(), "off")
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": "LIVE "}):
            self.assertEqual(server._bis_watch_mode(), "live")
        with patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": "yes"}):
            self.assertEqual(server._bis_watch_mode(), "off")


if __name__ == "__main__":
    unittest.main()


class EcbDiscovery(unittest.TestCase):
    """The summons half of the watch, on the real 546 ECB pages."""

    def test_first_pass_stores_the_history_and_alerts_none(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        ecb = [d for d in db.dob_logs.docs if d.get("dataset") == "bis-ecb"]
        self.assertEqual(len(ecb), 20)                       # 19 on 3255205 + 1 on 3423445
        self.assertTrue(all(d["bin_first_pass"] for d in ecb))
        self.assertEqual([e for e in emails if e[0] in {d["raw_dob_id"] for d in ecb}], [])
        w = db.source_sync_state.docs[0]["watch"]["bis_ecb"]
        self.assertEqual((w["last_success_at"], w["last_error"]), (NOW, None))

    def test_a_summons_bis_has_and_levelog_does_not_is_found_and_emailed_once(self):
        db, emails = _seed(), []
        db.source_sync_state.docs[0]["watch"] = {"bis_ecb": {"bins_first_synced": ["3255205", "3423445"]}}
        from lib import bis_violations as bv
        for r in bv.parse_ecb_list((FIX / "ecb_3255205.html").read_text(encoding="latin-1"))["rows"]:
            if r["ecb_number"] not in ("39556260N", "39556258Y"):      # LeveLog lacks the two open ones
                db.dob_logs.docs.append({"_id": f"od_{r['ecb_number']}", "project_id": "p546",
                                         "record_type": "violation", "raw_dob_id": r["ecb_number"],
                                         "dataset": "6bgk-3dad", "is_deleted": False})
        db.dob_logs.docs.append({"_id": "od_35716973H", "project_id": "p546", "record_type": "violation",
                                 "raw_dob_id": "35716973H", "dataset": "6bgk-3dad", "is_deleted": False})
        _run(db, _BIS(), "live", emails=emails)
        found = sorted(d["raw_dob_id"] for d in db.dob_logs.docs if d.get("dataset") == "bis-ecb")
        self.assertEqual(found, ["39556258Y", "39556260N"])
        self.assertEqual(sorted(e for e in emails if e[0] in found),
                         [("39556258Y", "bis", "new"), ("39556260N", "bis", "new")])
        emails.clear()
        _run(db, _BIS(), "live", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual(emails, [])

    def test_an_ecb_outage_does_not_fail_the_complaint_watch(self):
        db, emails = _seed(), []

        class _EcbDown(_BIS):
            async def get(self, url, **kw):
                if "ECBQueryByLocationServlet" in url:
                    self.urls.append(url)
                    return _Resp(503, "down")
                return await super().get(url, **kw)
        _run(db, _EcbDown(), "live", emails=emails)
        w = db.source_sync_state.docs[0]["watch"]
        self.assertEqual(w["bis_complaints"]["last_success_at"], NOW)
        self.assertNotIn("last_success_at", w["bis_ecb"])
        self.assertIn("HTTP 503", w["bis_ecb"]["last_error"])


class BothBinsAreMonitored(unittest.TestCase):
    """546 Saratoga has two BINs on one lot. The rear BIN (3423445) shares no
    job with 3255205, so the job-sharing rule never reached it."""

    def test_the_watch_reads_both_bins_in_every_mode(self):
        for mode in ("shadow", "live"):
            db, emails = _seed(), []
            s = _run(db, _BIS(), mode, emails=emails)
            self.assertEqual(s["lot_bins"], ["3423445"])
            self.assertEqual(sorted(b["bin"] for b in s["bins"]), ["3255205", "3423445"])
            self.assertEqual(sorted(e["bin"] for e in s["ecb"]), ["3255205", "3423445"])

    def test_shadow_does_not_hand_the_rear_bin_to_the_open_data_scan(self):
        """Review finding: saving lot_bins in shadow made the Open Data scan
        store (and post) the rear BIN's records -- shadow must cause nothing."""
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        self.assertNotIn("lot_bins", db.source_sync_state.docs[0]["watch"]["bis_complaints"])

    def test_live_then_the_open_data_scan_reads_the_rear_bin_too(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        asked = []

        async def query(nyc_bin, address="", answered=None):
            asked.append(nyc_bin)
            return []
        fetched = []
        with patch.object(server, "db", db), patch.object(server, "_query_dob_apis", query):
            asyncio.run(server._with_site_bins("p546", "3255205", [], {}, fetched))
        self.assertEqual((asked, fetched), (["3423445"], ["3423445"]))


class DisplayedOnTheComplianceScreen(unittest.TestCase):
    """GET /api/projects/{id}/dob-logs -- what the Compliance screen reads,
    with the screen's own arguments (date_range='all', limit 200)."""

    def test_the_two_complaints_are_in_the_feed_as_open_action_items(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        user = {"id": "u_admin", "_id": "u_admin", "company_id": "co_blueview", "role": "admin"}
        with patch.object(server, "db", db):
            out = asyncio.run(server.get_dob_logs(
                "p546", current_user=user, severity=None, record_type=None, limit=200, skip=0,
                include_seed=False, signal_kinds=None, severity_kind=None, date_range="all",
                unread_only=False, search=None))
        rows = [lg if isinstance(lg, dict) else (lg.model_dump() if hasattr(lg, "model_dump") else lg.dict())
                for lg in out["logs"]]
        by = {lg.get("raw_dob_id"): lg for lg in rows}
        for cn in ("3A88489", "3A88492"):
            self.assertIn(cn, by)
            self.assertEqual((by[cn]["record_type"], by[cn]["severity"]), ("complaint", "Action"))


class RoutedToEmail(unittest.TestCase):
    """The real sender: _send_critical_dob_alert_throttled -> recipients ->
    lib.notifications.send_notification. Only the provider call is stubbed."""

    def _world(self):
        db, emails = _seed(), []
        db.users.docs += [
            {"_id": "u_admin", "company_id": "co_blueview", "role": "admin", "email": "admin@example.test"},
            {"_id": "u_pm", "company_id": "co_blueview", "role": "pm", "email": "pm@example.test",
             "assigned_projects": ["p546"]},
            {"_id": "u_pm2", "company_id": "co_blueview", "role": "pm", "email": "pm2@example.test",
             "assigned_projects": ["p_other"]},
            {"_id": "u_cp", "company_id": "co_blueview", "role": "cp", "email": "cp@example.test",
             "assigned_projects": ["p546"]},
        ]
        return db

    def test_each_complaint_emails_the_admin_and_the_projects_pm_once(self):
        db, sent = self._world(), []

        async def fake_notify(_db, **kw):
            sent.append((kw["recipient"], kw["permit_renewal_id"], kw["subject"], kw["text"]))
            return {"status": "sent"}
        with patch.object(server, "db", db), patch.object(server, "RESEND_API_KEY", "test-key"), \
                patch("lib.notifications.send_notification", fake_notify):
            asyncio.run(server.run_bis_complaint_watch_for_project(
                copy.deepcopy(PROJECT), _BIS(), mode="live", now=NOW))
            asyncio.run(server.run_bis_complaint_watch_for_project(
                copy.deepcopy(PROJECT), _BIS(), mode="live", now=NOW + timedelta(minutes=10)))
        got = sorted((r, eid) for r, eid, _, _ in sent)
        self.assertEqual(got, [("admin@example.test", "dob_log:3A88489"), ("admin@example.test", "dob_log:3A88492"),
                               ("pm@example.test", "dob_log:3A88489"), ("pm@example.test", "dob_log:3A88492")])
        text = next(t for r, eid, _, t in sent if eid == "dob_log:3A88489")
        self.assertIn("NO ROOF PROTECTION", text)
        self.assertIn("A complaint is not a violation", text)


class OffAndShadowCannotSend(unittest.TestCase):
    """The rollout's safety claim, pinned. Every send path is replaced by one
    that FAILS the test if reached: the critical-alert email, the notification
    layer under it (with a Resend key set, so only the mode could stop it), and
    dob_logs writes -- the WhatsApp group tick posts only what dob_logs holds."""

    def _tripwires(self, db):
        def boom(*a, **k):
            raise AssertionError("a send path was reached")

        async def aboom(*a, **k):
            boom()
        return [patch.object(server, "db", db), patch.object(server, "RESEND_API_KEY", "test-key"),
                patch.object(server, "_send_critical_dob_alert", aboom),
                patch("lib.notifications.send_notification", aboom)]

    def test_off_reads_nothing_and_sends_nothing(self):
        db = _seed()
        ps = self._tripwires(db) + [patch.dict(os.environ, {"BIS_COMPLAINT_WATCH_MODE": "off"}),
                                    patch.object(server.httpx, "AsyncClient",
                                                 lambda *a, **k: (_ for _ in ()).throw(AssertionError("BIS read")))]
        for p in ps:
            p.start()
        try:
            asyncio.run(server.bis_complaint_watch_tick())
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(db.complaint_watch_ledger.docs, [])
        self.assertNotIn("watch", db.source_sync_state.docs[0])

    def test_unset_and_garbage_modes_are_off(self):
        for v in (None, "", "on", "true", "1", "shadow-live"):
            env = {} if v is None else {"BIS_COMPLAINT_WATCH_MODE": v}
            with patch.dict(os.environ, env, clear=False):
                if v is None:
                    os.environ.pop("BIS_COMPLAINT_WATCH_MODE", None)
                self.assertEqual(server._bis_watch_mode(), "off", v)

    def test_shadow_reads_bis_but_writes_no_record_and_sends_nothing(self):
        db = _seed()
        before = [dict(d) for d in db.dob_logs.docs]
        ps = self._tripwires(db)
        for p in ps:
            p.start()
        try:
            s = asyncio.run(server.run_bis_complaint_watch_for_project(
                copy.deepcopy(PROJECT), _BIS(), mode="shadow", now=NOW))
        finally:
            for p in reversed(ps):
                p.stop()
        self.assertEqual(db.dob_logs.docs, before)
        self.assertEqual([w for w in db.dob_logs.writes], [])
        self.assertTrue(any(d["status"] == "would_alert" for d in db.complaint_watch_ledger.docs))
        self.assertTrue(s["decisions"])


class ComplianceAndAssistantFreshness(unittest.TestCase):
    """What a person sees about 546 after each mode, with honest freshness."""

    def _dob_status(self, db):
        with patch.object(server, "db", db):
            return asyncio.run(server._handle_dob_status("p546", company_id="co_blueview"))

    # The assistant and the endpoint measure freshness against the real clock,
    # so these passes run at the real time (the BIS pages are still the fixtures).
    def test_live_lists_both_complaints_and_says_bis_was_checked(self):
        db, emails = _seed(), []
        now = datetime.now(timezone.utc)
        _run(db, _BIS(), "live", now=now, emails=emails)
        out = self._dob_status(db)
        self.assertIn("Open DOB complaints (2)", out)
        self.assertIn("3A88489", out)
        self.assertIn("3A88492", out)
        self.assertIn("Checked DOB BIS directly", out)
        with patch.object(server, "db", db):
            f = asyncio.run(server.get_dob_freshness("p546", project=dict(PROJECT)))
        self.assertTrue(f["can_say_no_new_complaints"])
        self.assertEqual(f["sources"][0]["last_success_at"], now.isoformat())

    def test_shadow_never_says_none_was_found(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", now=datetime.now(timezone.utc), emails=emails)
        out = self._dob_status(db)
        self.assertIn("No open DOB complaints on file.", out)
        self.assertIn("trial mode", out)
        self.assertNotIn("Checked DOB BIS directly", out)


class ReviewFindings(unittest.TestCase):
    """Defects an independent review found on this branch, each pinned."""

    def test_a_stored_naive_detected_at_does_not_crash_the_pass(self):
        # Motor returns naive datetimes; BIS received times are aware.
        from lib import complaint_watch as cw2
        rec = {"complaint_number": "3A88489", "bin": "3255205", "status": "ACTIVE", "category": "8A",
               "received_at": "2026-11-10T11:22:00-05:00", "disposition_code": "A3"}
        d = cw2.alert_decision(rec, project_bins={"3255205"}, first_sync=False, already_alerted=False,
                               now=NOW, first_seen_at=datetime(2026, 11, 10, 16, 30))
        self.assertEqual((d["alert"], d["event"], d["priority"]), (True, "stop_work_order", "critical"))

    def _july_morning(self):
        """3A70077 as LeveLog held it on 2026-07-07 before the inspection:
        ACTIVE, no disposition, detected_at naive as Mongo returns it. The BIS
        pages are the real ones, which show it RESOLVED with L1 (partial SWO)."""
        db = _seed()
        row = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A70077")
        row.update(current_status="ACTIVE", complaint_status="ACTIVE", disposition_code=None,
                   detected_at=datetime(2026, 7, 7, 13, 0), status_history=[])
        db.source_sync_state.docs[0]["watch"] = {"bis_complaints": {"bins_first_synced": ["3255205", "3423445"]}}
        return db, row

    def test_a_stop_work_disposition_on_a_stored_complaint_emails_once_as_swo(self):
        db, row = self._july_morning()
        emails = []
        s = _run(db, _BIS(), "live", emails=emails)
        self.assertTrue(s["ecb"], "the pass must reach the ECB half (no crash on the naive date)")
        self.assertEqual([e for e in emails if e[0] == "3A70077"], [("3A70077", "bis", "swo")])
        self.assertEqual((row["disposition_code"], row["current_status"], row["complaint_status"]), ("L1", "CLOSED", "CLOSED"))
        self.assertTrue(row.get("order_issued_at") or row.get("order_issued"), row.keys())
        emails.clear()
        _run(db, _BIS(), "live", now=NOW + timedelta(minutes=10), emails=emails)
        self.assertEqual([e for e in emails if e[0] == "3A70077"], [])

    def test_the_next_day_open_data_refresh_does_not_email_the_order_again(self):
        from lib import dob_alert_gate
        db, row = self._july_morning()
        _run(db, _BIS(), "live", emails=[])
        open_data_after = dict(row, current_status="CLOSED", disposition_code="L1")
        self.assertIsNone(dob_alert_gate.update_issues_order(row, open_data_after))

    def test_a_property_page_failure_is_an_error_and_the_saved_rear_bin_still_reads(self):
        db, emails = _seed(), []
        db.source_sync_state.docs[0]["watch"] = {"bis_complaints": {"lot_bins": ["3423445"]}}

        class _ProfileDown(_BIS):
            async def get(self, url, **kw):
                if "PropertyProfileOverviewServlet" in url:
                    self.urls.append(url)
                    return _Resp(503, "down")
                return await super().get(url, **kw)
        s = _run(db, _ProfileDown(), "shadow", emails=emails)
        self.assertIn("3423445", [b["bin"] for b in s["bins"]])
        w = db.source_sync_state.docs[0]["watch"]["bis_complaints"]
        self.assertNotIn("last_success_at", w)
        self.assertIn("property profile: HTTP 503", w["last_error"])

    def test_a_deleted_complaint_is_not_reinserted_or_realerted(self):
        db, emails = _seed(), []
        db.dob_logs.docs.append({"_id": "gone", "project_id": "p546", "record_type": "complaint",
                                 "raw_dob_id": "3A88489", "current_status": "ACTIVE", "is_deleted": True})
        _run(db, _BIS(), "live", emails=emails)
        self.assertEqual(len([d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489"]), 1)
        self.assertNotIn("3A88489", [e[0] for e in emails])

    def test_an_email_already_sent_by_the_open_data_path_is_not_sent_again(self):
        db, emails = _seed(), []
        db.system_config.docs.append({"key": "dob_alert_sent:p546:3A88489:new", "sent_at": NOW})
        _run(db, _BIS(), "live", emails=emails)
        self.assertNotIn("3A88489", [e[0] for e in emails])
        self.assertIn("3A88492", [e[0] for e in emails])


class TheCardReadsDobsOwnWords(unittest.TestCase):
    def test_bis_rows_carry_the_summary_the_compliance_card_shows(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "live", emails=emails)
        row = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "3A88489")
        self.assertEqual(row["ai_summary"],
                         "DOB complaint 3A88489 (8A Construction Safety Compliance (CSC) Action) received on "
                         "Nov 10, 11:22 AM: NO ROOF PROTECTION, NO WINDOW PROTECTION NO DOCS. Not inspected yet.")
        ecb = next(d for d in db.dob_logs.docs if d["raw_dob_id"] == "39556260N")
        self.assertIn("ECB/OATH summons 39556260N (Class - 2), issued 2026-07-07", ecb["ai_summary"])


class ShadowWritesNothingAnyOtherJobReads(unittest.TestCase):
    """No scheduled job can act on shadow's output if shadow writes nothing any
    other job reads. Both halves pinned: a census of everything a shadow pass
    writes, and a census of every reader of what it may write."""

    def test_a_shadow_pass_writes_only_its_ledger_and_its_own_watch_state(self):
        db, emails = _seed(), []
        _run(db, _BIS(), "shadow", emails=emails)
        wrote = {name: c for name, c in db._c.items() if c.writes or c.__dict__.get("updates")}
        self.assertEqual(sorted(wrote), ["complaint_watch_ledger", "source_sync_state"])
        self.assertTrue(all(w[0] == "insert" for w in db.complaint_watch_ledger.writes))
        keys = {k for u in db.source_sync_state.updates for op in u.values() for k in op}
        self.assertTrue(all(k == "company_id" or k.startswith("watch.") for k in keys), keys)
        self.assertNotIn("watch.bis_complaints.lot_bins", keys)
        self.assertEqual(emails, [])

    def test_nothing_but_the_watch_reads_what_shadow_writes(self):
        """Every reader of complaint_watch_ledger and of source_sync_state.watch
        in the backend. lot_bins (read by the Open Data scan) is written only
        in live -- pinned above."""
        import re as _re
        backend = Path(server.__file__).parent
        readers = {}
        for f in [backend / "server.py", *sorted((backend / "lib").glob("*.py"))]:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _re.search(r'COMPLAINT_WATCH_LEDGER\]|complaint_watch_ledger|get\("watch"\)', line) \
                        and "insert_one" not in line and "delete_one" not in line \
                        and not line.lstrip().startswith("#"):
                    readers.setdefault(f.name, []).append(line.strip()[:70])
        joined = "\n".join(f"{k}: {v}" for k, vs in readers.items() for v in vs)
        self.assertEqual(sorted(readers), ["complaint_watch.py", "server.py"], joined)
        # In server.py: the watch's own reads + the Open Data scan's lot_bins read.
        srv = readers["server.py"]
        self.assertTrue(all(("find_one" in r) or ("COMPLAINT_WATCH_LEDGER =" in r) or ("lot_bins" in r)
                            or ("bis_ecb" in r) or ("bis_complaints" in r) for r in srv), joined)


class EverySourceReportsItsOwnState(unittest.TestCase):
    """546's real source_sync_state shape (production probe 2026-11-10), plus
    the per-dataset rows: one failing dataset shows as itself."""

    def test_each_source_and_dataset_has_its_own_status(self):
        from lib import complaint_watch as cw2
        now = NOW
        ok = now - timedelta(minutes=10)
        state = {"sources": {s: {"synced_at": ok} for s in (
                    "dot_oath", "dot_permits", "dob_cofo", "dob_complaints", "dob_job_filings",
                    "dob_permits", "dob_boiler", "dob_elevator", "dob_violations")},
                 "datasets": {"6bgk-3dad": {"synced_at": ok}, "855j-jady": {"synced_at": ok},
                              "3h2n-5cm9": {"synced_at": ok},
                              "3usq-5cid": {"last_error_at": ok},
                              "xubg-57si": {"synced_at": now - timedelta(hours=3)}},
                 "watch": {"bis_complaints": {"last_success_at": ok, "last_attempt_at": ok, "mode": "live"},
                           "bis_ecb": {"last_attempt_at": ok, "last_error": "BIN 3255205: HTTP 503",
                                       "mode": "live"}}}
        f = cw2.freshness(state, now=now)
        by = {r["source"]: r for r in f["sources"]}
        self.assertEqual(by["bis_complaints"]["status"], "fresh")
        self.assertEqual((by["bis_ecb"]["status"], by["bis_ecb"]["last_error"]), ("failing", "BIN 3255205: HTTP 503"))
        self.assertEqual(by["dob_violations"]["status"], "partial")
        self.assertIn("3usq-5cid", by["dob_violations"]["last_error"])
        self.assertEqual(by["dataset:3usq-5cid"]["status"], "failing")
        self.assertEqual(by["dataset:6bgk-3dad"]["status"], "fresh")
        self.assertEqual(by["dataset:xubg-57si"]["status"], "stale")
        for s in ("dob_complaints", "dob_permits", "dob_job_filings", "dob_cofo", "dob_boiler",
                  "dob_elevator", "dot_oath", "dot_permits"):
            self.assertEqual(by[s]["status"], "fresh", s)
        self.assertTrue(f["can_say_no_new_complaints"])
        self.assertFalse(f["can_say_no_new_summonses"])
