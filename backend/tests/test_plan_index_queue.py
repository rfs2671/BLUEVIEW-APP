"""The plan index queue: a restart resumes, never loses the work.

The first Boyland re-index queued 16 files as asyncio tasks; the container
restarted two minutes later and every task was gone. These tests pin the
replacement: a row per file in plan_index_jobs, a worker that claims one job
at a time on a lease, and a reclaim when that lease is not renewed.

The database is an in-memory stand-in with the parts of Mongo's filter and
update language the queue uses. No network, no model, no poppler.
"""

import asyncio
import inspect
import os
import re
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


def _run(coro):
    return asyncio.run(coro)


_MISSING = object()


def _get(doc, key):
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _utc(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def _match(doc, q):
    for key, cond in (q or {}).items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        val = _get(doc, key)
        v = None if val is _MISSING else val
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and v not in arg:
                    return False
                if op == "$nin" and v in arg:
                    return False
                if op == "$ne" and v == arg:
                    return False
                if op == "$lt" and not (v is not None and _utc(v) < _utc(arg)):
                    return False
                if op == "$lte" and not (v is not None and _utc(v) <= _utc(arg)):
                    return False
                if op == "$gte" and not (v is not None and v >= arg):
                    return False
                if op == "$regex" and not (isinstance(v, str) and re.search(
                        arg, v, re.I if "i" in (cond.get("$options") or "") else 0)):
                    return False
        elif v != cond:
            return False
    return True


def _apply(doc, update):
    for k, v in update.get("$set", {}).items():
        doc[k] = v
    for k, v in update.get("$inc", {}).items():
        doc[k] = (doc.get(k) or 0) + v
    for k in update.get("$unset", {}):
        doc.pop(k, None)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n=None):
        return [dict(r) for r in self.rows]


class _Coll:
    def __init__(self):
        self.rows = []

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if _match(r, q)])

    async def find_one(self, q=None, proj=None, **kw):
        for r in self.rows:
            if _match(r, q):
                return dict(r)
        return None

    async def update_one(self, q, update, upsert=False):
        for r in self.rows:
            if _match(r, q):
                _apply(r, update)
                return
        if upsert:
            row = {k: v for k, v in q.items() if not k.startswith("$")}
            for k, v in update.get("$setOnInsert", {}).items():
                row[k] = v
            _apply(row, update)
            self.rows.append(row)

    async def find_one_and_update(self, q, update, sort=None, return_document=None):
        rows = [r for r in self.rows if _match(r, q)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda r: _utc(r.get(key)) or datetime.min.replace(tzinfo=timezone.utc),
                      reverse=direction < 0)
        if not rows:
            return None
        _apply(rows[0], update)
        return dict(rows[0])

    async def count_documents(self, q):
        return sum(1 for r in self.rows if _match(r, q))

    async def delete_many(self, q):
        self.rows = [r for r in self.rows if not _match(r, q)]


class _Db:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.setdefault(n, _Coll())

    def __getitem__(self, n):
        return self._c.setdefault(n, _Coll())


NOW = datetime.now(timezone.utc)


def _now():
    """For anything that must still be in the FUTURE when the test runs. NOW is
    taken at import, and the full suite reaches these tests twelve minutes
    later — a lease of NOW + 2 minutes had already expired."""
    return datetime.now(timezone.utc)


