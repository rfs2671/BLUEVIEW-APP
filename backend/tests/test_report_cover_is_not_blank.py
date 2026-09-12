"""PAGE 1 OF THE FILED REPORT CARRIED THE HEADER AND NOTHING ELSE.

── MIGRATED 12 SEPTEMBER, AND CI IS WHAT CAUGHT IT ────────────────────────

These tests are WeasyPrint-gated: they skip where the native libraries are
absent, and the guard turns that skip into a failure under CI. A local suite
reported green while they never ran, which is precisely the hole the guard
exists to cover -- and the reason the report replacement's migration ledger
never listed this file.

THE CAUSE CANNOT RECUR ON THIS DOCUMENT. The investor report has no email
shell, no content row and no embedded section; it is three composed pages. The
unqualified `tr` rule that relocated the body is not in its stylesheet and has
nothing to match if it were.

So the halves went different ways, and the original account below is kept
because the defect is worth being able to read:

  * PAGE 1 IS NOT JUST THE HEADER is the claim worth keeping, and it is
    rewritten against the page that exists rather than deleted.
  * THE SHELL ROWS AND THEIR EXEMPTION moved to the per-logbook PDF, which
    still is an email-style document and still carries both rules.
  * EACH SECTION ON ITS OWN SHEET is deleted. There are no sections.

── AND THE ORIGINAL ───────────────────────────────────────────────────────


The operator photographed it: a cover page with the LEVELOG banner, the date,
the address, and then white paper to the fold. Every section of the report
began on page 2.

THE CAUSE, MEASURED. The print block carried an unqualified
`tr { page-break-inside: avoid }`, written for roster rows. This document's
outer markup is an email layout, and one of the rows it matched is the
wrapper's single CONTENT row -- the cell holding every section of the report.
WeasyPrint will not split a row it has been told to keep together, so it
relocated the entire body to a fresh sheet and left page 1 with the header and
the summary. The rule meant for a man's name and his check-in time was applied
to the whole document.

Ablated one rule at a time on real production HTML (2026-09-05, project
588 Thomas S Boyland Street):

    2026-08-25   before   7 pages   page 1 = 109 chars, header + summary only
    2026-08-25   after    6 pages   page 1 = 450 chars, Daily Progress Report

THE FIX IS PARTIAL AND THAT IS ASSERTED BELOW, NOT GLOSSED. On 2026-08-31 the
first section is ~1715px -- taller than a whole A4 page -- and it still begins
on page 2 after this change, because `.doc-section { break-inside: avoid }`
relocates it independently. `break-inside` has no "avoid only if it fits", so
closing that case means deciding whether a section may split when it cannot
fit, which is a ruling about a filed document and not a CSS question. See
test_weasyprint_break_inside_semantics.py for the engine behaviour that makes
this unavoidable.

TWO CONSTRAINTS, the same two as the sibling geometry file:

1. WHICH PAGE, NEVER A PIXEL COUNT. CI renders against Ubuntu's pango,
   production against Debian's. "The section title is on page 1" survives the
   difference; "page 1 ends at y=794" does not.

2. THE SKIP IS GUARDED. Without WeasyPrint's native libraries this file skips;
   under `CI` the skip becomes a failure, so it cannot go green for the reason
   it exists.
"""

from __future__ import annotations

import asyncio
import copy
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

try:
    from weasyprint import HTML
except Exception as exc:  # pragma: no cover - depends on native libraries
    HTML = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

DATE = "2026-08-12"
PROJECT = "p1"


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query or {}))


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


def _page_text(page) -> str:
    out = []

    def walk(box):
        text = getattr(box, "text", None)
        if text:
            out.append(text)
        for child in getattr(box, "children", ()) or ():
            walk(child)

    walk(page._page_box)
    return " ".join(out)


@unittest.skipIf(HTML is None and not os.environ.get("CI"),
                 f"weasyprint native libraries unavailable: {_IMPORT_ERROR}")
