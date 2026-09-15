"""Guess which project a WhatsApp group belongs to, from the group's name.

WHAT THIS IS FOR. A superintendent adds the bot to "Boyland - Framing" and
should not then have to find that group in a list and pair it with a project by
hand. The name he already chose almost always says which job it is. This reads
it and offers ONE answer, which a person then confirms.

IT NEVER LINKS ANYTHING. Everything here is a suggestion that pre-fills a
dropdown. The confirm is a separate, authenticated, tenant-checked action —
see the pending-groups routes in server.py. A wrong guess here costs a person
one tap; an auto-link would cost a crew's daily log landing on another
customer's job.

── WHY NOT token_set_ratio ON THE WHOLE STRING ─────────────────────────────

That was the first design and it fails the cases it exists for. Measured, at
the 80 threshold the spec asks for:

    "Boyland - Framing"  vs "588 Thomas S Boyland St"   58.3   MISS
    "Walworth crew"      vs "8 Walworth St"             76.2   MISS

Both are obvious to a human and both lose, for the same reason: a group name is
a street plus a word about the crew, and an address is a house number plus a
street plus a suffix. Comparing the wholes drowns the one token that carries the
meaning in four that carry none. Raising the threshold to catch them would let
"Brooklyn jobs" match anything in Brooklyn.

So the comparison is field-wise. The group name is stripped to its meaningful
tokens and the address to its STREET tokens, and those are compared. The same
two cases then score 100 and 100, and "Brooklyn jobs" scores zero because after
the borough is removed there is nothing left to compare.

── THE NOISE LISTS ARE THE WHOLE DESIGN, SO THEY ARE EXPLICIT ──────────────

Three things get removed from a group name before matching, and each removal is
a decision:

  CREW WORDS ("crew", "chat", "site", "job", "team") say nothing about WHICH
  job. Left in, they match every project equally and drag every score toward
  the middle.

  TRADE WORDS ("framing", "concrete", "electrical") are worse than useless:
  several groups on one project differ only by trade, so a trade token pushes
  two groups toward the SAME project rather than telling them apart.

  PLACE WORDS (borough names, "nyc") match a whole city of projects. "Brooklyn
  jobs" must return nothing, and it is a named test case for that reason.

A name that is entirely noise — "Site chat 2" — leaves no tokens and returns no
suggestion, which is correct: nothing about it says which job it is.

── ONE CLEAR WINNER OR NOTHING ─────────────────────────────────────────────

Two projects over the threshold means the name is ambiguous, and the honest
response to an ambiguous name is an empty dropdown rather than a coin flip. A
person looking at an unfilled row knows a decision is needed. A person looking
at a confidently wrong pre-fill confirms it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# The score a field comparison must reach. From the spec; also the point at
# which "Boyland" stops matching "Bolander" in the street lists this sees.
MATCH_THRESHOLD = 80.0

# Words about the CONVERSATION, not the job.
_CREW_WORDS = frozenset({
    "crew", "crews", "chat", "chats", "group", "team", "guys", "boys",
    "site", "jobsite", "job", "jobs", "project", "work", "works",
    "wa", "whatsapp", "main", "general", "daily", "info", "updates",
})

# Words about the TRADE. Two groups on one job differ by exactly these, so a
# trade token actively pushes them together instead of telling them apart.
_TRADE_WORDS = frozenset({
    "framing", "framers", "concrete", "cement", "electrical", "electric",
    "electricians", "plumbing", "plumbers", "hvac", "mechanical", "sprinkler",
    "demo", "demolition", "masonry", "roofing", "steel", "drywall",
    "carpentry", "carpenters", "super", "supers", "safety", "cleaning",
    "scaffold", "scaffolding", "facade", "interior", "exterior",
})

# Words that match a whole borough's worth of projects.
_PLACE_WORDS = frozenset({
    "nyc", "ny", "new", "york", "brooklyn", "queens", "bronx", "manhattan",
    "staten", "island", "bklyn", "bk", "city",
})

# Street-type suffixes, removed from BOTH sides so "Walworth St" and
# "Walworth" are the same street.
_STREET_TYPES = frozenset({
    "st", "street", "ave", "av", "avenue", "blvd", "boulevard", "rd", "road",
    "pl", "place", "ct", "court", "dr", "drive", "ln", "lane", "way", "sq",
    "square", "ter", "terrace", "pkwy", "parkway", "hwy", "highway",
    "n", "s", "e", "w", "north", "south", "east", "west",
})

_STOP = _CREW_WORDS | _TRADE_WORDS | _PLACE_WORDS | _STREET_TYPES

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: Optional[str]) -> List[str]:
    """Lowercase alphanumeric runs. Punctuation is a separator, so
    "Boyland - Framing", "Boyland/Framing" and "Boyland, framing" are one
    thing."""
    return _TOKEN_RE.findall((text or "").lower())


def name_tokens(group_name: Optional[str]) -> List[str]:
    """What is left of a group name once the words that say nothing are gone.

    Digits survive — a house number is one of the strongest signals there is,
    and "588 Boyland" should match on either half."""
    return [t for t in _tokens(group_name) if t not in _STOP]


def street_tokens(address: Optional[str]) -> List[str]:
    """The street part of an address: no house number, no suffix, no
    direction.

    THE LEADING NUMBER IS DROPPED HERE AND MATCHED SEPARATELY. Leaving it in
    lets "8 Walworth" score against "8 Something Else" on the strength of a
    single digit, which at these string lengths is a large share of the
    ratio."""
    toks = _tokens(address)
    if toks and toks[0].isdigit():
        toks = toks[1:]
    return [t for t in toks if t not in _STOP and not t.isdigit()]


def house_number(address: Optional[str]) -> str:
    """The leading number of an address, or ''."""
    toks = _tokens(address)
    return toks[0] if toks and toks[0].isdigit() else ""


def _ratio(a: List[str], b: List[str]) -> float:
    """token_set_ratio over two token lists, 0.0 when either side is empty.

    Imported lazily so this module stays importable — and unit-testable — in
    an environment that has not installed rapidfuzz yet. A missing library
    degrades to "no suggestion", which is the safe direction: the screen still
    works, the dropdown is simply empty."""
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover - exercised by the import test
        return 0.0
    return float(fuzz.token_set_ratio(" ".join(a), " ".join(b)))


def score_project(group_name: Optional[str], project: Dict[str, Any]) -> float:
    """How strongly this group name points at this project, 0-100.

    Every field is scored and the best one wins, because a group may be named
    after any of them: the street, the nickname somebody set, or — for the
    people who work off filings — the BIN.
    """
    gtoks = name_tokens(group_name)
    if not gtoks:
        return 0.0

    best = 0.0

    # A BIN or BBL in the name is not a guess. These are unique, nobody types
    # one by accident, and an exact hit outranks everything else.
    exact_ids = {
        str(project.get("nyc_bin") or "").strip(),
        str(project.get("bbl") or "").strip(),
    }
    exact_ids.discard("")
    if exact_ids & set(gtoks):
        return 100.0

    # The nickname exists for exactly this: a name a person chose for the job,
    # compared against a name a person chose for the group.
    nickname = project.get("nickname")
    if nickname:
        best = max(best, _ratio(gtoks, name_tokens(nickname)))

    # The street.
    addr = project.get("address") or project.get("location") or ""
    stoks = street_tokens(addr)
    street_score = _ratio(gtoks, stoks)
    best = max(best, street_score)

    # The house number, which only counts ALONGSIDE a street hit. On its own a
    # number is far too weak — "8" appears in a great many addresses — but
    # "588 Boyland" against "588 Thomas S Boyland St" is two independent
    # agreements and deserves to clear on its own.
    hn = house_number(addr)
    if hn and hn in gtoks and street_score >= 50.0:
        best = max(best, 100.0)

    # The project's own name, last and unweighted. Often it IS the address,
    # in which case this adds nothing; when it is something else it is still
    # a thing a person might name a group after.
    best = max(best, _ratio(gtoks, name_tokens(project.get("name"))))

    return best


def suggest_project_for_group(
    projects: List[Dict[str, Any]],
    group_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    """The one project this group is probably for, or None.

    `projects` are the caller's own company's projects — the tenant scope is
    resolved by the caller, which is where the authenticated user is. This
    function has no database handle and cannot widen it.

    Returns {"project_id", "confidence"} or None. None means one of three
    things, and they are deliberately indistinguishable to the caller because
    the response is the same: nothing scored high enough, the name carried no
    signal, or two projects tied. Every one of them means "ask the person".
    """
    if not projects or not group_name:
        return None

    scored = []
    for p in projects:
        s = score_project(group_name, p)
        if s >= MATCH_THRESHOLD:
            scored.append((s, p))

    if len(scored) != 1:
        # Zero is no answer. Two or more is an ambiguous name, and a coin flip
        # presented as a confident pre-fill is worse than an empty dropdown —
        # an unfilled row tells the person a decision is needed.
        return None

    score, project = scored[0]
    pid = project.get("id") or project.get("_id")
    if pid is None:
        return None
    return {"project_id": str(pid), "confidence": round(score / 100.0, 3)}


__all__ = [
    "suggest_project_for_group",
    "score_project",
    "name_tokens",
    "street_tokens",
    "house_number",
    "MATCH_THRESHOLD",
]
