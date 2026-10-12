"""PM permission level, set by an admin when creating a PM, editable later:

- "Assigned jobs only" (default, pm_access "assigned"): adds subs, sets punch
  contacts and acts only on the jobs they're assigned to.
- "Same as admin" (pm_access "full"): everything an admin can do, on all jobs,
  except managing users/admins (and billing -- there is none yet).

Everywhere: the app's gates, WhatsApp DM actions, punch, chase settings.
Shown on the user's card; each change audited; only an admin changes it;
existing PMs migrate to "assigned".
"""

from __future__ import annotations

import asyncio
import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests import test_dm_actions as _dm  # noqa: E402

CO = "co_a"
MINE, THEIRS = "p_mine", "p_theirs"
ADMIN = {"_id": "u_admin", "id": "u_admin", "role": "admin", "company_id": CO,
         "account_status": "approved"}
PM_ASSIGNED = {"_id": "u_pma", "id": "u_pma", "role": "pm", "pm_access": "assigned",
               "company_id": CO, "assigned_projects": [MINE], "account_status": "approved"}
PM_LEGACY = {**PM_ASSIGNED, "_id": "u_pml", "id": "u_pml"}
PM_LEGACY.pop("pm_access")
PM_FULL = {**PM_ASSIGNED, "_id": "u_pmf", "id": "u_pmf", "pm_access": "full",
           "assigned_projects": []}


def _run(coro):
    return asyncio.run(coro)


def _refused(test, coro, code=403):
    with test.assertRaises(HTTPException) as e:
        _run(coro)
    test.assertEqual(e.exception.status_code, code)
    return e.exception


class TheLevel(unittest.TestCase):

    def test_read(self):
        self.assertEqual([server.pm_access_level(u) for u in
                          (PM_ASSIGNED, PM_LEGACY, PM_FULL, ADMIN, {"role": "cp", "pm_access": "full"})],
                         ["assigned", "assigned", "full", None, None])

    def test_only_the_two_values(self):
        self.assertEqual(server.clean_pm_access(" Full "), "full")
        for bad in ("admin", "", None, 1, "everything"):
            with self.subTest(bad):
                with self.assertRaises(HTTPException) as e:
                    server.clean_pm_access(bad)
                self.assertEqual(e.exception.status_code, 422)


class TheGates(unittest.TestCase):
    """App: a full PM passes the company-admin gate; never the user-admin one."""

    def test_company_admin_gate(self):
        # get_admin_user admits a full PM; get_admin_seat_user (platform-wide
        # and unscoped routes) does not -- see NotTheirCompanysToChange.
        self.assertTrue(server.is_company_admin(PM_FULL))
        self.assertFalse(server.is_company_admin(PM_ASSIGNED))
        self.assertFalse(server.is_company_admin(PM_LEGACY))
        self.assertEqual(_run(server.get_admin_user(PM_FULL)), PM_FULL)
        _refused(self, server.get_admin_user(PM_ASSIGNED))

    def test_users_and_admins_stay_with_an_admin(self):
        for pm in (PM_FULL, PM_ASSIGNED):
            with self.subTest(pm["pm_access"]):
                _refused(self, server.get_user_admin(pm))
                self.assertFalse(server.holds_admin_seat(pm))
        self.assertTrue(server.holds_admin_seat(ADMIN))

    def test_approving_an_account_is_user_management(self):
        import inspect
        sig = inspect.signature(server.admin_approve_user)
        self.assertIs(sig.parameters["current_user"].default.dependency, server.get_user_admin)
        sig = inspect.signature(server.create_admin_user)
        self.assertIs(sig.parameters["admin"].default.dependency, server.get_user_admin)
        sig = inspect.signature(server.update_admin_user)
        self.assertIs(sig.parameters["admin"].default.dependency, server.get_user_admin)


