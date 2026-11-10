"""DOB NOW: Inspections (the public Accela Citizen Access portal) read into
evidence. Pure: no network, no database.

THE MISS THIS EXISTS FOR (588 Thomas S Boyland St, verified by hand on
2026-11-10). The portal at a810-lmpaca.nyc.gov/CitizenAccessBuildings holds the
job's plumbing results, and LeveLog said they were "not in public data":

  1. The completed-inspection list is filled by an ASP.NET ASYNC POSTBACK that
     the page fires on load. A plain GET returns the literal placeholder
     "There are no completed inspections on this record." for EVERY record,
     including ones with results. The placeholder was read as a negative.
     So: a STATIC page never yields a checked list (`loaded` False, "not
     checked"); only the async delta (parse_inspection_list) can say a list
     was read, and only the delta can say it is empty.
  2. The per-floor results live in another section ("Application Information
     Table" / "PL FLOOR RESULTS"). parse_record reads every "* FLOOR RESULTS"
     table generically.
  3. Records are split across the site's BINs (588: current 3430621 and the
     demolished house's 3255362); lib/dob_now_portal searches every BIN.

WHAT A RESULT IS WORTH (lib/evidence.py's ladder):
  - a DOB inspector's Pass (list or spot check)  -> verified done, dated.
  - Fail / Disapproved / Not accepted            -> verified FAILED. A failure
                                                    never becomes a pass.
  - Certified (a licensed master plumber's self-certification under an
    advance notice)                              -> CONFIRMED done, not
                                                    verified. A DOB spot check
                                                    Pass on the same notice is
                                                    a separate verified item.
  - a floor-results table cell                   -> UNDATED (`on` None): the
                                                    table carries no date. A
                                                    cell is dated only by an
                                                    inspection's own comment
                                                    naming it, and then the
                                                    item says it is a LINK
                                                    INFERENCE and its basis.
  "Pass-Final" means the inspection is resulted. NONE of this is a plumbing
  sign-off, and none satisfies TR1 special inspections, electrical, sprinkler
  or fire alarm: only plumbing nodes are ever produced.

PRIVACY. Person names, phones and emails are never kept: not the owner, not a
contact, not a licensed professional's name. A licensed FIRM name is kept. A
request comment keeps its first line only (the lines after it are who will
meet the inspector, with phone numbers), scrubbed of phones and emails.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import evidence as E
from lib.plans import level_suggestion as LS

SOURCE = "dob_now_inspections"
LABEL = "DOB NOW: Inspections"
PORTAL = "a810-lmpaca.nyc.gov/CitizenAccessBuildings"

#: The gate a rough plumbing result passes (graph_v1's, per level).
PLUMBING_ROUGH = "gate_plumbing_rough"
#: Underground plumbing (water/sanitary, storm drainage below the slab). Not a
#: node of the progress frame: kept as its own name so it is never merged into
#: rough or into site utilities.
PLUMBING_UNDERGROUND = "plumbing_underground"
PLUMBING_NODES = (PLUMBING_ROUGH, PLUMBING_UNDERGROUND)

PLACEHOLDER_COMPLETED = "There are no completed inspections on this record."
NOT_LOADED_STATIC = ("not checked: a static page does not hold the inspection list (the portal fills it by an "
                     "async postback on load); its placeholder is not a result")
NOT_SIGNOFF = "not a plumbing sign-off"
NOT_OTHER_TRADES = ("none of these is a plumbing sign-off, and none covers TR1 special inspections, electrical "
                    "(DOB NOW: Inspections Plus), sprinkler or fire alarm")

_PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ERROR = re.compile(r"experiencing technical difficulties|/Error\.aspx", re.I)
#: A Cloudflare interstitial. NOT the bot-management script every normal page
#: carries (/cdn-cgi/challenge-platform/scripts/...): that is no challenge.
_CHALLENGE = re.compile(r"<title>\s*Just a moment\.\.\.|_cf_chl_opt|Attention Required! \| Cloudflare", re.I)


# ── SMALL READERS ──────────────────────────────────────────────────────────

def _text(fragment: Any) -> str:
    """Visible text of an HTML fragment, whitespace collapsed."""
    t = re.sub(r"<br\s*/?>", "\n", str(fragment or ""), flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    return " ".join(t.split())


def _lines(fragment: Any) -> List[str]:
    t = re.sub(r"<br\s*/?>", "\n", str(fragment or ""), flags=re.I)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return [" ".join(x.split()) for x in t.splitlines() if x.strip()]


def scrub(text: Any) -> str:
    """No phone number and no email address survives."""
    return " ".join(_EMAIL.sub("[email removed]", _PHONE.sub("[phone removed]", str(text or ""))).split())


def us_date(v: Any) -> Optional[str]:
    """'07/15/2026' -> '2026-07-15'; None when it is not a date."""
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _at(day: str, clock: str) -> Optional[str]:
    """'11/05/2026', '10:20 AM' -> '2026-11-05T10:20'."""
    d = us_date(day)
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AP]M)", str(clock or ""), re.I)
    if not d:
        return None
    if not m:
        return d
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return f"{d}T{h:02d}:{m.group(2)}"


def page_problem(text: Any) -> Optional[str]:
    """'technical_difficulties' | 'challenge' | None. A page that is either is
    UNREACHABLE: never read as a record, never as 'none'."""
    s = str(text or "")
    if _CHALLENGE.search(s):
        return "challenge"
    if _ERROR.search(s):
        return "technical_difficulties"
    return None


# ── THE STATIC RECORD PAGE ─────────────────────────────────────────────────

_TITLE = re.compile(r"class=['\"][^'\"]*ACA_Title_Text[^'\"]*['\"][^>]*>(.*?)</div>", re.S)
_LABEL = re.compile(r"<span class=['\"]ACA_SmLabelBolder font11px['\"]>(.*?)</span>", re.S)
_VALUE = re.compile(r"<span class=['\"]ACA_SmLabel ACA_SmLabel_FontSize['\"]>(.*?)</span>", re.S)
_TOKEN = re.compile(r"(?P<title>class=['\"][^'\"]*ACA_Title_Text[^'\"]*['\"][^>]*>(?P<t>.*?)</div>)"
                    r"|(?P<label><span class=['\"]ACA_SmLabelBolder font11px['\"]>(?P<l>.*?)</span>)"
                    r"|(?P<value><span class=['\"]ACA_SmLabel ACA_SmLabel_FontSize['\"]>(?P<v>.*?)</span>)", re.S)


def _between(s: str, start: str, *ends: str) -> str:
    """From `start` to the FIRST of `ends` after it (or the end of the text)."""
    i = s.find(start)
    if i < 0:
        return ""
    found = [j for j in (s.find(e, i + len(start)) for e in ends) if j > 0]
    return s[i:min(found)] if found else s[i:]


def _key(label: str) -> str:
    return _text(label).rstrip(":").strip()


def _sections(fragment: str) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """[(title, [(label, raw value html)])] in page order."""
    out: List[Tuple[str, List[Tuple[str, str]]]] = []
    label: Optional[str] = None
    for m in _TOKEN.finditer(fragment or ""):
        if m.group("title"):
            out.append((_text(m.group("t")), []))
            label = None
        elif m.group("label"):
            label = _key(m.group("l"))
        elif m.group("value") and label is not None:
            if not out:
                out.append(("", []))
            out[-1][1].append((label, m.group("v")))
            label = None
    return out


def _rows(pairs: Sequence[Tuple[str, str]]) -> List[Dict[str, str]]:
    """A repeating table: a new row starts when a label repeats."""
    rows: List[Dict[str, str]] = []
    for label, raw in pairs:
        if not rows or label in rows[-1]:
            rows.append({})
        rows[-1][label] = raw
    return rows


def _comment(raw: str) -> Optional[str]:
    """A request comment's first line, scrubbed: the rest names who meets the
    inspector, with phone numbers."""
    first = next(iter(_lines(raw)), "")
    return scrub(first) or None


_BUSINESS = re.compile(r"\b(?:INC|LLC|L\.L\.C|CORP|CORPORATION|CO|COMPANY|LTD|DPC|PLLC|PC|LLP|SVCS|SERVICES?|GROUP|"
                       r"ENTERPRISES?|CONSTRUCTION|CONTRACTING|PLUMBING|PIPING|HEATING|ELECTRIC(?:AL)?|ENGINEERING|"
                       r"ARCHITECTS?|ASSOCIATES|INSPECTION|MECHANICAL|SPRINKLER|DEVELOPMENT)\b|&", re.I)


def _firm(s: str) -> Optional[str]:
    """The licensed professional's FIRM (the line after the person's name).
    The person's name is never kept."""
    m = re.search(r"id=['\"]tbl_licensedps['\"].*?<td class=['\"]td_child_left['\"]></td><td>(.*?)</td>", s, re.S)
    if not m:
        return None
    lines = _lines(m.group(1))
    if len(lines) < 2 or _PHONE.search(lines[1]):
        return None
    firm = re.sub(r"\s+\d{4,}\s*$", "", scrub(lines[1])).strip()
    # The second line is the business only when it says so: an electrician's
    # block can carry a second PERSON name there ("RICHARD NEU 003052").
    return firm if _BUSINESS.search(firm) else None


