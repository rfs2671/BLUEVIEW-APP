"""The SST label says the word the card prints, and names hours only when
colour determined the class.

THE LABEL. `SST_FULL` printed plainly "SST". The 40-hour credential is printed
**Worker** on the card, and a reader comparing this register to the card in a
man's wallet has to find the same word on both. `SST_UNSPECIFIED` printed the
raw constant `SST_UNSPECIFIED` on a document that goes to lenders -- the
frontend note called it "ugly and true" and left "Part 3A decides what it
should say". It says "SST Unspecified": the same claim, legibly.

THE HOURS, and why they are not simply looked up. Hours are a property of the
CLASS, never something read off the card -- the OCR prompt already forbids
returning an hours value as a class, because "40 hours" and "Worker" are one
class stated two ways. So hours may be shown only when the class came from the
signal that does not wash off:

    BLUE   -> SST_FULL        40 hr   the common card, carries NO class text
    YELLOW -> SST_SUPERVISOR  62 hr
    RED    -> SST_TEMPORARY   10 hr   the OSHA course; SIX MONTHS, not five years

D6 stores that provenance as `class_source`, and only two of its five values
earn hours: `color_and_text` (the one confirmed state) and `color_only` (the
40-hour card, which has no class text to corroborate with). `text_only` is an
OCR'd word on a card that may not carry one -- exactly the reading this rule
refuses. `conflict` produces no class at all. An absent `class_source` predates
colour entirely.

NOTHING OTHERWISE, AND NO MARKER. A reader who sees "(62 hr)" on one row and
not the next reads it as a difference between two WORKERS, not between two
photographs. Making the distinction visible would put our OCR confidence onto a
compliance record, which is not what that document is for. Absent is the honest
form: the label says what is known and stops. The resulting unevenness is real
and is the lesser harm; it resolves as cards are rescanned.

A SPACE, NOT AN EM DASH. The ruling asked for "SST -- Supervisor".
AbsentKeyIsStatedTest forbids `&mdash;` in a rendered document outside the
sanctioned "&mdash; Not recorded", and it is right on the substance: four
columns of this same table print `&mdash;` to mean ABSENT, so a dash inside a
Cert Type label sits beside dashes meaning "no cert type recorded" and reads as
one. The ruling's substance is the WORD, and it survives the punctuation.
"""

import ast
import inspect
import os
import re
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


def label(stored, live_type=None, class_source=None):
    return server.sst_class_label(stored, live_type, class_source)


class TheLabelIsTheWordTheCardPrints(unittest.TestCase):
    def test_the_forty_hour_card_says_worker_not_just_SST(self):
        """The register called it plainly "SST". The card says Worker."""
        self.assertEqual(label("SST", "SST_FULL", "text_only"), "SST Worker")

    def test_supervisor_says_supervisor(self):
        self.assertEqual(label("SST Supervisor", None, None), "SST Supervisor")

    def test_temporary_says_temporary(self):
        self.assertEqual(label("SST Temporary", None, None), "SST Temporary")

    def test_unspecified_keeps_saying_unspecified(self):
        """Never a class, never blank, and never the raw constant."""
        out = label("SST_UNSPECIFIED", "SST_UNSPECIFIED", "color_only")
        self.assertEqual(out, "SST Unspecified")

    def test_unspecified_never_takes_hours(self):
        """It is the ABSENCE of an answer. No colour can lend it a duration."""
        for src in ("color_only", "color_and_text", "text_only", None):
            self.assertNotIn("hr", label("SST Unspecified", "SST_UNSPECIFIED", src))

    def test_a_dead_class_takes_no_hours_either(self):
        """SST_LIMITED ceased to be a valid card in August 2020. Naming its
        duration would dress a dead scheme as a live credential."""
        self.assertEqual(label("SST Limited", "SST_LIMITED", "color_and_text"),
                         "SST Limited")

    def test_no_em_dash_reaches_any_label(self):
        for cls, text in server.SST_CLASS_LABEL.items():
            self.assertNotIn("&mdash;", text, cls)
            self.assertNotIn("—", text, cls)


class HoursOnlyWhenColourDeterminedTheClass(unittest.TestCase):
    def test_color_only_earns_them_this_is_the_forty_hour_card(self):
        """No class text exists to corroborate with, which is the NORMAL case
        for the commonest card on a NYC site -- not a defect."""
        self.assertEqual(label("SST", "SST_FULL", "color_only"),
                         "SST Worker (40 hr)")

    def test_color_and_text_earns_them(self):
        self.assertEqual(
            label("SST Supervisor", "SST_SUPERVISOR", "color_and_text"),
            "SST Supervisor (62 hr)")

    def test_the_temporary_card_is_ten_hours(self):
        self.assertEqual(label("SST Temporary", "SST_TEMPORARY", "color_only"),
                         "SST Temporary (10 hr)")

    def test_text_only_earns_NOTHING(self):
        """An OCR'd word on a card that may not carry one. This is the exact
        reading the rule refuses."""
        self.assertEqual(
            label("SST Supervisor", "SST_SUPERVISOR", "text_only"),
            "SST Supervisor")

    def test_a_conflict_earns_nothing(self):
        self.assertEqual(label("SST Supervisor", "SST_SUPERVISOR", "conflict"),
                         "SST Supervisor")

    def test_a_row_predating_colour_earns_nothing(self):
        """class_source absent. Most rows on a live register today."""
        self.assertEqual(label("SST Supervisor", "SST_SUPERVISOR", None),
                         "SST Supervisor")

    def test_a_row_that_joins_to_no_live_cert_earns_nothing(self):
        self.assertEqual(label("SST", None, None), "SST Worker")

    def test_every_class_source_is_covered_by_these_tests(self):
        """If D6 ever grows a sixth source, this fails rather than letting an
        unconsidered value fall into the hours branch by default."""
        self.assertEqual(server.SST_COLOUR_DERIVED_SOURCES,
                         frozenset({"color_and_text", "color_only"}))


