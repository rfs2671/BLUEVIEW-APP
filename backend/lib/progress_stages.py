"""THE PROGRESS BOARD: how far each kind of work has got, floor by floor, read
from the filed daily logs -- with an ESTIMATED percent per kind of work.

Operator ruling, 2026-11-18: the report's progress is built automatically from
the daily logs and their photographs, shown as a trade-by-floor stage board
with an estimated percent per trade, labelled as estimated from site records.
Nothing here is measured on site; every stage is traceable to log lines.

THE KINDS OF WORK. One log line can name several ("Ceiling drops, interior
framing, sheet rack" -- framing AND drywall by one company), so each phrase of
a line is classified on its own words first, then by the trade the daily log
recorded for the work (`work_trades`), then by the crew's own trade. A crew
that installs nothing (cleaning, hauling, security) is never progress.

THE STAGE OF ONE KIND OF WORK ON ONE FLOOR, at the end of the period:
  appears complete  the log says the work there is complete / done / finished;
                    OR the next trade in the building sequence worked on that
                    floor after this one's last day there, and this one has
                    not been back for a week (framing is followed by sheetrock,
                    sheetrock by taping, MEP rough-in is closed in by drywall)
  in progress       worked on that floor in the last 7 days of the period
  started           worked there before, neither of the above
  not started       no log line places this work on that floor

THE ESTIMATE. Per kind of work: the floors where it appears complete count
fully and the floors where it is in progress or started count half, over every
floor any filed log has named. Rounded to the nearest 5. No estimate for work
the logs never place on a floor (a facade, the roof). It is an estimate from
the records, printed as one and never mixed with a schedule file's figures.

Pure: no database, no network, no model.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

NONE, STARTED, ACTIVE, DONE = "none", "started", "active", "done"
STAGE_LABEL = {NONE: "Not started", STARTED: "Started", ACTIVE: "In progress", DONE: "Appears complete"}
STAGE_WEIGHT = {NONE: 0.0, STARTED: 0.5, ACTIVE: 0.5, DONE: 1.0}
#: "In progress" = worked on that floor within this many days of the end.
RECENT_DAYS = 7
#: A trade followed by the next one is complete only after this long away,
#: and only when the next one has worked there on at least FOLLOW_DAYS days
#: since (one day of sheetrock does not close in a floor's ductwork).
AWAY_DAYS = 7
FOLLOW_DAYS = 3
HISTORY_POINTS = 12

FLOOR_RE = re.compile(r"\b(?:fl(?:oor)?s?\.?\s*#?(\d{1,2})(?:\s*(?:-|–|to|&|and)\s*(\d{1,2}))?"
                      r"|(\d{1,2})(?:st|nd|rd|th)\s+fl(?:oor)?)\b", re.IGNORECASE)


_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "ground": 1}
_SINGLE_FLOOR = re.compile(r"\b(\d{1,2})\s+fl(?:oor)?\b(?!s)|\b(" + "|".join(_ORDINAL)
                           + r")\s+(?:fl(?:oor)?|level)\b", re.IGNORECASE)


def floors_of_text(text: Any) -> List[int]:
    """"floors 1-4" -> [1, 2, 3, 4]; "3rd floor" -> [3]; "1 floor", "first
    floor" and "ground floor" -> [1]; "4 floors" (a count) and "Outer bldg"
    -> []."""
    out: List[int] = []
    for m in _SINGLE_FLOOR.finditer(str(text or "")):
        out.append(int(m.group(1)) if m.group(1) else _ORDINAL[m.group(2).lower()])
    for m in FLOOR_RE.finditer(str(text or "")):
        a = m.group(1) or m.group(3)
        b = m.group(2)
        if a:
            lo = int(a)
            hi = int(b) if b else lo
            out.extend(range(min(lo, hi), max(lo, hi) + 1))
    return sorted(set(n for n in out if 0 < n < 100))


def floor_runs(floors: Iterable[int]) -> List[str]:
    """[1, 2, 3, 7, 9, 10] -> ["1–3", "7", "9–10"]: each run of consecutive
    floors once. A tower's "floors 26, 27, 28, 29, 34, 35 and 36" is
    "floors 26–29 and 34–36"."""
    fs = sorted(set(floors))
    runs: List[List[int]] = []
    for f in fs:
        if runs and f == runs[-1][1] + 1:
            runs[-1][1] = f
        else:
            runs.append([f, f])
    out = []
    for a, b in runs:
        out.append(str(a) if a == b else f"{a}–{b}")
    return out


def floors_words(floors: Iterable[int]) -> str:
    fs = sorted(set(floors))
    if not fs:
        return ""
    if len(fs) == 1:
        return f"floor {fs[0]}"
    runs = floor_runs(fs)
    if len(runs) == 1:
        return f"floors {runs[0]}"
    return "floors " + ", ".join(runs[:-1]) + f" and {runs[-1]}"


# ── THE KINDS OF WORK ────────────────────────────────────────────────────────

def _rx(*words: str) -> "re.Pattern[str]":
    return re.compile("|".join(words), re.IGNORECASE)


#: (key, label, STRONG words, WEAK words). Strong words name the work wherever
#: they appear; a weak word ("blocking", "fixture") names it only when the
#: crew's own trade says nothing (a window crew's "blocking" is window work).
FAMILIES: Tuple[Tuple[str, str, Optional["re.Pattern[str]"], Optional["re.Pattern[str]"]], ...] = (
    ("demolition", "Demolition", _rx(r"\bdemo(?:lition)?\b", r"\babatement"), None),
    ("excavation", "Excavation & foundations", _rx(r"\bexcavat", r"\bunderpin", r"\bshoring", r"\bbackfill",
                                                   r"\bfoundation", r"\bfooting"), None),
    ("concrete", "Concrete", _rx(r"\bconcrete", r"\bslab\b", r"\brebar", r"\bformwork", r"\bpour(?:ed|ing)?\b"), None),
    ("steel", "Steel & stairs", _rx(r"\bstructural steel", r"\bsteel\b", r"\bstairs?\b", r"\bstair ?case",
                                    r"\brailings?\b", r"\bwelding"), _rx(r"\biron\b")),
    ("framing", "Framing", _rx(r"\bfram(?:e|es|ed|ing|ers?)\b", r"\bstuds?\b", r"\bceiling drops?\b",
                               r"\bdrop ceiling", r"\bsoffits?\b", r"\bbulkheads?\b", r"\bfurring",
                               r"\bdoor bucks?\b", r"\bcfs\b", r"\bjoists?\b"),
     _rx(r"\bblocking\b", r"\btracks?\b", r"\bheaders?\b", r"\bsheathing\b", r"\bpartitions?\b",
         r"\bcarpent")),
    ("electrical", "Electrical", _rx(r"\belectric", r"\bwir(?:e|es|ing)\b", r"\bconduit", r"\bpull(?:ing)? wire",
                                     r"\blight(?:ing)?\b", r"\breceptacles?\b", r"\boutlets?\b", r"\bfeeders?\b",
                                     r"\bswitchgear\b"),
     _rx(r"\bpanels?\b", r"\bdevices?\b", r"\bswitch(?:es)?\b")),
    ("plumbing", "Plumbing", _rx(r"\bplumb", r"\bpip(?:e|es|ing)\b", r"\bsanitary", r"\bdomestic water",
                                 r"\bwater main", r"\bgas (?:line|pipe)", r"\bboiler", r"\bwater heater",
                                 r"\btoilets?\b", r"\bsinks?\b"),
     _rx(r"\bfixtures?\b", r"\brisers?\b", r"\bwaste\b", r"\bvents?\b", r"\bdrains?\b")),
    ("low_voltage", "Low voltage", _rx(r"\blow ?voltage", r"\bdata\b", r"\btelecom", r"\bcable pull",
                                       r"\bintercom", r"\bfire alarm", r"\bcctv\b", r"\bcameras?\b"),
     _rx(r"\bcables?\b")),
    ("hvac", "HVAC / ductwork", _rx(r"\bhvac\b", r"\bduct", r"\bvrf\b", r"\bcondensers?\b", r"\bmini ?splits?\b",
                                    r"\brooftop units?\b", r"\brtus?\b", r"\bexhaust fans?\b", r"\bair handl"),
     _rx(r"\bmechanical\b", r"\bmep\b")),
    ("sprinkler", "Sprinklers", _rx(r"\bsprinkler", r"\bfire suppression", r"\bstandpipe"), None),
    ("insulation", "Insulation", _rx(r"\binsulat", r"\bspray ?foam", r"\bbatts?\b", r"\bfire ?stop",
                                     r"\bfireproof"), _rx(r"\bvapou?r barrier")),
    ("drywall", "Drywall / sheetrock", _rx(r"\bdry ?wall", r"\bsheet ?r(?:o|a)ck", r"\bgypsum", r"\bgyp\b",
                                          r"\bhang(?:ing)? (?:board|rock|sheet)", r"\bshaft ?wall",
                                          r"\bceiling board"), _rx(r"\bboards?\b")),
    ("taping", "Taping & compound", _rx(r"\btap(?:e|es|ed|ing|ers?)\b", r"\bspackl", r"\bcompound\b",
                                        r"\bskim(?: coat)?\b", r"\bmud(?:ding)?\b", r"\bcorner bead"),
     _rx(r"\bsand(?:ing)?\b", r"\bpatch(?:ing)?\b")),
    ("painting", "Painting", _rx(r"\bpaint", r"\bprim(?:e|er|ing)\b", r"\bstain(?:ing)?\b"), None),
    ("flooring", "Flooring & tile", _rx(r"\bflooring\b", r"\btil(?:e|es|ing)\b", r"\bunderlayment",
                                        r"\bwaterproof", r"\blvt\b", r"\bvinyl", r"\bhardwood", r"\bcarpet",
                                        r"\bgrout", r"\bthin ?set", r"\bself.?level"), None),
    ("windows", "Windows", _rx(r"\bwindows?\b", r"\bglaz", r"\bcurtain ?wall", r"\bstorefront"), None),
    ("facade", "Exterior walls & facade", _rx(r"\bstucco", r"\bfa[cç]ade", r"\beifs\b", r"\bbrick",
                                              r"\bmasonry", r"\bmason\b", r"\bcmu\b", r"\bsiding", r"\bcladding"),
     _rx(r"\bblock\b")),
    ("roofing", "Roofing", _rx(r"\broofing\b", r"\broofers?\b", r"\bmembrane", r"\bflashing", r"\bparapet",
                               r"\bcoping"), None),
)
LABEL = {k: lab for k, lab, _s, _w in FAMILIES}
ORDER = {k: n for n, (k, *_rest) in enumerate(FAMILIES)}

#: Work that is not built floor by floor: its stage is shown for the building,
#: never as a share of the floors (a foundation is not "25%" of a 4-storey job
#: because it sits under floor 1).
BUILDING_WIDE = ("demolition", "excavation", "concrete", "roofing")

#: MEP work has a rough-in and, after the walls are painted, a finish: two
#: rows, because a plumber back for fixtures is not plumbing going backwards.
FINISH_CAPABLE = ("plumbing", "electrical", "low_voltage", "hvac", "sprinkler")
_FINISH_WORDS = _rx(r"\btrim(?:ming)?(?: out)?\b", r"\bfixtures?\b", r"\bfinish(?:es|ing)?\b",
                    r"\bdevices?\b", r"\bcover ?plates?\b", r"\bset (?:fixtures|toilets|sinks|vanit)",
                    r"\bdiffusers?\b", r"\bgrilles?\b", r"\bregisters?\b", r"\bsprinkler heads?\b",
                    r"\btop ?out\b")
for _k in FINISH_CAPABLE:
    LABEL[f"{_k}_finish"] = f"{LABEL[_k]} finish"
    LABEL[_k] = f"{LABEL[_k]} rough-in"
    ORDER[f"{_k}_finish"] = ORDER["painting"] + 0.5 + ORDER[_k] / 100.0

#: The next work on a floor that closes this work in or covers it.
_CLOSES = ("drywall", "taping", "painting")
#: The structure is behind everything from framing on.
_INTERIOR = ("framing", "plumbing", "electrical", "low_voltage", "hvac", "sprinkler", "insulation") + _CLOSES + ("flooring",)
SUCCESSORS: Dict[str, Tuple[str, ...]] = {
    "framing": _CLOSES + ("flooring",), "plumbing": _CLOSES, "electrical": _CLOSES, "low_voltage": _CLOSES,
    "hvac": _CLOSES, "sprinkler": _CLOSES, "insulation": _CLOSES, "drywall": ("taping", "painting"),
    "taping": ("painting",), "steel": _CLOSES + ("flooring",),
    "demolition": ("excavation", "concrete") + _INTERIOR, "excavation": ("concrete",) + _INTERIOR,
    "concrete": ("steel",) + _INTERIOR,
}
#: "All areas", "entire building": every floor the logs have named.
_ALL_FLOORS = _rx(r"\ball (?:areas|floors|levels)\b", r"\bentire (?:building|bldg)\b",
                  r"\bwhole (?:building|bldg)\b", r"\bthroughout\b")

#: Crews that install nothing: a cleaning crew's "stucco" is clean-up.
_NON_INSTALL = _rx(r"clean", r"janitor", r"porter", r"security", r"guard", r"trucking", r"hauling",
                   r"rubbish", r"dumpster", r"carting", r"flagg", r"traffic", r"deliver", r"supervis",
                   r"inspector", r"engineer", r"survey", r"safety", r"scaffold", r"sidewalk shed",
                   r"exterminat", r"\bpest\b")
#: Phrases that are not progress whoever wrote them.
_NOT_WORK = _rx(r"\bclean(?:ing|ed|up)?\b", r"\bdebris\b", r"\bdeliver", r"\bunload", r"\bsafety\b",
                r"\bmeeting\b", r"\binspection\b", r"\bprotection\b", r"\bscaffold", r"\bhoist\b",
                r"\bmaterial(?:s)? (?:handling|staging)", r"\bno work\b")
_DONE = _rx(r"\b(?:complete[d]?|done|finished)\b")
_NOT_DONE = _rx(r"\b(?:not|almost|nearly|partially|partly|half)\s+(?:yet\s+)?(?:complete[d]?|done|finished)\b",
                r"\bto be (?:complete[d]?|done|finished)\b")
_SPLIT = re.compile(r"\s*(?:,|;|/|\s\+\s|\s&\s|\band\b|\bthen\b)\s*", re.IGNORECASE)


def _strong(text: str) -> Optional[str]:
    """The family whose STRONG words appear first in the text."""
    best: Tuple[int, int, str] = (10 ** 6, 0, "")
    for n, (k, _lab, strong, _weak) in enumerate(FAMILIES):
        m = strong.search(text) if strong else None
        if m and (m.start(), n) < best[:2]:
            best = (m.start(), n, k)
    return best[2] or None


def _weak(text: str) -> Optional[str]:
    for k, _lab, _strong_rx, weak in FAMILIES:
        if weak and weak.search(text):
            return k
    return None


def crew_family(trade: Any, company: Any = "") -> Optional[str]:
    """The kind of work a crew's trade (then its company name) says."""
    for t in (str(trade or ""), str(company or "")):
        k = _strong(t) or _weak(t)
        if k:
            return k
    return None