def _record_id(s: str) -> Optional[str]:
    m = re.search(r'id="ctl00_PlaceHolderMain_lblPermitNumber"[^>]*>([^<]*)<', s)
    return _text(m.group(1)) if m else None


def _record_type(s: str) -> Optional[str]:
    m = re.search(r'id="ctl00_PlaceHolderMain_lblPermitType"[^>]*>([^<]*)<', s)
    return _text(m.group(1)) if m else None


def _status(s: str) -> Optional[str]:
    m = re.search(r'id="ctl00_PlaceHolderMain_lblRecordStatus"[^>]*>(.*?)</span>', s, re.S)
    return _text(m.group(1)) or None if m else None


def static_list_state(s: str) -> Dict[str, Any]:
    """What a STATIC page says about the inspection list: never loaded. The
    placeholder is recorded as seen, and is not a result."""
    return {"loaded": False, "why": NOT_LOADED_STATIC, "placeholder_seen": PLACEHOLDER_COMPLETED in _html.unescape(s)}


def parse_record(static_html: Any) -> Dict[str, Any]:
    """One record's static CapDetail page:

      {record_id, record_type, status, opened, proposed_job_start, expiration,
       job_description, work_floors: [..], licensed_firm, bins: [..],
       fields: {label: value} (Application Information, flat),
       tables: {title: [{label: value}]} (Application Information Table),
       floor_results: {title: {floor: {test: result}}} for every
                      '* FLOOR RESULTS' table,
       request: {date, time} | None, advance_notice: [{inspection_type, floor,
       request_comment}], advance_notice_results: [{id, inspection_type,
       scheduled, floor, result}], inspection_list: {loaded: False, ..},
       problem: None | 'technical_difficulties' | 'challenge'}

    No person name, phone or email is kept."""
    s = str(static_html or "")
    problem = page_problem(s)
    out: Dict[str, Any] = {"record_id": _record_id(s), "record_type": _record_type(s), "status": _status(s),
                           "opened": None, "proposed_job_start": None, "expiration": None, "job_description": None,
                           "work_floors": [], "licensed_firm": None, "bins": [], "fields": {}, "tables": {},
                           "floor_results": {}, "request": None, "advance_notice": [], "advance_notice_results": [],
                           "inspection_list": static_list_state(s), "problem": problem}
    if problem and not out["record_id"]:
        return out
    out["licensed_firm"] = _firm(s)
    jd = re.search(r"Job Description:.*?<td class=['\"]td_child_left font12px['\"]></td><td>(.*?)</td>", s, re.S)
    out["job_description"] = scrub(_text(jd.group(1))) or None if jd else None
    out["bins"] = sorted(set(re.findall(r"<h2>BIN:</h2><div class=['\"]ACA_SmLabel ACA_SmLabel_FontSize['\"]>\s*(\d{7})", s)))
    asi = _between(s, 'id="ctl00_PlaceHolderMain_PermitDetailList1_lblASIList"',
                   'id="ctl00_PlaceHolderMain_PermitDetailList1_tbASITList"',
                   'id="ctl00_PlaceHolderMain_PermitDetailList1_lblASITableList"',
                   'id="ctl00_PlaceHolderMain_PermitDetailList1_tbParcelList"',
                   'id="ctl00_PlaceHolderMain_PermitDetailList1_palParceList"')
    asit = _between(s, 'id="ctl00_PlaceHolderMain_PermitDetailList1_lblASITableList"',
                    'id="ctl00_PlaceHolderMain_PermitDetailList1_tbParcelList"',
                    'id="ctl00_PlaceHolderMain_PermitDetailList1_palParceList"')
    fields: Dict[str, str] = {}
    for title, pairs in _sections(asi):
        if "AFFIRMATION" in title.upper():
            continue
        for label, raw in pairs:
            if "affirm" in label.lower() or len(label) > 80:
                continue
            fields[label] = scrub(_text(raw))
    out["fields"] = fields
    out["opened"] = us_date(fields.get("Opened") or fields.get("Opened Date") or fields.get("Date Opened"))
    out["proposed_job_start"] = us_date(fields.get("Proposed Job Start Date"))
    out["expiration"] = us_date(fields.get("Expiration Date"))
    wf = fields.get("Work on Floor(s)") or ""
    out["work_floors"] = [p.strip() for p in wf.split(",") if p.strip()]
    if "REQUEST DATE AND TIME" in {t.upper() for t, _ in _sections(asi)} or fields.get("Start Time"):
        out["request"] = {"date": us_date(fields.get("Date")), "time": fields.get("Start Time") or None,
                          "at": _at(fields.get("Date") or "", fields.get("Start Time") or "")}
    for title, pairs in _sections(asit):
        rows = _rows(pairs)
        clean = []
        for r in rows:
            clean.append({k: (_comment(v) if k.lower().startswith("request comment") else scrub(_text(v)))
                          for k, v in r.items()})
        out["tables"][title] = clean
        if re.search(r"FLOOR RESULTS\s*$", title, re.I):
            table: Dict[str, Dict[str, str]] = {}
            for r in clean:
                floor = r.get("FLOOR") or r.get("Floor")
                if not floor:
                    continue
                cells = table.setdefault(floor, {})
                for k, v in r.items():
                    if k.upper() != "FLOOR" and v:
                        cells[k] = v
            out["floor_results"][title] = table
        elif "ADVANCE NOTICE" in title.upper():
            for r in clean:
                if r.get("Result") or r.get("ID"):
                    out["advance_notice_results"].append({
                        "id": r.get("ID"), "inspection_type": r.get("Inspection Type"),
                        "scheduled": us_date(r.get("Scheduled Date")), "floor": r.get("Floor"),
                        "result": r.get("Result")})
                elif r.get("Inspection Type"):
                    out["advance_notice"].append({"inspection_type": r.get("Inspection Type"), "floor": r.get("Floor"),
                                                  "request_comment": r.get("Request Comments")})
    return out


