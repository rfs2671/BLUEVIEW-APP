"""The PDF uses the whole page; the email keeps its 680px column.

ONE HTML SERVES TWO MEDIA. generate_combined_report builds a wrapper at
width="680" / max-width:680px, which is the right column for an email client.
get_combined_report_pdf hands that SAME string to WeasyPrint, where 680px sits
on a ~794px A4 page and leaves a dead strip down the right — the Activity
Details table stopping mid-page, reading on a phone as though the document had
been trimmed.

Email clients ignore @media print, so releasing the width there costs the email
nothing. Both halves are asserted, because fixing one by breaking the other is
the failure mode.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
# THE REPORT's shell specifically. server.py contains several <style> blocks
# (the kiosk page, other renderers), so this anchors on a string unique to
# this one rather than the first <style> in the file.
_A = SRC.index(":root {{ color-scheme: light only; }}")
_RAW = SRC[_A:SRC.index("</head>", _A)]
# CSS COMMENTS STRIPPED. The block DOCUMENTS the rule it adds — "Email clients
# ignore @media print" — and three mutations survived because the assertions
# were matching that prose instead of the rule. Comments describe; only the
# CSS behaves.
SHELL = re.sub(r"/\*.*?\*/", "", _RAW, flags=re.S)


class ThePrintedPageIsFullWidth(unittest.TestCase):
    def test_there_is_a_print_media_block(self):
        self.assertIn("@media print", SHELL)

    def test_it_releases_the_wrapper(self):
        block = SHELL[SHELL.index("@media print"):]
        self.assertIn("width: 100% !important", block)
        self.assertIn("max-width: 100% !important", block)

    def test_and_a_page_box_with_real_margins(self):
        self.assertIn("@page", SHELL)
        self.assertIn("margin: 12mm", SHELL)


class TheEmailKeepsItsColumn(unittest.TestCase):
    """The control. Releasing the width unconditionally would blow the email
    layout out to the full client width, which is why this is print-only."""

    def test_the_wrapper_is_still_680_for_email(self):
        """Scoped to THIS report's wrapper. `width="680"` also appears in the
        other PDF renderer, so a whole-file assertion passed on that copy while
        this one had been widened — the mutation survived until it was bounded."""
        i = SRC.index(":root {{ color-scheme: light only; }}")
        wrapper = SRC[i:SRC.index("<!-- HEADER -->", i)]
        self.assertIn('width="680" class="wrapper"', wrapper)
        self.assertIn("max-width:680px", wrapper)

    def test_the_release_is_INSIDE_the_print_block_only(self):
        before = SHELL[:SHELL.index("@media print")]
        self.assertNotIn("max-width: 100% !important", before,
                         "the wrapper is released for every medium, not just print")

    def test_the_dark_mode_rules_are_untouched(self):
        self.assertIn("prefers-color-scheme: dark", SHELL)
        self.assertIn("[data-ogsc] .wrapper", SHELL)


class ThePdfPathStillUsesThisHtml(unittest.TestCase):
    """If the PDF ever stops going through generate_combined_report, this fix
    is pointed at the wrong document and should fail loudly."""

    def test_the_pdf_renders_the_combined_report(self):
        fn = SRC[SRC.index("async def get_combined_report_pdf"):]
        fn = fn[:2000]
        self.assertIn("await generate_combined_report(project_id, date)", fn)
        self.assertIn("HTML(string=html).write_pdf()", fn)


if __name__ == "__main__":
    unittest.main()
