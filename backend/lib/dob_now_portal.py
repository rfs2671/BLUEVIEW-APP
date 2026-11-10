"""Read DOB NOW: Inspections (the public Accela Citizen Access portal) for every
BIN of a job site. NETWORK; the parsing is lib/dob_now_inspections (pure).

OFF IN PRODUCTION. `enabled()` reads DOB_NOW_PORTAL_ENABLED, default off:
turning on a new external scraper is the owner's call. While it is off, every
answer that touches inspections says this source was NOT CHECKED (lib/
source_coverage), never that it holds nothing. The operator probe
(scripts/dob_now_inspections_probe.py) runs it locally on demand, flag or not.

HOW THE PORTAL IS READ (verified by hand against the 588 pages, 2026-11-10):
  search_by_bin   CapHome.aspx, an ASP.NET async postback with the BIN in
                  ctl00$PlaceHolderMain$generalSearchForm$txtGSParcelNo; the
                  results come 10 per page, and a further page is a
                  __doPostBack on the grid with 'Page$N'.
  fetch_record    a plain GET of CapDetail.aspx: the record and its tables.
  fetch_inspection_list
                  the on-load async postback the page fires to fill its
                  inspection list (ScriptManager1 =
                  'ctl00$PlaceHolderMain$InspectionList$inspectionUpdatePanel|
                  ctl00$PlaceHolderMain$InspectionList$btnRefreshGridView',
                  __ASYNCPOST=true, header X-MicrosoftAjax: Delta=true). The
                  static page alone says "no completed inspections" for every
                  record, results or not.
The search response itself was not captured raw on 2026-11-10 (the record list
was read in a browser); its result-row parsing follows the portal's standard
grid markup and is the least-proven part of this reader.

An error page ("We are experiencing technical difficulties") or a Cloudflare
challenge is UNREACHABLE, reported as such, never as "none". Every BIN of the
site is searched (588: current 3430621 and the demolished house's 3255362)
and records are deduped by record id across BINs. The session is injected so
tests never touch the network; a polite delay separates requests.
"""

from __future__ import annotations

import html as _html
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import dob_now_inspections as D

BASE = "https://a810-lmpaca.nyc.gov/CitizenAccessBuildings/"
HOME = BASE + "Cap/CapHome.aspx?module=DOB&TabName=DOB"
DETAIL = (BASE + "Cap/CapDetail.aspx?Module=DOB&TabName=DOB&capID1={c1}&capID2={c2}&capID3={c3}"
          "&agencyCode=BUILDINGS")
