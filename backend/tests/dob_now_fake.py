"""A fake DOB NOW: Inspections portal for tests: serves the SANITIZED 588
fixtures (tests/fixtures/dob_now/) to lib/dob_now_portal.Portal. No network.

The BIN search: the record list per BIN is the portal's own for 588 (read in a
browser on 2026-11-10, raw/accela/records_by_bin_search.json), cut to the five
records the fixtures hold. BIN 3430621's results come back on TWO pages so the
pager is exercised. The search-result markup is the portal's standard grid
row; the real search response was not captured raw.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FIX = Path(__file__).resolve().parent / "fixtures" / "dob_now"
NEW_BIN, OLD_BIN = "3430621", "3255362"

#: record id -> (capID1, capID3, BINs it is found under), from the portal's search.
RECORDS: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "B01141294S5PL": ("DUB26", "07Y1R", (NEW_BIN, OLD_BIN)),
    "CERT-ADV-PL-26-010624": ("DUB26", "09S11", (NEW_BIN,)),
    "ADV-PL-26-014303": ("DUB26", "0BU8Z", (NEW_BIN,)),
    "B23173802S5PL": ("DUB26", "0B76K", (NEW_BIN,)),
    "ADV-PL-26-011521": ("DUB26", "09JTA", (OLD_BIN,)),
}
BY_CAP3 = {c3: rid for rid, (_c1, c3, _b) in RECORDS.items()}
PAGE_SIZE = 3


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def delta(*segments: Tuple[str, str, str]) -> str:
    return "".join(f"{len(c)}|{t}|{i}|{c}|" for t, i, c in segments)


HOME_HTML = """<html><body><form method="post" action="./CapHome.aspx?module=DOB&amp;TabName=DOB">
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs-home" />
<input type="hidden" name="__EVENTTARGET" value="" />
<input name="ctl00$PlaceHolderMain$generalSearchForm$txtGSParcelNo" type="text" value="" />
<script type="text/javascript">Sys.WebForms.PageRequestManager._initialize('ctl00$ScriptManager1', 'aspnetForm',
['tctl00$PlaceHolderMain$updatePanel','','tctl00$PlaceHolderMain$updatePanel2',''], [], [], 90, 'ctl00');</script>
</form></body></html>"""


def _row(rid: str) -> str:
    c1, c3, _b = RECORDS[rid]
    return (f'<tr class="ACA_TabRow_Odd"><td><a id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList_ctl02_hlPermitNumber" '
            f'href="/CitizenAccessBuildings/Cap/CapDetail.aspx?Module=DOB&amp;TabName=DOB&amp;capID1={c1}&amp;capID2=00000'
            f'&amp;capID3={c3}&amp;agencyCode=BUILDINGS"><strong><span id="ctl00_PlaceHolderMain_dgvPermitList_'
            f'gdvPermitList_ctl02_lblPermitNumber1">{rid}</span></strong></a></td></tr>')


def search_delta(bin_: str, page: int) -> str:
    rids = [r for r, (_c1, _c3, bins) in RECORDS.items() if bin_ in bins]
    chunk = rids[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    pages = (len(rids) + PAGE_SIZE - 1) // PAGE_SIZE
    # The portal's own pager markup (captured live 2026-11-10): numbered
    # LinkButtons with an EMPTY event argument, in table.aca_pagination.
    pager = '<table class="aca_pagination" align="Center" border="0"><tr>' + "".join(
        f'<td class="aca_pagination_td"><span class="SelectedPageButton font11px">{n}</span></td>' if n == page else
        f'<td class="aca_pagination_td"><a href="javascript:__doPostBack(&#39;ctl00$PlaceHolderMain$dgvPermitList'
        f'$gdvPermitList$ctl13$ctl{n + 1:02d}&#39;,&#39;&#39;)">{n}</a></td>' for n in range(1, pages + 1)) + \
        "</tr></table>"
    first = (page - 1) * PAGE_SIZE + 1
    body = (f'<span class="ACA_Label">Showing {first}-{first + len(chunk) - 1} of {len(rids)} </span>'
            f'<table id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList">' + "".join(_row(r) for r in chunk)
            + f"</table>{pager}")
    return delta(("updatePanel", "ctl00_PlaceHolderMain_updatePanel", body),
                 ("hiddenField", "__VIEWSTATE", f"vs-{bin_}-{page}"),
                 ("updatePanelIDs", "", "tctl00$PlaceHolderMain$updatePanel,,tctl00$PlaceHolderMain$dgvPermitList"
                                        "$updatePanel,"))


class Resp:
    def __init__(self, text: str, status_code: int = 200, url: str = ""):
        self.text, self.status_code, self.url = text, status_code, url


class FakeSession:
    """`static_only`: the inspection postback answers with the static page
    (the list never loads). `error_on`: record ids whose pages are the
    portal's 'technical difficulties' page. `challenge`: every call is a
    Cloudflare interstitial. `override`: record id -> delta text.
    `one_page`: the pager never leaves page 1 (a short read).
    `search_reply`: every search answers with this text instead (a failed or
    unrecognised reply). `no_details`: the inspection details pages 404."""

    def __init__(self, *, static_only: bool = False, error_on: Tuple[str, ...] = (), challenge: bool = False,
                 override: Optional[Dict[str, str]] = None, one_page: bool = False,
                 search_reply: Optional[str] = None, no_details: bool = False):
        self.one_page, self.search_reply, self.no_details = one_page, search_reply, no_details
        self.static_only, self.error_on, self.challenge = static_only, set(error_on), challenge
        self.override = dict(override or {})
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def _cap(self, url: str) -> Optional[str]:
        m = re.search(r"capID3=(\w+)", url)
        return BY_CAP3.get(m.group(1)) if m else None

    def get(self, url: str, timeout: Any = None, **kw) -> Resp:
        self.calls.append(("GET", url, {}))
        if self.challenge:
            return Resp("<html><head><title>Just a moment...</title></head><script>window._cf_chl_opt={}</script>"
                        "</html>", 403, url)
        if "CapHome" in url:
            return Resp(HOME_HTML, 200, url)
        if "Inspection/InspectionDetails.aspx" in url:
            m = re.search(r"[?&]ID=(\d+)", url)
            name = f"detail_{m.group(1)}.html" if m else ""
            if self.no_details or not m or not (FIX / name).exists():
                return Resp("", 404, url)
            return Resp(fixture(name), 200, url)
        rid = self._cap(url)
        if rid in self.error_on:
            return Resp(fixture_error(), 200, "https://a810-lmpaca.nyc.gov/CitizenAccessBuildings/Error.aspx?ErrorId=x")
        if rid:
            return Resp(fixture(f"record_{rid}.html"), 200, url)
        return Resp("", 404, url)

    def post(self, url: str, data: Optional[Dict[str, Any]] = None, timeout: Any = None, headers: Any = None,
             **kw) -> Resp:
        data = dict(data or {})
        self.calls.append(("POST", url, data))
        if self.challenge:
            return Resp("<title>Just a moment...</title>", 403, url)
        if "CapHome" in url:
            if self.search_reply is not None:
                return Resp(self.search_reply, 200, url)
            bin_ = data.get("ctl00$PlaceHolderMain$generalSearchForm$txtGSParcelNo", "")
            if not any(bin_ in b for _c1, _c3, b in RECORDS.values()):
                return Resp(no_results_delta(), 200, url)
            m = re.search(r"gdvPermitList\$ctl13\$ctl(\d+)$", data.get("__EVENTTARGET") or "")
            page = int(m.group(1)) - 1 if m and not self.one_page else 1
            if m:
                assert data.get("ctl00$ScriptManager1", "").startswith("ctl00$PlaceHolderMain$dgvPermitList$updatePanel|")
            return Resp(search_delta(bin_, page), 200, url)
        rid = self._cap(url)
        if rid in self.override:
            return Resp(self.override[rid], 200, url)
        if self.static_only:
            return Resp(fixture(f"record_{rid}.html"), 200, url)
        return Resp(fixture(f"inspections_{rid}.txt"), 200, url)


def no_results_delta() -> str:
    """The portal's reply to a search that matched nothing (its own words,
    captured live 2026-11-10)."""
    return delta(("updatePanel", "ctl00_PlaceHolderMain_updatePanel", "<div>Record Number:</div>"),
                 ("updatePanel", "ctl00_PlaceHolderMain_updatePanel2",
                  "<span>Notice:</span><span>Your search returned no results. Please modify your search criteria and "
                  "try again.</span>"),
                 ("hiddenField", "__VIEWSTATE", "vs-none"))


#: The three replies the adversarial review showed read as "checked, nothing found".
BAD_SEARCH_REPLIES = {
    "error segment": "22|error|500|An unknown error occurred|",
    "a plain page saying no records": "<html>No records found.</html>",
    "a delta with only a hidden field": "5|hiddenField|__VIEWSTATE|vs-xx|",
}


def fixture_error() -> str:
    return ("<html><body><div>System Message:</div><div>We are experiencing technical difficulties. Please try "
            "again later or contact the Agency for assistance.</div></body></html>")


def portal(**kw):
    """A Portal over the fake session, with no delay and a fixed clock."""
    from datetime import datetime, timezone
    from lib import dob_now_portal as P
    return P.Portal(FakeSession(**kw), delay=0, sleep=lambda s: None,
                    clock=lambda: datetime(2026, 11, 10, 13, 30, tzinfo=timezone.utc))