class TheCoverCarriesTheFirstSection(unittest.TestCase):

    def setUp(self):
        if HTML is None:
            self.fail(f"weasyprint did not import in CI: {_IMPORT_ERROR}")

        self.db = _DB()
        self.db.projects.docs = [{
            "_id": PROJECT, "name": "8 Walworth St", "address": "8 Walworth St",
            "project_class": "regular",
        }]
        self.db.checkins.docs = [
            {"project_id": PROJECT, "date": DATE, "worker_id": f"w{i}",
             "worker_name": f"Worker {i}", "company": "AAZ",
             "status": "checked_in", "check_in_time": f"{DATE}T11:00:00Z"}
            for i in range(4)
        ]
        # SEVERAL SECTIONS, EACH SHORT. Every section carries
        # `page-break-after:always`, so more than one guarantees a multi-page
        # document -- which is the precondition for the defect. A single tall
        # section would ALSO be relocated by the .doc-section wrapper, and the
        # test would then be measuring the case this change does not fix.
        self.db.logbooks.docs = [
            {"_id": f"lb{i}", "project_id": PROJECT, "date": DATE,
             "log_type": lt, "is_deleted": False, "status": "submitted",
             "cp_name": "carl cp", "data": {"notes": f"note {i}"}}
            for i, lt in enumerate(("toolbox_talk", "hot_work", "fall_protection"))
        ]
        # AND A DAY WITH WORK ON IT. The original fixture only needed several
        # short sections; the page that replaced them has an activity to
        # describe, and "page 1 is not just the header" is not a claim worth
        # testing on a day with nothing to put there.
        self.db.logbooks.docs.append({
            "_id": "lb_dj", "project_id": PROJECT, "date": DATE,
            "log_type": "daily_jobsite", "is_deleted": False,
            "status": "submitted", "cp_name": "carl cp",
            "data": {"activities": [{
                "company": "AAZ", "trade": "Concrete", "num_workers": "4",
                "work_locations": "1st floor",
                "work_description": "slab pour", "photos": [],
            }]},
        })
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]

    def _pages(self):
        # NO MARKER CHECK HERE. An `assertIn('class="shell"')` in this helper
        # made every assertion below fail on the pre-fix code for the wrong
        # reason -- the marker's absence -- so the control proved the class was
        # missing and never that the cover was blank. The marker is asserted
        # once, on its own, below.
        html = asyncio.run(server.generate_combined_report(PROJECT, DATE))
        return HTML(string=html).render().pages

    def test_the_shell_rows_are_on_the_document_that_still_has_a_shell(self):
        """A rule on `tr.shell` is inert unless the rows carry it.

        THE SHELL MOVED, AND SO DID THE COUNT. The investor report was an
        email-style layout and is now three composed pages; the per-logbook
        PDF is the email-style document, and it is the one whose rows must
        carry the class its exemption names.
        """
        html = asyncio.run(server.generate_single_logbook_html(
            {"_id": "lb0", "project_id": PROJECT, "date": DATE,
             "log_type": "toolbox_talk", "status": "submitted",
             "cp_name": "carl cp", "data": {"notes": "note"}}))
        self.assertGreaterEqual(html.count('<tr class="shell">'), 3)

    def test_and_the_investor_report_has_no_shell_to_protect(self):
        """THE OTHER HALF, AND IT IS WHY THE DEFECT CANNOT RECUR HERE. The
        rule that relocated the body matched a row of the email shell. There
        is no shell, so there is nothing for an unqualified `tr` rule to
        match even if one were written."""
        html = asyncio.run(server.generate_combined_report(PROJECT, DATE))
        self.assertNotIn('<tr class="shell">', html)

    def test_the_fixture_is_actually_longer_than_one_page(self):
        """The precondition. A one-page report cannot exhibit the defect, and
        every assertion below would pass on one."""
        self.assertGreater(len(self._pages()), 1)

    def test_page_one_is_not_just_the_header(self):
        """THE CLAIM THIS FILE IS FOR, ON THE PAGE THAT EXISTS.

        The old cover carried the banner, the date and the address, and then
        white paper to the fold. The new page 1 has to carry the day: the
        summary, the gate figures and the activity. Named rather than counted,
        because a character count passes on a page of running heads.
        """
        first = _page_text(self._pages()[0])
        self.assertIn("DAILY CONSTRUCTION REPORT", first)    # the head
        for substance in ("EXECUTIVE SUMMARY", "GATE CHECK-INS",
                          "TODAY’S DOCUMENTED ACTIVITY", "AAZ"):
            self.assertIn(substance, first,
                          f"page 1 does not carry {substance!r} -- the cover "
                          f"is the header and nothing else again")

    # DELETED: test_the_report_still_starts_each_section_on_its_own_sheet
    #
    #   It guaranteed that releasing the shell rows did not run two FILED
    #   DOCUMENTS together on one sheet. The report embeds no filed document
    #   now -- it indexes them -- so there are no sections to run together and
    #   nothing the guarantee can be made about.
    #
    #   What replaced the sections is the record index on page 3, and that the
    #   report is exactly three pages is asserted on four day shapes in
    #   test_report_renderer.py::ThePageCount. See
    #   docs/audits/report-replacement-ledger.md.

    def test_the_report_is_more_than_one_page_and_the_first_is_not_the_last(self):
        """THE PRECONDITION THIS FILE ALWAYS HAD, restated. A one-page report
        cannot exhibit a blank cover, and every assertion here would pass on
        one.

        TWO PAGES ON THIS FIXTURE, NOT THREE, and the difference is the
        design. The day's one activity carries no photographs, so the evidence
        page collapses entirely -- a page reserved for evidence that does not
        exist is the empty-section defect the whole redesign was about. Page 2
        here is the project record.
        """
        pages = self._pages()
        self.assertEqual(len(pages), 2,
                         "the fixture's day has no photographs, so the "
                         "evidence page should collapse")
        self.assertNotEqual(_page_text(pages[0]), _page_text(pages[-1]))
        self.assertIn("Project record", _page_text(pages[-1]))


