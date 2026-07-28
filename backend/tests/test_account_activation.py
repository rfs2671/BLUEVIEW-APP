"""Account activation gating — the server-side cost control.

Verifies: new signups default to pending; existing users backfilled to
approved; pending users are rejected from cost-bearing endpoints BEFORE any
external call; approved users pass; the seeded demo is free + open; admin
approve flips status and non-admins can't.
"""

import asyncio
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
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── require_approved unit tests (the guard itself) ───────────────────
def test_guard_blocks_pending():
    import server
    with pytest.raises(HTTPException) as ei:
        _run(server.require_approved({"account_status": "pending", "role": "admin"}))
    assert ei.value.status_code == 403
    assert ei.value.detail == {"error": "account_pending"}


def test_guard_allows_approved():
    import server
    u = {"account_status": "approved", "role": "worker"}
    assert _run(server.require_approved(u)) is u


def test_guard_grandfathers_missing_field():
    import server
    # Legacy user with no account_status must NOT be locked out.
    u = {"role": "admin"}
    assert _run(server.require_approved(u)) is u


def test_guard_bypasses_site_device():
    import server
    u = {"role": "site_device", "site_mode": True}
    assert _run(server.require_approved(u)) is u


# ── Backfill migration ───────────────────────────────────────────────
def test_backfill_migration_targets_only_missing_field():
    import server
    db = MagicMock()
    db.users.update_many = AsyncMock(return_value=MagicMock(modified_count=3))
    orig = server.db
    server.db = db
    try:
        _run(server.run_account_status_startup_migration())
    finally:
        server.db = orig
    db.users.update_many.assert_awaited_once()
    flt, update = db.users.update_many.await_args.args
    assert flt == {"account_status": {"$exists": False}}       # only legacy docs
    assert update == {"$set": {"account_status": "approved"}}   # never locks out


# ── TestClient helpers ───────────────────────────────────────────────
def _client_with_user(user, *, db=None):
    import server

    async def _fake_user():
        return user

    orig_db = server.db
    orig_company = server.get_user_company_id
    if db is not None:
        server.db = db
    server.get_user_company_id = lambda u: None
    server.app.dependency_overrides[server.get_current_user] = _fake_user

    def _restore():
        server.db = orig_db
        server.get_user_company_id = orig_company
        server.app.dependency_overrides.clear()

    return TestClient(server.app), _restore


# ── Signup defaults to pending ───────────────────────────────────────
def test_signup_defaults_to_pending():
    import server
    db = MagicMock()
    db.users.find_one = AsyncMock(return_value=None)             # email free
    db.users.insert_one = AsyncMock(return_value=MagicMock(inserted_id="newid"))
    orig_db = server.db
    server.db = db
    server.app.dependency_overrides[server.check_auth_rate_limit] = lambda: None
    try:
        client = TestClient(server.app)
        r = client.post("/api/auth/register", json={
            "email": "new@example.com", "password": "pw", "name": "New", "role": "owner",
        })
        assert r.status_code == 200, r.text
        assert r.json()["account_status"] == "pending"
        inserted = db.users.insert_one.await_args.args[0]
        assert inserted["account_status"] == "pending"          # forced server-side
    finally:
        server.db = orig_db
        server.app.dependency_overrides.clear()


# ── Cost endpoint: pending blocked BEFORE external call ──────────────
def test_pending_blocked_on_cost_endpoint_and_no_external_call(monkeypatch):
    import server
    monkeypatch.setattr(server, "run_dob_sync_for_project", AsyncMock())
    client, restore = _client_with_user(
        {"_id": "u1", "id": "u1", "role": "admin", "account_status": "pending"})
    try:
        r = client.post("/api/projects/proj1/dob-sync")
        assert r.status_code == 403
        assert r.json()["detail"] == {"error": "account_pending"}
        # The DOB external sync must NEVER be reached for a pending account.
        server.run_dob_sync_for_project.assert_not_awaited()
    finally:
        restore()


