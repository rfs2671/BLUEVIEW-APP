"""NYC DOT holiday construction embargo: Nov 15 - Jan 2, waiver = stipulation 410.

THE FINDING (live data, 2026-10-22). DOT writes the waiver as stipulation 410
on the permit -- "A WAIVER IS GRANTED TO ALLOW WORK TO OCCUR DURING THE HOLIDAY
CONSTRUCTION EMBARGO (IN EFFECT ANNUALLY FROM NOVEMBER 15TH THROUGH JANUARY 2ND
THE FOLLOWING YEAR) ..." -- in the stipulations dataset gsgx-6efw, which the
permit dataset does not carry. A matched, active permit whose work dates
overlap the season and which has no 410 must be flagged; unread stipulations
are UNKNOWN and never alert.

The fixture tests/fixtures/dot_embargo/M022026294C45.json is a recorded, unedited
NYC Open Data read (permit + its 18 stipulations, 410 among them). The permit
without the waiver is the same record with another number and the 410 row
removed.

The job tests drive the REAL _dot_sync_tick, _dot_stipulations_tick,
_dot_embargo_alert_tick and _gc_alerts_tick against an in-memory db; only the
network (fetch), the email sender (lib.notifications.send_notification) and
the WhatsApp wire (the GC harness of test_whatsapp_gc_alerts) are replaced.

Both the email and the GC group post carry the operator's action line, EN then
ES, and neither sends before the project's first DOT permit pass completes
(source_sync first_synced_at).

CONTROL RUN: on origin/main every test here fails -- lib/dot_embargo.py, the
two ticks, the route and dot_logs.work_start do not exist. The import is guarded
so each test fails on its own assertion rather than as one collection error.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
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

from pymongo.errors import DuplicateKeyError  # noqa: E402

import server  # noqa: E402
from lib import dot_sync  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, _Cursor  # noqa: E402

try:
    from lib import dot_embargo as E  # noqa: E402
except ImportError:          # origin/main: the control run
    E = None

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "dot_embargo"
                      / "M022026294C45.json").read_text(encoding="utf-8"))
REAL_PERMIT = FIXTURE["permit"]                       # has 410
REAL_STIPS = FIXTURE["stipulations"]
NO_WAIVER_NUM = "M022026294X01"                       # synthetic: no 410
NO_WAIVER_PERMIT = {**REAL_PERMIT, "permitnumber": NO_WAIVER_NUM}
NO_WAIVER_STIPS = [{**r, "permitnumber": NO_WAIVER_NUM}
                   for r in REAL_STIPS if r["stipulationid"] != "410"]
STIP_DATASET = "gsgx-6efw"
# Operator copy (2026-10-22), written out here rather than read from the code.
ACTION_EN = "No street work Nov 15 - Jan 2 unless DOT grants one."
ACTION_ES = ("No se permite trabajo en la calle del 15 de nov al 2 de ene salvo que "
             "el DOT otorgue una exención.")
# The coverage limit #852 stated (operator copy). DOT Phase 1 B matches segment
# permits (permittee + frontage) and REMOVED it: these lines must be gone.
COVERAGE_EN = ("Checks permits matched to your address. Permits filed by street segment "
               "arrive with the next update.")
COVERAGE_ES = ("Revisa los permisos vinculados a su dirección. Los permisos registrados por "
               "tramo de calle llegarán con la próxima actualización.")

UTC = timezone.utc
OCT22 = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)    # the sync that first sees them
NOV1_7AM = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)  # 07:00 EST (DST ended 02:00)
NOV2_7AM = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
NOV12_7AM = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _run(coro):
    return asyncio.run(coro)


def _need():
    if E is None:
        raise AssertionError("lib/dot_embargo.py does not exist (origin/main)")


# ── an in-memory db with a real _id uniqueness ──────────────────────────────

class _Cur(_Cursor):
    async def to_list(self, n=None, length=None):
        return await super().to_list(n)


class _Col(AsyncFakeCollection):
    def find(self, flt=None, projection=None, **kw):
        return _Cur(super().find(flt, projection)._docs)

    async def insert_one(self, doc, **kw):
        if "_id" in doc and any(str(d.get("_id")) == str(doc["_id"]) for d in self.docs):
            raise DuplicateKeyError(f"E11000 duplicate key {doc['_id']}")
        return await super().insert_one(doc, **kw)

    async def update_one(self, flt, update, upsert=False, **kw):
        """+ upsert, which the source-sync state write relies on."""
        res = await super().update_one(flt, update, **kw)
        if res.matched_count or not upsert:
            return res
        doc = {k: v for k, v in (flt or {}).items()
               if not k.startswith("$") and not isinstance(v, dict)}
        await self.insert_one(doc)
        return await super().update_one({"_id": doc["_id"]}, update, **kw)


class _DB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Col(name)
        return self._c[name]


def _world(company="c1", is_test=False):
    db = _DB()
    db.companies.docs += [{"_id": company, "name": "Acme GC", **({"is_test": True} if is_test else {})}]
    db.projects.docs += [{"_id": "p1", "company_id": company, "name": "475 West Broadway",
                          "address": "475 West Broadway, Manhattan, NY"}]
    db.users.docs += [{"_id": "u1", "company_id": company, "role": "admin",
                       "email": "admin@acme.test"},
                      {"_id": "u2", "company_id": company, "role": "cp",
                       "email": "cp@acme.test"}]
    return db


def _fetch(permits, stips):
    """permits: the tqtj-sjs8 rows; stips: {permit: rows | None (failed read)}."""
    calls = []

    async def fetch(dataset, params):
        calls.append(dataset)
        if dataset == dot_sync.PERMIT_DATASET:
            return copy.deepcopy(permits)
        if dataset == STIP_DATASET:
            m = re.search(r"permitnumber = '([^']+)'", params.get("$where", ""))
            got = stips.get(m.group(1)) if m else None
            return None if got is None else copy.deepcopy(got)
        return []
    fetch.calls = calls
    return fetch


class _Env:
    """One world + the patched sender; drives the real ticks."""

    def __init__(self, **kw):
        self.db = _world(**kw)
        self.send = AsyncMock(return_value={"status": "sent"})

    def sync(self, permits, stips, now=OCT22):
        with patch.object(server, "db", self.db):
            return _run(server._dot_sync_tick(now=now, fetch=_fetch(permits, stips)))

    def stipulations(self, stips, now=OCT22):
        with patch.object(server, "db", self.db):
            return _run(server._dot_stipulations_tick(now=now, fetch=_fetch([], stips)))

    def alerts(self, now, key="re_test_key", kill=""):
        with patch.object(server, "db", self.db), \
                patch.object(server, "RESEND_API_KEY", key), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": kill}), \
                patch("lib.notifications.send_notification", self.send):
            return _run(server._dot_embargo_alert_tick(now=now))

    def emails(self):
        return [c.kwargs for c in self.send.await_args_list]

    def row(self, num):
        return next(d for d in self.db.dot_logs.docs if d.get("number") == num)


def _row(start, end, status="ISSUED & PRINTED", waiver=False, **kw):
    r = {"record_type": "dot_permit", "number": "P1", "status": status,
         "work_start": start, "expiration_date": end, "issue_date": "2026-10-01T10:00:00.000",
         "detected_at": datetime(2026, 10, 2, tzinfo=UTC)}
    if waiver is not None:
        r["holiday_waiver"] = waiver
    r.update(kw)
    return r


# ═══ Pure rules ═════════════════════════════════════════════════════════════

class TheSeason(unittest.TestCase):

    def setUp(self):
        _need()

    def test_bounds_span_the_year_change(self):
        s = E.season_for(date(2026, 11, 20))
        self.assertEqual((s.year, s.start, s.end), (2026, date(2026, 11, 15), date(2027, 1, 2)))
        self.assertEqual(E.season_for(date(2027, 1, 1)), s)
        self.assertEqual(E.season_for(date(2027, 1, 2)), s)
        self.assertEqual(E.season_for(date(2027, 1, 3)).year, 2027)
        self.assertEqual(E.season_for(date(2026, 10, 22)), s)       # the next one

    def test_alert_window_is_nov_1_to_jan_2(self):
        self.assertFalse(E.in_alert_window(date(2026, 10, 31)))
        self.assertTrue(E.in_alert_window(date(2026, 11, 1)))
        self.assertTrue(E.in_alert_window(date(2026, 12, 31)))
        self.assertTrue(E.in_alert_window(date(2027, 1, 2)))
        self.assertFalse(E.in_alert_window(date(2027, 1, 3)))


class TheOverlapEdges(unittest.TestCase):

    def setUp(self):
        _need()
        self.s = E.season_for(date(2026, 11, 1))

    def test_ends_nov_14_is_not_exposed_nov_15_is(self):
        self.assertFalse(E.exposed(_row("2026-10-01T00:00:00.000", "2026-11-14T23:59:59.000"), self.s))
        self.assertTrue(E.exposed(_row("2026-10-01T00:00:00.000", "2026-11-15T00:00:00.000"), self.s))

    def test_starts_jan_3_is_not_exposed_jan_2_is(self):
        self.assertFalse(E.exposed(_row("2027-01-03T00:00:00.000", "2027-02-01T00:00:00.000"), self.s))
        self.assertTrue(E.exposed(_row("2027-01-02T00:00:00.000", "2027-02-01T00:00:00.000"), self.s))

    def test_across_the_year_change_and_around_the_season(self):
        self.assertTrue(E.exposed(_row("2026-12-28T00:00:00.000", "2027-01-10T00:00:00.000"), self.s))
        self.assertTrue(E.exposed(_row("2026-09-01T00:00:00.000", "2027-03-01T00:00:00.000"), self.s))
        self.assertTrue(E.exposed(_row("2027-01-01T00:00:00.000", "2027-01-01T23:59:59.000"), self.s))

    def test_the_real_permit_is_exposed(self):
        log = dot_sync.to_log("dot_permit", REAL_PERMIT)
        self.assertTrue(E.exposed(log, self.s))                   # Nov 3 - Nov 30

    def test_only_active_permits(self):
        rng = ("2026-11-01T00:00:00.000", "2026-12-01T00:00:00.000")
        self.assertTrue(E.exposed(_row(*rng, status="ISSUED & PRINTED"), self.s))
        self.assertTrue(E.exposed(_row(*rng, status="EMERGENCY"), self.s))
        for st in ("EXPIRED", "VOIDED", "DELINQUENT", "", None):
            self.assertFalse(E.exposed(_row(*rng, status=st), self.s), st)

    def test_no_end_date_is_not_exposed(self):
        self.assertFalse(E.exposed(_row("2026-11-01T00:00:00.000", None), self.s))


class TheWaiver(unittest.TestCase):

    def setUp(self):
        _need()

    def test_true_false_none(self):
        self.assertIs(E.has_waiver({"holiday_waiver": True}), True)
        self.assertIs(E.has_waiver({"holiday_waiver": False}), False)
        self.assertIsNone(E.has_waiver({"holiday_waiver": None}))
        self.assertIsNone(E.has_waiver({}))

    def test_read_from_the_recorded_stipulations(self):
        got = E.stipulation_fields("M022026294C45", REAL_STIPS)
        self.assertIs(got["holiday_waiver"], True)
        self.assertEqual(len(got["stipulations"]), 18)
        w = next(s for s in got["stipulations"] if s["id"] == "410")
        self.assertTrue(w["text"].startswith("A WAIVER IS GRANTED TO ALLOW WORK TO OCCUR "
                                             "DURING THE HOLIDAY CONSTRUCTION EMBARGO"))
        self.assertIs(E.stipulation_fields(NO_WAIVER_NUM, NO_WAIVER_STIPS)["holiday_waiver"], False)

    def test_nothing_read_is_unknown_not_no_waiver(self):
        self.assertIsNone(E.stipulation_fields("M022026294C45", [])["holiday_waiver"])
        # another permit's rows are not this permit's
        self.assertIsNone(E.stipulation_fields(NO_WAIVER_NUM, REAL_STIPS)["holiday_waiver"])

    def test_unknown_is_never_flagged(self):
        s = E.season_for(date(2026, 11, 1))
        rng = ("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000")
        self.assertTrue(E.needs_waiver(_row(*rng, waiver=False), s))
        self.assertFalse(E.needs_waiver(_row(*rng, waiver=True), s))
        self.assertFalse(E.needs_waiver(_row(*rng, waiver=None), s))


class WhatIsDue(unittest.TestCase):

    RNG = ("2026-11-03T00:00:00.000", "2026-11-30T23:59:59.000")

    def setUp(self):
        _need()

    def due(self, row, today):
        return [(d["permit"], d["kind"], d["send_date"]) for d in E.due_sends([row], today)]

    def test_nov_1_and_nov_12_only(self):
        r = _row(*self.RNG)
        self.assertEqual(self.due(r, date(2026, 11, 1)), [("P1", "reminder", date(2026, 11, 1))])
        self.assertEqual(self.due(r, date(2026, 11, 12)), [("P1", "reminder", date(2026, 11, 12))])
        for d in (date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 11),
                  date(2026, 11, 13), date(2026, 12, 1), date(2026, 10, 1)):
            self.assertEqual(self.due(r, d), [], d)

    def test_waiver_or_unknown_is_never_due(self):
        self.assertEqual(self.due(_row(*self.RNG, waiver=True), date(2026, 11, 1)), [])
        self.assertEqual(self.due(_row(*self.RNG, waiver=None), date(2026, 11, 1)), [])

    def _new(self, issued, seen):
        return _row("2026-11-20T00:00:00.000", "2026-12-20T00:00:00.000",
                    issue_date=f"{issued.isoformat()}T09:00:00.000",
                    detected_at=datetime(seen.year, seen.month, seen.day, 18, 0, tzinfo=UTC))

    def test_first_sight_within_two_days(self):
        r = self._new(issued=date(2026, 11, 19), seen=date(2026, 11, 20))
        self.assertEqual(self.due(r, date(2026, 11, 20)), [("P1", "first_sight", date(2026, 11, 20))])
        # next morning: same send date, so the ledger stops a second send
        self.assertEqual(self.due(r, date(2026, 11, 21)), [("P1", "first_sight", date(2026, 11, 20))])

    def test_first_sight_three_days_old_is_not_sent(self):
        r = self._new(issued=date(2026, 11, 18), seen=date(2026, 11, 20))
        self.assertEqual(self.due(r, date(2026, 11, 21)), [])

    def test_first_sight_needs_detection_inside_the_window(self):
        r = self._new(issued=date(2026, 10, 30), seen=date(2026, 10, 31))
        self.assertEqual(self.due(r, date(2026, 11, 2)), [])

    def test_reminder_and_first_sight_on_one_day_send_once(self):
        r = self._new(issued=date(2026, 10, 31), seen=date(2026, 11, 1))
        self.assertEqual(self.due(r, date(2026, 11, 1)), [("P1", "reminder", date(2026, 11, 1))])

    def test_the_ledger_key(self):
        self.assertEqual(E.ledger_id("p1", "M022026294X01", 2026, date(2026, 11, 1)),
                         "dot:p1:embargo:M022026294X01:2026:2026-11-01")


class TheBanner(unittest.TestCase):

    def setUp(self):
        _need()

    def test_lists_missing_inside_the_window_only(self):
        rows = [_row("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000", number="B", waiver=False),
                _row("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000", number="A", waiver=True),
                _row("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000", number="C", waiver=None)]
        got = E.banner(rows, date(2026, 11, 20))
        self.assertTrue(got["show"])
        self.assertEqual([p["number"] for p in got["missing_waiver"]], ["B"])
        self.assertEqual([p["number"] for p in got["unknown"]], ["C"])
        before = E.banner(rows, date(2026, 10, 31))
        self.assertEqual((before["show"], before["missing_waiver"]), (False, []))

    def test_unreadable_stipulations_alone_still_show_it(self):
        # "Waiver not verified" (ruling 2026-10-22): a permit whose
        # stipulations could not be read is shown on the screen; the email
        # and the group post still ignore it (TheAlertJob, TheGroupPost).
        rows = [_row("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000", number="C", waiver=None),
                _row("2026-11-03T00:00:00.000", "2026-11-30T00:00:00.000", number="A", waiver=True)]
        got = E.banner(rows, date(2026, 11, 20))
        self.assertTrue(got["show"])
        self.assertEqual(got["missing_waiver"], [])
        self.assertEqual([p["number"] for p in got["unknown"]], ["C"])
        self.assertFalse(E.banner(rows, date(2026, 10, 31))["show"])


# ═══ Through the real job code ══════════════════════════════════════════════

class TheSyncStoresWorkStartAndStipulations(unittest.TestCase):

    def test_to_log_stores_the_work_start(self):
        log = dot_sync.to_log("dot_permit", REAL_PERMIT)
        self.assertEqual(log.get("work_start"), "2026-11-03T00:00:00.000")
        self.assertEqual(log["expiration_date"], "2026-11-30T23:59:59.000")

    def test_a_new_permit_has_its_stipulations_read_in_the_sync(self):
        _need()
        env = _Env()
        r = env.sync([REAL_PERMIT, NO_WAIVER_PERMIT],
                     {"M022026294C45": REAL_STIPS, NO_WAIVER_NUM: NO_WAIVER_STIPS})
        self.assertEqual((r["new"], r["stipulations_read"]), (2, 2))
        self.assertIs(env.row("M022026294C45")["holiday_waiver"], True)
        self.assertIs(env.row(NO_WAIVER_NUM)["holiday_waiver"], False)
        self.assertEqual(env.row(NO_WAIVER_NUM)["stipulations_fetched_at"], OCT22)
        self.assertNotIn("410", [s["id"] for s in env.row(NO_WAIVER_NUM)["stipulations"]])

    def test_the_daily_job_reads_and_a_failed_read_writes_nothing(self):
        _need()
        env = _Env()
        env.sync([REAL_PERMIT], {})                          # stipulations failed
        self.assertNotIn("holiday_waiver", env.row("M022026294C45"))
        r = env.stipulations({"M022026294C45": REAL_STIPS})
        self.assertEqual((r["permits"], r["read"]), (1, 1))
        self.assertIs(env.row("M022026294C45")["holiday_waiver"], True)
        r = env.stipulations({}, now=OCT22 + timedelta(days=1))   # a later failed read
        self.assertEqual(r["failed"], 1)
        self.assertIs(env.row("M022026294C45")["holiday_waiver"], True)   # not erased
        self.assertEqual(env.row("M022026294C45")["stipulations_fetched_at"], OCT22)

    def test_an_empty_read_is_unknown(self):
        _need()
        env = _Env()
        env.sync([REAL_PERMIT], {"M022026294C45": []})
        self.assertIsNone(env.row("M022026294C45")["holiday_waiver"])


class TheAlertJob(unittest.TestCase):

    def setUp(self):
        _need()

    def _env(self, permit, stips, **kw):
        env = _Env(**kw)
        env.sync([permit], stips)
        return env

    def test_nov_1_no_waiver_sends_one_email(self):
        env = self._env(NO_WAIVER_PERMIT, {NO_WAIVER_NUM: NO_WAIVER_STIPS})
        r = env.alerts(NOV1_7AM)
        mails = env.emails()
        self.assertEqual(len(mails), 1, r)                    # the admin; the CP never
        m = mails[0]
        self.assertEqual(m["recipient"], "admin@acme.test")
        self.assertEqual(m["trigger_type"], "dot_embargo_waiver_missing")
        self.assertEqual(m["permit_renewal_id"], f"dot:p1:embargo:{NO_WAIVER_NUM}:2026:2026-11-01")
        self.assertIn(f"Holiday embargo: permit {NO_WAIVER_NUM} has no waiver", m["subject"])
        self.assertIn(f"Embargo navideño: el permiso {NO_WAIVER_NUM} no tiene exención", m["subject"])
        for s in (NO_WAIVER_NUM, "PLACE EQUIPMENT OTHER THAN CRANE OR SHOV",
                  "Nov 3, 2026 - Nov 30, 2026", "Nov 15, 2026 - Jan 2, 2027",
                  "apply to DOT (OCMC) for a holiday embargo waiver, or stop work",
                  "3 nov 2026 - 30 nov 2026", "15 nov 2026 - 2 ene 2027", "detenga"):
            self.assertIn(s, m["text"], s)
        self.assertLess(m["text"].index("What to do"), m["text"].index("Qué hacer"))
        self.assertIn(NO_WAIVER_NUM, m["html"])
        for line in (ACTION_EN, ACTION_ES):
            self.assertIn(line, m["text"])
            self.assertIn(line, m["html"])
        self.assertLess(m["text"].index(ACTION_EN), m["text"].index(ACTION_ES))
        # DOT Phase 1 B: the coverage note is gone from the email, EN and ES.
        for line in (COVERAGE_EN, COVERAGE_ES, "Permits filed by street segment",
                     "registrados por tramo de calle"):
            self.assertNotIn(line, m["text"])
            self.assertNotIn(line, m["html"])
        self.assertFalse(hasattr(E, "COVERAGE_NOTE_EN") or hasattr(E, "COVERAGE_NOTE_ES"))
        (led,) = env.db.dot_alert_ledger.docs
        self.assertEqual(led["_id"], f"dot:p1:embargo:{NO_WAIVER_NUM}:2026:2026-11-01")

    def test_nov_1_with_the_waiver_sends_nothing(self):
        env = self._env(REAL_PERMIT, {"M022026294C45": REAL_STIPS})
        env.alerts(NOV1_7AM)
        self.assertEqual(env.emails(), [])

    def test_nov_1_unreadable_stipulations_send_nothing(self):
        env = self._env(NO_WAIVER_PERMIT, {})                 # every read failed
        self.assertIsNone(E.has_waiver(env.row(NO_WAIVER_NUM)))
        env.alerts(NOV1_7AM)
        self.assertEqual(env.emails(), [])
        self.assertEqual(env.db.dot_alert_ledger.docs, [])

    def test_a_second_run_the_same_day_sends_nothing(self):
        env = self._env(NO_WAIVER_PERMIT, {NO_WAIVER_NUM: NO_WAIVER_STIPS})
        env.alerts(NOV1_7AM)
        r = env.alerts(NOV1_7AM + timedelta(hours=3))
        self.assertEqual(len(env.emails()), 1)
        self.assertEqual(r["already"], 1)

    def test_nov_2_nothing_nov_12_one_again(self):
        env = self._env(NO_WAIVER_PERMIT, {NO_WAIVER_NUM: NO_WAIVER_STIPS})
        env.alerts(NOV1_7AM)
        env.alerts(NOV2_7AM)
        self.assertEqual(len(env.emails()), 1)
        env.alerts(NOV12_7AM)
        mails = env.emails()
        self.assertEqual(len(mails), 2)
        self.assertTrue(mails[1]["permit_renewal_id"].endswith(":2026:2026-11-12"))

    def _seeded(self, is_test, dot_synced=True):
        """The row (and sync state) the sync would have written, seeded
        directly: the sync itself leaves a test company out."""
        env = _Env(is_test=is_test)
        env.db.dot_logs.docs.append({**dot_sync.to_log("dot_permit", NO_WAIVER_PERMIT),
                                     "project_id": "p1", "company_id": "c1",
                                     "holiday_waiver": False, "detected_at": OCT22})
        srcs = ["dob_violations"] + (["dot_permits"] if dot_synced else [])
        env.db.source_sync_state.docs.append(
            {"_id": "p1", "company_id": "c1",
             "sources": {x: {"first_synced_at": OCT22, "synced_at": OCT22} for x in srcs}})
        return env

    def test_a_test_companys_project_sends_nothing(self):
        env = self._env(NO_WAIVER_PERMIT, {NO_WAIVER_NUM: NO_WAIVER_STIPS}, is_test=True)
        self.assertEqual(env.db.dot_logs.docs, [])          # the sync left it out
        env = self._seeded(is_test=True)
        env.alerts(NOV1_7AM)
        self.assertEqual(env.emails(), [])
        control = self._seeded(is_test=False)               # same world, real company
        control.alerts(NOV1_7AM)
        self.assertEqual(len(control.emails()), 1)

    def test_nothing_sends_before_the_first_dot_pass(self):
        env = self._seeded(is_test=False, dot_synced=False)
        r = env.alerts(NOV1_7AM)
        self.assertEqual((env.emails(), env.db.dot_alert_ledger.docs, r["waiting_sync"]),
                         ([], [], 1))
        env.db.source_sync_state.docs[0]["sources"]["dot_permits"] = {
            "first_synced_at": NOV1_7AM, "synced_at": NOV1_7AM}
        env.alerts(NOV1_7AM + timedelta(hours=1))          # the pass completed
        self.assertEqual(len(env.emails()), 1)

    def test_no_resend_key_or_kill_switch_sends_nothing_and_keeps_the_day(self):
        env = self._env(NO_WAIVER_PERMIT, {NO_WAIVER_NUM: NO_WAIVER_STIPS})
        env.alerts(NOV1_7AM, key="")
        env.alerts(NOV1_7AM, kill="1")
        self.assertEqual((env.emails(), env.db.dot_alert_ledger.docs), ([], []))
        env.alerts(NOV1_7AM)                                  # switch cleared: it goes
        self.assertEqual(len(env.emails()), 1)

    def test_first_sight_of_a_new_permit_in_the_window(self):
        fresh = {**NO_WAIVER_PERMIT, "permitissuedate": "2026-11-19T10:00:00.000",
                 "issuedworkstartdate": "2026-11-20T00:00:00.000",
                 "issuedworkenddate": "2026-12-20T23:59:59.000"}
        env = _Env()
        env.sync([fresh], {NO_WAIVER_NUM: NO_WAIVER_STIPS},
                 now=datetime(2026, 11, 20, 15, 0, tzinfo=UTC))
        env.alerts(datetime(2026, 11, 21, 12, 0, tzinfo=UTC))
        env.alerts(datetime(2026, 11, 22, 12, 0, tzinfo=UTC))
        mails = env.emails()
        self.assertEqual(len(mails), 1)
        self.assertTrue(mails[0]["permit_renewal_id"].endswith(":2026:2026-11-20"))


# ═══ WhatsApp: the GC group post (kind "dot_embargo") ════════════════════════

from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world, synced_state,
)

GC_OCT22 = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
GC_NOV1 = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)      # 11 AM ET, Sunday
GC_NOV12 = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)    # 11 AM ET, Thursday


def _gc_permit(waiver=False, **kw):
    row = {**dot_sync.to_log("dot_permit", NO_WAIVER_PERMIT),
           "_id": "d_x01", "project_id": "proj_a", "company_id": CO_A,
           "detected_at": OCT22}
    if waiver is not None:
        row["holiday_waiver"] = waiver
    row.update(kw)
    return row


class TheGroupPost(unittest.TestCase):

    def setUp(self):
        _need()

    def _ticks(self, db, times):
        """The embargo posts only (the permit's own expiry reminders post too)."""
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            for t in times:
                _run(server._gc_alerts_tick(t))
            return [x["message"] for x in _group_sends(c) if "embargo" in x["message"]]

    def test_once_on_nov_1_and_once_on_nov_12(self):
        db = _gc_world(dot_logs=[_gc_permit()])
        texts = self._ticks(db, [
            GC_OCT22,                                    # the kind's baseline
            datetime(2026, 10, 31, 16, 0, tzinfo=UTC),
            GC_NOV1, GC_NOV1 + timedelta(minutes=15), GC_NOV1 + timedelta(hours=4),
            datetime(2026, 11, 2, 16, 0, tzinfo=UTC),
            GC_NOV12, GC_NOV12 + timedelta(minutes=15)])
        self.assertEqual(len(texts), 2, texts)
        ids = [x["_id"] for x in db.whatsapp_notification_ledger.rows
               if x.get("kind") == "gc_dot_embargo"]
        self.assertEqual(sorted(ids), [
            f"gc:proj_a:dot_embargo:dotpermit:{NO_WAIVER_NUM}:embargo:2026:2026-11-01",
            f"gc:proj_a:dot_embargo:dotpermit:{NO_WAIVER_NUM}:embargo:2026:2026-11-12"])
        for t in texts:
            self.assertTrue(t.startswith("🟠 "), t)
            self.assertIn("Holiday embargo: this DOT permit has no waiver", t)
            self.assertIn(ACTION_EN, t)
            self.assertIn(ACTION_ES, t)
            self.assertLess(t.index(ACTION_EN), t.index(ACTION_ES))
            self.assertIn(f"DOT permit #{NO_WAIVER_NUM}", t)
            self.assertIn("Source: DOT", t)

    def test_with_the_waiver_or_unknown_nothing_posts(self):
        for waiver in (True, None):
            db = _gc_world(dot_logs=[_gc_permit(waiver=waiver)])
            self.assertEqual(self._ticks(db, [GC_OCT22, GC_NOV1, GC_NOV12]), [], waiver)

    def test_nothing_posts_before_the_first_dot_pass(self):
        from lib import source_sync
        state = synced_state("proj_a", ("proj_a", CO_A), sources=source_sync.DOB_SOURCES)
        db = _gc_world(dot_logs=[_gc_permit()], source_sync_state=[state])
        self.assertEqual(self._ticks(db, [GC_OCT22, GC_NOV1]), [])
        # The pass completes on Nov 1: Nov 1's post still goes (a dated
        # reminder is not a backlog the baseline hides).
        # Stamped in the past of the WALL CLOCK: the tick dates the kind's
        # baseline marker with datetime.now(), and a marker older than the
        # first sync is re-baselined on every tick.
        done = datetime(2026, 10, 1, tzinfo=UTC)
        db.source_sync_state.rows[0]["sources"]["dot_permits"] = {
            "first_synced_at": done, "synced_at": done}
        texts = self._ticks(db, [GC_NOV1 + timedelta(minutes=15),
                                 GC_NOV1 + timedelta(minutes=30),
                                 GC_NOV1 + timedelta(minutes=45)])
        self.assertEqual(len(texts), 1, texts)
        self.assertIn(ACTION_EN, texts[0])

    def test_the_dot_permit_switch_gates_it(self):
        db = _gc_world(dot_logs=[_gc_permit()])
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._set_whatsapp_project_fields(
                "proj_a", CO_A, {"dot_permit_alerts": False}))
            for t in (GC_OCT22, GC_NOV1):
                _run(server._gc_alerts_tick(t))
            self.assertEqual([x for x in _group_sends(c) if "embargo" in x["message"]], [])
        self.assertTrue(any(x.get("kind") == "gc_dot_embargo" and x.get("status") == "seen_while_off"
                            for x in db.whatsapp_notification_ledger.rows))


