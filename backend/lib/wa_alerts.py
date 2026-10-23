"""GC group alerts, every kind, every source — the pure parts.

What a project's GC WhatsApp group is told, each item once ever (the ledger),
never a backlog (each kind is baselined on first sight), inside the project's
send window, with the group's bot on and that kind switched on.

  DOB  new violation · new DOB complaint · stop-work order issued /
       rescinded · violation status change DOB marks Action · permit status
       change (issued / expired / revoked) · permit expiring (30/14/7/1)
  DOT  new DOT violation / summons · DOT permit expiring (30/14/7/1) or
       expired · holiday embargo: an active permit exposed to Nov 15 - Jan 2
       with no waiver (lib/dot_embargo.py; Nov 1, Nov 12, first sight)

ONE FORMAT, every alert:

    🔴 588 Thomas S Boyland St
    <what happened, plain English>
    Violation #35123456 · Oct 7, 2026 · ACTIVE
    Source: DOB · https://…

The number, date, status and link are copied from the record. The "what
happened" line is either a fixed template built from record values, or an AI
sentence that passed wa_gc.check_summary against the record's facts (no
number, date, code or amount the record does not carry); otherwise the
template. Nothing here invents a fine, a deadline or a cure date.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from lib import dot_embargo, dot_sync, wa_gc

# ── The kinds and their switches ────────────────────────────────────────────

# kind -> the per-project switch (whatsapp_project.<switch>) that gates it.
KIND_SWITCH = {
    "violation": "violation_alerts",
    "permit": "permit_reminders",
    "complaint": "complaint_alerts",
    "swo": "swo_alerts",
    "swo_rescinded": "swo_alerts",
    "violation_status": "violation_status_alerts",
    "permit_status": "permit_status_alerts",
    "dot_violation": "dot_violation_alerts",
    "dot_permit": "dot_permit_alerts",
    # The holiday embargo is about a DOT permit: the DOT permit switch.
    "dot_embargo": "dot_permit_alerts",
    # An update that issued a Stop Work Order or vacate order, and the one
    # summary for a newly added BIN (lib/dob_alert_gate, ruling 2026-10-22).
    "order": "swo_alerts",
    "order_lifted": "swo_alerts",
    "bin_added": "violation_alerts",
}
SWITCHES = tuple(dict.fromkeys(KIND_SWITCH.values()))
# "violation" and "permit" were baselined by the original GC alerts under one
# marker; every later kind gets its own, so switching it on for a project that
# already has history never posts that history.
LEGACY_KINDS = ("violation", "permit")
NEW_KINDS = tuple(k for k in KIND_SWITCH if k not in LEGACY_KINDS)
# Fed by the DOT sync, not DOB: they wait for the project's first DOT pass.
DOT_KINDS = ("dot_violation", "dot_permit", "dot_embargo")

RED, ORANGE, GREEN = "🔴", "🟠", "🟢"

_CRITICAL_TEXT = re.compile(r"\bvacate\b|\bstop[- ]work order\b", re.IGNORECASE)


def is_critical(it: Dict[str, Any]) -> bool:
    """A Stop Work Order or a Vacate order: what may still post on Shabbos
    when the company says so. A rescinded order is not."""
    if it.get("kind") in ("swo", "order"):
        return True
    if it.get("kind") not in ("violation", "complaint"):
        return False
    rec = it.get("rec") or {}
    sub = str(rec.get("violation_subtype") or "").upper()
    if sub.startswith(("SWO", "VACATE")):
        return True
    text = " ".join(str(rec.get(k) or "") for k in (
        "violation_type", "violation_category", "description", "category",
        "complaint_category", "summary", "record_type"))
    return bool(_CRITICAL_TEXT.search(text))
CLOSED_WORDS = ("certified", "dismissed", "paid", "resolved", "closed",
                "rescind", "lifted", "complied", "withdrawn")

# ── Is a status text a closed one? ──────────────────────────────────────────
#
# DEFECT MEASURED (2026 audit): is_closed() did SUBSTRING matching over
# CLOSED_WORDS, so 'UNPAID' ('paid'), 'UNRESOLVED' ('resolved'), 'NOT CERTIFIED'
# ('certified') and 'NOT COMPLIED' ('complied') all read as CLOSED. Those are
# the OPEN states of a violation, so an unpaid/unresolved violation was dropped
# from the new-violation alerts and from every "open" count built on it.
#
# RULE: tokenise the NORMALISED status (upper-case, every non-alphanumeric run is
# a separator, so 'UN-RESOLVED' -> UN RESOLVED) and look for WHOLE WORDS from the
# closed vocabulary. A closed word directly preceded by a negator (NOT / NO /
# NON / UN / NEVER / WITHOUT / NOT-YET) is NOT closed. Words that merely CONTAIN
# a closed word (UNPAID, UNRESOLVED, UNCERTIFIED, NONCOMPLIED) are different
# tokens and never match. OPEN / ACTIVE / PENDING carry no closed word and so
# are open by construction.
#
# The vocabulary adds the BARE forms BIS really writes ('V-DOB VIOLATION -
# RESOLVE' / '... DISMISS': see server._classify_resolution_state), which the
# old substring test could not match either ('resolved' is not in 'resolve').
_CLOSED_TOKENS = frozenset({
    "CERTIFIED", "DISMISSED", "DISMISS", "PAID", "RESOLVED", "RESOLVE",
    "CLOSED", "CLOSE", "RESCINDED", "RESCIND", "LIFTED", "COMPLIED",
    "WITHDRAWN",
})
_NEGATORS = frozenset({"NOT", "NO", "NON", "UN", "NEVER", "WITHOUT"})
_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")


def status_tokens(status: Any) -> List[str]:
    return [t for t in _TOKEN_SPLIT.split(str(status or "").upper()) if t]


def status_is_closed(status: Any) -> bool:
    """True when the status TEXT names a closed outcome (whole words, with
    negation handled - see the block comment above).

    "CERTIFICATE ACCEPTED" (a violation's certificate of correction was
    accepted: it is resolved) is closed; found on a real job, where the report
    called it OPEN and HIGH. ACCEPTED alone is not a closed word (a filing can
    be accepted and still be live), so it counts only right after CERT*, and a
    negator before either word keeps it open ("NOT ACCEPTED", "CERTIFICATE
    NOT ACCEPTED")."""
    toks = status_tokens(status)
    for i, t in enumerate(toks):
        before = toks[i - 1] if i > 0 else ""
        if t in _CLOSED_TOKENS and before not in _NEGATORS:
            return True
        if t == "ACCEPTED" and before not in _NEGATORS and before.startswith("CERT"):
            if i < 2 or toks[i - 2] not in _NEGATORS:
                return True
    return False


def kind_baseline_id(project_id: str, kind: str) -> str:
    return f"gc:{project_id}:baseline:{kind}"


# ── Reading records ─────────────────────────────────────────────────────────

def _t(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _stamp(r: Dict[str, Any]) -> datetime:
    v = r.get("status_changed_at") or r.get("detected_at")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def latest_per_record(rows: Iterable[Dict[str, Any]], key: str = "raw_dob_id"
                      ) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = _t(r.get(key))
        if rid and (rid not in best or _stamp(r) > _stamp(best[rid])):
            best[rid] = r
    return [best[k] for k in sorted(best)]


def is_closed(r: Dict[str, Any]) -> bool:
    for k in ("resolution_state", "complaint_status", "status", "current_status",
              "hearing_status"):
        if status_is_closed(r.get(k)):
            return True
    return bool(_t(r.get("closed_date")))


# ── Open violations: one rule for the app, the DM facts and the brief ───────
#
# A DOB violation or stop-work order is OPEN when its record's NEWEST row
# (latest_per_record) has a resolution_state outside RESOLVED_STATES; a
# missing resolution_state counts as open (conservative). resolution_state
# is classified at ingestion from DOB's own status words
# (server._classify_resolution_state / _swo_resolution_state). The app's
# open-violation tile (/api/dob-logs/summary) applies the same rule in its
# aggregation, over the same record types.
#
# A DOT summons (dot_logs) is open when is_closed() says not: its stored
# status is dot_sync.closed_reason() (PAID IN FULL / DISMISSED / COMPLIED)
# once the summons is settled, else the hearing's status -- the rule
# Upcoming's OATH hearings use.

RESOLVED_STATES = ("certified", "dismissed", "paid", "resolved")
OPEN_VIOLATION_TYPES = ("violation", "swo")


def open_dob_violations(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The open DOB violations and stop-work orders among dob_logs rows:
    the newest row of each, by raw_dob_id."""
    return [r for r in latest_per_record(
                r for r in rows if _t(r.get("record_type")).lower() in OPEN_VIOLATION_TYPES)
            if _t(r.get("resolution_state")).lower() not in RESOLVED_STATES]


def open_dot_summonses(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The open DOT summonses among dot_logs rows (one row per record)."""
    return [r for r in rows
            if _t(r.get("record_type")).lower() == "dot_violation"
            and _t(r.get("number")) and not is_closed(r)]


def record_number(r: Dict[str, Any]) -> str:
    """The record's own number. The keys are the field names the dob_logs
    extractors (server._extract_*_fields) STORE - not the dataset's names.
    DEFECT MEASURED: job_status / cofo / boiler / elevator / facade_fisp fell
    through to ("number",), which none of them has, so they returned '' and
    postable() dropped them."""
    rt = _t(r.get("record_type")).lower()
    order = {
        "violation": ("violation_number",),
        "complaint": ("complaint_number",),
        "swo": ("stop_work_order_number", "violation_number"),
        "permit": ("job_number", "permit_number"),
        "job_status": ("job_filing_number", "job_number"),
        "cofo": ("co_number",),
        "boiler": ("tracking_number", "boiler_id", "device_number"),
        "elevator": ("device_number", "tracking_number"),
        "facade_fisp": ("filing_number", "tracking_number"),
        "dot_violation": ("number",),
        "dot_permit": ("number",),
    }.get(rt, ("number",))
    for k in order:
        v = _t(r.get(k))
        if v:
            return v
    return ""


def record_issue_date(r: Dict[str, Any]) -> Optional[date]:
    rt = _t(r.get("record_type")).lower()
    order = {
        "violation": ("violation_date",),
        "complaint": ("complaint_date",),
        "swo": ("violation_date",),
        "permit": ("issuance_date", "filing_date"),
        "job_status": ("filing_date",),
        "cofo": ("issuance_date",),
        "boiler": ("filing_date", "inspection_date"),
        "elevator": ("filing_date", "inspection_date"),
        "facade_fisp": ("filing_date",),
        "dot_violation": ("issue_date",),
        "dot_permit": ("issue_date",),
    }.get(rt, ("issue_date",))
    for k in order:
        d = wa_gc.parse_dob_date(r.get(k))
        if d:
            return d
    return None


def record_status(r: Dict[str, Any]) -> str:
    for k in ("current_status", "status", "complaint_status", "permit_status",
              "filing_status", "resolution_state"):
        v = _t(r.get(k))
        if v:
            return v
    return ""


# ── What a record's status WAS on a date ────────────────────────────────────
#
# For reports that must say what the regulatory status was on the day they
# describe, not what it is now. Reads the `status_history` contract of
# lib/status_history.py; pure, no database.

def _utc(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _status_events(rows: List[Dict[str, Any]]) -> List[Any]:
    """[(at, order, status)] for every dated status fact the rows carry.

    A row WITH status_history contributes each of its entries. A row WITHOUT
    one (legacy, or a permit/311 diff row written before the field existed)
    contributes ONE fact: its stored status, dated by detected_at (falling
    back to status_changed_at). A diff row's status_changed_at equals its
    detected_at, so for a permit timeline this is "the latest row whose
    status_changed_at/detected_at <= when". Rows with no usable date add
    nothing: a status we cannot date is never claimed for a date."""
    events: List[Any] = []
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        hist = r.get("status_history")
        if isinstance(hist, list) and hist:
            for e in hist:
                at = _utc(e.get("at")) if isinstance(e, dict) else None
                if at is not None:
                    events.append((at, n, e.get("status")))
                    n += 1
            continue
        at = _utc(r.get("detected_at")) or _utc(r.get("status_changed_at"))
        if at is None:
            continue
        stored = r["current_status"] if "current_status" in r else (
            r.get("status") if "status" in r else r.get("permit_status"))
        events.append((at, n, stored))
        n += 1
    return events


def status_as_of(row_or_rows: Any, when_utc: datetime) -> Optional[str]:
    """The status string a record had at `when_utc`, or None.

    `row_or_rows`: one dob_logs/dot_logs row, or the list of rows that share
    one raw_dob_id (a permit's diff-row timeline). Result is the status of the
    LATEST dated fact at or before `when_utc` (an entry stamped exactly at
    `when_utc` counts; ties go to the later-written fact). Facts are:

      * every `status_history` entry of a row that has one;
      * for a row without history, its stored current_status (status for
        dot_logs) dated by detected_at - so a legacy row is believed ONLY
        from the moment it was first seen: before that, None. Its later
        (unrecorded) changes are unknowable and are not guessed.

    None means "unknown at that time": the record was not yet seen, or the
    status then was empty. Naive datetimes (pymongo's default) are UTC.
    Statuses are returned as stored (history entries are normalised upper
    case already).
    """
    when = _utc(when_utc)
    if when is None:
        raise ValueError("when_utc must be a datetime")
    rows = row_or_rows if isinstance(row_or_rows, (list, tuple)) else [row_or_rows]
    best = None
    for at, order, status in _status_events(list(rows)):
        if at <= when and (best is None or (at, order) >= (best[0], best[1])):
            best = (at, order, status)
    if best is None:
        return None
    return None if best[2] is None else str(best[2])


def closed_as_of(row_or_rows: Any, when_utc: datetime) -> Optional[bool]:
    """Whether the record was CLOSED at `when_utc` by its status text
    (status_is_closed). None when the status then is unknown (see
    status_as_of) - the report layer must say "unknown", not "open"."""
    st = status_as_of(row_or_rows, when_utc)
    return None if st is None else status_is_closed(st)


# ── What a project has to say now ───────────────────────────────────────────

def collect(dob_rows: List[Dict[str, Any]], dot_rows: List[Dict[str, Any]],
            today: date) -> List[Dict[str, Any]]:
    """Every alertable item a project has today: [{kind, item, rec, exp?,
    prev?}]. `item` is the ledger key part — once ever per item."""
    out: List[Dict[str, Any]] = []
    latest = latest_per_record(dob_rows)

    for r in latest:
        rt = _t(r.get("record_type")).lower()
        rid = _t(r.get("raw_dob_id"))
        if rt == "violation" and not is_closed(r):
            out.append({"kind": "violation", "item": rid, "rec": r})
        elif rt == "complaint" and _t(r.get("source")).lower() != "311" \
                and _t(r.get("complaint_source")).lower() != "311" and not is_closed(r):
            out.append({"kind": "complaint", "item": rid, "rec": r})
        elif rt == "swo":
            status = _t(r.get("current_status") or r.get("status")).upper()
            if "RESCIND" in status or "LIFTED" in status:
                if r.get("previous_status") is not None and not r.get("is_seed_transition"):
                    out.append({"kind": "swo_rescinded", "item": f"{rid}:rescinded", "rec": r})
            elif not is_closed(r):
                out.append({"kind": "swo", "item": rid, "rec": r})
        elif rt == "permit":
            if _t(r.get("permit_status")).upper() == "REVOKED":
                continue
            exp = wa_gc.parse_dob_date(r.get("expiration_date"))
            t = wa_gc.permit_threshold_due(exp, today)
            if t is not None:
                out.append({"kind": "permit", "item": f"{rid}:{t}", "rec": r, "exp": exp})

    # Status changes: every change row, not only the latest.
    for r in dob_rows:
        rt = _t(r.get("record_type")).lower()
        prev, cur = _t(r.get("previous_status")), _t(r.get("current_status"))
        if not prev or not cur or prev == cur or r.get("is_seed_transition"):
            continue
        rid, row_id = _t(r.get("raw_dob_id")), _t(r.get("_id"))
        if not rid or not row_id:
            continue
        if rt == "violation" and _t(r.get("severity")) == "Action":
            # A violation is refreshed IN PLACE (one row, status_history grows),
            # so `rid:row_id` names the row, not the transition: a second real
            # change on the same row would be swallowed by the once-ever ledger.
            # From the third history entry on, the entry count is part of the
            # key; the first change keeps the original key shape so nothing
            # already posted is posted again.
            n = len(r.get("status_history") or [])
            item = f"{rid}:{row_id}" if n <= 2 else f"{rid}:{row_id}:{n}"
            out.append({"kind": "violation_status", "item": item,
                        "rec": r, "prev": prev})
        elif rt == "permit" and any(w in cur.upper() for w in ("ISSUED", "EXPIRED", "REVOKED")):
            out.append({"kind": "permit_status", "item": f"{rid}:{row_id}",
                        "rec": r, "prev": prev})

    for r in latest_per_record(dot_rows, key="raw_id"):
        rt = _t(r.get("record_type")).lower()
        rid = _t(r.get("raw_id"))
        if rt == "dot_violation" and not is_closed(r):
            out.append({"kind": "dot_violation", "item": rid, "rec": r})
        elif rt == "dot_permit":
            # Only an active permit ("ISSUED & PRINTED"). A row DOT already
            # shows as EXPIRED / VOIDED / DELINQUENT gets nothing; "expired"
            # below is an active permit whose end date has passed.
            if not dot_sync.permit_is_active(r.get("status")):
                continue
            exp = wa_gc.parse_dob_date(r.get("expiration_date"))
            if exp is None:
                continue
            days = (exp - today).days
            t = wa_gc.permit_threshold_due(exp, today)
            if t is not None:
                out.append({"kind": "dot_permit", "item": f"{rid}:{t}", "rec": r, "exp": exp})
            elif -30 <= days < 0:
                out.append({"kind": "dot_permit", "item": f"{rid}:expired", "rec": r, "exp": exp})

    # Holiday embargo: the same due dates as the email (dot_embargo.due_sends).
    # The item names the permit, season and send date: once ever each.
    permits = [r for r in latest_per_record(dot_rows, key="raw_id")
               if _t(r.get("record_type")).lower() == "dot_permit"]
    for d in dot_embargo.due_sends(permits, today):
        rid = _t(d["row"].get("raw_id")) or f"dotpermit:{d['permit']}"
        out.append({"kind": "dot_embargo", "rec": d["row"], "season": d["season"],
                    "item": f"{rid}:embargo:{d['season'].year}:{d['send_date'].isoformat()}"})
    return out


def baseline_items(items: List[Dict[str, Any]], kind: str, today: date) -> List[str]:
    """What to record as seen when `kind` is first switched on for a project:
    everything of that kind that exists now — and, for permits, every
    threshold already passed — so nothing old is ever posted."""
    keys = []
    for it in items:
        if it["kind"] != kind:
            continue
        if kind == "dot_embargo":
            # Dated reminders, each due on its own day: there is no backlog to
            # hide, so a project baselined on Nov 1 still gets Nov 1's post.
            continue
        if kind in ("permit", "dot_permit") and it.get("exp") is not None:
            base = it["item"].rsplit(":", 1)[0]
            keys += [f"{base}:{t}" for t in wa_gc.thresholds_passed(it["exp"], today)]
            if it["item"].endswith(":expired"):
                keys.append(it["item"])
        else:
            keys.append(it["item"])
    return list(dict.fromkeys(keys))


# ── The message ─────────────────────────────────────────────────────────────

LABEL = {
    "violation": "Violation", "violation_status": "Violation",
    "complaint": "Complaint", "swo": "Stop-work order",
    "swo_rescinded": "Stop-work order", "permit": "Permit",
    "permit_status": "Permit", "dot_violation": "DOT summons",
    "dot_permit": "DOT permit", "dot_embargo": "DOT permit", "bin_added": "BIN",
}
ICON = {
    "violation": RED, "complaint": RED, "swo": RED, "dot_violation": RED,
    "swo_rescinded": ORANGE, "violation_status": ORANGE, "permit_status": ORANGE,
    "permit": ORANGE, "dot_permit": ORANGE, "dot_embargo": ORANGE,
    "order": RED, "bin_added": ORANGE,
    "order_lifted": GREEN,
}
# Kinds whose "what happened" line may be an AI sentence (checked). The others
# are status or date changes, said exactly by a template.
AI_KINDS = ("violation", "complaint", "swo", "dot_violation")

FACT_FIELDS = (
    "violation_number", "violation_type", "violation_category", "violation_date",
    "description", "penalty_amount", "status", "respondent", "notice_type",
    "complaint_number", "complaint_date", "complaint_status", "category_label",
    "stop_work_order_number", "number", "issue_date", "charge", "agency",
)


def facts(rec: Dict[str, Any]) -> Dict[str, str]:
    return {k: _t(rec.get(k)) for k in FACT_FIELDS if _t(rec.get(k))}


def nice_date(d: Optional[date]) -> str:
    return f"{d:%b} {d.day}, {d.year}" if d else ""


def template_line(kind: str, rec: Dict[str, Any], *, today: date,
                  exp: Optional[date] = None, prev: str = "") -> str:
    """The fixed 'what happened' line: record values only."""
    desc = _t(rec.get("description")) or _t(rec.get("category_label")) \
        or _t(rec.get("charge"))
    if kind == "violation":
        return f"New DOB violation: {desc}." if desc else "New DOB violation issued."
    if kind == "complaint":
        return f"New DOB complaint: {desc}." if desc else "New DOB complaint filed."
    if kind == "swo":
        return f"DOB issued a stop-work order: {desc}." if desc else "DOB issued a stop-work order."
    if kind == "swo_rescinded":
        return "DOB rescinded the stop-work order."
    if kind == "violation_status":
        return f"Violation status changed: {prev} → {record_status(rec)}."
    if kind == "permit_status":
        work = _t(rec.get("work_type"))
        return (f"{work + ' p' if work else 'P'}ermit status changed: "
                f"{prev} → {record_status(rec)}.")
    if kind in ("permit", "dot_permit"):
        what = (_t(rec.get("work_type")) + " permit").strip() if kind == "permit" \
            else "DOT permit"
        what = what[0].upper() + what[1:]
        days = (exp - today).days if exp else None
        if days is None:
            return f"{what} expiring."
        if days < 0:
            return f"{what} expired on {nice_date(exp)}."
        lead = ("expires today" if days == 0 else "expires tomorrow" if days == 1
                else f"expires in {days} days")
        return f"{what} {lead} ({nice_date(exp)})."
    if kind == "dot_violation":
        return f"New DOT summons: {desc}." if desc else "New DOT summons issued."
    if kind == "dot_embargo":
        start, end = dot_embargo.work_dates(rec)
        work = (f" (work {nice_date(start)} - {nice_date(end)})" if start and end else "")
        return (f"Holiday embargo: this DOT permit has no waiver{work}. "
                f"{dot_embargo.ACTION_EN}\n"
                f"Embargo navideño: este permiso del DOT no tiene exención. "
                f"{dot_embargo.ACTION_ES}")
    if kind == "order":
        which = _t((rec.get("order_issued") or {}).get("kind"))
        return "DOB issued a vacate order." if which == "vacate" else "DOB issued a stop-work order."
    return "DOB record updated."


AI_SYSTEM_PROMPT = (
    "You write ONE short plain-English sentence for a construction crew's "
    "WhatsApp group saying what happened, from a NYC agency record. Use ONLY "
    "the facts given. Do not add any number, date, dollar amount, code, law, "
    "deadline or fine. Do not include the record number or a link (they are "
    "added separately)."
)


def what_line(kind: str, rec: Dict[str, Any], ai_text: Optional[str], *,
              today: date, exp: Optional[date] = None, prev: str = "") -> str:
    """The AI sentence if it passed the record check, else the template."""
    if kind in AI_KINDS and ai_text:
        text = " ".join(ai_text.split())
        if text and wa_gc.check_summary(text, facts(rec)):
            return text
    return template_line(kind, rec, today=today, exp=exp, prev=prev)


def record_line(kind: str, rec: Dict[str, Any]) -> str:
    """'<record type> #<number> · <issue date> · <status>' — each part from
    the record, left out when the record does not carry it."""
    label_kind = _t(rec.get("record_type")).lower() if kind in ("order", "order_lifted") else kind
    parts = [f"{LABEL.get(label_kind, 'Record')} #{record_number(rec)}"]
    d = record_issue_date(rec)
    if d:
        parts.append(nice_date(d))
    st = record_status(rec)
    if st:
        parts.append(st)
    return " · ".join(parts)


def source_line(kind: str, rec: Dict[str, Any]) -> str:
    src = "DOT" if kind.startswith("dot_") else "DOB"
    link = _t(rec.get("dob_link") or rec.get("link"))
    return f"Source: {src}" + (f" · {link}" if link else "")


def alert_message(kind: str, rec: Dict[str, Any], *, address: str,
                  what: str) -> str:
    return "\n".join([f"{ICON.get(kind, ORANGE)} {address}", what,
                      record_line(kind, rec), source_line(kind, rec)])


def postable(kind: str, rec: Dict[str, Any]) -> bool:
    """An item without its record number is not posted (omit if unsure). A
    BIN summary names the BIN, not a record."""
    if kind == "bin_added":
        return bool(_t(rec.get("site_bin")))
    return bool(record_number(rec))
