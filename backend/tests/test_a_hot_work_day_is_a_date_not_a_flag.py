"""8 WALWORTH'S HOT-WORK TILE READ PENDING EVERY MORNING AND WOULD HAVE
FOREVER.

── THE DEFECT ──────────────────────────────────────────────────────────────

`hot_work` is declared `frequency: "as_needed"` in LOGBOOK_TYPE_REGISTRY and
was gated by ONE persistent project boolean, `hot_work_permitted`. Nothing
answered whether the log was DUE, so the CP's logbook list fell back to a
by-DATE read of `todayLogs["hot_work"]`, got "pending", and the completion bar
counted it. 8 Walworth has that toggle on. Welding or no welding, the tile was
red -- and no amount of filing could ever make it green tomorrow.

This is the identical defect #611 fixed for `subcontractor_orientation`. Hot
work was deliberately left alone there, and the class `HotWorkIsLeftAlone` in
test_an_as_needed_log_is_not_due_every_day.py says why: NOBODY HAD DEFINED WHEN
A HOT-WORK PERMIT LOG IS DUE, and inventing that rule would have been asserting
an obligation the operator never stated.

── THE RULING, AND IT IS TWO FACTS ─────────────────────────────────────────

    "Hot work: due only on days hot work happens. CP or super toggles it on
     for that day. Dated, not persistent."

    "hot_work_permitted stays as the admin's standing permit statement (the
     FDNY permit and certificate of fitness are paper he holds). The dated
     toggle is the CP/super declaring hot work happened that day, and it's
     only available on a project where the standing field is on. No permit,
     no day."

So the two facts are LAYERED and are not the same fact stored twice:

    projects.hot_work_permitted    this site MAY do hot work. Standing,
                                   admin's, still the registry `conditional`.
    hot_work_days (project, date)  hot work IS happening on this day. Dated,
                                   the CP's or the superintendent's.

THE STANDING FIELD ALONE NEVER MAKES THE LOG DUE. That is the entire defect,
and `EightWalworthsExactShape` below is the production case that prompted this.

── WHAT THIS IS NOT ────────────────────────────────────────────────────────

It is NOT a CP-settable version of the old boolean. That would reproduce the
bug: left on, Pending forever again. A date expires because tomorrow's read
asks about tomorrow, not because anybody switched anything off.

It is NOT a weakening of the client's fail-open guard. A type the server says
nothing about still keeps its tile -- `TheFailOpenPropertyIsUntouched` pins
that on a type with no rule. Hot work stopped needing the silence by acquiring
a rule.

It is NOT a change to `subcontractor_orientation`. `TheOrientationRuleIsUntouched`
asserts its row is byte-identical whether or not hot work is in the set.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from lib.logbook.hot_work_cadence import (  # noqa: E402
    HOT_WORK_DECLARED,
    as_days,
    hot_work_period,
)
from tests.source_text import code_of  # noqa: E402

PROJECT = "8walworth"
DAY = "2026-09-18"


# ── THE RULE, WITH NO DATABASE ANYWHERE NEAR IT ────────────────────────────

class ADayIsDueOnlyWhenSomebodyDeclaredIt(unittest.TestCase):

    def test_no_declaration_is_nothing_to_do(self):
        """The 8 Walworth morning: permit on, nobody welding, no log owed."""
        row = hot_work_period(DAY, [])
        self.assertTrue(row["satisfied"])
        self.assertIsNone(row["due_reason"])
        self.assertIs(row["declared"], False)

    def test_a_declaration_for_today_makes_it_due(self):
        row = hot_work_period(DAY, [DAY])
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], HOT_WORK_DECLARED)
        self.assertIs(row["declared"], True)

    def test_yesterdays_declaration_does_not_hold_today_open(self):
        """THE WHOLE RULING IN ONE ASSERTION. Nobody switched anything off;
        the day simply stopped being the day."""
        row = hot_work_period(DAY, ["2026-09-17"])
        self.assertTrue(row["satisfied"])

    def test_tomorrows_declaration_does_not_open_today(self):
        row = hot_work_period(DAY, ["2026-09-19"])
        self.assertTrue(row["satisfied"])

    def test_one_declaration_among_many_days_is_matched_exactly(self):
        row = hot_work_period(DAY, ["2026-09-16", DAY, "2026-09-20"])
        self.assertFalse(row["satisfied"])

    def test_the_day_is_named_on_both_ends_of_the_period(self):
        """UNLIKE the orientation row, which sets these to None because an
        as-needed log has no cadence. A hot-work day IS a date -- the ruling is
        literally a date -- so naming it reports the declaration. It is still
        not a cadence: nothing here says the log recurs."""
        row = hot_work_period(DAY, [DAY])
        self.assertEqual(row["period_start"], DAY)
        self.assertEqual(row["period_end"], DAY)

    def test_it_names_who_declared_it(self):
        row = hot_work_period(DAY, [DAY], declared_by="Andre Duval")
        self.assertEqual(row["declared_by"], "Andre Duval")

    def test_a_nameless_declaration_is_still_due(self):
        """A missing name is not a missing obligation -- the same rule the
        orientation row applies to its worker names."""
        for name in (None, "", "   "):
            with self.subTest(name=name):
                row = hot_work_period(DAY, [DAY], declared_by=name)
                self.assertFalse(row["satisfied"])
                self.assertIsNone(row["declared_by"])

    def test_a_satisfied_row_names_nobody(self):
        """There is no declarer of a day nobody declared, and carrying a name
        there would put a man's name under 'no hot work today'."""
        self.assertIsNone(hot_work_period(DAY, [], declared_by="X")["declared_by"])

    def test_dates_are_compared_as_strings(self):
        """The declared date arrives off a Mongo document and the day under
        test off `eastern_today()`. A comparison across two shapes would report
        every day undeclared -- a tile that never appears at all, which is
        worse than the one that always did."""
        class _Day:
            def __str__(self):
                return DAY

        self.assertEqual(as_days([None, "", "  ", DAY]), {DAY})
        self.assertFalse(hot_work_period(DAY, [_Day()])["satisfied"])

    def test_a_blank_day_is_not_a_day(self):
        """A caller with no date must not match a row with no date."""
        for day in (None, "", "   "):
            with self.subTest(day=day):
                row = hot_work_period(day, [""])
                self.assertTrue(row["satisfied"])
                self.assertIsNone(row["period_start"])

    def test_filing_the_log_does_not_satisfy_the_day(self):
        """SATISFIED IS ABOUT THE DECLARATION, NOT THE FILING, and the rule
        takes no filing argument at all -- so there is no way for it to.

        `cadenceStatus` gives a log filed today the last word, so the tile
        reads Done and STAYS UP for the rest of that day. Reporting a filed day
        as satisfied would make the tile vanish the moment the CP signed it,
        taking with it the door he opens a SECOND hot-work log through -- and
        hot work is `immediate`-class, so an afternoon operation is a second
        discrete log, never an edit of the morning's."""
        self.assertEqual(S.LOGBOOK_TIMING_CLASS["hot_work"], "immediate")
        self.assertFalse(hot_work_period(DAY, [DAY])["satisfied"])
        self.assertEqual(hot_work_period(DAY, [DAY])["filed_on"], [])

    def test_the_weekly_rules_field_is_left_empty(self):
        """`uncovered_weekend_workers` belongs to the toolbox rule. The one
        client that reads it must not find something else in it."""
        self.assertEqual(hot_work_period(DAY, [DAY])["uncovered_weekend_workers"], [])

    def test_it_does_not_borrow_the_orientations_people_fields(self):
        """`uncovered_workers` is a claim about PEOPLE. An empty list here
        would read as 'nobody is waiting', which is a different statement from
        'this log is not about people'."""
        row = hot_work_period(DAY, [DAY])
        self.assertNotIn("uncovered_workers", row)
        self.assertNotIn("uncovered_worker_count", row)

    def test_the_shape_matches_the_weekly_row(self):
        """Same keys the client already renders, so `periods` carries a third
        type with no new payload."""
        from lib.logbook.weekly_cadence import toolbox_period
        weekly = toolbox_period("2026-09-16", ["2026-09-15"], [], [])
        self.assertTrue(set(weekly).issubset(set(hot_work_period(DAY, [DAY]))))


