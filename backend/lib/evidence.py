"""ONE SHAPE FOR EVERY PIECE OF PROGRESS EVIDENCE, AND ONE LADDER OF TRUST.

Every source the progress engine reads (filed daily logs, photos, gate
check-ins, WhatsApp statements, signed logbooks, punch closeouts, DOB records,
the confirmed schedule file) produces items in this shape, so the engine combines
them in one place and every answer can say where each fact came from.

THE LADDER, strongest first. A higher rung never erases a lower one; a later item
of the same rung supersedes an earlier one only for the same subject, place and
work, and both are kept.

  verified   an authoritative record outside the job's own people: a DOB Letter
             of Completion / sign-off, an agency letter on file.
  confirmed  signed or closed inside LeveLog by the responsible party: a pour log
             filed by the competent person, a punch item the superintendent
             closed, a signed logbook entry that states completion.
  attested   a named person's statement through WhatsApp or the app ("plumbing
             rough passed on 3", "6 done"), kept with their words.
  observed   a photo the vision index describes as showing the work. Never more.
  reported   a filed daily-log crew row saying the crew did the work there.
  estimate   computed by LeveLog (a forecast, a projection). NEVER a fact, never
             shown without the word "estimate" and its basis.

UNKNOWN is not a rung: it is the absence of items, and it never means not done.
No item carries a percent unless a source stated one; a stated percent keeps the
source's name ("schedule file states 40%", "requisition bills 80%").

Pure: no database, no network.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

KINDS = ("verified", "confirmed", "attested", "observed", "reported", "estimate")
_RANK = {k: i for i, k in enumerate(KINDS)}

#: What an item says about the work.
CLAIMS = ("done", "in_progress", "started", "failed", "scheduled", "present", "blocked",
          # A person's answer to a targeted confirmation (lib/confirmation_queue):
          # "not yet", "nobody was there", and "don't know" -- kept as said, so a
          # "don't know" is never read as a no. status() reads none of them.
          "not_yet", "absent", "dont_know")


def item(kind: str, claim: str, *, source: str, ref: str, project_id: Any, node: Optional[str] = None,
         levels: Sequence[str] = (), space: Optional[str] = None, sub: Optional[str] = None,
         on: Optional[date] = None, by: Optional[str] = None, quote: Optional[str] = None,
         shared: bool = False, stated_percent: Optional[float] = None,
         basis: Optional[str] = None, note: Optional[str] = None,
         said_at: Optional[datetime] = None, candidates: Sequence[str] = ()) -> Dict[str, Any]:
    """One piece of evidence. `source` names the collection or feed, `ref` the
    record inside it (so it can be shown and audited). `shared`: the record names
    several places together ("floors 1-4") and is not about one alone.
    `basis` is required for an estimate. `said_at`: when the statement or record
    was made (a report's created_at), which orders two items of one day and
    places an undated one: it is never shown as the date of the work.
    `candidates`: the levels the record NAMED but that could not be placed
    (the project does not have them, or its levels could not be read): the
    item's `levels` is then [] -- place unknown, never the building's."""
    if kind not in _RANK:
        raise ValueError(f"unknown evidence kind {kind!r}")
    if claim not in CLAIMS:
        raise ValueError(f"unknown claim {claim!r}")
    if kind == "estimate" and not basis:
        raise ValueError("an estimate needs its basis")
    return {"kind": kind, "claim": claim, "source": source, "ref": str(ref), "project_id": str(project_id),
            "node": node, "levels": sorted(set(levels)), "space": space, "sub": sub, "on": on, "by": by,
            "quote": quote, "shared": bool(shared), "stated_percent": stated_percent, "basis": basis, "note": note,
            "said_at": said_at, "candidates": sorted(set(candidates or ()))}


def rank(kind: str) -> int:
    """0 is strongest."""
    return _RANK[kind]


def _naive(at: Any) -> Optional[datetime]:
    if not isinstance(at, datetime):
        return None
    return at.astimezone(timezone.utc).replace(tzinfo=None) if at.tzinfo else at


def order_key(i: Dict[str, Any]) -> Tuple[int, int, datetime]:
    """THE ONE ORDER of "newest" (owner ruling): by the record's own date; an
    undated record by the day it was said (it cannot have happened later);
    within a day, an undated record last, then by when it was said. A record
    with neither is oldest. So an earlier dated pass can never hide a later
    undated failure."""
    on = i.get("on")
    on = on.date() if isinstance(on, datetime) else on
    said = _naive(i.get("said_at"))
    if isinstance(on, date):
        return (on.toordinal(), 0, said or datetime.min)
    if said:
        return (said.date().toordinal(), 1, said)
    return (0, 1, datetime.min)


def newest(items: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pool = list(items)
    return max(pool, key=order_key) if pool else None


def strongest(items: Iterable[Dict[str, Any]], *, facts_only: bool = True) -> Optional[Dict[str, Any]]:
    """The strongest item, newest first within a rung. An estimate is never a fact."""
    pool = [i for i in items if not (facts_only and i["kind"] == "estimate")]
    if not pool:
        return None
    best = min(rank(i["kind"]) for i in pool)
    return newest(i for i in pool if rank(i["kind"]) == best)


def about(items: Iterable[Dict[str, Any]], *, node: Optional[str] = None, level: Optional[str] = None,
          sub: Optional[str] = None) -> List[Dict[str, Any]]:
    """The items about this work, place and sub (None matches anything)."""
    out = []
    for i in items:
        if node is not None and i["node"] != node:
            continue
        if level is not None and level not in i["levels"]:
            continue
        if sub is not None and (i["sub"] or "").lower() != sub.lower():
            continue
        out.append(i)
    return out


#: Claims that say work was going on (or present). Anything else -- a booking,
#: "not yet", "blocked", "nobody was there", "don't know" -- says no work was seen.
WORK_CLAIMS = ("done", "in_progress", "started", "failed", "present")
_STRONG = ("verified", "confirmed", "attested")


def status(items: Sequence[Dict[str, Any]]) -> str:
    """One word for a package from its items, strongest first:

      done_<rung> | failed_<rung>   a done / failed at attested or stronger (a
                                    failure stated after a pass wins at a rung)
      in_progress_<rung>            work stated or signed in progress at
                                    attested or stronger ("partly passed", a
                                    pour in progress, "started")
      in_progress_observed          a photo shows the work
      reported                      a REPORTED item says work went on (a log
                                    row, the schedule file's actual): only then
      scheduled_<rung>              only a booking ("inspection booked for
                                    the 14th"): booked is not in progress
      not_yet_<rung> | blocked_<rung>  only a person's "not yet" / "blocked"
      unknown                       nothing, or only "don't know" / "nobody
                                    was there": unknown is never not done

    Nothing below 'attested' can say done."""
    facts = [i for i in items if i["kind"] != "estimate"]
    if not facts:
        return "unknown"
    for kind in _STRONG:
        last = newest(i for i in facts if i["kind"] == kind and i["claim"] in ("done", "failed"))
        if last:
            return f"{last['claim']}_{kind}"
    for kind in _STRONG:
        if any(i["kind"] == kind and i["claim"] in WORK_CLAIMS for i in facts):
            return f"in_progress_{kind}"
    if any(i["kind"] == "observed" for i in facts):
        return "in_progress_observed"
    if any(i["kind"] == "reported" and i["claim"] in WORK_CLAIMS for i in facts):
        return "reported"
    for claim in ("scheduled", "blocked", "not_yet"):
        pool = [i for i in facts if i["claim"] == claim]
        if pool:
            return f"{claim}_{min(pool, key=lambda i: rank(i['kind']))['kind']}"
    return "unknown"
