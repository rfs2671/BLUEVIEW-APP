"""R2 objects destroyed by a delete path that said it would not destroy them.

Three places where the deletion code's OWN STATED INTENT and its behaviour
disagree. None of these needs a retention ruling — each is the code failing to
do the thing its docstring or its sibling comment says it does.

  1. DELETE /projects/{id}/files/{file_id} — the docstring has always read
     "For Dropbox-synced files we only remove the Mongo row — Dropbox is the
     source of truth there". The handler deleted the R2 object unconditionally.

  2. THE SAME ROUTE, THE SHARED KEY. A file's R2 key is
     `{company_id}/{project_id}/{filename}` — the BASENAME only, no path
     component. The direct-upload path de-duplicates on name and suffixes a
     timestamp so it can never overwrite; the Dropbox sync path does NOT, and
     keys the row on `dropbox_path` instead. So two rows for
     `/Drawings/A/plan.pdf` and `/Drawings/B/plan.pdf` are TWO rows addressing
     ONE object. Deleting either row destroyed the shared bytes, and the
     surviving row then pointed at nothing.

     THE LOSS IS PERMANENT, not merely temporary. Sync would not restore it:
     the surviving row's `dropbox_content_hash` still matches Dropbox, so the
     sync takes its "Unchanged — just update last_synced_at" branch and never
     re-uploads. Nobody deleted that file and nobody is told it is gone.

  3. hard_delete_project — "Physically removes the project and every document,
     storage object and config key it owns", while the file scan is capped at
     `to_list(5000)`. Past 5000 files the page-index rows orphan with nothing
     left to find them by (project_files is deleted straight after), and on a
     company-less project the objects orphan too, because the
     `{company_id}/{project_id}/` prefix sweep is skipped when company_id is
     falsy and the per-row loop is the only thing that would have caught them.

  4. hard_delete_project's logbook-photo sweep. The capture-scheme key writer
     runs every segment through `_logbook_photo_key_segment`; the sweep built
     its prefix from the RAW project id. Two comments in the key-writer region
     promise the cascade sweeps both photo schemes "with one unconditional
     prefix" — a prefix computed a different way than the keys were written
     cannot make that promise.

    python -m pytest backend/tests/test_delete_paths_r2_object_loss.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
         "account_status": "approved"}

PROJECT_ID = "projA"
FILE_ID = "6a8c4acd0000000000000002"
SHARED_KEY = "companyA/projA/plan.pdf"


class _R2Spy:
    """Records every delete_object / list_objects_v2 the code performs."""

    def __init__(self, listing=None):
        self.deleted = []           # list of (bucket, key)
        self.listed = []            # list of (bucket, prefix)
        self._listing = listing or {}

    def delete_object(self, Bucket=None, Key=None, **kw):
        self.deleted.append((Bucket, Key))
        return {}

    def list_objects_v2(self, Bucket=None, Prefix=None, **kw):
        self.listed.append((Bucket, Prefix))
        keys = self._listing.get(Prefix, [])
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    @property
    def deleted_keys(self):
        return [k for _b, k in self.deleted]


# ── 1 + 2: the single-file delete route ─────────────────────────────────────

def _run_file_delete(rec, siblings=0, r2=None):
    """Call delete_project_file for `rec`, with `siblings` OTHER live rows
    sharing its r2_key. Returns (response, r2_spy)."""
    spy = r2 if r2 is not None else _R2Spy()
    db = MagicMock()
    db.project_files.find_one = AsyncMock(
        side_effect=lambda q, *a, **kw: dict(rec) if rec is not None else None)
    db.project_files.delete_one = AsyncMock(
        return_value=MagicMock(deleted_count=1))
    db.project_files.count_documents = AsyncMock(return_value=siblings)
    with patch.object(server, "db", db), \
         patch.object(server, "_r2_client", spy), \
         patch.object(server, "R2_BUCKET_NAME", "bucket"):
        res = asyncio.run(server.delete_project_file(
            project_id=PROJECT_ID, file_id=FILE_ID, current_user=ADMIN))
    return res, spy, db


def _row(**over):
    base = {"_id": FILE_ID, "project_id": PROJECT_ID, "company_id": "companyA",
            "r2_key": SHARED_KEY, "name": "plan.pdf"}
    base.update(over)
    return base


class DropboxSyncedFileKeepsItsObject(unittest.TestCase):
    """THE DOCSTRING'S OWN CLAIM, made true."""

    def test_a_dropbox_synced_row_does_not_delete_the_r2_object(self):
        res, spy, _db = _run_file_delete(
            _row(dropbox_path="/Drawings/A/plan.pdf"))
        self.assertEqual(
            spy.deleted_keys, [],
            "the docstring says a Dropbox-synced file loses only its Mongo "
            "row; the object must survive",
        )
        self.assertFalse(res["r2_deleted"])

    def test_the_mongo_row_still_goes(self):
        """Only the OBJECT is spared. The row is what the admin asked to
        remove and the file must stop appearing."""
        res, _spy, db = _run_file_delete(
            _row(dropbox_path="/Drawings/A/plan.pdf"))
        db.project_files.delete_one.assert_awaited()
        self.assertTrue(res["mongo_deleted"])

    def test_a_direct_upload_is_untouched_by_the_dropbox_rule(self):
        """REGRESSION GUARD. A row with no dropbox_path and no sibling is the
        sole owner of its bytes; sparing it would leak an orphan forever."""
        res, spy, _db = _run_file_delete(_row())
        self.assertEqual(spy.deleted_keys, [SHARED_KEY])
        self.assertTrue(res["r2_deleted"])


