"""Phase V2.3 — tests for the surviving utility functions.

These tests were originally in ``test_v2_2_ingestion.py`` (the
file deleted by Commit 1). Migrated verbatim except for:

  • Import target: ``lib.statistical_engine.utils`` instead of
    ``lib.statistical_engine.ingestion``.
  • Function name: ``normalize_bbl`` instead of
    ``_normalize_bbl_for_storage`` (renamed in the migration).

V2.3 Commit 3: the transitional ``TestTransitionalCollectionConstants``
class was removed alongside the 9 NYC_* / STATISTICAL_BASELINES
/ INGESTION_STATE constants it pinned. Those constants no
longer exist on utils.py — the lazy-query rewrite in Commit 3
removed every consumer of them.
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

from lib.statistical_engine import utils as se_utils  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# _construct_bbl_from_components
# ──────────────────────────────────────────────────────────────────


class TestConstructBblFromComponents(unittest.TestCase):
    """V2.2.4 → V2.3: function migrated verbatim from
    lib/statistical_engine/ingestion.py to lib/statistical_engine/
    utils.py. Same 9 test cases as V2.2.4."""

    def test_under_padded_normal_case(self):
        rec = se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "38"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_socrata_row_2_actual_padding(self):
        # Verbatim shape from Socrata 3h2n-5cm9 row 2 (curl
        # probe 2026-05-10). Both block and lot zero-padded to
        # 5 chars; lot's 5th char is the over-pad we strip.
        rec = se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "00847", "lot": "00038"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_further_over_padded(self):
        rec = se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "000847", "lot": "000038"},
        )
        self.assertEqual(rec, "1008470038")
        self.assertEqual(len(rec), 10)

    def test_all_zeros_returns_none(self):
        rec = se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "0", "lot": "00"},
        )
        self.assertIsNone(rec)

    def test_invalid_boro_returns_none(self):
        rec = se_utils._construct_bbl_from_components(
            {"boro": "6", "block": "847", "lot": "38"},
        )
        self.assertIsNone(rec)

    def test_non_numeric_components_return_none(self):
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "MANHATTAN", "block": "847", "lot": "38"},
        ))
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "ABC", "lot": "38"},
        ))
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "X"},
        ))

    def test_missing_component_returns_none(self):
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "847"},  # no lot
        ))
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"block": "847", "lot": "38"},  # no boro
        ))
        self.assertIsNone(se_utils._construct_bbl_from_components({}))

    def test_block_too_large_returns_none(self):
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "100000", "lot": "38"},
        ))

    def test_lot_too_large_returns_none(self):
        self.assertIsNone(se_utils._construct_bbl_from_components(
            {"boro": "1", "block": "847", "lot": "10000"},
        ))


# ──────────────────────────────────────────────────────────────────
# normalize_bbl (was _normalize_bbl_for_storage in V2.2.4)
# ──────────────────────────────────────────────────────────────────


class TestNormalizeBbl(unittest.TestCase):

    def test_strips_pluto_decimal_suffix(self):
        self.assertEqual(
            se_utils.normalize_bbl("4061730023.00000000"),
            "4061730023",
        )

    def test_clean_value_passes_through(self):
        self.assertEqual(
            se_utils.normalize_bbl("4061730023"),
            "4061730023",
        )

    def test_none_passes_through(self):
        self.assertIsNone(se_utils.normalize_bbl(None))

    def test_empty_string_passes_through(self):
        # Falsy input → pass-through (returns the input as-is).
        self.assertEqual(se_utils.normalize_bbl(""), "")

    def test_real_decimal_not_stripped(self):
        # Non-zero tail must NOT be stripped — that would corrupt
        # legitimate decimal values from non-PLUTO sources.
        self.assertEqual(se_utils.normalize_bbl("3.5"), "3.5")

    def test_partial_zero_tail_not_stripped(self):
        # Mixed-zero tail (e.g. "100.50000") is NOT all-zero
        # after the decimal point, so it stays untouched.
        self.assertEqual(se_utils.normalize_bbl("100.50000"), "100.50000")

    def test_non_digit_head_not_stripped(self):
        # If the part before the dot isn't pure digits, this isn't
        # a Socrata-padded numeric — leave it alone.
        self.assertEqual(se_utils.normalize_bbl("ABC.000"), "ABC.000")


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 3: removed surfaces
# ──────────────────────────────────────────────────────────────────


class TestRemovedTransitionalConstants(unittest.TestCase):
    """V2.3 Commit 3 deleted the 9 NYC_* /
    STATISTICAL_BASELINES / INGESTION_STATE collection-name
    constants from utils.py once all consumers were rewritten
    to lazy SocrataClient queries. Pin the removal so a stray
    re-introduction surfaces immediately."""

    def test_constants_removed(self):
        for name in (
            "NYC_VIOLATIONS_COLLECTION",
            "NYC_INSPECTIONS_COLLECTION",
            "NYC_PERMITS_COLLECTION",
            "NYC_COMPLAINTS_311_COLLECTION",
            "NYC_ECB_VIOLATIONS_COLLECTION",
            "NYC_HPD_VIOLATIONS_COLLECTION",
            "NYC_PLUTO_COLLECTION",
            "STATISTICAL_BASELINES_COLLECTION",
            "INGESTION_STATE_COLLECTION",
        ):
            self.assertFalse(
                hasattr(se_utils, name),
                f"utils.py still exposes {name}; should have been removed",
            )


if __name__ == "__main__":
    unittest.main()
