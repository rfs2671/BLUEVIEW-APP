"""Decisions for a DOB complaint seen by any source: is it this project's, is it
new, does it alert, how urgently, and what has happened to it since.

Pure functions. No database, no network. server.py does the I/O.

THE FAILURE THIS ANSWERS (546 Saratoga, 2026-11-10). Two Construction Safety
Compliance complaints (3A88489 11:22, 3A88492 11:25 ET) were on DOB BIS within
hours and LeveLog said nothing:
  * the only complaint source was the Open Data daily extract (next-day);
  * an open 8A complaint with no disposition scored severity "Good", so the
    email path would not have sent it even after ingest;
  * the project had no confirmed WhatsApp group, so the group path could not;
  * the assistant's DOB answer read violations only and said "No recent
    violations on file" with no word on how fresh that was.

RULES (each has a test in tests/test_complaint_watch_546.py):
  * One complaint = one record = one alert, whichever source saw it first
    (keyed by the normalized complaint number, never by source).
  * A complaint attaches to a project only when its BIN is one of the
    project's BINs (own BIN, the lot's other BINs per BIS, the site BINs).
  * First sync of a BIN: history is a baseline and does not alert -- EXCEPT an
    open complaint DOB received in the last 48 hours, which is not history.
  * Late arrival: an open complaint first seen days after DOB received it
    still alerts, marked late. It is never silently dropped as "stale".
  * Closed on arrival: no "new complaint" alert -- unless its disposition is
    an enforcement event (violation served, stop-work, vacate), which alerts
    as that event.
  * Every non-alert carries a reason a person can read.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from lib.bis_complaints import ET, OPEN_STATUSES, normalize_complaint_number

try:  # the code tables live at the backend root
    from dob_complaint_codes import (DOB_CATEGORY_CODES, DOB_DISPOSITION_CODES,
                                     get_category_label, get_disposition_label)
except Exception:  # pragma: no cover - tests run from backend/
    DOB_CATEGORY_CODES, DOB_DISPOSITION_CODES = {}, {}
    get_category_label = get_disposition_label = lambda c: str(c or "")

FIRST_SYNC_RECENT = timedelta(hours=48)
_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
LATE_AFTER = timedelta(days=2)

# Words in DOB's own complaint text that name a physical hazard to people.
SAFETY_TERMS = (
    "UNSAFE", "PROTECTION", "FALL", "ROOF", "WINDOW", "SCAFFOLD", "SHED", "FENCE",
    "FIRE EXTINGUISHER", "EXTINGUISHER", "HOUSEKEEPING", "DEBRIS", "SHORING", "COLLAPSE",
    "GUARD", "HANDRAIL", "NETTING", "CRANE", "EXCAVATION", "STABILITY", "PEDESTRIAN",
    "OVERHEAD", "OPENING", "PARAPET", "SAFETY",
)
# Construction-safety categories: CSC actions and site-safety categories.
SAFETY_CATEGORIES = {"8A", "01", "02", "10", "14", "16", "28", "30", "40", "41", "43",
                     "62", "64", "67", "68", "69", "81", "82", "89", "8B", "8C", "8D"}

# Per DOB's own labels (dob_complaint_codes.DOB_DISPOSITION_CODES):
#   ORDER      an order DOB ISSUED: stop-work (A3 full, L1 partial, H5, K4, K6)
#              or vacate (Y1 full, Y3 partial).
#   EMERGENCY  padlock / emergency declaration: urgent, but not a stop-work order.
#   VIOLATION  a violation or summons SERVED -- including H3 / H4 / V3, served
#              FOR disobeying a stop-work order: not a new order.
#   RESCIND    an order lifted: L2 / Y2 in full, L3 / Y4 in part.
ORDER_DISPOSITIONS = {"A3", "H5", "L1", "K4", "K6", "Y1", "Y3"}
VACATE_DISPOSITIONS = {"Y1", "Y3"}
EMERGENCY_DISPOSITIONS = {"P3", "RH", "RI"}
VIOLATION_DISPOSITIONS = {"A1", "A2", "A4", "A5", "A6", "A8", "A9", "B1", "B2", "R5", "RK", "K5", "ND",
                          "H3", "H4", "V3"}
RESCIND_DISPOSITIONS = {"L2", "L3", "Y2", "Y4"}


def bins_for_project(project: Mapping[str, Any], *, lot_bins: Iterable[str] = (),
                     site_bins: Iterable[str] = ()) -> Set[str]:
    out = {re.sub(r"\D", "", str(project.get("nyc_bin") or ""))}
    out |= {re.sub(r"\D", "", str(b or "")) for b in lot_bins}
    out |= {re.sub(r"\D", "", str(b or "")) for b in site_bins}
    return {b for b in out if len(b) == 7 and not b.endswith("000000")}


def _as_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=ET)
    return None


def received_at(rec: Mapping[str, Any]) -> Optional[datetime]:
    """When DOB received it: BIS's timestamp, else the entered date at ET midnight."""
    bis = rec.get("bis") or {}
    for v in (bis.get("received_at"), rec.get("received_at")):
        d = _as_dt(v)
        if d:
            return d
    for v in (bis.get("received_date"), rec.get("date_entered"), rec.get("complaint_date")):
        if v:
            s = str(v)[:10]
            try:
                y, m, dd = (int(x) for x in s.split("-"))
                return datetime(y, m, dd, tzinfo=ET)
            except ValueError:
                continue
    return None


