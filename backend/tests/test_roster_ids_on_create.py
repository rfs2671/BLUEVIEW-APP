"""ROSTER IDS ARE MINTED ON CREATE, AND SUBS COUNTS THE ROSTER.

Device round 5, B1 / B7 / B8 — one root cause, as the operator identified.

`_merge_trade_assignments` had ONE call site, the project UPDATE path. A roster
supplied at CREATION was stored exactly as the client sent it, with no
server-minted `id` on any row — and `get_daily_headcount` skips id-less rows:

    _rid = str(_assignment.get("id") or "").strip()
    if not _rid:
        continue

so `roster_ids` came out empty and `subcontractor_id` was None on EVERY activity
row. The chip ranker then had no trade and fell back to the whole catalogue.
The crew-level ruling was implemented; it was one call site short of the door.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")


class TestBothPathsMintByTheSameRule(unittest.TestCase):
    def test_create_mints_ids_for_a_roster_supplied_at_creation(self):
        rows = server._merge_trade_assignments(
            [], [{"trade": "Concrete", "company": "Vanguard"},
                 {"trade": "Formwork", "company": "Vanguard"}])
        self.assertEqual(len(rows), 2)
        for row in rows:
            with self.subTest(row=row):
                self.assertTrue(str(row.get("id") or "").strip(),
                                "an id-less row is invisible to get_daily_headcount")
        self.assertNotEqual(rows[0]["id"], rows[1]["id"],
                            "two crews at one company are two roster rows")

    def test_the_create_path_calls_it(self):
        """The whole defect in one assertion: it was only ever called on update."""
        self.assertEqual(_SRC.count("_merge_trade_assignments("), 3)  # def + update + create
        create = _SRC[_SRC.index("async def create_project"):]
        create = create[:create.index("async def ", 20)]
        self.assertIn("_merge_trade_assignments(", create)

    def test_a_clients_id_is_still_discarded(self):
        """Ids are SERVER-OWNED — unchanged by adding the second call site."""
        rows = server._merge_trade_assignments(
            [], [{"trade": "Concrete", "company": "Vanguard", "id": "client-made-this"}])
        self.assertNotEqual(rows[0]["id"], "client-made-this")

    def test_an_empty_roster_at_creation_is_not_an_error(self):
        self.assertEqual(server._merge_trade_assignments([], []), [])

    def test_nothing_here_rewrites_stored_projects(self):
        """Existing projects keep their id-less rows until someone edits them.
        The backfill is the operator's call, and this pins that the code does
        not quietly make it for him."""
        create = _SRC[_SRC.index("async def create_project"):]
        create = create[:create.index("async def ", 20)]
        self.assertNotIn("update_many", create)


class TestSubsCountsTheRosterNotTheLoginTable(unittest.TestCase):
    """`db.subcontractors` is the subcontractor LOGIN directory — email,
    password, unique email index. The crew-level ruling retired it, so it is
    correctly empty and "Subs 0" was an accurate count of the wrong thing."""

    def _endpoint(self):
        src = _SRC[_SRC.index('@api_router.get("/checkin/{project_id}/companies")'):]
        return src[:src.index("@api_router", 10)]

    def test_it_no_longer_reads_the_login_directory(self):
        """Asserted as a QUERY, not as a word.

        assertNotIn("db.subcontractors", ...) failed on the endpoint's own
        docstring and on the comment explaining why the collection was
        dropped — the fifth time on this project that a source assertion
        matched prose ABOUT the thing instead of the thing. A call has
        parentheses; an explanation does not.
        """
        import re
        self.assertIsNone(
            re.search(r"db\.subcontractors\.\w+\(", self._endpoint()),
            "the endpoint still queries the retired login directory")

    def test_it_reads_the_project_roster(self):
        self.assertIn('project.get("trade_assignments")', self._endpoint())

    def test_it_returns_the_roster_and_nothing_else(self):
        """BEHAVIOURAL, not textual.

        The two assertions this replaces checked that `_assignment_is_inactive`
        and `_roster_key` APPEARED in the endpoint, and both survived a mutation
        that removed the call — the identifier still appeared elsewhere in the
        slice. Calling the endpoint settles what it does.
        """
        import asyncio
        from unittest.mock import patch

        project = {
            "_id": "p1", "company_id": None,
            "trade_assignments": [
                {"id": "r1", "company": "Vanguard", "trade": "Concrete"},
                {"id": "r2", "company": "vanguard ", "trade": " concrete"},
                {"id": "r3", "company": "Gone Ltd", "trade": "Demolition",
                 "status": "inactive"},
                {"id": "r4", "company": "Air Star", "trade": "HVAC / Mechanical"},
            ],
        }

        class _Projects:
            async def find_one(self, *_a, **_k):
                return project

        class _Db:
            projects = _Projects()

            def __getattr__(self, name):
                raise AssertionError(f"the endpoint queried db.{name}")

        with patch.object(server, "db", _Db()):
            out = asyncio.run(server.get_project_companies("p1"))

        rows = out["companies"] if isinstance(out, dict) else out
        names = [(r["name"], r["trade"]) for r in rows]
        self.assertIn(("Vanguard", "Concrete"), names)
        self.assertIn(("Air Star", "HVAC / Mechanical"), names)
        self.assertNotIn("Gone Ltd", [n for n, _ in names])
        self.assertEqual(
            len([n for n, _ in names if n.strip().lower() == "vanguard"]), 1,
            "a case-only edit must not produce two entries for one crew")


if __name__ == "__main__":
    unittest.main()
