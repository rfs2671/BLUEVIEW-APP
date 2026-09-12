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
_REPORT_PKG = Path(server.__file__).parent / "lib" / "report"
_RENDERER = (_REPORT_PKG / "renderer.py").read_text(encoding="utf-8")
_VIEW = (_REPORT_PKG / "view.py").read_text(encoding="utf-8")
_MODEL = (_REPORT_PKG / "model.py").read_text(encoding="utf-8")

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

    def test_there_is_nothing_left_to_normalise_BY_HAND(self):
        """Both hand-rolled blocks lived in the "Site Superintendent Log"
        section, which rendered from db.daily_logs -- last row 16 April 2026 --
        and so had not appeared on a report in five months. The section is
        gone and they went with it.

        assertTrue, NOT assertIn: `_SRC` is 2.3MB and assertIn PRINTS ITS
        CONTAINER. Running this file after the removal cost exactly that.
        docs/audits/check-harness.md section 12."""
        for marker in ('sup_sig_raw.get("signer_name")',
                       'cp_sig_raw.get("signer_name")'):
            self.assertTrue(
                marker not in _SRC,
                f"a hand-rolled signer-name read is back: {marker}. The shared "
                "renderer normalises the name; a second spelling is how the "
                "two drifted the first time.")

    def test_the_fallback_LIVES_IN_THE_SHARED_RENDERER_NOW(self):
        """These two hand-rolled blocks held the `or default` fallback that a
        stored null needs -- `.get(k, default)` returns None for one. Both were
        inside the retired "Site Superintendent Log" section, so the assertion
        moves to the renderer that is left rather than being deleted: the rule
        is about what a document PRINTS for a nameless signature, and that
        document still prints one.

        EXECUTED, not read. The old pair scanned source text; this renders."""
        html = server.render_signature_html({"paths": [[{"x": 1, "y": 2},
                                                        {"x": 3, "y": 4}]],
                                             "signerName": ""},
                                            "CP Signature")
        self.assertTrue(html, "a signature with no name rendered nothing at all")
        # ANCHORED ON THE CONSTRUCT. A bare ban on "None" is four characters:
        # "None recorded" and "Nonentity" both satisfy it, and the bare-literal
        # gate refuses it for exactly that. What must not appear is the NAME
        # SLOT holding a null, which is parenthesised.
        self.assertNotIn("(None)", html,
                         "a stored null reached the page in the name slot")
        self.assertNotIn(": None", html,
                         "a stored null reached the page as the signer")


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

    def test_the_date_and_the_address_are_still_on_the_page(self):
        """The two cells that stayed. They are a stacked HERO rather than a
        table row now -- the banner they used to sit in was replaced by a
        white masthead over it -- so they are read off the renderer that draws
        them."""
        self.assertIn('<div class="haddr">{esc(banner.address.upper())}</div>',
                      _RENDERER)
        self.assertIn('<div class="hwhen">{esc(banner.dateline)}</div>',
                      _RENDERER)

    def test_the_banner_cannot_leave_a_hole_where_the_cell_was(self):
        """WHY THE LAYOUT HALF OF THE OLD TEST IS GONE RATHER THAN MOVED.

        It asserted the survivors were widened to 50% each, because a removed
        cell that leaves 33/34 behind prints two columns crammed against the
        left with a third of the page blank. The banner is a STACKED BLOCK: it
        has no column widths at all, so there is no proportion to get wrong
        and no third column to remove. That is asserted rather than assumed --
        a future banner rebuilt as a table would want the old test back.
        """
        block = _RENDERER[_RENDERER.index("def render_hero("):]
        block = block[:block.index("\ndef ")]
        self.assertNotIn("width=", block)
        self.assertNotIn("<td", block)

    def test_the_gate_figure_is_still_printed_and_now_carries_its_qualifier(self):
        """THE RULE, STRENGTHENED. The cell was removed because a bare gate
        count explains nothing. The figure is back, on the rail, beside the
        reconciliation between the gate and the log -- so it is not the number
        that was banned, it is the number the ban was asking for."""
        self.assertIn('RailCell(str(model.gate.check_ins), "Gate check-ins"',
                      _VIEW)
        self.assertIn("on daily log", _MODEL)
        self.assertIn("gate check-ins", _MODEL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
