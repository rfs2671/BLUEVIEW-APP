"""Phase V2.3 Commit 6 — Predictive inspection surfacing tests.

Coverage of the 16 spec contract points + display-format unit
tests + resolution sweep edge cases:

   1. happy path → returns prediction dict (confidence ≥0.70)
   2. confidence <0.70 → returns None
   3. sample size <10 → returns None
   4. inspection rate <0.50 → returns None
   5. no historical complaints → returns None
   6. display message format "Inspection likely tomorrow between 3-5 PM"
   7. confidence calc bounds (min / max / saturation)
   8. try_predict_inspection_from_complaint success path inserts row
   9. try_ wrapper below-threshold path no insert
  10. try_ wrapper on exception does not propagate
  11. sweep: active prediction with matching DOB inspection → hit
  12. sweep: expired without inspection → miss
  13. sweep: still-active not yet expired → still_active (no mutation)
  14. opportunistic_resolution_check scoped to one project
  15. cleanup: resolved >30 days deleted; <30 days preserved
  16. Hook-predicate suppression cases (existing not None,
      is_seed_transition, severity != Action) covered by the
      hook tests in test_v2_2_schema_scaffolding.py grep tests
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from lib.statistical_engine import predictions as pred  # noqa: E402
from lib.statistical_engine.predictions import (  # noqa: E402
    PREDICTION_CONFIDENCE_SATURATION_SAMPLES,
    PREDICTION_CONFIDENCE_THRESHOLD,
    PREDICTION_HOUR_WINDOW_SPAN,
    PREDICTION_INSPECTION_WINDOW_DAYS,
    PREDICTION_METHOD,
    PREDICTION_MIN_INSPECTION_RATE,
    PREDICTION_MIN_SAMPLE_SIZE,
    RESOLVED_PREDICTION_RETENTION_DAYS,
    _compute_confidence,
    _format_display_message,
    cleanup_resolved_predictions,
    opportunistic_resolution_check,
    predict_inspection_from_complaint,
    sweep_prediction_resolutions,
    try_predict_inspection_from_complaint,
)
from lib.statistical_engine.schema import PREDICTED_EVENTS_COLLECTION  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    SocrataQueryError,
)

from _socrata_mock import MockSocrataClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Stub Mongo collections
# ──────────────────────────────────────────────────────────────────


class _StubPredColl:
    def __init__(self, docs: List[Dict[str, Any]] = None) -> None:
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.insert_one_calls: List[Dict[str, Any]] = []
        self.update_one_calls: List[Dict[str, Any]] = []
        self.delete_many_calls: List[Dict[str, Any]] = []

    def find(self, query: Dict[str, Any] = None):
        out = list(self.docs)
        if query:
            out = [d for d in out if _match(d, query)]

        class _Cur:
            def __init__(self_inner, items):
                self_inner._items = items

            def __aiter__(self_inner):
                async def _gen():
                    for it in self_inner._items:
                        yield it
                return _gen()
        return _Cur(out)

    async def insert_one(self, doc: Dict[str, Any]):
        self.insert_one_calls.append(dict(doc))
        # Pop _id from doc shape if present, else assign a fake.
        doc_copy = dict(doc)
        doc_copy["_id"] = doc.get("_id") or f"pid_{len(self.docs)}"
        self.docs.append(doc_copy)
        r = MagicMock(); r.inserted_id = doc_copy["_id"]
        return r

    async def update_one(self, filter_: Dict[str, Any], update: Dict[str, Any]):
        self.update_one_calls.append({
            "filter": dict(filter_), "update": dict(update),
        })
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock(); r.modified_count = 1
                return r
        r = MagicMock(); r.modified_count = 0
        return r

    async def delete_many(self, filter_: Dict[str, Any]):
        self.delete_many_calls.append(dict(filter_))
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, filter_)]
        r = MagicMock(); r.deleted_count = before - len(self.docs)
        return r


def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        actual = doc.get(k)
        if isinstance(v, dict):
            if "$lt" in v:
                if not (isinstance(actual, datetime) and actual < v["$lt"]):
                    return False
            elif "$in" in v:
                if actual not in v["$in"]:
                    return False
            else:
                return False
        elif actual != v:
            return False
    return True


class _StubProjectsColl:
    def __init__(self, docs: List[Dict[str, Any]] = None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    async def find_one(self, query: Dict[str, Any]):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


class _StubDb:
    def __init__(self, projects=None, predictions=None):
        self.projects = _StubProjectsColl(projects)
        self._cs = {PREDICTED_EVENTS_COLLECTION: _StubPredColl(predictions)}

    def __getitem__(self, name):
        if name not in self._cs:
            self._cs[name] = _StubPredColl()
        return self._cs[name]


# ──────────────────────────────────────────────────────────────────
# Confidence + display unit tests
# ──────────────────────────────────────────────────────────────────


class TestConfidenceCalc(unittest.TestCase):

    def test_zero_sample_returns_zero(self):
        self.assertEqual(_compute_confidence(inspection_rate=1.0, sample_size=0), 0.0)

    def test_full_sample_full_rate_hits_cap(self):
        # 1.0 × 1.0 = 1.0, capped at 0.99.
        self.assertEqual(_compute_confidence(inspection_rate=1.0, sample_size=100), 0.99)

    def test_threshold_boundary_at_saturation(self):
        # rate=0.70 at sample=50 → scale=1.0 → 0.70 exactly.
        c = _compute_confidence(
            inspection_rate=0.70,
            sample_size=PREDICTION_CONFIDENCE_SATURATION_SAMPLES,
        )
        self.assertAlmostEqual(c, 0.70)
        self.assertGreaterEqual(c, PREDICTION_CONFIDENCE_THRESHOLD)

    def test_low_sample_dampens(self):
        # rate=1.0 at sample=10 → scale=0.2 → 0.20 confidence.
        c = _compute_confidence(inspection_rate=1.0, sample_size=10)
        self.assertAlmostEqual(c, 0.20)

    def test_high_rate_high_sample(self):
        # rate=0.85 sample=45 → 0.85 × 0.9 = 0.765 (above threshold).
        c = _compute_confidence(inspection_rate=0.85, sample_size=45)
        self.assertAlmostEqual(c, 0.85 * 0.9, places=4)
        self.assertGreaterEqual(c, PREDICTION_CONFIDENCE_THRESHOLD)


class TestDisplayMessageFormat(unittest.TestCase):
    """Pin the operator-facing string format from the spec example
    "Inspection likely tomorrow between 3-5 PM"."""

    def test_spec_example_tomorrow_3_5_pm(self):
        # median 28h = ~1.17 days → "tomorrow". mode 16 = 4 PM.
        # span 1 → window 15-17 → "3-5 PM".
        msg = _format_display_message(28.0, 16)
        self.assertEqual(msg, "Inspection likely tomorrow between 3-5 PM.")

    def test_today_window(self):
        msg = _format_display_message(4.0, 10)  # ~0 days, 10 AM
        self.assertEqual(msg, "Inspection likely today between 9-11 AM.")

    def test_multi_day_window(self):
        msg = _format_display_message(72.0, 14)  # 3 days, 2 PM
        self.assertEqual(msg, "Inspection likely in 3 days between 1-3 PM.")

    def test_noon_boundary_split_ampm(self):
        # mode 12 (noon), span 1 → window [11, 13] = "11 AM - 1 PM".
        msg = _format_display_message(4.0, 12)
        self.assertEqual(msg, "Inspection likely today between 11 AM - 1 PM.")

    def test_midnight_boundary_split_ampm(self):
        # mode 0 (midnight), span 1 → [23, 1] = "11 PM - 1 AM" (defensive).
        msg = _format_display_message(4.0, 0)
        self.assertEqual(msg, "Inspection likely today between 11 PM - 1 AM.")

    def test_format_is_documented_pattern(self):
        # Regex pin: "Inspection likely <day_phrase> between <window>."
        msg = _format_display_message(28.0, 16)
        self.assertRegex(
            msg,
            r"^Inspection likely (today|tomorrow|in \d+ days) "
            r"between .+\.$",
        )


# ──────────────────────────────────────────────────────────────────
# predict_inspection_from_complaint
# ──────────────────────────────────────────────────────────────────


def _seed_correlated_training_set(
    socrata: MockSocrataClient,
    *,
    complaint_type: str = "Illegal Construction",
    borough: str = "MANHATTAN",
    sample_size: int = 60,
    match_rate: float = 0.80,
    delta_hours: int = 28,  # roughly 1 day + 4 hours
    inspection_hour: int = 16,  # 4 PM
):
    """Seed historical complaints + DOB inspections such that the
    join produces a known inspection_rate + median + mode.

    Args:
      sample_size: total historical complaints seeded
      match_rate: fraction that have a matching inspection within window
      delta_hours: time from complaint to inspection for matches
      inspection_hour: hour-of-day for all matched inspections
    """
    base_date = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
    n_matched = int(round(sample_size * match_rate))

    # Historical complaints
    complaints = []
    inspections = []
    for i in range(sample_size):
        c_date = base_date + timedelta(days=i)
        bbl = f"100100{i:04d}"
        complaints.append({
            "unique_key": f"H{i:04d}",
            "bbl": bbl,
            "complaint_type": complaint_type,
            "borough": borough,
            "created_date": c_date.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if i < n_matched:
            # Add an inspection within the 7-day window at the
            # specified delta + hour-of-day.
            i_date = (c_date + timedelta(hours=delta_hours)).replace(
                hour=inspection_hour, minute=0, second=0,
            )
            inspections.append({
                "bbl": bbl,
                "inspection_date": i_date.strftime("%Y-%m-%dT%H:%M:%S"),
            })
    socrata.seed(DATASET_COMPLAINTS_311, complaints)
    socrata.seed(DATASET_DOB_INSPECTIONS, inspections)


class TestPredictInspectionFromComplaint(unittest.TestCase):

    def _complaint(self):
        return {
            "unique_key": "TRIGGER_311_1",
            "complaint_type": "Illegal Construction",
            "borough": "MANHATTAN",
            "created_date": datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S",
            ),
        }

    def _project(self):
        return {
            "_id": "PROJ_A",
            "company_id": "co_a",
            "nyc_bin": "1234567",
            "bbl": "1001234567",
            "borough": "MANHATTAN",
        }

    def test_happy_path_returns_prediction_dict(self):
        socrata = MockSocrataClient()
        _seed_correlated_training_set(
            socrata, sample_size=60, match_rate=0.85,
            delta_hours=28, inspection_hour=16,
        )
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNotNone(result)
        self.assertEqual(result["trigger_kind"], "311_inspection_prediction")
        self.assertEqual(result["method"], PREDICTION_METHOD)
        self.assertEqual(result["trigger_complaint_id"], "TRIGGER_311_1")
        self.assertEqual(result["project_id"], "PROJ_A")
        self.assertEqual(result["outcome_status"], "active")
        self.assertGreaterEqual(result["confidence"], PREDICTION_CONFIDENCE_THRESHOLD)
        self.assertIn("display_message", result)
        self.assertIn("Inspection likely", result["display_message"])
        # expires_at = predicted_at + 7 days
        delta = result["expires_at"] - result["predicted_at"]
        self.assertEqual(delta.days, PREDICTION_INSPECTION_WINDOW_DAYS)

    def test_below_confidence_threshold_returns_none(self):
        # rate=0.70 at sample=30 → scale=0.6 → confidence=0.42 → below
        socrata = MockSocrataClient()
        _seed_correlated_training_set(
            socrata, sample_size=30, match_rate=0.70,
        )
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNone(result)

    def test_sample_size_below_minimum_returns_none(self):
        socrata = MockSocrataClient()
        _seed_correlated_training_set(
            socrata,
            sample_size=PREDICTION_MIN_SAMPLE_SIZE - 1,
            match_rate=1.0,
        )
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNone(result)

    def test_inspection_rate_below_minimum_returns_none(self):
        # rate=0.30 — below the PREDICTION_MIN_INSPECTION_RATE=0.50 floor.
        socrata = MockSocrataClient()
        _seed_correlated_training_set(
            socrata, sample_size=100, match_rate=0.30,
        )
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNone(result)

    def test_no_historical_complaints_returns_none(self):
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNone(result)

    def test_missing_complaint_metadata_returns_none(self):
        # Defensive: complaint with no complaint_type / borough /
        # unique_key shouldn't blow up.
        socrata = MockSocrataClient()
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), {}, now=now,
        ))
        self.assertIsNone(result)

    def test_socrata_query_error_returns_none(self):
        socrata = MockSocrataClient()
        socrata.add_handler(
            DATASET_COMPLAINTS_311,
            raises=SocrataQueryError("kaboom", dataset_id=DATASET_COMPLAINTS_311),
        )
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        result = _run(predict_inspection_from_complaint(
            socrata, self._project(), self._complaint(), now=now,
        ))
        self.assertIsNone(result)


# ──────────────────────────────────────────────────────────────────
# try_predict_inspection_from_complaint wrapper
# ──────────────────────────────────────────────────────────────────


class TestTryPredictWrapper(unittest.TestCase):

    def _complaint(self):
        return {
            "unique_key": "WRAPPER_TEST_1",
            "complaint_type": "Illegal Construction",
            "borough": "MANHATTAN",
            "created_date": "2026-05-13T09:00:00",
        }

    def _project(self):
        return {"_id": "P_WRAP", "company_id": "co_w"}

    def test_success_inserts_prediction(self):
        db = _StubDb()
        fake_pred = {
            "project_id": "P_WRAP",
            "trigger_kind": "311_inspection_prediction",
            "confidence": 0.85,
            "display_message": "Inspection likely tomorrow between 3-5 PM.",
            "outcome_status": "active",
            "method": PREDICTION_METHOD,
        }

        async def _fake_predict(*_a, **_kw):
            return fake_pred

        with patch.object(pred, "predict_inspection_from_complaint",
                          new=_fake_predict):
            _run(try_predict_inspection_from_complaint(
                db, self._project(), self._complaint(),
            ))

        # Insert hit the predicted_events collection.
        self.assertEqual(
            len(db[PREDICTED_EVENTS_COLLECTION].insert_one_calls), 1,
        )
        inserted = db[PREDICTED_EVENTS_COLLECTION].insert_one_calls[0]
        self.assertEqual(inserted["confidence"], 0.85)

    def test_below_threshold_no_insert(self):
        db = _StubDb()

        async def _none_predict(*_a, **_kw):
            return None  # below-threshold path

        with patch.object(pred, "predict_inspection_from_complaint",
                          new=_none_predict):
            _run(try_predict_inspection_from_complaint(
                db, self._project(), self._complaint(),
            ))

        self.assertEqual(
            len(db[PREDICTED_EVENTS_COLLECTION].insert_one_calls), 0,
        )

    def test_compute_exception_does_not_propagate(self):
        db = _StubDb()

        async def _explodes(*_a, **_kw):
            raise RuntimeError("simulated compute bug")

        # Should NOT raise.
        with patch.object(pred, "predict_inspection_from_complaint",
                          new=_explodes):
            _run(try_predict_inspection_from_complaint(
                db, self._project(), self._complaint(),
            ))
        # No insert happened (exception path).
        self.assertEqual(
            len(db[PREDICTED_EVENTS_COLLECTION].insert_one_calls), 0,
        )

    def test_timeout_does_not_propagate(self):
        db = _StubDb()

        async def _hangs(*_a, **_kw):
            await asyncio.sleep(99)
            return {}

        with patch.object(pred, "predict_inspection_from_complaint", new=_hangs), \
             patch.object(pred, "PREDICTION_COMPUTE_TIMEOUT_SECONDS", 0.05):
            _run(try_predict_inspection_from_complaint(
                db, self._project(), self._complaint(),
            ))
        self.assertEqual(
            len(db[PREDICTED_EVENTS_COLLECTION].insert_one_calls), 0,
        )

    def test_logs_would_notify_marker_on_success(self):
        """The TODO-shaped log marker is what an operator greps
        for to see which predictions WOULD have fired before
        Commit 7's notifications collection lands."""
        db = _StubDb()
        fake_pred = {
            "project_id": "P_WRAP",
            "trigger_kind": "311_inspection_prediction",
            "confidence": 0.88,
            "display_message": "Inspection likely tomorrow between 3-5 PM.",
            "outcome_status": "active",
            "method": PREDICTION_METHOD,
        }

        async def _fake_predict(*_a, **_kw):
            return fake_pred

        with patch.object(pred, "predict_inspection_from_complaint",
                          new=_fake_predict), \
             self.assertLogs(pred.logger, level="INFO") as logs:
            _run(try_predict_inspection_from_complaint(
                db, self._project(), self._complaint(),
            ))

        self.assertIn("WOULD NOTIFY", "\n".join(logs.output))
        self.assertIn("Commit 7", "\n".join(logs.output))


