"""The one-line per-subcontractor summary for the INVESTOR report.

THE CHECK WAS BUILT FIRST, and it still governs. `verify_sentence` landed
before any model call existed, because it is the only thing that makes
auto-approve safe: the line sends itself at the admin's daily send time whether
or not a human looked at it. A check that can be talked past is worse than no
feature at all.

THE GENERATOR IS BELOW IT, and is subordinate to it. Every sentence the model
produces goes through `verify_sentence` before it can reach a page, and a
sentence that fails is NOT retried and NOT repaired — `plain_facts` renders
instead. There is no path from the model to the report that skips the check;
`summary_line` is the only public entry point and it always verifies.

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

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

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


# ── The model call ───────────────────────────────────────────────────────────
#
# Mirrors lib/ai/phase_inference.py deliberately: same SDK, same client
# construction, same structured-output config, same temperature=0, same
# swallow-and-return-None failure posture. A second AI surface that fails in a
# second way is a second thing to learn at 6am.

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

# One string, nothing else. There is no `reasoning` field on purpose: this runs
# once per activity row per report, and a field nothing reads is tokens spent
# on every row of every day.
SENTENCE_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentence": {"type": "string"},
    },
    "required": ["sentence"],
}

# THE PROMPT STATES THE TWO RULES, and the verifier enforces them anyway.
#
# This is not redundancy for its own sake. Asking for a compliant sentence is
# how we get a USABLE one most of the time; the check is how we are safe the
# rest of the time. If the prompt were the only guard the feature would be a
# hope, and if the check were the only guard almost every line would refuse to
# the fallback and the page would read like a spreadsheet.
_PROMPT_TEMPLATE = """You are writing ONE sentence for a construction progress report read by an investor or a bank.

The facts below are the COMPLETE record of what the site supervisor logged for this crew today. There is nothing else. You were not there.

Company: {company}
Trade: {trade}
Workers on site (counted at the gate): {worker_count}
Activities the supervisor tapped: {activities}
Locations the supervisor tapped: {locations}
Photographs taken: {photo_count}

Write one sentence, at most 20 words, describing what this crew did today.

TWO ABSOLUTE RULES:

1. NO NEW NOUNS. Every activity, location, material, quantity or thing you name must appear in the facts above. Do not infer what the work was "for" or what comes next. If the supervisor tapped "rebar" and "formwork", you may write about rebar and formwork; you may NOT write about a pour, a slab, a deck, or a schedule, because nobody recorded those.

2. NO COMPLETION CLAIMS. Never say or imply that anything is complete, finished, done, wrapped up, ready, installed, poured, delivered, or closed out. Progress language only: "continuing", "underway", "in progress", "ongoing". Whether work finished is not something a tap can tell you, and stating it to a lender is a false statement.

You may use ordinary grammar words, and the words: crew, crews, worker, workers, work, working, today, day, continuing, ongoing, underway, progress.

Return JSON: {{"sentence": <the sentence>}}
"""


def _prompt_for(payload: Dict[str, object]) -> str:
    """Render the prompt from the closed input set — and NOTHING else.

    Empty fields are named as such rather than omitted. A prompt with a missing
    line invites the model to fill the gap; a prompt that says "none recorded"
    tells it there is nothing there to reach for.
    """
    def _listing(key: str) -> str:
        items = [str(x).strip() for x in (payload.get(key) or [])  # type: ignore[union-attr]
                 if str(x).strip()]
        return ", ".join(items) if items else "(none recorded)"

    def _scalar(key: str) -> str:
        value = payload.get(key)
        text = str(value).strip() if value is not None else ""
        return text or "(not recorded)"

    return _PROMPT_TEMPLATE.format(
        company=_scalar("company"),
        trade=_scalar("trade"),
        worker_count=_scalar("worker_count"),
        activities=_listing("activities"),
        locations=_listing("locations"),
        photo_count=_scalar("photo_count"),
    )


def generate_sentence(payload: Dict[str, object]) -> Optional[str]:
    """One Gemini call for one activity row. The VERIFIED sentence, or None.

    Returns None — never a partial, never an unchecked string — if:
      • GEMINI_API_KEY is unset
      • the call raises, or the response will not parse
      • the sentence fails verify_sentence

    NO RETRY ON A FAILED CHECK. A refusal means the model reached for something
    nobody tapped, and asking a temperature-0 model the same question again is
    both the same question and a second charge. The caller falls back to
    plain_facts, which is what a reader would have got anyway.
    """
    if not GEMINI_API_KEY:
        # SAID OUT LOUD, once per row. Without this the no-key path was the
        # only one of the three outcomes that left NO trace: a failure logs at
        # ERROR and a refusal at INFO, but a missing key returned None in
        # silence — so a report full of plain facts looked identical whether
        # the model was never called, had failed, or had been correctly
        # refused. That is exactly the question the operator had to ask about
        # a live report, and it should have been answerable from the logs.
        logger.warning(
            "Sub-summary SKIPPED for %r: GEMINI_API_KEY is not set, so no "
            "sentence was generated and the plain facts were rendered.",
            payload.get("company"),
        )
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_prompt_for(payload),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SENTENCE_RESPONSE_SCHEMA,
                temperature=0,
            ),
        )
        sentence = str(json.loads(response.text).get("sentence") or "").strip()
    except Exception as e:  # noqa: BLE001 — per-row tolerance, as phase_inference
        logger.error(
            "Sub-summary generation failed for %r: %r",
            payload.get("company"), e,
        )
        return None

    # THE GATE. Nothing returns from this function unverified.
    ok, reason, offending = verify_sentence(sentence, payload)
    if not ok:
        logger.info(
            "Sub-summary refused for %r: %s %r",
            payload.get("company"), reason, offending,
        )
        return None
    return sentence


# WHY THERE IS NO summary_line() WRAPPER HERE.
#
# The obvious convenience — `generate_sentence(p) or plain_facts(p)` — is wrong
# for the one caller that exists. The progress report prints the company itself,
# in bold, as the anchor of "one line per subcontractor", and plain_facts opens
# with the company too; folding them together yields "Kestrel Electric — Kestrel
# Electric (Electrical) — 4 workers...". So the report owns its own fallback,
# which is the line it already rendered before this generator existed.
#
# plain_facts stays as this module's self-contained answer for a caller that
# prints nothing of its own. It is not the report's answer.
