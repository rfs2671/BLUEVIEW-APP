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
from typing import (Any, Collection, Dict, Iterable, List, Optional,
                    Sequence, Tuple)

from lib.plan_records import TIER_ORDER, tier_rank
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
           "answer_is_grounded", "contains_label", "render_records", "cite",
           "meets_the_floor", "floor_terms", "ASKING_WORDS",
           "subject_is_known", "abbreviation_forms", "CONVENTIONS",
           "NOT_FOUND", "not_found_text",
           "is_index_record", "drop_indexes",
           "dimension_is_impossible", "drop_impossible_dimensions",
           "dangling_callouts", "referenced_sheets_missing",
           "matched_only_through_label",
           "INTENTS", "GEOMETRY_INTENT", "RENDERABLE"]
