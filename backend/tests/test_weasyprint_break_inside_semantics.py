"""WHAT `break-inside: avoid` ACTUALLY DOES WHEN THE BLOCK IS TOO TALL.

This file exists because a comment in `generate_combined_report` said the
opposite, and no check in this repository could contradict it:

    "A section taller than a page cannot honour it, and WeasyPrint drops the
    request rather than leaving the sheet blank -- which is what makes this
    safe on a sixty-man pre-shift sheet."

WeasyPrint does not drop it. It moves the block to a fresh sheet first, and
splits it there only because it has run out of anywhere else to put it. The
blank sheet is exactly what you get, and it is worst on precisely the case the
comment called safe.

Measured on production data before this file was written (2026-09-05): the
2026-08-31 report's first section is ~1715px, far taller than a whole A4 page,
and it still began on page 2. Page 1 carried the header and the summary row and
nothing else. That is what makes the old claim never-true rather than drifted.

WHY IT SURVIVED SO LONG. Every page-geometry test in this repo asserts the CSS
a renderer EMITS. None renders a page. A false claim about what the renderer
does with that CSS therefore sat beside a suite structurally incapable of
disagreeing with it. See docs/audits/check-harness.md section 8.

═══════════════════════════════════════════════════════════════════════════
THE TWO CONSTRAINTS ON EVERY ASSERTION IN THIS FILE
═══════════════════════════════════════════════════════════════════════════

1. ASSERT WHICH PAGE SOMETHING LANDS ON. NEVER A PIXEL COUNT.

   CI renders against Ubuntu 24.04's pango; production is `python:3.12-slim`,
   which is Debian. Same WeasyPrint, same major pango, different builds and
   different fonts. Text metrics will differ. "Page 2, not page 1" survives
   that; "779.0px" does not, and the next person to add a case here will want
   to pin a number. Do not.

2. THE SKIP IS GUARDED. WeasyPrint's native libraries are absent on at least
   one authoring machine (Windows), so this file skips there rather than
   failing the local suite. A skip that also fires in CI would make this file
   green for the whole reason it exists, so `CI` turns the skip into a failure.

   The libraries need no install step: ubuntu-latest (image ubuntu24
   20260831.293.1) renders WeasyPrint 69.0 unaided, measured. One footnote for
   whoever probes this again -- `dpkg -s libglib2.0-0` reports ABSENT on that
   image even though the library is there, because 24.04 renamed the package
   `libglib2.0-0t64` in the time_t transition and it merely PROVIDES the old
   name. A census by production's package names reports a false negative.
"""

from __future__ import annotations

import os
import unittest

try:
    from weasyprint import HTML
except Exception as exc:  # pragma: no cover - depends on native libraries
    HTML = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _page_text(page) -> str:
    """Every string laid out on one page, in order."""
    out = []

    def walk(box):
        text = getattr(box, "text", None)
        if text:
            out.append(text)
        for child in getattr(box, "children", ()) or ():
            walk(child)

    walk(page._page_box)
    return " ".join(out)


def _pages(html: str):
    return HTML(string=html).render().pages


#: A4 at 12mm margins, the report's own page box. Filler eats most of page one
#: so that the subject lands on the fold; SUBJECT_MARK is unique per case so an
#: assertion cannot be satisfied by the filler.
_SHELL = """
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ font-family: sans-serif; font-size: 14px; margin: 0; }}
  .filler {{ height: {filler}px; background: #eee; }}
  tr.subject {{ break-inside: {rule}; page-break-inside: {rule}; }}
  td {{ padding: 0; }}
</style>
<div class="filler">FILLER</div>
<table><tr class="subject"><td>
  <div>SUBJECT-START</div>
  <div style="height:{body}px">BODY</div>
  <div>SUBJECT-END</div>
</td></tr></table>
"""


def _doc(*, filler: int, body: int, rule: str) -> str:
    return _SHELL.format(filler=filler, body=body, rule=rule)


@unittest.skipIf(HTML is None and not os.environ.get("CI"),
                 f"weasyprint native libraries unavailable: {_IMPORT_ERROR}")
