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

    def test_only_link_roles(self):
        with self.assertRaises(HTTPException) as e:
            _groups(_db(), PM)
        self.assertEqual(e.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
