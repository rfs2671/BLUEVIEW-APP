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
# Up to this many jobs, an all-jobs answer gets message excerpts too; above
# it, counts only — but always every job.
CROSS_DETAIL_MAX_JOBS = 15

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


MENU_AGAIN_TEXT = "Reply with the number or the address."
NUDGE_TEXT = "I'm here. Ask about a job and I'll check it."


def house_number(label: str) -> str:
    first = str(label or "").strip().split(" ")[0]
    return first if first.isdigit() else ""


def pick_from_menu(text: Any, options: List[Dict[str, Any]]) -> Optional[str]:
    """The id of the job a reply to an open "Which job?" menu picks, else
    None. Accepts the menu number ("2"), the house number ("588", also inside
    a sentence: "I said 588"), or a partial address / group name
    ("walworth"). Only the menu's own jobs; two matches is no pick."""
    i = parse_menu_choice(text, len(options))
    if i is not None:
        return str(options[i]["id"])
    t = _norm(text)
    by_number = [o for o in options if house_number(o.get("label"))
                 and f" {house_number(o.get('label'))} " in t]
    if len(by_number) == 1:
        return str(by_number[0]["id"])
    hit = match_jobs(str(text or ""), options)
    return str(hit[0]) if len(hit) == 1 else None


def is_menu_message(body: Any) -> bool:
    return str(body or "").strip().startswith("Which job?")


_EMPTY_RE = re.compile(r"^[\s.?!…,;:-]*$")
_NUDGE = {"hello", "hi", "hey", "ping", "bump", "anyone", "and", "so", "well", "hello?"}


def is_nudge(text: Any) -> bool:
    """'.', '?', '??', 'hello?', 'bump': no question of its own -- with a
    reply-to, the quoted message is the question."""
    t = str(text or "").strip().lower()
    if _EMPTY_RE.match(t):
        return True
    words = re.findall(r"[a-z]+", t)
    return 0 < len(words) <= 2 and all(w in _NUDGE for w in words)


def with_quoted(text: str, quoted_body: str, quoted_from_bot: bool) -> str:
    """The question to answer for a reply-to in a DM (as in groups): the
    quoted message is the context. A nudge under your own question is that
    question again."""
    q = str(quoted_body or "").strip()
    t = str(text or "").strip()
    if not q:
        return t
    if not quoted_from_bot and is_nudge(t):
        return q
    who = "your (Levelog Assistant's) earlier message" if quoted_from_bot \
        else "their earlier message"
    return f"{t}\n\n(This is a reply to {who}: \"{q[:400]}\")"


HISTORY_HOURS = 4
HISTORY_MAX = 20


def history_messages(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """This chat's recent messages, oldest first, as chat turns for the
    model: theirs as 'user', Levelog's (answers, menus, the brief) as
    'assistant'."""
    out = []
    for r in rows:
        b = str(r.get("body") or "").strip()
        if not b:
            continue
        out.append({"role": "assistant" if str(r.get("sender") or "") == "bot" else "user",
                    "content": b[:1500]})
    return out[-HISTORY_MAX:]


def last_question(rows: Iterable[Dict[str, Any]], jobs: List[Dict[str, Any]]) -> str:
    """Their latest message in the history that asks something (not a
    bare job name, not a nudge)."""
    for r in reversed(list(rows)):
        if str(r.get("sender") or "") == "bot":
            continue
        b = str(r.get("body") or "").strip()
        if b and not is_nudge(b) and not is_job_only(b, jobs):
            return b
    return ""


def job_named(text: Any, jobs: List[Dict[str, Any]], *, in_sentence: bool = False
              ) -> Optional[str]:
    """The one job a message names by house number ("588", "I said 588")
    or address -- not by menu number (no menu is open). In a sentence only
    a house number of 2+ digits counts ("since 8:07" is not 8 Walworth)."""
    t = _norm(text)
    by_number = [o for o in jobs if house_number(o.get("label"))
                 and (not in_sentence or len(house_number(o.get("label"))) >= 2)
                 and f" {house_number(o.get('label'))} " in t]
    if len(by_number) == 1:
        return str(by_number[0]["id"])
    hit = match_jobs(str(text or ""), jobs)
    return str(hit[0]) if len(hit) == 1 else None


def is_job_only(text: Any, jobs: List[Dict[str, Any]]) -> bool:
    """'588', '8 walworth', 'the 588 one': names a job and asks nothing."""
    t = str(text or "").strip()
    if not t or "?" in t or len(t.split()) > 4:
        return False
    return job_named(t, jobs) is not None


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
    "the group. Talk like a sharp assistant super texting a PM: lead with the "
    "answer, short, direct, no filler, no greeting, never 'Yes, that's current "
    "information'. The earlier messages of this chat (both sides, including the "
    "morning brief you sent) are above: use them to understand what 'that', "
    "'those', 'the 2 added' or 'since the morning' mean, and never pivot to an "
    "unrelated topic. Numbers and names come ONLY from this turn's tool results, "
    "never from the earlier messages or memory. If a reference is truly "
    "ambiguous, ask ONE short question naming the options. Name a job "
    "by its address. Answer only about the job named in the facts above. Use "
    "the tools for data; never invent a DOB number, date, fine, permit or "
    "violation. You cannot file, renew, change or create anything here: if "
    "asked, say that is done in the Levelog app. You cannot send drawing "
    "images or the company's full worker roster here: say what the drawings "
    "say (search_plans) or who is on this job (who_on_site), and that sheets "
    "are in the app."
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
