"""AN ABSENCE IS ONLY AS GOOD AS THE SOURCES THAT WERE READ.

The 588 miss (2026-11-10): LeveLog said the job's plumbing inspection results
were "not in public data". They were on the public DOB NOW: Inspections portal;
LeveLog had never read it. "None" was said about a source nobody checked.

So every answer that states an absence about inspections ("no inspections",
"none on record") goes through here. A source is one of:

  checked      read, with the time it was read (`as_of`)
  not_checked  not read by this answer (a reader that is off, a source
               LeveLog does not read at all), with why
  unreachable  asked and did not answer (an error page, a challenge, a
               timeout), with why
  not_loaded   reached, but the part that holds the answer did not load
               (a static page whose inspection list is filled by a postback)

`absence()` may say "none" only when EVERY applicable source was checked; any
other source is named, with why, and the words say this is not a finding of
none. Pure: no database, no network.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

CHECKED, NOT_CHECKED, UNREACHABLE, NOT_LOADED = "checked", "not_checked", "unreachable", "not_loaded"
STATES = (CHECKED, NOT_CHECKED, UNREACHABLE, NOT_LOADED)
_STATE_WORDS = {NOT_CHECKED: "not checked", UNREACHABLE: "unreachable", NOT_LOADED: "not loaded"}

# ── THE INSPECTION SOURCES ────────────────────────────────────────────────
DOB_OPEN_DATA = "dob_open_data"
DOB_NOW_INSPECTIONS = "dob_now_inspections"
TEAM_REPORTS = "inspection_reports"
LABELS = {
    DOB_OPEN_DATA: "NYC Open Data DOB job filings and permits (sign-offs), as LeveLog's DOB sync stored them",
    DOB_NOW_INSPECTIONS: "DOB NOW: Inspections (public portal: plumbing and other trade inspection results)",
    TEAM_REPORTS: "inspections the team posted in WhatsApp (inspection reports)",
    "dob_now_inspections_plus": "DOB NOW: Inspections Plus (electrical inspections)",
    "dep": "DEP water-main, wet-connection and sewer-connection inspections",
    "fdny": "FDNY fire-alarm and sprinkler acceptance tests",
    "tr1": "TR1 special inspections (filed by the special inspector in DOB NOW: Build; results not public)",
}
#: Sources no LeveLog reader covers: always named, never silently dropped.
NOT_READ_BY_LEVELOG = ("dob_now_inspections_plus", "dep", "fdny", "tr1")
NOT_A_LEVELOG_SOURCE = "not a source LeveLog reads"


def entry(key: str, state: str, *, label: Optional[str] = None, as_of: Any = None, why: Optional[str] = None,
          found: Optional[int] = None) -> Dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"unknown coverage state {state!r}")
    if state == CHECKED and as_of is None:
        raise ValueError("a checked source needs the time it was read")
    if state != CHECKED and not why:
        raise ValueError("a source that was not checked needs why")
    return {"key": key, "label": label or LABELS.get(key, key.replace("_", " ")), "state": state,
            "as_of": as_of, "why": why, "found": found}


def not_read_by_levelog() -> List[Dict[str, Any]]:
    return [entry(k, NOT_CHECKED, why=NOT_A_LEVELOG_SOURCE) for k in NOT_READ_BY_LEVELOG]


def checked(sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources or () if s.get("state") == CHECKED]


def unchecked(sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources or () if s.get("state") != CHECKED]


def complete(sources: Sequence[Dict[str, Any]]) -> bool:
    """Every applicable source was read. An empty list is NOT complete:
    nothing was read."""
    return bool(sources) and not unchecked(sources)


def _when(v: Any) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M UTC") if v.tzinfo else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).replace("T", " ") if v else "time not recorded"


def _said(s: Dict[str, Any]) -> str:
    if s["state"] == CHECKED:
        return f"{s['label']} (read {_when(s.get('as_of'))})"
    return f"{s['label']} ({_STATE_WORDS[s['state']]}: {s.get('why')})"


def coverage_lines(sources: Sequence[Dict[str, Any]], *, topic: str = "inspections") -> List[str]:
    """Which sources were read for this answer and which were not."""
    got, gone = checked(sources), unchecked(sources)
    out = [f"Sources for {topic} — checked: " + ("; ".join(_said(s) for s in got) if got else "none") + "."]
    if gone:
        out.append(f"Not checked, so {topic} there are unknown (not absent): " + "; ".join(_said(s) for s in gone) + ".")
    return out


def absence(what: str, sources: Sequence[Dict[str, Any]]) -> str:
    """The only way an answer says there are no `what`. 'None' only when every
    source was checked; otherwise the unchecked sources are named."""
    got, gone = checked(sources), unchecked(sources)
    if complete(sources):
        return f"No {what} in any source checked: " + "; ".join(_said(s) for s in got) + "."
    seen = "; ".join(_said(s) for s in got) if got else "no source"
    return (f"No {what} found in what was checked ({seen}). Not checked: " + "; ".join(_said(s) for s in gone)
            + f". So this is not a finding that there are no {what}.")


#: Words that state an absence about inspections. "Not in public data" is
#: ALWAYS wrong for DOB NOW (the portal is public); the rest are allowed only
#: when every applicable source was checked, or when the same text names each
#: source that was NOT checked, with its state.
_PUBLIC_RX = r"(?:\bnot|n['’]t)\s+(?:in|on|part\s+of)\s+(?:nyc\s+|the\s+)?public\s+(?:data|records?)\b"
_PUBLIC_DATA = re.compile(_PUBLIC_RX, re.I)
_INSP = r"(?:\w+[\s-]+){0,3}inspections?(?:\s+results?)?"
BARE_ABSENCE = re.compile(
    _PUBLIC_RX +
    rf"|\bthere\s+(?:were|are|is|was|have\s+been|has\s+been)\s+no\s+{_INSP}"
    rf"|\bno\s+{_INSP}\s+(?:happened|on\s+(?:the\s+)?record|(?:were\s+|was\s+)?found|exists?|(?:were\s+|was\s+)?recorded"
    r"|(?:have|has)\s+been|yet|so\s+far|at\s+all)\b"
    r"|\bnever\s+(?:been\s+)?inspected\b|\b(?:dob|nobody|no\s+one)\s+(?:has\s+)?never\s+inspected\b"
    r"|\bno\s+inspection\s+results?\b|\bnone\s+on\s+(?:the\s+)?record\b|\bnothing\s+on\s+(?:the\s+)?record\b"
    r"|\bthere\s+are\s+no\s+completed\s+inspections\b|\binspection\(s\)\s+with\s+no\s+record\b"
    r"|\bno\s+(?:\w+\s+){0,2}inspections?\s+(?:were\s+|was\s+)?(?:done|held|performed|passed|carried\s+out)\b", re.I)
_STATE_SAID = re.compile(r"\bnot\s+checked\b|\bunreachable\b|\bnot\s+loaded\b", re.I)


def short(source: Dict[str, Any]) -> str:
    """A source's name without its gloss: 'DOB NOW: Inspections'."""
    return str(source.get("label") or source.get("key") or "").split(" (")[0]


