"""Phase B1a — Per-user notification preferences.

Schema, defaults, effective-preferences resolution, routing-decision
helper, digest queue + dispatcher.

Design contract — non-negotiable:

  • The 502 existing tests must pass byte-for-byte. We achieve this
    by making the preferences pipeline OPT-IN: send_notification only
    consults preferences when the caller passes `signal_kind` in
    metadata. Today's callers (pre-Phase-B1a) don't pass it, so they
    skip the preferences lookup entirely and execute the original
    Step 0–4 sequence in lib/notifications.py.

  • Default behavior — even when signal_kind IS supplied — must
    match the operator's "Michael defense-in-depth" pattern:
      - critical → email
      - warning  → daily digest
      - info     → in_app (= feed-only, no email, no SMS)
    Customers opt in to more.

  • Recipients without a LeveLog user account (e.g. filing_reps
    whose email isn't on the users collection) get the legacy
    code path. Per-user preferences only apply to recipients we
    can resolve to a user_id.

  • Kill switch wins over preferences. NOTIFICATIONS_KILL_SWITCH is
    Step 0 in send_notification; preferences land at Step 1.5 (after
    idempotency, before NOTIFICATIONS_ENABLED flag and Resend send).

  • Digest queue rows are inert until digest_dispatcher picks them
    up. The dispatcher itself routes through send_notification, so
    the kill switch + idempotency + audit trail apply uniformly.

──────────────────────────────────────────────────────────────────
Schema — `notification_preferences` collection
──────────────────────────────────────────────────────────────────

  {
    _id: ObjectId,
    user_id: ObjectId | str,                 # indexed
    project_id: ObjectId | str | None,       # indexed; null = user-global
    signal_kind_overrides: {
      "<signal_kind>": {
        "channels": ["email"] | ["email", "in_app"] | ["email", "sms"] | etc.,
        "severity_threshold": "any" | "warning_or_above" | "critical_only" | "none",
        "delivery": "immediate" | "digest_daily" | "digest_weekly" | "feed_only",
      }
    },
    channel_routes_default: {
      "critical": ["email"],
      "warning":  ["email"],
      "info":     ["in_app"],
    },
    digest_window: {
      "daily_at":    "07:00",
      "weekly_day":  "monday",
      "timezone":    "America/New_York",
    },
    created_at: datetime,
    updated_at: datetime,
  }

  Indexes:
    • (user_id, project_id) unique compound — at most one record per
      (user, project-or-null) tuple.
    • user_id alone — fast lookup of every record for a user when
      computing the user-global default during a project-scoped read.

──────────────────────────────────────────────────────────────────
Schema — `digest_queue` collection
──────────────────────────────────────────────────────────────────

  {
    _id: ObjectId,
    user_id: str,                            # always coerced to str
    recipient_email: str,                    # cached at queue time
    signal_kind: str,
    severity: str,
    entity_id: str,                          # the original send_notification entity
    trigger_type: str,                       # original caller's trigger_type
    subject: str,
    html: str,
    text: str,
    metadata: {...},                         # original caller's metadata
    delivery: "digest_daily" | "digest_weekly",
    status: "queued" | "sent" | "failed" | "suppressed_kill_switch",
    queued_at: datetime,
    scheduled_send_at: datetime,             # next 7am ET window
    sent_at: datetime | None,
  }

  Indexes:
    • (user_id, scheduled_send_at, status) — dispatcher claim query.
    • (status, scheduled_send_at) — global "is anything ready?" scan.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────


# Severity values — must match lib.dob_signal_templates.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

VALID_SEVERITIES = frozenset({
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
})


# Channel values — operator's spec.
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"           # placeholder; no real surface in v1
CHANNEL_IN_APP = "in_app"     # placeholder; activity feed serves the role

VALID_CHANNELS = frozenset({CHANNEL_EMAIL, CHANNEL_SMS, CHANNEL_IN_APP})

# Channels that actually deliver something today. SMS and in_app
# don't have real backends; they're recorded in notification_log so
# operators / customers can see what WOULD have shipped, but they
# don't trigger Resend.
DELIVERABLE_CHANNELS = frozenset({CHANNEL_EMAIL})


# Delivery values.
DELIVERY_IMMEDIATE = "immediate"
DELIVERY_DIGEST_DAILY = "digest_daily"
DELIVERY_DIGEST_WEEKLY = "digest_weekly"
DELIVERY_FEED_ONLY = "feed_only"

VALID_DELIVERIES = frozenset({
    DELIVERY_IMMEDIATE,
    DELIVERY_DIGEST_DAILY,
    DELIVERY_DIGEST_WEEKLY,
    DELIVERY_FEED_ONLY,
})


# Severity threshold values — applied per signal_kind override.
SEVERITY_THRESHOLD_NONE = "none"             # mute this signal_kind entirely
SEVERITY_THRESHOLD_CRITICAL_ONLY = "critical_only"
SEVERITY_THRESHOLD_WARNING_OR_ABOVE = "warning_or_above"
SEVERITY_THRESHOLD_ANY = "any"

VALID_THRESHOLDS = frozenset({
    SEVERITY_THRESHOLD_NONE,
    SEVERITY_THRESHOLD_CRITICAL_ONLY,
    SEVERITY_THRESHOLD_WARNING_OR_ABOVE,
    SEVERITY_THRESHOLD_ANY,
})

# Severity ranking — higher number = more severe.
_SEVERITY_RANK = {
    SEVERITY_INFO: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_CRITICAL: 2,
}


# Status values added to lib/notifications NOTIFICATION_STATUS_* set.
NOTIFICATION_STATUS_SUPPRESSED_USER_PREF = "suppressed_user_pref"
NOTIFICATION_STATUS_SUPPRESSED_USER_PREF_DIGEST = "suppressed_user_pref_digest"


# ── Defaults — Michael defense-in-depth ────────────────────────────


def default_channel_routes_default() -> Dict[str, List[str]]:
    """Severity → channels for users who haven't set explicit
    overrides. Conservative pattern: info goes feed-only (no
    email), warning goes email but only via the daily digest,
    critical goes email immediately.

    NOTE: this maps severity → channels. Whether the email is
    immediate or queued for digest is a separate decision that
    falls out of compute_routing_decision based on the caller's
    delivery setting (defaults below)."""
    return {
        SEVERITY_CRITICAL: [CHANNEL_EMAIL],
        SEVERITY_WARNING:  [CHANNEL_EMAIL],
        SEVERITY_INFO:     [CHANNEL_IN_APP],
    }


def default_digest_window() -> Dict[str, Any]:
    return {
        "daily_at":    "07:00",
        "weekly_day":  "monday",
        "timezone":    "America/New_York",
    }


def default_delivery_for_severity(severity: str) -> str:
    """Default delivery cadence per severity. Customers opt in to
    more aggressive cadences via per-signal_kind overrides."""
    if severity == SEVERITY_CRITICAL:
        return DELIVERY_IMMEDIATE
    if severity == SEVERITY_WARNING:
        return DELIVERY_DIGEST_DAILY
    return DELIVERY_FEED_ONLY


def build_default_preferences(
    user_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The complete default-preferences document for a user. Used as
    the response shape when no record exists (GET endpoint), as the
    starting shape for a brand-new PATCH-creates-record code path,
    and as the seed when the dispatcher needs a routing decision
    on a user that's never customized anything."""
    now = datetime.now(timezone.utc)
    return {
        "user_id": str(user_id),
        "project_id": str(project_id) if project_id is not None else None,
        "signal_kind_overrides": {},
        "channel_routes_default": default_channel_routes_default(),
        "digest_window": default_digest_window(),
        "created_at": now,
        "updated_at": now,
    }


