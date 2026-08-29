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
# GRAMMAR: structure only. Nothing here names a thing, a place or a quantity,
# so none of it needs declaring to the model word by word -- "ordinary grammar
# words" covers it in the prompt.
_GRAMMAR = frozenset("""
a an and the of to at on in for with by from into onto over under near
is are was were be been being has have had
""".split())

# PERMITTED CONTENT: words that DO carry meaning and are allowed anyway,
# because each asserts that work HAPPENED without asserting what it produced or
# that it finished.
#
# THE PROMPT IS GENERATED FROM THIS SET (_PERMITTED_CONTENT_LINE below), and
# that is the load-bearing part of this change. The four verbs on the last line
# were added to the verifier to fix a real refusal -- a live payload produced
# "...worked on site clean-up and material delivery" and came back
# UNTRACED_TERM ['worked'] -- and the PROMPT WAS NEVER UPDATED. The model went
# on being told not to write the sentences the verifier had just learned to
# accept. Fourteen words were undeclared by the time this was noticed. Deriving
# the declaration removes the possibility rather than fixing the wording.
_PERMITTED_CONTENT = frozenset("""
crew crews worker workers man men
continuing continued continues ongoing underway progress progressing
work working works today day
worked performed performing carried out
""".split())

_CONNECTIVES = _GRAMMAR | _PERMITTED_CONTENT

# What the prompt tells the model it may use, in the prompt's own voice.
# Sorted so the string is stable across runs and reviewable in a diff.
_PERMITTED_CONTENT_LINE = ", ".join(sorted(_PERMITTED_CONTENT))

# WHY THOSE FIVE, and no more.
#
# The verifier was refusing on VERBS, not on nouns. `working` was allowed and
# `worked` was not — the past tense of a word already in the list — so a model
# writing the most natural sentence about tapped chips was refused for
# literalism rather than for reaching beyond the record. Executed against a
# real payload: "...worked on site clean-up and material delivery" came back
# UNTRACED_TERM ['worked'].
#
# INFLECTIONS AND ONE PARTICLE. Every addition asserts that work HAPPENED and
# none asserts that it FINISHED, which is the whole distinction this module
# defends. `out` is here only to let "carried out" through; it is a preposition
# and carries no claim on its own.
#

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

