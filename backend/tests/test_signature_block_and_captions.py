"""A SIGNATURE SPLIT ACROSS A PAGE, AND CAPTIONS NOBODY COULD READ.

B6 — "CP Signature (Michael Cespedes):" ended one page and his signature began
the next. `_wrap` builds a <table> whose label and image are separate <tr>s, and
the print CSS carries `tr { page-break-inside: avoid }` — which protects each
ROW and explicitly PERMITS a break between them. The `.doc-section` wrapper does
not help: a section holding a sixty-man roster is already taller than a page, so
the renderer drops its avoid request for the whole section.

The rule goes on the TABLE, which covers every one of `render_signature_html`'s
call sites at once, plus the two hand-rolled copies of the same table in
`generate_combined_report`.

B3 — AND THE REPORTED DIAGNOSIS WAS HALF WRONG, WHICH IS WORTH RECORDING.
The complaint was "too small and too low-contrast". Computed against white:

    #64748b  group caption, 12px   4.76:1   PASSES AA
    #b45309  "added after filing"   5.02:1   PASSES AA
    #94a3b8  attribution, 9px       2.56:1   FAILS AA *and* AA-large

So the 12px caption's problem is SIZE, not contrast — it passes, by 0.26. The
genuine accessibility failure is the 9px attribution line, and at 9px nothing
qualifies as WCAG "large text" (18pt / 14pt bold), so the 3:1 threshold never
applied to any of them: every one had to clear 4.5:1 and one did not.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

#: STRIPPED of comments and docstrings. Every assertion below is about what
#: the code EMITS, and this change explains itself in comments that name the
#: colours and sizes being removed — asserting over the raw file matched the
#: explanations. Three of these tests failed that way on the first run.
_SRC = code_of("server.py")
_PNG = "iVBORw0KGgoAAAANSUhEUg"


def _ratio(hex_colour: str, bg=(255, 255, 255)) -> float:
    """WCAG 2.x contrast ratio. Computed, not looked up."""
    def _lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def _lum(rgb):
        r, g, b = (_lin(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    fg = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    a, b = sorted((_lum(fg), _lum(bg)))
    return (b + 0.05) / (a + 0.05)


class TheSignatureBlockStaysTogether(unittest.TestCase):
    def test_the_wrapper_table_asks_not_to_be_split(self):
        html = server.render_signature_html({"data": _PNG, "signer_name": "m c"})
        self.assertIn("page-break-inside:avoid", html)
        self.assertIn("break-inside:avoid", html)

    def test_the_label_and_the_image_are_inside_the_same_table(self):
        """The property, not the spelling: whatever the markup, the label must
        not be able to leave the image behind."""
        html = server.render_signature_html({"data": _PNG, "signer_name": "m c"})
        table = html[html.index("<table"):html.index("</table>")]
        self.assertIn("Signature", table)
        self.assertIn("<img", table)

    def test_every_signature_state_carries_the_rule(self):
        """A signature with only a name renders a different branch."""
        for sig in ({"data": _PNG}, _PNG):
            self.assertIn("break-inside:avoid", server.render_signature_html(sig))

    def test_the_two_hand_rolled_copies_carry_it_too(self):
        """`generate_combined_report` spells this table twice by hand for the
        daily log's superintendent and competent-person signatures. Fixing only
        the shared renderer would leave those two splitting."""
        self.assertEqual(
            _SRC.count("style=\"margin-top:12px;page-break-inside:avoid;break-inside:avoid;\""),
            2)

    def test_no_signature_table_was_left_without_it(self):
        """The census: every signature-block table in the file, counted."""
        tables = re.findall(r'<table[^>]*margin-top:(?:8|12)px[^>]*>', _SRC)
        self.assertEqual(len(tables), 3)
        for t in tables:
            self.assertIn("break-inside:avoid", t)


class TheCaptionsAreLegible(unittest.TestCase):
    def test_the_attribution_colour_now_passes_AA(self):
        """The one that failed: 2.56:1, below AA and below AA-large."""
        self.assertLess(_ratio("#94a3b8"), 3.0)          # the control
        self.assertGreaterEqual(_ratio("#475569"), 4.5)

    def test_the_warning_colour_still_passes_and_improves(self):
        self.assertGreaterEqual(_ratio("#b45309"), 4.5)  # already passed
        self.assertGreater(_ratio("#92400e"), _ratio("#b45309"))

    def test_the_group_caption_colour_passed_before_and_still_does(self):
        """Recorded because the reported diagnosis said otherwise: the 12px
        caption was a SIZE problem, not a contrast one."""
        self.assertGreaterEqual(_ratio("#64748b"), 4.5)
        self.assertGreater(_ratio("#475569"), _ratio("#64748b"))

    def test_no_nine_pixel_text_survives(self):
        """Illegible in print whatever the contrast."""
        self.assertNotIn("font-size:9px", _SRC)

    def test_the_failing_colour_is_gone_from_the_captions(self):
        i = _SRC.index("def _photo_added_after_filing_caption")
        j = _SRC.index("\ndef ", i + 10)
        self.assertNotIn("#94a3b8", _SRC[i:j])

    def test_the_sub_captions_cannot_overflow_their_tile(self):
        """160px of text inside a 166px tile, and no word-break before this —
        one unbreakable token ran into the neighbouring tile."""
        i = _SRC.index("def _photo_added_after_filing_caption")
        j = _SRC.index("\ndef ", i + 10)
        self.assertEqual(_SRC[i:j].count("overflow-wrap:anywhere"), 2)

    def test_the_caption_is_still_emitted_at_all(self):
        """The absence rule: a legibility fix that removed the caption would
        satisfy every assertion above."""
        self.assertIn("_photo_added_after_filing_caption", _SRC)
        i = _SRC.index("_pg1_photos += (")
        self.assertIn("font-size:13px", _SRC[i:i + 200])
        self.assertIn("{_cap}", _SRC[i:i + 200])


if __name__ == "__main__":
    unittest.main(verbosity=2)
