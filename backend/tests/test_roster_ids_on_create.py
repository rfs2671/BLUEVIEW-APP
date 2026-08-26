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


class TestNoCheckinPathReadsTheRetiredLoginDirectory(unittest.TestCase):
    """RE-ANCHORED, NOT DELETED.

    This class was written against GET /checkin/{project_id}/companies, which
    once read `db.subcontractors` -- the subcontractor LOGIN directory, with
    email, password and a unique email index. The crew-level ruling retired
    that concept: a roster entry is (trade x company) on a project and there
    are no subcontractor logins, so the collection is correctly empty and
    "Subs 0" was an accurate count of the wrong thing.

    That endpoint is now DELETED -- it had no caller and had already drifted
    from the one the gate reads. Deleting it would have deleted this guard with
    it, so the assertion moves to the endpoint that survived, and widens: no
    check-in path may query the retired directory.

    THE CONCERN IS STILL LIVE. `db.subcontractors` has seven other call sites
    in the owner/subcontractor admin routes. This is not a dead collection; it
    is a collection the GATE must not consult.
    """

    def _checkin_handlers(self):
        """Every /checkin route handler body, sliced to the next decorator."""
        import re
        out = {}
        for m in re.finditer(r'@api_router\.\w+\("(/checkin[^"]*)"', _SRC):
            start = m.start()
            nxt = _SRC.find("@api_router", start + 10)
            out[m.group(1)] = _SRC[start:nxt if nxt != -1 else len(_SRC)]
        return out

    def test_there_are_checkin_handlers_to_check(self):
        """A scan that silently matched nothing would pass forever."""
        handlers = self._checkin_handlers()
        self.assertGreaterEqual(len(handlers), 4, f"found only {list(handlers)}")
        self.assertIn("/checkin/{project_id}/{tag_id}/info", handlers)

    def test_no_checkin_handler_queries_the_login_directory(self):
        """Asserted as a QUERY, not as a word.

        assertNotIn("db.subcontractors", ...) used to fail on the endpoint's own
        docstring and on the comment explaining why the collection was dropped
        -- a source assertion matching prose ABOUT the thing instead of the
        thing. A call has parentheses; an explanation does not.
        """
        import re
        for path, body in self._checkin_handlers().items():
            with self.subTest(path=path):
                self.assertIsNone(
                    re.search(r"db\.subcontractors\.\w+\(", body),
                    f"{path} queries the retired login directory")

    def test_the_gate_reads_the_project_roster_instead(self):
        """The roster the admin maintains, not an accounts table."""
        body = _SRC[_SRC.index("def _active_assignments"):]
        body = body[:body.index("def _merge_trade_assignments")]
        self.assertIn('"trade_assignments"', body)
        self.assertNotIn("subcontractors", body)

    def test_the_dead_endpoint_is_really_gone(self):
        """Both the route and the handler. A decorator removed while the
        function survives leaves a reachable name and a confusing grep."""
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertNotIn("/api/checkin/{project_id}/companies", paths)
        self.assertFalse(hasattr(server, "get_project_companies"))


class TestTheGateRosterIsIndexStable(unittest.TestCase):
    """BEHAVIOURAL, and it pins the contract the check-in <select> rests on.

    checkin.html builds its options with the ARRAY INDEX as the option value
    (`opt.value = String(i)`) and resolves the pick back by index. The server
    filters inactive rows HERE so the two stay in step -- filtering on the
    client would desynchronize it and a worker would pick one crew and file
    another.
    """

    def _info(self, assignments):
        import asyncio
        from unittest.mock import patch

        project = {"_id": "p1", "name": "588 Thomas", "company_name": "GC",
                   "trade_assignments": assignments}

        class _Db:
            class nfc_tags:
                @staticmethod
                async def find_one(*_a, **_k):
                    return {"tag_id": "t1", "project_id": "p1",
                            "location_description": "North Gate"}

            class projects:
                @staticmethod
                async def find_one(*_a, **_k):
                    return project

            def __getattr__(self, name):
                raise AssertionError(f"the endpoint queried db.{name}")

        with patch.object(server, "db", _Db()):
            return asyncio.run(server.get_checkin_info("p1", "t1"))

    def test_inactive_rows_are_dropped_server_side(self):
        out = self._info([
            {"id": "r1", "company": "Vanguard", "trade": "Concrete"},
            {"id": "r2", "company": "Gone Ltd", "trade": "Demolition",
             "status": "inactive"},
            {"id": "r3", "company": "Air Star", "trade": "HVAC / Mechanical"},
        ])
        rows = out["trade_assignments"]
        self.assertEqual([r["company"] for r in rows], ["Vanguard", "Air Star"],
                         "an inactive crew must not be offered at the gate")

    def test_order_is_preserved(self):
        """The index contract. Reordering here silently repoints every option
        value the client already rendered."""
        out = self._info([
            {"id": "r1", "company": "A", "trade": "Concrete"},
            {"id": "r2", "company": "B", "trade": "Framing"},
            {"id": "r3", "company": "C", "trade": "Drywall"},
        ])
        self.assertEqual([r["trade"] for r in out["trade_assignments"]],
                         ["Concrete", "Framing", "Drywall"])

    def test_rows_missing_either_field_are_dropped(self):
        out = self._info([
            {"id": "r1", "company": "A", "trade": "Concrete"},
            {"id": "r2", "company": "", "trade": "Framing"},
            {"id": "r3", "company": "C", "trade": ""},
        ])
        self.assertEqual(len(out["trade_assignments"]), 1)

    def test_it_returns_trade_and_company_not_name(self):
        """The shape the gate actually reads. The deleted /companies endpoint
        returned `name` for the same value, which is how two shapes for one
        roster drifted apart unnoticed."""
        out = self._info([{"id": "r1", "company": "Vanguard", "trade": "Concrete"}])
        row = out["trade_assignments"][0]
        self.assertEqual(set(row), {"trade", "company"})


if __name__ == "__main__":
    unittest.main()
