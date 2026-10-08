"""Levelog Assistant in a direct message — the pure parts.

Who may use it, which job a message is about, the "Which job?" menu, and
whether a question is about one job, all of them, or neither. No database and
no network here; server.py (`_dm_assistant_*`) does the reading.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# Everyone who is not an opted-in Admin or PM gets this, and only this. The
# same words for an unknown number, a CP, a superintendent or an admin who
# has not turned the assistant on: nothing here tells a stranger who has an
# account or what role they hold.
NOT_FOR_YOU_TEXT = (
    "This assistant is for project admins. Ask your admin to add you."
)
NO_JOBS_TEXT = "Levelog Assistant here. You don't have any jobs in Levelog yet."
MENU_EXPIRED_TEXT = "Which job did you mean? Name the address and I'll answer."

JOB_MEMORY_SECONDS = 30 * 60      # the last job used in this DM
MENU_SECONDS = 10 * 60            # how long a "Which job?" menu stays open
MENU_MAX = 9

SCOPE_PROJECT = "project"
SCOPE_ALL = "all"
SCOPE_GENERAL = "general"


def _norm(text: Any) -> str:
    t = str(text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " " + re.sub(r"\s+", " ", t).strip() + " "


def street_label(project: Dict[str, Any]) -> str:
    """'588 Thomas S Boyland St, Brooklyn, NY' -> '588 Thomas S Boyland St'.
    The job's address, short; its name only when no address is on file."""
    for k in ("address", "location"):
        v = str(project.get(k) or "").strip()
        if v:
            return v.split(",")[0].strip()
    return str(project.get("name") or "the project").strip()


_SUFFIXES = {"st", "street", "ave", "avenue", "rd", "road", "blvd", "pl",
             "place", "ct", "court", "dr", "drive", "ln", "lane", "pkwy",
             "parkway", "ter", "terrace", "way", "s", "n", "e", "w"}


def job_aliases(project: Dict[str, Any], group_names: Iterable[str] = ()) -> List[str]:
    """What a person may call this job in a message, normalised.

    The street address ('588 thomas s boyland st'), its house number and first
    street word ('588 thomas'), the street name without the number when it is
    distinctive ('thomas s boyland', 'walworth'), the project name, and the
    names of its WhatsApp groups."""
    out = set()
    street = _norm(street_label(project)).strip()
    if street:
        out.add(street)
        words = street.split()
        if len(words) >= 2 and words[0].isdigit():
            out.add(f"{words[0]} {words[1]}")
            name = words[1:]
            trimmed = list(name)
            while len(trimmed) > 1 and trimmed[-1] in _SUFFIXES:
                trimmed.pop()          # "boyland st" -> "boyland"; a middle "s" stays
            out.add(" ".join([words[0]] + trimmed))
            for cand in (" ".join(name), " ".join(trimmed)):
                if cand and (len(cand.split()) >= 2 or len(cand) >= 6):
                    out.add(cand)
    for v in [project.get("name")] + list(group_names):
        n = _norm(v).strip()
        if len(n) >= 4:
            out.add(n)
    return sorted(out, key=len, reverse=True)


def match_jobs(text: str, jobs: List[Dict[str, Any]]) -> List[str]:
    """Ids of the jobs a message names (each job: {id, aliases}). Whole
    words only, so '8 walworth' does not match '58 walworth'."""
    t = _norm(text)
    scored = []
    for j in jobs:
        found = [a for a in j.get("aliases") or [] if f" {a} " in t]
        if found:
            # A name WITH its house number ("8 walworth") beats the bare
            # street ("walworth") that two jobs on one street share.
            strength = 2 if any(a.split()[0].isdigit() for a in found) else 1
            scored.append((strength, j["id"]))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [jid for s, jid in scored if s == best]


def menu_text(jobs: List[Dict[str, Any]]) -> str:
    """'Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St'"""
    parts = [f"{i}) {j['label']}" for i, j in enumerate(jobs[:MENU_MAX], 1)]
    return "Which job? " + " ".join(parts)


