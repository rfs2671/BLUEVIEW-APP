"""DOB BIS complaints: the low-latency source for a NEW complaint.

WHY THIS EXISTS. LeveLog's only complaint source was NYC Open Data `eabe-havv`
(DOB Complaints Received). That dataset is a DAILY EXTRACT: every row carries
`dobrundate` = the extract's midnight, and the portal republishes it once a day
(measured 2026-11-10: rowsUpdatedAt 17:15 UTC, newest Brooklyn complaint
3A88386 entered 11/09). A complaint DOB receives at 11:22 on day D is in the
day D+1 extract, published the afternoon of D+1 -- about 26 hours later.
Polling that dataset every 15 minutes does not make it fresher.

BIS (a810-bisweb.nyc.gov) is where DOB enters the complaint. On 2026-11-10 the
two 546 Saratoga complaints received 11:22 and 11:25 ET (3A88489, 3A88492) were
on BIS at the first check (14:48 ET) while Open Data had neither. BIS answers a
plain GET -- from a laptop and, measured the same day, from the production
container (HTTP 200, 0.2 s). It is NOT the Akamai-walled DOB NOW portal.

WHAT THIS MODULE IS. Pure parsers over BIS's HTML (tested against the real
pages in tests/fixtures/bis_complaints/) and a fetch helper that reports an
explicit outcome. A list is "complete" only when the rows read equal the total
BIS states on the page; a failed or partial read is never an absence.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

BIS_BASE = "https://a810-bisweb.nyc.gov/bisweb/"
ET = ZoneInfo("America/New_York")

# BIS list-view status abbreviations.
LIST_STATUS = {"ACT": "ACTIVE", "RES": "RESOLVED", "CLO": "CLOSED", "CLS": "CLOSED"}
OPEN_STATUSES = {"ACTIVE", "OPEN", "ACT"}


def list_url(bin_: str, *, allcount: Optional[str] = None) -> str:
    if allcount:
        return (f"{BIS_BASE}ComplaintsByAddressServlet?allbin={bin_}&allcount={allcount}"
                f"&requestid=2&next.x=1&next.y=1")
    return f"{BIS_BASE}ComplaintsByAddressServlet?requestid=1&allbin={bin_}"


class StatelessBisClient:
    """BIS keeps a person's last search in a session cookie and can answer the
    next search of ANOTHER kind with the old page. Measured in production
    2026-11-11 with one client shared across projects: a complaints request
    for BIN 3426220 came back as the OATH/ECB search page, and an ECB request
    for BIN 3255362 failed the same way -- both reported as "unrecognized
    page". Every request therefore goes out with no session, except the
    continuation of a complaints list (requestid=2), which pages within one."""

    def __init__(self, client):
        self._c = client

    def _jar(self):
        inner = getattr(self._c, "_inner", self._c)
        return getattr(inner, "cookies", None)

    async def get(self, url, **kw):
        if "requestid=2" not in str(url):
            jar = self._jar()
            if jar is not None:
                jar.clear()
        return await self._c.get(url, **kw)


def detail_url(complaint_number: str) -> str:
    return f"{BIS_BASE}OverviewForComplaintServlet?complaintno={complaint_number}&requestid=0"


def property_url(bin_: str) -> str:
    return f"{BIS_BASE}PropertyProfileOverviewServlet?bin={bin_}"


def normalize_complaint_number(v: Any) -> str:
    """One spelling per complaint across BIS, Open Data and stored rows."""
    return re.sub(r"[^0-9A-Z]", "", str(v or "").upper())


def _text(fragment: str) -> str:
    s = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _strip_comments(page: str) -> str:
    return re.sub(r"<!--.*?-->", " ", page, flags=re.S)


def _mdy(s: str) -> Optional[str]:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


# ── List view: ComplaintsByAddressServlet ────────────────────────────────────

@dataclass
class ListPage:
    bin: Optional[str]
    premises: Optional[str]
    block: Optional[str]
    lot: Optional[str]
    total: Optional[int]
    page: Optional[int]
    pages: Optional[int]
    next_allcount: Optional[str]
    rows: List[Dict[str, Any]] = field(default_factory=list)


def parse_complaint_list(page: str) -> ListPage:
    body = _strip_comments(page)
    flat = _text(body)
    bin_m = re.search(r"BIN:\s*(\d{7})", flat)
    prem = re.search(r"Premises:\s*(.+?)\s+BIN:", flat)
    blk = re.search(r"Block:\s*(\d+)", flat)
    lot = re.search(r"Lot:\s*(\d+)", flat)
    # The count sits right after "Lot: <n>". A BIN with no complaints prints
    # "NO COMPLAINT RECORDS FOUND" and an EMPTY count, and the old pattern took
    # the LOT number for it (12 Walworth St, lot 33: "33 complaints, 0 rows",
    # 2026-11-11) -- an incomplete read on every pass.
    if "NO COMPLAINT RECORDS FOUND" in flat.upper():
        tot = re.match(r"(0)", "0")
    else:
        tot = (re.search(r"Lot:\s*\d+\s+(\d+)\s+Total Complaints", flat)
               or re.search(r"(?<!Lot: )(\d+)\s+Total Complaints", flat))
    pg = re.search(r"Page:\s*(\d+)\s+of\s+(\d+)", flat)
    nxt = None
    form = re.search(r'<form[^>]*name="frmnext".*?</form>', body, flags=re.S | re.I)
    if form:
        ac = re.search(r'name="allcount"\s+value="(\d+)"', form.group(0))
        nxt = ac.group(1) if ac else None
    rows: List[Dict[str, Any]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)
        link = re.search(r"OverviewForComplaintServlet\?[^\"']*vlcompdetlkey=(\d+)", tr)
        if link and len(tds) >= 7:
            cells = [_text(t) for t in tds[:7]]
            status_raw = cells[6].upper()
            rows.append({
                "complaint_number": normalize_complaint_number(cells[0]),
                "address": cells[1],
                "date_entered": _mdy(cells[2]),
                "category": cells[3].upper(),
                "inspection_date": _mdy(cells[4]),
                "disposition_code": cells[5].upper() or None,
                "status": LIST_STATUS.get(status_raw, status_raw or None),
                "bis_detail_key": link.group(1),
                "description": None,
            })
        elif rows and len(tds) == 2 and not _text(tds[0]) and rows[-1]["description"] is None:
            rows[-1]["description"] = _text(tds[1]) or None
    return ListPage(
        bin=bin_m.group(1) if bin_m else None, premises=prem.group(1).strip() if prem else None,
        block=blk.group(1) if blk else None, lot=lot.group(1) if lot else None,
        total=int(tot.group(1)) if tot else None,
        page=int(pg.group(1)) if pg else None, pages=int(pg.group(2)) if pg else None,
        next_allcount=nxt, rows=rows)


# ── Detail view: OverviewForComplaintServlet ────────────────────────────────

def _labeled(flat: str, label: str, stop: str) -> Optional[str]:
    m = re.search(re.escape(label) + r"\s*(.*?)\s*(?:" + stop + r")", flat)
    v = m.group(1).strip() if m else None
    return v or None


def parse_complaint_detail(page: str) -> Dict[str, Any]:
    flat = _text(_strip_comments(page))
    head = re.search(r"Overview for Complaint #:\s*([0-9A-Z]*)\s*=\s*([A-Z ]*?)\s+Complaint at", flat)
    if "COMPLAINT NUMBER NOT FOUND" in flat or not head or not head.group(1):
        return {"found": False}
    out: Dict[str, Any] = {
        "found": True,
        "complaint_number": normalize_complaint_number(head.group(1)),
        "status": head.group(2).strip() or None,
    }
    out["address"] = _labeled(flat, "Complaint at:", r"BIN:")
    b = re.search(r"BIN:\s*(\d{7})", flat)
    out["bin"] = b.group(1) if b else None
    out["description"] = _labeled(flat, "Re:", r"Category Code:")
    cat = re.search(r"Category Code:\s*([0-9A-Z]{2})\s+(.*?)\s+(?:DOB District|Assigned To)", flat)
    out["category"] = cat.group(1) if cat else None
    out["category_desc"] = cat.group(2).strip() if cat else None
    out["assigned_to"] = _labeled(flat, "Assigned To:", r"Priority:")
    pr = re.search(r"Priority:\s*([A-Z0-9])\b", flat)
    out["priority"] = pr.group(1) if pr else None
    rec = re.search(r"Received:\s*(\d{2}/\d{2}/\d{4})(?:\s+(\d{1,2}):(\d{2}))?", flat)
    out["received_date"] = _mdy(rec.group(1)) if rec else None
    out["received_at"] = None
    if rec and rec.group(2):
        mo, d, y = (int(x) for x in rec.group(1).split("/"))
        out["received_at"] = datetime(y, mo, d, int(rec.group(2)), int(rec.group(3)), tzinfo=ET).isoformat()
    blk = re.search(r"Block:\s*(\d+)", flat)
    lot = re.search(r"Lot:\s*(\d+)", flat)
    out["block"], out["lot"] = (blk.group(1) if blk else None), (lot.group(1) if lot else None)
    insp = _labeled(flat, "Last Inspection:", r"Disposition:")
    out["last_inspection_date"] = _mdy(insp or "") if insp and "NONE" not in insp else None
    badge = re.search(r"BY BADGE #\s*(\d+)", insp or "")
    out["inspector_badge"] = badge.group(1) if badge else None
    disp = _labeled(flat, "Disposition:", r"ECB Violation #:|Comments:|Complaint Disposition History")
    dm = re.match(r"(\d{2}/\d{2}/\d{4})\s*-\s*([0-9A-Z]{2})\s*-\s*(.*)", disp or "")
    out["disposition_date"] = _mdy(dm.group(1)) if dm else None
    out["disposition_code"] = dm.group(2) if dm else None
    out["disposition_desc"] = dm.group(3).strip() if dm else None
    ecb = _labeled(flat, "ECB Violation #:", r"Comments:|Complaint Disposition History")
    out["ecb_violation_numbers"] = re.findall(r"\b\d{8}[A-Z]\b", ecb or "")
    out["comments"] = _labeled(flat, "Comments:", r"Complaint Disposition History")
    return out


# ── Property profile: the lot's other BINs ──────────────────────────────────

def parse_property_profile(page: str) -> Dict[str, Any]:
    flat = _text(_strip_comments(page))
    b = re.search(r"BIN#\s*(\d{7})", flat)
    extra = re.search(r"Additional BINs for Building:\s*([\d\s]*)", flat)
    return {
        "bin": b.group(1) if b else None,
        "additional_bins": re.findall(r"\b\d{7}\b", extra.group(1)) if extra else [],
        "stop_work_order": bool(re.search(r"(?<!PARTIAL )STOP WORK ORDER EXISTS", flat.upper())),
        "partial_stop_work_order": ("PARTIAL STOP WORK ORDER EXISTS" in flat.upper()),
        "vacate_order": ("VACATE ORDER EXISTS" in flat.upper()),
    }


# ── Fetch with an explicit outcome ──────────────────────────────────────────

@dataclass
class BinRead:
    """What one BIN's BIS read established. `complete` = every row BIS says
    exists was read; `ok` = the newest page answered and parsed. A read that is
    not `ok` says NOTHING about whether complaints exist."""
    bin: str
    ok: bool
    complete: bool
    rows: List[Dict[str, Any]]
    total: Optional[int]
    checked_at: datetime
    error: Optional[str] = None


async def read_bin(client, bin_: str, *, now: datetime, known: Optional[set] = None,
                   max_pages: int = 3) -> BinRead:
    """Newest-first BIS list for one BIN. Reads further pages only while every
    row on the page is unknown (more new complaints than fit on a page)."""
    rows: List[Dict[str, Any]] = []
    total = None
    url = list_url(bin_)
    for _ in range(max_pages):
        try:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (LeveLog DOB monitor)"},
                                 timeout=30.0)
        except Exception as e:  # network, timeout
            return BinRead(bin_, False, False, rows, total, now, f"{type(e).__name__}")
        if r.status_code != 200:
            return BinRead(bin_, False, False, rows, total, now, f"HTTP {r.status_code}")
        page = parse_complaint_list(r.text)
        if page.bin != bin_ or page.total is None:
            return BinRead(bin_, False, False, rows, total, now, "unrecognized page")
        total = page.total
        rows += page.rows
        all_new = known is not None and all(x["complaint_number"] not in known for x in page.rows)
        if not (page.next_allcount and all_new):
            break
        url = list_url(bin_, allcount=page.next_allcount)
    return BinRead(bin_, True, total is not None and len(rows) >= total, rows, total, now)
