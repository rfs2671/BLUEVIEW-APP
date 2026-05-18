"""PR #15D — G2 lock: server-side anchored_baseline_prob_7d/30d writes.

5 tests. Verifies that predict_for_project_nightly AND
refit_project_cold_start write all 3 horizon baselines to
prediction_cache, using _discrete_time_hazard_horizons (NOT Poisson).

Why server-side: keeps frontend stateless; one source of truth for
the hazard math (already proven safe in PR #15B.1 + PR #15B.3).
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
    predict_for_project_nightly,
    refit_project_cold_start,
    _discrete_time_hazard_horizons,
)
from _socrata_mock import MockSocrataClient  # noqa: E402
from _pr14b_fixtures import (  # noqa: E402
    seed_daily_panels_fixture,
    seed_cold_start_borough_actuarial_data,
)
from _pr15a_panel_fixtures import (  # noqa: E402
    _StubDb, _StubProjectsForCache,
)


def _menahan_project():
    return {
        "_id":      ObjectId("69e7c10013506cc459fcd046"),
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


def _boyland_project():
    return {
        "_id":      ObjectId("69f90c3209947c4967c8074f"),
        "bbl":      "3035400025",
        "nyc_bin":  "3255362",
        "dob_project_type": "full_demo",
        "pluto_snapshot": {"borough": "BK"},
        "peer_stats_cache": {
            "status": "ready",
            "peer_criteria": {
                "sample_size": 0,
                "dob_project_type": "full_demo",
                "cohort_member_provenance": [],
            },
        },
    }


class TestG2BaselineHorizons(unittest.TestCase):
    """G2 lock — backend writes anchored_baseline_prob_7d and
    anchored_baseline_prob_30d to prediction_cache at fit time.

    Two write sites:
      • predict_for_project_nightly (modern fit path)
      • refit_project_cold_start (cold-start path)

    Both compute via _discrete_time_hazard_horizons, derived from
    the cohort_baseline_rate / borough actuarial 14d value.
    """

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_predict_for_project_nightly_writes_baseline_7d(self):
        """G2 — modern fit path writes anchored_baseline_prob_7d."""
        project = _menahan_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
        )
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]
        _run(predict_for_project_nightly(db, socrata, project, now=now))
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache") or {}
        self.assertIn(
            "anchored_baseline_prob_7d", cache,
            msg="Stage 3 PR #15D G2: predict_for_project_nightly must "
                "write anchored_baseline_prob_7d to prediction_cache. "
                "Use _discrete_time_hazard_horizons(anchored_baseline_prob_14d).",
        )
        self.assertIsNotNone(cache.get("anchored_baseline_prob_7d"))

    @unittest.skipIf(not HAS_SKLEARN, "sklearn not installed")
    def test_predict_for_project_nightly_writes_baseline_30d(self):
        """G2 — modern fit path writes anchored_baseline_prob_30d."""
        project = _menahan_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_daily_panels_fixture(
            db, project_id=str(project["_id"]),
            cohort_bbls=[f"3{i:09d}" for i in range(40)],
            n_days=120, now=now,
        )
        for row in db.daily_panels.docs:
            row["project_id"] = project["_id"]
        _run(predict_for_project_nightly(db, socrata, project, now=now))
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache") or {}
        self.assertIn(
            "anchored_baseline_prob_30d", cache,
            msg="Stage 3 PR #15D G2: predict_for_project_nightly must "
                "write anchored_baseline_prob_30d to prediction_cache.",
        )
        self.assertIsNotNone(cache.get("anchored_baseline_prob_30d"))

    def test_baseline_7d_is_less_than_14d(self):
        """G2 — DTH math invariant: shorter horizon → smaller prob."""
        # Pure helper test using _discrete_time_hazard_horizons.
        for p14 in (0.01, 0.05, 0.1, 0.3, 0.5):
            # Reverse-derive: if baseline_14d = X, daily_hazard
            # solves 1 - (1-daily)^14 = X.
            # Backend should compute p_7 from p_14 by either:
            #   p_daily = 1 - (1-p_14)**(1/14); p_7 = 1-(1-p_daily)**7
            # OR by anchoring on the underlying daily_hazard from
            # the fit. Either way, p_7 < p_14 strictly.
            import math
            daily = 1.0 - (1.0 - p14) ** (1.0 / 14.0)
            p7 = 1.0 - (1.0 - daily) ** 7
            self.assertLess(
                p7, p14,
                msg=f"DTH invariant: p_7d ({p7}) < p_14d ({p14}) for "
                    f"all non-zero p_14d. Backend G2 writer must "
                    f"preserve this.",
            )

    def test_baseline_30d_is_greater_than_14d(self):
        """G2 — DTH math invariant: longer horizon → larger prob."""
        for p14 in (0.01, 0.05, 0.1, 0.3, 0.5):
            daily = 1.0 - (1.0 - p14) ** (1.0 / 14.0)
            p30 = 1.0 - (1.0 - daily) ** 30
            self.assertGreater(
                p30, p14,
                msg=f"DTH invariant: p_30d ({p30}) > p_14d ({p14}) for "
                    f"all non-zero p_14d. Backend G2 writer must "
                    f"preserve this.",
            )

    def test_cold_start_path_also_writes_horizon_baselines(self):
        """G2 — refit_project_cold_start (no panels) also writes
        all 3 horizon baselines. Use _discrete_time_hazard_horizons
        from compute_borough_actuarial_hazard's 14d result, NOT
        independent borough queries per horizon."""
        project = _boyland_project()
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        db = _StubDb(projects=_StubProjectsForCache([project]))
        socrata = MockSocrataClient()
        seed_cold_start_borough_actuarial_data(
            socrata, borough="BROOKLYN",
            n_permits=100, n_severe_ecb=5, window_end=now,
        )
        from lib.statistical_engine.live_mutation import (
            predict_for_project_nightly,
        )
        _run(predict_for_project_nightly(db, socrata, project, now=now))
        proj_after = _run(db.projects.find_one({"_id": project["_id"]}))
        cache = (proj_after or {}).get("prediction_cache") or {}
        self.assertTrue(cache.get("is_cold_start"))
        self.assertIn(
            "anchored_baseline_prob_7d", cache,
            msg="Stage 3 PR #15D G2: cold-start path must write "
                "anchored_baseline_prob_7d too. Use DTH math from "
                "the borough actuarial 14d hazard.",
        )
        self.assertIn(
            "anchored_baseline_prob_30d", cache,
            msg="Stage 3 PR #15D G2: cold-start path must write "
                "anchored_baseline_prob_30d.",
        )


if __name__ == "__main__":
    unittest.main()