# ── THE ASYNC DELTA (the inspection list, as the browser receives it) ──────

def delta_segments(text: Any) -> List[Tuple[str, str, str]]:
    """ASP.NET AJAX delta 'len|type|id|content|...' -> [(type, id, content)].
    Raises ValueError when the text is not a delta."""
    s = str(text or "")
    out, i = [], 0
    while i < len(s):
        j = s.index("|", i)
        n = int(s[i:j])
        k = s.index("|", j + 1)
        l = s.index("|", k + 1)
        out.append((s[j + 1:k], s[k + 1:l], s[l + 1:l + 1 + n]))
        i = l + 1 + n + 1
    return out


_SPANS = re.compile(r"<SPAN[^>]*>(.*?)</SPAN>", re.S | re.I)


def outcome(result: Any) -> str:
    """'pass' | 'fail' | 'certified' | 'other' from the portal's result words.
    A failure is read first: 'Not Passed' is a fail."""
    r = _text(result).lower()
    if re.search(r"\b(?:fail(?:ed|s)?|disapproved?|rejected|not\s+(?:approved|accepted|passed)|violation)\b", r):
        return "fail"
    if re.search(r"\bcertif(?:ied|ication)\b", r):
        return "certified"
    if re.search(r"\bpass(?:ed)?\b|\bapproved\b|\baccepted\b", r):
        return "pass"
    return "other"


