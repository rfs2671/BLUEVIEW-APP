"""Behavioral wiring test — POST /api/projects spawns prewarm_peer_stats.

Replaces the two SOURCE-TEXT anchor tests that used to live in
tests/test_v2_2_schema_scaffolding.py::TestServerPyV23PrewarmWiring
(``test_create_project_endpoint_spawns_prewarm`` and
``test_create_project_endpoint_wraps_spawn_in_try_except``). Those matched
server.py's text against the substring anchor

    @api_router.post("/projects", response_model=ProjectResponse)

which silently broke on 2026-07-19 when the decorator gained
``dependencies=[Depends(require_approved)]``. The production spawn was never
touched — the anchor just stopped matching — and, worse, the anchor lookup
fails *before* the spawn is ever checked, so the tests would have failed
identically had the spawn actually been deleted. They stopped guarding the
behavior they existed to guard.

This test drives the real endpoint through TestClient and asserts on
BEHAVIOR: that create_project spawns exactly one asyncio task carrying the
``prewarm_peer_stats`` coroutine, tagged with the new project id, and that a
spawn failure is swallowed so project creation still returns 200 and still
persists. It FAILS if the spawn is removed; it does NOT care about decorator
kwargs, handler formatting, or where the try/except block sits.

Isolation: ``asyncio.create_task`` is patched globally, but the side effect
intercepts ONLY the prewarm coroutine and delegates every other coroutine to
the real implementation, so framework/task-group internals keep working.
Overrides and server.db are restored in teardown (per the pattern audited in
docs/audits/test-isolation-2026-07-23.md).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

# Captured before any monkeypatch so the side effect can delegate real
# (non-prewarm) task spawns back to the framework.
_REAL_CREATE_TASK = asyncio.create_task

_APPROVED_ADMIN = {
    "_id": "admin1",
    "id": "admin1",
    "role": "admin",
    "account_status": "approved",
    "company_id": "co1",
    "company_name": "Acme Co",
}

_INSERTED_ID = "pid_behavioral_123"


def _make_side_effect(*, raise_on_prewarm: bool):
    """Return an asyncio.create_task replacement that intercepts ONLY the
    prewarm coroutine (closing it so it is never actually run, optionally
    raising to simulate a spawn failure) and delegates everything else to the
    real create_task so the ASGI machinery is unaffected."""
    def _side_effect(coro, *args, **kwargs):
        if getattr(coro, "__qualname__", "") == "prewarm_peer_stats":
            coro.close()  # we assert on the call, never run the coroutine
            if raise_on_prewarm:
                raise RuntimeError("simulated create_task failure")
            return MagicMock(name="fake_prewarm_task")
        return _REAL_CREATE_TASK(coro, *args, **kwargs)
    return _side_effect


def _prewarm_calls(create_task_mock):
    """The subset of create_task calls whose coroutine is prewarm_peer_stats."""
    return [
        c for c in create_task_mock.call_args_list
        if c.args and getattr(c.args[0], "__qualname__", "") == "prewarm_peer_stats"
    ]


def _wire(monkeypatch, *, raise_on_prewarm=False):
    """Stand up server.app with DB, audit_log, and the BIN lookup mocked so
    POST /api/projects reaches the prewarm spawn with zero external calls.

    get_current_user is overridden with an approved admin — it feeds BOTH the
    handler's get_admin_user and the route's require_approved dependency — and
    require_approved is additionally overridden as a passthrough so the test
    does not depend on how the approval gate is wired. Returns
    (TestClient, db_mock, create_task_mock, restore)."""
    import server

    db = MagicMock()
    db.projects.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=_INSERTED_ID))

    async def _fake_user():
        return dict(_APPROVED_ADMIN)

    orig_db = server.db
    server.db = db
    monkeypatch.setattr(server, "audit_log", AsyncMock())
    monkeypatch.setattr(
        server, "fetch_nyc_bin_from_address",
        AsyncMock(return_value={"nyc_bin": None}))

    create_task_mock = MagicMock(
        side_effect=_make_side_effect(raise_on_prewarm=raise_on_prewarm))
    monkeypatch.setattr(asyncio, "create_task", create_task_mock)

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    server.app.dependency_overrides[server.require_approved] = lambda: None

    def _restore():
        server.db = orig_db
        server.app.dependency_overrides.clear()

    return TestClient(server.app), db, create_task_mock, _restore


def test_create_project_spawns_prewarm_task(monkeypatch):
    """POST /api/projects spawns exactly one prewarm_peer_stats task, tagged
    with the freshly-inserted project id."""
    client, _db, create_task_mock, restore = _wire(monkeypatch)
    try:
        r = client.post(
            "/api/projects", json={"name": "Behavioral Test Project"})
        assert r.status_code == 200, r.text
        assert r.json()["id"] == _INSERTED_ID

        prewarm = _prewarm_calls(create_task_mock)
        assert len(prewarm) == 1, (
            "expected exactly one prewarm_peer_stats task spawn, "
            f"got {len(prewarm)}")
        (coro,), kwargs = prewarm[0].args, prewarm[0].kwargs
        assert coro.__qualname__ == "prewarm_peer_stats"
        assert kwargs.get("name") == f"prewarm_peer_stats:{_INSERTED_ID}"
    finally:
        restore()


def test_create_project_survives_prewarm_spawn_failure(monkeypatch):
    """If spawning the prewarm task raises, the handler's try/except swallows
    it: the project is still created, the endpoint still returns 200, and the
    failure is logged for operators."""
    import server

    warnings = []
    monkeypatch.setattr(
        server.logger, "warning",
        lambda msg, *a, **k: warnings.append(str(msg)))

    client, db, create_task_mock, restore = _wire(
        monkeypatch, raise_on_prewarm=True)
    try:
        r = client.post(
            "/api/projects", json={"name": "Behavioral Test Project"})
        # Spawn raised, but project creation still succeeded end-to-end.
        assert r.status_code == 200, r.text
        assert r.json()["id"] == _INSERTED_ID
        # The project was actually persisted (not short-circuited by the raise).
        db.projects.insert_one.assert_awaited_once()
        # The spawn was attempted exactly once...
        assert len(_prewarm_calls(create_task_mock)) == 1
        # ...and the swallow was logged so operators can grep it.
        assert any("prewarm task spawn failed" in m for m in warnings), warnings
    finally:
        restore()
