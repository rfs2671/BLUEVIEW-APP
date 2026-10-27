"""WHICH LEVEL OF THIS SET A PERSON MEANS.

Asked about the "5th floor ceiling" on a set whose numbered floors stop at
the fourth and whose next level up is a mezzanine (2026-10-27), the search
looked for the word 5TH, which no sheet prints, and found nothing. The owner
was not wrong: the mezzanine IS the fifth level he walks up to. The set calls
it something else.

So a level phrase in a question is read against the levels THE SET ITSELF
names (sheet titles and the index's floor column, read by the same closed
table the level suggestion uses - lib/plans/level_suggestion.tokens_in) and
mapped to them:

- a numbered floor the set has is that floor;
- an ordinal past the highest numbered floor is the next level up: the
  mezzanine if the set has one, then the roof;
- "top floor" is the highest occupied level - and when a mezzanine sits over
  the numbered floors it is either, so both are returned;
- roof / mezz / cellar / ground are the set's level of that name.

THE ANSWER SAYS THE MAPPING ("5th floor = Mezzanine (A-104) on this set").
A mapping nobody is shown is a guess; one he is shown he can correct.

QUERY INTERPRETATION ONLY. Nothing here decides what a record may say or
whether an answer binds - that is plan_search's gate, untouched. Pure, no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lib.plans.level_suggestion import (
    BELOW, CELLAR, FLOOR_PREFIX, GROUND, LABELS, MEZZANINE, ROOF, BULKHEAD,
    floor_number, tokens_in,
)

_ORDINAL_WORDS: Dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
}
_LEVEL_NOUN = r"(?:floor|flr|fl|level|lvl|story|storey)"
_ORD = r"(?:(\d{1,2})\s*(?:st|nd|rd|th)|(" + "|".join(_ORDINAL_WORDS) + r"))"

#: (kind, pattern). Anchored on a level noun or a level word, so "5 units" or
#: "phase 3" never become a floor.
_PHRASES = (
    ("numbered", re.compile(r"\b" + _ORD + r"\s*" + _LEVEL_NOUN + r"\b\.?", re.I)),
    ("numbered", re.compile(r"\b" + _LEVEL_NOUN + r"\s*#?\s*(\d{1,2})\b(?!\s*(?:st|nd|rd|th)\b)",
                            re.I)),
    ("top", re.compile(r"\b(?:top|highest|upper(?:most)?|uppermost)\s+"
                       r"(?:occupied\s+)?" + _LEVEL_NOUN + r"\b", re.I)),
    ("mezzanine", re.compile(r"\bmezz(?:anine)?\b\.?(?:\s+" + _LEVEL_NOUN + r"\b)?", re.I)),
    ("cellar", re.compile(r"\b(?:cellar|basement)\b(?:\s+" + _LEVEL_NOUN + r"\b)?", re.I)),
    ("ground", re.compile(r"\bground\s+" + _LEVEL_NOUN + r"\b", re.I)),
    ("roof", re.compile(r"\broof\s+(?:floor|level)\b|\b(?:on|at)\s+the\s+roof\b", re.I)),
)
#: A `floor` argument is a level by where it was written: "5", "5th" and
#: "fifth" there need no noun (level_suggestion makes the same distinction).
_BARE = re.compile(r"^\s*(?:(\d{1,2})(?:\s*(?:st|nd|rd|th))?|("
                   + "|".join(_ORDINAL_WORDS) + r"))\s*$", re.I)

_ROOF_FIELD = re.compile(r"^\s*(?:the\s+)?roof(?:\s+(?:floor|level))?\s*$", re.I)

_CEILING = re.compile(r"\b(?:ceilings?|clg|underside|overhead)\b", re.I)


def find_phrases(text: str, *, field_is_a_level: bool = False) -> List[Dict[str, Any]]:
    """The level phrases in `text`: [{said, kind, n, span}], in order."""
    t = str(text or "")
    if not t.strip():
        return []
    if field_is_a_level:
        m = _BARE.match(t)
        if m:
            n = int(m.group(1)) if m.group(1) else _ORDINAL_WORDS[m.group(2).lower()]
            return [{"said": _ordinal(n) + " floor", "kind": "numbered", "n": n,
                     "span": (0, len(t)), "raw": t.strip()}]
        if _ROOF_FIELD.match(t):
            return [{"said": "roof", "kind": "roof", "n": None,
                     "span": (0, len(t)), "raw": t.strip()}]
    out: List[Dict[str, Any]] = []
    taken: List[tuple] = []
    for kind, rx in _PHRASES:
        for m in rx.finditer(t):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            n = None
            if kind == "numbered":
                g = [x for x in m.groups() if x]
                n = int(g[0]) if g[0].isdigit() else _ORDINAL_WORDS[g[0].lower()]
            raw = m.group(0).strip()
            said = ((_ordinal(n) + " floor") if n is not None
                    else "roof" if kind == "roof" else raw.lower())
            out.append({"said": said, "kind": kind, "n": n, "span": (a, b), "raw": raw})
            taken.append((a, b))
    return sorted(out, key=lambda p: p["span"][0])


def _ordinal(n: int) -> str:
    suffix = "th"
    if not 11 <= n % 100 <= 13:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _order(token: str) -> tuple:
    n = floor_number(token)
    if n is not None:
        return (1, n)
    if token in BELOW:
        return (0, BELOW.index(token))
    return (2, (MEZZANINE, ROOF, BULKHEAD).index(token)
            if token in (MEZZANINE, ROOF, BULKHEAD) else 99)


def _sheet_rank(s: str) -> tuple:
    # An architectural sheet first: it is the one that DRAWS the level.
    return (0 if s.upper().startswith("A") else 1, s)


def set_levels(rows: Iterable[dict]) -> List[Dict[str, Any]]:
    """The levels this set names, bottom to top:
    [{token, label, floor, sheets, page_ids}].

    A sheet belongs to a level when its TITLE names that level and at most
    one other ("ROOF AND BULKHEAD PLAN"); an elevation whose title lists
    every floor is evidence that the level exists, not the sheet that draws
    it. A row with no title falls back to its floor column."""
    found: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        number = str(row.get("sheet_number") or "").strip()
        title_toks, _ = tokens_in(row.get("sheet_title") or "")
        fl = row.get("floors")
        fl = ", ".join(str(x) for x in fl) if isinstance(fl, (list, tuple)) else (fl or "")
        floor_toks: List[str] = []
        for src in (row.get("floor"), fl):
            for tok in tokens_in(src or "", field_is_a_level=True)[0]:
                if tok not in floor_toks:
                    floor_toks.append(tok)
        draws = title_toks if title_toks else floor_toks
        for tok in set(title_toks) | set(floor_toks):
            slot = found.setdefault(tok, {"sheets": [], "page_ids": []})
            if tok in draws and len(draws) <= 2:
                if number and number not in slot["sheets"]:
                    slot["sheets"].append(number)
                pid = row.get("_id")
                if pid is not None and str(pid) not in slot["page_ids"]:
                    slot["page_ids"].append(str(pid))
    out = []
    for tok in sorted(found, key=_order):
        n = floor_number(tok)
        out.append({"token": tok, "floor": n,
                    "label": LABELS.get(tok) or f"{_ordinal(n)} Floor",
                    "sheets": sorted(found[tok]["sheets"], key=_sheet_rank),
                    "page_ids": found[tok]["page_ids"]})
    return out


def _by_token(levels: Sequence[dict]) -> Dict[str, dict]:
    return {lv["token"]: lv for lv in levels or []}


def top_occupied(levels: Sequence[dict]) -> List[str]:
    """The highest level people occupy: the mezzanine when the set has one
    over its numbered floors, and the highest numbered floor."""
    have = _by_token(levels)
    nums = [lv["floor"] for lv in levels or [] if lv.get("floor")]
    out = []
    if MEZZANINE in have:
        out.append(MEZZANINE)
    if nums:
        out.append(f"{FLOOR_PREFIX}{max(nums)}")
    return out


def map_phrase(phrase: Dict[str, Any], levels: Sequence[dict]) -> Dict[str, Any]:
    """One phrase against the set's levels.

    {said, levels: [level...], how, restate}. `how` is one of
    same | next_up | top | named | ambiguous | absent; `restate` is True when
    the set's name for it differs from the user's, which is when the answer
    must say the mapping."""
    have = _by_token(levels)
    nums = sorted(lv["floor"] for lv in levels or [] if lv.get("floor"))
    kind, said = phrase.get("kind"), phrase.get("said") or ""

    def out(toks: Sequence[str], how: str) -> Dict[str, Any]:
        got = [have[t] for t in toks if t in have]
        return {"said": said, "kind": kind, "levels": got,
                "how": how if got else "absent",
                "restate": not (how == "same" and got)}

    if kind == "numbered":
        n = phrase.get("n") or 0
        tok = f"{FLOOR_PREFIX}{n}"
        if tok in have:
            return out([tok], "same")
        if nums and n > nums[-1]:
            above = [t for t in (MEZZANINE, ROOF) if t in have]
            i = n - nums[-1] - 1
            if i < len(above):
                return out([above[i]], "next_up")
        return out([], "absent")
    if kind == "top":
        toks = top_occupied(levels)
        return out(toks, "ambiguous" if len(toks) > 1 else "top")
    if kind == "mezzanine":
        return out([MEZZANINE], "same")
    if kind == "roof":
        return out([ROOF], "same")
    if kind == "cellar":
        return out([CELLAR], "same")
    if kind == "ground":
        if GROUND in have:
            return out([GROUND], "same")
        return out([f"{FLOOR_PREFIX}1"], "named")
    return out([], "absent")


def map_text(text: str, levels: Sequence[dict], *, field_is_a_level: bool = False
             ) -> List[Dict[str, Any]]:
    """Every level phrase in `text`, mapped."""
    return [map_phrase(p, levels) for p in find_phrases(text, field_is_a_level=field_is_a_level)]


def _name(lv: dict) -> str:
    s = lv.get("sheets") or []
    return f"{lv['label']} ({s[0]})" if s else lv["label"]


def describe(m: Dict[str, Any], levels: Sequence[dict]) -> str:
    """The sentence the answer must carry for one mapping."""
    got = m.get("levels") or []
    if not got:
        names = ", ".join(lv["label"] for lv in levels or []) or "none indexed"
        return (f"{m['said']}: this set has no level by that name "
                f"(its levels: {names})")
    if len(got) > 1:
        return (f"{m['said']} = " + " or ".join(_name(lv) for lv in got)
                + " on this set - it could be either; cover both")
    return f"{m['said']} = {_name(got[0])} on this set"


def strip_phrases(text: str, *, field_is_a_level: bool = False) -> str:
    """`text` with its level phrases taken out - the words the drawings
    print are searched; "5th floor" is not one of them."""
    t = str(text or "")
    if field_is_a_level and (_BARE.match(t) or _ROOF_FIELD.match(t)):
        return ""
    for p in sorted(find_phrases(t), key=lambda p: -p["span"][0]):
        a, b = p["span"]
        t = t[:a] + " " + t[b:]
    t = re.sub(r"\s+", " ", t).strip(" ,;:-")
    t = re.sub(r"^(?:(?:on|at|in|of|for|the)\s+)+|(?:\s+(?:on|at|in|of|for|the))+$", "",
               t, flags=re.I)
    return t.strip()


def asks_about_ceiling(text: str) -> bool:
    return bool(_CEILING.search(str(text or "")))


def without_ceiling(text: str) -> str:
    """The subject with its ceiling words out: the roof assembly prints the
    insulation, the deck, the board - not the word ceiling."""
    t = re.sub(r"\s+", " ", _CEILING.sub(" ", str(text or ""))).strip(" ,;:-")
    return t


_ROOF_ASSEMBLY = re.compile(r"\broof", re.I)
_DETAILS = re.compile(r"\b(?:details?|sections?|assembl(?:y|ies)|wall\s+sections?)\b", re.I)


def roof_assembly_sheets(rows: Iterable[dict]) -> List[Dict[str, Any]]:
    """The sheets that draw the roof ASSEMBLY - roof sections and details.

    The ceiling of the top occupied level is the underside of that assembly,
    so a question about it is answered there as much as on the floor plan."""
    found: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("sheet_title") or "")
        if not (_ROOF_ASSEMBLY.search(title) and _DETAILS.search(title)):
            continue
        number = str(row.get("sheet_number") or "").strip()
        slot = found.setdefault(number, {"sheet_number": number, "title": title,
                                         "page_ids": []})
        if row.get("_id") is not None and str(row["_id"]) not in slot["page_ids"]:
            slot["page_ids"].append(str(row["_id"]))
    return [found[k] for k in sorted(found, key=_sheet_rank)]
