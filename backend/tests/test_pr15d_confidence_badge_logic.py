"""PR #15D — confidence.badge computation tests (L8 + Q3 locks).

6 tests. Pure helper, no I/O.

Target:
  lib.statistical_engine.live_mutation.compute_confidence_badge(
      prediction_cache: dict,
  ) -> Optional[str]

L8 lock: returns one of {None, "limited_peer_sample", "cold_start"}.
Q3 lock: missing flags default to False (conservative — no badge
surfaced unless an explicit signal True is present).

Precedence:
  is_cold_start=True              → "cold_start" (regardless of other flags)
  is_cold_start=False, low_conf=T → "limited_peer_sample"
  is_cold_start=False, low_conf=F → None
  missing flags                   → None (per Q3)
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
        compute_confidence_badge,
    )
    HAS_HELPER = True
except ImportError:
    compute_confidence_badge = None  # type: ignore
    HAS_HELPER = False


class TestConfidenceBadgeLogic(unittest.TestCase):
    """L8 + Q3 — confidence.badge computation. Reads flags from a
    prediction_cache dict and returns the badge string per UX spec.
    B-SERIALIZE lock: computed at API serialization time, NOT
    persisted in prediction_cache."""

    def _require(self):
        if not HAS_HELPER:
            self.fail(
                "Stage 3 PR #15D (L8, Q3, B-SERIALIZE): implement "
                "lib.statistical_engine.live_mutation."
                "compute_confidence_badge("
                "prediction_cache: dict) -> Optional[str]\n"
                "L8 returns one of {None, 'limited_peer_sample', "
                "'cold_start'}.\n"
                "Precedence:\n"
                "  1. is_cold_start=True → 'cold_start'\n"
                "  2. is_cold_start=False, low_confidence_flag=True "
                "→ 'limited_peer_sample'\n"
                "  3. else → None\n"
                "Q3: missing flags default to False (no badge unless "
                "explicit True signal)."
            )

    def test_badge_cold_start_takes_precedence(self):
        """L8 — cold_start always wins regardless of low_conf flag."""
        self._require()
        self.assertEqual(
            compute_confidence_badge({
                "is_cold_start": True, "low_confidence_flag": True,
            }),
            "cold_start",
            msg="cold_start + low_conf=True must return 'cold_start'",
        )
        self.assertEqual(
            compute_confidence_badge({
                "is_cold_start": True, "low_confidence_flag": False,
            }),
            "cold_start",
            msg="cold_start + low_conf=False must return 'cold_start'",
        )

    def test_badge_limited_peer_sample(self):
        """L8 — non-cold-start with low_confidence_flag=True."""
        self._require()
        self.assertEqual(
            compute_confidence_badge({
                "is_cold_start": False, "low_confidence_flag": True,
            }),
            "limited_peer_sample",
        )

    def test_badge_null_for_high_confidence(self):
        """L8 — both flags False → no badge."""
        self._require()
        self.assertIsNone(
            compute_confidence_badge({
                "is_cold_start": False, "low_confidence_flag": False,
            }),
        )

    def test_badge_defaults_to_null_when_flags_missing(self):
        """Q3 — missing flags default to False → None badge.
        Conservative: no badge surfaced without explicit signal."""
        self._require()
        self.assertIsNone(
            compute_confidence_badge({}),
            msg="Q3: empty dict → None (no badge unless explicit flag)",
        )
        self.assertIsNone(
            compute_confidence_badge({"is_cold_start": None}),
            msg="Q3: None is_cold_start treated as False",
        )
        self.assertIsNone(
            compute_confidence_badge({"low_confidence_flag": None}),
            msg="Q3: None low_confidence_flag treated as False",
        )

    def test_badge_handles_partial_cache_dict(self):
        """Q3 — only one flag set: cold_start=True wins; low_conf
        alone surfaces limited_peer_sample; neither → None."""
        self._require()
        self.assertEqual(
            compute_confidence_badge({"is_cold_start": True}),
            "cold_start",
            msg="Partial cache with only is_cold_start=True → "
                "'cold_start' (low_conf missing → default False)",
        )
        self.assertIsNone(
            compute_confidence_badge({"is_cold_start": False}),
            msg="is_cold_start=False alone, low_conf missing → None",
        )
        self.assertEqual(
            compute_confidence_badge({"low_confidence_flag": True}),
            "limited_peer_sample",
            msg="low_confidence_flag=True alone (is_cold_start "
                "missing → False) → 'limited_peer_sample'",
        )

    def test_badge_returns_canonical_string_values_only(self):
        """L8 — only 3 valid return values. Asserts the helper
        doesn't leak unexpected strings."""
        self._require()
        valid_returns = {None, "cold_start", "limited_peer_sample"}
        for flags in [
            {},
            {"is_cold_start": True},
            {"is_cold_start": False},
            {"low_confidence_flag": True},
            {"low_confidence_flag": False},
            {"is_cold_start": True, "low_confidence_flag": True},
            {"is_cold_start": True, "low_confidence_flag": False},
            {"is_cold_start": False, "low_confidence_flag": True},
            {"is_cold_start": False, "low_confidence_flag": False},
        ]:
            result = compute_confidence_badge(flags)
            self.assertIn(
                result, valid_returns,
                msg=f"L8: compute_confidence_badge({flags!r}) = "
                    f"{result!r}; must be in {valid_returns}",
            )


if __name__ == "__main__":
    unittest.main()