def _phrases(text: Any) -> List[str]:
    t = FLOOR_RE.sub(" ", str(text or ""))
    return [p for p in (" ".join(x.split()).strip(" .-") for x in _SPLIT.split(t)) if p]


def families_of(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    """[(family, phrase)] for one crew row of a daily log, in the order the
    line names them. [] for a crew that installs nothing."""
    crew_label = f"{row.get('trade') or ''} {row.get('company') or ''}"
    crew = crew_family(row.get("trade"), row.get("company"))
    if (_NON_INSTALL.search(crew_label) and crew is None) or _NON_INSTALL.search(str(row.get("trade") or "")):
        return []
    recorded = [k for k in (crew_family(t) for t in (row.get("work_trades") or [])) if k]
    out: List[Tuple[str, str]] = []
    phrases = _phrases(row.get("work")) or [""]
    for ph in phrases:
        if ph and _NOT_WORK.search(ph):
            continue
        fam = (_strong(ph) if ph else None) or (recorded[0] if recorded else None)
        if fam is None:
            weak = _weak(ph) if ph else None
            fam = crew or weak
        if fam is None:
            continue
        if fam in FINISH_CAPABLE and ph and _FINISH_WORDS.search(ph):
            fam = f"{fam}_finish"
        out.append((fam, ph))
    return out


def _done_word(phrase: str) -> bool:
    return bool(_DONE.search(phrase)) and not _NOT_DONE.search(phrase)


# ── THE BOARD ────────────────────────────────────────────────────────────────

def _base(fam: str) -> str:
    return fam[:-len("_finish")] if fam.endswith("_finish") else fam


def _stage(dates: List[date], done_dates: List[date], followed_days: int, end: date) -> str:
    """`followed_days`: distinct days the next trade worked there after this
    one's last day."""
    last = max(dates)
    if done_dates and max(done_dates) >= last:
        return DONE
    if (end - last).days < RECENT_DAYS:
        return ACTIVE
    if followed_days >= FOLLOW_DAYS and (end - last).days >= AWAY_DAYS:
        return DONE
    return STARTED


def _round5(x: float) -> int:
    return int(x / 5.0 + 0.5) * 5


def _board(rows: List[Dict[str, Any]], end: date, floors_fixed: Optional[List[int]] = None,
           plan_floors: Iterable[int] = ()) -> Dict[str, Any]:
    """`floors_fixed`: count the estimate over these floors (the history uses
    the floors known at the end of the period, so a floor first named later
    does not make the earlier weeks look further along)."""
    # (family, floor) -> dates worked, dates a "complete" was logged
    worked: Dict[Tuple[str, Any], List[date]] = defaultdict(list)
    done: Dict[Tuple[str, Any], List[date]] = defaultdict(list)
    places: Dict[str, Counter] = defaultdict(Counter)
    who: Dict[str, Counter] = defaultdict(Counter)
    photos: Dict[str, int] = defaultdict(int)
    floors_seen: set = set()
    kept: List[Tuple[Dict[str, Any], List[Tuple[str, str]], List[int]]] = []
    for r in rows:
        d = r.get("date")
        if not isinstance(d, date) or d > end:
            continue
        fams = families_of(r)
        if not fams:
            continue
        fl = list(r.get("floors") or floors_of_text(r.get("where")) or floors_of_text(r.get("work")))
        floors_seen.update(fl)
        kept.append((r, fams, fl))
    for r, fams, fl in kept:
        d = r["date"]
        if not fl and _ALL_FLOORS.search(f"{r.get('where') or ''} {r.get('work') or ''}"):
            fl = sorted(floors_seen)
        for fam in dict.fromkeys(f for f, _ph in fams):
            if r.get("company"):
                who[fam][r["company"]] += 1
            photos[fam] += len(r.get("photos") or [])
        for fam, ph in fams:
            spots = fl if fl and fam not in BUILDING_WIDE else ["elsewhere"]
            if spots == ["elsewhere"] and r.get("where"):
                places[fam][" ".join(str(r["where"]).split())[:40]] += 1
            for f in spots:
                worked[(fam, f)].append(d)
                if ph and _done_word(ph):
                    done[(fam, f)].append(d)
    logged = sorted(floors_seen)
    floors = sorted(floors_seen | set(plan_floors)) if floors_fixed is None else list(floors_fixed)
    trades: Dict[str, Dict[str, Any]] = {}
    for fam in sorted({f for f, _x in worked}, key=lambda f: (ORDER.get(f, 99), f)):
        cells: Dict[Any, Dict[str, Any]] = {}
        for f in floors:
            ds = worked.get((fam, f))
            if not ds:
                cells[f] = {"stage": NONE}
                continue
            last = max(ds)
            # a finish row has no next trade: only its own "complete" ends it
            followed = {x for s in SUCCESSORS.get(fam, ()) for x in worked.get((s, f), []) if x > last}
            cells[f] = {"stage": _stage(ds, done.get((fam, f), []), len(followed), end),
                        "first": min(ds), "last": last, "days": len(set(ds))}
        elsewhere = None
        if worked.get((fam, "elsewhere")):
            ds = worked[(fam, "elsewhere")]
            elsewhere = {"stage": _stage(ds, done.get((fam, "elsewhere"), []), 0, end),
                         "first": min(ds), "last": max(ds), "days": len(set(ds)),
                         "places": [p for p, _n in places[fam].most_common(2)]}
        on_floors = [c for c in cells.values() if c["stage"] != NONE]
        estimate = (_round5(100.0 * sum(STAGE_WEIGHT[c["stage"]] for c in cells.values()) / len(floors))
                    if floors and on_floors else None)
        trades[fam] = {"key": fam, "label": LABEL.get(fam, fam), "cells": cells, "elsewhere": elsewhere,
                       "estimate": estimate,
                       "counts": {"done": sum(1 for c in cells.values() if c["stage"] == DONE),
                                  "under_way": sum(1 for c in cells.values() if c["stage"] in (ACTIVE, STARTED)),
                                  "of": len(floors)},
                       # who did it: the companies with a real share of the lines, not one stray mention
                       "companies": [c for c, n in who[fam].most_common(3)
                                     if len(who[fam]) == 1 or n >= max(2, 0.2 * who[fam].most_common(1)[0][1])],
                       "photos": photos[fam]}
    return {"floors": floors, "trades": trades, "floors_logged": logged,
            "floors_from_schedule": sorted(set(floors) - set(logged)) if floors_fixed is None else []}


def build(rows: Iterable[Dict[str, Any]], *, end: date, period_start: Optional[date] = None,
          plan_floors: Iterable[int] = ()) -> Dict[str, Any]:
    """The board as of `end`, plus the estimate as it stood at the end of each
    week before (`history`, oldest first, at most HISTORY_POINTS), read from
    the records up to each of those days only."""
    rows = [r for r in rows if isinstance(r.get("date"), date)]
    b = _board(rows, end, plan_floors=plan_floors)
    first = min((r["date"] for r in rows if r["date"] <= end and families_of(r)), default=None)
    history: List[Dict[str, Any]] = []
    if first is not None:
        we = end
        while we >= first and len(history) < HISTORY_POINTS:
            snap = _board(rows, we, b["floors"]) if we != end else b
            history.append({"end": we, "estimates": {k: t["estimate"] for k, t in snap["trades"].items()
                                                      if t["estimate"] is not None}})
            we -= timedelta(days=7)
        history.reverse()
    b["history"] = history
    b["end"] = end
    b["period_start"] = period_start
    # The kinds of work of the period, the most-worked first: days on which a
    # filed log placed the work anywhere in the period.
    days_in: Dict[str, set] = defaultdict(set)
    for r in rows:
        if period_start and period_start <= r["date"] <= end:
            for fam, _ph in families_of(r):
                days_in[fam].add(r["date"])
    b["worked_in_period"] = sorted((k for k in b["trades"] if days_in.get(k)),
                                   key=lambda k: (-len(days_in[k]), ORDER.get(k, 99)))
    return b


# ── IN PLAIN ENGLISH ─────────────────────────────────────────────────────────

def sentence(t: Dict[str, Any], floors: List[int]) -> str:
    """"Framing (Arkon Builders): appears complete on floors 1–2; in progress
    on floors 3–4." No percent: the estimate is printed beside it, labelled."""
    by: Dict[str, List[int]] = defaultdict(list)
    for f, c in t["cells"].items():
        if c["stage"] != NONE:
            by[c["stage"]].append(f)
    parts = []
    for st, words in ((DONE, "appears complete on"), (ACTIVE, "in progress on"),
                      (STARTED, "started earlier on")):
        if by.get(st):
            parts.append(f"{words} {floors_words(by[st])}")
    ew = t.get("elsewhere")
    if ew:
        where = " and ".join(ew.get("places") or []) or "areas not tied to a floor"
        parts.append(f"{STAGE_LABEL[ew['stage']].lower()} at {where}")
    none = [f for f, c in t["cells"].items() if c["stage"] == NONE]
    if none and floors and len(none) < len(floors):
        parts.append(f"not yet reported on {floors_words(none)}")
    who = f" ({', '.join(t['companies'])})" if t.get("companies") else ""
    return f"{t['label']}{who}: " + ("; ".join(parts) if parts else "no work reported") + "."


def floors_basis(board: Dict[str, Any]) -> str:
    """What the estimate is counted over, in one sentence."""
    n, extra = len(board.get("floors") or []), board.get("floors_from_schedule") or []
    if not n:
        return ""
    if extra:
        return (f"Counted over {n} floors: the {len(board.get('floors_logged') or [])} a filed daily log has named "
                f"and {len(extra)} more that the confirmed schedule file names ({floors_words(extra)}).")
    return (f"Counted over the {n} floor{'' if n == 1 else 's'} a filed daily log has named so far. The report is not "
            "told how many floors the job has, so a floor no log has named yet is not counted.")


def counts_words(t: Dict[str, Any]) -> str:
    """"complete on 14 of 22 floors, under way on 3" -- the count behind a percent."""
    c = t.get("counts") or {}
    if not c.get("of") or t.get("estimate") is None:
        return ""
    return (f"{c['done']} of {c['of']} floors appear complete" + (f", {c['under_way']} under way" if c["under_way"] else ""))


BASIS = ("Estimated from the filed daily logs: on each floor, work the log reports as complete, or that the next "
         "trade in sequence has followed (and the crew has not returned to in a week), counts as complete; work "
         "reported on that floor counts as half done; a floor that no log line names for that work counts as not started. "
         "Not measured on site and not taken from a schedule.")