# ── THE SAME RULE, REACHED THROUGH THE REAL ENDPOINT HELPER ────────────────

def _match(doc, query):
    for k, v in (query or {}).items():
        got = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and got == v["$ne"]:
                return False
            continue
        if got != v:
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
        self.writes = []

    def find(self, query=None, projection=None):
        self.reads += 1
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, *a, **k):
        self.reads += 1
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def distinct(self, field, query=None):
        self.reads += 1
        out = []
        for d in self.docs:
            if _match(d, query or {}) and d.get(field) not in (None, *out):
                out.append(d.get(field))
        return out

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert=False):
        self.writes.append({"query": copy.deepcopy(query),
                            "update": copy.deepcopy(update),
                            "upsert": upsert})
        for d in self.docs:
            if _match(d, query or {}):
                d.update(update.get("$set") or {})
                return
        if upsert:
            doc = dict(query)
            doc.update(update.get("$setOnInsert") or {})
            doc.update(update.get("$set") or {})
            self.docs.append(doc)


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


class _PeriodsFixture(unittest.TestCase):
    """A project whose ONLY as-needed obligation under test is hot work.

    No check-ins and no workers, so `_orientation_period_rows` answers in one
    read and its row is a constant -- this file is about the hot-work row and
    must not be reading the orientation's state by accident.
    """

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self._orig = (S.db, S.to_query_id)
        S.db = self.db
        S.to_query_id = lambda x: x

    def tearDown(self):
        S.db, S.to_query_id = self._orig
        self.loop.close()

    def declare(self, day=DAY, project=PROJECT, active=True):
        self.db.hot_work_days.docs.append({
            "project_id": project, "date": day, "active": active,
            "declared_by": "u1", "declared_by_name": "Andre Duval",
        })

    def periods(self, required=("hot_work",), on_date=DAY):
        rows = self.loop.run_until_complete(
            S._logbook_periods(PROJECT, list(required), on_date=on_date))
        return {r["log_type"]: r for r in rows}


