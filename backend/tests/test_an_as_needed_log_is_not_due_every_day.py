"""ZERO WORKERS ANYWHERE WERE WAITING FOR AN ORIENTATION, AND ALL THREE CPs
SAW A PENDING TILE.

── THE DEFECT, AND IT IS A NUMBER ──────────────────────────────────────────

`subcontractor_orientation` is declared `frequency: "as_needed"` in
LOGBOOK_TYPE_REGISTRY. It is due for one reason: a worker checked in on this
project and has no orientation on it.

`get_required_logbooks` never reads `frequency` -- it resolves the required set
from `applicable_classes` and `conditional` and nothing else -- so the type
came back on every project every day. The CP's logbook list then asked
`todayLogs["subcontractor_orientation"]`, which is a by-DATE read, and got
"pending". The completion bar counted it, so the operator read 4/6 where the
sixth item was not due at all.

MEASURED READ-ONLY ACROSS ALL THREE ACTIVE PROJECTS:

    8 Walworth      0 checked-in workers,  0 orientations
    588 Thomas     63 checked-in workers, 65 oriented
    857 Prescott   13 checked-in workers, 13 oriented

Not one worker is uncovered. The log is not due anywhere, and it read Pending
everywhere.

── REQUIRED IS NOT DUE ─────────────────────────────────────────────────────

THE TYPE STAYS IN THE REQUIRED SET. test_required_logbooks_model.py asserts it
is unconditionally resolved for every §3310 class, and that is still correct:
the project must keep this logbook. What changes is whether it is due TODAY,
which is a different question and is answered on the `periods` channel that
`toolbox_talk` already crosses the wire on.

── WHAT IT IS NOT ──────────────────────────────────────────────────────────

It is NOT a cadence. The row's `period_start` and `period_end` are None on
purpose; `_logbook_periods` previously refused to emit the row at all on the
reasoning that "inventing a period for it would be this function asserting a
cadence nobody has defined", and that reasoning is preserved -- what the row
asserts is coverage, not an elapsed period.

It is NOT `unsigned_orientations`, which counts orientation LOGS that exist
and are unsigned. A project can have zero of those and still owe an
orientation to a man who has none.

It is NOT a rule about `hot_work`. Hot work is as_needed too and reads Pending
forever on 8 Walworth for the same shape of reason, but NO SERVER RULE DEFINES
WHEN A HOT-WORK PERMIT LOG IS DUE and this change does not invent one. The
last class here asserts that no row is emitted for it.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from lib.logbook.orientation_cadence import (  # noqa: E402
    NAME_LIMIT,
    WORKER_NOT_ORIENTED,
    as_ids,
    orientation_period,
    uncovered_workers,
)
from tests.source_text import code_of  # noqa: E402

PROJECT = "588thomas"


# ── THE RULE, WITH NO DATABASE ANYWHERE NEAR IT ────────────────────────────

class ItIsDueWhenSomebodyNeedsIt(unittest.TestCase):

    def test_nobody_checked_in_is_nothing_to_do(self):
        """8 Walworth: no workers, no orientations, and the tile was red."""
        row = orientation_period([], [], [])
        self.assertTrue(row["satisfied"])
        self.assertIsNone(row["due_reason"])
        self.assertEqual(row["uncovered_worker_count"], 0)

    def test_everybody_oriented_is_nothing_to_do(self):
        """857 Prescott: 13 checked in, 13 oriented."""
        ids = [f"w{i}" for i in range(13)]
        row = orientation_period(ids, ids, [])
        self.assertTrue(row["satisfied"])

    def test_one_uncovered_worker_makes_it_due(self):
        row = orientation_period(["w1", "w2"], ["w1"], [])
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], WORKER_NOT_ORIENTED)
        self.assertEqual(row["uncovered_worker_count"], 1)
        self.assertEqual(row["uncovered_workers"], ["w2"])

    def test_the_embedded_list_counts_as_coverage_on_its_own(self):
        """`workers.safety_orientations[]` predates the orientation LOGBOOK and
        still holds live rows. A man covered only there is oriented."""
        row = orientation_period(["w1"], [], ["w1"])
        self.assertTrue(row["satisfied"])

    def test_the_logbook_counts_as_coverage_on_its_own(self):
        row = orientation_period(["w1"], ["w1"], [])
        self.assertTrue(row["satisfied"])

    def test_covered_by_EITHER_not_by_both(self):
        """Requiring both records would re-open the log for every worker
        oriented before one of the two writers existed."""
        row = orientation_period(["w1", "w2"], ["w1"], ["w2"])
        self.assertTrue(row["satisfied"])

    def test_ids_are_compared_as_strings(self):
        """`checkins.worker_id` is a string and `workers._id` is an ObjectId.
        Comparing the raw shapes reports EVERY worker uncovered and turns a
        permanently-green tile into a permanently-red one."""
        class _Oid:
            def __init__(self, v):
                self.v = v

            def __str__(self):
                return self.v

        row = orientation_period(["507f1f77bcf86cd799439011"], [],
                                 [_Oid("507f1f77bcf86cd799439011")])
        self.assertTrue(row["satisfied"])

    def test_blank_ids_are_not_workers(self):
        self.assertEqual(as_ids([None, "", "  ", "w1"]), {"w1"})
        self.assertTrue(orientation_period(["", None], [], [])["satisfied"])

    def test_it_names_the_men(self):
        row = orientation_period(["w1", "w2"], [], [],
                                 names={"w1": "Andre Duval"})
        self.assertFalse(row["satisfied"])
        # A name where one is known, the id where none is -- never a blank.
        self.assertEqual(row["uncovered_workers"], ["Andre Duval", "w2"])

    def test_the_name_list_is_capped_but_the_count_is_not(self):
        """The one surface that renders this is a line under a tile on a
        phone. The reason is a sentence, not a roster export."""
        ids = [f"w{i:03d}" for i in range(NAME_LIMIT + 5)]
        row = orientation_period(ids, [], [])
        self.assertEqual(len(row["uncovered_workers"]), NAME_LIMIT)
        self.assertEqual(row["uncovered_worker_count"], NAME_LIMIT + 5)

    def test_it_asserts_NO_cadence(self):
        """An as-needed log has no period. Putting today's date in these
        fields would be the invention `_logbook_periods` refused to make."""
        for row in (orientation_period([], [], []),
                    orientation_period(["w1"], [], [])):
            self.assertIsNone(row["period_start"])
            self.assertIsNone(row["period_end"])
            self.assertEqual(row["filed_on"], [])

    def test_the_weekly_rules_field_is_left_empty(self):
        """`uncovered_weekend_workers` belongs to the toolbox rule. The client
        that reads it must not find something else in it."""
        row = orientation_period(["w1"], [], [])
        self.assertEqual(row["uncovered_weekend_workers"], [])

    def test_the_shape_matches_the_weekly_row(self):
        """Same keys the client already renders, so `periods` carries a second
        type with no new payload."""
        from lib.logbook.weekly_cadence import toolbox_period
        weekly = toolbox_period("2026-09-16", ["2026-09-15"], [], [])
        orient = orientation_period(["w1"], ["w1"], [])
        self.assertTrue(set(weekly).issubset(set(orient)))

    def test_uncovered_workers_is_exported_for_the_caller(self):
        """The server looks the names up from THIS, not from a row that has
        already substituted them -- a row falls back to the id where no name
        is known, and reading those back would be reading its own default."""
        self.assertEqual(uncovered_workers(["w1", "w2"], ["w1"], []), ["w2"])


# ── THE SAME RULE, REACHED THROUGH THE REAL ENDPOINT HELPER ────────────────

def _get(doc, path):
    """A dotted field read, so `data.worker_id` resolves the way Mongo does."""
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            out = [_get(c, part) for c in cur]
            return [v for v in out if v is not None]
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc, query):
    for k, v in (query or {}).items():
        got = _get(doc, k)
        if isinstance(v, dict):
            if "$ne" in v:
                vals = got if isinstance(got, list) else [got]
                if v["$ne"] in vals:
                    return False
            if "$in" in v:
                vals = got if isinstance(got, list) else [got]
                if not any(x in v["$in"] for x in vals):
                    return False
            continue
        vals = got if isinstance(got, list) else [got]
        if v not in vals:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield copy.deepcopy(d)
        return gen()

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self):
        self.docs = []
        self.reads = 0

    def find(self, query=None, projection=None):
        self.reads += 1
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def distinct(self, field, query=None):
        self.reads += 1
        out = []
        for d in self.docs:
            if not _match(d, query or {}):
                continue
            v = _get(d, field)
            for item in (v if isinstance(v, list) else [v]):
                if item is not None and item not in out:
                    out.append(item)
        return out


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]

    @property
    def reads(self):
        return sum(c.reads for c in self._c.values())


class TheEndpointHelperAnswersIt(unittest.TestCase):
    """`_logbook_periods` is what the payload calls. These drive it."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.checkins.docs = [
            {"project_id": PROJECT, "worker_id": "w1"},
            {"project_id": PROJECT, "worker_id": "w1"},   # same man, day two
            {"project_id": PROJECT, "worker_id": "w2"},
            {"project_id": "other", "worker_id": "w9"},   # another project
        ]
        self.db.logbooks.docs = []
        self.db.workers.docs = [
            {"_id": "w1", "name": "Andre Duval"},
            {"_id": "w2", "name": "Marcus Reilly"},
        ]
        self._orig_db, self._orig_tq = S.db, S.to_query_id
        S.db = self.db
        S.to_query_id = lambda x: x

    def tearDown(self):
        S.db, S.to_query_id = self._orig_db, self._orig_tq
        self.loop.close()

    def periods(self, required=("subcontractor_orientation",)):
        rows = self.loop.run_until_complete(
            S._logbook_periods(PROJECT, list(required)))
        return {r["log_type"]: r for r in rows}

    def orient(self, worker_id, *, by_logbook=True):
        if by_logbook:
            self.db.logbooks.docs.append({
                "project_id": PROJECT,
                "log_type": "subcontractor_orientation",
                "data": {"worker_id": worker_id},
            })
        else:
            for w in self.db.workers.docs:
                if w["_id"] == worker_id:
                    w.setdefault("safety_orientations", []).append(
                        {"project_id": PROJECT})

    # ── the row exists at all ──────────────────────────────────────────────

    def test_a_row_is_emitted_for_the_orientation(self):
        """The whole defect in one assertion: there was no row, so the screen
        kept its by-date answer and the tile said Pending."""
        self.assertIn("subcontractor_orientation", self.periods())

    def test_two_uncovered_workers_make_it_due_and_it_names_them(self):
        row = self.periods()["subcontractor_orientation"]
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], WORKER_NOT_ORIENTED)
        self.assertEqual(row["uncovered_worker_count"], 2)
        self.assertEqual(sorted(row["uncovered_workers"]),
                         ["Andre Duval", "Marcus Reilly"])

    def test_orienting_everybody_satisfies_it(self):
        self.orient("w1")
        self.orient("w2", by_logbook=False)
        row = self.periods()["subcontractor_orientation"]
        self.assertTrue(row["satisfied"])
        self.assertIsNone(row["due_reason"])

    def test_a_DRAFT_orientation_still_counts(self):
        """The CP's signature is what `unsigned_orientations` is for. Treating
        an unsigned orientation as no orientation would tell him to orient a
        man he has already oriented."""
        self.orient("w1")
        self.orient("w2")
        self.db.logbooks.docs[0]["status"] = "draft"
        self.assertTrue(self.periods()["subcontractor_orientation"]["satisfied"])

    def test_another_projects_orientation_does_not_count(self):
        self.db.logbooks.docs.append({
            "project_id": "other", "log_type": "subcontractor_orientation",
            "data": {"worker_id": "w1"},
        })
        self.db.workers.docs[1]["safety_orientations"] = [
            {"project_id": "other"}]
        self.assertFalse(self.periods()["subcontractor_orientation"]["satisfied"])

    def test_a_deleted_checkin_is_not_a_worker_on_site(self):
        self.orient("w1")
        self.db.checkins.docs[2]["is_deleted"] = True
        self.assertTrue(self.periods()["subcontractor_orientation"]["satisfied"])

    def test_a_deleted_orientation_does_not_cover_him(self):
        self.orient("w1")
        self.orient("w2")
        self.db.logbooks.docs[1]["is_deleted"] = True
        self.assertFalse(self.periods()["subcontractor_orientation"]["satisfied"])

    # ── what it costs ──────────────────────────────────────────────────────

    def test_it_is_three_reads_when_satisfied_and_none_per_worker(self):
        """This runs on a SCREEN LOAD. Four workers, three reads -- and the
        number does not move when the roster does."""
        self.orient("w1")
        self.orient("w2")
        self.periods()
        self.assertEqual(self.db.reads, 3)

        for i in range(40):
            self.db.checkins.docs.append(
                {"project_id": PROJECT, "worker_id": f"x{i}"})
            self.orient(f"x{i}")
        for c in self.db._c.values():
            c.reads = 0
        self.periods()
        self.assertEqual(self.db.reads, 3)

    def test_the_name_lookup_is_ONE_extra_read_only_when_it_is_due(self):
        self.periods()
        self.assertEqual(self.db.reads, 4)

    def test_a_project_with_no_checkins_is_answered_in_ONE_read(self):
        """8 Walworth. With nobody on the list the difference is taken from,
        the other two reads could only return men who are not in it."""
        self.db.checkins.docs = []
        row = self.periods()["subcontractor_orientation"]
        self.assertTrue(row["satisfied"])
        self.assertEqual(self.db.reads, 1)

    def test_the_worker_read_is_bounded_by_the_checked_in_set(self):
        """A worker oriented here who has never checked in is not an answer to
        the question. Narrowing the read to the check-in set lets it ride the
        `_id` index and cannot change the result."""
        self.db.workers.docs.append({
            "_id": "ghost", "name": "Never Arrived",
            "safety_orientations": [{"project_id": PROJECT}],
        })
        self.orient("w1")
        self.orient("w2")
        row = self.periods()["subcontractor_orientation"]
        self.assertTrue(row["satisfied"])
        self.assertEqual(row["uncovered_worker_count"], 0)

    def test_it_costs_nothing_when_the_type_is_not_required(self):
        self.periods(required=["daily_jobsite", "osha_log"])
        self.assertEqual(self.db.reads, 0)

    def test_the_toolbox_read_is_not_paid_for_by_an_orientation_project(self):
        """Each type's reads sit behind its own membership test."""
        self.orient("w1")
        self.orient("w2")
        self.periods(required=["subcontractor_orientation"])
        self.assertEqual(self.db.logbooks.reads, 1)

    # ── failing does not take the screen down ──────────────────────────────

    def test_a_broken_read_costs_the_row_and_not_the_list(self):
        class _Boom(_Coll):
            async def distinct(self, *a, **k):
                raise RuntimeError("mongo is having a day")

        boom = _Boom()
        boom.docs = self.db.checkins.docs
        self.db._c["checkins"] = boom
        self.assertEqual(self.periods(), {})

    def test_a_broken_name_lookup_still_leaves_the_row_due(self):
        """A missing name is not a missing obligation."""
        class _Coll2(_Coll):
            def find(self, *a, **k):
                raise RuntimeError("no")

        w = _Coll2()
        w.docs = self.db.workers.docs
        self.db._c["workers"] = w
        row = self.periods()["subcontractor_orientation"]
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["uncovered_worker_count"], 2)