class BreakInsideAvoidRelocatesRatherThanDropping(unittest.TestCase):

    def setUp(self):
        if HTML is None:
            self.fail(
                "weasyprint did not import in CI, so this file would have "
                f"skipped the whole reason it exists: {_IMPORT_ERROR}")

    # ── The control comes first, because every assertion below is worthless
    #    if the subject was never straddling the fold in the first place. ──

    def test_CONTROL_without_the_rule_the_block_splits_across_the_fold(self):
        """`break-inside: auto` — the subject starts on page 1 and continues
        onto page 2. This proves the fixture straddles; a fixture that fitted
        entirely on page 2 would satisfy every assertion below while measuring
        nothing."""
        pages = _pages(_doc(filler=700, body=500, rule="auto"))
        self.assertGreaterEqual(len(pages), 2)
        self.assertIn("SUBJECT-START", _page_text(pages[0]))
        self.assertIn("SUBJECT-END", _page_text(pages[1]))

    def test_the_rule_moves_the_whole_block_to_page_two(self):
        """The same fixture, `avoid`. Page 1 keeps only the filler."""
        pages = _pages(_doc(filler=700, body=500, rule="avoid"))
        self.assertGreaterEqual(len(pages), 2)
        first = _page_text(pages[0])
        self.assertIn("FILLER", first)
        self.assertNotIn("SUBJECT-START", first)
        self.assertIn("SUBJECT-START", _page_text(pages[1]))

    def test_A_BLOCK_TALLER_THAN_A_PAGE_IS_ALSO_MOVED_FIRST(self):
        """THE CLAIM THE OLD COMMENT MADE, AND THE CASE IT CALLED SAFE.

        The block cannot fit on any page, so the request is unsatisfiable. The
        comment asserted WeasyPrint would therefore drop it and start on page 1.
        It does not: the block is relocated to a fresh sheet and split there,
        and page 1 is left holding the filler alone.

        This is the sixty-man pre-shift sheet, and it is the shape measured on
        the 2026-08-31 production report — ~1715px of section, still beginning
        on page 2."""
        pages = _pages(_doc(filler=700, body=2400, rule="avoid"))
        self.assertGreaterEqual(len(pages), 3)
        first = _page_text(pages[0])
        self.assertIn("FILLER", first)
        self.assertNotIn("SUBJECT-START", first,
                         "the request was dropped — the old comment was right "
                         "and this file should be deleted")
        self.assertIn("SUBJECT-START", _page_text(pages[1]))

    def test_and_it_does_split_once_it_is_there(self):
        """The other half of the behaviour: relocation is not refusal. The
        over-tall block still splits, just one sheet later than the comment
        said and with a sheet wasted."""
        pages = _pages(_doc(filler=700, body=2400, rule="avoid"))
        starts = [i for i, p in enumerate(pages) if "SUBJECT-START" in _page_text(p)]
        ends = [i for i, p in enumerate(pages) if "SUBJECT-END" in _page_text(p)]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 1)
        self.assertGreater(ends[0], starts[0], "it did not split at all")

    def test_a_block_that_FITS_is_not_moved(self):
        """The boundary. Nothing here should discourage the rule's real use —
        when the block fits in the space left, it stays where it is."""
        pages = _pages(_doc(filler=100, body=200, rule="avoid"))
        self.assertIn("SUBJECT-START", _page_text(pages[0]))
        self.assertIn("SUBJECT-END", _page_text(pages[0]))


@unittest.skipIf(HTML is None and not os.environ.get("CI"), "see above")
class ThePageBoxIsTheOneTheReportAsksFor(unittest.TestCase):
    """A4 at 12mm, asserted once so that a wrong @page cannot quietly explain
    a wrong result above. Rounded to the nearest pixel — this is the page BOX,
    fixed by the CSS, not a text metric, so it is stable across builds."""

    def setUp(self):
        if HTML is None:
            self.fail(f"weasyprint did not import in CI: {_IMPORT_ERROR}")

    def test_a4_at_twelve_millimetre_margins(self):
        page = _pages(_doc(filler=10, body=10, rule="avoid"))[0]
        self.assertEqual(round(page.width), 794)
        self.assertEqual(round(page.height), 1123)


if __name__ == "__main__":
    unittest.main(verbosity=2)
