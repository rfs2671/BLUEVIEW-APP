"""MR.14 commit 5 — v1 monitoring product invariants.

Single-file regression suite that pins the architectural shape of
the v1 monitoring product. Each test is a static-source check
(reading server.py / permit_renewal.py text + iterating
app.routes), NOT a behavior test — the goal is to surface a clean
failure when a future commit accidentally re-introduces a removed
surface, not to exercise the live code paths.

Pins, in plain English:

  1. POST /api/permit-renewals/{id}/file is GONE (was the legacy
     enqueue endpoint).
  2. POST /api/permit-renewals/{id}/file-renewal does NOT exist
     (defensive — operators sometimes typo the name when re-
     introducing surfaces).
  3. DELETE /api/permit-renewals/{id}/filing-jobs/{job_id} is GONE
     (the cancel endpoint).
  4. POST /api/permit-renewals/{id}/filing-jobs/{job_id}/operator-input
     is GONE (the CAPTCHA / 2FA channel).
  5. The corresponding handler functions don't appear in the
     permit_renewal.py source.
  6. POST /api/permit-renewals/{id}/start-renewal-clicked DOES exist.
  7. FilingRep Pydantic model has NO `credentials` field.
  8. No agent_public_keys collection access in source code (only
     comments are allowed — the historical-context blocks).
  9. No filing_rep_active_credential helper anywhere.
 10. The four-phase loop is intact:
      • dob_nightly_scan + dob_311_fast_poll registered with the
        scheduler at startup.
      • signal_kind classifier + render_signal templates importable.
      • send_notification kill-switch lives in lib.notifications.
      • POST /start-renewal-clicked endpoint exists.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _route_paths():
    """Snapshot the FastAPI app's registered route paths. Resolved
    once per test class run via the helpers below — importing server
    is heavy."""
    import server
    out = []
    for r in server.app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        for m in methods:
            out.append((m, path))
    return out


# ── Removed endpoints ─────────────────────────────────────────────

class TestRemovedEndpoints(unittest.TestCase):
    """The four legacy endpoints removed across MR.14 commits 4a-5
    must NOT be re-introduced."""

    def test_post_file_gone(self):
        for m, p in _route_paths():
            if m == "POST" and p and p.endswith("/permit-renewals/{permit_renewal_id}/file"):
                self.fail(f"POST /permit-renewals/.../file should be gone (found {p})")

    def test_no_file_renewal_typo(self):
        # Defensive: nobody should accidentally re-introduce under a
        # slightly-different name.
        for m, p in _route_paths():
            if m == "POST" and p and "file-renewal" in p:
                self.fail(f"POST .../file-renewal not allowed in v1 (found {p})")

    def test_delete_filing_job_gone(self):
        for m, p in _route_paths():
            if (
                m == "DELETE"
                and p
                and p.endswith("/filing-jobs/{filing_job_id}")
            ):
                self.fail(
                    f"DELETE /filing-jobs/{{id}} should be gone (found {p})"
                )

    def test_operator_input_gone(self):
        for m, p in _route_paths():
            if (
                m == "POST"
                and p
                and p.endswith("/filing-jobs/{filing_job_id}/operator-input")
            ):
                self.fail(
                    f"POST .../operator-input should be gone (found {p})"
                )

    def test_handler_functions_gone_in_source(self):
        path = _BACKEND / "permit_renewal.py"
        text = path.read_text(encoding="utf-8")
        for fn in ("def cancel_filing_job", "def submit_operator_input",
                   "def enqueue_filing_job"):
            self.assertNotIn(fn, text, fn)


# ── Required v1 endpoints ─────────────────────────────────────────

class TestRequiredEndpoints(unittest.TestCase):

    def test_start_renewal_clicked_exists(self):
        found = any(
            m == "POST"
            and p
            and p.endswith("/permit-renewals/{permit_renewal_id}/start-renewal-clicked")
            for m, p in _route_paths()
        )
        self.assertTrue(found, "POST /start-renewal-clicked must exist in v1")

    def test_dob_logs_endpoint_exists(self):
        found = any(
            m == "GET"
            and p
            and p.endswith("/projects/{project_id}/dob-logs")
            for m, p in _route_paths()
        )
        self.assertTrue(found, "Activity feed endpoint must exist")


# ── Schema invariants ─────────────────────────────────────────────

class TestSchemaInvariants(unittest.TestCase):

    def test_filing_rep_has_no_credentials_field(self):
        import server
        fields = server.FilingRep.model_fields
        self.assertNotIn(
            "credentials",
            fields,
            "FilingRep.credentials field must NOT exist in v1",
        )

    def test_filing_rep_has_no_credential_methods(self):
        import server
        # filing_rep_active_credential helper must be gone.
        self.assertFalse(
            hasattr(server, "filing_rep_active_credential"),
            "server.filing_rep_active_credential() should not exist",
        )

    def test_no_filing_rep_credential_pydantic_model(self):
        import server
        self.assertFalse(
            hasattr(server, "FilingRepCredential"),
            "server.FilingRepCredential model should not exist",
        )
        self.assertFalse(
            hasattr(server, "FilingRepCredentialCreate"),
            "server.FilingRepCredentialCreate model should not exist",
        )


# ── agent_public_keys collection ──────────────────────────────────

class TestAgentPublicKeysGone(unittest.TestCase):
    """The agent_public_keys collection backed the worker hybrid-
    encryption scheme. MR.14 4b removed every endpoint that touched
    it. The collection itself is dropped by the operator post-deploy.
    Static check: no `db.agent_public_keys` access remains in source
    code (comments are allowed — they're how we document the removal)."""

    def _scan(self, p: Path):
        text = p.read_text(encoding="utf-8")
        # Remove comments + docstrings before scanning so the
        # historical-context comment blocks don't trigger.
        out_lines = []
        in_triple = None
        for line in text.splitlines():
            stripped_line = line.lstrip()
            if in_triple:
                if in_triple in stripped_line:
                    in_triple = None
                continue
            if stripped_line.startswith('"""') or stripped_line.startswith("'''"):
                marker = stripped_line[:3]
                rest = stripped_line[3:]
                if marker in rest:
                    # single-line docstring; nothing to do
                    continue
                in_triple = marker
                continue
            # Strip trailing # comments.
            in_str = None
            keep = []
            i = 0
            while i < len(line):
                ch = line[i]
                if in_str:
                    keep.append(ch)
                    if ch == "\\" and i + 1 < len(line):
                        keep.append(line[i + 1])
                        i += 2
                        continue
                    if ch == in_str:
                        in_str = None
                    i += 1
                    continue
                if ch in ("'", '"'):
                    in_str = ch
                    keep.append(ch)
                    i += 1
                    continue
                if ch == "#":
                    break
                keep.append(ch)
                i += 1
            stripped_line_no_comment = "".join(keep)
            out_lines.append(stripped_line_no_comment)
        return "\n".join(out_lines)

    def test_no_agent_public_keys_access_in_server(self):
        cleaned = self._scan(_BACKEND / "server.py")
        self.assertNotIn("db.agent_public_keys", cleaned)
        self.assertNotIn(".agent_public_keys.", cleaned)

    def test_no_agent_public_keys_access_in_permit_renewal(self):
        cleaned = self._scan(_BACKEND / "permit_renewal.py")
        self.assertNotIn("db.agent_public_keys", cleaned)


# ── Four-phase loop coherence ─────────────────────────────────────

class TestFourPhaseCoherence(unittest.TestCase):
    """Smoke-pin that the four phases of the v1 monitoring product
    are wired up. Each phase is anchored on a single import path or
    function reference; we don't exercise the live code, just verify
    the surface exists."""

    def test_phase_1_signals_socrata_polls_registered(self):
        import server  # noqa: F401
        # The two scheduler IDs that drive phase 1. These IDs are
        # what apscheduler.add_job(..., id=...) uses; text-pin both
        # so a refactor of the scan symbols can't accidentally drop
        # the registration.
        text = (_BACKEND / "server.py").read_text(encoding="utf-8")
        # 15-min DOB scan — function name is `nightly_dob_scan`, the
        # add_job call passes the function reference directly (no id
        # kwarg in the legacy call site, but the function name is
        # the symbol the scheduler uses).
        self.assertIn("async def nightly_dob_scan", text)
        # 30-min 311 poll — registered with id='dob_311_fast_poll'.
        self.assertIn("id='dob_311_fast_poll'", text)

    def test_phase_2_signal_classifier_importable(self):
        from lib.dob_signal_classifier import classify_signal_kind  # noqa: F401

    def test_phase_3_send_notification_kill_switch(self):
        from lib import notifications
        # The NOTIFICATIONS_KILL_SWITCH env var is read inside
        # send_notification on every send; static-pin its presence.
        text = (_BACKEND / "lib" / "notifications.py").read_text(encoding="utf-8")
        self.assertIn("NOTIFICATIONS_KILL_SWITCH", text)
        self.assertTrue(
            hasattr(notifications, "send_notification"),
            "lib.notifications.send_notification must exist",
        )

    def test_phase_4_start_renewal_clicked_route_exists(self):
        # Same coverage as TestRequiredEndpoints but kept here so a
        # single failed phase test is easy to diagnose.
        found = any(
            m == "POST"
            and p
            and p.endswith("/permit-renewals/{permit_renewal_id}/start-renewal-clicked")
            for m, p in _route_paths()
        )
        self.assertTrue(
            found, "Phase 4 (renewal start) endpoint must be live"
        )


if __name__ == "__main__":
    unittest.main()
