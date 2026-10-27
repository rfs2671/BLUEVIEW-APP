"""NEVER ABSENCE AS FACT: a DM answer about the drawings says what it did NOT
FIND, in the sheets it searched -- never what the building does not have.

10-27, spray foam on 588: search_plans returned A-104.00 and A-302.00 records
and the model answered "Nothing on the drawings calls for spray foam on the
5th floor ceiling." That is a claim about the building. What is knowable is a
claim about the search: these sheets were searched, and this was not found in
them. The prompt already said so (_render_records_for_model); the model said
the other thing anyway. So it is enforced here, on the text, as it goes out.

    detect(text, plans=True)          -> the absence-assertion sentences
    rewrite(text, trace)              -> (text, n rewritten)

A flagged sentence becomes

    Not found in the sheets I searched: A-104.00, A-302.00.

(the sheets THIS TURN's plan tools returned or said they searched -- never
invented), and once, after the answer, the closest thing that was found:

    Closest detail: A-302.00 — "<the top record's quote>"

With no plan tool this turn, a sentence that says the drawings lack something
becomes "I didn't search the sheets for that." A turn with no plan tool and
no drawing word (attendance: "No one checked in yet") is not touched.

NOT FLAGGED: questions; the allowed "Not found in the sheets…" line; what the
bot says of itself ("I couldn't find that in the drawings I've indexed");
a sheet's own note quoted with its sheet (A-302 note: "…NOT REQUIRED…").
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Tuple

PLAN_TOOLS = frozenset({"search_plans", "query_plan", "send_sheet", "sheet_info",
                        "check_drawing_set"})

NOT_FOUND_PREFIX = "Not found in the sheets I searched"
NOT_SEARCHED_TEXT = "I didn't search the sheets for that."
QUOTE_CHARS = 160

# ── WHAT AN ABSENCE ASSERTION LOOKS LIKE ──────────────────────────────────
_NEG = (r"(?:no|not|none|nothing|never|neither|nor|without|doesn'?t|does\s+not|don'?t|"
        r"do\s+not|isn'?t|is\s+not|aren'?t|are\s+not|wasn'?t|was\s+not|weren'?t|"
        r"didn'?t|did\s+not|ningun[oa]?|ningún|nada|sin)")
_VERB = (r"(?:call(?:s|ed|ing)?\s+(?:for|out)|requir\w*|show\w*|specif\w*|mention\w*|"
         r"need\w*|indicat\w*|list\w*|includ\w*|detail\w*|referenc\w*|appear\w*|"
         r"requier\w*|indica\w*|muestra\w*|especific\w*|menciona\w*|necesit\w*|"
         r"incluy\w*|aparece\w*|pide\w*)")
_ABSENCE = [
    # "Nothing on the drawings calls for", "no spray foam is required", "isn't specified"
    re.compile(r"\b" + _NEG + r"\b(?:[\s,]+[\w'’./-]+){0,4}?[\s,]+" + _VERB + r"\b", re.I),
    re.compile(r"\b" + _NEG + r"\s+" + _VERB + r"\b", re.I),
    re.compile(r"\bthere(?:\s+is|\s+are|'s|’s)\s+no\b", re.I),
    re.compile(r"\bthere\s+(?:isn'?t|aren'?t|is\s+not|are\s+not)\b", re.I),
    re.compile(r"\bnone\s+of\s+the\s+(?:sheets|drawings|plans|notes|details|specs)\b", re.I),
    re.compile(r"\bno\s+(?:sheet|drawing|plan|note|detail|mention|callout|reference|spec)s?\b",
               re.I),
    re.compile(r"\bno\s+hay\b", re.I),
    re.compile(r"\bningun[oa]?\s+de\s+l[oa]s\s+(?:hojas|planos|notas)\b", re.I),
]
# The bot about itself: "I didn't search", "I couldn't find that in the drawings".
_SELF = re.compile(r"^\s*(?:i|we)(?:'ve|’ve|'m|’m)?\s+(?:have\s+)?(?:did\s*n[o']?t|didn’t|"
                   r"could\s*n[o']?t|couldn’t|can\s*n[o']?t|can’t|cannot|have\s*n[o']?t|"
                   r"haven’t|was\s*n[o']?t|wasn’t)\s+(?:yet\s+)?"
                   r"(?:search|look|check|find|found|open|read|get|see\s+the\s+sheet)", re.I)
_DRAWING_WORD = re.compile(r"\b(?:drawings?|sheets?|plans?|specs?|specifications?|details?|"
                           r"sections?|schedules?|elevations?|notes?|planos?|hojas?)\b", re.I)
SHEET_RE = re.compile(r"\b[A-Z]{1,4}-?\d{1,4}(?:\.\d{1,3})?[A-Z]?\b")
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|«[^»]*»")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")


def _sentences(line: str) -> List[str]:
    return [s for s in _SENT_SPLIT.split(line) if s.strip()]


_ADVICE = re.compile(r"\b(?:there(?:'s|’s|\s+is)\s+)?no\s+need\s+to\b", re.I)


def _hits(s: str) -> List[re.Match]:
    s = _ADVICE.sub(" ", s)                       # "no need to worry" is advice
    return [m for p in _ABSENCE for m in p.finditer(s)]


def _quotes_a_note(s: str) -> bool:
    """The negative is the SHEET's words, not the model's: inside quotes, or
    printed in capitals ("NOT REQUIRED"), next to a sheet number."""
    if not SHEET_RE.search(s):
        return False
    if not _hits(_QUOTED.sub(" ", s)):
        return True
    return all(m.group(0) == m.group(0).upper() for m in _hits(s))


def is_absence_claim(sentence: str, plans: bool = True) -> bool:
    """One sentence asserts that the drawings/job lack something. `plans`:
    a plan tool ran this turn (else only a sentence that names the drawings
    counts -- "No one checked in" is not about them)."""
    s = (sentence or "").strip()
    if not s or s.endswith("?") or s.endswith("？") or s.startswith("¿"):
        return False
    if s.lower().startswith(NOT_FOUND_PREFIX.lower()) or s.startswith("Closest detail:"):
        return False
    if _SELF.search(s) or re.match(r"^\s*not\s+sure\b", s, re.I):
        return False
    if not _hits(s):
        return False
    if _quotes_a_note(s):
        return False
    if not plans and not (_DRAWING_WORD.search(s) or SHEET_RE.search(s)):
        return False
    return True


def detect(text: str, plans: bool = True) -> List[str]:
    """Every absence-assertion sentence in `text`, in order."""
    return [s.strip() for line in str(text or "").split("\n") for s in _sentences(line)
            if is_absence_claim(s, plans)]


def quotes_a_sheet(sentence: str) -> bool:
    """For the probe: a flagged sentence that carries a sheet number (a
    false-positive candidate -- it may be quoting a sheet's note)."""
    return bool(SHEET_RE.search(sentence or ""))


# ── WHAT THIS TURN SEARCHED ──────────────────────────────────────────────
_CITE = re.compile(r"^-\s+(.+?)\s+\[([^\]]+)\]", re.M)
_SEARCHED_TOO = re.compile(r"searched too \(([^)]*)\)")
_NOT_FOUND_IN = re.compile(r"Not found in the sheets searched:\s*([^'\n]*?)\.?(?:'|\n|$)")
_SENT = re.compile(r"(?:Sent the image of|Would send the image of|Found)\s+([A-Z]{1,4}-?\d[\w.]*)")


def _sheet_of(where: str) -> str:
    return re.sub(r"\s*\(\+\d+ sheets?\)\s*$", "", str(where or "")).strip()


def plan_calls(trace: Optional[Iterable[dict]]) -> List[dict]:
    return [t for t in trace or [] if isinstance(t, dict) and t.get("tool") in PLAN_TOOLS
            and not t.get("error")]


def evidence(trace: Optional[Iterable[dict]]) -> Tuple[List[str], Optional[Tuple[str, str]]]:
    """(the sheets this turn's plan tools returned or searched, in order;
    the top record as (sheet, quote) or None). Only what the tool results
    say -- never a sheet from anywhere else."""
    sheets: List[str] = []
    top: Optional[Tuple[str, str]] = None

    def add(s: str) -> None:
        s = (s or "").strip().rstrip(".")
        if s and s not in sheets:
            sheets.append(s)
    for t in plan_calls(trace):
        for r in t.get("records") or []:
            sheet = str(r.get("sheet") or r.get("sheet_number") or "").strip()
            if not sheet:
                continue
            add(sheet)
            quote = re.sub(r"\s+", " ", str(r.get("quote") or "")).strip()
            if top is None and quote:
                top = (sheet, quote[:QUOTE_CHARS])
        result = str(t.get("result") or "")
        for quote, where in _CITE.findall(result):
            sheet = _sheet_of(where)
            add(sheet)
            if top is None and quote.strip():
                top = (sheet, re.sub(r"\s+", " ", quote).strip()[:QUOTE_CHARS])
        for m in _SEARCHED_TOO.finditer(result):
            for s in m.group(1).split(","):
                add(s)
        for m in _NOT_FOUND_IN.finditer(result):
            for s in m.group(1).split(","):
                add(s)
        for m in _SENT.finditer(result):
            add(m.group(1))
    return sheets, top


def not_found_line(sheets: List[str]) -> str:
    return f"{NOT_FOUND_PREFIX}: {', '.join(sheets)}." if sheets else f"{NOT_FOUND_PREFIX}."


def rewrite(text: Any, trace: Optional[Iterable[dict]] = None) -> Tuple[str, int]:
    """(the answer with each absence assertion replaced, how many were). The
    first becomes the not-found line, the rest are dropped (one line says
    it); the closest detail found goes after the answer, once."""
    text = str(text or "")
    plans = bool(plan_calls(trace))
    if not text.strip():
        return text, 0
    sheets, top = evidence(trace) if plans else ([], None)
    line_for = not_found_line(sheets) if plans else NOT_SEARCHED_TEXT
    n, said, out_lines = 0, False, []
    for line in text.split("\n"):
        parts = _sentences(line)
        if not parts:
            out_lines.append(line)
            continue
        kept = []
        for s in parts:
            if is_absence_claim(s, plans):
                n += 1
                if not said:
                    kept.append(line_for)
                    said = True
            else:
                kept.append(s)
        if kept:
            out_lines.append(" ".join(kept))
    if not n:
        return text, 0
    out = "\n".join(out_lines).strip()
    if plans and top and "Closest detail:" not in out:
        out += f'\nClosest detail: {top[0]} — "{top[1]}"'
    return out, n