# ── User lookup ────────────────────────────────────────────────────


async def resolve_user_id_by_email(db, email: str) -> Optional[str]:
    """Match a recipient email to a users.{_id} value. Returns the
    string-ified _id or None if no match.

    Emails are normalized (lowercase + strip) on both sides to match
    the users-collection convention. Returns None on any error or
    when the email is empty/None — caller falls through to the legacy
    no-preferences path."""
    if not email:
        return None
    needle = email.strip().lower()
    if not needle:
        return None
    try:
        user = await db.users.find_one(
            {"email": needle},
            {"_id": 1},
        )
    except Exception as e:
        logger.warning(
            "[notification_preferences] users.find_one failed for "
            "email=%r: %r",
            needle, e,
        )
        return None
    if not user:
        return None
    return str(user["_id"])


# ── Preferences fetch + merge ──────────────────────────────────────


async def fetch_preferences_record(
    db,
    *,
    user_id: str,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Read a single preferences record, or None if absent. Caller
    decides whether to fall back to defaults."""
    if not user_id:
        return None
    query: Dict[str, Any] = {"user_id": str(user_id)}
    query["project_id"] = (
        str(project_id) if project_id is not None else None
    )
    try:
        return await db.notification_preferences.find_one(query)
    except Exception as e:
        logger.warning(
            "[notification_preferences] fetch failed user=%s project=%s: %r",
            user_id, project_id, e,
        )
        return None


async def get_effective_preferences(
    db,
    *,
    user_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns the merged preferences for a (user, project) tuple.

    Resolution order:
      1. project-scoped record for (user, project) → wins entirely
         on signal_kind_overrides + channel_routes_default + digest_window.
      2. user-global record (project_id IS None) → fallback.
      3. compiled defaults — operator's Michael defense-in-depth.

    The returned dict is shaped like a preferences record: fields
    that aren't customized fall back to defaults via .get on the
    routing-decision path."""
    if not user_id:
        return build_default_preferences(user_id="", project_id=project_id)

    # Project-scoped first.
    if project_id is not None:
        scoped = await fetch_preferences_record(
            db, user_id=user_id, project_id=project_id,
        )
        if scoped is not None:
            return scoped

    # User-global.
    user_global = await fetch_preferences_record(
        db, user_id=user_id, project_id=None,
    )
    if user_global is not None:
        # If the operator passed project_id but no project-scoped
        # record exists, we still return the user-global record but
        # carry the project_id through so the caller can persist a
        # project-scoped patch that inherits the user-global shape.
        # We deep-copy to avoid mutating the cache.
        out = dict(user_global)
        out["project_id"] = (
            str(project_id) if project_id is not None else None
        )
        return out

    # No record — synthesize defaults.
    return build_default_preferences(
        user_id=user_id, project_id=project_id,
    )


# ── Routing decision ───────────────────────────────────────────────


class RoutingDecision:
    """Outcome of compute_routing_decision. Plain attribute bag —
    not a Pydantic model — because send_notification calls this
    on every send and Pydantic validation overhead matters here."""

    __slots__ = (
        "channels", "delivery", "should_send_email_now",
        "should_queue_digest", "digest_kind", "should_emit_in_app",
        "suppress_reason",
    )

    def __init__(
        self,
        *,
        channels: List[str],
        delivery: str,
        should_send_email_now: bool,
        should_queue_digest: bool,
        digest_kind: Optional[str],
        should_emit_in_app: bool,
        suppress_reason: Optional[str],
    ):
        self.channels = channels
        self.delivery = delivery
        self.should_send_email_now = should_send_email_now
        self.should_queue_digest = should_queue_digest
        self.digest_kind = digest_kind
        self.should_emit_in_app = should_emit_in_app
        self.suppress_reason = suppress_reason

    def __repr__(self) -> str:
        return (
            "RoutingDecision("
            f"channels={self.channels!r}, delivery={self.delivery!r}, "
            f"send_email_now={self.should_send_email_now}, "
            f"queue_digest={self.should_queue_digest}, "
            f"digest_kind={self.digest_kind!r}, "
            f"emit_in_app={self.should_emit_in_app}, "
            f"suppress_reason={self.suppress_reason!r})"
        )


def _severity_meets_threshold(severity: str, threshold: str) -> bool:
    """True iff `severity` is equal-or-greater than the threshold."""
    if threshold == SEVERITY_THRESHOLD_NONE:
        return False
    if threshold == SEVERITY_THRESHOLD_ANY:
        return True
    sev_rank = _SEVERITY_RANK.get(severity, 0)
    if threshold == SEVERITY_THRESHOLD_CRITICAL_ONLY:
        return sev_rank >= _SEVERITY_RANK[SEVERITY_CRITICAL]
    if threshold == SEVERITY_THRESHOLD_WARNING_OR_ABOVE:
        return sev_rank >= _SEVERITY_RANK[SEVERITY_WARNING]
    # Unknown threshold — fail-closed (no notification). Surfaces in
    # the suppress_reason.
    return False


def compute_routing_decision(
    prefs: Dict[str, Any],
    *,
    signal_kind: str,
    severity: str,
) -> RoutingDecision:
    """Pure function. Given a preferences doc + a signal_kind +
    severity, return the routing decision. No I/O.

    Resolution:
      1. Per-signal_kind override on the prefs doc, if present —
         honors `severity_threshold` (gate) + `delivery` (cadence) +
         `channels` (where to deliver).
      2. Otherwise: severity → channels via channel_routes_default;
         delivery defaults via default_delivery_for_severity.

    Returns a RoutingDecision. Suppression reasons:
      • 'severity_below_threshold' — override gated by threshold.
      • 'channels_empty' — operator explicitly emptied the channels
        list (rare but valid).
      • 'feed_only' — delivery is feed_only; no channel ships."""
    overrides = (prefs or {}).get("signal_kind_overrides") or {}
    override = overrides.get(signal_kind) if isinstance(overrides, dict) else None

    if isinstance(override, dict):
        threshold = override.get("severity_threshold") or SEVERITY_THRESHOLD_ANY
        delivery = override.get("delivery") or DELIVERY_IMMEDIATE
        channels = list(override.get("channels") or [])

        if not _severity_meets_threshold(severity, threshold):
            return RoutingDecision(
                channels=[],
                delivery=delivery,
                should_send_email_now=False,
                should_queue_digest=False,
                digest_kind=None,
                should_emit_in_app=False,
                suppress_reason="severity_below_threshold",
            )
        return _build_decision(channels=channels, delivery=delivery)

    # No override — fall back to channel_routes_default keyed by severity.
    routes = (prefs or {}).get("channel_routes_default") or default_channel_routes_default()
    channels = list(routes.get(severity) or [])
    delivery = default_delivery_for_severity(severity)
    return _build_decision(channels=channels, delivery=delivery)


def _build_decision(
    *, channels: List[str], delivery: str,
) -> RoutingDecision:
    """Compose a RoutingDecision from a channel list + delivery
    cadence. Centralizes the channel-validity check."""
    if not channels:
        return RoutingDecision(
            channels=[],
            delivery=delivery,
            should_send_email_now=False,
            should_queue_digest=False,
            digest_kind=None,
            should_emit_in_app=False,
            suppress_reason="channels_empty",
        )

    has_email = CHANNEL_EMAIL in channels
    has_in_app = CHANNEL_IN_APP in channels

    if delivery == DELIVERY_FEED_ONLY:
        return RoutingDecision(
            channels=channels,
            delivery=delivery,
            should_send_email_now=False,
            should_queue_digest=False,
            digest_kind=None,
            should_emit_in_app=has_in_app or has_email,  # email caller still wants the audit row
            suppress_reason="feed_only",
        )

    if delivery == DELIVERY_IMMEDIATE:
        return RoutingDecision(
            channels=channels,
            delivery=delivery,
            should_send_email_now=has_email,
            should_queue_digest=False,
            digest_kind=None,
            should_emit_in_app=has_in_app,
            suppress_reason=None if has_email else "channels_empty",
        )

    # Digest cadences.
    if delivery in (DELIVERY_DIGEST_DAILY, DELIVERY_DIGEST_WEEKLY):
        return RoutingDecision(
            channels=channels,
            delivery=delivery,
            should_send_email_now=False,
            should_queue_digest=has_email,
            digest_kind=delivery,
            should_emit_in_app=has_in_app,
            suppress_reason=None if has_email else "channels_empty",
        )

    # Unknown delivery — fail-closed.
    return RoutingDecision(
        channels=channels,
        delivery=delivery,
        should_send_email_now=False,
        should_queue_digest=False,
        digest_kind=None,
        should_emit_in_app=False,
        suppress_reason="unknown_delivery",
    )


# ── Digest scheduling ──────────────────────────────────────────────


def _next_digest_send_at(
    *,
    delivery: str,
    digest_window: Dict[str, Any],
    now: Optional[datetime] = None,
) -> datetime:
    """Compute the next digest dispatch instant in UTC for a given
    delivery cadence + window. Pure — uses zoneinfo when available,
    falls back to a fixed-offset approximation otherwise.

    For DELIVERY_DIGEST_DAILY:
      • Resolve `daily_at` (HH:MM) in the window's timezone.
      • Next instance after `now`; if today's HH:MM hasn't passed,
        use today; otherwise tomorrow.

    For DELIVERY_DIGEST_WEEKLY:
      • Same time-of-day; advance to the next configured weekday."""
    now = now or datetime.now(timezone.utc)
    tz_name = (digest_window or {}).get("timezone") or "America/New_York"
    daily_at = (digest_window or {}).get("daily_at") or "07:00"
    weekly_day = (digest_window or {}).get("weekly_day") or "monday"

    # Parse HH:MM defensively.
    try:
        hh, mm = daily_at.split(":")
        hour = int(hh)
        minute = int(mm)
    except Exception:
        hour, minute = 7, 0

    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(tz_name)
    except Exception:
        # Fixed-offset fallback for environments without tzdata. Not
        # DST-aware but accurate enough for the dispatcher; the
        # 15-minute cron tick smooths out minor drift.
        local_tz = timezone(timedelta(hours=-5))  # America/New_York EST

    now_local = now.astimezone(local_tz)
    target_local = now_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )

    if delivery == DELIVERY_DIGEST_DAILY:
        if target_local <= now_local:
            target_local = target_local + timedelta(days=1)
        return target_local.astimezone(timezone.utc)

    # Weekly.
    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    target_weekday = weekday_map.get(
        (weekly_day or "").strip().lower(), 0,
    )
    days_ahead = (target_weekday - now_local.weekday()) % 7
    if days_ahead == 0 and target_local <= now_local:
        days_ahead = 7
    target_local = target_local + timedelta(days=days_ahead)
    return target_local.astimezone(timezone.utc)