def is_311(rec: Mapping[str, Any]) -> bool:
    """A 311 service request stored as a complaint (lib/wa_alerts reads it the
    same way). Not a DOB complaint; never reconciled by DOB complaint number."""
    return (str(rec.get("source") or "").lower() == "311"
            or str(rec.get("complaint_source") or "").lower().startswith("311")   # "311 Complaint" too
            or str(rec.get("raw_dob_id") or "").startswith("311:"))


def is_open(rec: Mapping[str, Any]) -> bool:
    st = str(rec.get("status") or rec.get("complaint_status") or rec.get("current_status") or "").upper()
    return st in OPEN_STATUSES


def disposition_class(code: Optional[str]) -> Optional[str]:
    c = str(code or "").strip().upper()
    if not c:
        return None
    if c in ORDER_DISPOSITIONS:
        return "order"
    if c in EMERGENCY_DISPOSITIONS:
        return "emergency"
    if c in VIOLATION_DISPOSITIONS:
        return "violation"
    if c in RESCIND_DISPOSITIONS:
        return "order_lifted"
    risk = (DOB_DISPOSITION_CODES.get(c) or {}).get("risk")
    if risk == "RESOLVED":
        return "no_action"
    if risk == "PENDING":
        return "no_access"
    return "other"


def safety_assessment(rec: Mapping[str, Any]) -> Dict[str, Any]:
    """`tier`: 'order' (stop-work/vacate), 'safety', or 'standard', with the
    words that decided it. Only DOB's own fields are read."""
    cat = str(rec.get("category") or rec.get("complaint_type") or rec.get("complaint_category") or "").upper()
    text = " ".join(str(rec.get(k) or "") for k in ("description", "comments")).upper()
    disp = str(rec.get("disposition_code") or "").upper()
    reasons: List[str] = []
    if disposition_class(disp) == "order" or re.search(r"\b(P?SWO|STOP (ALL )?WORK)\b", text):
        reasons.append("stop-work or vacate order" if disposition_class(disp) == "order"
                       else "DOB's text names a stop-work order")
        return {"tier": "order", "reasons": reasons}
    if cat in SAFETY_CATEGORIES:
        reasons.append(f"category {cat}: {get_category_label(cat)}")
    hits = []
    for t in SAFETY_TERMS:
        if t in text and not any(t in h for h in hits):
            hits.append(t)
    if hits:
        reasons.append("DOB's text: " + ", ".join(t.lower() for t in hits[:5]))
    risk = (DOB_CATEGORY_CODES.get(cat) or {}).get("risk")
    if risk in ("CRITICAL", "HIGH"):
        reasons.append(f"category risk {risk}")
    tier = "safety" if (cat in SAFETY_CATEGORIES or risk in ("CRITICAL", "HIGH")
                        or (hits and cat not in {"4S", "7F"})) else "standard"
    return {"tier": tier, "reasons": reasons}