class ASharedKeyIsNotDestroyed(unittest.TestCase):
    """The basename collision: two rows, one object."""

    def test_the_object_survives_while_another_live_row_points_at_it(self):
        res, spy, _db = _run_file_delete(_row(), siblings=1)
        self.assertEqual(
            spy.deleted_keys, [],
            "another live project_files row still addresses this object — "
            "deleting it strands that row on bytes that no longer exist",
        )
        self.assertFalse(res["r2_deleted"])

    def test_the_sibling_query_excludes_this_row_and_soft_deleted_rows(self):
        """The count must not find the row being deleted (which would spare
        every object forever) nor a soft-deleted one (which is not a live
        reference)."""
        _res, _spy, db = _run_file_delete(_row(), siblings=0)
        db.project_files.count_documents.assert_awaited()
        q = db.project_files.count_documents.await_args.args[0]
        self.assertEqual(q.get("r2_key"), SHARED_KEY)
        self.assertIn("$ne", q.get("_id", {}))
        self.assertEqual(q.get("is_deleted"), {"$ne": True})

    def test_a_row_with_no_key_never_asks_and_never_deletes(self):
        res, spy, db = _run_file_delete(_row(r2_key=""))
        self.assertEqual(spy.deleted_keys, [])
        self.assertFalse(res["r2_deleted"])
        db.project_files.count_documents.assert_not_awaited()


# ── 3 + 4: the project purge ────────────────────────────────────────────────

class _Find:
    """A cursor whose to_list HONOURS its length argument, the way Motor's
    does. A fake that ignored it could not show the 5000 cap at all."""

    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs) if length is None else list(self._docs)[:length]