BIN_FIELD = "ctl00$PlaceHolderMain$generalSearchForm$txtGSParcelNo"
SEARCH_BUTTON = "ctl00$PlaceHolderMain$btnNewSearch"
LIST_PANEL = "ctl00$PlaceHolderMain$InspectionList$inspectionUpdatePanel"
LIST_BUTTON = "ctl00$PlaceHolderMain$InspectionList$btnRefreshGridView"
AJAX_HEADERS = {"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeveLog-DOB-NOW-reader"

FLAG = "DOB_NOW_PORTAL_ENABLED"
DEFAULT_DELAY = 1.5           # seconds between requests to the portal
MAX_PAGES = 10                # search pages per BIN (10 records a page)
TIMEOUT = 60
CACHE_SECONDS = 6 * 3600


def enabled() -> bool:
    """Off unless DOB_NOW_PORTAL_ENABLED is set true (owner approval)."""
    return str(os.environ.get(FLAG, "")).strip().lower() in ("1", "true", "yes", "on")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Unreachable(Exception):
    """The portal answered with an error page, a challenge, or not at all."""


# ── THE SITE'S BINS ────────────────────────────────────────────────────────

def _real_bin(b: Any) -> Optional[str]:
    d = re.sub(r"\D", "", str(b or ""))
    return d if len(d) == 7 and not d.endswith("000000") else None


def site_bins(project: Dict[str, Any], dob_rows: Iterable[Dict[str, Any]] = ()) -> List[str]:
    """Every BIN of the job site: the project's own (`nyc_bin`), any a person
    listed (`additional_bins`), and any BIN the stored DOB records show shares
    a job with them (lib/report_regulatory.split_by_bin's rule: 588's records
    sit under 3255362 and 3430621). Obsolete BINs of a demolished building are
    found this way when their filings share the job; otherwise a person lists
    them in `additional_bins`."""
    from lib import report_regulatory
    own = [b for b in (_real_bin(x) for x in [project.get("nyc_bin"), *(project.get("additional_bins") or [])]) if b]
    inferred: List[str] = []
    rows = [r for r in dob_rows or () if isinstance(r, dict)]
    if own and rows:
        inferred = list(report_regulatory.split_by_bin(rows, own)[3])
    return list(dict.fromkeys(own + [b for b in (_real_bin(x) for x in inferred) if b]))


# ── FORM HANDLING ──────────────────────────────────────────────────────────

def form_fields(page: str) -> Dict[str, str]:
    """The form's posted fields (hidden inputs, text inputs, selects)."""
    out: Dict[str, str] = {}
    for m in re.finditer(r"<input[^>]*>", page or ""):
        tag = m.group(0)
        n = re.search(r'name="([^"]+)"', tag)
        if not n or re.search(r'type="(?:checkbox|radio|submit|button|image)"', tag, re.I):
            continue
        v = re.search(r'value="([^"]*)"', tag)
        out[_html.unescape(n.group(1))] = _html.unescape(v.group(1)) if v else ""
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', page or "", re.S):
        sel = (re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', m.group(2))
               or re.search(r'<option[^>]*value="([^"]*)"', m.group(2)))
        out[_html.unescape(m.group(1))] = _html.unescape(sel.group(1)) if sel else ""
    return out


def apply_delta_fields(fields: Dict[str, str], delta: str) -> Dict[str, str]:
    """A postback's delta carries the new hidden fields (__VIEWSTATE ...): the
    next postback must send them."""
    out = dict(fields)
    try:
        for typ, ident, content in D.delta_segments(delta):
            if typ == "hiddenField":
                out[ident] = content
    except (ValueError, IndexError):
        pass
    return out


# ── THE FETCHER ────────────────────────────────────────────────────────────

class Portal:
    """One polite reader. `session` is a requests.Session-like object (get,
    post); `sleep` and `clock` are injectable so tests run instantly."""

    def __init__(self, session: Any = None, *, delay: float = DEFAULT_DELAY,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] = now_utc):
        if session is None:
            import requests
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
        self.s, self.delay, self.sleep, self.clock = session, delay, sleep, clock
        self._last: Optional[float] = None
        self.log: List[Dict[str, Any]] = []

    def _wait(self) -> None:
        if self._last is not None and self.delay:
            self.sleep(self.delay)
        self._last = 1.0

    def _call(self, method: str, url: str, **kw) -> Dict[str, Any]:
        self._wait()
        at = self.clock()
        try:
            r = getattr(self.s, method)(url, timeout=TIMEOUT, **kw)
        except Exception as e:  # network down, timeout
            self.log.append({"method": method, "url": url, "at": at, "status": None, "error": type(e).__name__})
            raise Unreachable(f"{type(e).__name__} from the portal") from e
        text = getattr(r, "text", "") or ""
        status = getattr(r, "status_code", 200)
        self.log.append({"method": method.upper(), "url": url, "at": at, "status": status, "bytes": len(text)})
        problem = D.page_problem(text) or ("technical_difficulties" if "/Error.aspx" in str(getattr(r, "url", "")) else None)
        if problem == "challenge" or status in (403, 429, 503):
            raise Unreachable(f"the portal answered with a {'Cloudflare challenge' if problem == 'challenge' else f'HTTP {status}'}")
        if problem:
            raise Unreachable("the portal answered 'We are experiencing technical difficulties'")
        if status >= 400:
            raise Unreachable(f"the portal answered HTTP {status}")
        return {"text": text, "fetched_at": at, "url": url, "status": status}

    # -- search --------------------------------------------------------------
    def search_by_bin(self, bin_: str) -> Dict[str, Any]:
        """{bin, records: {record_id: {capid: (c1, c2, c3), record_id}}, pages,
        stated_total, fetched_at}. Raises Unreachable."""
        home = self._call("get", HOME)
        fields = form_fields(home["text"])
        panel = re.search(r"'t(ctl00\$PlaceHolderMain\$[^']*updatePanel[^']*)'", home["text"])
        panel_id = panel.group(1) if panel else "ctl00$PlaceHolderMain$updatePanel"
        fields.update({BIN_FIELD: bin_, "__EVENTTARGET": SEARCH_BUTTON, "__EVENTARGUMENT": "", "__ASYNCPOST": "true",
                       "ctl00$ScriptManager1": f"{panel_id}|{SEARCH_BUTTON}"})
        first = self._call("post", HOME, data=fields, headers=dict(AJAX_HEADERS, Referer=HOME))
        records: Dict[str, Dict[str, Any]] = {}
        pages_read = 1
        text = first["text"]
        redirect = parse_redirect(text)
        if redirect:              # one record: the portal goes straight to it
            records[redirect["capid_key"]] = {"record_id": None, "capid": redirect["capid"]}
            return {"bin": bin_, "records": records, "pages": 1, "stated_total": 1, "fetched_at": first["fetched_at"]}
        records.update(parse_search_results(text))
        total = stated_total(text)
        fields = apply_delta_fields(fields, text)
        seen_pages = {1}
        grid = grid_panel(text, panel_id)
        while pages_read < MAX_PAGES:
            nxt = next_page(text, seen_pages)
            if not nxt:
                break
            number, target, arg = nxt
            seen_pages.add(number)
            fields.update({"__EVENTTARGET": target, "__EVENTARGUMENT": arg, "__ASYNCPOST": "true",
                           "ctl00$ScriptManager1": f"{grid}|{target}"})
            fields.pop(SEARCH_BUTTON, None)
            page = self._call("post", HOME, data=fields, headers=dict(AJAX_HEADERS, Referer=HOME))
            text = page["text"]
            records.update(parse_search_results(text))
            fields = apply_delta_fields(fields, text)
            pages_read += 1
        return {"bin": bin_, "records": records, "pages": pages_read, "stated_total": total,
                "fetched_at": first["fetched_at"]}

    # -- one record ----------------------------------------------------------
    def fetch_record(self, capid: Sequence[str]) -> Dict[str, Any]:
        """The static CapDetail page: {text, fetched_at, url, status}."""
        c1, c2, c3 = capid
        return self._call("get", DETAIL.format(c1=c1, c2=c2, c3=c3))

    def fetch_inspection_list(self, capid: Sequence[str], static: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Replay the on-load async postback that fills the inspection list.
        `static`: the record page already fetched (its form state is reused)."""
        page = static or self.fetch_record(capid)
        url = page["url"]
        f = form_fields(page["text"])
        f.pop(LIST_BUTTON, None)
        f.update({"ctl00$ScriptManager1": f"{LIST_PANEL}|{LIST_BUTTON}", "__EVENTTARGET": "", "__EVENTARGUMENT": "",
                  "__ASYNCPOST": "true", LIST_BUTTON: ""})
        return self._call("post", url, data=f, headers=dict(AJAX_HEADERS, Referer=url))


# ── SEARCH RESULT READERS (pure) ───────────────────────────────────────────

_CAP_ROW = re.compile(r"capID1=(\w+)&(?:amp;)?capID2=(\w+)&(?:amp;)?capID3=(\w+)[^>]*>\s*(?:<[^>]+>\s*)*([A-Z0-9][A-Z0-9-]{5,})")


def parse_search_results(text: str) -> Dict[str, Dict[str, Any]]:
    """{record_id: {record_id, capid}} from a search results page or delta."""
    out: Dict[str, Dict[str, Any]] = {}
    for c1, c2, c3, rid in _CAP_ROW.findall(text or ""):
        out.setdefault(rid, {"record_id": rid, "capid": (c1, c2, c3)})
    return out


def stated_total(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s+Record(?:s)?\s+results?|Showing\s+\d+-\d+\s+of\s+(\d+)", text or "", re.I)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def page_links(text: str) -> List[Tuple[int, str, str]]:
    """[(page number, event target, event argument)] of the results pager.

    The portal's pager (seen live, 2026-11-10) is a table.aca_pagination of
    numbered LinkButtons: <a href="javascript:__doPostBack('...gdvPermitList
    $ctl13$ctl03','')">2</a>. The stock GridView form ('Page$N') is read too."""
    plain = _html.unescape(text or "")
    out: List[Tuple[int, str, str]] = []
    for target, arg, label in re.findall(
            r"""__doPostBack\('([^']*gdvPermitList[^']*)','([^']*)'\)"?\s*>\s*(\d+)\s*</a>""", plain):
        out.append((int(label), target, arg))
    for target, arg, n in re.findall(r"__doPostBack\('([^']*gdvPermitList[^']*)','(Page\$(\d+))'\)", plain):
        out.append((int(n), target, arg))
    return sorted(set(out))


def next_page(text: str, seen: Iterable[int]) -> Optional[Tuple[int, str, str]]:
    """The lowest-numbered pager link to a page not yet read."""
    seen = set(seen)
    return next((link for link in page_links(text) if link[0] not in seen), None)


def grid_panel(text: str, default: str) -> str:
    """The update panel that holds the results grid (its pager posts to it)."""
    try:
        for typ, _i, content in D.delta_segments(text):
            if typ == "updatePanelIDs":
                m = re.search(r"t?(ctl00\$PlaceHolderMain\$dgvPermitList\$updatePanel)\b", content)
                if m:
                    return m.group(1)
    except (ValueError, IndexError):
        pass
    return default


def parse_redirect(text: str) -> Optional[Dict[str, Any]]:
    """A delta that redirects to one record's CapDetail page."""
    try:
        segs = D.delta_segments(text)
    except (ValueError, IndexError):
        return None
    for typ, _i, content in segs:
        if typ == "pageRedirect":
            m = re.search(r"capID1=(\w+)&(?:amp;)?capID2=(\w+)&(?:amp;)?capID3=(\w+)", _html.unescape(content))
            if m:
                return {"capid": m.groups(), "capid_key": "-".join(m.groups())}
    return None


# ── EVERY BIN, EVERY RECORD ────────────────────────────────────────────────

def check_bins(bins: Sequence[str], portal: Optional[Portal] = None, *, keep_raw: bool = False,
               only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Search every BIN, then read each record ONCE (deduped by record id
    across BINs): its static page and its inspection list.

      {state: checked | partial | unreachable | not_checked, bins, fetched_at,
       records: [{record_id, capid, bins_found, record, inspections,
                  fetched_at, raw?}],
       unreachable: [{what, why}], searched: {bin: {pages, stated_total, found}}}

    `partial`: some BIN search, record or list could not be read; those are
    named in `unreachable` and their absence is unknown."""
    portal = portal or Portal()
    bins = [b for b in (_real_bin(x) for x in bins or ()) if b]
    started = portal.clock()
    out: Dict[str, Any] = {"state": "not_checked", "bins": bins, "fetched_at": started, "records": [],
                           "unreachable": [], "searched": {}}
    if not bins:
        out["why"] = "the project has no real BIN"
        return out
    found: Dict[str, Dict[str, Any]] = {}
    for b in bins:
        try:
            res = portal.search_by_bin(b)
        except Unreachable as e:
            out["unreachable"].append({"what": f"BIN {b} search", "why": str(e)})
            continue
        out["searched"][b] = {"pages": res["pages"], "stated_total": res["stated_total"], "found": len(res["records"])}
        if res["stated_total"] is not None and len(res["records"]) < res["stated_total"]:
            # Fewer rows than the portal says it has: the rest are UNREAD, not absent.
            out["unreachable"].append({"what": f"BIN {b} search",
                                       "why": f"read {len(res['records'])} of the {res['stated_total']} records "
                                              "the portal lists"})
        for key, r in res["records"].items():
            slot = found.setdefault(r.get("record_id") or key, {"record_id": r.get("record_id"), "capid": r["capid"],
                                                                 "bins_found": []})
            if b not in slot["bins_found"]:
                slot["bins_found"].append(b)
    for key, slot in found.items():
        if only and slot["record_id"] not in only:
            continue
        entry: Dict[str, Any] = dict(slot)
        try:
            page = portal.fetch_record(slot["capid"])
        except Unreachable as e:
            out["unreachable"].append({"what": f"record {slot['record_id'] or key}", "why": str(e)})
            continue
        rec = D.parse_record(page["text"])
        entry["record_id"] = rec.get("record_id") or slot["record_id"] or key
        entry["record"], entry["fetched_at"] = rec, page["fetched_at"]
        try:
            lst = portal.fetch_inspection_list(slot["capid"], page)
            entry["inspections"] = D.parse_inspection_list(lst["text"])
            if keep_raw:
                entry["raw"] = {"record": page["text"], "inspections": lst["text"]}
        except Unreachable as e:
            entry["inspections"] = {"loaded": False, "why": str(e), "completed": [], "upcoming": []}
            out["unreachable"].append({"what": f"record {entry['record_id']} inspection list", "why": str(e)})
        if not entry["inspections"].get("loaded"):
            if not any(u["what"].startswith(f"record {entry['record_id']}") for u in out["unreachable"]):
                out["unreachable"].append({"what": f"record {entry['record_id']} inspection list",
                                           "why": entry["inspections"].get("why") or "not loaded"})
        out["records"].append(entry)
    out["records"].sort(key=lambda e: str(e.get("record_id")))
    if not out["searched"]:
        out["state"] = "unreachable"
        out["why"] = "; ".join(u["why"] for u in out["unreachable"]) or "no BIN search answered"
    else:
        out["state"] = "partial" if out["unreachable"] else "checked"
    out["requests"] = list(portal.log)
    return out


def not_checked(bins: Sequence[str], why: str) -> Dict[str, Any]:
    return {"state": "not_checked", "bins": list(bins), "fetched_at": None, "records": [], "unreachable": [],
            "searched": {}, "why": why}


def coverage_entry(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """This portal check as one lib/source_coverage entry."""
    from lib import source_coverage as SC
    if not result or result.get("state") == "not_checked":
        return SC.entry(SC.DOB_NOW_INSPECTIONS, SC.NOT_CHECKED,
                        why=(result or {}).get("why") or f"the portal reader is off ({FLAG})")
    if result["state"] == "unreachable":
        return SC.entry(SC.DOB_NOW_INSPECTIONS, SC.UNREACHABLE, why=result.get("why") or "the portal did not answer")
    if result["state"] == "partial":
        gone = "; ".join(f"{u['what']}: {u['why']}" for u in result.get("unreachable") or [])
        return SC.entry(SC.DOB_NOW_INSPECTIONS, SC.NOT_LOADED, why=f"read in part; {gone}")
    return SC.entry(SC.DOB_NOW_INSPECTIONS, SC.CHECKED, as_of=result.get("fetched_at"),
                    found=sum(len((r.get("inspections") or {}).get("completed") or []) for r in result.get("records") or []))


# ── A SHORT IN-PROCESS MEMORY (nothing is written to any database) ─────────

_CACHE: Dict[Tuple[str, ...], Tuple[float, Dict[str, Any]]] = {}
_LOCK = threading.Lock()


def remember(bins: Sequence[str], result: Dict[str, Any], *, at: Optional[float] = None) -> None:
    if result.get("state") not in ("checked", "partial"):
        return
    with _LOCK:
        _CACHE[tuple(sorted(bins))] = (time.monotonic() if at is None else at, result)


def cached(bins: Sequence[str], *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    with _LOCK:
        hit = _CACHE.get(tuple(sorted(bins)))
    if not hit:
        return None
    t = time.monotonic() if now is None else now
    return hit[1] if t - hit[0] <= CACHE_SECONDS else None


def forget() -> None:
    with _LOCK:
        _CACHE.clear()
