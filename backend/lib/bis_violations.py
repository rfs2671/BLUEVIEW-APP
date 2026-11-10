"""DOB BIS violation lists: ECB/OATH summonses and DOB violations, per BIN.

WHY. LeveLog's violation sources were the Open Data datasets 6bgk-3dad
(ECB/OATH), 3h2n-5cm9 (BIS DOB violations) and 855j-jady (DOB NOW Safety), each
a daily extract, plus 3usq-5cid, a COVID-era stop-work dataset with nothing
after 2020-05-28. BIS's own per-BIN lists are what DOB updates as it enters a
summons or violation; they answer a plain GET (measured from production
2026-11-10).

ECB LIST (ECBQueryByLocationServlet?requestid=0&allbin=<BIN>). The page embeds a
structured dump of the record it rendered:
    TotViolsIssued :: 19        TotViolsOpen :: 2
    BxsnqbylArray ::  ARRAY[13 * 45]
    [1]
        [0:ExtEcbViolNo]{39556260N}
        [1:ExtActiveFlag]{A}
        ...
        [10:ExtViolIssueDate]{20260707}
That dump is parsed, not the table: it carries every field with its own name,
and the page's own count lets a read say it is COMPLETE (rows == issued) or not.
A partial or failed read is never an absence.

DOB VIOLATION LIST (ActionsByLocationServlet?requestid=0&allbin=<BIN>
&allinquirytype=BXS4OCV3&stypeocv3=V): rows of number, type/status, file date.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List, Optional

BIS_BASE = "https://a810-bisweb.nyc.gov/bisweb/"


def ecb_list_url(bin_: str) -> str:
    return f"{BIS_BASE}ECBQueryByLocationServlet?requestid=0&allbin={bin_}"


def dob_violation_list_url(bin_: str) -> str:
    return (f"{BIS_BASE}ActionsByLocationServlet?requestid=0&allbin={bin_}"
            f"&allinquirytype=BXS4OCV3&stypeocv3=V")


def ecb_detail_url(number: str) -> str:
    return f"{BIS_BASE}ECBQueryByNumberServlet?ecbin={number}"


def normalize_violation_number(v: Any) -> str:
    """'039556258Y' (OATH ticket) and '39556258Y' (DOB ECB number) are one summons."""
    s = re.sub(r"[^0-9A-Z]", "", str(v or "").upper())
    return s[1:] if len(s) == 10 and s[0] == "0" and s[-1].isalpha() else s


def _ymd(v: str) -> Optional[str]:
    v = (v or "").strip()
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if re.fullmatch(r"\d{8}", v) else None


def parse_ecb_list(page: str) -> Dict[str, Any]:
    """{'bin', 'total_issued', 'total_open', 'rows': [...], 'complete'}."""
    def scalar(name: str) -> Optional[str]:
        m = re.search(rf"^\s*{name}\s*::\s*(.*?)\s*$", page, flags=re.M)
        return m.group(1).strip() if m else None

    rows: List[Dict[str, Any]] = []
    for block in re.split(r"^\s*\[\d+\]\s*$", page.split("BxsnqbylArray", 1)[-1], flags=re.M)[1:]:
        f = dict(re.findall(r"\[\d+:(\w+)\]\{([^}]*)\}", block))
        num = normalize_violation_number(f.get("ExtEcbViolNo"))
        if not num:
            continue
        bal = f.get("ExtBalanceDue") or ""
        rows.append({
            "ecb_number": num,
            "active": (f.get("ExtActiveFlag") or "").strip() == "A",
            "respondent": (f.get("ExtRespName") or "").strip() or None,
            "certification_status": (f.get("ExtCompStatusExp") or "").strip() or None,
            "hearing_status": (f.get("ExtHearingStatusExp") or "").strip() or None,
            "unit": (f.get("ExtUnitCodeExp") or "").strip() or None,
            "violation_type": (f.get("ExtViolTypeExp") or "").strip() or None,
            "balance_due": (int(bal) / 100.0) if bal.isdigit() else None,
            "issue_date": _ymd(f.get("ExtViolIssueDate") or ""),
            "severity": (f.get("CompSeverity") or "").strip() or None,
            "infraction_code": (f.get("InfrLine") or "").strip() or None,
        })
    issued = scalar("TotViolsIssued")
    opened = scalar("TotViolsOpen")
    vbin = scalar("VlBin") or scalar("AllBin")
    total = int(issued) if issued and issued.isdigit() else None
    return {
        "bin": vbin if vbin and re.fullmatch(r"\d{7}", vbin) else None,
        "total_issued": total,
        "total_open": int(opened) if opened and opened.isdigit() else None,
        "rows": rows,
        "complete": total is not None and len(rows) >= total,
    }


def parse_dob_violation_list(page: str) -> Dict[str, Any]:
    """BIS DOB violations: [{'number', 'type', 'status', 'file_date', 'closure_date'}]."""
    flat = re.sub(r"<!--.*?-->", " ", page, flags=re.S)
    text = _html.unescape(re.sub(r"<[^>]+>", "\n", flat)).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    b = re.search(r"BIN:\s*(\d{7})", " ".join(lines))
    rows: List[Dict[str, Any]] = []
    for i, x in enumerate(lines):
        m = re.match(r"^(V\*?\s*[0-9A-Z\-]{6,})$", x) or re.match(r"^(V[0-9A-Z\-]{6,})$", x)
        if not m or i + 2 >= len(lines):
            continue
        typ = lines[i + 1]
        if "VIOLATION" not in typ.upper():
            continue
        st = "CLOSED" if "CLOSED" in typ.upper() else ("ACTIVE" if "ACTIVE" in typ.upper() else None)
        closure = re.search(r"CLOSURE DATE:\s*(\d{2}/\d{2}/\d{4})", " ".join(lines[i + 2:i + 4]))
        rows.append({"number": re.sub(r"\s+", "", m.group(1)), "type": typ, "status": st,
                     "file_date": lines[i + 2], "closure_date": closure.group(1) if closure else None})
    return {"bin": b.group(1) if b else None, "rows": rows}
