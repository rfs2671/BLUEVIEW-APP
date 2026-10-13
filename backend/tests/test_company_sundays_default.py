"""Company setting "Default: chase on Sundays" (on by default).

Orthodox GCs work Sundays, so a new job chases on Sundays unless the
company says otherwise. New jobs take the company's default when they are
created (saved on the job, so changing the default later leaves them). Jobs
that already exist keep what they have today (migration 0d, once). Admins
see and change it in Company settings; audited.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_chase  # noqa: E402
from tests.test_whatsapp_attention import ADMIN, ADMIN_B, CO_A, PM, _run  # noqa: E402
from tests.test_whatsapp_chase import _db  # noqa: E402


def _row(db, pid):
    for r in db.notification_preferences.rows:
        if r.get("project_id") == pid and r.get("scope") == "project":
            return r.get("whatsapp_project") or {}
    return None


class TheSetting(unittest.TestCase):

    def setUp(self):
        self.db = _db()

    def test_on_by_default_and_admin_changes_it_audited(self):
        with patch.object(server, "db", self.db):
            self.assertEqual(_run(server.get_company_whatsapp_settings(ADMIN)),
                             {"chase_sundays_default": True})
            out = _run(server.patch_company_whatsapp_settings({"chase_sundays_default": False}, ADMIN))
            self.assertEqual(out, {"chase_sundays_default": False})
            self.assertEqual(_run(server.get_company_whatsapp_settings(ADMIN)),
                             {"chase_sundays_default": False})
            # Another company's admin sees its own default, not ours.
            self.assertEqual(_run(server.get_company_whatsapp_settings(ADMIN_B)),
                             {"chase_sundays_default": True})
        (a,) = [a for a in self.db.audit_logs.rows if a["action"] == "whatsapp_company_settings"]
        self.assertEqual((a["details"]["before"], a["details"]["after"]),
                         ({"chase_sundays_default": True}, {"chase_sundays_default": False}))

    def test_admins_only_and_bools_only(self):
        with patch.object(server, "db", self.db):
            for call in (lambda: server.get_company_whatsapp_settings(PM),
                         lambda: server.patch_company_whatsapp_settings(
                             {"chase_sundays_default": False}, PM)):
                with self.assertRaises(HTTPException) as e:
                    _run(call())
                self.assertEqual(e.exception.status_code, 403)
            for bad in ({}, {"chase_sundays_default": "no"}, {"chase_sundays": False}):
                with self.assertRaises(HTTPException) as e:
                    _run(server.patch_company_whatsapp_settings(bad, ADMIN))
                self.assertEqual(e.exception.status_code, 422)


class NewJobs(unittest.TestCase):

    def setUp(self):
        self.db = _db()

    def settings(self, pid):
        with patch.object(server, "db", self.db):
            return _run(server._whatsapp_project_settings(pid))

    def create(self, name):
        admin = {**ADMIN, "id": ADMIN.get("id") or ADMIN.get("_id"), "company_id": CO_A}
        with patch.object(server, "db", self.db), \
                patch.object(server, "run_dob_sync_for_project", lambda *a, **k: None, create=True):
            made = _run(server.create_project(server.ProjectCreate(name=name, address=f"{name}, Brooklyn, NY"),
                                              admin=admin))
        return str(getattr(made, "id", None) or (made or {}).get("id"))

    def test_a_new_job_chases_on_sundays_by_default(self):
        pid = self.create("9 Menahan St")
        self.assertIs(_row(self.db, pid)[wa_chase.SUNDAYS_OFF], False)       # saved on the job
        self.assertIs(self.settings(pid)[wa_chase.SUNDAYS_OFF], False)
        self.assertIs(self.settings(pid)[wa_chase.SHABBOS_OFF], True)

    def test_a_new_job_follows_the_company_default_off(self):
        with patch.object(server, "db", self.db):
            _run(server.patch_company_whatsapp_settings({"chase_sundays_default": False}, ADMIN))
        pid = self.create("12 Penn St")
        self.assertIs(self.settings(pid)[wa_chase.SUNDAYS_OFF], True)

    def test_changing_the_default_later_leaves_jobs_as_they_are(self):
        pid = self.create("9 Menahan St")
        with patch.object(server, "db", self.db):
            _run(server.patch_company_whatsapp_settings({"chase_sundays_default": False}, ADMIN))
        self.assertIs(self.settings(pid)[wa_chase.SUNDAYS_OFF], False)

    def test_a_job_with_nothing_saved_reads_the_company_default(self):
        # e.g. a job made by onboarding, not create_project.
        self.assertIs(self.settings("proj_a")[wa_chase.SUNDAYS_OFF], False)
        with patch.object(server, "db", self.db):
            _run(server.patch_company_whatsapp_settings({"chase_sundays_default": False}, ADMIN))
        self.assertIs(self.settings("proj_a")[wa_chase.SUNDAYS_OFF], True)

    def test_the_chase_follows_it(self):
        from datetime import datetime, timezone
        from lib import shabbos
        sun = datetime(2026, 12, 20, 12, 35, tzinfo=shabbos.NY).astimezone(timezone.utc)
        self.assertIsNone(wa_chase.quiet(sun, self.settings("proj_a")))
        with patch.object(server, "db", self.db):
            _run(server.patch_company_whatsapp_settings({"chase_sundays_default": False}, ADMIN))
        self.assertEqual(wa_chase.quiet(sun, self.settings("proj_a")), "sunday")


class ExistingJobsKeepTheirValue(unittest.TestCase):
    """Migration 0d: every job that exists keeps the Sundays it has today."""

    def setUp(self):
        self.db = _db()
        self.db.projects.rows = [
            {"_id": "p_none", "company_id": CO_A, "name": "No row"},
            {"_id": "p_bare", "company_id": CO_A, "name": "Row, no switch"},
            {"_id": "p_on", "company_id": CO_A, "name": "Chases Sundays"},
            {"_id": "p_legacy", "company_id": CO_A, "name": "Old weekends on"},
            {"_id": "p_gone", "company_id": CO_A, "name": "Deleted", "is_deleted": True},
        ]
        self.db.notification_preferences.rows = [
            {"_id": "r1", "user_id": None, "project_id": "p_bare", "scope": "project",
             "company_id": CO_A, "whatsapp_project": {"violation_alerts": False}},
            {"_id": "r2", "user_id": None, "project_id": "p_on", "scope": "project",
             "company_id": CO_A, "whatsapp_project": {"chase_sundays_off": False}},
            {"_id": "r3", "user_id": None, "project_id": "p_legacy", "scope": "project",
             "company_id": CO_A, "whatsapp_project": {"chase_weekends": True}},
        ]

    def migrate(self):
        with patch.object(server, "db", self.db):
            return _run(server._chase_sundays_pin_migration())

    def sundays_off(self, pid):
        with patch.object(server, "db", self.db):
            return _run(server._whatsapp_project_settings(pid))[wa_chase.SUNDAYS_OFF]

    def test_pinned_once(self):
        before = {pid: True for pid in ("p_none", "p_bare")}          # read as Sundays off before
        self.assertEqual(self.migrate(), 3)                            # none, bare, legacy
        self.assertEqual(_row(self.db, "p_none")[wa_chase.SUNDAYS_OFF], before["p_none"])
        self.assertEqual(_row(self.db, "p_bare")[wa_chase.SUNDAYS_OFF], before["p_bare"])
        self.assertIs(_row(self.db, "p_bare")["violation_alerts"], False)          # untouched
        self.assertIs(_row(self.db, "p_on")[wa_chase.SUNDAYS_OFF], False)          # untouched
        self.assertIs(_row(self.db, "p_legacy")[wa_chase.SUNDAYS_OFF], False)      # weekends on
        self.assertIsNone(_row(self.db, "p_gone"))
        # Existing jobs read exactly as before, whatever the company default.
        for pid, want in (("p_none", True), ("p_bare", True), ("p_on", False), ("p_legacy", False)):
            self.assertIs(self.sundays_off(pid), want, pid)
        # Once: a job added afterwards (nothing saved) is left to the default.
        self.db.projects.rows.append({"_id": "p_new", "company_id": CO_A, "name": "New"})
        self.assertEqual(self.migrate(), 0)
        self.assertIsNone(_row(self.db, "p_new"))
        self.assertIs(self.sundays_off("p_new"), False)

    def test_it_runs_at_startup_after_0c(self):
        import inspect
        src = inspect.getsource(server.run_whatsapp_startup_migrations)
        self.assertLess(src.index("_chase_rest_days_migration()"),
                        src.index("_chase_sundays_pin_migration()"))


if __name__ == "__main__":
    unittest.main()
