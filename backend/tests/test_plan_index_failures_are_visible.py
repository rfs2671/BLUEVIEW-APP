"""A plan-index job that gave up is not silent.

_run_plan_index_job marks a file `failed` after PLAN_INDEX_MAX_ATTEMPTS and
writes the reason onto the job row. Nothing read that row.
document-index-status returns it per file, and the only client that ever called
document-index-status was a dead wrapper in the app's api.js — no component
imports it. So a drawing set that failed three times disappeared, and the next
anyone heard of it was a plan question answering "not on the indexed drawings"
about a sheet sitting in Plans & Files.

Zero jobs are failed in production today, across every project. This is latent,
not active, and it is the only one of the three review items that can lose work
without anyone learning.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
ACME = "company-acme"
OTHER = "company-other"


def _job(fid, status, *, company=ACME, attempts=1, lease=None, name=None, err=None):
    return {"_id": fid, "project_id": "p1", "company_id": company,
            "file_name": name or f"{fid}.pdf", "status": status,
            "attempts": attempts, "lease_until": lease, "error": err,
            "pages_done": 0, "pages_total": None,
            "updated_at": NOW - timedelta(minutes=int(fid[-1]) if fid[-1].isdigit() else 0)}


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n=None):
        return [dict(r) for r in self.rows]


class _Coll:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def _match(self, r, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict) and "$ne" in v:
                if r.get(k) == v["$ne"]:
                    return False
            elif r.get(k) != v:
                return False
        return True

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if self._match(r, q)])

    async def find_one(self, q=None, proj=None):
        for r in self.rows:
            if self._match(r, q):
                return dict(r)
        return None


class _Db:
    def __init__(self, jobs=(), files=(), projects=()):
        self._c = {server.PLAN_INDEX_JOBS: _Coll(jobs)}
        self.project_files = _Coll(files)
        self.projects = _Coll(projects)

    def __getitem__(self, n):
        return self._c.setdefault(n, _Coll())


def _run(coro):
    return asyncio.run(coro)


ADMIN = {"_id": "u1", "role": "admin", "company_id": ACME}


class WhatTheFailedListShows(unittest.TestCase):

    def _list(self, jobs, user=None, projects=()):
        db = _Db(jobs=jobs, projects=projects)
        with mock.patch.object(server, "db", db):
            return _run(server.list_failed_plan_index_jobs(current_user=user or ADMIN))

    def test_a_job_that_gave_up(self):
        out = self._list([_job("f1", "failed", err="stopped after 3 attempts")])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["jobs"][0]["state"], "failed")
        self.assertEqual(out["jobs"][0]["error"], "stopped after 3 attempts")
        self.assertEqual(out["jobs"][0]["file_name"], "f1.pdf")

    def test_a_cancelled_job_too(self):
        out = self._list([_job("f1", "cancelled", err="the file no longer exists")])
        self.assertEqual(out["jobs"][0]["state"], "cancelled")

    def test_a_running_job_whose_lease_ran_out_is_stuck(self):
        # Real clock: _as_utc is what reads the lease, and mocking the module's
        # datetime takes that with it.
        gone = datetime.now(timezone.utc) - timedelta(minutes=5)
        out = self._list([_job("f1", "running", lease=gone)])
        self.assertEqual(out["jobs"][0]["state"], "stuck")

    def test_work_in_progress_is_not_a_failure(self):
        live = datetime.now(timezone.utc) + timedelta(minutes=5)
        out = self._list([
            _job("f1", "done"),
            _job("f2", "queued"),
            _job("f3", "skipped"),
            _job("f4", "running", lease=live),
        ])
        self.assertEqual(out["count"], 0, out["jobs"])

    def test_it_names_the_project_so_nobody_opens_sixteen(self):
        out = self._list([_job("f1", "failed")],
                         projects=[{"_id": "p1", "address": "588 THOMAS S BOYLAND STREET"}])
        self.assertEqual(out["jobs"][0]["project_name"], "588 THOMAS S BOYLAND STREET")

    def test_another_company_is_not_listed(self):
        out = self._list([_job("f1", "failed"), _job("f2", "failed", company=OTHER)])
        self.assertEqual([j["file_id"] for j in out["jobs"]], ["f1"])

    def test_the_platform_operator_sees_every_company(self):
        with mock.patch.object(server, "is_platform_operator", lambda u: True):
            out = self._list([_job("f1", "failed"),
                              _job("f2", "failed", company=OTHER)],
                             user={"_id": "op", "role": "owner", "email": "op@x"})
        self.assertEqual({j["file_id"] for j in out["jobs"]}, {"f1", "f2"})

    def test_newest_first(self):
        out = self._list([_job("f1", "failed"), _job("f3", "failed")])
        self.assertEqual([j["file_id"] for j in out["jobs"]], ["f1", "f3"])


class RetryPutsItBackOnTheQueue(unittest.TestCase):

    FILE = {"_id": "f1", "project_id": "p1", "company_id": ACME, "name": "ST.pdf",
            "r2_key": "k"}

    def _retry(self, files=None, user=None):
        seen = {}

        async def enqueue(project_id, company_id, rec, *, source, resume=True):
            seen.update(project_id=project_id, company_id=company_id,
                        name=rec.get("name"), source=source, resume=resume)
            return "queued"

        db = _Db(files=files if files is not None else [self.FILE])
        with mock.patch.object(server, "db", db), \
                mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "_enqueue_plan_index", enqueue):
            out = _run(server.retry_plan_index_job("p1", "f1", current_user=user or ADMIN))
        return out, seen

    def test_it_queues_the_file(self):
        out, seen = self._retry()
        self.assertTrue(out["queued"])
        self.assertEqual(out["file_name"], "ST.pdf")
        self.assertEqual(seen["name"], "ST.pdf")
        self.assertEqual(seen["source"], "retry")

    def test_it_resumes_rather_than_paying_for_finished_pages_again(self):
        _out, seen = self._retry()
        self.assertTrue(seen["resume"], "a restart re-buys every vision call already spent")

    def test_a_file_that_is_not_there(self):
        with self.assertRaises(server.HTTPException) as e:
            self._retry(files=[])
        self.assertEqual(e.exception.status_code, 404)

    def test_another_companys_file(self):
        with self.assertRaises(server.HTTPException) as e:
            self._retry(files=[dict(self.FILE, company_id=OTHER)])
        self.assertEqual(e.exception.status_code, 403)

    def test_a_deleted_file_is_not_retried(self):
        with self.assertRaises(server.HTTPException) as e:
            self._retry(files=[dict(self.FILE, is_deleted=True)])
        self.assertEqual(e.exception.status_code, 404)


class OneQueueingPath(unittest.TestCase):

    def test_retry_goes_through_the_enqueue_everything_else_uses(self):
        import inspect
        src = inspect.getsource(server.retry_plan_index_job)
        self.assertIn("_enqueue_plan_index(", src)
        # A second writer would drift from the first: _enqueue_plan_index is
        # what resets attempts, clears the error and lifts not_before.
        self.assertNotIn("db[PLAN_INDEX_JOBS]", src)

    def test_the_enqueue_clears_what_a_retry_must_clear(self):
        import inspect
        src = inspect.getsource(server._enqueue_plan_index)
        for field in ('"attempts": 0', '"error": None', '"not_before": None',
                      '"status": "queued"'):
            with self.subTest(field=field):
                self.assertIn(field, src)


if __name__ == "__main__":
    unittest.main()
