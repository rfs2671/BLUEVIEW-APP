"""GET /projects/{project_id}/activity-chips — the sequence engine's only caller.

app/scheduling/ has held 86 nodes and 145 edges since it was written, and
rank_activities was called by NOTHING on main except its own test: it was built
to order activity chips for a screen that had none. This is the data side of
that wiring.

The four non-negotiables, each asserted here rather than assumed:

  * suggestions RANK order, they never PRE-SELECT;
  * "Other" is always present and always LAST;
  * rules never BLOCK an entry — an unrecognized prior degrades, it does not
    raise;
  * a project with no structural system gets BOTH loops and is told the system
    is not set. It is never guessed.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


class _Result:
    def __init__(self):
        self.inserted_id = "x"
        self.matched_count = 1
        self.modified_count = 1


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None
        self.updated = []

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query or {}) if callable(v) else v

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result()

    async def insert_one(self, doc, *a, **k):
        return _Result()

    async def count_documents(self, *a, **k):
        return 0


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_DEFAULT = object()   # so `project=None` can mean "no such project"


def _mk_db(*, project=_DEFAULT, prior=None):
    db = _FakeDb()
    proj = {"_id": "proj1"} if project is _DEFAULT else project
    db.projects.set_find_one(lambda q: proj)
    db.logbooks.set_find_one(lambda q: prior)
    return db


def _get(db, *, date=None, role="cp", trade=None):
    async def _fake_user():
        return {
            "_id": "u1", "id": "u1", "role": role, "company_id": "co_a",
            "account_status": "approved", "full_name": "Carl CP",
            "assigned_projects": ["proj1"],
        }

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            params = []
            if date:
                params.append(f"date={date}")
            if trade:
                params.append(f"trade={trade}")
            q = ("?" + "&".join(params)) if params else ""
            return TestClient(server.app).get(f"/api/projects/proj1/activity-chips{q}")
    finally:
        server.app.dependency_overrides.clear()


class TheFourNonNegotiables(unittest.TestCase):

    def test_other_is_present_and_last(self):
        body = _get(_mk_db()).json()
        self.assertEqual(body["chips"][-1]["id"], "other")
        self.assertEqual(
            [c["id"] for c in body["chips"]].count("other"), 1,
            "Other appears exactly once — never duplicated into a band",
        )

    def test_nothing_is_ever_pre_selected(self):
        body = _get(_mk_db()).json()
        self.assertTrue(body["chips"], "the endpoint returned no chips at all")
        self.assertTrue(
            all(c["selected"] is False for c in body["chips"]),
            "a pre-selected chip would put words in the CP's mouth",
        )

    def test_an_unrecognized_prior_degrades_and_never_raises(self):
        prior = {"date": "2026-08-08", "data": {"activities": [
            {"activity_chip_id": "no_such_activity_node"},
        ]}}
        resp = _get(_mk_db(prior=prior), date="2026-08-09")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("no_such_activity_node", body["unrecognized_prior_ids"])
        self.assertTrue(body["chips"], "a rule miss must not empty the chip list")

    def test_unset_structural_system_offers_BOTH_loops_and_says_so(self):
        body = _get(_mk_db(project={"_id": "proj1"})).json()
        ids = {c["id"] for c in body["chips"]}
        self.assertFalse(body["structural_system_set"])
        self.assertEqual(body["structural_system"], "unknown")
        self.assertIn("columns_shearwall_rebar", ids, "cast-in-place loop missing")
        self.assertIn("cfs_wall_panels", ids, "CFS loop missing")


class StructuralSystemIsNeverGuessed(unittest.TestCase):

    def test_cast_in_place_excludes_the_cfs_loop(self):
        body = _get(_mk_db(project={"_id": "proj1", "structural_system": "cast_in_place"})).json()
        ids = {c["id"] for c in body["chips"]}
        self.assertTrue(body["structural_system_set"])
        self.assertIn("columns_shearwall_rebar", ids)
        self.assertNotIn("cfs_wall_panels", ids)

    def test_cfs_excludes_the_cast_in_place_loop(self):
        body = _get(_mk_db(project={"_id": "proj1", "structural_system": "cfs"})).json()
        ids = {c["id"] for c in body["chips"]}
        self.assertTrue(body["structural_system_set"])
        self.assertIn("cfs_wall_panels", ids)
        self.assertNotIn("columns_shearwall_rebar", ids)

    def test_a_junk_value_is_unknown_not_a_guess(self):
        body = _get(_mk_db(project={"_id": "proj1", "structural_system": "steel?"})).json()
        self.assertEqual(body["structural_system"], "unknown")
        self.assertFalse(body["structural_system_set"])

    def test_the_field_is_settable_through_the_project_models(self):
        """A field nothing can write is a dead field."""
        self.assertIn("structural_system", server.ProjectUpdate.model_fields)
        self.assertIn("structural_system", server.ProjectCreate.model_fields)


class PriorDayDrivesTheRanking(unittest.TestCase):

    def test_priors_are_read_strictly_before_the_requested_day(self):
        seen = {}

        def _find_one(q):
            seen.update(q)
            return None

        db = _mk_db()
        db.logbooks.set_find_one(_find_one)
        _get(db, date="2026-08-09")
        self.assertEqual(seen.get("date"), {"$lt": "2026-08-09"},
                         "re-opening today's log must rank off YESTERDAY, not itself")
        self.assertEqual(seen.get("log_type"), "daily_jobsite")
        self.assertEqual(seen.get("is_deleted"), {"$ne": True})

    def test_a_logged_activity_promotes_its_successors(self):
        prior = {"date": "2026-08-08", "data": {"activities": [
            {"activity_chip_id": "excavation"},
        ]}}
        body = _get(_mk_db(prior=prior), date="2026-08-09").json()
        suggested = [c["id"] for c in body["chips"] if c["band"] == "suggested"]
        self.assertIn("excavation", suggested, "concurrent/multi-day work stays offered")
        self.assertIn("shoring", suggested, "a rule successor should be promoted")

    def test_no_prior_is_a_cold_start_not_an_error(self):
        body = _get(_mk_db(prior=None)).json()
        suggested = [c["id"] for c in body["chips"] if c["band"] == "suggested"]
        self.assertIn("site_prep", suggested)
        self.assertIsNone(body["prior_date"])

    def test_prior_date_is_reported_so_the_ui_can_be_honest(self):
        prior = {"date": "2026-08-01", "data": {"activities": [{"activity_chip_id": "excavation"}]}}
        body = _get(_mk_db(prior=prior), date="2026-08-09").json()
        self.assertEqual(body["prior_date"], "2026-08-01")


class RememberedOtherEntries(unittest.TestCase):

    def test_a_remembered_label_comes_back_as_its_own_chip(self):
        db = _mk_db(project={"_id": "proj1", "remembered_other_activities": ["window washing rig"]})
        body = _get(db).json()
        chips = {c["id"]: c for c in body["chips"]}
        self.assertIn("other:window washing rig", chips)
        self.assertEqual(chips["other:window washing rig"]["label"], "window washing rig")
        self.assertEqual(chips["other:window washing rig"]["band"], "remembered_other")

    def test_a_remembered_label_still_is_not_pre_selected(self):
        db = _mk_db(project={"_id": "proj1", "remembered_other_activities": ["rig"]})
        body = _get(db).json()
        self.assertTrue(all(c["selected"] is False for c in body["chips"]))

    def test_other_stays_last_even_with_remembered_entries(self):
        db = _mk_db(project={"_id": "proj1", "remembered_other_activities": ["zzz late alphabetically"]})
        body = _get(db).json()
        self.assertEqual(body["chips"][-1]["id"], "other")


class ExtractionHelpers(unittest.TestCase):
    """These read CP-authored payloads, so they must be tolerant of every
    shape the eleven log types produce — most have no activities at all."""

    def test_chip_ids_are_extracted_and_deduped_in_order(self):
        data = {"activities": [
            {"activity_chip_id": "excavation"},
            {"activity_chip_id": "shoring"},
            {"activity_chip_id": "excavation"},
        ]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation", "shoring"])

    def test_an_other_row_is_reported_under_its_own_label_id(self):
        data = {"activities": [
            {"activity_chip_id": "other", "activity_other_label": "window washing rig"},
        ]}
        self.assertEqual(server._activity_chip_ids(data), ["other:window washing rig"])

    def test_a_row_with_no_chip_is_invisible_not_an_error(self):
        """Rules never block an entry: a CP may log work with no chip at all."""
        data = {"activities": [{"work_description": "patched a leak"}]}
        self.assertEqual(server._activity_chip_ids(data), [])

    def test_shapes_that_are_not_activity_payloads_are_tolerated(self):
        for junk in (None, {}, {"activities": None}, {"activities": "x"},
                     {"activities": [None, 3, "x"]}, [], "nope"):
            with self.subTest(junk=junk):
                self.assertEqual(server._activity_chip_ids(junk), [])
                self.assertEqual(server._other_labels_in(junk), [])

    def test_other_labels_require_a_label(self):
        data = {"activities": [{"activity_chip_id": "other", "activity_other_label": "   "}]}
        self.assertEqual(server._other_labels_in(data), [])


class RememberingIsFailureIsolated(unittest.IsolatedAsyncioTestCase):

    async def test_labels_are_added_to_the_project(self):
        db = _FakeDb()
        with patch.object(server, "db", db):
            await server._remember_other_activities("proj1", {"activities": [
                {"activity_chip_id": "other", "activity_other_label": "rig"},
            ]})
        self.assertEqual(len(db.projects.updated), 1)
        _q, u = db.projects.updated[0]
        self.assertEqual(u["$addToSet"]["remembered_other_activities"]["$each"], ["rig"])

    async def test_nothing_is_written_when_there_is_nothing_to_remember(self):
        db = _FakeDb()
        with patch.object(server, "db", db):
            await server._remember_other_activities("proj1", {"activities": [
                {"activity_chip_id": "excavation"},
            ]})
        self.assertEqual(db.projects.updated, [])

    async def test_a_failed_write_never_propagates(self):
        """A CP's log must not fail because a convenience list did not update."""
        class _Boom(_FakeCollection):
            async def update_one(self, *a, **k):
                raise RuntimeError("mongo down")

        db = _FakeDb()
        db._c["projects"] = _Boom("projects")
        with patch.object(server, "db", db):
            await server._remember_other_activities("proj1", {"activities": [
                {"activity_chip_id": "other", "activity_other_label": "rig"},
            ]})  # must not raise