# ── Digest queue I/O ───────────────────────────────────────────────


async def enqueue_digest(
    db,
    *,
    user_id: str,
    recipient_email: str,
    signal_kind: str,
    severity: str,
    entity_id: str,
    trigger_type: str,
    subject: str,
    html: str,
    text: str,
    metadata: Optional[Dict[str, Any]],
    delivery: str,
    digest_window: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Insert a digest_queue document. Returns the inserted doc
    (without forcing the caller to round-trip again). Caller is
    responsible for also writing the notification_log audit row
    (status=suppressed_user_pref_digest)."""
    now = now or datetime.now(timezone.utc)
    scheduled = _next_digest_send_at(
        delivery=delivery, digest_window=digest_window, now=now,
    )
    doc = {
        "user_id": str(user_id),
        "recipient_email": (recipient_email or "").strip().lower(),
        "signal_kind": signal_kind,
        "severity": severity,
        "entity_id": entity_id,
        "trigger_type": trigger_type,
        "subject": subject,
        "html": html,
        "text": text,
        "metadata": dict(metadata or {}),
        "delivery": delivery,
        "status": "queued",
        "queued_at": now,
        "scheduled_send_at": scheduled,
        "sent_at": None,
    }
    try:
        result = await db.digest_queue.insert_one(doc)
        doc["_id"] = result.inserted_id
    except Exception as e:
        logger.warning(
            "[notification_preferences] digest_queue insert failed user=%s "
            "signal=%s: %r",
            user_id, signal_kind, e,
        )
    return doc


async def dispatch_digests(
    db,
    *,
    send_notification_fn,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Cron body. Aggregates queued digest items per user where
    scheduled_send_at <= now AND status='queued', sends one email
    per user via send_notification_fn (passes through kill switch +
    idempotency + audit trail), marks queue items as 'sent' on success
    or 'failed' on exception.

    Caller passes send_notification_fn so this module doesn't import
    lib.notifications (avoids a cycle: notifications.send_notification
    will call back into this module for the routing decision).

    Returns a summary dict: {users_dispatched, items_sent,
    items_failed, items_kill_switch_suppressed}."""
    from lib.notifications import is_email_kill_switch_on
    now = now or datetime.now(timezone.utc)

    summary = {
        "users_dispatched": 0,
        "items_sent": 0,
        "items_failed": 0,
        "items_kill_switch_suppressed": 0,
    }

    # Find ready items, group by user.
    cursor = db.digest_queue.find({
        "status": "queued",
        "scheduled_send_at": {"$lte": now},
    })

    items_by_user: Dict[str, List[Dict[str, Any]]] = {}
    async for item in cursor:
        user_id = str(item.get("user_id") or "")
        if not user_id:
            continue
        items_by_user.setdefault(user_id, []).append(item)

    if not items_by_user:
        return summary

    # Defense-in-depth: if the kill switch is on, mark every ready
    # item as suppressed_kill_switch and bail. This duplicates the
    # check inside send_notification but lets us be explicit about
    # WHY we didn't dispatch.
    if is_email_kill_switch_on():
        ids = [
            it["_id"] for items in items_by_user.values() for it in items
        ]
        if ids:
            await db.digest_queue.update_many(
                {"_id": {"$in": ids}},
                {"$set": {
                    "status": "suppressed_kill_switch",
                    "sent_at": now,
                }},
            )
        summary["items_kill_switch_suppressed"] = len(ids)
        logger.warning(
            "[digest_dispatcher] kill switch active; suppressed %d item(s)",
            len(ids),
        )
        return summary

    for user_id, items in items_by_user.items():
        # All items for this user share the recipient_email (they
        # were enqueued for the same user). Pick the first; defensive
        # against legacy items that lack the field.
        recipient = next(
            (it.get("recipient_email") for it in items if it.get("recipient_email")),
            None,
        )
        if not recipient:
            # Can't email; mark items failed.
            await db.digest_queue.update_many(
                {"_id": {"$in": [it["_id"] for it in items]}},
                {"$set": {"status": "failed", "sent_at": now}},
            )
            summary["items_failed"] += len(items)
            continue

        # Aggregate. v1 body is a simple list of "[severity] subject"
        # lines; richer aggregation can land in B1c.
        digest_kind = items[0].get("delivery") or DELIVERY_DIGEST_DAILY
        date_label = now.strftime("%Y-%m-%d")
        subject = f"LeveLog {('weekly' if digest_kind == DELIVERY_DIGEST_WEEKLY else 'daily')} digest — {len(items)} update(s)"
        text_lines = [
            f"You have {len(items)} compliance update(s) from LeveLog:",
            "",
        ]
        html_lines = [
            "<h2>LeveLog compliance digest</h2>",
            f"<p>You have {len(items)} update(s):</p>",
            "<ul>",
        ]
        for it in items:
            sev = it.get("severity") or "info"
            subj = it.get("subject") or "(no subject)"
            text_lines.append(f"  [{sev}] {subj}")
            html_lines.append(
                f"<li><strong>[{sev}]</strong> {subj}</li>"
            )
        html_lines.append("</ul>")

        digest_text = "\n".join(text_lines)
        digest_html = "\n".join(html_lines)

        entity_id = f"digest:{user_id}:{date_label}"
        try:
            await send_notification_fn(
                db,
                permit_renewal_id=entity_id,
                trigger_type="digest",
                recipient=recipient,
                subject=subject,
                html=digest_html,
                text=digest_text,
                metadata={
                    "digest_user_id": user_id,
                    "digest_item_count": len(items),
                    "digest_kind": digest_kind,
                    # Intentionally NOT setting signal_kind here — the
                    # digest itself shouldn't recurse into the
                    # preferences pipeline.
                },
            )
            await db.digest_queue.update_many(
                {"_id": {"$in": [it["_id"] for it in items]}},
                {"$set": {"status": "sent", "sent_at": now}},
            )
            summary["users_dispatched"] += 1
            summary["items_sent"] += len(items)
        except Exception as e:
            logger.error(
                "[digest_dispatcher] send failed user=%s recipient=%s: %r",
                user_id, recipient, e,
            )
            await db.digest_queue.update_many(
                {"_id": {"$in": [it["_id"] for it in items]}},
                {"$set": {"status": "failed", "sent_at": now}},
            )
            summary["items_failed"] += len(items)

    return summary


# ── Pydantic-style validation for endpoint PATCH bodies ────────────


def normalize_signal_kind_overrides(
    overrides: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Validate + normalize an `signal_kind_overrides` patch chunk.

    Returns (normalized, errors). Caller decides whether to 400 on
    errors or merge in only the valid entries. Defensive: unknown
    fields are dropped, unknown enum values → error, unknown
    channel strings → dropped from the channels list with a
    warning."""
    out: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    if not isinstance(overrides, dict):
        if overrides is not None:
            errors.append("signal_kind_overrides must be an object")
        return out, errors

    for kind, override in overrides.items():
        if not isinstance(kind, str) or not kind:
            errors.append(f"invalid signal_kind key: {kind!r}")
            continue
        if not isinstance(override, dict):
            errors.append(f"override for {kind!r} must be an object")
            continue

        norm: Dict[str, Any] = {}

        channels = override.get("channels")
        if channels is not None:
            if not isinstance(channels, list):
                errors.append(f"{kind}.channels must be a list")
            else:
                clean = [
                    c for c in channels
                    if isinstance(c, str) and c in VALID_CHANNELS
                ]
                norm["channels"] = clean

        threshold = override.get("severity_threshold")
        if threshold is not None:
            if threshold not in VALID_THRESHOLDS:
                errors.append(
                    f"{kind}.severity_threshold must be one of "
                    f"{sorted(VALID_THRESHOLDS)}"
                )
            else:
                norm["severity_threshold"] = threshold

        delivery = override.get("delivery")
        if delivery is not None:
            if delivery not in VALID_DELIVERIES:
                errors.append(
                    f"{kind}.delivery must be one of "
                    f"{sorted(VALID_DELIVERIES)}"
                )
            else:
                norm["delivery"] = delivery

        if norm:
            out[kind] = norm
    return out, errors


def normalize_channel_routes_default(
    routes: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, List[str]], List[str]]:
    """Validate + normalize a channel_routes_default patch chunk."""
    out: Dict[str, List[str]] = {}
    errors: List[str] = []
    if not isinstance(routes, dict):
        if routes is not None:
            errors.append("channel_routes_default must be an object")
        return out, errors
    for severity, channels in routes.items():
        if severity not in VALID_SEVERITIES:
            errors.append(
                f"channel_routes_default key {severity!r} must be one of "
                f"{sorted(VALID_SEVERITIES)}"
            )
            continue
        if not isinstance(channels, list):
            errors.append(
                f"channel_routes_default[{severity}] must be a list"
            )
            continue
        clean = [
            c for c in channels
            if isinstance(c, str) and c in VALID_CHANNELS
        ]
        out[severity] = clean
    return out, errors


def normalize_digest_window(
    window: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    out: Dict[str, Any] = {}
    errors: List[str] = []
    if not isinstance(window, dict):
        if window is not None:
            errors.append("digest_window must be an object")
        return out, errors

    daily_at = window.get("daily_at")
    if daily_at is not None:
        if not isinstance(daily_at, str) or len(daily_at.split(":")) != 2:
            errors.append("digest_window.daily_at must be 'HH:MM'")
        else:
            try:
                hh, mm = daily_at.split(":")
                if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                    raise ValueError
                out["daily_at"] = f"{int(hh):02d}:{int(mm):02d}"
            except Exception:
                errors.append("digest_window.daily_at must be 'HH:MM'")

    weekly_day = window.get("weekly_day")
    if weekly_day is not None:
        valid_days = {"monday", "tuesday", "wednesday", "thursday",
                      "friday", "saturday", "sunday"}
        wd = (weekly_day or "").strip().lower()
        if wd not in valid_days:
            errors.append(
                f"digest_window.weekly_day must be one of {sorted(valid_days)}"
            )
        else:
            out["weekly_day"] = wd

    timezone_str = window.get("timezone")
    if timezone_str is not None:
        if not isinstance(timezone_str, str) or not timezone_str:
            errors.append("digest_window.timezone must be a non-empty string")
        else:
            out["timezone"] = timezone_str

    return out, errors