def alert_decision(rec: Mapping[str, Any], *, project_bins: Set[str], first_sync: bool,
                   already_alerted: bool, now: datetime,
                   first_seen_at: Optional[datetime] = None) -> Dict[str, Any]:
    """{'alert': bool, 'event', 'priority', 'late', 'reason'} -- never a bare False."""
    cn = normalize_complaint_number(rec.get("complaint_number") or rec.get("raw_dob_id"))
    b = re.sub(r"\D", "", str(rec.get("bin") or rec.get("nyc_bin") or ""))
    out: Dict[str, Any] = {"complaint_number": cn, "alert": False, "event": "new_complaint",
                           "priority": "normal", "late": False, "reason": ""}
    if not cn:
        out["reason"] = "no complaint number"
        return out
    if b not in project_bins:
        out["reason"] = f"wrong property: BIN {b or '?'} is not one of this project's BINs"
        return out
    if already_alerted:
        out["reason"] = "duplicate: this complaint was already alerted"
        return out
    rcv = received_at(rec)
    # A stored detected_at comes back from Mongo without a timezone; BIS's
    # received time has one. Normalize both before subtracting.
    now = _as_dt(now) or now
    seen = _as_dt(first_seen_at) or now
    sa = safety_assessment(rec)
    dclass = disposition_class(rec.get("disposition_code"))
    order_event = ("vacate_order" if str(rec.get("disposition_code") or "").strip().upper()
                   in VACATE_DISPOSITIONS else "stop_work_order")
    if not is_open(rec):
        if dclass in ("order", "violation", "emergency"):
            out.update(alert=True, event={"order": order_event, "violation": "violation_served"}.get(
                           dclass, "new_complaint"),
                       priority=("high" if dclass == "violation" else "critical"),
                       reason=f"closed on arrival but DOB disposed it {rec.get('disposition_code')}")
            if first_sync and not (rcv and now - rcv <= FIRST_SYNC_RECENT):
                out.update(alert=False, reason="baseline: history on the first sync of this BIN")
            return out
        out["reason"] = "closed on arrival with no enforcement disposition"
        return out
    if first_sync and not (rcv and now - rcv <= FIRST_SYNC_RECENT):
        out["reason"] = "baseline: open complaint older than 48h on the first sync of this BIN"
        return out
    out["alert"] = True
    if dclass == "order":
        out["event"] = order_event
    out["priority"] = {"order": "critical", "safety": "high"}.get(sa["tier"], "normal")
    if dclass == "emergency":
        out["priority"] = "critical"
    out["late"] = bool(rcv and seen - rcv > LATE_AFTER)
    out["reason"] = "; ".join(sa["reasons"]) or "open DOB complaint"
    return out


SUMMONS_RECENT = timedelta(days=7)


def summons_decision(row: Mapping[str, Any], *, bin_: str, project_bins: Set[str], first_sync: bool,
                     already_alerted: bool, now: datetime) -> Dict[str, Any]:
    """An ECB/OATH summons BIS lists for a BIN that LeveLog has not stored.
    Class 1 = immediately hazardous -> critical; Class 2 -> high; else normal."""
    num = str(row.get("ecb_number") or "")
    out: Dict[str, Any] = {"number": num, "alert": False, "event": "violation_served",
                           "priority": "normal", "late": False, "reason": ""}
    if re.sub(r"\D", "", str(bin_ or "")) not in project_bins:
        out["reason"] = f"wrong property: BIN {bin_} is not one of this project's BINs"
        return out
    if already_alerted:
        out["reason"] = "duplicate: this summons was already alerted"
        return out
    if not row.get("active"):
        out["reason"] = "resolved on arrival"
        return out
    issued = None
    if row.get("issue_date"):
        try:
            y, m, d = (int(x) for x in str(row["issue_date"])[:10].split("-"))
            issued = datetime(y, m, d, tzinfo=ET)
        except ValueError:
            issued = None          # undated: history on a first sync, never a crash
    age = (now - issued) if issued else None
    if first_sync and not (age is not None and age <= FIRST_SYNC_RECENT):
        out["reason"] = "baseline: open summons older than 48h on the first sync of this BIN"
        return out
    sev = str(row.get("severity") or "").upper()
    out["priority"] = "critical" if "1" in sev else "high" if "2" in sev else "normal"
    out["late"] = bool(age is not None and age > SUMMONS_RECENT)
    out["alert"] = True
    out["reason"] = f"{sev or 'unclassed'} summons, {row.get('unit') or 'DOB'}"
    return out


def card_summary(rec: Mapping[str, Any]) -> str:
    """The Compliance card's one-line summary (its `ai_summary` field) for a
    complaint BIS found first: DOB's own words, no model in between."""
    cn = rec.get("complaint_number") or rec.get("raw_dob_id")
    cat = str(rec.get("category") or rec.get("complaint_type") or "")
    rcv = received_at(rec)
    when = ""
    if rcv:
        t = rcv.astimezone(ET)
        when = f" on {t:%b} {t.day}" + (f", {(t.hour % 12) or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
                                         if (t.hour or t.minute) else "")
    desc = str(rec.get("description") or "").strip().rstrip(".")
    insp = rec.get("last_inspection_date") or rec.get("inspection_date")
    state = (f"Inspected {insp}." if insp else "Not inspected yet.")
    return (f"DOB complaint {cn} ({cat} {get_category_label(cat)}) received{when}: {desc}. {state}").replace("  ", " ")


