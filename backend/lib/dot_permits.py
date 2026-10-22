"""DOT permits and setup (DOT Phase 1 B) -- the pure parts (no database, no HTTP).

SETUP, per project (`projects.dot_setup`):

    {status: "unset" | "suggested" | "confirmed",
     permittees: [{name, norm, source, seen_on}],
     frontages:  [{boro, on, from, to, source, suggested_by?, confirmed}],
     suggested_at, confirmed_by, confirmed_at}

  * street names are stored normalized (dot_sync.norm_street), the borough as
    its code ("3" = Brooklyn);
  * a frontage matches only when `confirmed` is True (an admin / full-access
    PM added or confirmed it). A superintendent's suggestion is stored with
    source "superintendent", suggested_by, confirmed False: no effect on
    matching until confirmed;
  * matching (dot_sync.classify_permit) uses the setup only once its status is
    "confirmed".

SUGGESTIONS (suggest()): from the permits already matched to the project by
ADDRESS whose permitissuedate is within 24 months -- the permittee names
ranked by count (the company's own name pre-checked when it appears) and the
segments those permits name. With none: the on-street of the project address
and the cross streets DOT has published for that street (one grouped request,
fallback_frontage()).

EXPIRY (expiry_due()): an email 14 and 3 days before a permit's work end (New
York dates), for CONFIRMED and ACTIVE permits only -- never a renewed, voided or
already expired one. The threshold due is the smallest one reached (14 from 14
days out, 3 from 3 days out, through the last day), so a run that misses a day
still sends; once per (project, permit, threshold, work end) in
dot_alert_ledger (`expiry_ledger_id`).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from lib import dot_embargo, dot_sync

TRIGGER_TYPE = "dot_permit_expiring"
EXPIRY_THRESHOLDS = (14, 3)
EXPIRING_DAYS = 14            # the screen's "expiring" section
SUGGEST_MONTHS = 24

SOURCE_SUGGESTED = "suggested"         # from the project's matched permits
SOURCE_ADMIN = "admin"                 # typed by an admin / full-access PM
SOURCE_SUPERINTENDENT = "superintendent"
SOURCE_DOT = "dot_cross_streets"       # the street's published cross streets


# ── Expiry ──────────────────────────────────────────────────────────────────

def expiry_threshold(days_left: Optional[int]) -> Optional[int]:
    """14 for 4..14 days left, 3 for 0..3 days left, else None."""
    if days_left is None or days_left < 0 or days_left > EXPIRY_THRESHOLDS[0]:
        return None
    due = None
    for t in EXPIRY_THRESHOLDS:
        if days_left <= t:
            due = t
    return due


def work_end(row: Dict[str, Any]) -> Optional[date]:
    return dot_embargo.parse_day(row.get("work_end") or row.get("expiration_date"))


def renewal_of(row: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Optional[str]:
    """The renewal: what the sync stored (it read the chain), else what the
    project's own permits say (another permit naming this one as previous)."""
    return row.get("renewed_by") or dot_sync.renewed_by(row, rows)


def _permits(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("record_type") or "") == "dot_permit" and r.get("number")]