class EightWalworthsExactShape(_PeriodsFixture):
    """THE PRODUCTION CASE THAT PROMPTED THE RULING.

    `hot_work_permitted` is TRUE on this project -- which is why the type is in
    its required set at all -- and nobody has declared a hot-work day. Before
    this change the screen had no row to read, fell back to the by-date answer
    and said Pending. It must now say not-due.
    """

    def test_permitted_with_nothing_declared_is_NOT_DUE(self):
        row = self.periods()["hot_work"]
        self.assertTrue(row["satisfied"],
                        "the standing permit alone must never make the log due "
                        "-- that is the defect being fixed")
        self.assertIs(row["declared"], False)

    def test_the_standing_field_is_not_even_read_by_the_rule(self):
        """A row computed from `hot_work_permitted` would be the old bug with
        a period wrapper round it. The project document is not consulted."""
        self.db.projects.docs = [{"_id": PROJECT, "hot_work_permitted": True}]
        self.assertTrue(self.periods()["hot_work"]["satisfied"])
        self.assertEqual(self.db.projects.reads, 0)

    def test_a_declared_day_is_due_and_names_the_man(self):
        self.declare()
        row = self.periods()["hot_work"]
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], HOT_WORK_DECLARED)
        self.assertEqual(row["declared_by"], "Andre Duval")

    def test_the_day_after_is_not_due_again(self):
        """NOBODY SWITCHED ANYTHING OFF. The next day's read asks about the
        next day, which nobody declared."""
        self.declare()
        self.assertFalse(self.periods(on_date=DAY)["hot_work"]["satisfied"])
        self.assertTrue(self.periods(on_date="2026-09-19")["hot_work"]["satisfied"])

    def test_a_withdrawn_declaration_stops_being_due(self):
        self.declare(active=False)
        self.assertTrue(self.periods()["hot_work"]["satisfied"])

    def test_another_projects_hot_work_day_is_not_this_ones(self):
        self.declare(project="588thomas")
        self.assertTrue(self.periods()["hot_work"]["satisfied"])

    def test_it_is_one_read_on_one_key(self):
        """A CP pays for this standing at a gate. Not a scan of the project's
        hot-work history -- the only question is about one day."""
        self.periods()
        self.assertEqual(self.db.reads, 1)

    def test_it_is_still_unconditionally_required_when_the_permit_is_on(self):
        """Nothing about the required SET changed. `conditional` is still
        `hot_work_permitted`, so the permit still decides whether the project
        keeps this logbook at all; the row decides whether today is a day it is
        owed."""
        got = set(S.get_required_logbooks("regular", {"hot_work_permitted": True}))
        self.assertIn("hot_work", got)
        self.assertNotIn(
            "hot_work",
            S.get_required_logbooks("regular", {"hot_work_permitted": False}))

    def test_no_permit_means_no_row_because_there_is_no_tile(self):
        """A project the type is not required on asks nothing and pays
        nothing."""
        self.assertEqual(self.periods(required=("daily_jobsite",)), {})
        self.assertEqual(self.db.reads, 0)


