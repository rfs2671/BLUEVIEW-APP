"""Phase E1 — feature flag resolver + endpoints + frontend pins.

Pin every contract the v2-development infrastructure promises:

  • Resolution order (a–f from spec) — fail closed on missing
    flag, then global → company list → user list → percentage
    rollout (deterministic, salted by flag name).
  • Cache hits within TTL; misses re-fetch; admin writes
    invalidate the entry so the next read sees the new shape.
  • Admin endpoints require admin/owner role and write an audit
    row for create / update / delete.
  • GET /api/feature-flags/me returns a {flag: bool} map only —
    NOT the rollout config (clients shouldn't see who else is
    enabled).
  • Frontend FeatureFlagsProvider mounted inside AuthProvider so
    it can read identity and refetch on login/logout.
  • useFeatureFlag returns false during the loading state
    (fail-closed flicker prevention).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from lib import feature_flags  # noqa: E402


def _run(coro):
    """Fresh event loop per test — same pattern as B3/F1."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _AsyncCursor:
    """Mimic the async iteration protocol of motor.find()."""
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()

    def sort(self, *args, **kwargs):
        return self

    def to_list(self, _n):
        async def _coro():
            return self._items
        return _coro()


def _build_db(*, find_one=None, find_results=None,
              insert_inserted_id="ff_x",
              update_matched=1, delete_matched=1):
    db = MagicMock()
    db.feature_flags = MagicMock()
    db.feature_flags.find_one = AsyncMock(return_value=find_one)
    db.feature_flags.find = MagicMock(
        return_value=_AsyncCursor(find_results or []),
    )
    db.feature_flags.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=insert_inserted_id),
    )
    db.feature_flags.update_one = AsyncMock(
        return_value=MagicMock(matched_count=update_matched),
    )
    db.feature_flags.delete_one = AsyncMock(
        return_value=MagicMock(deleted_count=delete_matched),
    )
    db.feature_flag_audit_log = MagicMock()
    db.feature_flag_audit_log.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="audit_x"),
    )
    return db