def test_approved_passes_guard_and_reaches_handler(monkeypatch):
    import server
    monkeypatch.setattr(server, "run_dob_sync_for_project", AsyncMock(return_value=[]))
    db = MagicMock()
    db.projects.find_one = AsyncMock(
        return_value={"_id": "proj1", "company_id": "co1", "is_deleted": False,
                      "nyc_bin": "2115914", "address": "852 E 176 St"})
    db.system_config.find_one = AsyncMock(return_value=None)     # no rate-limit hit
    db.system_config.update_one = AsyncMock(return_value=MagicMock())
    client, restore = _client_with_user(
        {"_id": "u1", "id": "u1", "role": "admin", "account_status": "approved",
         "company_id": "co1"}, db=db)
    try:
        r = client.post("/api/projects/proj1/dob-sync")
        assert r.status_code != 403                              # guard did NOT block
        server.run_dob_sync_for_project.assert_awaited_once()    # handler ran
    finally:
        restore()


# ── Seeded demo: free + open to pending ──────────────────────────────
def test_demo_open_to_pending_and_no_external_calls(monkeypatch):
    import server
    # Guard against any accidental external call in the demo path.
    monkeypatch.setattr(server, "run_dob_sync_for_project", AsyncMock())
    if hasattr(server, "fetch_nyc_bin_from_address"):
        monkeypatch.setattr(server, "fetch_nyc_bin_from_address", AsyncMock())
    client, restore = _client_with_user(
        {"_id": "u1", "id": "u1", "role": "owner", "account_status": "pending"})
    try:
        r = client.get("/api/demo/project")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is True
        assert body["dob_summary"]["permits"] == 5
        server.run_dob_sync_for_project.assert_not_awaited()
        if hasattr(server, "fetch_nyc_bin_from_address"):
            server.fetch_nyc_bin_from_address.assert_not_awaited()
    finally:
        restore()


# ── Admin approve ────────────────────────────────────────────────────
def test_admin_approve_flips_status():
    # Approve is tenant-scoped now: actor and target must share a company
    # (or the actor is the platform operator). Two users who merely both
    # LACK a company are NOT the same company — absence is not authorization.
    import server
    db = MagicMock()
    db.users.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    db.users.find_one = AsyncMock(return_value={"_id": "target", "account_status": "approved", "company_id": "c1"})
    client, restore = _client_with_user(
        {"_id": "owner1", "id": "owner1", "role": "owner", "account_status": "approved", "company_id": "c1"}, db=db)
    try:
        r = client.patch("/api/admin/users/target/approve")
        assert r.status_code == 200, r.text
        assert r.json()["account_status"] == "approved"
        setd = db.users.update_one.await_args.args[1]["$set"]
        assert setd["account_status"] == "approved"
    finally:
        restore()


def test_admin_cannot_approve_across_companies():
    """Tenant scoping on the very route that decides who gets un-gated."""
    import server
    db = MagicMock()
    db.users.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    db.users.find_one = AsyncMock(return_value={
        "_id": "target", "account_status": "pending", "company_id": "OTHER"})
    client, restore = _client_with_user(
        {"_id": "owner1", "id": "owner1", "role": "owner",
         "account_status": "approved", "company_id": "c1"}, db=db)
    try:
        r = client.patch("/api/admin/users/target/approve")
        assert r.status_code == 403, r.text
        db.users.update_one.assert_not_awaited()
    finally:
        restore()


def test_non_admin_cannot_approve():
    import server
    client, restore = _client_with_user(
        {"_id": "w1", "id": "w1", "role": "worker", "account_status": "approved"})
    try:
        r = client.patch("/api/admin/users/target/approve")
        assert r.status_code == 403                              # admin gate
        assert r.json()["detail"] != {"error": "account_pending"}  # role, not pending
    finally:
        restore()


def test_pending_admin_cannot_self_approve():
    import server
    client, restore = _client_with_user(
        {"_id": "a1", "id": "a1", "role": "admin", "account_status": "pending"})
    try:
        r = client.patch("/api/admin/users/a1/approve")
        assert r.status_code == 403
        assert r.json()["detail"] == {"error": "account_pending"}
    finally:
        restore()
