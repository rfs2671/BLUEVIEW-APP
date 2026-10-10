"""THE EXECUTIVE SUMMARY, ASSEMBLED FROM FILED CONTENT AND NOTHING ELSE.

Ruled 2026-10-10, with the wording approved against 588 Thomas on 2026-10-05:

    Framing on the 3rd–4th floors, Plumbing on the 1st–4th, HVAC / Mechanical
    on the 1st–2nd.

    Arkon Builders (13) worked on framing (layout, track and studs) on the 3rd
    and 4th floors. ... The toolbox talk at 8:00 AM had 22 attendees. The
    daily site inspection passed on every item, and the superintendent
    reported no incidents, unsafe conditions or DOB actions.

NO GENERATED TEXT. Every clause is a template over one filed field, and a
field that was not filed contributes no clause -- the summary gets shorter, it
never gets vaguer. The connective words ("worked on", "had", "passed on")
are the template's; every noun, number, time and description is the record's.

WHAT THE TEMPLATES MAY NOT SAY, carried over from the fallback they replace:
that no incidents occurred when the superintendent's log is not filed, and
that a company had workers on site when only a description exists. A count
prints only where the daily log recorded one.

PURE, like the model: it is handed the resolved model and the three filed
documents' `data`, and reads no database and no clock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import location_vocabulary as lv
from . import model as m


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _listed(items: Sequence[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ══════════════════════════════════════════════════════════════════════════
#  WHERE, IN WORDS
# ══════════════════════════════════════════════════════════════════════════

#: The non-storey tokens as a sentence names them. `SITE` is not here: a
#: sitewide row is "throughout the site", which takes no "on the".
_AREA_WORDS: Dict[str, str] = {
    "ROOF": "roof", "MEZZ": "mezzanine", "G": "ground floor",
    "CELLAR": "cellar", "SUBCELLAR": "sub-cellar", "B": "basement",
    "UG": "underground", "FDN": "foundation", "EX": "EX", "SW": "sidewalk",
}


def _runs(levels: Sequence[int]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for n in sorted(set(levels)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def floors_phrase(levels: Sequence[int], *, compact: bool,
                  noun: bool = True) -> str:
    """"3rd and 4th floors", "1st through 4th floors" -- or, compact,
    "3rd–4th floors". `noun=False` drops "floor(s)" for a headline clause
    that follows one which already said it."""
    if not levels:
        return ""
    runs = _runs(levels)
    pieces: List[str] = []
    for lo, hi in runs:
        if lo == hi:
            pieces.append(lv.ordinal(lo))
        elif compact:
            pieces.append(f"{lv.ordinal(lo)}–{lv.ordinal(hi)}")
        elif hi == lo + 1:
            pieces.append(f"{lv.ordinal(lo)} and {lv.ordinal(hi)}")
        else:
            pieces.append(f"{lv.ordinal(lo)} through {lv.ordinal(hi)}")
    text = _listed(pieces) if len(pieces) > 1 else pieces[0]
    if not noun:
        return text
    return text + (" floor" if len(set(levels)) == 1 else " floors")


def where_phrase(resolution: "lv.Resolution", *, compact: bool,
                 noun: bool = True) -> str:
    """"on the 3rd and 4th floors", "on the 1st floor and roof",
    "throughout the site", or "" when nothing readable was recorded."""
    levels = [lv.level_number(t) for t in resolution.areas]
    levels = [n for n in levels if n is not None]
    others = [_AREA_WORDS[t] for t in resolution.areas
              if lv.level_number(t) is None and t in _AREA_WORDS]
    parts = ([floors_phrase(levels, compact=compact, noun=noun)]
             if levels else []) + others
    if parts:
        return "on the " + _listed(parts)
    if resolution.sitewide:
        return "throughout the site"
    return ""


# ══════════════════════════════════════════════════════════════════════════
#  THE HEADLINE
# ══════════════════════════════════════════════════════════════════════════

def headline(model: "m.ReportDisplayModel") -> str:
    """One clause per crew: its trade (or, with none recorded, its company),
    and where it worked. In log order.

    "floors" IS SAID ONCE. "Framing on the 3rd–4th floors, Plumbing on the
    1st–4th" -- the approved wording -- and a later clause says it again only
    when the one before it did not.
    """
    clauses: List[str] = []
    said_floors = False
    for a in model.activities:
        what = m.proper_case(a.trade) if a.trade else a.company_display
        levels = [lv.level_number(t) for t in a.location.areas]
        has_levels = any(n is not None for n in levels)
        where = where_phrase(a.location, compact=True,
                             noun=not (said_floors and has_levels))
        said_floors = said_floors or has_levels
        clauses.append(f"{what} {where}".strip())
    if not clauses:
        return "No activity documented"
    return ", ".join(clauses) + "."


# ══════════════════════════════════════════════════════════════════════════
#  THE BODY
# ══════════════════════════════════════════════════════════════════════════

def _lead_lower(text: str) -> str:
    """"framing (layout...)" for "Framing (layout...)"; "MEP rough-in" kept.

    Only a capitalised ordinary word is lowered -- the description continues a
    sentence the template began. An acronym or a mixed-case name is the
    record's spelling."""
    first = text.split(" ", 1)[0]
    if len(first) > 1 and first[0].isupper() and first[1:].islower():
        return text[0].lower() + text[1:]
    return text


