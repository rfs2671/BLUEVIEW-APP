"""The regulatory section of a progress report, read AS OF the period.

WHAT THE OLD SECTION SAID, AND WHY IT COULD NOT BE TRUSTED. It listed every
DOB/DOT row whose `detected_at` -- the moment LeveLog first SAW the record --
fell in the period, and called them "new ... issued". Four consequences, each
measured in the audit of 2026-10-19:

  * a project's whole history (up to 50 rows per dataset) landed in the
    period containing its first sync, because first-sync rows were never
    marked as a backlog;
  * a violation issued in the period but detected the day after it was not
    in it, and one issued years ago and detected in it was;
  * dates printed without a year ("Mar 4" for a 2019 violation);
  * "None -- no new DOB or DOT records" was printed when the project had no
    BIN, DOB tracking was off, a dataset failed, or the sync had never run:
    an absence asserted with nothing behind it.

THE RULES HERE.
  ISSUED     the record's own issue date is in the period. First-sync rows are
             therefore never "new" -- an old record has an old issue date.
  CHANGED    the record's status changed during the period, read from its
             status history (`status_history`, written by the sync) or from a
             permit's status-change rows. A change the sync could not date
             (`legacy_first_refresh`) is NOT a change in a period: we know it
             happened sometime before that refresh, not when.
  OPEN       open AS OF THE PERIOD'S LAST DAY, from the same history. A report
             for last month read today says what was open at month end, not
             what is open now. A record whose status at that moment cannot be
             established (its only dated refresh came after the period) is
             counted as UNCERTAIN and named, never as open or closed.
  COVERAGE   whether the feed was actually checked through the period's end.
             "None recorded" is printed only when coverage is verified; else
             the section says what is unknown.

One record is one entry: a permit that changed status twice has several rows
and appears once, with the status it had at the period's end. 311 service
requests are not construction records and are left out. Every entry keeps the
id of the row it came from so the report can cite it.

Pure: no I/O.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from lib.datefmt import strftime as _fmt
from lib import wa_alerts, wa_gc

NY = ZoneInfo("America/New_York")

KIND_LABELS = {"violation": "DOB violation", "swo": "Stop Work Order", "complaint": "DOB complaint",
               "permit": "DOB permit", "dot_violation": "DOT summons", "dot_permit": "DOT permit",
               "job_status": "DOB job filing", "cofo": "Certificate of Occupancy"}
#: Records that can be "open": something the owner has to resolve.
OPEN_TYPES = ("violation", "swo", "complaint", "dot_violation")
#: Records with an issue date: the ones that can be "issued in the period".
ISSUED_TYPES = ("violation", "swo", "complaint", "permit", "dot_violation", "dot_permit")
PERMIT_TYPES = ("permit", "dot_permit")
EXPIRY_HORIZON_DAYS = 60
CHANGE_SOURCES = ("sync", "row")


def _utc(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _day_end(d: date) -> datetime:
    """The last instant of `d` in New York, in UTC: "as of the end of the day"."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=NY).astimezone(timezone.utc)


