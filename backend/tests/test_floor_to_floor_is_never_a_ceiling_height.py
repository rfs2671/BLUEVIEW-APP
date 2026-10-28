"""Floor-to-floor is derived from a section's level marks, and is never a
ceiling height (operator ruling 2026-10-27, queue item 3):

    "derive floor-to-floor from A-300's level marks; answer "ceiling height
    not shown; floor-to-floor 10'-0" (A-300.00)". Floor-to-floor must never
    bind as a ceiling height."

A-300.00 (AR - 3.28.25.pdf p20, LONGITUDINAL SECTIONS) prints seven level
marks, BASE PLANE 33.37' 0'-0" to BULKHEAD 93.37' +60'-0", 10'-0" apart every
time - by elevation, by height above the datum, by the drawn spacing at its
3/16" = 1'-0" scale, and by the six 10'-0" strings printed between them. The
records below are production's, verbatim. Before this change a search for the
ceiling height never returned A-300.00 (its marks print neither CEILING nor
HEIGHT), and every intent but attribute bound "The ceiling height is 10'-0"."
on any returned record that printed 10'-0".

Each test fails by assertion on the branch before this change (#894's head).
"""

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_eval as ev  # noqa: E402
from lib import plan_search as ps  # noqa: E402

RULED = "Ceiling height not shown; floor-to-floor 10'-0\" (A-300.00)"
INTENTS = ["attribute", "", "identify", "existence", "location", "geometry", "count"]
A300_PAGE = "6adf9ce8bbd592e9bb0e52a9"


def levels_mod():
    try:
        return importlib.import_module("lib.plan_floor_to_floor")
    except ImportError as e:  # the branch before this change has no such module
        raise AssertionError(f"lib.plan_floor_to_floor is not importable: {e}")


def rec(quote, sheet="A-300.00", page=A300_PAGE, title="LONGITUDINAL SECTIONS", **kw):
    base = {"project_id": "p", "page_id": page, "record_type": "text", "ordinal": 0,
            "tier": "text_layer", "source": "text_layer", "quote": quote, "label": None,
            "subject_terms": [], "payload": {}, "sheet_number": sheet, "sheet_title": title,
            "file_id": "6a90ebce1df3e1f2588018a2", "file_name": "AR - 3.28.25.pdf",
            "page_number": 20, "discipline": "AR"}
    base.update(kw)
    return base


# A-300.00's marks, in production's record order
MARKS = ["BASE PLANE 33.37' 0'-0\"", "FOURTH FLOOR 63.37' +30'-0\"", "ROOF 83.37' +50'-0\"",
         "MEZZANINE 73.37' +40'-0\"", "BULKHEAD 93.37' +60'-0\"",
         "SECOND FLOOR 43.37' +10'-0\"", "THIRD FLOOR 53.37' +20'-0\""]
A300 = ([rec(q, ordinal=i) for i, q in enumerate(MARKS)]
        + [rec("10'-0\"", ordinal=20 + i) for i in range(6)]
        + [rec("50'-0\" BUILDING & BASE HEIGHT", ordinal=30)])
ORDER = ["BASE PLANE", "SECOND FLOOR", "THIRD FLOOR", "FOURTH FLOOR", "MEZZANINE", "ROOF",
         "BULKHEAD"]


def derived_row(ceiling_asked=True, printed=0, intervals=None, why=None):
    """The floor-to-floor row search_plans returns, written out (not built by
    lib.plan_floor_to_floor, so the gate and render tests run on any branch)."""
    ivs = intervals or [{"from": a, "to": b, "text": "10'-0\"", "inches": 120.0}
                        for a, b in zip(ORDER, ORDER[1:])]
    return rec(" | ".join(sorted(MARKS, key=lambda m: float(m.split()[-2][:-1]))),
               record_type="levels", source="level_marks", ordinal=-1,
               payload={"levels": [], "floor_to_floor": [] if why else ivs, "why": why,
                        "same_marks_on": ["A-301.00"], "ceiling_asked": ceiling_asked,
                        "ceiling_heights_printed": printed})


# what else a ceiling search returns (production, verbatim)
CEILINGS = [rec("6 CEILING DETAIL", sheet="A-302.00", page="pg302", title="DETAILS"),
            rec("1 HOUR FIRE RATED CEILING W/ ONE LAYER OF 5/8\" GYPSUM BOARD",
                sheet="A-302.00", page="pg302", title="DETAILS", ordinal=1),
            rec("1/2 \" METAL FLUSHED ON THE CEILING", sheet="A.3.5", page="pg35",
                title="RCP- LOBBY")]
