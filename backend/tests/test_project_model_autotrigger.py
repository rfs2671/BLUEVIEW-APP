"""Auto-trigger tests: aggregate_project_model runs after plan indexing of a
file completes (the shared _index_pdf_file completion point used by upload +
Dropbox + both re-index endpoints). Uses asyncio.run wrappers (repo convention)
+ hand-mocked server internals; no new deps.
"""

import asyncio
import contextlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── R2 + stateful fake db (only what the code under test touches) ─────
class _Body:
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b


class _R2:
    def get_object(self, Bucket=None, Key=None):
        return {"Body": _Body(b"pdfbytes")}


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):   # operator clause ($gte/$ne/...) — ignore in fake
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, items):
        self._items = list(items)

    async def to_list(self, length=None):
        return [dict(d) for d in self._items]


class _Coll:
    def __init__(self):
        self.docs = []

    def find(self, query):
        return _Cursor([d for d in self.docs if _match(d, query)])

    async def find_one(self, query):
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def update_one(self, flt, update, upsert=False):
        setd = update.get("$set", {})
        for d in self.docs:
            if _match(d, flt):
                d.update(setd)
                return
        if upsert:
            nd = dict(flt)
            nd.update(setd)
            self.docs.append(nd)


class _DB:
    def __init__(self):
        self.document_page_index = _Coll()
        self.project_models = _Coll()


@contextlib.contextmanager
def _patched_server(*, db, agg=None):
    """Patch _index_pdf_file's heavy internals so it reaches its completion
    point cheaply. If `agg` is given, aggregate_project_model is replaced with
    it; otherwise the real aggregator runs (against the fake db)."""
    import server

    isp = AsyncMock()
    saved = {
        "QWEN_API_KEY": server.QWEN_API_KEY,
        "_r2_client": server._r2_client,
        "R2_BUCKET_NAME": server.R2_BUCKET_NAME,
        "db": server.db,
    }
    server.QWEN_API_KEY = "test-key"
    server._r2_client = _R2()
    server.R2_BUCKET_NAME = "bucket"
    server.db = db

    with contextlib.ExitStack() as stack:
        p = stack.enter_context
        p(mock.patch.object(server, "_pdf_total_pages", lambda b: 1))
        p(mock.patch.object(server, "_pdf_page_texts", lambda b: [""]))
        p(mock.patch.object(server, "_render_dpi_for", lambda *a, **k: 200))
        p(mock.patch.object(server, "_render_pdf_page", lambda *a, **k: b"jpeg"))
        p(mock.patch.object(server, "_index_single_page", isp))
        if agg is not None:
            p(mock.patch("app.scheduling.aggregator.aggregate_project_model", agg))
        try:
            yield server, isp
        finally:
            for k, v in saved.items():
                setattr(server, k, v)


async def _drive_index(server, project_id="proj1", file_id="f1"):
    await server._index_pdf_file(
        project_id, "co1",
        {"_id": file_id, "name": "plan_AR.pdf", "r2_key": "k1"},
    )
    # Let the fire-and-forget aggregate task created at completion run.
    for _ in range(20):
        await asyncio.sleep(0)


# ── Tests ────────────────────────────────────────────────────────────
def test_autotrigger_fires_aggregate_once_with_project_id():
    agg = AsyncMock()
    db = MagicMock()
    db.document_page_index.find_one = AsyncMock(return_value=None)  # hash-cache miss
    with _patched_server(db=db, agg=agg) as (server, isp):
        asyncio.run(_drive_index(server))
    agg.assert_awaited_once()
    # aggregate_project_model(db, project_id)
    assert agg.await_args.args[1] == "proj1"
    assert isp.await_count == 1  # the single page was indexed


def test_aggregate_failure_does_not_break_indexing():
    agg = AsyncMock(side_effect=RuntimeError("boom"))
    db = MagicMock()
    db.document_page_index.find_one = AsyncMock(return_value=None)
    with _patched_server(db=db, agg=agg) as (server, isp):
        # Must NOT raise despite the aggregator blowing up.
        asyncio.run(_drive_index(server))
    assert isp.await_count == 1     # indexing completed
    agg.assert_awaited_once()       # trigger attempted, error swallowed


def test_trigger_is_wired_at_shared_completion_point():
    import server
    import inspect
    src = inspect.getsource(server._index_pdf_file)
    assert "asyncio.create_task(_auto_aggregate_project_model(project_id))" in src
    # Convergence: upload + Dropbox + re-index endpoints all spawn _index_pdf_file.
    full = Path(server.__file__).read_text(encoding="utf-8")
    assert full.count("_index_pdf_file(") >= 4  # 1 def + upload + dropbox + reindex


def test_reaggregate_preserves_confirmed_field_via_autotrigger():
    from app.scheduling.aggregator import build_project_model, apply_confirm
    from app.scheduling.project_model import ModelConfirmRequest, ScalarConfirm

    db = _DB()
    # Seed the project's indexed pages (file_id 'pre' so the hash-cache lookup
    # for the incoming file_id 'f1' misses and _index_pdf_file proceeds).
    seed_pages = [
        {"_id": "sp1", "project_id": "proj1", "is_spec_page": False,
         "file_id": "pre", "floor": "3", "discipline": "AR"},
        {"_id": "sp2", "project_id": "proj1", "is_spec_page": False,
         "file_id": "pre", "floor": "2", "discipline": "AR"},
        {"_id": "sp3", "project_id": "proj1", "is_spec_page": False,
         "file_id": "pre", "floor": "1", "discipline": "AR"},
    ]
    db.document_page_index.docs.extend(seed_pages)

    # Prior model with an operator-confirmed override: floors = 99.
    base = build_project_model("proj1", seed_pages, now=FIXED_NOW)
    confirmed = apply_confirm(
        base, ModelConfirmRequest(scalars=[ScalarConfirm(field="floors", value=99)]),
        user_id="op", now=FIXED_NOW,
    )
    db.project_models.docs.append(confirmed.model_dump(mode="python"))

    # Real aggregator (agg=None); a second file finishes indexing → auto-trigger.
    with _patched_server(db=db, agg=None) as (server, isp):
        asyncio.run(_drive_index(server, file_id="f1"))

    stored = db.project_models.docs[0]
    assert stored["floors"] == 99  # operator override preserved (derived would be 3)
    assert stored["field_provenance"]["floors"]["status"] == "confirmed"
    assert len(db.project_models.docs) == 1  # still one current model per project
