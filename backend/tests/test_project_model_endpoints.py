"""Endpoint tests for the ProjectModel aggregator via TestClient + a stateful
in-memory fake db (no mongomock dependency, matching the repo's hand-rolled
fake-db convention). Covers aggregate / get / confirm / unconfirmed and a
persistence merge round-trip."""

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ── Minimal stateful async fake db ───────────────────────────────────
def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):   # operator clause ($ne, $in, ...) — ignore in fake
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
        self.projects = _Coll()
        self.document_page_index = _Coll()
        self.project_models = _Coll()


def _page(pid, **kw):
    base = {
        "_id": pid, "project_id": "proj1", "is_spec_page": False,
        "discipline": None, "floor": None, "sheet_title": None, "summary": None,
        "notes": None, "materials": None, "spaces": None, "code_refs": None,
    }
    base.update(kw)
    return base


def _client(pages):
    import server

    db = _DB()
    db.projects.docs.append({"_id": "proj1", "company_id": "co1", "is_deleted": False})
    db.document_page_index.docs.extend(pages)

    user = {"_id": "u_op", "id": "u_op", "role": "admin", "company_id": "co1"}

    async def _fake_user():
        return user

    original_db = server.db
    original_company = server.get_user_company_id
    server.db = db
    server.get_user_company_id = lambda u: "co1"
    server.app.dependency_overrides[server.get_current_user] = _fake_user

    def _restore():
        server.db = original_db
        server.get_user_company_id = original_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), db, _restore


def test_aggregate_then_get_returns_proposed_model():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    client, db, restore = _client(pages)
    try:
        r = client.post("/api/projects/proj1/model/aggregate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == "proj1"
        assert body["field_provenance"]["has_sprinkler"]["status"] == "proposed"
        assert any(si["inspection_type"] == "firestopping" for si in body["special_inspections"])
        # persisted → GET returns the same model
        assert len(db.project_models.docs) == 1
        g = client.get("/api/projects/proj1/model")
        assert g.status_code == 200
        assert g.json()["floors"] == 4
    finally:
        restore()


def test_get_before_aggregate_is_404():
    client, db, restore = _client([_page("p1")])
    try:
        assert client.get("/api/projects/proj1/model").status_code == 404
    finally:
        restore()


def test_confirm_sets_confirmed_and_stamps_user():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    client, db, restore = _client(pages)
    try:
        client.post("/api/projects/proj1/model/aggregate")
        r = client.patch("/api/projects/proj1/model/confirm", json={
            "scalars": [{"field": "has_gas", "value": True}],
            "special_inspection_ids": ["si_firestopping"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_gas"] is True
        assert body["field_provenance"]["has_gas"]["status"] == "confirmed"
        assert body["field_provenance"]["has_gas"]["last_confirmed_by"] == "u_op"
        assert body["field_provenance"]["has_gas"]["last_confirmed_at"] is not None
        si = next(s for s in body["special_inspections"] if s["id"] == "si_firestopping")
        assert si["provenance"]["status"] == "confirmed"
    finally:
        restore()


def test_confirm_unknown_type_rejected_422():
    pages = [_page("p1"), _page("p2"), _page("p3")]
    client, db, restore = _client(pages)
    try:
        client.post("/api/projects/proj1/model/aggregate")
        r = client.patch("/api/projects/proj1/model/confirm",
                         json={"special_inspection_types": ["bogus_type"]})
        assert r.status_code == 422
        assert "bogus_type" in r.text
    finally:
        restore()


def test_unconfirmed_lists_only_proposed():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    client, db, restore = _client(pages)
    try:
        client.post("/api/projects/proj1/model/aggregate")
        client.patch("/api/projects/proj1/model/confirm", json={
            "scalars": [{"field": "has_gas", "value": False}],
            "special_inspection_ids": ["si_firestopping"],
        })
        r = client.get("/api/projects/proj1/model/unconfirmed")
        assert r.status_code == 200
        view = r.json()
        fields = {s["field"] for s in view["scalars"]}
        assert "has_gas" not in fields
        assert "floors" in fields
        assert "si_firestopping" not in {si["id"] for si in view["special_inspections"]}
    finally:
        restore()


def test_reaggregate_preserves_confirmed_via_persistence():
    pages = [_page("p1", notes="firestopping"), _page("p2", floor="4"), _page("p3", discipline="SP")]
    client, db, restore = _client(pages)
    try:
        client.post("/api/projects/proj1/model/aggregate")
        client.patch("/api/projects/proj1/model/confirm",
                     json={"scalars": [{"field": "floors", "value": 99}]})
        # Re-run aggregation; the confirmed override must persist.
        r = client.post("/api/projects/proj1/model/aggregate")
        assert r.status_code == 200
        body = r.json()
        assert body["floors"] == 99
        assert body["field_provenance"]["floors"]["status"] == "confirmed"
        assert len(db.project_models.docs) == 1  # still one current model per project
    finally:
        restore()
