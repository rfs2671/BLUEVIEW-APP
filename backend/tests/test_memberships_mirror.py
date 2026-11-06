"""Memberships, stage 1: a mirror of the users documents that nothing reads.

The rulings (2026-11-05): one person, many company memberships
{user, company, role, project scope, status}. This stage builds the collection
and keeps it equal to what the users documents say. It must change nothing a
person can do or see, so the last class here pins that no code reads it yet.
"""

from __future__ import annotations

import asyncio
import copy
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))

from bson import ObjectId  # noqa: E402

from lib import memberships as m  # noqa: E402
from async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, matches  # noqa: E402

CO_A = "6a00000000000000000000aa"
CO_B = "6a00000000000000000000bb"


def user(uid, company=CO_A, role="admin", **kw):
    return {"_id": ObjectId(uid), "company_id": company, "role": role, **kw}


U1 = "6b0000000000000000000001"
U2 = "6b0000000000000000000002"


def apply(writes, rows):
    """plan_mirror's writes applied the way run_membership_mirror applies them."""
    rows = copy.deepcopy(rows)
    for w in writes:
        hit = next((r for r in rows if r["user_id"] == w["key"]["user_id"]
                    and r["company_id"] == w["key"]["company_id"]), None)
        if hit is None:
            rows.append({**w["key"], **w["set"]})
        else:
            hit.update(w["set"])
    return rows


class ExpectedFromUser(unittest.TestCase):

    def test_a_user_with_a_company_has_one_membership_carrying_its_scope(self):
        row = m.expected_from_user(user(U1, role="pm", pm_access="assigned",
                                        assigned_projects=[ObjectId(U2), "p2"]))
        self.assertEqual(row, {
            "user_id": U1, "company_id": CO_A, "role": "pm", "pm_access": "assigned",
            "assigned_projects": [U2, "p2"], "status": m.STATUS_ACTIVE})

    def test_no_company_means_no_membership(self):
        # The platform operator's row and a pending signup both have none.
        self.assertIsNone(m.expected_from_user(user(U1, company=None)))
        self.assertIsNone(m.expected_from_user(user(U1, company="  ")))

    def test_a_soft_deleted_user_keeps_a_removed_membership(self):
        self.assertEqual(m.expected_from_user(user(U1, is_deleted=True))["status"],
                         m.STATUS_REMOVED)


class PlanMirror(unittest.TestCase):

    def test_backfill_inserts_one_row_per_user_with_a_company(self):
        users = [user(U1), user(U2, company=None)]
        writes = m.plan_mirror(users, [])
        self.assertEqual([(w["key"], w["insert"]) for w in writes],
                         [({"user_id": U1, "company_id": CO_A}, True)])
        self.assertEqual(writes[0]["set"]["origin"], m.ORIGIN_USERS_MIRROR)

    def test_a_rerun_over_unchanged_users_writes_nothing(self):
        users = [user(U1), user(U2, role="cp")]
        rows = apply(m.plan_mirror(users, []), [])
        self.assertEqual(m.plan_mirror(users, rows), [])
        self.assertEqual(m.parity(users, rows), {"missing": 0, "stale": 0})

    def test_a_role_change_on_the_user_reaches_the_membership(self):
        rows = apply(m.plan_mirror([user(U1, role="pm")], []), [])
        writes = m.plan_mirror([user(U1, role="admin")], rows)
        self.assertEqual(len(writes), 1)
        self.assertFalse(writes[0]["insert"])
        self.assertEqual(apply(writes, rows)[0]["role"], "admin")

    def test_a_soft_delete_and_a_restore_flip_the_same_row(self):
        rows = apply(m.plan_mirror([user(U1)], []), [])
        rows = apply(m.plan_mirror([user(U1, is_deleted=True)], rows), rows)
        self.assertEqual([r["status"] for r in rows], [m.STATUS_REMOVED])
        rows = apply(m.plan_mirror([user(U1)], rows), rows)
        self.assertEqual([r["status"] for r in rows], [m.STATUS_ACTIVE])

    def test_a_company_change_ends_the_old_row_and_starts_the_new_one(self):
        rows = apply(m.plan_mirror([user(U1, company=CO_A)], []), [])
        rows = apply(m.plan_mirror([user(U1, company=CO_B)], rows), rows)
        self.assertEqual(sorted((r["company_id"], r["status"]) for r in rows),
                         [(CO_A, m.STATUS_REMOVED), (CO_B, m.STATUS_ACTIVE)])

    def test_a_user_gone_from_users_is_ended_never_deleted(self):
        # hard_delete_company removes the users documents themselves.
        rows = apply(m.plan_mirror([user(U1)], []), [])
        writes = m.plan_mirror([], rows)
        self.assertEqual(writes, [{"key": {"user_id": U1, "company_id": CO_A},
                                   "set": {"status": m.STATUS_REMOVED}, "insert": False}])

    def test_a_row_the_mirror_did_not_write_is_not_the_mirrors_to_end(self):
        # Stage 2 adds memberships of its own (an admin adding an existing
        # person to a second company). The users document does not imply them.
        theirs = {"user_id": U1, "company_id": CO_B, "role": "cp",
                  "status": m.STATUS_ACTIVE, "origin": "admin_add"}
        rows = apply(m.plan_mirror([user(U1)], [theirs]), [theirs])
        self.assertEqual(m.plan_mirror([user(U1)], rows), [])
        self.assertIn(theirs, rows)


