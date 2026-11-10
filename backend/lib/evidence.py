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

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence

KINDS = ("verified", "confirmed", "attested", "observed", "reported", "estimate")
_RANK = {k: i for i, k in enumerate(KINDS)}

#: What an item says about the work.
CLAIMS = ("done", "in_progress", "started", "failed", "scheduled", "present", "blocked")


def item(kind: str, claim: str, *, source: str, ref: str, project_id: Any, node: Optional[str] = None,
         levels: Sequence[str] = (), space: Optional[str] = None, sub: Optional[str] = None,
         on: Optional[date] = None, by: Optional[str] = None, quote: Optional[str] = None,
         shared: bool = False, stated_percent: Optional[float] = None,
         basis: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """One piece of evidence. `source` names the collection or feed, `ref` the
    record inside it (so it can be shown and audited). `shared`: the record names
    several places together ("floors 1-4") and is not about one alone.
    `basis` is required for an estimate."""
    if kind not in _RANK:
        raise ValueError(f"unknown evidence kind {kind!r}")
    if claim not in CLAIMS:
        raise ValueError(f"unknown claim {claim!r}")
    if kind == "estimate" and not basis:
        raise ValueError("an estimate needs its basis")
    return {"kind": kind, "claim": claim, "source": source, "ref": str(ref), "project_id": str(project_id),
            "node": node, "levels": sorted(set(levels)), "space": space, "sub": sub, "on": on, "by": by,
            "quote": quote, "shared": bool(shared), "stated_percent": stated_percent, "basis": basis, "note": note}


def rank(kind: str) -> int:
    """0 is strongest."""
    return _RANK[kind]


def strongest(items: Iterable[Dict[str, Any]], *, facts_only: bool = True) -> Optional[Dict[str, Any]]:
    """The strongest item, newest first within a rung. An estimate is never a fact."""
    pool = [i for i in items if not (facts_only and i["kind"] == "estimate")]
    if not pool:
        return None
    return sorted(pool, key=lambda i: (rank(i["kind"]), -(i["on"].toordinal() if isinstance(i["on"], date) else 0)))[0]


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


def status(items: Sequence[Dict[str, Any]]) -> str:
    """One word for a package from its items: done_verified | done_confirmed |
    done_attested | failed_attested | in_progress_observed | reported | unknown.
    A failure stated after a pass wins at the same rung; nothing below 'attested'
    can say done."""
    facts = [i for i in items if i["kind"] != "estimate"]
    if not facts:
        return "unknown"
    for kind in ("verified", "confirmed", "attested"):
        mine = sorted((i for i in facts if i["kind"] == kind and i["claim"] in ("done", "failed")),
                      key=lambda i: i["on"].toordinal() if isinstance(i["on"], date) else 0)
        if mine:
            last = mine[-1]
            return f"{last['claim']}_{kind}"
    if any(i["kind"] == "observed" for i in facts):
        return "in_progress_observed"
    return "reported"
