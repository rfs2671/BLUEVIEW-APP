"""Which sheet a page IS, and whether it is a sheet at all.

588 Thomas S Boyland St, 2026-09-16. Three current roof plans, all one
drawing:

  A-105.00  Owners set - 6.9.26.pdf        'A-105.00 16 OF 31 ROOF AND BULKEAD PLAN'
  A-105.01  AR - 8.18.26.pdf               'A-105.01 16 OF 31 ROOF AND BULKEAD PLAN'
  A-300     AR - 6.9.26 (Gas change).pdf   no id in the title strip at all

Two faults, and they are unrelated to each other:

  * A-300 is a section callout, not a sheet number. The page's only sheet ids
    are the five its bubbles point at — A-200, A-201, A-202, A-300, A-301 —
    and the old validate_sheet_number accepted the model's reading because it
    appeared "in the page text". It collides with the real A-300.00,
    LONGITUDINAL SECTIONS.
  * AR - 8.18.26.pdf reissues ten sheets and bumps every suffix, .00 -> .01.
    Supersession compared exact strings, so nine pairs stayed current at once.

And the project's files hold DOB forms numbered 'Page 2 of 2', a survey
numbered '0' and an attachment numbered 'F', which were being listed to the
agent as sheets.
"""

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib import plan_text as pt  # noqa: E402
from tests.test_plan_index_v3 import _Db, _run, T0  # noqa: E402


class ACalloutIsNotASheetNumber(unittest.TestCase):
    """The three pages, exactly as pdfplumber reads them out of the PDFs.

    The strips are trimmed to their tails; the ids and the place are what
    plan_text actually extracts from those pages."""

    # AR - 6.9.26 (Gas change).pdf p2. No title block in the text layer at
    # all: the strip ends in the legend and two section bubbles.
    GAS_P2_STRIP = ('LEGEND A FLOOR/AREA/ROOF DRAIN SMOKE/CARBON MONOXIDE DETECTOR '
                    'EXIT SIGN DOOR TAG WINDOW TAG WALL TAG W1 EXHAUST FAN W1 1 A-300 1 A-200')
    GAS_P2_IDS = ["A-300", "A-200"]
    PAGE_IDS = ["A-300", "A-301", "A-200", "A-201", "A-202"]

    # AR - 8.18.26.pdf p7. Same two bubbles in the strip, plus a title block.
    P7_STRIP = ("DRAWING NO. SHEET NO. 588 THOMAS S BOYLAND STREET, BROOKLYN, NY 11212 "
                "A-105.01 16 OF 31 ROOF AND BULKEAD PLAN")
    P7_IDS = ["A-300", "A-200", "A-105.01"]

    def test_the_roof_plan_is_left_unnumbered_rather_than_filed_as_a_300(self):
        sn, flag = pt.validate_sheet_number(
            "A-300", self.GAS_P2_IDS, self.PAGE_IDS, None,
            pt.sheet_position(self.GAS_P2_STRIP), self.GAS_P2_STRIP)
        self.assertIsNone(sn, "A-300 is where this sheet POINTS, not what it is")
        self.assertEqual(flag, "sheet_number_ambiguous")

    def test_the_sheet_beside_it_in_the_same_file_is_unaffected(self):
        strip = ("DRAWING NO. SHEET NO. 588 THOMAS S BOYLAND STREET, BROOKLYN, NY 11212 "
                 "A-100.00 11 OF 31 FIRST FLOOR PLAN")
        sn, flag = pt.validate_sheet_number(
            "A-100.00", ["A-300", "A-200", "A-100.00"], self.PAGE_IDS, None,
            pt.sheet_position(strip), strip)
        self.assertEqual((sn, flag), ("A-100.00", None))

    def test_the_august_reissue_is_unaffected(self):
        sn, flag = pt.validate_sheet_number(
            "A-105.01", self.P7_IDS, self.PAGE_IDS, None,
            pt.sheet_position(self.P7_STRIP), self.P7_STRIP)
        self.assertEqual((sn, flag), ("A-105.01", None))

    def test_the_place_beats_the_model_when_they_disagree(self):
        sn, flag = pt.validate_sheet_number(
            "A-300", self.P7_IDS, self.PAGE_IDS, None,
            pt.sheet_position(self.P7_STRIP), self.P7_STRIP)
        self.assertEqual((sn, flag), ("A-105.01", "sheet_number_corrected"))

    def test_the_body_text_never_gets_a_vote(self):
        sn, _ = pt.validate_sheet_number("A-200", [], ["A-200", "A-201"])
        self.assertIsNone(sn)

    def test_a_lone_title_block_id_is_still_taken(self):
        self.assertEqual(
            pt.validate_sheet_number("A-105.01", ["A-105.01"], ["A-105.01", "A-300"]),
            ("A-105.01", None))

    def test_the_model_reading_a_drawing_list_position_is_still_corrected(self):
        # S-001.00's title strip reads '2S-001.00' and the model returned "2".
        self.assertEqual(pt.validate_sheet_number("2", ["S-001.00"], ["S-001.00"]),
                         ("S-001.00", "sheet_number_corrected"))

    def test_two_title_ids_still_prefer_the_decimal_one(self):
        sn, flag = pt.validate_sheet_number(None, ["A-100", "A-105.00"], [])
        self.assertEqual((sn, flag), ("A-105.00", "sheet_number_from_text"))

    def test_several_full_ids_let_the_model_choose_between_them(self):
        sn, flag = pt.validate_sheet_number("T-001.00", ["T-001.00", "A-100.00"], [])
        self.assertEqual((sn, flag), ("T-001.00", "sheet_number_ambiguous"))

    def test_the_drawing_list_is_the_one_second_chance(self):
        sn, flag = pt.validate_sheet_number(
            "A-300", [], self.PAGE_IDS, {"A-104.00": 15, "A-105.00": 16}, (16, 31))
        self.assertEqual((sn, flag), ("A-105.00", "sheet_number_from_drawing_list"))

    def test_an_ambiguous_drawing_list_position_resolves_nothing(self):
        sn, flag = pt.validate_sheet_number(
            "A-300", [], self.PAGE_IDS, {"A-105.00": 16, "A-105.01": 16}, (16, 31))
        self.assertIsNone(sn)
        self.assertEqual(flag, "sheet_number_unresolved")


