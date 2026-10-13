"""The company's subs, for the DM assistant: list_subs and find_sub.

Tue Oct 13, 10:52 AM: "Is there low voltage company in subs list?" got
"Which job?", then for 588: "I can't check the full list of subcontractors
here. Please use the app." Both wrong. The subs list is every live job's
roster (trade_assignments: a trade and the company doing it), so a question
about the list is answered for the company -- each sub, its trades, the jobs
it is on, and its punch contact there -- never "Which job?", never "use the
app".

  rows()          one row per (job, roster row): company, trade, job, contact
  by_company()    the list, one entry per company
  find()          the rows a trade or a name matches: the trade synonyms
                  (lib/trades.py) and SEARCH_GROUPS ("low voltage" = LV,
                  data, security, fire alarm cabling ...)
  render_list() / render_find()   the plain text the tools return
  company_question()   a question about the subs list itself (no job needed)

Pure: no database, no server import. Never a phone number: a punch contact is
a name.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from lib import trades as lib_trades

#: Words that mean the same kind of sub. A search for any of them finds a
#: sub whose trade or name has any of them.
SEARCH_GROUPS: List[List[str]] = [
    ["low voltage", "lv", "data", "cabling", "structured cabling", "security",
     "fire alarm", "fire alarm cabling", "access control", "cctv", "cameras", "camera",
     "telecom", "av", "audio visual", "intercom", "network", "networking"],
]

_GENERIC = {"sub", "subs", "subcontractor", "subcontractors", "company", "companies",
            "contractor", "contractors", "guy", "guys", "vendor", "vendors", "trade",
            "crew", "someone", "somebody", "anyone", "anybody", "list", "our", "we",
            "the", "a", "an", "any", "in", "on", "for", "of", "is", "are", "there",
            "do", "have", "got", "who", "whos", "which", "what", "use", "doing",
            "inc", "llc", "corp", "co", "does", "can", "you", "me", "tell", "show",
            "all", "my", "please", "check", "if", "know", "whats", "need", "has",
            "us", "here", "it", "they", "them", "with", "type", "kind", "one", "ones"}

MAX_LIST = 30


def _fold(text: Any) -> str:
    return lib_trades.fold(text)


def _words(text: Any) -> List[str]:
    return [w for w in _fold(text).split() if w]


def _has(hay: str, term: str) -> bool:
    """`term` as whole words in `hay` (both folded)."""
    return bool(term) and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", hay) is not None


# ── The rows ────────────────────────────────────────────────────────────────

def rows(projects: Iterable[Dict[str, Any]], label, *,
         contacts: Optional[Dict[str, Dict[str, str]]] = None,
         active=None) -> List[Dict[str, Any]]:
    """One row per (job, active roster row): {company, trade, job_id, job,
    contact}. `label(project)` names the job; `contacts` is
    {project_id: {roster row id: person name}}; `active(project)` the
    project's selectable roster rows (default: every row)."""
    out = []
    for p in projects:
        pid = str(p.get("_id") or p.get("id") or "")
        roster = active(p) if active else (p.get("trade_assignments") or [])
        for r in roster:
            company = " ".join(str(r.get("company") or "").split())
            trade = " ".join(str(r.get("trade") or "").split())
            if not company and not trade:
                continue
            out.append({"company": company or "(no company yet)", "trade": trade,
                        "job_id": pid, "job": label(p),
                        "contact": ((contacts or {}).get(pid) or {}).get(str(r.get("id") or ""))})
    return out


def by_company(rs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{company, trades, jobs: [{job, trade, contact}]}], by company name."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rs:
        key = _fold(r["company"])
        e = out.setdefault(key, {"company": r["company"], "trades": [], "jobs": []})
        if r["trade"] and r["trade"] not in e["trades"]:
            e["trades"].append(r["trade"])
        e["jobs"].append({"job": r["job"], "trade": r["trade"], "contact": r.get("contact")})
    return sorted(out.values(), key=lambda e: e["company"].lower())


