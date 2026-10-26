"""The glyph pass does not run on a set that is being re-indexed (2026-10-26).

A re-index deletes the file's page rows first and writes them back a page at
a time. The pass was started a minute after a re-index of AR 3.28.25, read the
set with that file missing, and wrote 221 rows against 181: 48 count answers
bound a wrong figure and 46 set-health items named sheets that were only being
rewritten. Now:

- the run endpoint refuses (409) while any re-index of the project is queued
  or running, and says which;
- a re-index enqueued or started while a pass is running makes the pass end
  without writing anything;
- the re-index routes return a job id, and a read-only route reports the job.

Tests use a fake in-flight job; the control run on main fails by assertion.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402

PID = "proj-boyland"
ADMIN = {"_id": "u1", "role": "admin", "company_id": "co1"}


def _guarded():
    assert hasattr(server, "_reindex_in_flight"), "the pass does not look at re-index jobs (main)"


def _job(status, **kw):
    now = datetime.now(timezone.utc)
    return dict({"_id": "file-ar328", "project_id": PID, "file_name": "AR - 3.28.25.pdf",
                 "status": status, "pages_done": 3, "pages_total": 26,
                 "enqueued_at": now - timedelta(minutes=5), "started_at": now - timedelta(minutes=5)}, **kw)


class TheRunEndpointRefuses(unittest.TestCase):

    def _run(self, jobs):
        _guarded()
        db = AsyncFakeDB()
        db[server.PLAN_INDEX_JOBS].docs.extend(jobs)
        started = []

        async def fake_pass(pid):
            started.append(pid)
            return {}
        with patch.object(server, "db", db), patch.object(server, "_plan_glyph_pass", fake_pass):
            out = asyncio.run(server.run_plan_glyph_pass(PID, current_user=ADMIN))
            asyncio.run(asyncio.sleep(0))
        server._GLYPH_PASS_RUNNING.discard(PID)
        return out

    def test_while_a_reindex_is_running(self):
        with self.assertRaises(HTTPException) as cm:
            self._run([_job("running")])
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("re-index is in progress", cm.exception.detail["reason"])
        self.assertEqual([j["file_name"] for j in cm.exception.detail["jobs"]], ["AR - 3.28.25.pdf"])

    def test_while_one_is_queued(self):
        with self.assertRaises(HTTPException) as cm:
            self._run([_job("queued")])
        self.assertEqual(cm.exception.status_code, 409)

    def test_a_finished_reindex_does_not_block(self):
        out = self._run([_job("done", finished_at=datetime.now(timezone.utc))])
        self.assertEqual(out, {"started": True})


class APassDuringAReindexWritesNothing(unittest.TestCase):

    def _pass(self, job_during=None, job_before=None):
        _guarded()
        db = AsyncFakeDB()
        if job_before:
            db[server.PLAN_INDEX_JOBS].docs.append(job_before)
        written = []

        async def pages(pid):
            if job_during:     # a re-index arrives while the pass reads
                db[server.PLAN_INDEX_JOBS].docs.append(job_during())
            return [], {}

        async def write_rows(pid, rows):
            written.append("rows")
            return len(rows)

        async def write_health(pid, items):
            written.append("health")
            return len(items)
        with patch.object(server, "db", db), patch.object(server, "_glyph_pages", pages), \
                patch.object(server, "_write_glyph_records", write_rows), \
                patch.object(server, "_write_set_health", write_health):
            summary = asyncio.run(server._plan_glyph_pass(PID))
        return summary, written

    def test_a_reindex_started_during_the_pass_aborts_it(self):
        summary, written = self._pass(job_during=lambda: _job(
            "running", enqueued_at=datetime.now(timezone.utc), started_at=datetime.now(timezone.utc)))
        self.assertEqual(written, [])
        self.assertIn("nothing written", summary.get("aborted", ""))

    def test_one_that_started_and_finished_during_it_aborts_it_too(self):
        def arrives():         # stamped when it arrives, after the pass began
            now = datetime.now(timezone.utc)
            return _job("done", enqueued_at=now, started_at=now, finished_at=now)
        summary, written = self._pass(job_during=arrives)
        self.assertEqual(written, [])

    def test_a_reindex_finished_before_the_pass_lets_it_write(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        summary, written = self._pass(job_before=_job("done", enqueued_at=old, started_at=old, finished_at=old))
        self.assertEqual(written, ["rows", "health"])
        self.assertNotIn("aborted", summary)


class TheJobIsVisible(unittest.TestCase):

    def test_reindex_document_returns_its_job_id(self):
        _guarded()
        db = AsyncFakeDB()
        db.project_files.docs.append({"_id": "file-ar328", "project_id": PID, "company_id": "co1",
                                      "name": "AR - 3.28.25.pdf", "r2_key": "k"})

        async def enqueue(*a, **k):
            return "queued"

        class _R2:
            def get_object(self, **k):
                raise RuntimeError("no network in tests")
        from tests.async_fake_mongo import AsyncFakeCollection

        async def delete_many(self, flt=None, **kw):     # the fake has none
            return None
        with patch.object(server, "db", db), patch.object(server, "QWEN_API_KEY", "k"), \
                patch.object(server, "_enqueue_plan_index", enqueue), patch.object(server, "_r2_client", _R2()), \
                patch.object(server, "to_query_id", lambda x: x), \
                patch.object(AsyncFakeCollection, "delete_many", delete_many, create=True):
            out = asyncio.run(server.reindex_project_document(PID, {"file_id": "file-ar328"}, current_user=ADMIN))
        self.assertEqual(out["job_id"], "file-ar328")

    def test_the_status_route_reports_the_job(self):
        _guarded()
        db = AsyncFakeDB()
        db[server.PLAN_INDEX_JOBS].docs.append(_job("running"))
        with patch.object(server, "db", db):
            out = asyncio.run(server.plan_index_job_status(PID, "file-ar328", current_user=ADMIN))
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(server.plan_index_job_status(PID, "no-such-job", current_user=ADMIN))
        self.assertEqual((out["status"], out["pages_done"], out["pages_total"], out["job_id"]),
                         ("running", 3, 26, "file-ar328"))
        self.assertEqual(cm.exception.status_code, 404)

    def test_another_projects_job_is_not_reported(self):
        _guarded()
        db = AsyncFakeDB()
        db[server.PLAN_INDEX_JOBS].docs.append(_job("running", project_id="someone-elses-project"))
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(server.plan_index_job_status(PID, "file-ar328", current_user=ADMIN))
        self.assertEqual(cm.exception.status_code, 404)

    def test_the_pass_status_names_the_reindex_in_flight(self):
        _guarded()
        db = AsyncFakeDB()
        db[server.PLAN_INDEX_JOBS].docs.append(_job("running"))
        with patch.object(server, "db", db):
            out = asyncio.run(server.plan_glyph_pass_status(PID, current_user=ADMIN))
        self.assertFalse(out["running"])
        self.assertEqual([j["file_name"] for j in out["reindex_in_flight"]], ["AR - 3.28.25.pdf"])


if __name__ == "__main__":
    unittest.main()
