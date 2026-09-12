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

AN UNKNOWN STRING IS PRESERVED VERBATIM AND SURFACED. `resolve` returns it in
`unmapped` so the page can print it. It is never dropped and never attached to
a neighbouring token: normalisation is not allowed to silently improve bad
source data.

AN AMBIGUOUS STRING IS NEVER NORMALISED AUTOMATICALLY. This table holds exact
keys only. There is no fuzzy match, no stemming, no edit distance and no
model -- a string it has not seen cannot be guessed at.

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
#: NOTHING MAPS TO `ROOF` YET. It is here so the first roof string that arrives
#: has a place to go, rather than the order being edited under pressure on the
#: day it appears.
DISPLAY_ORDER: Tuple[str, ...] = (
    "ROOF", "L5", "L4", "L3", "L2", "L1", "G", "B", "UG", "FDN", "EX", "SW",
)

#: (rail, prose). Short for the five-second rail, long for the activity rows
#: and any sentence. The rail stays terse on purpose: a reader who sees
#: "B / UG" learns which is which from the rows beneath, and lengthening every
#: token to cover that one case would bloat the one element built for scanning.
LABELS: Dict[str, Tuple[str, str]] = {
    "ROOF": ("Roof", "Roof"),
    "L5": ("L5", "Level 5"),
    "L4": ("L4", "Level 4"),
    "L3": ("L3", "Level 3"),
    "L2": ("L2", "Level 2"),
    "L1": ("L1", "Level 1"),
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
        rather than ACTIVE AREAS and names the value it failed on -- "no area
        recorded" under ACTIVE AREAS claims the system knows there were none,
        when in fact a location WAS recorded and this table could not read it.
        """
        notes: List[str] = []
        if self.areas:
            if self.sitewide:
                notes.append("Sitewide activity also recorded")
            if self.unmapped:
                notes.append("Unmapped: " + ", ".join(self.unmapped))
            return (str(len(self.areas)), "Active areas",
                    [" / ".join(LABELS[t][0] for t in self.areas)] + notes)
        if self.sitewide:
            if self.unmapped:
                notes.append("Unmapped: " + ", ".join(self.unmapped))
            return ("Sitewide", "Recorded activity",
                    ["No specific area recorded"] + notes)
        if self.unmapped:
            return ("—", "Location",
                    ["Unmapped source value: " + ", ".join(self.unmapped)])
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

    tokens, unmapped, located, mapped = set(), [], 0, 0
    sitewide = False
    for value in raw_values:
        key = _key(value)
        if not key:
            continue
        located += 1
        hit = table.get(key)
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
