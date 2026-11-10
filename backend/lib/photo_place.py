"""Where a daily-log photo was taken, and how far the records can say so.

A photo has no GPS and no per-photo tag. What it has is the crew row it was
filed under, which is often "floors 1-4", and whatever the vision read could
legibly make out in it. Nobody is asked to identify a photo. A person MAY answer
once when asked, and that answer is the strongest evidence there is.

`infer` returns {level, space, room_type, certainty, candidates, evidence[]}.
THE OWNER'S RULE: never a specific location without sufficient evidence. So:

    confirmed    a person said so (photo_place_confirmations)
    inferred     the log row names exactly one level or unit; or legible text
                 matches a REAL tag from this job's plans; or a legible floor
                 marking agrees with the levels the row names
    lent         reserved: a confirmed same-place photo lending its place.
                 Disabled until a benchmark on real photos sets LEND_MIN_INLIERS.
                 It only ever fills a place nothing else assigned: a lent place
                 below the threshold (a geometry miss) changes nothing at all
    constrained  the row names several levels ("floors 1-4"): those are the
                 candidates and none is chosen
    suggested    something points at a level and nothing corroborates it: a
                 floor marking on a row that names no level, or a level named
                 only in the work description. A hint for a person, not a place
    conflict     the evidence disagrees: nothing is assigned
    unknown      nothing to go on

Only `confirmed`, `inferred` and `lent` assign anything (`is_sufficient`).

MATCHING IS EXACT. A visible text matches a plan tag only when the whole item,
less a word like APT or UNIT, IS the tag; a floor marking only when the whole
item is one ("FLOOR 3", "3RD FL", "ROOF"). "5TH FLOOR EXIT THIS WAY" is a sign
about somewhere else and "L3" is a lintel mark, and bare numbers are nothing.

A plan tag's level comes only from a sheet titled for ONE level. "TYPICAL FLOOR
PLAN" and "SECOND THROUGH FIFTH FLOOR PLAN" say nothing about any one level, and
4A is never assumed to be on the fourth floor just because it is called 4A. A
tag that ALSO appears on such a sheet ("STAIR 1" on the cellar plan and the
typical plan) is on levels nobody listed, so it pins no level at all.

Room type is carried but never assigns a place: every floor has a bathroom.

Pure: no database, no network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import work_state as W
from lib.plans import level_suggestion as LS

CONFIRMED, INFERRED, LENT = "confirmed", "inferred", "lent"
CONSTRAINED, SUGGESTED, CONFLICT, UNKNOWN = "constrained", "suggested", "conflict", "unknown"
SUFFICIENT = (CONFIRMED, INFERRED, LENT)

#: The inlier count (lib/photo_geometry) a same-place match must reach before a
#: confirmed photo may lend its place. None: disabled, and it stays None until
#: scripts/photo_relation_benchmark.py has been run on labeled real photos.
LEND_MIN_INLIERS: Optional[int] = None

_ORDINAL = "|".join(LS._ORDINAL_WORDS)
_FLOOR_MARK = re.compile(
    r"(?:floor|level|lvl)\s*[-#:.]?\s*(?P<a>\d{1,2})"
    r"|(?:flr|fl)\.?\s+(?P<b>\d{1,2})"
    r"|(?P<c>\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:floor|flr|fl)\.?"
    rf"|(?P<w>{_ORDINAL})\s+(?:floor|flr|fl)\.?", re.I)
_NAMED_MARK: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"sub[\s-]?(?:cellar|basement)", re.I), LS.SUB_CELLAR),
    (re.compile(r"cellar|basement", re.I), LS.CELLAR),
    (re.compile(r"ground\s+(?:floor|level)", re.I), LS.GROUND),
    (re.compile(r"mezz(?:anine)?", re.I), LS.MEZZANINE),
    (re.compile(r"roof", re.I), LS.ROOF),
    (re.compile(r"bulkhead", re.I), LS.BULKHEAD),
)
_TAG_PREFIX = re.compile(r"^(?:(?:APT|APARTMENT|UNIT|SUITE|STE|ROOM|RM|DOOR|NO)\s+)+")
_NOT_A_TAG = frozenset({"PUBLIC", "UNNAMED"})
_UNIT_WORD = re.compile(r"(?<![A-Za-z0-9])\d{1,2}[A-Za-z](?![A-Za-z0-9])")
_MANY_LEVELS = re.compile(r"\b(?:typ(?:ical)?|thru|through|and|to)\b|&|/|\d\s*-\s*\d", re.I)
_PLAN_WORD = re.compile(r"\bplans?\b", re.I)
_NAMED_TAG_MIN = 4


def tag_key(text: Any) -> str:
    """A tag's comparison form: upper case, no punctuation, no leading APT/UNIT.
    "Apt. 4-A" and "4A" are one key."""
    key = " ".join(re.sub(r"[^A-Z0-9 ]", " ", str(text or "").upper()).split())
    key = _TAG_PREFIX.sub("", key)
    return key.replace(" ", "") if re.fullmatch(r"\d{1,3} [A-Z]{1,2}", key) else key


def _usable_tag(key: str) -> bool:
    """A single letter or a two-digit number is on every photo of a job."""
    return len(key) >= 2 and key not in _NOT_A_TAG and not (key.isdigit() and len(key) < 3)


def _sheet_level(title: Any) -> List[str]:
    """The one level a plan sheet is titled for, or []."""
    t = str(title or "")
    if not _PLAN_WORD.search(t) or _MANY_LEVELS.search(t):
        return []
    tokens = LS.tokens_in(t)[0]
    return tokens if len(tokens) == 1 else []


def spaces_from_plan_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{tag key: {tag, levels, sheets}} from plan_records / plan_areas rows.
    "non-unit:BIKE ROOM" is the tag BIKE ROOM; "sheet:A-101" is a refusal, not a
    place. A sheet that does not name one level adds no level."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows or ():
        raw = str(r.get("unit") or "").strip()
        if not raw or raw.lower().startswith("sheet:"):
            continue
        if raw.lower().startswith("non-unit:"):
            raw = raw.split(":", 1)[1].strip()
        key = tag_key(raw)
        if not _usable_tag(key):
            continue
        slot = out.setdefault(key, {"tag": raw, "levels": [], "sheets": [], "open": False})
        one = _sheet_level(r.get("sheet_title"))
        slot["levels"] = sorted(set(slot["levels"]) | set(one))
        # Also on a sheet that names no ONE level ("TYPICAL FLOOR PLAN 2-6"):
        # the tag's levels are not all known, so it can never pin one.
        slot["open"] = slot["open"] or not one
        sheet = str(r.get("sheet_number") or "")
        if sheet and sheet not in slot["sheets"] and len(slot["sheets"]) < 8:
            slot["sheets"].append(sheet)
    return out


def _floor_mark(text: Any) -> Optional[str]:
    """The level a piece of legible text IS, or None. The whole text."""
    t = " ".join(str(text or "").split())
    m = _FLOOR_MARK.fullmatch(t)
    if m:
        word = m.group("w")
        n = LS._ORDINAL_WORDS[word.lower()] if word else int(m.group("a") or m.group("b") or m.group("c"))
        return f"{LS.FLOOR_PREFIX}{n}" if 1 <= n <= LS.MAX_SUGGESTED_STORIES else None
    for rx, token in _NAMED_MARK:
        if rx.fullmatch(t):
            return token
    return None


def _visible(photo: Dict[str, Any]) -> List[str]:
    v = photo.get("visible_text")
    return [str(x) for x in v if str(x).strip()] if isinstance(v, list) else []


def _room(photo: Dict[str, Any]) -> Optional[str]:
    room = str(photo.get("room_type") or "").strip().lower()
    return room if room and room != "unknown" else None


def _row_space(row: Dict[str, Any], where: str, spaces: Dict[str, Dict[str, Any]],
               evidence: List[Dict[str, Any]]) -> Optional[str]:
    """The one unit or named space the crew row names, as a tag key."""
    named = {tag_key(u) for u in _UNIT_WORD.findall(where)}
    if len(named) > 1:
        evidence.append({"source": "log_row", "text": where, "used": False,
                         "says": f"the log row names several units ({', '.join(sorted(named))})"})
        return None
    if row["space"]:
        return tag_key(row["space"])
    rooms = [k for k in spaces if len(k) >= _NAMED_TAG_MIN and not k[0].isdigit()
             and re.search(rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])", where.upper())]
    return rooms[0] if len(rooms) == 1 else None


def _answers(confirmations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each person's latest answer: a person may correct himself. Append-only."""
    latest: Dict[str, Dict[str, Any]] = {}
    for c in sorted(confirmations or (), key=lambda c: str(c.get("at") or "")):
        latest[str(c.get("by_user_id") or c.get("by_name") or "?")] = c
    return list(latest.values())