# ──────────────────────────────────────────────────────────────────
# sweep_prediction_resolutions
# ──────────────────────────────────────────────────────────────────


class TestSweepPredictionResolutions(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    def _active_prediction(self, _id, predicted_at_offset_days=1,
                            expires_offset_days=7):
        predicted_at = self.now - timedelta(days=predicted_at_offset_days)
        return {
            "_id": _id,
            "project_id": "P_SWEEP",
            "trigger_kind": "311_inspection_prediction",
            "method": PREDICTION_METHOD,
            "predicted_at": predicted_at,
            "expires_at": predicted_at + timedelta(days=expires_offset_days),
            "outcome_status": "active",
        }

    def test_active_with_matching_inspection_hit(self):
        prediction = self._active_prediction("PRED_HIT")
        db = _StubDb(
            projects=[{"_id": "P_SWEEP", "nyc_bin": "9999999"}],
            predictions=[prediction],
        )
        socrata = MockSocrataClient()
        # An inspection occurred after predicted_at.
        inspect_time = prediction["predicted_at"] + timedelta(hours=20)
        socrata.seed(DATASET_DOB_INSPECTIONS, [{
            "bin": "9999999",
            "inspection_date": inspect_time.strftime("%Y-%m-%dT%H:%M:%S"),
        }])

        # Patch the ServerHttpClient usage so the sweep uses our mock.
        with patch.object(pred, "ServerHttpClient") as MockHttp, \
             patch.object(pred, "SocrataClient", return_value=socrata):
            MockHttp.return_value.__aenter__ = lambda self_inner: asyncio_async_return(self_inner)
            MockHttp.return_value.__aexit__ = lambda self_inner, *_a: asyncio_async_return(None)
            stats = _run(sweep_prediction_resolutions(db, now=self.now))

        self.assertEqual(stats["hit"], 1)
        # The prediction got updated with outcome_status=hit + resolved_at.
        updated = db[PREDICTED_EVENTS_COLLECTION].docs[0]
        self.assertEqual(updated["outcome_status"], "hit")
        self.assertIsNotNone(updated.get("resolved_at"))
        self.assertIsNotNone(updated.get("actual_inspection_date"))

    def test_expired_without_inspection_miss(self):
        prediction = self._active_prediction(
            "PRED_MISS",
            predicted_at_offset_days=10,
            expires_offset_days=7,  # expired 3 days ago
        )
        db = _StubDb(
            projects=[{"_id": "P_SWEEP", "nyc_bin": "9999999"}],
            predictions=[prediction],
        )
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [])  # no inspections

        with patch.object(pred, "ServerHttpClient") as MockHttp, \
             patch.object(pred, "SocrataClient", return_value=socrata):
            MockHttp.return_value.__aenter__ = lambda self_inner: asyncio_async_return(self_inner)
            MockHttp.return_value.__aexit__ = lambda self_inner, *_a: asyncio_async_return(None)
            stats = _run(sweep_prediction_resolutions(db, now=self.now))

        self.assertEqual(stats["miss"], 1)
        updated = db[PREDICTED_EVENTS_COLLECTION].docs[0]
        self.assertEqual(updated["outcome_status"], "miss")
        self.assertIsNotNone(updated.get("resolved_at"))

    def test_still_active_not_yet_expired_unchanged(self):
        prediction = self._active_prediction(
            "PRED_ACTIVE",
            predicted_at_offset_days=2,
            expires_offset_days=7,  # not yet expired
        )
        db = _StubDb(
            projects=[{"_id": "P_SWEEP", "nyc_bin": "9999999"}],
            predictions=[prediction],
        )
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [])

        with patch.object(pred, "ServerHttpClient") as MockHttp, \
             patch.object(pred, "SocrataClient", return_value=socrata):
            MockHttp.return_value.__aenter__ = lambda self_inner: asyncio_async_return(self_inner)
            MockHttp.return_value.__aexit__ = lambda self_inner, *_a: asyncio_async_return(None)
            stats = _run(sweep_prediction_resolutions(db, now=self.now))

        self.assertEqual(stats["still_active"], 1)
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(stats["miss"], 0)
        # Status preserved as active.
        unchanged = db[PREDICTED_EVENTS_COLLECTION].docs[0]
        self.assertEqual(unchanged["outcome_status"], "active")

    def test_expired_no_bin_marks_expired_no_data(self):
        prediction = self._active_prediction(
            "PRED_NO_BIN",
            predicted_at_offset_days=10,
            expires_offset_days=7,  # expired
        )
        db = _StubDb(
            projects=[{"_id": "P_SWEEP"}],  # no nyc_bin
            predictions=[prediction],
        )
        socrata = MockSocrataClient()

        with patch.object(pred, "ServerHttpClient") as MockHttp, \
             patch.object(pred, "SocrataClient", return_value=socrata):
            MockHttp.return_value.__aenter__ = lambda self_inner: asyncio_async_return(self_inner)
            MockHttp.return_value.__aexit__ = lambda self_inner, *_a: asyncio_async_return(None)
            stats = _run(sweep_prediction_resolutions(db, now=self.now))

        self.assertEqual(stats["expired_no_data"], 1)
        unchanged = db[PREDICTED_EVENTS_COLLECTION].docs[0]
        self.assertEqual(unchanged["outcome_status"], "expired_no_data")

    def test_empty_collection_returns_zero_stats(self):
        db = _StubDb()
        stats = _run(sweep_prediction_resolutions(db, now=self.now))
        self.assertEqual(stats["checked"], 0)
        self.assertEqual(stats["hit"], 0)


