"""Workers who check in after the Daily Jobsite Log is signed: what the log owes them.

OPERATOR RULING 2026-11-12: a worker who checks in after the day's log is signed
"has to be included in the books", automatically. #1049 did that with ONE
instrument -- a full correction of the log, which clears the signature and makes
the CP re-sign the whole document.

OPERATOR RULING 2026-11-18 (this module): that is too much for most late
arrivals. A man who works for a sub that is ALREADY on the signed log, in the
trade the log already describes, changes ONE number -- how many were on site --
and the work the CP described is already the sub's work. Making the CP re-sign
a whole log for that is a signature spent on nothing.

So there are two cases, and the rule that separates them is a question about
the SIGNED DOCUMENT, not about the worker:

    Does the signed log already have a crew card this man belongs on?

    YES  -> the man is RECORDED on the signed log as "arrived after signing"
            (`late_arrivals`, a top-level field, never inside `data`). The CP
            signs nothing. The sheet says so, in the same words and the same
            place it says a photograph was added after filing.

    NO   -> a crew the CP never described (a sub that is not on the log, or a
            second trade of a sub that is). That crew needs a card with work on
            it, and the work has to be written and signed by a person, so the
            correction #1049 opens is still the right instrument.

A SIGNATURE IS AN ATTESTED ACT AND NOTHING HERE SIGNS FOR ANYONE. What is
recorded is a fact the GATE already holds (who badged in, when, for which sub);
it is printed apart from the signed content and labelled as not part of what the
CP attested to. Same standard as `append_activity_photo`, for the same reason.

PURE. No database, no clock, no server import: the route reads and writes, this
decides. That is what lets every edge below be pinned by a test that needs
nothing running.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

#: The gate writes this literal when a worker's subcontractor (or trade) is not
#: on the project roster. It is a placeholder, not a company.
UNASSIGNED = "unassigned"

#: The words the sheet and the screen carry. English first, then Spanish.
LATE_ARRIVALS_LABEL = "Arrived after signing"
LATE_ARRIVALS_LABEL_ES = "Llegaron después de la firma"


def _key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _named(value: Any) -> str:
    """The comparison key, or "" when the value is blank or the placeholder."""
    k = _key(value)
    return "" if k in ("", UNASSIGNED) else k


def crew_cards(log: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(company, trade) of every crew card on the log, as comparison keys.

    A card with no company is a loose row for one unassigned man; it is not a
    crew a late arrival can join, so it is not listed.
    """
    out: List[Tuple[str, str]] = []
    data = (log or {}).get("data")
    for a in (data.get("activities") if isinstance(data, dict) else None) or []:
        if not isinstance(a, dict):
            continue
        company = _named(a.get("company"))
        if company:
            out.append((company, _named(a.get("trade"))))
    return out


def has_crew_card(log: Dict[str, Any], worker: Dict[str, Any]) -> bool:
    """True when the signed log already has a card this worker belongs on.

    THE MATCH IS THE SCREEN'S OWN. The daily log keys a crew on (company,
    trade), and a stored card with no trade may adopt the company's one crew
    (`reconcileCrewsWithRoster`). This mirrors both, so the two surfaces cannot
    disagree about whether a man "was already on the log".

    EVERY DOUBT RESOLVES TOWARD THE CORRECTION, which costs the CP one extra
    signature, and never toward a silent record, which would put a man on a
    crew the CP did not describe:

        no company / the placeholder      -> False  (nobody to put him under)
        company not on the log            -> False  (a new sub)
        company on the log, other trade   -> False  (a second crew needs work)
        two trades on the log, he has none-> False  (cannot tell which)
    """
    company = _named((worker or {}).get("company"))
    if not company:
        return False
    cards = [t for c, t in crew_cards(log) if c == company]
    if not cards:
        return False
    trade = _named((worker or {}).get("trade"))
    if trade in cards:
        return True
    # One crew for this company, and either side leaves its trade unsaid.
    return len(cards) == 1 and (not cards[0] or not trade)


def split_late(log: Dict[str, Any],
               late: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(joins an existing card, needs a card the CP must write), order kept."""
    joins: List[Dict[str, Any]] = []
    needs: List[Dict[str, Any]] = []
    for w in late:
        (joins if has_crew_card(log, w) else needs).append(w)
    return joins, needs


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def record_row(worker: Dict[str, Any], recorded_at: datetime) -> Dict[str, Any]:
    """The row written onto the signed log. A fact copied from the gate."""
    return {
        "worker_id": str(worker.get("worker_id") or ""),
        "worker_name": str(worker.get("worker_name") or "").strip(),
        "company": str(worker.get("company") or "").strip(),
        "trade": str(worker.get("trade") or "").strip(),
        "checked_in_at": _iso(worker.get("check_in_time")),
        "recorded_at": recorded_at,
    }


def recorded_ids(log: Dict[str, Any]) -> set:
    return {str(r.get("worker_id")) for r in ((log or {}).get("late_arrivals") or [])
            if isinstance(r, dict) and r.get("worker_id")}


def recorded_rows(log: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What the log carries, as plain data a sheet or a screen can draw."""
    return [r for r in ((log or {}).get("late_arrivals") or []) if isinstance(r, dict)]
