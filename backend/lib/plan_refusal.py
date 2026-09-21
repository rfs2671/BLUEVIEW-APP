"""A refusal is checked against the sheet before it is sent.

── THE WARRANT FOR AN ABSENCE ─────────────────────────────────────────────

A number needs a record about its subject: `answer_is_grounded` enforces that
and refuses an answer whose figures no record prints. A REFUSAL passed
nothing. It was the only output in this system with no evidence behind it,
and it was produced whenever retrieval came back empty — which happens for
reasons that have nothing to do with the drawings.

    An absence needs evidence that THE PLACE IT WOULD BE WAS LOOKED AT.

That is what this is. Before a refusal is sent, the top candidate sheet is
rendered and a model is asked one bounded question: does this sheet STATE the
thing? It may confirm or contradict. It may never supply the value.

── WHY THIS IS NOT THE VISION PATH THAT WAS REMOVED ───────────────────────

`41 PTAC units` came from a model summing off a picture. That path is still
closed. The asymmetry here is what makes it safe:

    vision says YES, wrongly -> "it's on A-101.00, I couldn't read it".
                                A superintendent opens the sheet, finds
                                nothing, and has lost two minutes.
    vision says NO,  wrongly -> the refusal ships exactly as it does today.
                                No worse than the current behaviour.

Neither failure puts a fabricated number in front of anyone.

── MEASURED BEFORE BUILDING, on the 27 refusals of the 40-question split ──

24 had a candidate sheet. Vision said the content WAS there for 6 of them —
false refusals being shipped — and confirmed absence for 18. Cost: 2,626
input tokens and 6 output tokens per refusal, one image and one line back.

THE 18 IS AN UPPER BOUND ON WARRANTED REFUSALS. Only two of them were checked
by rendering the sheet and reading it, and one of those two looked wrong
until a phrasing probe showed it was not. One verified case in a sample of
two is not an error rate, and quoting it as one would be the same proxy
mistake this file exists to avoid.

── RESOLUTION AND TARGETING ARE NOT THE LIMIT. PHRASING IS. ───────────────

Measured: all seven re-checked verdicts were identical at 2000px and 3000px,
and cropping to the title block changed nothing. But on ONE sheet, ONE crop,
the same model answered NO to "when was the architectural set issued" and YES
to "the drawing date" and "when the drawing was issued".

So the check is sensitive to wording, and that decides whose words to use.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence, Tuple

#: Never more than a verdict and a short phrase. It averaged 6 output tokens
#: in measurement; this is the ceiling, not the target.
MAX_OUTPUT_TOKENS = 60

_PROMPT = (
    "You are checking a construction drawing.\n\n"
    "QUESTION: does this sheet STATE {subject}?\n\n"
    "Answer with exactly one line:\n"
    "  YES | <where on the sheet>\n"
    "  NO\n\n"
    "Rules: do NOT write the value. Do not explain. If the sheet only "
    "REFERS to {subject} on another sheet, answer NO."
)


def check_prompt(user_words: str) -> str:
    """The bounded question, asked in THE USER'S OWN WORDS.

    NOT the retrieval subject. The subject is the model's paraphrase of the
    question, and it is the thing being checked for having missed something —
    asking the check in the same terms that already failed would inherit the
    failure. It also matters more than it looks: measured on one sheet and one
    crop, this model answers NO to "when was the architectural set issued" and
    YES to "the drawing date". The wording decides the verdict, so the wording
    must be the one the person actually used.
    """
    return _PROMPT.format(subject=(user_words or "").strip() or "this")


#: A location phrase carrying a digit is a VALUE escaping. Measured: asked not
#: to write the value, this model answered `YES | 2/27/2025`.
_HAS_DIGIT = re.compile(r"\d")


def parse_verdict(reply: str) -> Tuple[str, str]:
    """(verdict, location) — verdict is 'yes' | 'no' | 'unknown'.

    ── STRIPPING IS THE ENFORCEMENT ───────────────────────────────────────
    #
    # The prompt forbids writing the value and the model writes it anyway.
    # A prompt rule is an instruction; this is the enforcement, and the
    # distinction is the same one that moved "the drawings do not specify"
    # out of `_ABSENCE_RE` and into the gate: being told is not a guarantee.
    #
    # So the verdict is parsed, the location phrase is kept ONLY if it carries
    # no digit, and everything else is discarded. A location is a courtesy; a
    # value is a claim, and this call is not allowed to make one.
    """
    t = (reply or "").strip()
    if not t:
        return "unknown", ""
    head = t.splitlines()[0]
    up = head.upper().lstrip("*-• ")
    if up.startswith("YES"):
        loc = head.split("|", 1)[1].strip() if "|" in head else ""
        loc = re.sub(r"\s+", " ", loc).strip(" .;:")
        if _HAS_DIGIT.search(loc) or len(loc) > 60:
            loc = ""
        return "yes", loc
    if up.startswith("NO"):
        return "no", ""
    return "unknown", ""


def found_but_unreadable(sheet: str, location: str = "") -> str:
    """What to say when the sheet states it and we could not read it.

    More useful than "not found" — it points somewhere a person can open —
    and it still states nothing we cannot back. The sheet number comes from
    OUR record, not from the model; only the location phrase is the model's,
    and only when it carries no digits.
    """
    s = (sheet or "").strip()
    if not s:
        return ""
    where = f" ({location})" if location else ""
    return (f"It's on {s}{where} — I couldn't read it off the sheet. "
            f"Worth opening that one.")


def candidate_sheet(records: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The sheet to look at: the highest-ranked record's, which is the same
    ordering the answer would have been built from."""
    for r in records or []:
        s = str((r or {}).get("sheet_number") or "").strip()
        if s:
            return s
    return None


__all__ = ["MAX_OUTPUT_TOKENS", "check_prompt", "parse_verdict",
           "found_but_unreadable", "candidate_sheet"]
