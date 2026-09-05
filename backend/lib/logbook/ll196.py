"""Phase V2.0 — LL196 (NYC Local Law 196 / SST card) attestation.

NYC LL196 requires GCs to maintain proof that every worker on
their job site holds a current Site Safety Training (SST) card.
LeveLog already tracks worker certifications (server.py
`validate_worker_certifications`); this module rolls that data
up into a monthly attestation PDF that's:

  • generated on demand. THERE IS NO 3 AM TICK. This docstring and
    docs/features/v2-logbook.md both claimed one; nothing schedules
    `generate_ll196_attestation`, and its only caller in the repo is
    POST /projects/{id}/logbook/attestations/generate (server.py:7411),
    which no client calls either. Every attestation that exists was
    produced by an operator running the curl in
    docs/operations/runbook.md §14.5,
  • uploaded to R2 at a deterministic key
    (`ll196/{company_id}/{project_id}/{year}-{month:02}.pdf`),
  • recorded in logbook_entries with category=ll196_attestation.

WHO IS ON IT. Every worker with a check-in on this project inside the
attestation month, Eastern. Argued in full at `_roster_for_period`, which is
also where the query that returned zero rows on every run since this module
shipped is written up. LL196 makes the GC responsible for "every worker on
their site", and `checkins` is the only record written unconditionally for
every worker on every visit.

The PDF carries:
  • the attestation period (year + month),
  • the project + company,
  • a worker roster with each worker's SST status (current /
    expired / missing / not-required-for-trade),
  • a summary line ("All N workers in good standing" or
    "K workers with deficiencies — see roster"),
  • the operator's name + the generation timestamp.

Pure logic (compliance computation + HTML rendering) is split
from the I/O (R2 upload + Mongo write) so tests can exercise
each layer without external services.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from lib.cert_vocab import SST_CLASS_TYPES
from lib.logbook.schema import (
    CATEGORY_LL196,
    SOURCE_AUTO_DETECTED,
    STATUS_COMPLETE,
    STATUS_DEFICIENT,
    STATUS_NO_SITE_ACTIVITY,
)

logger = logging.getLogger(__name__)

# NYC. The attestation period is a calendar month on the job site, and every
# other date in this product is bounded the same way -- see
# scripts/correct_missing_daily_log_flags.py::_day_had_gate_activity:
# "Eastern, because that is the day boundary every other date in this product
# uses ... A UTC comparison would move a 20:00 check-in to the next day."
# On a month boundary that error moves a whole shift onto the wrong filing.
_SITE_TZ = "America/New_York"

# server.py:13336 WORKER_PROJECT_TRADES_COLLECTION. NOT imported: server.py
# imports this module, so the dependency runs the other way (the reasoning is
# written out in lib/cert_vocab.py). The two names are pinned equal by
# tests/test_ll196_population.py so this copy cannot drift silently.
_WORKER_PROJECT_TRADES = "worker_project_trades"

# The sentinel a flagged check-in carries when the project had no trades
# configured. server.py refuses to store it as a pairing and renders it
# "Pending assignment"; it is not a trade and must never print as one.
_UNASSIGNED = "UNASSIGNED"


# Cert types that count as a current SST card. Mirrors
# server.py::validate_worker_certifications.
# THE COPY IS GONE. This read
#
#     _SST_CERT_TYPES = ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")
#
# three members against the canonical four, dropping SST_TEMPORARY. A worker
# holding a temporary card was admitted at the gate as a legible class and
# counted MISSING in the roster below -- a filed DOB attestation contradicting
# the gate about the same man.
_SST_CERT_TYPES = SST_CLASS_TYPES


def _worker_sst_status(
    worker: Dict[str, Any], *, now: Optional[datetime] = None,
) -> Tuple[str, Optional[str]]:
    """Classify one worker's SST standing. Returns
    (status, expiration_iso_or_none) where status is:

      "current"      — has at least one SST cert with a valid
                       (today < expiration) expiration date.
      "no_expiry"    — has an SST cert with NO expiration date
                       on file. We treat as current (operator
                       didn't enter expiration yet) but flag for
                       follow-up via a different rule.
      "expired"      — has SST cert(s) but every one's
                       expiration is in the past.
      "missing"      — no SST cert on file at all.

    Pure function — `now` injectable for tests.
    """
    cur_now = now or datetime.now(timezone.utc)
    certs = worker.get("certifications") or []
    sst_certs = [c for c in certs if (c.get("type") or "") in _SST_CERT_TYPES]
    if not sst_certs:
        return "missing", None

    best_expiry: Optional[datetime] = None
    has_no_expiry = False
    for c in sst_certs:
        exp_raw = c.get("expiration_date") or c.get("expires_at") or ""
        if not exp_raw:
            has_no_expiry = True
            continue
        try:
            # Accept either ISO date or datetime; trim to date.
            if isinstance(exp_raw, datetime):
                exp_dt = exp_raw if exp_raw.tzinfo else exp_raw.replace(tzinfo=timezone.utc)
            else:
                # str — allow with or without 'T' / 'Z'.
                s = str(exp_raw).replace("Z", "+00:00")
                exp_dt = datetime.fromisoformat(s[:19]) if len(s) >= 10 else None
                if exp_dt and exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if exp_dt and (best_expiry is None or exp_dt > best_expiry):
            best_expiry = exp_dt

    if best_expiry is not None and best_expiry > cur_now:
        return "current", best_expiry.strftime("%Y-%m-%d")
    if has_no_expiry:
        return "no_expiry", None
    return "expired", None


def _display_trade(value: Any) -> str:
    """The trade as it may be PRINTED, or "" when there isn't one.

    The same rule as server.py's `_recorded_trade` (server.py:13501), which
    says it directly: "Anything that reads a frozen trade to decide whether
    one exists has to ask through here, or the sentinel reads as a real answer
    and suppresses the lookup that would have produced one." UNASSIGNED is the
    frozen way of recording that NOTHING was recorded; printing it on a filing
    would put a trade on a man who has not been assigned one.

    This is a second copy of that rule, not an import -- server.py imports this
    module, so the dependency cannot run back the other way (lib/cert_vocab.py
    has the reasoning). tests/test_ll196_population.py pins the two against
    each other so the copy cannot drift the way `_SST_CERT_TYPES` did.
    """
    s = str(value or "").strip()
    return "" if s.upper() == _UNASSIGNED else s


def build_attestation_data(
    *, project: Dict[str, Any], workers: List[Dict[str, Any]],
    year: int, month: int,
    now: Optional[datetime] = None,
    trade_by_worker_id: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Pure: roll up worker SST status into the attestation_data
    dict that gets stored on the logbook_entries row.

    Test focus: the counts + roster shape are the contract this
    function promises. PDF rendering (below) consumes this dict
    verbatim, so testing this function locks the data contract.

    `trade_by_worker_id` carries the PER-PROJECT trade, resolved by the
    orchestrator. A worker document has no usable `trade`: the gate writers
    deliberately stopped recording one ("no `trade` / `company` here. Those are
    per-project and live in worker_project_trades; a worker-level copy is what
    bled across jobs" -- server.py:14683), so reading it off the worker either
    prints blank or prints ANOTHER JOB's answer. When the map is supplied it is
    the only source; a worker missing from it renders blank, which is correct
    -- absent beats silently wrong on a compliance register. When it is None
    the caller has no project context at all and the legacy field is used.
    """
    cur_now = now or datetime.now(timezone.utc)
    roster: List[Dict[str, Any]] = []
    counts = {"current": 0, "no_expiry": 0, "expired": 0, "missing": 0}
    for w in workers:
        status, expiry = _worker_sst_status(w, now=cur_now)
        counts[status] = counts.get(status, 0) + 1
        worker_id = str(w.get("_id") or w.get("id") or "")
        if trade_by_worker_id is None:
            trade = _display_trade(w.get("trade"))
        else:
            trade = _display_trade(trade_by_worker_id.get(worker_id))
        roster.append({
            "worker_id": worker_id,
            "name": w.get("name") or w.get("full_name") or "(unnamed)",
            "trade": trade,
            "sst_status": status,
            "sst_expiration": expiry,
        })
    # Sort: deficiencies first (sorts attention to the top),
    # then by name.
    status_priority = {"missing": 0, "expired": 1, "no_expiry": 2, "current": 3}
    roster.sort(key=lambda r: (
        status_priority.get(r["sst_status"], 9),
        r["name"].lower(),
    ))

    deficient_count = counts["missing"] + counts["expired"]
    if not workers:
        # NOBODY ON SITE IS NOT A PASS. "All 0 workers in good standing" over
        # an empty table, filed with status=complete, is an affirmative
        # statement about a roster that was never read. The schema already
        # carries the ruling for the identical shape on daily logs
        # (schema.py STATUS_NO_SITE_ACTIVITY): "the log was not filed, and
        # saying it was is the same false claim in the other direction."
        overall_status = STATUS_NO_SITE_ACTIVITY
        summary = (
            f"No worker checked in on this project during "
            f"{year}-{month:02d}. Nothing is attested for this period."
        )
    elif deficient_count == 0:
        overall_status = STATUS_COMPLETE
        summary = f"All {len(workers)} workers in good standing"
    else:
        overall_status = STATUS_DEFICIENT
        summary = (
            f"{deficient_count} of {len(workers)} workers with SST deficiencies"
        )

    return {
        "project_id": str(project.get("_id") or project.get("id") or ""),
        "project_name": project.get("name") or "",
        "company_id": str(project.get("company_id") or ""),
        "year": int(year),
        "month": int(month),
        "period_label": f"{year}-{month:02d}",
        "worker_count": len(workers),
        "counts": counts,
        "deficient_count": deficient_count,
        "overall_status": overall_status,
        "summary": summary,
        "roster": roster,
        "generated_at": cur_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render_attestation_html(attestation: Dict[str, Any]) -> str:
    """Pure: build the HTML that weasyprint will turn into a PDF.
    Inline styles only (no external CSS); deterministic output so
    tests can assert on key strings.
    """
    def _esc(s: str) -> str:
        # Minimal HTML escape: &, <, > — enough for the project
        # name + summary fields that flow into the title and body.
        # No quotes (not used in attribute context here).
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
    period = attestation.get("period_label", "")
    project_name = _esc(attestation.get("project_name"))
    summary = _esc(attestation.get("summary"))
    worker_count = attestation.get("worker_count", 0)
    counts = attestation.get("counts", {})
    rows_html = []
    status_color = {
        "current": "#16a34a",
        "no_expiry": "#ca8a04",
        "expired": "#b91c1c",
        "missing": "#b91c1c",
    }
    status_label = {
        "current": "Current",
        "no_expiry": "No expiration on file",
        "expired": "EXPIRED",
        "missing": "MISSING",
    }
    for r in attestation.get("roster", []):
        s = r.get("sst_status", "")
        expiry = r.get("sst_expiration") or "—"
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(r.get('name'))}</td>"
            f"<td>{_esc(r.get('trade'))}</td>"
            f"<td style='color:{status_color.get(s, '#000')};font-weight:600'>"
            f"{status_label.get(s, s)}</td>"
            f"<td>{_esc(expiry)}</td>"
            f"</tr>"
        )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<title>LL196 Attestation — {project_name} — {period}</title>