# a record that prints 10'-0" about something else: the union vouches on it
SETBACK = rec("10'-0\" REQ. SETBACK", sheet="Z-002.01", page="pgz2",
              title="BUILDING HEIGHT AND SETBACK DIAGRAMS")


def bound(text, records, intent):
    return ps.answer_is_grounded(text, records, intent=intent)[0]


class AFloorToFloorIsNeverACeilingHeight(unittest.TestCase):
    """Under every intent, whatever else prints the figure."""

    CLAIMS = ["The ceiling height is 10'-0\".", "ceiling height: 10'-0\".",
              "Ceiling height - 10'-0\"", "The ceilings are 10 feet high.",
              "The CLG HT is 10'-0\".", "Ceiling height: 120 inches.",
              "The ceiling height is 50'-0\".",
              "Floor-to-floor is 10'-0\" (ceiling height not shown)."]

    def test_no_ceiling_claim_binds_on_level_evidence(self):
        records = A300 + [derived_row(), SETBACK] + CEILINGS
        leaks = [(i or '""', c) for i in INTENTS for c in self.CLAIMS if bound(c, records, i)]
        self.assertEqual(leaks, [], "a floor-to-floor or level figure bound as a ceiling height")

    def test_a_plan_sheets_own_mark_does_not_lend_its_height(self):
        # asked about the second floor's ceiling, a plan's own level mark is
        # among the records: its +10'-0" is a level, not a ceiling height
        plan = [rec(MARKS[5], sheet="A-101.00", page="pg101", title="SECOND FLOOR PLAN")]
        leaks = [i or '""' for i in INTENTS
                 if bound("The second floor ceiling height is 10'-0\".", plan + CEILINGS, i)]
        self.assertEqual(leaks, [])


class TheRuledAnswerBinds(unittest.TestCase):

    def test_the_ruled_sentence_binds_under_every_intent(self):
        records = [derived_row()] + CEILINGS
        refused = [i or '""' for i in INTENTS if not bound(RULED, records, i)]
        self.assertEqual(refused, [], f"{RULED!r} refused")
        refused = [i or '""' for i in INTENTS
                   if not bound("The floor-to-floor is 10'-0\" on every storey.", records, i)]
        self.assertEqual(refused, [])

    def test_a_derived_figure_binds_only_where_a_clause_names_a_floor_to_floor(self):
        records = [derived_row()]
        for claim in ["The apartment is 10'-0\".", "The floor-to-floor is 12'-0\".",
                      "The roof is at 50'-0\"."]:
            for i in ("", "attribute", "identify"):
                self.assertFalse(bound(claim, records, i), f"{claim!r} bound under {i!r}")

    def test_marks_that_disagree_state_no_floor_to_floor(self):
        records = [derived_row(why="THIRD FLOOR is marked twice")]
        for i in ("", "attribute"):
            self.assertFalse(bound("The floor-to-floor is 10'-0\".", records, i))


class WhatTheCrewIsSent(unittest.TestCase):
    """render_records: what the gate sends when it refuses a composed answer."""

    def test_the_render_is_the_ruled_sentence(self):
        got = ps.render_records([derived_row()] + CEILINGS, "ceiling height")
        self.assertEqual(got, RULED)

    def test_not_shown_needs_its_warrant(self):
        # a set that prints a ceiling height: the floor-to-floor is said, the
        # absence is not, and the records that print it follow
        got = ps.render_records([derived_row(printed=1)] + CEILINGS, "ceiling height")
        self.assertTrue(got.startswith("Floor-to-floor 10'-0\" (A-300.00)"), got)
        self.assertNotIn("not shown", got)
        self.assertIn("6 CEILING DETAIL [A-302.00]", got)
        # not counted: never "not shown"
        got = ps.render_records([derived_row(printed=None)] + CEILINGS, "ceiling height")
        self.assertNotIn("not shown", got)

    def test_storeys_that_differ_are_named(self):
        ivs = [{"from": "BASE PLANE", "to": "SECOND FLOOR", "text": "14'-0\"", "inches": 168.0},
               {"from": "SECOND FLOOR", "to": "THIRD FLOOR", "text": "10'-0\"", "inches": 120.0}]
        got = ps.render_records([derived_row(intervals=ivs)], "ceiling height")
        self.assertEqual(got, "Ceiling height not shown; floor-to-floor 14'-0\" BASE PLANE to "
                              "SECOND FLOOR, 10'-0\" SECOND FLOOR to THIRD FLOOR (A-300.00)")
        # the ruled sentence, storey by storey, binds as it is written
        self.assertTrue(bound(got, [derived_row(intervals=ivs)], "attribute"), got)
        rows = [derived_row(intervals=ivs)]
        self.assertTrue(bound("The floor-to-floor from the base plane to the second floor "
                              "is 14'-0\".", rows, "attribute"))
        self.assertFalse(bound("The ceiling height is 14'-0\".", rows + [SETBACK], ""))


