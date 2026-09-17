"""NOTHING IN THIS PRODUCT DESTROYS A FILED RECORD, AND A COMPANY CANNOT
LEAVE ITS PROJECTS BEHIND.

── THE TWO DEFECTS, BOTH MEASURED ──────────────────────────────────────────

ONE. `hard_delete_project` physically removes a project and every document it
owns, and the R2 sweeps delete by PREFIX — those objects have no rows to
rebuild from. Nothing asked whether the project held a filed logbook or a
signature event. A BC 3301.13 log and a worker's gate affirmation were one
click from gone, and the operator found out what had been in there afterwards.

TWO. `hard_delete_company` checked for active ADMINS and nothing else. It
deleted the company and every user under it and NEVER LOOKED AT PROJECTS. It
ran four times; three of those company ids still have projects in the database
with no company document to hang them on — 26 projects and 20 logbooks, one of
them LIVE and appearing on the operator's own project list under no card.

── WHY THE BLOCK IS A REFUSAL AND NOT A WARNING ────────────────────────────

A count on a confirmation dialog is a thing an operator clicks past at the end
of a long day. These are statutory records and a person's attestation; the
system is not entitled to destroy them on anybody's say-so, including the
platform operator's — retention is owed to a regulator, and he is not the party
it is owed to. Soft delete hides them and keeps them, and that is the operation
for a project with records.

── AND WHY THE CASCADE IS REFUSED RATHER THAN RUN ──────────────────────────

Deleting a project is a decision about compliance records, one project at a
time, with its own refusal. Running it implicitly for twenty-six of them to
satisfy a click on a different row is how the orphans happened in the first
place.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret_for_the_suite")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.purge_dependencies import (  # noqa: E402
    company_dependencies, confirm_matches, project_dependencies,
)

PROJECT = "6a5f63bc147407d3261df2c7"
COMPANY = "6a32a11051c7a54c476d2149"


class _Coll:
    """Counts whatever the query asks for, from a fixed answer table."""

    def __init__(self, answers=None, rows=None):
        self.answers = answers or {}
        self.rows = rows or []
        self.seen = []

    async def count_documents(self, query):
        self.seen.append(query)
        for key, value in self.answers.items():
            if key in str(query):
                return value
        return self.answers.get("*", 0)

    def find(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self.rows)


class _DB:
    def __init__(self, table):
        self.table = table

    def __getitem__(self, name):
        return self.table.get(name, _Coll())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.table.get(name, _Coll())


class AFiledLogbookBlocksThePurge(unittest.TestCase):

    def test_a_submitted_logbook_blocks(self):
        db = _DB({"logbooks": _Coll({"status": 3, "*": 3})})
        out = asyncio.run(project_dependencies(db, PROJECT, ["logbooks"]))
        kinds = [b["kind"] for b in out["blocking"]]
        self.assertIn("filed_logbooks", kinds)

    def test_a_signature_event_blocks(self):
        db = _DB({"signature_events": _Coll({"*": 7})})
        out = asyncio.run(project_dependencies(db, PROJECT, []))
        kinds = [b["kind"] for b in out["blocking"]]
        self.assertIn("signature_events", kinds)

    def test_a_project_with_neither_does_not_block(self):
        """THE OTHER HALF, AND IT HAS TO WORK. A block that fires on everything
        is a delete button that never works, and the operator then goes back to
        deleting rows by hand in Atlas — which is the incident this came from."""
        db = _DB({"logbooks": _Coll({"*": 0}),
                  "signature_events": _Coll({"*": 0})})
        out = asyncio.run(project_dependencies(db, PROJECT, ["logbooks"]))
        self.assertEqual(out["blocking"], [])

    def test_drafts_alone_do_not_block(self):
        """A draft is unfinished work, not a filed record. The selector asks
        for submitted OR locked, and this is the case that proves it is not
        just counting logbooks."""
        db = _DB({"logbooks": _Coll({"status": 0, "*": 12}),
                  "signature_events": _Coll({"*": 0})})
        out = asyncio.run(project_dependencies(db, PROJECT, ["logbooks"]))
        self.assertEqual(out["blocking"], [])
        self.assertEqual(out["counts"]["logbooks"], 12)

    def test_the_block_says_WHY(self):
        """An operator who is refused and not told why goes looking for a
        bigger role, or for Atlas."""
        db = _DB({"signature_events": _Coll({"*": 1})})
        out = asyncio.run(project_dependencies(db, PROJECT, []))
        self.assertTrue(out["blocking"][0]["reason"].strip())
        self.assertIn("attestation", out["blocking"][0]["reason"])

    def test_the_unrecoverable_part_is_named_separately(self):
        """R2 objects are deleted by PREFIX and have no rows to rebuild from.
        That is a different warning from "you will lose 40 checkins", and
        burying it in the same list is how it stops being read."""
        db = _DB({"project_files": _Coll({"*": 6}),
                  "document_page_index": _Coll({"*": 86})})
        out = asyncio.run(project_dependencies(db, PROJECT, []))
        self.assertEqual(out["unrecoverable"],
                         {"project_files": 6, "indexed_pages": 86})


class ACompanyCannotLeaveItsProjectsBehind(unittest.TestCase):

    def test_any_project_blocks_the_company_delete(self):
        db = _DB({"projects": _Coll(rows=[
            {"_id": "p1", "name": "857 Prescott Pl", "is_deleted": False},
        ])})
        out = asyncio.run(company_dependencies(db, COMPANY))
        self.assertEqual([b["kind"] for b in out["blocking"]],
                         ["projects_would_be_orphaned"])

    def test_a_SOFT_DELETED_project_blocks_it_too(self):
        """THE EXACT SHAPE OF THE FOUR ORPHANS. Every one of the 26 stranded
        projects is soft-deleted; if only live projects blocked, this delete
        would have been allowed all four times and still orphaned them."""
        db = _DB({"projects": _Coll(rows=[
            {"_id": "p1", "name": "638 Lafayette Avenue", "is_deleted": True},
        ])})
        out = asyncio.run(company_dependencies(db, COMPANY))
        self.assertEqual([b["kind"] for b in out["blocking"]],
                         ["projects_would_be_orphaned"])
        self.assertEqual(out["blocking"][0]["live"], 0)

    def test_a_company_with_no_projects_is_deletable(self):
        db = _DB({"projects": _Coll(rows=[])})
        out = asyncio.run(company_dependencies(db, COMPANY))
        self.assertEqual(out["blocking"], [])

    def test_it_NAMES_the_projects(self):
        """"This company still has projects" sends the operator hunting. The
        names are what let him decide whether to delete or reparent them."""
        db = _DB({"projects": _Coll(rows=[
            {"_id": "p1", "name": "857 Prescott Pl", "is_deleted": False},
            {"_id": "p2", "name": "587 Prescott Place", "is_deleted": False},
        ])})
        out = asyncio.run(company_dependencies(db, COMPANY))
        self.assertEqual(out["blocking"][0]["names"],
                         ["857 Prescott Pl", "587 Prescott Place"])


class TheNameIsTyped(unittest.TestCase):

    def test_it_matches_the_name(self):
        self.assertTrue(confirm_matches("857 Prescott Pl", "857 Prescott Pl"))

    def test_case_and_spacing_are_forgiven(self):
        """The control exists to make the act deliberate, not to test
        transcription."""
        self.assertTrue(confirm_matches("  857   prescott PL ", "857 Prescott Pl"))

    def test_a_different_name_does_not(self):
        self.assertFalse(confirm_matches("587 Prescott Place", "857 Prescott Pl"))

    def test_EMPTY_MATCHES_NOTHING(self):
        """A project with no name would otherwise be deletable by sending "" —
        an empty confirmation on the row least likely to be the one anybody
        meant."""
        for expected in ("", None, "   "):
            with self.subTest(expected=expected):
                self.assertFalse(confirm_matches("", expected))
                self.assertFalse(confirm_matches("anything", expected))

    def test_a_prefix_is_not_enough(self):
        self.assertFalse(confirm_matches("857", "857 Prescott Pl"))


class TheEndpointsEnforceIt(unittest.TestCase):
    """The rules are pure and tested above; these assert they are REACHED, and
    reached BEFORE anything is destroyed."""

    def setUp(self):
        self.src = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def _body(self, marker, end="\n@api_router"):
        start = self.src.index(marker)
        return self.src[start:self.src.index(end, start)]

    def test_the_project_purge_blocks_and_confirms_before_it_deletes(self):
        body = self._body("async def hard_delete_project")
        gate = body.index("SIGNED_RECORDS_PRESENT")
        confirm = body.index("CONFIRM_NAME_MISMATCH")
        for destructive in ("delete_many(", "_r2_delete_prefix", "delete_one("):
            if destructive in body:
                with self.subTest(destructive):
                    self.assertLess(
                        gate, body.index(destructive),
                        "the signed-record refusal must precede every "
                        "destructive call — a refusal after the R2 sweep has "
                        "already destroyed the photographs")
                    self.assertLess(confirm, body.index(destructive))

    def test_the_company_delete_refuses_orphaning(self):
        body = self._body("async def hard_delete_company")
        self.assertIn("PROJECTS_WOULD_BE_ORPHANED", body)
        self.assertLess(body.index("PROJECTS_WOULD_BE_ORPHANED"),
                        body.index("delete_many("))

    def test_the_company_audit_row_is_written_BEFORE_the_delete(self):
        """It has to survive the delete. A row written afterwards is a row that
        is not written when the delete succeeds and the process then dies."""
        body = self._body("async def hard_delete_company")
        self.assertLess(body.index('audit_log(\n        "company_hard_delete"'),
                        body.index("await db.users.delete_many"))

    def test_the_company_audit_row_names_the_actor(self):
        body = self._body("async def hard_delete_company")
        self.assertIn("actor_id(current_user)", body)
        self.assertNotIn('current_user.get("_id", "")', body)

    def test_both_take_a_typed_name(self):
        for fn in ("hard_delete_project", "hard_delete_company"):
            with self.subTest(fn):
                self.assertIn("confirm_name", self._body(f"async def {fn}"))


class ThePanelHidesNothing(unittest.TestCase):

    def setUp(self):
        self.src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        start = self.src.index("async def get_companies")
        whole = self.src[start:self.src.index("\nclass TestFlagUpdate", start)]
        # THE CODE, NOT THE PROSE. This function's docstring QUOTES the old
        # query in order to explain what changed, so a search over the whole
        # body finds the very string the change removed — and the assertion
        # fails on the explanation rather than on the code.
        self.body = whole[whole.index('"""', whole.index('"""') + 3) + 3:]

    def test_the_company_query_is_unfiltered(self):
        """A soft-deleted company used to vanish with no way to see it existed.
        It is a row with a status now."""
        self.assertIn("db.companies.find({})", self.body)
        self.assertNotIn('{"is_deleted": {"$ne": True}}', self.body)

    def test_the_docstring_still_records_what_it_replaced(self):
        """Belt and braces on the slice above: if the docstring ever stops
        quoting the old query, the assertion above is passing over prose that
        is no longer there and proves less than it looks."""
        head = self.src[self.src.index("async def get_companies"):]
        self.assertIn('{"is_deleted": {"$ne": True}}',
                      head[:head.index('"""', head.index('"""') + 3)])

    def test_it_returns_orphans(self):
        self.assertIn('"orphans"', self.body)

    def test_every_row_carries_a_status(self):
        for word in ('"deleted"', '"test"', '"active"'):
            with self.subTest(word):
                self.assertIn(word, self.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
