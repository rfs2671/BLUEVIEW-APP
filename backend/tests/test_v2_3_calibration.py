"""Phase V2.3 — calibration loop + admin endpoint tests.

Replaces test_v2_2_calibration.py. Outcome attribution now uses
SocrataClient for the "did the predicted event occur?" lookup,
keyed on the new ``TRIGGER_EVIDENCE_DATASET`` mapping.
Aggregation / admin / prior-tuning paths are Mongo-only and
unchanged from V2.2.

Coverage:
  • Outcome statuses (hit / miss / expired_no_data) pinned.
  • TRIGGER_EVIDENCE_DATASET maps all 8 triggers to (dataset_id,
    date_column) tuples.
  • attribute_outcome_for_prediction (now socrata-aware):
      - hit when matching event lands in window
      - miss when no matching event lands
      - expired_no_data when project BIN unresolvable
      - flips outcome_status on the original prediction
  • attribute_outcomes_for_expired_predictions walks expired
    rows + summarizes; accepts optional socrata.
  • compute_calibration_stats math (per-trigger + overall).
  • set_trigger_prior / get_trigger_prior round-trip; rejects
    unknown trigger / out-of-range prior.
  • Admin endpoints exist on server.py with admin-user gating
    (only the two surviving endpoints — Commit 1 removed the
    backfill endpoint).
  • V2.2 cron was deleted by Commit 1; pin the removal.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from lib.statistical_engine import calibration as cal  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402
from lib.statistical_engine import triggers as tr  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_COMPLAINTS_311,
)

from _socrata_mock import MockSocrataClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Outcome constants + evidence mapping
# ──────────────────────────────────────────────────────────────────


class TestOutcomeConstants(unittest.TestCase):

    def test_outcome_strings_pinned(self):
        self.assertEqual(cal.OUTCOME_HIT, "hit")
        self.assertEqual(cal.OUTCOME_MISS, "miss")
        self.assertEqual(cal.OUTCOME_EXPIRED_NO_DATA, "expired_no_data")

    def test_evidence_mapping_covers_all_triggers(self):
        for kind in tr.ALL_TRIGGER_KINDS:
            self.assertIn(kind, cal.TRIGGER_EVIDENCE_DATASET,
                          f"{kind} missing evidence dataset mapping")

    def test_evidence_mapping_shape_is_dataset_plus_date_field(self):
        # V2.3: each entry is (dataset_id, date_field_name).
        for kind, entry in cal.TRIGGER_EVIDENCE_DATASET.items():
            self.assertIsInstance(entry, tuple, f"{kind}: not a tuple")
            self.assertEqual(len(entry), 2, f"{kind}: wrong arity")
            dataset_id, date_field = entry
            self.assertIsInstance(dataset_id, str)
            self.assertRegex(dataset_id, r"^[a-z0-9]{4}-[a-z0-9]{4}$")
            self.assertIsInstance(date_field, str)
            self.assertTrue(date_field.endswith("_date"))


# ──────────────────────────────────────────────────────────────────
# Stub DB (Mongo state — predictions / outcomes / projects)
# ──────────────────────────────────────────────────────────────────


class _StubColl:
    def __init__(self, docs=None):
        self.docs: list = list(docs or [])

    def find(self, query=None, projection=None):
        out = list(self.docs)
        if query:
            filtered = []
            for d in out:
                ok = True
                for k, v in query.items():
                    actual = d.get(k)
                    if isinstance(v, dict):
                        if "$gte" in v and not (
                            actual is not None and actual >= v["$gte"]
                        ):
                            ok = False; break
                        if "$lte" in v and not (
                            actual is not None and actual <= v["$lte"]
                        ):
                            ok = False; break
                    elif actual != v:
                        ok = False; break
                if ok: filtered.append(d)
            out = filtered

        items = list(out)

        class _Cur:
            def __init__(self_inner):
                self_inner._limit = None
            def limit(self_inner, n):
                self_inner._limit = n
                return self_inner
            def __aiter__(self_inner):
                async def _gen():
                    n = 0
                    for it in items:
                        if self_inner._limit is not None and n >= self_inner._limit:
                            break
                        n += 1
                        yield it
                return _gen()
        return _Cur()

    async def find_one(self, query):
        for d in self.docs:
            ok = True
            for k, v in query.items():
                if d.get(k) != v: ok = False; break
            if ok: return d
        return None

    async def insert_one(self, doc):
        self.docs.append(doc)
        r = MagicMock(); r.inserted_id = f"id_{len(self.docs)}"
        return r

    async def update_one(self, filter_, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update: d.update(update["$set"])
                r = MagicMock(); r.upserted_id = None
                return r
        new_doc = dict(filter_)
        if "$set" in update: new_doc.update(update["$set"])
        if upsert: self.docs.append(new_doc)
        r = MagicMock(); r.upserted_id = "u" if upsert else None
        return r


class _StubDb:
    def __init__(self):
        self._cs = {}
        self.projects = _StubColl()

    def __getitem__(self, name):
        if name not in self._cs:
            self._cs[name] = _StubColl()
        return self._cs[name]


# ──────────────────────────────────────────────────────────────────
# attribute_outcome_for_prediction (socrata-aware)
# ──────────────────────────────────────────────────────────────────


class TestAttributeOutcome(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        self.predicted_at = self.now - timedelta(days=10)
        self.expires_at = self.now - timedelta(days=1)

    def _prediction(self, **overrides):
        base = {
            "_id": "PRED1",
            "project_id": "P1",
            "trigger_kind": "311_at_bin",
            "predicted_at": self.predicted_at,
            "expires_at":   self.expires_at,
            "outcome_status": "active",
        }
        base.update(overrides)
        return base

    def test_hit_when_matching_event_lands(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        socrata = MockSocrataClient()
        # 311_at_bin → DATASET_COMPLAINTS_311 / created_date.
        socrata.seed(DATASET_COMPLAINTS_311, [{
            "bin": "1234567",
            "created_date":
                (self.predicted_at + timedelta(days=3)).strftime(
                    "%Y-%m-%dT%H:%M:%S"),
        }])
        # Seed the prediction so update_one finds it.
        db[se_schema.PREDICTED_EVENTS_COLLECTION].docs = [self._prediction()]
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), socrata=socrata, now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "hit")
        self.assertIsNotNone(outcome["actual_event_at"])
        self.assertEqual(outcome["hit_window_days"], 3)

    def test_miss_when_no_matching_event(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [])
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), socrata=socrata, now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "miss")
        self.assertIsNone(outcome["actual_event_at"])

    def test_expired_no_data_when_bin_unresolvable(self):
        db = _StubDb()
        db.projects.docs = []  # no project found
        socrata = MockSocrataClient()
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), socrata=socrata, now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "expired_no_data")

    def test_inserts_to_prediction_outcomes(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [])
        _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), socrata=socrata, now=self.now,
        ))
        self.assertEqual(
            len(db[se_schema.PREDICTION_OUTCOMES_COLLECTION].docs), 1,
        )

    def test_records_model_version(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [])
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), socrata=socrata, now=self.now,
        ))
        self.assertEqual(outcome["model_version"], se_schema.MODEL_VERSION)


# ──────────────────────────────────────────────────────────────────
# attribute_outcomes_for_expired_predictions
# ──────────────────────────────────────────────────────────────────


class TestDailyAttribution(unittest.TestCase):

    def test_walks_expired_active_predictions(self):
        db = _StubDb()
        now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        db[se_schema.PREDICTED_EVENTS_COLLECTION].docs = [
            {
                "_id": "A", "project_id": "P1",
                "trigger_kind": "311_at_bin",
                "predicted_at": now - timedelta(days=10),
                "expires_at":   now - timedelta(days=1),
                "outcome_status": "active",
            },
            {
                "_id": "B", "project_id": "P1",
                "trigger_kind": "csc_periodic",
                "predicted_at": now - timedelta(days=10),
                "expires_at":   now - timedelta(days=1),
                "outcome_status": "active",
            },
            {
                "_id": "C", "project_id": "P1",
                "trigger_kind": "311_at_bin",
                "predicted_at": now - timedelta(days=2),
                "expires_at":   now + timedelta(days=5),
                "outcome_status": "active",
            },
            {
                "_id": "D", "project_id": "P1",
                "trigger_kind": "311_at_bin",
                "predicted_at": now - timedelta(days=20),
                "expires_at":   now - timedelta(days=10),
                "outcome_status": "miss",
            },
        ]
        socrata = MockSocrataClient()  # no events seeded → all misses
        summary = _run(cal.attribute_outcomes_for_expired_predictions(
            db, socrata=socrata, now=now,
        ))
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["misses"], 2)


# ──────────────────────────────────────────────────────────────────
# compute_calibration_stats (Mongo-only, unchanged from V2.2)
# ──────────────────────────────────────────────────────────────────


class TestCalibrationStats(unittest.TestCase):

    def test_per_trigger_and_overall_math(self):
        db = _StubDb()
        outcomes = [
            *[{"trigger_kind": "311_at_bin",   "outcome": "hit",
               "model_version": "statistical-v1"} for _ in range(4)],
            {"trigger_kind": "311_at_bin",     "outcome": "miss",
             "model_version": "statistical-v1"},
            *[{"trigger_kind": "csc_periodic", "outcome": "hit",
               "model_version": "statistical-v1"} for _ in range(2)],
            *[{"trigger_kind": "csc_periodic", "outcome": "miss",
               "model_version": "statistical-v1"} for _ in range(2)],
            {"trigger_kind": "neighbor_swo",   "outcome": "expired_no_data",
             "model_version": "statistical-v1"},
        ]
        db[se_schema.PREDICTION_OUTCOMES_COLLECTION].docs = outcomes
        stats = _run(cal.compute_calibration_stats(
            db, model_version="statistical-v1",
        ))
        self.assertEqual(stats["model_version"], "statistical-v1")
        self.assertEqual(stats["sample_size"], 10)
        self.assertAlmostEqual(
            stats["by_trigger"]["311_at_bin"]["accuracy"], 0.80, places=4,
        )
        self.assertAlmostEqual(
            stats["by_trigger"]["csc_periodic"]["accuracy"], 0.50, places=4,
        )
        self.assertAlmostEqual(
            stats["by_trigger"]["neighbor_swo"]["accuracy"], 0.0, places=4,
        )
        self.assertEqual(stats["overall"]["hits"], 6)
        self.assertEqual(stats["overall"]["misses"], 3)
        self.assertEqual(stats["overall"]["expired_no_data"], 1)
        self.assertAlmostEqual(
            stats["overall"]["accuracy"], 6 / 9, places=4,
        )


# ──────────────────────────────────────────────────────────────────
# Manual prior tuning (Mongo-only, unchanged from V2.2)
# ──────────────────────────────────────────────────────────────────


class TestTriggerPriors(unittest.TestCase):

    def test_round_trip(self):
        db = _StubDb()
        _run(cal.set_trigger_prior(
            db, trigger_kind="311_at_bin", prior=0.82,
            note="recalibrated", set_by_user_id="u_admin",
        ))
        prior = _run(cal.get_trigger_prior(db, "311_at_bin"))
        self.assertAlmostEqual(prior, 0.82)

    def test_get_returns_none_when_unset(self):
        db = _StubDb()
        prior = _run(cal.get_trigger_prior(db, "311_at_bin"))
        self.assertIsNone(prior)

    def test_rejects_unknown_trigger(self):
        db = _StubDb()
        with self.assertRaises(ValueError):
            _run(cal.set_trigger_prior(
                db, trigger_kind="not_a_trigger", prior=0.5,
            ))

    def test_rejects_out_of_range_prior(self):
        db = _StubDb()
        with self.assertRaises(ValueError):
            _run(cal.set_trigger_prior(
                db, trigger_kind="311_at_bin", prior=1.5,
            ))

    def test_idempotent_upsert(self):
        db = _StubDb()
        _run(cal.set_trigger_prior(
            db, trigger_kind="311_at_bin", prior=0.80,
        ))
        _run(cal.set_trigger_prior(
            db, trigger_kind="311_at_bin", prior=0.85,
        ))
        self.assertEqual(
            len(db[cal.TRIGGER_PRIORS_COLLECTION].docs), 1,
        )
        prior = _run(cal.get_trigger_prior(db, "311_at_bin"))
        self.assertAlmostEqual(prior, 0.85)


# ──────────────────────────────────────────────────────────────────
# Admin endpoints (server.py wiring — Commit 1 removed backfill)
# ──────────────────────────────────────────────────────────────────


class TestServerAdminEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_calibration_endpoint_present(self):
        self.assertIn(
            '@api_router.get("/admin/risk-score/calibration")', self.text,
        )

    def test_calibration_uses_admin_user_dep(self):
        s = self.text.find(
            '@api_router.get("/admin/risk-score/calibration")',
        )
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e if e > s else s + 1500]
        self.assertIn("Depends(get_admin_user)", slice_)
        self.assertIn("compute_calibration_stats", slice_)

    def test_weights_endpoint_present(self):
        self.assertIn(
            '@api_router.post("/admin/risk-score/weights")', self.text,
        )

    def test_weights_uses_admin_user_dep(self):
        s = self.text.find(
            '@api_router.post("/admin/risk-score/weights")',
        )
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e if e > s else s + 1500]
        self.assertIn("Depends(get_admin_user)", slice_)
        self.assertIn("set_trigger_prior", slice_)


# ──────────────────────────────────────────────────────────────────
# V2.2 calibration cron — removed by Commit 1
# ──────────────────────────────────────────────────────────────────


class TestV22CalibrationCronRemoved(unittest.TestCase):
    """The daily v2_2_calibration_attribution cron was removed in
    V2.3 Commit 1. Pin the removal so a future rewire surfaces
    explicitly. A new V2.3 daily cron will land in a later
    commit once the lazy-query path is fully settled."""

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_v22_tick_id_gone(self):
        self.assertNotIn("v2_2_calibration_attribution", self.text)

    def test_v22_tick_func_gone(self):
        self.assertNotIn("_v22_calibration_tick", self.text)


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExports(unittest.TestCase):

    def test_calibration_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "OUTCOME_HIT", "OUTCOME_MISS", "OUTCOME_EXPIRED_NO_DATA",
            "TRIGGER_PRIORS_COLLECTION",
            "attribute_outcome_for_prediction",
            "attribute_outcomes_for_expired_predictions",
            "compute_calibration_stats",
            "set_trigger_prior", "get_trigger_prior",
        ):
            self.assertTrue(hasattr(stat_engine, name),
                            f"missing re-export: {name}")


if __name__ == "__main__":
    unittest.main()