def _list_rows(panel: str, grid: str) -> List[Dict[str, Any]]:
    m = re.search(rf'id="ctl00_PlaceHolderMain_InspectionList_{grid}"(.*?)</table>\s*</div>', panel, re.S)
    if not m:
        return []
    rows = []
    for r in re.findall(r'<tr class="InspectionListRow">(.*?)</td>\s*</tr>', m.group(1), re.S):
        spans = [_text(x) for x in _SPANS.findall(r)]
        if len(spans) < 2:
            continue
        result = spans[0]
        tm = re.match(r"(.*)\((\d+)\)\s*$", spans[1])
        typ, ident = (tm.group(1).strip(), tm.group(2)) if tm else (spans[1], None)
        when = next((x for x in spans[2:] if re.search(r"\d{1,2}/\d{1,2}/\d{4}", x)), "")
        dm = re.search(r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+at\s+(\d{1,2}:\d{2}\s*[AP]M))?", when, re.I)
        spot = bool(re.match(r"\s*spot\s+check\b", result, re.I))
        base = re.sub(r"^\s*spot\s+check\s*-\s*", "", result, flags=re.I)
        rows.append({"id": ident, "type": typ, "result": result, "outcome": outcome(base),
                     "final": bool(re.search(r"-\s*final\b", base, re.I)), "spot_check": spot,
                     "resulted_at": _at(dm.group(1), dm.group(2) or "") if dm else None, "when_said": when or None})
    return rows


