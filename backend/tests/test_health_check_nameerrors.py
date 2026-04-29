"""Regression tests for the two parked NameErrors in the Job 3
DOB NOW health-check code path. Both fired every 30 minutes on every
replica via `nightly_renewal_scan` → `run_dob_now_health_check`,
polluting the log signal we'll need clean for tomorrow's post-flip
review.

Fixes pinned here:

1. `name 'db' is not defined` in `_send_health_check_alert`.
   The function used `db.system_config.find_one(...)` and
   `db.system_config.update_one(...)` but didn't accept `db` as
   a parameter. Now takes `db` as the first positional arg, with
   the caller (`run_dob_now_health_check`) updated to match.

2. `name 'js_hash_current' is not defined` in `run_dob_now_health_check`.
   The variable was referenced in the persisted health-check record
   but never assigned anywhere in the function. The compute step
   for the JS-bundle hash feature was never implemented. Replaced
   with a None literal so the persisted doc shape (consumed by
   GET /permit-renewals/health-status which already uses
   .get("js_hash")) stays coherent without referencing an undefined
   name.

Each test invokes the previously-broken code path with stub IO and
asserts no NameError. Mocked stack: ServerHttpClient (HTTP), Resend
(email), Mongo (system_config). Real network and real DB are not
touched.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import permit_renewal  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── _send_health_check_alert: db NameError ─────────────────────────

class TestSendHealthCheckAlertDbParam(unittest.TestCase):
    """The function must accept `db` and exercise it without raising
    NameError. We don't actually want an email to send during the
    test, so we set RESEND_API_KEY empty — the function takes the
    early-return branch (the cooldown branch is reached only when
    Resend is configured). That still proves the signature is fixed:
    pre-fix the function couldn't even be called with a `db` arg
    because the signature only took `issues`."""

    def test_signature_accepts_db_first(self):
        """Pre-fix: TypeError because signature was (issues). Post-fix:
        the call shape (db, issues) succeeds."""
        db = MagicMock()  # never accessed in the early-return branch
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}, clear=False):
            # This call would fail pre-fix with TypeError on the kwarg
            # mismatch. Post-fix it returns cleanly via the
            # "RESEND_API_KEY not set" guard.
            permit_renewal.RESEND_API_KEY = ""
            _run(permit_renewal._send_health_check_alert(db, ["unreachable"]))

    def test_cooldown_branch_uses_passed_in_db(self):
        """When RESEND_API_KEY + OWNER_ALERT_EMAIL are set, the
        function reaches the cooldown branch which calls
        `db.system_config.find_one(...)`. Pre-fix this is the line
        that raised NameError. Post-fix it uses the parameter."""
        db = MagicMock()
        db.system_config = MagicMock()
        # Cooldown record from <24h ago → suppression branch fires
        # and the function returns before any Resend call.
        db.system_config.find_one = AsyncMock(return_value={
            "key": "dob_health_check_last_alert",
            "sent_at": datetime.now(timezone.utc) - timedelta(hours=1),
        })
        permit_renewal.RESEND_API_KEY = "fake"
        permit_renewal.OWNER_ALERT_EMAIL = "owner@example.com"
        try:
            _run(permit_renewal._send_health_check_alert(db, ["issue"]))
        finally:
            permit_renewal.RESEND_API_KEY = ""
            permit_renewal.OWNER_ALERT_EMAIL = ""
        # Cooldown read happened against the passed-in db — proves
        # the parameter is wired through.
        db.system_config.find_one.assert_awaited_once_with(
            {"key": "dob_health_check_last_alert"}
        )


# ── run_dob_now_health_check: js_hash_current NameError ────────────

class TestHealthCheckJsHashFix(unittest.TestCase):
    """The persistence write at the end of `run_dob_now_health_check`
    referenced an undefined `js_hash_current` symbol. Pre-fix: every
    invocation raised NameError on the persistence step (after the
    HTTP probe ran successfully). Post-fix: js_hash is persisted as
    None and the function returns cleanly."""

    def test_writes_persisted_record_without_nameerror(self):
        captured = {}

        # Stub the HTTP client to return 200 — keeps the issues list
        # empty and avoids reaching _send_health_check_alert (covered
        # in the test class above).
        class _StubResp:
            status_code = 200
        class _StubClient:
            async def __aenter__(self_inner): return self_inner
            async def __aexit__(self_inner, *a): return False
            async def get(self_inner, url, **kw): return _StubResp()

        async def _capture_update(filt, update, upsert=False):
            captured["filter"] = filt
            captured["update"] = update
            captured["upsert"] = upsert
            return MagicMock()

        db = MagicMock()
        db.system_config = MagicMock()
        db.system_config.update_one = AsyncMock(side_effect=_capture_update)

        with patch("permit_renewal.ServerHttpClient", new=lambda *a, **kw: _StubClient()):
            result = _run(permit_renewal.run_dob_now_health_check(db))

        # Function returned cleanly — pre-fix this was a NameError.
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["issues"], [])

        # Persisted doc has js_hash=None (not undefined).
        update = captured.get("update", {})
        set_fields = update.get("$set", {})
        self.assertIn("js_hash", set_fields,
                      "writer dropped js_hash key entirely")
        self.assertIsNone(set_fields["js_hash"],
                          "js_hash should be None in the persisted doc")
        # Sanity: other fields still populated.
        self.assertEqual(set_fields["status"], "passed")
        self.assertEqual(set_fields["issues"], [])
        self.assertEqual(captured["upsert"], True)


if __name__ == "__main__":
    unittest.main()