# ──────────────────────────────────────────────────────────────────
# opportunistic_resolution_check
# ──────────────────────────────────────────────────────────────────


class TestOpportunisticResolutionCheck(unittest.TestCase):

    def test_scoped_to_one_project(self):
        """Active predictions for project A should be resolved;
        active predictions for project B should be ignored."""
        now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        pred_a = {
            "_id": "P_A_PRED", "project_id": "PROJECT_A",
            "trigger_kind": "311_inspection_prediction",
            "method": PREDICTION_METHOD,
            "predicted_at": now - timedelta(days=2),
            "expires_at": now + timedelta(days=5),
            "outcome_status": "active",
        }
        pred_b = {
            "_id": "P_B_PRED", "project_id": "PROJECT_B",
            "trigger_kind": "311_inspection_prediction",
            "method": PREDICTION_METHOD,
            "predicted_at": now - timedelta(days=2),
            "expires_at": now + timedelta(days=5),
            "outcome_status": "active",
        }
        db = _StubDb(
            projects=[
                {"_id": "PROJECT_A", "nyc_bin": "1111111"},
                {"_id": "PROJECT_B", "nyc_bin": "2222222"},
            ],
            predictions=[pred_a, pred_b],
        )
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [{
            "bin": "1111111",
            "inspection_date": (now - timedelta(hours=20)).strftime(
                "%Y-%m-%dT%H:%M:%S",
            ),
        }])

        with patch.object(pred, "ServerHttpClient") as MockHttp, \
             patch.object(pred, "SocrataClient", return_value=socrata):
            MockHttp.return_value.__aenter__ = lambda self_inner: asyncio_async_return(self_inner)
            MockHttp.return_value.__aexit__ = lambda self_inner, *_a: asyncio_async_return(None)
            stats = _run(opportunistic_resolution_check(
                db, "PROJECT_A", now=now,
            ))

        # Only project A was checked; only project A's pred was resolved.
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["hit"], 1)
        # Project B's prediction stayed active.
        b = next(d for d in db[PREDICTED_EVENTS_COLLECTION].docs
                 if d["_id"] == "P_B_PRED")
        self.assertEqual(b["outcome_status"], "active")


