"""Retrieval over typed records, and the gate every composed answer passes.

WHAT THIS REPLACES
==================

The keyword matcher. `question_kind` decided the shape of an answer AND
whether to look at all; `QUERY_SYNONYMS` mapped "ac" to "ptac" by hand;
`_one_edit_apart` forgave typos; the head-noun fallback retried with the last
word. Every one of those was a patch for "the letters did not line up", and
none of them generalises to the next drafter.

Here the agent says what it is looking for, this ranks records by the strength
of the evidence behind them, and the agent composes from what comes back.

TIER BEFORE SIMILARITY
======================

A schedule cell read from a detected grid outranks a note that merely mentions
the word, and both outrank anything a vision model read off the image. Within
a tier, how well the record matches decides. An answer never cites a lower
tier when a higher one exists for the same attribute on the same sheet — that
is `best_per_attribute`, and it is why "41 PTAC units" stops being quotable
while the schedule that shows them stays findable.

THE GATE
========

`answer_is_grounded` is not advice. Every number and every dimension in a
composed answer must appear in a record that was actually returned — in its
quote, in a scalar of its payload, or in its own identity, so a citation like
"A-105.01" is not mistaken for a claim. An answer that fails falls back to
`render_records`, which can only say what the records say.

A LABEL IS MATCHED AGAINST AND NEVER RENDERED
=============================================

Words a vision model supplied for a mark it could not read widen what the
search finds. `render_records` reads `quote`; it has never read `label`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib.plan_records import TIER_ORDER, tier_rank

# What a reader is entitled to see is a printed string. These are the fields a
# render may draw on; `label` is deliberately not among them.
RENDERABLE = ("quote",)

INTENTS = ("count", "attribute", "existence", "location", "identify", "geometry")

# Named now, routed later. A question about how things sit together — "does the
# duct clear the beam" — is the one shape a line of text cannot answer however
# well it matches, and it is the intended trigger for looking at the drawing
# rather than reading it. That routing is NOT built here; today geometry only
# orders the records, like every other intent.
GEOMETRY_INTENT = "geometry"

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9./&'\"-]*")
_STOP = frozenset({
    "the", "a", "an", "of", "on", "in", "at", "to", "for", "is", "are", "was",
    "were", "do", "does", "did", "it", "its", "this", "that", "and", "or", "be",
    "what", "which", "how", "many", "much", "there", "any", "me", "show", "tell",
    "please", "about", "them", "they", "we", "have", "has", "with", "from",
})


def search_terms(subject: str) -> List[str]:
    """The agent's subject, as words to match. No synonyms, no stemming, no
    typo tolerance: the agent has already decided what it is looking for, and
    a second guesser here is the thing being removed."""
    out: List[str] = []
    for w in _WORD.findall((subject or "").lower()):
        if w in _STOP or w in out:
            continue
        out.append(w)
    return out


def _haystacks(record: Dict[str, Any]) -> List[str]:
    """Everything a record may be MATCHED on — quote, label and subject terms.

    The label is here and nowhere in the render. That asymmetry is the point:
    it widens what is found without ever becoming what is said."""
    parts = [record.get("quote") or "", record.get("label") or ""]
    parts += [str(t) for t in (record.get("subject_terms") or [])]
    payload = record.get("payload")
    if isinstance(payload, dict):
        parts.append(str(payload.get("name") or ""))
    return [p.lower() for p in parts if p]


def match_score(record: Dict[str, Any], terms: Sequence[str]) -> float:
    """How much of what was asked for this record actually contains."""
    if not terms:
        return 0.0
    hay = " | ".join(_haystacks(record))
    if not hay:
        return 0.0
    hit = sum(1 for t in terms if t in hay)
    if not hit:
        return 0.0
    # A record whose own words are mostly the thing asked for beats one that
    # mentions it in passing, so a long note does not outrank a legend entry.
    density = min(1.0, sum(len(t) for t in terms if t in hay) / max(len(hay), 1) * 8)
    return hit / len(terms) + 0.25 * density


# Which record types answer which intent first. Advisory: this orders, it never
# filters, because a wrong guess about intent must cost ranking and not the
# answer — that was the 2026-09-16 regression.
_INTENT_PRIOR: Dict[str, Tuple[str, ...]] = {
    "count": ("schedule", "tag", "element"),
    "attribute": ("schedule", "note", "dimension", "legend_entry"),
    "existence": ("legend_entry", "tag", "element", "note", "text"),
    "location": ("callout", "element", "text"),
    "identify": ("legend_entry", "schedule", "element"),
    GEOMETRY_INTENT: ("callout", "text"),
}


def rank(records: Iterable[Dict[str, Any]], terms: Sequence[str],
         intent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tier first, then how well it matches, then the intent's preference."""
    prior = _INTENT_PRIOR.get(intent or "", ())

    def key(r: Dict[str, Any]):
        score = match_score(r, terms)
        rt = r.get("record_type")
        return (
            tier_rank(r.get("tier")),              # evidence, before anything
            -round(score, 4),                      # then what it actually says
            prior.index(rt) if rt in prior else len(prior),
            r.get("sheet_number") or "",
            r.get("ordinal") or 0,
        )

    return sorted([r for r in records if match_score(r, terms) > 0], key=key)


