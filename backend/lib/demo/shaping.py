"""THE SHAPING FUNCTIONS — one per screen, each returning what the REAL
handler returns, built from `dataset.py` and nothing else.

Pure functions over static data. No database, no network, no clock: the only
input is `today`, and the caller supplies it. Every function is safe to call
any number of times and returns a fresh structure each time, so a serialiser
cannot edit the canned set out from under the next request.

── WHY THE SHAPE IS THE WHOLE JOB ─────────────────────────────────────────

These payloads are consumed by screens written against the real endpoints. A
field the real handler returns and this one does not is a blank control, a
crash on `.map`, or — worst — a control the client renders in its "not
configured yet" state, which tells a prospect something false about the
product. So each function below names the handler it was derived from and
returns that handler's envelope exactly: the pagination envelope where there is
one, a bare list where the handler returns a bare list, the `{project_id,
…, logs}` object where that is what is sent.

── WHERE THIS MODULE BORROWS, AND WHERE IT RESTATES ───────────────────────

It imports two pure `lib/` modules and refuses to import anything else:

  * `lib.dob_signal_templates.render_signal` — the SAME renderer the real
    activity-feed handler runs over each row, so the demo's titles and bodies
    are the product's own copy rather than a second set that drifts from it;
  * `lib.logbook.weekly_cadence.toolbox_period` / `work_week` — the same rule
    the real `periods` payload is computed with.

It does NOT import `server`. Everything in server.py that this module would
otherwise call — `get_required_logbooks`, `logbook_activations`,
`is_immediate_preshift`, `logbook_timing_class` — is a rule that lives on the
far side of an import cycle, so those answers are STATED in `dataset.py` and
reconciled against the real functions by the test suite. The reconciliation is
a test rather than a comment because a comment cannot fail.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from lib.dob_signal_templates import render_signal
from lib.logbook.weekly_cadence import toolbox_period, work_week

from . import dataset as D

#: NYC DOB compliance runs on the New York calendar day, and the gate times in
#: the dataset are Eastern wall-clock. zoneinfo is stdlib and deterministic —
#: converting here is arithmetic, not I/O.
_EASTERN = ZoneInfo("America/New_York")

#: The immediate-freeze types, from `LOGBOOK_TIMING_CLASS`. Restated (see the
#: header) and reconciled by a test against `server.logbook_timing_class`.
_TIMING_CLASS = {
    "preshift_signin": "immediate",
    "toolbox_talk": "immediate",
    "subcontractor_orientation": "immediate",
    "osha_log": "immediate",
    "scaffold_maintenance": "immediate",
    "hot_work": "immediate",
    "concrete_operations": "immediate",
    "crane_operations": "immediate",
    "excavation_monitoring": "immediate",
    "fall_protection": "immediate",
    "daily_jobsite": "end_of_day",
    "ssc_daily_safety_log": "end_of_day",
    "site_superintendent_log": "visit",
}

#: The one log type whose filer is a named person rather than anyone on the
#: project — BC 3301.13.13 is the superintendent's own record, and the demo
#: signs it in his name rather than the CP's.
_CS_OWNED_LOG_TYPE = "site_superintendent_log"

#: The projection GET /workers applies (WORKER_LIST_FIELDS) plus the serialised
#: id. A list row in this app has never carried the card image, the signature,
#: the OSHA data or the certifications — each is served to the one screen that
#: needs it by an endpoint of its own — and a demo row that carried them would
#: be the only one in the product that does.
_WORKER_LIST_FIELDS = (
    "id", "name", "phone", "company", "trade", "company_id", "status",
    "is_deleted", "created_at", "updated_at",
)

#: The statuses the DOB summary counts as CLOSED. Anything else — including a
#: null — is open, which is the conservative reading for a compliance count.
_CLOSED_VIOLATION_STATES = {"certified", "dismissed", "paid", "resolved"}


# ── DATES ───────────────────────────────────────────────────────────────────

def _as_date(today) -> date:
    """The day this call is being made FOR.

    Accepts a `date`, an ISO string (which is what `eastern_date()` hands back
    on the server, so a route can pass its answer straight through), or None
    for the anchor. Anything else is a caller bug and raises rather than
    silently resolving to the anchor: a demo quietly rendering a fixed day in
    2026 is the failure this whole scheme exists to prevent, and it must not be
    reachable by passing the wrong type.
    """
    if today is None:
        return D.DEMO_ANCHOR
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    if isinstance(today, str):
        return date.fromisoformat(today[:10])
    raise TypeError(f"today must be a date, an ISO string or None, not {type(today)!r}")


def _is_instant_field(name: str) -> bool:
    """Does this field hold a moment rather than a calendar day?

    `at` and `*_at` do — `detected_at`, `created_at`, `completed_at` — and the
    real documents store those as datetimes while storing `date`,
    `expiration_date` and friends as strings. Rendering a datetime where the
    real row holds a string is how a client-side `.slice(0, 10)` starts
    printing a timezone.
    """
    return name == "at" or name.endswith("_at")


def _render_offset(field: str, days: int, today: date, *, forward: bool):
    day = today + timedelta(days=days) if forward else today - timedelta(days=days)
    if _is_instant_field(field):
        # Midday UTC. A nine-a.m. would be a claim about the hour something
        # happened, and these offsets only ever encoded a day.
        return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)
    return day.isoformat()


def _resolve(value, today: date):
    """Deep-copy `value`, resolving every date offset and dropping every
    `_`-prefixed key.

    The one place the offset convention documented in dataset.py is
    implemented. Everything the module returns goes through here, which is also
    what guarantees a caller cannot mutate the canned set: the structure handed
    back shares no dict or list with the constants.
    """
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if not isinstance(key, str) or not key.startswith("_"):
                out[key] = _resolve(inner, today)
                continue
            if key.endswith("_days_ago"):
                field = key[1:-len("_days_ago")]
                out[field] = _render_offset(field, inner, today, forward=False)
            elif key.endswith("_in_days"):
                field = key[1:-len("_in_days")]
                out[field] = _render_offset(field, inner, today, forward=True)
            # Any other `_` key is scaffolding for a builder below (the gate
            # times, the plan markers) and is dropped rather than served.
        return out
    if isinstance(value, list):
        return [_resolve(v, today) for v in value]
    if isinstance(value, tuple):
        return [_resolve(v, today) for v in value]
    return copy.deepcopy(value)


def _page(items: list, limit: int, skip: int) -> dict:
    """`paginated_query`'s envelope, computed the way it computes it: `total` is
    the size of the MATCHED set, not of the page, and `has_more` is
    `skip + limit < total`."""
    total = len(items)
    return {
        "items": items[skip:skip + limit],
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


# ── THE PROJECT ─────────────────────────────────────────────────────────────

def demo_project(today=None) -> dict:
    """GET /projects/{project_id}, and GET /demo/project.

    The response model on the real route is `ProjectResponse`; this carries
    every field it declares plus the five keys `_DEMO_PROJECT` has always
    carried (is_demo, dob_summary, recent_activity, special_inspections, note),
    which only survive because GET /demo/project has no response model.
    """
    day = _as_date(today)
    project = _resolve(D.DEMO_PROJECT, day)
    project["required_logbooks"] = list(D.DEMO_REQUIRED_LOGBOOKS)
    return project


def demo_project_list(today=None, limit: int = 50, skip: int = 0) -> dict:
    """GET /projects — the pagination envelope, with `defcon_tier` on each row.

    The real handler computes the tier per project and swallows any failure to
    None, because a list must not break on one project's compute. The demo has
    one project and no engine behind it, so the honest value is None: "no tier
    computed", which is the state the list already renders for a brand-new
    project.
    """
    row = demo_project(today)
    row["defcon_tier"] = None
    return _page([row], limit, skip)


def demo_required_logbooks(today=None) -> dict:
    """GET /projects/{project_id}/required-logbooks.

    Every key the real handler sends. `filing` and `activations` are stated in
    dataset.py and reconciled by tests; `periods` is COMPUTED, with the real
    rule, from the demo's own toolbox talk and check-ins — see
    `_toolbox_periods`.
    """
    day = _as_date(today)
    project = demo_project(day)
    return {
        "project_id": D.DEMO_PROJECT_ID,
        "project_class": project["project_class"],
        "classification_assessed": True,
        "required_logbooks": list(D.DEMO_REQUIRED_LOGBOOKS),
        "activations": copy.deepcopy(D.DEMO_ACTIVATIONS),
        "filing": copy.deepcopy(D.DEMO_FILING_RIGHTS),
        "periods": _toolbox_periods(day),
    }


def _toolbox_periods(day: date) -> list:
    """`_logbook_periods`' answer for the weekly log, from the real rule.

    `toolbox_period` is pure and lives in lib/, so the demo can ask the same
    question the server asks instead of asserting an answer. The three inputs
    are the demo's own: the date the talk was filed, whoever checked in on the
    Saturday or Sunday of this week, and whoever the talk names as an attendee.
    """
    filed = [_toolbox_talk_date(day).isoformat()]
    span = work_week(day)
    weekend_ids = set()
    if span:
        monday = span[0]
        weekend = {monday + timedelta(days=5), monday + timedelta(days=6)}
        if day in weekend:
            weekend_ids = {c["worker_id"] for c in D.DEMO_CHECKINS}
    covered = {
        a["worker_id"]
        for a in D.DEMO_LOGBOOK_DATA["toolbox_talk"]["attendees"]
        if a.get("worker_id")
    }
    row = toolbox_period(day, filed, weekend_ids, covered)
    return [row] if row else []


# ── THE LOGBOOKS ────────────────────────────────────────────────────────────

def _toolbox_talk_date(day: date) -> date:
    """The Monday of the work week containing `day` — see WEEK_START.

    `work_week` returns None only for an unreadable date, which cannot happen
    here; the fallback keeps the talk on the day being viewed rather than
    raising on a branch nothing can reach.
    """
    span = work_week(day)
    return span[0] if span else day


def _logbook_date(offset, day: date) -> date:
    if offset == D.WEEK_START:
        return _toolbox_talk_date(day)
    return day + timedelta(days=offset)


def _cp_name_for(log_type: str) -> str:
    """Whose name goes on the sheet.

    `_resolved_cp_name` derives this from the authenticated filer rather than
    from the body, and for BC 3301.13.13 the filer is the registered
    construction superintendent — a different person from the CP. A demo that
    signed the superintendent's statutory record in the CP's name would be
    showing a prospect the one thing that log exists to prevent.
    """
    if log_type == _CS_OWNED_LOG_TYPE:
        return D.DEMO_FILING_RIGHTS[0]["registered_name"]
    return D.DEMO_CP_NAME


def _cp_signature(log_type: str, log_date: date, status: str):
    """The affirmed-signature shape `_finalize_cp_signature` stores.

    AN AFFIRMATION, NOT AN IMAGE. A real signed log may carry a drawn
    signature; this one never will. A fabricated ink mark is a fabricated act
    by a named person, and the demo has no such person — so the sheet carries
    the affirmation, which is a claim the demo can honestly make about itself.

    An unsigned draft has no signature at all, because stamping one would
    assert a signer: the absence-read-as-a-claim shape the real code keeps
    closing.
    """
    if status != "submitted":
        return None
    signed_at = datetime.combine(log_date, time(16, 0), tzinfo=timezone.utc)
    return {
        "affirmed": True,
        "affirmedAt": signed_at.isoformat(),
        "affirmed_received_at": signed_at.isoformat(),
        "name": _cp_name_for(log_type),
    }


def _logbook_document(log_type: str, offset, status: str, day: date) -> dict:
    log_date = _logbook_date(offset, day)
    created = datetime.combine(log_date, time(11, 0), tzinfo=timezone.utc)
    updated = datetime.combine(log_date, time(20, 0), tzinfo=timezone.utc)
    timing_class = _TIMING_CLASS.get(log_type, "end_of_day")
    doc = {
        # An id a reader can place at a glance: type and day, never an
        # ObjectId-shaped string that could be mistaken for a real row.
        "id": f"demo-log-{log_type}-{log_date.isoformat()}",
        "project_id": D.DEMO_PROJECT_ID,
        "project_name": D.DEMO_PROJECT["name"],
        "company_id": D.DEMO_COMPANY_ID,
        "log_type": log_type,
        "date": log_date.isoformat(),
        "data": _resolve(D.DEMO_LOGBOOK_DATA[log_type], day),
        "cp_signature": _cp_signature(log_type, log_date, status),
        "cp_name": _cp_name_for(log_type),
        "status": status,
        # THE FREEZE MODEL, derived exactly as create_logbook derives it:
        # submitted AND immediate. An end-of-day narrative is NOT locked by
        # being submitted — it is frozen by the finalize — and a demo that
        # locked one would show a CP a document he could not have added his
        # afternoon photo to.
        "is_locked": status == "submitted" and timing_class == "immediate",
        "timing_class": timing_class,
        # One filing of each type per day in this set, so every sequence is 1.
        "instance_seq": 1,
        "created_by": D.DEMO_USER_ID,
        "created_by_name": D.DEMO_CP_NAME,
        "created_at": created,
        "updated_at": updated,
        "is_deleted": False,
    }
    if doc["cp_signature"] is not None:
        # Stamped from the authenticated session and never from the body — the
        # account whose request carried the signature.
        doc["signed_by"] = D.DEMO_USER_ID
    return doc


def demo_logbooks(today=None, log_type: Optional[str] = None,
                  date: Optional[str] = None, limit: int = 50,
                  skip: int = 0) -> dict:
    """GET /logbooks/project/{project_id} — the pagination envelope, sorted by
    `date` descending, which is what `paginated_query(sort_field="date")` does.

    The real endpoint's `log_type` and `date` filters are honoured because
    twelve client pickers choose the document to open out of what this returns;
    a demo that ignored the filters would hand a picker the whole set and it
    would open the wrong day.
    """
    day = _as_date(today)
    rows = [_logbook_document(t, off, status, day)
            for (t, off, status) in D.DEMO_LOGBOOK_PLAN]
    if log_type:
        rows = [r for r in rows if r["log_type"] == log_type]
    if date:
        rows = [r for r in rows if r["date"] == date]
    # Descending by date, and by log type within a day so the order is total
    # and the same two calls never disagree.
    rows.sort(key=lambda r: (r["date"], r["log_type"]), reverse=True)
    return _page(rows, limit, skip)


def demo_logbook_by_id(logbook_id: str, today=None) -> Optional[dict]:
    """GET /logbooks/{logbook_id}. None for an id this set does not hold — the
    real route 404s, and inventing a document for an unknown id is how a demo
    starts answering questions about rows that do not exist."""
    for row in demo_logbooks(today, limit=len(D.DEMO_LOGBOOK_PLAN))["items"]:
        if row["id"] == logbook_id:
            return row
    return None


# ── THE CREW ────────────────────────────────────────────────────────────────

def _worker_document(worker: dict, day: date) -> dict:
    doc = _resolve(worker, day)
    doc["is_deleted"] = False
    doc["updated_at"] = doc.get("created_at")
    return doc


def demo_workers(today=None, limit: int = 50, skip: int = 0) -> dict:
    """GET /workers — the pagination envelope, sorted by `name` ASCENDING (the
    real call passes sort_dir=1), carrying only the projected list fields."""
    day = _as_date(today)
    rows = []
    for worker in D.DEMO_WORKERS:
        full = _worker_document(worker, day)
        rows.append({k: full[k] for k in _WORKER_LIST_FIELDS if k in full})
    rows.sort(key=lambda r: r["name"])
    return _page(rows, limit, skip)


def demo_worker(worker_id: str, today=None) -> Optional[dict]:
    """GET /workers/{worker_id} — the full `WorkerResponse` document, or None
    for an id this set does not hold."""
    day = _as_date(today)
    for worker in D.DEMO_WORKERS:
        if worker["id"] == worker_id:
            return _worker_document(worker, day)
    return None


def demo_worker_certifications(worker_id: str, today=None) -> Optional[dict]:
    """GET /workers/{worker_id}/certifications.

    `validation` is `validate_worker_certifications`' shape, stated in
    dataset.py — see the note there on why it is not computed. No row carries
    `needs_review` or `review_reason`: the real endpoint OVERLAYS those at read
    time when it finds a problem, and this roster is built to have none.
    """
    worker = demo_worker(worker_id, today)
    if worker is None:
        return None
    return {
        "worker_id": worker["id"],
        "worker_name": worker["name"],
        "certifications": worker["certifications"],
        "validation": copy.deepcopy(D.DEMO_CERT_VALIDATION),
    }


# ── THE DAY AT THE GATE ─────────────────────────────────────────────────────

def _eastern_instant(day: date, hour: int, minute: int) -> datetime:
    """A wall-clock time on the New York calendar day, as the UTC instant a row
    stores. The offset is resolved per DAY rather than assumed, so a demo read
    either side of a DST change still shows a 6:42 start."""
    return datetime.combine(day, time(hour, minute), tzinfo=_EASTERN).astimezone(
        timezone.utc)


def _checkin_row(row: dict, day: date) -> dict:
    worker = next(w for w in D.DEMO_WORKERS if w["id"] == row["worker_id"])
    check_in = _eastern_instant(day, *row["_in"])
    check_out = _eastern_instant(day, *row["_out"]) if row["_out"] else None
    return {
        "id": row["id"],
        "worker_id": worker["id"],
        "worker_name": worker["name"],
        "worker_company": worker["company"],
        # THE TRADE IS THE PROJECT'S, NOT THE WORKER DOCUMENT'S. One man holds
        # different trades on different jobs; `workers.trade` is a single slot
        # filled by whichever project reached him first. This set has one
        # project, so the two agree — the comment is here because the next
        # person to add a second demo project needs to know they will not.
        "worker_trade": worker["trade"],
        "project_id": D.DEMO_PROJECT_ID,
        "project_name": D.DEMO_PROJECT["name"],
        "check_in_time": check_in,
        "check_out_time": check_out,
        "status": "checked_out" if check_out else "checked_in",
        "timestamp": check_in,
        "company_id": D.DEMO_COMPANY_ID,
        "is_deleted": False,
    }


def _checkin_rows(day: date) -> list:
    rows = [_checkin_row(r, day) for r in D.DEMO_CHECKINS]
    rows.sort(key=lambda r: r["check_in_time"], reverse=True)
    return rows


def demo_checkins(today=None, date: Optional[str] = None, limit: int = 50,
                  skip: int = 0) -> dict:
    """GET /checkins — the pagination envelope, newest first.

    The real endpoint's `date` filter is an Eastern calendar day. Every row in
    this set is on `today`, so any other date returns an empty page, which is
    the true answer rather than an invented one.
    """
    day = _as_date(today)
    rows = _checkin_rows(day)
    if date and date != day.isoformat():
        rows = []
    return _page(rows, limit, skip)


def demo_project_checkins(today=None, limit: int = 200, skip: int = 0) -> list:
    """GET /checkins/project/{project_id} — a BARE LIST, not an envelope, with
    `worker_trade` resolved. The two check-in endpoints do not have the same
    shape and a client written against one crashes on the other."""
    rows = _checkin_rows(_as_date(today))
    return rows[skip:skip + limit]


# ── THE DOB RECORD ──────────────────────────────────────────────────────────

def _dob_row(record: dict, day: date) -> dict:
    row = _resolve(record, day)
    row["project_id"] = D.DEMO_PROJECT_ID
    row["company_id"] = D.DEMO_COMPANY_ID
    row["nyc_bin"] = D.DEMO_PROJECT["nyc_bin"]
    row["is_seed_transition"] = False
    row["read_by_user"] = []
    row["status_changed_at"] = row.get("detected_at")
    # THE SAME RENDERER THE REAL HANDLER RUNS. Copy edits to the activity feed
    # land in one place, and the demo inherits them instead of drifting into a
    # second set of wording nobody maintains.
    rendered = render_signal(row.get("signal_kind") or "", row)
    row["title"] = rendered.get("title") or row.get("ai_summary") or ""
    row["body"] = rendered.get("body") or ""
    row["severity_kind"] = rendered.get("severity") or "info"
    row["action_text"] = rendered.get("action_text") or row.get("next_action") or ""
    # NO dob_link. The real handler rebuilds one from the raw record so a row
    # opens on the DOB's own site; a demo record has no raw record and no BIS
    # entry, and a link that 404s on nyc.gov is worse than no link at all.
    row["dob_link"] = None
    # Computed per caller on the real route. A demo principal has read nothing.
    row["is_read"] = False
    return row


def demo_dob_logs(today=None, record_type: Optional[str] = None,
                  severity: Optional[str] = None, limit: int = 20,
                  skip: int = 0) -> dict:
    """GET /projects/{project_id}/dob-logs — the handler's own object, not a
    pagination envelope: {project_id, project_name, nyc_bin, track_dob_status,
    total, logs}. `total` is the size of the matched set, and `logs` is the
    page."""
    day = _as_date(today)
    rows = [_dob_row(r, day) for r in D.DEMO_DOB_RECORDS]
    if record_type:
        rows = [r for r in rows if r["record_type"] == record_type]
    if severity:
        rows = [r for r in rows if r.get("severity") == severity]
    # status_changed_at desc, then detected_at desc — a true status change ahead
    # of a mere re-detection. Both are the same instant in this set, so the id
    # breaks the tie and keeps the order total.
    rows.sort(key=lambda r: (r["status_changed_at"], r["detected_at"], r["id"]),
              reverse=True)
    return {
        "project_id": D.DEMO_PROJECT_ID,
        "project_name": D.DEMO_PROJECT["name"],
        "nyc_bin": D.DEMO_PROJECT["nyc_bin"],
        "track_dob_status": True,
        "total": len(rows),
        "logs": rows[skip:skip + limit],
    }


def demo_dob_summary(today=None) -> dict:
    """GET /projects/dob-summary — {by_project, totals}.

    COMPUTED FROM THE SAME ROWS the detail list serves, by the same rules the
    real aggregation applies: a violation is open unless its resolution_state
    is one of the four closed states; a complaint is open only with no
    closed_date AND no /closed/i status; a permit is active while its expiry is
    in the future and it is not REVOKED, and expiring when that expiry is
    inside thirty days.

    It is computed rather than stated because this endpoint and the detail list
    are the two screens a prospect moves between, and a tile that disagrees
    with the list behind it is the single most visible way a demo can be caught
    lying. Nothing here may be typed by hand.
    """
    day = _as_date(today)
    rows = [_dob_row(r, day) for r in D.DEMO_DOB_RECORDS]

    def _expiry(row) -> Optional[date]:
        raw = row.get("expiration_date")
        return date.fromisoformat(raw) if raw else None

    violations = [r for r in rows if r["record_type"] in ("violation", "swo")]
    complaints = [r for r in rows if r["record_type"] == "complaint"]
    permits = [r for r in rows if r["record_type"] == "permit"]

    open_violations = len([
        r for r in violations
        if (r.get("resolution_state") or "open") not in _CLOSED_VIOLATION_STATES
    ])
    open_complaints = len([
        r for r in complaints
        if not r.get("closed_date")
        and "closed" not in str(r.get("complaint_status") or "").lower()
    ])
    dated_permits = [(r, _expiry(r)) for r in permits]
    permits_no_expiry = len([r for r, exp in dated_permits if exp is None])
    active_permits = len([
        r for r, exp in dated_permits
        if exp is not None and exp >= day and r.get("permit_status") != "REVOKED"
    ])
    permits_expiring = len([
        r for r, exp in dated_permits
        if exp is not None and day <= exp <= day + timedelta(days=30)
    ])

    counts = {
        "open_violations": open_violations,
        "open_complaints": open_complaints,
        "permits_expiring": permits_expiring,
        "total_violations": len(violations),
        "total_complaints": len(complaints),
        "total_permits": active_permits,
        "permits_no_expiry": permits_no_expiry,
    }
    return {
        "by_project": {D.DEMO_PROJECT_ID: dict(counts, has_risk_score=False)},
        # One project, and it has no risk score: there is no engine behind a
        # demo, and "Scoring" is the state the real UI shows for exactly that.
        "totals": dict(counts, projects_without_score=1, projects_total=1),
    }


# ── PLANS AND FILES ─────────────────────────────────────────────────────────

def demo_files(today=None) -> list:
    """GET /projects/{project_id}/dropbox-files — a BARE LIST of the row shape
    the R2-cached branch builds.

    `r2_url` is the backend proxy path a real row carries, and NOTHING SERVES
    IT: there is no object behind any of these. See the note in dataset.py —
    what that endpoint answers for a demo principal is a decision for whoever
    wires the routes, and the two honest answers are a 404 and a placeholder.
    """
    day = _as_date(today)
    rows = []
    for record in D.DEMO_FILES:
        row = _resolve(record, day)
        rows.append({
            "name": row["name"],
            "path": row["path"],
            "id": row["id"],
            "type": "file",
            "size": row["size"],
            "modified": row["modified"],
            "r2_url": f"/api/projects/{D.DEMO_PROJECT_ID}/files/{row['id']}/content",
            "cache_version": row["cache_version"],
            "source": row["source"],
            "index_status": row["index_status"],
        })
    return rows
