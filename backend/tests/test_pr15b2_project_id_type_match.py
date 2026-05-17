"""PR #15B.2 — project_id type unification hotfix tests.

4 tests in TestProjectIdTypeMatch:
  1. test_fit_project_panel_finds_rows_when_panels_stored_as_objectid
  2. test_fit_project_panel_finds_rows_when_panels_stored_as_string
  3. test_inline_backstop_recognizes_objectid_keyed_panels
  4. test_compute_cohort_baseline_rate_finds_objectid_keyed_panels

Root cause (Stage 10 PR #15B.1 verification):
  • PR #15A writes daily_panels with project_id as ObjectId
    (compute_daily_panel uses project["_id"] directly).
  • PR #15B reads with project_id as str(project["_id"]).
  • All 3 read sites in live_mutation.py return 0 rows → fit returns
    None → falls to cold-start for every project with provenance.

Production verification (Stage 10):
  • daily_panels Menahan by ObjectId: 45,900 rows
  • daily_panels Menahan by string:        0 rows
"""

from __future__ import annotations

import asyncio
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

from bson import ObjectId  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


from lib.statistical_engine.live_mutation import (  # noqa: E402
    fit_project_panel, predict_for_project_nightly,
)
from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import seed_daily_panels_fixture  # noqa: E402
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubProjectsForCache,
)


def _seed_panel_rows_with_pid(db, *, project_id, n_days=120, now=None):
    """Seed daily_panels but FORCE project_id type to the value
    passed (ObjectId or str). Mimics what compute_daily_panel does
    at production: project_id field stamped with project["_id"]
    directly (ObjectId), without stringification.
    """
    # Use the canonical seeder for row shape — it stamps a string
    # project_id by default. Then mutate the seeded rows in place.
    cur_now = now or datetime(2026, 5, 15, tzinfo=timezone.utc)
    seed_daily_panels_fixture(
        db, project_id=str(project_id),
        cohort_bbls=[f"3{i:09d}" for i in range(40)],
        n_days=n_days, now=cur_now,
    )
    # Overwrite the seeded string project_id with the requested
    # type. The test point is: does the production code's query
    # filter match THIS shape?
    for row in db.daily_panels.docs:
        row["project_id"] = project_id


def _make_project(oid_hex: str = "69e7c10013506cc459fcd046"):
    """Menahan-shape project for fit + backstop tests."""
    return {
        "_id":      ObjectId(oid_hex),
        "bbl":      "3033040024",
        "nyc_bin":  "3325703",
        "dob_project_type": "major_alt_with_enlargement",
        "pluto_snapshot": {"borough": "BK"},
        "peer_stats_cache": {
            "status": "ready",
            "peer_criteria": {
                "sample_size": 60,
                "dob_project_type": "major_alt_with_enlargement",
                "cohort_member_provenance": [
                    {"bbl": f"3{i:09d}"} for i in range(60)
                ],
            },
        },
    }