def _attribute_key(record: Dict[str, Any]) -> Tuple[str, str, str]:
    """What this record is ABOUT, for the purpose of not citing it twice."""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    subject = (record.get("subject_terms") or [""])[0]
    return (str(record.get("sheet_number") or ""),
            str(record.get("record_type") or ""),
            str(payload.get("tag") or payload.get("symbol") or subject or "").upper())


def best_per_attribute(ranked: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Never a lower tier when a higher one says the same thing on the same
    sheet. `ranked` must already be tier-ordered."""
    seen: Dict[Tuple[str, str, str], str] = {}
    out: List[Dict[str, Any]] = []
    for r in ranked:
        k = _attribute_key(r)
        if k in seen and tier_rank(r.get("tier")) > tier_rank(seen[k]):
            continue
        seen.setdefault(k, r.get("tier"))
        out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# The gate
# ══════════════════════════════════════════════════════════════════════════

# A value, not a name: the digits inside 'PTAC-1', 'M-200.00' or 'A-105.01'
# are an identifier, and a rule that treats them as claims fails every answer
# that cites its source. The letter before the hyphen is what separates them.
_VALUE_RE = re.compile(r"(?<![A-Za-z0-9.\-/])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])")

# A DIMENSION IS CHECKED AS ITS NUMBERS. 12'-6" is split to 12 and 6, and both
# must be supported. Comparing the whole token instead would fail an answer
# that writes 12' where the sheet prints 12'-0", which is a formatting
# difference and not a fabrication. The residue is that a transposition —
# 6'-12" against a sheet's 12'-6" — passes; closing that needs the units the
# next extraction pass adds, and it is noted rather than papered over.
_UNIT_RE = re.compile(r"['\"′″]")
# A separator before a digit is a separator — UNLESS a letter stands in front
# of it, which is what makes A-105.01 and PTAC-1 names rather than numbers.
_SPLIT_RE = re.compile(r"(?<![A-Za-z])[-/](?=\d)")


def _values(text: str) -> List[str]:
    flat = _SPLIT_RE.sub(" ", _UNIT_RE.sub(" ", text or ""))
    out = [m.group(0).replace(",", "").rstrip(".") for m in _VALUE_RE.finditer(flat)]
    return [v for v in out if v]


def _supported_values(records: Sequence[Dict[str, Any]]) -> set:
    """Every number a returned record can vouch for."""
    ok: set = set()
    for r in records or []:
        ok.update(_values(r.get("quote") or ""))
        # ── WHAT A CITATION MAY CONTAIN ────────────────────────────────────
        #
        # A sheet number, a job number and an issue date are how an answer says
        # where it came from, and a gate that reads them as claims fails every
        # well-cited answer. `page_number` is deliberately NOT here: it is a
        # bare small integer, and whitelisting it would let "9 units" through
        # on any page nine. An answer that cites only a page number and no
        # sheet falls back to the render, which prints the page itself.
        for field in ("sheet_number", "filing_id", "issued_date"):
            ok.update(_values(str(r.get(field) or "")))
        payload = r.get("payload")
        if isinstance(payload, dict):
            for v in payload.values():
                if isinstance(v, (str, int, float)):
                    ok.update(_values(str(v)))
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, (str, int, float)):
                            ok.update(_values(str(item)))
                        elif isinstance(item, list):
                            for cell in item:
                                ok.update(_values(str(cell)))
    return ok


def answer_is_grounded(text: str, records: Sequence[Dict[str, Any]]
                       ) -> Tuple[bool, List[str]]:
    """(ok, the numbers nothing returned can vouch for).

    A CHECK ON THE OUTPUT, not an instruction in a prompt. The model composes;
    this decides whether what it composed may be sent. A number with nothing
    behind it is the worst failure this product has — it looks verified."""
    said = _values(text)
    if not said:
        return True, []
    ok = _supported_values(records)
    unsupported = [v for v in said if v not in ok]
    return (not unsupported), unsupported


def contains_label(text: str, records: Sequence[Dict[str, Any]]) -> List[str]:
    """Vision-supplied words that reached the answer. Must always be empty.

    A label the sheet ALSO prints is not a leak — if some record's quote
    carries the phrase, the drawing said it and a reader may be told it. What
    this catches is the phrase that exists only because a model looked at a
    picture: PACKAGE TERMINAL AIR CONDITIONER and KICKER arrived together, and
    nothing in the text layer separates them."""
    low = (text or "").lower()
    printed = " | ".join((r.get("quote") or "").lower() for r in records or [])
    out = set()
    for r in records or []:
        lab = (r.get("label") or "").strip().lower()
        if len(lab) >= 4 and lab in low and lab not in printed:
            out.add(r["label"].strip())
    return sorted(out)


def matched_only_through_label(record: Dict[str, Any], terms: Sequence[str]) -> bool:
    """True when the ONLY thing tying this record to the subject is a label —
    words a vision model supplied for a mark the sheet does not explain."""
    return (match_score(record, terms) > 0
            and match_score(dict(record, label=None), terms) == 0)


def render_records(records: Sequence[Dict[str, Any]], subject: str = "",
                   limit: int = 4) -> str:
    """What the records say, and nothing else. The fallback when the gate
    refuses a composed answer, and the only renderer that exists.

    Reads `quote`. Has never read `label`.

    ── NOT READING THE LABEL WAS NOT ENOUGH ───────────────────────────────
    #
    # Measured by the eval, 2026-09-17. Asked 'what is a kicker', search
    # returned two legend entries on M-104.00 whose quotes are 'KE 1' and
    # 'KE 2', matched ONLY through the vision label 'KICKER EXHAUST 1'. This
    # printed no label, and replied:
    #
    #     Kicker — on the drawings:
    #     M-104.00 (legend_entry): KE 1 — read from the drawing image ...
    #
    # which states the invented meaning outright. The header names the
    # subject; the line under it supplies a mark; together they say the mark
    # IS the subject, and nothing on the sheet says so.
    #
    # So a record that matches the subject only through a label is not listed
    # under that subject at all. The label may still widen what a search
    # FINDS — that is what #568 kept it for — but it is never the reason a
    # reader is shown something as an answer.
    """
    terms = search_terms(subject)
    if terms:
        records = [r for r in records if not matched_only_through_label(r, terms)]
    if not records:
        return "Not on the indexed drawings."
    label = (subject or "That").strip()
    label = label.upper() if len(label) <= 4 else label[:1].upper() + label[1:]
    lines = [f"{label} — on the drawings:"]
    for r in records[:limit]:
        where = r.get("sheet_number") or (
            f"{r.get('file_name')} p{r.get('page_number')}" if r.get("file_name")
            else f"page {r.get('page_number')}" if r.get("page_number") else None)
        if not where:
            continue
        quote = re.sub(r"\s+", " ", r.get("quote") or "").strip()
        if not quote:
            continue
        line = f"{where} ({r.get('record_type')}): {quote[:200]}"
        if r.get("tier") == TIER_ORDER[-1]:
            line += " — read from the drawing image, verify against the sheet"
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else "Not on the indexed drawings."


__all__ = ["search_terms", "match_score", "rank", "best_per_attribute",
           "answer_is_grounded", "contains_label", "render_records",
           "matched_only_through_label",
           "INTENTS", "GEOMETRY_INTENT", "RENDERABLE"]