def bare_absence(text: Any, sources: Optional[Sequence[Dict[str, Any]]] = None) -> Optional[str]:
    """The first absence phrase in `text` the coverage does not back, or None.

    'Not in public data' always counts. Any other absence phrase is backed
    only when every applicable source was checked (`sources` complete), or the
    SAME text names every unchecked source together with its state ('not
    checked' / 'unreachable' / 'not loaded'). Without `sources` nothing is
    known to be checked, so any absence phrase counts. A line saying
    'checked:' is NOT a pass on its own."""
    t = str(text or "")
    m = _PUBLIC_DATA.search(t) or BARE_ABSENCE.search(t)
    if not m:
        return None
    if _PUBLIC_DATA.search(t):
        return _PUBLIC_DATA.search(t).group(0)
    if sources is None:
        return m.group(0)
    if complete(sources):
        return None
    gone = unchecked(sources)
    named = all(short(s) and short(s) in t for s in gone) and _STATE_SAID.search(t)
    return None if named else m.group(0)


def enforce(text: Any, sources: Sequence[Dict[str, Any]], *, topic: str = "inspections") -> Tuple[str, Optional[str]]:
    """(text, the phrase that was not backed | None). A text whose absence the
    coverage does not back gets its 'not in public data' sentences replaced
    and the coverage lines appended, so what goes out names every source that
    was not checked. Used on every composed inspections answer."""
    t = str(text or "")
    bad = bare_absence(t, sources)
    if not bad:
        return t, None
    t = re.sub(r"[^.\n]*" + _PUBLIC_DATA.pattern + r"[^.\n]*\.?",
               "Not every inspection source was checked, so what is missing here is unknown, not absent.",
               t, flags=re.I)
    return t.rstrip() + "\n" + "\n".join(coverage_lines(sources, topic=topic)), bad


#: The tools whose results carry the inspection coverage lines.
INSPECTION_TOOLS = frozenset({"dob_status", "project_status"})
_NOT_CHECKED_LINE = re.compile(r"Not checked, so [^:\n]*unknown \(not absent\):([^\n]*)")


def _trace_unchecked(trace: Optional[Iterable[Dict[str, Any]]]) -> Tuple[bool, List[str]]:
    """(an inspections tool ran, the sources its result says were NOT checked).
    A result that carries no coverage line (cut short, or an old shape) counts
    as 'not every inspection source' checked."""
    ran, names = False, []
    for t in trace or ():
        if not isinstance(t, dict) or t.get("tool") not in INSPECTION_TOOLS or t.get("error"):
            continue
        ran = True
        res = str(t.get("result") or "")
        lines = _NOT_CHECKED_LINE.findall(res)
        for said in lines:
            for label in LABELS.values():
                nm = label.split(" (")[0]
                if nm in said and nm not in names:
                    names.append(nm)
        if not lines and "Sources for inspection" not in res and "not every inspection source" not in names:
            names.append("not every inspection source")
    return ran, names


def rewrite_reply(text: Any, trace: Optional[Iterable[Dict[str, Any]]] = None) -> Tuple[str, int]:
    """THE REPLY PATH: (the answer, sentences replaced). A model-written
    answer that says no inspections happened, or that results are not in
    public data, has the first such sentence replaced by what is known -- the
    sources this turn's dob_status / project_status said were NOT checked, or
    that no inspection source was checked this turn -- and the rest dropped.
    'Not in public data' is replaced even when every source was checked."""
    t = str(text or "")
    ran, names = _trace_unchecked(trace)
    if not ran:
        say = "I haven't checked the inspection sources for that (dob_status reads them)."
    elif names:
        say = "That is not a finding that none happened: not checked — " + ", ".join(names) + "."
    else:
        say = "Every inspection source was checked."

    def flagged(p: str) -> bool:
        return bool(_PUBLIC_DATA.search(p)) or (bool(BARE_ABSENCE.search(p)) and (not ran or bool(names)))
    n, out = 0, []
    for row in t.split("\n"):
        kept = []
        for p in re.split(r"(?<=[.!?])\s+", row):
            if p and flagged(p):
                n += 1
                if n == 1:
                    kept.append(say)
            else:
                kept.append(p)
        out.append(" ".join(x for x in kept if x))
    return ("\n".join(out), n) if n else (t, 0)