class _WithDb(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        p = mock.patch.object(server, "db", self.db)
        p.start()
        self.addCleanup(p.stop)

    @property
    def jobs(self):
        return self.db.plan_index_jobs.rows

    def job(self, file_id):
        return next(j for j in self.jobs if j["_id"] == file_id)


class EnqueueIsIdempotentPerFile(_WithDb):

    def test_a_new_file_is_queued_with_nothing_done(self):
        out = _run(server._enqueue_plan_index("p1", "c1", {"_id": "f1", "name": "ST.pdf"},
                                              source="reindex_all"))
        self.assertEqual(out, "queued")
        j = self.job("f1")
        self.assertEqual((j["status"], j["pages_done"], j["project_id"], j["source"]),
                         ("queued", 0, "p1", "reindex_all"))

    def test_resume_keeps_progress_and_a_full_reindex_resets_it(self):
        rec = {"_id": "f1", "name": "ST.pdf"}
        _run(server._enqueue_plan_index("p1", "c1", rec, source="upload"))
        self.job("f1").update(status="failed", pages_done=9)
        _run(server._enqueue_plan_index("p1", "c1", rec, source="reindex_all", resume=True))
        self.assertEqual((self.job("f1")["status"], self.job("f1")["pages_done"]), ("queued", 9))
        _run(server._enqueue_plan_index("p1", "c1", rec, source="reindex_all", resume=False))
        self.assertEqual(self.job("f1")["pages_done"], 0)
        self.assertEqual(len(self.jobs), 1)

    def test_a_file_being_indexed_is_run_again_after_not_raced(self):
        rec = {"_id": "f1", "name": "ST.pdf"}
        _run(server._enqueue_plan_index("p1", "c1", rec, source="upload"))
        self.job("f1").update(status="running", lease_until=_now() + timedelta(minutes=2))
        out = _run(server._enqueue_plan_index("p1", "c1", rec, source="dropbox_sync"))
        self.assertEqual(out, "rerun_after_current")
        self.assertEqual(self.job("f1")["status"], "running")
        self.assertTrue(self.job("f1")["rerun"])


class AClaimTakesOneJobOnALease(_WithDb):

    def _q(self, fid, minutes_ago, **extra):
        row = {"_id": fid, "project_id": "p1", "status": "queued", "not_before": None,
               "enqueued_at": NOW - timedelta(minutes=minutes_ago), "attempts": 0}
        row.update(extra)
        self.jobs.append(row)

    def test_oldest_queued_first_and_the_lease_is_set(self):
        self._q("new", 1)
        self._q("old", 10)
        job = _run(server._claim_plan_index_job("w1"))
        self.assertEqual(job["_id"], "old")
        self.assertEqual((job["status"], job["worker"], job["attempts"]), ("running", "w1", 1))
        self.assertGreater(_utc(job["lease_until"]), NOW)

    def test_a_deferred_job_waits_for_its_time(self):
        self._q("later", 10, not_before=_now() + timedelta(minutes=5))
        self.assertIsNone(_run(server._claim_plan_index_job("w1")))

    def test_a_restart_the_dead_workers_job_is_claimed_again(self):
        """The container died mid-file: status still running, lease not renewed."""
        self._q("f1", 30, status="running", worker="old-container",
                lease_until=NOW - timedelta(seconds=1), attempts=1, pages_done=12)
        job = _run(server._claim_plan_index_job("new-container"))
        self.assertEqual((job["_id"], job["worker"], job["attempts"], job["pages_done"]),
                         ("f1", "new-container", 2, 12))

    def test_a_live_lease_is_not_stolen(self):
        self._q("f1", 30, status="running", worker="w0", lease_until=_now() + timedelta(minutes=2))
        self.assertIsNone(_run(server._claim_plan_index_job("w1")))


class HowAJobEnds(_WithDb):

    def setUp(self):
        super().setUp()
        self.db.project_files.rows.append({"_id": "f1", "project_id": "p1", "name": "ST.pdf",
                                           "company_id": "c1", "r2_key": "k"})
        self.jobs.append({"_id": "f1", "project_id": "p1", "status": "running", "worker": "w1",
                          "attempts": 1, "deferrals": 0, "file_name": "ST.pdf",
                          "lease_until": _now() + timedelta(minutes=2)})

    def _run_with(self, result=None, raises=None):
        calls = []

        async def fake(project_id, company_id, rec, job=None):
            calls.append(job)
            if raises:
                raise raises
            return result

        with mock.patch.object(server, "_index_pdf_file", fake), \
                mock.patch.object(server, "to_query_id", lambda x: x):
            status = _run(server._run_plan_index_job(dict(self.job("f1")), "w1"))
        return status, calls

    def test_done(self):
        status, calls = self._run_with({"outcome": "done"})
        self.assertEqual(status, "done")
        j = self.job("f1")
        self.assertEqual((j["status"], j["lease_until"], j["worker"]), ("done", None, None))
        self.assertEqual(calls[0]["_id"], "f1", "the worker hands the job to the indexer")

    def test_deferred_goes_back_in_the_queue_with_its_profile(self):
        status, _ = self._run_with({"outcome": "deferred", "profile": {"vector_pages": 44}})
        j = self.job("f1")
        self.assertEqual((status, j["status"], j["deferrals"], j["attempts"]), ("queued", "queued", 1, 0))
        self.assertGreater(_utc(j["not_before"]), NOW)
        self.assertEqual(j["profile"], {"vector_pages": 44})

    def test_skipped_and_failed_are_recorded(self):
        self.assertEqual(self._run_with({"outcome": "skipped"})[0], "skipped")
        self.job("f1").update(status="running")
        status, _ = self._run_with(raises=MemoryError("boom"))
        self.assertEqual(status, "failed")
        self.assertIn("MemoryError", self.job("f1")["error"])

    def test_a_file_that_kills_the_container_every_time_stops_being_retried(self):
        self.job("f1")["attempts"] = server.PLAN_INDEX_MAX_ATTEMPTS + 1
        status, calls = self._run_with({"outcome": "done"})
        self.assertEqual((status, calls), ("failed", []))
        self.assertIn("attempts", self.job("f1")["error"])

    def test_a_deleted_file_is_cancelled(self):
        self.db.project_files.rows.clear()
        status, calls = self._run_with({"outcome": "done"})
        self.assertEqual((status, calls), ("cancelled", []))

    def test_a_rerun_requested_while_it_ran_is_queued_again(self):
        self.job("f1")["rerun"] = True
        status, _ = self._run_with({"outcome": "done"})
        j = self.job("f1")
        self.assertEqual((status, j["status"], j["rerun"], j["attempts"]), ("queued", "queued", False, 0))


class TheWorkerWaitsForWhatItNeeds(unittest.TestCase):

    def test_no_poppler_pauses_it_and_says_why(self):
        with mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "_r2_client", object()), \
                mock.patch.object(server, "POPPLER_OK", False), \
                mock.patch.object(server, "POPPLER_DETAIL", "not on PATH"):
            ok, why = server._plan_index_ready()
        self.assertFalse(ok)
        self.assertIn("poppler check failed (not on PATH)", why)

    def test_it_starts_at_boot_after_the_poppler_check(self):
        src = inspect.getsource(server.startup_event)
        self.assertLess(src.index("_check_poppler"), src.index("_plan_index_worker()"))
        self.assertIn("POPPLER CHECK: OK", src)
        self.assertIn("POPPLER CHECK: FAILED", src)


