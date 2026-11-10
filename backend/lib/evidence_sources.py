"""Every progress source, turned into lib/evidence.py items.

THE RETURN SHAPE (what other lanes consume). `collect(...)` here, and the server
loader `_progress_evidence(project, company_id, start, end)` that feeds it,
return `(items, coverage)`:

  items     a list of lib/evidence.item() dicts, unchanged in shape:
              {kind, claim, source, ref, project_id, node, levels, space, sub,
               on, by, quote, shared, stated_percent, basis, note, said_at,
               candidates}
            `candidates`: levels the record named that the project's frame
            does not hold (or every level, while the frame is unreadable):
            `levels` is then [], place unknown, never a guessed floor.
            `node` is a graph_v1 node id, a lib/work_nodes id, an inspection
            gate id (gate_plumbing_rough ...), or None when the record names
            no kind of work (a check-in, a punch item, a superintendent's
            inspection walk). `levels` are lib/plans/level_suggestion tokens;
            [] means the place is unknown, never "everywhere". `on` is a date
            or None (no date stated: never filled in). `source` names the feed:
              daily_log        reported   in_progress  (a filed crew row)
              photo_index      observed   in_progress  (what a photo shows)
              inspection_reports attested done | failed | in_progress | scheduled
              dob_logs         verified   done         (a DOB sign-off)
              concrete_operations confirmed done | in_progress (a filed pour log)
              punch_items      confirmed  done         (one closed item)
              superintendent_log attested present      (his daily inspection)
              checkins         reported   present      (presence, never progress)
              schedule_file    reported   done | started (the file's actuals)
  coverage  {"window": {"start", "end"}, "by_kind": {kind: n},
             "by_source": {source: n}, "unreadable": [sources not read],
             <source>: {what was read, what made items, what was left out and
             why}}. A source in `unreadable` was not read: its absence of items
             is unknown, never "nothing happened".

THE WINDOW. Day-by-day sources (crew rows, photos, check-ins, the
superintendent's log) give items dated inside [start, end]. Standing records
(pour logs, DOB sign-offs, inspection reports, punch closures, schedule
actuals) give every item up to `end`, and an undated one: a foundation signed
off last month is still signed off. Nothing said after `end` is read.

RULES THAT ARE THE POINT (each has a test, and a mutation of each is caught):
  - A crew row naming several levels is SHARED, never about one of them.
  - A photo gives only the work its description shows, and a level only when
    lib/photo_place says the evidence is sufficient. A photo never says done.
  - Only a VALIDATED inspection result counts: an unresolved row, or one whose
    result was never read back from the words, makes no claim (it is counted).
    A failure stays a failure.
  - A DOB sign-off covers the FILING's scope, building-wide unless the filing's
    `work_on_floor` names levels. Construction fence / sidewalk shed is site
    protection, not progress. A filing with no sign-off makes no claim.
  - A pour log says done only for a structural slab or deck pour at a level it
    names; a partial or topping pour, or one with no level, is in progress.
  - A closed punch item is done for THAT item at its floor and area: node None,
    never the package of work.
  - Check-ins say who was present, never what was built.
  - No percent is computed. A schedule file's stated percent is kept as the
    file's, labelled.

Pure: no database, no network.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import attendance
from lib import dob_signoffs as DS
from lib import evidence as E
from lib import inspection_reports as IR
from lib import photo_place
from lib import progress_report as P
from lib import report_regulatory
from lib import work_nodes
from lib import work_state as W
from lib.plans import level_suggestion as LS
from lib.wa_facts import checkin_company

Item = Dict[str, Any]

# ── SMALL READERS ──────────────────────────────────────────────────────────


def as_day(v: Any) -> Optional[date]:
    """A date from a date, a datetime or an ISO string; None otherwise."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _t(v: Any) -> str:
    return " ".join(str(v or "").split())


def _notes(*bits: Optional[str]) -> Optional[str]:
    kept = [b for b in bits if b]
    return "; ".join(kept) if kept else None


def _filed(log: Dict[str, Any]) -> bool:
    """server.logbook_is_filed's rule (locked, or submitted), and not withdrawn."""
    return (bool(log.get("is_locked")) or str(log.get("status") or "") == "submitted") \
        and str(log.get("status") or "") != "withdrawn" and not log.get("is_deleted")


