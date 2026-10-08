"""Integrations → WhatsApp → Groups: every group the Levelog number is in,
for this company — linked ones with their job's address and what they are
(GC group confirmed / waiting for confirm / trade group), then the ones not
linked yet. Another company's groups never appear."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    ADMIN, ADMIN_B, CO_A, CO_B, G_B, G_GC, G_PLUMB, NOON, PM, _Ctx, _confirm,
    _world,
)


def _run(coro):
    return asyncio.run(coro)


def _db():
    db = _world()
    for p in db.projects.rows:
        p["address"] = {"proj_a": "588 Thomas S Boyland St", "proj_b": "9 Other St"}[p["_id"]]
    db[server.PENDING_GROUPS].rows += [
        {"_id": "pg1", "group_id": "120363000000000301@g.us", "group_name": "New Job Crew",
         "company_id": CO_A, "status": "pending", "first_seen": NOON},
        {"_id": "pg2", "group_id": "120363000000000302@g.us", "group_name": "B's new group",
         "company_id": CO_B, "status": "pending", "first_seen": NOON},
    ]
    return db


def _groups(db, user=ADMIN):
    with _Ctx(db=db):
        return _run(server.whatsapp_company_groups(current_user=user))["groups"]


class CompanyGroups(unittest.TestCase):

    def test_linked_groups_show_with_address_and_status(self):
        db = _db()
        with _Ctx(db=db):
            _confirm()
        got = {g["group_id"]: g for g in _groups(db)}
        self.assertEqual(got[G_GC]["status"], server.GROUP_GC_CONFIRMED)
        self.assertEqual(got[G_GC]["project_label"], "588 Thomas S Boyland St")
        self.assertEqual(got[G_GC]["group_name"], "Main St Project")
        self.assertEqual(got[G_PLUMB]["status"], server.GROUP_TRADE)

    def test_a_linked_group_shows_with_no_gc_and_no_pending(self):
        """The bug: 588 Thomas was linked, nothing pending, the card was empty."""
        db = _world()
        got = _groups(db)
        self.assertEqual({g["group_id"] for g in got}, {G_GC, G_PLUMB})
        self.assertTrue(all(g["status"] == server.GROUP_TRADE for g in got))

    def test_waiting_for_confirm(self):
        db = _db()
        with _Ctx(db=db):
            _run(server._set_whatsapp_project_fields("proj_a", CO_A, {"gc_proposal": {
                "status": "pending", "group_id": G_GC, "group_name": "Main St Project",
                "admin_user_id": "u_admin", "sent_at": server.datetime.now(server.timezone.utc),
                "expires_at": server.datetime.now(server.timezone.utc) + timedelta(hours=4)}}))
        got = {g["group_id"]: g for g in _groups(db)}
        self.assertEqual(got[G_GC]["status"], server.GROUP_GC_WAITING)
        self.assertEqual(got[G_PLUMB]["status"], server.GROUP_TRADE)

    def test_not_linked_groups_follow_and_link_nothing(self):
        got = _groups(_db())
        last = got[-1]
        self.assertEqual((last["group_name"], last["status"], last["project_id"]),
                         ("New Job Crew", server.GROUP_NOT_LINKED, None))

    def test_another_companys_groups_never_appear(self):
        got = {g["group_id"] for g in _groups(_db())}
        self.assertNotIn(G_B, got)
        self.assertNotIn("120363000000000302@g.us", got)
        got_b = {g["group_id"] for g in _groups(_db(), ADMIN_B)}
        self.assertEqual(got_b, {G_B, "120363000000000302@g.us"})

    def test_a_group_whose_job_is_gone_is_left_out(self):
        db = _db()
        next(p for p in db.projects.rows if p["_id"] == "proj_a")["is_deleted"] = True
        self.assertFalse({G_GC, G_PLUMB} & {g["group_id"] for g in _groups(db)})

    def test_an_unlinked_group_comes_back_as_not_linked(self):
        """Unlinking only deactivates the binding; the bot is still in the
        group, so it must show as Not linked (and be linkable), not vanish."""
        db = _db()
        db[server.PENDING_GROUPS].rows.append(
            {"_id": "pgx", "group_id": G_PLUMB, "group_name": "Main St Plumbing",
             "company_id": CO_A, "status": "linked", "linked_project_id": "proj_a",
             "greeted_at": NOON, "invite_sent_at": NOON})
        with _Ctx(db=db):
            _run(server.whatsapp_unlink_group("g2", current_user=ADMIN))
            pending = _run(server.whatsapp_pending_groups(current_user=ADMIN))["pending"]
        got = {g["group_id"]: g for g in _groups(db)}
        self.assertEqual(got[G_PLUMB]["status"], server.GROUP_NOT_LINKED)
        self.assertIn(G_PLUMB, {p["group_id"] for p in pending})     # the Link screen sees it
        self.assertEqual(got[G_GC]["status"], server.GROUP_TRADE)    # the other is untouched

    def test_unlink_with_no_registry_row_adds_one_without_greeting_again(self):
        db = _db()
        with _Ctx(db=db):
            _run(server.whatsapp_unlink_group("g2", current_user=ADMIN))
        row = next(r for r in db[server.PENDING_GROUPS].rows if r["group_id"] == G_PLUMB)
        self.assertEqual((row["status"], row["company_id"]), ("pending", CO_A))
        self.assertIsNotNone(row["greeted_at"])
        self.assertIsNotNone(row["invite_sent_at"])
        self.assertIn(G_PLUMB, {g["group_id"] for g in _groups(db)})
        self.assertNotIn(G_PLUMB, {g["group_id"] for g in _groups(db, ADMIN_B)})

    def test_a_pm_reads_only_their_projects_linked_groups(self):
        db = _db()
        got = _groups(db, PM)                       # PM: assigned to proj_a
        self.assertEqual({g["group_id"] for g in got}, {G_GC, G_PLUMB})
        self.assertNotIn(server.GROUP_NOT_LINKED, {g["status"] for g in got})
        other = dict(PM, assigned_projects=["proj_x"])
        self.assertEqual(_groups(db, other), [])

    def test_other_roles_are_refused(self):
        for role in ("superintendent", "worker"):
            with self.assertRaises(HTTPException) as e:
                _groups(_db(), dict(PM, role=role))
            self.assertEqual(e.exception.status_code, 403, role)


if __name__ == "__main__":
    unittest.main()
