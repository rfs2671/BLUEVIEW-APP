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
from typing import Any, Dict, Iterable, List, Optional, Sequence

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


#: Words that state an absence on their own. An answer that carries one must
#: also carry coverage words (coverage_lines / absence).
BARE_ABSENCE = re.compile(
    r"\bnot\s+in\s+(?:nyc\s+)?public\s+data\b|\bno\s+(?:\w+\s+){0,2}inspections?\s+(?:happened|on\s+record|were\s+found)\b"
    r"|\bnone\s+on\s+record\b|\bthere\s+are\s+no\s+completed\s+inspections\b", re.I)
COVERAGE_WORDS = re.compile(r"\bnot\s+checked\b|\bchecked:\s", re.I)


def bare_absence(text: Any) -> Optional[str]:
    """The first absence phrase in `text` that no coverage statement backs, or
    None. A text that names what was and was not checked may say none."""
    t = str(text or "")
    m = BARE_ABSENCE.search(t)
    if not m:
        return None
    return None if COVERAGE_WORDS.search(t) and not re.search(r"\bnot\s+in\s+(?:nyc\s+)?public\s+data\b", t, re.I) \
        else m.group(0)