class Wiring(unittest.TestCase):

    def test_the_route_is_registered_and_guarded(self):
        route = next(
            (r for r in server.app.routes
             if getattr(r, "path", "") == "/api/projects/{project_id}/activity-chips"),
            None,
        )
        self.assertIsNotNone(route, "the endpoint is not registered")
        names = {getattr(d.dependency, "__name__", "") for d in route.dependencies}
        self.assertIn("require_approved", names)
        self.assertIn("require_project_access", names)

    def test_a_missing_project_is_404(self):
        self.assertEqual(_get(_mk_db(project=None)).status_code, 404)

    def test_it_is_a_GET_so_the_tenant_write_lists_are_unchanged(self):
        """CLEAN_ROUTES in test_tenant_isolation_writes covers write verbs only,
        so this route adds nothing to those hardcoded counts."""
        route = next(
            r for r in server.app.routes
            if getattr(r, "path", "") == "/api/projects/{project_id}/activity-chips"
        )
        self.assertEqual(set(route.methods), {"GET"})


class TheDefaultDayIsEasternNotUTC(unittest.TestCase):
    """`date` is optional. When it is omitted the endpoint picks the day itself,
    and on the UTC clock that is TOMORROW from 20:00 EDT (19:00 EST).

    That matters here more than on a screen: priors are read with
    {"$lt": day}, so a day that is one ahead silently ranks off the WRONG
    prior instead of returning nothing obvious.

    THE CLOCK IS PINNED. This defect is invisible before 20:00 Eastern, so a
    test reading the real current time would pass all morning and prove nothing.
    """

    _EDT_2100 = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)   # 21:00 EDT 08-09
    _EST_1900 = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)   # 19:00 EST 01-15

    def test_the_boundary_instants_actually_discriminate(self):
        """If UTC and Eastern agreed at these instants the assertions below
        would pass on the broken code too."""
        self.assertEqual(self._EDT_2100.strftime("%Y-%m-%d"), "2026-08-10")
        self.assertEqual(server.eastern_date(self._EDT_2100), "2026-08-09")
        self.assertEqual(self._EST_1900.strftime("%Y-%m-%d"), "2026-01-16")
        self.assertEqual(server.eastern_date(self._EST_1900), "2026-01-15")

    def _day_the_endpoint_defaulted_to(self, pinned_eastern_day):
        """Run the endpoint with no ?date and report the day it queried priors
        with, by capturing the filter it built."""
        seen = {}

        def _find_one(q):
            seen.update(q)
            return None

        db = _mk_db()
        db.logbooks.set_find_one(_find_one)
        with patch.object(server, "eastern_today", lambda: pinned_eastern_day):
            resp = _get(db)          # NO date param
        self.assertEqual(resp.status_code, 200, resp.text)
        return seen.get("date", {}).get("$lt")

    def test_at_2100_edt_it_defaults_to_the_eastern_day(self):
        got = self._day_the_endpoint_defaulted_to(server.eastern_date(self._EDT_2100))
        self.assertEqual(got, "2026-08-09")
        self.assertNotEqual(got, "2026-08-10", "that is the UTC day — the bug")

    def test_at_1900_est_it_defaults_to_the_eastern_day(self):
        got = self._day_the_endpoint_defaulted_to(server.eastern_date(self._EST_1900))
        self.assertEqual(got, "2026-01-15")
        self.assertNotEqual(got, "2026-01-16", "that is the UTC day — the bug")

    def test_an_explicit_date_still_wins(self):
        seen = {}

        def _find_one(q):
            seen.update(q)
            return None

        db = _mk_db()
        db.logbooks.set_find_one(_find_one)
        with patch.object(server, "eastern_today", lambda: "2026-08-09"):
            _get(db, date="2026-07-04")
        self.assertEqual(seen.get("date", {}).get("$lt"), "2026-07-04")

    def test_the_endpoint_calls_the_shared_helper_not_a_variant(self):
        i = _SRC.index("async def get_activity_chips")
        block = _SRC[i:i + 2500]
        self.assertIn("or eastern_today()", block)
        self.assertNotIn('datetime.now(timezone.utc).strftime("%Y-%m-%d")', block)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestUnresolvedTradeIsRecorded(unittest.TestCase):
    """WE LEARN WHAT ADMINS TYPE, rather than guessing at synonyms.

    The alias map is a FIXED LIST IN CODE by ruling. An unmapped trade falls
    back to the whole catalogue — loud in the right way (too many chips) and
    silent in the wrong way (nothing false). An admin-editable map would swap
    that for a mis-mapping nobody sees: `Cleaning` pointed at Demolition looks
    exactly like a correct suggestion and lands behind a signed daily log.

    The real cost of a fixed list is that nobody FINDS OUT a string missed.
    `Concrete / Cement` sat on a live project resolving to nothing and only
    surfaced because someone read a roster by hand.
    """

    def test_an_unresolved_trade_is_logged_with_the_string(self):
        with self.assertLogs(server.logger, level="INFO") as cap:
            body = _get(_mk_db(), trade="Cleaning").json()
        self.assertEqual(body["resolved_trades"], [])
        joined = " ".join(cap.output)
        self.assertIn("Cleaning", joined)
        self.assertIn("unresolved roster trade", joined)

    def test_a_resolved_trade_logs_nothing(self):
        """A note, not a metric. It must not fire on the normal path."""
        with self.assertLogs(server.logger, level="INFO") as cap:
            server.logger.info("sentinel")     # assertLogs needs one record
            body = _get(_mk_db(), trade="Electrician").json()
        self.assertEqual(body["resolved_trades"], ["Electrical"])
        self.assertNotIn("unresolved roster trade", " ".join(cap.output))

    def test_no_trade_at_all_logs_nothing(self):
        """A crew with no trade is the ordinary case, not a miss."""
        with self.assertLogs(server.logger, level="INFO") as cap:
            server.logger.info("sentinel")
            _get(_mk_db()).json()
        self.assertNotIn("unresolved roster trade", " ".join(cap.output))

    def test_the_request_is_unchanged_by_the_logging(self):
        """It records and returns; it never refuses, and the fallback to the
        unfiltered catalogue is exactly what it was."""
        body = _get(_mk_db(), trade="Cleaning").json()
        self.assertGreater(len(body["chips"]), 0)
        self.assertEqual(body["chips"][-1]["id"], "other")

    def test_a_long_string_is_truncated_before_it_reaches_the_log(self):
        with self.assertLogs(server.logger, level="INFO") as cap:
            _get(_mk_db(), trade="Z" * 300).json()
        for line in cap.output:
            if "unresolved roster trade" in line:
                self.assertLess(len(line), 400, line[:120])