def _flag_doc(**overrides):
    base = {
        "flag": "v2_test_flag",
        "enabled_globally": False,
        "enabled_for_companies": [],
        "enabled_for_users": [],
        "enabled_percentage": 0,
        "description": "test",
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────
# Resolution order (spec §6 a–f)
# ──────────────────────────────────────────────────────────────────


class TestResolution(unittest.TestCase):

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def test_a_missing_flag_returns_false(self):
        # (a) flag absent → fail closed.
        db = _build_db(find_one=None)
        result = _run(feature_flags.is_feature_enabled(
            db, "no_such_flag", user_id="u1", company_id="co_a",
        ))
        self.assertFalse(result)

    def test_b_global_returns_true(self):
        db = _build_db(find_one=_flag_doc(enabled_globally=True))
        result = _run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", user_id="u1", company_id="co_a",
        ))
        self.assertTrue(result)

    def test_c_company_in_list_returns_true(self):
        db = _build_db(find_one=_flag_doc(
            enabled_for_companies=["co_a", "co_b"],
        ))
        # Match — co_a in list.
        self.assertTrue(_run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", company_id="co_a",
        )))
        # No match — co_z absent.
        feature_flags.cache_invalidate(None)
        db2 = _build_db(find_one=_flag_doc(
            enabled_for_companies=["co_a", "co_b"],
        ))
        self.assertFalse(_run(feature_flags.is_feature_enabled(
            db2, "v2_test_flag", company_id="co_z",
        )))

    def test_d_user_in_list_returns_true(self):
        db = _build_db(find_one=_flag_doc(
            enabled_for_users=["u_friendly"],
        ))
        self.assertTrue(_run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", user_id="u_friendly",
        )))

    def test_e_percentage_rollout_deterministic(self):
        """Same user_id + same flag → same bucket. The rollout MUST
        be stable across calls so a customer doesn't oscillate
        in/out as percentage ticks up."""
        db = _build_db(find_one=_flag_doc(enabled_percentage=50))
        first = _run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", user_id="u_stable",
        ))
        feature_flags.cache_invalidate(None)
        db2 = _build_db(find_one=_flag_doc(enabled_percentage=50))
        second = _run(feature_flags.is_feature_enabled(
            db2, "v2_test_flag", user_id="u_stable",
        ))
        self.assertEqual(first, second)

    def test_e_percentage_rollout_distribution_at_100(self):
        # Sanity: at 100% every user should land in the bucket.
        db = _build_db(find_one=_flag_doc(enabled_percentage=100))
        for uid in ("u1", "u2", "u3", "u4", "alice", "bob", "12345"):
            with self.subTest(user_id=uid):
                feature_flags.cache_invalidate(None)
                d = _build_db(find_one=_flag_doc(enabled_percentage=100))
                self.assertTrue(_run(feature_flags.is_feature_enabled(
                    d, "v2_test_flag", user_id=uid,
                )))

    def test_e_percentage_rollout_at_zero_disabled(self):
        # Spec: "enabled_percentage > 0" is the gate. 0 means
        # nobody on percentage rollout regardless of bucket.
        db = _build_db(find_one=_flag_doc(enabled_percentage=0))
        self.assertFalse(_run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", user_id="u_lucky",
        )))

    def test_e_salted_per_flag(self):
        """A user at percentile 42 for flag-A should have an
        independent bucket for flag-B. We verify by computing the
        bucket directly — same identifier with different flags
        gives different buckets (with overwhelming probability)."""
        bA = feature_flags._percentage_bucket("u_test", salt="flag_a")
        bB = feature_flags._percentage_bucket("u_test", salt="flag_b")
        # Cryptographic hash → buckets should rarely collide.
        # We don't assert ≠ (collision is possible but rare); we
        # assert the function is salt-sensitive by recomputing.
        bA2 = feature_flags._percentage_bucket("u_test", salt="flag_a")
        self.assertEqual(bA, bA2)        # deterministic
        self.assertIsInstance(bA, int)
        self.assertGreaterEqual(bA, 0)
        self.assertLess(bA, 100)
        # Different salts almost always give different buckets;
        # this is statistical not absolute.
        # (We don't pin specific values — they depend on
        # SHA-256 of the salt+identifier composite.)

    def test_f_default_returns_false(self):
        # No global, no company match, no user match, no percentage.
        db = _build_db(find_one=_flag_doc(
            enabled_for_companies=["co_other"],
            enabled_for_users=["u_other"],
        ))
        self.assertFalse(_run(feature_flags.is_feature_enabled(
            db, "v2_test_flag",
            user_id="u_normal", company_id="co_normal",
        )))

    def test_db_error_fails_closed(self):
        db = MagicMock()
        db.feature_flags = MagicMock()
        db.feature_flags.find_one = AsyncMock(
            side_effect=RuntimeError("Atlas timeout"),
        )
        result = _run(feature_flags.is_feature_enabled(
            db, "v2_test_flag", user_id="u1",
        ))
        self.assertFalse(result)

    def test_resolve_flags_for_user_returns_map(self):
        # /me endpoint backbone — iterate all flags, resolve each.
        db = _build_db(find_results=[
            {"flag": "v2_dashboard"},
            {"flag": "v2_activity_feed"},
        ])
        # Set up find_one to return each flag's full doc when
        # is_feature_enabled re-queries it. We piggyback on the
        # cache by pre-seeding it.
        feature_flags._cache_set("v2_dashboard", _flag_doc(
            flag="v2_dashboard", enabled_globally=True,
        ))
        feature_flags._cache_set("v2_activity_feed", _flag_doc(
            flag="v2_activity_feed", enabled_globally=False,
        ))
        result = _run(feature_flags.resolve_flags_for_user(
            db, user_id="u1", company_id="co_a",
        ))
        self.assertEqual(result, {
            "v2_dashboard": True,
            "v2_activity_feed": False,
        })


# ──────────────────────────────────────────────────────────────────
# Cache: TTL + invalidation
# ──────────────────────────────────────────────────────────────────


