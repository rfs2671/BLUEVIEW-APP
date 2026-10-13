"""Every WhatsApp job list and lookup leaves out a job marked for deletion.

Tue Oct 13, 10:52 AM: "9 MENAHAN STREET" in the DM's Which-job list. The job
was added and then undone by DM on Mon 8:30 PM; undo marks the project for
deletion (marked_for_deletion), which the app's lists already hide
(ACTIVE_PROJECT_FILTER), but the WhatsApp side read `is_deleted` only.

The functions below are every WhatsApp read of `projects` that filters on
deletion at all. Each must use ACTIVE_PROJECT_FILTER, not a local
`is_deleted` clause, so a job marked for deletion is invisible to the bot
exactly as it is to the app."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text()

WHATSAPP_READS = [
    "_bot_project_scope", "_dm_assistant_projects", "_dm_other_company_job",
    "_find_project_for_contact", "_punch_link_open", "_assert_link_project_owned",
    "whatsapp_pending_groups", "whatsapp_company_groups", "whatsapp_pending_group_by_token",
    "_dot_sync_tick", "_upcoming_city_tick",
]


def _body(name: str) -> str:
    m = re.search(rf"^(?:async )?def {name}\(", SRC, re.M)
    assert m, name
    end = re.search(r"^(?:async )?def |^@", SRC[m.end():], re.M)
    return SRC[m.start(): m.end() + (end.start() if end else len(SRC))]


class EveryWhatsAppRead(unittest.TestCase):

    def test_uses_the_one_filter(self):
        for name in WHATSAPP_READS:
            with self.subTest(name):
                body = _body(name)
                self.assertIn("ACTIVE_PROJECT_FILTER", body)
                for m in re.finditer(r"db\.projects\.(?:find_one|find)\((.{0,300})", body, re.S):
                    self.assertNotRegex(m.group(1).split(".to_list")[0],
                                        r'"is_deleted": \{"\$ne": True\}(?![^)]*ACTIVE)',
                                        f"{name}: a local is_deleted clause")

    def test_the_filter_leaves_out_marked_for_deletion(self):
        from lib.project_state import ACTIVE_PROJECT_FILTER
        self.assertEqual(ACTIVE_PROJECT_FILTER["marked_for_deletion"], {"$ne": True})


if __name__ == "__main__":
    unittest.main()


class TheDiag(unittest.TestCase):
    """scripts/diag_undone_job.py, on a fake db: the add, the undo, the state."""

    def test_prints_the_rows(self):
        import asyncio
        import contextlib
        import io
        from datetime import datetime, timezone
        from unittest.mock import patch

        import server
        from scripts import diag_undone_job as diag
        from tests._fake_mongo import FakeDb

        db = FakeDb()
        t = datetime(2026, 10, 13, 0, 30, tzinfo=timezone.utc)          # Mon 8:30 PM ET
        db.projects.rows.append({"_id": "pm", "company_id": "c1", "name": "9 Menahan St",
                                 "address": "9 MENAHAN STREET, Brooklyn, NY, USA",
                                 "created_at": t, "created_by": "u1",
                                 "marked_for_deletion": True, "marked_by": "u1", "marked_at": t})
        db.users.rows.append({"_id": "u1", "name": "Roy", "role": "admin",
                              "phone": "17185550100"})
        db.audit_logs.rows.extend([
            {"action": "whatsapp_dm_action", "user_id": "u1", "resource_id": "pm",
             "timestamp": t, "details": {"via": "whatsapp_dm", "said": "add 9 menahan",
                                         "action": "add_job", "after": {"name": "9 Menahan St"}}},
            {"action": "whatsapp_dm_undo", "user_id": "u1", "resource_id": "pm",
             "timestamp": t, "details": {"via": "whatsapp_dm", "undo": {"kind": "job"}}}])
        out = io.StringIO()
        with patch.object(server, "db", db), contextlib.redirect_stdout(out):
            self.assertEqual(asyncio.run(diag.main_async(
                type("A", (), {"match": "menahan", "since": None})())), 0)
        text = out.getvalue()
        self.assertIn("marked_for_deletion=True", text)
        self.assertIn("Mon Oct 12 08:30:00 PM ET  whatsapp_dm_action", text)
        self.assertIn("whatsapp_dm_undo", text)
        self.assertIn("said: 'add 9 menahan'", text)
        self.assertIn("pm: hidden", text)
        self.assertNotIn("17185550100", text)
