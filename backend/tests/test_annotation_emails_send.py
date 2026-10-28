"""A PLAN NOTE IS EMAILED TO EACH RECIPIENT, WITH ITS PROJECT ON THE ROW.

`_send_annotation_emails` built the send_notification metadata from a
`project_id` it never defined. Every call raised NameError inside the
per-recipient try, the except logged `annotation send_notification error`,
and no plan-note email was ever sent. The project comes from the annotation
document itself (create_annotation writes `project_id` onto it).

Run:  python -m pytest backend/tests/test_annotation_emails_send.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret_for_the_suite")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bson import ObjectId  # noqa: E402

import server  # noqa: E402

ANN_ID = str(ObjectId())
PROJECT_ID = str(ObjectId())
CREATOR = str(ObjectId())
ALICE = str(ObjectId())
BOB = str(ObjectId())

USERS = {
    CREATOR: {"name": "Pat Creator", "email": "creator@example.com"},
    ALICE: {"name": "Alice", "email": "alice@example.com"},
    BOB: {"name": "Bob", "email": "bob@example.com"},
}


class _Annotations:
    async def find_one(self, query, projection=None):
        return {"_id": query["_id"], "screenshot": "https://cdn.example.com/s.png"}


class _Users:
    async def find_one(self, query, projection=None):
        return USERS.get(str(query["_id"]))


class _DB:
    document_annotations = _Annotations()
    users = _Users()


class PlanNoteEmailsAreSent(unittest.TestCase):
    def test_one_send_per_recipient_with_the_annotation_project(self):
        annotation = {
            "id": ANN_ID,
            "project_id": PROJECT_ID,
            "comment": "Check the beam at grid C",
            "created_by": CREATOR,
        }
        sent = mock.AsyncMock(return_value={"status": "sent"})
        with mock.patch.object(server, "db", _DB()), \
                mock.patch.object(server.asyncio, "sleep", mock.AsyncMock()), \
                mock.patch("lib.notifications.send_notification", sent), \
                mock.patch.object(server.logger, "error") as logged_error:
            asyncio.run(server._send_annotation_emails(
                annotation, "Tower One", [CREATOR, ALICE, BOB], CREATOR,
            ))

        logged_error.assert_not_called()
        # The creator is skipped; each other recipient gets exactly one send.
        recipients = [c.kwargs["recipient"] for c in sent.await_args_list]
        self.assertEqual(recipients, ["alice@example.com", "bob@example.com"])
        for call in sent.await_args_list:
            self.assertEqual(call.kwargs["trigger_type"], "annotation_note")
            self.assertEqual(call.kwargs["permit_renewal_id"], f"annotation:{ANN_ID}")
            meta = call.kwargs["metadata"]
            self.assertEqual(meta["annotation_id"], ANN_ID)
            self.assertEqual(meta["project_id"], PROJECT_ID)
            self.assertEqual(meta["creator_name"], "Pat Creator")


if __name__ == "__main__":
    unittest.main()
