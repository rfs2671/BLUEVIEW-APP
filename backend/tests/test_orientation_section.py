"""THE ORIENTATION SECTION REPORTS SOMETHING, OR IT REPORTS NOTHING AT ALL.

An orientation is due ONCE PER WORKER, before he starts. Most days bring no new
workers, so most days have nothing to put in the "Oriented Today" table — and
it printed anyway: five column headers over a single cell reading "No
orientations filed today". A section that reports nothing on a compliance
document teaches a reader to skip it, and the line above it is the one that
matters.

WHAT MUST SURVIVE THE SUPPRESSION, and why the whole section could not simply
be dropped on a quiet day: the coverage line is the LL196 first-timer check.

    "3 of 5 on-site workers — 2 on-site worker(s) with no orientation on file"

That is a real deficiency, and it is a deficiency on EXACTLY the days nobody was
oriented. The section renders whenever anybody checked in, which is what lets it
catch an un-oriented worker on a day no orientation was filed; suppressing the
section would have deleted the warning along with the empty table.

So: the table goes when it is empty, the coverage line stays either way.
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


def _checkin(worker_id, name):
    return {"project_id": PROJECT, "date": DATE, "worker_id": worker_id,
            "worker_name": name, "company": "AAZ", "status": "checked_in",
            "check_in_time": "2026-08-12T11:00:00Z"}


def _orientation(worker_id, name, *, date=DATE, signed=True):
    return {
        "_id": f"or_{worker_id}_{date}", "project_id": PROJECT, "date": date,
        "log_type": "subcontractor_orientation", "is_deleted": False,
        "is_locked": True, "status": "submitted", "cp_name": "carl cp",
        "data": {
            "worker_id": worker_id, "worker_name": name, "worker_trade": "laborer",
            "worker_company": "AAZ", "completed_at": f"{date}T08:00:00Z",
            "worker_signature": {"paths": [[{"x": 1, "y": 1}]]} if signed else None,
        },
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.db = _DB()
        self.db.projects.docs = [{
            "_id": PROJECT, "name": "8 Walworth St", "address": "8 Walworth St",
            "project_class": "regular",
        }]
        self.db.logbooks.docs = []
        self.db.checkins.docs = [_checkin("w1", "Wilmer Carrillo"),
                                 _checkin("w2", "Segundo Pilamunga")]
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]

    def html(self):
        return asyncio.run(server.generate_combined_report(PROJECT, DATE))

    def section(self):
        """Just the orientation section, so an assertion cannot be satisfied by
        another part of a 60KB document.

        Anchored on the SECTION TITLE cell, not on the bare label: the label is
        also the registry name that page 1's compliance line prints, and slicing
        from the first occurrence caught that instead."""
        h = self.html()
        anchor = ">Subcontractor Safety Orientation</td>"
        i = h.find(anchor)
        if i < 0:
            return ""
        # Section titles render as a table with this margin; the next one is
        # where this section ends.
        k = h.find("margin:28px 0 12px 0", i + len(anchor))
        return h[i:k if k > i else len(h)]


class TheEmptyTableIsGone(Base):

    def test_a_day_with_no_new_workers_renders_no_table(self):
        """Both men were oriented weeks ago. Nothing was filed today, and
        nothing is outstanding."""
        self.db.logbooks.docs = [
            _orientation("w1", "Wilmer Carrillo", date="2026-07-01"),
            _orientation("w2", "Segundo Pilamunga", date="2026-07-02"),
        ]
        sec = self.section()
        self.assertNotIn("Oriented Today", sec)
        self.assertNotIn("No orientations filed today", sec)
        self.assertNotIn(">Conducted By (CP)<", sec)

    def test_but_the_coverage_line_still_prints(self):
        """The section is not suppressed — only the table inside it."""
        self.db.logbooks.docs = [
            _orientation("w1", "Wilmer Carrillo", date="2026-07-01"),
            _orientation("w2", "Segundo Pilamunga", date="2026-07-02"),
        ]
        sec = self.section()
        self.assertIn("First-time orientation on file", sec)
        self.assertIn("2 of 2 on-site workers", sec)

    def test_the_placeholder_sentence_is_gone_from_the_whole_document(self):
        self.assertNotIn("No orientations filed today", self.html())


class TheGapWarningSurvives(Base):
    """The reason the section could not simply be dropped on a quiet day."""

    def test_an_un_oriented_worker_is_reported_with_no_table_present(self):
        self.db.logbooks.docs = [_orientation("w1", "Wilmer Carrillo",
                                              date="2026-07-01")]
        sec = self.section()
        self.assertIn("1 of 2 on-site workers", sec)
        self.assertIn("1 on-site worker(s) with no orientation on file", sec)
        # ...and the empty table is still absent. The two are independent.
        self.assertNotIn("Oriented Today", sec)

    def test_nobody_oriented_at_all_is_the_loudest_case(self):
        sec = self.section()
        self.assertIn("0 of 2 on-site workers", sec)
        self.assertIn("2 on-site worker(s) with no orientation on file", sec)
        self.assertNotIn("Oriented Today", sec)

    def test_full_coverage_draws_no_warning(self):
        self.db.logbooks.docs = [
            _orientation("w1", "Wilmer Carrillo", date="2026-07-01"),
            _orientation("w2", "Segundo Pilamunga", date="2026-07-02"),
        ]
        self.assertNotIn("no orientation on file", self.section())


class TheTableReturnsWhenThereIsSomethingInIt(Base):

    def test_an_orientation_filed_today_renders_the_table(self):
        self.db.logbooks.docs = [_orientation("w1", "Wilmer Carrillo")]
        sec = self.section()
        self.assertIn("Oriented Today", sec)
        self.assertIn(">Conducted By (CP)<", sec)
        self.assertIn("Wilmer Carrillo", sec)

    def test_the_signed_count_appears_only_when_something_was_filed(self):
        self.assertNotIn("Worker acknowledgments signed", self.section())
        self.db.logbooks.docs = [_orientation("w1", "Wilmer Carrillo")]
        self.assertIn("Worker acknowledgments signed", self.section())

    def test_an_unsigned_acknowledgment_is_still_called_out(self):
        """worker_signature is hardcoded null on manual entries; an unattested
        acknowledgment must never read as complete."""
        self.db.logbooks.docs = [_orientation("w1", "Wilmer Carrillo", signed=False)]
        sec = self.section()
        self.assertIn("UNSIGNED", sec)
        self.assertIn("0 of 1 filed today", sec)

    def test_a_row_that_names_nobody_still_reaches_the_table(self):
        """NOT the Group 1 rule. An orientation is ONE DOCUMENT PER WORKER, not
        a row in a roster, so a nameless one is a malformed record rather than
        a spare row — and dropping it would hide it. It renders with an em dash
        and the reader can see there is a document that names no one."""
        doc = _orientation("w3", "")
        doc["data"]["worker_name"] = ""
        self.db.logbooks.docs = [doc]
        self.assertIn("Oriented Today", self.section())


if __name__ == "__main__":
    unittest.main()
