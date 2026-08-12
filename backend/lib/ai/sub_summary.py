"""The one-line per-subcontractor summary for the INVESTOR report — verifier.

THIS FILE CONTAINS NO MODEL CALL. The post-generation check is built and proved
first, because it is the only thing that makes auto-approve safe: the line
sends itself at the admin's daily send time whether or not a human looked at
it. A check that can be talked past is worse than no feature at all.

WHERE THIS MAY AND MAY NOT GO. The investor report only. It is NEVER written
into a logbook — page 2 is the legal record and the CP signs it. Nothing here
writes to db.logbooks and nothing here is imported by a logbook path.

THE TWO HARD RULES, as ruled:

  NO NEW NOUNS. Every activity or location word in the sentence must trace to
  something the CP tapped. If he tapped rebar and formwork, "rebar and formwork
  continuing at the back section" is fine. "Preparing for the pour" is not —
  nobody tapped a pour.

  NO COMPLETION CLAIMS, EVER. "Continuing", "underway", "in progress" are safe.
  "Complete", "finished", "wrapping up" are claims the app cannot verify, and
  they are exactly what the investor is asking and exactly what cannot be
  answered from a tap.

A sentence failing either rule does not send. The plain facts go instead —
never nothing.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ── The closed vocabulary a sentence may use beyond its own input ────────────
#
# Deliberately SMALL. Every word here is a word the model may introduce without
# tracing to a tap, so it is grammar and progress language only — never
# anything that could name work, a place, a material or a quantity.
_CONNECTIVES = frozenset("""
a an and the of to at on in for with by from into onto over under near
is are was were be been being has have had
crew crews worker workers man men
continuing continued continues ongoing underway progress progressing
work working works today day
""".split())

# ── Completion claims ────────────────────────────────────────────────────────
#
# Checked as whole words on the RAW sentence, before anything else, and as a
# deny-list rather than as "unknown nouns". Several of these could legitimately
# appear inside an activity label ("poured", "installed"), and the sentence is
# asserting an end state either way. The cost of a missed completion claim is a
# false statement to a lender, so this fails closed on the word itself.
_COMPLETION_TERMS = frozenset("""
complete completed completes completion
finish finished finishes finishing
done wrapping wrapped
final finalised finalized
closed closing
ready
topped topping
poured
installed
delivered
signoff
""".split())

_WORD = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> List[str]:
    """Lowercased word tokens. Punctuation and hyphens are separators, so
    "MEP rough-in" yields mep / rough / in and each is checked on its own."""
    return [t.lower() for t in _WORD.findall(text or "")]


def _singular(tok: str) -> str:
    """A crude depluraliser, and crude ON PURPOSE.

    The input is a fixed catalogue of activity and location labels, not free
    prose, so the only morphology that legitimately appears is a plural: the CP
    taps "column" and the sentence says "columns". Anything cleverer — a
    stemmer mapping "pouring" to "pour" — would let a COMPLETION claim in
    through the back door, which is the one thing this must not do.
    """
    if len(tok) > 3 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("es") and not tok.endswith("ses"):
        return tok[:-2]
    # >2, not >3: "branch rough-in" pluralises to "rough-ins", whose last token
    # is the three-letter "ins". Callers try the RAW token first, so short
    # connectives like "was" and "has" never reach this.
    if len(tok) > 2 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def allowed_vocabulary(payload: Dict[str, object]) -> frozenset:
    """Every token the sentence is permitted to contain.

    THE CLOSED INPUT SET and nothing else: the company, the trade, the
    activities the CP tapped, the locations he tapped, and the numbers already
    in the payload. Photo count is an input but contributes no noun — it is a
    number, not a thing on site.
    """
    words: List[str] = []
    for key in ("company", "trade"):
        words += _tokens(str(payload.get(key) or ""))
    for act in (payload.get("activities") or []):      # type: ignore[union-attr]
        words += _tokens(str(act))
    for loc in (payload.get("locations") or []):       # type: ignore[union-attr]
        words += _tokens(str(loc))
    for count_key in ("worker_count", "photo_count"):
        value = payload.get(count_key)
        if value is not None:
            words.append(str(value))
    return frozenset(_singular(w) for w in words) | _CONNECTIVES


def verify_sentence(
    sentence: str, payload: Dict[str, object],
) -> Tuple[bool, Optional[str], List[str]]:
    """Does this sentence trace entirely to what the CP tapped?

    Returns (ok, reason, offending_words). `reason` is a machine code, never
    prose — the caller decides what, if anything, a human ever reads.

    FAILS CLOSED. An empty sentence, a sentence of only connectives, or
    anything it cannot account for is a refusal.
    """
    text = (sentence or "").strip()
    raw = _tokens(text)
    if not raw:
        return False, "EMPTY", []

    # 1. COMPLETION CLAIMS, first and on the raw tokens.
    hits = sorted({t for t in raw if t in _COMPLETION_TERMS})
    if hits:
        return False, "COMPLETION_CLAIM", hits

    # 2. NO NEW NOUNS. Everything else must trace to the input.
    allowed = allowed_vocabulary(payload)
    # RAW FIRST, then the depluralised form. Raw-first is what keeps a short
    # connective ("was", "has") from being singularised into nonsense before
    # it has had the chance to match itself.
    unknown = sorted({
        t for t in raw if t not in allowed and _singular(t) not in allowed
    })
    if unknown:
        return False, "UNTRACED_TERM", unknown

    # 3. It must actually SAY something. A sentence of pure connectives traces
    #    perfectly and reports nothing.
    content = [t for t in raw
               if t not in _CONNECTIVES and _singular(t) not in _CONNECTIVES]
    if not content:
        return False, "NO_CONTENT", []

    return True, None, []


def plain_facts(payload: Dict[str, object]) -> str:
    """The fallback, used whenever the check refuses — never nothing.

    Deliberately dull and mechanical: only what is in the payload, in a fixed
    order, with no progress language at all. It is not trying to read well; it
    is trying to be unarguable.
    """
    company = str(payload.get("company") or "").strip() or "Subcontractor"
    trade = str(payload.get("trade") or "").strip()
    count = payload.get("worker_count")
    acts = [str(a).strip() for a in (payload.get("activities") or []) if str(a).strip()]
    locs = [str(x).strip() for x in (payload.get("locations") or []) if str(x).strip()]

    line = company
    if trade:
        line += f" ({trade})"
    if count is not None:
        # "workers", not "on site": `site` is not in the closed
        # vocabulary, and widening the allow-list to fit the fallback
        # would hand the model a free noun. The fallback bends instead.
        line += f" — {count} workers"
    if acts:
        line += ": " + ", ".join(acts)
    if locs:
        line += " at " + ", ".join(locs)
    return line
