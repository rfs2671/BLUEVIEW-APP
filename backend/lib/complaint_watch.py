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

ORDER_DISPOSITIONS = {"A3", "H5", "L1", "K4", "K6", "Y1", "Y3", "P3", "RH", "RI", "H3", "H4", "V3"}
VIOLATION_DISPOSITIONS = {"A8", "B1", "B2", "R5", "A6", "RK", "K5", "ND"}
RESCIND_DISPOSITIONS = {"L3", "L4", "A4", "H6"}


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
            or str(rec.get("complaint_source") or "").lower() == "311"
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
    seen = first_seen_at or now
    sa = safety_assessment(rec)
    dclass = disposition_class(rec.get("disposition_code"))
    if not is_open(rec):
        if dclass in ("order", "violation"):
            out.update(alert=True, event=("stop_work_order" if dclass == "order" else "violation_served"),
                       priority=("critical" if dclass == "order" else "high"),
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
    out["priority"] = {"order": "critical", "safety": "high"}.get(sa["tier"], "normal")
    out["late"] = bool(rcv and seen - rcv > LATE_AFTER)
    out["reason"] = "; ".join(sa["reasons"]) or "open DOB complaint"
    return out


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
    "dob_complaints": "NYC Open Data complaints (daily)",
    "dob_violations": "DOB / ECB violations",
}


def freshness(state: Optional[Mapping[str, Any]], *, now: datetime,
              stale_after: timedelta = timedelta(minutes=45)) -> Dict[str, Any]:
    sources = (state or {}).get("sources") or {}
    watch = ((state or {}).get("watch") or {}).get("bis_complaints") or {}
    rows: List[Dict[str, Any]] = []
    for key in ("bis_complaints", "dob_complaints", "dob_violations"):
        if key == "bis_complaints":
            last_ok, last_err = _as_dt(watch.get("last_success_at")), watch.get("last_error")
            last_try = _as_dt(watch.get("last_attempt_at"))
        else:
            last_ok, last_err, last_try = _as_dt((sources.get(key) or {}).get("synced_at")), None, None
        age = (now - last_ok) if last_ok else None
        rows.append({
            "source": key, "label": SOURCE_LABELS[key],
            "last_success_at": last_ok.isoformat() if last_ok else None,
            "last_attempt_at": last_try.isoformat() if last_try else None,
            "last_error": last_err,
            "status": ("never" if not last_ok else "stale" if age > stale_after else "fresh"),
        })
    live = rows[0]["status"] == "fresh"
    return {
        "sources": rows,
        "can_say_no_new_complaints": live,
        "note": ("Checked DOB BIS directly; new complaints show within minutes."
                 if live else
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
        head = {"critical": "ORDEN DE PARAR TRABAJO", "high": "Queja de seguridad del DOB",
                "normal": "Nueva queja del DOB"}[decision.get("priority", "normal")]
        lines = [f"*{head} — {project_name}*",
                 f"Queja {cn}, recibida por el DOB {when}." + (" (Llegó tarde.)" if decision.get("late") else ""),
                 f"Dice: {desc}." if desc else "",
                 ("Todavía sin inspección. Una queja no es una violación: corrija esto antes de que llegue el inspector."
                  if not insp else f"Inspeccionada {insp}."),
                 link]
    else:
        head = {"critical": "STOP-WORK ORDER", "high": "DOB safety complaint",
                "normal": "New DOB complaint"}[decision.get("priority", "normal")]
        lines = [f"*{head} — {project_name}*",
                 f"Complaint {cn}, received by DOB {when}." + (" (Arrived late.)" if decision.get("late") else ""),
                 f"It says: {desc}." if desc else "",
                 ("Not inspected yet. A complaint is not a violation: fix this before the inspector comes."
                  if not insp else f"Inspected {insp}."),
                 link]
    return "\n".join(x for x in lines if x)
