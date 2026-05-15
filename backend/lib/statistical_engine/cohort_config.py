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

PR #14E extension (Stage 3 §7.4 lock) — Unified Cohort. Each entry
gains two new keys:

  • modern_path  — dict describing the pkdm-hqz6 (DOB NOW C of O)
    source. ``None`` for ``full_demo`` (Q4 lock: pkdm-hqz6 has no
    DEMOLITION job_type). Shape:
        {
            "pkdm_job_types":      tuple of strings (case variants per Risk 3),
            "yearbuilt_filter_min": int or None  # 2000 for NB, None for others (Q3),
            "apply_yearbuilt_filter": bool       # mirror of above for clarity,
        }

  • legacy_path  — dict describing the BIS Legacy Golden Era source.
    Shape:
        {
            "bis_job_types":     tuple of strings,
            "window_start_iso":  "2018-06-30",
            "window_end_iso":    "2021-06-30",
            "secondary_fallback": dict | absent  # A1 → NB merge (T4 PR #14B carry-over)
        }
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


# PR #14E (Q7 lock) — BIS Legacy Golden Era window. Reused across
# all non-None legacy_path entries.
_PR14E_LEGACY_WINDOW = {
    "window_start_iso": "2018-06-30",
    "window_end_iso":   "2021-06-30",
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
        # PR #14E Q2 + Q3 + Risk 3 lock.
        "modern_path": {
            "pkdm_job_types":         ("NEW BUILDING", "New Building"),
            "yearbuilt_filter_min":   2000,   # Q3: NB-only filter
            "apply_yearbuilt_filter": True,
        },
        "legacy_path": {
            "bis_job_types":     ("NB",),
            **_PR14E_LEGACY_WINDOW,
        },
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
        # PR #14E Q2 + Q3 — A1 cohort sources pkdm-hqz6
        # ALTERATION TYPE 1; no yearbuilt filter (Q3: NB-only).
        "modern_path": {
            "pkdm_job_types":         ("ALTERATION TYPE 1",),
            "yearbuilt_filter_min":   None,
            "apply_yearbuilt_filter": False,
        },
        "legacy_path": {
            "bis_job_types":     ("A1",),
            **_PR14E_LEGACY_WINDOW,
            # T4 PR #14B carry-over: A1 → NB secondary fallback
            # remains on the Legacy path so PR #14B coverage doesn't
            # regress when Modern is unavailable.
            "secondary_fallback": {
                "expands_to":    "new_building",
                "trigger_below": 30,
            },
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
        # PR #14E Q2 + Q3 — minor_alt cohort sources pkdm-hqz6
        # 'Alteration CO'; no yearbuilt filter, no story filter.
        "modern_path": {
            "pkdm_job_types":         ("Alteration CO",),
            "yearbuilt_filter_min":   None,
            "apply_yearbuilt_filter": False,
        },
        "legacy_path": {
            "bis_job_types":     ("A2", "A3"),
            **_PR14E_LEGACY_WINDOW,
        },
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
        # PR #14E Q4 lock — full_demo has NO modern path.
        # pkdm-hqz6 is a C of O (occupancy) dataset; demolished
        # buildings don't get C of O. Cohort stays BIS DM only.
        # _fetch_demo_cohort handles the dedicated path (T7 lock).
        "modern_path": None,
        "legacy_path": {
            "bis_job_types":     ("DM",),
            **_PR14E_LEGACY_WINDOW,
        },
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
