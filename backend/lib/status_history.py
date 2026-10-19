"""Status history for dob_logs / dot_logs rows - the pure parts.

WHY THIS EXISTS (defect measured by the 2026 audit). Before this module a
dob_logs row carried only its FIRST-SIGHT status: every non-permit record type
(violation, DOB complaint, SWO, job_status, cofo, boiler, elevator, facade) was
INSERT-ONCE, so a Stop Work Order DOB later rescinded stayed 'open' forever and
a dismissed violation stayed 'active'. dot_logs kept only the latest status plus
`previous_status`, overwritten every 2h. A progress report sent to an owner or
lender needs the regulatory status AS IT WAS on a given date, and neither store
could answer that.

THE CONTRACT (other code relies on it). Every row carries

    status_history: [{"status": <str|None>, "at": <datetime UTC>,
                      "source": "first_seen" | "sync" | "legacy_first_refresh"}]

ordered by time. `status` is normalised exactly like dob_logs.current_status
(stripped + upper-cased; None when empty), so history, current_status and
previous_status always compare equal when they mean the same thing.

  first_seen             the row was created: one entry, at detected_at.
  sync                   a later sync saw a different status: appended.
  legacy_first_refresh   the row pre-dates this field. Its history is
                         SYNTHESISED as [first_seen: stored status @ detected_at]
                         and, if the API now says something different, this
                         entry is appended. We cannot know WHEN that change
                         really happened (the row was a never-refreshed
                         first-sight snapshot), so the entry says so, and the
                         caller marks the write `is_seed_transition` so NOTHING
                         is alerted (there was a documented incident of ~80
                         duplicate renewal emails from exactly this shape).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

FIRST_SEEN = "first_seen"
SYNC = "sync"
LEGACY_FIRST_REFRESH = "legacy_first_refresh"
SOURCES = (FIRST_SEEN, SYNC, LEGACY_FIRST_REFRESH)


def norm_status(v: Any) -> Optional[str]:
    """The normalisation of server._extract_dob_log_status: strip + upper,
    None for empty/absent."""
    if v is None:
        return None
    s = str(v).strip()
    return s.upper() if s else None


def as_utc(v: Any) -> Optional[datetime]:
    """An aware-UTC datetime, or None. pymongo hands back NAIVE datetimes
    (stored UTC) unless the client is tz-aware, so naive means UTC."""
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def entry(status: Any, at: datetime, source: str) -> Dict[str, Any]:
    return {"status": norm_status(status), "at": at, "source": source}


def _first_seen_at(row: Dict[str, Any], default: datetime) -> datetime:
    return (as_utc(row.get("detected_at")) or as_utc(row.get("created_at"))
            or default)


def prior_history(row: Dict[str, Any], now: datetime
                  ) -> Tuple[List[Dict[str, Any]], bool]:
    """(history, is_legacy) of a stored row. A row without a usable
    `status_history` is LEGACY: its history is synthesised from the stored
    current_status (dob_logs) or status (dot_logs) at detected_at. The stored
    value is used as-is (it was normalised when written)."""
    hist = row.get("status_history")
    if isinstance(hist, list) and hist:
        return [dict(e) for e in hist if isinstance(e, dict)], False
    stored = row["current_status"] if "current_status" in row else row.get("status")
    return [{"status": stored if stored is None else str(stored),
             "at": _first_seen_at(row, now), "source": FIRST_SEEN}], True


def new_row_history(status: Any, at: datetime) -> List[Dict[str, Any]]:
    """History of a row that has just been created (nothing existed)."""
    return [entry(status, at, FIRST_SEEN)]


def refreshed_history(existing: Dict[str, Any], new_status: Any, now: datetime,
                      *, changed: bool, in_place: bool
                      ) -> Tuple[List[Dict[str, Any]], bool]:
    """(history, is_legacy) for `existing` after a sync that saw `new_status`.

    `changed` is the caller's own change test (kept there so it cannot drift
    from the comparator that already decided insert-vs-update). When changed,
    one entry is appended: 'legacy_first_refresh' for an in-place refresh of a
    legacy row (see module docstring), otherwise 'sync'. Rows that form their
    own timeline (permits, 311: a NEW row per change, `in_place=False`) always
    append 'sync' - their stored status was refreshed on every sync, so the
    moment of change is known to within one poll and a legacy permit change is
    a genuine event, not a seed.
    """
    hist, legacy = prior_history(existing, now)
    if changed:
        src = LEGACY_FIRST_REFRESH if (legacy and in_place) else SYNC
        hist.append(entry(new_status, now, src))
    return hist, legacy