def crew_sentence(a: "m.ActivityDisplayState") -> str:
    count = f" ({a.log_count})" if a.log_count is not None else ""
    head = f"{a.company_display}{count}"
    where = where_phrase(a.location, compact=False)
    if a.description:
        return " ".join(x for x in (f"{head} worked on",
                                    _lead_lower(a.description), where) if x) + "."
    if where:
        return f"{head} worked {where}."
    return f"{head} is on the daily log."


def _clock(value) -> str:
    """"8:00 AM" for "08:00 AM". Nothing else about the string changes."""
    text = _clean(value)
    return text[1:] if len(text) > 1 and text[0] == "0" and text[1].isdigit() \
        else text


def toolbox_sentence(toolbox: Optional[dict]) -> str:
    if not isinstance(toolbox, dict):
        return ""
    attendees = [x for x in (toolbox.get("attendees") or [])
                 if isinstance(x, dict)]
    when = _clock(toolbox.get("meeting_time"))
    if not attendees:
        return ""
    n = len(attendees)
    noun = "attendee" if n == 1 else "attendees"
    at = f" at {when}" if when else ""
    return f"The toolbox talk{at} had {n} {noun}."


#: The daily log's free "Other" inspection carries a note, not a pass or a
#: fail; server.py's renderer skips it on the same rule (OTHER_INSPECTION_KEY).
_OTHER_INSPECTION = "other_checklist"


def inspection_clause(checklist: Optional[dict]) -> str:
    results = []
    for key, value in (checklist or {}).items():
        if not isinstance(value, dict):
            continue
        result = _clean(value.get("result")).lower()
        if key == _OTHER_INSPECTION and not result:
            continue
        results.append(result)
    if not results:
        return ""
    failed = results.count("fail")
    passed = results.count("pass")
    if failed:
        word = "item" if failed == 1 else "items"
        return f"the daily site inspection recorded {failed} failed {word}"
    if passed == len(results):
        return "the daily site inspection passed on every item"
    return f"the daily site inspection passed on {passed} of {len(results)} items"


#: The three superintendent sections the approved sentence names, in its order.
_SUPER_SECTIONS: Tuple[Tuple[str, str], ...] = (
    ("incidents", "incidents"),
    ("unsafe_conditions", "unsafe conditions"),
    ("dob_actions", "DOB actions"),
)


def superintendent_clause(superintendent: Optional[dict]) -> str:
    """Only from a FILED superintendent's log, and only the sections it
    answered. "none to report" is his statement; a section he did not answer
    contributes nothing, because silence is not a report of none."""
    if not isinstance(superintendent, dict):
        return ""
    none, some = [], []
    for key, label in _SUPER_SECTIONS:
        sec = superintendent.get(key)
        if not isinstance(sec, dict) or not sec:
            continue
        (none if sec.get("none_to_report") else some).append(label)
    bits = []
    if none:
        bits.append("reported no " + _listed_or(none))
    if some:
        bits.append("recorded " + _listed(some))
    if not bits:
        return ""
    return "the superintendent " + " and ".join(bits)


def _listed_or(items: Sequence[str]) -> str:
    if len(items) <= 2:
        return " or ".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def body(model: "m.ReportDisplayModel", *, toolbox: Optional[dict] = None,
         checklist: Optional[dict] = None,
         superintendent: Optional[dict] = None) -> Optional[str]:
    """The paragraph, or None when the log describes no crew -- the caller
    then prints the counts-only fallback it always did."""
    if not model.activities:
        return None
    sentences = [crew_sentence(a) for a in model.activities]
    tb = toolbox_sentence(toolbox)
    if tb:
        sentences.append(tb)
    closing = [c for c in (inspection_clause(checklist),
                           superintendent_clause(superintendent)) if c]
    if closing:
        joined = ", and ".join(closing)
        sentences.append(joined[0].upper() + joined[1:] + ".")
    return " ".join(sentences)
