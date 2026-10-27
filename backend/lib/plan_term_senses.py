"""ONE WORD, TWO THINGS ON A DRAWING.

A BULKHEAD on a roof plan is the stair or elevator enclosure that rises
above the roof; a BULKHEAD on a reflected ceiling plan is a dropped box of
ceiling hiding a duct. A superintendent asked about "kitchen soffits"
(2026-10-27) means the box over the cabinets, not the underside of an eave.
An answer that quotes the one for the other is wrong with a citation behind
it - the worst kind of wrong.

So for the few words that carry two construction meanings, the meaning is
taken from CONTEXT - the question's own words, the level it names - and,
when the question does not settle it, from what the returned sheet lines
actually print beside the word. When neither settles it the answer covers
each meaning separately, or asks which.

A SMALL TABLE OF DATA, NOT A SYNONYM LIST. Each meaning carries the words
that point to it; nothing here makes one term equal to another, and nothing
here touches what a record may bind (plan_search's gate). Pure, no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: term -> its meanings. `cues` are words that point to the meaning, in a
#: question or printed next to the term on a sheet; `levels` are set level
#: tokens (lib.plans.level_suggestion) whose sheets draw that meaning.
SENSES: Dict[str, Sequence[Dict[str, Any]]] = {
    "bulkhead": (
        {"name": "rooftop bulkhead",
         "gloss": "the stair or elevator enclosure that rises above the roof",
         "cues": ("roof", "rooftop", "stair", "stairs", "elevator", "elev",
                  "parapet", "penthouse"),
         "levels": ("ROOF", "BULKHEAD")},
        {"name": "ceiling bulkhead",
         "gloss": "a dropped box of ceiling (a soffit) that hides ducts or pipes",
         "cues": ("ceiling", "clg", "kitchen", "bathroom", "corridor", "hallway",
                  "soffit", "dropped", "duct", "ductwork", "gyp", "rcp", "reflected"),
         "levels": ()},
    ),
    "soffit": (
        {"name": "exterior soffit",
         "gloss": "the underside of an overhang, eave, canopy or balcony outside",
         "cues": ("exterior", "eave", "eaves", "overhang", "canopy", "balcony",
                  "facade", "cornice", "outside", "entrance", "vented"),
         "levels": ()},
        {"name": "interior soffit",
         "gloss": "a dropped box at an inside ceiling - over kitchen cabinets, "
                  "a bathroom or a duct run",
         "cues": ("kitchen", "cabinet", "cabinets", "ceiling", "clg", "bathroom",
                  "corridor", "duct", "ductwork", "interior", "gyp", "rcp"),
         "levels": ()},
    ),
    "chase": (
        {"name": "pipe/duct chase",
         "gloss": "an enclosed cavity framed around pipes, ducts or risers",
         "cues": ("pipe", "pipes", "duct", "ducts", "riser", "risers", "plumbing",
                  "shaft", "framed", "enclosure", "wall", "walls"),
         "levels": ()},
        {"name": "cut chase",
         "gloss": "a groove cut into masonry or concrete to bury conduit or pipe",
         "cues": ("masonry", "concrete", "cmu", "brick", "block", "groove",
                  "cut", "slab", "chased"),
         "levels": ()},
    ),
}


def _term_rx(term: str) -> "re.Pattern[str]":
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?:s|es)?(?![A-Za-z0-9])",
                      re.I)


def terms_in(text: str) -> List[str]:
    """The two-meaning terms `text` uses."""
    return [t for t in SENSES if _term_rx(t).search(str(text or ""))]


def _cue_hits(text: str, cues: Iterable[str], term: str) -> List[str]:
    low = _term_rx(term).sub(" ", str(text or "").lower())
    return [c for c in cues if re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", low)]


def resolve(term: str, question: str, level_tokens: Iterable[str] = (),
            records: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """{term, senses, meaning, why}. `meaning` is a sense name, or None when
    neither the question nor the sheets settle it."""
    senses = list(SENSES.get(term) or ())
    base = {"term": term, "senses": [{"name": s["name"], "gloss": s["gloss"]} for s in senses],
            "meaning": None, "why": ""}
    if not senses:
        return base
    lv = set(level_tokens or ())
    ctx = []
    for s in senses:
        hits = _cue_hits(question, s["cues"], term)
        hits += [f"the {t.lower()} level" for t in s["levels"] if t in lv]
        ctx.append(hits)
    with_ctx = [i for i, h in enumerate(ctx) if h]
    if len(with_ctx) == 1:
        i = with_ctx[0]
        return dict(base, meaning=senses[i]["name"],
                    why="the question says " + ", ".join(f"'{h}'" for h in ctx[i][:3]),
                    sense=senses[i])
    if with_ctx:
        return dict(base, why="the question points both ways")
    # THE SHEETS: what is printed beside the word in the lines returned.
    rx = _term_rx(term)
    seen: List[List[str]] = [[] for _ in senses]
    for r in records or []:
        q = str(r.get("quote") or "")
        if not rx.search(q):
            continue
        for i, s in enumerate(senses):
            if _cue_hits(q, s["cues"], term) and r.get("sheet_number"):
                if r["sheet_number"] not in seen[i]:
                    seen[i].append(str(r["sheet_number"]))
    shown = [i for i, s in enumerate(seen) if s]
    if len(shown) == 1:
        i = shown[0]
        return dict(base, meaning=senses[i]["name"],
                    why="the sheets that print it show only this meaning ("
                        + ", ".join(seen[i][:3]) + ")", sense=senses[i])
    return dict(base, why=("the sheets show both meanings" if shown
                           else "nothing in the question or the sheets settles it"))


def levels_for(resolved: Dict[str, Any]) -> List[str]:
    """Set level tokens whose sheets draw the resolved meaning."""
    s = resolved.get("sense") or {}
    return list(s.get("levels") or ())


def describe(resolved: Dict[str, Any]) -> str:
    """The instruction line for one term."""
    senses = resolved.get("senses") or []
    # Lettered, not numbered: a number the answer copies is a number the
    # gate must find printed on a sheet.
    both = "; ".join(f"({'abcdef'[i]}) {s['name']} = {s['gloss']}"
                     for i, s in enumerate(senses))
    head = (f"'{resolved['term']}' means two different things on drawings - "
            f"never treat one as the other: {both}.")
    if resolved.get("meaning"):
        return (f"{head} Here it means the {resolved['meaning']} ({resolved['why']}): "
                f"answer about that only, and do not use a line about the other "
                f"meaning as if it were this one.")
    return (f"{head} The question does not settle which ({resolved.get('why')}): "
            f"answer each meaning separately, each from its own lines, or ask "
            f"which one they mean.")