# ── THE PROJECT'S FRAME (lib/location_binder): every source is bound to it ──
#
# `frame` is server._project_place_frame's {levels, spaces, known, excluded,
# unreadable?}. A level the project does not have, or ANY level while the
# frame could not be read, is not placed: the item's levels are [] and what
# the record named rides along as `candidates` (place unknown, never the
# building's, never a guessed floor). With no frame, or a frame that holds no
# level at all, nothing changes: the words' own reading stands.

def _frame_binds(frame: Optional[Dict[str, Any]]) -> bool:
    return bool(frame) and bool(frame.get("levels") or frame.get("unreadable"))


def bind_levels(levels: Sequence[str], frame: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str], Optional[str]]:
    """(levels kept, candidates, note) for levels a record states outright."""
    levels = [lv for lv in levels or () if lv]
    if not levels or not _frame_binds(frame):
        return list(levels), [], None
    if frame.get("unreadable"):
        return [], sorted(set(levels)), "the project's levels could not be read, so no level is placed"
    have = set(frame.get("levels") or ())
    ground = frame.get("ground_level")
    if LS.GROUND in levels and LS.GROUND not in have and ground in have:
        # The frame says the first floor is at grade with nothing below it.
        levels = sorted({ground if lv == LS.GROUND else lv for lv in levels}, key=LS._sort_key)
    if all(lv in have for lv in levels):
        return list(levels), [], None
    out = sorted(lv for lv in set(levels) if lv not in have)
    return [], sorted(set(levels)), ("names " + ", ".join(W.level_label(lv) for lv in out)
                                     + ", which the project's levels do not include; not placed")


def place_text(text: Any, frame: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str], Optional[str]]:
    """(levels, candidates, note) for a free-text location, read by
    lib/location_binder against the frame. With no frame the words are read
    alone, a unit's digits never taken for its floor ("3B" is not Floor 3)."""
    from lib import location_binder as LB
    if not _frame_binds(frame):
        return W.places_in(LB._units(str(text or ""))[1])["levels"], [], None
    b = LB.bind(text, [] if frame.get("unreadable") else frame.get("levels"), frame.get("spaces"),
                ground_level=frame.get("ground_level"), frame_complete=bool(frame.get("complete")))
    if b["certainty"] != LB.NONE:
        return list(b["levels"]), [], None
    if not b["candidates"]:
        return [], [], None
    why = ("the project's levels could not be read" if frame.get("unreadable")
           else str(b["reason"]).replace("_", " "))
    return [], list(b["candidates"]), f"{why}; not placed"


# ── FILED DAILY-LOG CREW ROWS: reported ────────────────────────────────────

