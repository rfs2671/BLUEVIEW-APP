"""Which DOB records email, and what the email says. Pure: no DB, no HTTP.

WHAT HAPPENED (2026-10-22). #829 taught the DOB sync to fetch the job site's
other building BINs. On its first run in production it reached BIN 3430621 for
588 Thomas S Boyland for the first time and found complaint 3A78809 -- entered
by DOB on 09/02/2026 and CLOSED the same day -- plus ECB violations 39558662P
(active) and 39558663R (resolved), all dated 09/02. The sync's only backfill
guard was "first scan of this PROJECT is silent", the project had been scanned
for months, and a seven-week-old closed complaint went to the customer as a
"New complaint".

THE RULES (operator rulings, 2026-10-22):

  1. Email only for a record NEW to Levelog whose DOB entry / issue date is
     within the last NEW_RECORD_MAX_AGE_DAYS (2). Older: stored, no email.
  2. An update to an existing record (status, disposition) never emails --
     EXCEPT an update that issues a Stop Work Order or a vacate order.
     [Roy to confirm the exception.]
  3. The first sync of a newly added BIN stores everything silently
     (`scan_key`: initial_scan_done:dob:<project_id>:<bin>).
  4. A closed or resolved record never emails as new.
  5. The email shows "Received by DOB: <date>" and the current status.

A NEW record with no DOB date at all is refused too: rule 1 asks for a date
within two days, and a record that cannot show one has not shown it.

THE TRADE, STATED. DOB's open data can publish a record days after DOB dated
it (an ECB summons is dated when served, and appears when loaded). A genuine
record that reaches the feed more than 2 days after its own date is stored and
shown in the app, and not emailed. That is the ruling: a missed email is
recoverable in the app; an old record sent as "new" is not.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional

from lib import wa_alerts, wa_gc
from lib.datefmt import strftime as _fmt

NEW_RECORD_MAX_AGE_DAYS = 2

#: Where each record type keeps the date DOB itself gave it, in the order they
#: are tried: complaints (date_entered), violations / SWOs / ECB (issue date),
#: permits and C of Os (issuance), filings, inspections.
RECEIVED_FIELDS = ("complaint_date", "date_entered", "violation_date", "issue_date",
                   "issuance_date", "filing_date", "inspection_date")

REFUSED_FIRST_SCAN_OF_BIN = "first_scan_of_bin"
REFUSED_CLOSED = "closed"
REFUSED_TOO_OLD = "too_old"
REFUSED_NO_DATE = "no_dob_date"


def scan_key(project_id: str, bin_: str) -> str:
    """system_config key: the DOB sync has finished a full pass of this BIN
    for this project."""
    return f"initial_scan_done:dob:{project_id}:{bin_}"


def received_date(row: Dict[str, Any]) -> Optional[date]:
    """The date DOB gave the record, or None when the record carries none."""
    for k in RECEIVED_FIELDS:
        d = wa_gc.parse_dob_date((row or {}).get(k))
        if d is not None:
            return d
    return None


def too_old(row: Dict[str, Any], today: date) -> bool:
    """Older than the window, or no DOB date to show it is not."""
    d = received_date(row)
    return d is None or (today - d).days > NEW_RECORD_MAX_AGE_DAYS


def new_alert_refusal(row: Dict[str, Any], today: date, *,
                      bin_scanned: bool = True) -> Optional[str]:
    """Why a FIRST SIGHTING of `row` must not email, or None when it may.
    `row` is the stored dob_log (its normalised fields)."""
    if not bin_scanned:
        return REFUSED_FIRST_SCAN_OF_BIN
    if wa_alerts.is_closed(row):
        return REFUSED_CLOSED
    if received_date(row) is None:
        return REFUSED_NO_DATE
    if too_old(row, today):
        return REFUSED_TOO_OLD
    return None


# ── Rule 2: the one update that emails ──────────────────────────────────────

_ORDER_TEXT = re.compile(r"\bstop[- ]work\b|\bswo\b|\bvacate\b", re.IGNORECASE)
_ORDER_ENDED = re.compile(r"rescind|lifted|previously issued|underway|disobey|failure to obey",
                          re.IGNORECASE)
_VACATE = re.compile(r"\bvacate\b", re.IGNORECASE)


def _disposition_label(row: Dict[str, Any]) -> str:
    code = str((row or {}).get("disposition_code") or "").strip()
    if not code:
        return ""
    try:
        from dob_complaint_codes import get_disposition_label
        return get_disposition_label(code)
    except Exception:
        return ""


def _order_text(row: Dict[str, Any]) -> str:
    r = row or {}
    return " ".join(str(r.get(k) or "") for k in (
        "violation_subtype", "violation_type", "violation_category", "description",
        "current_status", "status")) + " " + _disposition_label(r)


def order_in_force(row: Dict[str, Any]) -> Optional[str]:
    """"swo" / "vacate" when the record, as it stands, names a Stop Work Order
    or a vacate order that is in force; None otherwise. A rescinded or lifted
    order, or a violation FOR disobeying one, is not a new order."""
    r = row or {}
    if str(r.get("record_type") or "").lower() == "swo":
        status = str(r.get("current_status") or r.get("status") or "")
        return None if (_ORDER_ENDED.search(status) or wa_alerts.is_closed(r)) else "swo"
    text = _order_text(r)
    if not _ORDER_TEXT.search(text) or _ORDER_ENDED.search(text):
        return None
    return "vacate" if _VACATE.search(text) else "swo"


def update_issues_order(before: Optional[Dict[str, Any]], after: Dict[str, Any]) -> Optional[str]:
    """The order an UPDATE issues: in force after the change and not before."""
    now_ = order_in_force(after)
    if now_ is None:
        return None
    return None if order_in_force(before or {}) == now_ else now_


# ── The email: EN / ES copy and the record line ─────────────────────────────

COPY = {
    "en": {
        "subject_new": "New {rt} on {project}",
        "intro_new": "Levelog picked up a new {rt} on {project}.",
        "subject_swo": "Stop Work Order on {project}",
        "intro_swo": "DOB issued a Stop Work Order on {project}.",
        "subject_vacate": "Vacate order on {project}",
        "intro_vacate": "DOB issued a vacate order on {project}.",
        "received": "Received by DOB",
        "status": "Status",
        "not_stated": "not stated",
    },
    "es": {
        "subject_new": "Nuevo registro del DOB en {project}",
        "intro_new": "Levelog encontró un registro nuevo del DOB en {project}.",
        "subject_swo": "Orden de suspensión de obra en {project}",
        "intro_swo": "El DOB emitió una orden de suspensión de obra en {project}.",
        "subject_vacate": "Orden de desalojo en {project}",
        "intro_vacate": "El DOB emitió una orden de desalojo en {project}.",
        "received": "Recibido por el DOB",
        "status": "Estado",
        "not_stated": "no indicado",
    },
}

#: The events an email can be for. "new": a first sighting that passed
#: new_alert_refusal. "swo" / "vacate": an update that issued that order.
EVENTS = ("new", "swo", "vacate")

_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic")


def _date_label(d: Optional[date], lang: str) -> str:
    if d is None:
        return COPY[lang]["not_stated"]
    if lang == "es":
        return f"{d.day} {_ES_MONTHS[d.month - 1]} {d.year}"
    return _fmt(d, "%b %-d, %Y")


def record_number(row: Dict[str, Any]) -> str:
    for k in ("complaint_number", "violation_number", "stop_work_order_number",
              "job_number", "raw_dob_id"):
        v = str((row or {}).get(k) or "").strip()
        if v:
            return v
    return ""


def current_status(row: Dict[str, Any], lang: str) -> str:
    r = row or {}
    st = str(r.get("current_status") or r.get("complaint_status") or r.get("status") or "").strip()
    return st or COPY[lang]["not_stated"]


def record_line(row: Dict[str, Any], rt: str, lang: str) -> str:
    """'Complaint 3A78809 · Received by DOB: Sep 2, 2026 · Status: CLOSED'
    (Spanish: no type word -- the number is on the English line above it)."""
    c = COPY[lang]
    head = f"{rt[:1].upper()}{rt[1:]} {record_number(row)}".strip() if lang == "en" else ""
    parts = [p for p in (
        head,
        f"{c['received']}: {_date_label(received_date(row), lang)}",
        f"{c['status']}: {current_status(row, lang)}",
    ) if p]
    return " · ".join(parts)


# ── WhatsApp GC group alerts: the same rules (operator ruling 2026-10-22) ────
#
# The group alerts (server._gc_alerts_tick, lib/wa_alerts) post once ever per
# item from a ledger, with a per-kind baseline. They now follow the email's
# rules: a record new to Levelog posts only if DOB dated it within 2 days, an
# update never posts unless it issued a SWO or vacate order, and the first sync
# of a newly added BIN is silent -- except ONE summary per project per new BIN.

GC_NEW_RECORD_KINDS = ("violation", "complaint", "swo")
GC_UPDATE_KINDS = ("violation_status", "permit_status", "swo_rescinded")
ORDER_KIND = "order"            # an update that issued a SWO / vacate order
BIN_ADDED_KIND = "bin_added"    # one summary for a newly added BIN
REFUSED_UPDATE = "update"


def gc_refusal(item: Dict[str, Any], today: date) -> Optional[str]:
    """Why a group alert item must not post, or None when it may."""
    kind, rec = item.get("kind"), item.get("rec") or {}
    if kind in GC_UPDATE_KINDS:
        return REFUSED_UPDATE
    if kind in GC_NEW_RECORD_KINDS:
        if rec.get("bin_first_pass"):
            return REFUSED_FIRST_SCAN_OF_BIN
        if received_date(rec) is None:
            return REFUSED_NO_DATE
        if too_old(rec, today):
            return REFUSED_TOO_OLD
    if kind == ORDER_KIND:
        d = wa_gc.parse_dob_date(((rec.get("order_issued") or {}).get("at")))
        if d is None or (today - d).days > NEW_RECORD_MAX_AGE_DAYS:
            return REFUSED_TOO_OLD
    return None


def gc_order_items(latest_rows, today: date) -> list:
    """An item for each record an UPDATE put under a SWO / vacate order within
    the window (the sync stamps `order_issued` when update_issues_order says
    so). Keyed on the order and its day, so a later, separate order posts."""
    out = []
    for r in latest_rows or []:
        oi = (r or {}).get("order_issued") or {}
        d = wa_gc.parse_dob_date(oi.get("at"))
        rid = str(r.get("raw_dob_id") or "")
        if not rid or d is None or oi.get("kind") not in ("swo", "vacate"):
            continue
        if (today - d).days > NEW_RECORD_MAX_AGE_DAYS:
            continue
        out.append({"kind": ORDER_KIND, "item": f"{rid}:order:{oi['kind']}:{d:%Y%m%d}",
                    "rec": r, "order": oi["kind"]})
    return out


#: The record types a BIN summary lists when open.
BIN_SUMMARY_TYPES = ("violation", "complaint", "swo")


def gc_bin_summary_items(latest_rows) -> list:
    """ONE item per BIN whose first pass stored records: the rows the sync
    flagged `bin_first_pass`, grouped by their `site_bin`. Only open records
    are listed (lib/wa_alerts.is_closed), newest DOB date first."""
    by_bin: Dict[str, list] = {}
    for r in latest_rows or []:
        b = str((r or {}).get("site_bin") or "")
        if b and r.get("bin_first_pass"):
            by_bin.setdefault(b, []).append(r)
    out = []
    for b in sorted(by_bin):
        open_rows = [r for r in by_bin[b]
                     if str(r.get("record_type") or "").lower() in BIN_SUMMARY_TYPES
                     and not wa_alerts.is_closed(r)]
        open_rows.sort(key=lambda r: received_date(r) or date.min, reverse=True)
        out.append({"kind": BIN_ADDED_KIND, "item": f"bin:{b}",
                    "rec": {"site_bin": b, "raw_dob_id": f"bin:{b}"},
                    "bin": b, "open": open_rows})
    return out


_TYPE_WORD = {
    "en": {"violation": "Violation", "complaint": "Complaint", "swo": "Stop-work order"},
    "es": {"violation": "Infracción", "complaint": "Queja", "swo": "Orden de suspensión de obra"},
}
BIN_SUMMARY_COPY = {
    "en": {"head": "Now also tracking BIN {bin} for this job.",
           "open": "Open items found: {n}", "none": "No open items found."},
    "es": {"head": "Ahora también seguimos el BIN {bin} de esta obra.",
           "open": "Pendientes abiertos: {n}", "none": "No hay pendientes abiertos."},
}


def _bin_item_line(r: Dict[str, Any], lang: str) -> str:
    rt = str(r.get("record_type") or "").lower()
    word = _TYPE_WORD[lang].get(rt, rt.title())
    c = COPY[lang]
    return (f"• {word} {record_number(r)} · {c['received']}: "
            f"{_date_label(received_date(r), lang)} · {c['status']}: {current_status(r, lang)}")


def bin_summary_message(address: str, bin_: str, open_rows, icon: str = "🟠") -> str:
    """The one group message for a newly added BIN, English then Spanish."""
    lines = [f"{icon} {address}"]
    for lang in ("en", "es"):
        c = BIN_SUMMARY_COPY[lang]
        lines.append(c["head"].format(bin=bin_))
        if open_rows:
            lines.append(c["open"].format(n=len(open_rows)))
            lines += [_bin_item_line(r, lang) for r in open_rows]
        else:
            lines.append(c["none"])
    lines.append("Source: DOB")
    return "\n".join(lines)


def headline(event: str, rt: str, project: str, lang: str) -> Dict[str, str]:
    """{subject, intro} for an event in EVENTS."""
    c = COPY[lang]
    ev = event if event in EVENTS else "new"
    return {"subject": c[f"subject_{ev}"].format(rt=rt, project=project),
            "intro": c[f"intro_{ev}"].format(rt=rt, project=project)}