class TheLiveClassMustMATCHTheFiledRow(unittest.TestCase):
    """The guard that stops a corrected worker record rewriting a filed one."""

    def test_a_row_filed_as_supervisor_never_takes_the_worker_cards_hours(self):
        """The worker's live cert was reclassified to SST_FULL after filing.
        The filed row still says Supervisor. Appending "(40 hr)" would state a
        duration for a class this row does not claim."""
        self.assertEqual(label("SST Supervisor", "SST_FULL", "color_only"),
                         "SST Supervisor")

    def test_and_the_reverse(self):
        self.assertEqual(label("SST", "SST_SUPERVISOR", "color_and_text"),
                         "SST Worker")

    def test_when_they_agree_the_hours_appear(self):
        self.assertEqual(label("SST", "SST_FULL", "color_and_text"),
                         "SST Worker (40 hr)")


class NonSSTRowsAreNotThisRulesBusiness(unittest.TestCase):
    def test_osha_rows_pass_through_untouched(self):
        for text in ("OSHA 10", "OSHA 30", "OSHA"):
            self.assertEqual(label(text, "SST_FULL", "color_only"), text)

    def test_so_do_the_other_cert_types_the_CP_can_pick(self):
        for text in ("Flagman", "Forklift", "Scaffold", "Other"):
            self.assertEqual(label(text, "SST_FULL", "color_only"), text)

    def test_an_empty_label_stays_empty(self):
        """The helper must not invent a placeholder: the two renderers have
        DIFFERENT empty conventions and each applies its own at the call site."""
        self.assertEqual(label("", None, None), "")
        self.assertEqual(label(None, None, None), "")


class FiledSpellingsAllResolve(unittest.TestCase):
    """A filed register is never rewritten, so the READER absorbs the history."""

    def test_the_pre_ruling_spellings_still_resolve(self):
        for stored in ("SST", "SST Supervisor", "SST_UNSPECIFIED"):
            self.assertTrue(label(stored, None, None).startswith("SST"))

    def test_dashes_of_every_kind_reduce_to_one_key(self):
        for stored in ("SST - Supervisor", "SST — Supervisor",
                       "SST &mdash; Supervisor", "sst supervisor",
                       "  SST   Supervisor  "):
            self.assertEqual(label(stored, None, None), "SST Supervisor",
                             f"{stored!r} did not resolve")


class BothRenderersUseIt(unittest.TestCase):
    def test_the_cell_helper_is_called_by_both(self):
        self.assertEqual(SRC.count("_osha_type_cell(e, class_by_key)"), 1)
        self.assertEqual(SRC.count("_osha_type_cell(e, _class_by_key)"), 1)

    def test_the_per_logbook_pdf_makes_the_same_join(self):
        """One register must not print two different class names depending on
        which document you ask for. Creating a SECOND divergence to avoid
        touching the Review column's would have been the worse trade."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.generate_single_logbook_html))))
        self.assertIn("osha_review_index(_wdocs)[3]", code)

    def test_a_failed_lookup_leaves_the_labels_alone(self):
        """A FAILED READ IS NOT A REFUSAL -- the posture preshift_affirmations
        already takes in this same function. A register must not fail to render
        because a lookup did."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.generate_single_logbook_html))))
        self.assertIn("_class_by_key = {}", code)
        self.assertIn("[osha] class lookup failed", code)

    def test_the_index_carries_the_class(self):
        idx = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.osha_review_index))))
        self.assertIn("class_by_key", idx)
        self.assertIn("cert.get('class_source')", idx)

    def test_it_is_built_in_the_SAME_pass_as_the_review_index(self):
        """A second walk over the same documents is how two indexes come to
        disagree about which row they describe."""
        self.assertEqual(SRC.count("def osha_review_index"), 1)


class TheScreenAndTheDocumentAgreeOnTheWORD(unittest.TestCase):
    def test_the_frontend_labels_match_the_backend_ones(self):
        for cls, text in server.SST_CLASS_LABEL.items():
            self.assertIn(f"{cls}: '{text}'", MODEL,
                          f"the screen and the register disagree about {cls}")

    def test_the_screen_adds_no_hours(self):
        """It cannot: class_source lives on the LIVE worker cert, which this
        screen does not have when it builds a row. It says the class and stops."""
        for hours in ("40 hr", "62 hr", "10 hr"):
            self.assertNotIn(hours, MODEL)

    def test_unspecified_is_no_longer_absent_from_the_map(self):
        self.assertIn("SST_UNSPECIFIED: 'SST Unspecified'", MODEL)


class TheHoursTableIsTheColourTable(unittest.TestCase):
    def test_it_matches_the_colours_D6_maps(self):
        self.assertEqual(server.SST_CLASS_HOURS, {
            "SST_FULL": "40 hr",
            "SST_SUPERVISOR": "62 hr",
            "SST_TEMPORARY": "10 hr",
        })

    def test_every_class_with_hours_is_one_a_colour_produces(self):
        produced = set(server._CARD_COLOR_CLASS_MAP.values())
        self.assertTrue(set(server.SST_CLASS_HOURS) <= produced,
                        "a class carries hours that no colour can determine, so "
                        "its hours could never honestly be shown")


if __name__ == "__main__":
    unittest.main()