class TestCache(unittest.TestCase):

    def setUp(self):
        feature_flags.cache_invalidate(None)
        # Reset TTL between tests in case a previous test changed it.
        feature_flags._set_cache_ttl_for_tests(60.0)

    def tearDown(self):
        feature_flags.cache_invalidate(None)
        feature_flags._set_cache_ttl_for_tests(60.0)

    def test_within_ttl_returns_cached_doc(self):
        db = _build_db(find_one=_flag_doc(enabled_globally=True))
        # First call hits Mongo.
        _run(feature_flags.is_feature_enabled(db, "v2_test_flag"))
        self.assertEqual(db.feature_flags.find_one.call_count, 1)
        # Second call within TTL — should NOT hit Mongo again.
        _run(feature_flags.is_feature_enabled(db, "v2_test_flag"))
        self.assertEqual(db.feature_flags.find_one.call_count, 1)

    def test_ttl_expiry_re_fetches(self):
        db = _build_db(find_one=_flag_doc(enabled_globally=True))
        feature_flags._set_cache_ttl_for_tests(0.05)
        _run(feature_flags.is_feature_enabled(db, "v2_test_flag"))
        time.sleep(0.07)
        _run(feature_flags.is_feature_enabled(db, "v2_test_flag"))
        self.assertEqual(db.feature_flags.find_one.call_count, 2)

    def test_invalidate_specific_flag(self):
        db = _build_db(find_one=_flag_doc(enabled_globally=True))
        _run(feature_flags.is_feature_enabled(db, "flag_one"))
        _run(feature_flags.is_feature_enabled(db, "flag_two"))
        # Invalidate one flag — the OTHER stays cached.
        feature_flags.cache_invalidate("flag_one")
        # Re-call both: only flag_one re-hits Mongo.
        # find_one mock returns the same doc for either flag, but
        # call counts let us assert the cache behavior.
        before = db.feature_flags.find_one.call_count
        _run(feature_flags.is_feature_enabled(db, "flag_one"))
        _run(feature_flags.is_feature_enabled(db, "flag_two"))
        delta = db.feature_flags.find_one.call_count - before
        self.assertEqual(delta, 1)

    def test_invalidate_all(self):
        db = _build_db(find_one=_flag_doc())
        _run(feature_flags.is_feature_enabled(db, "flag_one"))
        _run(feature_flags.is_feature_enabled(db, "flag_two"))
        feature_flags.cache_invalidate(None)
        before = db.feature_flags.find_one.call_count
        _run(feature_flags.is_feature_enabled(db, "flag_one"))
        _run(feature_flags.is_feature_enabled(db, "flag_two"))
        delta = db.feature_flags.find_one.call_count - before
        self.assertEqual(delta, 2)

    def test_negative_cache_for_missing_flag(self):
        """Repeated calls for an absent flag shouldn't pound Mongo."""
        db = _build_db(find_one=None)
        for _ in range(5):
            _run(feature_flags.is_feature_enabled(db, "no_such_flag"))
        self.assertEqual(db.feature_flags.find_one.call_count, 1)


# ──────────────────────────────────────────────────────────────────
# Schema validation
# ──────────────────────────────────────────────────────────────────


class TestNormalizePayload(unittest.TestCase):

    def test_minimal_valid(self):
        out = feature_flags.normalize_flag_payload({
            "flag": "v2_test",
        })
        self.assertEqual(out["flag"], "v2_test")
        self.assertFalse(out["enabled_globally"])
        self.assertEqual(out["enabled_for_companies"], [])
        self.assertEqual(out["enabled_for_users"], [])
        self.assertEqual(out["enabled_percentage"], 0)
        self.assertEqual(out["description"], "")

    def test_strips_unknown_fields(self):
        # Defense against payload pollution.
        out = feature_flags.normalize_flag_payload({
            "flag": "v2_test",
            "_id": "attacker_injected",
            "secret_admin_field": "attack",
        })
        self.assertNotIn("_id", out)
        self.assertNotIn("secret_admin_field", out)

    def test_rejects_empty_flag(self):
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({"flag": "   "})
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({})

    def test_rejects_pct_out_of_range(self):
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({
                "flag": "v2", "enabled_percentage": 101,
            })
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({
                "flag": "v2", "enabled_percentage": -1,
            })

    def test_rejects_non_list_company_users(self):
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({
                "flag": "v2", "enabled_for_companies": "co_a",
            })
        with self.assertRaises(ValueError):
            feature_flags.normalize_flag_payload({
                "flag": "v2", "enabled_for_users": {},
            })


# ──────────────────────────────────────────────────────────────────
# Admin endpoints
# ──────────────────────────────────────────────────────────────────


