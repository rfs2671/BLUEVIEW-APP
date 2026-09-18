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


# ══════════════════════════════════════════════════════════════════════════
# Matching
# ══════════════════════════════════════════════════════════════════════════
#
# ── A TERM IS A WORD, NOT A RUN OF LETTERS ─────────────────────────────────
#
# This matched with `term in haystack`, and the database narrowed with an
# unanchored regex of the same term. So 'air' matched STAIRS, 'unit' matched
# COMMUNITY, 'ac' matched SPACE and EACH — and every one of those rows was a
# candidate, and could win. On a 36-inch sheet set the short words a person
# actually types are exactly the ones that sit inside longer ones.
#
# A term now has to stand on its own: nothing alphanumeric immediately before
# it or after it. A hyphen, a slash, a quote mark or a space is a boundary, so
# 'ptac' still matches PTAC-1 and '42"' still matches 42" PARAPET.
#
# ── AND A PLURAL IS THE SAME WORD ──────────────────────────────────────────
#
# Substring matching found 'drain' inside DRAINS for free. A boundary would
# lose that, and a person asks 'how many roof drains' of a sheet that prints
# ROOF DRAIN. So a term also matches its own form with or without a trailing
# S or ES. That is the whole of it — the same rule _find_elements has used
# since the plural defect, not a stemmer, and not a synonym table. The shorter
# form must be at least three letters, or 'gas' would match GA (gauge).
#
# The SAME pattern narrows the database query and decides the match here, so
# the two cannot disagree about what a candidate is.

_ALNUM_BEFORE = r"(?<![A-Za-z0-9])"
_ALNUM_AFTER = r"(?![A-Za-z0-9])"
_MIN_STEM = 3


def term_forms(term: str) -> List[str]:
    """The term, and the one plural or singular form it may also be written in."""
    t = (term or "").lower()
    if not t:
        return []
    forms = [t]
    if t[-1].isalpha():
        # -ES is only a plural after a sibilant: BOXES, SWITCHES. PILES is
        # PILE + S, and stripping ES from it would invent PIL.
        if (t.endswith("es") and len(t) - 2 >= _MIN_STEM
                and t[:-2].endswith(("s", "x", "z", "ch", "sh"))):
            forms.append(t[:-2])
        if t.endswith("s") and len(t) - 1 >= _MIN_STEM:
            forms.append(t[:-1])
        if len(t) >= _MIN_STEM and not t.endswith("s"):
            forms.append(t + "s")
            if t.endswith(("x", "z", "ch", "sh")):
                forms.append(t + "es")
    out: List[str] = []
    for f in forms:
        if f not in out:
            out.append(f)
    return out


def term_pattern(term: str) -> str:
    """A regular expression that matches `term` as a word, in either number.

    Written to mean the same thing to Python's `re` and to MongoDB's PCRE, and
    used by both — search_plans narrows with it, rank() matches with it."""
    alts = "|".join(re.escape(f) for f in sorted(term_forms(term), key=len, reverse=True))
    return f"{_ALNUM_BEFORE}(?:{alts}){_ALNUM_AFTER}"


_PATTERNS: Dict[str, "re.Pattern[str]"] = {}


def _rx(term: str) -> "re.Pattern[str]":
    p = _PATTERNS.get(term)
    if p is None:
        p = _PATTERNS[term] = re.compile(term_pattern(term), re.I)
    return p


def _printed(record: Dict[str, Any]) -> List[str]:
    """What the sheet actually says about this record: the quote, the terms the
    writer derived from printed text, and a payload name. NOT the label."""
    parts = [record.get("quote") or ""]
    parts += [str(t) for t in (record.get("subject_terms") or [])]
    payload = record.get("payload")
    if isinstance(payload, dict):
        parts.append(str(payload.get("name") or ""))
    return [p for p in parts if p]


