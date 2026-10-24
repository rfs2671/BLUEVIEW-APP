"""The hearing and penalty an ECB card shows. Pure: no DB, no HTTP.

FIELDS (ECB/OATH dataset 6bgk-3dad, stored by server._extract_violation_fields):
  hearing_date     "20261118"   (YYYYMMDD, a New York calendar day)
  hearing_time     "930"        (HMM / HHMM, New York clock: 9:30)
  hearing_status   "PENDING" / "IN VIOLATION" / "DISMISSED" / ... or blank
  penalty_imposed  "1250"       (the column is spelled `penality_imposed`)
  balance_due      "1250"
  ecb_status       "ACTIVE" / "RESOLVE"

THE $0 THAT WAS NOT A PENALTY. The card used to print `penalty_amount`, which
for an ECB row is 6bgk-3dad `amount_paid` (the extractor's last fallback) -- so
39558662P, $1,250 imposed and its hearing still PENDING, read "$0 Penalty
Amount" in orange. The penalty is `penalty_imposed`. When that is $0 or blank
and the hearing is still to come, nothing has been set yet: the card says
"Penalty set at hearing", in a neutral colour, not an amount.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional

from lib.dob_plain_labels import is_ecb

__all__ = ["hearing_day", "hearing_clock", "hearing_pending", "hearing", "penalty"]


def hearing_day(raw: Any) -> Optional[str]:
    """'20261118' / '2026-11-18T00:00:00.000' -> '2026-11-18', else None."""
    s = str(raw or "").strip()
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def hearing_clock(raw: Any) -> Optional[str]:
    """'930' -> '09:30', '1030' -> '10:30', '09:30:00' -> '09:30', else None."""
    s = str(raw or "").strip()
    m = re.match(r"^(\d{1,2}):?(\d{2})(?::\d{2})?$", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def hearing_pending(row: Dict[str, Any], today: date) -> bool:
    """Is the hearing still to come? OATH's own PENDING says so; any other
    hearing status is an outcome. With none, an unresolved summons whose
    hearing day is today or later is pending."""
    hs = str(row.get("hearing_status") or "").strip().upper()
    if hs:
        return hs == "PENDING"
    if "RESOLVE" in str(row.get("ecb_status") or "").upper():
        return False
    day = hearing_day(row.get("hearing_date"))
    return bool(day) and day >= today.isoformat()


def hearing(row: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    if not is_ecb(row):
        return None
    day = hearing_day(row.get("hearing_date"))
    if not day:
        return None
    return {"date": day, "time": hearing_clock(row.get("hearing_time")),
            "pending": hearing_pending(row, today)}


def _amount(raw: Any) -> Optional[float]:
    s = re.sub(r"[,$\s]", "", str(raw or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _money(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def penalty(row: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    """{"kind": "amount", "amount", "balance_due"} | {"kind": "set_at_hearing"}
    | None (nothing to show)."""
    if not is_ecb(row):
        return None
    amt = _amount(row.get("penalty_imposed"))
    if amt and amt > 0:
        out: Dict[str, Any] = {"kind": "amount", "amount": _money(amt)}
        bal = _amount(row.get("balance_due"))
        if bal is not None:
            out["balance_due"] = _money(bal)
        return out
    if hearing_pending(row, today):
        return {"kind": "set_at_hearing"}
    return None
