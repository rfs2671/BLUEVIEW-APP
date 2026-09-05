"""AN ANSWERED "NO" MUST NOT READ AS "NOBODY ANSWERED".

Twelve tables printed a raw stored value where a label belongs. The operator
read them off a filed report: `no` under a column headed `Injury`, the literal
`True` under `Status`, `flag: True` inside a joined cell, a tick against the
WORD "No" in the same column.

THE WORST WAS NOT COSMETIC. `_cs_item_body`'s guard read

    elif value not in (None, "", False, []):

and `False == 0` in Python, so a FALSE answer took the same branch as an absent
one: no row was appended, and if it was the item's only field the function
returned NOT_RECORDED. The superintendent answered and BC 3301.13.13 said he had
not. That branch was unguarded in BOTH directions -- nothing caught the bug and
nothing would have caught the fix.

THE MACHINERY EXISTED AND WAS SCOPE-TRAPPED. `_yn`, `has()` and
`toggle_map_rows` -- whose comments already argue "False and 0 ARE captured
values and render as captured" -- live INSIDE `generate_single_logbook_html`,
unreachable from the combined report, `get_daily_log_pdf` and `_cs_item_body`,
which is eight of the twelve sites. Only their scope was wrong. `answer_label`
is that rule at module level.

AND THERE WERE TWO `NOT_RECORDED` CONSTANTS with different literals -- an
entity inside the per-logbook renderer, the em-dash character at module level --
so one absence read two ways depending on which document you asked for, and each
spelling had a test pinning it. Now one.

STORED VALUES ARE NOT TOUCHED. Production holds only `'yes'`, `'no'` and null
(329 worker rows, zero capitalised, zero boolean), and the editor compares with
strict lowercase equality -- so rewriting a stored `"Yes"` would render the
toggle unselected and let the CP's first tap silently overwrite a filed answer.
The helper reads tolerantly and writes nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402
from lib.logbook.superintendent_log import (  # noqa: E402
    ITEMS_BY_KEY, _has_content,
)

_CODE = code_of("server.py")
NR = server.NOT_RECORDED


class TheHelperStatesTheThirdAnswer(unittest.TestCase):
    def test_absence_is_stated(self):
        for absent in (None, "", "   "):
            self.assertEqual(server.answer_label(absent), NR)

    def test_false_is_an_answer_not_an_absence(self):
        """THE BUG, AS A UNIT. `False` must never reach the same output as
        `None`."""
        self.assertEqual(server.answer_label(False), "No")
        self.assertNotEqual(server.answer_label(False), NR)

    def test_true_is_a_word_not_the_literal(self):
        self.assertEqual(server.answer_label(True), "Yes")

    def test_zero_is_an_answer_too(self):
        """`0 == False` is what made the original guard drop both."""
        self.assertEqual(server.answer_label(0), "0")
        self.assertNotEqual(server.answer_label(0), NR)

    def test_the_stored_lowercase_domain_reads_as_words(self):
        """What production actually holds."""
        self.assertEqual(server.answer_label("yes"), "Yes")
        self.assertEqual(server.answer_label("no"), "No")

    def test_it_tolerates_the_shapes_it_does_not_write(self):
        """Fixtures carry "Yes"/"No"; reading tolerantly costs nothing and is
        NOT a licence to normalise what is stored."""
        for v, want in (("Yes", "Yes"), ("No", "No"), ("YES", "Yes"),
                        ("true", "Yes"), ("false", "No"),
                        ("checked", "Yes"), ("unchecked", "No")):
            self.assertEqual(server.answer_label(v), want, v)

    def test_na_is_preserved_as_na(self):
        for v in ("na", "N/A", "n/a"):
            self.assertEqual(server.answer_label(v), "N/A")

    def test_an_unrecognised_value_is_shown_not_guessed(self):
        """Flattening an unknown answer to "No" would invent a finding."""
        self.assertEqual(server.answer_label("deferred"), "Deferred")

    def test_the_labels_are_overridable_without_changing_absence(self):
        self.assertEqual(server.answer_label(True, yes="Confirmed"), "Confirmed")
        self.assertEqual(server.answer_label(None, yes="Confirmed"), NR)


class TheSuperintendentsAnsweredNoSurvives(unittest.TestCase):
    """SITE 5 -- the data-loss bug, EXECUTED against real registered items.

    THE FIRST DRAFT OF THIS CLASS USED A SYNTHETIC ITEM AND PASSED NOTHING, and
    that is how the real root was found. `_cs_item_body` returned NOT_RECORDED
    before reaching the branch under test, because `_has_content` in
    lib/logbook/superintendent_log.py carried THE SAME defect one level up --
    `elif value not in (None, "", False)` -- so a block whose only field was
    False was judged to have no content at all and the renderer never saw it.
    Fixing the renderer alone changed nothing. Both are fixed; this proves the
    whole chain by rendering.
    """

    def _body(self, key, block):
        item = ITEMS_BY_KEY[key]
        return server._cs_item_body(item, block, "Mike")

    def test_a_false_answer_is_printed_not_dropped(self):
        out = self._body("daily_inspection",
                         {"inspected_on": "", "location": "", "result": False})
        self.assertIn("No", out)
        self.assertNotIn(NR, out)

    def test_a_false_inside_a_finding_row_survives(self):
        """'was it corrected?' answered NO is the answer that matters most on
        an unsafe-conditions item."""
        out = self._body("unsafe_conditions", {"entries": [{"corrected": False}]})
        self.assertIn("No", out)
        self.assertNotIn(NR, out)
        self.assertNotIn("False", out)

    def test_a_true_answer_is_a_word_not_the_literal(self):
        out = self._body("daily_inspection",
                         {"inspected_on": "", "location": "", "result": True})
        self.assertIn("Yes", out)
        self.assertNotIn("True", out)

    def test_a_genuinely_absent_item_still_says_so(self):
        """The other half. Fixing the drop must not turn absence into 'No'."""
        self.assertIn(NR, self._body("daily_inspection", {}))

    def test_the_presence_check_itself_counts_a_boolean(self):
        """The root, asserted directly: `_has_content` decides whether the
        renderer is reached at all."""
        item = ITEMS_BY_KEY["daily_inspection"]
        self.assertTrue(_has_content(item, {"result": False}))
        self.assertFalse(_has_content(item, {}))


class TheTablesThatHadNoCoverage(unittest.TestCase):
    """SITES 3, 4, 7 and 8 -- zero tests existed for any of them."""

    def test_site3_the_superintendent_checklist_status_is_a_label(self):
        i = _CODE.index("safety_rows = ")
        self.assertIn("answer_label(", _CODE[i:i + 400])

    def test_site4_the_daily_log_pdf_checklist_too(self):
        i = _CODE.index("safety_html = ")
        seg = _CODE[i:i + 500]
        self.assertIn("answer_label(", seg)

    def test_site4_stops_printing_the_raw_snake_case_key(self):
        """`item_key` reached paper as `fall_protection` while the combined
        report's twin already title-cased the same key."""
        i = _CODE.index("safety_html = ")
        self.assertIn('item_key.replace("_", " ").title()', _CODE[i:i + 500])

    def test_site7_a_nested_boolean_is_a_word(self):
        """`", ".join(f"{ik}: {iv}")` printed `flag: True`, and its `if iv`
        filter dropped a nested False entirely."""
        i = _CODE.index('v_str = ", ".join(')
        seg = _CODE[i:i + 320]
        self.assertIn("answer_label(iv)", seg)
        self.assertIn("isinstance(iv, bool) or iv", seg)

    def test_site8_the_orientation_column_stops_mixing_a_glyph_and_a_word(self):
        """A tick against the word "No" in one column."""
        i = _CODE.index("val = answer_label(checked)")
        self.assertGreater(i, 0)
        self.assertNotIn('"&#10003;" if checked else "No"', _CODE)


class ThePreShiftAnswersReadAsAnswers(unittest.TestCase):
    """SITES 1 and 2, in both renderers."""

    def test_both_renderers_route_the_two_answers_through_the_helper(self):
        self.assertEqual(_CODE.count('answer_label(w.get("had_injury"))'), 2)
        self.assertEqual(_CODE.count('answer_label(w.get("inspected_ppe"))'), 2)

    def test_neither_still_prints_the_raw_value(self):
        self.assertNotIn('w.get("had_injury") or "&mdash;"', _CODE)
        self.assertNotIn('w.get("inspected_ppe") or "&mdash;"', _CODE)


class ThereIsOneNotRecorded(unittest.TestCase):
    def test_the_shadowing_local_constant_is_gone(self):
        """Two constants, one name, different literals -- the same absence read
        two ways depending on which document you asked for."""
        self.assertEqual(_CODE.count("NOT_RECORDED = "), 1)

    def test_it_is_the_one_the_device_shows(self):
        """test_weather_display_and_chip_trade pins this against `fNotRecorded`
        in en.js: one record must read the same in the app and in the PDF."""
        self.assertEqual(server.NOT_RECORDED, "— Not recorded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
