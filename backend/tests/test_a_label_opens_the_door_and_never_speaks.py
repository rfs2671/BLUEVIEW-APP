"""A LABEL MAY WIDEN WHAT IS FOUND. IT MAY NEVER BE WHAT IS SAID.

`rank` admitted any record sharing ONE word with the subject, and `search_plans`
then filled all eight slots with the best of a bad lot. Measured on the live
corpus 2026-09-18: all 40 questions a superintendent would actually ask
returned 8 records, `nothing found` was reachable for none of them, and "what
is the concrete pour schedule" reached a LIGHTING SCHEDULE on the shared word
'schedule'.

The floor fixes that by asking whether ONE record carries every word of the
subject. The set collectively is not enough — one record printing 'number' and
another printing 'ptac-2' 'cover' a question neither answers.

── WHY THE FLOOR COUNTS A VISION LABEL, AND WHAT THAT MUST NOT COST ──────────

Checked against the corpus before it was built: PACKAGE TERMINAL AIR
CONDITIONER, the expansion of PTAC, is printed on NO sheet. It exists only in
`label` on ten legend entries across M-100.00, M-101.00 and M-103.00. A
printed-only floor would answer "nothing found" to "how many packaged terminal
air conditioners" on a building that has 41 of them.

So the floor reads labels — it decides what may be FOUND. Everything about
what may be SAID is unchanged, and these tests are what say so: the floor runs
BEFORE `matched_only_through_label`, which still removes every label-only
record from what is returned. A label opens the door and never speaks through
it.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as ps  # noqa: E402

#: A legend entry whose mark is printed and whose expansion is a vision read.
#: This is the real shape on M-100.00: quote 'PTAC-1', label 'PACKAGE TERMINAL
#: AIR CONDITIONER'.
LEGEND = {"record_type": "legend_entry", "tier": "vision_read",
          "page_id": "p1", "sheet_number": "M-100.00", "quote": "PTAC-1",
          "label": "PACKAGE TERMINAL AIR CONDITIONER",
          "payload": {"tag": "PTAC-1"}}

#: A record that prints the mark and nothing of the expansion.
SCHEDULE = {"record_type": "schedule", "tier": "ocr_grid_cell",
            "page_id": "p2", "sheet_number": "M-200.00",
            "quote": "ROOMS PTAC UNITS SCHEDULE | PTAC-1 | 21",
            "payload": {"name": "ROOMS PTAC UNITS SCHEDULE"}}


class TheFloorAsksWhetherTheWordsAppearAtAll(unittest.TestCase):

    def test_one_record_carrying_every_word_meets_it(self):
        terms = ps.search_terms("ROOMS PTAC UNITS SCHEDULE")
        self.assertTrue(ps.meets_the_floor([SCHEDULE], terms))

    def test_a_set_may_not_cover_a_question_between_them(self):
        """The failure this replaced: one record prints 'number', another
        prints the mark, and neither answers the question."""
        a = dict(SCHEDULE, quote="Sheet List Table Sheet Number")
        b = dict(SCHEDULE, quote="PTAC-2")
        self.assertFalse(
            ps.meets_the_floor([a, b], ps.search_terms("PTAC-2 number plan")))

    def test_the_concrete_pour_question_no_longer_reaches_a_lighting_schedule(self):
        lighting = dict(SCHEDULE, quote="LIGHTING SCHEDULE FIXTURE | LOCATION")
        self.assertFalse(ps.meets_the_floor(
            [lighting], ps.search_terms("concrete pour schedule")))


class AskingWordsAreNotTheSubject(unittest.TestCase):

    def test_a_question_word_is_not_required_of_the_drawing(self):
        """`search_terms` drops 'how' as a stop word; the asking list handles
        the ones that survive it, like 'tall'."""
        terms = ps.search_terms("how tall is the parapet")
        self.assertEqual(terms, ["tall", "parapet"])
        self.assertEqual(ps.floor_terms(terms), ["parapet"])

    def test_a_subject_of_nothing_but_asking_words_keeps_them(self):
        """Stripping to nothing would empty every result, so the strict
        reading stands."""
        self.assertEqual(ps.floor_terms(["many", "size"]), ["many", "size"])

    def test_the_list_is_closed_and_every_word_carries_its_reason(self):
        """A floor that gains a word whenever a question fails is a tuned
        threshold wearing a different coat. Each entry justifies itself, and
        this fails on any that does not."""
        for word, why in ps.ASKING_WORDS.items():
            self.assertTrue(
                why and len(why.split()) >= 4,
                f"{word!r} is in the asking list with no reason given")
            self.assertEqual(word, word.lower())

    def test_it_stays_small(self):
        """Not a threshold to tune. If this needs raising, the thing to
        question is the approach, not the number."""
        self.assertLessEqual(len(ps.ASKING_WORDS), 25)


class ALabelOpensTheDoor(unittest.TestCase):

    def test_a_label_can_satisfy_the_floor(self):
        """The suite asks this as 'package terminal air conditioner', and the
        ONE sheet that prints it prints PACKAGED - which 'package' does not
        match, because term_forms knows plurals and not participles. So the
        label is the only thing in the corpus that carries the word the
        question uses, and without it a building with 41 of them answers
        'nothing found'."""
        terms = ps.search_terms("package terminal air conditioner")
        self.assertTrue(ps.meets_the_floor([LEGEND], terms),
                        "the legend's label did not open the door")

    def test_but_that_record_is_not_returnable(self):
        """CONDITION 1. The same record that satisfied the floor is removed
        from what comes back, because it matched on nothing the sheet prints."""
        terms = ps.search_terms("package terminal air conditioner")
        self.assertTrue(ps.matched_only_through_label(LEGEND, terms))

    def test_a_record_printing_the_words_is_not_removed(self):
        terms = ps.search_terms("ROOMS PTAC UNITS SCHEDULE")
        self.assertFalse(ps.matched_only_through_label(SCHEDULE, terms))

    def test_the_label_never_reaches_a_render(self):
        """Stronger than expected, and worth pinning: `render_records` does not
        merely omit the label, it refuses the record entirely. A legend entry
        reached only through its label renders as nothing at all."""
        render = ps.render_records([LEGEND], "package terminal air conditioner")
        self.assertNotIn("PACKAGE TERMINAL AIR CONDITIONER", render)
        self.assertNotIn("PTAC-1", render)
        # Through the CONSTANT, not the words. The refusal was reworded on
        # 2026-09-20 — it no longer claims what the drawings contain — and a
        # test pinned to the old string fails for a wording change while the
        # behaviour it guards is untouched.
        self.assertEqual(render, ps.NOT_FOUND)

    def test_a_printed_record_still_renders(self):
        render = ps.render_records([SCHEDULE], "ROOMS PTAC UNITS SCHEDULE")
        self.assertIn("PTAC-1", render)

    def test_the_gate_still_catches_a_label_in_an_answer(self):
        leaked = ps.contains_label(
            "These are package terminal air conditioners.", [LEGEND])
        self.assertTrue(leaked, "a label reached an answer uncaught")


class TheOrderIsTheDesign(unittest.TestCase):
    """The floor runs BEFORE label-only records are dropped. Reversed, the
    PTAC question would floor out on a corpus that prints the expansion
    nowhere — 'nothing found' for 41 units."""

    def test_checking_the_floor_after_the_filter_would_empty_it(self):
        terms = ps.search_terms("package terminal air conditioner")
        survivors = [r for r in (LEGEND, SCHEDULE)
                     if not ps.matched_only_through_label(r, terms)]
        self.assertFalse(ps.meets_the_floor(survivors, terms),
                         "this is the order the code must NOT use")
        self.assertTrue(ps.meets_the_floor([LEGEND, SCHEDULE], terms),
                        "this is the order the code uses")


if __name__ == "__main__":
    unittest.main()