def parse_inspection_list(async_delta_text: Any) -> Dict[str, Any]:
    """The inspection list from the on-load async postback's delta:
    {loaded: True, completed: [{id, type, result, outcome, final, spot_check,
    resulted_at}], upcoming: [...]}. Anything that is not that delta -- a
    static page, an error page, a challenge, a redirect -- is NOT loaded
    (`loaded` False with `why`): never an empty checked list."""
    s = str(async_delta_text or "")
    problem = page_problem(s)
    try:
        segs = delta_segments(s)
    except (ValueError, IndexError):
        return {"loaded": False, "why": problem or "not an async postback delta (a static page's placeholder is "
                                                      "not a result)", "completed": [], "upcoming": []}
    kinds = {t for t, _i, _c in segs}
    if "error" in kinds or "pageRedirect" in kinds:
        return {"loaded": False, "why": "the portal answered the postback with an error or a redirect",
                "completed": [], "upcoming": []}
    panel = next((c for t, i, c in segs if t == "updatePanel" and i.endswith("inspectionUpdatePanel")), None)
    if panel is None:
        return {"loaded": False, "why": problem or "the delta holds no inspection list", "completed": [], "upcoming": []}
    completed = _list_rows(panel, "gvListCompleted")
    upcoming = _list_rows(panel, "gvListUpcoming")
    count = re.search(r"Completed Inspections:(?:</FONT>)?\s*\((\d+)\)", panel)
    return {"loaded": True, "completed": completed, "upcoming": upcoming,
            "stated_count": int(count.group(1)) if count else (0 if PLACEHOLDER_COMPLETED in panel else None)}


# ── TO EVIDENCE ────────────────────────────────────────────────────────────

_FLOOR_NUM = re.compile(r"^0*(\d{1,3})$")
_NAMED_FLOORS = {"MEZ": LS.MEZZANINE, "MEZZ": LS.MEZZANINE, "ROF": LS.ROOF, "ROOF": LS.ROOF, "CEL": LS.CELLAR,
                 "CELLAR": LS.CELLAR, "SCL": LS.SUB_CELLAR, "BLK": LS.BULKHEAD, "BUL": LS.BULKHEAD}
#: Floor codes that name no level of the building.
_NOT_A_LEVEL = {"OSP": "OSP is the open space (site), not a floor",
                "UDG": "UDG is underground, which names no single level"}


def level_of(code: Any) -> Tuple[List[str], Optional[str]]:
    """(levels, note) for a DOB NOW floor code: '001' -> FLOOR_1, MEZ, ROF;
    OSP (open space / site) and UDG (underground) name no level."""
    c = _text(code).upper()
    m = _FLOOR_NUM.match(c)
    if m and 1 <= int(m.group(1)) <= LS.MAX_SUGGESTED_STORIES:
        return [f"{LS.FLOOR_PREFIX}{int(m.group(1))}"], None
    if c in _NAMED_FLOORS:
        return [_NAMED_FLOORS[c]], None
    if c in _NOT_A_LEVEL:
        return [], _NOT_A_LEVEL[c]
    return [], f"floor code {c or '(blank)'} names no level we read"


