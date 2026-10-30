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

import logging
import re
from fractions import Fraction
from typing import (Any, Collection, Dict, Iterable, List, NamedTuple,
                    Optional, Sequence, Tuple)

from lib import plan_areas as _areas
from lib import plan_dimensions as _dims
from lib import plan_floor_to_floor as _f2f
from lib.plan_records import TIER_ORDER, column_role, tier_rank
from lib.plan_text import SHEET_ID_RE

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


#: CHARACTERS THAT LOOK LIKE A QUOTE AND ARE NOT ONE.
#:
#: Every pattern in this system that spells an English contraction wrote it
#: as `n[o']?t` — which matches the STRAIGHT apostrophe and nothing else.
#: Measured 2026-09-20, on `classify_reply`:
#:
#:     "I couldn't find that - closest is A-101.00."   ->  refusal
#:     "I couldn’t find that - closest is A-101.00."   ->  CITED
#:
#: That is not a new defect. It IS the 87.5% defect, unfixed for one spelling:
#: a refusal that names its closest sheet satisfies the citation test, and the
#: anchored refusal opener was supposed to catch it first. The anchor closed
#: the door for `couldn't` and left it open for `couldn’t`.
#:
#: NORMALISE THE CHARACTER, DO NOT WIDEN THE CLASS. Spelling the variants into
#: `n[o'’]?t` would fix the sentence we happened to look at and leave the next
#: pattern in the file — and there were four such spellings across two files
#: when this was written. One normalisation in front of all of them cannot
#: drift out of step with any of them.
_QUOTE_LOOKALIKES = str.maketrans({
    "\u2018": "'",   # U+2018  LEFT SINGLE QUOTATION MARK
    "\u2019": "'",   # U+2019  RIGHT SINGLE QUOTATION MARK - the smart apostrophe
    "\u02bc": "'",   # U+02BC  MODIFIER LETTER APOSTROPHE
    "\u02b9": "'",   # U+02B9  MODIFIER LETTER PRIME
    "\u2032": "'",   # U+2032  PRIME
    "\u00b4": "'",   # U+00B4  ACUTE ACCENT
    "\u0060": "'",   # U+0060  GRAVE ACCENT
    "\u201c": '"',   # U+201C  LEFT DOUBLE QUOTATION MARK
    "\u201d": '"',   # U+201D  RIGHT DOUBLE QUOTATION MARK
    "\u2033": '"',   # U+2033  DOUBLE PRIME
})


def normalise_quotes(text: str) -> str:
    """Fold quote-lookalikes to ASCII, FOR MATCHING ONLY.

    The returned string is never what anyone is shown or what gets stored —
    a drawing's `9'-2"` must reach the crew exactly as the sheet prints it.
    This exists so that a pattern written with a straight apostrophe cannot
    be defeated by a model that types a curly one.
    """
    return (text or "").translate(_QUOTE_LOOKALIKES)


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


# ══════════════════════════════════════════════════════════════════════════
# A GC TYPES WORDS. THE DRAWING PRINTS ABBREVIATIONS.
# ══════════════════════════════════════════════════════════════════════════
#
# `apartment square footage` returned nothing while A-101.00 prints, and the
# corpus stores verbatim, `2A 1 BEDROOM APT. NET: 482 SQ. FT.` — the record
# matches none of those three words. Abbreviation is not an edge case; it is
# how every sheet is written.
#
# TWO HALVES, and the split is structural rather than convenient.
#
#   TRUNCATIONS are derivable. MIN is the first three letters of MINIMUM,
#   CONC of CONCRETE, ELEV of ELEVATION. No list is needed: generate the
#   word's own prefixes and require a period, which is what marks the token
#   abbreviated.
#
#   CONTRACTIONS are not. APT drops the middle of APARTMENT, FT the middle of
#   FEET, GYB of GYPSUM BOARD. No rule derives them, so they are listed — and
#   the list is the part that has to be disciplined, because a hand-kept list
#   of word relationships is exactly what rotted before.
#
# ── WHY THREE LETTERS ──────────────────────────────────────────────────────
#
# Measured against 37 query words including deliberately risky ones. At a
# two-letter minimum there are FOUR false bridges: `notes` -> NO. (which means
# NUMBER), `stair`/`steel`/`story` -> ST. (STREET), `electrical` -> EL.
# (ELEVATION). Drawings reuse that tiny namespace for unrelated words. At
# three the collisions vanish and every remaining match is a true
# abbreviation — STRUCT, SEC, PROV, INFO, CORP, PROP. At four, MIN, TYP, MAX,
# DIM, DIA and COL are all lost.
#
# It is a threshold, and it is a break rather than an optimum: 4 errors at
# two, 0 at three. The mechanism is namespace collision, not a fitted score.
#
# ── FORWARD DIRECTION ONLY, AND THIS MUST NOT BE RELAXED ───────────────────
#
# This maps A QUERY WORD to abbreviations of it. The reverse — expanding an
# abbreviation found in a record into candidate words — is NOISY and must not
# be added: measured on this corpus, NO. resolves to NOTE, SEC. to SECURED,
# EL. to ELEMENT, ST. to STEP. The query word is given; that is what makes
# this direction safe.
_ABBREV_MIN_PREFIX = 3

#: Generated prefixes that are ENGLISH WORDS, not abbreviations.
#:
#: `notes` generates the prefix NOT, and a sheet that ends a sentence with
#: "...SHALL NOT." would be bridged to it. Latent false bridges are the ones
#: that bite later and get diagnosed as something else, so this is closed
#: before shipping rather than after.
#:
#: DERIVED, NOT HAND-PICKED. Counted across the 173-page corpus, every one of
#: these appears ZERO times followed by a period and 14-414 times bare:
#:
#:     NOT 0/414   ARE 0/162   PER 0/117   OUT 0/59
#:     SET 0/52    END 0/30    CAN 0/14
#:
#: while every real abbreviation appears at least once WITH one — SEC 53/0,
#: CONC 18/0, PROV 32/0, MIN 65/28, MAX 38/13, TYP 19/11, DIA 6/1, CORP 14/1.
#: The separation is total, so the exclusion costs nothing: no valid bridge
#: is in this set. The same counting is how a future entry should be argued.
_PROSE_PREFIXES = {
    "not", "are", "per", "out", "set", "end", "can",
    # the same shape, not observed as a prefix here but the same class
    "the", "and", "for", "all", "any", "has", "was", "one", "two",
    "new", "use", "see", "way", "top", "its", "may", "our",
}


#: Contractions, which no rule derives. Each entry earns its place by
#: EVIDENCE, never by argument:
#:
#:   1. it appears N+ times in an indexed corpus, written as `ABBR.`;
#:   2. its expansion is a word a GC demonstrably types;
#:   3. it is a DRAWING CONVENTION, not a judgement about meaning.
#:
#: (3) is the one that matters. APT = APARTMENT is what every set on earth
#: prints; nobody has to be persuaded of it. IF YOU FIND YOURSELF ARGUING FOR
#: AN ENTRY, THAT IS THE SIGNAL IT IS A SYNONYM AND NOT A CONVENTION, and it
#: does not belong here — that argument is how the deleted synonym table grew.
#:
#: AND IT NEVER GROWS IN A PR THAT IS NOT ABOUT THIS LIST. A contraction added
#: while fixing something else is the other way that table grew.
#:
#: Counts are occurrences of `ABBR.` in the 588 Boyland corpus, 173 pages.
CONVENTIONS = {
    "ft":  ("feet", 422),
    "sf":  ("square feet", 381),
    "sq":  ("square", 417),
    "apt": ("apartment", 94),
    "gyb": ("gypsum board", 44),
    "qty": ("quantity", 17),
    "psf": ("pounds per square foot", 13),
}

#: expansion -> the abbreviations that stand for it.
#:
#: SINGLE-WORD EXPANSIONS ONLY, and the exclusion is not tidiness. Splitting
#: `square feet` into its words and mapping each to SF made the query word
#: `square` match `SF.` and `PSF.`, which is a bridge nobody asked for: SF
#: stands for the PHRASE, not for either word in it. A per-term bridge cannot
#: express a phrase, so the multi-word entries stay documented and unwired
#: until something matches phrases. Listing them is still worth it — they are
#: the evidence for what a phrase bridge would have to cover.
_BY_WORD: Dict[str, List[str]] = {}
for _ab, (_exp, _n) in CONVENTIONS.items():
    if " " in _exp:
        continue
    _BY_WORD.setdefault(_exp, []).append(_ab)


def abbreviation_forms(term: str) -> List[str]:
    """How this word may appear ABBREVIATED, each needing a trailing period.

    Truncations are generated from the word itself; contractions come from
    CONVENTIONS. Returns the bare tokens — `term_pattern` adds the period,
    which is what keeps `MIN` from matching the word MINE.
    """
    t = (term or "").lower()
    if len(t) <= _ABBREV_MIN_PREFIX:
        return []
    out: List[str] = []
    for n in range(_ABBREV_MIN_PREFIX, len(t)):
        pre = t[:n]
        if pre in _PROSE_PREFIXES:
            continue          # an English word, not an abbreviation
        out.append(pre)
    for ab in _BY_WORD.get(t, ()):
        if ab not in out:
            out.append(ab)
    return out


def term_pattern(term: str) -> str:
    """A regular expression that matches `term` as a word, in either number.

    Written to mean the same thing to Python's `re` and to MongoDB's PCRE, and
    used by both — search_plans narrows with it, rank() matches with it."""
    forms = [re.escape(f) for f in term_forms(term)]
    # An abbreviation is only an abbreviation when the period says so. Without
    # it `MIN` matches MINE and `CONC` matches nothing useful — the period is
    # the whole signal that the token stands for a longer word.
    forms += [re.escape(a) + r"\." for a in abbreviation_forms(term)]
    alts = "|".join(sorted(forms, key=len, reverse=True))
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


# ══════════════════════════════════════════════════════════════════════════
# The floor
# ══════════════════════════════════════════════════════════════════════════
#
# ── WORDS THAT NAME THE ASKING, NOT THE THING ──────────────────────────────
#
# A floor asks whether the subject's words appear on the drawings at all. That
# only works if the words it requires are words a DRAWING would print. These
# are not: they belong to the question, and a sheet has no reason to carry
# them. Measured 2026-09-18 — requiring every term emptied 27 of 40
# superintendent questions, and the damage was almost entirely these.
#
# THIS LIST IS CLOSED. It is small, and every entry is justified where it
# sits. It may not grow case by case: a floor that gains a word whenever a
# question fails is a tuned threshold wearing a different coat, and
# test_the_asking_words_are_justified fails on any entry without a reason.
#
# Removing a word from a subject only makes the floor MORE permissive — fewer
# terms are required — so a wrong entry costs recall of the floor's strictness
# and never costs an answer.
# `big` — 2026-09-20. "how big are the apartments" refused, because `big`
# appears in none of 12,031 records and the floor reads an unknown word as
# evidence the drawings do not discuss the subject. That reading is right for
# `solar` and wrong for `big`: one names a thing, the other asks about size.
#
# THIS IS THE SECOND WORD THIS LIST HAS MISSED, and the list is hand-kept by
# design — small, closed, each entry justified. Two misses is not an argument
# for a longer list; it is an argument that question words should come from
# somewhere other than accretion. Recorded rather than solved here.
ASKING_WORDS = {
    # asking for a position
    "where": "a sheet draws the thing; it does not print the word 'where'",
    "location": "the question's noun for position, not the thing located",
    "located": "as above, in verb form",
    # asking for a magnitude — the sheet prints the NUMBER, not the property
    "tall": "'how tall' asks for a height the sheet prints as a dimension",
    "big": "'how big' asks for a size; no sheet in the corpus prints the word",
    "high": "the adjective form of the same question; HIGH SHED is printed on "
            "the shed drawing, and stripping a printed word only widens",
    "wide": "'how wide' asks for a width the sheet prints as a dimension",
    "width": "the noun a question uses; a sheet prints the measurement itself",
    "long": "'how long' asks for a length printed as a dimension",
    "deep": "'how deep' asks for a depth printed as a dimension",
    "depth": "the noun form; footings print their depth as a number",
    "thick": "'how thick' asks for a thickness printed as a dimension",
    "size": "'what size' asks for a dimension the sheet prints as a number",
    "height": "the noun a question uses for a printed vertical dimension",
    # asking for a quantity or a kind
    "many": "from 'how many'; the sheet prints a QTY column, not the word",
    "much": "from 'how much'; the sheet prints the amount, never the asking",
    "number": "'number of X' asks a quantity. Measured: this word alone pulled "
              "the Sheet List Table, TABLE 504.4 and four other indexes into a "
              "PTAC question, and one of them vouched for an invented 9",
    "type": "'what type' asks for a classification the sheet prints as a mark",
    # asking about the document rather than the building
    "issued": "a question about the set's date; the sheet prints the date",
}


def floor_terms(terms: Sequence[str]) -> List[str]:
    """The subject's own words, with the question's words taken out.

    Never empty: a question made ENTIRELY of asking words — 'how many', 'what
    size' — has no subject to floor on, and stripping to nothing would empty
    every result. The original terms stand in that case, which is the strict
    reading and the safe one."""
    kept = [t for t in terms if t not in ASKING_WORDS]
    return kept or list(terms)


def subject_is_known(terms: Sequence[str],
                     known: Collection[str]) -> bool:
    """Does the corpus know EVERY word of the subject?

    ── THE FLOOR ASKED THE WRONG QUESTION ─────────────────────────────────
    #
    # It asked whether ONE RECORD carried every word. Measured 2026-09-20,
    # that refused `apartment square footage` while A-101.00 prints, and the
    # corpus stores verbatim, `2A 1 BEDROOM APT. NET: 482 SQ. FT.` — because
    # the sheet abbreviates and the GC does not. Six of eighteen ordinary
    # phrasings returned nothing for content that was extracted, stored, on a
    # live page and correct.
    #
    # ── WHY ABSENCE, AND NOT RARITY ────────────────────────────────────────
    #
    # The obvious alternative was to require the RAREST term rather than all
    # of them. Measured and rejected: document frequency does not track
    # discriminating power. On this corpus `concrete` appears in 121 records
    # and `schedule` in 114, so "rarest" picks SCHEDULE for `concrete pour
    # schedule` — the generic word, the one a LIGHTING SCHEDULE matched, which
    # is the exact failure the floor exists to stop. No cutoff separates 114
    # from 121 without being fitted to this corpus.
    #
    # What IS decisive is a word the corpus has never seen. `solar` appears in
    # none of 12,031 records; so do `kicker`, `escalator`, `helipad`, `chase`
    # and `pour`. That is not noise to be dropped — IT IS THE FINDING. A
    # subject containing a word the drawings never use is a subject these
    # drawings do not discuss.
    #
    # So the rule is a fact and not a threshold: every word of the subject
    # must be one the corpus uses. 25 of 26 against 20 of 26 for the old
    # rule, with every absent-case still refusing.
    #
    # ── WHAT THIS DELIBERATELY DOES NOT DO ────────────────────────────────
    #
    # It does not make the answer reachable. `apartment square footage` now
    # passes and returns 8 records, NONE of which is the A-101.00 line that
    # answers it — that record matches none of `apartment`, `square` or
    # `footage`, so it is never in the candidate set at all. This removes a
    # false refusal; it does not fix retrieval, and the two should not be
    # confused because both end in a disappointed superintendent.
    #
    # `known` is computed over quote, label AND subject_terms — the same
    # fields the candidate query narrows on. A label counts here for the
    # reason it always has: PACKAGE TERMINAL AIR CONDITIONER is printed on no
    # sheet in this corpus and lives only in labels, and a printed-only floor
    # would refuse a building with 41 of them. What a label may never do is
    # ANSWER, which `matched_only_through_label` still enforces.
    """
    want = floor_terms(terms)
    if not want:
        return True
    have = {str(k).lower() for k in (known or ())}
    return all(t.lower() in have for t in want)


def meets_the_floor(records: Iterable[Dict[str, Any]],
                    terms: Sequence[str]) -> bool:
    """Does ONE record carry every word of the subject?

    ── WHY ONE RECORD AND NOT THE SET ─────────────────────────────────────
    #
    # A set can cover a question by accident: one record prints 'number',
    # another prints 'ptac-2', and between them they 'cover' a question
    # neither answers. Measured on the 40, the set-wide form let a LIGHTING
    # SCHEDULE stand as the answer to 'what is the concrete pour schedule',
    # on the shared word 'schedule' alone.
    #
    # ── AND WHY A LABEL COUNTS HERE ────────────────────────────────────────
    #
    # `match_score` includes the vision-supplied label, and that is deliberate:
    # the floor decides what may be FOUND, not what may be SAID. The expansion
    # of PTAC — PACKAGE TERMINAL AIR CONDITIONER — is printed on no sheet in
    # the corpus; it exists only in labels on ten legend entries. A printed-
    # only floor would answer 'nothing found' to 'how many packaged terminal
    # air conditioners' on a building with 41 of them.
    #
    # What a label may never do is ANSWER. `matched_only_through_label` still
    # removes every label-only record from what is returned, so a label can
    # open the door and never speak through it.
    """
    want = floor_terms(terms)
    if not want:
        return True
    for r in records or []:
        hay = _haystacks(r)
        if all(_score(hay, [t])[0] > 0 for t in want):
            return True
    return False


# ── AN INDEX OF THE SET IS NOT A FACT ABOUT THE BUILDING ───────────────────
#
# A drawing list, a sheet index and an abbreviations table all match a great
# many subjects, because they LIST the things the set contains. Asked 'door
# schedule', retrieval returned T-001.01 - the drawing list, whose row happens
# to read 'A-400 DOOR SCHEDULE' - ahead of A-400.00, which IS the door
# schedule. Asked 'vent fan', the GENERAL ABBREVIATIONS table on M-001.00 led.
#
# Both were live complaints from a GC on 2026-09-19.
#
# This is not fixed by ranking. An index legitimately matches the words; it
# is the KIND of record that disqualifies it from leading, and that is what is
# keyed on here rather than a score.
_INDEX_NAME = re.compile(
    r"^\s*(?:DRAWING\s+LIST|SHEET\s+LIST|SHEET\s+INDEX|LIST\s+OF\s+DRAWINGS"
    r"|GENERAL\s+ABBREVIATIONS|ABBREVIATIONS)\b", re.I)
#: A schedule most of whose first column is a SHEET NUMBER is an index of the
#: set, whatever it calls itself. Measured on 588 Boyland: no equipment
#: schedule keys its rows by sheet number, and every index does.
_INDEX_ROW_SHARE = 0.6
_INDEX_MIN_ROWS = 3


def is_index_record(record: Dict[str, Any]) -> bool:
    """Does this record INDEX the set rather than describe the building?"""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if _INDEX_NAME.search(str(payload.get("name") or "")):
        return True
    if _INDEX_NAME.search(str(record.get("quote") or "")):
        return True
    rows = payload.get("rows") or []
    firsts = [str(row[0] or "") for row in rows
              if isinstance(row, list) and row and str(row[0] or "").strip()]
    if len(firsts) < _INDEX_MIN_ROWS:
        return False
    sheetish = sum(1 for f in firsts if SHEET_ID_RE.search(f.upper()))
    return sheetish / len(firsts) >= _INDEX_ROW_SHARE


def dimension_is_impossible(record: Dict[str, Any]) -> bool:
    """Has the writer marked this record's value structurally impossible?

    Read off the record rather than recomputed, so search and the indexer can
    never disagree about what counts as impossible. plan_records.emit is the
    one place that decides.
    """
    if not isinstance(record, dict):
        return False
    if record.get("dimension_defect"):
        return True
    payload = record.get("payload")
    return bool(isinstance(payload, dict) and payload.get("dimension_defect"))


def drop_impossible_dimensions(records: Sequence[Dict[str, Any]]
                               ) -> List[Dict[str, Any]]:
    """Fabricated dimensions out, and UNLIKE drop_indexes, out unconditionally.

    An index kept when nothing else matched still points somewhere useful, so
    it survives as a pointer. A dimension that cannot exist points nowhere:
    9'-714" is not a weaker reading of 9'-7 1/4", it is a different number
    that the drawing does not contain. Keeping it because it was all we had
    would be preferring a wrong answer to 'not found', which is the one trade
    this reader does not make.
    """
    return [r for r in records or [] if not dimension_is_impossible(r)]