@unittest.skipIf(HTML is None and not os.environ.get("CI"), "see above")
class TheNestedRowsAreStillProtected(unittest.TestCase):
    """The exemption is scoped to the five shell rows. A roster row inside the
    content cell must still refuse to split — that is what the rule was written
    for, and releasing it wholesale is the other way to make the test above
    pass."""

    def setUp(self):
        if HTML is None:
            self.fail(f"weasyprint did not import in CI: {_IMPORT_ERROR}")

    def test_the_exemption_names_a_class_and_not_the_bare_element(self):
        """THE RULE MOVED TO THE DOCUMENT THAT STILL HAS A SHELL.

        It was anchored to the combined report's stylesheet, and deliberately:
        server.py held two print blocks and an unanchored `index("@media
        print")` read the wrong renderer and passed on the strength of the
        other one's `tr.shell`. There is one print block now -- the
        per-logbook PDF's -- because the report's went with its shell, so the
        anchor is the renderer itself.

        BOTH HALVES STILL MATTER on that document. The bare rule is what keeps
        a man's name and his check-in time on one sheet; the class is what
        stops it being applied to the whole document.
        """
        src = Path(server.generate_single_logbook_html.__code__.co_filename
                   ).read_text(encoding="utf-8")
        i = src.index("async def generate_single_logbook_html(")
        block = src[i:src.index("</style>", i)]
        # DOUBLED BRACES. This block is inside an f-string, so the source
        # carries `{{` where the rendered stylesheet carries `{`. The original
        # assertion had them doubled for the same reason and I un-doubled them
        # when re-anchoring; CI caught it.
        self.assertIn("tr.shell {{ page-break-inside: auto", block)
        # The bare rule survives, or nothing is protected any more.
        self.assertIn("tr {{ page-break-inside: avoid", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