class TheOrientationRuleIsUntouched(_PeriodsFixture):
    """#611 IS NOT BEING RE-OPENED. Its row must be identical whether or not
    hot work is in the required set, and its failure must not take the hot-work
    row down with it (and vice versa) -- the two try blocks in
    `_logbook_periods` are separate for exactly that."""

    def test_the_orientation_row_is_the_same_with_and_without_hot_work(self):
        self.declare()
        alone = self.periods(required=("subcontractor_orientation",))
        together = self.periods(
            required=("subcontractor_orientation", "hot_work"))
        self.assertEqual(alone["subcontractor_orientation"],
                         together["subcontractor_orientation"])

    def test_an_uncovered_worker_still_opens_the_orientation(self):
        self.db.checkins.docs = [{"project_id": PROJECT, "worker_id": "w1"}]
        row = self.periods(required=("subcontractor_orientation", "hot_work"))
        self.assertFalse(row["subcontractor_orientation"]["satisfied"])
        self.assertTrue(row["hot_work"]["satisfied"])

    def test_a_broken_hot_work_read_leaves_the_orientation_row_standing(self):
        class _Boom(_Coll):
            async def find_one(self, *a, **k):
                raise RuntimeError("no")

        self.db._c["hot_work_days"] = _Boom()
        rows = self.periods(required=("subcontractor_orientation", "hot_work"))
        self.assertIn("subcontractor_orientation", rows)
        self.assertNotIn("hot_work", rows)

    def test_a_broken_orientation_read_leaves_the_hot_work_row_standing(self):
        class _Boom(_Coll):
            async def distinct(self, *a, **k):
                raise RuntimeError("no")

        self.db._c["checkins"] = _Boom()
        self.declare()
        rows = self.periods(required=("subcontractor_orientation", "hot_work"))
        self.assertNotIn("subcontractor_orientation", rows)
        self.assertFalse(rows["hot_work"]["satisfied"])


class TheFailOpenPropertyIsUntouched(_PeriodsFixture):
    """WHAT #611's `HotWorkIsLeftAlone` WAS REALLY PINNING.

    That class asserted no row was emitted for `hot_work`, and the reason it
    gave was the general property: the client predicate keys on
    `frequency === 'as_needed'`, so a type the server says nothing about must
    keep its tile. Hot work now HAS a rule and is no longer an instance of that
    property -- so the property is re-pinned here on a type that has none, and
    the old class is rewritten rather than deleted.

    THE GUARD DID NOT MOVE. Hot work became an exception by acquiring a rule.
    """

    def test_a_type_with_no_rule_gets_no_row(self):
        """A REQUIRED TYPE THIS FUNCTION HAS NEVER HEARD OF -- which is the
        case the property is really for: the NEXT as-needed type, added before
        anybody writes its rule. The two as-needed types in the registry today
        both have one, so the instance cannot be drawn from it."""
        self.assertEqual(self.periods(
            required=("a_type_with_no_rule_yet", "daily_jobsite")), {})

    def test_and_costs_nothing(self):
        self.periods(required=("a_type_with_no_rule_yet",))
        self.assertEqual(self.db.reads, 0)

    def test_exactly_three_types_are_answered_and_no_others(self):
        """THE CENSUS, so a fourth rule cannot be added without this file
        noticing. Everything else is silent by construction."""
        every = [e["key"] for e in S.LOGBOOK_TYPE_REGISTRY]
        self.declare()
        answered = set(self.periods(required=tuple(every)))
        self.assertEqual(answered,
                         {"toolbox_talk", "subcontractor_orientation", "hot_work"})


# ── THE TWO FACTS, AND THE LAYER BETWEEN THEM ──────────────────────────────

class TheRegistryDeclaresBothOwners(unittest.TestCase):
    """The FDNY reasoning is CONFIRMED by the ruling, not overturned by it: the
    admin still says the site may do hot work. What moved is a different
    question -- who says hot work is happening today."""

    def test_the_standing_permit_is_still_the_admins(self):
        entry = next(e for e in S.LOGBOOK_TYPE_REGISTRY if e["key"] == "hot_work")
        self.assertEqual(entry["activated_by"], "admin")
        self.assertEqual(entry["conditional"], "hot_work_permitted")

    def test_the_dated_declaration_is_the_cps(self):
        entry = next(e for e in S.LOGBOOK_TYPE_REGISTRY if e["key"] == "hot_work")
        self.assertEqual(entry["dated_activated_by"], "cp")
        self.assertEqual(entry["dated_activation"], "hot_work_days")

    def test_hot_work_is_the_only_dated_type(self):
        """ANCHOR. The endpoint branches on the PRESENCE of the key, so a
        second dated type needs no code change -- and this says so out loud
        rather than leaving the next reader to find out by adding one."""
        dated = [e["key"] for e in S.LOGBOOK_TYPE_REGISTRY
                 if e.get("dated_activation")]
        self.assertEqual(dated, ["hot_work"])

    def test_only_a_dated_type_names_a_dated_owner(self):
        for e in S.LOGBOOK_TYPE_REGISTRY:
            with self.subTest(key=e["key"]):
                if not e.get("dated_activation"):
                    self.assertIsNone(e.get("dated_activated_by"))

    def test_the_fdny_reasoning_is_still_written_down(self):
        """It was RIGHT and it is not deleted. A comment removed as 'superseded'
        is how the next change re-argues a question the operator settled."""
        src = code_of("server.py", raw=True)
        block = src[src.index('"key": "hot_work"'):]
        block = block[:block.index('"key": "concrete_operations"')]
        for phrase in ("FDNY permit", "certificate of fitness",
                       "declaring the work permitted is not"):
            self.assertIn(phrase, block, f"the registry lost {phrase!r}")

    def test_the_comment_records_what_the_app_now_takes_on_trust(self):
        """WHITESPACE-NORMALISED, because the sentence is wrapped over two
        comment lines with a `#` and an indent between them -- a literal
        substring search would report a missing sentence that is there."""
        src = code_of("server.py", raw=True)
        block = src[src.index('"key": "hot_work"'):]
        block = block[:block.index('"key": "concrete_operations"')]
        flat = " ".join(block.replace("#", " ").split())
        self.assertIn("takes the CP's word that hot work is happening today",
                      flat)