# NOTHING HERE MAY ASSERT COMPLETION. Enforced below rather than trusted: the
# two sets are checked disjoint at import, so a later addition like "finished"
# cannot quietly become a connective and walk past the completion gate.
_ASSERTED_ACTIVITY_VERBS = frozenset("worked performed performing carried out".split())
assert not (_ASSERTED_ACTIVITY_VERBS & _COMPLETION_TERMS), (
    "a connective may never be a completion term"
)

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
    activities the CP tapped, and the locations he tapped.

    NO NUMBERS, and that is a narrowing rather than an oversight. This admitted
    str(worker_count) and str(photo_count), which was a hole rather than a
    convenience: the check is TOKEN MEMBERSHIP, so it can say a number appears
    somewhere in the payload but NOT that it is being used to state the fact it
    came from. On a payload with worker_count 6 and photo_count 4,

        "4 workers continuing formwork and rebar on the 3rd floor"

    PASSED -- a verified sentence carrying the wrong headcount to a lender. The
    two counts were interchangeable and the verifier could not tell.

    Both are gone from here and from the prompt, and the model is told to state
    no quantities at all. The question of whether to also allow number-WORDS
    ("six" alongside "6") disappears with them; allowing spellings would have
    doubled this surface rather than closing it.

    Nothing is lost from the report: the crew table prints the headcount in its
    own column, from the record rather than from a sentence. If a count ever
    has to appear IN the sentence, the answer is not vocabulary -- it is
    template insertion, and there is a followups entry saying so.
    """
    words: List[str] = []
    for key in ("company", "trade"):
        words += _tokens(str(payload.get(key) or ""))
    for act in (payload.get("activities") or []):      # type: ignore[union-attr]
        words += _tokens(str(act))
    for loc in (payload.get("locations") or []):       # type: ignore[union-attr]
        words += _tokens(str(loc))
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
        # THE FALLBACK MAY STATE THE COUNT because the fallback is not model
        # output. This line is written by code, from the payload, and cannot be
        # transposed with another number -- which is exactly the guarantee the
        # closed vocabulary could not give the model and the reason numbers
        # were removed from it. It is the template-insertion shape, already
        # working, on the one line that needed it.
        #
        # "workers", not "on site": `site` is still not in the vocabulary, and
        # the prompt no longer suggests it either.
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
# gemini-3.5-flash-lite. gemini-2.5-flash-lite was RETIRED under this key and
# every call returned 404 NOT_FOUND: "no longer available to new users. Please
# update your code to use models/gemini-3.5-flash-lite". The env var is unset in
# production (checked 2026-08-28), so this default IS the live value -- there is
# no override to change and nothing else to update.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

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

The facts below are the COMPLETE record for this crew today. There is nothing else. You were not there.

Company: {company}
Trade: {trade}
Activities recorded: {activities}
Locations recorded: {locations}

Write one sentence, at most 20 words, describing what this crew did today.

THREE ABSOLUTE RULES:

1. NO NEW NOUNS. Every activity, location, material, quantity or thing you name must appear in the facts above. Do not infer what the work was "for" or what comes next. If the facts name "rebar" and "formwork", you may write about rebar and formwork; you may NOT write about a pour, a slab, a deck, or a schedule, because nobody recorded those.

2. NO COMPLETION CLAIMS. Never say or imply that anything is complete, finished, done, wrapped up, ready, installed, poured, delivered, or closed out. Progress language only: "continuing", "underway", "in progress", "ongoing". Whether work finished is not something a tap can tell you, and stating it to a lender is a false statement.

3. NO QUANTITIES. Do not state any number, in digits or in words -- not a headcount, not a count of anything. The report prints the crew size in its own column, from the record. A number in this sentence cannot be traced to the fact it came from, so there are none.

You may use ordinary grammar words, and these words: {permitted}.

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
        activities=_listing("activities"),
        locations=_listing("locations"),
        # DERIVED, never typed. The prompt and the verifier now say the same
        # thing because only one of them is written down.
        permitted=_PERMITTED_CONTENT_LINE,
    )


def _error_trace(e: Exception) -> str:
    """The exception CLASS, the HTTP status and the status NAME. Nothing else.

    WHY NOT THE MESSAGE, still. google-genai builds
    `str(e)` as "404 NOT_FOUND. {response_json}", and that trailing dict is the
    server's own body — it can carry a request id, a URL or a fragment of what
    was sent. This string is RENDERED, so the message stays out. That refusal
    was right and is unchanged.

    WHY THE STATUS IS DIFFERENT, and why withholding it cost a day. `.code` is
    an int off the HTTP response and `.status` is a fixed enum token
    (NOT_FOUND, PERMISSION_DENIED, RESOURCE_EXHAUSTED). Neither can carry an
    identifier. "failed: ClientError" is true of a retired model, a revoked
    key, a malformed request and an exhausted quota alike, and the operator
    cannot reach the logs that separate them — which is the whole reason this
    trace exists. It said the least useful true thing.

    THE STATUS IS SHAPE-CHECKED rather than trusted: it is derived from the
    response body, so a server returning prose there must not be able to put
    prose on this page. Anything that is not an A-Z_ token is dropped.
    """
    parts = [type(e).__name__]
    code = getattr(e, "code", None)
    if isinstance(code, int):
        parts.append(str(code))
    status = getattr(e, "status", None)
    if isinstance(status, str) and re.fullmatch(r"[A-Z_]{1,40}", status):
        parts.append(status)
    return " ".join(parts)


def generate_sentence_traced(
    payload: Dict[str, object],
) -> Tuple[Optional[str], str]:
    """The verified sentence AND which of the four outcomes produced it.

    WHY THIS EXISTS. All four branches returned None and differed only in what
    they LOGGED, so from outside the process they were indistinguishable — and
    the operator cannot reach Railway's runtime logs. A diagnosis has now been
    blocked on unreadable logs twice, which is a design problem, not an
    operations one: a decision the report makes on every row should be legible
    from the report.

    The outcome is a SHORT MACHINE STRING, never prose and never the key:

        "generated"
        "skipped: no key"
        "failed: <ExceptionClass> <code> <STATUS>"   e.g. failed: ClientError 404 NOT_FOUND
        "refused: UNTRACED_TERM worked"

    generate_sentence() below is the same code with the outcome dropped, so
    there is one implementation and callers that do not want the trace are
    unchanged.
    """
    if not GEMINI_API_KEY:
        logger.warning(
            "Sub-summary SKIPPED for %r: GEMINI_API_KEY is not set, so no "
            "sentence was attempted and the plain facts render instead.",
            payload.get("company"),
        )
        return None, "skipped: no key"

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
        # The class, the status code and the status NAME — see _error_trace
        # for what is deliberately still withheld and why.
        return None, f"failed: {_error_trace(e)}"

    # THE GATE. Nothing returns from this function unverified.
    ok, reason, offending = verify_sentence(sentence, payload)
    if not ok:
        logger.info(
            "Sub-summary refused for %r: %s %r",
            payload.get("company"), reason, offending,
        )
        # The offending terms are the CP's own vocabulary or the model's, never
        # anything secret, and they are the whole point: "refused" alone tells
        # nobody what to change.
        _terms = " ".join(offending[:4])
        return None, f"refused: {reason}{(' ' + _terms) if _terms else ''}"
    return sentence, "generated"


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

    A THIN WRAPPER, deliberately. generate_sentence_traced above is the one
    implementation; this drops the outcome for callers that only want the
    sentence, so the two can never disagree about what happened.
    """
    return generate_sentence_traced(payload)[0]
