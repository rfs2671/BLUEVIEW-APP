"""CANONICAL WORK LOCATIONS. A CONTROLLED TABLE, NOT A PARSER AND NOT A MODEL.

`work_locations` on an activity row is free text. Across every activity row on
production -- 112 rows, 85 carrying a location, 27 blank -- there are 25
distinct strings, and one floor is spelled four ways: `1st floor`, `1st fl`,
`First floor`, `1 floor`. Printing those as four areas is accurate about the
database and useless to a reader; collapsing them by guessing is the report
asserting structure the product does not have.

So the investor layer maps recorded strings to canonical tokens through the
table below, and THE RAW STRING STAYS ON THE RECORD. The legal renderers keep
printing `work_locations` verbatim, which is what an inspector needs and what
the conducting party actually typed.

── THE THREE RUNTIME PROTECTIONS ─────────────────────────────────────────────

AN UNKNOWN STRING IS PRESERVED, AND NEVER PRINTED. `resolve` returns it in
`unmapped`, where coverage counts it. It is never attached to a neighbouring
token: normalisation is not allowed to silently improve bad source data. It is
also not printed on the page any more -- ruled 2026-10-10, after the tile read
"Unmapped source value: 3rd Floor, 4th Floor, ..." on an investor document. An
area the table cannot read is left off; it is not announced.

AN AMBIGUOUS STRING IS NEVER NORMALISED AUTOMATICALLY. This table holds exact
keys only. There is no fuzzy match, no stemming, no edit distance and no
model -- a string it has not seen cannot be guessed at.

ONE SHAPE IS RECOGNISED, AND IT IS THE APP'S OWN. The daily log's location
chips are generated, not typed: `buildingLevelChips` in
frontend/src/utils/dailyJobsiteModel.js emits "Sub-cellar", "Cellar",
"<ordinal> Floor", "Mezzanine" and "Roof", and saves the CP's picks as ONE
comma-joined string ("3rd Floor, 4th Floor"). This table was built from older
hand-typed text and knew none of them, so every chip-built row resolved to
nothing. `_chip_tokens` reads exactly that closed set -- "<n>st|nd|rd|th
Floor" and the four named levels -- and a comma-joined value is split into its
parts only after the whole string has missed (one hand-typed key, "Foundation,
Ex. 2&4", carries a comma of its own).

COVERAGE IS MEASURED AND RETURNED. A table that silently stops matching most of
the corpus looks exactly like a table that is working, and the only difference
is a number nobody was computing.

── FOUR DECISIONS THAT ARE THE OPERATOR'S, NOT THIS TABLE'S ─────────────────

GROUND IS ITS OWN TOKEN AND NOT LEVEL 1. In New York the ground floor and the
first floor are often the same storey and sometimes are not. A lookup table
does not get to decide which on a given building; a project override may.

BELOW GRADE IS FOUR TOKENS, NOT ONE. `UG`, `B`, `FDN` and `EX` describe
materially different areas and stages, and a scaffold log and a foundation
inspection are not about the same place.

`EX` KEEPS ITS ABBREVIATION IN BOTH LABEL COLUMNS. The reading that it means
excavation rests on three rows, and three rows is not enough to turn an
abbreviation into a factual label on an investor document. When it is
confirmed, only its entry in `LABELS` changes and no stored mapping moves.

A SPAN EXPANDS. `Floors 3-5` contributes three tokens, because the rail answers
where work occurred rather than how many strings were typed.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: The scope token. DELIBERATELY NOT IN `DISPLAY_ORDER`.
#:
#: "Throughout site" is a statement about the extent of the work, not another
#: storey. Counting it as an area makes the rail say three where the building
#: has two, and on a day when it is the only thing recorded it makes the rail
#: say one area without naming any -- which is worse than saying nothing.
#: Excluding it from the order makes it STRUCTURALLY INCAPABLE of being
#: counted as a place, rather than relying on every call site to remember.
SCOPE = "SITE"

#: The closed set of canonical tokens, in display order. A token absent from
#: here cannot be rendered, which is what stops one being invented at a call
#: site.
#:
#: IT READS LIKE AN ELEVATION: roof, the highest numbered level down to the
#: first, then ground, then below grade, then the public way. An earlier draft
#: ran bottom-upward and produced "UG / L1" where a reader scanning a section
#: drawing expects "L1 / UG".
#:
#: THE LEVELS RUN TO `MAX_LEVEL`, not to five. The app offers a chip for every
#: storey the project declares, and 588 Thomas files a 4th Floor; a closed set
#: that stopped at L5 would quietly drop the 6th floor of the next building.
#: The mezzanine sits between the 2nd and the 1st, and the cellars below
#: ground, which is where a section drawing puts them.
MAX_LEVEL = 99
LEVELS: Tuple[str, ...] = tuple(f"L{n}" for n in range(MAX_LEVEL, 0, -1))
DISPLAY_ORDER: Tuple[str, ...] = (
    ("ROOF",) + LEVELS[:-1] + ("MEZZ", "L1", "G", "CELLAR", "SUBCELLAR",
                               "B", "UG", "FDN", "EX", "SW")
)

#: (rail, prose). Short for the five-second rail, long for the activity rows
#: and any sentence. The rail stays terse on purpose: a reader who sees
#: "B / UG" learns which is which from the rows beneath, and lengthening every
#: token to cover that one case would bloat the one element built for scanning.
LABELS: Dict[str, Tuple[str, str]] = {
    "ROOF": ("Roof", "Roof"),
    **{f"L{n}": (f"L{n}", f"Level {n}") for n in range(1, MAX_LEVEL + 1)},
    "MEZZ": ("Mezzanine", "Mezzanine"),
    "CELLAR": ("Cellar", "Cellar"),
    "SUBCELLAR": ("Sub-cellar", "Sub-cellar"),
    "G": ("G", "Ground"),
    "B": ("B", "Basement"),
    "UG": ("UG", "Underground"),
    "FDN": ("FDN", "Foundation"),
    "EX": ("EX", "EX"),
    "SW": ("SW", "Sidewalk"),
    SCOPE: ("Sitewide", "Sitewide"),
}

#: EVERY KEY IS A STRING THAT EXISTS IN PRODUCTION. Nothing is inferred from
#: shape, and the count beside each group is how many activity rows carry it.
VOCABULARY: Dict[str, Tuple[str, ...]] = {
    # Level 1 -- 48 rows, four spellings.
    "1st floor": ("L1",),
    "1st fl": ("L1",),
    "first floor": ("L1",),
    "1 floor": ("L1",),
    # Spans -- one string, more than one area.
    "1st 2nd floor": ("L1", "L2"),
    "1st and 2nd floor": ("L1", "L2"),
    "2-3 floor": ("L2", "L3"),
    "floors 3-5": ("L3", "L4", "L5"),
    # Ground -- 8 rows. Its own token; see the module docstring.
    "ground": ("G",),
    "ground floor": ("G",),
    "ground level": ("G",),
    # Below grade -- four different things.
    "underground": ("UG",),
    "basement": ("B",),
    "foundation footings": ("FDN",),
    "foundation front": ("FDN",),
    "foundation grade": ("FDN",),
    "foundation walls ex 2&4": ("FDN", "EX"),
    "foundation, ex. 2&4": ("FDN", "EX"),
    "ex 2-4": ("EX",),
    # The whole job -- four spellings, one of them a typo, all real.
    "all areas": (SCOPE,),
    "t/o": (SCOPE,),
    "through": (SCOPE,),
    "thrugghout site": (SCOPE,),
    # Exterior / public way. Load-bearing for the sidewalk-shed log.
    "sidewalk": ("SW",),
}


def _key(value) -> str:
    return " ".join(str(value or "").split()).lower()


#: The four named chips `buildingLevelChips` emits, keyed as `_key` spells them.
_NAMED_CHIPS: Dict[str, str] = {
    "roof": "ROOF",
    "mezzanine": "MEZZ",
    "cellar": "CELLAR",
    "sub-cellar": "SUBCELLAR",
}

_ORDINAL_FLOOR = re.compile(r"^(\d{1,2})(st|nd|rd|th) floor$")


def _chip_tokens(key: str) -> Optional[Tuple[str, ...]]:
    """The token for one chip label the app generates, or None.

    THE SUFFIX MUST BE THE RIGHT ONE. "2th Floor" is not a label the app can
    produce, so it is not one this reads; a typed string that merely looks
    like a chip goes through the table like any other.
    """
    if key in _NAMED_CHIPS:
        return (_NAMED_CHIPS[key],)
    hit = _ORDINAL_FLOOR.match(key)
    if not hit:
        return None
    n = int(hit.group(1))
    if not 1 <= n <= MAX_LEVEL or hit.group(2) != ordinal_suffix(n):
        return None
    return (f"L{n}",)


def ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def ordinal(n: int) -> str:
    return f"{n}{ordinal_suffix(n)}"


def level_number(token: str) -> Optional[int]:
    """3 for "L3"; None for every token that is not a numbered storey."""
    if token.startswith("L") and token[1:].isdigit():
        return int(token[1:])
    return None


class Resolution:
    """What the page may say about where the work was.

    Four answers, and three of them are not the area list -- which is the whole
    reason this is an object rather than a list of tokens.
    """

    __slots__ = ("areas", "sitewide", "unmapped", "located", "mapped")

    def __init__(self, areas, sitewide, unmapped, located, mapped):
        self.areas: List[str] = areas
        self.sitewide: bool = sitewide
        self.unmapped: List[str] = unmapped
        self.located: int = located
        self.mapped: int = mapped

    @property
    def coverage(self) -> Optional[float]:
        """Mapped rows over located rows, as a percentage, or None.

        NONE WHEN NOTHING WAS LOCATED, never 100. A day with no recorded
        location has not achieved perfect normalisation; it has nothing to
        normalise, and reporting that as 100% would hide degradation behind
        the days that happen to be empty.
        """
        return (100.0 * self.mapped / self.located) if self.located else None

    def rail(self) -> Tuple[str, str, List[str]]:
        """(value, label, notes) for the five-second rail. Three shapes.

        NAMED AREAS carry the count and the tokens. SCOPE ALONE reads Sitewide
        and says no specific area was recorded. NOTHING MAPPED reads LOCATION
        rather than ACTIVE AREAS and says nothing beneath -- "no area
        recorded" would claim the system knows there were none, when in fact
        a location WAS recorded and this table could not read it. What it
        could not read is not printed either (see the module docstring).
        """
        if self.areas:
            notes = (["Sitewide activity also recorded"] if self.sitewide
                     else [])
            return (str(len(self.areas)), "Active areas",
                    [" / ".join(LABELS[t][0] for t in self.areas)] + notes)
        if self.sitewide:
            return ("Sitewide", "Recorded activity",
                    ["No specific area recorded"])
        if self.unmapped:
            return ("—", "Location", [])
        return ("—", "Location", ["No location recorded"])

    def prose(self) -> str:
        """The long form, for an activity row."""
        if self.areas:
            return " / ".join(LABELS[t][1] for t in self.areas)
        if self.sitewide:
            return LABELS[SCOPE][1]
        return ""


def resolve(raw_values: Iterable,
            overrides: Optional[Dict[str, Sequence[str]]] = None) -> Resolution:
    """Canonical tokens for recorded strings, plus everything else the page
    needs to be honest about them.

    `overrides` is a PER-PROJECT map, applied over the global table for a
    building that spells something its own way -- or that establishes, for
    itself, that its ground floor and first floor are the same storey. It is
    checked first so a project can correct the global table, never the reverse.
    """
    table = dict(VOCABULARY)
    for k, v in (overrides or {}).items():
        table[_key(k)] = tuple(v)

    def lookup(key: str) -> Optional[Tuple[str, ...]]:
        hit = table.get(key)
        return hit if hit is not None else _chip_tokens(key)

    tokens, unmapped, located, mapped = set(), [], 0, 0
    sitewide = False
    for value in raw_values:
        key = _key(value)
        if not key:
            continue
        located += 1
        # THE WHOLE STRING FIRST, then its comma-separated parts. A part that
        # reads is kept even when a sibling does not, because "3rd Floor,
        # Stair 2" says where the work was as surely as "3rd Floor" does.
        hit = lookup(key)
        if hit is None:
            parts = [" ".join(s.split()) for s in str(value).split(",")]
            parts = [p for p in parts if p]
            found = [lookup(_key(p)) for p in parts] if len(parts) > 1 else []
            if any(f is not None for f in found):
                hit = tuple(t for f in found if f is not None for t in f)
                unmapped.extend(p for p, f in zip(parts, found) if f is None)
        if hit is None:
            unmapped.append(" ".join(str(value).split()))
            continue
        mapped += 1
        for token in hit:
            if token == SCOPE:
                sitewide = True
            else:
                tokens.add(token)
    return Resolution(
        areas=[t for t in DISPLAY_ORDER if t in tokens],
        sitewide=sitewide,
        unmapped=sorted(set(unmapped), key=str.lower),
        located=located,
        mapped=mapped,
    )