def _t(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _is_311(r: Dict[str, Any]) -> bool:
    return (_t(r.get("source")).lower() == "311" or _t(r.get("complaint_source")).lower() == "311"
            or _t(r.get("raw_dob_id")).startswith("311:"))


def _rtype(r: Dict[str, Any]) -> str:
    return _t(r.get("record_type")).lower()


def _is_swo(r: Dict[str, Any]) -> bool:
    sub = _t(r.get("violation_subtype")).upper()
    return _rtype(r) == "swo" or sub.startswith(("SWO", "VACATE"))


def _kind_label(r: Dict[str, Any]) -> str:
    if _t(r.get("violation_subtype")).upper().startswith("VACATE"):
        return "Vacate Order"
    if _is_swo(r):
        return "Stop Work Order"
    return KIND_LABELS.get(_rtype(r), _rtype(r).replace("_", " ").capitalize() or "Record")


def _record_key(r: Dict[str, Any]) -> str:
    if _rtype(r).startswith("dot_"):
        return "dot:" + _t(r.get("raw_id") or r.get("raw_dob_id"))
    return _t(r.get("raw_dob_id"))


Point = Tuple[datetime, str, str]       # (when, status, source)


def _points(rows: List[Dict[str, Any]]) -> List[Point]:
    """Every dated status a record is known to have had, oldest first. Rows
    that carry a `status_history` contribute it; a row without one (an older
    row, a permit's status-change row) contributes the one status it holds,
    dated by its own change time, else the time it was first seen."""
    pts: List[Point] = []
    for r in rows:
        hist = r.get("status_history")
        if isinstance(hist, list) and hist:
            for h in hist:
                at, st = _utc((h or {}).get("at")), _t((h or {}).get("status"))
                if at and st:
                    pts.append((at, st, _t((h or {}).get("source")) or "sync"))
            continue
        at = _utc(r.get("status_changed_at")) or _utc(r.get("detected_at")) or _utc(r.get("created_at"))
        st = wa_alerts.record_status(r)
        if at and st:
            pts.append((at, st, "row" if r.get("status_changed_at") and not r.get("is_seed_transition")
                        else "first_seen"))
    pts.sort(key=lambda p: p[0])
    out: List[Point] = []
    for p in pts:
        if out and out[-1][:2] == p[:2]:
            continue
        out.append(p)
    return out


def _status_at(pts: List[Point], at: datetime) -> Tuple[Optional[str], bool]:
    """(status as of `at`, uncertain). Uncertain when the record's status at
    that moment cannot be told: nothing was known by then, or the next dated
    refresh after it could not say when the status actually changed."""
    known = [p for p in pts if p[0] <= at]
    later = [p for p in pts if p[0] > at]
    status = known[-1][1] if known else None
    uncertain = status is None or any(p[2] == "legacy_first_refresh" for p in later[:1])
    return status, uncertain


def _closed_status(status: Optional[str]) -> bool:
    return bool(status) and wa_alerts.is_closed({"current_status": status})


def _link(r: Dict[str, Any]) -> Optional[str]:
    v = _t(r.get("dob_link") or r.get("link"))
    return v if v.startswith("https://") else None


def _entry(rows: List[Dict[str, Any]], latest: Dict[str, Any], status: Optional[str],
           closed: Optional[bool]) -> Dict[str, Any]:
    rt = _rtype(latest)
    return {"id": _record_key(latest), "row_id": _t(latest.get("_id")), "type": rt,
            "kind": _kind_label(latest), "number": wa_alerts.record_number(latest) or "",
            "issued": wa_alerts.record_issue_date(latest), "status": status or "",
            "closed": closed, "link": _link(latest), "expires": None,
            "source": "dot" if rt.startswith("dot_") else "dob"}


def _expiry(r: Dict[str, Any]) -> Optional[date]:
    return wa_gc.parse_dob_date(r.get("expiration_date"))


SERIES_MIN = 3


def _collapse_series(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """DOT street permits issued together (one application: sidewalk, roadway,
    equipment, fence ... all issued the same day, same status, same expiry) as ONE
    entry. The first real 588 report listed 20 of them, burying every real risk.
    Nothing is dropped: `members` carries every number, and the evidence index
    prints them. Only DOT permits group, and only 3 or more that agree on date,
    status and expiry."""
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for e in entries:
        key = (e["issued"], e["status"], e["expires"], e.get("changed_on")) if e.get("type") == "dot_permit" else None
        groups.setdefault(key if key else id(e), []).append(e)
    out: List[Dict[str, Any]] = []
    for g in groups.values():
        if len(g) < SERIES_MIN:
            out += g
            continue
        g = sorted(g, key=lambda x: x["number"])
        first = dict(g[0])
        first["members"] = [x["number"] for x in g]
        first["kind"] = f"{first['kind']}s ({len(g)})"
        first["number"] = f"{g[0]['number']} +{len(g) - 1} more"
        out.append(first)
    return sorted(out, key=lambda x: entries.index(next(e for e in entries if e["id"] == x["id"])))


FRESH_HOURS = 24


def coverage(sync: Optional[Dict[str, Any]], end: date, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Was the feed checked through the end of the period? `sync` is
    {"tracking": bool, "dob": datetime|None, "dob_complete": bool,
    "dot": datetime|None}, read by the server from the project and its
    `source_sync_state`.

    A period that has ended must have been checked AFTER it ended. A period
    that is still running (its last day is today or later) cannot be checked
    "through the end of the day" yet: it counts as verified when the feed was
    checked within FRESH_HOURS of `now`."""
    sync = sync or {}
    if sync.get("tracking") is False:
        return {"state": "not_tracked", "note": "DOB/DOT monitoring is not enabled for this project, "
                "so no regulatory records are reported."}
    dob, dot = _utc(sync.get("dob")), _utc(sync.get("dot"))
    if dob is None:
        return {"state": "unknown", "note": "The DOB/DOT feed has no completed sync on record for this "
                "project, so regulatory records are not reported."}
    through = _day_end(end)
    if now is not None and through > now:
        through = now - timedelta(hours=FRESH_HOURS)
    if dob < through:
        return {"state": "stale", "dob_through": dob, "dot_through": dot,
                "note": f"The DOB/DOT feed was last checked {_fmt(dob.astimezone(NY), '%b %-d, %Y')}, "
                        "before the end of this period; later changes are not reflected."}
    partial = not sync.get("dob_complete", True) or (dot is not None and dot < through)
    return {"state": "partial" if partial else "verified", "dob_through": dob, "dot_through": dot,
            "note": ("Some regulatory sources were not fully checked through the end of this period."
                     if partial else
                     f"DOB/DOT feed checked {_fmt(dob.astimezone(NY), '%b %-d, %Y')}.")}


_BIN_IN_LINK = re.compile(r"[?&](?:all)?bin=(\d{6,7})\b")


def row_bin(r: Dict[str, Any]) -> str:
    """The Building Identification Number the RECORD itself belongs to: its own
    `bin` / `bin__` field, else the one in its DOB link (built from the
    record). NOT the row's `nyc_bin`, which is the PROJECT's BIN when it was
    synced and says nothing about which building the record is for."""
    for k in ("bin", "bin__", "bin_number"):
        v = re.sub(r"\D", "", _t(r.get(k)))
        if v:
            return v
    m = _BIN_IN_LINK.search(_t(r.get("dob_link") or r.get("link")))
    return m.group(1) if m else ""


_JOB_BASE = re.compile(r"^[A-Za-z]?\d{8,9}")


def job_base(r: Dict[str, Any]) -> str:
    """The job a filing belongs to, without its filing suffix: "B01141294-S5"
    and "B01141294-P8" are the same job B01141294."""
    if _rtype(r) not in ("permit", "job_status"):      # a violation number is not a job
        return ""
    m = _JOB_BASE.match(_t(wa_alerts.record_number(r)).upper())
    return m.group(0) if m else ""


def split_by_bin(dob_rows: Iterable[Dict[str, Any]], bins: Iterable[Any]):
    """(kept, excluded, unverified, inferred) for a project whose BIN(s) are `bins`.

    A record whose own BIN is the project's belongs. A record under ANOTHER BIN
    belongs too when its JOB also appears under the project's BIN: one DOB job
    (B01141294) can be filed against more than one building of a lot, so that
    BIN is part of the site (the real 588 data: jobs B01141294 and B01409772
    each appear under BINs 3255362 and 3430621). Such BINs are `inferred`, and
    all their records are kept.

    Only a record under a BIN that shares NO job with the project's is another
    building's -- a neighbour's, from the address search: EXCLUDED and listed
    for review. A record with no readable BIN cannot be shown to belong or
    not: KEPT and counted as unverified, never dropped quietly. With no
    project BIN there is nothing to compare: all kept."""
    want = {re.sub(r"\D", "", str(b or "")) for b in bins if re.sub(r"\D", "", str(b or ""))}
    rows = list(dob_rows)
    if not want:
        return rows, [], 0, []
    own_jobs = {job_base(r) for r in rows if row_bin(r) in want and job_base(r)}
    inferred = sorted({row_bin(r) for r in rows if row_bin(r) and row_bin(r) not in want
                       and job_base(r) and job_base(r) in own_jobs})
    site = want | set(inferred)
    kept, excluded, unverified = [], [], 0
    for r in rows:
        b = row_bin(r)
        if not b:
            kept.append(r)
            unverified += 1
        elif b in site:
            kept.append(r)
        else:
            excluded.append(r)
    return kept, excluded, unverified, inferred


def _excluded_entries(rows: List[Dict[str, Any]], want: Iterable[str]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = _record_key(r) or _t(r.get("_id"))
        issued = wa_alerts.record_issue_date(r)
        seen[key] = {"type": _rtype(r), "kind": _kind_label(r), "number": wa_alerts.record_number(r) or "",
                     "issued": issued, "status": wa_alerts.record_status(r), "bin": row_bin(r),
                     "link": _link(r), "reason": "belongs to a different BIN than this project"}
    return sorted(seen.values(), key=lambda e: (e["bin"], str(e["issued"] or ""), e["number"]))


def build(dob_rows: Iterable[Dict[str, Any]], dot_rows: Iterable[Dict[str, Any]], start: date,
          end: date, *, today: Optional[date] = None, sync: Optional[Dict[str, Any]] = None,
          now: Optional[datetime] = None, project_bins: Iterable[Any] = ()) -> Dict[str, Any]:
    """The regulatory facts of a period.

    -> {"coverage": {...}, "issued": [...], "changed": [...], "open": [...],
        "swo_active": [...], "swo_lifted": [...], "expiring": [...],
        "uncertain": n, "counts": {...}}
    Every list holds entries from `_entry` (id, row_id, type, kind, number,
    issued, status, closed, link, expires, source) plus what that list adds.
    Lists are empty when coverage is not verified or partial-but-usable; the
    caller prints `coverage["note"]` instead of "none"."""
    cov = coverage(sync, end, now)
    out: Dict[str, Any] = {"coverage": cov, "issued": [], "changed": [], "open": [], "swo_active": [],
                           "swo_lifted": [], "expiring": [], "uncertain": 0, "excluded": [],
                           "bin_unverified": 0, "bins_inferred": [], "bins": sorted({re.sub(r"\D", "", str(b)) for b in project_bins if b}),
                           "counts": {"records": 0}}
    if cov["state"] in ("not_tracked", "unknown"):
        return out
    today = today or end
    end_at, start_at = _day_end(end), _day_end(start - timedelta(days=1))
    dob_rows, left_out, unverified, inferred = split_by_bin(dob_rows, project_bins)
    out["excluded"] = _excluded_entries(left_out, out["bins"])
    out["bin_unverified"] = unverified
    out["bins_inferred"] = inferred
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in list(dob_rows) + list(dot_rows):
        if r.get("is_deleted") or _is_311(r):
            continue
        rt = _rtype(r)
        if rt not in KIND_LABELS or not _record_key(r):
            continue
        groups.setdefault(_record_key(r), []).append(r)
    out["counts"]["records"] = len(groups)
    for rows in groups.values():
        rows.sort(key=lambda r: (_utc(r.get("status_changed_at")) or _utc(r.get("detected_at"))
                                 or datetime.min.replace(tzinfo=timezone.utc)))
        latest = rows[-1]
        rt = _rtype(latest)
        pts = _points(rows)
        status_end, uncertain = _status_at(pts, end_at)
        status_before, _ = _status_at(pts, start_at)
        issued = wa_alerts.record_issue_date(latest)
        first_seen = pts[0][0] if pts else None
        # A record LeveLog had not seen by the period's end, or whose issue
        # date is after it, is not part of this period's picture.
        if issued and issued > end:
            continue
        if not issued and (first_seen is None or first_seen > end_at):
            continue
        closed_end: Optional[bool] = None if uncertain else _closed_status(status_end)
        cd = wa_gc.parse_dob_date(latest.get("closed_date"))
        if closed_end is False and cd and cd <= end:
            closed_end = True
        e = _entry(rows, latest, status_end, closed_end)
        if rt in PERMIT_TYPES:
            e["expires"] = _expiry(latest)
        if uncertain and rt in OPEN_TYPES:
            out["uncertain"] += 1
        if rt in ISSUED_TYPES and issued and start <= issued <= end:
            out["issued"].append(dict(e))
        # CHANGED: a dated status change inside the period, not the record's
        # own creation and not an undatable legacy refresh.
        changes = [p for i, p in enumerate(pts) if i and p[2] in CHANGE_SOURCES
                   and start_at < p[0] <= end_at and p[1] != pts[i - 1][1]]
        if changes and not (issued and start <= issued <= end):
            prev = [p for p in pts if p[0] < changes[0][0]]
            c = dict(e)
            c.update(changed_from=prev[-1][1] if prev else status_before, changed_on=_utc(changes[-1][0]).astimezone(NY).date())
            out["changed"].append(c)
        if rt in OPEN_TYPES and closed_end is False:
            out["open"].append(dict(e))
            if _is_swo(latest):
                out["swo_active"].append(dict(e))
        if _is_swo(latest) and closed_end is True and changes:
            out["swo_lifted"].append(dict(e, changed_on=_utc(changes[-1][0]).astimezone(NY).date()))
        if rt in PERMIT_TYPES and not closed_end and e["expires"] \
                and end < e["expires"] <= end + timedelta(days=EXPIRY_HORIZON_DAYS) \
                and "REVOK" not in (status_end or "").upper():
            out["expiring"].append(dict(e))

    def newest(x: Dict[str, Any]):
        return (x["issued"] or date.min, x["kind"], x["number"])
    for k in ("issued", "changed", "expiring"):
        out[k] = _collapse_series(out[k])
    for k in ("issued", "changed", "open", "swo_active", "swo_lifted"):
        out[k].sort(key=newest, reverse=True)
    out["expiring"].sort(key=lambda x: (x["expires"], x["kind"], x["number"]))
    out["counts"].update(issued=len(out["issued"]), changed=len(out["changed"]), open=len(out["open"]),
                         swo_active=len(out["swo_active"]), expiring=len(out["expiring"]))
    return out