<style>
  body {{ font-family: 'Helvetica', sans-serif; color: #111; padding: 32px; }}
  h1 {{ font-size: 22px; margin: 0 0 8px 0; }}
  .meta {{ color: #555; font-size: 12px; margin-bottom: 24px; }}
  .summary {{ font-size: 15px; padding: 12px 16px; background: #f3f4f6;
             border-left: 4px solid #2563eb; margin-bottom: 24px; }}
  .counts {{ display: flex; gap: 24px; margin-bottom: 24px; font-size: 13px; }}
  .counts span {{ display: inline-block; padding: 4px 10px; background: #f9fafb;
                  border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f9fafb; }}
</style>
</head>
<body>
  <h1>NYC Local Law 196 — Site Safety Training Attestation</h1>
  <div class='meta'>
    Project: <strong>{project_name}</strong> &nbsp;·&nbsp;
    Period: <strong>{period}</strong> &nbsp;·&nbsp;
    Generated: {attestation.get('generated_at', '')}
  </div>
  <div class='summary'>{summary}</div>
  <div class='counts'>
    <span>Current: <strong>{counts.get('current', 0)}</strong></span>
    <span>No expiration on file: <strong>{counts.get('no_expiry', 0)}</strong></span>
    <span>Expired: <strong>{counts.get('expired', 0)}</strong></span>
    <span>Missing: <strong>{counts.get('missing', 0)}</strong></span>
    <span>Total workers: <strong>{worker_count}</strong></span>
  </div>
  <table>
    <thead><tr><th>Name</th><th>Trade</th><th>SST status</th><th>Expiration</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</body></html>"""


def r2_key_for(attestation: Dict[str, Any]) -> str:
    """Canonical R2 storage key for an attestation. Deterministic
    so re-generating overwrites in place."""
    return (
        f"ll196/{attestation['company_id']}/"
        f"{attestation['project_id']}/{attestation['period_label']}.pdf"
    )


# ──────────────────────────────────────────────────────────────────
# The population (I/O)
# ──────────────────────────────────────────────────────────────────


def _month_utc_window(year: int, month: int) -> Tuple[datetime, datetime]:
    """[start, end) in UTC for one Eastern calendar month.

    Pure and injectable-free so the boundary is testable on its own. The
    half-open end is the first instant of the next month, so a 23:59 EDT
    check-in on the last day lands INSIDE the period and a 00:00 EDT one on
    the first of the next month does not.
    """
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo(_SITE_TZ)
    start = datetime(year, month, 1, tzinfo=eastern)
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(nxt[0], nxt[1], 1, tzinfo=eastern)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def _roster_for_period(
    db, *, project_id: str, year: int, month: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """The month window of `roster_for_window`. See it for the join and why.

    Kept as its own name because the attestation asks a calendar question and
    the window arithmetic is Eastern-specific.
    """
    start_utc, end_utc = _month_utc_window(year, month)
    return await roster_for_window(
        db, project_id=project_id, start_utc=start_utc, end_utc=end_utc,
    )


async def roster_for_window(
    db, *, project_id: str,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    worker_filter: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Every worker who was on THIS site inside this window, plus each one's
    per-project trade. Returns (worker_documents, trade_by_worker_id).

    ONE ANSWER TO "WHO WAS ON THIS SITE". The LL196 attestation and the
    pre-shift roster picker both ask it, and two joins would let a statutory
    filing and the sheet a CP fills disagree about the same men -- the shape
    that put one worker on one report under two names. So the window is a
    parameter and the join is not.

    `start_utc` / `end_utc` are both optional: omit them for every check-in
    ever recorded on the project, which is what a picker wants (a man who last
    worked five weeks ago is exactly the row `+ Add Row` exists for).

    `worker_filter` is merged with `$and` rather than into the query dict, so a
    caller passing an unsatisfiable clause gets no rows instead of silently
    replacing the `_id` term. `projection` keeps `osha_card_image` -- a base64
    blob -- out of a list response.

    WHAT THIS REPLACED, and why it returned nothing:

        db.workers.find({"project_id": project_id, ...})

    `workers` documents have no top-level `project_id`. None of the three
    writers sets one -- register_and_checkin nests it inside
    `safety_orientations[]` (server.py:13892), submit_checkin writes none
    (server.py:14697), POST /workers builds from `WorkerCreate`, which has no
    such field (server.py:15561) -- and the PATCH allow-list excludes it. The
    design is stated at server.py:12293: "workers are NOT project-scoped --
    one worker spans many projects." So that filter matched zero rows on every
    run, and the attestation filed "All 0 workers in good standing".

    WHY `checkins` AND NOT THE OTHER TWO JOINS.

      * `safety_orientations[].project_id` records ONBOARDING, not presence.
        It is written on only one of the two gate paths and only when an
        orientation checklist was actually submitted, so most men never get
        one; and it has no end, so a man oriented in January still appears on
        a December filing after he left the job. Wrong in both directions at
        once. `hard_delete` also $pulls it (server.py:12293).
      * `worker_project_trades` is keyed on (worker_id, project_id) and is the
        closest thing to a roster, but `_store_worker_project_trade` REFUSES
        to write when the trade is blank or UNASSIGNED (server.py:13414), and
        the backfill enforces the same rule ("A worker whose history is
        UNASSIGNED-only gets NO pairing"). It therefore omits exactly the men
        whose paperwork is least complete -- the precise inversion of what a
        compliance register is for. It also carries no period.
      * `checkins` is written unconditionally, for every worker, on every
        visit, by BOTH live gate writers (server.py:14218, :14802), carrying
        project_id, worker_id and check_in_time. It is the only record that a
        man was on this site on this day, and it is what every other
        "who was on this project" read in server.py joins through.

    NO to_list CEILING ON THE SCAN. The old `.to_list(2000)` was a silent
    truncation waiting to happen on a filing that must be complete or say it
    is not; the cursor is iterated instead, with a projection so each row is
    three fields rather than a check-in document carrying base64 card images.
    """
    time_clause: Dict[str, Any] = {}
    if start_utc is not None:
        time_clause["$gte"] = start_utc
    if end_utc is not None:
        time_clause["$lt"] = end_utc

    worker_ids: List[str] = []
    seen: set = set()
    frozen_trade: Dict[str, str] = {}
    frozen_at: Dict[str, datetime] = {}

    _checkin_query: Dict[str, Any] = {
        "project_id": project_id,
        "is_deleted": {"$ne": True},
    }
    if time_clause:
        _checkin_query["check_in_time"] = time_clause
    cursor = db.checkins.find(
        _checkin_query,
        {"worker_id": 1, "worker_trade": 1, "check_in_time": 1, "_id": 0},
    )
    async for c in cursor:
        wid = str(c.get("worker_id") or "")
        if not wid:
            # A check-in that names no man cannot put one on the register.
            continue
        if wid not in seen:
            seen.add(wid)
            worker_ids.append(wid)
        trade = _display_trade(c.get("worker_trade"))
        if not trade:
            continue
        when = c.get("check_in_time")
        prev = frozen_at.get(wid)
        if prev is None or (when is not None and when >= prev):
            frozen_trade[wid] = trade
            if when is not None:
                frozen_at[wid] = when

    if not worker_ids:
        return [], {}

    # FROZEN FIRST, PAIRING SECOND, `workers` NEVER -- the same precedence
    # server.py applies wherever a trade is shown for a worker on a project.
    unresolved = [w for w in worker_ids if not frozen_trade.get(w)]
    if unresolved:
        try:
            pairs = await db[_WORKER_PROJECT_TRADES].find(
                {"project_id": project_id, "worker_id": {"$in": unresolved}},
                {"worker_id": 1, "trade": 1, "_id": 0},
            ).to_list(len(unresolved))
        except Exception as e:  # pragma: no cover — defensive
            # A missing trade prints blank; it must not lose the roster.
            logger.warning(f"[ll196] pairing lookup failed: {e!r}")
            pairs = []
        for p in pairs:
            t = _display_trade(p.get("trade"))
            if t:
                frozen_trade[str(p.get("worker_id") or "")] = t

    # Check-ins store `str(worker["_id"])`. Query both shapes: production ids
    # are ObjectIds, but legacy rows carry string _ids (the project lookup
    # below has the same fallback).
    query_ids: List[Any] = []
    for wid in worker_ids:
        oid = _to_object_id(wid)
        query_ids.append(oid)
        if oid != wid:
            query_ids.append(wid)

    _worker_query: Dict[str, Any] = {
        "_id": {"$in": query_ids},
        "is_deleted": {"$ne": True},
    }
    if worker_filter:
        # $and, NOT dict-merge. A caller's `{"_id": None}` tenant fallback would
        # otherwise REPLACE the `$in` term and return the wrong men rather than
        # none of them.
        _worker_query = {"$and": [_worker_query, worker_filter]}
    workers = await (
        db.workers.find(_worker_query, projection) if projection is not None
        else db.workers.find(_worker_query)
    ).to_list(len(query_ids))

    # A check-in whose worker document is gone or soft-deleted names nobody we
    # can attest about. It is not silently dropped: it is counted and logged,
    # because a register short by N men is the failure this whole change is
    # about.
    #
    # THE WINDOW IS PRINTED, NOT THE PERIOD. This used to interpolate `year`
    # and `month`, which were parameters of the month-shaped function this was
    # extracted from; the window is now the general fact and a caller with no
    # window says so. A NameError here would have raised inside the
    # attestation's own roster build.
    orphaned = len(worker_ids) - len(workers)
    if orphaned:
        _window = (
            f"{start_utc.isoformat()}..{end_utc.isoformat()}"
            if start_utc is not None and end_utc is not None else "all time"
        )
        logger.warning(
            f"[ll196] project={project_id} window={_window}: "
            f"{orphaned} of {len(worker_ids)} checked-in worker ids have no "
            f"live worker document; they are absent from the register",
        )
    return workers, frozen_trade


# ──────────────────────────────────────────────────────────────────
# Orchestrator (I/O)
# ──────────────────────────────────────────────────────────────────


async def generate_ll196_attestation(
    db,
    *,
    project_id: str,
    year: int,
    month: int,
    triggered_by_user_id: Optional[str] = None,
    r2_uploader: Optional[Callable[[bytes, str, str], str]] = None,
    pdf_renderer: Optional[Callable[[str], bytes]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Generate, upload, and record one monthly attestation.

    `r2_uploader` and `pdf_renderer` are injection points for
    tests — production passes the real `_upload_to_r2` and a
    weasyprint-backed renderer; tests pass stubs that capture the
    bytes without touching network or weasyprint's native deps.

    Returns the inserted/upserted logbook_entries row payload
    (without the _id, since upsert may not return it).
    """
    cur_now = now or datetime.now(timezone.utc)

    project = await db.projects.find_one({"_id": _to_object_id(project_id)})
    if project is None:
        # Fall back to string id (legacy projects sometimes have
        # str _ids).
        project = await db.projects.find_one({"_id": project_id})
    if project is None:
        raise ValueError(f"project not found: {project_id}")

    workers, trade_by_worker_id = await _roster_for_period(
        db, project_id=project_id, year=year, month=month,
    )

    attestation_data = build_attestation_data(
        project=project, workers=workers,
        year=year, month=month, now=cur_now,
        trade_by_worker_id=trade_by_worker_id,
    )

    # PDF render (operator can supply stub renderer; default uses
    # weasyprint).
    html = render_attestation_html(attestation_data)
    if pdf_renderer is None:
        pdf_renderer = _default_pdf_renderer
    pdf_bytes = pdf_renderer(html)

    # R2 upload.
    key = r2_key_for(attestation_data)
    r2_url = ""
    try:
        if r2_uploader is None:
            r2_uploader = _default_r2_uploader
        r2_url = r2_uploader(pdf_bytes, key, "application/pdf") or ""
    except Exception as e:
        logger.warning(
            f"[ll196] R2 upload failed for {key}: {e!r}",
        )

    attestation_data["r2_key"] = key
    attestation_data["r2_url"] = r2_url
    attestation_data["pdf_size_bytes"] = len(pdf_bytes)

    # Upsert the logbook_entries row. Dedupe on
    # (project_id, entry_date, category) — same project + same
    # period regenerates in place (R2 overwrite is also in place).
    entry_date = f"{year:04d}-{month:02d}-01"
    entry = {
        "company_id": attestation_data["company_id"],
        "project_id": attestation_data["project_id"],
        "entry_date": entry_date,
        "category": CATEGORY_LL196,
        "status": attestation_data["overall_status"],
        "source": SOURCE_AUTO_DETECTED,
        "linked_dob_log_ids": [],
        # ONLY a deficiency carries a deficiency reason. This read
        # `!= STATUS_COMPLETE`, which was the same test while `complete` and
        # `deficient` were the only two outcomes; with `no_site_activity` it
        # is not -- an empty month flags nobody and must not read as a fault.
        "deficiency_reason": (
            attestation_data["summary"]
            if attestation_data["overall_status"] == STATUS_DEFICIENT
            else None
        ),
        "attestation_data": attestation_data,
        "updated_at": cur_now,
    }
    await db.logbook_entries.update_one(
        {
            "project_id": attestation_data["project_id"],
            "entry_date": entry_date,
            "category": CATEGORY_LL196,
        },
        {
            "$set": entry,
            "$setOnInsert": {
                "created_at": cur_now,
                "created_by_user_id": triggered_by_user_id,
            },
        },
        upsert=True,
    )
    logger.info(
        f"[ll196] attestation generated project={project_id} "
        f"period={attestation_data['period_label']} "
        f"status={attestation_data['overall_status']} "
        f"r2={key}",
    )
    return entry


# ──────────────────────────────────────────────────────────────────
# Default I/O backends (production)
# ──────────────────────────────────────────────────────────────────


def _default_pdf_renderer(html: str) -> bytes:
    """Production: weasyprint. Imported lazily so tests that pass
    a stub don't need the native deps installed."""
    from weasyprint import HTML  # type: ignore
    return HTML(string=html).write_pdf()


def _default_r2_uploader(file_bytes: bytes, key: str, content_type: str) -> str:
    """Production: bridge to server.py's _upload_to_r2. Imported
    lazily so test code can inject a stub without booting the
    full server."""
    from server import _upload_to_r2  # type: ignore
    return _upload_to_r2(file_bytes, key, content_type) or ""


def _to_object_id(s: str):
    """Best-effort ObjectId parsing. Returns the original string
    on failure so callers can still query by string-id."""
    try:
        from bson import ObjectId
        return ObjectId(s)
    except Exception:
        return s
