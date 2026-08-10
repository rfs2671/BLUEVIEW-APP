"""A FAILED INSPECTION MUST NOT PRINT AS A PASSED ONE.

THE DEFECT THIS PREVENTS. The nine daily inspections were tick-chips, and both
PDF renderers printed them with

    ", ".join(k.replace("_", " ").title() for k, v in chk.items() if v)

which is correct while the value is a tick. The value is now {result, note} —
and A DICT IS TRUTHY. That same line would have listed a FAILED item in the
"Inspected" list, identically to a passed one, and dropped the note entirely.
On an NYC DOB 3301-02 that is a filed document stating an inspection was fine
when the Competent Person recorded that it was not.

Nothing warns you: the tests passed, the PDF rendered, the item appeared.

THREE STATES, AND THEY ARE DIFFERENT:
    pass        walked, and fine
    fail        walked, and not fine — the note prints, always
    not walked  NOT a pass, and named rather than silently omitted

LEGACY LOGS ARE UNTOUCHED. A document filed while this was a tick has
{key: True} and no result anywhere in it. It keeps printing exactly the plain
comma list it always did — an already-filed record does not change because the
app later learned to record more. That is asserted here byte-for-byte against
the old expression, not merely eyeballed.
"""

from __future__ import annotations

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

import server  # noqa: E402

R = server._display_inspections


def _old_expression(chk):
    """The exact line both renderers used before this change."""
    return ", ".join(k.replace("_", " ").title() for k, v in chk.items() if v)


class AFailedInspectionIsCalledFailed(unittest.TestCase):
    """THE test. This is what would have caught it."""

    def setUp(self):
        self.out = R({
            "street_frontage": {"result": "pass", "note": ""},
            "fall_protections": {"result": "fail", "note": "north edge open"},
        })

    def test_the_word_FAILED_appears(self):
        self.assertIn("FAILED", self.out)

    def test_the_failed_item_is_named(self):
        self.assertIn("Fall Protections", self.out)

    def test_and_what_failed_is_printed(self):
        self.assertIn("north edge open", self.out)

    def test_the_failure_is_NOT_in_the_passed_list(self):
        passed_line = [l for l in self.out.split("<br />") if l.startswith("Passed:")]
        self.assertEqual(len(passed_line), 1)
        self.assertNotIn("Fall Protections", passed_line[0],
                         "a failed inspection printed as a passed one")

    def test_the_old_expression_WOULD_have_got_this_wrong(self):
        """The control. Without it, the assertions above could pass against a
        renderer that never had the bug, and prove nothing."""
        wrong = _old_expression({
            "street_frontage": {"result": "pass", "note": ""},
            "fall_protections": {"result": "fail", "note": "north edge open"},
        })
        self.assertEqual(wrong, "Street Frontage, Fall Protections",
                         "the old line listed the failure as if it were fine")
        self.assertNotIn("north edge open", wrong, "and dropped the note")


class NotWalkedIsNotAPass(unittest.TestCase):
    def test_an_item_with_no_result_is_named_as_not_inspected(self):
        out = R({"permits": {"result": None, "note": ""}})
        self.assertIn("Not inspected: Permits", out)
        self.assertNotIn("Passed", out)

    def test_an_item_absent_from_the_dict_is_not_invented(self):
        out = R({"permits": {"result": "pass", "note": ""}})
        self.assertNotIn("Plans", out, "an item nobody recorded is not reported")

    def test_a_junk_result_is_not_coerced_into_a_pass(self):
        out = R({"plans": {"result": "probably fine", "note": ""}})
        self.assertIn("Not inspected: Plans", out)
        self.assertNotIn("Passed:", out)

    def test_a_fail_with_no_note_says_so_rather_than_printing_blank(self):
        out = R({"fire_safety": {"result": "fail", "note": "   "}})
        self.assertIn("FAILED", out)
        self.assertIn(server.NOT_RECORDED, out,
                      "a blank cell cannot be told from a question nobody asked")


class LegacyDocumentsDoNotChange(unittest.TestCase):
    """An already-filed record does not change because the app learned more."""

    LEGACY = {"street_frontage": True, "permits": True, "plans": False}

    def test_a_legacy_log_renders_exactly_as_it_did(self):
        self.assertEqual(R(self.LEGACY), _old_expression(self.LEGACY))

    def test_and_carries_none_of_the_new_vocabulary(self):
        out = R(self.LEGACY)
        for word in ("Passed", "FAILED", "Not inspected", "<span"):
            self.assertNotIn(word, out, f"legacy output gained {word!r}")

    def test_an_all_false_legacy_log_is_empty_as_before(self):
        chk = {"plans": False, "permits": False}
        self.assertEqual(R(chk), _old_expression(chk))
        self.assertEqual(R(chk), "")

    def test_empty_and_missing_render_empty_so_the_caller_prints_None(self):
        # Both call sites do `bold_para("Inspected", check_list or "None")`.
        for value in ({}, None, [], "nonsense"):
            self.assertEqual(R(value), "", repr(value))

    def test_a_stray_tick_inside_an_upgraded_log_is_not_a_pass(self):
        """Mixed shape — a log part-filled on each version. The tick says the
        CP looked and nothing about what he found."""
        out = R({"plans": True, "permits": {"result": "pass", "note": ""}})
        self.assertIn("Passed: Permits", out)
        self.assertIn("Not inspected: Plans", out)


class TheOrderIsTheOrderHeWalksThem(unittest.TestCase):
    def test_output_follows_INSPECTION_ORDER_not_dict_insertion(self):
        out = R({
            "permits": {"result": "pass", "note": ""},
            "street_frontage": {"result": "pass", "note": ""},
        })
        self.assertIn("Passed: Street Frontage, Permits", out,
                      "the PDF must not print them in whatever order a dict was built")

    def test_an_unknown_key_still_prints_rather_than_vanishing(self):
        out = R({"some_new_item": {"result": "fail", "note": "x"}})
        self.assertIn("Some New Item", out,
                      "an item added to the device before the server knows it")


class TheNoteIsEscaped(unittest.TestCase):
    def test_angle_brackets_in_a_note_cannot_close_the_span(self):
        out = R({"plans": {"result": "fail", "note": "<b>rail</b> gone"}})
        self.assertIn("&lt;b&gt;rail&lt;/b&gt;", out)
        self.assertNotIn("<b>rail</b>", out)


class BothRenderersUseTheOneHelper(unittest.TestCase):
    """The two call sites disagreed about weather once already, which is why
    _display_weather exists. The same discipline, asserted the same way."""

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_one_definition_and_two_call_sites(self):
        self.assertEqual(self.SRC.count("_display_inspections("), 3)

    def test_neither_renderer_kept_its_own_join(self):
        self.assertNotIn(
            'check_list = ", ".join(k.replace("_", " ").title()', self.SRC,
            "a renderer drifted back to the expression that printed a fail as a pass",
        )

    def test_equipment_KEPT_its_join_because_it_is_still_a_tick(self):
        """Equipment on site did not change shape, and must not be swept into
        this change: it is a presence tick, not an inspection result."""
        self.assertEqual(
            self.SRC.count('equip_list = ", ".join(k.replace("_", " ").title()'), 2,
            "equipment_on_site still renders as the plain list both PDFs expect",
        )


if __name__ == "__main__":
    unittest.main()