class HotWorkIsLeftAlone(unittest.TestCase):
    """`hot_work` HAS THE IDENTICAL DEFECT and is deliberately not fixed here.

    It is `frequency: "as_needed"`, gated only by the `hot_work_permitted`
    toggle, and 8 Walworth has that toggle on -- so its tile reads Pending
    forever there, exactly as the orientation tile did.

    NOBODY HAS DEFINED WHEN A HOT-WORK PERMIT LOG IS DUE. Inventing that rule
    here would be this change asserting an obligation the operator has never
    stated, which is the failure the orientation row goes out of its way to
    avoid. It needs a ruling, and until then hot_work behaves EXACTLY as it did
    before: a tile on the list and an entry in the denominator.

    The client predicate keys on `frequency === 'as_needed'`, so the only thing
    standing between hot_work and being silently hidden is that no row is
    emitted for it. That is asserted here rather than left to be noticed.
    """

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.checkins.docs = [{"project_id": PROJECT, "worker_id": "w1"}]
        self._orig_db, self._orig_tq = S.db, S.to_query_id
        S.db = self.db
        S.to_query_id = lambda x: x

    def tearDown(self):
        S.db, S.to_query_id = self._orig_db, self._orig_tq
        self.loop.close()

    def test_no_period_row_is_emitted_for_hot_work(self):
        rows = self.loop.run_until_complete(S._logbook_periods(
            PROJECT, ["hot_work", "subcontractor_orientation"]))
        self.assertEqual([r["log_type"] for r in rows],
                         ["subcontractor_orientation"])

    def test_hot_work_alone_costs_nothing_and_says_nothing(self):
        rows = self.loop.run_until_complete(
            S._logbook_periods(PROJECT, ["hot_work"]))
        self.assertEqual(rows, [])
        self.assertEqual(self.db.reads, 0)

    def test_it_is_still_unconditionally_required_when_the_toggle_is_on(self):
        """Nothing about the required SET changed for it, or for the
        orientation. See the note in test_required_logbooks_model.py."""
        got = set(S.get_required_logbooks("regular", {"hot_work_permitted": True}))
        self.assertIn("hot_work", got)
        self.assertIn("subcontractor_orientation", got)


