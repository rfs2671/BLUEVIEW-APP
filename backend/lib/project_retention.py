"""When a project's records may be destroyed — and, almost always, may not.

ONE DEFINITION, for the same reason `project_state.py` is one definition: the
question "is this project still owed to a regulator?" is asked by the purge
endpoint, by the response model and by the owner's review screen, and three
copies of it would drift into three different answers about the same project.

WHAT THIS IS. A brake on `DELETE /projects/{id}/hard-delete`, which physically
destroys a project's entire compliance history and, by prefix sweep, the stored
photographs referenced from it. ESRA BB2024-007 §V.4 requires seven years past
job completion. Until now that period was, in the compliance doc's own words,
"Not computable. No job-completion date exists."

WHAT THIS IS NOT, and must never become. Nothing here schedules, expires, or
deletes. These are pure functions over a project document; this module has no
database handle and cannot act even if a caller wanted it to. `purge_eligible_at`
is COMPUTED FOR DISPLAY and stored nowhere — the moment it becomes a stored
field, something will eventually sort on it. A date seven years past does not
cause a deletion; it only stops this module objecting to one a human asked for.

ABSENCE IS NOT A DATE — THE dob_logs TTL INCIDENT.
`docs/runbooks/dob-logs-ttl-removal-2026-07-24.md` records what happens when a
retention clock is keyed on the wrong instant. Two TTL indexes on `dob_logs`
were keyed on `detected_at` — the moment the app FIRST SAW a record, not the
date the event occurred. Every row on both tracked projects carried the same
`2026-07-21` first-sync stamp, so a 2019 violation and a 2026 violation shared
one expiry, and the indexes would have physically destroyed every permit,
complaint, inspection and job-status row around 2026-10-19.

`job_completion_date` is therefore asserted by a human and by nothing else. It
is never inferred from `updated_at` (which moves when an NFC tag is minted),
never from `last_dob_sync_at`, never from last activity, and never from
`projects.status` — which `project_state.py` documents as written once at
creation and never updated. A field written once at creation is not a
lifecycle, and a guess about when a job ended is exactly the class of mistake
that runbook exists to prevent.

The name is `_date`, not `_at`, and the value is a `"YYYY-MM-DD"` string,
matching `ssp_expiration_date`. It is a calendar date a human asserts about the
past, not an instant. A tz-aware datetime here would re-introduce the
Eastern-vs-UTC bug `eastern_date()` was added to fix: from 20:00 EDT the UTC day
is already tomorrow in New York, and a completion stamped a day late moves the
whole seven-year period a day late with it.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional

# ESRA BB2024-007 §V.4. Also the period `docs/coi-retention-guarantee.md`
# already argues for, so the product has one retention number, not two.
RETENTION_YEARS = 7

# `ssp_expiration_date`'s convention, matched exactly. Strict on purpose:
# "2020-3-1" and "03/01/2020" are REJECTED rather than coerced, because a
# coerced date is an invented one and this value governs destruction.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_calendar_date(value: Any) -> Optional[date]:
    """A `"YYYY-MM-DD"` string as a date, or None if it is not one.

    None means "no usable assertion" for every caller. Nothing downstream may
    read that as "eligible" — see `purge_eligible_at`.
    """
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # A well-shaped string that is not a real day: "2026-02-30".
        return None


def add_retention_years(completed: date) -> date:
    """`completed` plus the retention period.

    THE LEAP DAY. A job completed 2020-02-29 has no 2027-02-29 to land on.
    Resolved toward MARCH 1 — retaining one day longer — because this value
    only ever gates a destruction. Clamping to February 28 would release the
    brake a day early, and "a day early" is the direction that loses records.
    """
    year = completed.year + RETENTION_YEARS
    try:
        return completed.replace(year=year)
    except ValueError:
        return date(year, completed.month + 1, 1)


def purge_eligible_at(project: Dict[str, Any]) -> Optional[str]:
    """The first day the retention brake is off, as `"YYYY-MM-DD"`.

    NEVER STORED. NEVER ACTED ON. Computed for the response so an owner can
    see the date before deciding, and recomputed on every read so it cannot go
    stale against a corrected completion date.

    None means "not computable", which is the honest answer for a project
    nobody has asserted a completion for — and it is the answer FOREVER, not
    "eligible now". This mirrors the soft-delete purge, which skips rows with
    no `deleted_at` rather than inventing one.
    """
    completed = parse_calendar_date(project.get("job_completion_date"))
    if completed is None:
        return None
    return add_retention_years(completed).isoformat()


def legal_hold_view(project: Dict[str, Any]) -> Dict[str, Any]:
    """The hold, flattened for a response payload.

    A hold NEVER EXPIRES. There is deliberately no duration, no review date and
    no age at which it lapses: it is set by a human and cleared by a human. The
    placement fields survive the clearing, so a hold that was lifted still says
    who placed it and why.
    """
    return {
        "legal_hold": bool(project.get("legal_hold")),
        "legal_hold_reason": project.get("legal_hold_reason"),
        "legal_hold_by": project.get("legal_hold_by"),
        "legal_hold_at": project.get("legal_hold_at"),
    }


def retention_refusal(
    project: Dict[str, Any], today: Optional[str] = None,
) -> Optional[str]:
    """Why this project's records may not be destroyed, or None if nothing
    objects.

    ORDER MATTERS. The hold is checked first and answers on its own, so a held
    project whose seven years have long elapsed is refused for the RIGHT
    reason — the reason is shown to the person who asked, and "the retention
    period ends 2017-01-01" would read as a reason to proceed.

    A None return is NOT permission. It is the absence of a retention
    objection; the caller's tenancy and role gates are unaffected and still
    apply. Nothing in this module authorises anything.

    THE ABSENT-DATE CASE, stated because it is the one judgment here. A project
    with no asserted completion is not refused. The brake bites on a RECORDED
    completion; it does not convert a missing record into a permanent lock on
    the owner's only cleanup path, which would silently disable the endpoint for
    every project that exists today. `purge_eligible_at` still reports None for
    such a project, so nothing automated could ever find it eligible.
    """
    if project.get("legal_hold"):
        reason = (project.get("legal_hold_reason") or "").strip()
        detail = "A legal hold is in force on this project"
        if reason:
            detail = f"{detail}: {reason}"
        return (
            f"{detail}. Records cannot be deleted while the hold stands. "
            "A hold does not expire; an admin must lift it."
        )

    eligible = purge_eligible_at(project)
    if eligible is None:
        return None

    # Compared as `"YYYY-MM-DD"` strings, which sort lexicographically exactly
    # as dates. `today` comes from eastern_date() — the NEW YORK calendar day,
    # since NYC DOB compliance is anchored to it and the UTC day is already
    # tomorrow in New York from 20:00 EDT.
    now = today or ""
    if now and now >= eligible:
        return None

    return (
        f"This project's records are retained for {RETENTION_YEARS} years after "
        f"job completion ({project.get('job_completion_date')}). "
        f"They may not be deleted before {eligible}."
    )
