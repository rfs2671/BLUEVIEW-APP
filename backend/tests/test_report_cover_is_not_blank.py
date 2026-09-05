"""PAGE 1 OF THE FILED REPORT CARRIED THE HEADER AND NOTHING ELSE.

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

    def test_the_shell_rows_carry_the_class_the_exemption_needs(self):
        """A rule on `tr.shell` is inert unless the rows carry it. Five of
        them: the centring row, then the wrapper's header, summary, content
        and footer."""
        html = asyncio.run(server.generate_combined_report(PROJECT, DATE))
        self.assertEqual(html.count('<tr class="shell">'), 5)

    def test_the_fixture_is_actually_longer_than_one_page(self):
        """The precondition. A one-page report cannot exhibit the defect, and
        every assertion below would pass on one."""
        self.assertGreater(len(self._pages()), 1)

    def test_page_one_is_not_just_the_header(self):
        pages = self._pages()
        first = _page_text(pages[0])
        self.assertIn("Daily Construction Report", first)   # the header
        self.assertIn("Daily Progress Report", first,
                      "page 1 carries the header and nothing else — the cover "
                      "is blank")

    def test_the_report_still_starts_each_section_on_its_own_sheet(self):
        """THE GUARANTEE THIS MUST NOT BREAK. Releasing the shell rows must not
        run two filed documents together on one sheet."""
        pages = self._pages()
        titles = ("Tool Box Talk", "Hot Work", "Fall Protection")
        seen = {}
        for i, p in enumerate(pages):
            text = _page_text(p)
            for t in titles:
                if t in text and t not in seen:
                    seen[t] = i
        self.assertEqual(len(seen), len(titles), f"a section vanished: {seen}")
        self.assertEqual(len(set(seen.values())), len(titles),
                         f"two filed documents share a sheet: {seen}")


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
        """ANCHORED TO THIS REPORT'S STYLESHEET, not to the first `@media
        print` in the file. server.py now holds two print blocks -- the
        per-logbook PDF's was added first and appears EARLIER in the file -- so
        an unanchored `index("@media print")` reads the wrong renderer and
        passes on the strength of the other one's `tr.shell`. It did exactly
        that on the pre-fix control run."""
        src = Path(server.generate_combined_report.__code__.co_filename
                   ).read_text(encoding="utf-8")
        i = src.index(":root {{ color-scheme: light only; }}")
        block = src[i:src.index("</style>", i)]
        self.assertIn("tr.shell", block)
        # The bare rule survives, or nothing is protected any more.
        self.assertIn("tr {{ page-break-inside: avoid", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