class TheJobs(unittest.TestCase):
    """Assigned: their jobs only. Full: every job of the company."""

    def test_project_access(self):
        mine, theirs = {"company_id": CO}, {"company_id": CO}
        self.assertTrue(server.project_access_ok(mine, MINE, PM_ASSIGNED))
        self.assertFalse(server.project_access_ok(theirs, THEIRS, PM_ASSIGNED))
        self.assertFalse(server.project_access_ok(theirs, THEIRS, PM_LEGACY))
        self.assertTrue(server.project_access_ok(theirs, THEIRS, PM_FULL))
        # The role arrives off a Mongo document: " PM " is a PM.
        self.assertFalse(server.project_access_ok(theirs, THEIRS, {**PM_ASSIGNED, "role": " PM "}))
        self.assertTrue(server.project_access_ok(theirs, THEIRS, {**PM_FULL, "role": " PM "}))
        # Never another company's.
        self.assertFalse(server.project_access_ok({"company_id": "co_b"}, "p_b", PM_FULL))

    def _update(self, user, body):
        db = FakeDb(projects=[{"_id": MINE, "company_id": CO, "name": "Mine",
                               "trade_assignments": []}])
        with patch.object(server, "db", db):
            return _run(server.update_project(MINE, server.ProjectUpdate(**body), user)), db

    def test_an_assigned_pm_changes_the_subs_and_nothing_else(self):
        roster = [{"id": "t1", "company": "Power Direct", "trade": "Electrical"}]
        try:
            self._update(PM_ASSIGNED, {"trade_assignments": roster})
        except HTTPException as e:          # anything but the role gate is fine here
            self.assertNotEqual(e.status_code, 403, e.detail)
        with self.assertRaises(HTTPException) as ctx:
            self._update(PM_ASSIGNED, {"name": "Renamed"})
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("subs only", ctx.exception.detail)

    def test_a_full_pm_changes_the_job(self):
        try:
            self._update(PM_FULL, {"name": "Renamed"})
        except HTTPException as e:
            self.assertNotEqual(e.status_code, 403, e.detail)


class TheUsersScreen(unittest.TestCase):
    """Set when an admin creates a PM; edited later; each change audited."""

    def setUp(self):
        self.db = FakeDb(users=[copy.deepcopy(ADMIN), copy.deepcopy(PM_ASSIGNED),
                                {"_id": "u_cp", "id": "u_cp", "role": "cp", "company_id": CO,
                                 "name": "C", "email": "c@example.com"}],
                         audit_logs=[])
        for u in self.db.users.rows:
            u.setdefault("name", u["_id"]); u.setdefault("email", f"{u['_id']}@example.com")

    def update(self, uid, body, actor=ADMIN):
        with patch.object(server, "db", self.db):
            return _run(server.update_admin_user(uid, body, actor))

    def row(self, uid):
        return next(u for u in self.db.users.rows if u["_id"] == uid)

    def changes(self):
        return [a for a in self.db.audit_logs.rows if a.get("action") == "user_pm_access_change"]

    def test_an_admin_changes_it_and_it_is_audited(self):
        out = self.update("u_pma", {"pm_access": "full"})
        self.assertEqual(out.pm_access, "full")
        self.assertEqual(self.row("u_pma")["pm_access"], "full")
        (a,) = self.changes()
        self.assertEqual((a["user_id"], a["resource_id"], a["details"]),
                         ("u_admin", "u_pma", {"before": "assigned", "after": "full"}))
        self.update("u_pma", {"pm_access": "assigned"})
        self.assertEqual(self.changes()[-1]["details"], {"before": "full", "after": "assigned"})

    def test_saving_without_a_change_is_not_a_change(self):
        self.update("u_pma", {"name": "Dana", "role": "pm", "pm_access": "assigned"})
        self.assertEqual(self.changes(), [])

    def test_a_bad_value_or_another_role(self):
        with patch.object(server, "db", self.db):
            _refused(self, server.update_admin_user("u_pma", {"pm_access": "admin"}, ADMIN), 422)
            _refused(self, server.update_admin_user("u_cp", {"pm_access": "full"}, ADMIN), 422)
        self.assertEqual(self.row("u_pma")["pm_access"], "assigned")

    def test_made_a_pm_starts_at_assigned_and_leaving_pm_drops_it(self):
        self.update("u_cp", {"role": "pm"})
        self.assertEqual(self.row("u_cp")["pm_access"], "assigned")
        self.update("u_pma", {"role": "cp"})
        self.assertNotIn("pm_access", self.row("u_pma"))

    def test_create(self):
        async def ok_contact(*a, **k):
            return None
        with patch.object(server, "db", self.db):
            u = _run(server.create_admin_user(server.UserCreate(
                name="New PM", email="newpm@example.com", password="Str0ng!Passw0rd#", role="pm",
                pm_access="full"), ADMIN))
            self.assertEqual(u.pm_access, "full")
            u = _run(server.create_admin_user(server.UserCreate(
                name="Default PM", email="defpm@example.com", password="Str0ng!Passw0rd#", role="pm"), ADMIN))
            self.assertEqual(u.pm_access, "assigned")
            _refused(self, server.create_admin_user(server.UserCreate(
                name="A CP", email="cp2@example.com", password="Str0ng!Passw0rd#", role="cp",
                pm_access="full"), ADMIN), 422)

    def test_the_list_carries_it(self):
        import inspect
        self.assertIn('"pm_access": 1', inspect.getsource(server.get_admin_users))   # the list projection
        self.assertIn("pm_access", server.UserResponse.model_fields)