def _haystacks(record: Dict[str, Any]) -> List[str]:
    """Everything a record may be FOUND by — the printed words and the label.

    The label is here and nowhere in the render, and nowhere in how the record
    RANKS: it widens what is found without ever deciding what comes first."""
    return _printed(record) + ([record["label"]] if record.get("label") else [])


def _hits(hay: str, terms: Sequence[str]) -> List[str]:
    return [t for t in terms if _rx(t).search(hay)]


def _score(parts: Sequence[str], terms: Sequence[str]) -> Tuple[float, float]:
    """(coverage, density). Coverage is the share of the question's words the
    record contains; density is how much of the record those words are."""
    if not terms or not parts:
        return 0.0, 0.0
    hay = " | ".join(parts)
    hit = _hits(hay, terms)
    if not hit:
        return 0.0, 0.0
    density = min(1.0, sum(len(t) for t in hit) / max(len(hay), 1) * 8)
    return len(hit) / len(terms), density


def match_score(record: Dict[str, Any], terms: Sequence[str]) -> float:
    """Whether — and how well — a record can be FOUND for these terms, label
    included. This admits a record to ranking; it does not order it."""
    coverage, density = _score(_haystacks(record), terms)
    return coverage + 0.25 * density if coverage else 0.0


def printed_score(record: Dict[str, Any], terms: Sequence[str]) -> Tuple[float, float]:
    """(coverage, density) on the words the sheet prints. This ORDERS records."""
    return _score(_printed(record), terms)


def matched_only_through_label(record: Dict[str, Any], terms: Sequence[str]) -> bool:
    """True when the ONLY thing tying this record to the subject is a label —
    words a vision model supplied for a mark the sheet does not explain."""
    return match_score(record, terms) > 0 and printed_score(record, terms)[0] == 0


# ══════════════════════════════════════════════════════════════════════════
# Ranking
# ══════════════════════════════════════════════════════════════════════════

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

# When one page prints the same words more than once, the record kept is the
# most structured one: a schedule row says more than a loose line of the same
# text, and its payload carries the columns.
_TYPE_PREFERENCE = ("schedule", "element", "legend_entry", "note", "tag",
                    "dimension", "callout", "text")


def _page_of(record: Dict[str, Any]) -> str:
    """Which page a record is on. `page_id` when there is one — a sheet NUMBER
    is not an identity: seven current pages on 588 Boyland have none, and
    'no sheet number' is not one page."""
    return str(record.get("page_id") or
               f"{record.get('file_name')}#{record.get('page_number')}#"
               f"{record.get('sheet_number')}")


