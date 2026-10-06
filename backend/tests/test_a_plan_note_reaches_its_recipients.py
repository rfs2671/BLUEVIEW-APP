"""A PLAN NOTE REACHES THE PEOPLE IT WAS ADDRESSED TO.

`_send_annotation_emails` built each send's metadata with
`"project_id": str(project_id)` - and `project_id` was never defined in the
function. The NameError rose while the call's arguments were being built,
before `send_notification` (which writes notification_log) ran, and the
per-recipient `except Exception` logged it and moved on. Nothing sent,
nothing logged. It came in with the email consolidation (f1545563,
2026-05-03).

It had not yet cost an email: measured read-only on production 2026-10-06,
the one plan note addressed since then named only its own creator, and the
function returns before the broken line when nobody else is addressed. The
first note to anyone else would have vanished.

The test that existed (test_email_consolidation) checked that the source
SAYS trigger_type="annotation_note" - true whether or not the call can run.
This one runs it.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

PROJECT = "6a5f63bc147407d3261df2c7"
ANN = "6aa97c84b9079fe1226cf05f"
CREATOR = "64b000000000000000000001"
OTHER = "64b000000000000000000002"


def _db():
    users = {CREATOR: {"name": "Site Lead", "email": "creator@example.com"},
             OTHER: {"name": "PM", "email": "pm@example.com"}}

    async def find_user(q, *a, **k):
        return users.get(str(q.get("_id")))

    db = MagicMock()
    db.document_annotations.find_one = AsyncMock(
        return_value={"_id": ANN, "screenshot": "https://cdn.example/shot.png"})
    db.users.find_one = AsyncMock(side_effect=find_user)
    return db


def _annotation():
    """As the create endpoint stores it and hands it to the sender."""
    return {"id": ANN, "project_id": PROJECT, "comment": "Check the EF-2 duct",
            "recipients": [CREATOR, OTHER], "created_by": CREATOR}


class APlanNoteReachesItsRecipients(unittest.TestCase):

    def _send(self):
        import server
        sent = AsyncMock(return_value={"status": "sent"})
        with patch.object(server, "db", _db()), \
                patch("asyncio.sleep", AsyncMock()), \
                patch("lib.notifications.send_notification", sent):
            asyncio.run(server._send_annotation_emails(
                _annotation(), "588 Boyland", [CREATOR, OTHER], CREATOR))
        return sent

    def test_the_other_recipient_is_sent_one_notification(self):
        sent = self._send()
        self.assertEqual(sent.await_count, 1,
                         "the note was addressed to one other person and "
                         f"{sent.await_count} notification(s) were attempted")
        self.assertEqual(sent.await_args.kwargs["recipient"], "pm@example.com")
        self.assertEqual(sent.await_args.kwargs["trigger_type"], "annotation_note")

    def test_it_carries_the_notes_own_project(self):
        sent = self._send()
        self.assertEqual(sent.await_count, 1)
        self.assertEqual(sent.await_args.kwargs["metadata"]["project_id"], PROJECT)

    def test_the_creator_is_not_emailed_about_their_own_note(self):
        sent = self._send()
        self.assertNotIn("creator@example.com",
                         [c.kwargs["recipient"] for c in sent.await_args_list])


if __name__ == "__main__":
    unittest.main()
