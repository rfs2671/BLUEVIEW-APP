"""PR #15B.1 — B6 borough derivation helper tests.

4 tests in TestBoroughDerivation:
  1. test_derive_from_pluto_snapshot_BK_normalized_to_BROOKLYN
  2. test_derive_falls_back_to_bbl_prefix_when_pluto_missing
  3. test_bbl_prefix_handles_all_5_borough_codes
  4. test_derive_returns_none_when_both_sources_absent

CRITICAL: Stage 1 Probe C confirmed `project.borough` is NULL on ALL
5 production projects. This bug (B6) means PR #15B defaulted every
project to BROOKLYN, including the 2 Bronx projects (bronx, bailey).
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
    from lib.statistical_engine.live_mutation import derive_borough  # type: ignore
    HAS_DERIVE = True
except ImportError:
    derive_borough = None  # type: ignore
    HAS_DERIVE = False

try:
    from lib.statistical_engine.baselines import bbl_to_borough  # type: ignore
    HAS_BBL = True
except ImportError:
    bbl_to_borough = None  # type: ignore
    HAS_BBL = False


class TestBoroughDerivation(unittest.TestCase):
    """B6 lock — borough source priority chain:
      1. project["borough"]                    (top-level, usually None)
      2. project["pluto_snapshot"]["borough"]  ("BK"→"BROOKLYN" via PR #14I)
      3. project["bbl"][0]                     (deterministic prefix lookup)
    Returns full-uppercase borough name OR None."""

    def _require_derive(self):
        if not HAS_DERIVE:
            self.fail(
                "Stage 3 PR #15B.1 (B6): implement "
                "lib.statistical_engine.live_mutation."
                "derive_borough(project: Dict[str, Any]) -> Optional[str]\n"
                "Source priority:\n"
                "  1. project.get('borough')\n"
                "  2. _normalize_borough_to_full_name(\n"
                "       (project.get('pluto_snapshot') or {})"
                ".get('borough'))\n"
                "  3. bbl_to_borough(project.get('bbl') or project.get("
                "'nyc_bbl'))\n"
                "Returns None if none resolve. Caller decides default."
            )

    def _require_bbl(self):
        if not HAS_BBL:
            self.fail(
                "Stage 3 PR #15B.1 (B6): implement "
                "lib.statistical_engine.baselines.bbl_to_borough"
                "(bbl: Optional[str]) -> Optional[str]\n"
                "Returns full-uppercase borough from BBL[0] prefix:\n"
                "  '1' -> 'MANHATTAN', '2' -> 'BRONX', '3' -> 'BROOKLYN',\n"
                "  '4' -> 'QUEENS',    '5' -> 'STATEN ISLAND'\n"
                "Returns None for missing/malformed input."
            )

    # ── Test 1 — pluto BK → BROOKLYN ─────────────────────────

    def test_derive_from_pluto_snapshot_BK_normalized_to_BROOKLYN(self):
        """PR #14I _normalize_borough_to_full_name handles 'BK'→
        'BROOKLYN'. derive_borough must invoke it on pluto_snapshot."""
        self._require_derive()
        project = {"pluto_snapshot": {"borough": "BK"}}
        result = derive_borough(project)
        self.assertEqual(
            result, "BROOKLYN",
            msg=f"B6: pluto_snapshot.borough='BK' must derive "
                f"'BROOKLYN' via PR #14I helper. Got {result!r}",
        )
        # And BX → BRONX
        project_bx = {"pluto_snapshot": {"borough": "BX"}}
        self.assertEqual(
            derive_borough(project_bx), "BRONX",
            msg="B6: pluto BX must derive BRONX.",
        )

    # ── Test 2 — bbl fallback ────────────────────────────────

    def test_derive_falls_back_to_bbl_prefix_when_pluto_missing(self):
        """When pluto_snapshot is absent or pluto.borough is None,
        derive_borough must fall back to bbl[0] prefix lookup."""
        self._require_derive()
        project_bronx = {"bbl": "2029580210"}  # Real Bronx project
        self.assertEqual(
            derive_borough(project_bronx), "BRONX",
            msg="B6 fallback: bbl='2...' must derive BRONX",
        )
        project_brk = {"nyc_bbl": "3033040024"}  # Menahan-shape BBL
        self.assertEqual(
            derive_borough(project_brk), "BROOKLYN",
            msg="B6 fallback: nyc_bbl prefix '3' must derive BROOKLYN",
        )

    # ── Test 3 — all 5 borough codes ─────────────────────────

    def test_bbl_prefix_handles_all_5_borough_codes(self):
        """Stage 1 receipts: bbl prefix → borough mapping verified."""
        self._require_bbl()
        cases = [
            ("1000000000", "MANHATTAN"),
            ("2000000000", "BRONX"),
            ("3000000000", "BROOKLYN"),
            ("4000000000", "QUEENS"),
            ("5000000000", "STATEN ISLAND"),
        ]
        for bbl, expected in cases:
            self.assertEqual(
                bbl_to_borough(bbl), expected,
                msg=f"B6: bbl_to_borough({bbl!r}) expected {expected!r}",
            )
        # Defensive: unknown / malformed
        self.assertIsNone(bbl_to_borough(None))
        self.assertIsNone(bbl_to_borough(""))
        self.assertIsNone(
            bbl_to_borough("9999999999"),
            msg="B6: bbl prefix '9' unknown; must return None",
        )

    # ── Test 4 — none source available ───────────────────────

    def test_derive_returns_none_when_both_sources_absent(self):
        """Defensive: caller decides the default when nothing
        derivable. (predict_for_project_nightly currently defaults
        to 'BROOKLYN' on None, per Stage 3 design.)"""
        self._require_derive()
        self.assertIsNone(
            derive_borough({}),
            msg="B6: empty dict → None (caller decides default)",
        )
        self.assertIsNone(
            derive_borough({"pluto_snapshot": None, "bbl": None}),
            msg="B6: explicit None values → None",
        )


if __name__ == "__main__":
    unittest.main()