def drop_indexes(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Indexes out, UNLESS they are all there is.

    A question whose only match is the drawing list has not been answered, and
    'Not found. Closest: T-001.01.' is a better reply than a row of the index
    presented as the answer — but that is the RENDER's decision, not this
    one's. Here, keeping them when nothing else matched preserves the pointer.
    """
    kept = [r for r in records or [] if not is_index_record(r)]
    return kept if kept else list(records or [])


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
    scored = [(_rank_key(r, terms, prior), r) for r in dedupe_quotes(records)
              if match_score(r, terms) > 0]
    scored.sort(key=lambda kr: kr[0])
    return [r for _k, r in scored]


def _rank_key(r: Dict[str, Any], terms: Sequence[str], prior: Sequence[str]) -> tuple:
    coverage, density = printed_score(r, terms)
    rt = r.get("record_type")
    return (
        -round(coverage, 4),
        tier_rank(r.get("tier")),
        -round(density, 4),
        prior.index(rt) if rt in prior else len(prior),
        r.get("sheet_number") or "~",
        _page_of(r),
        r.get("ordinal") or 0,
    )


def rank_by_best(found: Sequence[Tuple[Sequence[Dict[str, Any]], Sequence[str]]],
                 intent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Several names for one thing, ranked as one list (search_plans `also`).

    `found` is each name's ranked records with that name's terms. A record
    ranks by the best key it earns under ANY name - coverage of that name's
    words in what the sheet prints, then tier, density and the rest exactly
    as `rank` orders them - so no name lends a record words it does not
    print. A record found under two names is one record: each name's list is
    already collapsed by `dedupe_quotes` from the same rows, so a note's
    copies come back as the same survivor carrying the same sheets."""
    prior = _INTENT_PRIOR.get(intent or "", ())
    best: Dict[Tuple[str, str], Tuple[tuple, Dict[str, Any]]] = {}
    for records, terms in found:
        for r in records:
            k = (_page_of(r), re.sub(r"\s+", " ", (r.get("quote") or "")).strip().upper())
            key = _rank_key(r, terms, prior)
            if k not in best or key < best[k][0]:
                best[k] = (key, r)
    return [r for _k, r in sorted(best.values(), key=lambda kr: kr[0])]


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


# ── A MENTION OUTRANKS THE MEASUREMENT ────────────────────────────────────
#
# Asked how high the sidewalk shed is, the eight results were SIDEWALK SHED,
# TYPICAL SIDEWALK SHED ELEVATION, a permit note and the shed letter's
# letterhead - mentions, every one printing both words of the subject - and
# 8' HIGH SHED, which prints one of them and the answer, ranked ninth to
# eleventh (2026-10-25).
#
# Ruling 2026-10-26: an attribute question whose results state fewer than two
# values gets up to two more records - a ninth and a tenth - that state one
# and print a word of the SUBJECT. Nothing already chosen is moved or
# dropped: replacing the last two slots, as first ruled, pushed out S-102.00's
# "(2) 800S162-54 BOX BEAM" and S-401.00's BOXED HEADER details, which answer
# their questions without a number.
#
# The shared word may not be the attribute itself. "Height" is printed on
# 50'-0" BUILDING & BASE HEIGHT, and lending a ceiling question that line
# because both say HEIGHT is the mention problem over again. Which words are
# the attribute comes from the question's attribute slot (search_plans
# `attribute`), not from a list here.
#
# NO SLOT, NO APPEND (ruling 2026-10-26). Without an attribute the question
# has not said it wants a measurement, and nothing here reads the question
# text to guess: "what are the beams" is answered by a member size that is
# not a measurement, and inferring otherwise is the attribute table again.
VALUE_SLOTS = 2
_UNIT_VALUE = re.compile(
    r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?\s*"
    r"(?:SF|SQ\.?\s*FT|GPM|CFM|PSI|PSF|LBS?|MPH|HRS?|%|°F?|KW|BTUH?|MBH|GA)(?![A-Za-z])",
    re.I)


def states_a_value(record: Dict[str, Any]) -> bool:
    """Does the record print a measurement: a dimension (plan_dimensions) or
    a number with a unit of measure?"""
    quote = str(record.get("quote") or "")
    return bool(_dims.find(_dims.unreverse(quote))) or bool(_UNIT_VALUE.search(quote))


def subject_words(subject: str, attribute: str = "") -> List[str]:
    """The subject's words, less the words of the attribute asked about (in
    either number: 'heights' is 'height')."""
    attr = {f for a in search_terms(attribute) for f in term_forms(a)}
    return [t for t in search_terms(subject) if not attr & set(term_forms(t))]


def _one_edit_apart(a: str, b: str) -> bool:
    """One letter inserted, dropped or changed - 'hight' and 'height'."""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


# ── THE PROPERTY GOES IN THE ATTRIBUTE, IN CODE AS WELL AS IN THE PROMPT ───
#
# Ruling 2026-10-26. The tool tells the agent property words go only in
# `attribute`, and on the benchmark it mostly obeyed; when it does not, the
# word reaches the floor and the ranker as part of the thing being looked
# for. So the arguments are normalized here, deterministically, before
# anything is ranked: a subject word that IS the attribute's word - in
# either number, or the user's misspelling the agent corrected in the
# attribute ('sidewalk shed hight' with attribute 'height') - leaves the
# subject. Only the attribute's own words move; nothing is inferred from a
# list, and a subject that would be left empty is left as it was.
def normalize_arguments(subject: str, attribute: str = "", intent: str = "",
                        floor: str = "") -> Tuple[str, str, str]:
    """(subject, attribute, floor) as search_plans should use them.

    ALSO: A COUNT IS NOT NARROWED BY FLOOR. Asked how many exhaust fans each
    apartment on the fourth floor has, the agent passed floor '4' and the
    floor filter emptied the pages before the located-symbol evidence - read
    for the whole project - was ever gathered: 0 records (benchmark,
    2026-10-26). A count's floor is the scope the answer states and the gate
    checks (glyph_values), not a filter on what is read."""
    attr_words = [w for w in search_terms(attribute or "")]
    forms = {f for w in attr_words for f in term_forms(w)}
    raw = (subject or "").split()
    kept = []
    for word in raw:
        t = re.sub(r"[^a-z0-9]", "", word.lower())
        same = bool(t) and (forms & set(term_forms(t)) or any(
            len(t) >= 4 and t[0] == w[0] and _one_edit_apart(t, w) for w in attr_words))
        if not same:
            kept.append(word)
    new_subject = " ".join(kept).strip() if kept else ""
    if not search_terms(new_subject):
        new_subject = subject or ""
    if (intent or "").strip().lower() == "count":
        floor = ""
    return new_subject, attribute or "", floor or ""


def value_records(shown: Sequence[Dict[str, Any]], rest: Sequence[Dict[str, Any]],
                  subject: str, attribute: str = "") -> List[Dict[str, Any]]:
    """Up to VALUE_SLOTS records from `rest`, in its order, to follow `shown`
    when fewer than VALUE_SLOTS of `shown` state a value: each states one and
    prints a subject word that is not the attribute's. Nothing at all when
    the call named no attribute."""
    if not (attribute or "").strip():
        return []
    if sum(states_a_value(r) for r in shown) >= VALUE_SLOTS:
        return []
    words = subject_words(subject, attribute)
    if not words:
        return []
    out = []
    for r in rest:
        if states_a_value(r) and printed_score(r, words)[0] > 0:
            out.append(r)
            if len(out) == VALUE_SLOTS:
                break
    return out


# ══════════════════════════════════════════════════════════════════════════
# Set-wide checks
# ══════════════════════════════════════════════════════════════════════════
#
# ── WHY THESE ARE NOT RETRIEVAL ────────────────────────────────────────────
#
# Everything above answers one question about one subject. A superintendent
# reading the set before mobilising has a different need: not "what does the
# drawing say about X" — he can read a drawing — but "what in this set does
# not add up". Those are comparisons ACROSS records, and the typed records are
# the nodes they run over.
#
# This is the first of them, and it is the shape the rest take: a pure
# function over records that returns findings, each naming its source sheet
# and what is wrong, with nothing inferred that the records do not carry.


def dangling_callouts(callouts: Iterable[Dict[str, Any]],
                      sheets_present: Iterable[str]) -> List[Dict[str, Any]]:
    """Callouts pointing at a sheet the set does not contain.

    ── THE TARGET MUST LOOK LIKE A SHEET NUMBER ───────────────────────────
    #
    # Measured on 588 Boyland 2026-09-19: of 106 callouts on current pages,
    # 76 resolve, 24 point at something absent and 6 carry no readable
    # target. But the 24 are NOT 24 findings. These were among them:
    #
    #     M-101.00 -> 'NO. 586'    'ADJACENT 2 STORY BRICK & CELLAR No. 586'
    #     3 OF 3   -> 'ELEV.'      'SEE ELEV. 1 ELEV.'
    #     P-100.00 -> 'NO. 586'    'SEE D.W. RISER. 1A No. 586'
    #
    # A neighbouring building's street number and a detail-bubble label are
    # not sheet references. Reporting them would train a superintendent to
    # ignore the report, which costs more than the check is worth.
    #
    # So a target counts only if it has the SHAPE of a sheet number — the
    # same `SHEET_ID_RE` the indexer identifies sheets with, so the check and
    # the corpus cannot disagree about what a sheet number is.
    #
    # Comparison is on the sheet number ALONE, not the revision: A-201 and
    # A-201.01 are the same drawing at different issues, and a callout to
    # 'A-201' is satisfied by 'A-201.01' being in the set.
    """
    have = set()
    for s in sheets_present or []:
        base = _sheet_base(s)
        if base:
            have.add(base)
    out: List[Dict[str, Any]] = []
    for c in callouts or []:
        payload = c.get("payload") if isinstance(c.get("payload"), dict) else c
        raw = str(payload.get("target_sheet") or "").strip().upper()
        target = _sheet_shaped(raw)
        if not target:
            continue
        if _sheet_base(target) in have:
            continue
        out.append({
            "from_sheet": c.get("sheet_number") or payload.get("sheet_number"),
            "detail_number": str(payload.get("detail_number") or "").strip(),
            "target_sheet": target,
            "quote": c.get("quote") or payload.get("text") or "",
        })
    out.sort(key=lambda f: (str(f["from_sheet"] or ""), f["target_sheet"]))
    return out


def referenced_sheets_missing(callouts: Iterable[Dict[str, Any]],
                              sheets_present: Iterable[str]
                              ) -> List[Dict[str, Any]]:
    """The same findings, grouped by the sheet that is not there.

    ── ONE MISSING SHEET IS ONE FINDING, NOT SEVEN ────────────────────────
    #
    # Measured on 588 Boyland 2026-09-19: eight dangling callouts, and SEVEN
    # of them are the structural drawings all pointing at S-400. A list of
    # eight rows says eight problems; the truth is two, and the useful
    # sentence is 'seven sheets reference S-400 and it is not in the set'.
    #
    # On a larger project the ungrouped form is a list nobody opens.
    #
    # ── AND THE WORDING IS DELIBERATE ──────────────────────────────────────
    #
    # 'referenced but not in the indexed set', never 'missing'. A sheet may
    # never have been issued, or may simply not have been uploaded, and
    # nothing in the records distinguishes those. Saying 'missing' asserts the
    # first and would send somebody to the architect over an upload.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for f in dangling_callouts(callouts, sheets_present):
        tgt = f["target_sheet"]
        row = out.setdefault(tgt, {"target_sheet": tgt, "referenced_by": [],
                                   "details": []})
        src = f.get("from_sheet")
        if src and src not in row["referenced_by"]:
            row["referenced_by"].append(src)
        if f.get("detail_number"):
            row["details"].append(f"{src}:{f['detail_number']}")
    rows = sorted(out.values(),
                  key=lambda r: (-len(r["referenced_by"]), r["target_sheet"]))
    for r in rows:
        r["referenced_by"].sort()
        n = len(r["referenced_by"])
        r["summary"] = (
            f"{r['target_sheet']} is referenced by {n} "
            f"{'sheet' if n == 1 else 'sheets'} and is not in the indexed set")
    return rows


def _sheet_shaped(text: str) -> str:
    """The sheet number inside `text`, or '' when it does not contain one."""
    m = SHEET_ID_RE.search((text or "").upper())
    return m.group(1) if m else ""


def _sheet_base(sheet: str) -> str:
    """'A-201.01' and 'A-201' are the same drawing at different issues."""
    s = (sheet or "").strip().upper()
    return s.split(".")[0] if s else ""


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


def _vouches_for_nothing(r: Dict[str, Any]) -> bool:
    """A contested cell, a located symbol outside its scoped count, an
    area row (lib.plan_areas: it vouches only through its own check,
    `_areas.figures_in_clause`), or a derived floor-to-floor row
    (lib.plan_floor_to_floor: only a clause naming a floor-to-floor may state its
    figures, answer_is_grounded) - the records `_supported_values` reads
    nothing from."""
    return (bool((r.get("payload") or {}).get("count_contested")) or is_glyph_evidence(r)
            or _areas.is_area_record(r) or _f2f.is_level_record(r))


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
        # A LOCATED SYMBOL VOUCHES ONLY THROUGH ITS COMPLETE, SCOPED COUNT
        # (glyph_values), and the union has no scope. A glyph row's payload
        # is coordinates, a door width and an RMS: let in here, it would
        # vouch for nearly any number. Measured: one EF-1 row carries 56,
        # 908 and fourteen coordinates.
        if is_glyph_evidence(r):
            continue
        # AN AREA ROW VOUCHES ONLY THROUGH ITS CHECK (lib.plan_areas): its
        # payload carries the measured figure, which binds only where the
        # printed one agrees, and the printed one, which a disagreement
        # withholds.
        if _areas.is_area_record(r):
            continue
        # A DERIVED FLOOR-TO-FLOOR ROW (lib.plan_floor_to_floor) lends its citation
        # and nothing else: its figures bind only in a clause naming a
        # floor-to-floor (answer_is_grounded), never in the union.
        if _f2f.is_level_record(r):
            for field in ("sheet_number", "filing_id", "issued_date"):
                ok.update(_values(str(r.get(field) or "")))
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
#
# A FULL STOP ENDS A SENTENCE. A DECIMAL POINT DOES NOT.
#
# This split on any '.', so the citation '[M-200.00]' became the clauses
# '[M-200' and '00]' \u2014 and the bare '00', in a clause naming nothing, was
# reported as an unsupported number. Live test 2026-09-19: the model wrote
# 'PTAC-1: 21 [M-200.00]', which is exactly right, and the gate replaced it
# with a render of the same content because of the sheet number in it.
#
# A period only separates when whitespace or the end of the text follows it,
# which is what makes it a full stop rather than part of a number.
_CLAUSE_SPLIT = re.compile(
    r"[;,!?\n\r]+|\.(?=\s|$)|\s[-\u2013\u2014]\s|\s[\u2022*]\s")


def _clauses(text: str) -> List[str]:
    return [c for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]


#: How an element's stated count was read. Only these two read it from a
#: schedule's quantity cell; the rest are not counts of the thing at all.
#: Excluded by operator ruling 2026-10-07: `tag_occurrences` / `glyph_match`
#: (one sheet's printed labels, unscoped - 'SD x8 on A.1.2' is not how many
#: smoke detectors the building has) and `vision_read` (the kind of count
#: behind the 41 PTAC units).
COUNTING_BASES = frozenset({"schedule_qty", "ocr_schedule_qty"})

#: The fields a record cites itself by.
_CITATION_FIELDS = ("sheet_number", "filing_id", "issued_date")


def _quantity_columns(payload: Dict[str, Any]) -> List[int]:
    """The columns of a schedule whose PRINTED header says quantity. The role
    stored at extraction wins; a bare header string is read by the same
    column_role, so there is one definition of what a quantity column is."""
    out = []
    for i, c in enumerate(payload.get("columns") or []):
        if isinstance(c, dict):
            role = (c.get("role") if c.get("role") is not None
                    else column_role(c.get("header") or ""))
        else:
            role = column_role(str(c or ""))
        if role == "quantity":
            out.append(i)
    return out


def _citation_texts(records: Sequence[Dict[str, Any]]) -> List[str]:
    """The citation strings an answer may carry - longest first, so a full
    date is removed before any shorter string inside it.

    A CITATION IS REMOVED AS TEXT; ITS DIGITS ARE NEVER WHITELISTED. These
    were read with `_values` and every number in them allowed in every
    clause: the AR set's issue date 8/18/2026 lent 8, 18 and 2026 to any
    count, so "There are 8 exhaust fans." passed on the say-so of 1,264
    Boyland records (measured 2026-10-07).

    A citation that is only digits is never removed: 26 Boyland records
    carry sheet_number '1', and removing '1' would wave any count of one
    through unchecked. A citation must hold a letter or a separator to be
    told apart from a count."""
    out = set()
    for r in records or []:
        for f in _CITATION_FIELDS:
            v = re.sub(r"\s+", " ", str(r.get(f) or "")).strip()
            if len(v) >= 3 and re.search(r"[A-Za-z/.\-]", v):
                out.add(v)
    return sorted(out, key=len, reverse=True)


def _strip_citations(clause: str, citations: Sequence[str]) -> str:
    for c in citations:
        clause = re.sub(_ALNUM_BEFORE + re.escape(c) + _ALNUM_AFTER, " ",
                        clause, flags=re.I)
    return clause


def _values_by_ident(records: Sequence[Dict[str, Any]]) -> Dict[str, set]:
    """What each named thing - a mark, a schedule - can vouch for AS A COUNT.

    ── ONLY A COUNTING SOURCE, NEVER A NUMBER THAT HAPPENS TO BE THERE ────
    #
    # This lent every number a record carried. Measured on 588 Boyland
    # 2026-10-07: 2,843 (mark, number) pairs could vouch for a count and 66
    # were counts. "There are 10 EF-1." passed on EF-1's 10 lb weight, "50
    # EF-1" on its CFM, "9000 PTAC-1" on a BTU rating, and a legend symbol
    # 'A' - which the article "a" names - lent its own bbox coordinates.
    #
    # A count is now vouched for by (operator ruling 2026-10-07):
    #   - the cell under a schedule column whose printed header says
    #     quantity, in the named mark's own row;
    #   - an element's count_if_stated when it was read from such a cell
    #     (COUNTING_BASES);
    #   - and, in the gate, a located-symbol tally (glyph_values).
    # Nothing else: no other cell, no payload number, no schedule NAME (a
    # schedule's rows are types, and counting them is what the render tells
    # the model never to do). A thing that can be named but states no count
    # is kept with an empty set: it is still named, and still lends nothing.
    #
    # ── A SCHEDULE IS ABOUT EVERY MARK IT LISTS, ROW BY ROW ────────────────
    #
    # Each ROW is indexed under the mark in its first cell, not grid-wide,
    # so PTAC-3 cannot borrow PTAC-1's 21. And this does NOT reopen the
    # contested cell: PTAC-2's QTY is written '(readings disagree)', which
    # carries no digit.
    """
    out: Dict[str, set] = {}
    for r in records or []:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        if payload.get("count_contested"):
            continue
        if is_glyph_evidence(r):        # counted by glyph_values, nowhere else
            continue
        key = _attribute_key(r)
        if key is None:
            continue
        mine = out.setdefault(key[2], set())
        if (r.get("record_type") == "element"
                and payload.get("count_basis") in COUNTING_BASES
                and payload.get("count_if_stated") is not None):
            mine.update(_values(str(payload["count_if_stated"])))
        qty = _quantity_columns(payload) if r.get("record_type") == "schedule" else []
        for row in (payload.get("rows") or []):
            if not isinstance(row, list) or not row:
                continue
            mark = re.sub(r"\s+", " ", str(row[0] or "")).strip().upper()
            # ── A ROW NUMBER IS NOT A SUBJECT ──────────────────────────────
            #
            # Many grids number their rows, so `row[0]` is often just '1', '2',
            # '9'. Indexed as idents those are CIRCULAR: the clause "There are
            # 9 PTAC-2 units" names the ident '9', which holds the value 9.
            # A thing a drawing NAMES has a letter in it.
            if not any(ch.isalpha() for ch in mark):
                continue
            vals = out.setdefault(mark, set())
            for i in qty:
                if i < len(row):
                    vals.update(_values(str(row[i])))
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


def glyph_tallies(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """tag -> Tally, over the registered-glyph records only.

    Separated so the gate and an answer composer see the SAME arithmetic. If
    the composer counted records itself and the gate counted them here, the
    two would disagree the first time one of them learned to skip an unread
    glyph — which is the three-incomparable-instruments failure in a new
    place.

    Scope is the units those records mention, plus any unit the emitter
    recorded as unregistered: a refusal to place is written as a record too,
    because a unit that produced no record is indistinguishable from a unit
    with nothing in it unless somebody says so.
    """
    from lib import plan_tally
    from lib.plan_extract import TIER_REGISTERED_GLYPH

    rows = [r for r in (records or [])
            if r.get("tier") == TIER_REGISTERED_GLYPH]
    if not rows:
        return {}
    scope = sorted({str(r.get("unit")) for r in rows if r.get("unit")})
    unreg = sorted({str(r.get("unit")) for r in rows
                    if r.get("glyph_status") == plan_tally.UNSUPPORTED_UNIT
                    and r.get("unit")})
    # An UNRESOLVED glyph has no tag, so it belongs to no tag's count and to
    # every tag's doubt: it might be any of them. It therefore enters each
    # tally as unresolved, which is what stops a total while leaving the
    # resolved part of every tag intact.
    unresolved = [{"tag": None, "unit": r.get("unit"),
                   "status": r.get("glyph_status") or plan_tally.UNREAD}
                  for r in rows
                  if r.get("glyph_status") in (plan_tally.UNREAD,
                                               plan_tally.CONTESTED)]
    out: Dict[str, Any] = {}
    for tag in sorted({str(r.get("label") or "") for r in rows
                       if r.get("label")
                       and r.get("glyph_status") == plan_tally.RESOLVED}):
        mine = [{"tag": tag, "unit": r.get("unit"),
                 "status": plan_tally.RESOLVED}
                for r in rows
                if r.get("label") == tag
                and r.get("glyph_status") == plan_tally.RESOLVED]
        out[tag] = plan_tally.tally(mine + unresolved, scope or None,
                                    unregistered_units=unreg)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Located symbols: a count binds only when every row is in hand
# ══════════════════════════════════════════════════════════════════════════
#
# ── A PARTIAL COUNT WAS BOUND AS A TOTAL ──────────────────────────────────
#
# Measured on 588 Boyland 2026-10-06, with the 84 rows of the placement pass
# (#660) in production: search_plans returns 8 records, the glyph rows rank
# below printed ones, and glyph_tallies counted the 2 of 16 EF-1 rows that
# came back. "There are 2 EF-1." was allowed. A tally can only ever count
# what it is handed, so it cannot be the thing that knows a total.
#
# So completeness is checked on the way in, by TWO INDEPENDENT READS of the
# same scope: search_plans fetches every row of the family, and separately
# asks the database how many there are (count_documents, at question time,
# never carried from the pass). The gate binds a count only when the rows in
# hand that satisfy the census's own filter number exactly the census. The
# rows in hand are a subset of what the filter matches, so equal counts mean
# equal sets - and any truncation anywhere downstream, by any caller, becomes
# a mismatch and a refusal, never a smaller number.
#
# ── A FAMILY IS A SCHEDULE, AND TWO SCHEDULES ARE NEVER ADDED ─────────────
#
# 'fan' names the EXHAUST FAN SCHEDULE (EF-1, EF-2) and the FAN SCHEDULE
# (SAF-1). A clause that names a family only by words both share says which
# family it counts no better than the question did, so it binds nothing from
# either; a clause that names one (exhaust fans) or a tag (EF-1) binds that
# family's own count. No figure is ever summed across families.
#
# ── SCOPE IS THE FLOOR PAIR, NAMED BY ITS PRINTED TITLE ───────────────────
#
# A floor is the architectural/mechanical pair the pass placed against
# (A-103.00 / M-103.00), and "fourth floor" maps to it through the printed
# sheet title, not the index's vision-written `floors` field ('1', 'second',
# 'Third Floor', ...). A sheet the pass refused names its floor the same way
# when it is in the NCS plan series; one that is not (another architect's
# A.1.x, an unnumbered page) cannot be placed on a floor and blocks only the
# building total. A building total binds only when NOTHING was refused.

from lib.plan_derive import PLAN_SHEET as _PLAN_SHEET  # noqa: E402
from lib.plan_extract import TIER_REGISTERED_GLYPH as _GLYPH_TIER  # noqa: E402
from lib import plan_tally as _tally  # noqa: E402

#: record_type of the census search_plans attaches beside the glyph rows.
#: Never written to the database: it exists only in a search's result.
GLYPH_CENSUS = "glyph_census"

#: Words a schedule name shares with every count question. "each UNIT has 2
#: exhaust fans" must not name the ROOMS PTAC UNITS SCHEDULE, nor the WALL
#: ELECTRIC UNIT HEATER SCHEDULE.
_GENERIC_FAMILY_WORDS = frozenset({
    "schedule", "unit", "room", "type", "equipment", "list", "table", "the",
    "and", "of", "with",
})

_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
}
_ORDINAL_FLOOR = re.compile(
    r"\b(" + "|".join(_ORDINALS) + r"|\d{1,2}(?:st|nd|rd|th))\s+"
    r"(?:floor|fl\b\.?|level|storey|story)", re.I)
_NAMED_LEVEL = re.compile(r"\b(roof|mezzanine|bulkhead|cellar|basement|penthouse)\b"
                          r"(?:\s+(?:floor|level))?", re.I)
_FLOOR_WORD = re.compile(r"\b(floor|floors|level|levels|storey|storeys|story|stories)\b",
                         re.I)
_SHEET_REF = re.compile(r"(?<![A-Za-z0-9])([A-Z])-(\d{3})(?:\.(\d{2}))?(?![A-Za-z0-9])",
                        re.I)
_UNIT_REF = re.compile(r"(?<![A-Za-z0-9.\-/])(\d{1,2}[A-Z]{1,2})(?![A-Za-z0-9])", re.I)
_PER_UNIT = re.compile(r"\b(each|every|per|apiece)\b", re.I)


def _stem(word: str) -> str:
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def family_words(name: str) -> frozenset:
    """The words that make a schedule's name say WHICH equipment it lists."""
    return frozenset(_stem(w) for w in re.findall(r"[A-Za-z]{2,}", name or "")
                     if _stem(w) not in _GENERIC_FAMILY_WORDS)


def _named_tags(text: str, tags: Iterable[str]) -> List[str]:
    return [t for t in tags
            if re.search(_ALNUM_BEFORE + re.escape(t) + _ALNUM_AFTER, text or "", re.I)]


# ── A COUNT NAMES ITS OWN FAMILY (ruling 71, 2026-10-28) ──────────────────
#
# "There are 9 water heaters." bound on WH-1's located 9 (production probe,
# 2026-10-28): HEATER is a word of the WALL ELECTRIC UNIT HEATER SCHEDULE,
# and one shared word was all a clause needed to name a family. WH-1 is a
# wall electric unit heater, not a water heater.
#
# Ruling 71: "a count binds only if its noun matches the family's own
# schedule description or tag (WH-1 = 'wall electric unit heater'; 'water
# heater' refuses). Use the schedule title/description text, no hand list."
#
#   THE NOUN is every phrase of the clause that holds one of the family's
#   own words or tags: a run of adjacent words, broken by any mark between
#   two words, by a figure, by a stop word (_STOP) or a per-unit word, and by
#   a sheet or unit reference ("on A-103.00", "4A") - which say where, never
#   what. In "There are 9 water heaters on the roof" the phrase is "water
#   heaters".
#
#   ITS OWN TEXT is the family's: the schedule's printed name, word by word,
#   each in either number or abbreviated (term_pattern), and its tags; a
#   plan-only family's object, its tags' own words and the names its note
#   prints for them (lib.plan_only). A word a schedule name shares with
#   every count question (_GENERIC_FAMILY_WORDS: unit, type, ...) neither
#   names nor misnames: "16 EF-1 units" is still EF-1.
#
#   Every other word in such a phrase is FOREIGN, and a clause with one
#   names no family through that phrase: "water heaters", "WH-1 fans",
#   "W1 doors" (W1 is a window) and "PTAC-1 air conditioners" (no PTAC
#   schedule prints AIR CONDITIONER) refuse. So does a level word inside
#   the noun ("roof exhaust fans"): state the level apart ("the roof has").
#
# What it does not decide: which family a clause naming several is about
# (_clause_subjects, as before), and the retrieval (glyph_families_for stays
# wide - fetching a family costs a census, and the agent shown WH-1's rows
# for "water heaters" can say what the set does have).

#: A word of a clause, as the noun check reads it: letters and digits, with
#: inner hyphens, dots, slashes and apostrophes ("WH-1", "J.R.", "owner's").
_NOUN_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-./'][A-Za-z0-9]+)*\.?")
_FIGURE_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?\.?")
_PER_WORDS = frozenset({"each", "every", "per", "apiece"})


def _alnum(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (word or "").lower())


def _noun_break(tok: str) -> bool:
    """A word that ends a noun phrase: a figure, a stop word, a per-unit
    word, or a sheet or unit reference."""
    low = tok.lower().rstrip(".")
    return bool(_FIGURE_TOKEN.fullmatch(tok) or low in _STOP or low in _PER_WORDS
                or _SHEET_REF.fullmatch(tok.rstrip(".")) or _UNIT_REF.fullmatch(tok.rstrip(".")))


class _Own(NamedTuple):
    """A family's own text: its words (each read by term_pattern), its tags,
    and the printed other names of a plan-only family's tags (alnum-only)."""
    words: Tuple[str, ...]
    tags: frozenset
    names: frozenset
    opening: bool = False


def _own_text(name: str, tags: Iterable[str], plan_only: Optional[Dict[str, Any]] = None,
              opening: bool = False, more: Iterable[str] = ()) -> _Own:
    words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", name or "")]
    names: set = set()
    po = plan_only or {}
    if po:
        words += [w.lower() for w in re.findall(r"[A-Za-z]{2,}", str(po.get("object") or ""))]
        for ws in (po.get("tag_words") or {}).values():
            words += [str(w).lower() for w in ws or []]
        also = po.get("also") if isinstance(po.get("also"), dict) else {}
        for al in also.values():
            for a in al or []:
                names.add(_alnum(a))
                names.update(_alnum(p) for p in re.findall(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*\.?", a))
    for m in more:
        words += [w.lower() for w in re.findall(r"[A-Za-z]{2,}", m or "")]
    return _Own(tuple(dict.fromkeys(words)),
                frozenset(str(t).strip().upper() for t in tags or () if t),
                frozenset(n for n in names if n), opening)


def _is_own(tok: str, own: _Own, prev: str) -> bool:
    bare = tok.rstrip(".")
    up = bare.upper()
    if up in own.tags and (len(up) > 1 or not own.opening or prev.lower() == "type"):
        return True                     # a lettered door type only as "type F"
    if own.opening:
        m = re.fullmatch(r"type-(\w+)|(\w+)-type", bare, re.I)
        if m and (m.group(1) or m.group(2)).upper() in own.tags:
            return True                 # "type-F", "F-type" (_named_opening_tags)
    if own.names and _alnum(tok) in own.names:
        return True
    return any(_rx(w).fullmatch(tok) or _rx(w).fullmatch(bare) for w in own.words)


def foreign_words(clause: str, own: _Own) -> List[str]:
    """The words of the clause's noun phrases that hold one of `own`'s words
    or tags and are not its own (ruling 71): [] when the clause names the
    family only by its own text, or names nothing of it.

    A LEVEL WORD NAMES WHERE, NOT WHAT: "roof" is a word of ROOF DRAINS, but
    "The roof level has 2 RD-1" holds no drain in "roof level" (measured on
    this repo's own count tests). A level word the family's text holds is its
    own, never a phrase's hit.

    EVERY CLAUSE SHAPE, ONE RULE (ruling 100, 2026-10-28: '"W1 doors 8." must
    refuse. The noun check applies to every clause shape (colon, no colon,
    inline)'): a phrase is judged whole wherever its figure stands - "W1
    doors: 8", "W1 doors 8", "8 W1 doors", "W1 doors (8)". So a verb inside
    the phrase fails closed too ("The overflow drains number 2"; ruling 99)."""
    out: List[str] = []
    run: List[Tuple[str, bool, bool]] = []      # (word, foreign, the family's hit)
    end, prev = 0, ""

    def close():
        if any(h for _w, _f, h in run):
            out.extend(w for w, foreign, _h in run if foreign)

    for m in _NOUN_TOKEN.finditer(clause or ""):
        tok = m.group(0)
        if (clause[end:m.start()]).strip():
            close()
            run = []
        end = m.end()
        if _is_own(tok, own, prev):
            level = bool(_NAMED_LEVEL.fullmatch(tok.rstrip(".")) or _FLOOR_WORD.fullmatch(tok.rstrip(".")))
            run.append((tok, False, not level))
        elif _noun_break(tok):
            close()
            run = []
        else:
            run.append((tok, _stem(tok.rstrip(".")) not in _GENERIC_FAMILY_WORDS, False))
        prev = tok
    close()
    return out


def _family_own(fam: "GlyphFamily", opening: bool = False) -> _Own:
    return _own_text(fam.name, fam.tags, fam.plan_only, opening)


def _ident_own(ident: str, mark_sources: Dict[str, set],
               fams_of: Dict[str, List["GlyphFamily"]]) -> _Own:
    """A printed mark's own text (_values_by_ident): the mark, the names of
    the schedules whose rows print it, and the own text of every family it
    is a tag of. A schedule named as a whole is its own name."""
    fams = fams_of.get(ident, [])
    parts = [_family_own(f) for f in fams]
    words = list(_own_text("", [], more=[ident] + sorted(mark_sources.get(ident, ()))).words)
    for p in parts:
        words += [w for w in p.words if w not in words]
    return _Own(tuple(words), frozenset({ident}).union(*(p.tags for p in parts)),
                frozenset().union(*(p.names for p in parts)))


def _named_opening_tags(text: str, tags: Iterable[str]) -> List[str]:
    """The door/window types a clause names. A tag of two or more characters
    (D1, W3) as a whole word, as printed - upper case. A ONE-LETTER TYPE
    (A..G) only as "type F", "type-F" or "F-type": as a bare word the
    article "a" / "A" would name door type A in every sentence."""
    out = []
    for t in tags:
        if len(t) > 1:
            rx = _ALNUM_BEFORE + re.escape(t) + _ALNUM_AFTER
        else:
            rx = (r"(?:(?i:\btype)[\s-]+" + re.escape(t) + _ALNUM_AFTER + "|"
                  + _ALNUM_BEFORE + re.escape(t) + r"-(?i:type)\b)")
        if re.search(rx, text or ""):
            out.append(t)
    return out


def glyph_families_for(subject: str, families: Dict[str, Sequence[str]]
                       ) -> Dict[str, List[str]]:
    """schedule name -> its tags, for every family the subject may be asking
    about: one of its tags is named, or one of its distinguishing words is.

    Deliberately WIDE. Fetching a family the question did not mean costs a
    census; missing one the question did mean would let a clause name a family
    the gate cannot see, which is how 'fans' could be bound to one schedule
    while the other was out of view."""
    words = {_stem(w) for w in re.findall(r"[A-Za-z]{2,}", subject or "")}
    out: Dict[str, List[str]] = {}
    for name, tags in (families or {}).items():
        tags = sorted({str(t).strip().upper() for t in (tags or []) if t})
        if not tags:
            continue
        if _named_tags(subject, tags) or (family_words(name) & words):
            out[name] = tags
    return out


def opening_families_for(subject: str, families: Dict[str, Sequence[str]]
                         ) -> Dict[str, List[str]]:
    """glyph_families_for, for the door and window schedules: a lettered type
    is named only as "type X" (_named_opening_tags) - "a unit" never fetches
    door type A."""
    words = {_stem(w) for w in re.findall(r"[A-Za-z]{2,}", subject or "")}
    out: Dict[str, List[str]] = {}
    for name, tags in (families or {}).items():
        tags = sorted({str(t).strip().upper() for t in (tags or []) if t})
        if tags and (_named_opening_tags(subject, tags) or (family_words(name) & words)):
            out[name] = tags
    return out


def _mark_sources(records: Sequence[Dict[str, Any]]) -> Dict[str, set]:
    """mark -> the schedules whose rows print it (by schedule name, as
    plan_glyph_pass.families keys them). A mark printed only by a schedule
    with no identifier column lends that schedule's numbers to nothing."""
    out: Dict[str, set] = {}
    for r in records or []:
        if r.get("record_type") != "schedule":
            continue
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        name = str(payload.get("name") or "").strip().upper()
        for row in payload.get("rows") or []:
            if isinstance(row, list) and row:
                mark = re.sub(r"\s+", " ", str(row[0] or "")).strip().upper()
                if any(ch.isalpha() for ch in mark):
                    out.setdefault(mark, set()).add(name)
    return out


def unreconciled_families_for(subject: str, names: Iterable[str]) -> List[str]:
    """The schedules with no identifier column (lib.plan_set_health,
    FAMILY_NOT_RECONCILED) the subject names by one of their words."""
    words = {_stem(w) for w in re.findall(r"[A-Za-z]{2,}", subject or "")}
    return sorted(n for n in names or [] if family_words(n) & words)


def _set_health(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records or [] if r.get("record_type") == "set_health"]


def render_set_health(records: Sequence[Dict[str, Any]]) -> str:
    """What the agent is shown of the set's health (lib.plan_set_health):
    the families it cannot count, tags it found that no schedule lists, tags
    it never located, mentions in notes, and the sheets the set refers to
    but does not hold."""
    items = _set_health(records)
    if not items:
        return ""
    lines = ["Drawing-set health (what the set says about its own completeness):"]
    for h in sorted(items, key=lambda h: (str(h.get("kind")), str(h.get("subject")), str(h.get("sheet")))):
        kind, detail = h.get("kind"), h.get("detail") or ""
        if kind == "family_not_reconciled":
            lines.append(f"- {detail} - state no count of these.")
        elif kind == "plan_tag_not_in_schedule":
            lines.append(f"- {detail} - state no count of {h.get('subject')}.")
        elif kind == "missing_referenced_sheet":
            lines.append(f"- warning: {detail}.")
        else:
            lines.append(f"- {detail}.")
    return "\n".join(lines)


#: rows (payload.kind) and censuses (scope) of the doors-and-windows pass
#: (lib.plan_openings) - kept apart from the mechanical symbols' everywhere:
#: an equipment census never counts an opening row, nor the reverse.
OPENING = "opening"


def _row_kind(r: Dict[str, Any]) -> Optional[str]:
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    return payload.get("kind")


def _kind_clause(scope: Optional[str]) -> Any:
    return OPENING if scope == OPENING else {"$ne": OPENING}


def glyph_family_filter(project_id: str, page_ids: Sequence[str],
                        family: str, tags: Sequence[str],
                        track: Optional[str] = None,
                        scope: Optional[str] = None) -> Dict[str, Any]:
    """Every glyph row of one family on the project's current pages: rows
    carrying one of its tags, and rows the pass ran for it that could not
    name themselves - of one drawing track, when `track` is given (rows of
    EMIT_VERSION 7 carry one) - and of the doors-and-windows pass only when
    `scope` is OPENING, never otherwise. `glyph_in_census` is the same
    predicate in Python."""
    flt = {"project_id": str(project_id), "page_id": {"$in": list(page_ids)},
           "record_type": "glyph", "tier": _GLYPH_TIER,
           "$or": [{"label": {"$in": list(tags)}}, {"payload.family": family}],
           "payload.kind": _kind_clause(scope)}
    if track is not None:
        flt["payload.track"] = track
    return flt


def glyph_refusal_filter(project_id: str, page_ids: Sequence[str],
                         track: Optional[str] = None,
                         scope: Optional[str] = None) -> Dict[str, Any]:
    """Every sheet the pass refused, on the project's current pages - the
    doors-and-windows pass's when `scope` is OPENING, else the equipment's."""
    flt = {"project_id": str(project_id), "page_id": {"$in": list(page_ids)},
           "record_type": "glyph", "tier": _GLYPH_TIER,
           "glyph_status": _tally.UNSUPPORTED_UNIT,
           "unit": {"$regex": "^sheet:"},
           "payload.kind": _kind_clause(scope)}
    if track is not None:
        flt["payload.track"] = track
    return flt


def glyph_census(kind: str, project_id: str, page_ids: Sequence[str], count: int,
                 family: Optional[str] = None, tags: Sequence[str] = (),
                 qty: Optional[Dict[str, str]] = None,
                 track: Optional[str] = None,
                 plan_only: Optional[Dict[str, Any]] = None,
                 scope: Optional[str] = None,
                 reads: Optional[Dict[str, Sequence[str]]] = None,
                 qty_readings: Optional[Dict[str, Sequence[str]]] = None) -> Dict[str, Any]:
    """What the database said, at question time, about one filter - and, for
    a family, what its schedule's QTY column prints per tag (`qty`, read by
    schedule_quantities), so a building total can be checked against it.
    One per drawing track when the rows carry one (`track`); with `reads`,
    the pages and sheet numbers that track's pass reads
    (server._glyph_track_pages), so a track that does not read a sheet is
    known not to (_unread_by_other_tracks). With `qty_readings`, what the two
    readings of each contested QTY cell said (schedule_quantity_readings) -
    for a reader, never a figure: the gate reads only `qty`."""
    out = {"record_type": GLYPH_CENSUS, "kind": kind,
           "project_id": str(project_id), "page_ids": sorted(map(str, page_ids)),
           "family": family, "tags": sorted(tags), "count": int(count),
           "qty": dict(qty or {})}
    if track is not None:
        out["track"] = track
    if scope is not None:
        out["scope"] = scope
    if plan_only is not None:
        # A PLAN-ONLY FAMILY (lib.plan_only): no schedule lists it; what the
        # set said about it AT QUESTION TIME - which details and notes name
        # it, each tag's own words, and any figure a note prints for a tag.
        out["plan_only"] = {k: plan_only.get(k) for k in
                            ("named_by", "tag_words", "printed", "also", "object")}
    if reads is not None:
        out["reads"] = {"pages": sorted(map(str, reads.get("pages") or ())),
                        "sheets": sorted(map(str, reads.get("sheets") or ()))}
    if qty_readings:
        out["qty_readings"] = {str(t): [str(v) for v in vs] for t, vs in qty_readings.items()}
    return out


def schedule_quantities(payload: Dict[str, Any], tags: Sequence[str]) -> Dict[str, str]:
    """tag -> the cell under the schedule's printed quantity header, as
    printed: a number, or the contested-cell text. Only tags in `tags`; a
    schedule with no quantity column gives {}."""
    payload = payload if isinstance(payload, dict) else {}
    qcols = _quantity_columns(payload)
    want = {str(t).strip().upper() for t in tags}
    out: Dict[str, str] = {}
    if not qcols:
        return out
    for row in payload.get("rows") or []:
        if not isinstance(row, list) or not row:
            continue
        mark = re.sub(r"\s+", " ", str(row[0] or "")).strip().upper()
        if mark in want and qcols[0] < len(row):
            out[mark] = re.sub(r"\s+", " ", str(row[qcols[0]] or "")).strip()
    return out


def schedule_quantity_readings(payload: Dict[str, Any], tags: Sequence[str]
                               ) -> Dict[str, List[str]]:
    """tag -> the two readings of its QTY cell, where they disagree and the
    cell is printed "(readings disagree)" (plan_ocr.read_grid_twice stores
    them in payload.contested_cells: the row's mark, the column, the
    readings). PTAC-2 on M-200.00: ['6', '9']. Only tags in `tags`, only the
    schedule's quantity column."""
    payload = payload if isinstance(payload, dict) else {}
    qcols = _quantity_columns(payload)
    want = {str(t).strip().upper() for t in tags}
    out: Dict[str, List[str]] = {}
    if not qcols:
        return out
    for c in payload.get("contested_cells") or []:
        if not isinstance(c, dict) or c.get("col") != qcols[0]:
            continue
        mark = re.sub(r"\s+", " ", str(c.get("mark") or "")).strip().upper()
        if mark in want:
            out[mark] = [re.sub(r"\s+", " ", str(v)).strip() for v in c.get("readings") or []]
    return out


def glyph_in_census(row: Dict[str, Any], census: Dict[str, Any]) -> bool:
    """`row` satisfies the filter `census` counted. The Python twin of
    glyph_family_filter / glyph_refusal_filter, clause for clause."""
    if (str(row.get("project_id")) != census.get("project_id")
            or str(row.get("page_id")) not in set(census.get("page_ids") or ())
            or row.get("record_type") != "glyph"
            or row.get("tier") != _GLYPH_TIER):
        return False
    if census.get("track") is not None and _row_track(row) != census["track"]:
        return False
    if (census.get("scope") == OPENING) != (_row_kind(row) == OPENING):
        return False
    if census.get("kind") == "refusals":
        unit = row.get("unit")
        return (row.get("glyph_status") == _tally.UNSUPPORTED_UNIT
                and isinstance(unit, str) and unit.startswith("sheet:"))
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return (row.get("label") in (census.get("tags") or ())
            or payload.get("family") == census.get("family"))


def is_glyph_evidence(r: Dict[str, Any]) -> bool:
    """A located-symbol row or its census: evidence ONLY through a scoped,
    complete count. Neither vouches for any number it happens to contain -
    a row's payload holds coordinates, a door width and an RMS, and a census
    holds the count that is the thing being checked."""
    return r.get("tier") == _GLYPH_TIER or r.get("record_type") == GLYPH_CENSUS


def _is_refusal(r: Dict[str, Any]) -> bool:
    unit = r.get("unit")
    return (r.get("glyph_status") == _tally.UNSUPPORTED_UNIT
            and isinstance(unit, str) and unit.startswith("sheet:"))


def _floor_key(sheet: Any) -> Optional[str]:
    m = _PLAN_SHEET.match(str(sheet or "").strip().upper())
    return m.group(2) if m else None


def _row_floor(r: Dict[str, Any]) -> Optional[str]:
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    arch = payload.get("arch") if isinstance(payload.get("arch"), dict) else {}
    return _floor_key(arch.get("sheet_number")) or _floor_key(r.get("sheet_number"))


def _title_level(title: Any) -> Optional[Any]:
    """The level a printed sheet title names: an ordinal, or a level word."""
    t = str(title or "")
    m = _ORDINAL_FLOOR.search(t)
    if m:
        w = m.group(1).lower()
        return _ORDINALS.get(w) or int(re.match(r"\d+", w).group(0))
    m = _NAMED_LEVEL.search(t)
    return m.group(1).lower() if m else None


#: A family's census matched and nothing was located: a fact about the rows
#: in hand, not about whether they are complete (glyph_books).
_NO_LOCATED = "no located symbols"


class GlyphFamily(NamedTuple):
    name: str
    tags: List[str]
    rows: List[Dict[str, Any]]          # its glyph rows in hand, refusals excluded
    why: Optional[str]                  # None when complete
    qty: Dict[str, str] = {}            # tag -> its schedule's QTY cell, as printed
    #: a plan-only family (lib.plan_only): what the set says about it, from
    #: its census - None for a schedule's family
    plan_only: Optional[Dict[str, Any]] = None


class GlyphBook(NamedTuple):
    families: Dict[str, GlyphFamily]
    refused: List[Dict[str, Any]]       # refusal rows in hand
    refusals_complete: bool
    levels: Dict[str, set]              # floor key -> names a clause may use
    titles: Dict[str, str]              # floor key -> how it is printed
    sheets: Dict[str, List[str]]        # floor key -> its sheet numbers
    units: Dict[str, List[str]]         # floor key -> apartment tags
    #: floor key -> {unit: what says it continues on another sheet}, or None
    #: when any row on the floor predates that reading (emit_version < 2).
    multi: Dict[str, Optional[Dict[str, List[str]]]] = {}
    #: floor key -> why its figures are refused: a track's rows of a
    #: mechanical sheet there do not number what the sheet locates
    #: (_invariant, EMIT_VERSION 7).
    invariant: Dict[str, str] = {}
    #: a book of door and window tags (opening_books): a lettered type is
    #: named only as "type X", and a tag or symbol that could not be read on
    #: a floor refuses that family's figures there and building-wide.
    opening: bool = False
    #: the drawing-set questions open on this track (ruling 21,
    #: lib.plan_set_questions): question id -> how the pages are named
    #: ("the A.1.x plans"). Their rows are in the book; which of them count
    #: is not decided.
    questions: Dict[str, str] = {}
    #: None: no reading chosen - with questions open, nothing building-wide
    #: binds from this book (_building_refused). A frozenset: one reading,
    #: the questions whose pages it counts (_reading_book).
    reading: Optional[frozenset] = None


def glyph_book(records: Sequence[Dict[str, Any]]) -> GlyphBook:
    """Every family the census covers, and whether its rows are all in hand."""
    rows, seen = [], set()
    for r in records or []:
        if r.get("tier") != _GLYPH_TIER or r.get("record_type") != "glyph":
            continue
        k = (str(r.get("page_id")), r.get("ordinal"))
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)
    censuses = [r for r in records or [] if r.get("record_type") == GLYPH_CENSUS]
    ref_c = [c for c in censuses if c.get("kind") == "refusals"]
    row_tracks = {_row_track(r) for r in rows}
    fam_c: Dict[str, List[Dict[str, Any]]] = {}
    for c in censuses:
        if c.get("kind") == "family" and c.get("family"):
            fam_c.setdefault(c["family"], []).append(c)
    unread = {n for n, cs in fam_c.items()
              if len(_unread_by_other_tracks(cs, rows, row_tracks)) < len(cs)}
    if any(isinstance(c.get("plan_only"), dict) for c in censuses) or unread:
        # beside a plan-only family, or a family whose sheets the other
        # tracks do not read, one track's rows and a census per track
        # (_plan_only_censuses, _unread_by_other_tracks): the other tracks'
        # refusals must be none too
        ref_c = _one_track(ref_c, row_tracks)
    refused = [r for r in rows if _is_refusal(r)]
    refusals_complete = (len(ref_c) == 1 and sum(
        1 for r in rows if glyph_in_census(r, ref_c[0])) == ref_c[0].get("count"))

    families: Dict[str, GlyphFamily] = {}
    for name, cs in fam_c.items():
        cs = _plan_only_censuses(cs, row_tracks)
        if name in unread:
            cs = _unread_by_other_tracks(cs, rows, row_tracks)
        c = cs[0]
        mine = [r for r in rows if glyph_in_census(r, c)]
        located = [r for r in mine if not _is_refusal(r)]
        tags = list(c.get("tags") or [])
        why = None
        if len(cs) != 1:
            why = "two censuses for one schedule"
        elif len(mine) != c.get("count"):
            why = f"{len(mine)} of {c.get('count')} rows in hand"
        elif not refusals_complete:
            why = "the sheets the pass refused are not all in hand"
        elif any(r.get("glyph_status") == _tally.RESOLVED
                 and (r.get("label") not in tags
                      or (r.get("payload") or {}).get("family") != name)
                 for r in located):
            # A row whose tag is not in today's schedule, or that was run
            # from another one: the pass and the schedule disagree.
            why = "a row's tag and its schedule disagree"
        elif not any(r.get("glyph_status") == _tally.RESOLVED for r in located):
            why = _NO_LOCATED
        po = c.get("plan_only") if isinstance(c.get("plan_only"), dict) else None
        if po is not None and why is None:
            why = _plan_only_why(mine, po)
        families[name] = GlyphFamily(name, tags, located, why,
                                     dict(c.get("qty") or {}), po)

    levels: Dict[str, set] = {}
    titles: Dict[str, str] = {}
    sheets: Dict[str, List[str]] = {}
    units: Dict[str, List[str]] = {}
    multi: Dict[str, Optional[Dict[str, List[str]]]] = {}
    for r in rows:
        k = _row_floor(r)
        if k is None:
            continue
        names = levels.setdefault(k, set())
        lvl = _title_level(r.get("sheet_title"))
        if lvl is not None:
            names.add(lvl)
            titles.setdefault(k, str(r.get("sheet_title") or ""))
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        arch = payload.get("arch") if isinstance(payload.get("arch"), dict) else {}
        for s in (r.get("sheet_number"), arch.get("sheet_number")):
            if s and s not in sheets.setdefault(k, []):
                sheets[k].append(s)
        for u in ((payload.get("units") or {}).get("tags") or []):
            if u not in units.setdefault(k, []):
                units[k].append(u)
        # FAIL CLOSED (operator ruling 2026-10-07): one row on the floor that
        # never read the evidence makes the whole floor unknown.
        ml = (payload.get("units") or {}).get("multi_level")
        if not isinstance(ml, dict):
            multi[k] = None
        elif multi.get(k, {}) is not None:
            merged = multi.setdefault(k, {})
            for u, ev in ml.items():
                merged.setdefault(str(u), [])
                merged[str(u)] += [e for e in (ev or []) if e not in merged[str(u)]]
    return GlyphBook(families, refused, refusals_complete, levels, titles,
                     sheets, units, multi)


# ══════════════════════════════════════════════════════════════════════════
# Two drawing tracks (ruling 2026-10-24)
# ══════════════════════════════════════════════════════════════════════════
#
# On 588 Boyland the filed AR set governs and the Owner's set (6/9/26) is the
# owner's post-CO additions - a second track, not a revision. The pass places
# every mechanical symbol once PER TRACK (plan_glyph_pass, EMIT_VERSION 7),
# so the gate reads:
#   TOTALS      a floor or the building counts each mechanical symbol ONCE,
#               whatever the track - each sheet's rows from one track, the
#               filed where it has them;
#   CENSUSES    per track: each track's rows are checked against the
#               database on their own;
#   INVARIANT   on every floor, each track's located rows of a family on a
#               mechanical sheet must number what that sheet's sweep locates
#               (payload.mech_count). A floor where one does not has its
#               totals refused - and that track's per-apartment figures
#               there - and it is logged;
#   APARTMENTS  per track, then: AGREE -> stated once; DIFFER -> both
#               stated, each labelled, and a claim binds only if it NAMES its
#               set and matches it; ONE TRACK ONLY -> that figure, labelled
#               (ruling 2026-10-24 on the owner's set: label, don't refuse).

log = logging.getLogger(__name__)

_FILED = "filed"
_FILED_LABEL = "the filed set"
_SET_WORD = r"(?:AR\s+)?(?:set|drawings?|plans?|track)"
#: A claim that names its set: "in the filed set", "per the owner's set",
#: "per the owner's post-CO set, 6/9/26". The date of a label goes with it.
_TRACK_CLAIM = {
    _FILED: re.compile(r"(?:\b(?:per|in|on|from|according\s+to)\s+)?(?:\bthe\s+)?"
                       r"\bfiled\s+" + _SET_WORD + r"\b"
                       r"(?:[\s,(]+\d{1,2}/\d{1,2}/\d{2,4}\)?)?", re.I),
    "post_co": re.compile(r"(?:\b(?:per|in|on|from|according\s+to)\s+)?(?:\bthe\s+)?"
                          r"(?:\bowner'?s'?\s+(?:post-?CO\s+)?|\bpost-?CO\s+)" + _SET_WORD
                          + r"\b(?:[\s,(]+\d{1,2}/\d{1,2}/\d{2,4}\)?)?", re.I),
}


def _row_track(r: Dict[str, Any]) -> Optional[str]:
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    return payload.get("track")


#: How a set's name reads once its date is gone (_undated_set_names).
_SET_NAME = {_FILED: "in the filed set", "post_co": "per the owner's set"}


def _undated_set_names(text: str) -> str:
    """Every set's name in `text` as one dateless phrase, BEFORE the answer
    is split into clauses: the splitter cuts at the comma of "per the
    owner's post-CO set, 6/9/26" and the date would be a clause of bare
    numbers."""
    for t, rx in _TRACK_CLAIM.items():
        text = rx.sub(" " + _SET_NAME[t], text)
    return text


# ── A FILE'S NAME AND A SET'S LABEL ARE CITATIONS, NEVER FIGURES ──────────
#
# #892 shows the model each record's file and drawing set ("A-302 (owner's
# set) · 588 Boyland Arch 7.2.pdf p3"), and a well-cited answer repeats them.
# The gate read their digits as claims - "7.2" and "588" were figures no
# record vouched for - and refused correct answers (spatial session,
# 2026-10-28). So, before any figure is read, every file name the evidence
# carries is removed AS TEXT, and every set label becomes its set's bare
# name (_SET_PLAIN, which _TRACK_CLAIM reads with the answer's own "per" /
# "in" in front of it), so a claim naming a set still binds only against
# that set's rows (_track_claim). A label replaced by a whole phrase left a
# second "per" behind, which reads as a per-unit scope. Exactly as _citation_texts: their digits are
# never whitelisted - "There are 588 PTAC units" must still bind on its own
# - and a name with no letter in it is never removed (a file called "588"
# names nothing a reader could tell from a count).
#
# WHAT IS REMOVED IS ONLY WHAT CANNOT BE PROSE OR SCOPE. Removing words can
# move a figure's scope: with a file "Apartment 4A.pdf", stripping
# "Apartment 4A" turned "Apartment 4A has 9 WH-1." from refused into a
# building figure that bound (Codex, #910). So only a file's WHOLE name,
# ".pdf" and all, is removed - never its bare stem - and a set label only
# when it carries a digit (only digits were ever the problem); and no name
# or label carrying a scope word (_SCOPE_WORD: apartment, unit, floor,
# level, a "4A"-style unit) is ever removed. An answer citing one is
# refused as before, which is the safe way to be wrong.

#: A set's bare name, for a label said in its place.
_SET_PLAIN = {_FILED: "filed set", "post_co": "owner's set"}


def _cited_name(v: Any) -> str:
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v if len(v) >= 3 and re.search(r"[A-Za-z]", v) else ""


#: A word that says WHERE in the building: a citation carrying one is never
#: removed, since removing it could widen a figure's scope.
_SCOPE_WORD = re.compile(
    r"\b(?:apt|apartments?|units?|floors?|fl|levels?|lvl|stor(?:y|ey|ies)|cellar|"
    r"basement|roof|penthouse|mezzanine|duplex|rooms?|suites?|\d+(?:st|nd|rd|th)|"
    r"\d{1,3}[A-Z])\b", re.I)


def _file_name_forms(name: Any) -> List[str]:
    """A file's name as an answer may cite it: whole, ".pdf" and all. Never
    the bare stem, and never a name that carries a scope word."""
    whole = _cited_name(name)
    if not whole or not whole.lower().endswith(".pdf"):
        return []
    if _SCOPE_WORD.search(whole[:-4]):
        return []
    return [whole]


def source_citations(records: Sequence[Dict[str, Any]],
                     sources: Iterable[Dict[str, Any]] = ()) -> Tuple[List[str], List[Tuple[str, str]]]:
    """(file-name forms, [(set label, its track)]), longest first. From each
    record's own file_name and arch set label, and from `sources`
    (plan_sources.source_of rows: file_name, track, label)."""
    names: set = set()
    labels: Dict[str, str] = {}
    for r in records or []:
        names.update(_file_name_forms(r.get("file_name")))
        a = ((r.get("payload") or {}).get("arch") or {}) if isinstance(r.get("payload"), dict) else {}
        lab, tr = _cited_name(a.get("drawing_track_label")), a.get("drawing_track")
        if lab and tr in _SET_PLAIN and re.search(r"\d", lab) and not _SCOPE_WORD.search(lab):
            labels.setdefault(lab, tr)
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        names.update(_file_name_forms(src.get("file_name")))
        lab, tr = _cited_name(src.get("label")), src.get("track")
        if lab and tr in _SET_PLAIN and re.search(r"\d", lab) and not _SCOPE_WORD.search(lab):
            labels.setdefault(lab, tr)
    return (sorted(names, key=len, reverse=True),
            sorted(labels.items(), key=lambda kv: len(kv[0]), reverse=True))


def strip_source_citations(text: str, records: Sequence[Dict[str, Any]],
                           sources: Iterable[Dict[str, Any]] = ()) -> str:
    """`text` with every set label said as its set's phrase and every file
    name removed: what the gate reads figures from."""
    names, labels = source_citations(records, sources)
    for lab, tr in labels:
        text = re.sub(_ALNUM_BEFORE + re.escape(lab) + _ALNUM_AFTER, " " + _SET_PLAIN[tr] + " ",
                      text, flags=re.I)
    return _strip_citations(text, names)


def _track_claim(clause: str) -> Tuple[frozenset, str]:
    """(the drawing tracks the clause names, the clause without those names).
    A set's name is where a figure comes from, never a figure: its date is
    removed with it."""
    named = set()
    for t, rx in _TRACK_CLAIM.items():
        if rx.search(clause):
            named.add(t)
            clause = rx.sub(" ", clause)
    return frozenset(named), clause


class GlyphBooks(NamedTuple):
    totals: GlyphBook                       # every mechanical symbol once
    tracks: Dict[Optional[str], GlyphBook]  # per drawing track
    labels: Dict[Optional[str], str]        # how the render names each


def _invariant(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[Optional[str], str], str]:
    """{(track, floor key): why} for every floor where a track's located rows
    of a family on a mechanical sheet do not number what that sheet's sweep
    locates (payload.mech_count) - or where the sheet's rows disagree about
    that number. Rows that carry no mech_count (before EMIT_VERSION 7) are
    not checked."""
    want: Dict[Tuple[str, Any], set] = {}
    have: Dict[Tuple[Optional[str], str, Any], int] = {}
    on: Dict[str, set] = {}
    floor: Dict[Tuple[Optional[str], str], Optional[str]] = {}
    for r in rows:
        p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        page, t = str(r.get("page_id")), _row_track(r)
        on.setdefault(page, set()).add(t)
        floor.setdefault((t, page), _row_floor(r))
        if "label_at" not in p:
            continue                    # a refusal, not a located label
        fam = p.get("family")
        if p.get("mech_count") is not None:
            want.setdefault((page, fam), set()).add(p["mech_count"])
        have[(t, page, fam)] = have.get((t, page, fam), 0) + 1
    out: Dict[Tuple[Optional[str], str], str] = {}
    for (page, fam), ns in want.items():
        for t in on.get(page, ()):
            n = have.get((t, page, fam), 0)
            if len(ns) == 1 and n == next(iter(ns)):
                continue
            k = floor.get((t, page)) or page
            why = (f"{fam}: {n} located on the {t or 'single'} track against "
                   f"{' / '.join(map(str, sorted(ns)))} on its mechanical sheet")
            out[(t, k)] = why
            log.warning("glyph two-track invariant: floor %s - %s", k, why)
    return out


def _track_label(t: Optional[str], rows: Sequence[Dict[str, Any]]) -> str:
    if t in (None, _FILED):
        return _FILED_LABEL
    for r in rows:
        a = (r.get("payload") or {}).get("arch") or {}
        if _row_track(r) == t and a.get("drawing_track") == t and a.get("drawing_track_label"):
            return a["drawing_track_label"]
    return f"the {t} set"


def glyph_books(records: Sequence[Dict[str, Any]]) -> GlyphBooks:
    """The totals book, a book per drawing track, and their labels. Rows
    of one track - or of none, before EMIT_VERSION 7 - give one book that is
    all three, as before."""
    # THE MECHANICAL SYMBOLS ONLY: door and window tags are opening_books'.
    records = [r for r in records or [] if not _is_opening_record(r)]
    rows = [r for r in records or [] if r.get("tier") == _GLYPH_TIER
            and r.get("record_type") == "glyph"]
    censuses = [r for r in records or [] if r.get("record_type") == GLYPH_CENSUS]
    # THE TRACKS ARE THE ROWS'. A census that names none counts every
    # track's rows (glyph_in_census): beside one track it is that track's;
    # beside two it counts both, matches neither, and refuses - fail closed.
    tracks = sorted({_row_track(r) for r in rows} or {c.get("track") for c in censuses},
                    key=lambda t: (t != _FILED, str(t)))
    inv = _invariant(rows)
    if len(tracks) <= 1:
        book = glyph_book(records)
        book = book._replace(invariant={k: w for (_t, k), w in inv.items()})
        t = tracks[0] if tracks else None
        return GlyphBooks(book, {t: book}, {t: _track_label(t, rows)})
    per: Dict[Optional[str], GlyphBook] = {}
    for t in tracks:
        b = glyph_book([r for r in rows if _row_track(r) == t]
                       + [c for c in censuses if c.get("track") in (t, None)])
        per[t] = b._replace(invariant={k: w for (tt, k), w in inv.items() if tt == t})
    # EACH MECHANICAL SHEET'S ROWS FROM ONE TRACK: the filed where it has any
    on: Dict[str, set] = {}
    for r in rows:
        on.setdefault(str(r.get("page_id")), set()).add(_row_track(r))
    gov = {p: (_FILED if _FILED in ts else sorted(ts, key=str)[0]) for p, ts in on.items()}
    chosen = [r for r in rows if _row_track(r) == gov[str(r.get("page_id"))]]
    synth: List[Dict[str, Any]] = []
    for c in censuses:
        if c.get("track") not in (tracks[0], None):
            continue                    # one per kind and family, as counted below
        c2 = {k: v for k, v in c.items() if k != "track"}
        c2["count"] = sum(1 for r in chosen if glyph_in_census(r, c2))
        synth.append(c2)
    totals = glyph_book(chosen + synth)
    fams = {}
    for name, fam in totals.families.items():
        why = fam.why
        for t, b in per.items():
            # A TRACK THAT DOES NOT COVER A SHEET DOES NOT VETO ITS TOTAL:
            # M-106.00 (the bulkhead, SAF-1's only sheet) is read by the
            # filed track alone, so the owner's track locates no SAF-1. Only
            # a track's incompleteness refuses the totals.
            f = b.families.get(name)
            why = why or (f.why if f and f.why != _NO_LOCATED else None
                          if f else f"no census of the {t} track")
        fams[name] = fam._replace(why=why)
    totals = totals._replace(
        families=fams,
        refusals_complete=all(b.refusals_complete for b in per.values()),
        invariant={k: w for (_t, k), w in inv.items()})
    return GlyphBooks(totals, per, {t: _track_label(t, rows) for t in tracks})


def _is_opening_record(r: Dict[str, Any]) -> bool:
    if r.get("record_type") == GLYPH_CENSUS:
        return r.get("scope") == OPENING
    return r.get("record_type") == "glyph" and _row_kind(r) == OPENING


def _apartment_clause(clause: str, books: GlyphBooks) -> bool:
    """The clause states a per-apartment figure: it names a unit some track
    has, or a per-unit share."""
    return bool(_PER_UNIT.search(clause)) or any(
        _clause_units(clause, b)[0] for b in books.tracks.values())


def _blocking(r: Dict[str, Any]) -> bool:
    """A REFUSED SHEET BLOCKS A COUNT ONLY IF IT COULD CARRY THE SYMBOLS
    (operator ruling 2026-10-07). The pass writes the role; an architectural
    sheet with no mechanical partner - the second set's A.1.x, an unnumbered
    roof plan - carries no mechanical symbol a total could miss. A refusal
    row with no role (written before emit_version 3) blocks: fail closed."""
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    # A plan-only family's plan (lib.plan_only) carries no mechanical symbol
    # either: refused, it blocks its own family (_plan_only_why), no other.
    return payload.get("role") not in ("architectural", "plan_only")


def _refused_floors(book: GlyphBook) -> set:
    return ({k for k in (_row_floor(r) for r in book.refused if _blocking(r)) if k}
            | set(book.invariant))


def _blocking_refusals(book: GlyphBook) -> List[Dict[str, Any]]:
    return [r for r in book.refused if _blocking(r)]


def _building_refused(book: GlyphBook) -> bool:
    # THE SET IS NOT DECIDED (ruling 21): a book holding the rows of an open
    # drawing-set question states no building figure of its own - only its
    # readings do, where they agree (_agreed_values).
    return (bool(_blocking_refusals(book)) or not book.refusals_complete
            or bool(book.invariant) or (bool(book.questions) and book.reading is None))


def _resolved(fam: GlyphFamily, tags: Sequence[str]) -> List[Dict[str, Any]]:
    return [r for r in fam.rows
            if r.get("glyph_status") == _tally.RESOLVED and r.get("label") in tags]


def _floor_count(book: GlyphBook, fam: GlyphFamily, tags: Sequence[str],
                 k: str) -> Optional[int]:
    if fam.why or k in _refused_floors(book):
        return None
    if book.opening and any(_unread(r) and _row_floor(r) == k for r in fam.rows):
        return None                     # a tag or symbol there named nothing
    n = sum(1 for r in _resolved(fam, tags) if _row_floor(r) == k)
    return n or None                    # zero rows never binds


def _qty_check(fam: GlyphFamily, tags: Sequence[str], n: int) -> Tuple[str, Optional[int]]:
    """("agrees" | "disagrees" | "unreadable" | "no_column", the QTY sum).

    THE SCHEDULE'S QTY IS THE STRONGEST CROSS-CHECK THERE IS (operator,
    2026-10-07): on 588 Boyland the located building totals of PTAC-1/2/3,
    WH-1 and SAF-1 each equal the QTY their schedule prints. A total that
    DISAGREES is not stated - neither number is - and the disagreement is
    said. A QTY cell that cannot be read (PTAC-2's is contested: two
    readings, 6 and 9) is not a disagreement; the total stands, unchecked."""
    if not fam.qty or not all(t in fam.qty for t in tags):
        return "no_column", None
    vals = []
    for t in tags:
        v = fam.qty[t]
        if not re.fullmatch(r"\d+", v or ""):
            return "unreadable", None
        vals.append(int(v))
    total = sum(vals)
    return ("agrees" if total == n else "disagrees"), total


#: A per-apartment phrase: "each unit", "every apartment", "per floor".
#: Narrower than _PER_UNIT on purpose - "21 PTAC-1 per the schedule" is a
#: building figure with its source, not a per-unit claim.
_PER_APARTMENT = re.compile(
    r"\b(each|every|per)\s+(?:\w+\s+)?(unit|units|apartment|apartments|apt|dwelling|"
    r"dwellings|room|rooms|floor|floors|level|levels|storey|storeys|story)\b|\bapiece\b",
    re.I)


def _building_scope(clause: str, book: GlyphBook) -> bool:
    """The clause names no floor, no unit and no per-apartment share - and no
    level or unit that maps to nothing. Only such a clause may state a
    figure that is printed for the whole building."""
    keys, floor_unknown = _clause_floors(clause, book)
    units, unit_unknown = _clause_units(clause, book)
    return not (keys or floor_unknown or units or unit_unknown
                or _PER_APARTMENT.search(clause))


def _qty_in_clause(clause: str, book: GlyphBook) -> Tuple[set, set]:
    """(QTY figures the clause may state, QTY figures it may not), for every
    tag it names that has a readable QTY cell.

    TWO RULINGS (operator, 2026-10-10), so the model is never told one thing
    while the gate accepts another:
      (a) NOTHING LOCATED, QTY PRINTED: the QTY stands. DH-1's schedule prints
          QTY 1 and the pass locates none (its label reads "DH-1. DUCT
          HEATER"): "There is 1 DH-1." binds, from the census's reading of
          that cell even when the schedule record itself did not come back.
      (b) BOTH EXIST AND DISAGREE: the QTY is withheld too. A complete located
          building count that differs from the printed QTY binds neither
          number - in the gate as well as the render. Withheld only where the
          located count can be called complete: the family's census matched
          and nothing that could carry the symbols was refused.
    An unreadable cell (PTAC-2: "(readings disagree)") is neither: it adds
    nothing and withholds nothing."""
    add, drop = set(), set()
    # A SCHEDULE'S QTY IS A BUILDING FIGURE: it is added only to a clause at
    # building scope. ("The bulkhead has 1 DH-1." is not what the schedule says.)
    building = _building_scope(clause, book)
    for fam in book.families.values():
        # ruling 71: "There is 1 DH-1 water heater." names no DH-1
        own_noun = not foreign_words(clause, _family_own(fam))
        for t in _named_tags(clause, fam.tags):
            q = fam.qty.get(t) or ""
            if not re.fullmatch(r"\d+", q):
                continue
            n_t = len(_resolved(fam, [t]))
            if n_t == 0:
                if building and own_noun:
                    add.add(q)
            elif not fam.why and not _building_refused(book) and int(q) != n_t:
                drop.add(q)
    return add, drop


def _unread(r: Dict[str, Any]) -> bool:
    return r.get("glyph_status") in (_tally.UNREAD, _tally.CONTESTED)


def _building_count(book: GlyphBook, fam: GlyphFamily,
                    tags: Sequence[str]) -> Optional[int]:
    if fam.why or _building_refused(book):
        return None
    if book.opening and any(_unread(r) for r in fam.rows):
        return None
    n = len(_resolved(fam, tags))
    if not n:
        return None
    if _qty_check(fam, tags, n)[0] == "disagrees":
        return None
    return n


def _continues(book: GlyphBook, k: str) -> Optional[Dict[str, List[str]]]:
    """{unit: evidence it continues on another sheet} for floor k, or None
    when the floor's rows never read it."""
    return book.multi.get(k) if k in book.multi else None


#: The link a stair writes between a duplex's two sheets
#: (plan_glyph_pass.seed_from_stairs): the lower unit's stair "reaches" the
#: upper plan, and the upper unit was "seeded from" the lower one - or, where
#: the upper plan names its own units, was "linked from" it (ruling
#: 2026-10-24, plan_glyph_pass.link_refusal).
_LEVEL_LINK = re.compile(r"\b(?:reaches|seeded from|linked from) ([A-Z]-\d{3}\.\d{2})\b")


def _apartment_floors(book: GlyphBook, u: str) -> Optional[List[str]]:
    """The floors one apartment spans, by following the links its evidence
    names - or None when they cannot be followed to the end.

    A unit nothing says continues is its one floor. A unit that continues
    must NAME where (a LOWER word or an unlinked stair says only that it
    goes on somewhere), every floor it names must list it, and every floor
    that lists the tag must be reached - a tag on two unlinked floors is two
    apartments or a mistake, never one apartment."""
    start = sorted(k for k, us in book.units.items() if u in (us or []))
    if not start:
        return None
    seen: set = set()
    todo = [start[0]]
    while todo:
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        cont = _continues(book, k)
        if cont is None or u not in (book.units.get(k) or []):
            return None
        ev = cont.get(u) or []
        links = [_floor_key(m) for e in ev for m in _LEVEL_LINK.findall(e)]
        if ev and not links:
            return None                 # it continues, and nothing says where
        if any(lk is None for lk in links):
            return None
        todo.extend(lk for lk in links if lk not in seen)
    if set(start) - seen:
        return None
    return sorted(seen)


def _placed(book: GlyphBook, fam: GlyphFamily, tags: Sequence[str],
            k: str) -> Optional[List[Dict[str, Any]]]:
    """The family's rows of `tags` on floor k when every row there named
    itself and every one of `tags` was placed (a unit or a named non-unit
    space), else None."""
    on = [r for r in fam.rows if _row_floor(r) == k]
    if any(r.get("glyph_status") != _tally.RESOLVED for r in on):
        return None
    mine = [r for r in on if r.get("label") in tags]
    if any(not r.get("unit") or str(r.get("unit")).startswith("sheet:") for r in mine):
        return None
    return mine


def _apartment_count(book: GlyphBook, fam: GlyphFamily, tags: Sequence[str],
                     u: str) -> Optional[int]:
    """THE WHOLE APARTMENT, summed across the sheets its stair links
    (ruling 2026-10-11): only when every linked sheet lists the unit, each
    of those floors is complete for the family (its census matched, nothing
    that could carry the symbols refused), and every symbol there named
    itself and was placed. A unit that continues with no link still
    refuses."""
    floors = _apartment_floors(book, u)
    if not floors:
        return None
    total = 0
    for k in floors:
        if fam.why or k in _refused_floors(book):
            return None
        mine = _placed(book, fam, tags, k)
        if mine is None:
            return None
        total += sum(1 for r in mine if r.get("unit") == u)
    return total


def _track_labels(fam: GlyphFamily, floors: Iterable[str]) -> List[str]:
    """How the render names each NON-FILED drawing track the family's rows on
    `floors` were placed against (payload.arch.drawing_track, EMIT_VERSION 6).

    A PER-APARTMENT FIGURE RESTS ON THE ARCHITECTURAL SHEET IT WAS PLACED
    AGAINST, and on 588 Boyland floors 2 to the mezzanine are placed against
    the Owner's set - the owner's post-CO additions, not the governing filed
    AR set (operator ruling 2026-10-24: label, don't refuse). Floor and
    building totals rest on the mechanical sheets alone and carry no label.
    A row written before the track was read says nothing about it."""
    wanted, out = set(floors), []
    for r in fam.rows:
        if _row_floor(r) not in wanted:
            continue
        a = (r.get("payload") or {}).get("arch") or {}
        tr = a.get("drawing_track")
        if tr and tr != "filed":
            lab = a.get("drawing_track_label") or f"the {tr} set ({a.get('file_name')})"
            if lab not in out:
                out.append(lab)
    return out


def _track_note(book: GlyphBook, fam: GlyphFamily, k: str, units: Iterable[str]) -> str:
    floors = {k}
    for u in units:
        floors |= set(_apartment_floors(book, u) or [])
    labels = _track_labels(fam, floors)
    return f"; these per-apartment figures are per {' and '.join(labels)}" if labels else ""


def _floor_label(book: GlyphBook, k: str) -> str:
    return " / ".join(sorted(book.sheets.get(k) or [])) or k


def _whole_note(book: GlyphBook, units: Iterable[str]) -> str:
    """'; the whole apartment, across A-103.00 / M-103.00 + A-104.00 / M-104.00'
    for the units among `units` that span linked sheets - the render names
    both sheets (ruling 2026-10-11)."""
    spans: Dict[Tuple[str, ...], List[str]] = {}
    for u in units:
        fl = _apartment_floors(book, u) or []
        if len(fl) > 1:
            spans.setdefault(tuple(fl), []).append(u)
    return "".join(f"; {', '.join(us)}: the whole apartment, counted across "
                   f"{' + '.join(_floor_label(book, k) for k in fl)}"
                   for fl, us in spans.items())


def _unit_counts(book: GlyphBook, fam: GlyphFamily, tags: Sequence[str],
                 k: str) -> Optional[Dict[str, int]]:
    """Per apartment on floor k, or None when the split may not be made: the
    floor is not complete, a glyph of the family there cannot name itself or
    its unit, or a symbol could not be placed (plan_tally.per_unit, here at
    floor scope).

    ── A UNIT IS THE WHOLE APARTMENT ──────────────────────────────────────
    #
    # Measured 2026-10-07: "4A has 2 exhaust fans." bound, and 4A is a
    # duplex - A-103.00 prints it LOWER, and its private stair lands on the
    # mezzanine, where M-104.00 gives it a third fan. The mezzanine is
    # refused, so the count was A-103.00's half of the apartment, stated as
    # the apartment. A unit's count is now returned only for a unit the rows
    # say is single-sheet; a unit anything says continues elsewhere is left
    # out, and so is every unit on a floor whose rows never read that
    # (operator ruling: fail closed until the rebuild).
    #
    # ── A DUPLEX IS COUNTED WHOLE WHEN ITS STAIR LINKS ITS SHEETS ──────────
    #
    # Since 2026-10-11 a stair carries its unit to the level it reaches
    # (plan_glyph_pass.seed_from_stairs), and the rows on both sheets name
    # the other. A unit whose links can be followed to every sheet, each
    # complete and placed, gets the WHOLE apartment's count (4A: 2 fans on
    # A-103.00 + 1 on A-104.00 = 3) - on either floor, since a floor named
    # alongside says which units, not which part. A unit that continues
    # with no link is still left out.
    """
    if _floor_count(book, fam, tags, k) is None or not book.units.get(k):
        return None
    cont = _continues(book, k)
    if cont is None:
        return None
    mine = _placed(book, fam, tags, k)
    if mine is None:
        return None
    out: Dict[str, int] = {}
    for u in book.units[k]:
        if not cont.get(u):
            out[u] = sum(1 for r in mine if r.get("unit") == u)
        else:
            v = _apartment_count(book, fam, tags, u)
            if v is not None:
                out[u] = v
    return out


def _per_unit(book: GlyphBook, fam: GlyphFamily, tags: Sequence[str],
              k: str) -> Optional[int]:
    """The figure every apartment on floor k shares - only when EVERY one of
    them is single-sheet. "Each unit on the fourth floor has 2" is read as
    per apartment; a floor named alongside says which units, not which part
    (operator ruling 2026-10-07)."""
    counts = _unit_counts(book, fam, tags, k)
    if counts is None or len(counts) != len(book.units.get(k) or []):
        return None
    return _uniform(counts)


def _uniform(counts: Optional[Dict[str, int]]) -> Optional[int]:
    if not counts:
        return None
    vals = set(counts.values())
    return vals.pop() if len(vals) == 1 and min(counts.values()) > 0 else None


def _clause_floors(clause: str, book: GlyphBook) -> Tuple[set, bool]:
    """(floor keys the clause names, whether it names a level nothing maps
    to). A level that maps to no floor is not 'no floor': it must not fall
    back to the building."""
    keys: set = set()
    unknown = False
    rest = clause
    for m in _ORDINAL_FLOOR.finditer(clause):
        w = m.group(1).lower()
        n = _ORDINALS.get(w) or int(re.match(r"\d+", w).group(0))
        hit = {k for k, names in book.levels.items() if n in names}
        keys |= hit
        unknown |= not hit
    rest = _ORDINAL_FLOOR.sub(" ", rest)
    for m in _NAMED_LEVEL.finditer(rest):
        hit = {k for k, names in book.levels.items() if m.group(1).lower() in names}
        keys |= hit
        unknown |= not hit
    rest = _NAMED_LEVEL.sub(" ", rest)
    for m in _SHEET_REF.finditer(rest):
        k = _floor_key(f"{m.group(1)}-{m.group(2)}.{m.group(3) or '00'}")
        if k is None:
            continue                    # a schedule or detail sheet: a citation
        if k in book.levels or k in book.sheets:
            keys.add(k)
        else:
            unknown = True
    rest = _SHEET_REF.sub(" ", rest)
    if _FLOOR_WORD.search(rest):
        unknown = True                  # 'each floor', 'the upper floors'
    return keys, unknown


def _clause_units(clause: str, book: GlyphBook) -> Tuple[Dict[str, str], bool]:
    """(unit -> its floor key, whether a unit-shaped token names no unit)."""
    text = _ORDINAL_FLOOR.sub(" ", clause)
    text = _SHEET_REF.sub(" ", text)
    found: Dict[str, str] = {}
    unknown = False
    for m in _UNIT_REF.finditer(text):
        tok = m.group(1).upper()
        if re.fullmatch(r"\d{1,2}(ST|ND|RD|TH)", tok):
            continue
        where = [k for k, us in book.units.items() if tok in us]
        span = _apartment_floors(book, tok) if len(where) > 1 else None
        if len(where) == 1:
            found[tok] = where[0]
        elif span and set(where) <= set(span):
            found[tok] = where[0]       # one apartment over linked sheets
        else:
            unknown = True
    return found, unknown


def _clause_subjects(clause: str, book: GlyphBook
                     ) -> Optional[List[Tuple[GlyphFamily, List[str]]]]:
    """[(family, the tags counted)], or None when the clause names a family
    only by words another family shares - 'fans' - which is never a count."""
    # EACH TAG ITS OWN SUBJECT: "4A has 1 EF-1 and 1 EF-2" states two counts
    # of one, not one count of two.
    named = _named_opening_tags if book.opening else _named_tags
    # A COUNT NAMES ITS OWN FAMILY (ruling 71): a tag, or a family's words,
    # in a phrase holding a word that is not the family's own ("WH-1 water
    # heaters", "W1 doors") names nothing of it.
    own = {n: _family_own(f, book.opening) for n, f in book.families.items()}
    tagged = [(fam, [t]) for fam in book.families.values()
              for t in named(clause, fam.tags)
              if not foreign_words(clause, own[fam.name])]
    if tagged:
        return tagged
    words = {_stem(w) for w in re.findall(r"[A-Za-z]{2,}", clause)}
    # A PLAN-ONLY FAMILY IS NAMED BY ITS OBJECT, never by a word it shares
    # with a schedule's name - "roof" is a level, and "the roof has 2
    # exhaust fans" must stay the exhaust-fan schedule's (_plan_only_subjects).
    plan = [s for fam in book.families.values() if fam.plan_only is not None
            and not foreign_words(clause, own[fam.name])
            for s in _plan_only_subjects(words, fam, clause)]
    sched = [n for n, f in book.families.items() if f.plan_only is None]
    hits = {name: family_words(name) & words for name in sched}
    hits = {n: h for n, h in hits.items() if h and not foreign_words(clause, own[n])}
    if not hits:
        return plan
    top = [n for n, h in hits.items() if not any(h < g for g in hits.values())]
    if len(top) != 1:
        return None
    fam = book.families[top[0]]
    return [(fam, list(fam.tags))] + plan


def _plan_only_subjects(words: set, fam: GlyphFamily,
                        clause: str = "") -> List[Tuple[GlyphFamily, List[str]]]:
    """What a clause's words name of a plan-only family: the tags whose own
    words it uses ("overflow" -> RD-2), or a name the set's own note gives
    the tag (ruling 15, 2026-10-28: "J.R. Smith", "detention" -> RD-1; only
    names lib.plan_only.also_names found printed), each its own subject;
    else, when it names the object ("roof drains"), the family as ONE
    subject - a combined total, which _book_values refuses. A clause without
    the object's noun names none of it ("the roof"); nor does one naming
    only the noun ("floor drains")."""
    from lib import plan_only as _po
    po = fam.plan_only or {}
    obj = [_stem(w) for w in re.findall(r"[A-Za-z]{2,}", str(po.get("object") or ""))]
    if not obj or obj[-1] not in words:
        return []
    also = po.get("also") if isinstance(po.get("also"), dict) else {}
    own = [t for t in fam.tags
           if {_stem(w) for w in ((po.get("tag_words") or {}).get(t) or [])} & words
           or any(_po.name_pattern(a).search(clause or "") for a in (also.get(t) or []))]
    if own:
        return [(fam, [t]) for t in own]
    if set(obj) <= words:
        return [(fam, list(fam.tags))]
    return []


def _joined_also_names(text: str, records: Sequence[Dict[str, Any]]) -> str:
    """`text` with each printed other name of a plan-only family's tag
    (census plan_only.also, ruling 15) written without its dots - 'J.R.
    Smith' -> 'JR Smith' - so the clause splitter does not cut it at 'J.R.'
    and leave the figure in a clause that names nothing."""
    from lib import plan_only as _po
    names = {a for c in records or [] if c.get("record_type") == GLYPH_CENSUS
             and isinstance(c.get("plan_only"), dict)
             and isinstance((c["plan_only"] or {}).get("also"), dict)
             for al in c["plan_only"]["also"].values() for a in al or []}
    for a in sorted(names, key=len, reverse=True):
        text = _po.name_pattern(a).sub(lambda m: m.group(0).replace(".", ""), text)
    return text


def _plan_only_censuses(cs: List[Dict[str, Any]], row_tracks: set) -> List[Dict[str, Any]]:
    """A PLAN-ONLY FAMILY'S PLAN IS ON ONE TRACK. search_plans counts every
    family once per drawing track; the roof drains' plan (P-206.00) is the
    filed track's alone, so beside rows of that one track the owner's census
    says 0 - and read as one book, two censuses for one family refused the
    lot. Here the rows' own track's census stands, provided every other
    track's census counted none of the family; anything else stays two
    censuses, and refuses.

    (Found 2026-10-26 emulating the rebuild against production. A schedule
    family on one track has the same shape - SAF-1 on M-106.00 - and is
    ruled apart: _unread_by_other_tracks, item 18.)"""
    if not all(isinstance(c.get("plan_only"), dict) for c in cs):
        return cs
    return _one_track(cs, row_tracks)


def _unread_by_other_tracks(cs: List[Dict[str, Any]], rows: Sequence[Dict[str, Any]],
                            row_tracks: set) -> List[Dict[str, Any]]:
    """A TRACK THAT DOES NOT READ A SHEET DOES NOT VETO THAT SHEET'S FAMILY
    TOTAL (ruling 2026-10-24; item 18, 2026-10-28: "SAF-1 bulkhead refusal
    across sets").

    M-106.00, the bulkhead, has no A-106 on either track, so only the filed
    track's pass reads it (server._glyph_track_pages) and SAF-1's one row is
    the filed track's. Asked about SAF-1, the rows in hand are that one
    track's and the census is per track - the owner's says 0 - and read as
    one book that was "two censuses for one schedule": "The bulkhead has 1
    SAF-1." refused (measured on production 2026-10-28). glyph_books already
    lets such a track stand aside when the rows of both tracks are in hand.

    Here the rows' own track's census stands ONLY when every other track's
    census of the family counted none AND says what that track reads
    (`reads`, glyph_census) AND that track reads none of the pages or sheet
    numbers the family's rows lie on. A track that reads the sheet and
    counts none is a difference between the sets, not a gap - it still
    refuses; so does a census that does not say what its track reads, and a
    family with no rows in hand (nothing to not read). Else all of them."""
    if len(cs) < 2 or len(row_tracks) != 1:
        return cs
    (t,) = row_tracks
    own = [c for c in cs if c.get("track") == t]
    if len(own) != 1:
        return cs
    mine = [r for r in rows if glyph_in_census(r, own[0])]
    if not mine:
        return cs
    for c in cs:
        if c is own[0]:
            continue
        reads = c.get("reads")
        if c.get("count") != 0 or not isinstance(reads, dict):
            return cs
        pages, sheets = set(reads.get("pages") or ()), set(reads.get("sheets") or ())
        if any(str(r.get("page_id")) in pages or not r.get("sheet_number")
               or str(r.get("sheet_number")) in sheets for r in mine):
            return cs
    return own


def _one_track(cs: List[Dict[str, Any]], row_tracks: set) -> List[Dict[str, Any]]:
    """The census of the rows' one track, when every other track's census of
    the same filter counted nothing; else all of them (and the caller refuses)."""
    if len(cs) < 2 or len(row_tracks) != 1:
        return cs
    (t,) = row_tracks
    own = [c for c in cs if c.get("track") == t]
    if len(own) == 1 and all(c.get("count") == 0 for c in cs if c is not own[0]):
        return own
    return cs


def _without_object(clause: str, fam: GlyphFamily) -> str:
    from lib import plan_only as _po
    obj = str((fam.plan_only or {}).get("object") or "").split()
    return _po.object_pattern(obj).sub(" ", clause) if obj else clause


def _plan_level(fam: GlyphFamily) -> Optional[Any]:
    """The level a plan-only family's plan names in its own printed title
    (P-206.00 ROOF SANITARY & STORM PLAN: 'roof'), or None - when its rows
    are on no plan, on more than one, or the title names no level."""
    levels = {_title_level(r.get("sheet_title")) for r in fam.rows}
    sheets = {r.get("sheet_number") for r in fam.rows}
    return next(iter(levels)) if len(levels) == 1 and len(sheets) == 1 else None


def _ordinal_name(n: int) -> str:
    return next((w for w, v in _ORDINALS.items() if v == n), f"{n}th")


def _without_plan_level(clause: str, fam: GlyphFamily) -> str:
    """THE PLAN'S OWN LEVEL IS NO SCOPE (ruling 14, 2026-10-28: "Can 'the
    roof' name where RD-1 and RD-2 are?" - "yes, only the level the plan's
    title names"). The clause less every phrase naming the level the
    family's plan title prints: "The roof has 2 RD-1." is the sheet-scope
    figure, located on P-206.00. Any other level stays in the clause, and
    _sheet_scope_only refuses it ("the fourth floor has 2 RD-1")."""
    lvl = _plan_level(fam)
    if lvl is None:
        return clause
    if isinstance(lvl, int):
        def ordinal(m):
            w = m.group(1).lower()
            n = _ORDINALS.get(w) or int(re.match(r"\d+", w).group(0))
            return " " if n == lvl else m.group(0)
        return _ORDINAL_FLOOR.sub(ordinal, clause)
    return _NAMED_LEVEL.sub(lambda m: " " if m.group(1).lower() == lvl else m.group(0), clause)


def _sheet_scope_only(clause: str, book: GlyphBook) -> bool:
    """The clause names no floor, no unit, no per-unit share, and nothing
    that maps to none of them."""
    keys, floor_unknown = _clause_floors(clause, book)
    units, unit_unknown = _clause_units(clause, book)
    return not (keys or floor_unknown or units or unit_unknown
                or _PER_UNIT.search(clause) or _PER_APARTMENT.search(clause))


def _plan_only_why(rows: Sequence[Dict[str, Any]], po: Dict[str, Any]) -> Optional[str]:
    """Why a plan-only family's located rows count for nothing, or None:
    no detail or note names it now; a label beside one of them could not be
    read as its tag (it could be any of them); or rows on more than one plan
    (the ruling is one plan, at sheet scope)."""
    if not po.get("named_by"):
        return "no detail or note in the set names it"
    if any(_is_refusal(r) for r in rows):
        return "its plan could not be read"
    if any(r.get("glyph_status") != _tally.RESOLVED for r in rows):
        return "a label beside one of them could not be read as its tag"
    if len({r.get("sheet_number") for r in rows}) > 1:
        return "located on more than one plan"
    return None


def _plan_only_count(book: GlyphBook, fam: GlyphFamily, tag: str) -> Optional[int]:
    """ONE TAG of a plan-only family at sheet scope: its located count, when
    the family is complete and no note's printed figure for the tag
    disagrees. A DISAGREEMENT WITHHOLDS BOTH (ruling 2026-10-26): the located
    count is not stated, and the printed figure lends nothing anywhere."""
    if fam.why or _building_refused(book):
        return None
    n = sum(1 for r in fam.rows if r.get("label") == tag
            and r.get("glyph_status") == _tally.RESOLVED)
    if not n:
        return None
    printed = ((fam.plan_only or {}).get("printed") or {}).get(tag) or []
    if any(str(p.get("value")) != str(n) for p in printed):
        return None
    return n


def glyph_values(clause: str, book) -> set:
    """The located-symbol counts this one clause may state - from one book,
    or from the two-track books (glyph_books).

    A CLAIM THAT NAMES A SET binds only against rows carrying that track -
    at every scope, from that track's own book - and never against rows that
    carry none (ruling 2026-10-24). Rows written before EMIT_VERSION 7 are
    one MIXED set: on 588 Boyland floor 1 and the roof were placed against
    the filed set and floors 2 to the mezzanine against the owner's. Read as
    either set they bind the other's figures - "1A has 1 PTAC per the
    owner's post-CO set" bound 1 where the owner's set holds 2. A clause
    naming two sets refuses: a figure cannot be checked against both.

    A claim naming no set:
      a floor or building figure  from the totals: each symbol once;
      a per-apartment figure      per track - the tracks must AGREE; if they
                                  differ nothing binds; if one track alone
                                  has a figure, it binds (label, don't
                                  refuse - the render names its set)."""
    named, bare = _track_claim(clause)
    if isinstance(book, GlyphBook):
        return set() if named else _book_values(clause, book)
    books: GlyphBooks = book
    if named:
        if len(named) != 1:
            return set()
        (t,) = named
        b = books.tracks.get(t)
        return _book_values(bare, b) if b is not None else set()
    if len(books.tracks) <= 1:
        return _book_values(bare, books.totals)
    if not _apartment_clause(bare, books):
        return _book_values(bare, books.totals)
    # A ZERO IS AN ANSWER HERE, though never a bound figure: the filed 1A
    # holds no PTAC-1 and the owner's holds one - the sets DIFFER, and the
    # owner's 1 is not "one track only".
    vals = [v for v in (_book_values(bare, b, zero=True) for b in books.tracks.values()) if v]
    if not vals:
        return set()
    return set(vals[0]) - {"0"} if all(v == vals[0] for v in vals) else set()


def _book_values(clause: str, book: GlyphBook, zero: bool = False) -> set:
    """The located-symbol counts this one clause may state, from one book.

    Scope, most specific first: named units; 'each/every/per' (a uniform
    per-apartment figure) on the floors named, or across the building when
    none is; named floors; else the building. A clause naming a level or a
    unit that maps to nothing gets nothing - it must not borrow a wider
    scope's figure."""
    out: set = set()
    subjects = _clause_subjects(clause, book)
    if not subjects:
        return out
    keys, floor_unknown = _clause_floors(clause, book)
    named_units, unit_unknown = _clause_units(clause, book)
    for fam, tags in subjects:
        if fam.plan_only is not None:
            # PER TAG ONLY, AT SHEET SCOPE (ruling 2026-10-26): a combined
            # total refuses, and so does any floor, unit or per-unit figure -
            # the family is located on its plan and placed nowhere. Its
            # object's name is not a scope: the ROOF of "overflow roof
            # drains" names no level. Nor is the level its plan's own title
            # names (ruling 14, 2026-10-28): "the roof has 2 RD-1".
            if len(tags) == 1 and _sheet_scope_only(
                    _without_plan_level(_without_object(clause, fam), fam), book):
                v = _plan_only_count(book, fam, tags[0])
                if v is not None:
                    out.add(str(v))
            continue
        if floor_unknown or unit_unknown:
            continue
        if named_units:
            for u, k in named_units.items():
                if keys and not (keys & set(_apartment_floors(book, u) or [k])):
                    continue            # '4A on the third floor'
                v = _apartment_count(book, fam, tags, u)
                if v or (zero and v == 0):
                    out.add(str(v))
        elif _PER_UNIT.search(clause):
            if keys:
                for k in keys:
                    v = _per_unit(book, fam, tags, k)
                    if v is not None:
                        out.add(str(v))
            elif not _building_refused(book) and not fam.why:
                per = [_per_unit(book, fam, tags, k)
                       for k in book.units if book.units.get(k)]
                if per and None not in per and len(set(per)) == 1:
                    out.add(str(per[0]))
        elif keys:
            for k in keys:
                n = _floor_count(book, fam, tags, k)
                if n is not None:
                    out.add(str(n))
        else:
            n = _building_count(book, fam, tags)
            if n is not None:
                out.add(str(n))
    return out


def _apartment_text(book: GlyphBook, fam: GlyphFamily, k: str,
                    note: bool = True) -> str:
    """The per-apartment part of floor k's line, from one book. `note` False
    leaves out the owner's-set label (_track_note): the two-track render
    labels figures itself."""
    out = ""
    counts = _unit_counts(book, fam, fam.tags, k)
    cont = _continues(book, k)
    per = _per_unit(book, fam, fam.tags, k)
    if cont is None and book.units.get(k):
        out += ("; per-apartment figures not available (these rows "
                "predate the reading of which units continue on "
                "another sheet)")
    elif per is not None:
        out += (f"; each unit ({', '.join(counts)}) has {per}" + _whole_note(book, counts)
                + (_track_note(book, fam, k, counts) if note else ""))
    elif cont and any(cont.values()) and not counts:
        out += (f"; {', '.join(u for u in book.units[k] if cont.get(u))} "
                f"continue on another sheet, so no per-apartment figure")
    elif counts:
        # A zero is never bound (glyph_values), so it is not printed as
        # a figure either.
        out += ("; per unit " + ", ".join(f"{u} {n}" for u, n in counts.items() if n)) if any(counts.values()) else ""
        out += _whole_note(book, [u for u, n in counts.items() if n])
        if note:
            out += _track_note(book, fam, k, [u for u, n in counts.items() if n])
        none = [u for u, n in counts.items() if not n]
        if none:
            out += f"; none placed in {', '.join(none)}"
        more = [u for u in book.units[k] if (cont or {}).get(u) and u not in counts]
        if more:
            out += (f"; {', '.join(more)} continue on another sheet, "
                    f"so no figure for them")
    else:
        out += "; per-unit split not available"
    return out


def _tracks_apartment_text(books: GlyphBooks, name: str, k: str) -> str:
    """Floor k's per-apartment figures across the drawing tracks: the same
    in every track that has the floor -> stated once, unlabelled; different
    -> both, each with its set, and the reader told to name the set; one
    track only -> that, with its set."""
    have: Dict[Optional[str], Tuple[GlyphBook, GlyphFamily, Dict[str, int]]] = {}
    for t, b in books.tracks.items():
        f = b.families.get(name)
        if f is not None and k in b.sheets:
            have[t] = (b, f, _unit_counts(b, f, f.tags, k) or {})
    if not have:
        return "; per-unit split not available"
    lead = next(iter(have))
    units: List[str] = []
    for b, _f, _c in have.values():
        units += [u for u in b.units.get(k) or [] if u not in units]
    if len(have) > 1 and all(c == have[lead][2] for _b, _f, c in have.values()) \
            and all(_apartment_text(b, f, k, note=False)
                    == _apartment_text(*have[lead][:2], k, note=False)
                    for b, f, _c in have.values()):
        return _apartment_text(*have[lead][:2], k, note=False)
    fmt = lambda v: str(v) if v else "none placed"        # noqa: E731
    agree, differ, alone = [], [], {}
    for u in units:
        vals = {t: c[u] for t, (_b, _f, c) in have.items() if u in c}
        if not vals:
            continue
        if len(vals) == len(have) and len(set(vals.values())) == 1:
            agree.append((u, next(iter(vals.values()))))
        elif len(vals) == 1:
            (t, v), = vals.items()
            alone.setdefault(t, []).append((u, v))
        else:
            differ.append((u, vals))
    out = ""
    if agree:
        out += ("; the sets agree: " + ", ".join(f"{u} {fmt(v)}" for u, v in agree)
                + _whole_note(have[lead][0], [u for u, v in agree if v]))
    for u, vals in differ:
        out += (f"; {u}: " + ", ".join(f"{fmt(v)} per {books.labels[t]}" for t, v in vals.items())
                + f" - THE SETS DIFFER: state {u}'s figure only with the set it is per")
    for t, uv in alone.items():
        out += ("; " + ", ".join(f"{u} {fmt(v)}" for u, v in uv)
                + f" per {books.labels[t]} only" + _whole_note(have[t][0], [u for u, v in uv if v]))
    return out or "; per-unit split not available"


def render_glyph_evidence(records: Sequence[Dict[str, Any]]) -> str:
    """What the agent is shown of the located symbols: per family, per floor,
    only the figures glyph_values would bind, and why the rest are not."""
    books = glyph_books(records)
    book = books.totals
    if not book.families:
        return ""
    two = len(books.tracks) > 1
    refused_k = _refused_floors(book)
    lines = ["Located symbols (each found on the mechanical plan and named by "
             "its schedule's tag). State a figure only at the scope shown, and "
             "never add two schedules together:"]
    if two:
        lines.append("Floor and building figures count each symbol once. "
                     "Per-apartment figures are read against each drawing set ("
                     + "; ".join(books.labels[t] for t in books.tracks)
                     + "): where the sets differ, both are shown - state such a "
                     "figure only in a sentence naming the set it is per.")
    for name in sorted(book.families):
        fam = book.families[name]
        if fam.plan_only is not None:
            lines += _render_plan_only(book, fam)
            continue
        head = f"{name} ({', '.join(fam.tags)})"
        if fam.why:
            # NOTHING LOCATED, QTY PRINTED: THE QTY STANDS (ruling (a),
            # 2026-10-10). The model is told the schedule's figure, which the
            # gate accepts - never "state no count" beside a count it allows.
            printed = [f"{t} {fam.qty[t]}" for t in fam.tags
                       if re.fullmatch(r"\d+", fam.qty.get(t) or "") and int(fam.qty[t]) > 0]
            if printed and not any(_resolved(fam, [t]) for t in fam.tags):
                lines.append(f"{head}: the schedule prints QTY {', '.join(printed)}; "
                             f"its symbols were not located.")
            else:
                lines.append(f"{head}: NOT COUNTED - {fam.why}. State no count of these.")
            continue
        lines.append(f"{head}:")
        floors = sorted({_row_floor(r) for r in fam.rows if _row_floor(r)} | refused_k)
        for k in floors:
            where = " / ".join(sorted(book.sheets.get(k) or [])) or k
            title = book.titles.get(k) or ""
            label = f"{title} [{where}]" if title else f"[{where}]"
            if k in refused_k:
                why = "; ".join(sorted(({str((r.get("payload") or {}).get("refusal") or "")
                                         for r in book.refused if _row_floor(r) == k}
                                        | ({book.invariant[k]} if k in book.invariant else set()))
                                       - {""}))
                lines.append(f"- {label}: not counted ({why})")
                continue
            total = _floor_count(book, fam, fam.tags, k)
            if not total:
                continue
            per_tag = [(t, _floor_count(book, fam, [t], k)) for t in fam.tags]
            per_tag = [(t, n) for t, n in per_tag if n]
            line = f"- {label}: " + ", ".join(f"{t} {n}" for t, n in per_tag)
            if len(per_tag) > 1:
                line += f"; {total} in all"
            line += (_tracks_apartment_text(books, name, k) if two
                     else _apartment_text(book, fam, k))
            lines.append(line)
        if fam.why or _building_refused(book):
            lines.append(f"- Whole building: NOT AVAILABLE - "
                         f"{len(_blocking_refusals(book))} sheet(s) that can carry "
                         f"these symbols were not counted")
            continue
        parts, disagree = [], False
        for t in fam.tags:
            n_t = len(_resolved(fam, [t]))
            st, q = _qty_check(fam, [t], n_t)
            if st == "disagrees" and n_t == 0:
                # ruling (a): none located - the schedule's figure stands
                parts.append(f"{t}: the schedule prints QTY {q}; its symbols were "
                             f"not located")
            elif st == "disagrees":
                disagree = True
                parts.append(f"{t}: located {n_t} but the schedule's QTY prints "
                             f"{q} - THEY DISAGREE; state neither as the total")
            elif st == "agrees":
                parts.append(f"{t} {n_t} (agrees with the schedule's QTY {q})")
            elif st == "unreadable":
                parts.append(f"{t} {n_t} (the schedule's QTY cell cannot be read: "
                             f"{fam.qty.get(t)!r} - not checked)")
            elif n_t:
                parts.append(f"{t} {n_t}")
        n = _building_count(book, fam, fam.tags)
        line = "- Whole building: " + "; ".join(parts)
        if n and len([t for t in fam.tags if _resolved(fam, [t])]) > 1 and not disagree:
            line += f"; {n} in all"
        lines.append(line)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Doors and windows: the tags the architectural plans print (lib.plan_openings)
# ══════════════════════════════════════════════════════════════════════════
#
# THE SAME BINDING RULES AS THE EQUIPMENT, in their own books. A door or
# window tag lives on its track's ARCHITECTURAL sheet - the filed A-101.00
# and the owner's A-101.00 are two pages - so there is no "each symbol once"
# total across tracks: EVERY scope is per track. A claim naming its set binds
# against that track's rows only; a claim naming none binds only when every
# track gives the same figure; where they differ the render states each,
# labelled. A tag or a symbol that could not be read on a floor refuses that
# family's figures there and building-wide (`GlyphBook.opening`), and a plan
# the pass could not read blocks its track's building figures.

def opening_books(records: Sequence[Dict[str, Any]]) -> GlyphBooks:
    """A book per drawing track of the door and window rows (payload.kind
    OPENING) and their censuses (scope OPENING). `totals` is unused: None."""
    rows = [r for r in records or [] if r.get("tier") == _GLYPH_TIER
            and r.get("record_type") == "glyph" and _row_kind(r) == OPENING]
    censuses = [r for r in records or [] if r.get("record_type") == GLYPH_CENSUS
                and r.get("scope") == OPENING]
    tracks = sorted({_row_track(r) for r in rows} or {c.get("track") for c in censuses},
                    key=lambda t: (t != _FILED, str(t)))
    inv = _invariant(rows)
    per: Dict[Optional[str], GlyphBook] = {}
    for t in tracks:
        mine = [r for r in rows if _row_track(r) == t]
        b = glyph_book(mine + [c for c in censuses if c.get("track") in (t, None)])
        qs = {}
        for r in mine:
            q = _question_of(r)
            if q is not None:
                qs.setdefault(q, str((r.get("payload") or {}).get(_SQ_LABEL) or "some plans"))
        per[t] = b._replace(opening=True, questions=qs,
                            invariant={k: w for (tt, k), w in inv.items() if tt == t})
    return GlyphBooks(None, per, {t: _track_label(t, rows) for t in tracks})


# ── THE SET IS NOT DECIDED: count every reading (ruling 21) ───────────────
#
# "The system never decides which drawings belong to a set or which governs.
# ... Until answered, or if no PM/SM exists: never pick one. Answers state
# the difference instead, e.g. 'the filed set has 36 type F doors without
# the A.1.x plans; including them gives N'. Claims bind only where both
# readings agree." (operator, 2026-10-27)
#
# The pass reads the pages of an open question and marks their rows with it
# (lib.plan_set_questions). A READING is a choice of which open questions'
# pages count; each is a book. A figure binds only where EVERY reading gives
# it - or every reading a claim names ("... without the A.1.x plans"). A page
# of a question that could not be read is a refusal in the readings that
# count it: they give nothing, so nothing that depends on it binds.

#: payload keys of a row of an open question (lib.plan_set_questions)
_SQ_KEY, _SQ_LABEL = "set_question", "set_question_label"
#: more open questions than this on one track: 2^n readings are not counted
#: - its building figures refuse, as the undecided book does
MAX_SET_QUESTIONS = 4


def _question_of(r: Dict[str, Any]) -> Optional[str]:
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    q = payload.get(_SQ_KEY)
    return str(q) if q else None


def _reading_book(book: GlyphBook, included: frozenset) -> GlyphBook:
    """The book as one reading counts it: the rows of the questions in
    `included`, and none of the other open questions'."""
    def keep(r):
        q = _question_of(r)
        return q is None or q in included
    fams = {n: f._replace(rows=[r for r in f.rows if keep(r)]) for n, f in book.families.items()}
    return book._replace(families=fams, refused=[r for r in book.refused if keep(r)],
                         reading=frozenset(included))


def _readings(book: GlyphBook) -> Optional[List[GlyphBook]]:
    """Every reading of an undecided book, or None for a decided one."""
    if not book.questions or book.reading is not None:
        return None
    qs = sorted(book.questions)
    if len(qs) > MAX_SET_QUESTIONS:
        return [book]
    import itertools
    return [_reading_book(book, frozenset(c))
            for k in range(len(qs) + 1) for c in itertools.combinations(qs, k)]


def _agreed_values(clause: str, book: GlyphBook,
                   spec: Optional[Dict[str, bool]] = None) -> set:
    """What one book lets the clause state: every reading's values that ALL
    the readings agree on - among the readings `spec` names ({question:
    counted?}, from the clause's own words; a question this book does not
    hold is no reading of it)."""
    rs = _readings(book)
    if rs is None:
        return _book_values(clause, book)
    if spec:
        rs = [b for b in rs if b.reading is None or all(
            (q in b.reading) == inc for q, inc in spec.items() if q in book.questions)]
    out: Optional[set] = None
    for b in rs:
        v = _book_values(clause, b)
        out = v if out is None else (out & v)
    return out or set()


_READING_WORD = (r"(?P<how>without|excluding|not\s+counting|leaving\s+out|"
                 r"including|counting|with)")


def _label_pattern(short: str) -> str:
    """'the A.1.x plans' -> a pattern for 'A.1.x plans' / 'A.1.x sheets' ..."""
    core = re.sub(r"^\s*the\s+", "", short or "", flags=re.I).strip()
    m = re.match(r"^(.*?)\s+(plans?|sheets?|drawings?|pages?)$", core, re.I)
    if m:
        return re.escape(m.group(1)).replace("\\ ", r"\s+") + r"\s+(?:plans?|sheets?|drawings?|pages?)"
    return re.escape(core).replace("\\ ", r"\s+")


def reading_phrases(clause: str, books: "GlyphBooks"
                    ) -> Tuple[Dict[str, bool], str]:
    """({question: counted?}, the clause without those phrases): "without the
    A.1.x plans" -> not counted, "including the A.1.x plans" (or "including
    them", after naming them) -> counted. A phrase naming two readings of
    one question names none."""
    labels: Dict[str, str] = {}
    for b in (books.tracks or {}).values():
        for q, lab in (b.questions or {}).items():
            labels.setdefault(q, lab)
    if not labels:
        return {}, clause
    spec: Dict[str, bool] = {}
    clash: set = set()
    last: Optional[str] = None
    pats = {q: _label_pattern(lab) for q, lab in labels.items()}
    alt = "|".join(f"(?P<q{i}>{pat})" for i, pat in enumerate(pats.values()))
    rx = re.compile(r"\b" + _READING_WORD + r"\s+(?:the\s+)?(?:" + alt
                    + r"|(?P<them>them|those|these))\b", re.I)
    order = list(pats)
    mentions = re.compile("|".join(f"(?:{p})" for p in pats.values()), re.I)

    def one(m):
        nonlocal last
        q = None
        for i, qid in enumerate(order):
            if m.group(f"q{i}"):
                q = qid
        if q is None:
            q = last
        if q is None:
            return m.group(0)
        last = q
        inc = not m.group("how").lower().startswith(("without", "excluding", "not", "leaving"))
        if q in spec and spec[q] != inc:
            clash.add(q)
        spec[q] = inc
        return " "
    # a question named before "them" is what "them" means
    first = mentions.search(clause)
    if first:
        for i, qid in enumerate(order):
            if re.fullmatch(pats[qid], first.group(0), re.I):
                last = qid
    out = rx.sub(one, clause)
    for q in clash:
        spec.pop(q, None)
    return spec, out


_READING_SPLIT = re.compile(r"\s(?:and|or|but|while|whereas)\s", re.I)


def reading_segments(clause: str, books: "GlyphBooks"
                     ) -> List[Tuple[str, Optional[Dict[str, bool]]]]:
    """A clause stating figures of several readings, one segment per
    conjunct, each with its own reading and the set the clause names: "The
    filed set has 36 type F doors without the A.1.x plans and 72 type F doors
    including the A.1.x plans" -> two claims, each checked against its
    reading. A clause naming no reading is itself, unchanged."""
    if not any((b.questions or {}) for b in (books.tracks or {}).values()):
        return [(clause, None)]
    _spec, stripped = reading_phrases(clause, books)
    if stripped == clause:
        return [(clause, None)]          # it names no reading
    named, _bare = _track_claim(clause)
    out: List[Tuple[str, Optional[Dict[str, bool]]]] = []
    # a conjunct with no figure of its own goes with the one before it:
    # "3 type D doors without the A.1.x plans and without the Roof Plan"
    segs: List[str] = []
    for seg in _READING_SPLIT.split(clause):
        if segs and not _values(reading_phrases(seg, books)[1]):
            segs[-1] = segs[-1] + " and " + seg
        elif seg.strip():
            segs.append(seg)
    for seg in segs:
        sp, stripped = reading_phrases(seg, books)
        if len(named) == 1 and not _track_claim(stripped)[0]:
            stripped = stripped + " " + _SET_NAME[next(iter(named))]
        out.append((stripped, sp or None))
    return out


def opening_values(clause: str, books: GlyphBooks,
                   spec: Optional[Dict[str, bool]] = None) -> set:
    """The door/window counts this one clause may state (opening_books).
    On a track whose set is not decided, only what every reading agrees on -
    or every reading `spec` names (reading_segments) - binds."""
    if not books.tracks:
        return set()
    named, bare = _track_claim(clause)
    if named:
        if len(named) != 1:
            return set()
        b = books.tracks.get(next(iter(named)))
        return _agreed_values(bare, b, spec) if b is not None else set()
    vals = [_agreed_values(bare, b, spec) for b in books.tracks.values()]
    if not vals[0] or any(v != vals[0] for v in vals):
        return set()
    return set(vals[0]) - {"0"}


def _type_name(t: str) -> str:
    return f"type {t}" if len(t) == 1 else t


def _opening_items(book: GlyphBook, fam: GlyphFamily) -> List[Tuple[str, str]]:
    """[(key, text)] - one family's figures from one book, only those the
    gate binds, in the order they are shown."""
    out: List[Tuple[str, str]] = []
    refused_k = _refused_floors(book)
    floors = sorted({_row_floor(r) for r in fam.rows if _row_floor(r)} | refused_k)
    for k in floors:
        where = " / ".join(sorted(book.sheets.get(k) or [])) or k
        title = book.titles.get(k) or ""
        label = f"{title} [{where}]" if title else f"[{where}]"
        if k in refused_k:
            why = "; ".join(sorted({str((r.get("payload") or {}).get("refusal") or "")
                                    for r in book.refused if _row_floor(r) == k} - {""}))
            out.append((f"floor {k}", f"{label}: not counted ({why or book.invariant.get(k)})"))
            continue
        if _floor_count(book, fam, fam.tags, k) is None and any(
                _unread(r) and _row_floor(r) == k for r in fam.rows):
            n = sum(1 for r in fam.rows if _unread(r) and _row_floor(r) == k)
            out.append((f"floor {k}", f"{label}: not counted ({n} tag(s) or symbol(s) there "
                                      f"could not be read)"))
            continue
        per_tag = [(t, _floor_count(book, fam, [t], k)) for t in fam.tags]
        per_tag = [(t, n) for t, n in per_tag if n]
        if not per_tag:
            continue
        text = f"{label}: " + ", ".join(f"{_type_name(t)} {n}" for t, n in per_tag)
        if len(per_tag) > 1:
            text += f"; {sum(n for _t, n in per_tag)} in all"
        out.append((f"floor {k}", text))
    units: List[str] = []
    for k in sorted(book.units):
        units += [u for u in book.units[k] if u not in units]
    for u in units:
        per_tag = [(t, _apartment_count(book, fam, [t], u)) for t in fam.tags]
        if not any(per_tag_n for _t, per_tag_n in per_tag):
            continue
        shown = [(t, n) for t, n in per_tag if n]
        held = [t for t, n in per_tag if n is None]
        text = f"{u}: " + ", ".join(f"{_type_name(t)} {n}" for t, n in shown)
        whole = _apartment_count(book, fam, fam.tags, u)
        if whole and len(shown) > 1:
            text += f"; {whole} in all"
        fl = _apartment_floors(book, u) or []
        if len(fl) > 1:
            text += f" (the whole apartment, {' + '.join(_floor_label(book, k) for k in fl)})"
        if held:
            text += f"; {', '.join(_type_name(t) for t in held)}: no per-apartment figure (a tag of that type on the floor was not placed)"
        out.append((f"unit {u}", text))
    if (not fam.why and book.questions and book.reading is None
            and not _building_refused(_reading_book(book, frozenset()))):
        out.append(("building", _undecided_building(book, fam)))
    elif fam.why or _building_refused(book) or any(_unread(r) for r in fam.rows):
        why = (fam.why or (f"{len(_blocking_refusals(book))} plan(s) carrying these tags were "
                           f"not read" if _blocking_refusals(book) or not book.refusals_complete
                           or book.invariant else
                           f"{len(book.questions)} drawing-set questions are open"
                           if book.questions else "a tag or symbol could not be read"))
        out.append(("building", f"Whole building: NOT AVAILABLE - {why}"))
    else:
        parts = [(t, _building_count(book, fam, [t])) for t in fam.tags]
        parts = [(t, n) for t, n in parts if n]
        if parts:
            text = "Whole building: " + ", ".join(f"{_type_name(t)} {n}" for t, n in parts)
            n = _building_count(book, fam, fam.tags)
            if n and len(parts) > 1:
                text += f"; {n} in all"
            out.append(("building", text))
    return out


def _reading_count(b: GlyphBook, fam: GlyphFamily, tags: Sequence[str]) -> Optional[int]:
    """One reading's building count - 0 included - or None when it cannot
    be counted (a page it counts was not read)."""
    if fam.why or _building_refused(b) or any(_unread(r) for r in fam.rows):
        return None
    return len(_resolved(fam, tags))


def _reading_name(book: GlyphBook, inc: frozenset, among: Sequence[str]) -> str:
    return " and ".join(("including " if q in inc else "without ") + book.questions[q]
                        for q in among)


def _undecided_building(book: GlyphBook, fam: GlyphFamily) -> str:
    """THE SET IS NOT DECIDED (ruling 21): what every reading agrees on,
    stated; every other figure stated with its reading, never alone. A
    question whose pages could not be read makes every reading that counts
    them unknown: said once."""
    rs = _readings(book) or [book]
    if len(rs) == 1:
        return (f"Whole building: NOT AVAILABLE - {len(book.questions)} drawing-set questions "
                f"are open")
    unread = sorted({q for r in book.refused for q in [_question_of(r)] if q})
    known = [q for q in sorted(book.questions) if q not in unread]
    shown = [b for b in rs if not (b.reading & set(unread))]
    agree, differ = [], []
    for t in fam.tags:
        got = [(b.reading, _reading_count(b, b.families[fam.name], [t])) for b in shown]
        vals = {v for _r, v in got}
        if len(vals) == 1 and not unread:
            v = next(iter(vals))
            if v:
                agree.append(f"{_type_name(t)} {v}")
            continue
        if len(vals) == 1 and next(iter(vals)) == 0:
            continue                    # none in any reading that can be counted
        parts = [f"{'not known' if v is None else v} {_reading_name(book, r, known + unread)}"
                 for r, v in got]
        parts += [f"not known including {book.questions[q]} (not read)" for q in unread]
        differ.append(f"{_type_name(t)}: " + "; ".join(parts))
    text = "Whole building: " + (", ".join(agree) + " (the same in every reading)"
                                 if agree else "no figure is the same in every reading")
    if differ:
        text += (". THE SET IS NOT DECIDED (a drawing-set question is open): "
                 + " | ".join(differ))
    return text


def render_set_questions(records: Sequence[Dict[str, Any]], books: GlyphBooks) -> List[str]:
    """One line per open drawing-set question: what it asks and whether it
    was asked (the stored question, record_type "set_question")."""
    stored = {str(r.get("_id") or r.get("id")): r for r in records or []
              if r.get("record_type") == "set_question"}
    out: List[str] = []
    for t, b in books.tracks.items():
        for q, short in sorted((b.questions or {}).items()):
            s = stored.get(q) or {}
            asked = [a for a in s.get("asked") or [] if a.get("sent")]
            if s.get("status") == "answered":
                # Recorded after this pass: the rows still read it as open,
                # so the figures stay two readings until the next pass (10-29:
                # "not decided" was said of Q1 while its answer was stored).
                from lib import plan_set_questions as _psq
                said = _psq.answered_phrase(s, books.labels.get(t) or "the set")
                out.append(f"- {s.get('code') + ': ' if s.get('code') else ''}"
                           f"{s.get('label') or short} - answered {said} by "
                           f"{s.get('answered_by_name') or 'the PM'} "
                           f"({s.get('answered_via') or 'WhatsApp'}, "
                           f"{str(s.get('answered_at') or '')[:10]}); it is applied at the next "
                           f"drawing check, so until then every figure that depends on it is "
                           f"still stated with its reading and never alone.")
                continue
            if asked:
                who = ", ".join(f"{a.get('name') or 'the PM'} ({a.get('channel') or 'WhatsApp'}, "
                                f"{str(a.get('at') or '')[:10]})" for a in asked)
                state = f"asked {who}; not answered yet"
            elif s.get("unasked_reason"):
                state = f"not asked: {s['unasked_reason']}"
            else:
                state = "not asked yet"
            label = s.get("label") or short
            out.append(f"- {s.get('code') + ': ' if s.get('code') else ''}{label} - part of "
                       f"{books.labels.get(t) or 'the set'} or not? Not decided: {state}. Until "
                       f"it is answered, every figure that depends on it is stated with its "
                       f"reading and never alone.")
    return out


def render_opening_evidence(records: Sequence[Dict[str, Any]]) -> str:
    """What the agent is shown of the door and window tags: per schedule,
    per floor, per apartment and building-wide, only the figures
    opening_values binds - stated once where every drawing set agrees, and
    each labelled where they differ."""
    books = opening_books(records)
    names = sorted({n for b in books.tracks.values() for n in b.families})
    if not names:
        return ""
    two = len(books.tracks) > 1
    lines = ["Door and window tags (each read on the architectural plan, named by "
             "its door/window schedule, and placed by the door or window drawn beside "
             "it). State a figure only at the scope shown; never add two schedules "
             "together; name a lettered type as 'type X' (e.g. 'type F'):"]
    if two:
        lines.append("Each drawing set is counted on its own ("
                     + "; ".join(books.labels[t] for t in books.tracks)
                     + "). A figure stated without naming a set must hold in every set; "
                       "where the sets differ both are shown - state such a figure only in a "
                       "sentence naming the set it is per.")
    for name in names:
        fams = {t: b.families[name] for t, b in books.tracks.items() if name in b.families}
        head = f"{name} ({', '.join(_type_name(t) for t in next(iter(fams.values())).tags)})"
        bad = [f.why for f in fams.values() if f.why and f.why != _NO_LOCATED]
        if bad:
            lines.append(f"{head}: NOT COUNTED - {bad[0]}. State no count of these.")
            continue
        lines.append(f"{head}:")
        items = {t: dict(_opening_items(books.tracks[t], f)) for t, f in fams.items()}
        keys: List[str] = []
        for t in fams:
            keys += [k for k, _v in _opening_items(books.tracks[t], fams[t]) if k not in keys]
        for key in keys:
            have = {t: it[key] for t, it in items.items() if key in it}
            # THE FIGURES DECIDE, NOT THE SHEET NUMBERS: the filed A-100.01 and
            # the owner's A-100.00 agreeing is one figure, stated once - as the
            # gate binds it unqualified.
            bare = {re.sub(r"\[[^\]]*\]", "[]", v) for v in have.values()}
            if len(have) == len(books.tracks) and len(bare) == 1:
                sheets = []
                for v in have.values():
                    sheets += [m for m in re.findall(r"\[([^\]]*)\]", v)[:1] if m not in sheets]
                v = next(iter(have.values()))
                lines.append("- " + (re.sub(r"\[[^\]]*\]", "[" + " / ".join(sheets) + "]", v, count=1)
                                     if sheets else v))
            else:
                for t, v in have.items():
                    lines.append(f"- per {books.labels[t]}: {v}")
                if two and len(have) == len(books.tracks):
                    lines.append("  (THE SETS DIFFER here: state these figures only with the set "
                                 "they are per)")
                elif two:
                    lines.append("  (only this set gives a figure here: state it only with the "
                                 "set it is per)")
    qlines = render_set_questions(records, books)
    if qlines:
        ex = next(iter(q for b in books.tracks.values() for q in (b.questions or {}).values()))
        lines.append("DRAWING-SET QUESTIONS (ruling 21: the system never decides which drawings "
                     "belong to a set). A figure that differs between readings is stated only "
                     "with its reading, in one sentence naming the set, e.g. 'The filed set has "
                     f"N type F doors without {ex} and M type F doors including {ex}.' - never "
                     "one reading's figure as the count:")
        lines += qlines
    return "\n".join(lines)


def _render_plan_only(book: GlyphBook, fam: GlyphFamily) -> List[str]:
    """A plan-only family's lines (ruling 2026-10-26): per tag, joined by
    '+', labelled where it was located and that no schedule lists it - and
    never a combined total."""
    from lib import plan_only as _po
    po = fam.plan_only or {}
    words = po.get("tag_words") or {}
    also = po.get("also") if isinstance(po.get("also"), dict) else {}

    def _tag(t):
        # ruling 15: the names the set's own note gives the tag, as printed
        said = [" ".join(words[t])] if words.get(t) else []
        if also.get(t):
            said.append("also " + ", ".join(f"'{a}'" for a in also[t]) + ", as its note prints")
        return f"{t} ({'; '.join(said)})" if said else t
    tags = ", ".join(_tag(t) for t in fam.tags)
    named = "; ".join(f"{n.get('where') or n.get('sheet') or n.get('file')} '{n.get('quote')}'"
                      for n in po.get("named_by") or [])
    if fam.why:
        return [f"{fam.name} ({tags}) - plan-only: NOT COUNTED - {fam.why}. "
                f"State no count of these."]
    lab = _po.label(r.get("sheet_number") for r in fam.rows)
    lvl = _plan_level(fam)
    # ruling 14: the one level a figure may name is its plan title's own
    where = (f" - for no floor or unit; the only level it may be said of is the "
             f"{lvl if isinstance(lvl, str) else _ordinal_name(lvl) + ' floor'} (its plan's title)"
             if lvl is not None else " - for no floor, level or unit")
    lines = [f"{fam.name} ({tags}) - plan-only, {lab}. Named in the set by: {named}. "
             f"State each tag's figure on its own{where}; never one total of {fam.name.lower()}:"]
    if _building_refused(book):
        lines.append(f"- NOT AVAILABLE - {len(_blocking_refusals(book))} sheet(s) that can "
                     f"carry located symbols were not counted")
        return lines
    parts, notes = [], []
    for t in fam.tags:
        n = sum(1 for r in fam.rows if r.get("label") == t)
        printed = (po.get("printed") or {}).get(t) or []
        off = [p for p in printed if str(p.get("value")) != str(n)]
        if off:
            notes.append(f"- {t}: located {n}, but {off[0].get('source')} prints "
                         f"{off[0].get('value')} - THEY DISAGREE; state neither")
            continue
        if n:
            parts.append(f"{t} {n}")
        for p in printed:
            notes.append(f"- {p.get('source')} prints {p.get('value')} for {t} - agrees")
    if parts:
        lines.append(f"- {' + '.join(parts)} ({lab})")
    return lines + notes


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
    # So a quantity is checked against the COUNTS of the things its own clause
    # NAMES - a quantity cell, a count read from one, a located-symbol tally
    # (_values_by_ident, glyph_values) - never against any other number a
    # record about them carries (2026-10-07: "10 EF-1" passed on a weight).
    # A clause that names nothing states a quantity of nothing, which is the
    # exact shape of an invented count, and it is refused.
    #
    # RESIDUE, recorded rather than papered over: a clause that names two marks
    # may borrow either one's numbers. Splitting further would break dimensions
    # like "12 and 1/2 inches", and the narrower rule is the one that can be
    # explained to somebody holding the drawing.
    """
    by_ident = _values_by_ident(records)
    books = glyph_books(records)
    book = books.totals
    obooks = opening_books(records)
    unreconciled = [h.get("subject") for h in _set_health(records)
                    if h.get("kind") == "family_not_reconciled"]
    mark_sources = _mark_sources(records)
    fams_of: Dict[str, List[GlyphFamily]] = {}
    for b in [book] + list(obooks.tracks.values()):
        for f in b.families.values():
            for t in f.tags:
                fams_of.setdefault(str(t).strip().upper(), []).append(f)
    # A DRAWING SET'S NAME IS A CITATION: "per the owner's post-CO set,
    # 6/9/26" says where a figure comes from - its date lends nothing.
    citations = sorted(set(_citation_texts(records)) | {
        l for l in list(books.labels.values()) + list(obooks.labels.values()) if len(l) >= 3}, key=len, reverse=True)
    # A DRAWING-SET QUESTION'S PAGES ARE NAMED, NOT COUNTED (ruling 21):
    # "the A.1.x plans" carries a 1 that is no figure.
    citations = sorted(set(citations) | {l for b in obooks.tracks.values()
                                         for l in (b.questions or {}).values() if len(l) >= 3},
                       key=len, reverse=True)
    unsupported: List[str] = []
    # "1,970 sq ft" is one figure: with area rows in hand the thousands comma
    # is not a clause break (_areas.join_thousands). Without them, unchanged.
    if any(_areas.is_area_record(r) for r in records or []):
        text = _areas.join_thousands(text)
    # "J.R. Smith" is one name (ruling 15), not a clause break at "J.R.":
    # only with a plan-only family's printed names in hand. Without, unchanged.
    text = _joined_also_names(text, records)
    segments = [seg for c in _clauses(_undated_set_names(text))
                for seg in reading_segments(c, obooks)]
    for clause, spec in segments:
        # A citation in the clause is removed as text before its numbers are
        # read (_citation_texts): '[M-200.00]' and 'issued 8/18/2026' say
        # where, and lend nothing to what is counted.
        named, bare = _track_claim(clause)
        said = _values(_strip_citations(bare, citations))
        if not said:
            continue
        # A FAMILY WITH NO IDENTIFIER COLUMN IS NOT COUNTED (PR 5, ruling
        # 2026-10-26): its schedule's rows are no closed tag set, so nothing
        # was checked against the plans. A clause about one - and about no
        # family or tag that WAS reconciled - binds nothing; the reason is in
        # render_set_health. ("PTAC units" stays the PTAC schedule's even
        # though an OCR table is named "PTAC-1".)
        named_marks = _idents_named_in(bare, by_ident.keys())
        sources = set().union(*(mark_sources.get(m, set()) for m in named_marks)) if named_marks else set()
        about_unreconciled = (bool(unreconciled_families_for(bare, unreconciled))
                              or bool(sources and sources <= set(unreconciled)))
        about_reconciled = (_clause_subjects(bare, book) != [] or bool(sources - set(unreconciled))
                            or any(_clause_subjects(bare, b) != [] for b in obooks.tracks.values()))
        if about_unreconciled and not about_reconciled:
            unsupported.extend(said)
            continue
        if named:
            # A CLAIM NAMING A SET binds only against that track's rows
            # (glyph_values) - never a printed QTY, which is no track's, and
            # never on untracked rows.
            allowed = glyph_values(clause, books) | opening_values(clause, obooks, spec)
            if _areas.is_area_clause(bare):
                a_add, a_drop = _areas.figures_in_clause(bare, records, named)
                allowed = (allowed - a_drop) | a_add
            unsupported.extend(v for v in said if v not in allowed)
            continue
        allowed: set = set()
        for ident in _idents_named_in(clause, by_ident.keys()):
            # A PRINTED COUNT NAMES ITS OWN THING TOO (ruling 71): the mark,
            # in a phrase of the words of the schedules that print it and of
            # the families it is a tag of - "9 WH-1 water heaters" is not
            # WH-1's QTY 9.
            if foreign_words(clause, _ident_own(ident, mark_sources, fams_of)):
                continue
            allowed |= by_ident[ident]
        # ── A PRINTED COUNT IS A BUILDING FIGURE ───────────────────────────
        #
        # Every counting source _values_by_ident lends is a schedule's QTY
        # cell, or an element count read from one - a figure for the whole
        # building. It bound in ANY clause naming the mark: measured on 588
        # Boyland 2026-10-10, 80 wrong answers across PTAC-1 21, PTAC-3 11,
        # WH-1 9 and DH-1 1 - "The fourth floor has 21 PTAC-1.", "4A has 9
        # WH-1.", "Each unit on the second floor has 11 PTAC-3." So a printed
        # count binds only at building scope; a floor or unit figure comes
        # from the located symbols (glyph_values, added below) or not at all.
        if not _building_scope(bare, book):
            allowed = set()
        # THE SCHEDULE'S QTY AND THE LOCATED COUNT AGREE, OR NEITHER IS SAID
        # (_qty_in_clause). Applied to the printed figures BEFORE the located
        # ones are added below, so a floor figure that happens to equal a
        # withheld QTY is still allowed at its own scope.
        qty_add, qty_drop = _qty_in_clause(bare, book)
        allowed = (allowed - qty_drop) | qty_add
        # A LOCATED SYMBOL'S COUNT IS ITS CARDINALITY, NOT A PRINTED DIGIT.
        # A schedule cell prints `21` and the record carries it. Eight
        # registered-glyph records carry no `8` anywhere — the eight IS how
        # many of them there are, so it has to be counted here or the gate
        # refuses a figure it fully supports.
        #
        # `glyph_tallies` returns nothing for a tag whose glyphs include one
        # that could not name itself, or whose scope includes a unit that was
        # never registered. So an unbindable total never reaches `allowed`
        # and the clause stating it is refused, while the resolved part stays
        # available through its own smaller total.
        # WHAT IS ALLOWED IS THE RESOLVED COUNT, NOT THE TOTAL.
        #
        # Seven fans that each named themselves support the figure 7, whether
        # or not an eighth glyph sits there unread. What the unread one
        # removes is 8 — a number resting on a record that does not know what
        # it is. So `resolved` is bound and nothing above it is, which is the
        # difference between "7 located, 1 more unread" and a silent 7 or a
        # confident 8.
        #
        # AND ONLY WHEN EVERY ROW IS IN HAND, AT THE SCOPE THE CLAUSE NAMES.
        # This counted whatever rows the search returned, and the search
        # returns eight: "There are 2 EF-1." was allowed with 16 in the
        # database (2026-10-06). glyph_values binds a figure only when the
        # rows in hand equal an independent census, and only at a scope -
        # unit, floor, building - nothing refused falls inside.
        allowed |= glyph_values(clause, books)
        # DOORS AND WINDOWS: their own books, every scope per drawing track
        allowed |= opening_values(clause, obooks, spec)
        # AN AREA AGREES WITH WHAT IS PRINTED, OR NEITHER IS SAID
        # (lib.plan_areas, ruling 2026-10-26, like the QTY above): a measured
        # area binds only where the plan prints one that agrees, and a
        # printed one the measurement contradicts is withheld.
        if _areas.is_area_clause(bare):
            a_add, a_drop = _areas.figures_in_clause(bare, records)
            allowed = (allowed - a_drop) | a_add
        unsupported.extend(v for v in said if v not in allowed)
    return (not unsupported), unsupported


# ══════════════════════════════════════════════════════════════════════════
# A printed value binds only to the subject its record names
# ══════════════════════════════════════════════════════════════════════════
#
# ── WHY THE UNION WAS NOT ENOUGH FOR AN ATTRIBUTE EITHER ──────────────────
#
# An attribute answer kept the union: a value bound if ANY returned record
# printed it. Measured 2026-10-27: "The ceiling height is 10'-0"." bound on
# A-300.00, which prints the floor-to-floor level marks and never the word
# CEILING; asked "ceiling height" on production, 13 printed values bound as
# the ceiling height - 1'-4" out of A-500.00's partition table, 1/2" out of
# "1/2" METAL FLUSHED ON THE CEILING". The drawings show no ceiling height.
#
# Ruling 2026-10-27 (operator): a printed value binds only when its record
# names the claim's subject or one of its alternative names.
#
#   THE CLAIM'S SUBJECT is what its clause says before the value - "the
#   ceiling height is 10'-0"" is about the ceiling height - in the words the
#   search reads (search_terms: the stop words out), a citation removed
#   first - and ONLY those words (ruling 2026-10-28, 6): what follows the
#   value is not required ("the parapet is 42" high" binds on 42" PARAPET),
#   and it never stands in for a subject either. A clause that names nothing
#   before its value - "a 42" parapet" - states a value of nothing, and it is
#   refused, as a count naming nothing is.
#
#   ITS RECORD NAMES IT when EVERY one of those words is printed where the
#   value is: as a word (term_pattern - the plural, a truncation with its
#   period, the CONVENTIONS contractions), or as an alternative name. "1/2"
#   METAL FLUSHED ON THE CEILING" names the ceiling and not its height.
#
#   WHERE THE VALUE IS. A schedule is a grid, and its record is the whole
#   grid: A-500.00's partition table prints CEILING in one type's cell and
#   FULL HEIGHT in another, so read as one record it "names" a ceiling
#   height it never states. So a schedule cell is named by the grid's own
#   name and headers, and by its row when a column of the grid is its
#   identifier (a row is then one thing - EF-1, DH-1); without one, by the
#   cell alone. Any other record is named by what it prints (_printed: the
#   quote, its subject terms, its payload name - never a vision label).
#
#   AN ALTERNATIVE NAME is an abbreviation the set's own abbreviations table
#   defines (abbreviation_table) - GA. = GAUGE on S-002.00 - and it names
#   only in the drawings of the file that prints that table, and only where
#   the value's own record prints it.
#
# What this does not touch: a count (_count_answer_is_bound), an area clause
# (lib.plan_areas decides those first, as before), and every intent other
# than "attribute", which keep the union.

#: An abbreviation as a table prints it: one token, no space.
_ABBREV_TOKEN = re.compile(r"^[A-Za-z0-9#Ø/&'.\-]{1,8}$")
#: A meaning: words, at least one letter, no colon (a colon is a heading).
_ABBREV_MEANING = re.compile(r"^[A-Z][A-Z0-9 /&'().,\-]*$")
_ABBREV_HEADING = re.compile(r"^\s*(?:GENERAL\s+)?ABBREVIATIONS?\s*:?\s*$", re.I)


def abbreviation_table(raw_text: str) -> Dict[str, List[str]]:
    """abbreviation -> its meanings, read off a page's text layer where it
    prints an ABBREVIATIONS list as alternating lines (S-002.00: "GA." then
    "GAUGE"). The list ends at the first pair that is not one - a heading
    ("GRAVITY LOADS:") or a line with a space where the abbreviation stands.
    "ELEVATION OR ELEVATOR" and "FEET/FOOT" are two meanings each."""
    out: Dict[str, List[str]] = {}
    lines = [ln.strip() for ln in (raw_text or "").splitlines()]
    i = 0
    while i < len(lines):
        if not _ABBREV_HEADING.match(lines[i]):
            i += 1
            continue
        i += 1
        while i + 1 < len(lines):
            ab, mean = lines[i], lines[i + 1]
            if not (_ABBREV_TOKEN.match(ab) and _ABBREV_MEANING.match(mean)
                    and any(c.isalpha() for c in mean)):
                break
            for m in re.split(r"\s+OR\s+|/", mean):
                m = m.strip()
                if m and m.upper() != ab.upper() and m not in out.setdefault(ab, []):
                    out[ab].append(m)
            i += 2
    return out


def _alias_pairs(table: Dict[str, List[str]]) -> List[Tuple[str, List[str]]]:
    """(abbreviation, the meaning's words) for every meaning, longest first."""
    pairs = [(ab, search_terms(m)) for ab, ms in (table or {}).items() for m in ms]
    return sorted([p for p in pairs if p[1]], key=lambda p: -len(p[1]))


def _abbrev_printed(ab: str, text: str) -> bool:
    """The abbreviation exactly as its table prints it, as a whole token."""
    return bool(re.search(_ALNUM_BEFORE + re.escape(ab) + _ALNUM_AFTER, text or ""))


def names_subject(text: str, words: Sequence[str],
                  table: Optional[Dict[str, List[str]]] = None) -> bool:
    """Does `text` print every one of `words`, each as a word or through an
    alternative name (`table`: abbreviation -> meanings) printed in `text`?"""
    if not words:
        return False
    left = list(words)
    for ab, mw in _alias_pairs(table or {}):
        n = len(mw)
        for k in range(len(left) - n + 1):
            if all(set(term_forms(a)) & set(term_forms(b))
                   for a, b in zip(left[k:k + n], mw)) and _abbrev_printed(ab, text):
                del left[k:k + n]
                break
    return all(_rx(w).search(text or "") for w in left)


def _scalars(v: Any) -> List[str]:
    """The strings `_supported_values` reads out of one payload value."""
    if isinstance(v, (str, int, float)):
        return [str(v)]
    out: List[str] = []
    if isinstance(v, list):
        for item in v:
            if isinstance(item, (str, int, float)):
                out.append(str(item))
            elif isinstance(item, list):
                out.extend(str(c) for c in item)
    return out


def value_parts(record: Dict[str, Any]) -> List[Tuple[List[str], str]]:
    """(the texts a value may be read from, the text that names what they
    are), part by part. The value texts are what `_supported_values` and
    plan_dimensions.record_texts read; only the naming is narrowed."""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    rows = payload.get("rows")
    if (record.get("record_type") != "schedule" or not isinstance(rows, list)
            or not any(isinstance(row, list) and row for row in rows)):
        texts = [str(record.get("quote") or "")]
        for v in payload.values():
            texts += _scalars(v)
        return [(texts, " | ".join(_printed(record)))]
    cols = payload.get("columns") or []
    headers = [str((c.get("header") if isinstance(c, dict) else c) or "") for c in cols]
    ident = [i for i, c in enumerate(cols) if isinstance(c, dict) and c.get("role") == "identifier"]
    grid = " | ".join([str(payload.get("name") or "")] + headers
                      + [str(t) for t in (record.get("subject_terms") or [])])
    # The grid as a whole - its quote, its name and headers, the payload's
    # other fields - is named by its name and headers alone.
    whole = [str(record.get("quote") or "")] + headers
    for k, v in payload.items():
        if k not in ("rows", "columns"):
            whole += _scalars(v)
    parts: List[Tuple[List[str], str]] = [(whole, grid)]
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        cells = [str(c if c is not None else "") for c in row]
        if ident:
            parts.append((cells, grid + " | " + " | ".join(cells)))
        else:
            parts.extend(([c], grid + " | " + c) for c in cells)
    return parts


def _claim_subject(clause: str, spans: Sequence[Tuple[int, int]]) -> List[str]:
    """The words a clause says its values are OF: the words before its first
    value, and only those.

    WHAT FOLLOWS THE VALUE IS NEVER THE SUBJECT (ruling 2026-10-28, 6). This
    read the words after the last value when none stood before it, for "a
    42" parapet". With counts decided by the count rule (states_a_count) it
    named the subject of no census claim (167,746 claims, 0 changes without
    it), and in the ceiling phrasing probe it bound 84 wrong ceiling heights:
    "A 5/8" ceiling." on A-302.00's "1 HOUR FIRE RATED CEILING W/ ONE LAYER
    OF 5/8" GYPSUM BOARD". "A 42" parapet." is now refused; "The parapet is
    42"." binds."""
    if not spans:
        return []
    return search_terms(clause[:min(s for s, _ in spans)])


# ── A COUNT IS NEVER AN ATTRIBUTE'S VALUE ─────────────────────────────────
#
# Measured 2026-10-28 on #894: 282 count claims bound under intent=attribute
# - "The roof has 13 EF-1." on P-400.00's HWRP-1 row (ROOF MECH ROOM, 13
# GPM), the subject being the word before the value - and with the
# attribute's own word kept in the subject (option B) 108 more: "The first
# floor has 8 exhaust fans." on Z-001.01's ZONING ANALYSIS, which names
# FIRST FLOOR. A record naming the floor is no count of the fans on it.
#
# Ruling 2026-10-28 (operator): a count claim never binds through the value
# path. A count binds only from a counting source - a census-checked located
# tally, a schedule QTY at its scope, a printed figure as earlier rulings
# allow - which is what _count_answer_is_bound reads. So an attribute clause
# that states a count is decided by that rule, and by nothing else.
#
# A CLAUSE STATES A COUNT when a bare number - not a dimension, not a number
# with a unit of measure (_UNIT_VALUE) - is followed by what it numbers: up
# to the first stop word, a phrase holding a mark (a word with a letter and
# a digit, as the count rule's idents have: EF-1, PTAC-2, A2; or "type F"),
# or ending in a plural ("8 exhaust fans", "36 type F doors"), or any thing
# at all after a 1 ("1 exhaust fan"). A magnitude word (ASKING_WORDS: "42
# high") is a measurement's, not a count's. "PTAC-1: 21." states its value
# after the subject and is an attribute's shape; it keeps the value path.
_COUNT_WORD = r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*"
_COUNTED = re.compile(
    r"(?<![A-Za-z0-9.\-/])(\d[\d,]*(?:\.\d+)?)[ \t]+(" + _COUNT_WORD
    + r"(?:[ \t]+" + _COUNT_WORD + r")*)")


def _is_mark(word: str) -> bool:
    return any(c.isalpha() for c in word) and any(c.isdigit() for c in word)


def _counted_phrases(clause: str) -> List[Tuple[str, List[str]]]:
    """(number, the words it numbers) for every count-shaped number in the
    clause (its dimensions and set names already blanked): a bare number,
    not one with a unit of measure, followed by a phrase up to the first stop
    word that holds a mark or "type X", ends in a plural, or follows a 1."""
    out: List[Tuple[str, List[str]]] = []
    for m in _COUNTED.finditer(clause or ""):
        if _UNIT_VALUE.match(clause, m.start()):
            continue
        words = []
        for w in m.group(2).split():
            if w.lower() in _STOP:
                break
            words.append(w)
        if not words or (words[0].lower() in ASKING_WORDS and words[0].lower() != "type"):
            continue
        low = [w.lower() for w in words]
        if (any(_is_mark(w) for w in words)
                or any(a == "type" and b for a, b in zip(low, low[1:]))
                or _is_plural(low[-1])
                or m.group(1).rstrip(".") == "1"):
            out.append((m.group(1), words))
    return out


def _is_plural(word: str) -> bool:
    """The gate's own plural: term_forms has a shorter form of the word."""
    w = (word or "").lower()
    return w.isalpha() and any(len(f) < len(w) for f in term_forms(w))


def states_a_count(clause: str) -> bool:
    """Does this clause (its dimensions and set names already blanked) state
    a number OF things - a count - rather than a value of something?"""
    return bool(_counted_phrases(clause))


# ── A FAMILY'S COUNT IS THE COUNT RULE'S, UNDER EVERY INTENT ──────────────
#
# Ruling 51 (Roy, 2026-10-28, verbatim): "a clause whose subject is a plural
# noun matching a reconciled family or tag family ("exhaust fans", "PTACs",
# "doors", "roof drains") followed by a bare integer routes to the count rule
# under every intent; it never takes the value path. A singular tag or a
# value with a unit ("PTAC-1: 9000", "EF-1: 50 CFM") stays on the value path."
#
# THE FAMILIES ARE THE ONES THE COUNT RULE KNOWS, from the records in hand
# (_count_families): the located-symbol families (glyph_books, plan-only ones
# among them), the door and window books (opening_books), every schedule with
# an identifier or quantity column (its name, its rows' marks), and the
# families set health says are not reconciled (the count rule refuses those).
# A plural is matched to a family the way the count rule and the search match
# one - its stem among the family's words (family_words) - or a tag of the
# family is named beside it ("PTAC-1 units"). A plural no family in hand
# names is not covered.
#
# Two shapes: "exhaust fans: 13." / "The exhaust fans are 13." (the family
# plural before a bare integer), and "The building has 13 exhaust fans." /
# "There are 13 EF-1." (a bare integer before the family plural, or before a
# mark - a mark is a tag whatever the records). Under intent=attribute every
# count-shaped clause routes (states_a_count, ruling 50).


def _count_families(records: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    """name -> tags, for every family the count rule can know from these
    records."""
    fams: Dict[str, set] = {}
    books = glyph_books(records)
    obooks = opening_books(records)
    for b in [books.totals, *books.tracks.values(), *obooks.tracks.values()]:
        if b is None:
            continue
        for name, fam in b.families.items():
            fams.setdefault(str(name).upper(), set()).update(str(t).upper() for t in fam.tags or [])
    for r in records or []:
        if r.get("record_type") != "schedule":
            continue
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        roles = set()
        for c in payload.get("columns") or []:
            if isinstance(c, dict):
                roles.add(c.get("role") if c.get("role") is not None else column_role(c.get("header") or ""))
            else:
                roles.add(column_role(str(c or "")))
        if not roles & {"identifier", "quantity"}:
            continue
        name = str(payload.get("name") or "").strip().upper()
        mine = fams.setdefault(name, set())
        for row in payload.get("rows") or []:
            if isinstance(row, list) and row:
                mark = re.sub(r"\s+", " ", str(row[0] or "")).strip().upper()
                if _is_mark(mark):
                    mine.add(mark)
    for h in _set_health(records):
        if h.get("kind") == "family_not_reconciled" and h.get("subject"):
            fams.setdefault(str(h["subject"]).upper(), set())
    return {n: sorted(t) for n, t in fams.items() if n}


def _names_a_family(words: Sequence[str], fams: Dict[str, List[str]]) -> bool:
    """Is the phrase's plural head one of a family's words, or is a tag of
    the family named beside a plural head?"""
    if not words or not _is_plural(words[-1]):
        return False
    head = _stem(words[-1])
    # A generic head ("PTAC units", "door types") is named by the words before it.
    heads = {head} | ({_stem(w) for w in words[:-1]} if head in _GENERIC_FAMILY_WORDS else set())
    phrase = " ".join(words)
    for name, tags in fams.items():
        if heads & family_words(name) or (tags and _named_tags(phrase, tags)):
            return True
    return False


_PHRASE_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")


def states_a_family_count(clause: str, fams: Dict[str, List[str]]) -> bool:
    """Ruling 51: does the clause (dimensions and set names blanked) state a
    bare integer of a family the records know - its plural before the
    integer, or after it - or a bare integer of a mark?"""
    c = clause or ""
    vals = list(_VALUE_RE.finditer(c))
    if not vals or any("." in m.group(0).rstrip(".") for m in vals):
        return False
    if any(_UNIT_VALUE.match(c, m.start()) for m in vals):
        return False
    before = [w for w in _PHRASE_WORD.findall(c[:vals[0].start()]) if w.lower() not in _STOP]
    if _names_a_family(before, fams):
        return True
    for _n, words in _counted_phrases(c):
        if any(_is_mark(w) for w in words) or _names_a_family(words, fams):
            return True
    return False


def _route_counts(text: str, records: Sequence[Dict[str, Any]], every: bool,
                  families: Optional[Dict[str, Sequence[str]]] = None
                  ) -> Tuple[str, List[str]]:
    """(the text with every count clause blanked, what the count rule refuses
    in them). `every`: route every count-shaped clause (intent=attribute,
    ruling 50); else only a family's or a mark's (ruling 51). A clause with a
    dimension, or an area clause with area rows in hand, is left as before."""
    source = _areas.join_thousands(text or "")
    masked = _dims.mask_quotation_marks(source)
    hold = list(masked)
    for f in _dims.find(masked):
        hold[f.span[0]:f.span[1]] = "\x00" * (f.span[1] - f.span[0])
    hold_s = "".join(hold)
    has_areas = any(_areas.is_area_record(r) for r in records or [])
    citations = _citation_texts(records)
    fams: Optional[Dict[str, List[str]]] = None
    out = list(source)
    bad: List[str] = []
    for c0, c1 in _clause_spans(hold_s):
        if "\x00" in hold_s[c0:c1]:
            continue
        _named, bare = _track_claim(hold_s[c0:c1])
        if has_areas and _areas.is_area_clause(bare):
            continue
        clause = _strip_citations(bare, citations)
        route = every and states_a_count(clause)
        if not route:
            if fams is None:
                fams = _count_families(records)
                for name, tags in (families or {}).items():
                    fams[str(name).upper()] = sorted(set(fams.get(str(name).upper(), []))
                                                     | {str(t).upper() for t in tags or []})
            route = states_a_family_count(clause, fams)
        if route:
            bad += _count_answer_is_bound(source[c0:c1], records)[1]
            out[c0:c1] = " " * (c1 - c0)
    return "".join(out), bad


# ── A CEILING'S HEIGHT IS NAMED AS ONE ────────────────────────────────────
#
# Measured 2026-10-28 on this rule: 0 claims that SAY "ceiling height" bound
# a printed value, but 204 that state one in other words did - "Ceilings are
# 5/8" high." on A-302.00's "1 HOUR FIRE RATED CEILING W/ ONE LAYER OF 5/8"
# GYPSUM BOARD", "The first floor has a 8 ceiling." on Z-001.01's zoning
# table (which names FIRST FLOOR). Words after the value are not required
# (ruling 6: "The parapet is 42" high." binds on 42" PARAPET), so HIGH and
# the trailing CEILING were never asked of the record. The drawings print no
# ceiling height at all.
#
# So, narrowly (coordinator's rule 2026-10-28, under Roy's condition (b)): a
# clause that names a ceiling AND says a height - anywhere in it, before or
# after the value - or puts its value directly before the ceiling ("a 9'
# ceiling") is a CEILING-HEIGHT clause. Its subject is {ceiling, height}, in
# whatever order it says them, plus every other word before its value (ruling
# 6, unchanged). It binds only on a record part naming a ceiling and a height
# where the value is. "The ceiling is 9'." says no height and is left as it
# is. No other trailing word becomes a subject.
#
# THE WORDS ARE lib/plan_floor_to_floor.py's (#900): one ceiling / height
# vocabulary, read here and by the floor-to-floor row alike. A CLAIM may also
# say TALL or "floor to ceiling" (_HEIGHT_SAID: claim-side wording only, never
# asked of a record).
_CEILING_WORD = _f2f.CEILING_WORD
_HEIGHT_WORD = _f2f.HEIGHT_WORD
_HEIGHT_SAID = re.compile(r"(?<![A-Za-z])(?:tall|floor[\s\-]*to[\s\-]*ceiling)(?![A-Za-z])", re.I)
#: A value directly before the ceiling: "a 9' ceiling", "a 9'-0" CLG", "a 8 ceiling".
_VALUE_CEILING = re.compile(r"[\d'\"′″]\s*" + _f2f.CEILING_PATTERN + r"(?![A-Za-z])", re.I)


def is_ceiling_height_clause(clause: str) -> bool:
    """Does the clause state a ceiling's height: it names a ceiling and says a
    height, or puts its value directly before the ceiling?"""
    c = clause or ""
    if not _CEILING_WORD.search(c):
        return False
    return bool(_HEIGHT_WORD.search(c) or _HEIGHT_SAID.search(c) or _VALUE_CEILING.search(c))


def _without_ceiling_height(text: str) -> str:
    """`text` less the words the {ceiling, height} subject already stands for."""
    for rx in (_HEIGHT_SAID, _CEILING_WORD, _HEIGHT_WORD):
        text = rx.sub(" ", text)
    return text


def _names_ceiling_height(naming: str) -> bool:
    """A record part naming a ceiling and a height where its value is."""
    return _f2f.names_ceiling_and_height(naming)


def _subject_bound(clause: str, records: Sequence[Dict[str, Any]],
                   citations: Sequence[str],
                   aliases: Optional[Dict[str, Dict[str, List[str]]]] = None
                   ) -> List[str]:
    """The values in one attribute clause (its quotation marks already
    blanked) that no record naming its subject prints. A dimension is one
    whole value (plan_dimensions); the rest are numbers, as `_values` reads
    them."""
    masked = _strip_citations(clause, citations)
    found = _dims.find(masked)
    rest = list(masked)
    for f in found:
        rest[f.span[0]:f.span[1]] = " " * (f.span[1] - f.span[0])
    flat = _SPLIT_RE.sub(" ", _UNIT_RE.sub(" ", "".join(rest)))
    nums = [(m.group(0).replace(",", "").rstrip("."), m.span()) for m in _VALUE_RE.finditer(flat)]
    nums = [(v, sp) for v, sp in nums if v]
    if not found and not nums:
        return []
    spans = [f.span for f in found] + [sp for _, sp in nums]
    subject = _claim_subject(flat, spans)
    # A CEILING-HEIGHT CLAUSE: {ceiling, height} plus the other words before
    # its value, named together where the value is.
    ceiling = is_ceiling_height_clause(masked)
    if ceiling:
        subject = search_terms(_without_ceiling_height(flat[:min(s for s, _ in spans)]))
    named: List[List[str]] = []
    if subject or ceiling:
        for r in records or []:
            if _vouches_for_nothing(r):
                continue
            table = (aliases or {}).get(str(r.get("file_id") or ""))
            for texts, naming in value_parts(r):
                if ceiling and not _names_ceiling_height(naming):
                    continue
                if (not subject) or names_subject(naming, subject, table):
                    named.append(texts)
    bad = [f.text.strip() for f in found
           if not any(_dims.supported(f, _dims.evidence(t)) for t in named)]
    printed = set()
    for t in named:
        for x in t:
            printed.update(_values(x))
    bad += [v for v, _sp in nums if v not in printed]
    return bad


def _clause_spans(text: str) -> List[Tuple[int, int]]:
    """Where each of `_clauses(text)` sits in `text`."""
    out, at = [], 0
    for m in _CLAUSE_SPLIT.finditer(text or ""):
        if text[at:m.start()].strip():
            out.append((at, m.start()))
        at = m.end()
    if (text or "")[at:].strip():
        out.append((at, len(text)))
    return out


def _ceiling_heights_bound(text: str, records: Sequence[Dict[str, Any]]
                           ) -> Tuple[str, List[str]]:
    """(`text` with its ceiling-height clauses blanked, the values those
    clauses state that no record part naming a ceiling and a height prints).

    Item 21 (#900's question 7): "The ceiling height is 50'-0"." bound on
    the `building` / `height` search under "", identify, existence, location
    and geometry - the union vouched on the printed 50'-0" BUILDING & BASE
    HEIGHT - while #894's ceiling rule (is_ceiling_height_clause,
    _subject_bound) held it only under attribute. A ceiling-height clause
    is now decided by that same rule under every intent; no other clause
    changes. Without a value the clause states nothing and stays."""
    masked = _dims.mask_quotation_marks(text or "")
    hold = list(masked)
    for f in _dims.find(masked):
        hold[f.span[0]:f.span[1]] = "\x00" * (f.span[1] - f.span[0])
    hold_s = "".join(hold)
    citations = _citation_texts(records)
    spans: List[Tuple[int, int]] = []
    bad: List[str] = []
    for c0, c1 in _clause_spans(hold_s):
        clause = _track_claim(masked[c0:c1])[1]
        if not is_ceiling_height_clause(clause):
            continue
        spans.append((c0, c1))
        bad += _subject_bound(clause, records, citations, None)
    return _blank(text or "", spans), bad


def _attribute_answer_is_bound(text: str, records: Sequence[Dict[str, Any]],
                               aliases: Optional[Dict[str, Dict[str, List[str]]]] = None
                               ) -> Tuple[bool, List[str]]:
    """An attribute answer, clause by clause: each value binds only on a
    record naming the clause's subject (_subject_bound). An area clause is
    decided as before - its area check first (lib.plan_areas), anything else
    by what any returned record prints. A clause stating a count is decided
    by the count rule alone (states_a_count, _count_answer_is_bound)."""
    has_areas = any(_areas.is_area_record(r) for r in records or [])
    source = _areas.join_thousands(text or "")
    masked = _dims.mask_quotation_marks(source)
    found = _dims.find(masked)
    hold = list(masked)
    for f in found:
        hold[f.span[0]:f.span[1]] = "\x00" * (f.span[1] - f.span[0])
    hold_s = "".join(hold)
    citations = _citation_texts(records)
    union = None
    unsupported: List[str] = []
    for c0, c1 in _clause_spans(hold_s):
        plain = hold_s[c0:c1].replace("\x00", " ")
        named, bare = _track_claim(plain)
        if has_areas and _areas.is_area_clause(bare):
            if union is None:
                union = (_dims.evidence(_dims.record_texts(records, _vouches_for_nothing)),
                         _supported_values(records))
            ev, ok = union
            unsupported += [f.text.strip() for f in found
                            if c0 <= f.span[0] < c1 and not _dims.supported(f, ev)]
            a_add, a_drop = _areas.figures_in_clause(bare, records, named)
            unsupported += [v for v in _values(plain)
                            if v not in a_add and (v in a_drop or v not in ok)]
            continue
        unsupported += _subject_bound(_track_claim(masked[c0:c1])[1], records,
                                      citations, aliases)
    return (not unsupported), unsupported


_NO_LEVEL_KIND, _CEILING_KIND, _FLOOR_TO_FLOOR_KIND = "", "ceiling", "floor_to_floor"
_UNIT_WORD = re.compile(r"(?<![A-Za-z])(?:feet|foot|ft|inch(?:es)?|in)\.?(?![A-Za-z])", re.I)


def _subjectless(clause: str, citations: Sequence[str]) -> bool:
    """A clause with a value and no word before it: it says its value is of
    whatever the clause before it named ("The ceiling height - 10'-0"",
    "floor-to-floor 14'-0" ..., 10'-0" SECOND FLOOR to THIRD FLOOR"). The
    words before the value are where #894 reads a clause's subject."""
    masked = _dims.mask_quotation_marks(_strip_citations(clause, citations))
    rest = list(masked)
    starts = []
    for f in _dims.find(masked):
        rest[f.span[0]:f.span[1]] = " " * (f.span[1] - f.span[0])
        starts.append(f.span[0])
    flat = _SPLIT_RE.sub(" ", _UNIT_RE.sub(" ", "".join(rest)))
    starts += [m.start() for m in _VALUE_RE.finditer(flat)]
    if not starts:
        return False
    return not search_terms(_UNIT_WORD.sub(" ", flat[:min(starts)]))


def _level_kinds(text: str, citations: Sequence[str]) -> List[Tuple[int, int, str]]:
    """(start, end, kind) per clause: a clause naming a ceiling is a ceiling
    clause (whatever else it names - the conservative reading); one naming a
    floor-to-floor is a floor-to-floor clause; a subjectless clause carries
    the kind of the clause before it; anything else has no level kind."""
    masked = _dims.mask_quotation_marks(text or "")
    hold = list(masked)
    for f in _dims.find(masked):
        hold[f.span[0]:f.span[1]] = "\x00" * (f.span[1] - f.span[0])
    out, prev = [], _NO_LEVEL_KIND
    for c0, c1 in _clause_spans("".join(hold)):
        clause = (text or "")[c0:c1]
        if _f2f.names_ceiling(clause):
            kind = _CEILING_KIND
        elif _f2f.names_floor_to_floor(clause):
            kind = _FLOOR_TO_FLOOR_KIND
        elif _subjectless(clause, citations):
            kind = prev
        else:
            kind = _NO_LEVEL_KIND
        out.append((c0, c1, kind))
        prev = kind
    return out


def _blank(text: str, spans: Iterable[Tuple[int, int]]) -> str:
    chars = list(text or "")
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    return "".join(chars)


def answer_is_grounded(text: str, records: Sequence[Dict[str, Any]],
                       intent: str = "",
                       aliases: Optional[Dict[str, Dict[str, List[str]]]] = None,
                       sources: Iterable[Dict[str, Any]] = (),
                       families: Optional[Dict[str, Sequence[str]]] = None
                       ) -> Tuple[bool, List[str]]:
    """(ok, the numbers nothing returned can vouch for).

    ── A FLOOR-TO-FLOOR IS NEVER A CEILING HEIGHT (ruling 2026-10-27) ─────
    #
    # "derive floor-to-floor from A-300's level marks; answer "ceiling height
    # not shown; floor-to-floor 10'-0" (A-300.00)". Floor-to-floor must never
    # bind as a ceiling height." With level evidence among the records - the
    # derived row (lib.plan_floor_to_floor) or a record printing a level mark - the
    # answer is decided clause by clause, under EVERY intent:
    #
    #   a clause naming a ceiling   decided as before but WITHOUT any level
    #                               evidence, and a dimension in it equal to
    #                               a floor-to-floor, or at least the largest,
    #                               is refused: a ceiling is lower than its
    #                               floor-to-floor by the slab;
    #   a clause naming a           the derived row's figures bind in it; the
    #   floor-to-floor              rest of it is decided as before;
    #   a subjectless clause        carries the kind of the clause before it;
    #   any other clause            decided exactly as before, together.
    #
    # Without level evidence, or without such a clause, nothing changes.
    """
    if not any(_f2f.is_level_evidence(r) for r in records or []):
        return _answer_is_grounded(text, records, intent, aliases, sources, families)
    kinds = _level_kinds(text, _citation_texts(records))
    if all(k == _NO_LEVEL_KIND for _a, _b, k in kinds):
        return _answer_is_grounded(text, records, intent, aliases, sources, families)
    plain = [r for r in records if not _f2f.is_level_evidence(r)]
    f2f = _f2f.floor_to_floor_in(records)
    stated = set(_f2f.stated_floor_to_floor(records))
    bad: List[str] = []
    rest = _blank(text, [(a, b) for a, b, k in kinds if k != _NO_LEVEL_KIND])
    if _clause_spans(rest):
        bad += _answer_is_grounded(rest, records, intent, aliases, sources, families)[1]
    for a, b, kind in kinds:
        clause = text[a:b]
        found = [f for f in _dims.find(_dims.mask_quotation_marks(clause)) if f.dims]
        if kind == _CEILING_KIND:
            bad += _answer_is_grounded(clause, plain, intent, aliases, sources, families)[1]
            for f in found:
                d = f.dims[0]
                if (d.unit == "in" and f2f and (Fraction(d.value) in f2f or d.value >= max(f2f))
                        and f.text.strip() not in bad):
                    bad.append(f.text.strip())
        elif kind == _FLOOR_TO_FLOOR_KIND:
            held = [f.span for f in found if len(f.dims) == 1 and f.dims[0].unit == "in"
                    and Fraction(f.dims[0].value) in stated]
            bad += _answer_is_grounded(_blank(_dims.mask_quotation_marks(clause), held),
                                       records, intent, aliases, sources, families)[1]
    return (not bad), bad


def _answer_is_grounded(text: str, records: Sequence[Dict[str, Any]],
                        intent: str = "",
                        aliases: Optional[Dict[str, Dict[str, List[str]]]] = None,
                        sources: Iterable[Dict[str, Any]] = (),
                        families: Optional[Dict[str, Sequence[str]]] = None
                        ) -> Tuple[bool, List[str]]:
    """(ok, the numbers nothing returned can vouch for), level evidence aside.

    A CHECK ON THE OUTPUT, not an instruction in a prompt. The model composes;
    this decides whether what it composed may be sent. A number with nothing
    behind it is the worst failure this product has — it looks verified.

    `sources` (plan_sources.source_of rows for the records' files): their
    file names and set labels are citations (strip_source_citations).

    `families` (server.plan_count_families): the project's countable families,
    name -> tags, so a plural names its family whatever the search returned
    (ruling 51); the records' own families count without it."""
    text = strip_source_citations(text or "", records, sources)
    it = (intent or "").strip().lower()
    # A COUNT CLAUSE IS DECIDED BY THE COUNT RULE, from its counting sources,
    # under every intent - never by the value path or the union (_route_counts:
    # ruling 50 under attribute, ruling 51 under every intent).
    routed: List[str] = []
    if it != "count":
        text, routed = _route_counts(text, records, every=(it == "attribute"),
                                     families=families)
    # AN ATTRIBUTE BINDS TO THE SUBJECT ITS RECORD NAMES (ruling 2026-10-27,
    # _attribute_answer_is_bound). `aliases`: file_id -> that file's own
    # abbreviations table (abbreviation_table), the alternative names.
    if it == "attribute":
        _ok, bad = _attribute_answer_is_bound(text, records, aliases)
    else:
        # A CEILING'S HEIGHT IS NAMED AS ONE UNDER EVERY INTENT (Roy's
        # condition (b), item 21): a ceiling-height clause binds only on a
        # record part naming a ceiling and a height, as under attribute; the
        # rest of the answer - every count among it - is decided as before.
        # Under count too: measured, 80 ceiling-height claims of a printed
        # 20X40" bound there on the `apartments` / `ceiling height` search.
        text, ceiling = _ceiling_heights_bound(text, records)
        _ok, bad = _answer_is_grounded_rest(text, records, intent)
        bad = ceiling + bad
    bad = routed + bad
    return (not bad), bad


def _answer_is_grounded_rest(text: str, records: Sequence[Dict[str, Any]],
                             intent: str = "") -> Tuple[bool, List[str]]:
    """answer_is_grounded for every intent but attribute, any count clause
    already routed (_route_counts)."""
    # ── A DIMENSION IS ONE VALUE, NOT ITS DIGITS ───────────────────────────
    #
    # "The doors are 3'-5" X 7'-0"." passed with only 3'-0" X 7'-0" printed:
    # a 3, a 5, a 7 and a 0 were each somewhere (2026-10-25). A dimension in
    # the claim now binds only if the whole of it, normalized, is printed in
    # what was returned (plan_dimensions); its digits are not checked again
    # as loose numbers. A count keeps its own rule untouched.
    masked = _dims.mask_quotation_marks(text or "")
    found = _dims.find(masked)
    bad_dims: List[str] = []
    if found:
        ev = _dims.evidence(_dims.record_texts(records, _vouches_for_nothing))
        bad_dims = [f.text.strip() for f in found if not _dims.supported(f, ev)]
    if (intent or "").strip().lower() == "count":
        ok, bad = _count_answer_is_bound(text, records)
        bad = bad_dims + bad
        return (not bad), bad
    rest = list(masked)
    for f in found:
        rest[f.span[0]:f.span[1]] = " " * (f.span[1] - f.span[0])
    said = _values("".join(rest))
    if not said:
        return (not bad_dims), bad_dims
    # A COUNT IS BOUND TO ITS SUBJECT; EVERYTHING ELSE KEEPS THE UNION.
    #
    # The failure measured was a quantity — "9 PTAC-2 units" — and the bound
    # rule is written for that shape. An attribute answer quotes a note or a
    # cell whose number often belongs to no mark at all: of the ten suite
    # cases stating a number, eight bind to a mark or a schedule and the two
    # that do not (a 42" parapet, a 1,970 sf recreation area) are both
    # attribute cases. Applying the bound rule to them would refuse two true
    # answers to catch nothing. (The count branch is taken above.)
    ok = _supported_values(records)
    if not any(_areas.is_area_record(r) for r in records or []):
        unsupported = bad_dims + [v for v in said if v not in ok]
        return (not unsupported), unsupported
    # AN AREA AGREES WITH WHAT IS PRINTED, OR NEITHER IS SAID (ruling
    # 2026-10-26, lib.plan_areas). The union holds every printed area - so a
    # clause stating one is decided by the area check first: a figure it
    # allows binds (the measured one included, which no quote prints), a
    # figure it withholds is refused whatever the union holds, and anything
    # else falls to the union as before.
    unsupported = list(bad_dims)
    for clause in _clauses(_areas.join_thousands("".join(rest))):
        named, bare = _track_claim(clause)
        vals = _values(clause)
        if not _areas.is_area_clause(bare):
            unsupported += [v for v in vals if v not in ok]
            continue
        a_add, a_drop = _areas.figures_in_clause(bare, records, named)
        unsupported += [v for v in vals if v not in a_add and (v in a_drop or v not in ok)]
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
        # A located symbol's label is not a vision word: it is the tag from
        # the schedule's own closed set (plan_symbols), matched to the label
        # printed beside the symbol - whose OCR ('EF -1(50)') rarely spells it
        # exactly. Reading it as a leak would refuse every count of them.
        if r.get("tier") == _GLYPH_TIER:
            continue
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


# ── A REFUSAL IS A CLAIM ABOUT THE SEARCH, NOT ABOUT THE DRAWINGS ─────────
#
# "The drawings do not specify the ceiling height" is a claim about the
# building, and it is the ONLY output in this system with no evidence behind
# it. Every number passes a gate that demands a record about its subject; a
# refusal passed nothing. It was produced whenever retrieval returned nothing,
# which happens for reasons that have nothing to do with the drawings — most
# often because the questioner used their own words and the sheet uses its
# abbreviations. Measured 2026-09-20: `apartment square footage` returns zero
# records while A-101.00 prints `APT 2A / NET: 482 SQ. FT.` and the record for
# it exists verbatim.
#
# A GC who checks the sheet and finds it there stops trusting the tool, and he
# is right to. So the reply says what is true — that it was not found — and
# points at the nearest thing, which he can check in seconds.
NOT_FOUND = "I couldn't find that in the drawings I've indexed."


def not_found_text(closest_sheet: str = "") -> str:
    """The refusal, naming the nearest sheet when there is one."""
    sheet = (closest_sheet or "").strip()
    return (f"I couldn't find that — closest is {sheet}." if sheet
            else NOT_FOUND)


def render_records(records: Sequence[Dict[str, Any]], subject: str = "",
                   limit: int = 3) -> str:
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
    # An area row is shown through its check (render_area_evidence), never
    # as a quote: its quote is a printed figure the check may withhold.
    everything = list(records or [])
    records = [r for r in everything if not _areas.is_area_record(r)
               and not _f2f.is_level_record(r)]
    # A DERIVED FLOOR-TO-FLOOR ROW IS SAID AS THE OPERATOR RULED IT
    # (lib.plan_floor_to_floor, 2026-10-27): `Ceiling height not shown; floor-to-floor
    # 10'-0" (A-300.00)`. When "not shown" is warranted that sentence is the
    # whole answer - no record returned prints a ceiling height to list.
    said = [ln for ln in (_f2f.answer_line(r) for r in everything
                          if _f2f.is_level_record(r)) if ln]
    if said:
        alone = any(((r.get("payload") or {}).get("ceiling_asked")
                     and (r.get("payload") or {}).get("ceiling_heights_printed") == 0)
                    for r in everything if _f2f.is_level_record(r))
        if alone:
            return "\n".join(said)
        rest = render_records(records, subject, limit) if records else ""
        return "\n".join(said + ([rest] if rest and rest != NOT_FOUND else []))
    if terms:
        records = [r for r in records if not matched_only_through_label(r, terms)]
    if not records:
        # NO SHEET IS NAMED HERE, and the first version of this named one.
        # This branch is reached only when there were no records at all, or
        # when every one of them matched through a LABEL — and "closest is
        # M-104.00" for the subject 'kicker' asserts a relationship that
        # exists only in a vision label, which is a quieter form of the leak
        # this function refuses on the line above. Naming the nearest sheet
        # belongs where candidates were dropped for a reason that IS about
        # the sheets.
        return NOT_FOUND
    lines: List[str] = []
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
        # ── THE SHEET IS A CITATION, NOT A SENTENCE ABOUT SHEETS ───────
        #
        # This printed a header naming the subject and then a line per record
        # reading 'M-200.00 (schedule): ...'. Live test 2026-09-19, a real GC:
        # every answer came back a paragraph hedging about which sheets
        # mention things, and he would not read them.
        #
        # The record type is machinery and is gone. The sheet trails the line
        # the way a citation does, so the eye reaches the content first.
        line = f"{quote[:200]} [{where_all}]"
        # A PRINTED AREA THE CHECK WITHHELD is not repeated as if it stood
        # (lib.plan_areas): the line says the drawn region disagrees.
        line += _areas.withheld_note(quote, everything)
        readings = (r.get("payload") or {}).get("count_readings")
        if readings:
            said = " and ".join(str(x.get("value")) for x in readings)
            line += (f" — two readings of that cell say {said}; "
                     f"verify against the sheet")
        if r.get("tier") == TIER_ORDER[-1]:
            line += " — read from the drawing image, verify against the sheet"
        lines.append(line)
    if not lines:
        return "Not found."
    # THE CLOSEST THING, NAMED, RATHER THAN A LIST OF WHAT MENTIONS IT.
    # A reader who cannot be answered is better served by one pointer than by
    # four lines he has to triage himself.
    return "\n".join(lines)


__all__ = ["search_terms", "normalise_quotes",
           "match_score", "rank", "best_per_attribute",
           "answer_is_grounded", "contains_label", "render_records", "cite", "rank_by_best",
           "VALUE_SLOTS", "states_a_value", "subject_words", "value_records", "normalize_arguments",
           "meets_the_floor", "floor_terms", "ASKING_WORDS",
           "subject_is_known", "abbreviation_forms", "CONVENTIONS",
           "NOT_FOUND", "not_found_text",
           "is_index_record", "drop_indexes",
           "dimension_is_impossible", "drop_impossible_dimensions",
           "dangling_callouts", "referenced_sheets_missing",
           "matched_only_through_label",
           "GLYPH_CENSUS", "glyph_families_for", "glyph_family_filter",
           "glyph_refusal_filter", "glyph_census", "glyph_in_census",
           "is_glyph_evidence", "glyph_book", "glyph_values",
           "render_glyph_evidence",
           "INTENTS", "GEOMETRY_INTENT", "RENDERABLE"]
