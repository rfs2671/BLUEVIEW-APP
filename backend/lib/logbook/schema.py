"""Phase V2.0 — logbook_entries schema constants + helpers.

Canonical taxonomy for category / status / source values, the
expected-workday rules (used by missing_detector), and the index
specs the startup hook ensures on the collection.

Schema (collection: logbook_entries):

    {
      _id:                ObjectId,
      company_id:         str,
      project_id:         str,
      entry_date:         str  (YYYY-MM-DD; matches db.daily_logs.date format),
      category:           str  (one of VALID_CATEGORIES),
      status:             str  (one of VALID_STATUSES),
      source:             str  (one of VALID_SOURCES),
      linked_dob_log_ids: [str] (optional cross-references),
      deficiency_reason:  str | None,
      attestation_data:   dict | None,    // populated for LL196
      created_at:         datetime,
      updated_at:         datetime,
      created_by_user_id: str | None,
    }

Indexes (LOGBOOK_ENTRIES_INDEXES below) are wired in server.py at
startup via _ensure_index_resilient.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterator, Optional

# ── Categories ────────────────────────────────────────────────────

CATEGORY_DAILY_LOG          = "daily_log"
CATEGORY_LL196              = "ll196_attestation"
CATEGORY_INSPECTION         = "inspection"
CATEGORY_DEFICIENCY         = "deficiency"
CATEGORY_MANPOWER           = "manpower"
CATEGORY_MATERIAL_DELIVERY  = "material_delivery"

VALID_CATEGORIES = (
    CATEGORY_DAILY_LOG,
    CATEGORY_LL196,
    CATEGORY_INSPECTION,
    CATEGORY_DEFICIENCY,
    CATEGORY_MANPOWER,
    CATEGORY_MATERIAL_DELIVERY,
)

# ── Statuses ──────────────────────────────────────────────────────

STATUS_COMPLETE   = "complete"
STATUS_MISSING    = "missing"
STATUS_DEFICIENT  = "deficient"
# A day the detector flagged that nobody worked. NOT "complete" -- the log was
# not filed and saying it was is the same false claim in the other direction --
# and not deleted, because the record of what the system asserted about a
# customer's compliance is worth keeping. 253 rows carried this shape on
# 2026-08-28: dead projects, duplicates, and a project nobody had ever worked
# through the gate. The read endpoints filter on STATUS_MISSING, so a row moved
# here leaves the customer's view without leaving the database.
STATUS_NO_SITE_ACTIVITY = "no_site_activity"

VALID_STATUSES = (STATUS_COMPLETE, STATUS_MISSING, STATUS_DEFICIENT,
                  STATUS_NO_SITE_ACTIVITY)

# ── Sources ───────────────────────────────────────────────────────

SOURCE_WHATSAPP       = "whatsapp"
SOURCE_MANUAL         = "manual"
SOURCE_AUTO_DETECTED  = "auto_detected"

VALID_SOURCES = (SOURCE_WHATSAPP, SOURCE_MANUAL, SOURCE_AUTO_DETECTED)

# ── Indexes (consumed by server.py startup) ───────────────────────
#
# Format mirrors the existing _ensure_index_resilient call sites:
# (keys, name, **opts).

LOGBOOK_ENTRIES_INDEXES = (
    {
        "keys": [("company_id", 1), ("project_id", 1), ("entry_date", 1)],
        "name": "logbook_company_project_date",
    },
    {
        "keys": [("project_id", 1), ("status", 1)],
        "name": "logbook_project_status",
    },
    {
        "keys": [("project_id", 1), ("category", 1)],
        "name": "logbook_project_category",
    },
    # Dedupe key for the missing_detector — one entry per
    # (project, date, category). The detector upserts on this key
    # so re-runs don't duplicate.
    {
        "keys": [("project_id", 1), ("entry_date", 1), ("category", 1)],
        "name": "logbook_project_date_category_unique",
        "unique": True,
    },
)


# ── Expected-workday rules ────────────────────────────────────────


def is_expected_workday(d: date, *, weekend_work: bool = False) -> bool:
    """Return True if a daily log is expected for the given date.

    Default rule: weekdays expected, weekends NOT expected. Projects
    with a `weekend_work` flag (e.g. emergency demo, court-ordered
    accelerated schedule) opt in to weekend expectations via the
    keyword arg.

    `d.weekday()` returns 0=Monday … 6=Sunday.
    """
    if weekend_work:
        return True
    return d.weekday() < 5  # Mon-Fri


def iter_expected_dates(
    start: date, end: date, *, weekend_work: bool = False,
) -> Iterator[date]:
    """Yield every expected-log date in `[start, end]` (inclusive),
    honoring the weekend_work toggle.

    Both bounds are inclusive — matches how operators describe a
    range ("from May 1 to May 7 = 7 days, Mon-Sun") and avoids
    fence-post bugs in the missing_detector.
    """
    if start > end:
        return
    cur = start
    while cur <= end:
        if is_expected_workday(cur, weekend_work=weekend_work):
            yield cur
        cur = cur + timedelta(days=1)


def date_to_str(d: date) -> str:
    """Canonical YYYY-MM-DD string. Matches db.daily_logs.date
    format so we can JOIN on entry_date == daily_logs.date."""
    return d.strftime("%Y-%m-%d")


def str_to_date(s: str) -> Optional[date]:
    """Parse YYYY-MM-DD; return None on bad input rather than
    raising. Defensive — Mongo can serve back surprising values
    over time."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
