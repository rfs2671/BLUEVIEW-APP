"""Phase V2.3 — trigger detector + event-predictor tests.

Replaces test_v2_2_triggers.py. The individual trigger detectors
are pure functions (untouched by V2.3); their positive/null tests
carry forward unchanged. The orchestrator-layer tests
(``gather_trigger_inputs``, ``run_triggers_for_project``) are
rewritten to use ``MockSocrataClient`` instead of the V2.2
_StubDb-with-nyc_*-collections fixture.

Coverage:
  • 8 trigger-kind constants exist with stable names.
  • Each trigger fires on its positive case and abstains on null.
  • Publication gate: confidence ≥ 0.70 AND peer_sample_size ≥ 20.
  • upsert_prediction is idempotent within a day.
  • expire_stale_predictions flips outcome_status only for past-
    expires_at, active predictions.
  • active_predictions_for_project filters active + unexpired.
  • gather_trigger_inputs: each of the 5 lazy Socrata fetches
    produces the right shape from seeded rows.
  • run_triggers_for_project end-to-end with mock client +
    seeded violations / 311.
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
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_HERE))

from lib.statistical_engine import triggers as tr  # noqa: E402
from lib.statistical_engine import schema as se_schema  # noqa: E402
from lib.statistical_engine.socrata_client import (  # noqa: E402
    DATASET_COMPLAINTS_311,
    DATASET_DOB_INSPECTIONS,
    DATASET_DOB_VIOLATIONS,
)

from _socrata_mock import MockSocrataClient  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────
# Trigger-kind constants
# ──────────────────────────────────────────────────────────────────


class TestTriggerKinds(unittest.TestCase):

    def test_nine_triggers(self):
        # V2.3 Commit 6 added TRIGGER_311_INSPECTION_PREDICTION as
        # a distinct kind from the existing TRIGGER_311_AT_BIN
        # (score-driven). Total moves from 8 → 9.
        self.assertEqual(len(tr.ALL_TRIGGER_KINDS), 9)

    def test_kind_names_pinned(self):
        self.assertEqual(tr.TRIGGER_311_AT_BIN, "311_at_bin")
        self.assertEqual(tr.TRIGGER_311_NEIGHBOR, "311_neighbor")
        self.assertEqual(tr.TRIGGER_CSC_PERIODIC, "csc_periodic")
        self.assertEqual(tr.TRIGGER_BOROUGH_SWEEP, "borough_sweep")
        self.assertEqual(tr.TRIGGER_NEIGHBOR_SWO, "neighbor_swo")
        self.assertEqual(tr.TRIGGER_CSE_FOLLOWUP, "cse_followup")
        self.assertEqual(tr.TRIGGER_CURE_DEADLINE_REINSPECT,
                         "cure_deadline_reinspection")
        self.assertEqual(tr.TRIGGER_SSMR_SHED_AGING, "ssmr_shed_aging")
        # V2.3 Commit 6 addition.
        self.assertEqual(tr.TRIGGER_311_INSPECTION_PREDICTION,
                         "311_inspection_prediction")

    def test_default_windows_present_for_each(self):
        for kind in tr.ALL_TRIGGER_KINDS:
            self.assertIn(kind, tr.DEFAULT_WINDOWS,
                          f"{kind} missing default window")
            lo, hi = tr.DEFAULT_WINDOWS[kind]
            self.assertGreaterEqual(hi, lo)


# ──────────────────────────────────────────────────────────────────
# BBL helpers
# ──────────────────────────────────────────────────────────────────


class TestBblBlockHelper(unittest.TestCase):

    def test_extracts_block(self):
        self.assertEqual(tr._bbl_block("1001234567"), "100123")

    def test_too_short_returns_none(self):
        self.assertIsNone(tr._bbl_block("1234"))

    def test_none_returns_none(self):
        self.assertIsNone(tr._bbl_block(None))

    def test_non_string_returns_none(self):
        self.assertIsNone(tr._bbl_block(1234567890))


# ──────────────────────────────────────────────────────────────────
# Each trigger: positive + null (pure functions, untouched)
# ──────────────────────────────────────────────────────────────────


class TestTrigger311AtBin(unittest.TestCase):

    def test_fires_on_recent_complaint(self):
        out = tr.trigger_311_at_bin(
            {"_id": "p1"},
            recent_311_at_bin=[{"record_id": "311_1"}],
            historical_match_rate=0.78,
            peer_sample_size=42,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["trigger_kind"], "311_at_bin")
        self.assertEqual(out["confidence"], 0.78)

    def test_silent_when_empty(self):
        self.assertIsNone(tr.trigger_311_at_bin(
            {"_id": "p1"},
            recent_311_at_bin=[],
            historical_match_rate=0.78,
            peer_sample_size=42,
        ))


class TestTrigger311Neighbor(unittest.TestCase):

    def test_fires_when_neighbors_have_311(self):
        out = tr.trigger_311_neighbor(
            {"_id": "p1"},
            recent_311_neighbor=[{"record_id": "n1"}, {"record_id": "n2"}],
            historical_match_rate=0.72,
            peer_sample_size=22,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["input_snapshot"]["neighbor_311_count"], 2)


class TestTriggerCscPeriodic(unittest.TestCase):

    def test_fires_when_overdue(self):
        out = tr.trigger_csc_periodic(
            {"_id": "p1"},
            days_since_last_csc=120,
            historical_match_rate=0.81,
            peer_sample_size=30,
            csc_cycle_days=90,
        )
        self.assertIsNotNone(out)

    def test_silent_when_within_cycle(self):
        self.assertIsNone(tr.trigger_csc_periodic(
            {"_id": "p1"},
            days_since_last_csc=30,
            historical_match_rate=0.81,
            peer_sample_size=30,
            csc_cycle_days=90,
        ))

    def test_silent_when_unknown_last_csc(self):
        self.assertIsNone(tr.trigger_csc_periodic(
            {"_id": "p1"},
            days_since_last_csc=None,
            historical_match_rate=0.81,
            peer_sample_size=30,
        ))


class TestTriggerBoroughSweep(unittest.TestCase):

    def test_fires_at_2_sigma_above_mean(self):
        history = [5] * 80 + [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        out = tr.trigger_borough_sweep(
            {"_id": "p1"},
            borough_inspection_counts_90d=history,
            last_7d_count=20,
            historical_match_rate=0.74,
            peer_sample_size=25,
        )
        self.assertIsNotNone(out)

    def test_silent_when_not_above_threshold(self):
        history = [5] * 90
        out = tr.trigger_borough_sweep(
            {"_id": "p1"},
            borough_inspection_counts_90d=history,
            last_7d_count=5,
            historical_match_rate=0.74,
            peer_sample_size=25,
        )
        self.assertIsNone(out)


class TestTriggerNeighborSwo(unittest.TestCase):

    def test_fires_on_neighbor_swo(self):
        out = tr.trigger_neighbor_swo(
            {"_id": "p1"},
            neighbor_swo_count_30d=2,
            historical_match_rate=0.71,
            peer_sample_size=30,
        )
        self.assertIsNotNone(out)

    def test_silent_when_zero(self):
        self.assertIsNone(tr.trigger_neighbor_swo(
            {"_id": "p1"},
            neighbor_swo_count_30d=0,
            historical_match_rate=0.71,
            peer_sample_size=30,
        ))


class TestTriggerCseFollowup(unittest.TestCase):

    def test_fires_on_nearby_violations(self):
        out = tr.trigger_cse_followup(
            {"_id": "p1"},
            nearby_violations_60d=3,
            historical_match_rate=0.75,
            peer_sample_size=30,
        )
        self.assertIsNotNone(out)


class TestTriggerCureDeadline(unittest.TestCase):

    def test_fires_when_cure_within_7_days(self):
        now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        out = tr.trigger_cure_deadline_reinspection(
            {"_id": "p1"},
            open_violations_with_cure=[
                {"cure_deadline": now + timedelta(days=3)},
            ],
            historical_match_rate=0.85,
            peer_sample_size=30,
            now=now,
        )
        self.assertIsNotNone(out)

    def test_silent_when_no_imminent_cure(self):
        now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        out = tr.trigger_cure_deadline_reinspection(
            {"_id": "p1"},
            open_violations_with_cure=[
                {"cure_deadline": now + timedelta(days=30)},
            ],
            historical_match_rate=0.85,
            peer_sample_size=30,
            now=now,
        )
        self.assertIsNone(out)


class TestTriggerSsmrShed(unittest.TestCase):

    def test_fires_on_old_shed(self):
        out = tr.trigger_ssmr_shed_aging(
            {"_id": "p1"},
            shed_age_days=120,
            historical_match_rate=0.73,
            peer_sample_size=25,
        )
        self.assertIsNotNone(out)

    def test_silent_on_young_shed(self):
        self.assertIsNone(tr.trigger_ssmr_shed_aging(
            {"_id": "p1"},
            shed_age_days=30,
            historical_match_rate=0.73,
            peer_sample_size=25,
        ))


# ──────────────────────────────────────────────────────────────────
# Publication gate
# ──────────────────────────────────────────────────────────────────


class TestPublicationGate(unittest.TestCase):

    def test_passes_when_both_thresholds_met(self):
        self.assertTrue(tr.passes_publication_gate({
            "confidence": 0.75, "peer_sample_size": 25,
        }))

    def test_fails_low_confidence(self):
        self.assertFalse(tr.passes_publication_gate({
            "confidence": 0.65, "peer_sample_size": 100,
        }))

    def test_fails_low_sample_size(self):
        self.assertFalse(tr.passes_publication_gate({
            "confidence": 0.95, "peer_sample_size": 5,
        }))

    def test_handles_none(self):
        self.assertFalse(tr.passes_publication_gate(None))

    def test_uses_schema_constants(self):
        self.assertTrue(tr.passes_publication_gate({
            "confidence": se_schema.MIN_CONFIDENCE_THRESHOLD,
            "peer_sample_size": se_schema.MIN_PEER_SAMPLE_SIZE,
        }))


# ──────────────────────────────────────────────────────────────────
# upsert_prediction + expire + active query
# ──────────────────────────────────────────────────────────────────


class _StubColl:
    def __init__(self):
        self.docs: list = []

    def find(self, query=None):
        outer = self
        items = list(outer.docs)
        if query:
            filtered = []
            for d in items:
                ok = True
                for k, v in query.items():
                    actual = d.get(k)
                    if isinstance(v, dict):
                        if "$gt" in v and not (actual is not None and actual > v["$gt"]):
                            ok = False; break
                        if "$lte" in v and not (actual is not None and actual <= v["$lte"]):
                            ok = False; break
                    elif actual != v:
                        ok = False; break
                if ok: filtered.append(d)
            items = filtered

        class _Cur:
            def __aiter__(_self):
                async def _gen():
                    for it in items: yield it
                return _gen()
        return _Cur()

    async def update_one(self, filter_, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update: d.update(update["$set"])
                r = MagicMock(); r.upserted_id = None
                return r
        new_doc = dict(filter_)
        if "$set" in update: new_doc.update(update["$set"])
        self.docs.append(new_doc)
        r = MagicMock(); r.upserted_id = "new"
        return r

    async def update_many(self, filter_, update):
        modified = 0
        for d in self.docs:
            ok = True
            for k, v in filter_.items():
                actual = d.get(k)
                if isinstance(v, dict):
                    if "$lte" in v and not (actual is not None and actual <= v["$lte"]):
                        ok = False; break
                elif actual != v:
                    ok = False; break
            if ok:
                if "$set" in update: d.update(update["$set"])
                modified += 1
        r = MagicMock(); r.modified_count = modified
        return r


class _StubDb:
    def __init__(self):
        self._cs = {}

    def __getitem__(self, name):
        if name not in self._cs:
            self._cs[name] = _StubColl()
        return self._cs[name]


class TestUpsertPrediction(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 5, 8, 14, 0, tzinfo=timezone.utc)
        self.project = {"_id": "P1", "company_id": "co_a"}
        self.passing = {
            "trigger_kind": "311_at_bin",
            "confidence": 0.78,
            "peer_sample_size": 42,
            "historical_match_rate": 0.78,
            "days_window_min": 1,
            "days_window_max": 14,
            "input_snapshot": {"recent_311_count": 1},
        }

    def test_persists_qualifying_prediction(self):
        db = _StubDb()
        out = _run(tr.upsert_prediction(
            db, project=self.project, prediction=self.passing,
            now=self.now,
        ))
        self.assertIsNotNone(out)
        self.assertEqual(
            len(db[se_schema.PREDICTED_EVENTS_COLLECTION].docs), 1,
        )

    def test_rejects_low_confidence(self):
        db = _StubDb()
        bad = dict(self.passing); bad["confidence"] = 0.65
        out = _run(tr.upsert_prediction(
            db, project=self.project, prediction=bad, now=self.now,
        ))
        self.assertIsNone(out)
        self.assertEqual(
            len(db[se_schema.PREDICTED_EVENTS_COLLECTION].docs), 0,
        )

    def test_rejects_small_sample(self):
        db = _StubDb()
        bad = dict(self.passing); bad["peer_sample_size"] = 5
        out = _run(tr.upsert_prediction(
            db, project=self.project, prediction=bad, now=self.now,
        ))
        self.assertIsNone(out)

    def test_idempotent_same_day(self):
        db = _StubDb()
        for _ in range(3):
            _run(tr.upsert_prediction(
                db, project=self.project, prediction=self.passing,
                now=self.now,
            ))
        self.assertEqual(
            len(db[se_schema.PREDICTED_EVENTS_COLLECTION].docs), 1,
        )

    def test_expires_at_set_from_window_max(self):
        db = _StubDb()
        out = _run(tr.upsert_prediction(
            db, project=self.project, prediction=self.passing,
            now=self.now,
        ))
        delta = out["expires_at"] - self.now
        self.assertGreaterEqual(delta.days, 13)
        self.assertLessEqual(delta.days, 14)


class TestExpireStalePredictions(unittest.TestCase):

    def test_flips_status_only_when_expired(self):
        db = _StubDb()
        now = datetime(2026, 5, 8, 14, 0, tzinfo=timezone.utc)
        db[se_schema.PREDICTED_EVENTS_COLLECTION].docs = [
            {
                "project_id": "P1", "trigger_kind": "311_at_bin",
                "expires_at": now - timedelta(days=1),
                "outcome_status": "active",
            },
            {
                "project_id": "P1", "trigger_kind": "311_at_bin",
                "expires_at": now + timedelta(days=5),
                "outcome_status": "active",
            },
        ]
        n = _run(tr.expire_stale_predictions(db, now=now))
        self.assertEqual(n, 1)
        statuses = [
            d["outcome_status"]
            for d in db[se_schema.PREDICTED_EVENTS_COLLECTION].docs
        ]
        self.assertIn("expired", statuses)
        self.assertIn("active", statuses)


class TestActivePredictionsQuery(unittest.TestCase):

    def test_returns_only_active_unexpired(self):
        db = _StubDb()
        now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        db[se_schema.PREDICTED_EVENTS_COLLECTION].docs = [
            {"project_id": "P1", "expires_at": now + timedelta(days=5),
             "outcome_status": "active"},
            {"project_id": "P1", "expires_at": now - timedelta(days=1),
             "outcome_status": "active"},
            {"project_id": "P1", "expires_at": now + timedelta(days=10),
             "outcome_status": "expired"},
        ]
        out = _run(tr.active_predictions_for_project(db, "P1", now=now))
        self.assertEqual(len(out), 1)


# ──────────────────────────────────────────────────────────────────
# gather_trigger_inputs (lazy Socrata)
# ──────────────────────────────────────────────────────────────────


class TestGatherTriggerInputs(unittest.TestCase):
    """Each of the 5 Socrata fetches inside gather_trigger_inputs
    produces the expected output shape from seeded rows."""

    def _project(self):
        return {
            "_id": "P1",
            "nyc_bin": "1234567",
            "bbl": "1001234567",
            "borough": "MANHATTAN",
        }

    def test_311_at_bin_hits_complaints_dataset(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [
            {"record_id": "311_a", "bin": "1234567",
             "bbl": "1001234567",
             "created_date": (now - timedelta(hours=2)).strftime(
                 "%Y-%m-%dT%H:%M:%S")},
        ])
        out = _run(tr.gather_trigger_inputs(
            socrata, self._project(), now=now,
        ))
        self.assertEqual(len(out["recent_311_at_bin"]), 1)
        self.assertEqual(out["borough_inspection_counts_90d"], [])

    def test_311_neighbor_filters_by_block_prefix_via_socrata(self):
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [
            {"record_id": "311_b", "bin": "1234567",
             "bbl": "1001234567",
             "created_date": (now - timedelta(hours=3)).strftime(
                 "%Y-%m-%dT%H:%M:%S")},
            {"record_id": "311_c", "bin": "9999999",
             "bbl": "1001234568",
             "created_date": (now - timedelta(hours=4)).strftime(
                 "%Y-%m-%dT%H:%M:%S")},
        ])
        out = _run(tr.gather_trigger_inputs(
            socrata, self._project(), now=now,
        ))
        # Only the neighbor BIN survives.
        self.assertEqual(len(out["recent_311_neighbor"]), 1)
        self.assertEqual(
            out["recent_311_neighbor"][0]["record_id"], "311_c",
        )

    def test_borough_inspections_aggregated_into_per_day_counts(self):
        """Schema-corrections hotfix: inspections (p937-wjvj) ships
        a numeric ``boro_code`` (1-5). The borough-sweep query
        filters on that, not the mixed-case ``borough`` text
        column."""
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_INSPECTIONS, [
            {"boro_code": "1", "inspection_date":
                (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")},
            {"boro_code": "1", "inspection_date":
                (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")},
            {"boro_code": "1", "inspection_date":
                (now - timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%S")},
        ])
        out = _run(tr.gather_trigger_inputs(
            socrata, self._project(), now=now,
        ))
        self.assertEqual(sum(out["borough_inspection_counts_90d"]), 3)
        self.assertEqual(out["last_7d_count"], 2)

    def test_neighbor_swo_and_nearby_violations_counted(self):
        """Schema-corrections hotfix: dob_violations (3h2n-5cm9)
        has NO ``bbl`` column; block-proximity goes through
        ``boro`` + ``block`` instead. ``issue_date`` is a
        ``YYYYMMDD`` text column, not ISO datetime. Project BBL
        ``1001234567`` decomposes to boro=1, block=``"123"``
        (BBL's middle 5 chars ``"00123"`` lstripped of leading
        zeros — matches the canonical NYC DOF block id format).
        """
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            # Same boro+block, different BIN, SWO description, last 30d.
            {"boro": "1", "block": "123", "bin": "1111111",
             "issue_date": (now - timedelta(days=10)).strftime("%Y%m%d"),
             "description": "STOP WORK ORDER issued"},
            # Same boro+block, different BIN, no SWO, last 60d.
            {"boro": "1", "block": "123", "bin": "2222222",
             "issue_date": (now - timedelta(days=40)).strftime("%Y%m%d"),
             "description": "Other"},
            # Same BIN as project — should be skipped.
            {"boro": "1", "block": "123", "bin": "1234567",
             "issue_date": (now - timedelta(days=20)).strftime("%Y%m%d"),
             "description": "Stop work"},
        ])
        out = _run(tr.gather_trigger_inputs(
            socrata, self._project(), now=now,
        ))
        self.assertEqual(out["nearby_violations_60d"], 2)
        self.assertEqual(out["neighbor_swo_count_30d"], 1)


# ──────────────────────────────────────────────────────────────────
# Orchestrator end-to-end
# ──────────────────────────────────────────────────────────────────


class TestRunTriggersOrchestrator(unittest.TestCase):

    def test_persists_qualifying_predictions(self):
        db = _StubDb()
        now = datetime(2026, 5, 8, tzinfo=timezone.utc)
        socrata = MockSocrataClient()
        socrata.seed(DATASET_COMPLAINTS_311, [
            {"record_id": "311_1", "bin": "1234567",
             "bbl": "1001234567",
             "created_date": (now - timedelta(hours=2)).strftime(
                 "%Y-%m-%dT%H:%M:%S")},
        ])
        socrata.seed(DATASET_DOB_INSPECTIONS, [])
        socrata.seed(DATASET_DOB_VIOLATIONS, [])
        project = {
            "_id": "P1", "company_id": "co_a",
            "nyc_bin": "1234567", "bbl": "1001234567",
            "borough": "MANHATTAN",
            "_peer_sample_size_for_test": 30,
        }
        out = _run(tr.run_triggers_for_project(
            db, project, socrata=socrata, now=now,
        ))
        self.assertGreaterEqual(len(out), 1)
        kinds = {p["trigger_kind"] for p in out}
        self.assertIn(tr.TRIGGER_311_AT_BIN, kinds)


# ──────────────────────────────────────────────────────────────────
# Package re-exports
# ──────────────────────────────────────────────────────────────────


class TestPackageReExports(unittest.TestCase):

    def test_triggers_api_reexported(self):
        from lib import statistical_engine as stat_engine
        for name in (
            "ALL_TRIGGER_KINDS", "TRIGGER_311_AT_BIN",
            "passes_publication_gate", "upsert_prediction",
            "active_predictions_for_project",
            "run_triggers_for_project",
        ):
            self.assertTrue(hasattr(stat_engine, name),
                            f"missing re-export: {name}")


# ──────────────────────────────────────────────────────────────────
# A2 trigger-input behavior pins (tests 7 + 8 of the A2 PR)
#
# B3 decision: recent_311_at_bin stays sourced from Socrata
# (preserves trigger calibration; mixing in DOB complaints from
# eabe-havv would change the signal's statistical correlate).
#
# B2 decision: open_violations_with_cure deferred. The cure-
# deadline trigger now returns an empty list regardless of
# upstream data (compliance_deadline field is too sparse on
# dob_logs and Socrata to be a reliable signal source).
#
# These tests call gather_trigger_inputs with the NEW A2
# signature (project_id + db kwargs). On main the function
# still has the old signature → tests fail with TypeError.
# After Stage 3 implementation, B3 + B2 behavior is pinned.
# ──────────────────────────────────────────────────────────────────


class TestA2TriggerInputContracts(unittest.TestCase):
    """Tests 7 + 8 of the A2 PR."""

    def _project(self):
        return {
            "_id": "test_project_X",
            "id": "test_project_X",
            "nyc_bin": "1234567",
            "bbl": "1001234567",
            "borough": "MANHATTAN",
        }

    def test_gather_trigger_inputs_recent_311_uses_socrata_not_mongo(self):
        """Test 7 — B3 Option 3 pin: recent_311_at_bin STAYS
        Socrata-sourced even after A2 adds project_id+db kwargs.

        Fixture: dob_logs contains a fresh complaint (DOB complaint
        with project's bbl, complaint_status=ACTIVE, within 24h).
        Socrata mock contains a DIFFERENT 311 complaint (same bbl,
        different record_id, within 24h).

        Assert: recent_311_at_bin contains only the SOCRATA
        complaint. The dob_logs complaint MUST NOT appear in the
        trigger input.

        Why this matters: trigger calibration (historical_match_rate
        in passes_publication_gate) was tuned against 311 complaints
        only. Mixing DOB complaints (eabe-havv) from dob_logs into
        the trigger would invalidate the calibration. B3 Option 3
        keeps the calibration intact by sourcing only Socrata
        erm2-nwe9.
        """
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td

        now = _dt(2026, 5, 13, tzinfo=_tz.utc)
        socrata = MockSocrataClient()

        # Socrata mock: 1 fresh 311 complaint at the project's bbl.
        socrata.seed(DATASET_COMPLAINTS_311, [
            {"record_id": "311_socrata_id",
             "bbl": "1001234567",
             "bin": "1234567",
             "created_date": (now - _td(hours=2)).strftime(
                 "%Y-%m-%dT%H:%M:%S")},
        ])

        # dob_logs (mocked stub_db): a fresh DOB complaint — this
        # MUST NOT leak into recent_311_at_bin.
        from tests.test_v2_3_baselines import _StubDb, _dob_log

        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                project_id="test_project_X",
                record_type="complaint",
                complaint_status="ACTIVE",
                complaint_date=(now - _td(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000"),
                raw_dob_id="dob_complaint_id",
            ),
        ])

        out = _run(tr.gather_trigger_inputs(
            socrata,
            self._project(),
            now=now,
            project_id="test_project_X",
            db=db,
        ))

        # Exactly one 311 complaint should appear — and it's
        # the SOCRATA one (record_id "311_socrata_id"), not the
        # dob_logs one (raw_dob_id "dob_complaint_id").
        recent_311 = out.get("recent_311_at_bin") or []
        self.assertEqual(
            len(recent_311), 1,
            "recent_311_at_bin should contain exactly 1 entry "
            "(the Socrata 311 complaint); dob_logs DOB complaints "
            "must not leak in per B3 Option 3",
        )
        # The single entry must be the Socrata one.
        actual_id = (
            recent_311[0].get("record_id")
            or recent_311[0].get("raw_dob_id")
            or recent_311[0].get("unique_key")
            or ""
        )
        self.assertEqual(
            actual_id, "311_socrata_id",
            f"recent_311_at_bin contains wrong source (got {actual_id!r}); "
            f"expected the Socrata 311 record, not the dob_logs DOB complaint",
        )

    def test_gather_trigger_inputs_open_violations_with_cure_deferred_returns_empty(self):
        """Test 8 — B2 deferral pin: open_violations_with_cure
        is ALWAYS an empty list, regardless of upstream content
        (dob_logs or Socrata).

        compliance_deadline (the field this trigger depends on)
        is sparsely populated — extracted via regex from
        free-form disposition text. Per the Stage 1 v3 deferral,
        this trigger stays empty in A2; the cure-deadline source
        upgrade is a follow-up PR.

        Fixture: seed BOTH Socrata violations (with a parseable
        cure_deadline in the future) AND dob_logs violations
        (with compliance_deadline set). The trigger input
        MUST be empty regardless.
        """
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td

        now = _dt(2026, 5, 13, tzinfo=_tz.utc)
        socrata = MockSocrataClient()

        # Socrata violations with cure_deadline in the future.
        socrata.seed(DATASET_DOB_VIOLATIONS, [
            {"bin": "1234567",
             "issue_date": (now - _td(days=10)).strftime("%Y%m%d"),
             "cure_deadline": (now + _td(days=7)).strftime("%Y-%m-%d"),
             "violation_number": "v_with_cure_socrata"},
        ])

        from tests.test_v2_3_baselines import _StubDb, _dob_log

        db = _StubDb()
        db.dob_logs.seed([
            _dob_log(
                project_id="test_project_X",
                record_type="violation",
                resolution_state="open",
                violation_date=(now - _td(days=10)).strftime("%Y%m%d"),
                compliance_deadline=(now + _td(days=7)).strftime("%Y-%m-%d"),
                raw_dob_id="v_with_cure_dob_logs",
            ),
        ])

        out = _run(tr.gather_trigger_inputs(
            socrata,
            self._project(),
            now=now,
            project_id="test_project_X",
            db=db,
        ))

        self.assertEqual(
            out.get("open_violations_with_cure"), [],
            "open_violations_with_cure must be [] regardless of "
            "upstream data per B2 deferral (cure-deadline source "
            "upgrade is a follow-up PR)",
        )


if __name__ == "__main__":
    unittest.main()
