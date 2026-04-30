"""MR.9 — Notification service: Resend integration + idempotency +
notification_log writes.

Centralizes the four steps every MR.9 trigger goes through:
  1. Build the email (templates lookup via lib.email_templates).
  2. Idempotency check against notification_log — skip if the same
     (permit_renewal_id, trigger_type, recipient) was sent in the
     last 23 hours. We use 23h instead of 24h so a daily cron at
     7am ET that drifts a few minutes past 7am the next day still
     dedups correctly.
  3. Resend send — wrapped in try/except so a single transient
     failure doesn't crash the cron. NOTIFICATIONS_ENABLED feature
     flag short-circuits the actual send: when off, we log the
     intent as `suppressed_flag_off` so operators can audit what
     would have gone out.
  4. notification_log write — always, regardless of send outcome.
     Status enum: sent / failed / suppressed_flag_off /
     suppressed_idempotent.

Existing Resend integration: server.py already does
`import resend` and reads `RESEND_API_KEY`. We re-use that pattern;
each callsite in this module imports `resend` lazily so the module
loads without the package present (e.g. in tests).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────

NOTIFICATIONS_ENABLED = os.environ.get(
    "NOTIFICATIONS_ENABLED", "false"
).strip().lower() in ("1", "true", "yes", "on")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# Match the existing FROM convention from server.py:
#   "Levelog <notifications@levelog.com>"
NOTIFICATION_FROM_ADDRESS = os.environ.get(
    "NOTIFICATION_FROM_ADDRESS",
    "Levelog <notifications@levelog.com>",
)

# Frontend base URL for action_link generation. Mirrors APP_BASE_URL
# in server.py:_permit_renewal_deep_link. Override per environment
# (preview vs production) via env var.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://www.levelog.com")

# Idempotency window — slightly less than 24h so a daily cron at 7am
# still dedups when it drifts a few minutes late. See module docstring.
IDEMPOTENCY_WINDOW_HOURS = 23


# ── Status enum ────────────────────────────────────────────────────

NOTIFICATION_STATUS_SENT = "sent"
NOTIFICATION_STATUS_FAILED = "failed"
NOTIFICATION_STATUS_SUPPRESSED_FLAG_OFF = "suppressed_flag_off"
NOTIFICATION_STATUS_SUPPRESSED_IDEMPOTENT = "suppressed_idempotent"
NOTIFICATION_STATUS_SUPPRESSED_NO_KEY = "suppressed_no_key"

VALID_NOTIFICATION_STATUSES = frozenset({
    NOTIFICATION_STATUS_SENT,
    NOTIFICATION_STATUS_FAILED,
    NOTIFICATION_STATUS_SUPPRESSED_FLAG_OFF,
    NOTIFICATION_STATUS_SUPPRESSED_IDEMPOTENT,
    NOTIFICATION_STATUS_SUPPRESSED_NO_KEY,
})


# ── Helpers ────────────────────────────────────────────────────────

def build_action_link(*, project_id: str, permit_dob_log_id: Optional[str] = None) -> str:
    """Deep link to the renewal-detail page on the LeveLog frontend.
    Matches the format of server.py:_permit_renewal_deep_link so
    operators get the same URL whether they click from the WhatsApp
    blurb or the email."""
    base = f"{APP_BASE_URL}/project/{project_id}/permit-renewal"
    if permit_dob_log_id:
        return f"{base}?permitId={permit_dob_log_id}"
    return base


async def collect_notification_recipients(db, company_id: str) -> List[str]:
    """Return the deduped list of email addresses to notify for a
    company. Sources:
      • All filing_reps[].email on the company doc.
      • The company's primary admin's email — first user with
        role in {admin, owner} and matching company_id, if any.

    Returns lowercased addresses with surrounding whitespace stripped.
    Empty list if no recipients found (caller should log + skip)."""
    out: List[str] = []
    seen = set()

    if not company_id:
        return out

    company = await db.companies.find_one({"_id": _to_query_id(company_id)})
    if company:
        for rep in (company.get("filing_reps") or []):
            email = (rep.get("email") or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                out.append(email)

    # Primary admin email — first matching user. We don't enforce
    # a "primary" flag since the user model doesn't carry one
    # explicitly; the first admin/owner is good enough for MR.9.
    try:
        admin_user = await db.users.find_one({
            "company_id": company_id,
            "role": {"$in": ["admin", "owner"]},
        })
        if admin_user:
            email = (admin_user.get("email") or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                out.append(email)
    except Exception as e:
        logger.warning(
            "[notifications] admin-email lookup failed for company %s: %r",
            company_id, e,
        )

    return out


def _to_query_id(s):
    """Local copy of server.to_query_id to avoid the circular import.
    Same behavior — try ObjectId, fall back to the string."""
    try:
        from bson import ObjectId
        return ObjectId(s)
    except Exception:
        return s


# ── Idempotency ────────────────────────────────────────────────────

async def is_idempotent_skip(
    db,
    *,
    permit_renewal_id: str,
    trigger_type: str,
    recipient: str,
) -> bool:
    """Returns True if a prior notification_log entry exists with
    status='sent' for the same (renewal, trigger, recipient) within
    IDEMPOTENCY_WINDOW_HOURS. Caller skips the send when True."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=IDEMPOTENCY_WINDOW_HOURS)
    existing = await db.notification_log.find_one({
        "permit_renewal_id": permit_renewal_id,
        "trigger_type": trigger_type,
        "recipient": recipient.lower().strip(),
        "status": NOTIFICATION_STATUS_SENT,
        "sent_at": {"$gte": cutoff},
    })
    return existing is not None


