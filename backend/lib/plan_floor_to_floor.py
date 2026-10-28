"""Floor-to-floor, derived from a section's level marks - and never a ceiling height.

NOT lib.plan_levels. That module (#891) reads which level of the set a
QUESTION means, from the set's sheet titles; this one reads the ELEVATIONS a
section prints. It reuses #891's level reading rather than building a second
one: every mark is named through the same closed vocabulary
(lib.plans.level_suggestion.tokens_in - SECOND FLOOR is FLOOR_2, MEZZANINE is
MEZZANINE), so a question #891 maps to a level ("5th floor" = the mezzanine
on this set) is answered with that level's storey.

Operator's rule (Roy, 2026-10-27): "derive floor-to-floor from A-300's level
marks; answer "ceiling height not shown; floor-to-floor 10'-0" (A-300.00)".
Floor-to-floor must never bind as a ceiling height."

WHAT A LEVEL MARK IS
  The text a section or elevation prints beside each level line:
  `SECOND FLOOR 43.37' +10'-0"` - a name, an elevation in decimal feet, and
  the level's height above the datum in feet-inches. Measured on 588 Boyland
  (AR - 3.28.25.pdf p20, A-300.00 LONGITUDINAL SECTIONS), bottom to top:

      BASE PLANE    33.37'    0'-0"
      SECOND FLOOR  43.37'  +10'-0"
      THIRD FLOOR   53.37'  +20'-0"
      FOURTH FLOOR  63.37'  +30'-0"
      MEZZANINE     73.37'  +40'-0"
      ROOF          83.37'  +50'-0"
      BULKHEAD      93.37'  +60'-0"

  Consecutive marks are 10'-0" apart every time, by both columns, by the
  drawn spacing at the sheet's 3/16" = 1'-0" (135 pt), and by the six 10'-0"
  strings the sheet prints between them. A-301.00 and every plan and
  elevation that prints a mark print the same ones.

THE DERIVATION (`derive`)
  The marks of ONE page, ordered by elevation; each interval between
  consecutive marks is a floor-to-floor. A mark's two columns must agree on
  every interval (elevation difference x 12 = height difference, within the
  0.01 ft the elevation is printed to), and a name printed twice must say the
  same thing twice - otherwise nothing is derived and the reason is said.
  Every other current page that prints a mark of the same name must agree
  with it too (`conflicts`); one that does not withholds every figure.

WHY IT IS NEVER A CEILING HEIGHT
  A ceiling height is measured from the finished floor to the ceiling, and a
  floor-to-floor from one floor to the next: the slab and the ceiling's
  build-up lie between them, so a ceiling height is always less than the
  floor-to-floor of its storey. The gate (plan_search.answer_is_grounded)
  therefore decides a clause that names a ceiling WITHOUT any level evidence,
  and refuses a figure in it equal to a floor-to-floor or at least the
  largest one.

"NOT SHOWN" NEEDS A WARRANT
  "Ceiling height not shown" is a claim about the drawings. It is said only
  when the search counted the project's current records and found none that
  names a ceiling and a height where it prints a dimension
  (`names_a_ceiling_height`); otherwise the floor-to-floor is said alone.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import plan_dimensions as _dims
from lib.plans.level_suggestion import LABELS, floor_number, tokens_in

#: A level row is derived at question time from the records that print the
#: marks, never stored: no pass writes it and nothing needs a rebuild.
RECORD_TYPE = "levels"
SOURCE = "level_marks"

#: NAME  ELEVATION'  +F'-I" - the name in capitals, the elevation in decimal
#: feet, the height above the datum as feet-inches (sign optional: the datum
#: prints 0'-0").
LEVEL_MARK = re.compile(
    r"(?P<name>[A-Z][A-Z0-9.&/\-]*(?:\s+[A-Z][A-Z0-9.&/\-]*)*)\s+"
    r"(?P<elev>\d{1,4}(?:\.\d{1,3})?)\s*'\s*"
    r"(?P<sign>[+\-±]?)\s*(?P<rel>\d{1,3}\s*'\s*-\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\s*\")")
#: Mongo's spelling of the same shape, to fetch candidates (re-checked above).
LEVEL_MARK_QUERY = r"[A-Z]\s+\d+(\.\d+)?\s*'\s*[+\-]?\s*\d+\s*'\s*-\s*\d+"

#: What a ceiling is printed as: CEILING(S), CLG, CLG.
_CEILING = re.compile(r"(?<![A-Za-z])(?:ceilings?|clgs?\.?)(?![A-Za-z])", re.I)
#: What a height is printed as.
_HEIGHT = re.compile(r"(?<![A-Za-z])(?:heights?|hights?|hgt\.?|ht\.?|high|clear(?:ance)?|"
                     r"a\.?\s?f\.?\s?f\.?)(?![A-Za-z])", re.I)
#: A floor-to-floor, by name.
_FLOOR_TO_FLOOR = re.compile(
    r"(?<![A-Za-z])(?:floor[\s\-]*to[\s\-]*floor|f\.?\s?t\.?\s?f\.?|flr[\s\-.]*to[\s\-]*flr\.?|"
    r"stor(?:e?y|ies)\s+heights?)(?![A-Za-z])", re.I)
#: The elevation is printed to 0.01 ft: the two columns of a mark agree when
#: they differ by less than that, in inches.
_TOL_IN = Fraction(12, 100)
#: A section, by its title.
_SECTION = re.compile(r"\bSECTIONS?\b", re.I)


def is_level_record(r: Dict[str, Any]) -> bool:
    return (r or {}).get("record_type") == RECORD_TYPE


def marks(text: str) -> List[Dict[str, Any]]:
    """Every level mark `text` prints: name, elevation (feet), height above
    the datum (inches), and the mark as printed."""
    out = []
    for m in LEVEL_MARK.finditer(text or ""):
        f = _dims.find(m.group("rel"))
        if not f or not f[0].dims or f[0].dims[0].unit != "in":
            continue
        rel = Fraction(f[0].dims[0].value) * (-1 if m.group("sign") == "-" else 1)
        name = re.sub(r"\s+", " ", m.group("name")).strip().upper()
        out.append({"name": name, "token": level_token(name),
                    "elevation_ft": Fraction(m.group("elev")), "height_in": rel,
                    "text": re.sub(r"\s+", " ", m.group(0)).strip()})
    return out


def level_token(name: str) -> Optional[str]:
    """The set's level token for a mark's name (#891's vocabulary,
    lib.plans.level_suggestion): SECOND FLOOR -> FLOOR_2. None when the name
    is not exactly one level (BASE PLANE is a datum, not a level)."""
    toks = tokens_in(name or "", field_is_a_level=True)[0]
    return toks[0] if len(toks) == 1 else None


def level_label(token: Optional[str]) -> str:
    """#891's label for a level token: "Mezzanine", "2nd Floor"."""
    if not token:
        return ""
    n = floor_number(token)
    if n is None:
        return LABELS.get(token, token)
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} Floor"


