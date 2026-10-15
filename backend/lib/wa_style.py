"""How every DM answer reads (Thu 11:35 AM: "How many arkon workers in 588"
got the whole site, 37 across every sub, and 9 late arrivals by name).

  * The first line is the answer: short, plain, no preamble.
  * At most 2 more short lines, only when they add something needed.
  * Lists and names only when asked ("who", "list", "names"); otherwise the
    offer "Want the names?" -- and "yes" sends them.
  * The short job name ("588", "8 Walworth"), never the full address in
    capitals.
  * About 300 characters, unless a list or the detail was asked for.

`tighten` is the post-check every DM answer goes through. Pure: no
database, no network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_CHARS = 300
MAX_LINES = 3                         # the answer, and at most 2 more
OFFER_NAMES = "Want the names?"
OFFER_MORE = "Want the details?"
OFFER_LIST = "Want the full list?"
MORE_SECONDS = 10 * 60                # "yes" to the offer, within 10 minutes

_ASKS_LIST = re.compile(
    r"\b(?:who|who'?s|whom|whose|list|lists|names?|name them|everyone|everybody|"
    r"each|every one|which (?:workers?|guys|people|ones|subs?|companies|items?)|"
    r"details?|detailed|in detail|full|breakdown|break it down|all of them|show me|"
    r"spell it out|settings|when (?:did|do|were|was) (?:they|those|these|he|she|the))\b",
    re.IGNORECASE)

_PREAMBLE_START = re.compile(
    r"^\s*(?:sure|of course|certainly|absolutely|great question|good question|ok(?:ay)?|"
    r"got it|here(?:'s| is| are)|let me|i(?:'ve| have) checked|i checked|based on|"
    r"according to)\b", re.IGNORECASE)


def _preamble(line: str) -> bool:
    """"Sure!", "Here's what I found:", "Let me check the records." -- a
    line that says nothing."""
    t = line.strip()
    if not t or len(t) > 70:
        return not t
    if re.fullmatch(r"(?i)(?:sure|of course|certainly|absolutely|got it|ok(?:ay)?)[!.,\s]*", t):
        return True
    return bool(_PREAMBLE_START.match(t)) and t.endswith((":", "…", "..."))


# A line that is one item of a list: "• …", "- …", "1) …", "1. …".
_ITEM = re.compile(r"^\s*(?:[•\-*–]|\d{1,3}[.)])\s+")

_MORE_YES = re.compile(
    r"^\s*(?:y|ya|yes|yeah|yep|yup|sure|please|pls|si|sí|go ahead|send (?:them|it)|"
    r"(?:the |all )?names|(?:the )?(?:full )?list|list them|show me|details|more|who)\b"
    r"[\s!.?]*(?:please|pls)?[\s!.?]*$", re.IGNORECASE)


def asks_for_list(question: Any) -> bool:
    """The question asks for names, a list or the detail ("who from Power
    Direct is here", "list the subs", "what are my settings")."""
    return bool(_ASKS_LIST.search(str(question or "")))


def wants_more(text: Any) -> bool:
    """"yes", "names", "list them" -- the answer to "Want the names?"."""
    t = str(text or "")
    return len(t.split()) <= 5 and bool(_MORE_YES.match(t))


def short_job(label: Any) -> str:
    """'588 Thomas S Boyland St' -> '588'; '8 Walworth St' -> '8 Walworth';
    a job with no house number keeps its name."""
    t = " ".join(str(label or "").split()).split(",")[0].strip()
    m = re.match(r"^(\d+[A-Za-z]?(?:-\d+)?)\s+(.*)$", t)
    if not m:
        return t
    num, rest = m.group(1), m.group(2)
    if len(re.sub(r"\D", "", num)) >= 3:
        return num
    words = [w for w in rest.split() if w.lower().strip(".") not in
             {"n", "s", "e", "w", "north", "south", "east", "west"}]
    return f"{num} {words[0]}" if words else num


_SUFFIX = {"st": "street", "ave": "avenue", "rd": "road", "blvd": "boulevard", "pl": "place",
           "ct": "court", "dr": "drive", "ln": "lane", "pkwy": "parkway", "ter": "terrace"}


def _variants(label: str) -> List[str]:
    """A job's address as it may be written: '588 Thomas S Boyland St',
    '588 THOMAS S BOYLAND STREET'."""
    base = " ".join(str(label or "").split()).split(",")[0].strip()
    if not base:
        return []
    out = {base}
    words = base.split()
    last = words[-1].lower().strip(".")
    if last in _SUFFIX:
        out.add(" ".join(words[:-1] + [_SUFFIX[last]]))
    for full, short in ((v, k) for k, v in _SUFFIX.items()):
        if last == full:
            out.add(" ".join(words[:-1] + [short]))
    return sorted(out, key=len, reverse=True)


def shorten_jobs(text: str, labels: Iterable[str]) -> str:
    """Every full job address in `text` (any case) as its short name."""
    out = str(text or "")
    for label in labels:
        short = short_job(label)
        if not short:
            continue
        for v in _variants(label):
            if v.lower() == short.lower():
                continue
            out = re.sub(r"(?<![\w])" + re.escape(v) + r"(?:,\s*(?:brooklyn|queens|bronx|manhattan|"
                         r"staten island|new york|ny)\b)*(?:,\s*ny\b)?(?![\w])", short, out,
                         flags=re.IGNORECASE)
    return out


def _cut_line(line: str, limit: int) -> str:
    """One line no longer than `limit`: up to its last full sentence (or
    clause) that fits, else its words."""
    if len(line) <= limit:
        return line
    head = line[:limit]
    for sep in (". ", "; ", " — ", ", "):
        i = head.rfind(sep)
        if i >= limit // 3:
            return head[:i + (1 if sep.startswith(".") else 0)].rstrip(" ,;—") + \
                ("" if sep.startswith(".") else ".")
    return head.rsplit(" ", 1)[0].rstrip(" ,;—") + "…"


def tighten(reply: Any, question: Any = "", labels: Iterable[str] = (),
            limit: int = MAX_CHARS) -> Tuple[str, bool]:
    """(the reply as it goes out, trimmed?). Full addresses become short
    names; a preamble line goes; over `limit` without a list asked for, the
    answer line stays, then at most 2 more lines that fit, and the offer
    ("Want the names?" when names were left out). `trimmed` -- the caller
    keeps the full reply for a "yes"."""
    text = clean(reply, labels)
    if asks_for_list(question):
        return text, False
    body = [l for l in text.splitlines() if l.strip()]
    first, rest = (body[0], body[1:]) if body else ("", [])
    # Short is not enough: a list or more than 3 lines unasked is cut too
    # (Codex on #802).
    if len(text) <= limit and len(body) <= MAX_LINES and not any(_ITEM.match(l) for l in rest):
        return text, False
    offer = (OFFER_NAMES if _names_in(rest) else OFFER_LIST if any(_ITEM.match(l) for l in rest)
             else OFFER_MORE)
    room = limit - len(offer) - 1
    kept = [_cut_line(first, room)]
    for l in rest:
        if len(kept) >= MAX_LINES or _ITEM.match(l):
            break
        if len("\n".join(kept + [l])) > room:
            break
        kept.append(l)
    return "\n".join(kept + [offer]), True


def clean(reply: Any, labels: Iterable[str] = ()) -> str:
    """Short job names, and no preamble line ("Sure! Here's what I found:")."""
    lines = [l.rstrip() for l in shorten_jobs(str(reply or "").strip(), labels).splitlines()]
    while len([l for l in lines if l.strip()]) > 1 and lines and _preamble(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def _names_in(lines: List[str]) -> bool:
    """Lines that name people: 3+ capitalised words in a row somewhere, or
    "A, B and C"."""
    t = " ".join(lines)
    return bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+(?:,| and) [A-Z][a-z]+", t))


# ── A SUB, NAMED IN A HEADCOUNT QUESTION ─────────────────────────────────────

def _fold(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


_CO_TAIL = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "group", "builders",
            "construction", "contracting", "contractors", "contractor", "services", "the",
            "enterprises", "nyc", "ny"}
_TRADE_WORDS = {"plumbing", "plumbers", "electric", "electrical", "electricians", "mechanical",
                "hvac", "roofing", "concrete", "drywall", "steel", "iron", "ironworks", "masonry",
                "painting", "painters", "carpentry", "glass", "glazing", "tile", "demolition",
                "demo", "excavation", "framing", "sprinkler", "sprinklers", "fire", "elevator",
                "windows", "doors", "flooring", "insulation", "waterproofing", "scaffolding"}
_NOT_A_CO = {"site", "here", "there", "today", "workers", "worker", "guys", "people", "crew",
             "many", "much", "how", "who", "what", "from", "with", "this", "that", "job"}


def company_in(question: Any, names: Iterable[str]) -> List[str]:
    """The companies (of `names`) a question names, fuzzy: "arkon" ->
    "Arkon Builders", "J&G" -> "J&G Plumbing", "power direct". Several when
    it names several."""
    q = f" {_fold(question)} "
    qwords = q.split()
    exact: List[str] = []
    loose: List[str] = []
    for name in sorted({str(n).strip() for n in names if str(n or "").strip()}):
        full = _fold(name)
        core = " ".join(w for w in full.split() if w not in _CO_TAIL) or full
        # "J&G" for "J&G Plumbing": the name without its trade words too.
        bare = " ".join(w for w in core.split() if w not in _TRADE_WORDS) or core
        if any(x and f" {x} " in q for x in (full, core)):
            exact.append(name)
            continue
        first = core.split()[0] if core else ""
        if (bare and len(bare) >= 3 and f" {bare} " in q) or (
                len(first) >= 4 and first not in _NOT_A_CO and (
                    first in qwords or any(_close(first, w) for w in qwords if len(w) >= 4))):
            loose.append(name)
    # "Power Direct" said in full: never "Power Electrical" too (Codex on
    # #802) -- a name said whole wins over a part of another.
    return exact or loose


def _close(a: str, b: str) -> bool:
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


_PRESENCE = re.compile(
    r"\b(?:is|are|was|were|did|has|have|any(?:one|body)?|who)\b.*\b(?:on ?site|onsite|here|there|"
    r"in today|working(?: today)?|checked in|check(?:ed)? in|show(?:ed)? up|come in|came in|"
    r"at (?:the )?(?:job|site))\b", re.IGNORECASE)


def asks_presence(question: Any) -> bool:
    """"is J&G on site", "who from Power Direct is here", "did Arkon show up"."""
    return bool(_PRESENCE.search(str(question or "")))