def dedupe_quotes(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One record per (page, printed words) — and for a NOTE, one per project.

    ── WHY, ON ONE PAGE ──────────────────────────────────────────────────
    #
    # A roof plan prints 42" PARAPET at every parapet run, and each is its own
    # text record. They all match, they all tie, and six of them fill a result
    # list that has room for eight — so every other sheet is pushed down by
    # one page saying the same thing six times. A second copy of a line adds
    # no evidence; it only takes a place.
    #
    # Kept: the strongest tier, then the most structured type, then the first.
    #
    # ── AND WHY A GENERAL NOTE IS DIFFERENT ────────────────────────────────
    #
    # This said, deliberately, that the same words on two sheets are two
    # citations. That is right for a parapet height measured on two different
    # plans: two sheets, two facts, and a reader wants both.
    #
    # A general note is not that. It is one paragraph the engineer stamps on
    # every sheet of a discipline, and the vision model reads it again on each
    # one because it sees each page alone. MEASURED ON 588 BOYLAND, 2026-09-17:
    #
    #   'refrigerant piping'  8 records, 2 distinct quotes — 6 slots repeated
    #   'AC units'            8 records, 5 distinct quotes — 3 slots repeated
    #   'condensate pump'     8 records, 5 distinct quotes — 3 slots repeated
    #
    # Asked about the AC units, the reader answered with one sentence said
    # five times, and the PTAC schedule — the thing that answers the question —
    # sat at positions six, seven and eight. 230 of the 323 repeated note rows
    # on this project are vision-read, which is exactly the population that
    # never passes through `boilerplate_lines`: that strips lines repeated
    # across a file's TEXT LAYER, and a note read off an image is not in it.
    #
    # So a note's copies collapse to ONE record, across pages, and the survivor
    # carries the sheets the others were on. NOTHING IS DROPPED AND NOTHING IS
    # HIDDEN — the reader is told 'M-100.00 (+4 sheets)'. Deletion would have
    # been wrong: 'COLD & HOT WATER SHALL BE COPPER TYPE L' is stamped on six
    # plumbing sheets and is the answer to what the hot water pipe is made of.
    """
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    seen_on: Dict[Tuple[str, str], List[str]] = {}
    for r in records:
        quote = re.sub(r"\s+", " ", (r.get("quote") or "")).strip().upper()
        if not quote:
            continue
        # A note is the same document reproduced; everything else is a fact
        # about the sheet it is on.
        k = ("", quote) if r.get("record_type") == "note" else (_page_of(r), quote)
        where = (r.get("sheet_number") or "").strip()
        cur = best.get(k)
        if cur is None:
            best[k] = r
            order.append(k)
            seen_on[k] = [where] if where else []
            continue
        if where and where not in seen_on[k]:
            seen_on[k].append(where)
        if _keep_rank(r) < _keep_rank(cur):
            best[k] = r
    out = []
    for k in order:
        r = best[k]
        others = [w for w in seen_on.get(k, []) if w != (r.get("sheet_number") or "").strip()]
        out.append(dict(r, also_on=others) if others else r)
    return out


def _keep_rank(r: Dict[str, Any]) -> Tuple[int, int]:
    rt = r.get("record_type")
    return (tier_rank(r.get("tier")),
            _TYPE_PREFERENCE.index(rt) if rt in _TYPE_PREFERENCE else len(_TYPE_PREFERENCE))


def rank(records: Iterable[Dict[str, Any]], terms: Sequence[str],
         intent: Optional[str] = None) -> List[Dict[str, Any]]:
    """What answers the question best, first.

    ── SIMILARITY FIRST, TIER BREAKS TIES ─────────────────────────────────
    #
    # This sorted on tier before anything else. The intent was that a schedule
    # cell should beat a vision read of the same thing — and it did, but it
    # also let ANY schedule cell beat ANY lower-tier record, however little of
    # the question it shared. Asked about a wall heater, a schedule cell that
    # shared only the word 'unit' came before the heater's own schedule.
    #
    # So the order is now:
    #
    #   1. coverage — how much of the question the PRINTED words contain
    #   2. tier     — among records that answer as much of it, the stronger
    #                 evidence first
    #   3. density  — among those, the record that is mostly the answer
    #   4. the intent's preferred record type, then page and ordinal, for a
    #      stable order
    #
    # Coverage is measured on printed words only. A label may admit a record;
    # it may not lift one above a record the sheet actually answers with.
    #
    # The narrower job the old rule was meant to do — never cite a vision read
    # when a schedule cell says the same thing — is best_per_attribute's, and
    # it still does it.
    """
    prior = _INTENT_PRIOR.get(intent or "", ())
    scored = []
    for r in dedupe_quotes(records):
        if match_score(r, terms) <= 0:
            continue
        coverage, density = printed_score(r, terms)
        rt = r.get("record_type")
        scored.append(((
            -round(coverage, 4),
            tier_rank(r.get("tier")),
            -round(density, 4),
            prior.index(rt) if rt in prior else len(prior),
            r.get("sheet_number") or "~",
            _page_of(r),
            r.get("ordinal") or 0,
        ), r))
    scored.sort(key=lambda kr: kr[0])
    return [r for _k, r in scored]


def _attribute_key(record: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """WHICH THING a record is about — or None when it does not say.

    A schedule is about the schedule it names; an element, a tag or a legend
    entry is about its mark. A note, a dimension, a callout or a loose line of
    text names no thing, and returning an empty key for them — as this did —
    made every such record on a sheet 'the same attribute', so a vision-read
    note was dropped whenever the sheet had any text-layer note at all,
    whatever either one said."""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    rt = str(record.get("record_type") or "")
    if rt == "schedule":
        ident = payload.get("name") or (record.get("subject_terms") or [""])[0]
    elif rt in ("element", "tag", "legend_entry"):
        ident = (payload.get("tag") or payload.get("symbol")
                 or (record.get("subject_terms") or [""])[0])
    else:
        ident = ""
    ident = re.sub(r"\s+", " ", str(ident or "")).strip().upper()
    if not ident:
        return None
    return (_page_of(record), rt, ident)


def best_per_attribute(ranked: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop a record when a STRONGER tier on the same page answers the SAME
    attribute — the same schedule, the same mark. Nothing else is dropped, and
    the order `rank` chose is kept.

    `ranked` is no longer tier-ordered, so the strongest tier per attribute is
    found first and then applied."""
    strongest: Dict[Tuple[str, str, str], int] = {}
    for r in ranked:
        k = _attribute_key(r)
        if k is not None:
            t = tier_rank(r.get("tier"))
            strongest[k] = min(t, strongest.get(k, t))
    out = []
    for r in ranked:
        k = _attribute_key(r)
        if k is not None and tier_rank(r.get("tier")) > strongest[k]:
            continue
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
    """Every number a returned record can vouch for.

    ── A CONTESTED CELL VOUCHES FOR NOTHING ───────────────────────────────
    #
    # When two independent readings of one schedule cell disagree, the record
    # carries both and stands behind neither. Letting either number through
    # here would put it in a composed answer with a citation behind it, which
    # is the whole failure this gate exists to stop — the fact that one of the
    # two happens to be right is not something we can demonstrate.
    """
    ok: set = set()
    for r in records or []:
        if (r.get("payload") or {}).get("count_contested"):
            continue
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


# A CLAUSE IS WHERE A NUMBER MEETS ITS SUBJECT.
#
# "PTAC-1: 21, PTAC-2: readings disagree, PTAC-3: 11" is one sentence and three
# claims, so a sentence is too coarse a unit — bound at sentence level, 21
# would vouch for PTAC-3. Commas, semicolons, dashes, newlines and bullets all
# separate claims in the answers this model writes.
#
# ' and ' is deliberately NOT a separator: "12 and 1/2 inches" is one value,
# and splitting there would break a dimension to catch a count.
#
# NEITHER IS ':'. A colon BINDS a label to its value \u2014 "PTAC-1: 21" is one
# claim, and splitting there put the mark in one clause and its own quantity
# in the next, so the TRUE answer was refused. Caught by the first smoke test
# against real records, which is why the separators are written out one at a
# time rather than reached for as a set.
_CLAUSE_SPLIT = re.compile(r"[.;,!?\n\r]+|\s[-\u2013\u2014]\s|\s[\u2022*]\s")


def _clauses(text: str) -> List[str]:
    return [c for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]


def _record_values(r: Dict[str, Any]) -> set:
    """Every number this one record can vouch for, from what it says."""
    out = set(_values(r.get("quote") or ""))
    payload = r.get("payload")
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, (str, int, float)):
                out.update(_values(str(v)))
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, (str, int, float)):
                        out.update(_values(str(item)))
                    elif isinstance(item, list):
                        for cell in item:
                            out.update(_values(str(cell)))
    return out