class TheScreenDropsASatisfiedAsNeededTile(unittest.TestCase):
    """The server half is useless without the client half, and the client half
    is one predicate. Asserted on the SOURCE because the behavioural test for
    it runs under node (requiredLogbooksWiring.test.cjs)."""

    def setUp(self):
        # code_of strips comments and docstrings. This file's own prose names
        # every symbol below, and so does the screen's -- the trap
        # tests/source_text.py exists for.
        self.screen = code_of("frontend/app/logbooks/index.jsx")
        self.cadence = code_of("frontend/src/utils/logbookCadence.js")

    def test_the_predicate_keys_on_the_frequency(self):
        self.assertIn("as_needed", self.screen)
        self.assertIn("periodSatisfied(periods, t.key) === true", self.screen)

    def test_it_is_not_a_client_side_list_of_log_types(self):
        """A hardcoded key here is the 'second model' getVisibleLogTypes was
        rewritten to stop being."""
        fn = self.screen[self.screen.index("const getVisibleLogTypes"):]
        fn = fn[:fn.index("\n  };")]
        self.assertNotIn("subcontractor_orientation", fn)

    def test_the_label_does_not_call_an_as_needed_log_weekly(self):
        self.assertIn("row.frequency === 'as_needed'", self.cadence)


def _fn_block(src, name):
    """The body of one top-level function, ending at the NEXT top-level
    definition.

    NOT `\\n\\n\\n`. `code_of` strips comments and leaves the blank lines
    behind, so a commented block inside the function produces a run of blank
    lines and a boundary of three newlines ends the slice EIGHT LINES IN. Both
    assertions below then read a stub that happens not to contain what they
    are looking for -- one would have failed loudly and the assertNotIn one
    would have PASSED, vacuously. Caught by the loud half on the first run.
    """
    block = src[src.index(f"async def {name}"):]
    rest = block[1:]
    ends = [rest.index(m) for m in ("\nasync def ", "\ndef ", "\n@api_router")
            if m in rest]
    return block[:min(ends) + 1] if ends else block


