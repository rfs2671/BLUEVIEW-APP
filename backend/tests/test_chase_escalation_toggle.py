"""Per user: "Gets chase escalation DMs".

- An admin gets them by default; a PM doesn't; nobody else can.
- Only an admin changes it (PUT /admin/users/{id}/chase-escalation), for an
  admin or a PM of their own company (their own too); every change audited.
- The 4:00 escalation goes to exactly the people with it on; a PM on
  assigned jobs only gets it for those jobs.
- A role change drops a stored choice: the new role's default applies.
"""

from __future__ import annotations

import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests import test_whatsapp_chase as _chase  # noqa: E402

CO = "co_a"
ADMIN = {"_id": "u_admin", "id": "u_admin", "role": "admin", "company_id": CO,
         "account_status": "approved"}


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class TheRule(unittest.TestCase):

    def test_defaults_and_overrides(self):
        g = server.gets_chase_escalation
        self.assertTrue(g({"role": "admin"}))
        self.assertFalse(g({"role": "pm"}))
        self.assertFalse(g({"role": "pm", "pm_access": "full"}))
        self.assertTrue(g({"role": "pm", "chase_escalation_dms": True}))
        self.assertFalse(g({"role": "admin", "chase_escalation_dms": False}))
        for role in ("cp", "superintendent", "worker"):
            with self.subTest(role):
                self.assertFalse(g({"role": role, "chase_escalation_dms": True}))


class TheSwitch(unittest.TestCase):

    def setUp(self):
        self.db = FakeDb(users=[
            copy.deepcopy(ADMIN),
            {"_id": "u_pm", "role": "pm", "pm_access": "assigned", "company_id": CO},
            {"_id": "u_cp", "role": "cp", "company_id": CO},
            {"_id": "u_other", "role": "pm", "company_id": "co_b"}], audit_logs=[])

    def set(self, uid, on, actor=ADMIN):
        with patch.object(server, "db", self.db):
            return _run(server.set_user_chase_escalation(uid, server.ChaseEscalationBody(on=on), actor))

    def row(self, uid):
        return next(u for u in self.db.users.rows if u["_id"] == uid)

    def audits(self):
        return [(a["resource_id"], a["details"]["before"], a["details"]["after"], a["details"]["via"])
                for a in self.db.audit_logs.rows if a.get("action") == "user_chase_escalation_change"]

    def test_an_admin_turns_a_pm_on_and_off_audited(self):
        self.assertEqual(self.set("u_pm", True)["chase_escalation_dms"], True)
        self.assertIs(self.row("u_pm")["chase_escalation_dms"], True)
        self.set("u_pm", True)                                     # no change: no row
        self.set("u_pm", False)
        self.assertEqual(self.audits(), [("u_pm", False, True, "toggle"),
                                         ("u_pm", True, False, "toggle")])
        (a,) = [a for a in self.db.audit_logs.rows if a["details"]["after"] is True]
        self.assertEqual(a["user_id"], "u_admin")

    def test_an_admin_turns_their_own_off(self):
        self.set("u_admin", False)
        self.assertFalse(server.gets_chase_escalation(self.row("u_admin")))
        self.assertEqual(self.audits(), [("u_admin", True, False, "toggle")])

    def test_only_an_admin_or_a_pm_of_their_company(self):
        with patch.object(server, "db", self.db):
            for uid, code in (("u_cp", 422), ("u_other", 403), ("nobody", 404)):
                with self.subTest(uid):
                    with self.assertRaises(HTTPException) as e:
                        _run(server.set_user_chase_escalation(
                            uid, server.ChaseEscalationBody(on=True), ADMIN))
                    self.assertEqual(e.exception.status_code, code)
        self.assertEqual(self.audits(), [])

    def test_only_admins_change_it(self):
        import inspect
        dep = inspect.signature(server.set_user_chase_escalation).parameters["admin"].default.dependency
        self.assertIs(dep, server.get_user_admin)
        for pm in ({"role": "pm", "pm_access": "full"}, {"role": "pm"}):
            with self.assertRaises(HTTPException) as e:
                _run(server.get_user_admin(pm))
            self.assertEqual(e.exception.status_code, 403)

    def test_the_users_list_carries_it(self):
        import inspect
        self.assertIn('"chase_escalation_dms": 1', inspect.getsource(server.get_admin_users))
        self.assertIn("chase_escalation_dms", server.UserResponse.model_fields)