def parse_menu_choice(body: Any, count: int) -> Optional[int]:
    """0-based index for a reply that is only a menu number, else None."""
    s = str(body or "").strip().rstrip(".)")
    if not s.isdigit():
        return None
    n = int(s)
    return n - 1 if 1 <= n <= min(count, MENU_MAX) else None


# ── Which kind of question ─────────────────────────────────────────────────

_ALL_RE = re.compile(
    r"\b(?:my|all(?: of)?(?: my)?|every|each|across(?: all)?(?: my)?|any of my)\s+"
    r"(?:jobs?|projects?|sites?|buildings?)\b"
    r"|\bacross\b|\bany new\b|\bwhich (?:jobs?|projects?|sites?)\b"
    r"|\b(?:this|next) (?:week|month)\b",
    re.IGNORECASE)
_PROJECT_RE = re.compile(
    r"\b(on site|onsite|who'?s (?:there|here|working)|crew|workers?|roster|"
    r"check[- ]?ins?|open items?|punch|daily log|violations?|permits?|"
    r"inspections?|dob|complaints?|swo|stop work|deliver(?:y|ies)|materials?|"
    r"drawings?|sheets?|plans?|happened|activity|going on|status|today|"
    r"yesterday|expir\w*|renew\w*)\b",
    re.IGNORECASE)
_GENERAL_RE = re.compile(
    r"^\s*(?:how do i|how to|how does|what is a|what's a|what is an|what does|"
    r"explain|can you explain|what are the rules|is it required|do i need|"
    r"help\b|what can you do)",
    re.IGNORECASE)


def question_scope(text: str) -> Optional[str]:
    """SCOPE_ALL / SCOPE_PROJECT / SCOPE_GENERAL by rule, or None when the
    rules cannot tell (the server then asks the model)."""
    t = str(text or "")
    if _GENERAL_RE.search(t) and not _ALL_RE.search(t):
        return SCOPE_GENERAL
    if _ALL_RE.search(t):
        return SCOPE_ALL
    if _PROJECT_RE.search(t):
        return SCOPE_PROJECT
    return None


DM_AGENT_CLAUSE = (
    "\n\nYOU ARE IN A PRIVATE WHATSAPP CHAT with one project admin or PM, not "
    "the group. Speak as Levelog Assistant: short, plain, specific. Name a job "
    "by its address. Answer only about the job named in the facts above. Use "
    "the tools for data; never invent a DOB number, date, fine, permit or "
    "violation. You cannot file, renew, change or create anything here: if "
    "asked, say that is done in the Levelog app."
)

CROSS_SYSTEM_PROMPT = (
    "You are Levelog Assistant, answering one project admin or PM in a private "
    "WhatsApp chat about ALL of their jobs. Use ONLY the facts below — one "
    "block per job, named by address. Never invent a job, number, date, fine, "
    "permit or violation; if the facts do not say, say you don't have it. "
    "Short: one line per job that matters, skip jobs with nothing to report, "
    "and say so in one line if nothing matches."
)

GENERAL_SYSTEM_PROMPT = (
    "You are Levelog Assistant, helping a NYC construction project admin or PM "
    "in a private WhatsApp chat. Answer general questions about using Levelog "
    "and general NYC DOB / site-safety practice in a few short sentences. You "
    "have NO project data here: never state a job's permits, violations, "
    "fines, dates or inspections, and never invent DOB figures. For "
    "rules and penalties, say it is general information, not legal advice, "
    "and point to the DOB or their expediter for their case. If the question "
    "is about one of their jobs, ask them to name the job's address."
)

SCOPE_CLASSIFIER_PROMPT = (
    "Classify a construction admin's WhatsApp question. Reply with exactly one "
    "word: project (about one job's data: crew, permits, violations, open "
    "items, deliveries, drawings, activity), all (about all of their jobs at "
    "once), or general (how to use the app, or general NYC DOB / safety "
    "knowledge with no specific job)."
)