class NotTheirCompanysToChange(unittest.TestCase):
    """Codex on #769 (P1): get_admin_user admits a full PM, so routes that are
    platform-wide, or that read/write a record by id with no company scope,
    must not ride on it."""

    SEAT_ROUTES = ("admin_list_feature_flags", "admin_create_feature_flag",
                   "admin_update_feature_flag", "admin_delete_feature_flag",
                   "admin_sentry_test", "scan_expiring_certifications",
                   "get_cs_registration", "delete_cs_registration",
                   "resolve_compliance_alert",
                   "list_failed_plan_index_jobs", "register_dropbox_webhook")

    def test_platform_wide_and_unscoped_routes_need_the_admin_seat(self):
        import inspect
        for name in self.SEAT_ROUTES:
            with self.subTest(name):
                deps = [p.default.dependency for p in inspect.signature(getattr(server, name)).parameters.values()
                        if hasattr(p.default, "dependency")]
                self.assertIn(server.get_admin_seat_user, deps)
        _refused(self, server.get_admin_seat_user(PM_FULL))
        self.assertEqual(_run(server.get_admin_seat_user(ADMIN)), ADMIN)

    def _world(self):
        return FakeDb(
            projects=[{"_id": "p_b", "company_id": "co_b"}],
            checklists=[{"_id": "cl_b", "company_id": "co_b", "title": "B's", "items": []},
                        {"_id": "cl_a", "company_id": CO, "title": "Ours", "items": []}],
            checklist_assignments=[],
            safety_staff_registrations=[{"_id": "ss_b", "company_id": "co_b", "name": "B"}],
            site_devices=[{"_id": "sd_b", "company_id": "co_b", "device_name": "B gate"},
                          {"_id": "sd_old", "project_id": "p_b", "device_name": "legacy"},
                          {"_id": "sd_a", "company_id": CO, "device_name": "Our gate"}],
            users=[])

    def test_another_companys_checklist_or_device_is_not_found(self):
        db = self._world()
        with patch.object(server, "db", db):
            for who in (ADMIN, PM_FULL):
                with self.subTest(who["role"]):
                    for call in (lambda: server.get_checklist("cl_b", who),
                                 lambda: server.update_checklist("cl_b", {"title": "x"}, who),
                                 lambda: server.delete_checklist("cl_b", who),
                                 lambda: server.get_checklist_assignments("cl_b", who),
                                 lambda: server.get_site_device("sd_b", who),
                                 lambda: server.get_site_device("sd_old", who),
                                 lambda: server.update_site_device("sd_b", {"is_active": False}, who),
                                 lambda: server.delete_site_device("sd_b", who),
                                 lambda: server.update_safety_staff("ss_b", {"name": "x"}, who),
                                 lambda: server.delete_safety_staff("ss_b", who)):
                        _refused(self, call(), 404)
            self.assertEqual(_run(server.get_checklist("cl_a", PM_FULL))["title"], "Ours")
            self.assertEqual(_run(server.get_site_device("sd_a", PM_FULL))["device_name"], "Our gate")
        b = next(r for r in db.checklists.rows if r["_id"] == "cl_b")
        self.assertEqual((b["title"], b.get("is_deleted")), ("B's", None))
        self.assertNotIn("is_active", next(r for r in db.site_devices.rows if r["_id"] == "sd_b"))


class EveryRoleWriterKeepsTheLevel(unittest.TestCase):
    """Codex on #769 (P2): the owner portal changes roles too. A stored level
    never outlives the PM role, and coming back to PM starts at assigned."""

    def test_the_rule(self):
        f = server.pm_access_on_role_change
        self.assertEqual(f({"role": "cp", "pm_access": "full"}, "pm"), ({"pm_access": "assigned"}, {}))
        self.assertEqual(f({"role": "pm"}, "pm"), ({"pm_access": "assigned"}, {}))
        self.assertEqual(f(PM_FULL, "pm"), ({}, {}))
        self.assertEqual(f(PM_FULL, "cp"), ({}, {"pm_access": ""}))
        self.assertEqual(f({"role": "cp"}, "admin"), ({}, {}))

    def test_owner_portal_pm_to_cp_and_back(self):
        from bson import ObjectId
        co, a1, pm = ObjectId(), ObjectId(), ObjectId()
        op = {"id": "op", "role": "owner", "is_platform_operator": True, "email": "ops@example.com"}
        db = FakeDb(companies=[{"_id": co, "name": "ACME"}],
                    users=[{"_id": a1, "role": "admin", "company_id": str(co), "email": "a@example.com"},
                           {"_id": pm, "role": "pm", "pm_access": "full", "company_id": str(co),
                            "email": "p@example.com"}],
                    audit_logs=[])
        row = lambda: next(u for u in db.users.rows if u["_id"] == pm)
        changes = lambda: [(a["details"]["before"], a["details"]["after"]) for a in db.audit_logs.rows
                           if a.get("action") == "user_pm_access_change"]
        with patch.object(server, "db", db):
            _run(server.owner_change_user_role(str(co), str(pm), server.OwnerRoleChange(role="cp"),
                                               operator=op))
            self.assertNotIn("pm_access", row())
            _run(server.owner_change_user_role(str(co), str(pm), server.OwnerRoleChange(role="pm"),
                                               operator=op))
        self.assertEqual(row()["pm_access"], "assigned")                 # not the old "full"
        self.assertEqual(changes(), [("full", None), (None, "assigned")])