class ASheetsPlaceInItsOwnSet(unittest.TestCase):

    def test_it_is_read_off_the_title_block(self):
        self.assertEqual(
            pt.sheet_position("A-105.00 16 OF 31 ROOF AND BULKEAD PLAN"), (16, 31))
        self.assertEqual(pt.sheet_position("SHEET 1 of 1"), (1, 1))

    def test_nonsense_is_not_a_place(self):
        self.assertIsNone(pt.sheet_position("ROOF AND BULKEAD PLAN"))
        self.assertIsNone(pt.sheet_position("32 OF 31"))     # past the end
        self.assertIsNone(pt.sheet_position("0 OF 31"))

    def test_a_dimension_is_not_a_place(self):
        self.assertIsNone(pt.sheet_position('SCALE 3/32" = 1\'-0"'))

    def test_the_tail_of_a_sheet_number_is_not_a_place(self):
        """The plumbing set prints 'P-202.00 of 19' — the number, then how
        many sheets there are, with no index. Read naively the '00' of
        P-202.00 is position zero, and the id sitting in front of it is
        'P-202': every P sheet in the set would have been renumbered to a
        truncated id that nothing can look up."""
        strip = ("588 THOMAS S. BOYLAND ST BROOKLYN, NY DOB JOB #: B01141294-S5. "
                 "P-202.00 of 19 D.O.B. JOB #:")
        self.assertIsNone(pt.sheet_position(strip))
        self.assertIsNone(pt._id_beside_position(strip))
        self.assertEqual(
            pt.validate_sheet_number("P-202.00", ["P-202.00"], [], None,
                                     pt.sheet_position(strip), strip),
            ("P-202.00", None))

    def test_a_place_that_makes_no_sense_is_skipped_not_taken(self):
        # '0 of 19' is rejected, and the real place later in the strip wins.
        strip = "P-202.00 of 19 ... A-105.01 16 OF 31"
        self.assertEqual(pt.sheet_position(strip), (16, 31))
        self.assertEqual(pt._id_beside_position(strip), "A-105.01")


class WhatCountsAsASheetNumber(unittest.TestCase):

    def test_the_drawings(self):
        for sn in ("A-105.00", "A-300", "S-001.00", "RCP-001.00", "SSP-013.00",
                   "GN-001.00", "M-200.00", "FA-007"):
            with self.subTest(sn=sn):
                self.assertTrue(pt.looks_like_a_sheet_number(sn))

    def test_the_documents_that_were_listed_as_drawings(self):
        # Every one of these is a current row on 588 Boyland.
        for sn in ("0", "Page 2 of 2", "1 OF 1", "1 OF 3", "F", "6/16/2025",
                   "BWSO-ALL-FRM-07-30-2018", "1", "", None):
            with self.subTest(sn=sn):
                self.assertFalse(pt.looks_like_a_sheet_number(sn))