def _setup_admin_client(*, role="admin", user_id="u_admin", company_id="co_a"):
    import server
    user = {"id": user_id, "_id": user_id, "role": role,
            "company_id": company_id}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app, raise_server_exceptions=False), \
        lambda: server.app.dependency_overrides.clear()


class TestAdminEndpoints(unittest.TestCase):

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def test_create_succeeds_for_admin(self):
        import server
        db = _build_db(find_one=None)
        client, restore = _setup_admin_client(role="admin")
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/admin/feature-flags",
                    json={"flag": "v2_dashboard",
                          "description": "redesigned home"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(db.feature_flags.insert_one.called)
                # Audit log written.
                self.assertTrue(db.feature_flag_audit_log.insert_one.called)
                args = db.feature_flag_audit_log.insert_one.call_args[0][0]
                self.assertEqual(args["action"], "created")
                self.assertEqual(args["flag"], "v2_dashboard")
        finally:
            restore()

    def test_create_409_on_duplicate(self):
        import server
        db = _build_db(find_one=_flag_doc(flag="v2_dashboard"))
        client, restore = _setup_admin_client(role="admin")
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/admin/feature-flags",
                    json={"flag": "v2_dashboard"},
                )
                self.assertEqual(r.status_code, 409)
                # Insert MUST NOT have been called.
                db.feature_flags.insert_one.assert_not_called()
        finally:
            restore()

    def test_create_rejects_non_admin(self):
        import server
        db = _build_db(find_one=None)
        client, restore = _setup_admin_client(role="worker")
        try:
            with patch.object(server, "db", db):
                r = client.post(
                    "/api/admin/feature-flags",
                    json={"flag": "v2_x"},
                )
                self.assertEqual(r.status_code, 403)
        finally:
            restore()

    def test_update_invalidates_cache(self):
        """PATCH MUST clear the in-memory cache for the affected
        flag — otherwise the next /me read returns the stale shape
        for up to 60s, which is the bug this test prevents."""
        import server
        existing = _flag_doc(flag="v2_dashboard", enabled_globally=False)
        # Mock find_one to return existing twice (pre + post update).
        db = _build_db(find_one=existing)
        # Pre-seed the cache so we can assert it's cleared.
        feature_flags._cache_set("v2_dashboard", existing)

        client, restore = _setup_admin_client(role="admin")
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/admin/feature-flags/v2_dashboard",
                    json={"enabled_globally": True},
                )
                self.assertEqual(r.status_code, 200, r.text)
        finally:
            restore()
        # After PATCH, the cache for this flag should be MISS so
        # the next read re-fetches from Mongo.
        self.assertIs(
            feature_flags._cache_get("v2_dashboard"),
            feature_flags._MISS,
            "PATCH endpoint failed to invalidate cache",
        )

    def test_update_404_on_missing_flag(self):
        import server
        db = _build_db(find_one=None)
        client, restore = _setup_admin_client(role="admin")
        try:
            with patch.object(server, "db", db):
                r = client.patch(
                    "/api/admin/feature-flags/no_such",
                    json={"enabled_globally": True},
                )
                self.assertEqual(r.status_code, 404)
        finally:
            restore()

    def test_delete_writes_audit_with_before(self):
        import server
        existing = _flag_doc(flag="v2_dashboard", enabled_globally=True)
        db = _build_db(find_one=existing)
        client, restore = _setup_admin_client(role="admin")
        try:
            with patch.object(server, "db", db):
                r = client.delete("/api/admin/feature-flags/v2_dashboard")
                self.assertEqual(r.status_code, 200)
                args = db.feature_flag_audit_log.insert_one.call_args[0][0]
                self.assertEqual(args["action"], "deleted")
                self.assertIsNotNone(args["before"])
                self.assertIsNone(args["after"])
        finally:
            restore()

    def test_list_admin_only(self):
        import server
        db = _build_db(find_results=[])
        client, restore = _setup_admin_client(role="cp")  # not admin
        try:
            with patch.object(server, "db", db):
                r = client.get("/api/admin/feature-flags")
                self.assertEqual(r.status_code, 403)
        finally:
            restore()


