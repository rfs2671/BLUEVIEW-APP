"""GET /projects/dob-summary response shape — pins the additive per-type
totals (total_violations / total_complaints / total_permits) and
permits_no_expiry alongside the open counts, and the Option-A active-permit
facet structure (REVOKED excluded, not-expired-by-date). Mocks the db so it
asserts the response assembly + pipeline wiring without a live Mongo.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

_PID = "p1"
_FACETS = {
    "open_violations":  [{"_id": _PID, "n": 2}],
    "open_complaints":  [{"_id": _PID, "n": 1}],
    "permits_expiring": [{"_id": _PID, "n": 2}],
    "total_violations": [{"_id": _PID, "n": 6}],
    "total_complaints": [{"_id": _PID, "n": 28}],
    "total_permits":    [{"_id": _PID, "n": 9}],
    "permits_no_expiry":[{"_id": _PID, "n": 3}],
}


def _mock_db():
    db = MagicMock()
    proj_cur = MagicMock(); proj_cur.to_list = AsyncMock(return_value=[{"_id": _PID}])
    db.projects.find = MagicMock(return_value=proj_cur)
    agg_cur = MagicMock(); agg_cur.to_list = AsyncMock(return_value=[_FACETS])
    db.dob_logs.aggregate = MagicMock(return_value=agg_cur)
    db.risk_scores.distinct = AsyncMock(return_value=[])
    return db


class DobSummaryShapeTest(unittest.IsolatedAsyncioTestCase):
    async def _call(self):
        db = _mock_db()
        with patch.object(server, "db", db):
            resp = await server.get_projects_dob_summary(
                project_id=None, current_user={"company_id": "c1", "_id": "u1"})
        return resp, db

    async def test_by_project_has_open_and_total_and_no_expiry(self):
        resp, _ = await self._call()
        bp = resp["by_project"][_PID]
        for k in ("open_violations", "open_complaints", "permits_expiring",
                  "total_violations", "total_complaints", "total_permits",
                  "permits_no_expiry", "has_risk_score"):
            self.assertIn(k, bp, f"missing {k}")
        self.assertEqual(bp["open_violations"], 2)
        self.assertEqual(bp["total_violations"], 6)
        self.assertEqual(bp["total_complaints"], 28)
        self.assertEqual(bp["total_permits"], 9)        # active
        self.assertEqual(bp["permits_no_expiry"], 3)

    async def test_totals_mirror_the_new_fields(self):
        resp, _ = await self._call()
        for k in ("total_violations", "total_complaints", "total_permits",
                  "permits_no_expiry"):
            self.assertIn(k, resp["totals"], f"totals missing {k}")
        self.assertEqual(resp["totals"]["total_permits"], 9)

    async def test_active_permit_facet_excludes_revoked_and_expired(self):
        _, db = await self._call()
        pipeline = db.dob_logs.aggregate.call_args[0][0]
        facet = next(s["$facet"] for s in pipeline if "$facet" in s)
        for k in ("total_violations", "total_complaints", "total_permits",
                  "permits_no_expiry"):
            self.assertIn(k, facet)
        tp = facet["total_permits"]
        # REVOKED excluded (on latest status, after dedup) …
        self.assertTrue(any(st.get("$match", {}).get("permit_status") == {"$ne": "REVOKED"}
                            for st in tp), "REVOKED not excluded")
        # … and only not-expired-by-date counted (>= today_start, no upper bound).
        self.assertTrue(any("_exp" in st.get("$match", {}) and "$gte" in st["$match"]["_exp"]
                            and "$lte" not in st["$match"]["_exp"] for st in tp),
                        "active facet is not an unbounded >= today filter")
        # permits_no_expiry keeps only the null-_exp permits.
        pne = facet["permits_no_expiry"]
        self.assertTrue(any(st.get("$match", {}).get("_exp", "x") is None for st in pne),
                        "permits_no_expiry does not select null-expiry permits")

    async def test_empty_project_set_totals_include_new_keys(self):
        db = _mock_db()
        db.projects.find.return_value.to_list = AsyncMock(return_value=[])
        with patch.object(server, "db", db):
            resp = await server.get_projects_dob_summary(
                project_id=None, current_user={"company_id": "c1"})
        for k in ("total_violations", "total_complaints", "total_permits",
                  "permits_no_expiry"):
            self.assertIn(k, resp["totals"])
            self.assertEqual(resp["totals"][k], 0)


if __name__ == "__main__":
    unittest.main()