def _citation_values(r: Dict[str, Any]) -> set:
    """A sheet number, a job number and an issue date are how an answer says
    where it came from. A gate that reads them as claims fails every well-cited
    answer, so they are allowed in any clause."""
    out: set = set()
    for field in ("sheet_number", "filing_id", "issued_date"):
        out.update(_values(str(r.get(field) or "")))
    return out


def _values_by_ident(records: Sequence[Dict[str, Any]]) -> Dict[str, set]:
    """What each named thing — a mark, a schedule — can vouch for.

    ── A SCHEDULE IS ABOUT EVERY MARK IT LISTS, ROW BY ROW ────────────────
    #
    # Indexing a schedule under its NAME alone refused true answers. Measured
    # 2026-09-18: asked "number of PTAC-2", retrieval returns the ROOMS PTAC
    # UNITS SCHEDULE but not the individual PTAC-1 element, so a clause saying
    # "PTAC-1: 21" named a thing no returned record was indexed under — and 21
    # is printed in that schedule, in PTAC-1's own row.
    #
    # So each ROW is indexed under the mark in its first cell. Row by row and
    # not grid-wide, because grid-wide would let PTAC-3 borrow PTAC-1's 21 —
    # a smaller hole than the one being closed, but the same kind, and the
    # rows are right there.
    #
    # This does NOT reopen the contested cell. That schedule carries 21 and 11
    # and neither 6 nor 9, because PTAC-2's QTY was written as '(readings
    # disagree)' rather than as a digit. The rule that keeps a contested cell
    # out of the grid is what makes this safe, and if it ever wrote a number
    # there instead, this would leak.
    """
    out: Dict[str, set] = {}
    for r in records or []:
        if (r.get("payload") or {}).get("count_contested"):
            continue
        key = _attribute_key(r)
        if key is None:
            continue
        out.setdefault(key[2], set()).update(_record_values(r))
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        for row in (payload.get("rows") or []):
            if not isinstance(row, list) or not row:
                continue
            mark = re.sub(r"\s+", " ", str(row[0] or "")).strip().upper()
            # ── A ROW NUMBER IS NOT A SUBJECT ──────────────────────────────
            #
            # Many grids number their rows, so `row[0]` is often just '1', '2',
            # '9'. Indexed as idents those are catastrophic and CIRCULAR: the
            # clause "There are 9 PTAC-2 units" names the ident '9', which
            # holds the value 9, and the number vouches for itself. Measured
            # exactly that way on 'number of PTAC-2', where a numbered row let
            # both 6 and 9 back through.
            #
            # This is the FA-001 mistake in a second place — there a row index
            # merged into a description cell and read as a sprinkler count.
            # A thing a drawing NAMES has a letter in it.
            if not any(ch.isalpha() for ch in mark):
                continue
            vals: set = set()
            for cell in row:
                vals.update(_values(str(cell)))
            out.setdefault(mark, set()).update(vals)
    return out


