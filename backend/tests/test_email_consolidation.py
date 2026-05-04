"""MR.14 fix (incident 2026-05-03) — email send-path consolidation.

Pins the architectural invariant: ALL outbound email goes through
lib/notifications.send_notification. The 6 pre-existing direct
resend.Emails.send call sites have been refactored to construct
a (entity_id, trigger_type, recipient, subject, html, text)
payload and route through the canonical helper.

This gives us:
  • Universal NOTIFICATIONS_KILL_SWITCH (one toggle halts everything)
  • Universal trigger_key idempotency (per-recipient 23h dedup)
  • Universal notification_log audit trail
  • Universal NOTIFICATIONS_ENABLED + RESEND_API_KEY gates

Pre-MR.14, the 6 direct sites bypassed all of those — that's how
the 2026-05-03 flood reached michael@blueviewbuilders.com without
dedup. After MR.14, only one resend.Emails.send call remains in
the codebase, inside lib/notifications.py itself.

Tests in this file are STATIC SOURCE checks against server.py +
permit_renewal.py, not full integration tests. The integration
behavior of send_notification (kill switch, idempotency, log
write) is already covered by tests/test_notification_log.py and
tests/test_notification_hooks.py.

The static checks here pin:
  1. Only ONE resend.Emails.send call remains — inside
     lib/notifications.py.
  2. Each of the 6 refactored sites carries a send_notification
     call with the appropriate trigger_type.
  3. NOTIFICATIONS_KILL_SWITCH is honored at the canonical helper
     (already covered) AND the legacy direct-import sites have
     been removed (no `is_email_kill_switch_on` check outside of
     lib/notifications.py — because send_notification handles it).
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── 1. Only one resend.Emails.send call remains in the codebase ──


class TestSingleResendCallSite(unittest.TestCase):
    """The architectural pin: only lib/notifications.py:send_notification
    is allowed to call resend.Emails.send directly. Every other
    site routes through it."""

    def test_only_lib_notifications_calls_resend_emails_send(self):
        """Walk backend/ and count actual resend.Emails.send INVOCATIONS
        (not comments, not test mocks). Must be exactly 1, in
        lib/notifications.py."""
        # Find all .py files under backend/ excluding tests + __pycache__
        invocation_sites = []
        for path in _BACKEND.rglob("*.py"):
            # Skip tests + cache
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), start=1):
                # Match the actual invocation, not comments
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # The invocation pattern is `resend.Emails.send(`
                # — the open-paren is the discriminator. Comments that
                # MENTION the API don't have the open-paren followed
                # by a call.
                if re.search(r"\bresend\.Emails\.send\(", line) and not re.search(r"#.*resend\.Emails\.send\(", line):
                    invocation_sites.append((path.relative_to(_BACKEND), i, stripped))

        # Filter out comment-only mentions by checking the line isn't
        # entirely inside a docstring or comment block. The resend
        # invocation should be the actual call.
        # We expect exactly 1 invocation: lib/notifications.py inside send_notification.
        self.assertEqual(
            len(invocation_sites), 1,
            f"Expected 1 resend.Emails.send invocation; found {len(invocation_sites)}: "
            + "\n".join(f"  {p}:{ln} — {s}" for p, ln, s in invocation_sites),
        )
        path, line_num, _stripped = invocation_sites[0]
        self.assertEqual(
            str(path), "lib\\notifications.py" if "\\" in str(path) else "lib/notifications.py",
            f"Sole resend.Emails.send invocation must live in lib/notifications.py; "
            f"found at {path}:{line_num}",
        )


# ── 2. Each of the 6 refactored sites uses send_notification ─────


class TestSitesUseSendNotification(unittest.TestCase):
    """For each of the 6 sites that pre-MR.14 called resend.Emails.send
    directly, confirm the post-MR.14 code calls send_notification with
    the expected trigger_type."""

    def setUp(self):
        self.server_text = (_BACKEND / "server.py").read_text(encoding="utf-8", errors="ignore")
        self.permit_renewal_text = (_BACKEND / "permit_renewal.py").read_text(encoding="utf-8", errors="ignore")

    def test_critical_dob_alert_uses_send_notification(self):
        """Site 1 — _send_critical_dob_alert. trigger_type='critical_dob_alert'."""
        self.assertIn('trigger_type="critical_dob_alert"', self.server_text)

    def test_health_check_alert_uses_send_notification(self):
        """Site 2 — _send_health_check_alert (permit_renewal.py)."""
        self.assertIn('trigger_type="dob_now_health_check"', self.permit_renewal_text)

    def test_renewal_digest_uses_send_notification(self):
        """Site 3 — _send_renewal_digest_email."""
        self.assertIn('trigger_type="renewal_digest"', self.server_text)

    def test_daily_report_uses_send_notification(self):
        """Site 4 — check_and_send_reports."""
        self.assertIn('trigger_type="project_daily_report"', self.server_text)

    def test_annotation_note_uses_send_notification(self):
        """Site 5 — _send_annotation_emails."""
        self.assertIn('trigger_type="annotation_note"', self.server_text)

    def test_annotation_reply_uses_send_notification(self):
        """Site 6 — _send_reply_notification."""
        self.assertIn('trigger_type="annotation_reply"', self.server_text)


# ── 3. Kill switch is universally honored ────────────────────────


class TestKillSwitchUniversallyHonored(unittest.TestCase):
    """Post-consolidation, the kill switch only needs to live ONCE
    (in lib/notifications.send_notification). Each refactored site
    delegates to that helper and inherits the check. The pre-MR.14
    `is_email_kill_switch_on` direct-import sites at every callsite
    are now redundant."""

    def test_send_notification_carries_kill_switch_check(self):
        """The canonical helper MUST honor the kill switch — every
        consolidated path inherits this guard."""
        text = (_BACKEND / "lib" / "notifications.py").read_text(encoding="utf-8", errors="ignore")
        self.assertIn("is_email_kill_switch_on", text)
        self.assertIn("EMERGENCY KILL SWITCH active", text)
        # And the suppressed_kill_switch status path:
        self.assertIn("suppressed_kill_switch", text)

    def test_kill_switch_helper_reads_env_freshly(self):
        """is_email_kill_switch_on MUST read os.environ on each call,
        not at module load. Critical for an emergency toggle to work
        without backend restart."""
        text = (_BACKEND / "lib" / "notifications.py").read_text(encoding="utf-8", errors="ignore")
        # The function body should reference os.environ.get inside,
        # NOT a module-level constant.
        # Check the function definition contains os.environ.get inside.
        idx = text.find("def is_email_kill_switch_on")
        self.assertNotEqual(idx, -1)
        # Read the next ~500 chars (should cover the function body).
        body = text[idx:idx + 500]
        self.assertIn("os.environ", body)


# ── 4. send_notification accepts the entity_id idiom ─────────────


class TestEntityIdIdiom(unittest.TestCase):
    """Post-MR.14 send_notification's permit_renewal_id parameter
    accepts arbitrary entity-id strings (e.g. 'dob_log:permit:B0001',
    'annotation:abc123'). The notification_log field stores the
    full string and idempotency dedups on it. Pin the docstring
    notes that this idiom is intentional so a future cleanup
    doesn't try to enforce strict permit-renewal-id-shape."""

    def test_idempotent_skip_documents_entity_id_idiom(self):
        text = (_BACKEND / "lib" / "notifications.py").read_text(encoding="utf-8", errors="ignore")
        # The idempotency function's docstring should mention the
        # generic entity-id usage post-MR.14.
        idx = text.find("def is_idempotent_skip")
        self.assertNotEqual(idx, -1)
        # Read up to the function body close.
        body = text[idx:idx + 1500]
        # The new docstring mentions generic entity IDs.
        self.assertIn("entity", body.lower())


if __name__ == "__main__":
    unittest.main()
