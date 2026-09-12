"""THE REPORT IS A PRINT DOCUMENT. THERE IS NO EMAIL COLUMN LEFT TO PROTECT.

WHAT THIS FILE USED TO ASSERT, and why it does not any more.

One HTML served two media. `generate_combined_report` built a wrapper at
`width="680"` because that is the right column for an email client, and
`@media print` released the width so the same string would not leave a dead
strip down the right of an A4 page. Both halves were asserted, because fixing
one by breaking the other was the failure mode.

The premise is gone. The report is now `@page { size: Letter portrait }` with
no wrapper at all, and nothing renders it but WeasyPrint and a browser.

AND THE OTHER HALF OF THE PREMISE WAS ALREADY GONE, WHICH IS WORTH CHECKING
RATHER THAN BELIEVING. The scheduled send does not use this HTML as a message
body: it renders a PDF, attaches it, and builds the body from
`render_for_trigger("project_daily_report", ...)`. That is asserted below, and
it is the load-bearing claim -- if somebody ever sends this string to an inbox
again, an email column becomes necessary again, and the test that says so
should fail first.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _function(name: str) -> str:
    for node in ast.walk(_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(_SRC, node) or ""
    raise AssertionError(f"{name} is gone")


class TheReportIsSetForPaper(unittest.TestCase):

    def setUp(self):
        from lib.report import renderer
        self.css = renderer.stylesheet()

    def test_it_declares_a_page_size(self):
        self.assertIn("@page", self.css)
        self.assertIn("size: Letter portrait", self.css)

    def test_there_is_no_email_column(self):
        """680px on a Letter page is a dead strip down the right, and it is
        the reason this file existed."""
        self.assertNotIn("680", self.css)
        self.assertNotIn("max-width: 680px", self.css)

    def test_no_media_print_release_is_needed_because_nothing_constrains_it(self):
        self.assertNotIn("@media print", self.css)

    def test_the_renderer_emits_no_bgcolor_or_table_shell(self):
        """`bgcolor` and a nested table shell were email-client compromises.
        They are answers to a question nobody is asking any more."""
        from lib.report import renderer
        self.assertNotIn("bgcolor", renderer.stylesheet())


class NothingSendsThisHtmlToAnInbox(unittest.TestCase):
    """THE LOAD-BEARING HALF. Dropping the email column is only safe while no
    inbox receives this string."""

    def test_the_scheduled_send_attaches_a_pdf_and_templates_the_body(self):
        body = _function("check_and_send_reports")
        self.assertIn("generate_combined_report", body)
        self.assertIn("write_pdf", body)
        self.assertIn('render_for_trigger("project_daily_report"', body)

    def test_the_report_html_is_not_passed_as_a_message_body(self):
        """The variable holding this HTML must reach a PDF renderer and an
        attachment, and nothing else."""
        body = _function("check_and_send_reports")
        for line in body.splitlines():
            if re.search(r"\bhtml\s*=\s*report_html\b", line):
                self.fail(f"the report HTML became a message body: {line.strip()}")

    def test_every_caller_either_renders_a_pdf_or_serves_it_to_a_browser(self):
        """FOUR CALL SITES, and a fifth that emailed it would be caught here.

        Two routes serve it to a browser or to WeasyPrint, one public grant
        does both, and the scheduler attaches a PDF. A new caller has to be
        added to this list deliberately.
        """
        callers = set()
        for node in ast.walk(_TREE):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) \
                    or getattr(node.func, "attr", None)
                if name != "generate_combined_report":
                    continue
                for fn in ast.walk(_TREE):
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and fn.lineno <= node.lineno <= (fn.end_lineno or 0):
                        callers.add(fn.name)
        self.assertEqual(
            callers,
            {"get_combined_report", "get_combined_report_pdf",
             "public_view_grant", "check_and_send_reports"},
            "a caller of generate_combined_report appeared or disappeared; if "
            "it emails the HTML, the email column has to come back")


if __name__ == "__main__":
    unittest.main(verbosity=2)