def _idents_named_in(clause: str, idents: Iterable[str]) -> List[str]:
    """Which of these things the clause actually names, as whole words."""
    found = []
    for ident in idents:
        # Belt to the braces above: an ident with no letter cannot be named by
        # a clause without the digit itself doing the naming, which is the
        # circularity this gate exists to stop.
        if not ident or not any(ch.isalpha() for ch in ident):
            continue
        pattern = _ALNUM_BEFORE + re.escape(ident) + _ALNUM_AFTER
        if re.search(pattern, clause or "", re.I):
            found.append(ident)
    return found


def _count_answer_is_bound(text: str, records: Sequence[Dict[str, Any]]
                           ) -> Tuple[bool, List[str]]:
    """Every quantity must come from a record about the thing it counts.

    ── WHY THE UNION WAS NOT ENOUGH ───────────────────────────────────────
    #
    # `_supported_values` asks whether a number appears in ANY returned record.
    # Measured on 588 Boyland 2026-09-18, with the contested PTAC-2 record
    # correctly excluded, the gate still passed "There are 9 PTAC-2 units":
    # the 9 came from a DCDA & RPZ backflow schedule's unverified cells, and
    # on another phrasing from the Sheet List Table. A zoning table vouched
    # for the 6. Nothing about those records is about PTAC-2 — they merely
    # contained the digit.
    #
    # So a quantity is checked against the values of the things its own clause
    # NAMES. A clause that names nothing states a quantity of nothing, which
    # is the exact shape of an invented count, and it is refused.
    #
    # RESIDUE, recorded rather than papered over: a clause that names two marks
    # may borrow either one's numbers. Splitting further would break dimensions
    # like "12 and 1/2 inches", and the narrower rule is the one that can be
    # explained to somebody holding the drawing.
    """
    by_ident = _values_by_ident(records)
    citations: set = set()
    for r in records or []:
        citations |= _citation_values(r)
    unsupported: List[str] = []
    for clause in _clauses(text):
        said = _values(clause)
        if not said:
            continue
        allowed = set(citations)
        for ident in _idents_named_in(clause, by_ident.keys()):
            allowed |= by_ident[ident]
        unsupported.extend(v for v in said if v not in allowed)
    return (not unsupported), unsupported


