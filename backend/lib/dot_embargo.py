"""NYC DOT holiday construction embargo -- the pure rules (no database, no HTTP).

THE EMBARGO. Every year from November 15 through January 2 of the following
year, DOT street work stops unless the permit carries a waiver. The waiver is a
STIPULATION on the permit, id "410". Its text, read from live data on
2026-10-22 (permits B012026295A03, B012026295A01, M022026294C43/C44/C45):

    "A WAIVER IS GRANTED TO ALLOW WORK TO OCCUR DURING THE HOLIDAY CONSTRUCTION
    EMBARGO (IN EFFECT ANNUALLY FROM NOVEMBER 15TH THROUGH JANUARY 2ND THE
    FOLLOWING YEAR), AS STIPULATED BY THE OCMC OFFICE."

Stipulations are their own dataset, gsgx-6efw (permitnumber, stipulationid,
stipulationfulltext, createdon); the permit dataset (tqtj-sjs8) does not carry
them. The sync stores them on the permit's dot_logs row as
`stipulations: [{id, text}]` and `holiday_waiver`.

THE RULE. A project's DOT permit is EXPOSED for a season when it is
  * active: status starts with ISSUED (dot_sync.permit_is_active) or EMERGENCY;
  * its work dates (work_start = issuedworkstartdate, expiration_date =
    issuedworkenddate) overlap Nov 15 .. Jan 2, both ends inclusive.
An exposed permit whose holiday_waiver is False is flagged. True is fine.

UNKNOWN IS NOT "NO WAIVER". holiday_waiver is None (or absent) when the
stipulations could not be read -- a failed request, or a successful one that
returned no stipulations at all for the permit (the stipulation dataset can
lag the permit dataset, and a permit with no stipulations is far more likely to
be unpublished than waiver-less). None NEVER alerts and is never shown as
missing a waiver.

WHEN THE EMAIL IS DUE (New York calendar dates, inside Nov 1 .. Jan 2):
  * Nov 1 and Nov 12: every flagged permit;
  * first sight: a flagged permit first matched (detected_at) inside the window
    whose DOT permitissuedate is no more than 2 days before today. Its send
    date is the day it was first seen, so the next day's run cannot send it a
    second time.
One send per (project, permit, season, send date): `ledger_id`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional
from zoneinfo import ZoneInfo

from lib import dot_sync

NY = ZoneInfo("America/New_York")

STIPULATION_DATASET = "gsgx-6efw"
WAIVER_STIPULATION_ID = "410"

SEASON_START = (11, 15)      # Nov 15
SEASON_END = (1, 2)          # Jan 2 of the following year
ALERT_FROM = (11, 1)         # alerts and the banner start Nov 1
REMINDER_DAYS = ((11, 1), (11, 12))
FIRST_SIGHT_MAX_AGE_DAYS = 2
UPCOMING_DAYS = 30           # stipulations are read for permits starting this soon

TRIGGER_TYPE = "dot_embargo_waiver_missing"

#: The action line every embargo email and GC group post carries (operator
#: copy, 2026-10-22). "one" is the waiver named just before it.
ACTION_EN = "No street work Nov 15 - Jan 2 unless DOT grants one."
ACTION_ES = ("No se permite trabajo en la calle del 15 de nov al 2 de ene salvo que "
             "el DOT otorgue una exención.")

#: COVERAGE LIMIT -- TEMPORARY. Only permits matched to the project's address
#: (borough + house + street) are checked; segment permits (no house number)
#: are not matched yet. The embargo email and the app banner (i18n
#: dotEmbargo.coverageNote) say so. DOT Phase 1 B REMOVES THIS: it adds permits
#: matched by permittee + frontage segment, after which the note is untrue.
COVERAGE_NOTE_EN = ("Checks permits matched to your address. Permits filed by street "
                    "segment arrive with the next update.")
COVERAGE_NOTE_ES = ("Revisa los permisos vinculados a su dirección. Los permisos "
                    "registrados por tramo de calle llegarán con la próxima actualización.")
LEDGER = "dot_alert_ledger"


class Season(NamedTuple):
    year: int        # the year the season STARTS (Nov 15 of this year)
    start: date
    end: date


# ── Dates ───────────────────────────────────────────────────────────────────

def parse_day(v: Any) -> Optional[date]:
    """A calendar date from a dataset value ("2026-11-30T23:59:59.000"), a
    date or a datetime -- or None. The datasets' timestamps are New York local
    dates with a time; only the date part is meant."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def ny_date(v: Any) -> Optional[date]:
    """The New York calendar date of an instant (a naive datetime is UTC, as
    Mongo returns it); a string or date is read as a date."""
    if isinstance(v, datetime):
        t = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return t.astimezone(NY).date()
    return parse_day(v)


def season_for(d: date) -> Season:
    """The season a date belongs to, or the next one. Jan 1 and Jan 2 belong
    to the season that started the previous November."""
    y = d.year - 1 if (d.month, d.day) <= SEASON_END else d.year
    return Season(y, date(y, *SEASON_START), date(y + 1, *SEASON_END))


def in_alert_window(d: date) -> bool:
    """Nov 1 .. Jan 2 (inclusive): when the banner shows and emails go out."""
    s = season_for(d)
    return date(s.year, *ALERT_FROM) <= d <= s.end


# ── One permit ──────────────────────────────────────────────────────────────

def is_active(status: Any) -> bool:
    s = str(status or "").strip().upper()
    return dot_sync.permit_is_active(s) or s.startswith("EMERGENCY")