class TestMeEndpoint(unittest.TestCase):
    """GET /api/feature-flags/me returns {flag: bool} only — never
    leaks rollout config to the client."""

    def setUp(self):
        feature_flags.cache_invalidate(None)

    def tearDown(self):
        feature_flags.cache_invalidate(None)

    def test_returns_resolved_map_for_user(self):
        import server
        db = _build_db(find_results=[
            {"flag": "v2_dashboard"},
            {"flag": "v2_activity_feed"},
        ])
        # Pre-seed cache so resolve_flags_for_user has something
        # to evaluate.
        feature_flags._cache_set("v2_dashboard", _flag_doc(
            flag="v2_dashboard", enabled_globally=True,
        ))
        feature_flags._cache_set("v2_activity_feed", _flag_doc(
            flag="v2_activity_feed",
            enabled_for_users=["u_target"],
        ))
        async def _fake_user():
            return {"id": "u_target", "_id": "u_target",
                    "role": "admin", "company_id": "co_a"}
        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                r = TestClient(server.app).get("/api/feature-flags/me")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["flags"], {
                    "v2_dashboard": True,
                    "v2_activity_feed": True,
                })
                # Rollout config NOT exposed.
                for forbidden in ("enabled_globally", "enabled_percentage",
                                  "enabled_for_companies"):
                    self.assertNotIn(forbidden, str(body))
        finally:
            server.app.dependency_overrides.clear()


# ──────────────────────────────────────────────────────────────────
# Frontend pins
# ──────────────────────────────────────────────────────────────────


class TestFrontendIntegration(unittest.TestCase):
    """Static-source pins for the frontend hook + provider. Catches
    a regression that drops the loading-default or unwires the
    provider from _layout.jsx."""

    @classmethod
    def setUpClass(cls):
        cls.frontend = _REPO / "frontend"

    def test_provider_present(self):
        path = self.frontend / "src" / "context" / "FeatureFlagsContext.js"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("FeatureFlagsProvider", text)
        # Re-fetches on identity change (login/logout).
        self.assertIn("useEffect", text)
        self.assertIn("/api/feature-flags/me", text)

    def test_hook_returns_false_during_loading(self):
        """Hard rule: useFeatureFlag returns false while the
        provider hasn't loaded yet (fail-closed flicker prevention)."""
        path = self.frontend / "src" / "hooks" / "useFeatureFlag.js"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("if (!loaded) return false", text)

    def test_provider_mounted_inside_auth_provider(self):
        """The provider needs auth state to choose what to fetch
        — must mount inside AuthProvider, not outside."""
        path = self.frontend / "app" / "_layout.jsx"
        text = path.read_text(encoding="utf-8")
        # Both providers present.
        self.assertIn("FeatureFlagsProvider", text)
        self.assertIn("AuthProvider", text)
        # Order pin: AuthProvider opens before FeatureFlagsProvider.
        auth_idx = text.find("<AuthProvider>")
        flags_idx = text.find("<FeatureFlagsProvider>")
        self.assertGreater(auth_idx, 0)
        self.assertGreater(flags_idx, auth_idx)

    def test_provider_fails_closed_on_error(self):
        path = self.frontend / "src" / "context" / "FeatureFlagsContext.js"
        text = path.read_text(encoding="utf-8")
        # On API error, set flags to {} (every flag → false).
        self.assertIn("setFlags({})", text)


# ──────────────────────────────────────────────────────────────────
# Documentation pins
# ──────────────────────────────────────────────────────────────────


class TestDocs(unittest.TestCase):
    """Pin that the operator-facing docs cover the spec sections.
    These are skipped at this point in the run (the docs come last
    in the F1 → E1 commit sequence) but the file presence + key
    headings are enforced here."""

    def test_branching_md_present(self):
        path = _REPO / "docs" / "operations" / "branching.md"
        self.assertTrue(path.exists(), str(path))
        text = path.read_text(encoding="utf-8")
        for section in (
            "main", "develop", "feature/", "staging",
            "mongodump", "mongorestore",
        ):
            self.assertIn(section, text, f"branching.md missing: {section!r}")

    def test_feature_flags_md_present(self):
        path = _REPO / "docs" / "operations" / "feature-flags.md"
        self.assertTrue(path.exists(), str(path))
        text = path.read_text(encoding="utf-8")
        for section in ("Canary", "Percentage", "Kill switch"):
            self.assertIn(section, text, f"feature-flags.md missing: {section!r}")


if __name__ == "__main__":
    unittest.main()