def _run_hard_delete(project, file_docs=(), r2=None):
    spy = r2 if r2 is not None else _R2Spy()
    db = MagicMock()
    db.projects.find_one = AsyncMock(return_value=dict(project))
    db.projects.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    db.project_files.find = MagicMock(return_value=_Find(file_docs))

    seen = {}

    def _coll(name):
        if name not in seen:
            c = MagicMock()
            c.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
            c.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
            seen[name] = c
        return seen[name]

    db.__getitem__.side_effect = _coll
    db.document_page_index = _coll("document_page_index")
    db.workers = _coll("workers")
    db.users = _coll("users")
    db.system_config = _coll("system_config")
    db.audit_logs = _coll("audit_logs")

    owner = {"_id": "own1", "id": "own1", "role": "owner",
             "company_id": project.get("company_id")}
    # The caller is the PLATFORM OPERATOR here. Not to dodge the tenant gate —
    # that gate has its own suite — but because a company-less project is
    # precisely the case only the operator can purge: the non-operator branch
    # refuses a caller with no company outright, so the orphaned project these
    # tests are about is unreachable any other way.
    with patch.object(server, "db", db), \
         patch.object(server, "is_platform_operator", lambda u: True), \
         patch.object(server, "_r2_client", spy), \
         patch.object(server, "R2_BUCKET_NAME", "bucket"), \
         patch.object(server, "audit_log", AsyncMock()):
        res = asyncio.run(server.hard_delete_project(
            project_id=project["_id"], owner=owner))
    return res, spy, seen


class HardDeleteCollectsEveryFile(unittest.TestCase):
    """"every document, storage object and config key it owns" — every."""

    N = 5200        # past the to_list(5000) cap

    def _big_project(self):
        # company_id deliberately ABSENT: that is the shape where the per-row
        # loop is the ONLY thing that would delete these objects, because the
        # `{company_id}/{project_id}/` prefix sweep is skipped entirely.
        return {"_id": PROJECT_ID, "name": "Big Tower", "company_id": ""}

    def _files(self):
        return [{"_id": f"f{i}", "r2_key": f"/projA/doc{i}.pdf"}
                for i in range(self.N)]

    def test_every_file_id_reaches_the_page_index_sweep(self):
        _res, _spy, colls = _run_hard_delete(self._big_project(), self._files())
        q = colls["document_page_index"].delete_many.await_args.args[0]
        self.assertEqual(
            len(q["file_id"]["$in"]), self.N,
            "file ids past the cap orphan their document_page_index rows with "
            "nothing left to find them by — project_files is deleted next",
        )

    def test_every_file_object_is_deleted_from_r2(self):
        _res, spy, _colls = _run_hard_delete(self._big_project(), self._files())
        per_row = [k for k in spy.deleted_keys if k.startswith("/projA/")]
        self.assertEqual(
            len(per_row), self.N,
            "on a company-less project the per-row loop is the only sweep "
            "that reaches these objects",
        )


class LogbookPhotoSweepMatchesTheWriter(unittest.TestCase):
    """The sweep prefix has to be built the way the keys were."""

    def test_the_sweep_prefix_uses_the_key_segment_function(self):
        pid = "proj a/b"          # every char the segment function rewrites
        project = {"_id": pid, "name": "Odd", "company_id": "companyA"}
        _res, spy, _colls = _run_hard_delete(project)
        expected = (
            f"logbook-photos/{server._logbook_photo_key_segment(pid)}/")
        self.assertIn(
            expected, [p for _b, p in spy.listed],
            "the capture-scheme writer sanitises the project segment; a sweep "
            "built from the raw id lists a prefix no photo was ever written "
            "under, and the photos survive the purge that claimed them",
        )

    def test_the_ordinary_case_is_unchanged(self):
        """An ObjectId-shaped id passes through the segment function
        untouched, so nothing about the normal purge moves."""
        project = {"_id": PROJECT_ID, "name": "T", "company_id": "companyA"}
        _res, spy, _colls = _run_hard_delete(project)
        prefixes = [p for _b, p in spy.listed]
        self.assertIn(f"logbook-photos/{PROJECT_ID}/", prefixes)
        self.assertIn(f"plans/{PROJECT_ID}/", prefixes)
        self.assertIn(f"companyA/{PROJECT_ID}/", prefixes)


if __name__ == "__main__":
    unittest.main()
