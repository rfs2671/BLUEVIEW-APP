"""A CS registration exists or it does not. There is no switch.

OPERATOR'S RULING, 2026-10-08:

  * Once a superintendent is assigned to a project he is its superintendent
    until he is assigned elsewhere -- meaning until User Management changes his
    assignment. There is no "assigned but switched off" state; `is_active` is
    neither read nor written.
  * Assigning creates the registration; unassigning ENDS it.
  * An ended registration stays on the record for the period it covered: a
    filed sheet from last month must still attribute correctly.
  * Assigning him to a SECOND project does not end the first. Two live
    registrations is exactly the state the one-job conflict alert flags.
  * Carried from the earlier ruling: nothing may leave a project whose CS log
    is ON with no live registration linked to an account.

These call the real handlers against a small in-memory database. Tenancy is
stubbed (`_cs_registration_under_admin` returns the row) because it is pinned
in test_a_registration_belongs_to_one_company.py and is not what this file is
about.
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from fastapi import HTTPException  # noqa: E402

ADMIN = {"id": "admin1", "role": "admin", "company_id": "c1"}
P588 = "p588"
P12 = "p12"
MICHAEL = "u-michael"
SECOND = "u-second"


def _match(doc, q):
    for k, v in (q or {}).items():
        got = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and got == v["$ne"]:
                return False
            if "$in" in v and got not in v["$in"]:
                return False
            continue
        if got != v:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(r) for r in self._rows]


class _Res:
    def __init__(self, n=0, inserted_id=None):
        self.matched_count = self.modified_count = n
        self.inserted_id = inserted_id


class _Coll:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]

    def find(self, q=None, *a, **k):
        return _Cursor([r for r in self.rows if _match(r, q)])

    async def find_one(self, q=None, *a, **k):
        for r in self.rows:
            if _match(r, q):
                return copy.deepcopy(r)
        return None

    async def count_documents(self, q=None, *a, **k):
        return len([r for r in self.rows if _match(r, q)])

    async def insert_one(self, doc):
        row = dict(doc)
        row.setdefault("_id", f"new{len(self.rows)}")
        self.rows.append(row)
        return _Res(1, row["_id"])

    async def update_one(self, q, u, **k):
        for r in self.rows:
            if _match(r, q):
                r.update(u.get("$set") or {})
                return _Res(1)
        return _Res(0)

    async def update_many(self, q, u, **k):
        n = 0
        for r in self.rows:
            if _match(r, q):
                r.update(u.get("$set") or {})
                n += 1
        return _Res(n)


class _DB:
    def __init__(self, regs=(), log_on=(P588,)):
        self.cs_registrations = _Coll(regs)
        self.projects = _Coll([
            {"_id": P588, "name": "588 Thomas", "company_id": "c1",
             "superintendent_log_active": P588 in log_on},
            {"_id": P12, "name": "12 Vestry", "company_id": "c1",
             "superintendent_log_active": P12 in log_on},
        ])
        self.compliance_alerts = _Coll()


def _reg(**over):
    row = {"_id": "r1", "project_id": P588, "full_name": "Michael Cespedes",
           "license_number": "32299", "license_number_normalized": "32299",
           "user_id": MICHAEL, "company_id": "c1", "is_deleted": False,
           "created_at": "2026-09-01T12:13:32"}
    row.update(over)
    return row


def _row(db, rid):
    return next(r for r in db.cs_registrations.rows if r["_id"] == rid)


class _Fixture(unittest.TestCase):
    def run_with(self, db, coro_fn):
        async def _audit(*a, **k):
            return None

        async def _under_admin(registration_id, admin):
            row = await db.cs_registrations.find_one({"_id": registration_id})
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            return row

        async def _link(user_id=None, registration=None, admin=None):
            return str(user_id).strip() or None if user_id else None

        with patch.object(S, "db", db), \
             patch.object(S, "to_query_id", lambda x: x), \
             patch.object(S, "audit_log", _audit), \
             patch.object(S, "get_user_company_id", lambda u: (u or {}).get("company_id")), \
             patch.object(S, "_cs_registration_under_admin", _under_admin), \
             patch.object(S, "_validated_cs_account_link", _link):
            return asyncio.run(coro_fn())

    def register(self, db, project_id, user_id, name="Michael Cespedes",
                 number="32299"):
        project = next(p for p in db.projects.rows if p["_id"] == project_id)
        return self.run_with(db, lambda: S._register_cs_on_project(
            project=project, project_id=project_id, full_name=name,
            license_number=number, admin=ADMIN, user_id=user_id))


class AssigningCreatesItAndReplacingEndsThePredecessor(_Fixture):

    def test_a_new_registration_carries_no_switch(self):
        db = _DB([], log_on=())
        out = self.register(db, P588, MICHAEL)
        row = db.cs_registrations.rows[-1]
        self.assertNotIn("is_active", row)
        self.assertNotIn("is_active", out)
        self.assertIsNone(row.get("ended_at"))

    def test_registering_his_replacement_ENDS_him_and_keeps_the_row(self):
        db = _DB([_reg()])
        self.register(db, P588, SECOND, name="Second Super", number="44444")
        old = _row(db, "r1")
        self.assertTrue(old.get("ended_at"))
        self.assertEqual(old.get("ended_reason"), "superseded")
        self.assertIsNot(old.get("is_deleted"), True)
        live = [r for r in db.cs_registrations.rows if not r.get("ended_at")]
        self.assertEqual([r["user_id"] for r in live], [SECOND])


class ASecondProjectEndsNothing(_Fixture):
    """"Assigning him to a second project does NOT end the first. Two live
    registrations is exactly the state the one-job conflict alert exists to
    flag." -- the operator, 2026-10-08."""

    def test_both_stay_live_and_the_alert_fires(self):
        db = _DB([_reg()])
        out = self.register(db, P12, MICHAEL)
        self.assertIsNone(_row(db, "r1").get("ended_at"))
        live = {r["project_id"] for r in db.cs_registrations.rows
                if not r.get("ended_at")}
        self.assertEqual(live, {P588, P12})
        self.assertTrue(out["conflict_warning"])
        self.assertEqual(
            [a["alert_type"] for a in db.compliance_alerts.rows],
            ["cs_one_job_conflict"])

    def test_an_ENDED_registration_elsewhere_is_no_conflict(self):
        db = _DB([_reg(ended_at="2026-09-20T00:00:00")], log_on=())
        out = self.register(db, P12, MICHAEL)
        self.assertIsNone(out["conflict_warning"])
        self.assertEqual(db.compliance_alerts.rows, [])

    def test_the_old_switch_off_does_not_hide_a_conflict(self):
        """`is_active: False` with no end is live -- so it IS a conflict."""
        db = _DB([_reg(is_active=False)])
        out = self.register(db, P12, MICHAEL)
        self.assertTrue(out["conflict_warning"])