class EveryEntryPointQueues(unittest.TestCase):

    def test_nothing_spawns_indexing_directly(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        calls = [m.start() for m in re.finditer(r"_index_pdf_file\(", src)]
        run_job = inspect.getsource(server._run_plan_index_job)
        self.assertEqual(len(calls), 2, "only the def and the worker's call")
        self.assertIn("_index_pdf_file(", run_job)
        self.assertNotIn("create_task(_index_pdf_file", src)

    def test_upload_sync_and_both_reindex_endpoints_enqueue(self):
        for fn in (server.reindex_project_document, server.reindex_all_project_files):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_enqueue_plan_index(", inspect.getsource(fn))
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn('source="upload"', src)
        self.assertIn('source="dropbox_sync"', src)


class ReindexAllWritesTheQueue(_WithDb):

    def setUp(self):
        super().setUp()
        for fid in ("st", "ar"):
            self.db.project_files.rows.append({"_id": fid, "project_id": "p1", "company_id": "c1",
                                               "name": f"{fid.upper()}.pdf", "r2_key": f"k/{fid}"})
        self.db.document_page_index.rows.append({"file_id": "st", "page_number": 1})

    def _call(self, resume):
        with mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "get_user_company_id", lambda u: "c1"):
            return _run(server.reindex_all_project_files("p1", resume=resume,
                                                         current_user={"id": "u1"}))

    def test_full_reindex_deletes_rows_and_queues_every_file(self):
        out = self._call(resume=False)
        self.assertEqual(out["queued"], 2)
        self.assertEqual({j["_id"]: j["status"] for j in self.jobs}, {"st": "queued", "ar": "queued"})
        self.assertEqual(self.db.document_page_index.rows, [])

    def test_resume_keeps_the_rows(self):
        self._call(resume=True)
        self.assertEqual(len(self.db.document_page_index.rows), 1)
        self.assertTrue(all(j["resume"] for j in self.jobs))


class StatusReadsTheQueueNotTheBucket(_WithDb):

    def test_no_pdf_is_downloaded(self):
        class NoR2:
            def get_object(self, **kw):
                raise AssertionError("document-index-status downloaded a PDF")

        self.db.project_files.rows.extend([
            {"_id": "st", "project_id": "p1", "company_id": "c1", "name": "ST.pdf", "r2_key": "k"},
            {"_id": "old", "project_id": "p1", "company_id": "c1", "name": "OLD.pdf", "r2_key": "k",
             "page_count": 4},
        ])
        self.jobs.append({"_id": "st", "project_id": "p1", "status": "running",
                          "pages_done": 6, "pages_total": 14, "attempts": 1})
        # One of the four is a spec page: it is an indexed page and is counted.
        self.db.document_page_index.rows.extend(
            [{"file_id": "old", "sheet_title": "A"}] * 3
            + [{"file_id": "old", "sheet_title": "[SPECIFICATION PAGE]", "is_spec_page": True}])
        with mock.patch.object(server, "_r2_client", NoR2()), \
                mock.patch.object(server, "get_user_company_id", lambda u: "c1"), \
                mock.patch.object(server, "_is_site_device", lambda u: False):
            out = _run(server.get_document_index_status("p1", current_user={"id": "u1"}))
        by = {f["file_id"]: f for f in out["files"]}
        self.assertEqual((by["st"]["indexed_pages"], by["st"]["total_pages"], by["st"]["queue_status"]),
                         (6, 14, "running"))
        self.assertEqual((by["old"]["indexed_pages"], by["old"]["total_pages"], by["old"]["queue_status"]),
                         (4, 4, "indexed"))


class PopplerIsCheckedForReal(unittest.TestCase):

    def test_missing_binaries(self):
        with mock.patch("shutil.which", lambda name: None):
            ok, detail = server._check_poppler()
        self.assertFalse(ok)
        self.assertIn("not on PATH", detail)

    def test_present_and_rendering(self):
        class Out:
            stderr = "pdftoppm version 25.03.0\nCopyright"
            stdout = ""

        with mock.patch("shutil.which", lambda name: f"/usr/bin/{name}"), \
                mock.patch("subprocess.run", lambda *a, **k: Out()), \
                mock.patch("pdf2image.convert_from_bytes", lambda *a, **k: [object()]):
            ok, detail = server._check_poppler()
        self.assertTrue(ok)
        self.assertIn("pdftoppm version 25.03.0", detail)
        self.assertIn("render self-test passed", detail)

    def test_a_render_that_fails_is_a_failure(self):
        class Out:
            stderr = "pdftoppm version 25.03.0"
            stdout = ""

        def boom(*a, **k):
            raise RuntimeError("Syntax Error")

        with mock.patch("shutil.which", lambda name: f"/usr/bin/{name}"), \
                mock.patch("subprocess.run", lambda *a, **k: Out()), \
                mock.patch("pdf2image.convert_from_bytes", boom):
            ok, detail = server._check_poppler()
        self.assertFalse(ok)
        self.assertIn("render self-test failed", detail)


class MemoryIsBoundedByThePage(unittest.TestCase):

    def test_poppler_writes_the_jpeg_to_disk(self):
        src = inspect.getsource(server._render_pdf_page)
        for needle in ('fmt="jpeg"', "paths_only=True", "output_folder=tmp"):
            with self.subTest(needle=needle):
                self.assertIn(needle, src)

    def test_the_file_is_read_from_disk_one_page_at_a_time(self):
        src = inspect.getsource(server._index_pdf_file)
        self.assertIn("plan_text.file_context, pdf_path", src)
        self.assertIn("plan_text.page_layout_at, pdf_path, page_num", src)
        self.assertIn("del pdf_bytes", src)
        self.assertNotIn("plan_text.page_layouts", src)

    def test_one_file_and_three_pages_at_a_time(self):
        self.assertEqual(server._PDF_INDEX_FILE_SEMAPHORE._value, 1)
        self.assertEqual(server.PLAN_INDEX_BATCH, 3)

    def test_page_layout_and_render_are_prepared_one_at_a_time(self):
        self.assertEqual(server._PLAN_PAGE_PREP_SEMAPHORE._value, 1)
        src = inspect.getsource(server._index_pdf_file)
        guarded = src[src.index("async with _PLAN_PAGE_PREP_SEMAPHORE"):]
        self.assertLess(guarded.index("page_layout_at"), guarded.index("await _index_single_page"))
        self.assertLess(guarded.index("_render_pdf_page"), guarded.index("await _index_single_page"))

    def test_thumbnails_decode_at_reduced_scale(self):
        self.assertIn("img.draft(", inspect.getsource(server._downscale_page_jpeg))


class AFailedRenderIsNotAFinishedPage(_WithDb):

    def test_no_image_leaves_the_page_for_the_next_resume(self):
        _run(server._index_single_page(
            project_id="p1", company_id="c1", file_id="f1", file_name="ST.pdf",
            file_hash="h", page_number=3, discipline="ST", page_text="SHORT",
            page_image_bytes=None))
        row = self.db.document_page_index.rows[0]
        self.assertFalse(row["page_complete"])
        self.assertTrue(row["render_failed"])


if __name__ == "__main__":
    unittest.main()
