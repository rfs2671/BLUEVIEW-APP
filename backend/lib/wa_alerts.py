"""GC group alerts, every kind, every source — the pure parts.

What a project's GC WhatsApp group is told, each item once ever (the ledger),
never a backlog (each kind is baselined on first sight), inside the project's
send window, with the group's bot on and that kind switched on.

  DOB  new violation · new DOB complaint · stop-work order issued /
       rescinded · violation status change DOB marks Action · permit status
       change (issued / expired / revoked) · permit expiring (30/14/7/1)
  DOT  new DOT violation / summons · DOT permit expiring (30/14/7/1) or
       expired

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

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from lib import wa_gc

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
}
SWITCHES = tuple(dict.fromkeys(KIND_SWITCH.values()))
# "violation" and "permit" were baselined by the original GC alerts under one
# marker; every later kind gets its own, so switching it on for a project that
# already has history never posts that history.
LEGACY_KINDS = ("violation", "permit")
NEW_KINDS = tuple(k for k in KIND_SWITCH if k not in LEGACY_KINDS)

RED, ORANGE = "🔴", "🟠"
CLOSED_WORDS = ("certified", "dismissed", "paid", "resolved", "closed",
                "rescind", "lifted", "complied", "withdrawn")


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
        v = _t(r.get(k)).lower()
        if v and any(w in v for w in CLOSED_WORDS):
            return True
    return bool(_t(r.get("closed_date")))


def record_number(r: Dict[str, Any]) -> str:
    rt = _t(r.get("record_type")).lower()
    order = {
        "violation": ("violation_number",),
        "complaint": ("complaint_number",),
        "swo": ("stop_work_order_number", "violation_number"),
        "permit": ("job_number", "permit_number"),
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
              "resolution_state"):
        v = _t(r.get(k))
        if v:
            return v
    return ""


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
            out.append({"kind": "violation_status", "item": f"{rid}:{row_id}",
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
            exp = wa_gc.parse_dob_date(r.get("expiration_date"))
            if exp is None:
                continue
            days = (exp - today).days
            t = wa_gc.permit_threshold_due(exp, today)
            if t is not None:
                out.append({"kind": "dot_permit", "item": f"{rid}:{t}", "rec": r, "exp": exp})
            elif -30 <= days < 0:
                out.append({"kind": "dot_permit", "item": f"{rid}:expired", "rec": r, "exp": exp})
    return out


def baseline_items(items: List[Dict[str, Any]], kind: str, today: date) -> List[str]:
    """What to record as seen when `kind` is first switched on for a project:
    everything of that kind that exists now — and, for permits, every
    threshold already passed — so nothing old is ever posted."""
    keys = []
    for it in items:
        if it["kind"] != kind:
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
    "dot_permit": "DOT permit",
}
ICON = {
    "violation": RED, "complaint": RED, "swo": RED, "dot_violation": RED,
    "swo_rescinded": ORANGE, "violation_status": ORANGE, "permit_status": ORANGE,
    "permit": ORANGE, "dot_permit": ORANGE,
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
    parts = [f"{LABEL.get(kind, 'Record')} #{record_number(rec)}"]
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
    """An item without its record number is not posted (omit if unsure)."""
    return bool(record_number(rec))
