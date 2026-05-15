"""PR #14B — parser for DOB NOW ``job_description`` free-text.

Extracts the four scope dimensions PR #14B's cohort logic needs:

    {
        "story_count":    int | None,
        "dwelling_units": int | None,
        "use_type":       "residential" | "commercial" | "mixed" | "other",
        "enlargement":    bool,
        "extracted_at":   datetime (UTC),
    }

Safe defaults (``None`` / ``False`` / ``"other"``) are returned when
the input doesn't contain a confident signal — the cohort builder
prefers an unfiltered fall-back over a misleading filter.

The grammar is intentionally narrow:

  • story_count   matches ``N STORY`` / ``N-STORY`` / ``N STORIES``
                  (word-bounded — ``1ST FLOOR`` does NOT match).
  • dwelling_units matches ``N DWELLING UNITS`` first, then a
                   shorter ``N UNITS`` form. ``N SQFT``,
                   ``N FLOORS`` etc. don't match.
  • enlargement   triggers on any of a fixed keyword list
                  (``ENLARGEMENT``, ``EXTENSION``, ``ADDITION``,
                  ``VERTICAL``, ``HORIZONTAL``, ``EXPAND``).
  • use_type      derives from residential/commercial keyword
                  lists; presence of both → ``mixed``; explicit
                  ``MIXED USE`` phrase also → ``mixed``.

The ``work_type`` parameter is accepted but currently unused — the
classifier already branches on it before calling the parser. It's
kept in the signature so the parser can grow into a context-aware
mode without a breaking API change.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ── Regex patterns ────────────────────────────────────────────────

# Story count: "5 STORY", "5-STORY", "5 STORIES". Word-bounded so
# "1ST FLOOR" / "2ND FLOOR" can't accidentally match.
_STORY_RE = re.compile(
    r"(\d+)\s*-?\s*STOR(?:Y|IES)\b",
    re.IGNORECASE,
)

# Dwelling units — explicit form first.
_DWELLING_UNITS_RE = re.compile(
    r"(\d+)\s+DWELLING\s+UNITS?\b",
    re.IGNORECASE,
)

# Shorter "N UNITS" form. Excludes "UNIT" mid-word (\b enforces
# boundary so "UNITED" won't match).
_UNITS_RE = re.compile(
    r"(\d+)\s+UNITS?\b",
    re.IGNORECASE,
)


# ── Keyword lists ─────────────────────────────────────────────────

_ENLARGEMENT_KEYWORDS = (
    "ENLARGEMENT",
    "ENLARGE",
    "EXTENSION",
    "ADDITION",
    "VERTICAL",
    "HORIZONTAL",
    "EXPAND",
)

# PR #14E §7.1 + T2 + Risk 7 lock — negation phrases that explicitly
# rule out enlargement, even when a positive keyword (ENLARGEMENT /
# EXTENSION / ADDITION / etc.) also appears in the description.
# Pre-PR-14E ``_extract_enlargement`` matched literal ``ENLARGEMENT``
# as positive without checking for negation; Stage 1 Task 5 sample
# BIN 3057867 ("...NO ENLARGEMENT IS PROPOSED. REMOVE PART EXT
# WALL...") mis-classified as major_alt_with_enlargement.
#
# Negation gate runs FIRST in _extract_enlargement so explicit
# negation always wins over a positive keyword hit.
NEGATION_KEYWORDS = (
    "NO ENLARGEMENT",
    "NOT ENLARGED",
    "WITHOUT ENLARGEMENT",
    "NO INCREASE IN BULK",
)

_RESIDENTIAL_KEYWORDS = (
    "RESIDENTIAL",
    "APARTMENT",
    "DWELLING",
    "FAMILY",
)

_COMMERCIAL_KEYWORDS = (
    "COMMERCIAL",
    "RETAIL",
    "OFFICE",
    "STORE",
    "TENANT",   # "TENANT FIT-OUT" is the standard DOB phrase for
                # commercial interior work
)


# ── Public API ────────────────────────────────────────────────────


def parse_dob_now_description(
    description: str,
    work_type: str = "",
) -> Dict[str, Any]:
    """Parse a DOB NOW ``job_description`` into structured scope.

    Returns a dict with these keys (always present):

      • ``story_count``     int or None
      • ``dwelling_units``  int or None
      • ``use_type``        str in {residential, commercial, mixed, other}
      • ``enlargement``     bool
      • ``extracted_at``    datetime (UTC)

    Args:
        description: Free-text job description from the DOB NOW
            ``job_description`` column. Empty string allowed.
        work_type: The DOB NOW ``work_type`` column. Currently
            unused — passed in for forward compatibility.

    The parser never raises on malformed input; it returns safe
    defaults instead.
    """
    text = (description or "").upper()

    return {
        "story_count":    _extract_story_count(text),
        "dwelling_units": _extract_dwelling_units(text),
        "use_type":       _extract_use_type(text),
        "enlargement":    _extract_enlargement(text),
        "extracted_at":   datetime.now(timezone.utc),
    }


# ── Per-field extractors ──────────────────────────────────────────


def _extract_story_count(text: str) -> Optional[int]:
    """Return the MAX ``N STORY``/``N STORIES``/``N-STORY`` value
    found in the text.

    PR #14E rationale (§7.6 target_state): enlargement descriptions
    routinely cite both the EXISTING and PROPOSED story counts
    (e.g., Menahan: "EXISTING 2 STORY ... PROPOSED 4-STORY+CELLAR+MEZZ").
    The cohort target_state needs the PROPOSED/post-enlargement
    state, which is reliably the larger value. Demolitions and
    new construction typically only cite one value, so max=value
    in those cases. Returns None when no match.
    """
    matches = _STORY_RE.findall(text)
    if not matches:
        return None
    counts: List[int] = []
    for m in matches:
        try:
            counts.append(int(m))
        except (TypeError, ValueError):
            continue
    if not counts:
        return None
    return max(counts)


def _extract_dwelling_units(text: str) -> Optional[int]:
    """Return the first dwelling-unit count.

    Prefers the explicit ``N DWELLING UNITS`` form. Falls back to a
    bare ``N UNITS`` match when no explicit form is present.
    """
    m = _DWELLING_UNITS_RE.search(text)
    if not m:
        m = _UNITS_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _extract_use_type(text: str) -> str:
    """Classify the use-type signal.

    Returns one of: ``"residential"``, ``"commercial"``, ``"mixed"``,
    ``"other"``. Both ``"MIXED USE"`` phrase and co-presence of
    residential + commercial keywords trigger ``"mixed"``.
    """
    has_residential = any(kw in text for kw in _RESIDENTIAL_KEYWORDS)
    has_commercial  = any(kw in text for kw in _COMMERCIAL_KEYWORDS)
    has_mixed_phrase = "MIXED USE" in text or "MIXED-USE" in text

    if has_mixed_phrase or (has_residential and has_commercial):
        return "mixed"
    if has_residential:
        return "residential"
    if has_commercial:
        return "commercial"
    return "other"


def _extract_enlargement(text: str) -> bool:
    """Return True iff any enlargement-family keyword is present
    AND no negation phrase explicitly rules it out.

    The keyword list is biased toward recall over precision —
    misclassifying an enlargement as a minor_alt is worse than the
    reverse, so we tolerate a few false positives. The classifier
    layer applies additional ``work_type`` + NB-keyword constraints
    before assigning ``major_alt_with_enlargement``.

    PR #14E §7.1 + T2 + Risk 7 lock — negation gate runs FIRST:
    descriptions containing ``NO ENLARGEMENT`` / ``NOT ENLARGED`` /
    ``WITHOUT ENLARGEMENT`` / ``NO INCREASE IN BULK`` return False
    even when a positive keyword also appears. Operator's BIN
    3057867 sample drove this fix.
    """
    if any(neg in text for neg in NEGATION_KEYWORDS):
        return False
    return any(kw in text for kw in _ENLARGEMENT_KEYWORDS)
