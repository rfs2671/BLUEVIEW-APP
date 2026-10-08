"""Owner portal: company admins and Deleted items (platform operator only).

Pinned here:
  * every new /owner route answers 404 to anyone who is not the platform
    operator -- a signed-in admin, and a missing or bad token alike;
  * add admin: promotes a user of this company, creates a new admin when the
    email has no account, refuses an account in another company;
  * change role and remove: refused when it would leave the company with no
    admin; every change writes one audit row;
  * Deleted items lists deleted companies, users and BOTH kinds of deleted
    project (legacy soft delete and admin-marked), with who and when;
  * restore brings back what was deleted in the same action (delete_batch_id)
    and the NFC tags a project's deletion closed, and refuses a child whose
    company is not live;
  * preview counts and deletes nothing; hard delete is reported disabled.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.pop("PLATFORM_GATES_ENFORCED", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bson import ObjectId  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import owner_portal  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO = ObjectId()
CO2 = ObjectId()
CID, CID2 = str(CO), str(CO2)
OP_ID = ObjectId()
A1, A2, PM1, OTHER = ObjectId(), ObjectId(), ObjectId(), ObjectId()
OPERATOR = {"id": str(OP_ID), "email": "ops@levelog.test", "role": "owner",
            "is_platform_operator": True}
ADMIN = {"id": str(A1), "email": "a1@acme.test", "role": "admin",
         "company_id": CID}
T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
STRONG = "Str0ng!Passw0rd#2026"


def run(coro):
    return asyncio.run(coro)


def _db(**extra):
    base = dict(
        companies=[{"_id": CO, "name": "ACME BUILDERS"},
                   {"_id": CO2, "name": "OTHER CO"}],
        users=[
            {"_id": OP_ID, "email": "ops@levelog.test", "name": "Operator",
             "role": "owner", "is_platform_operator": True},
            {"_id": A1, "email": "a1@acme.test", "name": "Ann Admin",
             "role": "admin", "company_id": CID},
            {"_id": PM1, "email": "pm@acme.test", "name": "Pat PM",
             "role": "pm", "company_id": CID},
            {"_id": OTHER, "email": "o@other.test", "name": "Oz",
             "role": "admin", "company_id": CID2},
        ],
    )
    base.update(extra)
    return FakeDb(**base)


def _audit(db, action):
    return [r for r in db.audit_logs.rows if r.get("action") == action]


def _err(ctx):
    return ctx.exception.status_code, ctx.exception.detail


class Gate404Test(unittest.TestCase):
    """Nobody but the operator learns these routes exist."""

    def _gate(self, who=None, raises=None):
        async def fake(**kw):
            if raises:
                raise raises
            return who
        with patch.object(server, "get_current_user", fake):
            return run(server.require_operator_404(request=None,
                                                   credentials=None))

    def test_operator_passes(self):
        self.assertIs(self._gate(OPERATOR), OPERATOR)

    def test_company_admin_gets_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._gate(ADMIN)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_legacy_owner_role_without_the_flag_gets_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._gate({"id": "x", "email": "x@x.test", "role": "owner"})
        self.assertEqual(ctx.exception.status_code, 404)

    def test_no_token_gets_404_not_401(self):
        with self.assertRaises(HTTPException) as ctx:
            self._gate(raises=HTTPException(status_code=401,
                                            detail="Not authenticated"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_every_new_route_carries_the_gate(self):
        want = {
            ("GET", "/api/owner/companies/{company_id}/users"),
            ("POST", "/api/owner/companies/{company_id}/admins"),
            ("PATCH", "/api/owner/companies/{company_id}/users/{user_id}/role"),
            ("DELETE", "/api/owner/companies/{company_id}/users/{user_id}"),
            ("GET", "/api/owner/deleted"),
            ("POST", "/api/owner/deleted/{kind}/{item_id}/restore"),
            ("GET", "/api/owner/deleted/{kind}/{item_id}/preview"),
        }
        found = set()
        for r in server.app.routes:
            methods = getattr(r, "methods", None) or set()
            for m in methods:
                if (m, getattr(r, "path", "")) in want:
                    calls = [d.call for d in r.dependant.dependencies]
                    self.assertIn(server.require_operator_404, calls,
                                  f"{m} {r.path} is missing the 404 gate")
                    found.add((m, r.path))
        self.assertEqual(found, want)


class CompanyUsersTest(unittest.TestCase):

    def test_lists_live_users_admins_first(self):
        db = _db()
        db.users.rows.append({"_id": ObjectId(), "email": "gone@acme.test",
                              "role": "admin", "company_id": CID,
                              "is_deleted": True})
        with patch.object(server, "db", db):
            out = run(server.owner_company_users(CID, operator=OPERATOR))
        self.assertEqual([u["email"] for u in out["users"]],
                         ["a1@acme.test", "pm@acme.test"])
        self.assertEqual(out["admin_count"], 1)
        self.assertNotIn("password", out["users"][0])
        self.assertEqual(out["company"]["name"], "ACME BUILDERS")

    def test_unknown_company_is_404(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_company_users(str(ObjectId()),
                                               operator=OPERATOR))
        self.assertEqual(ctx.exception.status_code, 404)


class AddAdminTest(unittest.TestCase):

    def test_promotes_a_user_of_this_company(self):
        db = _db()
        with patch.object(server, "db", db):
            out = run(server.owner_add_company_admin(
                CID, server.OwnerAddAdmin(email="PM@acme.test"),
                operator=OPERATOR))
        self.assertFalse(out["created"])
        pm = next(u for u in db.users.rows if u["_id"] == PM1)
        self.assertEqual(pm["role"], "admin")
        rows = _audit(db, "owner_admin_add")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["details"]["mode"], "promoted")
        self.assertEqual(rows[0]["details"]["from_role"], "pm")
        self.assertEqual(rows[0]["user_id"], str(OP_ID))

    def test_creates_a_new_admin_when_no_account(self):
        db = _db()
        with patch.object(server, "db", db):
            out = run(server.owner_add_company_admin(
                CID, server.OwnerAddAdmin(email="New@acme.test", name="Nia",
                                          password=STRONG),
                operator=OPERATOR))
        self.assertTrue(out["created"])
        new = next(u for u in db.users.rows if u.get("email") == "new@acme.test")
        self.assertEqual((new["role"], new["company_id"], new["account_status"]),
                         ("admin", CID, "approved"))
        self.assertNotEqual(new["password"], STRONG)
        self.assertEqual(_audit(db, "owner_admin_add")[0]["details"]["mode"],
                         "created")

    def test_new_account_needs_a_name(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_add_company_admin(
                    CID, server.OwnerAddAdmin(email="x@acme.test",
                                              password=STRONG),
                    operator=OPERATOR))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_weak_password_is_refused(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException):
                run(server.owner_add_company_admin(
                    CID, server.OwnerAddAdmin(email="x@acme.test", name="X",
                                              password="short"),
                    operator=OPERATOR))

    def test_account_in_another_company_is_refused(self):
        db = _db()
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_add_company_admin(
                    CID, server.OwnerAddAdmin(email="o@other.test"),
                    operator=OPERATOR))
        code, detail = _err(ctx)
        self.assertEqual((code, detail["code"]), (409, "OTHER_COMPANY"))
        self.assertEqual(_audit(db, "owner_admin_add"), [])

    def test_already_admin_is_refused(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_add_company_admin(
                    CID, server.OwnerAddAdmin(email="a1@acme.test"),
                    operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "ALREADY_ADMIN")

    def test_deleted_company_is_refused(self):
        db = _db()
        db.companies.rows[0]["is_deleted"] = True
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_add_company_admin(
                    CID, server.OwnerAddAdmin(email="pm@acme.test"),
                    operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "COMPANY_DELETED")


class RoleChangeAndRemoveTest(unittest.TestCase):

    def test_change_role_writes_audit(self):
        db = _db()
        with patch.object(server, "db", db):
            out = run(server.owner_change_user_role(
                CID, str(PM1), server.OwnerRoleChange(role="CP"),
                operator=OPERATOR))
        self.assertTrue(out["changed"])
        self.assertEqual(next(u for u in db.users.rows if u["_id"] == PM1)["role"], "cp")
        row = _audit(db, "owner_role_change")[0]
        self.assertEqual((row["details"]["from_role"], row["details"]["to_role"]),
                         ("pm", "cp"))

    def test_cannot_demote_the_last_admin(self):
        db = _db()
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_change_user_role(
                    CID, str(A1), server.OwnerRoleChange(role="pm"),
                    operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "LAST_ADMIN")
        self.assertEqual(next(u for u in db.users.rows if u["_id"] == A1)["role"], "admin")
        self.assertEqual(_audit(db, "owner_role_change"), [])

    def test_can_demote_when_another_admin_exists(self):
        db = _db()
        db.users.rows.append({"_id": A2, "email": "a2@acme.test",
                              "role": "admin", "company_id": CID})
        with patch.object(server, "db", db):
            out = run(server.owner_change_user_role(
                CID, str(A1), server.OwnerRoleChange(role="pm"),
                operator=OPERATOR))
        self.assertTrue(out["changed"])

    def test_role_must_be_assignable(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_change_user_role(
                    CID, str(PM1), server.OwnerRoleChange(role="owner"),
                    operator=OPERATOR))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_user_of_another_company_is_404(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_change_user_role(
                    CID, str(OTHER), server.OwnerRoleChange(role="pm"),
                    operator=OPERATOR))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cannot_remove_the_last_admin(self):
        db = _db()
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_remove_company_user(CID, str(A1),
                                                     operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "LAST_ADMIN")
        self.assertNotEqual(
            next(u for u in db.users.rows if u["_id"] == A1).get("is_deleted"), True)

    def test_remove_soft_deletes_with_who_and_batch(self):
        db = _db()
        with patch.object(server, "db", db):
            run(server.owner_remove_company_user(CID, str(PM1),
                                                 operator=OPERATOR))
        pm = next(u for u in db.users.rows if u["_id"] == PM1)
        self.assertTrue(pm["is_deleted"])
        self.assertEqual(pm["deleted_by"], str(OP_ID))
        self.assertTrue(pm["delete_batch_id"])
        self.assertEqual(len(_audit(db, "owner_user_remove")), 1)


def _deleted_db():
    batch = "b" * 32
    P_LEGACY, P_MARKED, U_GONE = ObjectId(), ObjectId(), ObjectId()
    D_CO = ObjectId()
    db = _db(
        projects=[
            {"_id": P_LEGACY, "name": "Old job", "address": "1 Main St",
             "company_id": CID, "is_deleted": True,
             "deleted_at": T0 - timedelta(days=30)},
            {"_id": P_MARKED, "name": "Marked job", "company_id": CID,
             "marked_for_deletion": True, "marked_by": str(A1),
             "marked_at": T0, "delete_batch_id": batch},
            {"_id": ObjectId(), "name": "Live job", "company_id": CID},
        ],
        nfc_tags=[
            {"_id": ObjectId(), "project_id": str(P_MARKED),
             "status": "project_closed", "closed_batch_id": batch},
            {"_id": ObjectId(), "project_id": str(P_MARKED),
             "status": "inactive"},
        ],
    )
    db.companies.rows.append({"_id": D_CO, "name": "GONE CO",
                              "is_deleted": True,
                              "deleted_at": T0 - timedelta(days=1)})
    db.users.rows.append({"_id": U_GONE, "email": "gone@acme.test",
                          "name": "Gus", "role": "pm", "company_id": CID,
                          "is_deleted": True, "deleted_by": str(OP_ID),
                          "deleted_at": T0 + timedelta(hours=1),
                          "deleted_user_ref": f"deleted_user:{U_GONE}",
                          "password": "hash"})
    return db, dict(legacy=P_LEGACY, marked=P_MARKED, user=U_GONE,
                    company=D_CO, batch=batch)


class DeletedItemsTest(unittest.TestCase):

    def test_lists_every_kind_with_who_and_when(self):
        db, ids = _deleted_db()
        with patch.object(server, "db", db):
            out = run(server.owner_deleted_items(operator=OPERATOR))
        by_id = {r["id"]: r for r in out["items"]}
        self.assertEqual(out["counts"], {"company": 1, "project": 2, "user": 1})
        self.assertEqual(by_id[str(ids["legacy"])]["state"], "deleted")
        self.assertEqual(by_id[str(ids["legacy"])]["name"], "Old job — 1 Main St")
        marked = by_id[str(ids["marked"])]
        self.assertEqual((marked["state"], marked["deleted_by_name"],
                          marked["company_name"]),
                         ("marked", "Ann Admin", "ACME BUILDERS"))
        user = by_id[str(ids["user"])]
        self.assertEqual(user["deleted_by_name"], "Operator")
        self.assertNotIn("password", user)
        self.assertFalse(user["hard_delete"]["enabled"])
        self.assertEqual(user["hard_delete"]["reason"],
                         "Pending delete-service fix")
        # Newest first.
        self.assertEqual(out["items"][0]["id"], str(ids["user"]))


class RestoreTest(unittest.TestCase):

    def test_restoring_a_marked_project_reopens_its_closed_tags(self):
        db, ids = _deleted_db()
        with patch.object(server, "db", db):
            out = run(server.owner_restore_deleted(
                "project", str(ids["marked"]), operator=OPERATOR))
        p = next(r for r in db.projects.rows if r["_id"] == ids["marked"])
        self.assertFalse(p["marked_for_deletion"])
        self.assertFalse(p["is_deleted"])
        for gone in ("marked_by", "marked_at", "delete_batch_id"):
            self.assertNotIn(gone, p)
        statuses = sorted(t["status"] for t in db.nfc_tags.rows)
        self.assertEqual(statuses, ["active", "inactive"])
        self.assertEqual(out["children"]["nfc_tags"], 1)
        row = _audit(db, "owner_restore")[0]
        self.assertEqual((row["user_id"], row["details"]["was"]),
                         (str(OP_ID), "marked"))

    def test_restore_brings_back_the_same_batch(self):
        db, ids = _deleted_db()
        # A user removed in the same action as the project.
        db.users.rows.append({"_id": ObjectId(), "email": "same@acme.test",
                              "company_id": CID, "role": "cp",
                              "is_deleted": True,
                              "delete_batch_id": ids["batch"]})
        with patch.object(server, "db", db):
            out = run(server.owner_restore_deleted(
                "project", str(ids["marked"]), operator=OPERATOR))
        same = next(u for u in db.users.rows if u.get("email") == "same@acme.test")
        self.assertFalse(same["is_deleted"])
        self.assertEqual(out["children"]["users"], 1)
        # A user deleted in a different action stays deleted.
        other = next(u for u in db.users.rows if u["_id"] == ids["user"])
        self.assertTrue(other["is_deleted"])

    def test_restoring_a_user_clears_the_deleted_fields(self):
        db, ids = _deleted_db()
        with patch.object(server, "db", db):
            run(server.owner_restore_deleted("user", str(ids["user"]),
                                             operator=OPERATOR))
        u = next(u for u in db.users.rows if u["_id"] == ids["user"])
        self.assertFalse(u["is_deleted"])
        for gone in ("deleted_at", "deleted_by", "deleted_user_ref"):
            self.assertNotIn(gone, u)
        self.assertEqual(u["restored_by"], str(OP_ID))

    def test_user_whose_email_is_taken_is_refused(self):
        db, ids = _deleted_db()
        db.users.rows.append({"_id": ObjectId(), "email": "gone@acme.test",
                              "company_id": CID, "role": "pm"})
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_restore_deleted("user", str(ids["user"]),
                                                 operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "EMAIL_IN_USE")

    def test_child_of_a_deleted_company_is_refused(self):
        db, ids = _deleted_db()
        db.companies.rows[0]["is_deleted"] = True
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_restore_deleted("project", str(ids["legacy"]),
                                                 operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "COMPANY_NOT_LIVE")

    def test_live_row_is_not_restored(self):
        db, _ = _deleted_db()
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_restore_deleted("user", str(PM1),
                                                 operator=OPERATOR))
        self.assertEqual(_err(ctx)[1]["code"], "NOT_DELETED")

    def test_unknown_kind_is_404(self):
        with patch.object(server, "db", _db()):
            with self.assertRaises(HTTPException) as ctx:
                run(server.owner_restore_deleted("worker", str(PM1),
                                                 operator=OPERATOR))
        self.assertEqual(ctx.exception.status_code, 404)


class PreviewTest(unittest.TestCase):

    def test_project_preview_counts_and_writes_nothing(self):
        db, ids = _deleted_db()
        pid = str(ids["legacy"])
        db.dob_logs.rows = [{"_id": ObjectId(), "project_id": pid}] * 3
        db.project_files.rows = [{"_id": ObjectId(), "project_id": pid}] * 2
        before = {n: [dict(r) for r in c.rows] for n, c in db._c.items()}
        with patch.object(server, "db", db):
            out = run(server.owner_preview_hard_delete(
                "project", pid, operator=OPERATOR))
        self.assertEqual(out["counts"]["dob_logs"], 3)
        self.assertEqual(out["r2_files"]["project_files"], 2)
        self.assertTrue(out["read_only"])
        self.assertEqual(out["hard_delete"],
                         {"enabled": False, "reason": "Pending delete-service fix"})
        after = {n: [dict(r) for r in c.rows] for n, c in db._c.items()
                 if n in before}
        self.assertEqual(after, before)
        self.assertEqual(db.audit_logs.rows, [])

    def test_user_preview_says_never_purged(self):
        db, ids = _deleted_db()
        with patch.object(server, "db", db):
            out = run(server.owner_preview_hard_delete(
                "user", str(ids["user"]), operator=OPERATOR))
        self.assertEqual(out["blocking"][0]["kind"], "never_purged")


class StampingTest(unittest.TestCase):

    def test_mark_user_deleted_stamps_who_and_a_batch(self):
        s = server._mark_user_deleted("u1", by="op", batch="bat")
        self.assertEqual((s["deleted_by"], s["delete_batch_id"]), ("op", "bat"))
        self.assertTrue(server._mark_user_deleted("u1")["delete_batch_id"])

    def test_leaves_no_admin(self):
        users = [{"_id": "a", "role": "admin"}, {"_id": "p", "role": "pm"},
                 {"_id": "x", "role": "admin", "is_deleted": True}]
        self.assertTrue(owner_portal.leaves_no_admin(users, "a"))
        self.assertTrue(owner_portal.leaves_no_admin(users, "a", "pm"))
        self.assertFalse(owner_portal.leaves_no_admin(users, "a", "admin"))
        self.assertFalse(owner_portal.leaves_no_admin(users, "p"))


if __name__ == "__main__":
    unittest.main()
