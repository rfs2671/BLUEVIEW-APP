"""DOB/DOT status refresh + status_history (2026 audit).

DEFECT MEASURED. run_dob_sync_for_project treated every NON-permit record as
insert-once, so its status was a first-sight snapshot: a rescinded Stop Work
Order stayed 'open', a resolved/dismissed violation 'active'. Progress reports
sent to owners/lenders need the regulatory status AS IT WAS on a date, so every
dob_logs / dot_logs row now carries `status_history`
[{status, at, source: first_seen|sync|legacy_first_refresh}], non-permit rows are
refreshed IN PLACE, and a LEGACY row's first refresh is silent
(is_seed_transition) so deploying this cannot storm customers (cf. the
2026-05-03 duplicate-email incident).

NEGATIVE CONTROLS (what goes red if the fix is reverted) are noted per test.
These tests drive the REAL run_dob_sync_for_project / _ingest_311_for_project /
_dot_store / _query_dob_apis against an in-memory db; only the network (the
record list, the HTTP client) and the alert sender are replaced.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

import server  # noqa: E402
from lib import dot_sync, status_history as sh, wa_alerts  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── a db that honours the two things the sync relies on ──────────────────────

class _Cur(__import__("tests.async_fake_mongo", fromlist=["_Cursor"])._Cursor):
    async def to_list(self, n=None, length=None):
        return await super().to_list(n)


class _Col(AsyncFakeCollection):
    """AsyncFakeCollection + find_one(sort=detected_at desc) + delete_many
    + to_list(length=)."""

    def find(self, flt=None, projection=None, **kw):
        return _Cur(super().find(flt, projection)._docs)

    async def find_one(self, flt=None, projection=None, sort=None, **kw):
        import copy
        from tests.async_fake_mongo import matches
        hits = [d for d in self.docs if matches(d, flt)]
        if sort and hits:
            (key, direction), = sort[:1]
            hits.sort(key=lambda d: d.get(key) or datetime.min, reverse=direction < 0)
        return copy.deepcopy(hits[0]) if hits else None

    async def delete_many(self, flt=None, **kw):
        from tests.async_fake_mongo import matches
        keep = [d for d in self.docs if not matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return type("R", (), {"deleted_count": n})()


class _DB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Col(name)
        return self._c[name]


BIN = "1234567"


def _project(pid="p1", company="c1", **kw):
    return {"_id": pid, "company_id": company, "nyc_bin": BIN,
            "address": "100 Main St, Brooklyn, NY", **kw}


def _swo_rec(num="SWO1", status="Active", **kw):
    r = {"_id_field": "stop_work_order_number", "stop_work_order_number": num,
         "_record_type": "swo", "_dataset": "3usq-5cid", "bin": BIN,
         "status": status, "issue_date": "2026-10-01T00:00:00.000",
         "description": "Full Stop Work Order"}
    r.update(kw)
    return r


def _viol_rec(isn="555", category="V*-DOB VIOLATION - ACTIVE", **kw):
    r = {"_id_field": "isn_dob_bis_viol", "isn_dob_bis_viol": isn,
         "_record_type": "violation", "_dataset": "3h2n-5cm9", "bin": BIN,
         "number": f"V{isn}", "violation_category": category,
         "issue_date": "20261001", "description": "Work without permit"}
    r.update(kw)
    return r


def _permit_rec(filing="B001-I1", status="ISSUED"):
    return {"_id_field": "job_filing_number", "job_filing_number": filing,
            "_collapsed_permit_id": filing, "_record_type": "permit",
            "_dataset": "rbx6-tga4", "bin": BIN, "permit_status": status,
            "work_type": "GC", "expired_date": "2030-01-01T00:00:00.000"}


class _Sync:
    """One db + a driver for run_dob_sync_for_project."""

    def __init__(self):
        self.db = _DB()
        self.alert = AsyncMock(return_value=True)

    def sync(self, project, records):
        recs = [dict(r) for r in records]
        with patch.object(server, "db", self.db), \
                patch.object(server, "_query_dob_apis", AsyncMock(return_value=recs)), \
                patch.object(server, "_send_critical_dob_alert_throttled", self.alert):
            return _run(server.run_dob_sync_for_project(project))

    def rows(self, pid=None, rt=None):
        return [d for d in self.db.dob_logs.docs
                if (pid is None or d["project_id"] == pid)
                and (rt is None or d["record_type"] == rt)]

    def seed_legacy(self, **row):
        """A row written BEFORE status_history existed."""
        base = {"project_id": "p1", "company_id": "c1", "nyc_bin": BIN,
                "is_deleted": False, "is_seed_transition": False,
                "detected_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "read_by_user": []}
        base.update(row)
        _run(self.db.dob_logs.insert_one(base))
        return base


def _hist(row):
    return [(e["status"], e["source"]) for e in row["status_history"]]


# ═══ non-permit rows are refreshed in place ══════════════════════════════════

class TestSwoRescindedRefresh(unittest.TestCase):
    def test_rescinded_swo_becomes_closed_in_place_with_history(self):
        """NEGATIVE CONTROL: restore the old `raw_id in existing_ids: continue`
        and the second sync leaves status ACTIVE / severity Action /
        stop_work_full forever (every assertion below fails)."""
        s = _Sync()
        s.sync(_project(), [_swo_rec(status="Active")])
        first = s.rows()[0]
        self.assertEqual(first["current_status"], "ACTIVE")
        self.assertEqual(first["severity"], "Action")
        self.assertEqual(first["signal_kind"], "stop_work_full")
        self.assertEqual(_hist(first), [("ACTIVE", "first_seen")])
        self.assertEqual(first["status_history"][0]["at"], first["detected_at"])
        s.alert.reset_mock()                  # the first sighting may alert (unchanged rule)

        s.sync(_project(), [_swo_rec(status="Rescinded")])
        rows = s.rows()
        self.assertEqual(len(rows), 1, "one row per record - no new row for a SWO")
        r = rows[0]
        self.assertEqual(r["_id"], first["_id"])
        self.assertEqual(r["current_status"], "RESCINDED")
        self.assertEqual(r["previous_status"], "ACTIVE")
        self.assertEqual(r["status"], "Rescinded")
        self.assertEqual(r["resolution_state"], "resolved")
        self.assertEqual(r["severity"], "Good", "a rescinded SWO is not Action")
        self.assertEqual(r["signal_kind"], "violation_resolved")
        self.assertFalse(r["is_seed_transition"])
        self.assertEqual(r["status_changed_at"], r["status_history"][-1]["at"])
        self.assertEqual(_hist(r), [("ACTIVE", "first_seen"), ("RESCINDED", "sync")])
        self.assertLessEqual(r["status_history"][0]["at"], r["status_history"][1]["at"])
        s.alert.assert_not_awaited()          # closed outcome never emails

    def test_swo_rescinded_alert_fires_for_refreshed_row_but_not_a_seed(self):
        """The GC `swo_rescinded` alert is previous_status based: it can now
        fire for a refreshed row, and stays silent for a legacy seed.
        NEGATIVE CONTROL: without is_seed_transition on the legacy refresh the
        second collect() would return a swo_rescinded item (a storm)."""
        today = date(2026, 10, 19)
        s = _Sync()
        s.sync(_project(), [_swo_rec(status="Active")])
        s.sync(_project(), [_swo_rec(status="Rescinded")])
        kinds = [i["kind"] for i in wa_alerts.collect(s.rows(), [], today)]
        self.assertEqual(kinds, ["swo_rescinded"])

        s2 = _Sync()
        s2.seed_legacy(record_type="swo", raw_dob_id="SWO1", severity="Action",
                       stop_work_order_number="SWO1", status="Active",
                       current_status="ACTIVE", violation_subtype="SWO_FULL")
        s2.sync(_project(), [_swo_rec(status="Rescinded")])
        r = s2.rows()[0]
        self.assertTrue(r["is_seed_transition"])
        self.assertEqual(r["severity"], "Good")
        self.assertEqual([i["kind"] for i in wa_alerts.collect(s2.rows(), [], today)], [])


class TestViolationResolvedRefresh(unittest.TestCase):
    def test_bis_violation_resolved(self):
        """BIS writes its state into violation_category ('... - RESOLVE').
        NEGATIVE CONTROL: insert-once keeps severity Action / state open."""
        s = _Sync()
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - ACTIVE")])
        self.assertEqual(s.rows()[0]["resolution_state"], "open")
        self.assertEqual(s.rows()[0]["severity"], "Action")
        s.alert.reset_mock()
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - RESOLVE")])
        (r,) = s.rows()
        self.assertEqual(r["resolution_state"], "resolved")
        self.assertEqual(r["severity"], "Good")
        self.assertEqual(r["signal_kind"], "violation_resolved")
        self.assertEqual(r["previous_status"], "V*-DOB VIOLATION - ACTIVE")
        self.assertEqual([x[1] for x in _hist(r)], ["first_seen", "sync"])
        s.alert.assert_not_awaited()

    def test_dob_now_violation_status_resolved_is_good(self):
        """855j-jady keeps its state in `violation_status`; the old severity
        never read it, so 'Resolved' / 'Disputed Successfully' stayed Action.
        NEGATIVE CONTROL: drop the resolution_state check in
        _determine_severity -> severity stays 'Action'."""
        for text in ("Resolved", "Disputed Successfully", "Cured"):
            with self.subTest(text):
                s = _Sync()
                rec = {"_id_field": "violation_number", "violation_number": "VIO-1",
                       "_record_type": "violation", "_dataset": "855j-jady",
                       "bin": BIN, "violation_issue_date": "2026-01-08"}
                s.sync(_project(), [dict(rec, violation_status="Active")])
                self.assertEqual(s.rows()[0]["severity"], "Action")
                s.sync(_project(), [dict(rec, violation_status=text)])
                self.assertEqual(s.rows()[0]["severity"], "Good")
                self.assertIn(s.rows()[0]["resolution_state"], ("resolved",))

    def test_unchanged_record_writes_nothing_and_keeps_history_length(self):
        """No status change and no field change -> no write at all (a 2h sync
        must not amplify writes). NEGATIVE CONTROL: an unconditional update
        would add an ('update', id) entry here."""
        s = _Sync()
        s.sync(_project(), [_viol_rec()])
        before = len(s.db.dob_logs.writes)
        s.sync(_project(), [_viol_rec()])
        self.assertEqual(len(s.db.dob_logs.writes), before)
        self.assertEqual(len(s.rows()[0]["status_history"]), 1)

    def test_field_refresh_without_status_change_is_silent(self):
        """Hearing/penalty fields refresh even if the status text did not
        move; no history entry, no alert."""
        s = _Sync()
        s.sync(_project(), [_viol_rec()])
        s.alert.reset_mock()
        s.sync(_project(), [_viol_rec(penalty_applied="1000", disposition_comments="HEARING SET")])
        (r,) = s.rows()
        self.assertEqual(r["penalty_amount"], "1000")
        self.assertEqual(r["disposition_comments"], "HEARING SET")
        self.assertEqual(len(r["status_history"]), 1)
        s.alert.assert_not_awaited()

    def test_other_non_permit_types_refresh(self):
        """job_status / cofo / complaint refresh through the same path."""
        s = _Sync()
        job = {"_id_field": "job_filing_number", "job_filing_number": "B9-I1",
               "_record_type": "job_status", "_dataset": "w9ak-ipjd", "bin": BIN}
        cofo = {"_id_field": "c_of_o_number", "c_of_o_number": "CO1",
                "_record_type": "cofo", "_dataset": "pkdm-hqz6", "bin": BIN}
        s.sync(_project(), [dict(job, filing_status="Pending"), dict(cofo, c_of_o_status="Temporary")])
        s.sync(_project(), [dict(job, filing_status="Approved"), dict(cofo, c_of_o_status="CO Issued")])
        by = {r["record_type"]: r for r in s.rows()}
        self.assertEqual(len(s.rows()), 2)
        self.assertEqual(by["job_status"]["current_status"], "APPROVED")
        self.assertEqual(by["job_status"]["signal_kind"], "filing_approved")
        self.assertEqual(by["cofo"]["current_status"], "CO ISSUED")
        self.assertEqual(_hist(by["cofo"]), [("TEMPORARY", "first_seen"), ("CO ISSUED", "sync")])


# ═══ alert safety ════════════════════════════════════════════════════════════

class TestLegacyFirstRefreshIsSilent(unittest.TestCase):
    def _legacy_violation(self, s):
        return s.seed_legacy(
            record_type="violation", raw_dob_id="555", severity="Action",
            violation_number="V555", status="V*-DOB VIOLATION - ACTIVE",
            current_status="V*-DOB VIOLATION - ACTIVE", resolution_state="open")

    def test_legacy_change_to_action_does_not_alert_then_genuine_change_does(self):
        """The migration-day rule. NEGATIVE CONTROL: if the legacy branch were
        not marked `legacy`, the first assert_not_awaited fails (the 2026-05-03
        storm); if genuine changes were silenced too, the later assert_awaited
        fails."""
        s = _Sync()
        self._legacy_violation(s)
        # ACTIVE -> HEARING: still Action severity, i.e. WOULD alert if genuine.
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - HEARING")])
        (r,) = s.rows()
        self.assertEqual(r["severity"], "Action")
        self.assertTrue(r["is_seed_transition"])
        self.assertEqual(r["previous_status"], "V*-DOB VIOLATION - ACTIVE")
        self.assertEqual(
            _hist(r), [("V*-DOB VIOLATION - ACTIVE", "first_seen"),
                       ("V*-DOB VIOLATION - HEARING", "legacy_first_refresh")])
        self.assertEqual(r["status_history"][0]["at"], datetime(2026, 3, 1, tzinfo=timezone.utc))
        s.alert.assert_not_awaited()

        # a LATER genuine change to Action severity alerts, once, through the
        # throttled wrapper, and un-seeds the row.
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - PENALTY")])
        (r,) = s.rows()
        self.assertFalse(r["is_seed_transition"])
        self.assertEqual([x[1] for x in _hist(r)], ["first_seen", "legacy_first_refresh", "sync"])
        s.alert.assert_awaited_once()
        sent_project, sent_log = s.alert.await_args.args
        self.assertEqual(sent_project["_id"], "p1")
        self.assertEqual(sent_log["raw_dob_id"], "555")
        self.assertEqual(sent_log["current_status"], "V*-DOB VIOLATION - PENALTY")
        self.assertEqual(s.alert.await_args.kwargs["source"], "dob")

    def test_legacy_unchanged_status_only_gains_history(self):
        s = _Sync()
        self._legacy_violation(s)
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - ACTIVE")])
        (r,) = s.rows()
        self.assertEqual(_hist(r), [("V*-DOB VIOLATION - ACTIVE", "first_seen")])
        self.assertFalse(r["is_seed_transition"], "no change -> flag untouched")
        s.alert.assert_not_awaited()

    def test_pre_mr14_row_without_current_status_is_also_seed(self):
        s = _Sync()
        s.seed_legacy(record_type="violation", raw_dob_id="555", severity="Action")
        s.sync(_project(), [_viol_rec(category="V*-DOB VIOLATION - HEARING")])
        (r,) = s.rows()
        self.assertTrue(r["is_seed_transition"])
        self.assertEqual(_hist(r)[0], (None, "first_seen"))
        s.alert.assert_not_awaited()

    def test_genuine_change_goes_through_real_throttled_path(self):
        """Through the REAL _send_critical_dob_alert_throttled: initial-scan
        suppression still applies to the refresh path, and once the scan is
        done a genuine change emails exactly once."""
        for scan_done, expect in ((False, 0), (True, 1)):
            with self.subTest(initial_scan_done=scan_done):
                s = _Sync()
                s.sync(_project(), [_viol_rec()])     # history present from here on
                sender = AsyncMock()
                with patch.object(server, "db", s.db), \
                        patch.object(server, "_query_dob_apis", AsyncMock(
                            return_value=[_viol_rec(category="V*-DOB VIOLATION - HEARING")])), \
                        patch.object(server, "_initial_scan_done", AsyncMock(return_value=scan_done)), \
                        patch.object(server, "_dob_alert_recently_sent", AsyncMock(return_value=False)), \
                        patch.object(server, "_mark_dob_alert_sent", AsyncMock()), \
                        patch.object(server, "_send_critical_dob_alert", sender):
                    _run(server.run_dob_sync_for_project(_project()))
                    _run(server.run_dob_sync_for_project(_project()))   # no further change
                self.assertEqual(sender.await_count, expect)

    def test_rescinded_closed_outcomes_never_alert(self):
        s = _Sync()
        s.sync(_project(), [_swo_rec(status="Active")])
        s.alert.reset_mock()
        s.sync(_project(), [_swo_rec(status="Lifted")])
        s.alert.assert_not_awaited()
        self.assertEqual(s.rows()[0]["severity"], "Good")


# ═══ project scoping ═════════════════════════════════════════════════════════

class TestProjectScoping(unittest.TestCase):
    def test_two_projects_on_one_bin_each_get_rows(self):
        """DEFECT: the diff lookup was `{"raw_dob_id": raw_id}` - not scoped
        by project - so project B found A's permit row, took the 'unchanged'
        branch and got NO row. NEGATIVE CONTROL: remove "project_id" from the
        find_one filter -> project p2 has 0 permit rows."""
        s = _Sync()
        recs = [_permit_rec(), _viol_rec(), _swo_rec()]
        s.sync(_project("p1"), recs)
        s.sync(_project("p2"), recs)
        for pid in ("p1", "p2"):
            self.assertEqual(sorted(r["record_type"] for r in s.rows(pid)),
                             ["permit", "swo", "violation"], pid)
        # a status change for p2 refreshes p2's rows only
        s.sync(_project("p2"), [_swo_rec(status="Rescinded"), _permit_rec(status="EXPIRED")])
        self.assertEqual(s.rows("p1", "swo")[0]["current_status"], "ACTIVE")
        self.assertEqual(s.rows("p2", "swo")[0]["current_status"], "RESCINDED")
        self.assertEqual([r["current_status"] for r in s.rows("p1", "permit")], ["ISSUED"])
        self.assertEqual(len(s.rows("p2", "permit")), 2)     # permit timeline = new row

    def test_311_two_projects_same_bbl(self):
        """Same defect on the 311 path. NEGATIVE CONTROL: unscoped lookup ->
        p2 gets no 311 row."""
        db = _DB()
        rec = {"unique_key": "999", "complaint_type": "Construction",
               "descriptor": "Noise", "status": "Open",
               "created_date": "2026-10-01T10:00:00.000", "agency": "DOB"}
        fetch = AsyncMock(return_value=[rec])
        with patch.object(server, "db", db), \
                patch.object(server, "_fetch_311_for_project", fetch), \
                patch.object(server, "_send_critical_dob_alert_throttled", AsyncMock()), \
                patch.object(server, "_initial_scan_done", AsyncMock(return_value=False)):
            for pid in ("p1", "p2"):
                _run(server._ingest_311_for_project(
                    {"_id": pid, "company_id": "c1", "nyc_bin": BIN, "bbl": "3000010001",
                     "address": "100 Main St"}, None))
        pids = sorted(d["project_id"] for d in db.dob_logs.docs)
        self.assertEqual(pids, ["p1", "p2"])
        for d in db.dob_logs.docs:
            self.assertEqual(_hist(d), [("OPEN", "first_seen")])


# ═══ permits / 311 keep the new-row timeline, with history ═══════════════════

class TestPermitTimelineCarriesHistory(unittest.TestCase):
    def test_permit_rows_form_timeline_and_carry_history(self):
        s = _Sync()
        s.sync(_project(), [_permit_rec(status="ISSUED")])
        s.sync(_project(), [_permit_rec(status="EXPIRED")])
        rows = sorted(s.rows(rt="permit"), key=lambda r: r["detected_at"])
        self.assertEqual(len(rows), 2, "permits keep new-row-per-change")
        self.assertEqual(_hist(rows[0]), [("ISSUED", "first_seen")])
        self.assertEqual(_hist(rows[1]), [("ISSUED", "first_seen"), ("EXPIRED", "sync")])
        self.assertEqual(rows[1]["previous_status"], "ISSUED")
        self.assertFalse(rows[1]["is_seed_transition"])

    def test_legacy_permit_change_is_a_real_event_not_a_seed(self):
        """Permit rows were refreshed on every sync, so a legacy permit's
        change is genuine: history is synthesised, source is 'sync', and the
        pre-existing is_seed rule (current_status key present -> not seed)
        is unchanged."""
        s = _Sync()
        s.seed_legacy(record_type="permit", raw_dob_id="permit:B001-I1",
                      current_status="ISSUED", permit_status="ISSUED", severity="Good")
        s.sync(_project(), [_permit_rec(status="EXPIRED")])
        new = max(s.rows(rt="permit"), key=lambda r: r["detected_at"])
        self.assertEqual(_hist(new), [("ISSUED", "first_seen"), ("EXPIRED", "sync")])
        self.assertFalse(new["is_seed_transition"])

    def test_legacy_permit_unchanged_gains_history(self):
        s = _Sync()
        s.seed_legacy(record_type="permit", raw_dob_id="permit:B001-I1",
                      current_status="ISSUED", permit_status="ISSUED", severity="Good")
        s.sync(_project(), [_permit_rec(status="ISSUED")])
        (r,) = s.rows(rt="permit")
        self.assertEqual(_hist(r), [("ISSUED", "first_seen")])

    def test_311_status_change_new_row_carries_history(self):
        db = _DB()
        base = {"unique_key": "7", "complaint_type": "Construction", "status": "Open",
                "created_date": "2026-10-01T10:00:00.000"}
        proj = {"_id": "p1", "company_id": "c1", "nyc_bin": BIN, "bbl": "3000010001",
                "address": "100 Main St"}
        for status in ("Open", "Closed"):
            with patch.object(server, "db", db), \
                    patch.object(server, "_fetch_311_for_project",
                                 AsyncMock(return_value=[dict(base, status=status)])), \
                    patch.object(server, "_send_critical_dob_alert_throttled", AsyncMock()), \
                    patch.object(server, "_initial_scan_done", AsyncMock(return_value=False)):
                _run(server._ingest_311_for_project(proj, None))
        rows = sorted(db.dob_logs.docs, key=lambda d: d["detected_at"])
        self.assertEqual(_hist(rows[-1]), [("OPEN", "first_seen"), ("CLOSED", "sync")])


# ═══ query correctness ═══════════════════════════════════════════════════════

class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else []

    def json(self):
        return self._body


class _FakeClient:
    """Captures every request; `script(url, params)` supplies the response."""
    calls: list = []
    script = staticmethod(lambda url, params: _Resp(200, []))

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, **k):
        _FakeClient.calls.append((url, dict(params or {})))
        return _FakeClient.script(url, dict(params or {}))


def _query(script=None, bin_=BIN, address="100 Main St, Brooklyn, NY"):
    _FakeClient.calls = []
    _FakeClient.script = staticmethod(script or (lambda u, p: _Resp(200, [])))
    with patch.object(server, "ServerHttpClient", _FakeClient):
        out = _run(server._query_dob_apis(bin_, address, {}))
    return out, list(_FakeClient.calls)


class TestQueryBuilding(unittest.TestCase):
    def test_every_endpoint_is_ordered_newest_first(self):
        """DEFECT: 855j-jady, 3h2n-5cm9, w9ak-ipjd (and others) used
        `$limit 50` with NO `$order`, so on a busy building the NEWEST rows
        could be the ones left out. NEGATIVE CONTROL: remove an `$order` ->
        that endpoint is listed in the failure."""
        _, calls = _query()
        self.assertGreater(len(calls), 15)
        unordered = [u for u, p in calls if "$order" not in p]
        self.assertEqual(unordered, [])
        by = {}
        for u, p in calls:
            by.setdefault(u.rsplit("/", 1)[-1].replace(".json", ""), []).append(p)
        for ds, order in (("855j-jady", "violation_issue_date DESC"),
                          ("3h2n-5cm9", "issue_date DESC"),
                          ("w9ak-ipjd", "filing_date DESC"),
                          ("eabe-havv", "date_entered DESC"),
                          ("6bgk-3dad", "issue_date DESC")):
            for p in by[ds]:
                self.assertEqual(p["$order"], order, ds)
        for ds in ("855j-jady", "3h2n-5cm9", "eabe-havv", "6bgk-3dad"):
            for p in by[ds]:
                self.assertEqual(p["$limit"], "250", ds)
        for ds in ("w9ak-ipjd", "3usq-5cid", "xubg-57si", "52dp-yji6"):
            for p in by[ds]:
                self.assertEqual(p["$limit"], "100", ds)

    def test_common_case_is_one_request_per_endpoint(self):
        _, calls = _query()
        self.assertFalse([p for _, p in calls if "$offset" in p])

    def test_full_first_page_fetches_one_more_page_capped(self):
        def script(url, params):
            if "855j-jady" in url and params.get("bin"):
                n = int(params["$limit"])
                off = int(params.get("$offset", 0))
                return _Resp(200, [{"violation_number": f"V{off + i}"} for i in range(n)])
            return _Resp(200, [])
        out, calls = _query(script)
        pages = [p for u, p in calls if "855j-jady" in u and p.get("bin")]
        self.assertEqual([p.get("$offset") for p in pages], [None, "250"])  # capped at 2
        self.assertEqual(len([r for r in out if r["_record_type"] == "violation"]), 500)

    def test_failed_second_page_is_not_a_full_sync(self):
        def script(url, params):
            if "855j-jady" in url and params.get("bin"):
                if params.get("$offset"):
                    return _Resp(500)
                return _Resp(200, [{"violation_number": f"V{i}"} for i in range(250)])
            return _Resp(200, [])
        answered = {}
        _FakeClient.calls = []
        _FakeClient.script = staticmethod(script)
        with patch.object(server, "ServerHttpClient", _FakeClient):
            _run(server._query_dob_apis(BIN, "100 Main St, Brooklyn, NY", answered))
        self.assertFalse(answered["violation"])

    def test_rejected_order_column_retries_unordered(self):
        """A wrong $order column 400s the whole request (the pkdm-hqz6
        incident). The ordered request is retried ONCE without it."""
        def script(url, params):
            if "w9ak-ipjd" in url and "$order" in params:
                return _Resp(400)
            if "w9ak-ipjd" in url:
                return _Resp(200, [{"job_filing_number": "B1"}])
            return _Resp(200, [])
        out, calls = _query(script)
        jobs = [p for u, p in calls if "w9ak-ipjd" in u and p.get("bin")]
        self.assertEqual(["$order" in p for p in jobs], [True, False])
        self.assertEqual([r["job_filing_number"] for r in out if r["_record_type"] == "job_status"], ["B1"])

    def test_dot_permit_query_is_ordered(self):
        pk = dot_sync.project_keys({"address": "588 Thomas S Boyland St, Brooklyn, NY"})
        qs = dot_sync.queries(pk)
        self.assertTrue(qs)
        for q in qs:
            self.assertIn("$order", q["params"], q["dataset"])


# ═══ DOT history ═════════════════════════════════════════════════════════════

class TestDotHistory(unittest.TestCase):
    def _store(self, db, status, now):
        log = {"record_type": "dot_violation", "raw_id": "oath:1", "number": "1",
               "status": status}
        with patch.object(server, "db", db):
            return _run(server._dot_store("p1", "c1", dict(log), "bbl", now))

    def test_new_changed_same(self):
        db = _DB()
        t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
        t1, t2 = t0 + timedelta(hours=2), t0 + timedelta(hours=4)
        self.assertEqual(self._store(db, "Hearing Scheduled", t0), "new")
        self.assertEqual(self._store(db, "Hearing Scheduled", t1), "same")
        self.assertEqual(self._store(db, "Hearing Held", t2), "changed")
        (r,) = db.dot_logs.docs
        self.assertEqual(r["status_history"], [
            {"status": "HEARING SCHEDULED", "at": t0, "source": "first_seen"},
            {"status": "HEARING HELD", "at": t2, "source": "sync"}])
        self.assertEqual(r["previous_status"], "Hearing Scheduled")
        self.assertEqual(r["status_changed_at"], t2)

    def test_legacy_dot_row(self):
        db = _DB()
        t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        _run(db.dot_logs.insert_one({"project_id": "p1", "raw_id": "oath:1",
                                     "status": "Hearing Scheduled", "detected_at": t0}))
        self.assertEqual(self._store(db, "Hearing Held", now), "changed")
        (r,) = db.dot_logs.docs
        self.assertEqual(r["status_history"], [
            {"status": "Hearing Scheduled", "at": t0, "source": "first_seen"},
            {"status": "HEARING HELD", "at": now, "source": "legacy_first_refresh"}])

    def test_legacy_dot_row_unchanged_gets_first_seen_only(self):
        db = _DB()
        t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
        _run(db.dot_logs.insert_one({"project_id": "p1", "raw_id": "oath:1",
                                     "status": "Hearing Scheduled", "detected_at": t0}))
        self.assertEqual(self._store(db, "Hearing Scheduled", t0 + timedelta(days=1)), "same")
        (r,) = db.dot_logs.docs
        self.assertEqual([e["source"] for e in r["status_history"]], ["first_seen"])

    def test_dot_status_change_cannot_alert(self):
        """wa_alerts.collect posts a DOT record once from its LATEST row and
        has no status-change kind for DOT: a legacy_first_refresh row yields
        exactly the items its status already did."""
        row = {"_id": "d1", "project_id": "p1", "company_id": "c1",
               "record_type": "dot_violation", "raw_id": "oath:1", "number": "1",
               "status": "HEARING HELD", "detected_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
               "status_history": [{"status": "X", "at": datetime(2026, 3, 1, tzinfo=timezone.utc),
                                   "source": "first_seen"},
                                  {"status": "HEARING HELD", "at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                                   "source": "legacy_first_refresh"}]}
        kinds = [i["kind"] for i in wa_alerts.collect([], [row], date(2026, 10, 19))]
        self.assertEqual(kinds, ["dot_violation"])   # unchanged by history


# ═══ wa_alerts helpers ═══════════════════════════════════════════════════════

class TestIsClosed(unittest.TestCase):
    OPEN = ["UNPAID", "UNRESOLVED", "NOT CERTIFIED", "NOT COMPLIED", "OPEN", "ACTIVE",
            "un-resolved", "Non-Complied", "NO RESOLVE", "NOT PAID", "UNCERTIFIED",
            "V*-DOB VIOLATION - ACTIVE", "HEARING SCHEDULED", "Disputed Unsuccessfully",
            "NEVER RESCINDED", ""]
    CLOSED = ["CLOSED", "Resolved", "DISMISSED", "PAID", "PAID IN FULL", "CERTIFIED",
              "RESCINDED", "LIFTED", "COMPLIED", "WITHDRAWN",
              "V*-DOB VIOLATION - RESOLVE", "V*-DOB VIOLATION - DISMISS",
              "Stop work order rescinded"]

    def test_status_text(self):
        """NEGATIVE CONTROL: with the old substring test every OPEN entry that
        contains a closed word (UNPAID, UNRESOLVED, NOT CERTIFIED, NOT
        COMPLIED, ...) is reported closed."""
        for s in self.OPEN:
            with self.subTest(open=s):
                self.assertFalse(wa_alerts.status_is_closed(s))
                self.assertFalse(wa_alerts.is_closed({"status": s}))
        for s in self.CLOSED:
            with self.subTest(closed=s):
                self.assertTrue(wa_alerts.status_is_closed(s))
                self.assertTrue(wa_alerts.is_closed({"status": s}))

    def test_every_field_and_closed_date(self):
        for k in ("resolution_state", "complaint_status", "status", "current_status",
                  "hearing_status"):
            self.assertTrue(wa_alerts.is_closed({k: "dismissed"}), k)
            self.assertFalse(wa_alerts.is_closed({k: "unpaid"}), k)
        self.assertTrue(wa_alerts.is_closed({"closed_date": "2026-01-01"}))
        self.assertFalse(wa_alerts.is_closed({"status": "ACTIVE", "closed_date": ""}))

    def test_unpaid_violation_is_still_alertable(self):
        row = {"_id": "v1", "record_type": "violation", "raw_dob_id": "V1",
               "status": "UNPAID", "current_status": "UNPAID",
               "detected_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}
        self.assertEqual([i["kind"] for i in wa_alerts.collect([row], [], date(2026, 10, 19))],
                         ["violation"])


class TestRecordNumber(unittest.TestCase):
    def test_per_type(self):
        """NEGATIVE CONTROL: the old table returned '' for the last five."""
        cases = [
            ({"record_type": "violation", "violation_number": "V1"}, "V1"),
            ({"record_type": "complaint", "complaint_number": "C1"}, "C1"),
            ({"record_type": "swo", "stop_work_order_number": "S1", "violation_number": "V"}, "S1"),
            ({"record_type": "swo", "violation_number": "V9"}, "V9"),
            ({"record_type": "permit", "job_number": "B1-I1"}, "B1-I1"),
            ({"record_type": "dot_violation", "number": "D1"}, "D1"),
            ({"record_type": "job_status", "job_filing_number": "B2-I1"}, "B2-I1"),
            ({"record_type": "cofo", "co_number": "CO-77"}, "CO-77"),
            ({"record_type": "boiler", "tracking_number": "T9"}, "T9"),
            ({"record_type": "elevator", "device_number": "ED1"}, "ED1"),
            ({"record_type": "facade_fisp", "filing_number": "F5"}, "F5"),
            ({"record_type": "facade_fisp", "tracking_number": "TR5"}, "TR5"),
            ({"record_type": "cofo"}, ""),
        ]
        for row, want in cases:
            with self.subTest(row=row):
                self.assertEqual(wa_alerts.record_number(row), want)

    def test_matches_what_the_extractors_store(self):
        """The keys are the ones server._extract_*_fields really write."""
        rows = {
            "job_status": {**server._extract_job_status_fields({"job_filing_number": "B2-I1"})},
            "cofo": {**server._extract_cofo_fields({"c_of_o_number": "CO-77"})},
            "boiler": {**server._extract_boiler_fields({"tracking_number": "T9"})},
            "elevator": {**server._extract_elevator_fields({"device_number": "ED1"})},
            "facade_fisp": {**server._extract_facade_fisp_fields({"filing_number": "F5"})},
        }
        want = {"job_status": "B2-I1", "cofo": "CO-77", "boiler": "T9",
                "elevator": "ED1", "facade_fisp": "F5"}
        for rt, row in rows.items():
            self.assertEqual(wa_alerts.record_number({**row, "record_type": rt}), want[rt], rt)

    def test_issue_dates_for_new_types(self):
        self.assertEqual(wa_alerts.record_issue_date(
            {"record_type": "cofo", "issuance_date": "2026-05-04"}), date(2026, 5, 4))
        self.assertEqual(wa_alerts.record_issue_date(
            {"record_type": "job_status", "filing_date": "2026-05-04"}), date(2026, 5, 4))


class TestStatusAsOf(unittest.TestCase):
    T = datetime(2026, 3, 1, tzinfo=timezone.utc)

    def d(self, days):
        return self.T + timedelta(days=days)

    def row(self):
        return {"detected_at": self.T, "current_status": "ACTIVE", "status_history": [
            {"status": "ACTIVE", "at": self.T, "source": "first_seen"},
            {"status": "RESCINDED", "at": self.d(10), "source": "sync"}]}

    def test_history_row(self):
        r = self.row()
        self.assertIsNone(wa_alerts.status_as_of(r, self.d(-1)), "before first seen")
        self.assertEqual(wa_alerts.status_as_of(r, self.T), "ACTIVE", "inclusive")
        self.assertEqual(wa_alerts.status_as_of(r, self.d(9)), "ACTIVE")
        self.assertEqual(wa_alerts.status_as_of(r, self.d(10)), "RESCINDED")
        self.assertEqual(wa_alerts.status_as_of(r, self.d(400)), "RESCINDED")
        self.assertFalse(wa_alerts.closed_as_of(r, self.d(9)))
        self.assertTrue(wa_alerts.closed_as_of(r, self.d(11)))
        self.assertIsNone(wa_alerts.closed_as_of(r, self.d(-1)), "unknown, not open")

    def test_legacy_row_only_after_it_was_first_seen(self):
        r = {"detected_at": self.T, "current_status": "ACTIVE"}
        self.assertIsNone(wa_alerts.status_as_of(r, self.d(-1)))
        self.assertEqual(wa_alerts.status_as_of(r, self.T), "ACTIVE")
        self.assertEqual(wa_alerts.status_as_of(r, self.d(100)), "ACTIVE")
        self.assertIsNone(wa_alerts.status_as_of({"current_status": "ACTIVE"}, self.d(1)),
                          "undated legacy row: never claimed")

    def test_permit_diff_row_timeline(self):
        rows = [
            {"detected_at": self.d(20), "status_changed_at": self.d(20), "current_status": "EXPIRED"},
            {"detected_at": self.T, "status_changed_at": self.T, "current_status": "ISSUED"},
        ]                                                    # unordered on purpose
        self.assertIsNone(wa_alerts.status_as_of(rows, self.d(-5)))
        self.assertEqual(wa_alerts.status_as_of(rows, self.d(19)), "ISSUED")
        self.assertEqual(wa_alerts.status_as_of(rows, self.d(20)), "EXPIRED")

    def test_timeline_of_rows_with_history_uses_latest_fact(self):
        a = {"status_history": [{"status": "ISSUED", "at": self.T, "source": "first_seen"}]}
        b = {"status_history": [{"status": "ISSUED", "at": self.T, "source": "first_seen"},
                                {"status": "EXPIRED", "at": self.d(5), "source": "sync"}]}
        self.assertEqual(wa_alerts.status_as_of([a, b], self.d(6)), "EXPIRED")
        self.assertEqual(wa_alerts.status_as_of([a, b], self.d(4)), "ISSUED")

    def test_naive_datetimes_are_utc(self):
        r = {"detected_at": datetime(2026, 3, 1), "current_status": "ACTIVE"}
        self.assertEqual(wa_alerts.status_as_of(r, self.T), "ACTIVE")

    def test_dot_row_uses_status(self):
        r = {"detected_at": self.T, "status": "ISSUED & PRINTED"}
        self.assertEqual(wa_alerts.status_as_of(r, self.d(1)), "ISSUED & PRINTED")

    def test_none_status_is_none(self):
        r = {"detected_at": self.T, "current_status": None}
        self.assertIsNone(wa_alerts.status_as_of(r, self.d(1)))

    def test_history_synthesis_helper(self):
        h, legacy = sh.prior_history({"detected_at": self.T, "current_status": "OPEN"}, self.d(1))
        self.assertTrue(legacy)
        self.assertEqual(h, [{"status": "OPEN", "at": self.T, "source": "first_seen"}])


class TestReportReadsHistoryAcrossSyncs(unittest.TestCase):
    def test_sync_then_status_as_of(self):
        """End to end: what a report asks ('was this SWO in force on D?')."""
        s = _Sync()
        s.sync(_project(), [_swo_rec(status="Active")])
        s.sync(_project(), [_swo_rec(status="Rescinded")])
        (r,) = s.rows()
        t_first, t_resc = (e["at"] for e in r["status_history"])
        mid = t_first + (t_resc - t_first) / 2 if t_resc > t_first else t_first
        self.assertEqual(wa_alerts.status_as_of(r, t_first - timedelta(seconds=1)), None)
        self.assertEqual(wa_alerts.status_as_of(r, t_first), "ACTIVE")
        self.assertEqual(wa_alerts.status_as_of(r, t_resc), "RESCINDED")
        self.assertTrue(wa_alerts.closed_as_of(r, t_resc))


class TestResetResyncReingest(unittest.TestCase):
    def test_reingested_rows_get_first_seen_and_no_seed(self):
        """reset-resync deletes the project's rows then re-syncs: the fresh
        rows are ordinary first sightings (first_seen history, not seeds)."""
        s = _Sync()
        s.sync(_project(), [_swo_rec(status="Rescinded"), _viol_rec()])
        _run(s.db.dob_logs.delete_many({"project_id": "p1"}))
        s.sync(_project(), [_swo_rec(status="Rescinded"), _viol_rec()])
        self.assertEqual(len(s.rows()), 2)
        for r in s.rows():
            self.assertEqual(r["status_history"][0]["source"], "first_seen")
            self.assertEqual(len(r["status_history"]), 1)
            self.assertFalse(r["is_seed_transition"])


if __name__ == "__main__":
    unittest.main()


class TheMorningBriefSeesInPlaceChanges(unittest.TestCase):
    """A violation or stop-work order is refreshed IN PLACE (one row, a growing
    status_history); the brief used to need a second row to see any change."""

    NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    SINCE = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

    def row(self, **kw):
        base = {"raw_dob_id": "SWO-1", "record_type": "swo", "stop_work_order_number": "SWO-1",
                "violation_number": "SWO-1", "severity": "Action",
                "detected_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                "status_changed_at": datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc),
                "previous_status": "ACTIVE", "current_status": "RESCINDED", "is_seed_transition": False,
                "status_history": [{"status": "ACTIVE", "at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                                    "source": "first_seen"},
                                   {"status": "RESCINDED", "at": datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc),
                                    "source": "sync"}]}
        base.update(kw)
        return base

    def items(self, row):
        from lib import wa_brief
        return wa_brief.job_items([row], self.SINCE, self.NOW)

    def test_a_rescinded_swo_changed_in_place_is_in_the_brief(self):
        got = self.items(self.row())
        self.assertTrue(any("SWO-1" in i["text"] and "ACTIVE → RESCINDED" in i["text"] for i in got), got)

    def test_a_legacy_first_refresh_is_not(self):
        self.assertEqual(self.items(self.row(is_seed_transition=True)), [])

    def test_a_row_that_never_changed_is_not(self):
        one = self.row(previous_status=None, current_status="ACTIVE",
                       status_history=[{"status": "ACTIVE", "at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                                        "source": "first_seen"}])
        self.assertFalse([i for i in self.items(one) if "changed" in i["text"]])

    def test_unpaid_is_not_closed(self):
        from lib import wa_brief
        self.assertFalse(wa_brief._is_closed({"current_status": "UNPAID"}))
        self.assertFalse(wa_brief._is_closed({"resolution_state": "NOT CERTIFIED"}))
        self.assertTrue(wa_brief._is_closed({"current_status": "RESOLVED"}))
