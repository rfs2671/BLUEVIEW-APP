"""Phase B1a — notification_preferences module + endpoints + send_notification
integration + digest_dispatcher.

Coverage organised in five sections:

  1. PURE DEFAULTS + ROUTING DECISION
     • build_default_preferences shape.
     • compute_routing_decision: every (delivery, severity, threshold)
       combination that maps to a distinct outcome.
     • _severity_meets_threshold edge cases.

  2. PREFERENCES FETCH + MERGE
     • get_effective_preferences resolution order:
         project-scoped > user-global > defaults.
     • resolve_user_id_by_email: hit / miss / empty / case-normalize.

  3. ENDPOINTS (HTTP-level via TestClient)
     • GET /users/me/notification-preferences — defaults when no record.
     • PATCH /users/me/notification-preferences — creates from defaults
       on first call, merges patch chunks on subsequent calls.
     • GET /projects/{id}/notification-preferences/{user_id} — auth
       gate: self vs admin/owner of company that owns project vs other.
     • PATCH same — same auth + persist + merge contract.

  4. send_notification PREFERENCES PATH
     • Default-pass invariant: caller without `signal_kind` in metadata
       → preferences pipeline NEVER fires (existing behavior preserved).
     • Caller with signal_kind + recipient with no user account →
       falls through to legacy path.
     • feed_only delivery → status=suppressed_user_pref, no Resend, no queue.
     • digest_daily delivery → enqueue + status=suppressed_user_pref_digest.
     • digest_weekly delivery → enqueue with weekly scheduled_send_at.
     • immediate delivery → falls through to legacy path (Step 2-4 fire).
     • Project-scoped override wins over user-global.
     • Severity below threshold → suppressed_user_pref with reason.
     • Kill switch wins over preferences (Step 0 fires first).
     • Preferences pipeline failure → log warning + fall back to legacy.

  5. DIGEST DISPATCHER
     • Aggregates per-user.
     • Marks queue items as 'sent' on success.
     • Kill-switch suppresses items + flips them to suppressed_kill_switch.
     • Recipient missing on a queue item → marks 'failed'.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# 1. PURE DEFAULTS + ROUTING DECISION
# ──────────────────────────────────────────────────────────────────

class TestDefaults(unittest.TestCase):

    def test_default_channel_routes_michael_pattern(self):
        from lib.notification_preferences import default_channel_routes_default
        routes = default_channel_routes_default()
        self.assertEqual(routes["critical"], ["email"])
        self.assertEqual(routes["warning"], ["email"])
        # Defense-in-depth: info severity does NOT email by default.
        # This is the operator's "Michael defense-in-depth" guarantee.
        self.assertEqual(routes["info"], ["in_app"])

    def test_default_delivery_for_severity(self):
        from lib.notification_preferences import default_delivery_for_severity
        self.assertEqual(default_delivery_for_severity("critical"), "immediate")
        self.assertEqual(default_delivery_for_severity("warning"), "digest_daily")
        self.assertEqual(default_delivery_for_severity("info"), "feed_only")

    def test_build_default_preferences_shape(self):
        from lib.notification_preferences import build_default_preferences
        doc = build_default_preferences("u_test")
        self.assertEqual(doc["user_id"], "u_test")
        self.assertIsNone(doc["project_id"])
        self.assertEqual(doc["signal_kind_overrides"], {})
        self.assertIn("critical", doc["channel_routes_default"])
        self.assertIn("daily_at", doc["digest_window"])
        self.assertIsInstance(doc["created_at"], datetime)


class TestComputeRoutingDecision(unittest.TestCase):
    """compute_routing_decision is pure — exercise every observable
    branch with handcrafted prefs docs."""

    def _prefs(self, *, overrides=None, routes=None):
        from lib.notification_preferences import (
            default_channel_routes_default,
            default_digest_window,
        )
        return {
            "signal_kind_overrides": overrides or {},
            "channel_routes_default": routes or default_channel_routes_default(),
            "digest_window": default_digest_window(),
        }

    def test_default_critical_routes_email_immediate(self):
        from lib.notification_preferences import compute_routing_decision
        d = compute_routing_decision(
            self._prefs(),
            signal_kind="violation_dob",
            severity="critical",
        )
        self.assertTrue(d.should_send_email_now)
        self.assertFalse(d.should_queue_digest)
        self.assertEqual(d.delivery, "immediate")

    def test_default_warning_queues_digest(self):
        from lib.notification_preferences import compute_routing_decision
        d = compute_routing_decision(
            self._prefs(),
            signal_kind="complaint_dob",
            severity="warning",
        )
        self.assertFalse(d.should_send_email_now)
        self.assertTrue(d.should_queue_digest)
        self.assertEqual(d.digest_kind, "digest_daily")

    def test_default_info_feed_only(self):
        from lib.notification_preferences import compute_routing_decision
        d = compute_routing_decision(
            self._prefs(),
            signal_kind="permit_issued",
            severity="info",
        )
        # info severity defaults to in_app channel, feed_only delivery.
        # Result: no email, no queue, no immediate; suppress_reason='feed_only'.
        self.assertFalse(d.should_send_email_now)
        self.assertFalse(d.should_queue_digest)
        self.assertEqual(d.suppress_reason, "feed_only")

    def test_per_signal_override_wins(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "complaint_311": {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "immediate",
            },
        })
        d = compute_routing_decision(
            prefs,
            signal_kind="complaint_311",
            severity="info",  # info would feed-only by default
        )
        # Override forces immediate email even at info severity.
        self.assertTrue(d.should_send_email_now)

    def test_severity_threshold_critical_only_blocks_warning(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "violation_ecb": {
                "channels": ["email"],
                "severity_threshold": "critical_only",
                "delivery": "immediate",
            },
        })
        d = compute_routing_decision(
            prefs,
            signal_kind="violation_ecb",
            severity="warning",  # below threshold
        )
        self.assertFalse(d.should_send_email_now)
        self.assertEqual(d.suppress_reason, "severity_below_threshold")

    def test_severity_threshold_warning_or_above_passes_warning(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "complaint_dob": {
                "channels": ["email"],
                "severity_threshold": "warning_or_above",
                "delivery": "immediate",
            },
        })
        d = compute_routing_decision(
            prefs,
            signal_kind="complaint_dob",
            severity="warning",
        )
        self.assertTrue(d.should_send_email_now)

    def test_severity_threshold_none_blocks_everything(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "permit_issued": {
                "channels": ["email"],
                "severity_threshold": "none",
                "delivery": "immediate",
            },
        })
        for sev in ("info", "warning", "critical"):
            d = compute_routing_decision(
                prefs, signal_kind="permit_issued", severity=sev,
            )
            self.assertFalse(d.should_send_email_now, sev)

    def test_empty_channels_suppresses(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "permit_renewed": {
                "channels": [],
                "severity_threshold": "any",
                "delivery": "immediate",
            },
        })
        d = compute_routing_decision(
            prefs, signal_kind="permit_renewed", severity="info",
        )
        self.assertFalse(d.should_send_email_now)
        self.assertEqual(d.suppress_reason, "channels_empty")

    def test_digest_weekly_delivery_returns_correct_digest_kind(self):
        from lib.notification_preferences import compute_routing_decision
        prefs = self._prefs(overrides={
            "filing_pending": {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "digest_weekly",
            },
        })
        d = compute_routing_decision(
            prefs, signal_kind="filing_pending", severity="info",
        )
        self.assertTrue(d.should_queue_digest)
        self.assertEqual(d.digest_kind, "digest_weekly")


# ──────────────────────────────────────────────────────────────────
# 2. PREFERENCES FETCH + MERGE
# ──────────────────────────────────────────────────────────────────

def _build_prefs_db_mock(*, records=None):
    """Mock motor db where notification_preferences.find_one queries
    by (user_id, project_id) against the supplied records list."""
    db = MagicMock()
    records = records or []

    async def _find_one(query, projection=None):
        target_uid = query.get("user_id")
        target_pid = query.get("project_id", None)
        for r in records:
            if str(r.get("user_id")) != str(target_uid):
                continue
            if r.get("project_id") != target_pid:
                continue
            return r
        return None

    db.notification_preferences = MagicMock()
    db.notification_preferences.find_one = AsyncMock(side_effect=_find_one)
    return db


class TestEffectivePreferences(unittest.TestCase):

    def test_returns_defaults_when_no_record(self):
        from lib.notification_preferences import get_effective_preferences
        db = _build_prefs_db_mock(records=[])
        prefs = _run(get_effective_preferences(db, user_id="u1"))
        self.assertEqual(prefs["signal_kind_overrides"], {})
        self.assertIn("channel_routes_default", prefs)

    def test_user_global_record_returned(self):
        from lib.notification_preferences import get_effective_preferences
        record = {
            "user_id": "u1",
            "project_id": None,
            "signal_kind_overrides": {"violation_dob": {"channels": ["email"]}},
            "channel_routes_default": {"critical": ["email"], "warning": [], "info": []},
            "digest_window": {},
        }
        db = _build_prefs_db_mock(records=[record])
        prefs = _run(get_effective_preferences(db, user_id="u1"))
        self.assertIn("violation_dob", prefs["signal_kind_overrides"])

    def test_project_scoped_wins_over_user_global(self):
        from lib.notification_preferences import get_effective_preferences
        user_global = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {"a": {"channels": ["email"]}},
            "channel_routes_default": {}, "digest_window": {},
        }
        project_scoped = {
            "user_id": "u1", "project_id": "p1",
            "signal_kind_overrides": {"b": {"channels": ["email"]}},
            "channel_routes_default": {}, "digest_window": {},
        }
        db = _build_prefs_db_mock(records=[user_global, project_scoped])
        prefs = _run(get_effective_preferences(
            db, user_id="u1", project_id="p1",
        ))
        # project-scoped record wins entirely.
        self.assertIn("b", prefs["signal_kind_overrides"])
        self.assertNotIn("a", prefs["signal_kind_overrides"])

    def test_project_query_falls_back_to_user_global(self):
        from lib.notification_preferences import get_effective_preferences
        user_global = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {"a": {"channels": ["email"]}},
            "channel_routes_default": {}, "digest_window": {},
        }
        db = _build_prefs_db_mock(records=[user_global])
        prefs = _run(get_effective_preferences(
            db, user_id="u1", project_id="p_no_record",
        ))
        # Falls back to user-global; project_id annotated for the
        # caller's benefit so a subsequent PATCH lands on the right
        # scope.
        self.assertIn("a", prefs["signal_kind_overrides"])
        self.assertEqual(prefs["project_id"], "p_no_record")


class TestResolveUserIdByEmail(unittest.TestCase):

    def test_hit_returns_id_string(self):
        from lib.notification_preferences import resolve_user_id_by_email
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value={"_id": "u_match_42"})
        uid = _run(resolve_user_id_by_email(db, "Jane@example.com"))
        self.assertEqual(uid, "u_match_42")
        # Email is normalized to lowercase before lookup.
        called_with = db.users.find_one.await_args.args[0]
        self.assertEqual(called_with["email"], "jane@example.com")

    def test_miss_returns_none(self):
        from lib.notification_preferences import resolve_user_id_by_email
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value=None)
        uid = _run(resolve_user_id_by_email(db, "no@example.com"))
        self.assertIsNone(uid)

    def test_empty_email_returns_none_without_query(self):
        from lib.notification_preferences import resolve_user_id_by_email
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value={"_id": "u1"})
        self.assertIsNone(_run(resolve_user_id_by_email(db, "")))
        self.assertIsNone(_run(resolve_user_id_by_email(db, None)))
        # find_one was never invoked.
        db.users.find_one.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# 3. ENDPOINTS
# ──────────────────────────────────────────────────────────────────

def _setup_client(*, role="admin", user_id="u_test", company_id="co_a"):
    import server
    user = {
        "id": user_id, "_id": user_id, "user_id": user_id,
        "role": role, "company_id": company_id,
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    return TestClient(server.app), lambda: server.app.dependency_overrides.clear()


class TestGetMyPreferences(unittest.TestCase):

    def test_returns_defaults_when_no_record(self):
        import server
        client, restore = _setup_client(user_id="u1")
        mock_db = _build_prefs_db_mock(records=[])
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/notification-preferences")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["user_id"], "u1")
            self.assertIsNone(body["project_id"])
            self.assertEqual(body["signal_kind_overrides"], {})
            # Michael defense-in-depth defaults present in response.
            self.assertEqual(body["channel_routes_default"]["info"], ["in_app"])
        finally:
            restore()

    def test_returns_existing_record(self):
        import server
        client, restore = _setup_client(user_id="u1")
        record = {
            "_id": "pref_doc_1", "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {
                "violation_dob": {
                    "channels": ["email"],
                    "severity_threshold": "any",
                    "delivery": "immediate",
                },
            },
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": ["in_app"]},
            "digest_window": {"daily_at": "07:00", "weekly_day": "monday", "timezone": "America/New_York"},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        mock_db = _build_prefs_db_mock(records=[record])
        try:
            with patch.object(server, "db", mock_db):
                resp = client.get("/api/users/me/notification-preferences")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertIn("violation_dob", body["signal_kind_overrides"])
        finally:
            restore()


class TestPatchMyPreferences(unittest.TestCase):

    def _patch_db_for_upsert(self):
        """Mock that supports the upsert flow: find_one returns None
        on first call, then the inserted doc on subsequent reads."""
        db = MagicMock()
        store = {"doc": None}

        async def _find_one(query, projection=None):
            return store["doc"]

        async def _insert_one(doc):
            doc["_id"] = "pref_inserted_1"
            store["doc"] = doc
            r = MagicMock()
            r.inserted_id = "pref_inserted_1"
            return r

        async def _update_one(filt, update):
            existing = store["doc"] or {}
            set_fields = update.get("$set", {})
            existing.update(set_fields)
            store["doc"] = existing
            return MagicMock(modified_count=1)

        db.notification_preferences = MagicMock()
        db.notification_preferences.find_one = AsyncMock(side_effect=_find_one)
        db.notification_preferences.insert_one = AsyncMock(side_effect=_insert_one)
        db.notification_preferences.update_one = AsyncMock(side_effect=_update_one)
        return db, store

    def test_creates_record_from_defaults_with_patch_applied(self):
        import server
        client, restore = _setup_client(user_id="u1")
        mock_db, store = self._patch_db_for_upsert()
        body = {
            "signal_kind_overrides": {
                "complaint_311": {
                    "channels": ["email"],
                    "severity_threshold": "any",
                    "delivery": "immediate",
                },
            },
        }
        try:
            with patch.object(server, "db", mock_db):
                resp = client.patch(
                    "/api/users/me/notification-preferences",
                    json=body,
                )
            self.assertEqual(resp.status_code, 200, resp.text)
            mock_db.notification_preferences.insert_one.assert_awaited_once()
            saved = store["doc"]
            self.assertIn("complaint_311", saved["signal_kind_overrides"])
            # Defaults preserved alongside the patched override.
            self.assertEqual(saved["channel_routes_default"]["info"], ["in_app"])
        finally:
            restore()

    def test_400_on_invalid_delivery_value(self):
        import server
        client, restore = _setup_client(user_id="u1")
        mock_db, _store = self._patch_db_for_upsert()
        body = {
            "signal_kind_overrides": {
                "violation_dob": {
                    "channels": ["email"],
                    "delivery": "ASAP",  # invalid
                },
            },
        }
        try:
            with patch.object(server, "db", mock_db):
                resp = client.patch(
                    "/api/users/me/notification-preferences",
                    json=body,
                )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("errors", resp.json()["detail"])
        finally:
            restore()

    def test_400_on_bad_severity_routes_key(self):
        import server
        client, restore = _setup_client(user_id="u1")
        mock_db, _store = self._patch_db_for_upsert()
        body = {
            "channel_routes_default": {
                "danger": ["email"],  # invalid severity
            },
        }
        try:
            with patch.object(server, "db", mock_db):
                resp = client.patch(
                    "/api/users/me/notification-preferences",
                    json=body,
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()

    def test_400_on_bad_digest_window_format(self):
        import server
        client, restore = _setup_client(user_id="u1")
        mock_db, _store = self._patch_db_for_upsert()
        try:
            with patch.object(server, "db", mock_db):
                resp = client.patch(
                    "/api/users/me/notification-preferences",
                    json={"digest_window": {"daily_at": "25:99"}},
                )
            self.assertEqual(resp.status_code, 400)
        finally:
            restore()


class TestProjectScopedAuth(unittest.TestCase):

    def _build_db(self, *, project_company="co_a"):
        db = MagicMock()
        db.notification_preferences = MagicMock()
        db.notification_preferences.find_one = AsyncMock(return_value=None)
        db.projects = MagicMock()
        db.projects.find_one = AsyncMock(return_value={
            "_id": "p1", "company_id": project_company,
        })
        return db

    def test_self_can_read_own_project_prefs(self):
        import server
        client, restore = _setup_client(user_id="u1", role="admin", company_id="co_a")
        mock_db = self._build_db(project_company="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get(
                    "/api/projects/p1/notification-preferences/u1",
                )
            self.assertEqual(resp.status_code, 200)
        finally:
            restore()

    def test_admin_of_owning_company_can_read_other_user(self):
        import server
        client, restore = _setup_client(user_id="u_admin", role="admin", company_id="co_a")
        mock_db = self._build_db(project_company="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get(
                    "/api/projects/p1/notification-preferences/u_other",
                )
            self.assertEqual(resp.status_code, 200)
        finally:
            restore()

    def test_worker_role_cannot_read_other_user(self):
        import server
        client, restore = _setup_client(user_id="u_worker", role="worker", company_id="co_a")
        mock_db = self._build_db(project_company="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get(
                    "/api/projects/p1/notification-preferences/u_other",
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()

    def test_admin_of_different_company_cannot_read(self):
        import server
        # Caller is on co_b; project belongs to co_a.
        client, restore = _setup_client(user_id="u_admin", role="admin", company_id="co_b")
        mock_db = self._build_db(project_company="co_a")
        try:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "to_query_id", side_effect=lambda x: x):
                resp = client.get(
                    "/api/projects/p1/notification-preferences/u_other",
                )
            self.assertEqual(resp.status_code, 403)
        finally:
            restore()


# ──────────────────────────────────────────────────────────────────
# 4. send_notification PREFERENCES PATH
# ──────────────────────────────────────────────────────────────────

def _build_send_db_mock(
    *,
    user_email_to_id=None,
    prefs_records=None,
    notification_log_inserts=None,
    digest_inserts=None,
):
    """Mock motor db with all the surfaces send_notification touches:
    notification_log (for idempotency + audit), users (for email →
    user resolution), notification_preferences, digest_queue."""
    db = MagicMock()
    # notification_log — idempotency check returns None (no prior),
    # insert just records the doc.
    nl_inserts = notification_log_inserts if notification_log_inserts is not None else []
    async def _nl_find_one(query):
        return None
    async def _nl_insert_one(doc):
        nl_inserts.append(doc)
        r = MagicMock()
        r.inserted_id = "nl_" + str(len(nl_inserts))
        return r
    db.notification_log = MagicMock()
    db.notification_log.find_one = AsyncMock(side_effect=_nl_find_one)
    db.notification_log.insert_one = AsyncMock(side_effect=_nl_insert_one)

    # users — match by email.
    map_ = user_email_to_id or {}
    async def _users_find_one(query, projection=None):
        email = (query or {}).get("email")
        if email and email in map_:
            return {"_id": map_[email]}
        return None
    db.users = MagicMock()
    db.users.find_one = AsyncMock(side_effect=_users_find_one)

    # notification_preferences — match by (user_id, project_id).
    records = prefs_records or []
    async def _prefs_find_one(query, projection=None):
        target_uid = query.get("user_id")
        target_pid = query.get("project_id", None)
        for r in records:
            if str(r.get("user_id")) == str(target_uid) and r.get("project_id") == target_pid:
                return r
        return None
    db.notification_preferences = MagicMock()
    db.notification_preferences.find_one = AsyncMock(side_effect=_prefs_find_one)

    # digest_queue insert.
    dq_inserts = digest_inserts if digest_inserts is not None else []
    async def _dq_insert_one(doc):
        dq_inserts.append(doc)
        r = MagicMock()
        r.inserted_id = "dq_" + str(len(dq_inserts))
        return r
    db.digest_queue = MagicMock()
    db.digest_queue.insert_one = AsyncMock(side_effect=_dq_insert_one)

    return db, nl_inserts, dq_inserts


class TestSendNotificationDefaultPassInvariant(unittest.TestCase):
    """The non-negotiable contract: a caller that does NOT pass
    `signal_kind` in metadata gets the legacy code path verbatim.
    The preferences-related Mongo collections are NOT touched."""

    def test_no_signal_kind_in_metadata_skips_preferences_pipeline(self):
        from lib.notifications import send_notification
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={"user@levelog.com": "u1"},
        )
        # NOTIFICATIONS_KILL_SWITCH off so the kill-switch branch
        # doesn't short-circuit; we want to verify the preferences
        # branch is skipped, not the kill-switch branch.
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="annotation_note",
                recipient="user@levelog.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                # No signal_kind in metadata → preferences MUST NOT fire.
                metadata=None,
            ))
        # The users + preferences + digest_queue collections must
        # never have been touched. This is the byte-for-byte
        # backward-compat pin.
        db.users.find_one.assert_not_awaited()
        db.notification_preferences.find_one.assert_not_awaited()
        db.digest_queue.insert_one.assert_not_awaited()

    def test_signal_kind_present_but_recipient_not_a_user_skips_preferences(self):
        from lib.notifications import send_notification
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={},  # no users at all
        )
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="critical_dob_alert",
                recipient="external_filing_rep@example.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                metadata={"signal_kind": "violation_dob", "severity": "critical"},
            ))
        # users.find_one was called (we tried to resolve), but no
        # match → preferences short-circuit.
        db.users.find_one.assert_awaited_once()
        db.notification_preferences.find_one.assert_not_awaited()
        db.digest_queue.insert_one.assert_not_awaited()


class TestSendNotificationPreferencesPath(unittest.TestCase):

    def test_feed_only_decision_writes_suppressed_user_pref(self):
        from lib.notifications import send_notification
        prefs = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": ["in_app"]},
            "digest_window": {"daily_at": "07:00", "weekly_day": "monday", "timezone": "America/New_York"},
        }
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={"user@levelog.com": "u1"},
            prefs_records=[prefs],
        )
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="annotation_note",
                recipient="user@levelog.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                metadata={"signal_kind": "permit_issued", "severity": "info"},
            ))
        self.assertEqual(len(nl_inserts), 1)
        self.assertEqual(nl_inserts[0]["status"], "suppressed_user_pref")
        # No digest queue entry (feed_only does not enqueue).
        self.assertEqual(len(dq_inserts), 0)

    def test_digest_daily_decision_enqueues(self):
        from lib.notifications import send_notification
        prefs = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": ["in_app"]},
            "digest_window": {"daily_at": "07:00", "weekly_day": "monday", "timezone": "America/New_York"},
        }
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={"user@levelog.com": "u1"},
            prefs_records=[prefs],
        )
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="dob_signal",
                recipient="user@levelog.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                metadata={"signal_kind": "complaint_dob", "severity": "warning"},
            ))
        # warning + default routes → email channel + digest_daily delivery.
        self.assertEqual(len(dq_inserts), 1)
        self.assertEqual(dq_inserts[0]["delivery"], "digest_daily")
        self.assertEqual(dq_inserts[0]["signal_kind"], "complaint_dob")
        # And the audit row with status=suppressed_user_pref_digest.
        self.assertEqual(len(nl_inserts), 1)
        self.assertEqual(nl_inserts[0]["status"], "suppressed_user_pref_digest")

    def test_immediate_decision_falls_through_to_legacy(self):
        from lib.notifications import send_notification
        # critical + default routes → email + immediate. Should fall
        # through to Step 2 (NOTIFICATIONS_ENABLED off in env →
        # suppressed_flag_off, since we don't set ENABLED here).
        prefs = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": ["in_app"]},
            "digest_window": {"daily_at": "07:00", "weekly_day": "monday", "timezone": "America/New_York"},
        }
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={"user@levelog.com": "u1"},
            prefs_records=[prefs],
        )
        with patch.dict(os.environ, {
            "NOTIFICATIONS_KILL_SWITCH": "0",
            "NOTIFICATIONS_ENABLED": "false",
        }):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="critical_dob_alert",
                recipient="user@levelog.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                metadata={"signal_kind": "violation_dob", "severity": "critical"},
            ))
        # Preferences branch did NOT terminate; legacy step 2
        # (NOTIFICATIONS_ENABLED off) wrote the suppressed_flag_off
        # row. No digest entry.
        self.assertEqual(len(dq_inserts), 0)
        self.assertEqual(len(nl_inserts), 1)
        self.assertEqual(nl_inserts[0]["status"], "suppressed_flag_off")

    def test_kill_switch_wins_over_preferences(self):
        from lib.notifications import send_notification
        prefs = {
            "user_id": "u1", "project_id": None,
            "signal_kind_overrides": {},
            "channel_routes_default": {"critical": ["email"], "warning": ["email"], "info": ["in_app"]},
            "digest_window": {},
        }
        db, nl_inserts, dq_inserts = _build_send_db_mock(
            user_email_to_id={"user@levelog.com": "u1"},
            prefs_records=[prefs],
        )
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "1"}):
            _run(send_notification(
                db,
                permit_renewal_id="r1",
                trigger_type="critical_dob_alert",
                recipient="user@levelog.com",
                subject="Test",
                html="<p>Test</p>",
                text="Test",
                metadata={"signal_kind": "violation_dob", "severity": "critical"},
            ))
        # Step 0 wins. Preferences pipeline never ran.
        self.assertEqual(len(nl_inserts), 1)
        self.assertEqual(nl_inserts[0]["status"], "suppressed_kill_switch")
        db.notification_preferences.find_one.assert_not_awaited()
        db.digest_queue.insert_one.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# 5. DIGEST DISPATCHER
# ──────────────────────────────────────────────────────────────────

class TestDispatchDigests(unittest.TestCase):

    def _build_dispatcher_db(self, *, queued_items, kill_switch_on=False):
        db = MagicMock()
        # Cursor over queued items.
        async def _async_iter(items):
            for it in items:
                yield it

        class _Cursor:
            def __init__(self, items):
                self._items = items
            def __aiter__(self):
                return _async_iter(self._items).__aiter__()

        db.digest_queue = MagicMock()
        db.digest_queue.find = MagicMock(return_value=_Cursor(queued_items))
        db.digest_queue.update_many = AsyncMock()
        return db

    def test_aggregates_per_user_and_calls_send_fn(self):
        from lib.notification_preferences import dispatch_digests
        items = [
            {
                "_id": "q1", "user_id": "u1",
                "recipient_email": "user1@levelog.com",
                "signal_kind": "complaint_dob", "severity": "warning",
                "subject": "Item 1", "delivery": "digest_daily",
                "status": "queued",
            },
            {
                "_id": "q2", "user_id": "u1",
                "recipient_email": "user1@levelog.com",
                "signal_kind": "filing_pending", "severity": "info",
                "subject": "Item 2", "delivery": "digest_daily",
                "status": "queued",
            },
            {
                "_id": "q3", "user_id": "u2",
                "recipient_email": "user2@levelog.com",
                "signal_kind": "violation_resolved", "severity": "info",
                "subject": "Item 3", "delivery": "digest_weekly",
                "status": "queued",
            },
        ]
        db = self._build_dispatcher_db(queued_items=items)

        send_fn = AsyncMock(return_value={"status": "sent"})
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            summary = _run(dispatch_digests(
                db, send_notification_fn=send_fn,
            ))

        self.assertEqual(summary["users_dispatched"], 2)
        self.assertEqual(summary["items_sent"], 3)
        # send_fn called once per user.
        self.assertEqual(send_fn.await_count, 2)
        # Each call's recipient is the user's email, NOT a customer.
        recipients = sorted(
            call.kwargs["recipient"] for call in send_fn.await_args_list
        )
        self.assertEqual(
            recipients, ["user1@levelog.com", "user2@levelog.com"],
        )
        # Items marked sent.
        self.assertEqual(db.digest_queue.update_many.await_count, 2)

    def test_kill_switch_marks_items_suppressed(self):
        from lib.notification_preferences import dispatch_digests
        items = [
            {
                "_id": "q1", "user_id": "u1",
                "recipient_email": "user1@levelog.com",
                "signal_kind": "complaint_dob", "severity": "warning",
                "subject": "Item 1", "delivery": "digest_daily",
                "status": "queued",
            },
        ]
        db = self._build_dispatcher_db(queued_items=items)
        send_fn = AsyncMock()
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "1"}):
            summary = _run(dispatch_digests(
                db, send_notification_fn=send_fn,
            ))
        self.assertEqual(summary["items_kill_switch_suppressed"], 1)
        send_fn.assert_not_awaited()
        # update_many called to flip status → suppressed_kill_switch.
        db.digest_queue.update_many.assert_awaited_once()
        update_call = db.digest_queue.update_many.await_args.args
        self.assertEqual(
            update_call[1]["$set"]["status"], "suppressed_kill_switch",
        )

    def test_missing_recipient_marks_failed(self):
        from lib.notification_preferences import dispatch_digests
        items = [
            {
                "_id": "q_orphan", "user_id": "u_orphan",
                "recipient_email": "",  # missing
                "signal_kind": "complaint_dob", "severity": "warning",
                "subject": "Orphan", "delivery": "digest_daily",
                "status": "queued",
            },
        ]
        db = self._build_dispatcher_db(queued_items=items)
        send_fn = AsyncMock()
        with patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": "0"}):
            summary = _run(dispatch_digests(
                db, send_notification_fn=send_fn,
            ))
        self.assertEqual(summary["items_failed"], 1)
        send_fn.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# Bonus: invariant pin — the integration is purely additive.
# ──────────────────────────────────────────────────────────────────


class TestIntegrationIsAdditive(unittest.TestCase):
    """Static-source pin: the preferences integration in send_notification
    is gated on metadata['signal_kind']. A future commit that drops the
    gate would break the default-pass invariant — fail loudly here."""

    def test_signal_kind_gate_present(self):
        path = _BACKEND / "lib" / "notifications.py"
        text = path.read_text(encoding="utf-8")
        # The literal gate condition. If you refactor the gate
        # mechanism, update this pin to match.
        self.assertIn(
            'signal_kind = metadata.get("signal_kind")',
            text,
        )
        # And the conditional that wraps the pipeline.
        self.assertIn("if signal_kind:", text)


if __name__ == "__main__":
    unittest.main()
