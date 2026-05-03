"""MR.14 (commit 2b) — notification routing per signal_kind.

Pins the admin-default policy. Per-user preferences are out of
scope for 2b (deferred to commit 3); these tests guard against
defaults silently changing.
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


class TestImmediateChannel(unittest.TestCase):
    """Critical signals MUST route to immediate email under the
    admin default policy. If a future commit accidentally moves
    one to 'digest_daily', operators miss real fires for hours."""

    def test_violation_dob_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("violation_dob"))

    def test_violation_ecb_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("violation_ecb"))

    def test_stop_work_full_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("stop_work_full"))

    def test_stop_work_partial_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("stop_work_partial"))

    def test_inspection_failed_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("inspection_failed"))

    def test_filing_disapproved_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("filing_disapproved"))

    def test_permit_expired_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("permit_expired"))

    def test_permit_revoked_is_immediate(self):
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("permit_revoked"))

    def test_final_signoff_is_immediate(self):
        """Both pass and fail final-signoff are milestones; always email."""
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("final_signoff"))

    def test_cofo_final_is_immediate(self):
        """Project-completion milestone — operators want this loud."""
        from lib.dob_signal_notifications import is_immediate_notification
        self.assertTrue(is_immediate_notification("cofo_final"))


class TestDigestChannels(unittest.TestCase):
    """Warning-level signals route to daily digest; info-level to
    weekly or feed-only."""

    def test_inspection_scheduled_is_daily_digest(self):
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_DIGEST_DAILY,
        )
        self.assertEqual(
            get_notification_channel("inspection_scheduled"),
            CHANNEL_DIGEST_DAILY,
        )

    def test_complaint_dob_is_daily_digest(self):
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_DIGEST_DAILY,
        )
        self.assertEqual(
            get_notification_channel("complaint_dob"),
            CHANNEL_DIGEST_DAILY,
        )

    def test_facade_fisp_is_daily_digest(self):
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_DIGEST_DAILY,
        )
        self.assertEqual(
            get_notification_channel("facade_fisp"),
            CHANNEL_DIGEST_DAILY,
        )

    def test_inspection_passed_is_weekly(self):
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_DIGEST_WEEKLY,
        )
        self.assertEqual(
            get_notification_channel("inspection_passed"),
            CHANNEL_DIGEST_WEEKLY,
        )

    def test_complaint_311_is_feed_only(self):
        """311 callers are noisy; don't email every one. Operator
        sees them in the activity feed; that's enough."""
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_FEED_ONLY,
        )
        self.assertEqual(
            get_notification_channel("complaint_311"),
            CHANNEL_FEED_ONLY,
        )


class TestUnknownKindFallback(unittest.TestCase):
    """Unknown signal_kinds (new dataset added without a policy)
    MUST fall back to feed-only. Fail-closed: a typo'd kind shouldn't
    accidentally email everyone."""

    def test_unknown_kind_is_feed_only(self):
        from lib.dob_signal_notifications import (
            get_notification_channel,
            CHANNEL_FEED_ONLY,
        )
        self.assertEqual(
            get_notification_channel("brand_new_signal_kind_xyz"),
            CHANNEL_FEED_ONLY,
        )


class TestPolicyCoversClassifierOutputs(unittest.TestCase):
    """Every concrete signal_kind from the classifier must have a
    policy entry. Catches the case where someone adds a classifier
    branch without setting the policy — the kind would silently
    fall back to feed-only."""

    def test_classifier_specific_outputs_have_policies(self):
        from lib.dob_signal_classifier import KNOWN_SIGNAL_KINDS
        from lib.dob_signal_notifications import SIGNAL_KIND_NOTIFICATION_POLICY
        # Generic fallback kinds (just record_type echoes) don't
        # need explicit policies; they fall through fine.
        FALLBACK_KINDS = {"unknown", "violation_open"}
        specific = set(KNOWN_SIGNAL_KINDS) - FALLBACK_KINDS
        missing = specific - set(SIGNAL_KIND_NOTIFICATION_POLICY.keys())
        self.assertEqual(
            missing, set(),
            f"signal_kinds without notification policy: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
