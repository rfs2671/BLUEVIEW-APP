"""Endpoint tests for the scheduling spine (TestClient + stateful fake db)."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from app.scheduling.project_model import (  # noqa: E402
    ProjectModel, Zone, SpecialInspection, FieldProvenance,
)

FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, key, direction=-1):
        self._items = sorted(self._items, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        items = self._items[:length] if length else self._items
        return [dict(d) for d in items]


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

    async def insert_one(self, doc):
        d = dict(doc)
        d.setdefault("_id", f"id{len(self.docs)}")
        self.docs.append(d)
        return type("R", (), {"inserted_id": d["_id"]})()


class _DB:
    def __init__(self):
        self.projects = _Coll()
        self.project_models = _Coll()
        self.sequence_graph = _Coll()
        self.project_schedules = _Coll()


def _seed_project_model(*, proposed_si=False):
    conf = FieldProvenance(source="operator_declared", confidence="high", status="confirmed")
    prop = FieldProvenance(source="plan_seeded", confidence="low", status="proposed")
    si = []
    if proposed_si:
        si = [SpecialInspection(id="si_firestopping", inspection_type="firestopping",
                                provenance=prop)]
    return ProjectModel(
        project_id="proj1", floors=2, has_gas=True, has_sprinkler=True,
        has_standpipe=True, has_elevator=False,
        zones=[Zone(id="A", floors=[1, 2], is_tco_phase=False, provenance=conf)],
        special_inspections=si, aggregated_at=FIXED_NOW,
    )


def _client(*, model=None):
    import server
    db = _DB()
    db.projects.docs.append({"_id": "proj1", "company_id": "co1", "is_deleted": False})
    if model is not None:
        db.project_models.docs.append(model.model_dump(mode="python"))

    user = {"_id": "u_op", "id": "u_op", "role": "admin", "company_id": "co1"}

    async def _fake_user():
        return user

    orig_db, orig_company = server.db, server.get_user_company_id
    server.db = db
    server.get_user_company_id = lambda u: "co1"
    server.app.dependency_overrides[server.get_current_user] = _fake_user

    def _restore():
        server.db = orig_db
        server.get_user_company_id = orig_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), db, _restore


def test_generate_then_get_roundtrip():
    client, db, restore = _client(model=_seed_project_model())
    try:
        r = client.post("/api/projects/proj1/schedule/generate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["schedule"]["graph_version"] == "graph_v1"
        assert len(body["schedule"]["phases"]) > 0
        assert body["warnings"] == []                      # all confirmed
        assert len(db.project_schedules.docs) == 1
        assert len(db.sequence_graph.docs) == 1            # seed graph upserted
        g = client.get("/api/projects/proj1/schedule")
        assert g.status_code == 200
        assert g.json()["graph_version"] == "graph_v1"
    finally:
        restore()


def test_generate_without_project_model_is_404():
    client, db, restore = _client(model=None)
    try:
        assert client.post("/api/projects/proj1/schedule/generate").status_code == 404
    finally:
        restore()


def test_get_before_generate_is_404():
    client, db, restore = _client(model=_seed_project_model())
    try:
        assert client.get("/api/projects/proj1/schedule").status_code == 404
    finally:
        restore()


def test_unconfirmed_input_surfaces_in_warnings_but_still_generates():
    client, db, restore = _client(model=_seed_project_model(proposed_si=True))
    try:
        r = client.post("/api/projects/proj1/schedule/generate")
        assert r.status_code == 200, r.text
        body = r.json()
        # Schedule still generated...
        assert len(body["schedule"]["phases"]) > 0
        # ...and the proposed special inspection surfaces as a warning.
        kinds = {(w["kind"], w.get("id")) for w in body["warnings"]}
        assert ("special_inspection", "si_firestopping") in kinds
    finally:
        restore()
