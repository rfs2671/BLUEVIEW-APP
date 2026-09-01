"""The Cert Type column prints what was filed, and composes nothing.

REPLACES test_sst_class_label.py, whose subject -- a render-time composer that
reworded the filed label and appended the hours the CLASS carries -- has been
removed. The ruling it implemented is not withdrawn, and the distinction is the
whole point of this file:

    THE WORDING RULING STANDS. "The label is the word the card prints": the
    40-hour credential is printed WORKER, so certLabel writes "SST Worker" when
    a row is FILED. That is in oshaLogModel.js and it is asserted below.

    THE COMPOSITION IS GONE. The register no longer rewords a row at print
    time, because a filed document must print what was filed.

TWO SPELLINGS ON ONE REGISTER ARE CORRECT, NOT A REGRESSION. certLabel wrote
plain "SST" for SST_FULL until ca71e5f and "SST Worker" after it. A register
showing both is showing what each row was filed with. DO NOT "FIX" THE OLD ROWS:
rewriting them is exactly the render-time composition this change removes.

WHY IT WAS REMOVED. Bulletin 2024-007 sec V.6 requires a signature's integrity
to be maintained with "any changes detectable after signing". A column whose
content differs between two renderings of one stored document cannot be
validated against a single moment. The same reasoning retired the pre-shift
affirmation overlay; if composition is wrong for an attestation about a named
man, it is wrong for a classification the card did not state.
"""

import ast
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")
MODEL = (BACKEND.parent / "frontend" / "src" / "utils"
         / "oshaLogModel.js").read_text(encoding="utf-8")


def cell(stored, **extra):
    row = {"certification_type": stored, "worker_id": "w1",
           "card_number": "JH447TBBXG"}
    row.update(extra)
    return server._osha_type_cell(row)


class ItPrintsWhatWasFiled(unittest.TestCase):
    def test_a_row_filed_before_the_ruling_still_says_SST(self):
        """A FILED DOCUMENT SHOWS WHAT WAS FILED. This is the case a reader
        will be tempted to call a bug."""
        self.assertEqual(cell("SST"), "SST")

    def test_a_row_filed_after_it_says_SST_Worker(self):
        self.assertEqual(cell("SST Worker"), "SST Worker")

    def test_both_spellings_can_appear_on_one_register(self):
        """Expected and accepted. It resolves as cards are rescanned and rows
        are refiled; it is not repaired by rewriting old rows."""
        self.assertNotEqual(cell("SST"), cell("SST Worker"))

    def test_non_sst_rows_pass_through_untouched(self):
        for text in ("OSHA 10", "OSHA 30", "Forklift", "Scaffold", "Other"):
            self.assertEqual(cell(text), text)

    def test_an_empty_label_stays_empty(self):
        """The helper invents no placeholder: the two renderers have DIFFERENT
        empty conventions and each applies its own at the call site."""
        self.assertEqual(cell(""), "")
        self.assertEqual(cell(None), "")

    def test_it_never_appends_hours(self):
        for stored in ("SST", "SST Worker", "SST Supervisor", "SST Temporary"):
            out = cell(stored)
            self.assertNotIn("hr", out)
            self.assertNotIn("(", out)


class ItComposesNothing(unittest.TestCase):
    CODE = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server._osha_type_cell))))

    def test_the_cell_takes_only_the_stored_row(self):
        """Not merely unused -- the live-class index is gone from the
        signature, so nothing can pass one again."""
        self.assertEqual(
            list(inspect.signature(server._osha_type_cell).parameters), ["entry"])

    def test_it_reads_no_live_certification(self):
        for live in ("class_source", "live_type", "class_by_key",
                     "sst_class_label"):
            self.assertNotIn(live, self.CODE)

    def test_the_composer_is_gone_from_the_module(self):
        self.assertFalse(hasattr(server, "sst_class_label"))
        self.assertFalse(hasattr(server, "SST_CLASS_HOURS"))
        self.assertFalse(hasattr(server, "SST_COLOUR_DERIVED_SOURCES"))

    def test_and_the_index_no_longer_builds_what_fed_it(self):
        """An index nobody reads is the same defect as a field nobody writes."""
        self.assertEqual(len(server.osha_review_index([])), 3)
        # THE CODE, NOT THE DOCSTRING. The docstring deliberately RECORDS that
        # a fourth element was removed, so a naive scan of the unparsed source
        # matches its own explanation -- the sixth text-search assertion this
        # session to do that. The docstring is dropped explicitly.
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(server.osha_review_index)))
        node = tree.body[0]
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)):
            node.body = node.body[1:]
        self.assertNotIn("class_by_key", ast.unparse(node))

    def test_both_renderers_call_the_one_argument_form(self):
        self.assertEqual(SRC.count("_osha_type_cell(e)"), 2)
        self.assertNotIn("_osha_type_cell(e, ", SRC)


class TheWordingRulingIsNotWithdrawn(unittest.TestCase):
    """It moved to where it belongs: the moment a row is FILED."""

    def test_the_screen_still_files_SST_Worker_for_the_forty_hour_card(self):
        """"The label is the word the card prints." The 40-hour credential is
        printed WORKER, and a reader comparing a row to the card in a man's
        wallet has to find the same word on both."""
        self.assertIn("SST_FULL: 'SST Worker'", MODEL)

    def test_and_names_the_other_classes(self):
        for cls, text in (("SST_SUPERVISOR", "SST Supervisor"),
                          ("SST_TEMPORARY", "SST Temporary"),
                          ("SST_LIMITED", "SST Limited")):
            self.assertIn(f"{cls}: '{text}'", MODEL)

    def test_unspecified_keeps_saying_unspecified(self):
        """Never a class, never blank, and never the raw constant."""
        self.assertIn("SST_UNSPECIFIED: 'SST Unspecified'", MODEL)

    def test_the_screen_adds_no_hours_either(self):
        for hours in ("40 hr", "62 hr", "10 hr"):
            self.assertNotIn(hours, MODEL)


class TheHoursKnowledgeSurvivesAsDocumentation(unittest.TestCase):
    """Removing the composer must not lose what colour determines."""

    def test_the_colour_map_is_still_the_live_rule(self):
        self.assertEqual(
            {c: t for c, t in server._CARD_COLOR_CLASS_MAP.items()},
            {"BLUE": "SST_FULL", "YELLOW": "SST_SUPERVISOR",
             "RED": "SST_TEMPORARY"})

    def test_and_the_hours_are_recorded_beside_it(self):
        block = SRC.split("SST_DEAD_CLASSES")[1][:2200]
        for hours in ("40 hr", "62 hr", "10 hr"):
            self.assertIn(hours, block)

    def test_the_note_says_why_the_composer_went(self):
        block = SRC.split("SST_DEAD_CLASSES")[1][:2200]
        self.assertIn("render-time composition", block)


if __name__ == "__main__":
    unittest.main()