class TheRuleIsWhereItCanBeTested(unittest.TestCase):

    def setUp(self):
        self.block = _fn_block(code_of("server.py"), "_orientation_period_rows")

    def test_the_slice_is_the_whole_function(self):
        """ANCHOR. Every assertion in this class reads `self.block`; a boundary
        that silently truncated it would make the absence tests say nothing."""
        self.assertGreater(len(self.block), 800)
        self.assertIn("return [orientation_period(", self.block)

    def test_the_server_holds_no_second_copy_of_it(self):
        """The set arithmetic lives in lib/logbook/orientation_cadence.py. A
        difference recomputed in server.py would be a second model."""
        block = self.block
        self.assertIn("orientation_period(", block)
        self.assertNotIn(") - set(", block)

    def test_the_reads_are_distinct_calls_and_not_a_loop(self):
        block = self.block
        self.assertIn('db.checkins.distinct(', block)
        self.assertIn('db.logbooks.distinct(', block)
        self.assertIn('db.workers.distinct(', block)
        # A find_one inside a loop is the shape this must never take.
        self.assertNotIn("find_one", block)
        # One `find`, and it is the name lookup over the uncovered set.
        self.assertEqual(block.count("db.workers.find("), 1)

    # `"periods": await _logbook_periods(` is NOT asserted here. It is already
    # held by test_a_weekly_log_is_not_due_every_day.py, and repeating it in
    # this class would put it behind a setUp that cannot run until the function
    # exists — so on a control run it would report as a failure caused by the
    # fixture rather than by the thing it checks. An assertion whose result is
    # decided by its neighbour's setUp is not an instrument.


if __name__ == "__main__":
    unittest.main(verbosity=2)
