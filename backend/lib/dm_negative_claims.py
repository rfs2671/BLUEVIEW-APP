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
# What a sentence is about when it is NOT the drawings: people on site,
# permits, deliveries. In a turn that also searched the plans, a negative
# about these ("There are no workers on site today") is left alone.
_OTHER_SUBJECT = re.compile(
    r"\b(?:no\s+one|nobody|anyone|any\s+one|workers?|crews?|guys|men|people|employees?|"
    r"on\s+site|checked\s+in|check(?:ed)?[\s-]?ins?|showed\s+up|head\s?count|deliver(?:y|ies)|"
    r"inspect(?:ion|ions|or|ors)|permits?|violations?|hearings?|DOB|DOT|nadie|trabajadores)\b",
    re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|«[^»]*»")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")
# A period after one of these is an abbreviation, not the end of a sentence.
# STRONG: never a sentence end ("approx. 10 ft", "Dr. Lee", "e.g. A-104").
# WEAK: a unit/word that may also end a sentence ("... is 10 in. See A-300."):
# no split only when the next word is not capitalised.
_ABBR_STRONG = frozenset({"approx", "dr", "mr", "mrs", "ms", "vs", "fig", "sq", "typ", "dia",
                          "ref", "dwg", "dwgs", "e.g", "i.e", "nos", "est", "incl", "no"})
_ABBR_WEAK = frozenset({"in", "ft", "sf", "min", "max", "ca", "etc", "ave", "st", "sec"})


def _is_abbreviation_end(line: str, start: int, end: int) -> bool:
    """The period at line[start:end] closes an abbreviation, not a sentence."""
    if line[start] != ".":
        return False
    m = re.search(r"([A-Za-z](?:[A-Za-z.]*[A-Za-z])?)$", line[:start])
    if not m:
        return False
    word = m.group(1).lower()
    if m.start() > 0 and line[m.start() - 1] in "-/" + "0123456789":
        return False                                  # part of a sheet id / number
    nxt = line[end:end + 1]
    if word == "no":
        return nxt.isdigit()                          # "No. 5" -- not "I said no. Then"
    if word in _ABBR_STRONG:
        return True
    return word in _ABBR_WEAK and not nxt.isupper()


def _sentences(line: str) -> List[str]:
    out, last = [], 0
    for m in re.finditer(r"[.!?]+(?=\s)\s+(?=\S)", line):
        if _is_abbreviation_end(line, m.start(), m.end()):
            continue
        out.append(line[last:m.end()])
        last = m.end()
    out.append(line[last:])
    return [s.strip() for s in out if s.strip()]


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
    # Typographic apostrophes match as straight ones ("don’t" = "don't").
    s = (sentence or "").strip().replace("\u2019", "'").replace("\u2018", "'")
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
    about_drawings = bool(_DRAWING_WORD.search(s) or SHEET_RE.search(s))
    if not plans and not about_drawings:
        return False
    if plans and not about_drawings and _OTHER_SUBJECT.search(s):
        return False                              # attendance / permits, not the plans
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


_CLAUSE_MASK = "\x00"
# What a clause split must not look inside: a "..." quote (a straight " opens
# one only when it is NOT a feet-inch mark, i.e. not after a digit, ' or -),
# a curly quote, or a parenthesis.
_CLAUSE_OPAQUE = re.compile(r"(?<![\d'\-])\"[^\"]*\"|“[^”]*”|«[^»]*»|\([^()]*\)")
_MEASURE = re.compile(      # ANY number+unit: used only to reject a lookalike inside a subject
    r"\d\s*(?:['\"]|ft\b|feet\b|foot\b|in\b|inch(?:es)?\b|mm\b|cm\b|m\b|sf\b|"
    r"sq\.?\s*ft\b|psf\b|%|°|hrs?\b|hours?\b)", re.I)
# STRICT WHITELIST (Roy, 11-03): a kept clause must be exactly
#     <subject> [is|are|=|:|of|at] <VALUE> [dimension word] [(sheet cite)]
# with VALUE one of a closed set, and the subject naming a measure (height,
# slab, floor-to-floor, ...) OR the clause citing a sheet. Anything else
# ("unit 5 in kitchens", "5 m or more", "typical is 10 ft (from my
# experience)", word numbers, no-unit clauses) is not a value: the whole
# sentence is replaced, as before.
_PRIMES = str.maketrans({"′": "'", "’": "'", "″": '"', "”": '"',
                         "“": '"', "‘": "'"})
_FRAC = r"(?:\s+\d+/\d+|-\d+/\d+)"
_VALUE = re.compile(
    r"(?:\d+(?:\.\d+)?'\s*-?\s*\d*" + _FRAC + r"?(?:\.\d+)?\s*\"?"      # 10'-0"  3'-6 1/2"  10'
    r"|\d+(?:\.\d+)?" + _FRAC + r"?\s*\""                                # 8" 5 1/2"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:ft|feet|foot|inch(?:es)?|in|m)\b\.?"      # 10 ft  8 in  3 m
    r"|\d[\d,]*(?:\.\d+)?\s*(?:sf|sq\.?\s*ft|gpm|cfm|psf|psi|mm|cm|btuh?|kw|mbh|tons?|hrs?|hours?)\b\.?"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:%|°\s*[FC]?))", re.I)
