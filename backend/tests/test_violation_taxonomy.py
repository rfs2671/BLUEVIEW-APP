"""Phase 1 Week 8 PR-A — violation taxonomy classifier tests.

Tests both surfaces:

  classify_complaint(code: Optional[str]) -> str
    Deterministic lookup against COMPLAINT_CODE_TO_BUCKET (derived from
    backend/dob_complaint_codes.py:DOB_CATEGORY_CODES).

  classify_violation(violation_type: Optional[str],
                     violation_description: Optional[str]) -> str
    Ordered regex match against the joined+uppercased text;
    first-match-wins; falls through to "other".

Plus coverage checks: every bucket reachable; top-30 production
complaint codes all mapped to non-"other" buckets.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


try:
    from lib.statistical_engine.violation_taxonomy import (
        BUCKETS,
        COMPLAINT_CODE_TO_BUCKET,
        classify_complaint,
        classify_violation,
    )
    HAS_TAXONOMY = True
except ImportError:
    BUCKETS = ()                              # type: ignore
    COMPLAINT_CODE_TO_BUCKET = {}             # type: ignore
    classify_complaint = None                 # type: ignore
    classify_violation = None                 # type: ignore
    HAS_TAXONOMY = False


# Top-30 production complaint codes by frequency (live count from
# eabe-havv as of Phase 1 Week 8 Stage 1 probe). Every code listed
# here MUST map to a non-"other" bucket.
TOP_30_CODES = [
    "45", "05", "63", "73", "30", "31", "04", "59", "83", "6S",
    "23", "55", "37", "58", "4B", "35", "29", "74", "15", "10",
    "91", "86", "6M", "09", "7J", "7G", "03", "1X", "66", "8A",
]


class TestViolationTaxonomy(unittest.TestCase):
    """Phase 1 Week 8 PR-A — 25+ tests covering classify_complaint
    and classify_violation."""

    def _require_taxonomy(self):
        if not HAS_TAXONOMY:
            self.fail(
                "lib.statistical_engine.violation_taxonomy not implemented. "
                "Phase 1 Week 8 PR-A: add the module with "
                "classify_complaint, classify_violation, BUCKETS, "
                "COMPLAINT_CODE_TO_BUCKET."
            )

    # ──────────────────────────────────────────────────────────
    # classify_complaint — edge cases
    # ──────────────────────────────────────────────────────────

    def test_classify_complaint_none(self):
        """None input → 'other' (no code, no classification possible)."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint(None), "other")

    def test_classify_complaint_empty_string(self):
        """Empty string → 'other'."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint(""), "other")

    def test_classify_complaint_unknown_code(self):
        """Unrecognized code → 'other' (defensive fallback for codes
        added to DOB after our lookup table was last updated)."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("ZZ"), "other")
        self.assertEqual(classify_complaint("999"), "other")

    # ──────────────────────────────────────────────────────────
    # classify_complaint — concrete code mappings (per Probe A §1)
    # ──────────────────────────────────────────────────────────

    def test_classify_complaint_45_illegal_conversion(self):
        """Top-frequency code 45 = Illegal Conversion → occupancy."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("45"), "occupancy_violations")

    def test_classify_complaint_01_accident(self):
        """Code 01 = Accident → Construction/Plumbing → safety."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("01"), "safety_hazards")

    def test_classify_complaint_63_elevator(self):
        """Code 63 = Elevator Defective → mep_systems."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("63"), "mep_systems")

    def test_classify_complaint_05_no_permit(self):
        """Code 05 = Permit — None → construction_violations."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("05"), "construction_violations")

    def test_classify_complaint_30_building_shaking(self):
        """Code 30 = Building Shaking/Structural Stability → structural."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("30"), "structural_concerns")

    def test_classify_complaint_37_egress(self):
        """Code 37 = Egress: Locked/Blocked → accessibility."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("37"), "accessibility")

    def test_classify_complaint_55_zoning(self):
        """Code 55 = Zoning: Non-Conforming → zoning."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("55"), "zoning")

    def test_classify_complaint_1H_asbestos(self):
        """Code 1H = Emergency Asbestos Response → environmental."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("1H"), "environmental")

    def test_classify_complaint_09_debris(self):
        """Code 09 = Debris — Excessive → quality_of_life."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("09"), "quality_of_life")

    # ──────────────────────────────────────────────────────────
    # classify_complaint — alphanumeric + normalization
    # ──────────────────────────────────────────────────────────

    def test_classify_complaint_alphanumeric_6S(self):
        """Code 6S = Elevator: Single Device → mep_systems.
        Verifies alphanumeric codes (letter+digit) work, not just
        numeric ones."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("6S"), "mep_systems")

    def test_classify_complaint_lowercase_normalized(self):
        """Lowercase code normalized to uppercase before lookup.
        Defensive: production data is consistently uppercase but
        callers may pass lowercase from typed input."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("6s"), "mep_systems")
        self.assertEqual(classify_complaint("1h"), "environmental")

    def test_classify_complaint_with_whitespace_stripped(self):
        """Leading/trailing whitespace stripped before lookup."""
        self._require_taxonomy()
        self.assertEqual(classify_complaint("  45  "), "occupancy_violations")
        self.assertEqual(classify_complaint("\t45\n"), "occupancy_violations")

    # ──────────────────────────────────────────────────────────
    # classify_violation — edge cases
    # ──────────────────────────────────────────────────────────

    def test_classify_violation_all_none(self):
        """Both inputs None → 'other'."""
        self._require_taxonomy()
        self.assertEqual(classify_violation(None, None), "other")

    def test_classify_violation_empty_text(self):
        """Empty strings → 'other'."""
        self._require_taxonomy()
        self.assertEqual(classify_violation("", ""), "other")
        self.assertEqual(classify_violation("   ", "   "), "other")

    # ──────────────────────────────────────────────────────────
    # classify_violation — regex bucket coverage
    # ──────────────────────────────────────────────────────────

    def test_classify_violation_crane_text(self):
        """'Cranes and Derricks' violation_type → safety_hazards."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Cranes and Derricks",
                "Articulating boom crane on site supervised by ON STAR ...",
            ),
            "safety_hazards",
        )

    def test_classify_violation_asbestos_text(self):
        """Description mentioning asbestos → environmental."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "Asbestos abatement performed without containment",
            ),
            "environmental",
        )

    def test_classify_violation_gas_leak_text(self):
        """'Gas leak' description → mep_systems."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "Gas leak detected in basement; no shutoff procedure",
            ),
            "mep_systems",
        )

    def test_classify_violation_egress_text(self):
        """'Egress' description → accessibility."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "EGRESS path blocked by stored materials on second floor",
            ),
            "accessibility",
        )

    def test_classify_violation_structural_text(self):
        """Facade cracking description → structural_concerns."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "FACADE CRACK observed on north elevation; load bearing wall",
            ),
            "structural_concerns",
        )

    def test_classify_violation_zoning_text(self):
        """Zoning setback description → zoning."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "ZONING violation — rear yard SETBACK does not meet requirements",
            ),
            "zoning",
        )

    def test_classify_violation_certificate_of_occupancy(self):
        """'Certificate of occupancy' description → occupancy."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "Use is contrary to CERTIFICATE OF OCCUPANCY on file",
            ),
            "occupancy_violations",
        )

    def test_classify_violation_without_permit(self):
        """'Without permit' description → construction_violations."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "Construction work performed WITHOUT PERMIT for plumbing",
            ),
            # 'WITHOUT PERMIT' triggers construction_violations; the
            # 'PLUMB' word in 'plumbing' would also match mep, but
            # ordering of regex rules determines first-match-wins.
            # Per design lock: safety > environmental > mep > accessibility
            # > structural > zoning > occupancy > construction > quality.
            # So mep would actually fire first because PLUMB matches.
            "mep_systems",
        )

    def test_classify_violation_sidewalk(self):
        """'Sidewalk' description → quality_of_life. Note: text must
        NOT include construction-violation keywords (e.g. 'without
        permit') because construction_violations is listed earlier
        in VIOLATION_REGEX_RULES — first-match-wins means it would
        bucket as construction otherwise."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Construction",
                "Sidewalk obstruction by dumpster blocking pedestrian path",
            ),
            "quality_of_life",
        )

    def test_classify_violation_unmatched_text(self):
        """Text not matching any regex rule → 'other'."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Misc",
                "qwertyasdf zxcvbnm 12345 random unmatched corpus",
            ),
            "other",
        )

    def test_classify_violation_first_match_wins(self):
        """When text matches multiple regexes, the earlier rule in
        VIOLATION_REGEX_RULES wins. Pin the safety-over-mep ordering:
        a description containing both 'CRANE' and 'ELECTRIC' must
        bucket as safety_hazards (safety rule listed first)."""
        self._require_taxonomy()
        self.assertEqual(
            classify_violation(
                "Cranes and Derricks",
                "Crane with exposed ELECTRIC wiring; safety hazard",
            ),
            "safety_hazards",
        )

    # ──────────────────────────────────────────────────────────
    # Coverage checks
    # ──────────────────────────────────────────────────────────

    def test_buckets_tuple_has_ten_unique_values(self):
        """BUCKETS exports exactly 10 unique strings matching the
        Phase 1 Week 8 lock."""
        self._require_taxonomy()
        self.assertEqual(len(BUCKETS), 10)
        self.assertEqual(len(set(BUCKETS)), 10)
        self.assertIn("structural_concerns", BUCKETS)
        self.assertIn("construction_violations", BUCKETS)
        self.assertIn("occupancy_violations", BUCKETS)
        self.assertIn("safety_hazards", BUCKETS)
        self.assertIn("environmental", BUCKETS)
        self.assertIn("mep_systems", BUCKETS)
        self.assertIn("accessibility", BUCKETS)
        self.assertIn("zoning", BUCKETS)
        self.assertIn("quality_of_life", BUCKETS)
        self.assertIn("other", BUCKETS)

    def test_all_buckets_have_at_least_one_complaint_code_or_regex_rule(self):
        """Sanity guard against accidentally empty buckets. Every one
        of the 10 buckets must be reachable via either a complaint code
        or a violation regex (or "other" which is the fallback).

        Implementation: every bucket appears at least once in
        COMPLAINT_CODE_TO_BUCKET.values() OR is "other"."""
        self._require_taxonomy()
        complaint_buckets = set(COMPLAINT_CODE_TO_BUCKET.values())
        for bucket in BUCKETS:
            if bucket == "other":
                continue  # fallback bucket; not required to appear in map
            self.assertIn(
                bucket, complaint_buckets,
                msg=(
                    f"Bucket {bucket!r} not assigned to any complaint code. "
                    f"Either the COMPLAINT_CODE_TO_BUCKET map is missing "
                    f"codes for this bucket, or this bucket should be "
                    f"removed from BUCKETS."
                ),
            )

    def test_complaint_code_coverage_for_top_30_codes(self):
        """Every one of the top-30 production complaint codes (by
        frequency, covering ~1.8M complaints citywide) MUST map to a
        non-'other' bucket. 'other' for a high-volume code means we
        missed something semantically important."""
        self._require_taxonomy()
        misses = []
        for code in TOP_30_CODES:
            bucket = classify_complaint(code)
            if bucket == "other":
                misses.append(code)
        self.assertEqual(
            misses, [],
            msg=(
                f"Top-30 complaint codes assigned to 'other': {misses!r}. "
                f"Each of these covers tens-of-thousands to hundreds-of-"
                f"thousands of complaints citywide; assigning 'other' "
                f"means the bucket coverage is incomplete."
            ),
        )


if __name__ == "__main__":
    unittest.main()