# ──────────────────────────────────────────────────────────────────
# cleanup_resolved_predictions
# ──────────────────────────────────────────────────────────────────


class TestCleanupResolvedPredictions(unittest.TestCase):

    def test_resolved_over_retention_deleted(self):
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        old_resolved = now - timedelta(days=RESOLVED_PREDICTION_RETENTION_DAYS + 5)
        recent_resolved = now - timedelta(days=RESOLVED_PREDICTION_RETENTION_DAYS - 5)
        active = {
            "_id": "ACT",
            "method": PREDICTION_METHOD,
            "outcome_status": "active",
            "resolved_at": None,
        }
        db = _StubDb(predictions=[
            {
                "_id": "OLD_HIT", "method": PREDICTION_METHOD,
                "outcome_status": "hit", "resolved_at": old_resolved,
            },
            {
                "_id": "OLD_MISS", "method": PREDICTION_METHOD,
                "outcome_status": "miss", "resolved_at": old_resolved,
            },
            {
                "_id": "RECENT", "method": PREDICTION_METHOD,
                "outcome_status": "hit", "resolved_at": recent_resolved,
            },
            active,
        ])

        stats = _run(cleanup_resolved_predictions(db, now=now))
        self.assertEqual(stats["deleted"], 2)
        # Recent + active survive.
        remaining_ids = {d["_id"] for d in db[PREDICTED_EVENTS_COLLECTION].docs}
        self.assertEqual(remaining_ids, {"RECENT", "ACT"})

    def test_other_method_not_touched(self):
        """V2.2-trigger predictions (no method field) must not
        be deleted by Commit-6's cleanup."""
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        old = now - timedelta(days=RESOLVED_PREDICTION_RETENTION_DAYS + 10)
        db = _StubDb(predictions=[
            {
                "_id": "V22_TRIG",
                # No method field — V2.2-shaped prediction
                "outcome_status": "hit",
                "resolved_at": old,
            },
        ])
        stats = _run(cleanup_resolved_predictions(db, now=now))
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(len(db[PREDICTED_EVENTS_COLLECTION].docs), 1)