class ARoleChangeDropsTheChoice(unittest.TestCase):

    def test_users_screen(self):
        db = FakeDb(users=[copy.deepcopy(ADMIN),
                           {"_id": "u_pm", "role": "pm", "pm_access": "assigned", "company_id": CO,
                            "name": "P", "email": "p@example.com", "chase_escalation_dms": True}],
                    audit_logs=[])
        with patch.object(server, "db", db):
            _run(server.update_admin_user("u_pm", {"role": "cp"}, ADMIN))
        row = next(u for u in db.users.rows if u["_id"] == "u_pm")
        self.assertNotIn("chase_escalation_dms", row)
        (a,) = [a for a in db.audit_logs.rows if a.get("action") == "user_chase_escalation_change"]
        self.assertEqual((a["details"]["before"], a["details"]["after"], a["details"]["via"]),
                         (True, False, "role_change"))

    def test_owner_portal(self):
        from bson import ObjectId
        co, a1, pm = ObjectId(), ObjectId(), ObjectId()
        op = {"id": "op", "role": "owner", "is_platform_operator": True, "email": "ops@example.com"}
        db = FakeDb(companies=[{"_id": co, "name": "ACME"}],
                    users=[{"_id": a1, "role": "admin", "company_id": str(co), "email": "a@example.com"},
                           {"_id": pm, "role": "pm", "company_id": str(co), "email": "p@example.com",
                            "chase_escalation_dms": False}],
                    audit_logs=[])
        with patch.object(server, "db", db):
            _run(server.owner_change_user_role(str(co), str(pm), server.OwnerRoleChange(role="admin"),
                                               operator=op))
        row = next(u for u in db.users.rows if u["_id"] == pm)
        self.assertNotIn("chase_escalation_dms", row)
        self.assertTrue(server.gets_chase_escalation(row))         # an admin's default: on
        self.assertEqual([(a["details"]["before"], a["details"]["after"]) for a in db.audit_logs.rows
                          if a.get("action") == "user_chase_escalation_change"], [(False, True)])


class WhoTheEscalationGoesTo(_chase._Base):
    """The 4:00 DM in the chase tick (shadow mode: recorded, not sent)."""

    def user(self, uid):
        return next(u for u in self.db.users.rows if u["_id"] == uid)

    def test_admins_by_default_not_pms(self):
        _chase._item(self.db)
        self.day()
        (dm,) = self.rows("admin_dm")
        self.assertEqual(dm["to_user_ids"], ["u_ana"])

    def test_a_pm_turned_on_gets_it_and_an_admin_turned_off_does_not(self):
        self.user("u_pm").update(chase_escalation_dms=True, assigned_projects=["proj_a"])
        self.user("u_ana")["chase_escalation_dms"] = False
        _chase._item(self.db)
        self.day()
        (dm,) = self.rows("admin_dm")
        self.assertEqual(dm["to_user_ids"], ["u_pm"])
        self.assertEqual(dm["to"], ["Pat PM"])

    def test_an_assigned_pm_only_for_their_jobs(self):
        self.user("u_pm").update(chase_escalation_dms=True, assigned_projects=["proj_other"])
        _chase._item(self.db)
        self.day()
        (dm,) = self.rows("admin_dm")
        self.assertEqual(dm["to_user_ids"], ["u_ana"])

    def test_a_full_access_pm_for_every_job(self):
        self.user("u_pm").update(chase_escalation_dms=True, pm_access="full", assigned_projects=[])
        _chase._item(self.db)
        self.day()
        (dm,) = self.rows("admin_dm")
        self.assertEqual(sorted(dm["to_user_ids"]), ["u_ana", "u_pm"])

    def test_nobody_on_means_no_dm(self):
        self.user("u_ana")["chase_escalation_dms"] = False
        _chase._item(self.db)
        self.day()
        self.assertEqual(self.rows("admin_dm"), [])


if __name__ == "__main__":
    unittest.main()
