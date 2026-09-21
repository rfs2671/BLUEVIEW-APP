"""A SHEET-NUMBER PREFIX NAMES A DISCIPLINE ONLY WHERE THE SET USES MORE THAN
ONE.

#642 made the sheet decide its discipline, prefix first: `A.4.1 PLUMBING PLAN`
became AR. Checked against the rendered title blocks, 588 Boyland's design set
numbers EVERY sheet `A.` — floor plans, the lighting plans A.3.0-A.3.1 and the
plumbing plans A.4.0-A.4.5 alike — so in that set `A` says nothing about whose
sheet it is, and a plumbing question filtered to PL could not reach five
plumbing plans.

── THE ORDER ──────────────────────────────────────────────────────────────

  1. the prefix, IF the set (file) numbers its sheets with two or more
  2. the title
  3. the prefix, when it is the set's only one
  4. the file name, never first; `other` is not evidence

(3) is not optional. Without it FA-001 'NOTES, LEGEND, DETAILS AND RISER
DIAGRAM' and SSP-010.00 'TYPICAL SAFETY DETAILS-1' reach the file name, which is
`other`, and 588 Boyland's KITCHEN PLAN and SITE PLAN sheets reach `ST` — the
street in "588 THOMAS BOYLAND ST SET", the defect #642 fixed. Measured on the
173-page corpus: taken literally the rule moved 28 pages, 8 of them back to ST
and 14 to other; with (3) it moves the 8 ruled pages and four cross-connection
pages that were `other`.

── ONE DISCIPLINE PER SHEET IS A KNOWN LIMIT ───────────────────────────────

A combined sheet gets one answer: A.3.2-A.3.4 'REFLECTED CEILING PLAN AND
LIGHTING PLAN' are AR, and the cross-connection set's 3 OF 3, 'NEW 2" COMBINED
WATER SERVICE, SPRINKLER WITH DOMESTIC TAKE-OFF PLAN', is SP.

`discipline_corpus.json` is every page of the corpus with its set's prefixes,
the value #642 gave and the value now given, both computed from the code, not
typed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_text  # noqa: E402
from source_text import strip_python  # noqa: E402

d = plan_text.discipline_for_page
CORPUS = json.loads((Path(__file__).resolve().parent / "discipline_corpus.json")
                    .read_text(encoding="utf-8"))

BOYLAND_SET = ["A"]                       # 588 THOMAS BOYLAND ST SET: one prefix
AR_328 = ["A", "GN", "RCP", "T", "Z"]     # AR - 3.28.25: real prefixes
NONE = []                                 # cross connection: no sheet prefixes


class ASingleLetterSetFallsToTheTitle(unittest.TestCase):

    def test_the_eight_ruled_pages(self):
        for sheet, title, want in (
                ("A.3.0", "LIGHTING AND APPLIANCES SCHEDULE", "EL"),
                ("A.3.1", "LIGHTING PLAN", "EL"),
                ("A.4.0", "FINISHES SCHEDULE AND PLUMBING SPECS", "PL"),
                ("A.4.1", "PLUMBING PLAN", "PL"),
                ("A.4.2", "PLUMBING PLAN", "PL"),
                ("A.4.3", "PLUMBING PLAN", "PL"),
                ("A.4.4", "PLUMBING PLAN", "PL"),
                ("A.4.5", "PLUMBING PLAN", "PL")):
            self.assertEqual(d(sheet, title, "ST", set_prefixes=BOYLAND_SET),
                             want, sheet)

    def test_a_reflected_ceiling_plan_with_lighting_stays_architectural(self):
        for sheet, title in (
                ("A.3.2", "REFLECTED CEILING PLAN AND LIGHTING PLAN"),
                ("A.3.3", "REFLECTED CEILING PLAN AND LIGHTING PLAN"),
                ("A.3.4", "REFLECTED CEILING PLAN AND LIGHTING PLAN"),
                ("A.3.5", "RCP- LOBBY")):
            self.assertEqual(d(sheet, title, "ST", set_prefixes=BOYLAND_SET),
                             "AR", sheet)


class TheStreetCannotComeBack(unittest.TestCase):
    """The eight 588 SET pages whose titles name no discipline. Taken
    literally, the rule sent every one of them to the file name: `ST`."""

    PAGES = (("A.1.0", "SITE PLAN"), ("A.4.6", "BATHROOM TILE LAYOUT"),
             ("A.5.1", "KITCHEN KEY PLAN"), ("A.5.2", "KITCHEN KEY PLAN"),
             ("A.5.3", "KITCHEN KEY PLAN"), ("A.5.4", "KITCHEN KEY PLAN"),
             ("A.5.5", "KITCHEN PLAN"), ("A.5.6", "KITCHEN PLAN"))

    def test_they_stay_architectural(self):
        for sheet, title in self.PAGES:
            self.assertEqual(d(sheet, title, "ST", set_prefixes=BOYLAND_SET),
                             "AR", sheet)

    def test_the_file_name_does_not_reach_them(self):
        for sheet, title in self.PAGES:
            self.assertEqual(
                d(sheet, title, "ST", set_prefixes=BOYLAND_SET),
                d(sheet, title, "other", set_prefixes=BOYLAND_SET), sheet)


class DetailsNameNoDiscipline(unittest.TestCase):
    """The seven pages the title check flagged because 'DETAILS' mapped to AR.
    Each keeps the discipline its title block supports."""

    def test_the_seven(self):
        for sheet, title, file_disc, prefixes, want in (
                ("GN-002.00", "ADA COMPLIANCE TYPICAL DETAILS", "AR", AR_328, "GN"),
                ("GN-003.00", "ADA COMPLIANCE TYPICAL DETAILS", "AR", AR_328, "GN"),
                ("FA-001", "NOTES, LEGEND, DETAILS AND RISER DIAGRAM", "other", ["FA"], "FA"),
                ("SSP-010.00", "TYPICAL SAFETY DETAILS-1", "other", ["SSP"], "SSP"),
                ("SSP-011.00", "TYPICAL SAFETY DETAILS-2", "other", ["SSP"], "SSP"),
                ("SSP-012.00", "TYPICAL SAFETY DETAILS-3", "other", ["SSP"], "SSP"),
                ("SSP-013.00", "TYPICAL SAFETY DETAILS-4", "other", ["SSP"], "SSP")):
            self.assertEqual(d(sheet, title, file_disc, set_prefixes=prefixes),
                             want, sheet)

    def test_the_generic_words_map_to_nothing(self):
        for title in ("TYPICAL DETAILS", "FINISH SCHEDULE", "DOOR SCHEDULE",
                      "WALL DETAILS"):
            self.assertIsNone(plan_text.discipline_from_title(title), title)


class TheCrossConnectionSet(unittest.TestCase):
    """Pinned as ruled. No sheet prefixes and a file name that gives `other`,
    so the title decides."""

    def test_backflow_and_rpz_sheets_are_plumbing(self):
        for title in ("Backflow Prevention Assembly Installation Approval",
                      "APPLICATION FOR APPROVAL OF BACKFLOW PREVENTION ASSEMBLIES",
                      "PROPOSED DCDA & RPZ INSTALLATION AT:",
                      "PROPOSED DCDA & RPZ INSTALLATION AT:"):
            self.assertEqual(d("", title, "other", set_prefixes=NONE), "PL", title)

    def test_the_combined_service_sheet_is_sprinkler(self):
        """One discipline per sheet. 'WATER SERVICE' is deliberately not a
        plumbing term: a future combined fire and domestic service sheet
        would otherwise file as plumbing."""
        self.assertEqual(d("3 OF 3", 'NEW 2" COMBINED WATER SERVICE, SPRINKLER '
                           "WITH DOMESTIC TAKE-OFF PLAN", "other",
                           set_prefixes=NONE), "SP")
        self.assertIsNone(plan_text.discipline_from_title("NEW WATER SERVICE"))

    def test_a_page_with_nothing_stays_other(self):
        self.assertEqual(d("", "", "other", set_prefixes=NONE), "other")


class ASetWithRealPrefixesStillTrustsThem(unittest.TestCase):

    def test_prefix_wins(self):
        self.assertEqual(d("M-200.00", "PLUMBING SCHEDULE", "ME",
                           set_prefixes=["EN", "M"]), "ME")
        self.assertEqual(d("EN-001.00", "ENERGY COMPLIANCE", "PL",
                           set_prefixes=["EN", "P"]), "GN")
        self.assertEqual(d("A-101.00", "LIGHTING PLAN", "AR",
                           set_prefixes=AR_328), "AR")

    def test_prefixes_that_are_not_disciplines_do_not_count(self):
        self.assertEqual(plan_text.set_prefix_count(["A", "XX", "a"]), 1)
        self.assertIsNone(plan_text.set_prefix_count(None))


class AnUnknownSetKeepsThe642Order(unittest.TestCase):
    """No text layer, no profile: the prefix leads, exactly as before."""

    def test_unknown(self):
        self.assertEqual(d("A.4.1", "PLUMBING PLAN", "ST"), "AR")
        self.assertEqual(d("A.4.1", "PLUMBING PLAN", "ST", set_prefixes=None), "AR")


class TheWholeCorpus(unittest.TestCase):
    """Every page, against the value each version of the code gives."""

    def test_it_is_the_whole_corpus(self):
        self.assertEqual(len(CORPUS), 173)

    def test_every_page_gets_its_pinned_discipline(self):
        for r in CORPUS:
            got = d(r["sheet"] or "", r["title"] or "", r["file_discipline"],
                    set_prefixes=r["set_prefixes"])
            self.assertEqual(got, r["now"], (r["file"], r["page"], r["sheet"]))

    def test_exactly_the_ruled_pages_moved(self):
        moved = sorted((r["file"][:16], r["page"], r["sheet"] or "",
                        r["was_642"], r["now"])
                       for r in CORPUS if r["was_642"] != r["now"])
        boyland = "588 THOMAS BOYLA"
        self.assertEqual(moved, sorted(
            [(boyland, 25, "A.3.0", "AR", "EL"), (boyland, 26, "A.3.1", "AR", "EL")]
            + [(boyland, 31 + i, f"A.4.{i}", "AR", "PL") for i in range(6)]
            + [("cross connection", 1, "", "other", "PL"),
               ("cross connection", 2, "", "other", "PL"),
               ("cross connection", 4, "1 OF 3", "other", "PL"),
               ("cross connection", 5, "2 OF 3", "other", "PL")]))

    def test_the_spatial_sessions_sheets_do_not_move(self):
        """A-103/M-103 takeoff reads these by sheet; none may change."""
        for r in CORPUS:
            if r["sheet"] in ("A-103.00", "A-100.01", "M-103.00", "M-100.00",
                              "M-200.00"):
                self.assertEqual(r["now"], r["was_642"], r["sheet"])


class TheIndexerPassesTheSet(unittest.TestCase):
    """A parameter nobody passes is the #642 order with extra steps. Both
    places a page's discipline is decided must be handed the set."""

    SRC = strip_python((Path(__file__).resolve().parents[1] / "server.py")
                       .read_text(encoding="utf-8"))

    def test_both_call_sites_pass_set_prefixes(self):
        calls = re.findall(r"plan_text\.discipline_for_page\((.*?)\)\s*,",
                           self.SRC, re.S)
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertIn("set_prefixes=set_prefixes", c)

    def test_the_set_comes_from_the_file_profile(self):
        self.assertRegex(self.SRC, r'set_prefixes = \(list\(\(ctx\.get\("profile"\) or \{\}\)'
                                   r'\.get\("title_prefixes"\)')
        self.assertIn("set_prefixes=set_prefixes,\n                )", self.SRC)


if __name__ == "__main__":
    unittest.main()
