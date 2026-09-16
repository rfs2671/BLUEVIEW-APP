"""WHICH LEVELS A BUILDING HAS, READ OFF ITS OWN SHEETS.

A SUGGESTION AND NOTHING ELSE. Nothing here writes, and the endpoint that calls
it is a GET. An admin reads the proposal beside the sheet numbers it came from
and presses Save; until he does, the project is unchanged. That is the whole
design: the drawings are evidence, not authority, and the one person who can
tell a zoning datum from a storey is the one looking at the building.

── WHY IT IS NOT A PARSER ───────────────────────────────────────────────────

`document_page_index.floor` is already extracted and it is filthy. On 588
Thomas, 155 indexed pages carry more than fifty distinct spellings:

    first / First / FIRST FLOOR / 1st / FIRST FL / 1ST FLOOR / first floor
    Fourth / fourth / Fourth Floor / 4TH FLOOR / FOURTH FL
    bulkhead / bulkhead roof / BULKHEAD 93.37' +60'-0"
    BASE PLANE, SECOND FLOOR, THIRD FLOOR, FOURTH FLOOR, MEZZANINE, ROOF

So the table below holds EXACT NORMALISED KEYS and patterns that are anchored
on the word "floor" or on a level noun. There is no fuzzy match, no stemming
and no model. A string it has not seen is returned in `unmapped` for the admin
to read; it is never dropped and never attached to a neighbouring token. This
is the same rule lib/report/location_vocabulary.py already follows, and for
the same reason: normalisation is not allowed to silently improve bad source
data on a document that ends up in front of a lender.

── THE THREE STRINGS THAT LOOK LIKE LEVELS AND ARE NOT ──────────────────────

BASE PLANE is a ZONING DATUM. It appears on every elevation and setback diagram
on 588 because that is where building height is measured from. It is not a
storey, nobody works "on the base plane", and a chip for it would put a survey
reference into a signed compliance record. Excluded by name.

FINISHED FLOOR is an annotation on a window schedule -- a height above the
slab, not a level. Excluded by name.

ROOF FLOOR is the roof. Plumbing spells it that way (P-105.00 "ROOF FLOOR
DOMESTIC WATER & GAS PLANS"); it is not a numbered storey above the roof.
Mapped to ROOF rather than excluded.

── WHAT COUNTS AS EVIDENCE ──────────────────────────────────────────────────

Both `sheet_title` and `floor` are read, because NEITHER IS RELIABLE ALONE.
On 588, 24 of 155 rows carry a BLANK sheet_title -- eleven architectural sheets
appear twice, once extracted and once empty -- so a suggester reading titles
only would lose them. And `floor` is empty on 70 of 155 rows, so one reading
that alone would lose the floor-plan series whose title is the only statement
of the level.

Rows are de-duplicated by (level, sheet_number) so eleven pages of the same
sheet are one piece of evidence, not eleven.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ── The closed token set ────────────────────────────────────────────────────
SUB_CELLAR = "SUB_CELLAR"
CELLAR = "CELLAR"
FOUNDATION = "FOUNDATION"
GROUND = "GROUND"
MEZZANINE = "MEZZANINE"
ROOF = "ROOF"
BULKHEAD = "BULKHEAD"

#: A numbered storey is FLOOR_<n>. Kept out of the constants above because the
#: set is open in n and closed in kind.
FLOOR_PREFIX = "FLOOR_"

#: Bottom to top, the order the chips render in. A numbered floor sorts between
#: GROUND and MEZZANINE by its own number.
BELOW: Tuple[str, ...] = (SUB_CELLAR, CELLAR, FOUNDATION, GROUND)
ABOVE: Tuple[str, ...] = (MEZZANINE, ROOF, BULKHEAD)

LABELS: Dict[str, str] = {
    SUB_CELLAR: "Sub-cellar",
    CELLAR: "Cellar",
    FOUNDATION: "Foundation",
    GROUND: "Ground",
    MEZZANINE: "Mezzanine",
    ROOF: "Roof",
    BULKHEAD: "Bulkhead",
}

#: Which project field each token would set, for the form that applies the
#: proposal. A numbered floor sets `building_stories` to the HIGHEST one seen,
#: which is handled by the caller rather than by a per-token mapping.
FIELD_OF: Dict[str, str] = {
    SUB_CELLAR: "has_sub_cellar",
    CELLAR: "has_cellar",
    MEZZANINE: "has_mezzanine",
    ROOF: "has_roof_bulkhead",
    BULKHEAD: "has_roof_bulkhead",
}

#: STRINGS THAT ARE NOT LEVELS. Matched before anything else, so no pattern
#: below can pick them up. Each one is on 588's sheets today.
NOT_A_LEVEL: Tuple[str, ...] = (
    "base plane",        # zoning datum on every elevation and setback diagram
    "finished floor",    # a height annotation on the window schedule
)

_WORD_TOKENS: Tuple[Tuple[str, str], ...] = (
    # Order matters: sub-cellar before cellar, or "sub-cellar" matches "cellar".
    (r"sub[\s-]?cellar", SUB_CELLAR),
    (r"sub[\s-]?basement", SUB_CELLAR),
    (r"cellar", CELLAR),
    (r"basement", CELLAR),
    (r"bulkhead", BULKHEAD),
    (r"mezzanine", MEZZANINE),
    (r"roof", ROOF),
    (r"ground\s+(?:floor|level)", GROUND),
    (r"foundation", FOUNDATION),
)

_ORDINAL_WORDS: Dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
}

#: A numbered storey, anchored on the word floor (or its abbreviation "fl"),
#: which is what stops "2 OF 3" on a sewer form and "Phase 3" from becoming
#: storeys. `\b(?:fl|floor)\b` requires the word; a bare number never matches.
_NUMBERED = re.compile(
    r"\b(?:(\d{1,2})\s*(?:st|nd|rd|th)?|("
    + "|".join(_ORDINAL_WORDS)
    + r"))\s+(?:fl|flr|floor)\b"
)

#: The highest storey this will believe from a drawing without a human. Beyond
#: it the suggestion reports the value and refuses to pre-fill, because a
#: two-digit misread on a title block should not silently make a project Major.
MAX_SUGGESTED_STORIES = 60


def _norm(value) -> str:
    """Lowercased, whitespace-collapsed. No other transformation."""
    return " ".join(str(value or "").split()).lower()


#: A BARE ordinal, with no "floor" after it. Read ONLY out of the `floor`
#: field, never out of a title — see `tokens_in`.
_BARE_ORDINAL = re.compile(
    r"^(?:(\d{1,2})\s*(?:st|nd|rd|th)|("
    + "|".join(_ORDINAL_WORDS)
    + r"))$"
)

#: A part naming a below-grade level in words this table will not resolve.
#: "FIRST UNDERGROUND FLOOR" is 588's only below-grade sheet (P-200.00) and it
#: is genuinely ambiguous: under-slab plumbing on a slab-on-grade building, or
#: a cellar storey nobody drew an architectural plan for. Emitting FLOOR_1 from
#: it would be wrong in both readings, and emitting CELLAR would invent a
#: storey. So it emits NOTHING and is reported verbatim for the admin to
#: settle, which is the one judgement this module exists not to make.
_AMBIGUOUS_BELOW = re.compile(r"\b(?:underground|below\s+grade|sub[\s-]?grade)\b")


def tokens_in(text, *, field_is_a_level: bool = False) -> Tuple[List[str], List[str]]:
    """(tokens, leftovers) for one string.

    ── THE TWO READINGS, AND WHY THEY ARE NOT THE SAME ─────────────────────

    `field_is_a_level` is True for the index's `floor` column and False for
    `sheet_title`, and it changes what a bare ordinal means.

    In the `floor` column the extractor writes `first`, `Fourth`, `2nd` with no
    noun, and the COLUMN supplies the noun: it is called floor, so "first"
    there is the first floor. In a TITLE the same word means nothing on its own
    -- "FIRST AID STATION", "Phase 3" -- so a title must carry the word floor
    (or `fl`) before a number becomes a storey.

    Reading both the same way is how "2 OF 3" on a sewer connection form and
    "SITE SAFETY PLAN - SUPERSTRUCTURE(PHASE-03)" become storeys.

    `leftovers` are collected ONLY from the level column. Every sheet title
    that is not about a level would otherwise land in the admin's "not
    understood" list -- window schedules, riser diagrams, the DCDA form -- and
    a list of forty irrelevant strings is one nobody reads, which is how the
    one string that MATTERS ("first underground") gets missed.
    """
    raw = _norm(text)
    if not raw:
        return [], []
    found: List[str] = []
    leftovers: List[str] = []
    # The extractor writes comma-separated lists on elevations and sections
    # ("BASE PLANE, SECOND FLOOR, THIRD FLOOR, ..."), so each part is read on
    # its own. A part is also read whole, because a title like "ROOF AND
    # BULKHEAD PLAN" is one part naming two levels.
    for part in [p.strip() for p in raw.split(",")] or [raw]:
        if not part:
            continue
        if part in NOT_A_LEVEL:
            continue
        if _AMBIGUOUS_BELOW.search(part):
            # Named, not guessed at. See _AMBIGUOUS_BELOW.
            if field_is_a_level and part not in leftovers:
                leftovers.append(part)
            continue
        hit = False
        for pat, token in _WORD_TOKENS:
            if re.search(r"\b" + pat + r"\b", part):
                if token not in found:
                    found.append(token)
                hit = True
        numbers = [
            int(m.group(1)) if m.group(1) else _ORDINAL_WORDS[m.group(2)]
            for m in _NUMBERED.finditer(part)
        ]
        if field_is_a_level and not numbers:
            m = _BARE_ORDINAL.match(part)
            if m:
                numbers = [int(m.group(1)) if m.group(1)
                           else _ORDINAL_WORDS[m.group(2)]]
        for n in numbers:
            if 1 <= n <= MAX_SUGGESTED_STORIES:
                tok = f"{FLOOR_PREFIX}{n}"
                if tok not in found:
                    found.append(tok)
                hit = True
        if not hit and field_is_a_level and part not in leftovers:
            leftovers.append(part)
    return found, leftovers


def floor_number(token: str) -> Optional[int]:
    """The storey number of a FLOOR_n token, or None for anything else."""
    if isinstance(token, str) and token.startswith(FLOOR_PREFIX):
        try:
            return int(token[len(FLOOR_PREFIX):])
        except ValueError:
            return None
    return None


def _sort_key(token: str) -> Tuple[int, int]:
    n = floor_number(token)
    if n is not None:
        return (1, n)
    if token in BELOW:
        return (0, BELOW.index(token))
    return (2, ABOVE.index(token) if token in ABOVE else 99)


def suggest_levels(rows: Iterable[dict]) -> dict:
    """The proposal, from `document_page_index` rows for one project.

    PURE AND TOTAL. No I/O and it never raises on a malformed row — a suggester
    that throws on one bad page would take the whole form down for a defect in
    a file nobody is looking at.

    Returns, and every key is there to be SHOWN rather than applied silently:

        levels      [{token, label, field, floor, sheets:[...], pages:int}]
        patch       the project fields an Apply would set
        unmapped    strings this table did not understand, verbatim
        pages       how many index rows were read
        title_gaps  rows with no sheet_title at all -- the extraction defect,
                    reported because it bounds how complete this can be
    """
    evidence: Dict[str, Dict[str, object]] = {}
    unmapped: List[str] = []
    pages = 0
    title_gaps = 0

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pages += 1
        title = str(row.get("sheet_title") or "")
        number = str(row.get("sheet_number") or "").strip()
        if not title.strip():
            title_gaps += 1
        # BOTH FIELDS, ALWAYS. See the module docstring: 24 of 155 rows on 588
        # have no title and 70 have no floor, and they are not the same rows.
        for source, is_level in ((title, False),
                                 (row.get("floor"), True),
                                 (row.get("floors"), True)):
            if isinstance(source, (list, tuple)):
                source = ", ".join(str(s) for s in source)
            toks, leftover = tokens_in(source, field_is_a_level=is_level)
            for tok in toks:
                slot = evidence.setdefault(
                    tok, {"sheets": [], "pages": 0})
                slot["pages"] = int(slot["pages"]) + 1
                if number and number not in slot["sheets"]:
                    slot["sheets"].append(number)
            for lv in leftover:
                if lv not in unmapped:
                    unmapped.append(lv)

    levels = []
    for tok in sorted(evidence, key=_sort_key):
        levels.append({
            "token": tok,
            "label": LABELS.get(tok) or _floor_label(tok),
            "field": FIELD_OF.get(tok),
            "floor": floor_number(tok),
            # SHEET NUMBERS, BECAUSE THE ADMIN IS CONFIRMING AND NOT TRUSTING.
            # "4th Floor" is a claim; "4th Floor -- A-103.00" is a claim he can
            # check in ten seconds against the drawing he already has.
            "sheets": sorted(evidence[tok]["sheets"])[:8],
            "pages": evidence[tok]["pages"],
        })

    return {
        "levels": levels,
        "patch": _patch_from(levels),
        "unmapped": unmapped[:40],
        "pages": pages,
        "title_gaps": title_gaps,
    }


def _floor_label(token: str) -> str:
    n = floor_number(token)
    if n is None:
        return token
    rem100, rem10 = n % 100, n % 10
    suffix = "th"
    if rem100 < 11 or rem100 > 13:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rem10, "th")
    return f"{n}{suffix} Floor"


def _patch_from(levels: Sequence[dict]) -> dict:
    """The project fields an Apply would set.

    `building_stories` IS THE HIGHEST NUMBERED FLOOR FOUND, and that is a
    judgement the admin has to make rather than accept: it is the one field
    here that re-derives the project's §3310 class. It is returned so the form
    can PRE-FILL it, never so that anything can write it.

    A mezzanine does NOT add to the storey count. It has its own flag because
    it is its own level, and counting it would inflate the number the major-
    building test reads.
    """
    patch: Dict[str, object] = {}
    top = 0
    for lv in levels:
        n = lv.get("floor")
        if isinstance(n, int) and n > top:
            top = n
        field = lv.get("field")
        if field:
            patch[field] = True
    if 0 < top <= MAX_SUGGESTED_STORIES:
        patch["building_stories"] = top
    return patch