def answer_is_grounded(text: str, records: Sequence[Dict[str, Any]],
                       intent: str = "") -> Tuple[bool, List[str]]:
    """(ok, the numbers nothing returned can vouch for).

    A CHECK ON THE OUTPUT, not an instruction in a prompt. The model composes;
    this decides whether what it composed may be sent. A number with nothing
    behind it is the worst failure this product has — it looks verified."""
    said = _values(text)
    if not said:
        return True, []
    # A COUNT IS BOUND TO ITS SUBJECT; EVERYTHING ELSE KEEPS THE UNION.
    #
    # The failure measured was a quantity — "9 PTAC-2 units" — and the bound
    # rule is written for that shape. An attribute answer quotes a note or a
    # cell whose number often belongs to no mark at all: of the ten suite
    # cases stating a number, eight bind to a mark or a schedule and the two
    # that do not (a 42" parapet, a 1,970 sf recreation area) are both
    # attribute cases. Applying the bound rule to them would refuse two true
    # answers to catch nothing.
    if (intent or "").strip().lower() == "count":
        return _count_answer_is_bound(text, records)
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


def cite(r: Dict[str, Any]) -> Optional[str]:
    """Where a record is, in the words a person can act on: its sheet number,
    else the file and page it came from, else the page alone. None when it can
    say none of those — and a record that cannot say where it is is not quoted.

    Live on 588 Boyland, 2026-09-16: an answer cited '?' for a page whose
    title block could not be read. Seven of the 111 current pages have no
    sheet number, so this runs every day. A blank or whitespace sheet number
    is the same case as a missing one; it printed as an empty citation.
    """
    sheet = (r.get("sheet_number") or "").strip()
    if sheet:
        return sheet
    page = r.get("page_number")
    name = (r.get("file_name") or "").strip()
    if name and page is not None:
        return f"{name} p{page}"
    if page is not None:
        return f"page {page}"
    return None


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
        where = cite(r)
        if not where:
            continue
        quote = re.sub(r"\s+", " ", r.get("quote") or "").strip()
        if not quote:
            continue
        # A note collapsed across sheets says so. The crew asked what the
        # drawings say; "on six sheets" is part of the answer, and hiding the
        # merge would make one stamping look like the only one.
        more = [w for w in (r.get("also_on") or []) if w]
        where_all = f"{where} (+{len(more)} sheet{'s' if len(more) > 1 else ''})" if more else where
        line = f"{where_all} ({r.get('record_type')}): {quote[:200]}"
        readings = (r.get("payload") or {}).get("count_readings")
        if readings:
            said = " and ".join(str(x.get("value")) for x in readings)
            line += (f" — two readings of that cell say {said}; "
                     f"verify against the sheet")
        if r.get("tier") == TIER_ORDER[-1]:
            line += " — read from the drawing image, verify against the sheet"
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else "Not on the indexed drawings."


__all__ = ["search_terms", "match_score", "rank", "best_per_attribute",
           "answer_is_grounded", "contains_label", "render_records", "cite",
           "matched_only_through_label",
           "INTENTS", "GEOMETRY_INTENT", "RENDERABLE"]
