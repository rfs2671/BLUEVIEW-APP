"""last_dob_sync_at must be STAMPED by a real sync, not merely defined.

The projects-table SYNCED column, the dashboard never-synced rollup, and the
project-detail badge all read `last_dob_sync_at`. If the write were removed, or
moved above one of run_dob_sync_for_project's three early returns, every one of
those surfaces would silently read "Never" forever — a false statement that no
type checker or import smoke test would catch.

So this drives the REAL run_dob_sync_for_project (HTTP + db stubbed, function
body untouched) and asserts the stamp actually lands.

Pins three things:
  1. a normal sync writes last_dob_sync_at to the project doc
  2. the value is an AWARE UTC datetime (not naive, not a string)
  3. a sync that bails at an early return does NOT stamp — a failed run must
     never look like a fresh one
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")


def _run(coro):
    return asyncio.run(coro)


def _mock_db(projects_update):
    """Minimal db double: enough for the sync to reach its completion path."""
    class _EmptyCursor:
        def sort(self, *_a, **_kw):
            return self

        async def to_list(self, *_a, **_kw):
            return []

        # server.py iterates this cursor with `async for`, so it needs the
        # async-iterator protocol, not just to_list().
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    dob_logs = MagicMock()
    dob_logs.find = MagicMock(return_value=_EmptyCursor())
    dob_logs.find_one = AsyncMock(return_value=None)
    dob_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id="x"))
    dob_logs.update_one = AsyncMock()
    dob_logs.count_documents = AsyncMock(return_value=0)

    projects = MagicMock()
    projects.update_one = projects_update
    # first_poll block reads the doc; return one that ALREADY has a first poll
    # so that guarded branch is skipped and we isolate the rolling stamp.
    projects.find_one = AsyncMock(
        return_value={"_id": "p1", "first_poll_completed_at": datetime.now(timezone.utc)}
    )

    system_config = MagicMock()
    system_config.update_one = AsyncMock()
    system_config.find_one = AsyncMock(return_value=None)

    db = MagicMock()
    db.dob_logs = dob_logs
    db.projects = projects
    db.system_config = system_config
    return db


class TestLastDobSyncAtStamp(unittest.TestCase):
    def test_normal_sync_stamps_aware_utc_timestamp(self):
        from server import run_dob_sync_for_project

        projects_update = AsyncMock()
        db = _mock_db(projects_update)

        # One well-formed record so the sync runs its normal course and reaches
        # the completion path. Shape matches what _query_dob_apis emits: the
        # id field is named by `_id_field`, and the type key is `_record_type`
        # (underscore-prefixed, in-flight) — not `record_type`.
        record = {
            "_id_field": "unique_key",
            "unique_key": "V-1",
            "_record_type": "violation",
            "_dataset": "3h2n-5cm9",
            "violation_number": "V-1",
        }

        with patch("server.db", db), \
             patch("server._query_dob_apis", AsyncMock(return_value=[record])):
            _run(run_dob_sync_for_project(
                {"_id": "p1", "company_id": "c1", "nyc_bin": "1234567",
                 "address": "100 Main St, BROOKLYN, NY 11221"}
            ))

        stamps = [
            c for c in projects_update.await_args_list
            if "last_dob_sync_at" in str(c)
        ]
        self.assertTrue(
            stamps,
            "a normal sync did not write last_dob_sync_at — the SYNCED column, "
            "never-synced card and project badge would read 'Never' forever",
        )

        value = stamps[-1].args[1]["$set"]["last_dob_sync_at"]
        self.assertIsInstance(value, datetime)
        self.assertIsNotNone(
            value.tzinfo,
            "last_dob_sync_at must be an AWARE UTC datetime, not naive",
        )
        self.assertEqual(value.utcoffset(), timezone.utc.utcoffset(None))

    def test_early_return_does_not_stamp(self):
        """A project with no BIN and no address bails at the first early
        return. That path must not record a successful sync."""
        from server import run_dob_sync_for_project

        projects_update = AsyncMock()
        db = _mock_db(projects_update)

        with patch("server.db", db):
            _run(run_dob_sync_for_project({"_id": "p1", "company_id": "c1"}))

        stamps = [
            c for c in projects_update.await_args_list
            if "last_dob_sync_at" in str(c)
        ]
        self.assertEqual(
            stamps, [],
            "a sync that bailed early stamped last_dob_sync_at — a failed run "
            "must never look like a fresh one",
        )


if __name__ == "__main__":
    unittest.main()
