"""PR #14B — table-driven cohort spec per ``dob_project_type``.

Each entry in ``COHORT_CONFIG`` describes how to discover the peer
cohort for that project type:

  • filter_fields         — list of cohort filter dimensions
  • story_count_tolerance — (pct, min_band) tuple used by
    ``compute_tolerance_band``; only consulted if
    ``story_count_band`` is in ``filter_fields``
  • dwelling_units_tolerance — same shape
  • geography_ladder      — list of tier names in fallback order
  • completion_filter     — dict with ``primary`` + ``fallback`` keys
                            naming the completion mechanism
  • bis_job_types         — set of BIS ``job_type`` codes that
                            define this cohort population

For ``major_alt_with_enlargement`` only, a ``secondary_fallback``
entry expands the cohort to merge ``new_building`` peers when the
primary cohort doesn't meet the floor.

``unknown`` is not a key — ``COHORT_CONFIG.get("unknown")`` returns
``None``, signalling the caller to skip cohort matching entirely.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


# Standard 4-tier geography ladder shared by every cohort spec.
_GEOGRAPHY_LADDER = [
    "zip_bldgclass_type",
    "cd_bldgclass_type",
    "borough_broader_type",
    "borough_type",
]


# Standard completion filter — Final C of O primary, BIS job_status
# IN ('X', 'U') fallback. Both encoded as enum-style strings the
# caller can branch on.
_COMPLETION_FILTER = {
    "primary":  "c_of_o_final",
    "fallback": "job_status_x_or_u",
}


COHORT_CONFIG: Dict[str, Dict[str, Any]] = {
    "new_building": {
        "filter_fields": [
            "building_class",
            "story_count_band",
            "dwelling_units_band",
            "geography",
        ],
        "story_count_tolerance":    (0.25, 1),   # ±25%, min ±1
        "dwelling_units_tolerance": (0.25, 2),   # ±25%, min ±2
        "geography_ladder":         list(_GEOGRAPHY_LADDER),
        "completion_filter":        dict(_COMPLETION_FILTER),
        "bis_job_types":            {"NB"},
    },
    "major_alt_with_enlargement": {
        "filter_fields": [
            "building_class",
            "story_count_band",
            "geography",
        ],
        "story_count_tolerance":    (0.25, 1),
        "dwelling_units_tolerance": (0.25, 2),
        "geography_ladder":         list(_GEOGRAPHY_LADDER),
        "completion_filter":        dict(_COMPLETION_FILTER),
        "bis_job_types":            {"A1"},
        # Per Stage 2.A T4 — when primary A1 cohort < 30, merge
        # in new_building peers (they share the structural-scope
        # axis of the active project).
        "secondary_fallback": {
            "expands_to": "new_building",
            "trigger_below": 30,
        },
    },
    "minor_alt": {
        "filter_fields": [
            "building_class",
            "geography",
        ],
        "story_count_tolerance":    None,
        "dwelling_units_tolerance": None,
        "geography_ladder":         list(_GEOGRAPHY_LADDER),
        "completion_filter":        dict(_COMPLETION_FILTER),
        "bis_job_types":            {"A2", "A3"},
    },
    "full_demo": {
        "filter_fields": [
            "building_class_demolished",
            "story_count_demolished",
            "geography",
        ],
        "story_count_tolerance":    (0.25, 1),
        "dwelling_units_tolerance": (0.25, 2),
        "geography_ladder":         list(_GEOGRAPHY_LADDER),
        "completion_filter":        dict(_COMPLETION_FILTER),
        "bis_job_types":            {"DM"},
    },
    # "unknown" deliberately absent — COHORT_CONFIG.get("unknown")
    # returns None per the locked design.
}


def compute_tolerance_band(
    value: int,
    pct: float,
    min_band: int,
) -> Tuple[int, int]:
    """Compute a ``(low, high)`` tolerance band around ``value``.

    Examples:
      • ``compute_tolerance_band(5, 0.25, 1)``  → ``(4, 6)``
        (5 × 0.25 = 1.25 → rounds to 1; max(1, min_band=1) = 1)
      • ``compute_tolerance_band(2, 0.25, 1)``  → ``(1, 3)``
        (2 × 0.25 = 0.5 → rounds to 0; max(0, 1) = 1 — min clamp)
      • ``compute_tolerance_band(20, 0.25, 2)`` → ``(15, 25)``
        (20 × 0.25 = 5; max(5, 2) = 5 — band wider than min)

    Returns half-open band ``(low, high)`` inclusive on both sides.
    """
    band_size = max(int(round(value * pct)), min_band)
    return (value - band_size, value + band_size)
