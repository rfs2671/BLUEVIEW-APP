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
it, or whose frame says its first floor is at grade with no cellar or
sub-cellar below (frame_from's `ground_level`; set only from has_cellar=False,
has_sub_cellar=False and first_floor_at_grade=True, never from silence). Even
then only "ground floor" / "planta baja" map: "ground level" and "grade" name
the site as often as a floor. A tag matches on WORD BOUNDARIES only: "3B" is
not in "13B" or "3BR".

NEVER A STRICT SUBSET (588, 2026-11-10). "1-2-3rd floor" and "1st/2nd 3rd fl"
were bound to the 3rd floor alone: a wrong single-floor claim, the worst
outcome. Runs of floor numbers ("1-2-3rd", "1st, 2nd & 3rd", "segundo y tercer
piso") are read whole, and every ordinal the words hold must be in the answer
or there is no answer (R_UNREAD: "3rd floor moving up to 4th", "Nov 4th 3rd
floor", "2nd coat on the 3rd floor"). A character no reader knows between two
floor numbers ("1st�4th", an export's lost dash) abstains too.

ROUND 2: THE RULE IS ON THE RESULT (adversarial review 1). `_structural` cuts
the words into chains of level material; every number, ordinal and level noun
in a chain that touches a level word is STATED, a span word between two
numbers states the floors between, and an answer missing any stated level is
none ("floors 2 3 4" is read whole or not at all). A span to the roof, and an
open range ("2nd floor and up", "above 2nd floor", "floors 2+"), expand against
the frame only when it is complete (frame_from: a storey count on record) and
only where the frame fixes the order (a mezzanine of unknown height stops it);
the answer then says R_EXPANDED. "upper floors", "under/below/between",
"top floor", and any exclusion ("not", "except", "menos") abstain. Two chains
with words between them that bind differently ("Framers 3rd floor plumbers 1st
floor") abstain (R_TRADES); bind_clauses splits on and / y / while / & when
both sides name a trade and a place.

SEVERAL TRADES, SEVERAL FLOORS. "Framers on the 3rd-4th floors, Plumber on the
1st-4th, HVAC on the 1st-2nd" has no single answer: the union puts framers on
floor 1. `bind` abstains (R_TRADES) when two or more clauses each name a trade
and a place and the places differ; `bind_clauses` returns each clause's own.
Not wired into a reader yet: the daily-log readers (work_state.evidence_rows,
evidence_sources' crew rows) carry ONE level set per row, and a row would have
to become one row per clause. Until then those rows abstain.

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
#: A floor the words name (an ordinal) that no reader placed: "3rd floor moving
#: up to 4th". The answer would be a strict subset of what was said, so none.
R_UNREAD = "level_named_not_read"
#: Different trades on different floors in one sentence ("Framers on the 3rd-4th
#: floors, Plumber on the 1st-4th"). The union would give every trade every
#: floor; bind_clauses reads each clause instead.
R_TRADES = "several_trades_several_levels"
#: GROUND bound to the project's first floor because its frame says the first
#: floor is at grade and nothing is below it.
R_GROUND = "ground_is_first_floor"

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
_RANGE_ORD = re.compile(rf"\b(\d{{1,2}})\s*{_ORD}\s*(?:fl(?:oo)?r?s?\.?\s*)?(?:-|–|—|(?:up\s+)?to|thru|through|until|till)\s*(\d{{1,2}})\s*{_ORD}\b",
                        re.I)
#: "1-4 floors", "2 thru 5 levels": the level word after the range.
_RANGE_AFTER = re.compile(rf"\b(\d{{1,2}})\s*(?:-|–|—|to|thru|through)\s*(\d{{1,2}})\s*(?:floors?|flrs?|fls?|levels?|lvls?|pisos?)\b",
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

# ── LISTS AND RUNS OF ORDINALS ─────────────────────────────────────────────
#: The readers above see a list when each number carries the level word, or the
#: word sits at one end of a list they know. They read "1-2-3rd floor" and
#: "1st/2nd 3rd fl" as the 3rd floor alone: a strict subset of what was said.
#: A RUN is two or more floor numbers joined by separators, with a level word
#: at either end (or the run is the whole text). A dash, "to", "thru", "al", "a"
#: between two numbers is a span; anything else is a list.
_EN_ORD_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
                "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
_ITEM = (rf"(?:\d{{1,2}}(?:\s*(?:st|nd|rd|th)\b|(?:er|ro|do|to|vo|no|mo)\b|°|º)?"
         rf"|\b(?:{'|'.join(sorted(_EN_ORD_WORD, key=len, reverse=True))}|{_ES_WORDS})\b)")
_SPAN_SEP = r"(?:-|–|—|\b(?:up\s+)?to\b|\bthru\b|\bthrough\b|\buntil\b|\btill\b|\bal\b|\ba\b)"
_LIST_SEP = r"(?:,|&|/|\+|\band\b|\by\b)"
#: Whitespace alone joins two items only when the second is an ordinal ("1st/2nd 3rd").
_SEP = rf"(?:\s*(?:{_SPAN_SEP}|{_LIST_SEP})\s*(?:and\s+|y\s+)?|\s+(?=\d{{1,2}}\s*(?:st|nd|rd|th)\b))"
_RUN = rf"{_ITEM}(?:{_SEP}{_ITEM})+"
_LVL_WORD = r"(?:floors?|flrs?|fls?|fl|levels?|lvls?|pisos?|stor(?:y|ey|ies|eys)|niveles|nivel)"
_RUNS = (re.compile(rf"\b{_LVL_WORD}\.?\s*#?\s*({_RUN})(?![\w/])", re.I),
         re.compile(rf"(?<![\w/])({_RUN})\s*{_LVL_WORD}\b", re.I),
         re.compile(rf"^\s*({_RUN})\s*\.?\s*$", re.I),
         # "3rd floor and 4th", "1st fl - 2nd": the word after the first item. The
         # tail is ordinals only and ends the clause, so "3rd floor and 2nd coat"
         # is not read as a list (the 2nd stays unread, and the answer is none).
         re.compile(rf"(?<![\w/])(\d{{1,2}}\s*(?:st|nd|rd|th)\s*{_LVL_WORD}\.?(?:\s*(?:{_SPAN_SEP}|{_LIST_SEP})\s*"
                    rf"(?:and\s+)?\d{{1,2}}\s*(?:st|nd|rd|th))+)(?=\s*(?:$|[,.;:)]))", re.I),
         # "floors 2 3 4": bare numbers after the level word, spaces only, ending
         # the clause. "floor 3 2 guys" does not end there, so the 2 stays unread.
         re.compile(rf"\b{_LVL_WORD}\.?\s*#?\s*(\d{{1,2}}(?:\s+\d{{1,2}})+)(?=\s*(?:$|[,.;:)&]))", re.I))
_ITEM_RX = re.compile(_ITEM, re.I)
#: "2do piso", "piso 4to": a Spanish numeric ordinal beside piso.
_ES_NUM_FLOOR = re.compile(r"(?<![\w/])(\d{1,2})(?:er|ro|do|to|vo|no|mo|°|º)\s*pisos?\b"
                           r"|\bpisos?\s*(\d{1,2})(?:er|ro|do|to|vo|no|mo|°|º)(?!\w)", re.I)
#: Every ordinal the words hold: "3rd", "4th", "2do", and an ordinal WORD when a
#: level word is in the text ("first and second floor"; Spanish "segundo" only
#: beside piso, since "un segundo" is a second of time).
_ORD_NUM = re.compile(r"(?<!\w)(\d{1,2})(?:\s*(?:st|nd|rd|th)|er|ro|do|to|vo|no|mo)\b", re.I)
_ORD_WORD = re.compile(rf"\b({'|'.join(_EN_ORD_WORD)}|{_ES_WORDS})\b", re.I)
_HAS_LVL_WORD = re.compile(rf"\b{_LVL_WORD}\b", re.I)
_GARBLED = re.compile(r"\d(?:st|nd|rd|th)?\s*[^\w\s,&/+\-–—.;:()'\"#°º]\s*\d", re.I)


def _item_n(item: str) -> Optional[int]:
    s = item.strip().lower()
    m = re.match(r"\d{1,2}", s)
    if m:
        return int(m.group(0))
    return _EN_ORD_WORD.get(s) or _ES_ORDINAL.get(s)


def _runs(text: str) -> Set[int]:
    """Every floor number a run names: "1-2-3rd floor" is 1, 2, 3."""
    out: Set[int] = {int(m.group(1) or m.group(2)) for m in _ES_NUM_FLOOR.finditer(text)}
    for k, rx in enumerate(_RUNS):
        for m in rx.finditer(text):
            run = m.group(1)
            items = list(_ITEM_RX.finditer(run))
            seps = [run[a.end():b.start()] for a, b in zip(items, items[1:])]
            if k != 4 and all(not s.strip() for s in seps):
                continue        # "Nov 4th 3rd floor": spaces alone do not make a list
            if k == 2 and re.search(r"\d\s*/\s*\d", run):
                continue        # a bare "2/3" is a date as often as two floors
            prev = None
            for i, it in enumerate(items):
                n = _item_n(it.group(0))
                if n is None:
                    prev = None
                    continue
                sep = re.sub(rf"\b{_LVL_WORD}\b\.?", " ", run[items[i - 1].end():it.start()], flags=re.I) if i else ""
                if prev is not None and re.fullmatch(rf"\s*{_SPAN_SEP}\s*", sep, re.I):
                    lo, hi = sorted((prev, n))
                    out |= set(range(lo, hi + 1))
                out.add(n)
                prev = n
    return out


def _ordinals_named(text: str) -> Set[int]:
    """Every floor number the words name as an ordinal. A result missing one is
    a strict subset of what was said."""
    out = {int(m.group(1)) for m in _ORD_NUM.finditer(text)}
    if _HAS_LVL_WORD.search(text):
        out |= {_item_n(m.group(1)) or 0 for m in _ORD_WORD.finditer(text)}
    return {n for n in out if n}


#: "ground floor", "ground fl", "planta baja": a FLOOR at grade. "Ground level",
#: "grade" and "at grade" name the site as often as a floor, and stay unmapped.
_GROUND_FLOOR = re.compile(r"\bground\s+(?:floor|flr|fl)\b|\bplanta\s+baja\b", re.I)
_GROUND_OTHER = re.compile(r"\bground\s+level\b", re.I)

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
                           "corridor": [], "text": t, "unread": [], "ground_floor": False, "garbled": False}
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
    for rx in (_RANGE_NUM, _RANGE_ORD, _RANGE_AFTER):
        for m in rx.finditer(rest):
            lo, hi = sorted((int(m.group(1)), int(m.group(2))))
            levels |= {_floor(n) or "" for n in range(lo, hi + 1)}
    for m in _ES_FLOOR.finditer(rest):
        levels.add(_floor(_ES_ORDINAL[(m.group(1) or m.group(2)).lower()]) or "")
    for n in _runs(rest):
        levels.add(_floor(n) or "")
    out["ground_floor"] = bool(_GROUND_FLOOR.search(rest)) and not _GROUND_OTHER.search(rest)
    if _ES_GROUND.search(rest) or out["ground_floor"]:
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
    # An ordinal no reader placed: answering without it would narrow.
    out["unread"] = sort_levels(f"{LS.FLOOR_PREFIX}{n}" for n in _ordinals_named(rest)
                                if f"{LS.FLOOR_PREFIX}{n}" not in out["levels"])
    # "1st�4th": a character no reader knows between two floor numbers (an
    # export ate the dash). A span or a list: not settled, so not read.
    out["garbled"] = bool(_GARBLED.search(rest))
    out["rest"] = rest
    return out


# ── ACCOUNTING: every level the words state, held against the answer ───────
#: Round 2 (adversarial review 1, C2/M10): per-phrase readers kept missing
#: phrasings ("floors 2 3 4" -> 2, "1st floor to roof" -> {1, ROOF}, "above 2nd
#: floor" -> 2). So the check is on the RESULT: the words are cut into tokens,
#: every number, ordinal and level noun in a chain that touches a level word is
#: a STATED level, and an answer missing one is no answer. Spans to a named
#: level and open-ended ranges expand against the frame only when the frame is
#: complete (its storey count is known); otherwise they abstain.

#: A dotted or timed number ("BC 3301.13.13", "8:00") is one token and no floor.
_TOKEN = re.compile(r"\d+(?:[.:]\d+)+|\d+\s*(?:st|nd|rd|th)\b|\d+(?:er|ro|do|to|vo|no|mo)\b|\d+|[^\W\d_]+\.?|\S",
                    re.I)
_NAMED_LEVEL = {"roof": LS.ROOF, "rooftop": LS.ROOF, "techo": LS.ROOF, "azotea": LS.ROOF, "mezz": LS.MEZZANINE,
                "mezzanine": LS.MEZZANINE, "mezzanina": LS.MEZZANINE, "cellar": LS.CELLAR, "basement": LS.CELLAR,
                "sotano": LS.CELLAR, "sótano": LS.CELLAR, "bulkhead": LS.BULKHEAD}
_LVL_WORDS = {"floor", "floors", "fl", "fls", "flr", "flrs", "level", "levels", "lvl", "lvls", "piso", "pisos",
              "story", "storey", "stories", "storeys", "nivel", "niveles"}
_CONNECT = {"and", "y", "to", "thru", "through", "al", "a", "up", "until", "till", "hasta", "the", "on", "at", "in",
            "of", "el", "la", "los", "las", "en", "del", "de", "from", "desde"}
_CONNECT_PUNCT = set(",&/+-–—#.;:()|'")
_SPAN_WORDS = {"to", "thru", "through", "al", "a", "until", "till", "hasta"}
_FLOORREF = (rf"(?:(\d{{1,2}})\s*(?:st|nd|rd|th|er|ro|do|to|vo|no|mo)?"
             rf"|\b({'|'.join(_EN_ORD_WORD)}|{_ES_WORDS})\b)")
_LVL_OPT = r"(?:\s*(?:floors?|flrs?|fls?|fl|levels?|pisos?)\b\.?)?"
_TO = r"\s*(?:-|–|—|\bup\s+to\b|\bto\b|\bthru\b|\bthrough\b|\bal\b|\ba\b|\bhasta\b|\buntil\b|\btill\b)\s*(?:the\s+|el\s+|la\s+)?"
_NAMED_RX = r"\b(roof(?:top)?|techo|azotea|mezz\w*|bulkhead|cellar|basement|s[oó]tano)\b"
_SPAN_NAMED = (re.compile(rf"{_FLOORREF}{_LVL_OPT}{_TO}{_NAMED_RX}", re.I),
               re.compile(rf"{_NAMED_RX}{_TO}(?:floors?\s+|pisos?\s+)?{_FLOORREF}", re.I),
               re.compile(rf"{_NAMED_RX}{_TO}{_NAMED_RX}", re.I))
_OPEN_UP = (re.compile(rf"{_FLOORREF}{_LVL_OPT}\s*(?:(?:and|&|y)\s*)?(?:up\b(?!\s*(?:to|thru|through|until)\b)|above\b"
                       rf"|higher\b|(?:para\s+|hacia\s+)?arriba\b)", re.I),
            re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)?(?:\s*(?:floors?|fl)\b\.?)?\s*\+(?!\s*\d)()", re.I))
_OPEN_ABOVE = (re.compile(rf"\b(?:above|over|encima\s+del?|sobre)\s+(?:the\s+|el\s+)?(?:floors?\s+|pisos?\s+)?{_FLOORREF}",
                          re.I),
               re.compile(rf"\b(?:floors?|levels?|pisos?)\s+(?:above|over)\s+(?:the\s+)?{_FLOORREF}", re.I))
_RELATIVE = re.compile(r"\b(?:under|underneath|underside|beneath|below|between|bajo|debajo|entre|upper|lower"
                       r"|bottom|above|encima|arriba|abajo)\b|(?<!roof )\btop\b", re.I)
_NEGATION = re.compile(r"\b(?:not|except|excluding|exclude|excl|other\s+than|minus|but|excepto|menos|salvo|sin)\b",
                       re.I)

R_OPEN = "open_or_named_span_needs_a_complete_frame"
R_RELATIVE = "relative_place"
R_NEGATION = "a_level_excluded"
#: A span or open range expanded against a COMPLETE frame: declared, never silent.
R_EXPANDED = "expanded_against_the_frame"


def _ref_n(m: "re.Match[str]", a: int = 1) -> Optional[int]:
    if m.group(a):
        return int(m.group(a))
    w = m.group(a + 1)
    return _item_n(w) if w else None


def _chains(rest: str) -> List[Dict[str, Any]]:
    """Maximal runs of level material: numbers, ordinals, level words, level
    nouns and the words that join them. A chain touching a level word, an
    ordinal or a level noun STATES every number in it."""
    has_word = bool(_HAS_LVL_WORD.search(rest))
    chains: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None

    def close():
        if cur and cur["anchor"] and cur["stated"]:
            cur["text"] = rest[cur["start"]:cur["end"]]
            chains.append(cur)

    for m in _TOKEN.finditer(rest):
        tok = m.group(0)
        low = tok.lower().rstrip(".")
        kind, val = "word", None
        if re.fullmatch(r"\d{1,2}", tok):
            kind, val = "num", int(tok)
        elif re.fullmatch(r"\d{1,2}\s*(?:st|nd|rd|th)|\d{1,2}(?:er|ro|do|to|vo|no|mo)", tok, re.I):
            kind, val = "anchor", int(re.match(r"\d+", tok).group(0))
        elif low in _LVL_WORDS:
            kind = "anchor"
        elif low in _NAMED_LEVEL:
            kind, val = "anchor", _NAMED_LEVEL[low]
        elif has_word and (low in _EN_ORD_WORD or low in _ES_ORDINAL):
            kind, val = "anchor", _item_n(low)
        elif low in _CONNECT or tok in _CONNECT_PUNCT:
            kind = "connect"
        if kind == "word":
            close()
            cur = None
            continue
        if cur is None:
            if kind == "connect":
                continue
            cur = {"start": m.start(), "end": m.end(), "anchor": False, "stated": set()}
        cur["end"] = m.end() if kind != "connect" else cur["end"]
        cur["anchor"] = cur["anchor"] or kind == "anchor"
        if kind == "connect" and (tok in "-–—" or low in _SPAN_WORDS):
            cur["span"] = True
        elif kind == "connect" and (tok in ",&/+" or low in ("and", "y")):
            cur["span"] = False
        if isinstance(val, int):
            # "1st floor up to 3rd floor": a span between two numbers states every floor between.
            if cur.get("span") and cur.get("last") is not None:
                lo, hi = sorted((cur["last"], val))
                cur["stated"] |= {f"{LS.FLOOR_PREFIX}{n}" for n in range(lo, hi + 1)}
            cur["last"], cur["span"] = val, False
        if val is not None:
            cur["stated"].add(val if isinstance(val, str) else f"{LS.FLOOR_PREFIX}{val}")
    close()
    return chains


def _expand(lo: int, frame: Set[str], *, inclusive: bool, to_roof: bool) -> Optional[List[str]]:
    """The frame's levels from floor `lo` up, or None when the frame cannot say
    (a mezzanine whose place in the order is unknown, a floor the frame lacks)."""
    nums = sorted(n for n in (LS.floor_number(t) for t in frame) if n is not None)
    if not nums or f"{LS.FLOOR_PREFIX}{lo}" not in frame:
        return None
    start = lo if inclusive else lo + 1
    out = [f"{LS.FLOOR_PREFIX}{n}" for n in nums if n >= start]
    if LS.MEZZANINE in frame:
        if not (inclusive and lo == nums[0]):
            return None          # where the mezzanine sits is not in the frame
        out.append(LS.MEZZANINE)
    if to_roof:
        if LS.ROOF not in frame:
            return None
        out.append(LS.ROOF)
    return out or None


def _structural(r: Dict[str, Any], levels: List[str], frame: Set[str], complete: bool
                ) -> Tuple[List[str], Optional[str], List[str], bool]:
    """(levels, abstention reason or None, extra candidates, expanded)."""
    rest = r.get("rest") or ""
    chains = _chains(rest)
    stated = set().union(*(c["stated"] for c in chains)) if chains else set()
    if (stated or levels) and _NEGATION.search(rest):
        return levels, R_NEGATION, sorted(stated), False
    expanded = False
    for rx in _SPAN_NAMED:
        for m in rx.finditer(rest):
            named = [g for g in m.groups() if g and re.fullmatch(_NAMED_RX, g, re.I)]
            if len(named) != 1 or not re.match(r"roof|techo|azotea", named[0], re.I):
                return levels, R_OPEN, sorted(stated), False     # mezzanine, cellar, two named ends
            lo = _ref_n(m, 1) if m.re is _SPAN_NAMED[0] else _ref_n(m, 2)
            bare = re.search(r"\d", m.group(0)) and not (_ORD_NUM.search(m.group(0)) or _HAS_LVL_WORD.search(rest))
            spread = _expand(lo, frame, inclusive=True, to_roof=True) if (complete and lo and not bare) else None
            if spread is None:
                return levels, R_OPEN, sorted(stated), False
            levels, expanded = sort_levels(set(levels) | set(spread)), True
    for rx, inclusive in ((_OPEN_UP[0], True), (_OPEN_UP[1], True), (_OPEN_ABOVE[0], False), (_OPEN_ABOVE[1], False)):
        for m in rx.finditer(rest):
            lo = _ref_n(m, 1)
            spread = _expand(lo, frame, inclusive=inclusive, to_roof=False) if (complete and lo) else None
            if spread is None:
                return levels, R_OPEN, sorted(stated), False
            if not inclusive:
                levels = [lv for lv in levels if lv != f"{LS.FLOOR_PREFIX}{lo}"]
                stated.discard(f"{LS.FLOOR_PREFIX}{lo}")
            levels, expanded = sort_levels(set(levels) | set(spread)), True
    if not expanded and (stated or levels or _HAS_LVL_WORD.search(rest)) and _RELATIVE.search(rest):
        return levels, R_RELATIVE, sorted(stated), False
    missing = sorted(stated - set(levels) - {LS.GROUND})
    if missing:
        return levels, R_UNREAD, missing, False
    # Two places with words between them that bind differently: which words go
    # with which place is not settled by one answer ("Framers 3rd floor
    # plumbers 1st floor"). bind_clauses splits them where a joining word does.
    valued = [set(read(c["text"])["levels"]) | c["stated"] for c in chains]
    if len(valued) >= 2 and len({frozenset(v) for v in valued}) > 1:
        return levels, R_TRADES, sorted(stated), False
    return levels, None, [], expanded


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
         source: str = FREE_TEXT, ground_level: Optional[str] = None,
         frame_complete: bool = False) -> Dict[str, Any]:
    """{levels, space, area, certainty: exact|constrained|none, reason,
    candidates, spaces_read, source}. See the module docstring. Total.

    `ground_level`: the frame's statement that GROUND is this level (frame_from
    sets it only when the project says the first floor is at grade with nothing
    below). Without it "ground floor" abstains on a frame that lacks GROUND.

    A sentence giving different trades different floors abstains (R_TRADES):
    the union would put every trade on every floor. bind_clauses reads it.

    `frame_complete`: the frame's numbered floors are all of the building's
    (frame_from: a storey count is on record). Only then does a span to the roof
    or an open range ("2nd floor and up", "above 2nd floor") expand against it,
    with reason R_EXPANDED; otherwise those abstain."""
    return _bind(text, project_levels, project_spaces, source=source, ground_level=ground_level, split=True,
                 complete=frame_complete)


def _bind(text: Any, project_levels: Optional[Iterable[str]], project_spaces: Any, *, source: str,
          ground_level: Optional[str], split: bool, complete: bool = False) -> Dict[str, Any]:
    r = read(text, source=source)
    frame = set(project_levels or ())
    spaces = _spaces(project_spaces)
    tags = _tags_named(r["text"] if source != DOB_WORK_ON_FLOOR else dob_text(r["text"]), r["units"], spaces) \
        if source != PHOTO_VISIBLE_TEXT else [u for u in r["units"] if u in spaces]
    levels, area = list(r["levels"]), r["area"]
    cands = levels + r["corridor"]
    grounded = False

    def no(reason: str, extra: Sequence[str] = ()) -> Dict[str, Any]:
        return _result([], None, area, NONE, reason, list(cands) + list(extra), source, tags)

    if not frame:
        return no(R_NO_FRAME)
    if r["choice"] and (levels or tags or r["units"] or re.search(r"\d", r["text"])):
        return no(R_CHOICE)
    if split and source in (FREE_TEXT, LOG_ROW, PHOTO_WHERE) and _mixed_trades(r["text"], frame, project_spaces,
                                                                             ground_level):
        return no(R_TRADES)
    if r["unread"] or r["garbled"]:
        return no(R_UNREAD, r["unread"])
    if (LS.GROUND in levels and LS.GROUND not in frame and ground_level and ground_level in frame
            and r["ground_floor"]):
        levels = sort_levels(ground_level if lv == LS.GROUND else lv for lv in levels)
        grounded = True
    expanded = False
    if source != PHOTO_VISIBLE_TEXT:
        levels, why, extra, expanded = _structural(r, levels, frame, complete)
        if why:
            return no(why, extra)
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
        one = R_GROUND if grounded else R_SPACE if space else R_LEVEL
        return _result(levels, space, area, EXACT if len(levels) == 1 else CONSTRAINED,
                       R_EXPANDED if expanded else one if len(levels) == 1 else R_LEVELS, cands, source, tags)
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


# ── CLAUSES: several trades, several floors, one sentence ─────────────────

#: A comma starts a new clause unless a floor number follows it ("1st, 2nd &
#: 3rd floors" is one list). ";" always does; ". " before a letter does.
_SENTENCE_SPLIT = re.compile(r"\s*;\s*|(?<![Ff]l)(?<![Aa]pt)(?<![Nn]o)\.\s+(?=[A-Za-z])")
_COMMA_SPLIT = re.compile(rf",\s*(?!(?:and\s+|&\s*|y\s+)?(?:{_ITEM})(?![A-Za-z]))", re.I)
_LABEL_PREFIX = re.compile(r"^\s*[A-Z][A-Z ]{2,}:\s*")
_NOT_TRADE = re.compile(
    rf"(?:\b{_LVL_WORD}\b\.?|(?<!\w)\d{{1,2}}(?:\s*(?:st|nd|rd|th)|er|ro|do|to|vo|no|mo)?\b|#"
    rf"|\b(?:{'|'.join(_EN_ORD_WORD)}|{_ES_WORDS})\b|\b(?:roof(?:top)?|mezz(?:anine)?|cellar|basement|bulkhead"
    r"|ground|planta\s+baja|on|at|in|of|the|to|thru|through|from|and|en|el|la|los|las|del|de|al|y|a)\b|[-–—&+])",
    re.I)


def _names_a_place(clause: str) -> bool:
    r = read(clause)
    return bool(r["levels"] or r["unread"] or r["corridor"] or _ORD_NUM.search(clause))


def _top_level_commas(sentence: str) -> List[str]:
    """Split on commas outside parentheses ("(layout, track and studs)" is one)."""
    out, depth, start = [], 0, 0
    for m in re.finditer(r"[()]|" + _COMMA_SPLIT.pattern, sentence, re.I):
        if m.group(0) == "(":
            depth += 1
        elif m.group(0) == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(sentence[start:m.start()])
            start = m.end()
    return out + [sentence[start:]]


_JOINER = re.compile(r"\s+(?:and|y|while|plus|&)\s+", re.I)


def _split_joined(part: str) -> List[str]:
    """"Framers on 3rd floor and plumbers on 1st floor" is two clauses: split on
    and / y / while / & where BOTH sides name a trade and a place. "1st and 2nd
    floor" has no trade on its left and stays one."""
    for m in _JOINER.finditer(part):
        left, right = part[:m.start()], part[m.end():]
        if all(_names_a_place(x) and re.search(r"[^\W\d_]{3,}", _trade_text(x)) for x in (left, right)):
            return [left] + _split_joined(right)
    return [part]


def _clauses(text: Any) -> List[str]:
    """Sentences, then their top-level comma parts. A part that names no place
    is the lead-in of the next part in its sentence ("Quality Plumbing worked on
    rough-in, Plumbing on the 1st through 4th floors" is one clause)."""
    t = _LABEL_PREFIX.sub("", " ".join(str(text or "").split())).strip()
    out: List[str] = []
    for sentence in _SENTENCE_SPLIT.split(t):
        held = ""
        for part in (p for piece in _top_level_commas(sentence or "") for p in _split_joined(piece)):
            part = part.strip(" .")
            if not part:
                continue
            joined = f"{held}, {part}" if held else part
            if _names_a_place(part):
                out.append(joined)
                held = ""
            else:
                held = joined
        if held:
            out.append(held)
    return out


def _trade_text(clause: str) -> str:
    """The clause's words with its place words taken out: "Framers on the
    3rd-4th floors" -> "Framers"."""
    s = re.sub(r"\(\s*\)", " ", _NOT_TRADE.sub(" ", clause))
    return " ".join(s.split()).strip(" ,./:")


def _elide(clause: str, sentence_has_level_word: bool) -> str:
    """"Plumber on the 1st" in a sentence that said "floors" once: the ordinal
    is a floor. Only inside a sentence that named the level word."""
    if sentence_has_level_word and not _HAS_LVL_WORD.search(clause) and not _GARBLED.search(clause):
        return _ORD_NUM.sub(lambda m: m.group(0) + " fl", clause)
    return clause


def _frame_parts(frame: Any) -> Tuple[List[str], Any, Optional[str], bool]:
    if isinstance(frame, dict):
        return ([] if frame.get("unreadable") else list(frame.get("levels") or ()), frame.get("spaces"),
                frame.get("ground_level"), bool(frame.get("complete")))
    return list(frame or ()), None, None, False


def bind_clauses(text: Any, frame: Any, *, source: str = FREE_TEXT) -> List[Dict[str, Any]]:
    """[{trade_text, text, levels, certainty, reason}] one per clause, each
    bound on its own. "Framers on the 3rd-4th floors, Plumber on the 1st-4th"
    is framers on 3-4 and plumbers on 1-4, never both on 1-4. `frame`: the
    frame_from dict (or a plain level list). A clause with no place abstains."""
    levels, spaces, ground, complete = _frame_parts(frame)
    parts = _clauses(text) or [" ".join(str(text or "").split())]
    has_word = bool(_HAS_LVL_WORD.search(" ".join(parts)))
    out = []
    for c in parts:
        b = _bind(_elide(c, has_word), levels, spaces, source=source, ground_level=ground, split=False,
                  complete=complete)
        out.append({"trade_text": _trade_text(c), "text": c, "levels": b["levels"] if b["certainty"] != NONE else [],
                    "certainty": b["certainty"], "reason": b["reason"]})
    return out


def _mixed_trades(text: str, levels: Iterable[str], spaces: Any, ground: Optional[str]) -> bool:
    """Two or more clauses that each name a trade and a place, and the places
    differ."""
    parts = _clauses(text)
    if len(parts) < 2:
        return False
    placed = [c for c in bind_clauses(text, {"levels": list(levels), "spaces": spaces, "ground_level": ground})
              if c["certainty"] != NONE and c["levels"] and re.search(r"[A-Za-z]{3,}", c["trade_text"])]
    return len(placed) >= 2 and len({tuple(c["levels"]) for c in placed}) > 1


def place(text: Any, frame: Dict[str, Any], *, source: str = FREE_TEXT) -> Dict[str, Any]:
    """work_state.places_in's shape, bound to a project: {"levels", "space"}.
    An abstention is no level. With no plan tags in the frame the space is the
    one places_in has always read, so nothing changes where nothing is known."""
    # An UNREADABLE frame (server _project_place_frame failed) binds against
    # no levels: an abstention, never the words' own guess.
    b = bind(text, [] if frame.get("unreadable") else frame.get("levels"), frame.get("spaces"), source=source,
             ground_level=frame.get("ground_level"), frame_complete=bool(frame.get("complete")))
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
    # GROUND is the first floor only on the project's own say-so: no cellar and
    # no sub-cellar (False, not unset), the first floor at grade, and no plan
    # sheet or log naming a level below it.
    ground, ground_basis = None, []
    first = f"{LS.FLOOR_PREFIX}1"
    if (p.get("has_cellar") is False and p.get("has_sub_cellar") is False and p.get("first_floor_at_grade") is True
            and first in basis and not any(t in basis for t in (LS.CELLAR, LS.SUB_CELLAR, LS.GROUND))):
        ground, ground_basis = first, ["has_cellar=False", "has_sub_cellar=False", "first_floor_at_grade"]
    return {"levels": sort_levels(basis), "spaces": spaces or {}, "basis": {k: v for k, v in basis.items()},
            "known": known, "excluded": excluded, "ground_level": ground, "ground_basis": ground_basis,
            # Every numbered floor is known only when the project states its storey count.
            "complete": bool(stories)}


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