class TestProjectIdTypeMatch(unittest.TestCase):
    """B7 lock — fit_project_panel + backstop + cohort_baseline_rate
    must find daily_panels rows regardless of whether project_id is
    stored as ObjectId (PR #15A's actual production behavior) or
    str (PR #15B's assumption)."""

    # ── Test 1 — fit succeeds against ObjectId-keyed panels ──

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_fit_project_panel_finds_rows_when_panels_stored_as_objectid(self):
        """Stage 10 production reality: PR #15A writes ObjectId
        project_id in daily_panels. fit_project_panel must find
        these rows when called from predict_for_project_nightly."""
        project = _make_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        # Seed panels keyed by ObjectId (production reality)
        _seed_panel_rows_with_pid(
            db, project_id=ObjectId("69e7c10013506cc459fcd046"),
            n_days=120, now=now,
        )
        result = _run(fit_project_panel(db, project, now=now))
        self.assertIsNotNone(
            result,
            msg="Stage 3 PR #15B.2: fit_project_panel returned None "
                "for project with 45,900-row daily_panels (Menahan-"
                "shape). Root cause: filter uses pid_str but rows "
                "stored as ObjectId. Fix: use {'$in': [raw_pid, "
                "pid_str]} filter at live_mutation.py:953.",
        )
        self.assertIsNotNone(result.get("beta_coefficients"))
        self.assertGreater(result.get("training_n_observations", 0), 0)
        self.assertFalse(
            result.get("is_cold_start_fallback"),
            msg="Modern fit expected, not cold-start.",
        )

    # ── Test 2 — fit succeeds against string-keyed panels (regression) ──

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_fit_project_panel_finds_rows_when_panels_stored_as_string(self):
        """Backward-compat: if some other code path writes panels
        with str project_id (PR #15B test fixtures do this), the
        $in filter must STILL match. Pre-PR-#15B.2 behavior."""
        project = _make_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        # Seed panels keyed by string (PR #15B fixture convention)
        _seed_panel_rows_with_pid(
            db, project_id="69e7c10013506cc459fcd046",
            n_days=120, now=now,
        )
        result = _run(fit_project_panel(db, project, now=now))
        self.assertIsNotNone(
            result,
            msg="Regression guard: string-keyed panels must still "
                "match after the $in fix. Pre-PR-#15B.2 the fit was "
                "GREEN for this case (the bug was ObjectId-only).",
        )
        self.assertIsNotNone(result.get("beta_coefficients"))

    # ── Test 3 — backstop respects ObjectId-keyed panels ────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_inline_backstop_recognizes_objectid_keyed_panels(self):
        """The B1 inline backstop checks if daily_panels has rows
        for this project; if 0, it rebuilds inline. With ObjectId-
        keyed panels but pid_str count_documents filter, the
        backstop spuriously fires (and wastes Socrata budget on a
        rebuild that just appends more rows). After PR #15B.2 fix,
        backstop must NOT fire — existing ObjectId rows are seen.

        Assertion strategy: track daily_panels.docs count before +
        after. Backstop firing invokes compute_daily_panel which,
        with a bin-rich provenance, queries eabe-havv → emits rows.
        Backstop NOT firing leaves docs untouched.
        """
        # Override provenance to include `bin` fields so the backstop's
        # compute_daily_panel would actually query eabe-havv if it fired.
        project = _make_project()
        project["peer_stats_cache"]["peer_criteria"][
            "cohort_member_provenance"
        ] = [
            {"bbl": f"3{i:09d}", "bin": f"33{i:05d}"} for i in range(60)
        ]
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        _seed_panel_rows_with_pid(
            db, project_id=ObjectId("69e7c10013506cc459fcd046"),
            n_days=120, now=now,
        )
        rows_before = len(db.daily_panels.docs)
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception:
            pass  # OK — we only care whether backstop fired
        rows_after = len(db.daily_panels.docs)
        eabe_calls = [c for c in socrata.calls if c[0] == "eabe-havv"]
        # Two-pronged check: (1) eabe-havv NOT touched (backstop's
        # compute_daily_panel never ran) AND (2) daily_panels count
        # unchanged (backstop didn't append rebuilt rows).
        self.assertEqual(
            len(eabe_calls), 0,
            msg=f"Backstop spuriously fired: {len(eabe_calls)} eabe-havv "
                f"calls. ObjectId-keyed panels exist (45,900 rows in "
                f"production) but pid_str count_documents returned 0. "
                f"Stage 3 fix at live_mutation.py:1239 — use $in filter.",
        )
        self.assertEqual(
            rows_after, rows_before,
            msg=f"Backstop spuriously fired: daily_panels grew from "
                f"{rows_before} → {rows_after} rows. Should be a no-op "
                f"because the project already has 4,800 ObjectId-keyed "
                f"rows pre-call.",
        )

    # ── Test 4 — cohort baseline finds ObjectId panels ──────

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_compute_cohort_baseline_rate_finds_objectid_keyed_panels(self):
        """anchored_baseline_prob_14d should be non-zero when panels
        contain real outcome data. With ObjectId-keyed panels but
        pid_str find filter, compute_cohort_baseline_rate sees 0
        rows → returns 0.0. After Stage 3 fix at line 1308, $in
        filter matches → real rate returned."""
        project = _make_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        _seed_panel_rows_with_pid(
            db, project_id=ObjectId("69e7c10013506cc459fcd046"),
            n_days=120, now=now,
        )
        try:
            _run(predict_for_project_nightly(db, socrata, project, now=now))
        except Exception:
            pass
        # Read back prediction_cache
        proj_after = _run(db.projects.find_one(
            {"_id": project["_id"]}
        ))
        cache = (proj_after or {}).get("prediction_cache", {}) or {}
        # Primary assertion: modern fit path was taken (NOT cold-start).
        # If cohort_tier_utilized == "borough_baseline", the cold-start
        # fallback fired — which means fit_project_panel returned None
        # because of the project_id type mismatch.
        self.assertNotEqual(
            cache.get("cohort_tier_utilized"), "borough_baseline",
            msg=f"PR #15B.2: ObjectId-keyed panels yielded cold-start "
                f"fallback. Got cohort_tier_utilized="
                f"{cache.get('cohort_tier_utilized')!r}, "
                f"is_cold_start={cache.get('is_cold_start')!r}. "
                f"Stage 3 must wire $in filter at line 1308 so "
                f"compute_cohort_baseline_rate's find sees the "
                f"ObjectId-keyed rows.",
        )
        # Secondary: anchored_baseline_prob_14d > 0 (rows exist with
        # real outcomes; mean should be non-zero in expectation).
        # NOTE: synthetic seed_daily_panels_fixture uses a low-bias
        # logistic, so mean outcome is small. Assert > 0 (not zero).
        ab = cache.get("anchored_baseline_prob_14d")
        self.assertIsNotNone(
            ab,
            msg="prediction_cache.anchored_baseline_prob_14d missing",
        )
        self.assertGreater(
            ab, 0.0,
            msg=f"anchored_baseline_prob_14d expected > 0 after "
                f"PR #15B.2 fix. Got {ab}. Pre-fix: 0.0 because "
                f"compute_cohort_baseline_rate found 0 panel rows.",
        )


if __name__ == "__main__":
    unittest.main()