_PLUMBING_WORDS = re.compile(r"\bPL\b|plumb|water\s+and\s+sanitary|\bWS\b|sanitary|storm|\bST\s+DRN\b|\bgas\b", re.I)


def test_node(test: Any, table_title: Any = "PL FLOOR RESULTS") -> Optional[str]:
    """The node a floor-table test or an inspection type names, conservatively:
    a plumbing ROUGH test -> the plumbing rough gate; a plumbing UNDERGROUND
    test -> underground plumbing; anything else (another trade, an unnamed
    floors inspection) -> None."""
    t = f"{_text(table_title)} {_text(test)}"
    if not _PLUMBING_WORDS.search(t):
        return None
    if re.search(r"\bund(?:er)?\s*gr(?:ou)?nd\b|\bunderground\b", t, re.I):
        return PLUMBING_UNDERGROUND
    if re.search(r"\brough\b", t, re.I):
        return PLUMBING_ROUGH
    return None


_KIND_WORDS = (("WS", re.compile(r"\bw/?s\b|\bwater\b", re.I)), ("ST DRN", re.compile(r"\bstorm\b|\bst\s*drn\b", re.I)),
               ("GAS", re.compile(r"\bgas\b", re.I)))


def _day(iso: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return None


def link_for(floor: str, test: str, result: str, linking: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The completed inspection whose OWN comment names this cell's work as
    passed, or None. A rough cell is linked by a comment naming its kind
    (W/S, storm, gas) and 'rough' and 'pass'; an OSP cell by a comment naming
    OSP and 'pass'. Only a passed cell is linked to a passing inspection."""
    if outcome(result) != "pass":
        return None
    for ins in linking:
        c = ins.get("comment") or ""
        if ins.get("outcome") != "pass" or not re.search(r"\bpass(?:ed)?\b", c, re.I):
            continue
        if floor.upper() == "OSP":
            if re.search(r"\bOSP\b", c):
                return ins
            continue
        if "ROUGH" not in test.upper() or not re.search(r"\brough\b", c, re.I):
            continue
        kind = next((rx for name, rx in _KIND_WORDS if test.upper().startswith(name)), None)
        if kind is not None and kind.search(c):
            return ins
    return None


def _bind(levels: List[str], frame: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str], Optional[str]]:
    from lib import evidence_sources as ES
    return ES.bind_levels(levels, frame)


def _join(*bits: Optional[str]) -> str:
    return "; ".join(b for b in bits if b)


def to_evidence(records: Iterable[Dict[str, Any]], project_id: Any, *,
                comments: Optional[Dict[str, str]] = None,
                frame: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(items, coverage) from portal records: [{"record": parse_record(..),
    "inspections": parse_inspection_list(..) | None}]. `comments`: an
    inspection's own result comment by inspection id (read from its details
    page), used ONLY to link an undated floor-table cell to that inspection's
    date, marked as a link inference."""
    comments = {str(k): str(v) for k, v in (comments or {}).items()}
    out: List[Dict[str, Any]] = []
    cov: Dict[str, Any] = {"records": 0, "lists_loaded": 0, "lists_not_loaded": [], "floor_cells": 0,
                           "no_claim": [], "linked_cells": 0, "items": 0}
    for entry in records or ():
        rec = entry.get("record") or {}
        rid = rec.get("record_id") or entry.get("record_id") or "?"
        cov["records"] += 1
        lst = entry.get("inspections") or {"loaded": False, "why": "not fetched"}
        completed = list(lst.get("completed") or []) if lst.get("loaded") else []
        if lst.get("loaded"):
            cov["lists_loaded"] += 1
        else:
            cov["lists_not_loaded"].append(rid)
        linking = [dict(c, comment=comments.get(str(c.get("id")), "")) for c in completed]

        # 1. Floor-results tables: undated, per floor.
        for title, table in (rec.get("floor_results") or {}).items():
            for floor, cells in table.items():
                lv, why_not = level_of(floor)
                levels, cands, unbound = _bind(lv, frame)
                for test, result in cells.items():
                    cov["floor_cells"] += 1
                    o = outcome(result)
                    if o == "other":
                        cov["no_claim"].append(f"{rid} {floor} {test}: {result}")
                        continue
                    kind = "confirmed" if o == "certified" else "verified"
                    claim = "failed" if o == "fail" else "done"
                    link = link_for(floor, test, result, linking)
                    on, basis = None, None
                    if link:
                        on = _day(link.get("resulted_at"))
                        basis = (f"link inference: inspection {link.get('id')} ({link.get('type')}) resulted "
                                 f"{link.get('resulted_at')} with the comment \"{scrub(link.get('comment'))}\"; "
                                 "the floor table itself carries no date")
                        cov["linked_cells"] += 1
                    out.append(E.item(
                        kind, claim, source=SOURCE, ref=f"{rid}|{title}|{floor}|{test}", project_id=project_id,
                        node=test_node(test, title), levels=levels, candidates=cands, on=on,
                        space="open space (site)" if floor.upper() == "OSP" else None,
                        by="licensed master plumber (self-certification)" if o == "certified" else "DOB",
                        quote=f"{title}: floor {floor}, {test}: {result}", basis=basis,
                        note=_join(f"{LABEL} record {rid}, floor-results table",
                                   None if on else "undated: the floor table carries no date",
                                   "a self-certification, not a DOB inspection" if o == "certified" else None,
                                   why_not, unbound, NOT_SIGNOFF)))

        # 2. The loaded completed-inspection list.
        notice = rec.get("advance_notice") or []
        for c in completed:
            o = c.get("outcome")
            if o == "other":
                cov["no_claim"].append(f"{rid} {c.get('id')}: {c.get('result')}")
                continue
            day = _day(c.get("resulted_at"))
            comment = comments.get(str(c.get("id")), "")
            said = f"{c.get('type')} ({c.get('id')}): {c.get('result')}"
            final = "'Final' means the inspection is resulted" if c.get("final") else None
            if c.get("spot_check") and notice:
                # A DOB spot check of the notice's self-certified inspections.
                for n in notice:
                    lv, why_not = level_of(n.get("floor"))
                    levels, cands, unbound = _bind(lv, frame)
                    out.append(E.item(
                        "verified", "failed" if o == "fail" else "done", source=SOURCE,
                        ref=f"{rid}|{c.get('id')}|{n.get('inspection_type')}", project_id=project_id,
                        node=test_node(n.get("inspection_type"), rec.get("record_type") or ""), levels=levels,
                        candidates=cands, on=day, by="DOB (spot check)", quote=said,
                        note=_join(f"{LABEL} record {rid}: DOB spot check of the advance-notice inspection "
                                   f"{n.get('inspection_type')}, floor {n.get('floor')}", final, why_not, unbound,
                                   NOT_SIGNOFF)))
                continue
            node = test_node(c.get("type"), rec.get("record_type") or "")
            basis = None
            if node is None and _PLUMBING_WORDS.search(f"{rec.get('record_type') or ''} {c.get('type') or ''}") \
                    and re.search(r"\brough\b", comment, re.I) and o == "pass":
                node = PLUMBING_ROUGH
                basis = f"the inspection's own comment names rough work: \"{scrub(comment)}\""
            kind = "confirmed" if o == "certified" else "verified"
            out.append(E.item(
                kind, "failed" if o == "fail" else "done", source=SOURCE, ref=f"{rid}|{c.get('id')}",
                project_id=project_id, node=node, levels=[], on=day, basis=basis,
                by="licensed master plumber (self-certification)" if o == "certified" else "DOB inspector",
                quote=said,
                note=_join(f"{LABEL} record {rid}", final,
                           "a self-certification, not a DOB inspection" if o == "certified" else None,
                           "the list names no floor", NOT_SIGNOFF)))

        # 3. Self-certification results filed on a CERT-ADV record.
        for r in rec.get("advance_notice_results") or []:
            o = outcome(r.get("result"))
            if o == "other":
                cov["no_claim"].append(f"{rid} {r.get('id')}: {r.get('result')}")
                continue
            lv, why_not = level_of(r.get("floor"))
            levels, cands, unbound = _bind(lv, frame)
            out.append(E.item(
                "confirmed" if o in ("certified", "pass") else "verified", "failed" if o == "fail" else "done",
                source=SOURCE, ref=f"{rid}|{r.get('id')}", project_id=project_id,
                node=test_node(r.get("inspection_type"), "PL"), levels=levels, candidates=cands,
                on=_day(r.get("scheduled")), by="licensed master plumber (self-certification)",
                quote=f"{r.get('inspection_type')} ({r.get('id')}), floor {r.get('floor')}: {r.get('result')}",
                note=_join(f"{LABEL} record {rid}: self-certification results filed on the advance notice; "
                           "not a DOB inspection", why_not, unbound, NOT_SIGNOFF)))
    cov["items"] = len(out)
    return out, cov


# ── THE ANSWER ─────────────────────────────────────────────────────────────

def _when(iso: Any) -> str:
    if isinstance(iso, datetime):
        return iso.strftime("%Y-%m-%d %H:%M UTC") if iso.tzinfo else iso.strftime("%Y-%m-%d %H:%M")
    s = str(iso or "")
    return s.replace("T", " ") if s else "date not shown"


def _floor_words(table: Dict[str, Dict[str, str]]) -> List[str]:
    out = []
    for floor, cells in table.items():
        lv, _why = level_of(floor)
        name = ("Floor " + str(int(floor))) if _FLOOR_NUM.match(floor) else {
            "MEZ": "Mezzanine", "ROF": "Roof", "OSP": "OSP (open space / site)"}.get(floor.upper(), floor)
        out.append(f"{name}: " + ", ".join(f"{t} {r.lower()}" for t, r in cells.items()))
    return out


def answer_lines(portal: Optional[Dict[str, Any]]) -> List[str]:
    """What the assistant prints from a portal check (lib/dob_now_portal's
    result). Every result names its record, who gave it and its date; an
    undated table says so; a list that was not loaded says 'not checked'."""
    if not portal:
        return []
    state = portal.get("state")
    bins = ", ".join(portal.get("bins") or []) or "no BIN"
    if state not in ("checked", "partial"):
        return []
    out = [f"\n{LABEL} (public portal, {PORTAL}), read {_when(portal.get('fetched_at'))} for BIN(s) {bins}:"]
    quiet: List[str] = []
    for entry in portal.get("records") or []:
        rec = entry.get("record") or {}
        rid = rec.get("record_id") or entry.get("record_id") or "?"
        typ = rec.get("record_type") or "record"
        lst = entry.get("inspections") or {}
        found = entry.get("bins_found") or []
        where = f", found under BIN {found[0]} only" if len(found) == 1 and len(portal.get("bins") or []) > 1 else ""
        lines: List[str] = []
        for c in lst.get("completed") or []:
            o = c.get("outcome")
            who = ("DOB spot check" if c.get("spot_check") else
                   "licensed master plumber self-certification, not a DOB inspection" if o == "certified" else
                   "DOB inspection")
            lines.append(f"    - {c.get('type')} ({c.get('id')}): {c.get('result')} — {who}, resulted "
                         f"{_when(c.get('resulted_at'))}")
        for r in rec.get("advance_notice_results") or []:
            lines.append(f"    - {r.get('inspection_type')} ({r.get('id')}), floor {r.get('floor')}: {r.get('result')} "
                         f"— self-certification results, scheduled {r.get('scheduled') or 'date not shown'}")
        if rec.get("advance_notice"):
            req = rec.get("request") or {}
            lines.append(f"    - advance notice for {_when(req.get('at') or req.get('date'))}: " + "; ".join(
                f"{n.get('inspection_type')}, floor {n.get('floor')}" for n in rec["advance_notice"]))
        for title, table in (rec.get("floor_results") or {}).items():
            lines.append(f"    - {title} (the table carries no dates): " + "; ".join(_floor_words(table)))
        if not lst.get("loaded"):
            lines.append(f"    - inspection list NOT checked ({lst.get('why') or 'not loaded'})")
        if lines:
            out.append(f"  {rid} ({typ}{where}):")
            out += lines
        elif lst.get("loaded"):
            quiet.append(rid)
    if quiet:
        out.append(f"  Read, with no completed inspection listed: {', '.join(quiet)}.")
    out.append(f"  {NOT_OTHER_TRADES[0].upper()}{NOT_OTHER_TRADES[1:]}.")
    return out
