"""V2.3 Commit 7 — In-app notifications inbox.

Distinct from ``lib/notifications.py`` (email via Resend); this module
backs the FE project-page notifications surface that Commit 6's
predictions need in order to actually surface to operators. Replaces
Commit 6's WOULD-NOTIFY log line with persisted in-app entries.

Naming: the existing ``lib/notifications.py`` (MR.9 email service)
owns the "notifications" name in the lib namespace. To avoid the
collision, the in-app inbox lives here under
``lib/notifications_inbox.py``. The Mongo collection is named
``notifications`` (distinct from ``notification_log`` which is the
email-send audit trail).

PUBLIC SURFACE:

  • ``dispatch_notification(db, *, project, kind, severity, title,
    message, source_kind, source_id, metadata, expires_at,
    deeplink_anchor, deeplink_path) -> List[str]``
    — Fan-out to eligible users for a project. Per-user dedup on
    ``(user_id, source_kind, source_id)``. Returns inserted-id list.

  • ``cleanup_inbox(db, *, now=None) -> Dict[str, int]``
    — Daily cron entry. Two operations:
       (A) Delete notifications with non-null ``read_at`` older
           than ``READ_RETENTION_DAYS``.
       (B) Auto-dismiss notifications whose ``status == "active"``
           AND ``expires_at`` is in the past (sets
           ``status="dismissed"`` + ``dismissed_at=now``).

ELIGIBLE RECIPIENTS (per Stage 1 Q3 Option B):

  Users in the project's company who are either:
    • admins/owners of the company, OR
    • have the project id in their ``assigned_projects`` list.

  Fan-out is capped at ``MAX_DISPATCH_RECIPIENTS=100`` with a
  WARNING log if the eligible set exceeds the cap. Prevents a
  single dispatch from blowing up the inbox for projects with
  large team rosters.

DOCUMENT SCHEMA (``db.notifications``):

  _id           ObjectId
  user_id       str         # recipient (denormalized for fast read)
  company_id    str         # multi-tenant scoping
  project_id    str         # deeplink target
  project_name  str         # denormalized to avoid join on read
  kind          str         # "inspection_prediction" | (future)
  severity      str         # "info" | "warning" | "critical"
  title         str
  message       str         # 1-2 sentence body
  source_kind   str         # what generated this ("prediction")
  source_id     str         # FK to source (predicted_events._id)
  deeplink      str         # FE route path (may name a child
                            # route), may include #anchor
  status        str         # "active" | "dismissed"
  created_at    datetime
  read_at       datetime | None
  dismissed_at  datetime | None
  expires_at    datetime | None
  metadata      dict        # source-specific extras

Status lifecycle:
  • Created → ``status="active"``, ``read_at=None``,
    ``dismissed_at=None``.
  • User marks read → ``read_at`` set (status STAYS "active";
    "read" is encoded by ``read_at != None``, not by status).
  • Auto-dismissed by ``cleanup_inbox`` when expires_at passes →
    ``status="dismissed"`` + ``dismissed_at`` set.
  • Old read entries deleted by ``cleanup_inbox`` after
    ``READ_RETENTION_DAYS``.

FE default query filters ``status="active"`` so dismissed
entries don't clutter the inbox view.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# ── Collection name + tunables ────────────────────────────────────

# Stored on db.<NOTIFICATIONS_COLLECTION>. Distinct from
# ``notification_log`` (email audit trail) and
# ``notification_preferences`` (settings).
NOTIFICATIONS_COLLECTION = "notifications"

# Max users to insert one notification for per dispatch. Bounds
# write fan-out so a project with an unusually large team
# roster doesn't take down the DB on one prediction.
MAX_DISPATCH_RECIPIENTS = 100

# How long a READ notification is retained before cleanup_inbox
# deletes it. Tuned long enough for the operator to scroll back
# through recent activity, short enough to bound the collection's
# unbounded growth.
READ_RETENTION_DAYS = 90


# ── Helpers ───────────────────────────────────────────────────────


def _build_deeplink(
    project_id: str,
    anchor: Optional[str] = None,
    sub_path: Optional[str] = None,
) -> str:
    """Construct the FE deeplink path for a project. Matches the
    expo-router route shape (``/project/{id}``). Anchor is
    appended with ``#`` for FE scroll-into-view of the relevant
    section.

    ``sub_path`` names a CHILD ROUTE under the project — a real
    screen with its own file in ``frontend/app/project/[id]/``
    (``"trades"`` -> ``/project/{id}/trades``).

    THE TWO ARE NOT INTERCHANGEABLE, and treating them as one is
    how ``deeplink_anchor="workforce"`` shipped: an anchor points
    at a SECTION of the project page, so it can only ever reach a
    section that page renders. "workforce" was not one — the
    string had zero matches anywhere under ``frontend/`` — and the
    admin the notification was written for was sent to a fragment
    that resolved to nothing. A destination that is its own screen
    has to be a path.
    """
    base = f"/project/{project_id}"
    if sub_path:
        base = f"{base}/{sub_path.strip('/')}"
    if anchor:
        return f"{base}#{anchor}"
    return base


async def _resolve_eligible_recipients(
    db, *, company_id: str, project_id: str,
) -> List[Dict[str, Any]]:
    """Return users eligible to receive a notification for this
    project. Two paths:
      • Role-based: admin/owner of the company.
      • Assignment-based: project_id appears in
        user.assigned_projects.

    Excludes soft-deleted users. Returns the raw user dicts so
    the caller can read ``_id``.

    Errors are logged + return an empty list so dispatch fails
    silently rather than raising into the prediction path.
    """
    if not company_id:
        return []
    try:
        cursor = db.users.find({
            "company_id": company_id,
            "is_deleted": {"$ne": True},
            "$or": [
                {"role": {"$in": ["admin", "owner"]}},
                {"assigned_projects": project_id},
            ],
        })
        users: List[Dict[str, Any]] = []
        async for u in cursor:
            users.append(u)
        return users
    except Exception as e:
        logger.error(
            "[inbox] recipient resolution failed for project %s: %r",
            project_id, e,
        )
        return []


# ── Dispatch ──────────────────────────────────────────────────────


async def dispatch_notification(
    db,
    *,
    project: Dict[str, Any],
    kind: str,
    severity: str = "info",
    title: str,
    message: str,
    source_kind: str,
    source_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    expires_at: Optional[datetime] = None,
    deeplink_anchor: Optional[str] = None,
    deeplink_path: Optional[str] = None,
) -> List[str]:
    """Dispatch an in-app notification to all eligible users for
    a project. Returns the list of inserted notification ids
    (strings).

    Per-user dedup: if a notification already exists for
    ``(user_id, source_kind, source_id)``, that user is skipped
    (idempotent re-dispatch — same prediction firing twice
    produces one inbox row per user, not two).

    Fan-out cap: if the eligible recipient set exceeds
    ``MAX_DISPATCH_RECIPIENTS``, the dispatch truncates and
    logs a WARNING. Operator visibility into this cap matters
    because a 100-recipient project usually means a config
    mistake (e.g., a user accidentally assigned to all
    projects), not legitimate fan-out.

    Empty recipient set is a quiet no-op (INFO log). Errors at
    per-user insert are isolated: one user's failure doesn't
    block the other recipients.
    """
    project_id = str(project.get("_id") or project.get("id") or "")
    if not project_id:
        logger.warning(
            "[inbox] dispatch_notification called with no project_id; "
            "skipping (kind=%s source=%s:%s)",
            kind, source_kind, source_id,
        )
        return []

    company_id = str(project.get("company_id") or "")
    project_name = project.get("name") or ""

    recipients = await _resolve_eligible_recipients(
        db, company_id=company_id, project_id=project_id,
    )

    if not recipients:
        logger.info(
            "[inbox] no eligible recipients for project %s; "
            "skipping dispatch (kind=%s source=%s:%s)",
            project_id, kind, source_kind, source_id,
        )
        return []

    if len(recipients) > MAX_DISPATCH_RECIPIENTS:
        logger.warning(
            "[inbox] fan-out capped: project %s has %d eligible "
            "users; truncating to %d (kind=%s)",
            project_id, len(recipients), MAX_DISPATCH_RECIPIENTS, kind,
        )
        recipients = recipients[:MAX_DISPATCH_RECIPIENTS]

    now = datetime.now(timezone.utc)
    deeplink = _build_deeplink(
        project_id, anchor=deeplink_anchor, sub_path=deeplink_path,
    )

    inserted_ids: List[str] = []
    for user in recipients:
        user_id = str(user.get("_id") or user.get("id") or "")
        if not user_id:
            continue

        # Per-user dedup. Same prediction firing twice (or a
        # restart-replay) shouldn't produce a duplicate inbox
        # row.
        try:
            existing = await db[NOTIFICATIONS_COLLECTION].find_one({
                "user_id":     user_id,
                "source_kind": source_kind,
                "source_id":   source_id,
            })
        except Exception as e:
            logger.warning(
                "[inbox] dedup check failed for user %s "
                "(kind=%s source=%s:%s): %r",
                user_id, kind, source_kind, source_id, e,
            )
            existing = None

        if existing:
            logger.debug(
                "[inbox] dedup hit: user=%s source=%s:%s; skipping",
                user_id, source_kind, source_id,
            )
            continue

        doc = {
            "user_id":      user_id,
            "company_id":   company_id,
            "project_id":   project_id,
            "project_name": project_name,
            "kind":         kind,
            "severity":     severity,
            "title":        title,
            "message":      message,
            "source_kind":  source_kind,
            "source_id":    source_id,
            "deeplink":     deeplink,
            "status":       "active",
            "created_at":   now,
            "read_at":      None,
            "dismissed_at": None,
            "expires_at":   expires_at,
            "metadata":     dict(metadata or {}),
        }
        try:
            res = await db[NOTIFICATIONS_COLLECTION].insert_one(doc)
            inserted = getattr(res, "inserted_id", None)
            if inserted is not None:
                inserted_ids.append(str(inserted))
        except Exception as e:
            logger.warning(
                "[inbox] insert failed for user %s (kind=%s "
                "source=%s:%s): %r",
                user_id, kind, source_kind, source_id, e,
            )

    logger.info(
        "[inbox] dispatched %d notification(s) for project %s "
        "(kind=%s source=%s, eligible=%d)",
        len(inserted_ids), project_id, kind, source_kind,
        len(recipients),
    )
    return inserted_ids


# ── Cleanup ───────────────────────────────────────────────────────


async def cleanup_inbox(
    db, *, now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Daily 03:55 ET cron entry. Performs two operations:

      A. Delete notifications where ``read_at`` is non-null AND
         older than ``READ_RETENTION_DAYS``. Bounds the
         collection's long-term growth.
      B. Auto-dismiss notifications where ``status="active"``
         AND ``expires_at`` is non-null AND in the past. Sets
         ``status="dismissed"`` + ``dismissed_at=now``. Cleans up
         expired predictions from the FE's default
         ``status="active"`` filter without deleting the audit
         trail.

    Both operations are best-effort: errors in one don't block
    the other. Returns stats ``{deleted, dismissed}`` for the
    wrapper cron's log line.
    """
    cur_now = now or datetime.now(timezone.utc)
    read_cutoff = cur_now - timedelta(days=READ_RETENTION_DAYS)
    stats = {"deleted": 0, "dismissed": 0}

    # Operation A: delete old-read.
    try:
        result = await db[NOTIFICATIONS_COLLECTION].delete_many({
            "read_at": {"$ne": None, "$lt": read_cutoff},
        })
        stats["deleted"] = getattr(result, "deleted_count", 0) or 0
    except Exception as e:
        logger.error(
            "[inbox_cleanup] delete-old-read failed: %r", e,
        )

    # Operation B: auto-dismiss expired actives.
    try:
        result = await db[NOTIFICATIONS_COLLECTION].update_many(
            {
                "status":     "active",
                "expires_at": {"$ne": None, "$lt": cur_now},
            },
            {"$set": {
                "status":       "dismissed",
                "dismissed_at": cur_now,
            }},
        )
        stats["dismissed"] = getattr(result, "modified_count", 0) or 0
    except Exception as e:
        logger.error(
            "[inbox_cleanup] dismiss-expired failed: %r", e,
        )

    return stats