class TheBannerStrings(unittest.TestCase):
    """The banner's coverage note was REMOVED by DOT Phase 1 B (segment permits
    are matched now): gone from the catalogue SOURCE, EN and ES, and from the
    screen (the node i18n test checks the EN/ES keys are identical)."""

    FE = Path(__file__).resolve().parents[2] / "frontend"

    def _ns(self, name):
        src = (self.FE / "src" / "i18n" / name).read_text(encoding="utf-8")
        i = src.index("dotEmbargo: {")
        return src[i:src.index("},", i)]

    def test_the_coverage_note_is_gone_from_en_and_es(self):
        for name, line in (("en.js", COVERAGE_EN), ("es.js", COVERAGE_ES)):
            self.assertIn("banner:", self._ns(name))          # the namespace was read
            self.assertNotIn("coverageNote:", self._ns(name), name)
            cat = (self.FE / "src" / "i18n" / name).read_text(encoding="utf-8")
            self.assertTrue(line not in cat, f"the coverage note is still in {name}")

    BANNER = "{(embargoMissing.length > 0 || embargoUnverified.length > 0) && ("

    def _banner(self):
        src = (self.FE / "app" / "project" / "[id]" / "dob-logs.jsx").read_text(encoding="utf-8")
        i = src.index(self.BANNER)
        return src, src[i:src.index("</GlassCard>", i)]

    def test_the_banner_no_longer_shows_it(self):
        # DOT Phase 1 B removed the coverage note; the banner (and its
        # "Waiver not verified" line, below) stays.
        src, banner = self._banner()
        self.assertIn("tEmbargo('action')", banner)
        self.assertTrue("tEmbargo('coverageNote')" not in src, "dob-logs.jsx still renders coverageNote")

    def test_waiver_not_verified_is_in_en_and_es(self):
        en, es = self._ns("en.js"), self._ns("es.js")
        self.assertIn("unverified: 'Waiver not verified: {list}'", en)
        self.assertIn("unverified: 'Exención no verificada: {list}'", es)
        self.assertIn("unverifiedTitle: 'Holiday embargo Nov 15 – Jan 2: check these permits'", en)
        self.assertIn("unverifiedTitle: 'Embargo navideño del 15 de nov al 2 de ene: revise estos permisos'", es)

    def test_the_banner_lists_the_unverified_permits_from_the_endpoints_unknown(self):
        src, banner = self._banner()
        self.assertIn("embargo.unknown.filter((p) => p && p.number)", src)
        self.assertIn("tEmbargo('unverified').replace('{list}', embargoUnverified.map((p) => p.number)",
                      banner)
        self.assertIn("tEmbargo('unverifiedTitle')", banner)
        self.assertIn("tEmbargo('action')", banner)