_DIMWORD = r"(?:deep|high|wide|thick|long|tall|clear|minimum|maximum|min|max|rated|rating|o\.?c\.?|apart|diameter|dia)"
_SHEET_ID = SHEET_RE.pattern.replace(r"\b", "")
_SHEET_CITE = re.compile(r"\(\s*(?:see\s+)?" + _SHEET_ID + r"(?:\s*(?:,|&|/|and)\s*" + _SHEET_ID + r")*\s*\)")
_MEASURE_NOUN = re.compile(
    r"height|floor|ceiling|slab|plenum|depth|width|thickness|clearance|length|diameter|"
    r"span|spacing|elevation|dimension|size|riser|tread|parapet|setback|opening|wall|door|"
    r"roof|beam|joist|column|duct|pipe|area|capacity|flow|load|slope|grade|level|story|"
    r"storey|headroom", re.I)
_CLAUSE_SHAPE = re.compile(
    r"^(?P<pre>[A-Za-z][\w'/. ,-]{0,60}?)\s*(?:\b(?:is|are|=|of|at)\b|:)?\s*"
    r"(?P<val>" + _VALUE.pattern + r")"
    r"(?:\s+" + _DIMWORD + r")?"
    r"(?P<cite>\s*" + _SHEET_CITE.pattern + r")?\s*\.?$", re.I)


def _whitelisted_value(clause: str) -> bool:
    c = clause.translate(_PRIMES).strip()
    m = _CLAUSE_SHAPE.match(c)
    if not m:
        return False
    pre = m.group("pre")
    if _MEASURE.search(re.sub(_SHEET_ID, " ", pre)):
        return False                                  # a second value / lookalike in the subject
    return (bool(m.group("cite")) or bool(_MEASURE_NOUN.search(pre))
            or bool(re.search(_SHEET_ID, pre, re.I)))      # "A-300 shows 10 ft"


_CONJUNCTION = re.compile(r"^\W*(?:but|and|or|so|yet|however|while|whereas|although|though|"
                          r"also|then|plus|nor|except|otherwise)\b", re.I)
_ABSENCE_TOKEN = re.compile(
    r"\b(?:no|none|not|nothing|never|nor|neither|without|missing|absent|unspecified|unknown|"
    r"tbd|lacks?|lacking|omitted)\b|n/a|n['’]t\b", re.I)


def _clauses(sentence: str) -> List[str]:
    """The sentence split at ; , : (followed by a space) outside quotes and
    parentheses. "1,000 SF" has no space after the comma: not split."""
    hidden: List[str] = []

    def mask(m: re.Match) -> str:
        hidden.append(m.group(0))
        return _CLAUSE_MASK
    masked = _CLAUSE_OPAQUE.sub(mask, sentence)
    parts = [c.strip() for c in re.split(r"[;,:]\s+", masked) if c.strip()]
    it = iter(hidden)
    return [re.sub(_CLAUSE_MASK, lambda _m: next(it), c) for c in parts]


def _clean_measured(c: str) -> bool:
    """POSITIVELY a whitelisted measured-value statement (see _CLAUSE_SHAPE):
    no leading conjunction, no absence word, balanced parentheses."""
    if c.count("(") != c.count(")"):
        return False
    if _CONJUNCTION.search(c) or _ABSENCE_TOKEN.search(c) or _hits(c):
        return False
    return _whitelisted_value(c)


def _raise_first(c: str) -> str:
    """Capital for a plain leading word only; never a sheet id or a unit."""
    m = re.match(r"[a-z]{3,}(?:-[a-z]+)*\b", c)
    if m and not SHEET_RE.match(c.upper()) and not re.match(r"[a-z]+\s*\d", c):
        return c[:1].upper() + c[1:]
    return c


def measured_clauses(sentence: str) -> List[str]:
    """The clauses of an absence sentence that state a value and make no
    absence claim of their own: "Ceiling height not shown; floor-to-floor
    10'-0\" (A-300.00)" -> ["Floor-to-floor 10'-0\" (A-300.00)"].

    FAILS TOWARD THE OLD BEHAVIOUR: the sentence is split only when EVERY
    clause is either an absence clause (dropped) or positively a clean
    measured-value statement (kept as written; only a plain leading word is
    capitalised). If any clause is neither -- a sheet reference alone, a
    conjunction-led fragment, "none on floor 3", a clause with no unit --
    the result is [] and the whole sentence is replaced, as before.
    Numbers inside the ABSENCE clauses are still dropped, as before."""
    if sentence.count("(") != sentence.count(")"):
        return []
    parts = _clauses(sentence)
    if len(parts) < 2:
        return []
    keep: List[str] = []
    dropped = 0
    for c in parts:
        if _hits(c):
            dropped += 1
        elif _clean_measured(c):
            keep.append(c)
        else:
            return []
    if not dropped:
        return []
    return [_raise_first(c) for c in keep]


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
                # A clause that states a measured value stays, on a line of
                # its own: only the absence clause is the gate's to replace.
                for c in measured_clauses(s):
                    kept.append("\n" + c)
            else:
                kept.append(s)
        if kept:
            out_lines.extend(re.sub(r" *\n *", "\n", " ".join(kept)).split("\n"))
    if not n:
        return text, 0
    out = "\n".join(out_lines).strip()
    if plans and top and "Closest detail:" not in out:
        out += f'\nClosest detail: {top[0]} — "{top[1]}"'
    return out, n