class TheActivationRowsAreTwo(unittest.TestCase):
    """TWO FACTS, TWO ROWS. One row's `active` can only carry one boolean, its
    `activated_by` one owner and its OFF copy one sentence -- and merging them
    is how 'permitted' came to mean 'due'."""

    def rows(self, project=None, declared=None):
        return S.logbook_activations(project or {}, declared)

    def test_hot_work_has_a_standing_row_and_a_day_row(self):
        hot = [a for a in self.rows() if a["log_type"] == "hot_work"]
        self.assertEqual([a["scope"] for a in hot], ["standing", "day"])

    def test_every_other_type_has_only_a_standing_row(self):
        seen = {}
        for a in self.rows():
            seen.setdefault(a["log_type"], []).append(a["scope"])
        for log_type, scopes in seen.items():
            with self.subTest(log=log_type):
                self.assertEqual(scopes,
                                 ["standing", "day"] if log_type == "hot_work"
                                 else ["standing"])

    def test_the_standing_row_tracks_the_project_field(self):
        on = [a for a in self.rows({"hot_work_permitted": True})
              if a["scope"] == "standing" and a["log_type"] == "hot_work"][0]
        self.assertIs(on["active"], True)
        self.assertEqual(on["activated_by"], "admin")
        self.assertEqual(on["field"], "hot_work_permitted")

    def test_the_day_row_tracks_todays_declaration_not_the_field(self):
        """THE POINT OF THE PAIR. Permitted does not mean declared."""
        row = [a for a in self.rows({"hot_work_permitted": True})
               if a["scope"] == "day"][0]
        self.assertIs(row["active"], False)
        declared = [a for a in self.rows({"hot_work_permitted": True},
                                         {"hot_work": True})
                    if a["scope"] == "day"][0]
        self.assertIs(declared["active"], True)

    def test_the_day_row_is_unavailable_without_the_permit(self):
        """NO PERMIT, NO DAY -- the courtesy half. The server refuses the
        request; this is what lets the screen say so instead of offering a
        control that will 400."""
        off = [a for a in self.rows({}) if a["scope"] == "day"][0]
        self.assertIs(off["available"], False)
        on = [a for a in self.rows({"hot_work_permitted": True})
              if a["scope"] == "day"][0]
        self.assertIs(on["available"], True)

    def test_the_day_row_is_owned_by_the_cp(self):
        row = [a for a in self.rows() if a["scope"] == "day"][0]
        self.assertEqual(row["activated_by"], "cp")

    def test_the_two_rows_do_not_share_a_label(self):
        """They name different things, and one sentence for both is how the
        screen would end up saying 'On -- it is on your logbook list' about a
        list it is not on."""
        hot = [a for a in self.rows() if a["log_type"] == "hot_work"]
        self.assertEqual(hot[0]["label"], "Hot Work Permit Log")
        self.assertEqual(hot[1]["label"], "Hot Work Permit Log — today")

    def test_it_does_no_io(self):
        """PURE, which is why the demo dataset can state its answer. A caller
        that cannot supply `declared_today` gets False -- the safe direction:
        it offers the control rather than claiming a declaration."""
        with patch.object(S, "db", None):
            self.assertIs(
                [a for a in self.rows({"hot_work_permitted": True})
                 if a["scope"] == "day"][0]["active"], False)


# ── DECLARING A DAY, THROUGH THE REAL ENDPOINT ─────────────────────────────

