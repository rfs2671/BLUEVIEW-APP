"""LL196 attestation — WHICH MEN THE FILING NAMES.

THE DEFECT THESE PIN. `generate_ll196_attestation` enumerated the roster with

    db.workers.find({"project_id": project_id, "is_deleted": {"$ne": True}})

and `workers` documents have no top-level `project_id`. Not one of the three
writers sets it (server.py:13905 register_and_checkin nests it inside
`safety_orientations[]`; server.py:14707 submit_checkin writes none;
server.py:15574 POST /workers builds from WorkerCreate, which has no such
field), the PATCH allow-list excludes it (server.py ALLOWED_WORKER_FIELDS), and
server.py:12293 states the design outright: "workers are NOT project-scoped —
one worker spans many projects." So the query matched nothing, always, and the
statutory filing rendered "All 0 workers in good standing" over an empty table
with status=complete. A clean pass, not a visible break.

WHY THE OLD TESTS WERE GREEN. `TestLL196Orchestrator` in test_v2_0_logbook.py
stubs `db.workers.find` with a MagicMock that IGNORES its filter and returns a
fixed list. Any query would have passed it, including one that matches nothing.
The fake below HONOURS the filter, which is the only way a test can tell a live
query from a dead one.

THE POPULATION. Every worker with a check-in on this project inside the
attestation month, in Eastern time. Argued in full in the report; in short:
LL196 attests that every worker ON SITE held a current SST card, `checkins` is
the only record written unconditionally for every worker on every visit, and
the same subsystem already defines "was anyone on this project" that way
(scripts/correct_missing_daily_log_flags.py::_day_had_gate_activity).

EVERY EXCLUSION TEST HERE ALSO ASSERTS AN INCLUSION. An empty roster excludes
everybody, so a bare "worker X is absent" assertion is green against the dead
query by construction and proves nothing. Each test below names a man who must
be there alongside the man who must not.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.logbook import ll196  # noqa: E402
from lib.logbook import schema as logbook_schema  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# A fake that HONOURS the query. The whole point.
# ──────────────────────────────────────────────────────────────────


def _match_op(value, op, operand) -> bool:
    if op == "$ne":
        return value != operand
    if op == "$in":
        return value in operand
    if op == "$nin":
        return value not in operand
    if op == "$gte":
        return value is not None and value >= operand
    if op == "$gt":
        return value is not None and value > operand
    if op == "$lte":
        return value is not None and value <= operand
    if op == "$lt":
        return value is not None and value < operand
    if op == "$exists":
        return (value is not None) == bool(operand)
    raise AssertionError(f"fake db does not implement operator {op!r}")


def _matches(doc: dict, filt: dict) -> bool:
    for field, cond in (filt or {}).items():
        if field in ("$and", "$or"):
            subs = [_matches(doc, s) for s in cond]
            if (all(subs) if field == "$and" else any(subs)) is False:
                return False
            continue
        value = doc.get(field)
        if isinstance(cond, dict) and cond and all(
                k.startswith("$") for k in cond):
            for op, operand in cond.items():
                if not _match_op(value, op, operand):
                    return False
        elif value != cond:
            return False
    return True


def _project(doc: dict, projection) -> dict:
    if not projection:
        return dict(doc)
    include = {k for k, v in projection.items() if v and k != "_id"}
    if not include:
        return dict(doc)
    out = {k: v for k, v in doc.items() if k in include}
    if projection.get("_id", 1):
        out["_id"] = doc.get("_id")
    return out


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        if n is not None and n >= 0:
            self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    def to_list(self, n=None):
        async def _c():
            return self._docs[:n] if (n is not None and n >= 0) else self._docs
        return _c()


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.update_one_calls = []

    def find(self, filt=None, projection=None):
        hits = [_project(d, projection) for d in self.docs if _matches(d, filt)]
        return _Cursor(hits)

    async def find_one(self, filt=None, projection=None):
        for d in self.docs:
            if _matches(d, filt):
                return _project(d, projection)
        return None

    async def update_one(self, filt, update, upsert=False):
        self.update_one_calls.append((filt, update, upsert))
        class _R:
            upserted_id = "x"
        return _R()


class _DB:
    def __init__(self, **collections):
        self._c = {name: _Collection(docs)
                   for name, docs in collections.items()}
        self._c.setdefault("logbook_entries", _Collection([]))

    # Motor exposes collections by BOTH attribute and item access, and this
    # module uses each (`db.checkins`, `db[_WORKER_PROJECT_TRADES]`). A fake
    # supporting only one turns a live query into a swallowed exception.
    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        c = self.__dict__.get("_c", {})
        if name not in c:
            c[name] = _Collection([])
        return c[name]


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

PROJECT = {"_id": "p1", "name": "857 Prescott", "company_id": "co_a"}

# May 2026 in New York is EDT (UTC-4).
MAY_MID = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
APR_MID = datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

CURRENT_SST = [{"type": "SST_FULL", "expiration_date": "2027-01-01"}]


def _worker(wid, name, certs=None, **extra):
    d = {"_id": wid, "name": name, "certifications": certs or [],
         "is_deleted": False}
    d.update(extra)
    return d


def _checkin(wid, project_id, when, **extra):
    d = {"worker_id": str(wid), "project_id": project_id,
         "check_in_time": when, "is_deleted": False,
         "worker_trade": "Carpenter"}
    d.update(extra)
    return d


def _generate(db, *, project_id="p1", year=2026, month=5, now=NOW):
    captured = {}

    def _renderer(html):
        captured["html"] = html
        return b"%PDF-stub"

    entry = _run(ll196.generate_ll196_attestation(
        db, project_id=project_id, year=year, month=month,
        r2_uploader=lambda b, k, ct: f"https://r2/{k}",
        pdf_renderer=_renderer,
        now=now,
    ))
    return entry, captured.get("html", "")


def _names(entry):
    return sorted(r["name"] for r in entry["attestation_data"]["roster"])


class TestLL196Population(unittest.TestCase):
    """The register must CONTAIN the men who were on site."""

    def test_roster_contains_the_workers_who_checked_in_that_month(self):
        """THE ONE THAT COULD NOT PASS BEFORE. Against the dead query the
        roster is [] and worker_count is 0, so every assertion here fails."""
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w2", "Bruno Katz", CURRENT_SST),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                _checkin("w2", "p1", MAY_MID),
            ],
        )
        entry, html = _generate(db)
        data = entry["attestation_data"]

        self.assertEqual(_names(entry), ["Alice Rivera", "Bruno Katz"])
        self.assertEqual(data["worker_count"], 2)
        self.assertEqual(data["counts"]["current"], 2)
        self.assertEqual(data["overall_status"], logbook_schema.STATUS_COMPLETE)
        # And the men are actually printed on the document that gets filed.
        self.assertIn("Alice Rivera", html)
        self.assertIn("Bruno Katz", html)

    def test_a_worker_with_no_sst_card_is_named_as_missing(self):
        """The filing's whole purpose: naming the man who cannot be attested
        for. Vacuous against the dead query — an empty roster reports
        `complete`, so this is the assertion the shipped code inverted."""
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w2", "Bruno Katz", []),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                _checkin("w2", "p1", MAY_MID),
            ],
        )
        entry, html = _generate(db)
        data = entry["attestation_data"]

        self.assertEqual(data["counts"]["missing"], 1)
        self.assertEqual(data["overall_status"],
                         logbook_schema.STATUS_DEFICIENT)
        by_name = {r["name"]: r for r in data["roster"]}
        self.assertEqual(by_name["Bruno Katz"]["sst_status"], "missing")
        self.assertEqual(by_name["Alice Rivera"]["sst_status"], "current")
        self.assertIn("MISSING", html)
        self.assertEqual(entry["deficiency_reason"], data["summary"])

    def test_repeat_checkins_list_the_worker_once(self):
        db = _DB(
            projects=[PROJECT],
            workers=[_worker("w1", "Alice Rivera", CURRENT_SST)],
            checkins=[
                _checkin("w1", "p1", datetime(2026, 5, 4, 11, tzinfo=timezone.utc)),
                _checkin("w1", "p1", datetime(2026, 5, 5, 11, tzinfo=timezone.utc)),
                _checkin("w1", "p1", datetime(2026, 5, 6, 11, tzinfo=timezone.utc)),
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(_names(entry), ["Alice Rivera"])
        self.assertEqual(entry["attestation_data"]["worker_count"], 1)


class TestLL196PopulationBoundaries(unittest.TestCase):
    """Each of these names a man who MUST be listed alongside the one who
    must not, so none of them can go green on an empty roster."""

    def test_another_projects_worker_is_not_on_this_filing(self):
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w9", "Otherjob Ortiz", CURRENT_SST),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                _checkin("w9", "p2", MAY_MID),
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(_names(entry), ["Alice Rivera"])

    def test_a_worker_from_a_different_month_is_not_on_this_filing(self):
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w8", "Lastmonth Lopez", CURRENT_SST),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                _checkin("w8", "p1", APR_MID),
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(_names(entry), ["Alice Rivera"])

    def test_soft_deleted_checkin_and_soft_deleted_worker_drop_out(self):
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w7", "Deleted Worker", CURRENT_SST, is_deleted=True),
                _worker("w6", "Voided Checkin", CURRENT_SST),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                _checkin("w7", "p1", MAY_MID),
                _checkin("w6", "p1", MAY_MID, is_deleted=True),
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(_names(entry), ["Alice Rivera"])

    def test_month_boundary_is_eastern_not_utc(self):
        """A 21:30 EDT check-in on 31 May is 01:30 UTC on 1 June. It belongs
        to the MAY filing — the same Eastern boundary
        correct_missing_daily_log_flags._day_had_gate_activity uses, and the
        one entry_date was written on."""
        db = _DB(
            projects=[PROJECT],
            workers=[
                _worker("w1", "Alice Rivera", CURRENT_SST),
                _worker("w2", "Latenight Nunez", CURRENT_SST),
                _worker("w3", "Firstshift Pak", CURRENT_SST),
            ],
            checkins=[
                _checkin("w1", "p1", MAY_MID),
                # 2026-05-31 21:30 EDT
                _checkin("w2", "p1",
                         datetime(2026, 6, 1, 1, 30, tzinfo=timezone.utc)),
                # 2026-06-01 07:00 EDT — genuinely June.
                _checkin("w3", "p1",
                         datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)),
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(_names(entry), ["Alice Rivera", "Latenight Nunez"])


class TestLL196EmptyMonthIsNotAPass(unittest.TestCase):
    """A month with nobody on site must not file as `complete`.

    Same ruling the schema already carries for daily logs:
    STATUS_NO_SITE_ACTIVITY exists because "the log was not filed, and saying
    it was is the same false claim in the other direction"
    (lib/logbook/schema.py:58-66, scripts/correct_missing_daily_log_flags.py).
    "All 0 workers in good standing" is that false claim in a document filed
    with the City."""

    def test_no_checkins_does_not_report_good_standing(self):
        db = _DB(
            projects=[PROJECT],
            workers=[_worker("w1", "Alice Rivera", CURRENT_SST)],
            checkins=[_checkin("w1", "p1", APR_MID)],
        )
        entry, html = _generate(db)
        data = entry["attestation_data"]

        self.assertEqual(data["worker_count"], 0)
        self.assertEqual(data["overall_status"],
                         logbook_schema.STATUS_NO_SITE_ACTIVITY)
        self.assertNotIn("in good standing", data["summary"])
        self.assertNotIn("in good standing", html)
        # An empty month is not a deficiency either — nobody is being flagged.
        self.assertIsNone(entry["deficiency_reason"])
        self.assertEqual(entry["status"],
                         logbook_schema.STATUS_NO_SITE_ACTIVITY)
        self.assertIn(entry["status"], logbook_schema.VALID_STATUSES)


class TestLL196RosterTrade(unittest.TestCase):
    """The Trade column. `workers` documents deliberately carry no `trade`
    any more (server.py:14683 "no `trade` / `company` here. Those are
    per-project"), so `w.get("trade")` printed a blank cell for every man on
    the register. The per-project answer resolves the way server.py states it:
    frozen check-in value first, stored pairing second, `workers` never."""

    def test_trade_comes_from_the_frozen_checkin(self):
        db = _DB(
            projects=[PROJECT],
            workers=[_worker("w1", "Alice Rivera", CURRENT_SST)],
            checkins=[_checkin("w1", "p1", MAY_MID, worker_trade="Ironworker")],
        )
        entry, html = _generate(db)
        self.assertEqual(entry["attestation_data"]["roster"][0]["trade"],
                         "Ironworker")
        self.assertIn("Ironworker", html)

    def test_unassigned_falls_through_to_the_stored_pairing(self):
        db = _DB(
            projects=[PROJECT],
            workers=[_worker("w1", "Alice Rivera", CURRENT_SST)],
            checkins=[_checkin("w1", "p1", MAY_MID,
                               worker_trade="UNASSIGNED")],
            worker_project_trades=[
                {"worker_id": "w1", "project_id": "p1", "trade": "Laborer"},
            ],
        )
        entry, _ = _generate(db)
        self.assertEqual(entry["attestation_data"]["roster"][0]["trade"],
                         "Laborer")

    def test_no_trade_anywhere_renders_blank_never_the_worker_document(self):
        """A worker-level `trade` is a value from some other job. Blank is
        correct; the other project's answer is silently wrong."""
        db = _DB(
            projects=[PROJECT],
            workers=[_worker("w1", "Alice Rivera", CURRENT_SST,
                             trade="StaleFromAnotherJob")],
            checkins=[_checkin("w1", "p1", MAY_MID,
                               worker_trade="UNASSIGNED")],
        )
        entry, html = _generate(db)
        self.assertEqual(entry["attestation_data"]["roster"][0]["trade"], "")
        self.assertNotIn("StaleFromAnotherJob", html)


class TestLL196SharedNames(unittest.TestCase):
    """`_WORKER_PROJECT_TRADES` is a copy of a server.py constant, held here
    because server.py imports this module and the dependency cannot run both
    ways (see lib/cert_vocab.py). A copy that nothing pins is how
    `_SST_CERT_TYPES` drifted to three members against the canonical four, so
    this pins it."""

    def test_collection_name_matches_server(self):
        import server
        self.assertEqual(ll196._WORKER_PROJECT_TRADES,
                         server.WORKER_PROJECT_TRADES_COLLECTION)

    def test_display_trade_agrees_with_recorded_trade(self):
        """`_display_trade` is a second copy of server.py's `_recorded_trade`,
        for the same import-cycle reason. Pinned on every shape that
        distinguishes them."""
        import server
        for v in ("UNASSIGNED", "unassigned", " Unassigned ", "Carpenter",
                  "  Ironworker  ", "", None, 0):
            self.assertEqual(ll196._display_trade(v),
                             server._recorded_trade(v),
                             f"diverged on {v!r}")


class TestLL196MonthWindow(unittest.TestCase):

    def test_window_is_eastern_and_half_open(self):
        start, end = ll196._month_utc_window(2026, 5)
        # 2026-05-01 00:00 EDT == 04:00 UTC
        self.assertEqual(start, datetime(2026, 5, 1, 4, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 6, 1, 4, tzinfo=timezone.utc))

    def test_december_rolls_the_year(self):
        start, end = ll196._month_utc_window(2026, 12)
        # EST (UTC-5) in December.
        self.assertEqual(start, datetime(2026, 12, 1, 5, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2027, 1, 1, 5, tzinfo=timezone.utc))

    def test_march_dst_transition_month(self):
        # DST starts 2026-03-08; the month still begins on EST and ends on EDT.
        start, end = ll196._month_utc_window(2026, 3)
        self.assertEqual(start, datetime(2026, 3, 1, 5, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 4, 1, 4, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
