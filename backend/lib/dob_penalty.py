"""A DOB / ECB penalty is not final until its hearing (operator ruling 2026-10-25).

Wherever a penalty is shown or sent and the hearing has not happened, it says
so: "$1,250 (hearing pending)" / "(audiencia pendiente)". One rule, used by the
alert/feed templates, the WhatsApp brief, the WhatsApp fact sets and the
Compliance screen (through the `penalty_hearing_pending` flag the dob-logs
read adds), so no surface can disagree with another.

HEARING PENDING, from what a violation row stores (server._extract_violation_fields):
  * `disposition_comments` carries the ECB `hearing_status`. An outcome word
    (DEFAULT, IN VIOLATION, DISMISSED, PAID, CURED, ...) means the hearing
    happened -> not pending. "PENDING" / "RESCHEDULED" / "ADJOURNED" -> pending.
  * otherwise `hearing_date` (ECB writes "20261118") on or after today (New
    York) -> pending.
  * neither -> not pending (no claim is made either way).
Pure: no clock is read unless `today` is omitted.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Optional

NOTE = {"en": "(hearing pending)", "es": "(audiencia pendiente)"}

_OUTCOME = re.compile(
    r"\b(DEFAULT\w*|IN VIOLATION|DISMISS\w*|WRITTEN OFF|PAID|CURED|STIPULATION|"
    r"SETTLED|DECISION|RESOLVED|CLOSED)\b", re.IGNORECASE)
_PENDING = re.compile(r"\b(PENDING|RESCHEDULED|ADJOURN\w*|NEW ISSUANCE)\b", re.IGNORECASE)


def _ny_today() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


def _day(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s) or re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def hearing_pending(row: Dict[str, Any], today: Optional[date] = None) -> bool:
    """True when the row's hearing has not happened yet (see module doc)."""
    status = " ".join(str(row.get(k) or "") for k in ("hearing_status", "disposition_comments"))
    if _OUTCOME.search(status):
        return False
    if _PENDING.search(status):
        return True
    d = _day(row.get("hearing_date"))
    return bool(d and d >= (today or _ny_today()))


def with_note(amount_text: str, row: Dict[str, Any], today: Optional[date] = None,
              lang: str = "en") -> str:
    """`amount_text` ("$1,250") with the note appended while the hearing is
    pending; unchanged otherwise (and unchanged when empty)."""
    if not amount_text or not hearing_pending(row, today):
        return amount_text
    return f"{amount_text} {NOTE.get(lang, NOTE['en'])}"
