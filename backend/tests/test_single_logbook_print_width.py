"""THE FIX WAS MADE ON ONE OF TWO RENDERERS AND STOPPED THERE.

`generate_combined_report` and `generate_single_logbook_html` print the same
stored records into two different documents. The combined report's 680px
wrapper on a ~794px A4 page left a dead strip down the right; that was
diagnosed and fixed with an `@page` box and a `@media print` width release
(tests/test_report_print_width.py). The OTHER renderer — the per-logbook PDF an
inspector downloads from `/api/reports/logbook/{id}/pdf` — carried the same
defect at 700px and nobody looked at it. That is the finding this file records:
a correction to one renderer of a shared record is not a correction to the
record, and there is no mechanism in this repo that would have said so.

AND THE COMMENT WAS WORSE THAN THE CSS. `generate_single_logbook_html`'s
docstring claimed it "reuses the same styling as the combined report", which is
what made the omission invisible on a read. It never reused the print block.
Worse, the 700px column was borrowed from a medium this document does not have:
this renderer has exactly ONE caller, `get_single_logbook_pdf`, which hands the
string to WeasyPrint and returns application/pdf. Nothing emails it.

THE WIDTH RELEASE IS STILL SCOPED TO PRINT ANYWAY. Deleting the 700px outright
would render identically today and hand a full-bleed table to any future email
consumer. `@media print` costs nothing on the only path that exists.

NOT ASSERTED HERE: the resulting page geometry. WeasyPrint cannot be imported
on the machine this was written on (its GTK/pango libraries are absent on
Windows), so no page-box width in this file is measured — every assertion below
is about the CSS the renderer emits, which is a weaker claim. Stated rather
than glossed.
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


class _ProjectsColl:
    async def find_one(self, *a, **k):
        return {"name": "Test Tower", "address": "1 Test St"}


class _RenderDb:
    projects = _ProjectsColl()


def render(logbook: dict) -> str:
    with patch.object(server, "db", _RenderDb()):
        return asyncio.run(server.generate_single_logbook_html(logbook))


def _doc(log_type: str, data: dict) -> dict:
    return {"_id": "lb1", "project_id": "proj1", "log_type": log_type,
            "date": "2026-09-05", "status": "submitted", "data": data}


#: A real render, not the source text. What the inspector's PDF is built from.
HTML = render(_doc("daily_jobsite", {"weather": "Clear", "notes": "n"}))

#: A SECOND SPECIMEN, BECAUSE THE FIRST NEVER REACHED THE CODE UNDER TEST.
#: `sub_title` is the only source of <h3> in this renderer and it is called from
#: nine branches — none of them `daily_jobsite`. The heading assertion below
#: failed on the fixture above while the rule it was checking was correct: a
#: specimen that does not exercise the subject reports on nothing. Written down
#: rather than quietly repaired, because it is the third time this shape has
#: produced a misleading run in this repo.
HTML_H3 = render(_doc("crane_operations",
                      {"load_entries": [{"time": "07:30", "description": "steel"}]}))

def _decommented(html: str) -> str:
    """CSS COMMENTS STRIPPED.

    The print block documents the rules it adds, naming the very selectors it
    installs — including the two it deliberately omits. The census below
    matched `.doc-section` inside that comment on its first run, passing
    judgment on the prose rather than on the stylesheet. The sibling file
    records three instances of the same defect. Comments describe; only the
    CSS behaves.
    """
    return re.sub(r"/\*.*?\*/", "", html, flags=re.S)


_STYLE = HTML[HTML.index("<style>"):HTML.index("</style>")]
STYLE = _decommented(_STYLE)
MARKUP = _decommented(HTML)


class ThePrintedPageIsFullWidth(unittest.TestCase):
    def test_there_is_a_page_box_with_real_margins(self):
        self.assertIn("@page", STYLE)
        self.assertIn("size: A4", STYLE)
        self.assertIn("margin: 12mm", STYLE)

    def test_there_is_a_print_media_block(self):
        self.assertIn("@media print", STYLE)

    def test_it_releases_the_wrapper(self):
        block = STYLE[STYLE.index("@media print"):]
        self.assertIn("width: 100% !important", block)
        self.assertIn("max-width: 100% !important", block)

    def test_the_release_has_something_to_release(self):
        """A rule on `.wrapper` is inert unless the wrapper carries the class.
        This is the half a copied stylesheet loses."""
        self.assertIn('class="wrapper"', HTML)
        table = HTML[HTML.index('class="wrapper"') - 120:]
        self.assertIn("max-width:700px", table[:200])


class TheColumnSurvivesForAnyOtherMedium(unittest.TestCase):
    """The control. Releasing the width unconditionally is the other way to
    make every assertion above pass."""

    def test_the_wrapper_is_still_700_outside_print(self):
        self.assertIn("max-width:700px", HTML)

    def test_the_release_is_INSIDE_the_print_block_only(self):
        before = STYLE[:STYLE.index("@media print")]
        self.assertNotIn("max-width: 100% !important", before)


class TheRulesMatchWhatThisRendererEmits(unittest.TestCase):
    """A stylesheet ported wholesale is dead CSS plus a false impression of
    coverage. The combined report's block styles `h2` and `.doc-section`;
    neither exists in this document, and a rule for a selector that never
    appears reads on the next audit as a protection that is in place."""

    def test_the_heading_rule_has_a_heading(self):
        self.assertIn("h3 {", STYLE.replace("h3{", "h3 {"))
        self.assertIn("<h3", HTML_H3, "the specimen does not reach sub_title")

    def test_no_rule_was_copied_for_a_selector_this_document_lacks(self):
        for markup in (MARKUP, HTML_H3):
            self.assertNotIn("doc-section", _decommented(markup))
            self.assertNotIn("<h2", _decommented(markup))
        self.assertNotIn("doc-section", STYLE)
        self.assertNotIn("h2", STYLE)

    def test_the_row_rule_is_present_and_has_rows(self):
        self.assertIn("page-break-inside: avoid", STYLE)
        self.assertIn("<tr>", HTML)


class TheRowRuleDoesNotSwallowTheShell(unittest.TestCase):
    """THE DEFECT THIS PORT WOULD OTHERWISE HAVE CARRIED ACROSS.

    An unqualified `tr { break-inside: avoid }` matches the outer layout
    table's single CONTENT row, which holds the entire document body. Rather
    than split it, WeasyPrint relocates it to a fresh sheet and page 1 is left
    holding only the header. That is measured on the combined report, whose
    shell is the same three-row shape: with the rule removed, a 461px section
    moved from page 2 back onto page 1 (page-1 content bottom 265px -> 794px,
    7 pages -> 6). The rule is wanted for the roster tables nested inside the
    content cell; the shell rows opt out.
    """

    def test_all_three_shell_rows_opt_out(self):
        for markup in (MARKUP, HTML_H3):
            self.assertEqual(_decommented(markup).count('<tr class="shell">'), 3)

    def test_the_exemption_exists_and_is_inside_the_print_block(self):
        block = STYLE[STYLE.index("@media print"):]
        self.assertIn("tr.shell", block)
        self.assertIn("break-inside: auto", block)

    def test_the_exemption_comes_AFTER_the_rule_it_overrides(self):
        """Same specificity would win on order alone; `tr.shell` is higher, so
        this is belt and braces — but a rule listed first reads to the next
        person as though order were doing the work."""
        block = STYLE[STYLE.index("@media print"):]
        self.assertLess(block.index("  tr {"), block.index("tr.shell"))

    def test_the_nested_tables_are_NOT_exempt(self):
        """The point of the rule. The roster and checklist tables inside the
        content cell must still refuse to split."""
        body = _decommented(HTML_H3)
        body = body[body.index('<tr class="shell"><td style="padding:24px 40px'):]
        self.assertIn("<tr>", body, "no unexempted row is left for the rule")


class ThisIsTheDocumentThatGetsPrinted(unittest.TestCase):
    """If the per-logbook PDF ever stops rendering this html, the fix is
    pointed at a document nobody prints and should fail loudly. Asserted on
    the dataflow rather than on a source line, so that moving the render off
    the event loop — which broke the sibling test once already — does not
    fail a correct change."""

    def test_the_pdf_endpoint_renders_THIS_renderers_output(self):
        tree = ast.parse(SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "get_single_logbook_pdf")

        assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "html"
                           for t in n.targets)]
        self.assertEqual(len(assigns), 1, "html is assigned more than once")
        self.assertIn("generate_single_logbook_html", ast.unparse(assigns[0].value))

        rendered = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Await)]
        self.assertTrue(
            any("to_thread" in r and "html" in r for r in rendered),
            f"the html is not what gets rendered: {rendered}")

    def test_it_returns_a_pdf_and_not_an_email(self):
        """The premise of the whole change: one medium, paper."""
        i = SRC.index("async def get_single_logbook_pdf")
        j = SRC.index("\nasync def ", i + 10)
        body = SRC[i:j]
        self.assertIn('media_type="application/pdf"', body)
        self.assertNotIn("send_email", body)


class TheStaleClaimIsGone(unittest.TestCase):
    """The docstring is why this went unread for as long as it did."""

    def test_it_no_longer_says_it_reuses_the_combined_reports_styling(self):
        doc = server.generate_single_logbook_html.__doc__ or ""
        self.assertNotIn("Reuses the same styling as the combined report", doc)

    def test_and_it_names_the_single_caller_and_the_medium(self):
        doc = server.generate_single_logbook_html.__doc__ or ""
        self.assertIn("get_single_logbook_pdf", doc)
        self.assertIn("WeasyPrint", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