class TheDerivation(unittest.TestCase):
    """lib.plan_floor_to_floor on A-300.00's marks."""

    def test_six_storeys_of_ten_feet(self):
        L = levels_mod()
        marks = [m for r in A300 for m in L.marks(r["quote"])]
        d = L.derive(marks)
        self.assertIsNone(d["why"])
        self.assertEqual([(i["from"], i["to"], i["text"]) for i in d["intervals"]],
                         [(a, b, "10'-0\"") for a, b in zip(ORDER, ORDER[1:])])
        row = L.level_record(A300[0], d, [], ["A-301.00"], True, 0)
        self.assertEqual(L.answer_line(row), RULED)
        self.assertEqual(row["sheet_number"], "A-300.00")

    def test_columns_that_disagree_derive_nothing(self):
        L = levels_mod()
        bad = MARKS[:5] + ["SECOND FLOOR 43.37' +11'-0\"", MARKS[6]]
        d = L.derive([m for q in bad for m in L.marks(q)])
        self.assertEqual(d["intervals"], [])
        self.assertIn("BASE PLANE", d["why"])
        good = L.derive([m for q in MARKS for m in L.marks(q)])
        other = L.marks("THIRD FLOOR 54.00' +20'-0\"")
        self.assertEqual(len(L.conflicts(good, [("A-102.00", m) for m in other])), 1)
        row = L.level_record(A300[0], good, L.conflicts(good, [("A-102.00", other[0])]),
                             [], True, 0)
        self.assertEqual(row["payload"]["floor_to_floor"], [])
        self.assertIn("not stated", L.answer_line(row))

    def test_a_section_is_chosen_over_a_plan(self):
        L = levels_mod()
        pages = [{"sheet_number": "A-101.00", "sheet_title": "SECOND FLOOR PLAN",
                  "marks": L.marks(MARKS[5])},
                 {"sheet_number": "A-301.00", "sheet_title": "CROSS SECTIONS",
                  "marks": [m for q in MARKS for m in L.marks(q)]},
                 {"sheet_number": "A-300.00", "sheet_title": "LONGITUDINAL SECTIONS",
                  "marks": [m for q in MARKS for m in L.marks(q)]},
                 {"sheet_number": "A-200.01", "sheet_title": "FRONT AND REAR ELEVATIONS",
                  "marks": [m for q in MARKS for m in L.marks(q)]}]
        self.assertEqual(L.choose_section(pages)["sheet_number"], "A-300.00")


# the set's own levels, as the page index names them (#891 reads these)
SET_PAGES = [{"_id": pid, "sheet_number": sn, "sheet_title": t, "floor": None, "floors": None}
             for pid, sn, t in [("pg101", "A-101.00", "SECOND FLOOR PLAN"),
                                ("pg102", "A-102.00", "THIRD FLOOR PLAN"),
                                ("pg103", "A-103.00", "FOURTH FLOOR PLAN"),
                                ("pg104", "A-104.00", "MEZZANINE PLAN"),
                                ("pg105", "A-105.01", "ROOF AND BULKHEAD PLAN"),
                                (A300_PAGE, "A-300.00", "LONGITUDINAL SECTIONS")]]


def _server():
    import server
    return server


