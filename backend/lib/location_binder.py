"""WHERE A STRING SAYS WORK WAS, CHECKED AGAINST THE BUILDING IT IS ABOUT.

Five vocabularies read locations in this codebase: the plan level tokens
(lib/plans/level_suggestion.py), the investor table
(lib/report/location_vocabulary.py), integer floors (progress_report.floors_in),
punch.read_location (English, Spanish, Yiddish), and work_state.places_in,
with photo_place on top of it. Each reads words. None of them asks whether the
building HAS the level the words name: "floor 9" on a four-storey job came back
as FLOOR_9, and "3B" came back as floor 3 because it starts with a 3.

`bind` is the one place that does. It CALLS those readers (it does not copy
them), unions what they read, and then holds the result against THIS project's
levels and plan tags:

    exact        one level, or one plan tag, or an exterior place
    constrained  several levels the words name together ("floors 1-4"). Every
                 one is a candidate and none is chosen: never one floor
    none         an abstention, with the reason. A level the project does not
                 have, a choice ("3 or 4"), two plan tags, a tag and a level
                 that disagree, a unit the plans do not hold, a corridor
                 number, nothing named at all

THE OWNER'S RULE: never a specific place without sufficient evidence. So a unit
name never implies its floor (4A is not assumed to be on the fourth floor); only
a plan sheet titled for ONE level places a tag. Ground is not floor 1 (the
investor table's ruling): GROUND binds only on a project whose levels include
it. A tag matches on WORD BOUNDARIES only: "3B" is not in "13B" or "3BR".

`frame_from` builds a project's level list from what exists (storey count,
has_* flags, plan sheets, levels named by at least two filed logs) and says
which basis each level rests on. Pure: no database, no network.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from lib import photo_place as PP
from lib import punch
from lib import work_state as W
from lib.plans import level_suggestion as LS
from lib.report import location_vocabulary as V

EXACT, CONSTRAINED, NONE = "exact", "constrained", "none"
EXTERIOR, SITEWIDE = "exterior", "sitewide"

#: Where a string came from changes how it is read, and nothing else.
FREE_TEXT = "free_text"
LOG_ROW = "log_row"                  # a crew row's work_locations
POUR_LOCATION = "pour_location"      # concrete log
PUNCH_FLOOR = "punch_floor"          # a field that IS a level: "4" is floor 4
PUNCH_AREA = "punch_area"
PHOTO_WHERE = "photo_where"
PHOTO_VISIBLE_TEXT = "photo_visible_text"   # each item read WHOLE (a sign is not a place)
DOB_WORK_ON_FLOOR = "dob_work_on_floor"
SOURCES = (FREE_TEXT, LOG_ROW, POUR_LOCATION, PUNCH_FLOOR, PUNCH_AREA, PHOTO_WHERE,
           PHOTO_VISIBLE_TEXT, DOB_WORK_ON_FLOOR)

#: The reasons a result gives. Each abstention names which one.
R_LEVEL, R_LEVELS, R_SPACE, R_EXTERIOR = "one_level", "several_levels", "plan_tag", "exterior"
R_NOT_IN_PROJECT = "level_not_in_project"
R_NO_FRAME = "project_levels_unknown"
R_CHOICE = "a_choice"
R_SPACES = "several_plan_tags"
R_DISAGREE = "tag_and_level_disagree"
R_UNIT_UNKNOWN = "unit_not_in_project"
R_TAGS_UNKNOWN = "plan_tags_unknown"
R_CORRIDOR = "corridor_number_not_a_floor"
R_BELOW = "below_grade_unsettled"
R_SITEWIDE = "sitewide"
R_AREA_ONLY = "area_without_level"
R_NOTHING = "no_place_named"

#: A level named by fewer filed logs than this is not taken as one of the
#: building's: one typo ("floor 14" on a four-storey job) is not a storey.
LOG_SEEN_MIN = 2

# ── WHAT THE READERS DO NOT COVER ──────────────────────────────────────────

_ORD = r"(?:st|nd|rd|th)"
_DASH = r"(?:-|–|—|to|thru|through|al|a)"
#: "floors 1 thru 4", "levels 2-3", "pisos 1 al 3". floors_in has -, –, to, &.
_RANGE_NUM = re.compile(rf"\b(?:floors?|flrs?|fls?|levels?|lvls?|pisos?)\.?\s*#?\s*(\d{{1,2}})\s*{_DASH}\s*(\d{{1,2}})\b",
                        re.I)
#: "1st-4th", "1st to 4th floor", "2nd thru 3rd fl".
_RANGE_ORD = re.compile(rf"\b(\d{{1,2}})\s*{_ORD}\s*(?:fl(?:oo)?r?s?\.?\s*)?(?:-|–|—|to|thru|through)\s*(\d{{1,2}})\s*{_ORD}\b",
                        re.I)
_ES_ORDINAL = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "quinto": 5,
               "sexto": 6, "septimo": 7, "séptimo": 7, "octavo": 8, "noveno": 9, "decimo": 10, "décimo": 10}
_ES_WORDS = "|".join(sorted(_ES_ORDINAL, key=len, reverse=True))
#: "segundo piso", "piso tercero". "cuarto" alone is a ROOM in Spanish, so the
#: word piso is required.
_ES_FLOOR = re.compile(rf"\b(?:({_ES_WORDS})\s+piso|piso\s+({_ES_WORDS}))\b", re.I)
_ES_GROUND = re.compile(r"\bplanta\s+baja\b", re.I)
#: "3 or 4", "3 o 4", "3?" -- a choice is not a place.
_CHOICE = re.compile(r"\bor\b|\d\s+o\s+\d|\?|\beither\b", re.I)
#: A unit: "3B", "3-B", "Apt 3 B", "unit #12C". Digits first, one letter, whole
#: word. A space between is read only after an apartment word: "1 y 2" is not a unit.
_UNIT = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:apt|apartment|apto|apartamento|unit|depto|departamento)\.?\s*#?\s*(\d{1,3})\s?-?\s?([A-Za-z])"
    r"|(\d{1,3})-?([A-Za-z]))(?![A-Za-z0-9])", re.I)
#: A place outside the building's levels.
_EXTERIOR = re.compile(r"\b(?:outer\s+(?:bldg|building)|outside|exterior|fa[cç]ade|fachada|open\s+space"
                       r"|(?:front|rear|back|side)\s+of\s+(?:the\s+)?(?:bldg|building)|sidewalk|acera)\b", re.I)
_PUNCH_EXTERIOR = ("facade", "sidewalk", "courtyard")
#: punch's named areas that ARE levels.
_PUNCH_LEVEL = {"roof": LS.ROOF, "cellar": LS.CELLAR, "basement": LS.CELLAR, "bulkhead": LS.BULKHEAD}
#: "corridor 3" is a corridor's number or the third floor's corridor. Not settled here.
_CORRIDOR_NO = re.compile(r"\b(?:corridor|corr|hallway|hall|pasillo)\.?\s*#?\s*(\d{1,2})\b", re.I)
#: The investor table's tokens, in the plan vocabulary. UG and EX are not a level.
_FROM_VOCAB = {"G": LS.GROUND, "CELLAR": LS.CELLAR, "SUBCELLAR": LS.SUB_CELLAR, "B": LS.CELLAR,
               "MEZZ": LS.MEZZANINE, "ROOF": LS.ROOF, "FDN": LS.FOUNDATION}
_VOCAB_UNSETTLED = ("UG", "EX")

# ── DOB work_on_floor ──────────────────────────────────────────────────────
#: One entry: "<kind>-<number>-<job reference...>". The number after "Floor
#: Number(s)" is the floor; after a named level ("Mezzanine-4-") it is not read.
_DOB_ENTRY = re.compile(r"^\s*(?P<kind>[A-Za-z][A-Za-z ()'./]*?)\s*-\s*(?P<n>\d{1,3})(?:\s*-.*)?$")
_DOB_FLOOR_KIND = re.compile(r"^floor\s+number\(?s?\)?$", re.I)
_DOB_REF = re.compile(r"\b[A-Z]{1,3}-?\d{3,}\S*|\b\d{4,}\b")


def dob_text(raw: Any) -> str:
    """A DOB work_on_floor value as words the readers know, the job
    references dropped: "Floor Number(s)-1-SO-5912-B011" -> "floor 1"."""
    out = []
    for entry in re.split(r"[;,]", str(raw or "")):
        entry = " ".join(entry.split())
        if not entry:
            continue
        m = _DOB_ENTRY.match(entry)
        if m:
            kind = " ".join(m.group("kind").split())
            out.append(f"floor {int(m.group('n'))}" if _DOB_FLOOR_KIND.match(kind) else kind)
            continue
        entry = re.sub(r"floor\s+number\(?s?\)?", "floors", entry, flags=re.I)
        out.append(" ".join(_DOB_REF.sub(" ", entry).split()))
    return ", ".join(e for e in out if e)


# ── READING ────────────────────────────────────────────────────────────────

def sort_levels(tokens: Iterable[str]) -> List[str]:
    return sorted(set(tokens), key=LS._sort_key)


def _floor(n: int) -> Optional[str]:
    return f"{LS.FLOOR_PREFIX}{n}" if 1 <= n <= LS.MAX_SUGGESTED_STORIES else None


def _units(text: str) -> Tuple[List[str], str]:
    """(unit tag keys named, the text with them blanked out). A unit is
    blanked so no reader takes its leading digits for a floor."""
    keys = []
    for m in _UNIT.finditer(text):
        digits, letter = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        keys.append(f"{int(digits)}{letter.upper()}")
    return list(dict.fromkeys(keys)), _UNIT.sub(" ", text)


def read(text: Any, *, source: str = FREE_TEXT) -> Dict[str, Any]:
    """What the words name, BEFORE any check against a project:
    {levels, units, area, choice, unsettled: [reasons], corridor: [levels]}."""
    t = " ".join(str(text or "").split())
    out: Dict[str, Any] = {"levels": [], "units": [], "area": None, "choice": False, "unsettled": [],
                           "corridor": [], "text": t}
    if not t:
        return out
    if source == PHOTO_VISIBLE_TEXT:
        # A sign: the WHOLE item is a floor marking or a tag, or it is nothing.
        mark = PP._floor_mark(t)
        out["levels"] = [mark] if mark else []
        key = PP.tag_key(t)
        out["units"] = [key] if PP._usable_tag(key) and not mark else []
        return out
    if source == DOB_WORK_ON_FLOOR:
        t = dob_text(t)
    out["choice"] = bool(_CHOICE.search(t))
    units, rest = _units(t)
    out["units"] = units
    levels: Set[str] = set(W.places_in(rest)["levels"])
    levels |= set(LS.tokens_in(rest, field_is_a_level=source == PUNCH_FLOOR)[0])
    if source == PUNCH_FLOOR and re.fullmatch(r"\d{1,2}", rest.strip()):
        levels.add(_floor(int(rest.strip())) or "")
    vocab = V.resolve([rest])
    for tok in vocab.areas:
        n = V.level_number(tok)
        if n is not None:
            levels.add(_floor(n) or "")
        elif tok in _FROM_VOCAB:
            levels.add(_FROM_VOCAB[tok])
        elif tok in _VOCAB_UNSETTLED:
            out["unsettled"].append(R_BELOW)
        elif tok == "SW":
            out["area"] = EXTERIOR
    for rx in (_RANGE_NUM, _RANGE_ORD):
        for m in rx.finditer(rest):
            lo, hi = sorted((int(m.group(1)), int(m.group(2))))
            levels |= {_floor(n) or "" for n in range(lo, hi + 1)}
    for m in _ES_FLOOR.finditer(rest):
        levels.add(_floor(_ES_ORDINAL[(m.group(1) or m.group(2)).lower()]) or "")
    if _ES_GROUND.search(rest):
        levels.add(LS.GROUND)
    if LS._AMBIGUOUS_BELOW.search(rest.lower()):
        out["unsettled"].append(R_BELOW)
    loc = punch.read_location(rest)
    area = str(loc.get("area") or "")
    if area in _PUNCH_LEVEL:
        levels.add(_PUNCH_LEVEL[area])
    if _EXTERIOR.search(rest) or area in _PUNCH_EXTERIOR:
        out["area"] = EXTERIOR
    elif area and area not in _PUNCH_LEVEL and not area.startswith("Apt "):
        out["area"] = area
    if vocab.sitewide and not levels:
        out["area"] = out["area"] or SITEWIDE
    out["corridor"] = sort_levels(_floor(int(m.group(1))) or "" for m in _CORRIDOR_NO.finditer(rest)) if not levels else []
    out["corridor"] = [c for c in out["corridor"] if c]
    out["levels"] = sort_levels(lv for lv in levels if lv)
    return out


# ── BINDING ────────────────────────────────────────────────────────────────

def _spaces(project_spaces: Any) -> Dict[str, Dict[str, Any]]:
    """{tag key: {"levels": [...]}} from photo_place.spaces_from_plan_rows' dict
    or a plain list of tags."""
    if isinstance(project_spaces, dict):
        return {k: {"levels": list((v or {}).get("levels") or [])} for k, v in project_spaces.items() if PP._usable_tag(k)}
    out: Dict[str, Dict[str, Any]] = {}
    for tag in project_spaces or ():
        key = PP.tag_key(tag)
        if PP._usable_tag(key):
            out[key] = {"levels": []}
    return out


def _tags_named(text: str, units: Sequence[str], spaces: Dict[str, Dict[str, Any]]) -> List[str]:
    """Every plan tag the words name, by whole word only."""
    norm = " ".join(re.sub(r"[^A-Z0-9]", " ", text.upper()).split())
    found = [u for u in units if u in spaces]
    for key in spaces:
        if key not in found and re.search(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", norm):
            found.append(key)
    # "STAIR A" is in "STAIR A LANDING"; a key inside a longer matched key is that key.
    return [k for k in found if not any(k != o and re.search(rf"(?<![A-Z0-9]){re.escape(k)}(?![A-Z0-9])", o)
                                        for o in found)]


def _result(levels: Sequence[str], space: Optional[str], area: Optional[str], certainty: str, reason: str,
            candidates: Iterable[str], source: str, spaces_read: Sequence[str] = ()) -> Dict[str, Any]:
    return {"levels": sort_levels(levels), "space": space, "area": area, "certainty": certainty, "reason": reason,
            "candidates": sort_levels(c for c in candidates if c), "spaces_read": list(spaces_read), "source": source}


def bind(text: Any, project_levels: Optional[Iterable[str]], project_spaces: Any = None, *,
         source: str = FREE_TEXT) -> Dict[str, Any]:
    """{levels, space, area, certainty: exact|constrained|none, reason,
    candidates, spaces_read, source}. See the module docstring. Total."""
    r = read(text, source=source)
    frame = set(project_levels or ())
    spaces = _spaces(project_spaces)
    tags = _tags_named(r["text"] if source != DOB_WORK_ON_FLOOR else dob_text(r["text"]), r["units"], spaces) \
        if source != PHOTO_VISIBLE_TEXT else [u for u in r["units"] if u in spaces]
    levels, area = list(r["levels"]), r["area"]
    cands = levels + r["corridor"]

    def no(reason: str) -> Dict[str, Any]:
        return _result([], None, area, NONE, reason, cands, source, tags)

    if not frame:
        return no(R_NO_FRAME)
    if r["choice"] and (levels or tags or r["units"] or re.search(r"\d", r["text"])):
        return no(R_CHOICE)
    if len(tags) > 1:
        return no(R_SPACES)
    space = tags[0] if tags else None
    if space and spaces[space]["levels"]:
        tag_levels = spaces[space]["levels"]
        if levels and not set(levels) & set(tag_levels):
            return no(R_DISAGREE)
        if not levels and len(tag_levels) == 1:
            levels = list(tag_levels)
    if any(lv not in frame for lv in levels):
        return no(R_NOT_IN_PROJECT)
    if source == PHOTO_VISIBLE_TEXT:
        units = []          # a sign that is not a tag is not a unit
    else:
        units = r["units"]
    if units and not spaces and not levels:
        return no(R_TAGS_UNKNOWN)
    if spaces and not space and any(u not in spaces for u in units):
        return no(R_UNIT_UNKNOWN) if not levels else _result(levels, None, area, EXACT if len(levels) == 1 else CONSTRAINED,
                                                             R_UNIT_UNKNOWN, cands, source, tags)
    if levels:
        return _result(levels, space, area, EXACT if len(levels) == 1 else CONSTRAINED,
                       R_SPACE if space and len(levels) == 1 else R_LEVEL if len(levels) == 1 else R_LEVELS,
                       cands, source, tags)
    if space:
        return _result([], space, area, EXACT, R_SPACE, cands, source, tags)
    if area == EXTERIOR:
        return _result([], None, EXTERIOR, EXACT, R_EXTERIOR, cands, source, tags)
    if r["corridor"]:
        return no(R_CORRIDOR)
    if r["unsettled"]:
        return no(r["unsettled"][0])
    if area == SITEWIDE:
        return no(R_SITEWIDE)
    return no(R_AREA_ONLY if area else R_NOTHING)


def place(text: Any, frame: Dict[str, Any], *, source: str = FREE_TEXT) -> Dict[str, Any]:
    """work_state.places_in's shape, bound to a project: {"levels", "space"}.
    An abstention is no level. With no plan tags in the frame the space is the
    one places_in has always read, so nothing changes where nothing is known."""
    b = bind(text, frame.get("levels"), frame.get("spaces"), source=source)
    levels = b["levels"] if b["certainty"] != NONE else []
    space = b["space"] if frame.get("spaces") else W.places_in(text)["space"]
    return {"levels": levels, "space": space}


# ── THE PROJECT'S LEVELS ───────────────────────────────────────────────────

_FLAG_LEVELS = {"has_sub_cellar": (LS.SUB_CELLAR,), "has_cellar": (LS.CELLAR,), "has_mezzanine": (LS.MEZZANINE,),
                "has_roof_bulkhead": (LS.ROOF, LS.BULKHEAD)}
#: Every building has these, so a frame with any level at all has them too.
EVERY_BUILDING = (LS.ROOF, LS.FOUNDATION)


def frame_from(project: Optional[Dict[str, Any]], page_rows: Iterable[Dict[str, Any]] = (),
               log_locations: Iterable[Iterable[Any]] = (), spaces: Any = None) -> Dict[str, Any]:
    """{levels, spaces, basis: {level: [why]}, known, excluded} for one project.

    `project`: its storey count and has_* flags (None is nobody said, not no).
    `page_rows`: document_page_index rows, read by level_suggestion.
    `log_locations`: per filed log, its crew rows' work_locations; a level counts
    when at least LOG_SEEN_MIN logs name it. A numbered floor above a stated
    storey count is excluded whatever names it. `known`: some level rests on
    the project or its plans, not on the logs alone."""
    p = project or {}
    basis: Dict[str, List[str]] = defaultdict(list)
    try:
        stories = int(p.get("building_stories") or 0)
    except (TypeError, ValueError):
        stories = 0
    stories = stories if 0 < stories <= LS.MAX_SUGGESTED_STORIES else 0
    for n in range(1, stories + 1):
        basis[f"{LS.FLOOR_PREFIX}{n}"].append("building_stories")
    for field, toks in _FLAG_LEVELS.items():
        if p.get(field) is True:
            for t in toks:
                basis[t].append(field)
    excluded: Dict[str, str] = {}

    def over(tok: str) -> bool:
        n = LS.floor_number(tok)
        return bool(stories) and n is not None and n > stories

    for lv in LS.suggest_levels(list(page_rows or ()))["levels"]:
        if over(lv["token"]):
            excluded[lv["token"]] = "above building_stories"
        else:
            basis[lv["token"]].append("plan_sheets")
    known = bool(basis)
    seen: Dict[str, int] = defaultdict(int)
    for log in log_locations or ():
        named: Set[str] = set()
        for s in log or ():
            named |= set(read(s, source=LOG_ROW)["levels"])
        for t in named:
            seen[t] += 1
    for t, n in seen.items():
        if n < LOG_SEEN_MIN:
            continue
        if over(t):
            excluded.setdefault(t, "above building_stories")
        else:
            basis[t].append(f"logs:{n}")
    if basis:
        for t in EVERY_BUILDING:
            basis[t].append("every_building")
    return {"levels": sort_levels(basis), "spaces": spaces or {}, "basis": {k: v for k, v in basis.items()},
            "known": known, "excluded": excluded}


# ── SCORING AGAINST A PERSON'S LABEL ───────────────────────────────────────

RIGHT, WRONG, ABSTAIN = "right", "wrong", "abstain"
NO_PLACE = "-"


def parse_levels(label: Any) -> List[str]:
    """"FLOOR_1|FLOOR_2", "1|2", "roof" -> tokens. "-" or blank -> []."""
    out = []
    for part in re.split(r"[|,;\s]+", str(label or "").strip()):
        if not part or part == NO_PLACE:
            continue
        up = part.upper()
        if re.fullmatch(r"\d{1,2}", up):
            out.append(f"{LS.FLOOR_PREFIX}{int(up)}")
        elif up in LS.LABELS or re.fullmatch(rf"{LS.FLOOR_PREFIX}\d{{1,2}}", up):
            out.append(up)
        else:
            raise ValueError(f"not a level token: {part!r}")
    return sort_levels(out)


def is_labeled(true_levels: Any, true_space: Any) -> bool:
    return bool(str(true_levels or "").strip() or str(true_space or "").strip())


def judge(result: Dict[str, Any], true_levels: Any, true_space: Any) -> str:
    """right | wrong | abstain. RIGHT: everything the binder claims is true (it
    may claim less than the label: a tag with no level is not wrong). A label
    of "-" in both columns says no place can be read; any answer there is wrong."""
    if result["certainty"] == NONE:
        return ABSTAIN
    tl = set(parse_levels(true_levels))
    ts = str(true_space or "").strip()
    ts = "" if ts == NO_PLACE else PP.tag_key(ts) if ts.upper() != EXTERIOR.upper() else EXTERIOR
    claimed_space = result["space"] or (EXTERIOR if result.get("area") == EXTERIOR else "")
    if result["levels"] and set(result["levels"]) != tl:
        return WRONG
    if claimed_space and claimed_space != ts:
        return WRONG
    return RIGHT if (result["levels"] or claimed_space) else WRONG


def has_place(true_levels: Any, true_space: Any) -> bool:
    ts = str(true_space or "").strip()
    return bool(parse_levels(true_levels)) or bool(ts and ts != NO_PLACE)