# ──────────────────────────────────────────────────────────────────
# Re-exports
# ──────────────────────────────────────────────────────────────────


class TestPredictionsReexports(unittest.TestCase):

    def test_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "predict_inspection_from_complaint",
            "try_predict_inspection_from_complaint",
            "sweep_prediction_resolutions",
            "opportunistic_resolution_check",
            "cleanup_resolved_predictions",
            "PREDICTION_CONFIDENCE_THRESHOLD",
            "PREDICTION_LOOKBACK_YEARS",
            "PREDICTION_INSPECTION_WINDOW_DAYS",
            "PREDICTION_MIN_SAMPLE_SIZE",
            "PREDICTION_MIN_INSPECTION_RATE",
            "PREDICTION_COMPUTE_TIMEOUT_SECONDS",
            "RESOLVED_PREDICTION_RETENTION_DAYS",
            "PREDICTION_METHOD",
        ):
            self.assertTrue(
                hasattr(stat_engine, name),
                f"missing re-export: {name}",
            )


# ──────────────────────────────────────────────────────────────────
# Small async return helper for the mocked ServerHttpClient
# ──────────────────────────────────────────────────────────────────


async def asyncio_async_return(value):
    return value


# ──────────────────────────────────────────────────────────────────
# V2.3 Commit 6 — integration tests of the 4-condition hook
# predicate in server.py:_ingest_311_for_project
# ──────────────────────────────────────────────────────────────────
#
# Imported lazily inside each test_method so test-collection
# doesn't trigger server.py's heavy module-level imports unless
# this test class actually runs. (Other tests in this file don't
# need server.py.)

