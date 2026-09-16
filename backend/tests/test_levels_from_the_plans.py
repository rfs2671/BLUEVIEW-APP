"""588'S FLOORS, READ OFF ITS OWN SHEETS — AND THE THREE STRINGS THAT ARE NOT.

`building_stories` is null on every project this product has, because nothing
ever wrote it. Asking an admin to type a storey count he would have to go and
look up is how it stays null. 588 Thomas has 155 indexed plan pages and the
title blocks say the answer.

── THE FIXTURES ARE PRODUCTION ROWS, VERBATIM ──────────────────────────────

Every row below is a real `document_page_index` document from 588 Thomas,
copied out of the probe. That matters: the `floor` column on that project holds
more than fifty distinct spellings of seven levels, including
`BULKHEAD 93.37' +60'-0"`, and a suggester tested against tidy input is a
suggester tested against data that does not exist.

── THE THREE THAT LOOK LIKE LEVELS AND ARE NOT ─────────────────────────────

BASE PLANE is a ZONING DATUM — the reference building height is measured from,
present on every elevation and setback diagram. It is not a storey, nobody
works on it, and a chip for it would put a survey reference into a signed
compliance record.

FINISHED FLOOR is a height annotation on the window schedule.

"SITE SAFETY PLAN - SUPERSTRUCTURE(PHASE-03)" and "2 OF 3" on a sewer
connection form contain digits and are not floors. This is why a TITLE must
carry the word floor before a number becomes a storey, while the `floor` COLUMN
may carry a bare ordinal — the column supplies the noun.

── AND THE ONE THAT NEEDS A HUMAN ──────────────────────────────────────────

P-200.00 "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN" is the only below-grade
sheet in the set and there is NO architectural cellar plan — nothing below
A-100. Under-slab sanitary on a slab-on-grade building, or a cellar storey
nobody drew? Emitting FLOOR_1 would be wrong in both readings and emitting
CELLAR would invent a storey, so it emits nothing and is reported verbatim for
the admin to settle. That is the judgement this module exists not to make.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.plans.level_suggestion import (  # noqa: E402
    MAX_SUGGESTED_STORIES,
    suggest_levels,
    tokens_in,
)


def _row(number, title, floor=""):
    return {"sheet_number": number, "sheet_title": title, "floor": floor}


#: 588 Thomas S Boyland Street, from document_page_index. Verbatim.
THOMAS_588 = [
    _row("A-100.00", "FIRST FLOOR PLAN", "first"),
    _row("A-100.01", "FIRST FLOOR PLAN", "first"),
    _row("A-101.00", "SECOND FLOOR PLAN", "second"),
    _row("A-102.00", "THIRD FLOOR PLAN", "Third"),
    _row("A-102.00", "", ""),                       # the extraction defect
    _row("A-103.00", "FOURTH FLOOR PLAN", "Fourth"),
    _row("A-104.00", "MEZZANINE PLAN", "mezzanine"),
    _row("A-104.00", "", ""),
    _row("A-105.00", "ROOF AND BULKEAD PLAN", ""),   # the typo is production's
    _row("A-105.01", "ROOF AND BULKHEAD PLAN", ""),
    _row("A-200.01", "FRONT AND REAR ELEVATIONS",
         "BASE PLANE, SECOND FLOOR, THIRD FLOOR, FOURTH FLOOR, MEZZANINE, "
         "ROOF, BULKHEAD"),
    _row("A-300.00", "LONGITUDINAL SECTIONS", "BULKHEAD 93.37' +60'-0\""),
    _row("A-302.00", "SECTION DETAILS", "FIRST FLOOR"),
    _row("A-400.00", "WINDOW SCHEDULE", "FINISHED FLOOR"),
    _row("A-500.00", "WALL PARTITION", ""),
    _row("FA-006", "MEZZANINE FLOOR FIRE ALARM PLAN", "mezzanine"),
    _row("FA-007", "ROOF FIRE ALARM PLAN", "roof"),
    _row("M-106.00", "BULKHEAD HVAC PLANS", ""),
    _row("P-105.00", "ROOF FLOOR DOMESTIC WATER & GAS PLANS", "ROOF FLOOR"),
    _row("P-200.00", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN",
         "first underground"),
    _row("P-207.00", "BULKHEAD SANITARY & STORM PLAN", "bulkhead"),
    _row("SSP-004.00", "SITE SAFETY PLAN - FOUNDATION-(PHASE-02)", ""),
    _row("SSP-005.00", "SITE SAFETY PLAN - SUPERSTRUCTURE(PHASE-03)", ""),
    _row("SSP-007.00", "FIRE SAFETY PLAN -02", "Third, Fourth"),
    _row("1 OF 3", "PROPOSED DCDA & RPZ INSTALLATION AT:", ""),
    _row("2 OF 3", "PROPOSED DCDA & RPZ INSTALLATION AT:",
         "FIRST FLOOR, SECOND FLOOR"),
    _row("Z-002.00", "BUILDING HEIGHT AND SETBACK DIAGRAMS",
         "BULKHEAD, ROOF, MEZZANINE, FOURTH FLOOR, THIRD FLOOR, SECOND FLOOR, "
         "FIRST FLOOR, BASE PLANE"),
    _row("T-001.00", "COVER SHEET", ""),
]


class ItReads588(unittest.TestCase):

    def setUp(self):
        self.out = suggest_levels(THOMAS_588)
        self.labels = [lv["label"] for lv in self.out["levels"]]

    def test_the_answer_is_four_storeys_a_mezzanine_a_roof_and_a_bulkhead(self):
        self.assertEqual(
            self.labels,
            ["Foundation", "1st Floor", "2nd Floor", "3rd Floor", "4th Floor",
             "Mezzanine", "Roof", "Bulkhead"])

    def test_the_patch_an_apply_would_set(self):
        self.assertEqual(self.out["patch"], {
            "building_stories": 4,
            "has_mezzanine": True,
            "has_roof_bulkhead": True,
        })

    def test_a_mezzanine_does_not_count_as_a_storey(self):
        """It has its own flag because it is its own level. Counting it would
        inflate the number the §3310 major-building test reads, which is the
        one field on this form that changes what logs the job must keep."""
        self.assertEqual(self.out["patch"]["building_stories"], 4)

    def test_nothing_claims_a_cellar(self):
        for lv in self.out["levels"]:
            self.assertNotIn(lv["token"], ("CELLAR", "SUB_CELLAR"))
        self.assertNotIn("has_cellar", self.out["patch"])
        self.assertNotIn("has_sub_cellar", self.out["patch"])

    def test_every_level_names_the_sheets_it_came_from(self):
        """"4th Floor" is a claim. "4th Floor — A-103.00" is a claim an admin
        can check in ten seconds against the drawing he already has."""
        by = {lv["label"]: lv["sheets"] for lv in self.out["levels"]}
        self.assertIn("A-100.00", by["1st Floor"])
        self.assertIn("A-103.00", by["4th Floor"])
        self.assertIn("A-104.00", by["Mezzanine"])
        self.assertIn("A-105.01", by["Roof"])
        self.assertIn("M-106.00", by["Bulkhead"])
        self.assertEqual(by["Foundation"], ["SSP-004.00"])

    def test_the_extraction_defect_is_REPORTED_not_absorbed(self):
        """Eleven architectural sheets are indexed twice on 588, once extracted
        and once entirely empty. The suggestion is drawn from a set with known
        holes in it and the form says so, rather than presenting a
        complete-looking list."""
        blank = [r for r in THOMAS_588 if not r["sheet_title"].strip()]
        self.assertEqual(self.out["title_gaps"], len(blank))
        self.assertGreater(len(blank), 0, "the fixture must carry the defect")
        self.assertEqual(self.out["pages"], len(THOMAS_588))


class ThreeStringsThatAreNotLevels(unittest.TestCase):

    def test_BASE_PLANE_is_a_zoning_datum(self):
        """ASSERTED ON THE TOKEN AND THE LABEL SET, NOT ON A SUBSTRING.

        `assertNotIn("base", label)` bans any label CONTAINING the word, which
        is satisfied or broken by anything that happens to contain it — a
        "Basement" chip would fail it for the wrong reason, and a token called
        `BP` would pass it while being the same defect. The exact sets are the
        claim: no token names it, no label names it, and it is not left in
        `unmapped` either, because it was excluded on purpose rather than
        misunderstood."""
        out = suggest_levels(THOMAS_588)
        self.assertNotIn("base plane", [u.lower() for u in out["unmapped"]])
        self.assertEqual(
            [lv["label"] for lv in out["levels"] if "base" in lv["label"].lower()],
            [])
        self.assertEqual(
            [lv["token"] for lv in out["levels"] if lv["token"].startswith("BASE")],
            [])
        # It appears on 588's elevations under a real sheet number, so the
        # fixture genuinely carries it — a skip that passed because the input
        # never mentioned it would prove nothing.
        self.assertTrue(any("BASE PLANE" in (r["floor"] or "") for r in THOMAS_588))

    def test_FINISHED_FLOOR_is_an_annotation(self):
        toks, _ = tokens_in("FINISHED FLOOR", field_is_a_level=True)
        self.assertEqual(toks, [])

    def test_a_phase_number_is_not_a_storey(self):
        """SITE SAFETY PLAN - SUPERSTRUCTURE(PHASE-03) and "2 OF 3" on a sewer
        form both carry digits. A title must say floor."""
        for title in ("SITE SAFETY PLAN - SUPERSTRUCTURE(PHASE-03)",
                      "PROPOSED DCDA & RPZ INSTALLATION AT:",
                      "FIRE SAFETY PLAN -02",
                      "TYPICAL SAFETY DETAILS-4"):
            with self.subTest(title):
                toks, _ = tokens_in(title)
                self.assertEqual([t for t in toks if t.startswith("FLOOR_")], [])

    def test_ROOF_FLOOR_is_the_roof_and_not_a_storey_above_it(self):
        toks, _ = tokens_in("ROOF FLOOR", field_is_a_level=True)
        self.assertEqual(toks, ["ROOF"])


class TheColumnSuppliesTheNoun(unittest.TestCase):
    """A bare ordinal means a floor in the `floor` column and nothing in a
    title. Reading both the same way is how a phase number becomes a storey."""

    def test_a_bare_ordinal_in_the_level_column_is_a_floor(self):
        for value, want in (("first", "FLOOR_1"), ("Fourth", "FLOOR_4"),
                            ("2nd", "FLOOR_2"), ("4TH", "FLOOR_4")):
            with self.subTest(value):
                toks, _ = tokens_in(value, field_is_a_level=True)
                self.assertEqual(toks, [want])

    def test_the_same_word_in_a_TITLE_is_nothing(self):
        for value in ("first", "Fourth", "2nd"):
            with self.subTest(value):
                self.assertEqual(tokens_in(value)[0], [])

    def test_a_title_that_says_floor_IS_read(self):
        self.assertEqual(tokens_in("FOURTH FLOOR PLAN")[0], ["FLOOR_4"])
        self.assertEqual(tokens_in("1ST FLOOR FIRE ALARM PLAN")[0], ["FLOOR_1"])

    def test_leftovers_are_collected_from_the_LEVEL_column_only(self):
        """Every sheet title that is not about a level would otherwise land in
        the admin's "not understood" list — window schedules, riser diagrams,
        the DCDA form — and forty irrelevant strings is a list nobody reads,
        which is how the one that matters gets missed."""
        out = suggest_levels(THOMAS_588)
        self.assertEqual(out["unmapped"], ["first underground"])


class TheAmbiguousOneIsNamedNotGuessed(unittest.TestCase):

    def test_first_underground_emits_no_token(self):
        toks, leftover = tokens_in("first underground", field_is_a_level=True)
        self.assertEqual(toks, [])
        self.assertEqual(leftover, ["first underground"])

    def test_and_it_does_not_become_the_first_floor(self):
        """FLOOR_1 would be wrong in both readings of that sheet."""
        out = suggest_levels([
            _row("P-200.00", "FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN",
                 "first underground"),
        ])
        self.assertEqual(out["levels"], [])
        self.assertEqual(out["unmapped"], ["first underground"])


class ItNeverThrowsAndNeverInvents(unittest.TestCase):

    def test_junk_rows(self):
        for rows in (None, [], [None], ["x"], [{}], [{"sheet_title": 7}],
                     [{"floor": ["FIRST FLOOR", "ROOF"]}]):
            with self.subTest(repr(rows)):
                out = suggest_levels(rows)
                self.assertIsInstance(out["levels"], list)
                self.assertIsInstance(out["patch"], dict)

    def test_a_list_valued_floor_field_is_read(self):
        out = suggest_levels([{"sheet_number": "X",
                               "floor": ["FIRST FLOOR", "ROOF"]}])
        self.assertEqual([lv["token"] for lv in out["levels"]],
                         ["FLOOR_1", "ROOF"])

    def test_an_absurd_storey_number_is_not_believed(self):
        """A two-digit misread on a title block must not silently make a
        project Major. Above the cap nothing is pre-filled."""
        out = suggest_levels([
            _row("X", f"{MAX_SUGGESTED_STORIES + 40}TH FLOOR PLAN")])
        self.assertNotIn("building_stories", out["patch"])

    def test_an_empty_index_suggests_nothing(self):
        out = suggest_levels([])
        self.assertEqual(out["levels"], [])
        self.assertEqual(out["patch"], {})
        self.assertEqual(out["pages"], 0)


class TheEndpointIsAGetAndWritesNothing(unittest.TestCase):

    def setUp(self):
        self.src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        start = self.src.index('/projects/{project_id}/suggested-levels')
        self.block = self.src[start:start + 5000]

    def test_it_is_registered_as_a_GET(self):
        self.assertIn('@api_router.get("/projects/{project_id}/suggested-levels")',
                      self.src)

    def test_nothing_in_it_writes(self):
        """NO WRITE WITHOUT CONFIRMATION, and the strongest form of that is a
        handler with no write in it. The admin presses Save on the form, which
        goes through update_project exactly as a typed answer does."""
        body = self.block[:self.block.index("\n@api_router")]
        for forbidden in ("update_one", "insert_one", "update_many",
                          "delete_one", "$set", "$addToSet"):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, body)

    def test_it_returns_what_it_would_REPLACE(self):
        """Apply on a project somebody has already answered for is an
        overwrite, and he should see what he is overwriting."""
        self.assertIn('out["current"]', self.block)

    def test_it_falls_back_to_the_file_ids(self):
        """The index is keyed by file_id in the delete path's own comment, and
        an older row may predate the project stamp. A suggestion that silently
        reads zero pages looks exactly like a building with no levels."""
        self.assertIn('"file_id": {"$in": file_ids}', self.block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