class UpsertingCollection(AsyncFakeCollection):
    """The shared fake has no upsert; this is the Mongo behaviour the mirror uses."""

    async def update_one(self, flt, update, upsert=False, **kw):
        if upsert and not any(matches(d, flt) for d in self.docs):
            doc = {"_id": ObjectId(), **flt, **(update.get("$setOnInsert") or {}),
                   **(update.get("$set") or {})}
            self.docs.append(doc)
            self.writes.append(("upsert", doc["_id"]))
            return None
        return await super().update_one(flt, update, **kw)


def fake_db(users):
    db = AsyncFakeDB()
    db._c[m.COLLECTION] = UpsertingCollection(m.COLLECTION)
    db.users.docs.extend(copy.deepcopy(users))
    return db


class RunMembershipMirror(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def run_mirror(self, db):
        with patch.object(self.server, "db", db):
            return asyncio.run(self.server.run_membership_mirror())

    def test_backfill_then_a_rerun_that_writes_nothing(self):
        db = fake_db([user(U1), user(U2, role="pm", pm_access="full"),
                      user("6b0000000000000000000003", company=None)])
        first = self.run_mirror(db)
        self.assertEqual(first, {"inserted": 2, "updated": 0, "missing": 0, "stale": 0})
        self.assertEqual(len(db.users.writes), 0, "the users documents are only read")
        rows = db[m.COLLECTION].docs
        self.assertTrue(all(r.get("created_at") and r.get("updated_at") for r in rows))

        written = len(db[m.COLLECTION].writes)
        again = self.run_mirror(db)
        self.assertEqual(again, {"inserted": 0, "updated": 0, "missing": 0, "stale": 0})
        self.assertEqual(len(db[m.COLLECTION].writes), written)

    def test_a_write_that_does_not_land_is_reported_not_hidden(self):
        db = fake_db([user(U1)])

        async def dropped(*a, **k):
            return None
        db[m.COLLECTION].update_one = dropped
        with self.assertLogs(self.server.logger, level="ERROR") as logs:
            out = self.run_mirror(db)
        self.assertEqual(out["missing"], 1)
        self.assertIn("did not converge", "\n".join(logs.output))

    def test_it_never_raises(self):
        db = fake_db([user(U1)])

        def broken(*a, **k):
            raise RuntimeError("mongo down")
        db.users.find = broken
        out = self.run_mirror(db)
        self.assertEqual(out["inserted"], 0)


SERVER_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def _function(name):
    start = SERVER_SRC.index(f"\nasync def {name}(")
    end = re.search(r"\n(?:async )?def |\n@", SERVER_SRC[start + 1:])
    # startup_event is the last function in the file.
    return SERVER_SRC[start: start + 1 + end.start()] if end else SERVER_SRC[start:]


class Wiring(unittest.TestCase):

    def test_startup_builds_the_indexes_then_mirrors_after_the_pm_access_backfill(self):
        startup = _function("startup_event")
        pm = startup.index("await run_pm_access_startup_migration()")
        idx = startup.index("await ensure_membership_indexes()")
        mirror = startup.index("await run_membership_mirror()")
        self.assertLess(pm, idx)
        self.assertLess(idx, mirror)

    def test_it_reruns_hourly(self):
        self.assertRegex(SERVER_SRC, r"run_membership_mirror,\s*IntervalTrigger\(hours=1\)")

    def test_one_membership_per_person_and_company(self):
        self.assertRegex(_function("ensure_membership_indexes"),
                         r'keys=\[\("user_id", 1\), \("company_id", 1\)\],\s*'
                         r'name="memberships_by_user_company", unique=True')


class NothingReadsItYet(unittest.TestCase):
    """STAGE 1 CHANGES NOTHING A PERSON CAN DO OR SEE.

    Every use of the collection is in the two functions that build it. When
    stage 2 moves reads over, it changes this test on purpose.
    """

    def test_the_collection_is_used_only_by_the_mirror(self):
        allowed = _function("ensure_membership_indexes") + _function("run_membership_mirror")
        uses = [ln for ln in SERVER_SRC.splitlines()
                if re.search(r"memberships_lib\.|db\.memberships\b|[\"']memberships[\"']", ln)]
        stray = [ln.strip() for ln in uses
                 if ln not in allowed and "import memberships as memberships_lib" not in ln]
        self.assertEqual(stray, [])

    def test_no_other_backend_module_reads_it(self):
        hits = []
        for path in _BACKEND.rglob("*.py"):
            rel = path.relative_to(_BACKEND).as_posix()
            if rel.startswith(("tests/", "scripts/")) or rel in ("server.py", "lib/memberships.py"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"memberships_lib|lib\.memberships|import memberships|[\"']memberships[\"']",
                         text):
                hits.append(rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
