"""Phase V2.2 — Commit 6 calibration loop + admin endpoints tests.

Pin every contract:

  • Outcome statuses (hit / miss / expired_no_data) pinned.
  • Per-trigger evidence-collection mapping covers all 8 triggers.
  • attribute_outcome_for_prediction:
      - hit when matching event lands in window
      - miss when no matching event lands
      - expired_no_data when project BIN unresolvable
      - flips outcome_status on the original prediction
  • attribute_outcomes_for_expired_predictions walks expired
    rows + summarizes.
  • compute_calibration_stats produces per-trigger + overall
    metrics with correct math.
  • set_trigger_prior + get_trigger_prior round-trip; rejects
    unknown trigger / out-of-range prior.
  • Admin endpoints exist on server.py with admin-user gating
    and the right paths.
  • Daily cron `v2_2_calibration_attribution` registered at
    5 AM ET.
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

from lib.statistical_engine import calibration as cal  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402
from lib.statistical_engine import triggers as tr  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
            self.assertIn(kind, cal.TRIGGER_EVIDENCE_COLLECTION,
                          f"{kind} missing evidence collection")


# ──────────────────────────────────────────────────────────────────
# Stub DB
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
# attribute_outcome_for_prediction
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
        db[se_schema.NYC_COMPLAINTS_311_COLLECTION].docs = [
            {
                "bin": "1234567",
                "occurred_date": self.predicted_at + timedelta(days=3),
            },
        ]
        # Seed the prediction so the update_one path can flip it.
        db[se_schema.PREDICTED_EVENTS_COLLECTION].docs = [self._prediction()]
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "hit")
        self.assertIsNotNone(outcome["actual_event_at"])
        self.assertEqual(outcome["hit_window_days"], 3)

    def test_miss_when_no_matching_event(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        db[se_schema.NYC_COMPLAINTS_311_COLLECTION].docs = []
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "miss")
        self.assertIsNone(outcome["actual_event_at"])

    def test_expired_no_data_when_bin_unresolvable(self):
        db = _StubDb()
        db.projects.docs = []  # no project found
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), now=self.now,
        ))
        self.assertEqual(outcome["outcome"], "expired_no_data")

    def test_inserts_to_prediction_outcomes(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), now=self.now,
        ))
        self.assertEqual(
            len(db[se_schema.PREDICTION_OUTCOMES_COLLECTION].docs), 1,
        )

    def test_records_model_version(self):
        db = _StubDb()
        db.projects.docs = [{"_id": "P1", "nyc_bin": "1234567"}]
        outcome = _run(cal.attribute_outcome_for_prediction(
            db, self._prediction(), now=self.now,
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
        # 3 predictions: 2 expired-active (eligible), 1 future
        # (skip), 1 already-attributed (skip).
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
        # No NYC events — both A and B should be misses.
        summary = _run(cal.attribute_outcomes_for_expired_predictions(
            db, now=now,
        ))
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["misses"], 2)


# ──────────────────────────────────────────────────────────────────
# compute_calibration_stats
# ──────────────────────────────────────────────────────────────────


class TestCalibrationStats(unittest.TestCase):

    def test_per_trigger_and_overall_math(self):
        db = _StubDb()
        # Seed a known outcome distribution:
        # 311_at_bin: 4 hits, 1 miss → accuracy 0.80
        # csc_periodic: 2 hits, 2 misses → accuracy 0.50
        # neighbor_swo: 1 expired_no_data → accuracy 0.0
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
        # 6 hits / (6 hits + 3 misses) = 0.667.
        self.assertAlmostEqual(
            stats["overall"]["accuracy"], 6 / 9, places=4,
        )


# ──────────────────────────────────────────────────────────────────
# Manual prior tuning
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
        # Only one row in the collection regardless.
        self.assertEqual(
            len(db[cal.TRIGGER_PRIORS_COLLECTION].docs), 1,
        )
        prior = _run(cal.get_trigger_prior(db, "311_at_bin"))
        self.assertAlmostEqual(prior, 0.85)


# ──────────────────────────────────────────────────────────────────
# Admin endpoints (server.py wiring)
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

    def test_backfill_endpoint_present(self):
        self.assertIn(
            '@api_router.post("/admin/risk-score/backfill")', self.text,
        )

    def test_backfill_uses_admin_user_dep(self):
        s = self.text.find(
            '@api_router.post("/admin/risk-score/backfill")',
        )
        e = self.text.find("@api_router", s + 1)
        slice_ = self.text[s:e if e > s else s + 1500]
        self.assertIn("Depends(get_admin_user)", slice_)
        self.assertIn("backfill_all_datasets", slice_)


# ──────────────────────────────────────────────────────────────────
# Daily calibration cron
# ──────────────────────────────────────────────────────────────────


class TestServerCalibrationCron(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_calibration_tick_id(self):
        self.assertIn("v2_2_calibration_attribution", self.text)

    def test_calibration_tick_at_5_am_et(self):
        self.assertIn(
            'CronTrigger(hour=5, minute=0, timezone="America/New_York")',
            self.text,
        )

    def test_calibration_tick_calls_attribution(self):
        s = self.text.find("async def _v22_calibration_tick")
        self.assertGreater(s, 0)
        e = self.text.find("scheduler.add_job", s)
        slice_ = self.text[s:e]
        self.assertIn(
            "attribute_outcomes_for_expired_predictions", slice_,
        )


# ──────────────────────────────────────────────────────────────────
# Documentation
# ──────────────────────────────────────────────────────────────────


class TestDocsLanded(unittest.TestCase):

    def test_v22_docs_present(self):
        path = _REPO / "docs" / "features" / "v2-2-statistical-engine.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        # Spot-check: lifecycle, weights, calibration, operator
        # checklist all addressed.
        self.assertIn("Statistical Risk Engine", text)
        self.assertIn("statistical-v1", text)
        self.assertIn("Operator action checklist", text)
        self.assertIn("BLUEVIEW", text)


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExportsCommit6(unittest.TestCase):

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