class OnlyTheRightPersonMayDeclareADay(unittest.TestCase):
    """ENFORCED SERVER-SIDE. The brief's own words: the endpoint enforces
    `activated_by`, so hiding a control on the client is a courtesy and never
    the guard."""

    def _call(self, body, role="cp", project=None):
        db = _DB()
        db.projects.docs = [dict(project if project is not None else {
            "_id": "p1", "project_class": "regular", "hot_work_permitted": True})]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            out = asyncio.run(S.set_logbook_activation(
                "p1", body, current_user={"id": "u1", "role": role,
                                          "full_name": "Andre Duval"}))
        return out, db

    def _day(self, active=True, **extra):
        return {"log_type": "hot_work", "active": active, "scope": "day", **extra}

    def test_a_cp_may_declare_a_hot_work_day(self):
        out, db = self._call(self._day())
        self.assertIs(out["active"], True)
        self.assertEqual(out["scope"], "day")
        self.assertEqual(out["date"], DAY)
        self.assertEqual(
            [(d["project_id"], d["date"], d["active"]) for d in db.hot_work_days.docs],
            [("p1", DAY, True)])

    def test_the_declaration_records_who_made_it(self):
        _, db = self._call(self._day())
        row = db.hot_work_days.docs[0]
        self.assertEqual(row["declared_by"], "u1")
        self.assertEqual(row["declared_by_name"], "Andre Duval")

    def test_it_does_NOT_touch_the_standing_permit(self):
        """THE WHOLE POINT OF THE SPLIT. A CP declaring a day must not be able
        to assert the FDNY permit the admin holds -- which is what a
        CP-settable version of the old boolean would have been."""
        _, db = self._call(self._day())
        self.assertEqual(db.projects.docs[0]["hot_work_permitted"], True)
        for w in db.projects.writes:
            self.assertEqual(set(w["update"]["$set"]), {"required_logbooks"})

    def test_the_date_is_the_servers_and_not_the_callers(self):
        """A caller who could name the date could declare a day whose log can
        no longer be filed, or a future day -- the persistent flag wearing a
        date."""
        _, db = self._call(self._day(date="2026-01-01"))
        self.assertEqual(db.hot_work_days.docs[0]["date"], DAY)

    def test_taking_it_back_keeps_the_row_and_clears_the_flag(self):
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular",
                             "hot_work_permitted": True}]
        db.hot_work_days.docs = [{"project_id": "p1", "date": DAY,
                                  "active": True, "declared_by": "u1"}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            asyncio.run(S.set_logbook_activation(
                "p1", self._day(active=False),
                current_user={"id": "u2", "role": "cp"}))
        self.assertEqual(len(db.hot_work_days.docs), 1)
        self.assertIs(db.hot_work_days.docs[0]["active"], False)

    def test_the_upsert_filter_is_the_two_fields_that_identify_the_day(self):
        """THE WRITER test_reads_without_writers.py CANNOT SEE.

        `project_id` and `date` are written by the upsert FILTER -- Mongo
        copies a filter's equality fields into the document it inserts -- and
        that sweep reads $set and insert literals, so it reports a read with no
        writer. Its baseline carries a note saying which writer and why it is
        invisible; THIS is what stops that note from being a hand-audit with an
        expiry date nobody set. Change the call site and this fails.
        """
        _, db = self._call(self._day())
        w = db.hot_work_days.writes[0]
        self.assertEqual(set(w["query"]), {"project_id", "date"})
        self.assertIs(w["upsert"], True)
        row = db.hot_work_days.docs[0]
        self.assertEqual(row["project_id"], "p1")
        self.assertEqual(row["date"], DAY)

    def test_declaring_the_same_day_twice_is_one_row(self):
        """An upsert on (project, date). The unique index does the
        de-duplication; this asserts the endpoint asks it to."""
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular",
                             "hot_work_permitted": True}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            for _ in range(2):
                asyncio.run(S.set_logbook_activation(
                    "p1", self._day(), current_user={"id": "u1", "role": "cp"}))
        self.assertEqual(len(db.hot_work_days.docs), 1)
        self.assertTrue(db.hot_work_days.writes[0]["upsert"])

    def test_an_admin_may_declare_one_too(self):
        for role in ("admin", "owner", "superintendent"):
            with self.subTest(role=role):
                out, _ = self._call(self._day(), role=role)
                self.assertIs(out["active"], True)

    def test_the_response_carries_the_fresh_periods(self):
        """SO THE TILE APPEARS ON THE SAME TAP. Without this the screen would
        hold a `periods` payload fetched before the declaration and go on
        hiding the tile until the next refetch."""
        out, _ = self._call(self._day())
        hot = [r for r in out["periods"] if r["log_type"] == "hot_work"]
        self.assertEqual(len(hot), 1)
        self.assertFalse(hot[0]["satisfied"])