def expiry_due(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """The expiry emails due on `today` (a New York date) for one project's
    dot_logs rows: [{permit, threshold, days, work_end, row, renewal}]."""
    permits = _permits(rows)
    out = []
    for row in permits:
        if not dot_sync.permit_confirmed(row):
            continue
        if not dot_embargo.is_active(row.get("status")) or dot_sync.permit_is_voided(row.get("status")):
            continue
        end = work_end(row)
        if end is None:
            continue
        days = (end - today).days
        t = expiry_threshold(days)
        if t is None:
            continue
        if renewal_of(row, permits):
            continue
        out.append({"permit": str(row["number"]), "threshold": t, "days": days,
                    "work_end": end, "row": row})
    return sorted(out, key=lambda d: (d["days"], d["permit"]))


def expiry_ledger_id(project_id: str, permit: str, threshold: int, end: date) -> str:
    return f"dot:{project_id}:expiry:{permit}:{threshold}:{end.isoformat()}"


# ── The permits screen ──────────────────────────────────────────────────────

GROUP_ORDER = {"active": 0, "expiring": 1, "expired": 2}


def boro_name(code: Any) -> str:
    return dot_sync.BORO_NAME.get(str(code or ""), "")


def segment_view(seg: Any) -> Optional[Dict[str, str]]:
    if not isinstance(seg, dict) or not seg.get("on"):
        return None
    return {"boro": str(seg.get("boro") or ""), "boro_name": boro_name(seg.get("boro")),
            "on": seg.get("on") or "", "from": seg.get("from") or "", "to": seg.get("to") or ""}


def permit_view(row: Dict[str, Any], today: date,
                rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    start, end = dot_embargo.work_dates(row)
    days = (end - today).days if end else None
    active = dot_embargo.is_active(row.get("status")) and not dot_sync.permit_is_voided(row.get("status"))
    if active and (days is None or days > EXPIRING_DAYS):
        group = "active"
    elif active and days >= 0:
        group = "expiring"
    else:
        group = "expired"
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    issued = dot_embargo.parse_day(row.get("issue_date"))
    return {
        "id": str(row.get("_id") or ""),
        "number": row.get("number"),
        "series": row.get("series"),
        "permit_type": row.get("permit_type") or row.get("description"),
        "status": row.get("status"),
        "permittee": row.get("permittee"),
        "issue_date": issued.isoformat() if issued else None,
        "work_start": start.isoformat() if start else None,
        "work_end": end.isoformat() if end else None,
        "days_left": days,
        "group": group,
        "segment": segment_view(row.get("segment")),
        "previous_permit": row.get("previous_permit"),
        "next_permit": row.get("next_permit"),
        "renewed_by": renewal_of(row, rows),
        "holiday_waiver": dot_embargo.has_waiver(row),
        # #852's rule: confirmed, active, exposed to the coming season, and
        # KNOWN to lack stipulation 410. Unknown is never flagged.
        "waiver_missing": dot_embargo.needs_waiver(row, dot_embargo.season_for(today)),
        "how": m.get("how") or row.get("matched_by"),
        "state": dot_sync.match_state(row),
        "link": row.get("link"),
    }


def board(rows: Iterable[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """What GET /dot/permits returns: the project's permits (active, then
    expiring within 14 days, then expired) and the ones waiting for a
    person's "yours?" -- only those whose work has not ended (older pending
    permits are counted, not listed: nothing alerts on them either way)."""
    permits = _permits(rows)
    mine, pending, older = [], [], 0
    for row in permits:
        st = dot_sync.match_state(row)
        if st == dot_sync.STATE_REJECTED:
            continue
        v = permit_view(row, today, permits)
        if st == dot_sync.STATE_NEEDS:
            if v["group"] == "expired":
                older += 1
            else:
                pending.append(v)
            continue
        mine.append(v)

    def _soonest(v):
        return (v["work_end"] or "9999-12-31", str(v["number"]))

    # active and expiring: the soonest end first; expired: the most recent first
    mine = (sorted([v for v in mine if v["group"] == "active"], key=_soonest)
            + sorted([v for v in mine if v["group"] == "expiring"], key=_soonest)
            + sorted([v for v in mine if v["group"] == "expired"], key=_soonest, reverse=True))
    pending.sort(key=lambda v: (v["work_end"] or "9999-12-31", str(v["number"])))
    counts = Counter(v["group"] for v in mine)
    return {"permits": mine, "needs_confirmation": pending,
            "needs_confirmation_older": older,
            "counts": {"active": counts.get("active", 0), "expiring": counts.get("expiring", 0),
                       "expired": counts.get("expired", 0), "needs_confirmation": len(pending)}}


# ── Setup ───────────────────────────────────────────────────────────────────

def empty_setup() -> Dict[str, Any]:
    return {"status": "unset", "permittees": [], "frontages": [], "suggested_at": None,
            "confirmed_by": None, "confirmed_at": None}


def load_setup(raw: Any) -> Dict[str, Any]:
    s = empty_setup()
    if isinstance(raw, dict):
        for k in s:
            if k in raw:
                s[k] = raw[k]
    s["permittees"] = [p for p in s.get("permittees") or [] if isinstance(p, dict)]
    s["frontages"] = [f for f in s.get("frontages") or [] if isinstance(f, dict)]
    if s.get("status") not in ("unset", "suggested", "confirmed"):
        s["status"] = "unset"
    return s


def clean_frontage(body: Dict[str, Any], default_boro: str = "") -> Dict[str, str]:
    """{boro, on, from, to}, normalized. ValueError when it names no borough,
    no on-street or no cross street."""
    raw_boro = str((body or {}).get("boro") or "").strip()
    boro = raw_boro if raw_boro in dot_sync.BORO_NAME else dot_sync.boro_code(raw_boro)
    boro = boro or str(default_boro or "")
    on = dot_sync.norm_street((body or {}).get("on"))
    fr = dot_sync.norm_street((body or {}).get("from"))
    to = dot_sync.norm_street((body or {}).get("to"))
    if boro not in dot_sync.BORO_NAME:
        raise ValueError("borough")
    if not on:
        raise ValueError("on")
    if not fr and not to:
        raise ValueError("cross")
    return {"boro": boro, "on": on, "from": fr, "to": to}


def same_frontage(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """The same segment as stored (exact, normalized; from/to either order)."""
    if str(a.get("boro") or "") != str(b.get("boro") or ""):
        return False
    if dot_sync.norm_street(a.get("on")) != dot_sync.norm_street(b.get("on")):
        return False
    pa = sorted([dot_sync.norm_street(a.get("from")), dot_sync.norm_street(a.get("to"))])
    pb = sorted([dot_sync.norm_street(b.get("from")), dot_sync.norm_street(b.get("to"))])
    return pa == pb


def clean_permittee(name: Any, source: str, seen_on: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    n = " ".join(str(name or "").split())
    norm = dot_sync.norm_permittee(n)
    if not norm:
        return None
    return {"name": n, "norm": norm, "source": source, "seen_on": list(seen_on or [])[:5]}


def _matched_by_address(row: Dict[str, Any]) -> bool:
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    return (m.get("how") or row.get("matched_by")) == dot_sync.MATCH_ADDRESS


def suggest(rows: Iterable[Dict[str, Any]], today: date,
            own_names: Iterable[Any] = ()) -> Dict[str, Any]:
    """Suggestions from the project's address-matched permits issued within
    24 months: {permittees: [{name, norm, count, seen_on, checked}],
    frontages: [{boro, on, from, to, count}], from_permits: n}."""
    since = dot_sync.months_ago(today, SUGGEST_MONTHS)
    own = {dot_sync.norm_permittee(n) for n in own_names or [] if dot_sync.norm_permittee(n)}
    recent = []
    for r in _permits(rows):
        issued = dot_embargo.parse_day(r.get("issue_date"))
        if _matched_by_address(r) and issued is not None and issued >= since:
            recent.append(r)
    names: Dict[str, Counter] = {}
    seen: Dict[str, List[str]] = {}
    for r in recent:
        raw = " ".join(str(r.get("permittee") or "").split())
        n = dot_sync.norm_permittee(raw)
        if not n:
            continue
        names.setdefault(n, Counter())[raw] += 1
        seen.setdefault(n, []).append(str(r.get("number")))
    permittees = [{"name": c.most_common(1)[0][0], "norm": n, "count": sum(c.values()),
                   "seen_on": seen[n][:5], "checked": n in own}
                  for n, c in names.items()]
    permittees.sort(key=lambda p: (-p["count"], p["name"]))
    fronts: List[Dict[str, Any]] = []
    for r in recent:
        seg = r.get("segment")
        if not isinstance(seg, dict):
            continue
        try:
            f = clean_frontage(seg)
        except ValueError:
            continue
        hit = next((x for x in fronts if same_frontage(x, f)), None)
        if hit:
            hit["count"] += 1
        else:
            fronts.append({**f, "count": 1})
    fronts.sort(key=lambda f: (-f["count"], f["on"], f["from"], f["to"]))
    return {"permittees": permittees, "frontages": fronts, "from_permits": len(recent)}


def fallback_frontage(pk: Dict[str, Any], cross_rows: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, Any]:
    """No matched permit yet: the address's on-street, and the cross-street
    pairs DOT has published for it (the grouped request's rows), most used
    first. cross_rows None = the request failed (unknown, not none)."""
    boro, on = str(pk.get("boro") or ""), pk.get("street") or ""
    pairs: List[Dict[str, Any]] = []
    for r in cross_rows or []:
        if not isinstance(r, dict):
            continue
        fr = dot_sync.norm_street(r.get("fromstreetname"))
        to = dot_sync.norm_street(r.get("tostreetname"))
        if not fr and not to:
            continue
        try:
            n = int(str(r.get("count") or r.get("count_1") or "0").split(".")[0])
        except ValueError:
            n = 0
        hit = next((p for p in pairs if sorted([p["from"], p["to"]]) == sorted([fr, to])), None)
        if hit:
            hit["count"] += n
        else:
            pairs.append({"boro": boro, "on": on, "from": fr, "to": to, "count": n})
    pairs.sort(key=lambda p: (-p["count"], p["from"], p["to"]))
    streets = sorted({x for p in pairs for x in (p["from"], p["to"]) if x})
    return {"boro": boro, "boro_name": boro_name(boro), "on": on,
            "cross_read": cross_rows is not None,
            "cross_segments": pairs[:40], "cross_streets": streets[:80]}


def setup_view(setup: Dict[str, Any]) -> Dict[str, Any]:
    s = load_setup(setup)
    return {
        "status": s["status"],
        "permittees": [{"name": p.get("name"), "norm": p.get("norm"), "source": p.get("source"),
                        "seen_on": p.get("seen_on") or []} for p in s["permittees"]],
        "frontages": [{"index": i, "boro": f.get("boro"), "boro_name": boro_name(f.get("boro")),
                       "on": f.get("on"), "from": f.get("from"), "to": f.get("to"),
                       "source": f.get("source"), "suggested_by": f.get("suggested_by"),
                       "suggested_by_name": f.get("suggested_by_name"),
                       "confirmed": f.get("confirmed") is True}
                      for i, f in enumerate(s["frontages"])],
        "suggested_at": s.get("suggested_at"),
        "confirmed_by": s.get("confirmed_by"),
        "confirmed_at": s.get("confirmed_at"),
    }
