"""A SECTION THAT COULD NOT RENDER, AND THE READ THAT FED IT.

About 110 lines of `generate_combined_report` rendered a "Site Superintendent
Log" section -- weather, worker count, notes, work performed, subcontractor
cards, a safety checklist, corrective actions, an incident log and two
signatures -- all from `db.daily_logs`, behind one `if daily_log:`.

That collection's last row is dated 16 April 2026. The daily record moved to
the logbook system that month, so the lookup returned None on every report
since and the section did not appear.

NOBODY WAS READING A BLANK BOX, and that was established by RENDERING a real
report from production rather than reading the branch: the section title is
absent from the output while "Construction Superintendent Log" and "Daily
Jobsite Log" are both present. So this removes a comprehension cost, not a
correctness one, and the distinction is the reason it is safe.

── IT IS DELETED RATHER THAN RE-POINTED ──────────────────────────────────────

`as_daily_log_row` exists and `get_report_preview` already uses it to read the
filed daily_jobsite logbook in the legacy row's shape, so this section COULD
have been fed from the logbook. It must not be. The same document already
renders `jobsite_html` and `cs_html` from the logbooks; feeding this one too
would print one record three times under three headings.

THE COLLECTION STAYS. Ninety-two records from April, with their read routes and
their PDF route. Retiring a renderer is not dropping data, and that is asserted
here so a later reader does not finish the job.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
#: Comments STRIPPED. The removal's own note names the collection and the
#: section in order to explain them, and counting that prose as a use is the
#: mistake this repository has made before.
_CODE = code_of("server.py")


def _fn(name):
    for n in ast.walk(_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} is not defined in server.py")


def _reads_daily_logs(fn) -> bool:
    """True if this function performs a query against db.daily_logs."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not isinstance(f, ast.Attribute):
            continue
        if f.attr not in ("find_one", "find", "count_documents", "aggregate"):
            continue
        if isinstance(f.value, ast.Attribute) and f.value.attr == "daily_logs":
            return True
    return False


class TheDeadSectionIsGone(unittest.TestCase):

    def test_the_report_no_longer_queries_the_legacy_collection(self):
        self.assertFalse(
            _reads_daily_logs(_fn("generate_combined_report")),
            "generate_combined_report still reads db.daily_logs, whose last "
            "row is dated April")

    def test_and_neither_does_the_scheduled_send(self):
        """`has_daily_log` was a dead read on the path every scheduled send
        takes: always None, and the filed daily record is already counted by
        `logbook_count`."""
        self.assertFalse(_reads_daily_logs(_fn("check_and_send_reports")))

    def test_the_section_title_is_not_emitted_anywhere(self):
        """Counted on STRIPPED code so the note explaining the removal does not
        read as the thing removed."""
        self.assertEqual(_CODE.count('"Site Superintendent Log"'), 0)

    def test_the_note_still_QUOTES_what_it_removed(self):
        """An erased claim leaves the next grep empty, and empty reads as 'no
        such problem'. The comment must keep the words."""
        # assertTrue, NOT assertIn: `_SRC` is 2.3MB of server.py and assertIn
        # PRINTS ITS CONTAINER. docs/audits/check-harness.md section 12 -- and
        # this is the third time in one day it has had to be said, which is the
        # outrun pattern the preamble describes rather than a lapse.
        self.assertTrue("Site Superintendent Log" in _SRC,
                        "the note no longer names the section it removed, so a "
                        "grep for it finds nothing")
        self.assertTrue("db.daily_logs" in _SRC,
                        "the note no longer names the collection it stopped "
                        "reading")


class TheSUCCESSORSStillRender(unittest.TestCase):
    """The vacuity guard, and the whole reason deleting was safe. If these
    stopped rendering too, the document would have lost the record rather than
    lost a duplicate of it."""

    def test_both_successor_sections_are_still_composed(self):
        src = ast.unparse(_fn("generate_combined_report"))
        for name in ("jobsite_html", "cs_html"):
            self.assertTrue(name in src, f"{name} is no longer composed")

    def test_their_titles_are_still_emitted(self):
        self.assertGreater(_CODE.count('"Daily Jobsite Log'), 0)
        self.assertGreater(_CODE.count('"Construction Superintendent Log'), 0)

    def test_the_dead_section_is_not_re_pointed_at_the_logbook(self):
        """`as_daily_log_row` would have made the old section render again from
        the filed daily_jobsite log. That is the tempting fix and it is wrong:
        the same record already has two sections in this document."""
        src = ast.unparse(_fn("generate_combined_report"))
        # ANCHORED AS A CALL. A bare ban on the identifier is substring
        # containment, so `as_daily_log_row_v2` would satisfy it -- which is
        # what test_absence_literals_are_specific refused, correctly.
        self.assertNotIn("as_daily_log_row(", src,
                         "the retired section is being fed from the logbook, "
                         "which prints one record under a third heading")

    def test_the_PREVIEW_still_uses_the_adapter__it_was_right_there(self):
        """The other half. `get_report_preview` reads the filed logbook through
        that adapter and must keep doing so -- its panel reported 'Subs 0' on a
        day with sixteen men until it did."""
        self.assertIn("as_daily_log_row", ast.unparse(_fn("get_report_preview")))


class TheCollectionAndItsRoutesSurvive(unittest.TestCase):
    """Retiring a renderer is not dropping data. Ninety-two records covering
    three weeks of April are a legal record."""

    def test_the_read_routes_are_untouched(self):
        for name in ("get_daily_log", "get_daily_log_by_date", "get_daily_log_pdf"):
            self.assertTrue(_reads_daily_logs(_fn(name)),
                            f"{name} no longer reads the collection it serves")

    def test_the_collection_is_still_queried_somewhere(self):
        """A guard on the guard: if NOTHING read db.daily_logs any more, the
        assertions above would be about routes that had quietly become dead
        too, and this file would be green over a deletion it never noticed."""
        readers = [n.name for n in ast.walk(_TREE)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and _reads_daily_logs(n)]
        self.assertGreaterEqual(
            len(readers), 3,
            f"only {len(readers)} functions still read db.daily_logs: {readers}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