class NoPermitNoDay(unittest.TestCase):
    """THE LAYER, AND IT IS THE SERVER'S. The operator: the dated toggle "is
    only available on a project where the standing field is on"."""

    def _call(self, active, permitted, role="cp"):
        db = _DB()
        doc = {"_id": "p1", "project_class": "regular"}
        if permitted is not None:
            doc["hot_work_permitted"] = permitted
        db.projects.docs = [doc]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            out = asyncio.run(S.set_logbook_activation(
                "p1", {"log_type": "hot_work", "active": active, "scope": "day"},
                current_user={"id": "u1", "role": role}))
        return out, db

    def test_a_day_cannot_be_declared_without_the_standing_permit(self):
        for permitted in (False, None):
            with self.subTest(permitted=permitted):
                with self.assertRaises(S.HTTPException) as cm:
                    self._call(True, permitted)
                self.assertEqual(cm.exception.status_code, 400)
                self.assertEqual(cm.exception.detail["code"],
                                 "HOT_WORK_DAY_REQUIRES_PERMIT")

    def test_the_refusal_writes_nothing_at_all(self):
        """A refusal that had already written the row would be a guard in
        name."""
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular"}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x):
            with self.assertRaises(S.HTTPException):
                asyncio.run(S.set_logbook_activation(
                    "p1", {"log_type": "hot_work", "active": True, "scope": "day"},
                    current_user={"id": "u1", "role": "cp"}))
        self.assertEqual(db.hot_work_days.docs, [])
        self.assertEqual(db.projects.writes, [])

    def test_an_ADMIN_is_refused_too(self):
        """It is not a rank gate. The permit is a fact about the PROJECT, and
        an admin who has not stated it has not stated it."""
        with self.assertRaises(S.HTTPException):
            self._call(True, False, role="admin")

    def test_taking_a_day_BACK_is_never_refused(self):
        """A project must always be able to reach the off state. An admin
        withdrawing the permit would otherwise strand a declaration nobody
        could take back."""
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular"}]
        db.hot_work_days.docs = [{"project_id": "p1", "date": DAY, "active": True}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            out = asyncio.run(S.set_logbook_activation(
                "p1", {"log_type": "hot_work", "active": False, "scope": "day"},
                current_user={"id": "u1", "role": "cp"}))
        self.assertIs(out["active"], False)
        self.assertIs(db.hot_work_days.docs[0]["active"], False)

    def test_withdrawing_the_permit_does_not_retract_a_declared_day(self):
        """PAST DECLARATIONS ARE FACTS ABOUT WHAT HAPPENED. A hot-work log
        filed last Tuesday does not stop having been due because a flag moved
        this morning. Switching the standing permit off writes the project
        field and NOTHING in `hot_work_days`."""
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular",
                             "hot_work_permitted": True}]
        db.hot_work_days.docs = [{"project_id": "p1", "date": DAY, "active": True}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x):
            asyncio.run(S.set_logbook_activation(
                "p1", {"log_type": "hot_work", "active": False},
                current_user={"id": "u1", "role": "admin"}))
        self.assertEqual(db.hot_work_days.writes, [])
        self.assertIs(db.hot_work_days.docs[0]["active"], True)


class TheScopeIsNotGuessed(unittest.TestCase):

    def _call(self, body, role="cp"):
        db = _DB()
        db.projects.docs = [{"_id": "p1", "project_class": "regular",
                             "hot_work_permitted": True}]
        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "eastern_today", lambda: DAY):
            out = asyncio.run(S.set_logbook_activation(
                "p1", body, current_user={"id": "u1", "role": role}))
        return out, db

    def test_an_unknown_scope_is_refused_not_defaulted(self):
        """Silently treating a typo as "standing" would take a request meaning
        'hot work today' and write the admin's permit statement instead."""
        with self.assertRaises(S.HTTPException) as cm:
            self._call({"log_type": "hot_work", "active": True, "scope": "dya"})
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail["code"], "ACTIVATION_SCOPE_UNKNOWN")

    def test_a_day_scope_on_a_type_that_has_none_is_refused(self):
        with self.assertRaises(S.HTTPException) as cm:
            self._call({"log_type": "scaffold_maintenance", "active": True,
                        "scope": "day"})
        self.assertEqual(cm.exception.detail["code"], "ACTIVATION_NOT_DATED")

    def test_no_scope_means_standing_which_is_what_every_caller_sent_before(self):
        """The four CP toggles have no second scope and their clients send no
        `scope` key. They must behave exactly as they did."""
        out, db = self._call({"log_type": "scaffold_maintenance", "active": True})
        self.assertEqual(out["scope"], "standing")
        self.assertIs(db.projects.docs[0]["scaffold_erected"], True)
        self.assertEqual(db.hot_work_days.docs, [])

    def test_a_cp_still_may_not_touch_the_standing_hot_work_permit(self):
        """UNCHANGED BY THE RULING. The FDNY permit is still the admin's."""
        with self.assertRaises(S.HTTPException) as cm:
            self._call({"log_type": "hot_work", "active": True})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.detail["code"], "ACTIVATION_REQUIRES_ADMIN")