def summons_card_summary(row: Mapping[str, Any]) -> str:
    due = row.get("balance_due")
    return (f"ECB/OATH summons {row.get('ecb_number')} ({str(row.get('severity') or '').title()}), "
            f"issued {row.get('issue_date') or '?'} by {row.get('unit') or 'DOB'}. "
            f"Hearing: {row.get('hearing_status') or 'pending'}."
            + (f" Penalty due: ${due:,.2f}." if isinstance(due, (int, float)) and due else ""))


def render_summons_alert(row: Mapping[str, Any], decision: Mapping[str, Any], *, project_name: str,
                         lang: str = "en") -> str:
    num = decision.get("number") or row.get("ecb_number")
    sev = str(row.get("severity") or "").title()
    due = row.get("balance_due")
    link = f"https://a810-bisweb.nyc.gov/bisweb/ECBQueryByNumberServlet?ecbin={num}"
    if lang == "es":
        lines = [f"*Citación ECB/OATH del DOB — {project_name}*",
                 f"Citación {num} ({sev}), emitida {row.get('issue_date') or ''}.",
                 f"Unidad: {row.get('unit') or ''}. Audiencia: {row.get('hearing_status') or 'pendiente'}.",
                 f"Multa pendiente: ${due:,.2f}." if isinstance(due, (int, float)) and due else "",
                 "Corrija la condición y presente el Certificado de Corrección.", link]
    else:
        lines = [f"*DOB ECB/OATH summons — {project_name}*",
                 f"Summons {num} ({sev}), issued {row.get('issue_date') or ''}.",
                 f"Unit: {row.get('unit') or ''}. Hearing: {row.get('hearing_status') or 'pending'}.",
                 f"Penalty due: ${due:,.2f}." if isinstance(due, (int, float)) and due else "",
                 "Correct the condition and file the Certificate of Correction.", link]
    return "\n".join(x for x in lines if x)


