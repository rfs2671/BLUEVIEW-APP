"""PR #14B Stage 2.B — cohort framework + classifier + parser tests.

Three test classes covering the three NEW modules PR #14B adds:

  • TestCohortConfig — lib/statistical_engine/cohort_config.py
    Table-driven cohort spec per dob_project_type enum.

  • TestDobNowParser — lib/statistical_engine/dob_now_parser.py
    parse_dob_now_description() regex + keyword extraction.

  • TestFetchProjectDobClassification —
    lib/statistical_engine/dob_classifier.py
    DOB NOW primary → BIS fallback → unknown classification chain.

All 24 tests written failing for the red phase. Stage 3 lands the
production modules and these tests turn green.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))


def _run(coro):
    return asyncio.run(coro)


# ─── Lazy imports — modules don't exist until Stage 3 lands ──────

try:
    from lib.statistical_engine.cohort_config import (  # type: ignore
        COHORT_CONFIG,
        compute_tolerance_band,
    )
    HAS_COHORT_CONFIG = True
except ImportError:
    COHORT_CONFIG = None  # type: ignore
    compute_tolerance_band = None  # type: ignore
    HAS_COHORT_CONFIG = False

try:
    from lib.statistical_engine.dob_now_parser import (  # type: ignore
        parse_dob_now_description,
    )
    HAS_DOB_NOW_PARSER = True
except ImportError:
    parse_dob_now_description = None  # type: ignore
    HAS_DOB_NOW_PARSER = False

try:
    from lib.statistical_engine.dob_classifier import (  # type: ignore
        fetch_project_dob_classification,
    )
    HAS_DOB_CLASSIFIER = True
except ImportError:
    fetch_project_dob_classification = None  # type: ignore
    HAS_DOB_CLASSIFIER = False


# ─── Test infrastructure imports ──────────────────────────────────

from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    DATASET_BIS_JOB_FILINGS,
    DATASET_C_OF_O_LEGACY,
    DATASET_DOB_PERMITS,
    seed_dob_now_for_bin,
    seed_bis_for_bin,
    seed_c_of_o_for_job,
)


# ──────────────────────────────────────────────────────────────────
# Test Class 1 — TestCohortConfig (6 tests)
# ──────────────────────────────────────────────────────────────────


class TestCohortConfig(unittest.TestCase):
    """Verify the table-driven cohort spec at
    ``lib/statistical_engine/cohort_config.py``. Pure config tests —
    no DB, no Socrata.

    Locked design (Stage 2.A T4): five project types with distinct
    cohort specs. ``unknown`` returns ``None`` to signal "skip
    cohort matching."
    """

    def _require_cohort_config(self):
        if not HAS_COHORT_CONFIG:
            self.fail(
                "lib.statistical_engine.cohort_config module not "
                "implemented. Stage 3: create the module with a "
                "COHORT_CONFIG dict (keys: new_building, "
                "major_alt_with_enlargement, minor_alt, full_demo) "
                "plus a compute_tolerance_band(value, pct, min_band) "
                "helper."
            )

    def test_new_building_spec_has_required_filter_fields(self):
        """Test 1 — new_building spec contains the locked filter set
        + tolerance bands + geography ladder + completion rule."""
        self._require_cohort_config()
        spec = COHORT_CONFIG.get("new_building")
        self.assertIsNotNone(
            spec, "COHORT_CONFIG missing 'new_building' entry"
        )
        self.assertIn("filter_fields", spec)
        for required in (
            "building_class",
            "story_count_band",
            "dwelling_units_band",
            "geography",
        ):
            self.assertIn(
                required, spec["filter_fields"],
                f"new_building filter_fields missing {required!r}; "
                f"got {spec['filter_fields']!r}",
            )
        self.assertIn("story_count_tolerance", spec)
        self.assertIn("dwelling_units_tolerance", spec)
        self.assertIn("geography_ladder", spec)
        self.assertIn("completion_filter", spec)

        # PR #14E — Modern path config (Q2 lock + Q3 yearbuilt filter).
        self.assertIn(
            "modern_path", spec,
            "PR #14E: new_building spec must carry a modern_path "
            "config dict. Stage 3: add to COHORT_CONFIG entries "
            "(cohort_config.py). Shape: "
            "{'pkdm_job_types': tuple, 'yearbuilt_filter_min': int}.",
        )
        modern = spec["modern_path"]
        self.assertIsNotNone(modern,
            "new_building HAS a modern path; only full_demo has "
            "modern_path=None (Q4 lock).")
        self.assertIn("pkdm_job_types", modern)
        # Risk 3: both casings of NEW BUILDING per pkdm-hqz6 vocab.
        pkdm_types = set(modern["pkdm_job_types"])
        self.assertEqual(
            pkdm_types, {"NEW BUILDING", "New Building"},
            "new_building.modern_path.pkdm_job_types must include "
            "both 'NEW BUILDING' and 'New Building' (Risk 3 case "
            "variants in pkdm-hqz6 enum).",
        )
        # Q3 lock: NB cohort applies yearbuilt >= 2000 filter.
        self.assertEqual(
            modern.get("yearbuilt_filter_min"), 2000,
            "new_building.modern_path.yearbuilt_filter_min must "
            "be 2000 (Q3 lock — modern-era construction peers).",
        )
        # PR #14E — Legacy path config (Q7 fallback).
        self.assertIn("legacy_path", spec)
        legacy = spec["legacy_path"]
        self.assertIn("bis_job_types", legacy)
        self.assertIn("NB", legacy["bis_job_types"])

    def test_major_alt_with_enlargement_secondary_fallback_to_nb(self):
        """Test 2 — operator's spec: when major_alt cohort < 30,
        secondary_fallback expands to include new_building cohort."""
        self._require_cohort_config()
        spec = COHORT_CONFIG.get("major_alt_with_enlargement")
        self.assertIsNotNone(spec)
        self.assertIn(
            "secondary_fallback", spec,
            "major_alt_with_enlargement spec missing "
            "secondary_fallback per operator's Stage 2.A T4 lock",
        )
        self.assertEqual(
            spec["secondary_fallback"].get("expands_to"),
            "new_building",
            "secondary_fallback should expand to new_building cohort",
        )

        # PR #14E — Modern path: ALTERATION TYPE 1; no yearbuilt filter (Q3).
        self.assertIn("modern_path", spec)
        modern = spec["modern_path"]
        self.assertIsNotNone(modern)
        self.assertIn(
            "ALTERATION TYPE 1", modern.get("pkdm_job_types", []),
            "major_alt_with_enlargement.modern_path.pkdm_job_types "
            "must include 'ALTERATION TYPE 1' per Stage 1 Task 4 "
            "enum discovery.",
        )
        self.assertIsNone(
            modern.get("yearbuilt_filter_min"),
            "A1 cohort must NOT filter by yearbuilt (Q3 lock — "
            "filter applies to NB only).",
        )
        # Legacy path preserves PR #14B secondary_fallback semantics.
        self.assertIn("legacy_path", spec)
        self.assertIn(
            "secondary_fallback", spec["legacy_path"],
            "Legacy path retains secondary_fallback (A1 → NB merge "
            "when primary < 30) per PR #14B T4 lock.",
        )

    def test_minor_alt_spec_no_story_or_unit_filtering(self):
        """Test 3 — minor_alt is a broad bucket; should NOT filter on
        story_count or dwelling_units (matches operator's T4 default
        behavior for ambiguous General Construction)."""
        self._require_cohort_config()
        spec = COHORT_CONFIG.get("minor_alt")
        self.assertIsNotNone(spec)
        filter_fields = spec.get("filter_fields", [])
        self.assertNotIn(
            "story_count_band", filter_fields,
            "minor_alt should NOT filter on story count",
        )
        self.assertNotIn(
            "dwelling_units_band", filter_fields,
            "minor_alt should NOT filter on dwelling units",
        )
        bis_types = spec.get("bis_job_types") or spec.get("job_types") or []
        self.assertEqual(
            set(bis_types), {"A2", "A3"},
            "minor_alt should map to BIS job_types A2 + A3",
        )

        # PR #14E — Modern path: Alteration CO; no yearbuilt filter.
        self.assertIn("modern_path", spec)
        modern = spec["modern_path"]
        self.assertIsNotNone(modern)
        self.assertIn(
            "Alteration CO", modern.get("pkdm_job_types", []),
            "minor_alt.modern_path.pkdm_job_types must include "
            "'Alteration CO' per Stage 1 Task 1 pkdm-hqz6 enum.",
        )
        self.assertIsNone(modern.get("yearbuilt_filter_min"))

    def test_full_demo_spec_uses_demolished_attributes(self):
        """Test 4 — full_demo cohort filters on the DEMOLISHED
        structure's attributes (from PLUTO snapshot frozen at
        project-create time per Risk 7 lock)."""
        self._require_cohort_config()
        spec = COHORT_CONFIG.get("full_demo")
        self.assertIsNotNone(spec)
        filter_fields = spec.get("filter_fields", [])
        self.assertIn(
            "building_class_demolished", filter_fields,
            "full_demo must filter on demolished structure's bldgclass",
        )
        bis_types = spec.get("bis_job_types") or spec.get("job_types") or []
        self.assertIn("DM", bis_types)

        # PR #14E Q4 lock: full_demo has NO modern path (pkdm-hqz6
        # has no DEMOLITION job_type; C of O is for OCCUPANCY).
        # Cohort stays BIS DM only.
        self.assertIn("modern_path", spec,
            "full_demo spec must EXPLICITLY carry modern_path key "
            "set to None (Q4 lock) — distinguishes 'BIS-only by "
            "design' from 'missing config'.")
        self.assertIsNone(
            spec["modern_path"],
            "full_demo.modern_path must be None per Q4 lock — "
            "pkdm-hqz6 has no DEMOLITION job_type so cohort sources "
            "from BIS DM only. _fetch_demo_cohort handles this path "
            "(T7 lock).",
        )
        # Legacy path still carries DM.
        self.assertIn("legacy_path", spec)
        self.assertIn("DM", spec["legacy_path"].get("bis_job_types", []))

    def test_unknown_project_type_returns_no_cohort_spec(self):
        """Test 5 — unknown is a marker meaning 'classifier failed';
        caller must handle (skip cohort, prompt user)."""
        self._require_cohort_config()
        self.assertIsNone(
            COHORT_CONFIG.get("unknown"),
            "COHORT_CONFIG['unknown'] should return None (signal "
            "for caller to skip cohort matching).",
        )

    def test_tolerance_band_helper_clamps_at_minimum(self):
        """Test 6 — compute_tolerance_band(value, pct, min_band)
        applies ±pct rounded to int, clamped to ±min_band minimum.

        Examples:
          • compute_tolerance_band(5, 0.25, 1)  → (4, 6)   # 5 ± 25% = 5 ± 1.25 → 5 ± 1 (rounded)
          • compute_tolerance_band(2, 0.25, 1)  → (1, 3)   # 2 ± 0.5 → 2 ± 1 (min clamp)
          • compute_tolerance_band(20, 0.25, 2) → (15, 25) # 20 ± 5; band > min, band wins
          • compute_tolerance_band(0, 0.25, 2)  → (0, 2)   # value=0, min=2 floor on lower bound
        """
        self._require_cohort_config()
        self.assertEqual(
            compute_tolerance_band(5, 0.25, 1),
            (4, 6),
            "5 ± 25% should expand to (4, 6)",
        )
        self.assertEqual(
            compute_tolerance_band(2, 0.25, 1),
            (1, 3),
            "2 ± 25% (= ±0.5) should clamp to min ±1 → (1, 3)",
        )
        self.assertEqual(
            compute_tolerance_band(20, 0.25, 2),
            (15, 25),
            "20 ± 25% (= ±5) > min ±2; band-side wins → (15, 25)",
        )


# ──────────────────────────────────────────────────────────────────
# Test Class 2 — TestDobNowParser (10 tests)
# ──────────────────────────────────────────────────────────────────


class TestDobNowParser(unittest.TestCase):
    """Verify ``parse_dob_now_description(description, work_type)``
    in ``lib/statistical_engine/dob_now_parser.py``.

    Returns dict: ``{story_count, dwelling_units, use_type,
    enlargement, extracted_at}`` with field set to None when
    extraction isn't confident (per Task 6 feasibility analysis).
    """

    def _require_parser(self):
        if not HAS_DOB_NOW_PARSER:
            self.fail(
                "lib.statistical_engine.dob_now_parser.parse_dob_now_description "
                "not implemented. Stage 3: create module with parser "
                "that returns {story_count, dwelling_units, use_type, "
                "enlargement, extracted_at}."
            )

    def test_parse_story_count_from_explicit_pattern(self):
        """Test 7 — 'X STORY' or 'X STORY ...' → story_count=X."""
        self._require_parser()
        result = parse_dob_now_description(
            "5 STORY MIXED USE BUILDING", "General Construction",
        )
        self.assertEqual(result.get("story_count"), 5)

    def test_parse_story_count_hyphenated(self):
        """Test 8 — 'X-STORY' hyphenated form."""
        self._require_parser()
        result = parse_dob_now_description(
            "NEW 5-STORY RESIDENTIAL BUILDING", "General Construction",
        )
        self.assertEqual(result.get("story_count"), 5)

    def test_parse_story_count_pluralized(self):
        """Test 9 — 'X STORIES' pluralized form."""
        self._require_parser()
        result = parse_dob_now_description(
            "BUILDING WITH 5 STORIES AND ROOFTOP DECK",
            "General Construction",
        )
        self.assertEqual(result.get("story_count"), 5)

    def test_parse_dwelling_units_explicit(self):
        """Test 10 — 'X DWELLING UNITS' verbatim."""
        self._require_parser()
        result = parse_dob_now_description(
            "PROPOSED 8 DWELLING UNITS PER PLANS",
            "General Construction",
        )
        self.assertEqual(result.get("dwelling_units"), 8)

    def test_parse_dwelling_units_short_form(self):
        """Test 11 — 'X UNITS' short form."""
        self._require_parser()
        result = parse_dob_now_description(
            "12 UNITS RESIDENTIAL APARTMENT BUILDING",
            "General Construction",
        )
        self.assertEqual(result.get("dwelling_units"), 12)

    def test_parse_enlargement_flag_explicit_keyword(self):
        """Test 12 — 'ENLARGEMENT' family of keywords."""
        self._require_parser()
        result = parse_dob_now_description(
            "VERTICAL ENLARGEMENT OF EXISTING 3-STORY BUILDING",
            "General Construction",
        )
        self.assertTrue(result.get("enlargement"))

    def test_parse_enlargement_flag_extension_synonym(self):
        """Test 13 — 'EXTENSION' / 'ADDITION' as enlargement synonyms."""
        self._require_parser()
        result = parse_dob_now_description(
            "REAR EXTENSION ADDING 200 SQFT TO 1ST FLOOR",
            "General Construction",
        )
        self.assertTrue(result.get("enlargement"))

    def test_parse_use_type_residential(self):
        """Test 14 — 'RESIDENTIAL' / 'APARTMENT' / 'FAMILY' → residential."""
        self._require_parser()
        result = parse_dob_now_description(
            "5-STORY RESIDENTIAL APARTMENT BUILDING WITH 8 UNITS",
            "General Construction",
        )
        self.assertEqual(result.get("use_type"), "residential")

    def test_parse_use_type_commercial(self):
        """Test 15 — 'COMMERCIAL' / 'OFFICE' / 'RETAIL' → commercial."""
        self._require_parser()
        result = parse_dob_now_description(
            "COMMERCIAL TENANT FIT-OUT 2ND FLOOR OFFICE SPACE",
            "General Construction",
        )
        self.assertEqual(result.get("use_type"), "commercial")

    def test_parse_returns_safe_defaults_when_unextractable(self):
        """Test 16 — facade-repair-style description with no scope
        signals: parser returns None / False / 'other' for each
        field (no false positives)."""
        self._require_parser()
        result = parse_dob_now_description(
            "FACADE REPAIRS AS PER PLANS. NO CHANGE IN USE, "
            "OCCUPANCY OR EGRESS.",
            "General Construction",
        )
        self.assertIsNone(result.get("story_count"))
        self.assertIsNone(result.get("dwelling_units"))
        self.assertFalse(
            result.get("enlargement"),
            "Facade repair must NOT be classified as enlargement",
        )
        self.assertEqual(result.get("use_type"), "other")

    def test_extract_enlargement_returns_false_on_negation(self):
        """PR #14E §7.1 + T2 lock — negation keywords win over
        positive enlargement keywords.

        Pre-PR-14E parser matched literal "ENLARGEMENT" as positive
        without checking for "NO ENLARGEMENT" / "NOT ENLARGED" / etc.
        Stage 1 Task 5 sample BIN 3057867 had description ending
        "...NO ENLARGEMENT IS PROPOSED. REMOVE PART EXT WALL..." —
        classifier mis-categorized as major_alt_with_enlargement.

        Stage 3 fix (dob_now_parser._extract_enlargement):
          NEGATION_KEYWORDS = (
              "NO ENLARGEMENT",
              "NOT ENLARGED",
              "WITHOUT ENLARGEMENT",
              "NO INCREASE IN BULK",
          )
          if any(neg in text for neg in NEGATION_KEYWORDS):
              return False  # negation wins, even if positive
                            # enlargement/extension/addition keyword
                            # also appears
          return any(kw in text for kw in _ENLARGEMENT_KEYWORDS)
        """
        self._require_parser()
        # Case A: explicit "NO ENLARGEMENT" alongside a positive
        # extension keyword. Negation must win.
        result = parse_dob_now_description(
            "REAR EXTENSION 200 SQFT TO 1ST FLOOR. NO ENLARGEMENT "
            "IS PROPOSED. STRUCTURAL SCOPE FILED SEPARATE.",
            "General Construction",
        )
        self.assertFalse(
            result.get("enlargement"),
            "Explicit 'NO ENLARGEMENT' must beat positive "
            "EXTENSION/ENLARGEMENT keyword. Stage 3 §7.1 + T2 lock: "
            "add NEGATION_KEYWORDS pre-filter to "
            "dob_now_parser._extract_enlargement (lib/statistical_engine/"
            "dob_now_parser.py)."
        )
        # Case B: "WITHOUT ENLARGEMENT" variant.
        result_b = parse_dob_now_description(
            "INTERIOR PARTITION WORK WITHOUT ENLARGEMENT.",
            "General Construction",
        )
        self.assertFalse(result_b.get("enlargement"))
        # Case C: positive enlargement language stays positive when
        # NO negation present. Defensive regression check.
        result_c = parse_dob_now_description(
            "VERTICAL ENLARGEMENT OF EXISTING 3-STORY BUILDING.",
            "General Construction",
        )
        self.assertTrue(
            result_c.get("enlargement"),
            "Positive enlargement description with NO negation "
            "must still return True. Negation gate should not "
            "over-fire.",
        )


# ──────────────────────────────────────────────────────────────────
# Test Class 3 — TestFetchProjectDobClassification (8 tests)
# ──────────────────────────────────────────────────────────────────


class _StubProjectsForClassifier:
    """Minimal Mongo `projects` stub for classifier persistence
    tests. Records update_one calls so tests can assert the
    classifier persisted the right $set payload.
    """

    def __init__(self, projects=None):
        self.docs = list(projects or [])
        self.update_one_calls: List[Dict[str, Any]] = []

    async def update_one(self, filter_doc, update_doc, **kwargs):
        self.update_one_calls.append(
            {"filter": filter_doc, "update": update_doc}
        )
        target_id = filter_doc.get("_id")
        for d in self.docs:
            if d.get("_id") == target_id:
                set_clause = update_doc.get("$set", {})
                for k, v in set_clause.items():
                    d[k] = v
        r = MagicMock()
        r.matched_count = 1
        r.modified_count = 1
        return r


class _StubDbForClassifier:
    def __init__(self, projects=None):
        self.projects = _StubProjectsForClassifier(projects)


class TestFetchProjectDobClassification(unittest.TestCase):
    """Verify ``fetch_project_dob_classification(socrata, project, db)``.

    Per Stage 2.A T4 (refined): full_demo from work_type only;
    explicit NB keywords required for new_building; explicit
    enlargement keywords for major_alt_with_enlargement; default
    minor_alt for unmatched General Construction; BIS fallback
    before unknown.
    """

    def _require_classifier(self):
        if not HAS_DOB_CLASSIFIER:
            self.fail(
                "lib.statistical_engine.dob_classifier."
                "fetch_project_dob_classification not implemented. "
                "Stage 3: create module with the function that "
                "queries DOB NOW primary, BIS fallback, returns "
                "(type, snapshot) tuple and persists to project doc."
            )

    def test_dob_now_full_demolition_classifies_as_full_demo(self):
        """Test 17 — work_type='Full Demolition' is the strongest
        signal. Bypasses job_description parsing."""
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="1234567",
            work_type="Full Demolition",
            filing_reason="Initial Permit",
            job_description="DEMOLISH EXISTING 3-STORY BUILDING",
        )
        db = _StubDbForClassifier(projects=[{"_id": "P1", "nyc_bin": "1234567"}])
        project = {"_id": "P1", "nyc_bin": "1234567"}
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "full_demo")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.get("work_type"), "Full Demolition")

    def test_dob_now_general_construction_with_nb_keywords_classifies_as_new_building(self):
        """Test 18 — 'NEW BUILDING' / 'NEW CONSTRUCTION' keywords
        explicit in job_description → new_building."""
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="2234567",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description=(
                "NEW BUILDING - 5-STORY RESIDENTIAL APARTMENT "
                "BUILDING WITH 8 DWELLING UNITS"
            ),
        )
        db = _StubDbForClassifier(projects=[{"_id": "P2", "nyc_bin": "2234567"}])
        project = {"_id": "P2", "nyc_bin": "2234567"}
        proj_type, _ = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "new_building")

    def test_dob_now_general_construction_with_enlargement_keywords_classifies_as_major_alt(self):
        """Test 19 — enlargement keywords without NB keywords →
        major_alt_with_enlargement."""
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="3234567",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description=(
                "VERTICAL ENLARGEMENT OF EXISTING 2-STORY BUILDING "
                "ADDING 3RD FLOOR"
            ),
        )
        db = _StubDbForClassifier(projects=[{"_id": "P3", "nyc_bin": "3234567"}])
        project = {"_id": "P3", "nyc_bin": "3234567"}
        proj_type, _ = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "major_alt_with_enlargement")

    def test_dob_now_general_construction_ambiguous_defaults_to_minor_alt(self):
        """Test 20 — per T4 default: General Construction + Initial
        Permit + no NB/enlargement keywords → minor_alt (safe broad
        bucket).
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="4234567",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description=(
                "INTERIOR RENOVATION OF APARTMENT 2B. NO CHANGE IN "
                "USE, EGRESS OR OCCUPANCY."
            ),
        )
        db = _StubDbForClassifier(projects=[{"_id": "P4", "nyc_bin": "4234567"}])
        project = {"_id": "P4", "nyc_bin": "4234567"}
        proj_type, _ = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(
            proj_type, "minor_alt",
            "Ambiguous General Construction must default to minor_alt "
            "per T4. Got: " + repr(proj_type),
        )

    def test_bis_fallback_when_dob_now_returns_empty(self):
        """Test 21 — DOB NOW has no rows for BIN; BIS fallback hits
        a NB row → new_building from BIS.
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        # NO DOB NOW seed. BIS has an NB filing.
        seed_bis_for_bin(
            socrata, bin="5234567", job_number="320100100",
            job_type="NB", building_class="C1", borough="BROOKLYN",
        )
        db = _StubDbForClassifier(projects=[{"_id": "P5", "nyc_bin": "5234567"}])
        project = {"_id": "P5", "nyc_bin": "5234567"}
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "new_building")
        self.assertEqual(
            snapshot.get("source"), "bis_fallback",
            "BIS-derived classifications should mark source='bis_fallback' "
            "for diagnostics",
        )

    def test_bis_a1_classifies_as_major_alt_with_enlargement(self):
        """Test 22 — BIS fallback: job_type='A1' →
        major_alt_with_enlargement (A1 = Alt-1 enlargement).
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_bis_for_bin(
            socrata, bin="6234567", job_number="320200200",
            job_type="A1", building_class="R6", borough="BROOKLYN",
        )
        db = _StubDbForClassifier(projects=[{"_id": "P6", "nyc_bin": "6234567"}])
        project = {"_id": "P6", "nyc_bin": "6234567"}
        proj_type, _ = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "major_alt_with_enlargement")

    def test_all_sources_fail_returns_unknown_with_marker(self):
        """Test 23 — BIN not in either DOB NOW or BIS → ('unknown',
        snapshot_with_failure_reason).
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        # Both empty. Initialize the dataset pools so the WHERE
        # evaluator has something to filter (and returns nothing).
        socrata.seed(DATASET_DOB_PERMITS, [])
        socrata.seed(DATASET_BIS_JOB_FILINGS, [])
        db = _StubDbForClassifier(projects=[{"_id": "P7", "nyc_bin": "7234567"}])
        project = {"_id": "P7", "nyc_bin": "7234567"}
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, project, db,
        ))
        self.assertEqual(proj_type, "unknown")
        self.assertIn(
            "unable_to_classify_reason", snapshot,
            "unknown classification must carry a "
            "'unable_to_classify_reason' marker so operator can "
            "diagnose without re-querying Socrata",
        )

    def test_classification_persists_dob_job_snapshot_on_project_doc(self):
        """Test 24 — successful classification persists three fields:
        dob_project_type, dob_job_snapshot, dob_extracted_scope.
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="8234567",
            work_type="General Construction",
            filing_reason="Initial Permit",
            job_description="NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS",
        )
        db = _StubDbForClassifier(projects=[{"_id": "P8", "nyc_bin": "8234567"}])
        project = {"_id": "P8", "nyc_bin": "8234567"}
        _run(fetch_project_dob_classification(socrata, project, db))
        self.assertEqual(
            len(db.projects.update_one_calls), 1,
            "classifier must call db.projects.update_one exactly once",
        )
        set_payload = db.projects.update_one_calls[0]["update"].get("$set", {})
        for field in (
            "dob_project_type",
            "dob_job_snapshot",
            "dob_extracted_scope",
        ):
            self.assertIn(
                field, set_payload,
                f"classifier $set missing {field!r}; got "
                f"{sorted(set_payload.keys())!r}",
            )

    # ──────────────────────────────────────────────────────────
    # PR #14D tests — classifier fixes (Bug 1 from production)
    # ──────────────────────────────────────────────────────────

    def test_classifier_filters_to_i1_jobs_via_like_clause(self):
        """PR #14D — Classifier WHERE clause must filter to initial
        (-I1) filings, ignoring subsequent (-S4 etc.) filings.

        Production Bug 1 root cause: B00736930-I1 (the actual
        Menahan A1 project) was overshadowed by B00736930-S4
        (Foundation, a later subsequent filing) because the
        classifier picked the first DOB NOW row by raw query order.
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        # Seed two rows for the same BIN: -I1 General Construction
        # and -S4 Foundation. Both have scope-ish work_types but
        # only the -I1 carries the project-defining description.
        socrata.seed(DATASET_DOB_PERMITS, [
            {
                "bin": "1234567",
                "job_filing_number": "B11234567-S4",
                "work_type": "Foundation",
                "filing_reason": "Initial Permit",
                "job_description": "FOUNDATION WORK PER PLANS.",
                "approved_date": "2024-03-15T00:00:00.000",
            },
            {
                "bin": "1234567",
                "job_filing_number": "B11234567-I1",
                "work_type": "General Construction",
                "filing_reason": "Initial Permit",
                "job_description": (
                    "NEW BUILDING 5-STORY RESIDENTIAL 8 UNITS"
                ),
                "approved_date": "2022-01-01T00:00:00.000",
            },
        ])
        db = _StubDbForClassifier(projects=[
            {"_id": "P_LIKE", "nyc_bin": "1234567"},
        ])
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, {"_id": "P_LIKE", "nyc_bin": "1234567"}, db,
        ))
        self.assertEqual(
            proj_type, "new_building",
            f"Classifier picked the wrong row. Expected new_building "
            f"from B11234567-I1 General Construction; got "
            f"{proj_type!r}. Stage 3 Fix 1: update "
            f"_classify_via_dob_now WHERE clause in "
            f"dob_classifier.py:~166 to "
            f"``bin = '...' AND (job_filing_number LIKE '%-I1' OR "
            f"job_filing_number LIKE '%-I1-%')`` + "
            f"``ORDER BY approved_date ASC``."
        )
        # Verify the WHERE clause actually issued contains -I1.
        permit_calls = [c for c in socrata.calls if c[0] == DATASET_DOB_PERMITS]
        self.assertGreater(len(permit_calls), 0)
        where_clauses = " | ".join(
            (c[1].get("where") or "") for c in permit_calls
        )
        self.assertIn(
            "-I1", where_clauses,
            f"DOB NOW WHERE clause must filter to -I1 suffix. "
            f"Stage 3 Fix 1: add LIKE '%-I1' to the query. "
            f"WHERE observed: {where_clauses!r}"
        )

    def test_dob_now_only_auxiliary_rows_triggers_bis_fallback(self):
        """PR #14D Q1 lock — DOB NOW returns rows but ALL are
        auxiliary work_types (no General Construction / Full
        Demolition). Classifier must fall through to BIS, not
        pick rows[0] (which would default to minor_alt).

        This is the structural Stage 1 Task 2 finding: many A1
        projects have NO General Construction row in DOB NOW —
        the A1 filing lives in BIS, and DOB NOW only carries
        auxiliary trades.
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        # DOB NOW: only Plumbing (auxiliary trade).
        seed_dob_now_for_bin(
            socrata, bin="2234567",
            job_filing_number="B12234567-I1",
            work_type="Plumbing",
            filing_reason="Initial Permit",
            job_description="NEW FIXTURES THROUGHOUT.",
        )
        # BIS: A1 → expects major_alt_with_enlargement.
        seed_bis_for_bin(
            socrata, bin="2234567", job_number="322021441",
            job_type="A1", building_class="C1", borough="BROOKLYN",
        )
        db = _StubDbForClassifier(projects=[
            {"_id": "P_AUX", "nyc_bin": "2234567"},
        ])
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, {"_id": "P_AUX", "nyc_bin": "2234567"}, db,
        ))
        self.assertEqual(
            proj_type, "major_alt_with_enlargement",
            f"DOB NOW Plumbing row is not scope-carrying; classifier "
            f"must fall through to BIS classification (A1 → "
            f"major_alt_with_enlargement). Got {proj_type!r}. "
            f"Stage 3 Q1 lock: in _classify_via_dob_now "
            f"(dob_classifier.py:~155), filter rows to scope-carrying "
            f"work_types and when preferred list is empty, return "
            f"(None, {{}}, {{}}) to trigger _classify_via_bis."
        )
        # Per Q2 lock: snapshot.source stays "bis_fallback" (don't
        # proliferate source variants).
        self.assertEqual(
            snapshot.get("source"), "bis_fallback",
            f"Per Q2 lock, snapshot.source must be 'bis_fallback' "
            f"when the BIS-fallback path fires (regardless of "
            f"whether DOB NOW had non-scope rows or was empty). "
            f"Got {snapshot.get('source')!r}."
        )

    def test_dob_now_construction_fence_with_bis_dm_classifies_as_full_demo(self):
        """PR #14D Q1 lock — Realistic full_demo project shape:
        DOB NOW has only Construction Fence rows, BIS has DM
        job_type. Parallel to the auxiliary→A1 test but exercises
        the DM (Full Demolition) BIS-fallback path.
        """
        self._require_classifier()
        socrata = MockSocrataClient()
        seed_dob_now_for_bin(
            socrata, bin="3234567",
            job_filing_number="B13234567-I1",
            work_type="Construction Fence",
            filing_reason="Initial Permit",
            job_description="INSTALLATION OF FENCE AS PER PLANS.",
        )
        seed_bis_for_bin(
            socrata, bin="3234567", job_number="322103157",
            job_type="DM", building_class="A2", borough="BROOKLYN",
        )
        db = _StubDbForClassifier(projects=[
            {"_id": "P_DM", "nyc_bin": "3234567"},
        ])
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata, {"_id": "P_DM", "nyc_bin": "3234567"}, db,
        ))
        self.assertEqual(
            proj_type, "full_demo",
            f"DM (Demolition) BIS row should classify as full_demo "
            f"even when DOB NOW has only Construction Fence rows. "
            f"Got {proj_type!r}. Stage 3 Q1 lock: same "
            f"scope-carrying fallback to BIS as the A1/Plumbing test."
        )
        self.assertEqual(snapshot.get("source"), "bis_fallback")

    def test_menahan_real_data_classifies_as_major_alt_with_enlargement(self):
        """PR #14D T3 lock — Real Menahan DOB NOW data (5 rows
        from operator's curl probe). Classifier MUST pick
        B00736930-I1 General Construction (the scope-carrying row
        with VERTICAL AND HORIZONTAL ENLARGEMENT language) and
        classify as major_alt_with_enlargement.

        This is the canary fixture: real curl data → real fixture
        → real test → real confidence at Stage 10 verification.
        """
        self._require_classifier()
        from _pr14b_fixtures import seed_menahan_realistic_dob_now
        socrata = MockSocrataClient()
        meta = seed_menahan_realistic_dob_now(socrata)
        db = _StubDbForClassifier(projects=[
            {"_id": "P_MENAHAN_REAL", "nyc_bin": meta["bin"]},
        ])
        proj_type, snapshot = _run(fetch_project_dob_classification(
            socrata,
            {"_id": "P_MENAHAN_REAL", "nyc_bin": meta["bin"]},
            db,
        ))
        self.assertEqual(
            proj_type, meta["expected_type"],
            f"Real Menahan classification regression. Expected "
            f"{meta['expected_type']!r}, got {proj_type!r}. "
            f"Investigation trail: PR #14D Bug 1 — pre-fix "
            f"classifier was picking B00736930-S4 Foundation (a "
            f"renewal subsequent filing) instead of the actual "
            f"B00736930-I1 General Construction row. Stage 3 fix: "
            f"-I1 suffix filter + scope-carrying work_type "
            f"preference. The selected row's job_filing_number "
            f"should be {meta['scope_row_job']}."
        )
        self.assertEqual(
            snapshot.get("job_filing_number"), meta["scope_row_job"],
            f"Classifier selected the wrong row. Snapshot "
            f"job_filing_number={snapshot.get('job_filing_number')!r}, "
            f"expected {meta['scope_row_job']!r} (the General "
            f"Construction row with vertical/horizontal enlargement "
            f"description)."
        )


if __name__ == "__main__":
    unittest.main()