class ADotOhOneIsTheSameSheetRevised(unittest.TestCase):

    def setUp(self):
        self.db = _Db()
        p = mock.patch.object(server, "db", self.db)
        p.start()
        self.addCleanup(p.stop)

    def _file(self, fid, days, name):
        self.db.project_files.rows.append(
            {"_id": fid, "project_id": "p1", "created_at": T0 + timedelta(days=days),
             "name": name})

    def _page(self, fid, page, sheet, file_hash, position=None):
        self.db.document_page_index.rows.append({
            "_id": f"{fid}-{page}", "project_id": "p1", "file_id": fid,
            "page_number": page, "sheet_number": sheet, "file_hash": file_hash,
            "superseded_by": None, "revision_date": None, "sheet_position": position,
        })

    def _row(self, rid):
        return next(r for r in self.db.document_page_index.rows if r["_id"] == rid)

    def _boyland_architectural(self):
        """The three architectural files, as they sit in the project."""
        self._file("owners", 0, "Owners set - 6.9.26.pdf")
        self._file("ar825", 1, "AR - 8.18.26.pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._page("owners", 6, "A-105.00", "h-owners")
        self._page("ar825", 7, "A-105.01", "h-825")
        self._page("ar325", 16, "A-105.00", "h-325")

    def test_the_august_reissue_supersedes_the_june_sheet(self):
        self._boyland_architectural()
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("ar825-7")["superseded_by"])
        self.assertEqual(self._row("owners-6")["superseded_by"], "ar825")
        self.assertEqual(self._row("ar325-16")["superseded_by"], "ar825")

    def test_a_number_with_no_suffix_cannot_hide_one_that_has_it(self):
        """The fault this ordering exists for. A roof plan misfiled as 'A-300'
        would stem to the same thing as A-300.00, LONGITUDINAL SECTIONS — and
        its file is newer, so the real sheet would have lost."""
        self._file("gas", 0, "AR - 6.9.26 (Gas change).pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._page("gas", 2, "A-300", "h-gas")
        self._page("ar325", 20, "A-300.00", "h-325")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("ar325-20")["superseded_by"],
                          "LONGITUDINAL SECTIONS was hidden by a mis-read roof plan")
        self.assertIsNone(self._row("gas-2")["superseded_by"])

    def test_the_same_number_in_two_files_still_supersedes(self):
        self._file("owners", 0, "Owners set - 6.9.26.pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._page("owners", 1, "A-101.00", "h-owners")
        self._page("ar325", 12, "A-101.00", "h-325")
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("ar325-12")["superseded_by"], "owners")

    def test_a_cover_sheet_is_reissued_within_its_own_set(self):
        """AR - 8.18.26's T-001.01 is AR - 3.28.25's T-001.00, redrawn. The
        structural set's own T-001.00 is a different cover and is untouched:
        the stem key is scoped by discipline, which is what the T-/EN-/GN-
        exclusion was protecting."""
        self._file("ar825", 1, "AR - 8.18.26.pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._file("st", 3, "ST - 7.29.26.pdf")
        self._page("ar825", 1, "T-001.01", "h-825")
        self._page("ar825", 6, "A-100.01", "h-825")
        self._page("ar325", 1, "T-001.00", "h-325")
        self._page("ar325", 11, "A-100.00", "h-325")
        self._page("st", 1, "T-001.00", "h-st")
        self._page("st", 2, "S-101.00", "h-st")
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("ar325-1")["superseded_by"], "ar825")
        self.assertIsNone(self._row("ar825-1")["superseded_by"])
        self.assertIsNone(self._row("st-1")["superseded_by"],
                          "the structural cover is not the architectural one")

    def test_the_same_general_sheet_in_two_issues_is_not_a_reissue(self):
        """Both files print GN-001.00 — nothing was renumbered, so nothing was
        replaced, and the old exclusion still holds. See
        test_plan_index_v3.py for the cross-discipline half of this."""
        self._file("ar825", 1, "AR - 8.18.26.pdf")
        self._file("ar901", 0, "AR - 9.1.26.pdf")
        self._page("ar825", 3, "GN-001.00", "h-825")
        self._page("ar825", 6, "A-100.01", "h-825")
        self._page("ar901", 1, "GN-001.00", "h-901")
        self._page("ar901", 2, "A-101.00", "h-901")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("ar825-3")["superseded_by"])
        self.assertIsNone(self._row("ar901-1")["superseded_by"])

    def test_two_places_in_the_set_means_two_sheets(self):
        """Corroboration. If the title blocks say 16 of 31 and 22 of 31, a
        shared stem is a coincidence and neither sheet is touched."""
        self._file("ar825", 1, "AR - 8.18.26.pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._page("ar825", 7, "A-105.01", "h-825", position=[22, 31])
        self._page("ar325", 16, "A-105.00", "h-325", position=[16, 31])
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("ar325-16")["superseded_by"])
        self.assertIsNone(self._row("ar825-7")["superseded_by"])

    def test_one_place_stated_and_one_unknown_still_supersedes(self):
        """Corroboration only. Most title blocks do not print a place, and
        requiring one would turn the fix off for the whole project."""
        self._boyland_architectural()
        self._row("ar825-7")["sheet_position"] = [16, 31]
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("owners-6")["superseded_by"], "ar825")

    def test_a_stale_revision_cloud_does_not_outrank_the_issue_date(self):
        """Z-001, exactly as the project holds it. AR - 3.28.25's Z-001.00
        carries a title-block revision date of 2/27/2025; AR - 8.18.26's
        Z-001.01, the sheet that replaces it, carries none. Ordering by
        revision date first made the March sheet supersede the August one."""
        self._file("ar825", 1, "AR - 8.18.26.pdf")
        self._file("ar325", 2, "AR - 3.28.25.pdf")
        self._page("ar825", 2, "Z-001.01", "h-825")
        self._page("ar325", 2, "Z-001.00", "h-325")
        self.db.document_page_index.rows[-1]["revision_date"] = "2/27/2025"
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("ar325-2")["superseded_by"], "ar825")
        self.assertIsNone(self._row("ar825-2")["superseded_by"])

    def test_a_stale_cloud_does_not_win_a_plain_sheet_number_either(self):
        """The same fault, on the exact-number key. Only the OLDER sheet was
        ever clouded, so a revision date exists on one side and not the other,
        and reading it first hands the older file the win. FA-007 has no
        suffix, so this is the plain key and not the reissue one."""
        self._file("new", 0, "FA - 8.30.26.pdf")
        self._file("old", 1, "FA - 6.30.26.pdf")
        self._page("new", 7, "FA-007", "h-new")
        self._page("old", 7, "FA-007", "h-old")
        self.db.document_page_index.rows[-1]["revision_date"] = "5/12/2026"
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("old-7")["superseded_by"], "new")
        self.assertIsNone(self._row("new-7")["superseded_by"])

    def test_the_revision_date_still_breaks_a_tie_between_two_same_day_issues(self):
        self._file("a", 0, "AR - 6.9.26 (Gas change).pdf")
        self._file("b", 1, "AR - 6.9.26.pdf")
        self._page("a", 1, "FA-007", "h-a", )
        self._page("b", 1, "FA-007", "h-b")
        self.db.document_page_index.rows[-1]["revision_date"] = "6/9/2026"
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("a-1")["superseded_by"], "b")

    def test_agreeing_places_supersede(self):
        self._boyland_architectural()
        self._row("ar825-7")["sheet_position"] = [16, 31]
        self._row("owners-6")["sheet_position"] = [16, 31]
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("owners-6")["superseded_by"], "ar825")


class ADocumentIsNotADrawing(unittest.TestCase):

    def test_the_row_says_which_it_is(self):
        import inspect
        src = inspect.getsource(server._index_single_page)
        self.assertIn("looks_like_a_sheet_number", src)
        self.assertIn('"is_document"', src)

    def test_forms_are_kept_out_of_the_sheet_index_the_agent_is_given(self):
        import inspect
        src = inspect.getsource(server._sheet_index_lines)
        self.assertIn('"is_document": {"$ne": True}', src)

    def test_and_out_of_sheet_lookup(self):
        import inspect
        src = inspect.getsource(server._find_named_sheet)
        self.assertIn('"is_document": {"$ne": True}', src)

    def test_their_text_is_still_searched(self):
        # _current_v3_chunks reads the page rows through _current_page_filter,
        # which knows nothing about is_document. A backflow-prevention form is
        # still the answer to a question about backflow prevention.
        import inspect
        # Anchored: the field only ever appears in a query as a quoted key, and
        # a bare word would be satisfied by any line that merely contains it.
        self.assertNotIn('"is_document"', inspect.getsource(server._current_page_filter))
        self.assertNotIn('"is_document"', inspect.getsource(server._current_v3_chunks))


if __name__ == "__main__":
    unittest.main()