# ── Send ───────────────────────────────────────────────────────────

async def send_notification(
    db,
    *,
    permit_renewal_id: str,
    trigger_type: str,
    recipient: str,
    subject: str,
    html: str,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Single send + log entry. Returns the inserted notification_log
    document (without _id, since the caller usually doesn't need it).

    Order of checks:
      1. Idempotent? → log `suppressed_idempotent`, return.
      2. NOTIFICATIONS_ENABLED off? → log `suppressed_flag_off`,
         return. (This honors the operator's pre-key-rotation safety
         valve — see MR.9 spec task 10.)
      3. RESEND_API_KEY missing? → log `suppressed_no_key`, return.
         Distinct from `suppressed_flag_off` so the operator can
         tell whether the issue is configuration or feature-flag.
      4. Resend send. On success → log `sent` with resend_message_id.
         On exception → log `failed` with error_detail.
    """
    recipient = (recipient or "").strip().lower()
    now = datetime.now(timezone.utc)

    # Step 1 — idempotency.
    if await is_idempotent_skip(
        db,
        permit_renewal_id=permit_renewal_id,
        trigger_type=trigger_type,
        recipient=recipient,
    ):
        return await _write_log_entry(
            db,
            permit_renewal_id=permit_renewal_id,
            trigger_type=trigger_type,
            recipient=recipient,
            status=NOTIFICATION_STATUS_SUPPRESSED_IDEMPOTENT,
            subject=subject,
            metadata=metadata,
            now=now,
        )

    # Step 2 — feature flag.
    if not NOTIFICATIONS_ENABLED:
        logger.info(
            "[notifications] NOTIFICATIONS_ENABLED=false; would have sent "
            "trigger=%s renewal=%s recipient=%s subject=%r",
            trigger_type, permit_renewal_id, recipient, subject,
        )
        return await _write_log_entry(
            db,
            permit_renewal_id=permit_renewal_id,
            trigger_type=trigger_type,
            recipient=recipient,
            status=NOTIFICATION_STATUS_SUPPRESSED_FLAG_OFF,
            subject=subject,
            metadata=metadata,
            now=now,
        )

    # Step 3 — key configured?
    if not RESEND_API_KEY:
        logger.warning(
            "[notifications] RESEND_API_KEY unset; cannot send "
            "trigger=%s renewal=%s",
            trigger_type, permit_renewal_id,
        )
        return await _write_log_entry(
            db,
            permit_renewal_id=permit_renewal_id,
            trigger_type=trigger_type,
            recipient=recipient,
            status=NOTIFICATION_STATUS_SUPPRESSED_NO_KEY,
            subject=subject,
            metadata=metadata,
            now=now,
        )

    # Step 4 — actual send.
    resend_message_id: Optional[str] = None
    error_detail: Optional[str] = None
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        result = resend.Emails.send({
            "from": NOTIFICATION_FROM_ADDRESS,
            "to": [recipient],
            "subject": subject,
            "html": html,
            "text": text,
        })
        # The Resend SDK returns a dict like {"id": "..."}. Defensive:
        # accept both dict and object responses.
        if isinstance(result, dict):
            resend_message_id = result.get("id")
        elif hasattr(result, "id"):
            resend_message_id = getattr(result, "id")
    except Exception as e:
        error_detail = str(e)
        logger.error(
            "[notifications] Resend send failed for trigger=%s renewal=%s: %r",
            trigger_type, permit_renewal_id, e,
        )

    status = (
        NOTIFICATION_STATUS_SENT if error_detail is None
        else NOTIFICATION_STATUS_FAILED
    )
    return await _write_log_entry(
        db,
        permit_renewal_id=permit_renewal_id,
        trigger_type=trigger_type,
        recipient=recipient,
        status=status,
        subject=subject,
        resend_message_id=resend_message_id,
        error_detail=error_detail,
        metadata=metadata,
        now=now,
    )


async def _write_log_entry(
    db,
    *,
    permit_renewal_id: str,
    trigger_type: str,
    recipient: str,
    status: str,
    subject: str,
    resend_message_id: Optional[str] = None,
    error_detail: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    now: datetime,
) -> Dict[str, Any]:
    """Insert a notification_log document. Always called — the log
    is the audit trail across every status outcome."""
    doc = {
        "permit_renewal_id": permit_renewal_id,
        "trigger_type": trigger_type,
        "recipient": recipient,
        "subject": subject,
        "status": status,
        "sent_at": now,
        "resend_message_id": resend_message_id,
        "error_detail": error_detail,
        "metadata": dict(metadata or {}),
        "is_deleted": False,
    }
    try:
        result = await db.notification_log.insert_one(doc)
        doc["_id"] = result.inserted_id
    except Exception as e:
        logger.error(
            "[notifications] notification_log insert failed for "
            "trigger=%s renewal=%s: %r",
            trigger_type, permit_renewal_id, e,
        )
    return doc
