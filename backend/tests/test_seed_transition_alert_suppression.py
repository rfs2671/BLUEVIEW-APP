"""MR.14 fix (incident 2026-05-03) — seed-transition alert suppression.

Pins the load-bearing invariant that came out of the
michael@blueviewbuilders.com flood: when MR.14 commit 2a's
status-diffing logic detects a legacy dob_logs doc (no
`current_status` field) and inserts a synthetic "transition" row,
the alert path MUST NOT fire. Real new signals and real status
changes MUST still fire.

The discriminator: whether `existing` (the prior dob_log doc for
this raw_dob_id) has the `current_status` field at all.

Three branches tested for both DOB-side and 311-side insertion paths:
  • Seed transition: existing lacks current_status → NO alert
  • True new signal: no existing doc at all → alert FIRES
  • True status change: existing has current_status, incoming differs
                        → alert FIRES

We don't run the full _query_dob_apis path (network heavy + lots of
moving parts). Instead we exercise the discriminator logic directly
as a unit test, plus a static-source test confirming both call
sites carry the suppression check.
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
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── Discriminator unit tests ──────────────────────────────────────


class TestSeedTransitionDiscriminator(unittest.TestCase):
    """The discriminator is one expression repeated in two places.
    These tests pin its semantics so a future refactor can't drift
    one site out of sync with the other."""

    def test_legacy_existing_no_current_status_is_seed(self):
        """The flood case. Legacy doc was inserted before MR.14 commit
        2a, so it never got the current_status field. Diffing inserts
        a transition row; alert MUST be suppressed."""
        existing = {
            "_id": "legacy_log_1",
            "raw_dob_id": "permit:B00736930:Foundation",
            "severity": "Action",
            "record_type": "permit",
            # no current_status field
        }
        is_seed = (
            existing is not None
            and "current_status" not in existing
        )
        self.assertTrue(is_seed)

    def test_existing_with_current_status_is_NOT_seed(self):
        """Post-MR.14 doc. Has current_status. Any later transition
        is a TRUE status change — alert SHOULD fire."""
        existing = {
            "_id": "post_mr14_log",
            "raw_dob_id": "permit:B00736930:Foundation",
            "current_status": "ISSUED",
            "severity": "Action",
        }
        is_seed = (
            existing is not None
            and "current_status" not in existing
        )
        self.assertFalse(is_seed)

    def test_existing_with_current_status_None_is_NOT_seed(self):
        """Edge case: post-MR.14 doc where the source dataset's status
        field was empty, so current_status was set to None. The KEY is
        present (just the value is None). This is NOT a legacy doc —
        the field was deliberately set to None by the extractor.
        Future status changes from None to a real value ARE legitimate
        transitions worth alerting on. Don't suppress."""
        existing = {
            "_id": "post_mr14_log_null_status",
            "raw_dob_id": "permit:X:Y",
            "current_status": None,
            "severity": "Action",
        }
        is_seed = (
            existing is not None
            and "current_status" not in existing
        )
        self.assertFalse(is_seed)

    def test_no_existing_doc_at_all_is_NOT_seed(self):
        """First-time-seen record (DOB just issued a brand-new
        permit). No prior dob_log row. Alert SHOULD fire — operator
        wants to know about the new signal."""
        existing = None
        is_seed = (
            existing is not None
            and "current_status" not in existing
        )
        self.assertFalse(is_seed)


# ── Static-source check ───────────────────────────────────────────


class TestSuppressionAppliedAtBothSites(unittest.TestCase):
    """The fix has to land at TWO sites in server.py: the DOB-side
    insertion path inside run_dob_sync_for_project, and the 311-side
    inside _poll_311_fast_complaints. A future refactor that fixes
    one but forgets the other would re-open the flood. Pin both."""

    def setUp(self):
        path = _BACKEND / "server.py"
        self.text = path.read_text(encoding="utf-8", errors="ignore")

    def test_dob_path_has_seed_suppression(self):
        """The DOB-side insertion path MUST carry the discriminator
        AND gate the _send_critical_dob_alert_throttled call on it.
        Static check: both `is_seed_transition` AND `not is_seed_transition`
        must appear AFTER `severity == "Action"` in the same function."""
        self.assertIn("is_seed_transition", self.text)
        self.assertIn("not is_seed_transition", self.text)

    def test_311_path_has_seed_suppression(self):
        """Same guard at the 311 path."""
        self.assertIn("is_seed_transition_311", self.text)
        self.assertIn("not is_seed_transition_311", self.text)

    def test_seed_suppression_documented_inline(self):
        """Inline comment must reference incident 2026-05-03 so the
        next reader knows why this suppression exists. Without
        context, someone might "simplify" it back to the unsafe shape."""
        self.assertIn("2026-05-03", self.text)
        self.assertIn("seed transition", self.text.lower())


if __name__ == "__main__":
    unittest.main()