# ── Finding one ─────────────────────────────────────────────────────────────

def terms(query: Any) -> List[str]:
    """What to look for: the words said, the trade they name
    (lib/trades.SYNONYMS), and every word of a SEARCH_GROUPS group they are
    in."""
    q = " ".join(w for w in _words(query) if w not in _GENERIC)
    if not q:
        return []
    out = [q]
    for group in SEARCH_GROUPS:
        if any(_has(q, t) or _has(t, q) for t in group):
            out += [t for t in group if t not in out]
    canon = lib_trades.resolve(q, sorted(set(lib_trades.SYNONYMS.values())))
    if canon:
        out.append(_fold(canon))
        out += [k for k, v in lib_trades.SYNONYMS.items() if v == canon and k not in out]
    return out


def find(query: Any, rs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rows whose trade or company name a trade or a name matches."""
    ts = terms(query)
    if not ts:
        return []
    hits = []
    for r in rs:
        trade, company = _fold(r["trade"]), _fold(r["company"])
        if any(_has(trade, t) or _has(company, t) or (t == trade and t) for t in ts) \
                or any(_has(t, trade) for t in ts if len(trade) > 3):
            hits.append(r)
    return hits


# ── What the tools say ──────────────────────────────────────────────────────

def _jobs_text(e: Dict[str, Any], with_trade: bool) -> str:
    parts = []
    for j in e["jobs"]:
        bits = [j["job"]]
        if with_trade and j.get("trade"):
            bits.append(j["trade"])
        if j.get("contact"):
            bits.append(f"punch contact {j['contact']}")
        parts.append(" — ".join(bits) if len(bits) > 1 else bits[0])
    return "; ".join(parts)


def _line(e: Dict[str, Any]) -> str:
    trades = ", ".join(e["trades"]) or "no trade set"
    several = len(e["trades"]) > 1
    return f"• {e['company']} ({trades}) — on {_jobs_text(e, several)}"


def render_list(rs: Sequence[Dict[str, Any]], job: Optional[str] = None) -> str:
    """The subs list (one job's, when `job` is named)."""
    groups = by_company(rs)
    where = f"on {job}" if job else "in your subs list"
    if not groups:
        return f"No subs {where} yet."
    head = f"{len(groups)} sub{'s' if len(groups) != 1 else ''} {where}:"
    lines = [_line(e) for e in groups[:MAX_LIST]]
    if len(groups) > MAX_LIST:
        lines.append(f"+{len(groups) - MAX_LIST} more in the Levelog app")
    return "\n".join([head] + lines)


def render_find(query: Any, rs: Sequence[Dict[str, Any]]) -> str:
    """Yes with who and where, or no with the list's trades."""
    what = " ".join(w for w in _words(query) if w not in _GENERIC) or str(query or "").strip()
    hits = find(query, rs)
    if hits:
        groups = by_company(hits)
        n = len(groups)
        head = f"Yes — {n} {'match' if n == 1 else 'matches'} for {what} in your subs list:"
        return "\n".join([head] + [_line(e) for e in groups[:MAX_LIST]])
    have = sorted({r["trade"] for r in rs if r["trade"]}, key=str.lower)
    tail = f" Trades on the list: {', '.join(have)}." if have else " The subs list is empty."
    return f"No {what} sub in your subs list.{tail}"


# ── Is this a question about the subs list? ─────────────────────────────────

_LIST_WORDS = re.compile(
    r"\bsubs?\s*(?:list|contractors?)\b|\bsubcontractors?\b|\bour subs\b|\bsub list\b"
    r"|\bmy subs\b|\ball (?:the |our |my )?subs\b|\bwhich subs\b|\bwhat subs\b", re.I)
_ASKS = re.compile(
    r"\b(?:do we (?:have|use|got)|have we got|is there|are there|any|who(?:'s| is| are)?|"
    r"who do we (?:use|have)|we have|got)\b", re.I)
_WHO_WORDS = re.compile(
    r"\b(?:compan(?:y|ies)|subs?|contractors?|guys?|someone|somebody|anyone|anybody|vendors?|"
    r"electrician|plumber|painter|roofer|mason|framer|glazier|carpenter|welder|surveyor|"
    r"installer|integrator)\b", re.I)
# On site right now is a job's check-ins, not the list.
_ON_SITE = re.compile(r"\b(?:on ?site|today|right now|checked in|check[- ]?ins?|working|"
                      r"here now|there now|showed up|arrived)\b", re.I)


def names_a_trade(text: Any) -> bool:
    """The text names a trade (a synonym) or a SEARCH_GROUPS word."""
    t = _fold(text)
    if any(_has(t, w) for g in SEARCH_GROUPS for w in g):
        return True
    return any(_has(t, k) for k in lib_trades.SYNONYMS if len(k) > 2)


def company_question(text: Any) -> bool:
    """A question about the company's subs list: "Is there low voltage
    company in subs list?", "do we have a plumber?", "who's our
    electrician?", "list our subs". Not one about who is on site."""
    t = str(text or "")
    if _ON_SITE.search(t):
        return False
    if _LIST_WORDS.search(t):
        return True
    return bool(_ASKS.search(t) and _WHO_WORDS.search(t) and names_a_trade(t))


_SUB_WORDS = re.compile(r"\bsubs?\b|\bsubcontractor|\bcompan(?:y|ies)\b|\bcontractors?\b", re.I)


def about_subs(text: Any) -> bool:
    """A question that is about subs at all (the company's list, or one
    job's): the backstop's trigger."""
    return company_question(text) or bool(_SUB_WORDS.search(str(text or "")))


# The model claiming it cannot see the subs (it can: list_subs / find_sub).
_DENIES_SUBS = re.compile(
    r"\b(?:can'?t|cannot|can ?not|unable to|not able to|don'?t have(?: any)? access|"
    r"do not have(?: any)? access|no access|not have access)\b[^.?!\n]{0,60}"
    r"\b(?:subs?|subcontractors?|contractors?|compan(?:y|ies)|vendors?|roster|list)", re.I)
_USE_APP = re.compile(
    r"\b(?:use|check|open|see|look|find|view|go to)\b[^.?!\n]{0,30}?\b(?:the\s+)?(?:levelog\s+)?app\b",
    re.I)


def denies_subs(reply: Any) -> bool:
    """The reply says it cannot check the subs, or sends them to the app
    for it."""
    r = str(reply or "")
    return bool(_DENIES_SUBS.search(r) or _USE_APP.search(r))


SYSTEM_PROMPT = (
    "You are Levelog Assistant in a private WhatsApp chat with a construction "
    "company admin or PM. They are asking about the COMPANY'S SUBS LIST: every "
    "sub on their jobs, with its trade, the jobs it is on and its punch "
    "contact. Use find_sub for a trade or a company name (it knows that low "
    "voltage also means LV, data, security and fire alarm cabling) and "
    "list_subs for the whole list. Answer from the tool results only: lead "
    "with yes or no, then who and which jobs. Short, plain, no greeting. "
    "Never say you cannot check the subs or that they should use the app: "
    "the tools are the subs list."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "find_sub",
        "description": (
            "Find subs in the company's subs list by trade or company name: "
            "'low voltage' (also LV, data, security, fire alarm cabling), "
            "'electrician', 'Arkon'. Returns each match with its trade, the jobs "
            "it is on and its punch contact there, or that there is none."),
        "parameters": {"type": "object", "properties": {
            "trade_or_name": {"type": "string",
                              "description": "A trade or a company name, as the user said it."}},
            "required": ["trade_or_name"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "list_subs",
        "description": (
            "The company's subs list: every sub, its trade(s), the jobs it is on "
            "and its punch contact there. Pass `job` (an address or house "
            "number) for one job's subs only."),
        "parameters": {"type": "object", "properties": {
            "job": {"type": "string", "description": "Optional: one job, as the user named it."}},
            "additionalProperties": False}}},
]