class NothingLeavesALiveLogWithNobodyToFileIt(_Fixture):
    """The CS log on 588 is ON. Every way of removing its only linked
    registration is refused with 409 CS_LOG_IS_ON, and the refusal writes
    nothing. The remedy the message names -- assign the replacement first --
    works, because a linked replacement supersedes in the same act."""

    def assertRefusedUntouched(self, db, call):
        before = copy.deepcopy(db.cs_registrations.rows)
        with self.assertRaises(HTTPException) as cm:
            self.run_with(db, call)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], "CS_LOG_IS_ON")
        self.assertIn("User Management", cm.exception.detail["message"])
        self.assertEqual(db.cs_registrations.rows, before,
                         "a refused change still wrote")

    def test_the_admin_delete(self):
        db = _DB([_reg()])
        self.assertRefusedUntouched(
            db, lambda: S.delete_cs_registration("r1", admin=ADMIN))

    def test_unlinking_it(self):
        db = _DB([_reg()])
        body = S.CSRegistrationUpdate(user_id=None)
        self.assertRefusedUntouched(
            db, lambda: S.update_cs_registration("r1", body, admin=ADMIN))

    def test_replacing_it_with_one_that_names_no_account(self):
        db = _DB([_reg()])
        project = db.projects.rows[0]
        self.assertRefusedUntouched(db, lambda: S._register_cs_on_project(
            project=project, project_id=P588, full_name="Nobody",
            license_number="55555", admin=ADMIN, user_id=None))

    def test_replacing_it_with_a_linked_one_is_allowed(self):
        db = _DB([_reg()])
        self.register(db, P588, SECOND, name="Second Super", number="44444")
        self.assertTrue(_row(db, "r1").get("ended_at"))

    def test_with_the_log_OFF_the_delete_ends_it(self):
        db = _DB([_reg()], log_on=())
        out = self.run_with(db, lambda: S.delete_cs_registration("r1", admin=ADMIN))
        self.assertEqual(out["message"], "CS registration ended")
        row = _row(db, "r1")
        self.assertEqual(row.get("ended_reason"), "removed")
        self.assertIsNot(row.get("is_deleted"), True)

    def test_a_second_linked_registration_keeps_the_project_covered(self):
        db = _DB([_reg(), _reg(_id="r2", user_id=SECOND)])
        self.run_with(db, lambda: S.delete_cs_registration("r1", admin=ADMIN))
        self.assertTrue(_row(db, "r1").get("ended_at"))


class AnEndedRegistrationIsHistory(_Fixture):
    """Its name, number and link are what sheets filed while it stood are
    attributed against. Editing one would rewrite what those sheets say."""

    def test_it_cannot_be_edited(self):
        db = _DB([_reg(ended_at="2026-09-20T00:00:00")], log_on=())
        body = S.CSRegistrationUpdate(full_name="Rewritten")
        with self.assertRaises(HTTPException) as cm:
            self.run_with(db, lambda: S.update_cs_registration("r1", body, admin=ADMIN))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(_row(db, "r1")["full_name"], "Michael Cespedes")

    def test_deleting_it_again_changes_nothing(self):
        db = _DB([_reg(ended_at="2026-09-20T00:00:00")], log_on=())
        out = self.run_with(db, lambda: S.delete_cs_registration("r1", admin=ADMIN))
        self.assertEqual(out["message"], "CS registration already ended")
        self.assertEqual(_row(db, "r1")["ended_at"], "2026-09-20T00:00:00")

    def test_the_put_body_has_no_switch(self):
        self.assertNotIn("is_active", S.CSRegistrationUpdate.model_fields)


if __name__ == "__main__":
    unittest.main(verbosity=2)
