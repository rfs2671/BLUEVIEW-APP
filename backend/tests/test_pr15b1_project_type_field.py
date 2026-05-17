"""PR #15B.1 — B3 project-type field extraction tests.

3 tests in TestProjectTypeField:
  1. test_reads_dob_project_type_from_top_level
  2. test_falls_back_to_nested_peer_criteria_when_top_missing
  3. test_falls_back_to_new_building_when_both_missing

Stage 1 Probe C verified ALL 5 production projects have
`dob_project_type` at the top level (NOT `dob_type_classification`
as PR #15B incorrectly assumed).
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
    from lib.statistical_engine.live_mutation import (  # type: ignore
        _extract_project_type,
    )
    HAS_EXTRACTOR = True
except ImportError:
    _extract_project_type = None  # type: ignore
    HAS_EXTRACTOR = False


class TestProjectTypeField(unittest.TestCase):
    """B3 lock — extractor source priority:
      1. project['dob_project_type']                                 (top-level)
      2. project['peer_stats_cache']['peer_criteria']['dob_project_type']  (nested)
      3. 'New Building'                                              (default)
    """

    def _require(self):
        if not HAS_EXTRACTOR:
            self.fail(
                "Stage 3 PR #15B.1 (B3, Q3): implement "
                "lib.statistical_engine.live_mutation."
                "_extract_project_type(project: Dict[str, Any]) -> str\n"
                "Replaces inline `project.get('dob_type_classification')` "
                "at 2 call sites (refit_project_cold_start + "
                "predict_for_project_nightly). Source priority:\n"
                "  1. project.get('dob_project_type')\n"
                "  2. peer_stats_cache.peer_criteria.dob_project_type\n"
                "  3. 'New Building' (default)\n"
                "All 5 production projects (Stage 1 Probe C) carry "
                "dob_project_type at top-level — extractor must NOT "
                "read the wrong key 'dob_type_classification'."
            )

    def test_reads_dob_project_type_from_top_level(self):
        """Stage 1 receipt: all 5 production projects have
        dob_project_type at top-level."""
        self._require()
        project = {"dob_project_type": "major_alt_with_enlargement"}
        result = _extract_project_type(project)
        self.assertEqual(
            result, "major_alt_with_enlargement",
            msg=f"B3: top-level dob_project_type must be read. "
                f"Got {result!r}",
        )

    def test_falls_back_to_nested_peer_criteria_when_top_missing(self):
        """Defensive: also accept nested location (PR #14E writes it
        there too)."""
        self._require()
        project = {
            "peer_stats_cache": {
                "peer_criteria": {"dob_project_type": "full_demo"}
            }
        }
        result = _extract_project_type(project)
        self.assertEqual(
            result, "full_demo",
            msg=f"B3: nested peer_criteria.dob_project_type must be "
                f"the fallback. Got {result!r}",
        )

    def test_falls_back_to_new_building_when_both_missing(self):
        """Last-resort default keeps the anchored label sane even
        when both sources are absent."""
        self._require()
        self.assertEqual(
            _extract_project_type({}), "New Building",
            msg="B3: empty dict → 'New Building' default",
        )
        self.assertEqual(
            _extract_project_type({"peer_stats_cache": {"peer_criteria": {}}}),
            "New Building",
            msg="B3: nested-but-missing → 'New Building' default",
        )


if __name__ == "__main__":
    unittest.main()
