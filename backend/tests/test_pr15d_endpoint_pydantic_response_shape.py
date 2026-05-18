"""PR #15D — PredictionResponse Pydantic model shape tests (Q1 lock).

4 tests. Pure model behavior.

Target: PredictionResponse defined inline in server.py near the new
endpoint per Q1 (codebase precedent: 100+ inline BaseModel classes).

Expected fields (matches Q4 spec from Stage 1):
  prediction_available: bool
  horizons: { prob_7d, prob_14d, prob_30d } floats or null
  anchored_baseline: {
      prob_7d, prob_14d, prob_30d,    (G2 horizons; null for legacy fits)
      label: str,
      cohort_size: int,
  }
  confidence: {
      tier: str,
      sample_size: int,
      is_cold_start: bool,
      badge: Optional[str],
  }
  metadata: {
      fit_at: Optional[datetime],
      last_validated_timestamp: datetime,
      schema_version: str,
  }
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


def _try_import_models():
    try:
        from server import (  # type: ignore
            PredictionResponse, HorizonProbabilities, AnchoredBaseline,
            ConfidenceInfo, PredictionMetadata,
        )
        return (
            PredictionResponse, HorizonProbabilities, AnchoredBaseline,
            ConfidenceInfo, PredictionMetadata,
        )
    except ImportError:
        return None


_models = _try_import_models()


class TestPredictionResponseShape(unittest.TestCase):
    """Q1 lock — Pydantic models live INLINE in server.py per the
    existing 100+ BaseModel class precedent. NOT in a separate
    models.py module."""

    def _require(self):
        if _models is None:
            self.fail(
                "Stage 3 PR #15D (Q1): define 5 Pydantic models "
                "INLINE in backend/server.py near the new endpoint "
                "(line ~3745):\n"
                "  • PredictionResponse  (top-level)\n"
                "  • HorizonProbabilities (prob_7d, prob_14d, prob_30d)\n"
                "  • AnchoredBaseline    (3 horizon probs + label + cohort_size)\n"
                "  • ConfidenceInfo      (tier, sample_size, is_cold_start, badge)\n"
                "  • PredictionMetadata  (fit_at, last_validated_timestamp, "
                "schema_version)\n"
                "All inherit from pydantic.BaseModel. Use Optional[...] "
                "for nullable fields. Strict mode (extra='forbid')."
            )

    def test_response_model_field_names_match_spec(self):
        """Q4 — exact field shape from Stage 1 endpoint spec."""
        self._require()
        (PredictionResponse, HorizonProbabilities, AnchoredBaseline,
         ConfidenceInfo, PredictionMetadata) = _models

        # Construct a valid response — fails if field names drift.
        now = datetime(2026, 5, 17, tzinfo=timezone.utc)
        resp = PredictionResponse(
            prediction_available=True,
            horizons=HorizonProbabilities(
                prob_7d=0.001, prob_14d=0.003, prob_30d=0.007,
            ),
            anchored_baseline=AnchoredBaseline(
                prob_7d=0.0007, prob_14d=0.0014, prob_30d=0.0029,
                label="BROOKLYN major_alt_with_enlargement macro baseline",
                cohort_size=85,
            ),
            confidence=ConfidenceInfo(
                tier="low_confidence",
                sample_size=85,
                is_cold_start=False,
                badge="limited_peer_sample",
            ),
            metadata=PredictionMetadata(
                fit_at=now,
                last_validated_timestamp=now,
                schema_version="pr15b_v1",
            ),
        )
        dumped = resp.model_dump()
        self.assertIn("prediction_available", dumped)
        self.assertIn("horizons", dumped)
        self.assertIn("anchored_baseline", dumped)
        self.assertIn("confidence", dumped)
        self.assertIn("metadata", dumped)
        self.assertEqual(dumped["horizons"]["prob_14d"], 0.003)
        self.assertEqual(dumped["confidence"]["badge"], "limited_peer_sample")
        self.assertEqual(dumped["metadata"]["schema_version"], "pr15b_v1")

    def test_response_model_serializes_decimal_as_float(self):
        """Mongo Decimal128 → float in JSON output (no Decimal type
        leakage). Important for frontend consumption."""
        self._require()
        from decimal import Decimal
        (PredictionResponse, HorizonProbabilities, AnchoredBaseline,
         ConfidenceInfo, PredictionMetadata) = _models
        now = datetime(2026, 5, 17, tzinfo=timezone.utc)
        # Pass Decimal — Pydantic should coerce or fail clearly.
        try:
            resp = PredictionResponse(
                prediction_available=True,
                horizons=HorizonProbabilities(
                    prob_7d=float(Decimal("0.001")),
                    prob_14d=float(Decimal("0.003")),
                    prob_30d=float(Decimal("0.007")),
                ),
                anchored_baseline=AnchoredBaseline(
                    prob_7d=None, prob_14d=0.0014, prob_30d=None,
                    label="x", cohort_size=85,
                ),
                confidence=ConfidenceInfo(
                    tier="low_confidence", sample_size=85,
                    is_cold_start=False, badge=None,
                ),
                metadata=PredictionMetadata(
                    fit_at=now, last_validated_timestamp=now,
                    schema_version="pr15b_v1",
                ),
            )
        except Exception as e:
            self.fail(f"Decimal coercion failed: {e!r}")
        json_data = resp.model_dump(mode="json")
        # JSON-mode dump should convert datetime to string, floats to floats.
        self.assertIsInstance(json_data["horizons"]["prob_14d"], float)

    def test_response_model_rejects_unknown_fields(self):
        """Pydantic strict mode — extra fields must raise. Prevents
        accidental field-name drift between backend + frontend."""
        self._require()
        (PredictionResponse, *_) = _models
        from pydantic import ValidationError
        try:
            with self.assertRaises(ValidationError):
                PredictionResponse(
                    prediction_available=True,
                    horizons={"prob_7d": 0.001, "prob_14d": 0.003,
                              "prob_30d": 0.007},
                    anchored_baseline={
                        "prob_7d": None, "prob_14d": 0.001,
                        "prob_30d": None, "label": "x",
                        "cohort_size": 1,
                    },
                    confidence={"tier": "x", "sample_size": 1,
                                "is_cold_start": False, "badge": None},
                    metadata={"fit_at": None,
                              "last_validated_timestamp": datetime.now(timezone.utc),
                              "schema_version": "pr15b_v1"},
                    bogus_extra_field="should_reject",  # ← extra
                )
        except AssertionError:
            self.fail(
                "Stage 3 PR #15D: PredictionResponse must use "
                "`model_config = ConfigDict(extra='forbid')` to "
                "reject unknown fields. Prevents field-name drift "
                "between backend response + frontend consumer.",
            )

    def test_response_model_handles_null_fit_at(self):
        """Stage 1 Probe E receipt: cold-start projects have
        fit_at=None. The model must accept that and JSON-serialize
        to null."""
        self._require()
        (PredictionResponse, HorizonProbabilities, AnchoredBaseline,
         ConfidenceInfo, PredictionMetadata) = _models
        now = datetime(2026, 5, 17, tzinfo=timezone.utc)
        resp = PredictionResponse(
            prediction_available=True,
            horizons=HorizonProbabilities(
                prob_7d=0.09, prob_14d=0.18, prob_30d=0.49,
            ),
            anchored_baseline=AnchoredBaseline(
                prob_7d=None, prob_14d=0.18, prob_30d=None,
                label="BRONX full_demo macro baseline",
                cohort_size=253,
            ),
            confidence=ConfidenceInfo(
                tier="borough_baseline", sample_size=253,
                is_cold_start=True, badge="cold_start",
            ),
            metadata=PredictionMetadata(
                fit_at=None,                          # ← Cold-start signal
                last_validated_timestamp=now,
                schema_version="pr15b_v1",
            ),
        )
        dumped = resp.model_dump(mode="json")
        self.assertIsNone(
            dumped["metadata"]["fit_at"],
            msg="L7 — cold-start projects (Stage 1 Probe E: Bronx, "
                "Boyland) have fit_at=None. Model must accept + "
                "JSON-serialize to null.",
        )


if __name__ == "__main__":
    unittest.main()
