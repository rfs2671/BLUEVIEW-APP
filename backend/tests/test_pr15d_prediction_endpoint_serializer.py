"""PR #15D — prediction_cache → PredictionResponse serializer tests.

10 tests. Uses the 5 saved Stage 1 fixtures (Menahan, Bronx, Bailey,
Lafayette, Boyland).

Target:
  server.serialize_prediction_cache_to_response(project: dict)
      -> PredictionResponse

Tests verify:
  • 5 fixtures round-trip correctly (Menahan, Bailey, Lafayette, Bronx, Boyland)
  • confidence.badge computed via compute_confidence_badge per fixture's flags
  • metadata.last_validated_timestamp populated even when fit_at=None (L7)
  • Missing prediction_cache → prediction_available=False
  • Legacy fits (without G2 baselines) → null prob_7d/30d in anchored_baseline
  • New fits (with G2 baselines) → all 3 baseline horizons populated
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))


from _pr15d_prediction_cache_loader import (  # noqa: E402
    load_prediction_cache_fixture,
)


def _try_import_serializer():
    try:
        from server import serialize_prediction_cache_to_response  # type: ignore
        return serialize_prediction_cache_to_response
    except ImportError:
        return None


_serialize = _try_import_serializer()


class TestPredictionEndpointSerializer(unittest.TestCase):
    """Pr15D — serializer converts project doc with prediction_cache
    sub-document to the PredictionResponse Pydantic model."""

    def _require(self):
        if _serialize is None:
            self.fail(
                "Stage 3 PR #15D: implement "
                "server.serialize_prediction_cache_to_response("
                "project: dict) -> PredictionResponse\n"
                "Reads project['prediction_cache']; constructs the "
                "PredictionResponse Pydantic model. Handles:\n"
                "  • Missing prediction_cache → prediction_available=False\n"
                "  • fit_at=None (cold-start) → preserve null in response\n"
                "  • Legacy fits (no G2 baselines) → null prob_7d/30d "
                "in anchored_baseline\n"
                "  • Calls compute_confidence_badge for confidence.badge\n"
                "B-SERIALIZE lock: badge computed here, NOT persisted "
                "in prediction_cache."
            )

    # ── Fixture-driven round-trip tests ─────────────────────

    def test_menahan_serializes_full_response(self):
        """Menahan fixture (n=85, modern fit, low_confidence tier)."""
        self._require()
        project = load_prediction_cache_fixture("menahan")
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertTrue(dumped["prediction_available"])
        cache = project["prediction_cache"]
        self.assertAlmostEqual(
            dumped["horizons"]["prob_7d"],
            cache["prob_violation_7d"],
            delta=1e-9,
        )
        self.assertEqual(
            dumped["anchored_baseline"]["label"],
            cache["anchored_baseline_label"],
        )
        self.assertEqual(
            dumped["confidence"]["sample_size"], 85,
        )
        # n=85 < 100 → low_confidence_flag should be True →
        # badge = "limited_peer_sample" (not cold_start since
        # Menahan is modern fit).
        self.assertEqual(
            dumped["confidence"]["badge"], "limited_peer_sample",
            msg=f"Menahan (n=85, low_conf=True, is_cold_start=False) "
                f"should yield badge='limited_peer_sample'. Got "
                f"{dumped['confidence']['badge']!r}",
        )

    def test_bailey_high_confidence_no_badge(self):
        """Bailey (n=141, high_confidence) → null badge."""
        self._require()
        project = load_prediction_cache_fixture("bailey")
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertEqual(
            dumped["confidence"]["tier"], "high_confidence",
            msg=f"Bailey cohort_tier_utilized expected "
                f"'high_confidence'. Got "
                f"{dumped['confidence']['tier']!r}",
        )
        self.assertIsNone(
            dumped["confidence"]["badge"],
            msg=f"Bailey is high_confidence + not cold-start → "
                f"badge should be None. Got "
                f"{dumped['confidence']['badge']!r}",
        )

    def test_lafayette_low_confidence_with_badge(self):
        """Lafayette (n=51) — between 30 and 100 → limited_peer_sample."""
        self._require()
        project = load_prediction_cache_fixture("lafayette")
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertEqual(
            dumped["confidence"]["badge"], "limited_peer_sample",
        )

    def test_bronx_cold_start_with_badge(self):
        """Bronx — is_cold_start=True (panel build failed despite
        n=253). Badge takes precedence."""
        self._require()
        project = load_prediction_cache_fixture("bronx")
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertTrue(dumped["confidence"]["is_cold_start"])
        self.assertEqual(
            dumped["confidence"]["badge"], "cold_start",
            msg=f"Bronx is_cold_start=True → badge='cold_start'. Got "
                f"{dumped['confidence']['badge']!r}",
        )
        # Horizons still populated from borough actuarial path
        self.assertGreater(
            dumped["horizons"]["prob_7d"], 0,
            msg="Cold-start Bronx still has non-zero horizons via "
                "borough actuarial baseline.",
        )

    def test_boyland_cold_start_sample_size_zero(self):
        """Boyland (n=0, is_cold_start=True)."""
        self._require()
        project = load_prediction_cache_fixture("boyland")
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertEqual(dumped["confidence"]["sample_size"], 0)
        self.assertEqual(dumped["confidence"]["badge"], "cold_start")
        self.assertTrue(dumped["confidence"]["is_cold_start"])

    # ── Schema version + metadata ───────────────────────────

    def test_response_includes_schema_version(self):
        """All fixtures: metadata.schema_version = 'pr15b_v1'."""
        self._require()
        for name in ("menahan", "bailey", "lafayette", "bronx", "boyland"):
            project = load_prediction_cache_fixture(name)
            resp = _serialize(project)
            self.assertEqual(
                resp.model_dump()["metadata"]["schema_version"],
                "pr15b_v1",
                msg=f"{name}: metadata.schema_version != 'pr15b_v1'",
            )

    def test_metadata_falls_back_to_last_validated_when_fit_at_null(self):
        """L7 lock — staleness anchored on last_validated_timestamp,
        which is always populated (even when fit_at is None for
        cold-start). Bronx + Boyland fixtures have fit_at=None."""
        self._require()
        for name in ("bronx", "boyland"):
            project = load_prediction_cache_fixture(name)
            resp = _serialize(project)
            dumped = resp.model_dump(mode="json")
            self.assertIsNone(
                dumped["metadata"]["fit_at"],
                msg=f"{name}: cold-start fit_at must be None in "
                    f"response (matches fixture).",
            )
            self.assertIsNotNone(
                dumped["metadata"]["last_validated_timestamp"],
                msg=f"{name}: last_validated_timestamp must be "
                    f"populated even for cold-start projects (L7).",
            )

    # ── Defensive cases ────────────────────────────────────

    def test_handles_missing_prediction_cache_entirely(self):
        """Project doc without prediction_cache field at all (newly
        onboarded project before first nightly fit)."""
        self._require()
        bare_project = {
            "_id": "newproject", "name": "Bare Project",
            "borough": "BROOKLYN", "dob_project_type": "new_building",
        }
        resp = _serialize(bare_project)
        dumped = resp.model_dump()
        self.assertFalse(
            dumped["prediction_available"],
            msg="No prediction_cache → prediction_available must be False",
        )
        # Horizons + anchored_baseline + confidence should be safe defaults
        # (null/empty) — caller's choice. We just verify no crash.

    def test_handles_legacy_cache_without_g2_baselines(self):
        """Existing fixtures lack G2 fields (added at Stage 3).
        Serializer must degrade gracefully: 14d baseline populated,
        7d + 30d baselines null."""
        self._require()
        project = load_prediction_cache_fixture("menahan")
        cache = project["prediction_cache"]
        # Strip G2 fields if present (Stage 1 fixtures pre-date G2 write)
        cache.pop("anchored_baseline_prob_7d", None)
        cache.pop("anchored_baseline_prob_30d", None)
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertIsNotNone(
            dumped["anchored_baseline"]["prob_14d"],
            msg="14d baseline must be present (always existed).",
        )
        self.assertIsNone(
            dumped["anchored_baseline"]["prob_7d"],
            msg="G2 7d baseline absent in legacy fit → None in response",
        )
        self.assertIsNone(
            dumped["anchored_baseline"]["prob_30d"],
            msg="G2 30d baseline absent in legacy fit → None in response",
        )

    def test_handles_cache_with_g2_baselines(self):
        """After Stage 3 G2 writes, fits include 7d + 30d baselines.
        Serializer surfaces all 3 horizons."""
        self._require()
        project = load_prediction_cache_fixture("menahan")
        # Simulate G2 fields present (post-Stage-3 write)
        project["prediction_cache"]["anchored_baseline_prob_7d"] = 0.00065
        project["prediction_cache"]["anchored_baseline_prob_30d"] = 0.00298
        resp = _serialize(project)
        dumped = resp.model_dump()
        self.assertAlmostEqual(
            dumped["anchored_baseline"]["prob_7d"], 0.00065, delta=1e-9,
        )
        self.assertAlmostEqual(
            dumped["anchored_baseline"]["prob_30d"], 0.00298, delta=1e-9,
        )


if __name__ == "__main__":
    unittest.main()
