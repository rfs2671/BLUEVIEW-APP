"""Activities a CONFIRMED project schedule has planned for a date, as chip hints.

Pure. A hint says "the schedule has this planned now", never "this is happening":
it lifts a chip in the ranking and gives the reason in the schedule file's own
words. Nothing is estimated or inferred about progress.

A chip matches a schedule activity only when every meaningful word of the chip's
label is in the activity's name ("pour slab" matches "Pour slab - floor 2";
"interior framing" does not match "Metal stud framing floor 2"). That is
deliberately strict: a wrong hint puts a suggestion behind a signed log, and a
missed one costs nothing -- the chip is still on the card.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["hints_for"]

_STOP = frozenset("the and for with floor floors level levels all area work phase".split())
WINDOW_BEFORE = 1     # days an activity may already have started / finished
WINDOW_AFTER = 3      # days before its planned start it already counts
MAX_HINTS = 4


def _tokens(text: Any) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) >= 3 and w not in _STOP}


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def hints_for(activities: Iterable[Dict[str, Any]], on: str, chips: Iterable[Any]) -> Dict[str, str]:
    """{chip id: reason} for chips whose label matches a schedule activity that
    is planned around `on` (YYYY-MM-DD) and not complete."""
    today = _day(on)
    if today is None:
        return {}
    planned: List[Dict[str, Any]] = []
    for a in activities or []:
        if not isinstance(a, dict) or a.get("kind") == "summary":
            continue
        start = _day(a.get("current_start")) or _day(a.get("baseline_start"))
        finish = _day(a.get("current_finish")) or _day(a.get("baseline_finish")) or start
        if not start or not finish or _day(a.get("actual_finish")):
            continue
        try:
            pct = float(a.get("percent_complete")) if a.get("percent_complete") is not None else None
        except (TypeError, ValueError):
            pct = None
        if pct is not None and pct >= 100:
            continue
        if start - timedelta(days=WINDOW_AFTER) <= today <= finish + timedelta(days=WINDOW_BEFORE):
            planned.append({"name": str(a.get("name") or ""), "tokens": _tokens(a.get("name")), "start": start,
                            "finish": finish})
    planned.sort(key=lambda p: (p["start"], p["name"]))
    out: Dict[str, str] = {}
    for c in chips or []:
        cid, label = getattr(c, "id", None), getattr(c, "label", None)
        toks = _tokens(label)
        if not cid or not toks or cid.startswith("other") or cid in out:
            continue
        for p in planned:
            if toks <= p["tokens"]:
                out[cid] = (f"scheduled: {p['name']} ({p['start'].strftime('%b')} {p['start'].day}"
                            f"–{p['finish'].strftime('%b')} {p['finish'].day})")
                break
    return dict(list(out.items())[:MAX_HINTS])
