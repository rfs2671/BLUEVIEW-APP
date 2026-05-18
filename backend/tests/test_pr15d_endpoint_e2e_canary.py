"""PR #15D — end-to-end canary tests through FastAPI TestClient.

5 tests. Uses the 5 saved Stage 1 fixtures + a motor-mock db so
the FastAPI handler reads real Atlas project shapes.

Pattern: dependency_overrides for both get_current_user AND for the
db dependency (if extracted), OR monkey-patch the module-level db
to a stub for the duration of the test.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from bson import ObjectId  # noqa: E402

from _pr15d_prediction_cache_loader import (  # noqa: E402
    load_prediction_cache_fixture,
)


def _try_import():
    try:
        from fastapi.testclient import TestClient
        import server
        return TestClient, server
    except ImportError:
        return None


_setup = _try_import()


def _endpoint_registered(server_mod) -> bool:
    if server_mod is None:
        return False
    for route in server_mod.app.routes:
        if hasattr(route, "path") and "/prediction" in route.path \
                and "{project_id}" in route.path:
            return True
    return False


class _AsyncFindReturn:
    """Coroutine-returning shim for db.projects.find_one."""
    def __init__(self, doc):
        self.doc = doc
    async def __call__(self, filter_, projection=None):
        return self.doc


class TestE2ECanary(unittest.TestCase):
    """End-to-end canary: real project shapes from Stage 1 +
    FastAPI handler + Pydantic serialization."""

    def _require_endpoint(self):
        if _setup is None or not _endpoint_registered(_setup[1]):
            self.fail(
                "Stage 3 PR #15D: register GET /api/projects/"
                "{project_id}/prediction. See "
                "test_pr15d_prediction_endpoint_auth.py for the "
                "endpoint contract spec."
            )

    def _authed_client(self, *, company_id="co_a"):
        """Set up TestClient with dependency_overrides for the
        current_user. Caller is responsible for clearing
        overrides via the returned tearer."""
        TestClient, server_mod = _setup
        async def _user():
            return {"id": "u1", "_id": "u1", "role": "admin",
                    "company_id": company_id}
        server_mod.app.dependency_overrides[
            server_mod.get_current_user
        ] = _user
        return TestClient(server_mod.app, raise_server_exceptions=False), \
            lambda: server_mod.app.dependency_overrides.clear()

    def _patch_db_for_project(self, project_doc):
        """Patch server.db with a MagicMock so the endpoint's
        ``db.projects.find_one`` call returns ``project_doc``.

        Why patch ``server.db`` (not ``server.db.projects.find_one``):
        Motor's ``AsyncIOMotorDatabase.__getattr__`` returns a fresh
        ``AsyncIOMotorCollection`` on every access (verified locally —
        ``server.db.projects is server.db.projects`` is False). So
        patching ``find_one`` on a transient collection instance does
        not affect subsequent ``db.projects`` accesses inside the
        endpoint. Replacing the whole ``db`` attribute with a single
        MagicMock fixes that — the proven pattern from
        ``test_b1c_endpoints.py:162``.

        We also stub ``to_query_id`` to pass the id through verbatim,
        so the test doesn't depend on ObjectId parsing.

        Returns a context manager to use with `with`."""
        TestClient, server_mod = _setup
        mock_db = MagicMock()
        mock_db.projects = MagicMock()
        mock_db.projects.find_one = AsyncMock(return_value=project_doc)

        class _CM:
            def __enter__(self_inner):
                self_inner.p1 = patch.object(server_mod, "db", mock_db)
                self_inner.p2 = patch.object(
                    server_mod, "to_query_id",
                    side_effect=lambda x: x,
                )
                self_inner.p1.start()
                self_inner.p2.start()
                return mock_db

            def __exit__(self_inner, *exc):
                self_inner.p2.stop()
                self_inner.p1.stop()
                return False

        return _CM()

    def test_e2e_menahan_returns_expected_payload(self):
        self._require_endpoint()
        TestClient, server_mod = _setup
        project = load_prediction_cache_fixture("menahan")
        # Ensure company_id matches the test user's "co_a"
        project["company_id"] = "co_a"
        client, restore = self._authed_client()
        try:
            with self._patch_db_for_project(project):
                r = client.get(
                    f"/api/projects/{project['_id']}/prediction"
                )
            self.assertEqual(
                r.status_code, 200,
                msg=f"E2E Menahan: expected 200, got {r.status_code}. "
                    f"Body: {r.text[:500]}",
            )
            body = r.json()
            self.assertTrue(body.get("prediction_available"))
            self.assertEqual(body["confidence"]["sample_size"], 85)
            self.assertEqual(
                body["anchored_baseline"]["label"],
                "BROOKLYN major_alt_with_enlargement macro baseline",
            )
            self.assertEqual(
                body["metadata"]["schema_version"], "pr15b_v1",
            )
        finally:
            restore()

    def test_e2e_boyland_cold_start_returns_borough_baseline(self):
        self._require_endpoint()
        TestClient, server_mod = _setup
        project = load_prediction_cache_fixture("boyland")
        project["company_id"] = "co_a"
        client, restore = self._authed_client()
        try:
            with self._patch_db_for_project(project):
                r = client.get(
                    f"/api/projects/{project['_id']}/prediction"
                )
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(
                body["confidence"]["is_cold_start"],
                msg="Boyland (n=0) → is_cold_start=True",
            )
            self.assertEqual(
                body["confidence"]["badge"], "cold_start",
                msg="Boyland → badge='cold_start'",
            )
            self.assertGreater(
                body["horizons"]["prob_7d"], 0,
                msg="Boyland prob_7d > 0 via borough actuarial baseline",
            )
        finally:
            restore()

    def test_e2e_returns_404_for_unknown_id(self):
        self._require_endpoint()
        client, restore = self._authed_client()
        try:
            # Patch server.db so find_one returns None — simulates
            # unknown ObjectId. Same MagicMock pattern as
            # _patch_db_for_project; see that docstring for rationale.
            with self._patch_db_for_project(None):
                r = client.get(
                    "/api/projects/aaaaaaaaaaaaaaaaaaaaaaaa/prediction"
                )
            self.assertEqual(
                r.status_code, 404,
                msg=f"Unknown project_id → 404. Got {r.status_code}",
            )
        finally:
            restore()

    def test_e2e_returns_403_for_different_company(self):
        self._require_endpoint()
        TestClient, server_mod = _setup
        project = load_prediction_cache_fixture("menahan")
        # User is in co_a, project belongs to co_DIFFERENT
        project["company_id"] = "co_DIFFERENT"
        client, restore = self._authed_client(company_id="co_a")
        try:
            with self._patch_db_for_project(project):
                r = client.get(
                    f"/api/projects/{project['_id']}/prediction"
                )
            self.assertEqual(
                r.status_code, 403,
                msg=f"Cross-company access → 403 (mirrors server.py:"
                    f"6957-6959 pattern). Got {r.status_code}. "
                    f"Body: {r.text[:200]}",
            )
        finally:
            restore()

    def test_e2e_response_content_type_is_application_json(self):
        self._require_endpoint()
        project = load_prediction_cache_fixture("menahan")
        project["company_id"] = "co_a"
        client, restore = self._authed_client()
        try:
            with self._patch_db_for_project(project):
                r = client.get(
                    f"/api/projects/{project['_id']}/prediction"
                )
            self.assertEqual(r.status_code, 200)
            self.assertIn(
                "application/json",
                r.headers.get("content-type", ""),
                msg=f"Content-Type must be application/json. Got "
                    f"{r.headers.get('content-type')!r}",
            )
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