def lifecycle_events(rec: Mapping[str, Any], *, ecb: Iterable[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """complaint -> inspection -> disposition -> violation / summons / order ->
    correction -> closure, as distinct events. Only what a source states."""
    ev: List[Dict[str, Any]] = []
    rcv = received_at(rec)
    if rcv:
        ev.append({"event": "received", "at": rcv.isoformat(), "source": "DOB"})
    insp = rec.get("last_inspection_date") or rec.get("inspection_date")
    if insp:
        ev.append({"event": "inspected", "at": str(insp)[:10], "badge": rec.get("inspector_badge")})
    code = rec.get("disposition_code")
    if code:
        ev.append({"event": "disposition", "at": (str(rec.get("disposition_date") or insp or "")[:10] or None),
                   "code": code, "label": rec.get("disposition_desc") or get_disposition_label(code),
                   "class": disposition_class(code)})
        if disposition_class(code) == "order":
            ev.append({"event": "order_issued", "at": str(rec.get("disposition_date") or "")[:10] or None,
                       "kind": "partial_stop_work" if str(code).upper() in {"L1", "K6"} else "stop_work_or_vacate"})
    for n in rec.get("ecb_violation_numbers") or []:
        ev.append({"event": "violation_issued", "ecb_number": n})
    for v in ecb:
        n = v.get("ecb_violation_number")
        st = str(v.get("ecb_violation_status") or "").upper()
        cert = str(v.get("certification_status") or v.get("hearing_status") or "").upper()
        if "CURE" in cert or "CERTIFICATE ACCEPTED" in cert or st == "RESOLVE":
            ev.append({"event": "corrected", "ecb_number": n, "status": cert or st})
        hd = v.get("hearing_date")
        if hd and st == "ACTIVE":
            ev.append({"event": "hearing_scheduled", "ecb_number": n, "at": str(hd)[:10]})
    st = str(rec.get("status") or "").upper()
    if st in ("RESOLVED", "CLOSED"):
        ev.append({"event": "closed", "status": st})
    return ev


# ── Source freshness: say what was checked, never imply "none" ───────────────

SOURCE_LABELS = {
    "bis_complaints": "DOB BIS complaints (live)",
    "bis_ecb": "ECB/OATH summonses on DOB BIS (live)",
    "dob_complaints": "DOB complaints (NYC Open Data, daily)",
    "dob_violations": "DOB / ECB violations (NYC Open Data, daily)",
    "dob_permits": "DOB permits (NYC Open Data)",
    "dob_job_filings": "DOB NOW job filings (NYC Open Data)",
    "dob_cofo": "Certificates of occupancy (NYC Open Data)",
    "dob_facade": "Facade (FISP) filings (NYC Open Data)",
    "dob_boiler": "Boiler inspections (NYC Open Data)",
    "dob_elevator": "Elevator devices (NYC Open Data)",
    "dot_oath": "DOT / OATH summonses",
    "dot_permits": "DOT street permits",
}
DATASET_LABELS = {
    "855j-jady": "DOB NOW Safety violations (Open Data)",
    "3h2n-5cm9": "DOB violations (Open Data)",
    "6bgk-3dad": "ECB/OATH violations (Open Data)",
    "3usq-5cid": "Stop-work orders, EO 202.6 (Open Data, ends 2020)",
    "eabe-havv": "DOB complaints received (Open Data)",
    "rbx6-tga4": "DOB NOW Build permits (Open Data)",
    "dm9a-ab7w": "DOB NOW Electrical permits (Open Data)",
    "ipu4-2q9a": "BIS permits (Open Data)",
    "w9ak-ipjd": "DOB NOW job filings (Open Data)",
    "pkdm-hqz6": "Certificates of occupancy (Open Data)",
    "xubg-57si": "Facade FISP (Open Data)",
    "52dp-yji6": "Boiler inspections (Open Data)",
    "e5aq-a4j2": "Elevator devices (Open Data)",
}
# The 15-minute Open Data scan stamps synced_at each pass; an hour without one
# means the scan, not the city, has stopped.
SCAN_STALE = timedelta(hours=1)


def _status(ok: Optional[datetime], err: Optional[datetime], now: datetime, stale: timedelta) -> str:
    if err and (not ok or err > ok):
        return "failing"
    if not ok:
        return "never"
    return "stale" if now - ok > stale else "fresh"


def freshness(state: Optional[Mapping[str, Any]], *, now: datetime,
              stale_after: timedelta = timedelta(minutes=45)) -> Dict[str, Any]:
    """Every monitored source and every dataset under it: last success, last
    attempt, last error, and a status of fresh / stale / failing / never --
    each judged on its OWN state, so one failure is visible as itself and
    never as "no records"."""
    from lib import source_sync  # local: complaint_watch stays importable alone
    st = state or {}
    sources = st.get("sources") or {}
    watches = st.get("watch") or {}
    datasets = st.get("datasets") or {}
    rows: List[Dict[str, Any]] = []

    for key in ("bis_complaints", "bis_ecb"):
        w = watches.get(key) or {}
        ok, at = _as_dt(w.get("last_success_at")), _as_dt(w.get("last_attempt_at"))
        err_text = w.get("last_error")
        st_ = ("failing" if err_text else "never" if not ok
               else "stale" if now - ok > stale_after else "fresh")
        rows.append({"source": key, "label": SOURCE_LABELS[key], "mode": w.get("mode") or "off",
                     "last_success_at": ok.isoformat() if ok else None,
                     "last_attempt_at": at.isoformat() if at else None,
                     "last_error": err_text, "status": st_})

    by_source: Dict[str, List[str]] = {}
    for d in datasets:
        by_source.setdefault(source_sync.DATASET_SOURCE.get(d, "other"), []).append(d)
    for key in [k for k in source_sync.SOURCES if k in sources or k in by_source]:
        ok = _as_dt((sources.get(key) or {}).get("synced_at"))
        failing = sorted(d for d in by_source.get(key, [])
                         if _status(_as_dt((datasets[d] or {}).get("synced_at")),
                                    _as_dt((datasets[d] or {}).get("last_error_at")), now, SCAN_STALE) == "failing")
        st_ = _status(ok, None, now, SCAN_STALE)
        rows.append({"source": key, "label": SOURCE_LABELS.get(key, key),
                     "last_success_at": ok.isoformat() if ok else None, "last_attempt_at": None,
                     "last_error": (f"failing datasets: {', '.join(failing)}" if failing else None),
                     "status": "partial" if failing and st_ == "fresh" else ("failing" if failing else st_)})

    for d in sorted(datasets):
        row = datasets[d] or {}
        ok, err = _as_dt(row.get("synced_at")), _as_dt(row.get("last_error_at"))
        if not (ok or err):
            continue
        rows.append({"source": f"dataset:{d}", "label": DATASET_LABELS.get(d, d),
                     "last_success_at": ok.isoformat() if ok else None,
                     "last_attempt_at": max(x for x in (ok, err) if x).isoformat(),
                     "last_error": (f"failed {err.isoformat()}" if err and (not ok or err > ok) else None),
                     "status": _status(ok, err, now, SCAN_STALE)})

    by_key = {r["source"]: r for r in rows}
    # Only a LIVE watch stores what it reads. In shadow the BIS read is real but
    # nothing reaches dob_logs, so a fresh shadow check next to an empty list
    # would be a false "none".
    bis, ecb = by_key["bis_complaints"], by_key["bis_ecb"]
    live = bis["status"] == "fresh" and bis["mode"] == "live"
    shadow = bis["status"] == "fresh" and bis["mode"] == "shadow"
    return {
        "sources": rows,
        "can_say_no_new_summonses": ecb["status"] == "fresh" and ecb["mode"] == "live",
        "can_say_no_new_complaints": live,
        "note": ("Checked DOB BIS directly; new complaints show within minutes."
                 if live else
                 "DOB BIS is being checked in a trial mode that does not add records here yet. NYC Open "
                 "Data refreshes once a day, so a complaint filed today may not appear here until "
                 "tomorrow afternoon."
                 if shadow else
                 "Not checked against DOB BIS recently. NYC Open Data refreshes once a day, so a "
                 "complaint filed today may not appear here until tomorrow afternoon."),
    }


# ── The message a GC should get ──────────────────────────────────────────────

def render_alert(rec: Mapping[str, Any], decision: Mapping[str, Any], *, project_name: str,
                 lang: str = "en") -> str:
    cn = decision.get("complaint_number") or rec.get("complaint_number")
    rcv = received_at(rec)
    when = ""
    if rcv:
        t = rcv.astimezone(ET)
        clock = f"{(t.hour % 12) or 12}:{t.minute:02d}" if (t.hour or t.minute) else ""
        if lang == "es":
            when = f"el {t.day} de {_ES_MONTHS[t.month - 1]}"
            when += f", {clock} {'a. m.' if t.hour < 12 else 'p. m.'}" if clock else ""
        else:
            when = f"{t:%b} {t.day}" + (f", {clock} {'AM' if t.hour < 12 else 'PM'}" if clock else "")
    desc = str(rec.get("description") or "").strip().rstrip(".")
    insp = rec.get("last_inspection_date") or rec.get("inspection_date")
    link = f"https://a810-bisweb.nyc.gov/bisweb/OverviewForComplaintServlet?complaintno={cn}&requestid=0"
    if lang == "es":
        head = ("ORDEN DE PARAR TRABAJO" if decision.get("event") == "stop_work_order" else
                "ORDEN DE DESALOJO" if decision.get("event") == "vacate_order" else
                {"critical": "Queja urgente del DOB", "high": "Queja de seguridad del DOB",
                 "normal": "Nueva queja del DOB"}[decision.get("priority", "normal")])
        lines = [f"*{head} — {project_name}*",
                 f"Queja {cn}, recibida por el DOB {when}." + (" (Llegó tarde.)" if decision.get("late") else ""),
                 f"Dice: {desc}." if desc else "",
                 ("Todavía sin inspección. Una queja no es una violación: corrija esto antes de que llegue el inspector."
                  if not insp else f"Inspeccionada {insp}."),
                 link]
    else:
        head = ("STOP-WORK ORDER" if decision.get("event") == "stop_work_order" else
                "VACATE ORDER" if decision.get("event") == "vacate_order" else
                {"critical": "Urgent DOB complaint", "high": "DOB safety complaint",
                 "normal": "New DOB complaint"}[decision.get("priority", "normal")])
        lines = [f"*{head} — {project_name}*",
                 f"Complaint {cn}, received by DOB {when}." + (" (Arrived late.)" if decision.get("late") else ""),
                 f"It says: {desc}." if desc else "",
                 ("Not inspected yet. A complaint is not a violation: fix this before the inspector comes."
                  if not insp else f"Inspected {insp}."),
                 link]
    return "\n".join(x for x in lines if x)
