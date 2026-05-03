"""MR.14 (commit 2b) — notification routing per signal_kind.

Maps each signal_kind from lib.dob_signal_classifier to a
notification policy:

  • channel:       email | sms | in_app | digest_daily | digest_weekly | none
  • severity_floor: minimum severity that triggers (info / warning / critical)

The actual delivery is handled by lib/notifications.py (MR.9). This
module just answers: "for THIS signal_kind, what's the right
delivery rule for THIS user, given their preferences?"

Per-user preferences are out of scope for commit 2b (operator
deferred to commit 2c or commit 3). For 2b we ship the *admin
defaults* — a single policy per signal_kind that applies to every
admin/owner of the company.

Defaults per operator's spec:
  • critical (failed inspections, stop work orders, violations
    issued, filing disapproved) → immediate email
  • warning (permits expiring, scheduled inspections within 48h,
    license renewal due within 30d) → daily digest
  • info (status updates, scheduled inspections >48h out) →
    weekly digest or feed-only
"""

from __future__ import annotations

from typing import Dict


# ── Policy constants ──────────────────────────────────────────────


CHANNEL_EMAIL_IMMEDIATE = "email_immediate"
CHANNEL_DIGEST_DAILY = "digest_daily"
CHANNEL_DIGEST_WEEKLY = "digest_weekly"
CHANNEL_FEED_ONLY = "feed_only"  # no email; activity feed only


# ── Default routing policy per signal_kind ────────────────────────
#
# Maintenance: when a new signal_kind is added to the classifier,
# add an entry here. Tests pin coverage so a new kind without a
# policy breaks loudly.

SIGNAL_KIND_NOTIFICATION_POLICY: Dict[str, str] = {
    # ── critical: immediate email ──
    "violation_dob":       CHANNEL_EMAIL_IMMEDIATE,
    "violation_ecb":       CHANNEL_EMAIL_IMMEDIATE,
    "stop_work_full":      CHANNEL_EMAIL_IMMEDIATE,
    "stop_work_partial":   CHANNEL_EMAIL_IMMEDIATE,
    "inspection_failed":   CHANNEL_EMAIL_IMMEDIATE,
    "filing_disapproved":  CHANNEL_EMAIL_IMMEDIATE,
    "permit_expired":      CHANNEL_EMAIL_IMMEDIATE,
    "permit_revoked":      CHANNEL_EMAIL_IMMEDIATE,
    "final_signoff":       CHANNEL_EMAIL_IMMEDIATE,  # milestone, both pass+fail

    # ── warning: daily digest ──
    "complaint_dob":         CHANNEL_DIGEST_DAILY,
    "inspection_scheduled":  CHANNEL_DIGEST_DAILY,
    "license_renewal_due":   CHANNEL_DIGEST_DAILY,
    "facade_fisp":           CHANNEL_DIGEST_DAILY,
    "boiler_inspection":     CHANNEL_DIGEST_DAILY,
    "elevator_inspection":   CHANNEL_DIGEST_DAILY,
    "filing_withdrawn":      CHANNEL_DIGEST_DAILY,
    "cofo_pending":          CHANNEL_DIGEST_DAILY,

    # ── info: weekly digest or feed-only ──
    "permit_issued":      CHANNEL_DIGEST_WEEKLY,
    "permit_renewed":     CHANNEL_DIGEST_WEEKLY,
    "filing_approved":    CHANNEL_DIGEST_WEEKLY,
    "filing_pending":     CHANNEL_FEED_ONLY,
    "violation_resolved": CHANNEL_DIGEST_WEEKLY,
    "complaint_311":      CHANNEL_FEED_ONLY,
    "inspection_passed":  CHANNEL_DIGEST_WEEKLY,
    "cofo_temporary":     CHANNEL_DIGEST_WEEKLY,
    "cofo_final":         CHANNEL_EMAIL_IMMEDIATE,  # milestone — exception

    # ── fallback for unknown / generic kinds ──
    "permit":      CHANNEL_FEED_ONLY,
    "job_status":  CHANNEL_FEED_ONLY,
    "inspection":  CHANNEL_FEED_ONLY,
    "cofo":        CHANNEL_FEED_ONLY,
}


def get_notification_channel(signal_kind: str) -> str:
    """Returns the default notification channel for a signal_kind.
    Unknown kinds fall back to feed-only (no email) — fail-closed
    so a new signal type doesn't accidentally email everyone before
    its policy is set."""
    return SIGNAL_KIND_NOTIFICATION_POLICY.get(signal_kind, CHANNEL_FEED_ONLY)


def is_immediate_notification(signal_kind: str) -> bool:
    """Convenience predicate. True iff this signal_kind triggers
    an immediate email under the admin default policy."""
    return get_notification_channel(signal_kind) == CHANNEL_EMAIL_IMMEDIATE