def is_level_mark_record(r: Dict[str, Any]) -> bool:
    """A record that prints a level mark (and is not the derived row)."""
    return not is_level_record(r) and bool(marks(str((r or {}).get("quote") or "")))


def is_level_evidence(r: Dict[str, Any]) -> bool:
    return is_level_record(r) or is_level_mark_record(r)


def feet_inches(inches: Fraction) -> str:
    """120 -> 10'-0"; 125.5 -> 10'-5 1/2"."""
    sign = "-" if inches < 0 else ""
    inches = abs(Fraction(inches))
    ft, rest = divmod(inches, 12)
    whole = int(rest)
    frac = rest - whole
    tail = f" {frac.numerator}/{frac.denominator}" if frac else ""
    return f"{sign}{int(ft)}'-{whole}{tail}\""


def derive(page_marks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """{"levels", "intervals", "why"} for the marks of ONE page. `why` is
    None when every interval is derived; otherwise nothing is derived."""
    by_name: Dict[str, Dict[str, Any]] = {}
    for m in page_marks:
        prev = by_name.get(m["name"])
        if prev and (prev["elevation_ft"] != m["elevation_ft"]
                     or prev["height_in"] != m["height_in"]):
            return {"levels": [], "intervals": [],
                    "why": f"{m['name']} is marked twice: {prev['text']} and {m['text']}"}
        by_name[m["name"]] = m
    levels = sorted(by_name.values(), key=lambda m: m["elevation_ft"])
    if len(levels) < 2:
        return {"levels": levels, "intervals": [], "why": "fewer than two level marks"}
    intervals = []
    for lo, hi in zip(levels, levels[1:]):
        by_height = hi["height_in"] - lo["height_in"]
        by_elev = (hi["elevation_ft"] - lo["elevation_ft"]) * 12
        if by_height <= 0 or abs(by_height - by_elev) >= _TOL_IN:
            return {"levels": levels, "intervals": [],
                    "why": (f"{lo['text']} to {hi['text']}: the elevations differ by "
                            f"{float(by_elev / 12):.2f}' and the heights by "
                            f"{feet_inches(by_height)}")}
        intervals.append({"from": lo["name"], "to": hi["name"], "inches": by_height,
                          "from_token": lo.get("token"), "to_token": hi.get("token"),
                          "text": feet_inches(by_height)})
    return {"levels": levels, "intervals": intervals, "why": None}


def conflicts(derived: Dict[str, Any], others: Iterable[Tuple[str, Dict[str, Any]]]
              ) -> List[str]:
    """Every mark another page prints under a level name the derivation has,
    that says something else. `others`: (where, mark)."""
    known = {m["name"]: m for m in derived.get("levels") or []}
    out = []
    for where, m in others:
        k = known.get(m["name"])
        if k and (k["elevation_ft"] != m["elevation_ft"] or k["height_in"] != m["height_in"]):
            out.append(f"{where} prints {m['text']}, the section {k['text']}")
    return out


def choose_section(pages: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The page the floor-to-floor is read from: a SECTION by its title,
    with the most marks, the lowest sheet number on a tie. `pages`: each
    {"sheet_number", "sheet_title", "marks", ...}. None when no section
    prints two marks."""
    cands = [p for p in pages if _SECTION.search(str(p.get("sheet_title") or ""))
             and len({m["name"] for m in p.get("marks") or []}) >= 2]
    if not cands:
        return None
    return sorted(cands, key=lambda p: (-len({m["name"] for m in p["marks"]}),
                                        str(p.get("sheet_number") or "")))[0]


# ── the question and the clause ────────────────────────────────────────────

def names_ceiling(text: str) -> bool:
    return bool(_CEILING.search(text or ""))


def names_floor_to_floor(text: str) -> bool:
    return bool(_FLOOR_TO_FLOOR.search(text or ""))


def is_level_subject(subject: str, attribute: str = "") -> bool:
    """A question the floor-to-floor answers or must be told apart from: a
    ceiling's height, or a floor-to-floor / storey height by name."""
    text = f"{subject or ''} {attribute or ''}"
    return (names_ceiling(text) and bool(_HEIGHT.search(text))) or names_floor_to_floor(text)


def names_a_ceiling_height(naming: str, value_texts: Sequence[str]) -> bool:
    """Does one part of a record (plan_search.value_parts: the text naming
    it, the texts its values are read from) name a ceiling AND a height and
    print a dimension? The warrant for "not shown" is that no part does.
    CLG and HT count here although no table of this set defines them: the
    wider the count, the rarer "not shown"."""
    if not (names_ceiling(naming) and _HEIGHT.search(naming or "")):
        return False
    return any(f.dims for t in value_texts
               for f in _dims.find(_dims.unreverse(_dims.mask_quotation_marks(t or ""))))


# ── the derived row ────────────────────────────────────────────────────────

_CITE = ("project_id", "company_id", "file_id", "file_hash", "file_name", "page_id",
         "page_number", "sheet_number", "sheet_title", "discipline", "issued_date",
         "filing_id", "floors")


def level_record(section: Dict[str, Any], derived: Dict[str, Any],
                 conflicting: Sequence[str], agreeing: Sequence[str],
                 ceiling_asked: bool, ceiling_heights_printed: Optional[int],
                 asked_levels: Sequence[str] = ()) -> Dict[str, Any]:
    """The row search_plans returns: cited to the section, quoting its marks
    as printed, carrying the floor-to-floor intervals - or why there are
    none. `ceiling_heights_printed`: how many current record parts name a
    ceiling height with a dimension (None: not counted). `asked_levels`: the
    set's level tokens the question named, as #891 mapped them
    (search_plans `interp["levels"]`)."""
    why = derived.get("why") or (("level marks disagree: " + "; ".join(conflicting[:3]))
                                 if conflicting else None)
    rec = {k: section.get(k) for k in _CITE if section.get(k) is not None}
    rec.update({
        "record_type": RECORD_TYPE, "source": SOURCE, "tier": "text_layer",
        "ordinal": -1, "label": None, "subject_terms": [],
        "quote": " | ".join(m["text"] for m in derived.get("levels") or []),
        "payload": {
            "levels": [{"name": m["name"], "token": m.get("token"),
                        "elevation_ft": float(m["elevation_ft"]),
                        "height": feet_inches(m["height_in"])}
                       for m in derived.get("levels") or []],
            "floor_to_floor": ([] if why else
                               [{"from": i["from"], "to": i["to"], "text": i["text"],
                                 "from_token": i.get("from_token"), "to_token": i.get("to_token"),
                                 "inches": float(i["inches"])} for i in derived["intervals"]]),
            "asked_levels": [t for t in asked_levels or [] if t],
            "why": why,
            "same_marks_on": list(agreeing),
            "ceiling_asked": bool(ceiling_asked),
            "ceiling_heights_printed": ceiling_heights_printed,
        },
    })
    return rec


def _intervals(r: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    return [] if p.get("why") else list(p.get("floor_to_floor") or [])


def stated_floor_to_floor(records: Sequence[Dict[str, Any]]) -> List[Fraction]:
    """The floor-to-floor figures a derived row states (inches) - what a
    clause naming a floor-to-floor may say."""
    out = []
    for r in records or []:
        if is_level_record(r):
            out += [Fraction(i["inches"]).limit_denominator(64) for i in _intervals(r)]
    return sorted(set(out))


def floor_to_floor_in(records: Sequence[Dict[str, Any]]) -> List[Fraction]:
    """Every floor-to-floor the records carry or imply (inches): the derived
    rows' figures, and the intervals between the level marks any one
    returned page prints. What a ceiling height may never be."""
    out = set(stated_floor_to_floor(records))
    by_page: Dict[str, List[Dict[str, Any]]] = {}
    for r in records or []:
        if is_level_mark_record(r):
            by_page.setdefault(str(r.get("page_id") or id(r)), []).extend(
                marks(str(r.get("quote") or "")))
    for ms in by_page.values():
        d = derive(ms)
        out.update(i["inches"] for i in d["intervals"])
    return sorted(out)


def figure_texts(records: Sequence[Dict[str, Any]]) -> List[str]:
    """The figures a derived row states and the heights its marks print, as
    text: what an instrument puts to the gate as a value of the subject."""
    out = []
    for r in records or []:
        if is_level_record(r):
            p = r.get("payload") or {}
            out += [i["text"] for i in _intervals(r)]
            out += [lv["height"] for lv in p.get("levels") or []]
    return sorted(set(out))


# ── what is said ───────────────────────────────────────────────────────────

def _where(r: Dict[str, Any]) -> str:
    return str(r.get("sheet_number") or r.get("file_name") or "the section")


def answer_line(r: Dict[str, Any]) -> str:
    """The answer, as the operator ruled it: `Ceiling height not shown;
    floor-to-floor 10'-0" (A-300.00)`. Storeys that differ are named one by
    one; marks that disagree state no figure."""
    p = r.get("payload") or {}
    lead = ("Ceiling height not shown; " if p.get("ceiling_asked")
            and p.get("ceiling_heights_printed") == 0 else "")
    where = _where(r)
    if p.get("why"):
        body = f"floor-to-floor not stated - {p['why']} ({where})"
    else:
        ivs = _intervals(r)
        if not ivs:
            return ""
        # THE STOREY THE QUESTION NAMED (#891: "5th floor" = the mezzanine on
        # this set): the interval from that level's mark up. A level with no
        # mark of its own is not guessed at - every storey is said.
        asked = set(p.get("asked_levels") or [])
        mine = [i for i in ivs if i.get("from_token") in asked]
        ivs = mine or ivs
        # THE FIGURE BEFORE THE STOREY, every time: each clause after the
        # first then has nothing before its value, and so stays a
        # floor-to-floor clause for the gate (plan_search._level_kinds).
        groups: Dict[str, List[str]] = {}
        for i in ivs:
            groups.setdefault(i["text"], []).append(f"{i['from']} to {i['to']}")
        if len(groups) == 1 and not mine:
            body = f"floor-to-floor {ivs[0]['text']} ({where})"
        else:
            body = "floor-to-floor " + ", ".join(
                f"{t} {' and '.join(spans)}" for t, spans in groups.items()) + f" ({where})"
    line = lead + body
    return line[0].upper() + line[1:]


def render_level_evidence(records: Sequence[Dict[str, Any]]) -> str:
    """The derived row as the model is shown it: the marks, the intervals,
    the rule, and the sentence to answer with."""
    rows = [r for r in records or [] if is_level_record(r)]
    if not rows:
        return ""
    lines = []
    for r in rows:
        p = r.get("payload") or {}
        where = _where(r)
        marks_txt = ", ".join(f"{lv['name']} {lv['height']}" for lv in p.get("levels") or [])
        lines.append(f"Levels ({where}'s level marks, bottom to top): {marks_txt}.")
        if p.get("why"):
            lines.append(f"Floor-to-floor is NOT stated: {p['why']}.")
        else:
            lines.append("Floor-to-floor, the distance between consecutive marks: "
                         + "; ".join(f"{i['from']} to {i['to']} {i['text']}"
                                     for i in _intervals(r)) + ".")
        lines.append("A floor-to-floor is NOT a ceiling height (the slab and ceiling lie "
                     "between them): never state it, or any level's height, as a ceiling height.")
        if p.get("ceiling_asked"):
            if p.get("ceiling_heights_printed") == 0:
                lines.append("No current sheet prints a ceiling height (checked: no record "
                             "names a ceiling and a height beside a dimension).")
            line = answer_line(r)
            if line:
                lines.append(f"Answer a ceiling-height question with exactly: {line}")
    return "\n".join(lines)


__all__ = ["RECORD_TYPE", "LEVEL_MARK", "LEVEL_MARK_QUERY", "marks", "derive", "conflicts",
           "level_token", "level_label",
           "choose_section", "is_level_record", "is_level_mark_record", "is_level_evidence",
           "names_ceiling", "names_floor_to_floor", "is_level_subject",
           "names_a_ceiling_height", "level_record", "stated_floor_to_floor",
           "floor_to_floor_in", "figure_texts", "answer_line", "render_level_evidence",
           "feet_inches"]