class TheEndpoint(unittest.TestCase):

    PATH = "/api/projects/{project_id}/dot/embargo"

    def test_registered_behind_project_access(self):
        route = next((r for r in server.api_router.routes
                      if getattr(r, "path", "") == self.PATH and "GET" in r.methods), None)
        self.assertIsNotNone(route, "route not on api_router")
        calls = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        self.assertIn("require_project_access", calls)
        self.assertIn("get_current_user", calls)

    def test_answers_from_the_projects_rows(self):
        _need()
        env = _Env()
        env.sync([REAL_PERMIT, NO_WAIVER_PERMIT],
                 {"M022026294C45": REAL_STIPS, NO_WAIVER_NUM: NO_WAIVER_STIPS})
        env.db.dot_logs.docs.append({**env.row(NO_WAIVER_NUM), "_id": "other",
                                     "project_id": "p2", "number": "OTHER1"})
        with patch.object(server, "db", env.db), \
                patch.object(server.dot_embargo, "ny_date", lambda _v: date(2026, 11, 20)):
            got = _run(server.get_dot_embargo("p1", current_user={}, project=env.db.projects.docs[0]))
        self.assertTrue(got["show"])
        self.assertEqual([p["number"] for p in got["missing_waiver"]], [NO_WAIVER_NUM])

    def test_answers_unverified_when_every_read_failed(self):
        _need()
        env = _Env()
        env.sync([NO_WAIVER_PERMIT], {})                       # every read failed
        with patch.object(server, "db", env.db), \
                patch.object(server.dot_embargo, "ny_date", lambda _v: date(2026, 11, 20)):
            got = _run(server.get_dot_embargo("p1", current_user={}, project=env.db.projects.docs[0]))
        self.assertTrue(got["show"])
        self.assertEqual(got["missing_waiver"], [])
        self.assertEqual([p["number"] for p in got["unknown"]], [NO_WAIVER_NUM])


if __name__ == "__main__":
    unittest.main()