# ── THE SCREEN'S HALF ──────────────────────────────────────────────────────

class TheScreenRendersTwoSwitchesAndOneTile(unittest.TestCase):
    """Asserted on the SOURCE because the behavioural test for it runs under
    node (requiredLogbooksWiring.test.cjs, logbookCadence.test.cjs).

    `code_of` strips comments and docstrings. This file's prose names every
    symbol below and so does the screen's -- the trap tests/source_text.py
    exists for.
    """

    def setUp(self):
        self.screen = code_of("frontend/app/logbooks/index.jsx")
        self.cadence = code_of("frontend/src/utils/logbookCadence.js")
        self.api = code_of("frontend/src/utils/api.js")

    def test_the_hiding_predicate_is_unchanged(self):
        """THE GUARD DID NOT MOVE. Hot work became an exception by acquiring a
        rule, not by this loosening."""
        self.assertIn("periodSatisfied(periods, t.key) === true", self.screen)

    def test_the_toggle_rows_are_keyed_on_type_AND_scope(self):
        """Two rows now carry `log_type: 'hot_work'`. Matching on the type
        alone would move both switches on one tap."""
        self.assertIn("a.scope || 'standing'", self.screen)
        self.assertIn("${act.log_type}:${act.scope || 'standing'}", self.screen)

    def test_the_client_sends_the_scope_it_was_given(self):
        self.assertIn("act.scope", self.screen)
        self.assertIn("scope", self.api)

    def test_the_client_does_not_decide_which_types_are_dated(self):
        """A hardcoded key here is the 'second model' getVisibleLogTypes was
        rewritten to stop being. `scope` and `available` are the server's
        words, carried on the row."""
        at = self.screen.index("activations.map((act)")
        block = self.screen[at:self.screen.index("</>", at)]
        self.assertNotIn("hot_work", block)
        self.assertIn("act.available !== false", block)

    def test_the_label_does_not_call_a_hot_work_day_a_week(self):
        self.assertIn("row.log_type === 'hot_work'", self.cadence)
        at = self.cadence.index("row.log_type === 'hot_work'")
        block = self.cadence[at:at + 600]
        self.assertNotIn("week", block)


def _fn_block(src, name):
    """The body of one top-level function, ending at the NEXT top-level
    definition.

    NOT `\\n\\n\\n`. `code_of` strips comments and leaves the blank lines
    behind, so a commented block inside the function produces a run of blank
    lines and a boundary of three newlines ends the slice a few lines in --
    after which an assertNotIn reads a stub and passes vacuously.
    """
    block = src[src.index(f"async def {name}"):]
    rest = block[1:]
    ends = [rest.index(m) for m in ("\nasync def ", "\ndef ", "\n@api_router")
            if m in rest]
    return block[:min(ends) + 1] if ends else block


class TheRuleIsWhereItCanBeTested(unittest.TestCase):

    def setUp(self):
        self.block = _fn_block(code_of("server.py"), "_hot_work_period_rows")

    def test_the_slice_is_the_whole_function(self):
        """ANCHOR. Every assertion here reads `self.block`; a boundary that
        silently truncated it would make the absence tests say nothing."""
        self.assertGreater(len(self.block), 200)
        self.assertIn("return [hot_work_period(", self.block)

    def test_the_server_holds_no_second_copy_of_it(self):
        """The date comparison lives in lib/logbook/hot_work_cadence.py. A
        comparison recomputed in server.py would be a second model."""
        self.assertIn("hot_work_period(", self.block)
        self.assertNotIn("== day", self.block)
        self.assertNotIn("eastern_today()", self.block)

    def test_the_read_is_one_keyed_find_one(self):
        self.assertIn("_hot_work_declaration(", self.block)
        self.assertNotIn("to_list", self.block)
        self.assertNotIn(".find(", self.block)

    def test_the_declaration_read_asks_for_the_active_row(self):
        """`active: True` is part of the QUERY. A read that found the row and
        then had to remember to look at the flag is one that will forget."""
        block = _fn_block(code_of("server.py"), "_hot_work_declaration")
        self.assertIn('"active": True', block)
        self.assertIn("db.hot_work_days.find_one", block)

    # `"periods": await _logbook_periods(` is NOT asserted here. It is already
    # held by test_a_weekly_log_is_not_due_every_day.py, and repeating it in
    # this class would put it behind a setUp that cannot run until the function
    # exists -- so on a control run it would report as a failure caused by the
    # fixture rather than by the thing it checks.


if __name__ == "__main__":
    unittest.main(verbosity=2)
