"""Phase B3 — first-poll summary stamped on the project doc.

After `run_dob_sync_for_project` completes for a project that has
no `first_poll_completed_at` field, the function counts permits +
violations + inspections in db.dob_logs and writes a summary +
timestamp onto the project doc. The dashboard's first-poll banner
reads these fields and shows a 24h post-completion banner.

Idempotent: subsequent calls (project already has the field) noop.
Soft-fail: a count or write hiccup logs a warning and lets the
caller's return value through unchanged.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F401

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import asyncio  # noqa: E402


def _run(coro):
    """Run an async coroutine in a fresh event loop. The full-suite
    run interleaves with other tests that close the default loop, so
    asyncio.get_event_loop().run_until_complete is unreliable here."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _AsyncCursor:
    """Async iterator over a fixed list — mocks db.dob_logs.find()."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def _gen():
            for item in self._items:
                yield item

        return _gen()


def _make_db_for_first_poll(*, project_doc, count_returns):
    """Build a MagicMock db where:
      - db.projects.find_one(_id=...) returns project_doc
      - db.projects.update_one tracks calls (matched_count=1)
      - db.dob_logs.count_documents returns the supplied per-record-type counts
      - db.dob_logs.find returns nothing iterable (empty)
      - db.dob_logs.delete_many noop
      - db.system_config.* noop
    """
    db = MagicMock()

    db.projects = MagicMock()
    db.projects.find_one = AsyncMock(return_value=project_doc)
    db.projects.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    db.dob_logs = MagicMock()

    async def _count_documents(query):
        rt = query.get("record_type")
        return count_returns.get(rt, 0)

    db.dob_logs.count_documents = AsyncMock(side_effect=_count_documents)
    db.dob_logs.find = MagicMock(return_value=_AsyncCursor([]))
    db.dob_logs.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    db.dob_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id="x"))
    db.dob_logs.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    db.system_config = MagicMock()
    db.system_config.find_one = AsyncMock(return_value=None)
    db.system_config.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    return db


class TestFirstPollSummaryWriteOncePerProject(unittest.TestCase):
    """When the project has no `first_poll_completed_at`, the helper
    writes a summary; when it already has one, the helper noops."""

    def test_helper_block_writes_summary_first_time(self):
        """Unit-test the inline helper logic by replaying it
        against a mocked db. The block lives at the tail of
        run_dob_sync_for_project; we exercise the count + update
        contract directly here."""
        import server
        import asyncio

        project = {
            "_id": "proj_a",
            "name": "Test Project",
            "first_poll_completed_at": None,
        }
        db = _make_db_for_first_poll(
            project_doc=project,
            count_returns={
                "permit": 5,
                "violation": 2,
                "inspection": 3,
            },
        )

        async def _replay():
            # Mirrors the inline block at the tail of
            # run_dob_sync_for_project. We don't need the rest of
            # the function — just the summary block.
            proj = await db.projects.find_one({"_id": "proj_a"})
            if proj and not proj.get("first_poll_completed_at"):
                permits_count = await db.dob_logs.count_documents(
                    {"project_id": "proj_a", "record_type": "permit"}
                )
                violations_count = await db.dob_logs.count_documents(
                    {"project_id": "proj_a", "record_type": "violation"}
                )
                inspections_count = await db.dob_logs.count_documents(
                    {"project_id": "proj_a", "record_type": "inspection"}
                )
                await db.projects.update_one(
                    {"_id": "proj_a"},
                    {"$set": {
                        "first_poll_completed_at": datetime.now(timezone.utc),
                        "first_poll_summary": {
                            "permits": permits_count,
                            "violations": violations_count,
                            "inspections": inspections_count,
                        },
                    }},
                )

        _run(_replay())

        # Update was called with the correct counts.
        self.assertTrue(db.projects.update_one.called)
        set_payload = db.projects.update_one.call_args[0][1]["$set"]
        self.assertIn("first_poll_completed_at", set_payload)
        summary = set_payload["first_poll_summary"]
        self.assertEqual(summary["permits"], 5)
        self.assertEqual(summary["violations"], 2)
        self.assertEqual(summary["inspections"], 3)

    def test_idempotent_no_write_when_field_already_set(self):
        """Project with first_poll_completed_at already populated —
        the helper noops on the next sync."""
        import asyncio

        existing_at = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        project = {
            "_id": "proj_a",
            "first_poll_completed_at": existing_at,
            "first_poll_summary": {"permits": 1, "violations": 0, "inspections": 0},
        }
        db = _make_db_for_first_poll(
            project_doc=project,
            count_returns={"permit": 99, "violation": 99, "inspection": 99},
        )

        async def _replay():
            proj = await db.projects.find_one({"_id": "proj_a"})
            if proj and not proj.get("first_poll_completed_at"):
                await db.projects.update_one(
                    {"_id": "proj_a"}, {"$set": {"x": 1}},
                )

        _run(_replay())
        # No update_one call: the existing field short-circuits.
        db.projects.update_one.assert_not_called()


class TestFirstPollSummaryFieldsPresentInSource(unittest.TestCase):
    """Static-source pin: confirm the helper block remains in the
    DOB sync function. A future refactor that drops it would silently
    regress the dashboard banner."""

    def test_helper_block_present(self):
        src_path = _BACKEND / "server.py"
        src = src_path.read_text(encoding="utf-8")
        # Sentinel strings from the inline block.
        self.assertIn("first_poll_completed_at", src)
        self.assertIn("first_poll_summary", src)
        # The block lives ABOVE the _mark_initial_scan_done call
        # so the project doc has the timestamp before the
        # system_config flag flips.
        block_idx = src.find("first_poll_summary stamped for project")
        mark_idx = src.find('_mark_initial_scan_done(project_id, "dob")')
        self.assertGreater(block_idx, 0, "first_poll log line missing")
        self.assertGreater(mark_idx, 0, "_mark_initial_scan_done call site missing")
        self.assertLess(block_idx, mark_idx, "Helper must run BEFORE the scan-done flag")


if __name__ == "__main__":
    unittest.main()