def from_daily_logs(activities: Iterable[Dict[str, Any]], project_id: Any,
                    frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """One item per kind of work per phrase of each filed crew row
    (progress_report._log_activities). Claim in_progress: a crew working on
    something is not the something finished."""
    # `frame`: the project's levels and plan tags (location_binder): a level
    # the job does not have, or words that name none clearly, are not placed.
    rows = W.evidence_rows(activities, frame)
    out: List[Item] = []
    for r in rows:
        shared = len(r["levels"]) > 1
        note = _notes("the log names the trade only, not which part of it" if r["generic"] else None,
                      "filed for several levels together, not one alone" if shared else None,
                      "from an amended log" if r["amended"] else None)
        for node in r["nodes"]:
            out.append(E.item("reported", "in_progress", source="daily_log", ref=f"{r['log_id']}|{r['work']}",
                              project_id=project_id, node=node, levels=r["levels"], space=r["space"],
                              sub=r["sub"] or None, on=r["date"], quote=r["work"], shared=shared, note=note))
    cov = {"phrases": len(rows), "matched": sum(1 for r in rows if r["nodes"]),
           "generic": sum(1 for r in rows if r["generic"]), "no_level": sum(1 for r in rows if not r["levels"]),
           "shared": sum(1 for r in rows if len(r["levels"]) > 1), "items": len(out),
           "not_matched": Counter(r["work"] for r in rows if not r["nodes"]).most_common(15)}
    return out, cov


# ── THE PHOTO INDEX: observed ──────────────────────────────────────────────

def from_photos(index_rows: Iterable[Dict[str, Any]], project_id: Any, *, log_ids: Optional[set] = None,
                spaces: Optional[Dict[str, Dict[str, Any]]] = None,
                confirmations: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """Only the work the DESCRIPTION shows (`seen_nodes`), never the crew row's
    words; a level only when lib/photo_place calls the place sufficient, and
    the project's frame has it."""
    photos = W.photo_rows(index_rows, log_ids, spaces=spaces, confirmations=confirmations, frame=frame)
    out: List[Item] = []
    placed = 0
    for p in photos:
        place = p["place"]
        sufficient = photo_place.is_sufficient(place)
        level = [place["level"]] if sufficient and place.get("level") else []
        level, cands, unbound = bind_levels(level, frame)
        placed += bool(level)
        note = _notes("a photo observes; it never verifies", f"place: {photo_place.how(place)}" if photo_place.how(place) else None,
                      unbound,
                      None if level or not place.get("candidates") else
                      "filed for " + ", ".join(W.level_label(c) for c in place["candidates"]) + "; none chosen")
        for node in p["seen_nodes"]:
            out.append(E.item("observed", "in_progress", source="photo_index", ref=str(p.get("short") or p.get("photo_key")),
                              project_id=project_id, node=node, levels=level, space=place.get("space") if sufficient else None,
                              sub=_t(p.get("sub")) or None, on=as_day(p.get("date")), quote=_t(p.get("description")) or None,
                              note=note, candidates=cands))
    cov = {"photos": len(photos), "shows_known_work": sum(1 for p in photos if p["seen_nodes"]),
           "placed_on_one_level": placed, "items": len(out)}
    return out, cov


# ── INSPECTION REPORTS: attested ───────────────────────────────────────────

_RESULT_CLAIM = {"passed": "done", "failed": "failed", "partial": "in_progress", "scheduled": "scheduled"}


def from_inspections(rows: Iterable[Dict[str, Any]], project_id: Any,
                     frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """A row counts only when its result was read back from the person's own
    words and agreed (`validated_result`, lib/inspection_reports.audit). An
    UNRESOLVED row, or one stored before the check existed, makes no claim."""
    out: List[Item] = []
    cov = Counter()
    for r in rows:
        cov["rows"] += 1
        status = r.get("status")
        if status == IR.UNRESOLVED:
            cov["unresolved"] += 1
            continue
        result = r.get("result")
        if status not in (IR.ATTESTED, IR.DOCUMENT) or result not in _RESULT_CLAIM:
            cov["no_result"] += 1
            continue
        if r.get("validated_result") != result:
            cov["not_validated"] += 1
            continue
        levels, cands, unbound = bind_levels(list(r.get("levels") or []), frame)
        on = as_day(r.get("inspected_on"))
        who = _t(r.get("reporter_name")) or "someone"
        heard = _t(r.get("hearsay_from"))
        said = r.get("created_at") if isinstance(r.get("created_at"), datetime) else None
        # Hearsay ("Joe said it passed") is the sender reporting what someone
        # else said: kept as REPORTED, attributed to the sender, never attested.
        out.append(E.item(
            "reported" if heard else "attested", _RESULT_CLAIM[result], source="inspection_reports",
            ref=str(r.get("_id") or ""),
            project_id=project_id, node=r.get("gate") or None, levels=levels, space=r.get("space") or None,
            on=on, by=who, quote=r.get("quote") or None, shared=len(levels) > 1, said_at=said, candidates=cands,
            note=_notes(f"reported by {who}, not verified", unbound,
                        f"hearsay: {who} reports that {heard} said it" if heard else None,
                        f"{IR.RELAYED_NOTE} (as said: {_t(r.get('relayed_from'))})" if _t(r.get("relayed_from")) else None,
                        f"as said: {r.get('inspection_as_said')}"
                        if r.get("inspection_as_said") else None,
                        "a sign-off document on file, read and not checked against anything"
                        if status == IR.DOCUMENT else None,
                        None if on else "inspection date not stated",
                        "names no inspection step we track" if not r.get("gate") else None)))
        cov["validated"] += 1
        if heard:
            cov["hearsay"] += 1
    cov["items"] = len(out)
    return out, dict(cov)


# ── DOB FILINGS: verified ──────────────────────────────────────────────────
#
# The sign-off vocabulary, read the way PR #1008's lib/dob_signoffs reads it
# (whole phrases, a negator directly before one keeps it open): w9ak-ipjd
# 'LOC Issued' / 'Full Demolition Signed-off', rbx6-tga4 'Signed-off', a
# Certificate of Operation or of Occupancy issued, electrical 'Job is
# complete'. 'QA Review for LOC' is not a sign-off. A stored `signoff_date`
# (PR #1008 adds it) is one too. Both the fields stored today and #1008's are
# read; any of them may be absent.

# The vocabulary is lib/dob_signoffs' (one reader, not two copies).
_STATUS_FIELDS = tuple(DS.STATUS_FIELDS) + tuple(k for k in ("job_status",) if k not in DS.STATUS_FIELDS)
_FILING_FIELDS = ("job_number", "job_filing_number", "job__")


def signoff_words(status: Any) -> bool:
    return DS.is_signed_off(status)


def _signoff_status(row: Dict[str, Any]) -> Optional[str]:
    for k in _STATUS_FIELDS:
        if signoff_words(row.get(k)):
            return _t(row.get(k))
    return None


#: DOB work type (or, when the row carries none, words of the filing's
#: description) -> nodes. Every match counts: "Foundation and earthwork" is two.
_DOB_WORK: Tuple[Tuple["re.Pattern[str]", Tuple[str, ...]], ...] = (
    (re.compile(r"\bdemolition\b", re.I), ("demolition",)),
    (re.compile(r"\bearth\s?work\b", re.I), ("excavation_soe",)),
    (re.compile(r"\bsupport\s+of\s+excavation\b|\bsoe\b", re.I), ("excavation_soe",)),
    (re.compile(r"\bfoundations?\b", re.I), ("foundation",)),
    (re.compile(r"(?<!non-)(?<!non )\bstructural\b", re.I), ("superstructure",)),
    # A plumbing filing's sign-off: DOB does not say which parts, and gas is not assumed.
    (re.compile(r"\bplumbing\b", re.I), ("rough_dwv", "rough_water")),
    (re.compile(r"\bsprinklers?\b", re.I), ("rough_sprinkler",)),
    (re.compile(r"\bstand[\s-]?pipes?\b", re.I), ("standpipe",)),
    # "Protection / mechanical methods" is a different DOB work type.
    (re.compile(r"\bmechanical\b(?!\s+methods\b)", re.I), ("rough_duct",)),
    (re.compile(r"\bfence\b|\bsidewalk\s+sheds?\b", re.I), ("site_protection",)),
)


def dob_nodes(text: Any) -> List[str]:
    out: List[str] = []
    for rx, nodes in _DOB_WORK:
        if rx.search(str(text or "")):
            out += [n for n in nodes if n not in out]
    return out


_DOB_FLOOR = re.compile(r"\bfloor\s+number\(s\)[\s-]*(\d{1,3})\b", re.I)
_DOB_NAMED = ((re.compile(r"\bsub[\s-]?cellar\b", re.I), LS.SUB_CELLAR), (re.compile(r"\bcellar\b", re.I), LS.CELLAR),
              (re.compile(r"\bmezzanine\b", re.I), LS.MEZZANINE), (re.compile(r"\broof\b", re.I), LS.ROOF),
              (re.compile(r"\bbulkhead\b", re.I), LS.BULKHEAD),
              # GROUND, bound to a floor only by a frame that says so (bind_levels).
              (re.compile(r"\bground\s+floor\b", re.I), LS.GROUND))


def dob_levels(work_on_floor: Any) -> List[str]:
    """Levels DOB's `work_on_floor` names ("Floor Number(s)-1-SO-5912-...,
    Mezzanine-4-SO-..., Roof-SO-..."). "Sidewalk" names none."""
    out = set()
    for part in str(work_on_floor or "").split(","):
        m = _DOB_FLOOR.search(part)
        if m and 1 <= int(m.group(1)) <= LS.MAX_SUGGESTED_STORIES:
            out.add(f"{LS.FLOOR_PREFIX}{int(m.group(1))}")
            continue
        for rx, token in _DOB_NAMED:
            if rx.search(part) and not (token == LS.CELLAR and _DOB_NAMED[0][0].search(part)):
                out.add(token)
                break
    return sorted(out)


def _filing(row: Dict[str, Any]) -> str:
    for k in _FILING_FIELDS:
        if _t(row.get(k)):
            return _t(row.get(k)).upper()
    return ""


def _latest(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A permit is a new row per change: the newest row per DOB record is its
    current state."""
    best: Dict[str, Dict[str, Any]] = {}
    for i, r in enumerate(rows):
        key = str(r.get("raw_dob_id") or f"{_filing(r)}|{r.get('work_type') or ''}|{r.get('record_type') or ''}|{i}")
        at = str(r.get("detected_at") or r.get("created_at") or "")
        if key not in best or at >= str(best[key].get("detected_at") or best[key].get("created_at") or ""):
            best[key] = r
    return list(best.values())


def from_dob(rows: Iterable[Dict[str, Any]], project_id: Any, *, bins: Sequence[Any] = (),
             frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """One verified `done` per (signed-off filing, node). Another building's
    rows (report_regulatory.split_by_bin) are left out."""
    kept, excluded, _unverified, _inferred = report_regulatory.split_by_bin(list(rows), bins)
    filings: Dict[str, Dict[str, Any]] = {}
    for r in _latest(x for x in kept if x.get("record_type") in ("permit", "job_status") and _filing(x)):
        f = filings.setdefault(_filing(r), {"rows": [], "status": None, "date": None, "types": [], "desc": [],
                                            "floors": [], "signed": False, "unsigned_types": []})
        f["rows"].append(r)
        said = _signoff_status(r)
        if not (said or as_day(r.get("signoff_date"))):
            # A row that is not itself signed off says nothing about what the
            # sign-off covers: a Sprinkler permit still "Permit Issued" on a
            # filing whose Plumbing permit is signed off is NOT signed off
            # (lib/dob_signoffs reads only signed-off rows the same way).
            f["unsigned_types"] += [x for x in (_t(r.get("work_type")), _t(r.get("work_types"))) if x]
            continue
        f["signed"] = True
        f["status"] = f["status"] or said or "sign-off date on file"
        f["date"] = f["date"] or as_day(r.get("signoff_date"))
        f["types"] += [x for x in (_t(r.get("work_type")), _t(r.get("work_types"))) if x]
        f["desc"] += [_t(r.get("job_description"))] if _t(r.get("job_description")) else []
        f["floors"] += [_t(r.get("work_on_floor"))] if _t(r.get("work_on_floor")) else []
    out: List[Item] = []
    not_signed, unmapped = [], []
    for number, f in sorted(filings.items()):
        if not f["signed"]:
            not_signed.append(number)
            continue
        nodes = dob_nodes(", ".join(f["types"]))
        from_desc = not nodes
        if from_desc:
            nodes = dob_nodes(" ".join(f["desc"]))
        if not nodes:
            unmapped.append({"filing": number, "work": ", ".join(dict.fromkeys(f["types"])) or (f["desc"] or [""])[0]})
            continue
        levels, cands, unbound = bind_levels(sorted({lv for fl in f["floors"] for lv in dob_levels(fl)}), frame)
        floors_said = "; ".join(dict.fromkeys(f["floors"]))
        work = ", ".join(dict.fromkeys(f["types"])) or (f["desc"] or [""])[0]
        scope = (f"DOB lists the filing's work on {', '.join(W.level_label(lv) for lv in levels)}" if levels else
                 f"DOB lists {floors_said}: {unbound}" if cands else
                 "building-wide: the filing names no level" + (f" (DOB lists: {floors_said})" if floors_said else ""))
        for node in nodes:
            out.append(E.item(
                "verified", "done", source="dob_logs", ref=number, project_id=project_id, node=node, levels=levels,
                on=f["date"], quote=f"{f['status']}: {work}", shared=len(levels) > 1, candidates=cands,
                note=_notes(f"DOB sign-off of filing {number}; it covers the filing's scope, {scope}",
                            "work read from the filing's description" if from_desc else None,
                            None if f["date"] else "DOB's sign-off date is not on the stored record",
                            None if work_nodes.is_progress(node) else "site protection, not construction progress")))
    cov = {"rows": len(kept) + len(excluded), "other_building": len(excluded), "filings": len(filings),
           "signed_off": sum(1 for f in filings.values() if f["signed"]), "not_signed_off": not_signed,
           "signed_off_unmapped": unmapped, "items": len(out)}
    return out, cov


# ── CONCRETE OPERATIONS LOGS: confirmed ────────────────────────────────────

_TOPPING = re.compile(r"\btopping\b", re.I)
_PARTIAL = re.compile(r"\bpartial(?:ly)?\b|\bpart\s+of\b|\bportion\b|\bhalf\b|\bsections?\b|\bphase\b"
                      r"|\b\d+\s+of\s+\d+\b|\bbays?\b|\bpour\s+#?\d+\b", re.I)
_SLAB = re.compile(r"\bslabs?\b|\bdecks?\b", re.I)


def pour_claim(location: Any, frame: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], str, List[str]]:
    """(node, claim, levels) for a pour at this location, its levels bound to
    the project's frame (place_text): "3B slab" is a unit's slab, never Floor 3
    done, and a floor the building does not have places nothing."""
    loc = _t(location)
    levels = place_text(loc, frame)[0]
    node = work_nodes.classify(loc)[0]
    kind = node[0] if node else None
    if kind == "foundation":
        return "foundation", "in_progress", levels
    if _SLAB.search(loc) and not _TOPPING.search(loc) and not _PARTIAL.search(loc) and levels:
        return "superstructure", "done", levels
    if _SLAB.search(loc) or kind == "superstructure":
        return "superstructure", "in_progress", levels
    return kind, "in_progress", levels


def from_pours(logbooks: Iterable[Dict[str, Any]], project_id: Any,
               frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """A FILED concrete-operations log (the competent person's): a structural
    slab or deck pour at a level it names is done there; anything else is in
    progress; a location that names no level gives no level."""
    out: List[Item] = []
    cov = Counter()
    for lg in logbooks:
        if lg.get("log_type") != "concrete_operations":
            continue
        cov["logs"] += 1
        if not _filed(lg):
            cov["not_filed"] += 1
            continue
        data = lg.get("data") if isinstance(lg.get("data"), dict) else {}
        loc = _t(data.get("pour_location"))
        if not loc:
            cov["no_location"] += 1
            continue
        node, claim, levels = pour_claim(loc, frame)
        _lv, cands, unbound = place_text(loc, frame)
        cov["no_level"] += not levels
        slumps = [s for s in data.get("slump_tests") or [] if isinstance(s, dict)]
        failed = sum(1 for s in slumps if s.get("pass") is False)
        out.append(E.item(
            "confirmed", claim, source="concrete_operations", ref=str(lg.get("_id") or ""), project_id=project_id,
            node=node, levels=levels, on=as_day(lg.get("date")), by=_t(lg.get("cp_name")) or None, quote=loc,
            shared=len(levels) > 1, candidates=cands,
            note=_notes("a filed concrete operations log", unbound,
                        "a topping pour, not the structural slab" if _TOPPING.search(loc) else None,
                        "a partial pour" if _PARTIAL.search(loc) else None,
                        None if levels or cands else "the pour location names no level",
                        None if node else "the pour location names no kind of work",
                        f"{failed} failed slump test(s) recorded" if failed else None)))
    cov["items"] = len(out)
    return out, dict(cov)


# ── CLOSED PUNCH ITEMS: confirmed ──────────────────────────────────────────

def from_punch(items: Iterable[Dict[str, Any]], project_id: Any,
               frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """An item an admin or PM closed ("P23 ok", lib/punch.super_verdict):
    done for THAT item, at its floor and area. Node None: one punch item is
    never the package of work."""
    out: List[Item] = []
    cov = Counter()
    for it in items:
        cov["items_read"] += 1
        if it.get("status") != "closed" or not it.get("closed_by"):
            continue
        floor = _t(it.get("floor"))
        level = W.level_asked(floor) if floor and floor != "?" else None
        levels, cands, unbound = bind_levels([level] if level else [], frame)
        area = _t(it.get("area"))
        space = area[4:] if area.startswith("Apt ") else (area if area and area != "?" else None)
        assignee = it.get("assignee") if isinstance(it.get("assignee"), dict) else {}
        pid = _t(it.get("pid")) or str(it.get("_id") or "")
        out.append(E.item(
            "confirmed", "done", source="punch_items", ref=pid, project_id=project_id, node=None,
            levels=levels, space=space, sub=_t(assignee.get("company")) or None, candidates=cands,
            on=as_day(it.get("closed_at")), by=str(it.get("closed_by")), quote=_t(it.get("text")) or None,
            note=_notes(f"punch item {pid} closed: this item only, not the package of work", unbound,
                        f"trade: {it.get('trade')}" if _t(it.get("trade")) and it.get("trade") != "?" else None,
                        None if level else "its floor is not on record")))
        cov["closed"] += 1
    cov["items"] = len(out)
    return out, dict(cov)


# ── THE SUPERINTENDENT'S DAILY INSPECTION: attested ────────────────────────

def _inspection_entries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    sec = data.get("daily_inspection")
    if isinstance(sec, dict) and isinstance(sec.get("entries"), list):
        return [e for e in sec["entries"] if isinstance(e, dict)]
    return [sec] if isinstance(sec, dict) else []


def from_superintendent(logbooks: Iterable[Dict[str, Any]], project_id: Any,
                        frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """Item 11 of a filed site superintendent's log (1 RCNY 3301-04(f)): where
    he says he inspected, in his own words. Presence at a place, not progress."""
    out: List[Item] = []
    cov = Counter()
    for lg in logbooks:
        if lg.get("log_type") != "site_superintendent_log":
            continue
        cov["logs"] += 1
        if not _filed(lg):
            cov["not_filed"] += 1
            continue
        data = lg.get("data") if isinstance(lg.get("data"), dict) else {}
        pres = data.get("presence") if isinstance(data.get("presence"), dict) else {}
        who = _t(lg.get("cp_name") or pres.get("printed_name") or lg.get("created_by_name")) or None
        for n, e in enumerate(_inspection_entries(data)):
            loc, result = _t(e.get("location")), _t(e.get("result"))
            if not (loc or result):
                continue
            levels, cands, unbound = place_text(loc, frame)
            out.append(E.item(
                "attested", "present", source="superintendent_log", ref=f"{lg.get('_id') or ''}#{n}", candidates=cands,
                project_id=project_id, levels=levels, on=as_day(e.get("inspected_on")) or as_day(lg.get("date")),
                by=who, quote=" - ".join(x for x in (loc, result) if x), shared=len(levels) > 1,
                note=_notes("the superintendent's daily inspection: where he inspected, not that work is done",
                            unbound, None if levels or cands else "names no single level")))
    cov["items"] = len(out)
    return out, dict(cov)


# ── GATE CHECK-INS: present ────────────────────────────────────────────────

def from_checkins(rows: Iterable[Dict[str, Any]], project_id: Any) -> Tuple[List[Item], Dict[str, Any]]:
    """One item per company per New York day: who was present. Never progress."""
    days: Dict[Tuple[date, str], Dict[str, Any]] = {}
    cov = Counter()
    for r in rows:
        cov["checkins"] += 1
        d = attendance.local_day(r.get("check_in_time"))
        name = checkin_company(r)
        if not d:
            cov["no_time"] += 1
            continue
        if not name or P.is_unassigned(name):
            cov["no_company"] += 1
            continue
        slot = days.setdefault((d, P.company_key(name)), {"name": name, "who": set()})
        slot["who"].add(attendance.worker_key(r))
    out = [E.item("reported", "present", source="checkins", ref=f"{d.isoformat()}|{key}", project_id=project_id,
                  sub=s["name"], on=d, note=f"{len(s['who'])} worker(s) checked in at the gate; presence, not progress")
           for (d, key), s in sorted(days.items())]
    cov["items"] = len(out)
    return out, dict(cov)


# ── A CONFIRMED SCHEDULE FILE'S ACTUALS: reported, by the file ─────────────

def from_schedule(schedule: Optional[Dict[str, Any]], project_id: Any,
                  frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """Activities the confirmed file gives an actual start or finish. The
    file's planned dates are not evidence of work and make no item."""
    out: List[Item] = []
    cov = Counter()
    for a in (schedule or {}).get("activities") or []:
        if a.get("kind") == "summary":
            continue
        cov["activities"] += 1
        fin, start = as_day(a.get("actual_finish")), as_day(a.get("actual_start"))
        if not (fin or start):
            continue
        cov["with_actuals"] += 1
        name = _t(a.get("name"))
        nodes, generic = W.classify(name, name)
        levels, cands, unbound = place_text(name, frame)
        pct = a.get("percent_complete")
        pct = float(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
        note = _notes(f"the schedule file states actual finish {fin.isoformat()}" if fin else
                      f"the schedule file states actual start {start.isoformat()}",
                      f"the schedule file states {pct:g}%" if pct is not None else None,
                      "the activity names the trade only" if generic else None, unbound,
                      None if nodes else "the activity names no kind of work we track")
        for node in nodes or [None]:
            out.append(E.item("reported", "done" if fin else "started", source="schedule_file", ref=str(a.get("id") or name),
                              project_id=project_id, node=node, levels=levels, on=fin or start, quote=name or None,
                              shared=len(levels) > 1, stated_percent=pct, note=note, candidates=cands))
    cov["items"] = len(out)
    return out, dict(cov)


# ── ALL OF THEM ────────────────────────────────────────────────────────────

#: Sources whose items are limited to the window: reported / observed ACTIVITY
#: (and the superintendent's presence walk). Everything else is a STANDING
#: record read without the window: a pour log, a DOB sign-off, a punch
#: closeout, an attested inspection, a schedule actual. A slab poured Jul 1 is
#: still poured in November; leaving it out would read as "no done marker".
DAILY_SOURCES = ("daily_log", "photo_index", "checkins", "superintendent_log")

#: The name coverage["unreadable"] gives the project's level frame when
#: server._project_place_frame could not read it.
FRAME_UNREADABLE = "place_frame"


def frame_state(frame: Optional[Dict[str, Any]]) -> str:
    """How the levels were bound: "frame unreadable" (the read failed: nothing
    placed), "known" (the project or its plans name levels), "logs only",
    "unknown" (no level known: the words read alone), "not given"."""
    if frame is None:
        return "not given"
    if frame.get("unreadable"):
        return "frame unreadable"
    if frame.get("known"):
        return "known"
    return "logs only" if frame.get("levels") else "unknown"


def in_window(i: Item, start: Optional[date], end: Optional[date]) -> bool:
    """Nothing dated after `end`, and nothing SAID after it (a report for a
    past period does not know what was said later); the window's start limits
    only the day-by-day sources."""
    said = i.get("said_at")
    if end and isinstance(said, datetime) and (attendance.local_day(said) or said.date()) > end:
        return False
    on = i["on"] if isinstance(i["on"], date) else None
    if on is None:
        return i["source"] not in DAILY_SOURCES
    if end and on > end:
        return False
    return not (start and i["source"] in DAILY_SOURCES and on < start)


def collect(project_id: Any, *, start: Optional[date] = None, end: Optional[date] = None,
            activities: Iterable[Dict[str, Any]] = (), photo_index: Iterable[Dict[str, Any]] = (),
            log_ids: Optional[set] = None, spaces: Optional[Dict[str, Dict[str, Any]]] = None,
            confirmations: Optional[Dict[str, List[Dict[str, Any]]]] = None,
            inspections: Iterable[Dict[str, Any]] = (), dob_rows: Iterable[Dict[str, Any]] = (),
            bins: Sequence[Any] = (), logbooks: Iterable[Dict[str, Any]] = (),
            punch_items: Iterable[Dict[str, Any]] = (), checkins: Iterable[Dict[str, Any]] = (),
            schedule: Optional[Dict[str, Any]] = None, unreadable: Sequence[str] = (),
            frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Item], Dict[str, Any]]:
    """(items, coverage): see the module docstring."""
    books = list(logbooks)
    parts = (("daily_log", from_daily_logs(activities, project_id, frame)),
             ("photo_index", from_photos(photo_index, project_id, log_ids=log_ids, spaces=spaces,
                                         confirmations=confirmations, frame=frame)),
             ("inspection_reports", from_inspections(inspections, project_id, frame)),
             ("dob_logs", from_dob(dob_rows, project_id, bins=bins, frame=frame)),
             ("concrete_operations", from_pours(books, project_id, frame)),
             ("punch_items", from_punch(punch_items, project_id, frame)),
             ("superintendent_log", from_superintendent(books, project_id, frame)),
             ("checkins", from_checkins(checkins, project_id)),
             ("schedule_file", from_schedule(schedule, project_id, frame)))
    items: List[Item] = []
    gone = set(unreadable)
    if frame and frame.get("unreadable"):
        gone.add(FRAME_UNREADABLE)
    coverage: Dict[str, Any] = {"window": {"start": start, "end": end}, "unreadable": sorted(gone),
                                "frame": frame_state(frame)}
    for name, (got, cov) in parts:
        kept = [i for i in got if in_window(i, start, end)]
        cov = dict(cov)
        cov["outside_window"] = len(got) - len(kept)
        coverage[name] = cov
        items += kept
    coverage["schedule_file"]["confirmed_file"] = bool(schedule)
    coverage["by_kind"] = dict(Counter(i["kind"] for i in items))
    coverage["by_source"] = dict(Counter(i["source"] for i in items))
    return items, coverage
