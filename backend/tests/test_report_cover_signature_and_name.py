"""THREE THINGS AN OPERATOR READ OFF A FILED REPORT ON A LAPTOP.

B5  The signature had a BORDER BOX around it — ink on a filed document framed
    like a form field.
B7  The same man was "michael Cespedes" beside the signature and "Michael
    Cespedes" everywhere else. TWO SOURCES for one name: every other rendering
    goes through `_capitalize_first(logbook["cp_name"])`, while the signature
    label reads `signer_name` straight off the signature object, stamped at
    signing time from whatever was typed.
B2  "WORKERS AT THE GATE" sat on the cover AND again on page 2, where the roster
    it counts actually appears. On the cover it was a number with nothing under
    it.

RENDERED, NOT GREPPED, wherever the function can be called. `render_signature_html`
is pure, so B5 and B7 are asserted against its actual output — a source check
would pass on a border defined in a second place and on a name normalised in a
comment. This file was written the week a suite of source-text assertions passed
against an R2 sweep that deleted nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")

# A one-pixel PNG is enough: these assertions are about the wrapper, not the ink.
_PNG = "iVBORw0KGgoAAAANSUhEUg"


class TheSignatureIsNotInABox(unittest.TestCase):
    def test_a_raster_signature_renders_with_no_border(self):
        html = server.render_signature_html({"data": _PNG, "signer_name": "x"})
        self.assertIn("<img", html)
        self.assertNotIn("border:1px solid", html)
        self.assertNotIn("border-radius", html)

    def test_a_bare_base64_signature_too(self):
        """The `isinstance(sig, str)` path is a second entry into the same
        renderer and would keep the box if only the dict path were changed."""
        html = server.render_signature_html(_PNG)
        self.assertIn("<img", html)
        self.assertNotIn("border:1px solid", html)

    def test_the_image_is_still_size_constrained(self):
        """Removing the frame must not remove the width cap — a full-bleed
        signature would push the page."""
        html = server.render_signature_html({"data": _PNG})
        self.assertIn("max-width:280px", html)


class TheTwO_HAND_ROLLED_COPIES_TOO(unittest.TestCase):
    """FOUND BY AN OVER-BROAD GREP DURING A REBASE RE-READ, WHICH IS THE POINT
    OF DOING ONE.

    `generate_combined_report` spells the signature block twice by hand for the
    daily log's superintendent and competent-person signatures, instead of
    calling `render_signature_html`. Both copies carried the border this change
    removed from the shared renderer, and both read `signer_name` RAW — so
    fixing the shared renderer alone would have left the same box and the same
    two spellings on the daily-log section, one screen further down the same
    document the operator was reading."""

    def _block(self, marker):
        i = _SRC.index(marker)
        return _SRC[i:i + 1400]

    def test_neither_hand_rolled_signature_has_a_border(self):
        self.assertEqual(
            _SRC.count("height:auto;border:1px solid #e2e8f0;border-radius:4px"), 0)

    def test_both_normalise_the_signer_name(self):
        for marker in ('sup_sig_raw.get("signer_name")',
                       'cp_sig_raw.get("signer_name")'):
            i = _SRC.index(marker)
            self.assertIn("_capitalize_first", _SRC[max(0, i - 200):i + 60])

    def test_the_defaults_survive_an_empty_name(self):
        """`.get(k, default)` returns None for a stored null; `or default` is
        what actually holds the fallback."""
        for marker in ('sup_sig_raw.get("signer_name") or "Superintendent"',
                       'cp_sig_raw.get("signer_name") or "Competent Person"'):
            self.assertIn(marker, _SRC)


class OneManHasOneSpelling(unittest.TestCase):
    def test_the_signer_name_is_capitalised_in_the_label(self):
        html = server.render_signature_html(
            {"data": _PNG, "signer_name": "michael Cespedes"}, "CP Signature")
        self.assertIn("Michael Cespedes", html)
        self.assertNotIn("michael Cespedes", html)

    def test_it_matches_what_every_other_rendering_does(self):
        """The two must agree by CONSTRUCTION, not by coincidence: both sides
        run the same normaliser over the same input."""
        raw = "michael Cespedes"
        html = server.render_signature_html({"data": _PNG, "signer_name": raw})
        self.assertIn(server._capitalize_first(raw), html)

    def test_the_signer_only_path_is_normalised_too(self):
        """A signature object with a name but no drawable image renders the
        name in prose. Same name, same rule."""
        html = server.render_signature_html({"signer_name": "jose castaneda"})
        self.assertIn("Jose", html)
        self.assertNotIn("jose castaneda", html)

    def test_a_missing_signer_still_renders(self):
        """_capitalize_first("") must not become the string "None" or raise.

        ANCHORED as `(None)`, not the bare word: a signature with no signer
        renders `label` alone, and the failure this guards is the empty name
        arriving inside the parenthesised label. A bare "None" would also match
        any explanatory prose that happened to contain it."""
        html = server.render_signature_html({"data": _PNG})
        self.assertIn("<img", html)
        self.assertNotIn("(None)", html)
        self.assertNotIn("()", html)


class TheCoverDoesNotCountWhatItDoesNotShow(unittest.TestCase):
    def test_workers_at_the_gate_is_gone_from_the_cover_summary(self):
        self.assertNotIn('font-weight:600;">WORKERS AT THE GATE</span>', _SRC)

    def test_the_summary_row_still_has_its_other_two_cells(self):
        self.assertIn('font-weight:600;">DATE</span>', _SRC)
        self.assertIn('font-weight:600;">ADDRESS</span>', _SRC)

    def test_the_two_remaining_cells_fill_the_row(self):
        """A removed cell that leaves 33/34 behind prints two columns crammed
        against the left with a third of the page blank — the cover is already
        the item being complained about for emptiness."""
        i = _SRC.index('font-weight:600;">DATE</span>')
        j = _SRC.index('font-weight:600;">ADDRESS</span>')
        row = _SRC[max(0, i - 400):j + 200]
        self.assertEqual(row.count('width="50%"'), 2)
        self.assertNotIn('width="33%"', row)
        self.assertNotIn('width="34%"', row)

    def test_the_count_itself_is_still_computed_and_used(self):
        """Only the cover CELL goes. `checkin_count` still feeds page 2, and a
        removal that orphaned it would be a different change."""
        self.assertGreater(_SRC.count("checkin_count"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