def work_dates(row: Dict[str, Any]):
    """(start, end) of the permit's work. Start falls back to the issue date
    for a row synced before work_start was stored."""
    start = parse_day(row.get("work_start")) or parse_day(row.get("issue_date"))
    end = parse_day(row.get("expiration_date"))
    return start, end


def exposed(row: Dict[str, Any], season: Season) -> bool:
    """An active DOT permit whose work dates overlap the season. Without a
    work end date nothing can be said, so it is not exposed."""
    if (row.get("record_type") or "dot_permit") != "dot_permit":
        return False
    if not is_active(row.get("status")):
        return False
    start, end = work_dates(row)
    if end is None:
        return False
    if start is not None and start > season.end:
        return False
    return end >= season.start


def has_waiver(row: Dict[str, Any]) -> Optional[bool]:
    """True / False when the stipulations were read; None when they were not."""
    v = row.get("holiday_waiver")
    return v if isinstance(v, bool) else None


def needs_waiver(row: Dict[str, Any], season: Season) -> bool:
    """Exposed AND known to have no waiver. None is never flagged."""
    return exposed(row, season) and has_waiver(row) is False


def stipulations_wanted(row: Dict[str, Any], today: date) -> bool:
    """A matched permit whose stipulations should be read: active, or its work
    starts within UPCOMING_DAYS."""
    if (row.get("record_type") or "") != "dot_permit" or not row.get("number"):
        return False
    if is_active(row.get("status")):
        return True
    start = parse_day(row.get("work_start"))
    return start is not None and today <= start <= today + timedelta(days=UPCOMING_DAYS)


# ── Stipulations ────────────────────────────────────────────────────────────

def stipulation_params(permit: str) -> Dict[str, str]:
    return {"$where": f"permitnumber = '{str(permit).replace(chr(39), chr(39) * 2)}'",
            "$select": "permitnumber,stipulationid,stipulationfulltext,createdon",
            "$order": "stipulationid", "$limit": "1000"}


def _sid(v: Any) -> str:
    return str(v or "").strip().upper()


def is_waiver_id(v: Any) -> bool:
    """"410" -- also written "0410" should the dataset ever zero-pad it."""
    s = _sid(v)
    return s.isdigit() and s.lstrip("0") == WAIVER_STIPULATION_ID


def stipulation_fields(permit: str, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The dot_logs fields from a SUCCESSFUL stipulations read. A read that
    returned nothing for this permit is unknown, not "no waiver"."""
    out: List[Dict[str, str]] = []
    seen = set()
    for r in records or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("permitnumber") or "").strip().upper() != str(permit).strip().upper():
            continue
        sid = _sid(r.get("stipulationid"))
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append({"id": sid, "text": str(r.get("stipulationfulltext") or "").strip()})
    out.sort(key=lambda s: s["id"])
    waiver: Optional[bool] = (any(is_waiver_id(s["id"]) for s in out)
                              if out else None)
    return {"stipulations": out, "holiday_waiver": waiver}


# ── What is due today ───────────────────────────────────────────────────────

def ledger_id(project_id: str, permit: str, season_year: int, send_date: date) -> str:
    return f"dot:{project_id}:embargo:{permit}:{season_year}:{send_date.isoformat()}"


def due_sends(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """The emails due on `today` (a New York date) for one project's dot_logs
    rows: [{permit, kind: 'reminder'|'first_sight', send_date, season, row}].
    One per (permit, send date); a reminder wins over a first sight."""
    if not in_alert_window(today):
        return []
    season = season_for(today)
    reminder_day = (today.month, today.day) in REMINDER_DAYS
    due: Dict[tuple, Dict[str, Any]] = {}
    for row in rows or []:
        permit = str(row.get("number") or "").strip()
        if not permit or not needs_waiver(row, season):
            continue
        if reminder_day:
            due[(permit, today)] = {"permit": permit, "kind": "reminder",
                                    "send_date": today, "season": season, "row": row}
        seen = ny_date(row.get("detected_at"))
        issued = parse_day(row.get("issue_date"))
        if (seen is not None and issued is not None and in_alert_window(seen)
                and season_for(seen) == season and seen <= today
                and 0 <= (today - issued).days <= FIRST_SIGHT_MAX_AGE_DAYS):
            due.setdefault((permit, seen), {"permit": permit, "kind": "first_sight",
                                            "send_date": seen, "season": season, "row": row})
    return sorted(due.values(), key=lambda d: (d["permit"], d["send_date"]))


def banner(rows: Iterable[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """What the Compliance screen shows: inside the window, the exposed
    permits known to lack the waiver."""
    season = season_for(today)
    window = in_alert_window(today)
    missing, unknown = [], []
    for row in rows or []:
        if not exposed(row, season):
            continue
        start, end = work_dates(row)
        item = {"number": row.get("number"), "description": row.get("description"),
                "work_start": start.isoformat() if start else None,
                "work_end": end.isoformat() if end else None}
        w = has_waiver(row)
        if w is False:
            missing.append(item)
        elif w is None:
            unknown.append(item)
    missing.sort(key=lambda x: str(x["number"]))
    unknown.sort(key=lambda x: str(x["number"]))
    # Shown for an UNVERIFIED waiver too ("Waiver not verified", operator ruling
    # 2026-10-22): the screen may say what the email never will, because a
    # reader can check it; unknown still never sends anything.
    return {"in_window": window, "show": window and bool(missing or unknown),
            "season": {"year": season.year, "start": season.start.isoformat(),
                       "end": season.end.isoformat()},
            "missing_waiver": missing if window else [],
            "unknown": unknown if window else []}