from unittest.mock import AsyncMock  # noqa: E402


def _build_hook_test_fixtures(
    *,
    existing: Optional[Dict[str, Any]],
    severity_action: bool,
    initial_scan_done: bool,
) -> Dict[str, Any]:
    """Build the project + rec + mock dependencies for a single
    _ingest_311_for_project hook test.

    Returns a dict carrying:
      • captured_tasks: list mutated by the fake create_task
      • project, rec: fixture data the function operates on
      • mock_db, mock_fetch, mock_alert, mock_initial_scan,
        mock_mark_initial: AsyncMocks for the I/O surface
      • create_task_fake: synchronous fn that records spawns +
        closes the spawned coroutine to silence warnings
    """
    captured_tasks: List[Dict[str, Any]] = []

    def create_task_fake(coro, *, name=None):
        # Record the spawn for assertion. Close the coroutine
        # so Python doesn't emit "coroutine was never awaited".
        captured_tasks.append({"name": name})
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    # Pick complaint_type to drive _severity_for_311 naturally.
    # "Illegal Construction" is in _311_ACTION_COMPLAINT_TYPES;
    # "Noise" is not.
    complaint_type = "Illegal Construction" if severity_action else "Noise"

    project = {
        "_id": "P_HOOK_TEST",
        "company_id": "co_hook",
        "nyc_bin": "1234567",
        "bbl": "1001234567",
        "borough": "MANHATTAN",
        "name": "Hook Test Project",
        "address": "100 Test Street",
    }
    rec = {
        "unique_key": "HOOK_TEST_311",
        "complaint_type": complaint_type,
        "status": "Open",
        "descriptor": "Test descriptor",
        "created_date": "2026-05-13T09:00:00",
        "agency": "DOB",
        "agency_name": "Department of Buildings",
        "incident_address": "100 Test Street",
        "city": "Manhattan",
        "closed_date": None,
        "resolution_description": "",
    }

    # Mock the db.dob_logs surface.
    mock_db = MagicMock()
    mock_db.dob_logs = MagicMock()
    mock_db.dob_logs.find_one = AsyncMock(return_value=existing)
    mock_db.dob_logs.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="dl_inserted_1"),
    )

    # Other dependencies (all async).
    mock_fetch = AsyncMock(return_value=[rec])
    mock_alert = AsyncMock(return_value=True)
    mock_initial_scan = AsyncMock(return_value=initial_scan_done)
    mock_mark_initial = AsyncMock()

    # The spawned target. Replaced with a coroutine factory that
    # never executes (its coroutine is closed by create_task_fake).
    async def _noop_predict(*_a, **_kw):
        return None

    return {
        "captured_tasks":    captured_tasks,
        "project":           project,
        "rec":               rec,
        "mock_db":           mock_db,
        "mock_fetch":        mock_fetch,
        "mock_alert":        mock_alert,
        "mock_initial_scan": mock_initial_scan,
        "mock_mark_initial": mock_mark_initial,
        "noop_predict":      _noop_predict,
        "create_task_fake":  create_task_fake,
    }