class SearchLeadsWithIt(unittest.TestCase):
    """search_plans against a fake database holding production's records."""

    def _search(self, subject, attribute="", intent="attribute", narrow_to=None):
        server = _server()
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        a301 = [rec(q, sheet="A-301.00", page="pg301", title="CROSS SECTIONS", ordinal=i)
                for i, q in enumerate(MARKS)]
        plan = [rec(MARKS[5], sheet="A-101.00", page="pg101", title="SECOND FLOOR PLAN")]
        db["plan_records"].docs = [dict(r) for r in A300 + a301 + plan + CEILINGS + [SETBACK]]
        every = sorted({r["page_id"] for r in db["plan_records"].docs})

        async def ids(project_id, discipline="", floor="", sheet_number=""):
            return list(narrow_to) if (narrow_to and (discipline or floor)) else every

        async def level_rows(project_id):  # what #891 reads the set's levels from
            return [dict(r) for r in SET_PAGES]
        with patch.object(server, "db", db), \
                patch.object(server, "_current_record_page_ids", ids), \
                patch.object(server, "_level_rows", level_rows):
            return asyncio.run(server.search_plans(
                "p", subject, intent=intent, attribute=attribute,
                discipline="AR" if narrow_to else ""))

    def test_a_ceiling_height_question_leads_with_the_floor_to_floor(self):
        for subject, attribute in [("ceiling", "height"), ("ceiling height", "height"),
                                   ("apartments", "ceiling height")]:
            got = self._search(subject, attribute)
            self.assertTrue(got, (subject, attribute))
            first = got[0]
            self.assertEqual((first.get("record_type"), first.get("sheet_number")),
                             ("levels", "A-300.00"), (subject, attribute))
            self.assertEqual(first["payload"]["ceiling_heights_printed"], 0)
            self.assertEqual(ps.render_records(got, subject), RULED)
            text = _server()._render_records_for_model(got, subject)
            self.assertIn(f"Answer a ceiling-height question with exactly: {RULED}", text)
            self.assertNotIn("- " + first["quote"], text)
        # and no other question brings it
        for subject, attribute in [("building", "height"), ("parapet", "height"),
                                   ("ceiling", "type")]:
            got = self._search(subject, attribute)
            self.assertFalse([r for r in got if r.get("record_type") == "levels"],
                             (subject, attribute))

    def test_a_filter_on_the_question_does_not_hide_the_section(self):
        got = self._search("ceiling", "height", narrow_to=["pg302"])
        self.assertEqual([r.get("record_type") for r in got[:1]], ["levels"])

    def test_a_floor_to_floor_question_is_answered_without_the_absence(self):
        got = self._search("floor-to-floor", "height")
        self.assertEqual([r.get("record_type") for r in got[:1]], ["levels"])
        self.assertEqual(ps.render_records(got, "floor-to-floor"),
                         "Floor-to-floor 10'-0\" (A-300.00)")


class ALevelTheQuestionNames(unittest.TestCase):
    """#891 reads "5th floor" against the set's own levels (lib.plan_levels):
    on this set it is the mezzanine. The floor-to-floor row names that storey,
    by the same vocabulary (lib.plans.level_suggestion)."""

    def test_marks_are_named_by_the_sets_levels(self):
        L = levels_mod()
        self.assertEqual([(m["name"], m["token"]) for q in MARKS for m in L.marks(q)],
                         [("BASE PLANE", None), ("FOURTH FLOOR", "FLOOR_4"), ("ROOF", "ROOF"),
                          ("MEZZANINE", "MEZZANINE"), ("BULKHEAD", "BULKHEAD"),
                          ("SECOND FLOOR", "FLOOR_2"), ("THIRD FLOOR", "FLOOR_3")])

    def test_the_fifth_floor_ceiling_is_the_mezzanine_storey(self):
        got = SearchLeadsWithIt()._search("5th floor ceiling", "height")
        self.assertEqual([r.get("record_type") for r in got[:1]], ["levels"])
        self.assertEqual(got[0]["payload"].get("asked_levels"), ["MEZZANINE"])
        said = ps.render_records(got, "ceiling")
        self.assertEqual(said, "Ceiling height not shown; floor-to-floor 10'-0\" MEZZANINE to "
                               "ROOF (A-300.00)")
        for i in INTENTS:
            self.assertTrue(bound(said, got, i), (said, i))


class TheEvalCase(unittest.TestCase):
    """The plan eval's ceiling-height case is the ruling."""

    def case(self):
        suite = ev.load_suite(str(Path(__file__).resolve().parents[1] / "eval" / "boyland.json"))
        return next(c for c in suite["cases"] if c["id"] == "ceiling-height")

    def test_the_case_names_the_ruled_sentence(self):
        self.assertEqual(self.case()["expect"].get("render"), RULED)

    def test_the_case_passes_on_the_derived_row_and_fails_on_a_floor_to_floor(self):
        case = self.case()
        returned = [derived_row()] + CEILINGS
        out = ev.score_case(case, returned, {})
        self.assertEqual(out["outcome"], "pass", out["reasons"])
        self.assertTrue(out["checks"]["no_value_binds"])
        # 5/8" and 1/2 " printed, and the derived 10'-0" though no record prints it alone
        self.assertEqual(out["checks"]["printed_values_put_to_the_gate"], 3)
        # a render that states the floor-to-floor as the ceiling height fails it
        with patch.object(ps, "render_records",
                          lambda rs, s="", limit=3: "Ceiling height 10'-0\" [A-300.00]"):
            self.assertIn("the render does not state",
                          " ".join(ev.score_case(case, returned, {})["reasons"]))


if __name__ == "__main__":
    unittest.main()
