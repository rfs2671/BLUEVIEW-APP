"""When a scheduled message fails to send, and what the failure was.

Wed Oct 14: the 8:00 brief's WaAPI send-message call answered HTTP 500 at
8:05 (three tries in 44 seconds), the ledger row became "failed", and that
was the day -- no later try, nothing saying why. A WaAPI 500 is usually
gone minutes later, so a scheduled send is tried again after 5, 15, then
every 30 minutes until its window closes; then it is a final failure and an
operator is told.

Pure: no I/O.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional

#: Minutes to wait after the 1st, 2nd, 3rd (and every later) failed try.
RETRY_MINUTES = (5, 15, 30)

_NUMBER = re.compile(r"\+?\d[\d\s().-]{5,}\d")


def next_try(attempts: int, failed_at: datetime) -> datetime:
    """When to try again after `attempts` failed tries, the last at
    `failed_at`."""
    i = max(0, min(int(attempts or 1) - 1, len(RETRY_MINUTES) - 1))
    return failed_at + timedelta(minutes=RETRY_MINUTES[i])


def is_final(attempts: int, failed_at: datetime, deadline: Optional[datetime]) -> bool:
    """No other try fits before `deadline`: this failure is the last."""
    return deadline is not None and next_try(attempts, failed_at) >= deadline


def scrub(text: Any, limit: int = 200) -> str:
    """A response body as one short line, with no phone numbers."""
    if isinstance(text, (dict, list)):
        try:
            text = json.dumps(text, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            text = str(text)
    s = _NUMBER.sub("[number]", " ".join(str(text or "").split()))
    return s[:limit]


def waapi_error(endpoint: str, code: Optional[int], body: Any,
                exc: Optional[BaseException]) -> str:
    """"http 500 (send-message): {"error":"…"}" -- which call, what status,
    and what WaAPI said; or the exception when no answer came."""
    if exc is not None:
        return f"{type(exc).__name__} ({endpoint})"
    said = scrub(body) if body not in (None, {}, "", []) else ""
    return f"http {code} ({endpoint})" + (f": {said}" if said else "")