class TheMigration(unittest.TestCase):

    def test_existing_pms_get_assigned_jobs_only(self):
        db = FakeDb(users=[copy.deepcopy(PM_LEGACY), copy.deepcopy(PM_FULL), copy.deepcopy(ADMIN)])
        with patch.object(server, "db", db):
            _run(server.run_pm_access_startup_migration())
            _run(server.run_pm_access_startup_migration())          # idempotent
        by = {u["_id"]: u.get("pm_access") for u in db.users.rows}
        self.assertEqual(by, {"u_pml": "assigned", "u_pmf": "full", "u_admin": None})


class TheWhatsAppDm(unittest.TestCase):
    """DM actions for both levels (the #768 harness, as a PM). Only the
    harness is borrowed, not Chat's tests."""

    setUp = _dm.Chat.setUp
    talk = _dm.Chat.talk
    audits = _dm.Chat.audits
    p588 = _dm.Chat.p588
    settings = _dm.Chat.settings

    def as_pm(self, level):
        user = {**(self.ident.get("user") or {}), "role": "pm", "pm_access": level}
        return {**self.ident, "role": "pm", "user": user}

    def test_assigned_pm_puts_a_sub_on_their_job_and_undoes_it(self):
        pm = self.as_pm("assigned")
        ask, done = self.talk("put power direct on 588 they're the electrician", "yes", ident=pm)
        self.assertEqual(done, "Done — Power Direct is on 588 Thomas St for Electrical.")
        self.assertEqual(self.talk("never mind", ident=pm), ["Undone — Power Direct is off 588 Thomas St."])

    def test_assigned_pm_sets_a_punch_contact(self):
        pm = self.as_pm("assigned")
        (ask,) = self.talk("punch contact for arkon is chris", ident=pm)
        self.assertEqual(ask, "Send Arkon Drywall's punch lists at 588 Thomas St to Chris Lopez?")
        self.talk("yes", ident=pm)
        self.assertIn("m_cl", self.settings()["punch_contacts"].values())
        self.assertEqual(self.talk("undo", ident=pm),
                         ["Undone — 588 Thomas St's punch contact is back the way it was."])
        self.assertNotIn("m_cl", (self.settings().get("punch_contacts") or {}).values())

    def test_assigned_pm_no_job_no_settings(self):
        pm = self.as_pm("assigned")
        no = ["Only a company admin can do that. I can add people, subs and punch contacts for you."]
        self.assertEqual(self.talk("add 9 menahan", ident=pm), no)
        self.assertEqual(self.talk("stop bugging people on weekends at 588", ident=pm), no)
        self.assertEqual(self.talk("start sending punch lists for real at 588", ident=pm), no)
        self.assertEqual(self.audits(), [])

    def test_full_pm_does_what_an_admin_does(self):
        pm = self.as_pm("full")
        found, done = self.talk("add 9 menahan", "yes", ident=pm)
        self.assertEqual(done, "Done — 9 Menahan St is set up. I'll start watching DOB and DOT for it.")
        self.settings()["chase_weekends"] = True
        ask, done = self.talk("stop bugging people on weekends at 588", "yes", ident=pm)
        self.assertEqual(done, "Done — no weekend reminders at 588 Thomas St.")
        ask, done = self.talk("start sending punch lists for real at 588", "588 thomas st", ident=pm)
        self.assertEqual(done, "Done — punch lists at 588 Thomas St now really go out.")

    def test_dm_scoping_follows_the_level(self):
        self.assertTrue(server._dm_is_admin(self.as_pm("full")))
        self.assertFalse(server._dm_is_admin(self.as_pm("assigned")))
        self.assertEqual(server._DM_PM_ACTIONS, ("add_person", "add_sub", "set_punch_contact"))


if __name__ == "__main__":
    unittest.main()