def _run_ingest_with_hook_mocks(fx: Dict[str, Any]) -> None:
    """Apply patches from the fixture dict + run
    _ingest_311_for_project. After the call returns,
    fx["captured_tasks"] holds the spawned-task records."""
    import server  # heavy import, lazy to keep other tests fast
    import asyncio as _asyncio_mod  # patched at module level

    with patch.object(server, "_fetch_311_for_project",
                      new=fx["mock_fetch"]), \
         patch.object(server, "db", new=fx["mock_db"]), \
         patch.object(server, "_send_critical_dob_alert_throttled",
                      new=fx["mock_alert"]), \
         patch.object(server, "_initial_scan_done",
                      new=fx["mock_initial_scan"]), \
         patch.object(server, "_mark_initial_scan_done",
                      new=fx["mock_mark_initial"]), \
         patch.object(server._stat_engine,
                      "try_predict_inspection_from_complaint",
                      new=fx["noop_predict"]), \
         patch.object(_asyncio_mod, "create_task",
                      new=fx["create_task_fake"]):
        _run(server._ingest_311_for_project(
            fx["project"], MagicMock(),
        ))


class TestPredictionHookIntegration(unittest.TestCase):
    """Runtime tests of the 4-condition prediction-spawn hook in
    server.py:_ingest_311_for_project. Verifies that
    ``asyncio.create_task`` is invoked (positive case) or NOT
    invoked (negative cases) per the predicate semantics.

    Closes the gap left by the grep-only tests in
    test_v2_2_schema_scaffolding.py — those only assert that
    the predicate strings appear in source; these prove the
    runtime behavior is correct.
    """

    # ── Positive case ──────────────────────────────────────────

    def test_all_four_conditions_met_spawns_prediction_task(self):
        """existing=None + not seed_transition + severity=Action
        + initial_scan_done=True → spawn fires exactly once with
        the documented task-name pattern."""
        fx = _build_hook_test_fixtures(
            existing=None,            # condition 1 PASS
            severity_action=True,     # condition 3 PASS
            initial_scan_done=True,   # condition 4 PASS
            # is_seed_transition_311 = (None is not None and ...) = False,
            # so condition 2 PASS automatically.
        )
        _run_ingest_with_hook_mocks(fx)

        # Exactly one spawn — for our single test record.
        self.assertEqual(len(fx["captured_tasks"]), 1)
        # Name follows the spec pattern: "predict_inspection:<project>:<complaint>"
        name = fx["captured_tasks"][0]["name"]
        self.assertIsNotNone(name)
        self.assertTrue(
            name.startswith("predict_inspection:"),
            f"unexpected task name: {name!r}",
        )
        self.assertIn("P_HOOK_TEST", name)
        self.assertIn("HOOK_TEST_311", name)

    # ── Negative cases ─────────────────────────────────────────

    def test_existing_not_none_blocks_spawn(self):
        """Condition 1 fails: existing is not None (a prior dob_logs
        row with the same raw_dob_id but different current_status,
        which is the status-transition insert path). Even with
        the other three conditions all passing, no spawn fires.

        The existing doc carries a current_status field different
        from the new record's, which means:
          - is_seed_transition_311 is False (has current_status)
          - existing is not None → condition 1 fails
        Isolates the existing-is-None gate from the seed-transition
        gate."""
        fx = _build_hook_test_fixtures(
            existing={
                "raw_dob_id":      "311:HOOK_TEST_311",
                "current_status":  "Closed",  # differs from rec's "Open"
                "complaint_status": "Closed",
            },
            severity_action=True,     # condition 3 still PASS
            initial_scan_done=True,   # condition 4 still PASS
        )
        _run_ingest_with_hook_mocks(fx)
        self.assertEqual(fx["captured_tasks"], [])

    def test_is_seed_transition_blocks_spawn(self):
        """Condition 2 fails: existing is non-None AND has no
        current_status field — the V2.2 schema-migration synthetic-
        seed shape. is_seed_transition_311 evaluates to True;
        ``not is_seed_transition_311`` therefore fails the gate.

        NOTE: this case also fails condition 1 (existing is not
        None), since is_seed_transition can ONLY be True when
        existing is non-None. The two conditions are not
        independently isolable. This test pins that the
        seed-transition branch — separately — would block, even
        if the existing-is-None gate didn't already do so.
        """
        fx = _build_hook_test_fixtures(
            existing={
                "raw_dob_id": "311:HOOK_TEST_311",
                # No current_status field — pre-V2.2 schema legacy.
                "complaint_status": "Open",
            },
            severity_action=True,
            initial_scan_done=True,
        )
        _run_ingest_with_hook_mocks(fx)
        self.assertEqual(fx["captured_tasks"], [])

    def test_severity_monitor_blocks_spawn(self):
        """Condition 3 fails: complaint_type maps to severity
        "Monitor" (not Action). Other three conditions all pass.
        Verifies non-Action 311 categories don't fire predictions."""
        fx = _build_hook_test_fixtures(
            existing=None,            # condition 1 PASS
            severity_action=False,    # complaint_type = "Noise" → "Monitor"
            initial_scan_done=True,   # condition 4 PASS
        )
        _run_ingest_with_hook_mocks(fx)
        self.assertEqual(fx["captured_tasks"], [])

    def test_initial_scan_not_done_blocks_spawn(self):
        """Condition 4 fails: _initial_scan_done returns False
        (first 311 poll for this project — backfill window).
        Other three conditions all pass. Verifies the backfill
        suppression prevents the operator from getting stale
        "inspection likely tomorrow" alerts on historical
        complaints."""
        fx = _build_hook_test_fixtures(
            existing=None,            # condition 1 PASS
            severity_action=True,     # condition 3 PASS
            initial_scan_done=False,  # condition 4 FAIL
        )
        _run_ingest_with_hook_mocks(fx)
        self.assertEqual(fx["captured_tasks"], [])


if __name__ == "__main__":
    unittest.main()