def _result(level: Optional[str], space: Optional[str], room: Optional[str], certainty: str,
            candidates: Iterable[str], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"level": level, "space": space, "room_type": room, "certainty": certainty,
            "candidates": sorted(set(candidates)), "evidence": evidence}


def infer(photo: Dict[str, Any], project_spaces: Optional[Dict[str, Dict[str, Any]]] = None, *,
          confirmations: Sequence[Dict[str, Any]] = (),
          lent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """See the module docstring. Total: a photo with nothing is `unknown`."""
    spaces = project_spaces or {}
    room = _room(photo)
    answers = _answers(confirmations)
    if answers:
        given = {(str(c.get("level") or ""), c.get("space") or None) for c in answers}
        evidence = [{"source": "confirmation", "used": len(given) == 1, "level": c.get("level"), "space": c.get("space"),
                     "by": c.get("by_name") or c.get("by_user_id"), "at": c.get("at"),
                     "says": f"confirmed by {c.get('by_name') or 'a person'}"} for c in answers]
        if len(given) > 1:
            return _result(None, None, room, CONFLICT, [lv for lv, _ in given if lv], evidence)
        level, space = next(iter(given))
        return _result(level or None, space, room, CONFIRMED, [level] if level else [], evidence)

    evidence: List[Dict[str, Any]] = []
    where = str(photo.get("where") or "")
    row = W.places_in(where)
    row_levels = list(row["levels"])
    row_space = _row_space(row, where, spaces, evidence)
    pins: List[str] = []                # levels something names outright
    mentioned = set(row_levels)
    conflict = False

    if len(row_levels) == 1:
        pins.append(row_levels[0])
        evidence.append({"source": "log_row", "text": where, "used": True, "level": row_levels[0],
                         "says": f"the log row names {W.level_label(row_levels[0])}"})
    elif row_levels:
        evidence.append({"source": "log_row", "text": where, "used": False, "levels": row_levels,
                         "says": f"the log row names several levels ({where})"})
    elif row_space is None:
        work_levels = W.places_in(photo.get("work"))["levels"]
        if work_levels:
            mentioned |= set(work_levels)
            evidence.append({"source": "log_work", "text": str(photo.get("work") or ""), "used": False, "levels": work_levels,
                             "says": "the work description mentions a level, which is not where the photo is filed"})

    # Row plus photo: every plan tag it names and every one legible in the picture.
    read = [tag_key(t) for t in _visible(photo)]
    tags = list(dict.fromkeys(k for k in read if k in spaces and _usable_tag(k)))
    if row_space and any(k != row_space for k in tags):
        conflict = True
        evidence.append({"source": "plan_tag", "text": ", ".join(tags), "used": False,
                         "says": f"a tag read in the photo disagrees with the log row's {row_space}"})
    for key in dict.fromkeys(([row_space] if row_space in spaces else []) + tags):
        levels = spaces[key]["levels"]
        is_open = bool(spaces[key].get("open"))
        mentioned |= set(levels)
        if row_levels and levels and not is_open and not set(levels) & set(row_levels):
            conflict = True
        if len(levels) == 1 and not is_open:
            pins.append(levels[0])
        evidence.append({"source": "plan_tag", "text": key, "used": key in tags or key == row_space, "levels": levels,
                         "space": key,
                         "says": ("text read in the photo matches the plan tag " if key in tags else "the log row names the plan tag ")
                         + spaces[key]["tag"] + (f" ({', '.join(spaces[key]['sheets'][:2])})" if spaces[key]["sheets"] else "")})

    loose: List[str] = []
    for text in _visible(photo):
        mark = _floor_mark(text)
        if not mark:
            continue
        mentioned.add(mark)
        if row_levels:
            agrees = mark in row_levels
            conflict = conflict or not agrees
            if agrees:
                pins.append(mark)
            evidence.append({"source": "floor_marking", "text": text, "used": agrees, "level": mark,
                             "says": f"a floor marking read in the photo, \"{text}\", "
                                     + ("is one of the log row's levels" if agrees else "is not one of the log row's levels")})
        else:
            loose.append(mark)
            evidence.append({"source": "floor_marking", "text": text, "used": False, "level": mark,
                             "says": f"a floor marking read in the photo, \"{text}\", with no level on the log row to check it against"})

    pinned = set(pins)
    if len(pinned) > 1 or (pinned and any(m not in pinned for m in loose)) or (not pinned and len(set(loose)) > 1):
        conflict = True
    # A tag on several levels still has to allow the level the rest settled on.
    for key in ([row_space] if row_space in spaces else []) + tags:
        if len(pinned) == 1 and spaces[key]["levels"] and not spaces[key].get("open") \
                and not pinned & set(spaces[key]["levels"]):
            conflict = True
    if conflict:
        return _result(None, None, room, CONFLICT, mentioned, evidence)

    named = {k for k in ([row_space] if row_space else []) + tags}
    space = next(iter(named)) if len(named) == 1 else None
    level = next(iter(pinned)) if pinned else None
    if not level and space and spaces.get(space, {}).get("open") and spaces[space]["levels"]:
        # Named on a one-level sheet AND on a typical one: which level is not
        # known, and placing it on the one level that was listed would be a guess.
        evidence.append({"source": "plan_tag", "text": space, "used": False, "levels": spaces[space]["levels"],
                         "says": f"the plan tag {spaces[space]['tag']} is also on a sheet that names no one level"})
        return _result(None, None, room, SUGGESTED, mentioned, evidence)
    if level or space:
        return _result(level, space, room, INFERRED, [level] if level else row_levels, evidence)
    if lent and LEND_MIN_INLIERS is not None and int(lent.get("inliers") or 0) >= LEND_MIN_INLIERS \
            and lent.get("level") and (not row_levels or lent["level"] in row_levels):
        evidence.append({"source": "lent", "used": True, "level": lent["level"], "says": "lent by a confirmed photo of the same place"})
        return _result(lent["level"], lent.get("space"), room, LENT, [lent["level"]], evidence)
    if len(row_levels) > 1:
        return _result(None, None, room, CONSTRAINED, row_levels, evidence)
    return _result(None, None, room, SUGGESTED if mentioned else UNKNOWN, mentioned, evidence)


def level_token(text: Any) -> Optional[str]:
    """The one level a person named, or that exact token; None otherwise."""
    t = str(text or "").strip()
    if t in LS.LABELS or re.fullmatch(rf"{LS.FLOOR_PREFIX}\d{{1,2}}", t):
        return t
    return W.level_asked(t)


def is_sufficient(place: Optional[Dict[str, Any]]) -> bool:
    return bool(place) and place.get("certainty") in SUFFICIENT


def levels_of(place: Dict[str, Any]) -> List[str]:
    """What work_state files a photo under: the assigned level; or, with no
    assignment, the levels it is shared between. A suggestion or a single
    contradicted level is not a place, so it gives nothing."""
    if is_sufficient(place) and place.get("level"):
        return [place["level"]]
    return place["candidates"] if place["certainty"] != SUGGESTED and len(place["candidates"]) > 1 else []


def how(place: Optional[Dict[str, Any]]) -> str:
    """In a sentence, for the reader: how this place was arrived at."""
    if not place:
        return ""
    used = [e["says"] for e in place.get("evidence") or [] if e.get("used")]
    if is_sufficient(place) and used:
        return "; ".join(used)
    return {CONSTRAINED: "the log row names several levels and the photo does not settle which",
            SUGGESTED: "only a hint, nothing corroborates it",
            CONFLICT: "the evidence disagrees, so no place is assigned",
            UNKNOWN: "nothing on record says where this was taken"}.get(place.get("certainty"), "")


def wants_floor(row: Dict[str, Any], place: Dict[str, Any]) -> bool:
    """Whether a person holding this photo could usefully be asked for its
    floor: an inside photo with no level assigned. The front of a building has
    no floor to ask about."""
    return row.get("view") in ("interior", "basement") and not (is_sufficient(place) and place.get("level"))


def reread_targets(rows: Iterable[Dict[str, Any]], budget: int, max_tries: int) -> List[Dict[str, Any]]:
    """The index rows worth a second vision read for legible place text, newest
    first, at most `budget`: rows filed under several levels or none. A row
    naming exactly one level already has its place, and reading it again could
    only contradict it."""
    out: List[Dict[str, Any]] = []
    for r in sorted(rows or (), key=lambda x: str(x.get("date") or ""), reverse=True):
        if len(out) >= max(0, budget):
            break
        if int(r.get("reread_tries") or 0) < max_tries and len(W.places_in(r.get("where"))["levels"]) != 1:
            out.append(r)
    return out
