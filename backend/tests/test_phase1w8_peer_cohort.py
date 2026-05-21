"""Phase 1 Week 8 PR-B — k-NN peer cohort matcher tests.

~18 tests across:

  Cascade layers:
    L1 full match returns 14 peers
    L1 under-14 falls to L2
    L2 under-14 falls to L3
    L3 always returns best available even if under 14
    L3 sorts by schedule_position distance then BIN

  Wildcard phase:
    "unknown" matches any phase at L1
    "unknown" matches any phase at L2
    phase_wildcard_expanded flag set when unknown used
    phase_wildcard_expanded flag false when strict match

  Violation bucket:
    recent_violation_bucket uses most-recent in 90d
    recent_violation_bucket null when no violations
    recent_violation_bucket excludes violations outside window

  Disclosure text:
    L1 no wildcard
    L1 with wildcard
    L2
    L3

  Edge cases:
    empty pool returns zero matches
    project with null work_type returns empty cohort
    _resolve_phase_enum_from_ratio clamps to nearest anchor
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


try:
    from lib.statistical_engine.peer_cohort import (
        compute_peer_cohort,
        _resolve_phase_enum_from_ratio,
        _phase_matches,
    )
    HAS_PEER_COHORT = True
except ImportError:
    compute_peer_cohort = None              # type: ignore
    _resolve_phase_enum_from_ratio = None   # type: ignore
    _phase_matches = None                   # type: ignore
    HAS_PEER_COHORT = False


# ─── In-memory stubs ──────────────────────────────────────────────


class _StubFindCollection:
    """Reused from test_pr15c. Supports find / find_one with the filter
    + sort + projection subset the peer_cohort module emits."""

    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def find(self, filter_=None, projection=None, sort=None):
        filter_ = filter_ or {}
        matched = [d for d in self.docs if _match_filter(d, filter_)]
        if sort:
            for field, direction in reversed(sort):
                matched.sort(
                    key=lambda d, f=field: d.get(f) or "",
                    reverse=(direction == -1),
                )
        return _AsyncCursor(matched)

    async def find_one(self, filter_=None, sort=None, projection=None):
        filter_ = filter_ or {}
        matched = [d for d in self.docs if _match_filter(d, filter_)]
        if not matched:
            return None
        if sort:
            for field, direction in reversed(sort):
                matched.sort(
                    key=lambda d, f=field: d.get(f) or "",
                    reverse=(direction == -1),
                )
        return matched[0]


class _AsyncCursor:
    def __init__(self, items):
        self._items = items

    def sort(self, field_or_list, direction=None):
        if direction is not None:
            sort = [(field_or_list, direction)]
        else:
            sort = field_or_list
        for field, d in reversed(sort):
            self._items.sort(
                key=lambda doc, f=field: doc.get(f) or "",
                reverse=(d == -1),
            )
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self._items)
        return list(self._items[:length])


def _match_filter(doc: Dict[str, Any], filter_: Dict[str, Any]) -> bool:
    """Mongo filter evaluator supporting the subset peer_cohort emits."""
    if "$or" in filter_:
        if not any(_match_filter(doc, sub) for sub in filter_["$or"]):
            return False
        filter_ = {k: v for k, v in filter_.items() if k != "$or"}
    for k, expected in filter_.items():
        actual = doc.get(k)
        if isinstance(expected, dict):
            for op, v in expected.items():
                if op == "$gte" and not (actual is not None and actual >= v):
                    return False
                elif op == "$lt" and not (actual is not None and actual < v):
                    return False
                elif op == "$in" and actual not in v:
                    return False
                elif op == "$nin" and actual in v:
                    return False
                elif op == "$ne" and actual == v:
                    return False
                elif op == "$exists" and v != (k in doc):
                    return False
        else:
            if actual != expected:
                return False
    return True


class _StubDb:
    def __init__(self):
        self.projects = _StubFindCollection()
        self.daily_logs = _StubFindCollection()
        self.socrata_ecb_violations_historical = _StubFindCollection()
        self.socrata_permits_historical = _StubFindCollection()
        self.prediction_models = _StubFindCollection()


def _seed_permit(bin_id, borough, work_type, issued_date):
    return {
        "bin": bin_id,
        "filing_reason": "Initial Permit",
        "issued_date": issued_date,
        "borough": borough,
        "work_type": work_type,
        "bbl": f"BBL_{bin_id}",
    }


def _seed_violation(bin_id, issue_date_yyyymmdd, *,
                    violation_type="Construction",
                    violation_description="Generic"):
    return {
        "bin": bin_id,
        "issue_date": issue_date_yyyymmdd,
        "violation_type": violation_type,
        "violation_description": violation_description,
    }


# ─── Test class ───────────────────────────────────────────────────


class TestPeerCohort(unittest.TestCase):
    """Phase 1 Week 8 PR-B — 18+ tests."""

    def _require(self):
        if not HAS_PEER_COHORT:
            self.fail(
                "lib.statistical_engine.peer_cohort not implemented. "
                "Phase 1 Week 8 PR-B: add compute_peer_cohort + helpers "
                "per Stage 2.A spec."
            )

    # ──────────────────────────────────────────────────────────
    # _resolve_phase_enum_from_ratio — unit
    # ──────────────────────────────────────────────────────────

    def test_helper_phase_enum_from_ratio_clamps_to_nearest_anchor(self):
        """Inverse of PHASE_TO_RATIO. 0.42 closer to superstructure
        (0.35; delta 0.07) than to interior (0.55; delta 0.13)."""
        self._require()
        self.assertEqual(
            _resolve_phase_enum_from_ratio(0.42), "superstructure",
        )
        # 0.60 closer to interior (0.55; delta 0.05) than mep (0.70; delta 0.10)
        self.assertEqual(
            _resolve_phase_enum_from_ratio(0.60), "interior",
        )
        # 1.4 is overrun; closest anchor is closeout (0.97; delta 0.43)
        self.assertEqual(
            _resolve_phase_enum_from_ratio(1.4), "closeout",
        )
        # None input → None
        self.assertIsNone(_resolve_phase_enum_from_ratio(None))

    # ──────────────────────────────────────────────────────────
    # _phase_matches — wildcard semantics
    # ──────────────────────────────────────────────────────────

    def test_phase_matches_strict_equal(self):
        """Two equal non-special values match."""
        self._require()
        self.assertTrue(_phase_matches("mep", "mep"))
        self.assertFalse(_phase_matches("mep", "foundation"))

    def test_phase_matches_unknown_wildcard(self):
        """'unknown' matches anything on either side per L4."""
        self._require()
        self.assertTrue(_phase_matches("unknown", "mep"))
        self.assertTrue(_phase_matches("mep", "unknown"))
        self.assertTrue(_phase_matches("unknown", "unknown"))

    def test_phase_matches_none_wildcard(self):
        """None matches anything (defensive)."""
        self._require()
        self.assertTrue(_phase_matches(None, "mep"))
        self.assertTrue(_phase_matches("mep", None))

    # ──────────────────────────────────────────────────────────
    # Cascade — Layer 1 full match
    # ──────────────────────────────────────────────────────────

    def test_l1_full_match_returns_14_peers(self):
        """When ≥14 BINs match all 4 dimensions, L1 fires and returns
        exactly 14 peers."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        project = {
            "_id": "P_ACTIVE", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.55},
        }

        # Seed 20 peer BINs all matching (BROOKLYN, GC) with
        # phase="unknown" (no daily_logs for them) and no recent
        # violations. Active project's bucket is null → L1 cascade
        # requires same bucket=null. Since peers have no violations,
        # their bucket is also null. Wildcard phase match on "unknown"
        # makes L1 succeed.
        db.socrata_permits_historical.docs = [
            _seed_permit(f"3{i:06d}", "BROOKLYN", "General Construction",
                         "2026-04-10T00:00:00.000")
            for i in range(20)
        ]
        # Active project's own permit so its work_type is discoverable
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )

        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 1)
        self.assertEqual(result["n_matches"], 14)
        self.assertEqual(len(result["peers"]), 14)

    def test_l1_under_14_falls_to_l2(self):
        """L1 with only 10 matches → cascade falls to L2. L2 broadens
        by dropping the violation_bucket constraint."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        # Active project with a specific violation bucket so L1's filter
        # requires same bucket.
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.55},
        }
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        # Active project's own ECB violation in window → defines bucket
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("3000000", "20260510",
                            violation_type="Construction",
                            violation_description="Crane operating without permit"),
        ]
        # Seed 5 peers WITH the same crane violation (matches L1)
        for i in range(5):
            bin_id = f"3{i+1:06d}"
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_type="Construction",
                                violation_description="Crane lift unsafe"),
            )
        # Seed 15 more peers WITHOUT violations (L1 won't match; L2 will)
        for i in range(15):
            bin_id = f"3{i+10:06d}"
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        # L1 gave 5 (below 14) → cascade to L2 which finds all 20.
        self.assertEqual(result["layer_used"], 2)
        self.assertEqual(result["n_matches"], 14)

    def test_l2_under_14_falls_to_l3(self):
        """L2 with <14 matches → cascade to L3. L3 drops phase, ranks
        by schedule_position_ratio distance."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        # Active project with phase=mep (from a daily_log).
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.70},
        }
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        # Only 3 peers with explicit phase=mep (L2 finds these via project
        # join; rest are unknown phase = wildcard). With 3 + many unknown,
        # L2 would actually meet 14 via wildcard expansion. To force L3,
        # seed peers in DIFFERENT borough (no L2 match) plus a few in same.
        # Actually simpler: L2 = (borough, work_type, phase). The active's
        # phase is "mep". Per L4 wildcard, peers with "unknown" phase match.
        # So if we seed lots of peers all in BROOKLYN/GC/unknown phase,
        # L2 succeeds via wildcard. To force L3, change peers' borough.

        # Pool of 20 peers in QUEENS (won't match BROOKLYN at any layer).
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"4{i:06d}", "QUEENS", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        # 5 peers in BROOKLYN/GC (these match L2 + L3 since wildcard phase).
        for i in range(5):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        # Active project's permit
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )

        # With wildcard phase, L2 (borough=BROOKLYN, work_type=GC,
        # phase=mep) → 5 peers (BROOKLYN BINs all have unknown phase = wildcard match).
        # 5 < 14 → cascade to L3.
        # L3 (borough=BROOKLYN, work_type=GC) → same 5 peers.
        # n_matches = 5; layer_used = 3.
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 3)
        self.assertEqual(result["n_matches"], 5)

    def test_l3_always_returns_best_available_even_if_under_14(self):
        """L3 is the terminal layer. If even L3 has <14, return what's
        available with honest 'Based on N closest matches'."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "MANHATTAN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        # Only 3 peers in MANHATTAN/GC; below 14 even at L3.
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "MANHATTAN", "General Construction",
                         "2026-04-15T00:00:00.000"),
            _seed_permit("1000001", "MANHATTAN", "General Construction",
                         "2026-04-10T00:00:00.000"),
            _seed_permit("1000002", "MANHATTAN", "General Construction",
                         "2026-04-11T00:00:00.000"),
            _seed_permit("1000003", "MANHATTAN", "General Construction",
                         "2026-04-12T00:00:00.000"),
        ]
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 3)
        self.assertLess(result["n_matches"], 14)
        self.assertEqual(result["n_matches"], 3)  # 3 peers + active excluded

    def test_l3_sorts_by_schedule_position_distance_then_bin(self):
        """L3 ranks candidates by |project.schedule_position - peer.schedule|
        ascending; tiebreak by BIN ascending."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "MANHATTAN",
            "prediction_cache": {
                "schedule_position_ratio": 0.50,
                # No cohort median, so peer schedule_position computed
                # via the project's cohort_median for parity.
            },
            "peer_stats_cache": {"peer_criteria": {
                "cohort_median_duration_days": 100.0,
            }},
        }
        # Seed 5 peers with permits that produce distinct elapsed-days,
        # mapped to schedule_position_ratio via the project's 100-day
        # denominator.
        # earliest_issued for bin_id X → elapsed = (now - issued).days
        # ratio = elapsed / 100 (clamped 0..1.5)
        # peer 1000010 issued 50 days ago → ratio 0.50 (distance 0.00)
        # peer 1000020 issued 30 days ago → ratio 0.30 (distance 0.20)
        # peer 1000030 issued 70 days ago → ratio 0.70 (distance 0.20) — tied
        # peer 1000040 issued 10 days ago → ratio 0.10 (distance 0.40)
        # peer 1000050 issued 90 days ago → ratio 0.90 (distance 0.40) — tied
        def _iso_days_ago(d):
            return (now - timedelta(days=d)).strftime("%Y-%m-%dT00:00:00.000")
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "MANHATTAN", "General Construction",
                         _iso_days_ago(50)),
            _seed_permit("1000010", "MANHATTAN", "General Construction",
                         _iso_days_ago(50)),
            _seed_permit("1000020", "MANHATTAN", "General Construction",
                         _iso_days_ago(30)),
            _seed_permit("1000030", "MANHATTAN", "General Construction",
                         _iso_days_ago(70)),
            _seed_permit("1000040", "MANHATTAN", "General Construction",
                         _iso_days_ago(10)),
            _seed_permit("1000050", "MANHATTAN", "General Construction",
                         _iso_days_ago(90)),
        ]
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 3)
        # Top peer is 1000010 (distance 0). Tiebreak between 1000020 and
        # 1000030 at distance 0.2: smaller BIN (1000020) wins.
        bins_order = [p["bin"] for p in result["peers"]]
        self.assertEqual(bins_order[0], "1000010",
                         msg=f"Closest peer must win; got {bins_order}")
        # 1000020 and 1000030 are tied at distance 0.2; 1000020 < 1000030.
        self.assertEqual(bins_order[1], "1000020")
        self.assertEqual(bins_order[2], "1000030")
        # 1000040 and 1000050 tied at 0.4; smaller wins.
        self.assertEqual(bins_order[3], "1000040")
        self.assertEqual(bins_order[4], "1000050")

    # ──────────────────────────────────────────────────────────
    # Wildcard phase
    # ──────────────────────────────────────────────────────────

    def test_phase_wildcard_expanded_flag_set_when_unknown_used(self):
        """If at least one peer matched via 'unknown' phase wildcard
        (not strict equality), the cohort_summary flag is True."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        # 20 peers, all with unknown phase (no daily_logs for them).
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        result = _run(compute_peer_cohort(db, project, now=now))
        # L1 succeeds via wildcard (project.phase=mep, peer.phase=unknown).
        self.assertTrue(
            result["cohort_summary"]["phase_wildcard_expanded"],
            msg="phase_wildcard_expanded must be True when peers' "
                "phase=unknown matched project's phase=mep via L4 wildcard",
        )

    def test_phase_wildcard_expanded_flag_false_when_strict_match(self):
        """If all matched peers had identical phase to the project,
        the wildcard flag is False (strict equality, no relaxation)."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)

        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        # Both project AND all 20 peers have phase=mep (everyone has a
        # daily_log).
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        # Seed 20 peer projects with phase=mep daily_logs.
        for i in range(20):
            pid = f"P_{i+1}"
            bin_id = f"3{i+1:06d}"
            db.projects.docs.append({
                "_id": pid, "nyc_bin": bin_id, "is_deleted": False,
            })
            db.daily_logs.docs.append({
                "project_id": pid, "date": "2026-05-15",
                "phase": "mep", "is_deleted": False,
            })
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        # Active project's daily_log + permit
        db.daily_logs.docs.append({
            "project_id": "P_A", "date": "2026-05-19",
            "phase": "mep", "is_deleted": False,
        })
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertFalse(
            result["cohort_summary"]["phase_wildcard_expanded"],
            msg="Strict phase equality (no unknowns in matched peers) "
                "must flip flag to False",
        )

    # ──────────────────────────────────────────────────────────
    # Violation bucket window
    # ──────────────────────────────────────────────────────────

    def test_recent_violation_bucket_uses_most_recent_in_90d(self):
        """Active project's recent_violation_bucket comes from the
        MOST-RECENT violation in the last 90 days, classified via
        classify_violation. Per L3 lock.

        To verify the bucket reaches the response, peers also need
        matching crane violations so L1 fires (cohort_summary.
        violation_bucket is only populated at L1 per Stage 2.A L8)."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        # Two violations in window — most recent should win.
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("3000000", "20260301",
                            violation_description="Egress blocked"),
            _seed_violation("3000000", "20260510",  # most recent
                            violation_description="Crane unsafe operation"),
        ]
        # 20 peers with matching crane violations so L1 fires + bucket
        # surfaces in cohort_summary
        for i in range(20):
            bin_id = f"3{i+1:06d}"
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_description="Crane unsafe operation"),
            )

        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 1)
        self.assertEqual(
            result["cohort_summary"]["violation_bucket"], "safety_hazards",
            msg="Most-recent violation (2026-05-10, 'crane unsafe') "
                "classifies as safety_hazards. Older 'egress' should be "
                "ignored.",
        )

    def test_recent_violation_bucket_null_when_no_violations(self):
        """Project with no ECB violations in 90d → bucket=null →
        L1 falls through (matches peers with bucket=null only, but
        most peers will also have bucket=null in this test setup)."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertIsNone(result["cohort_summary"]["violation_bucket"])

    def test_recent_violation_bucket_excludes_violations_outside_window(self):
        """Violation older than 90d must NOT contribute to recent
        bucket. 120-day-old violation → ignored → bucket=null."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        # 120 days ago = 2026-01-20 — well outside 90d window.
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("3000000", "20260120",
                            violation_description="Asbestos exposure"),
        ]
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertIsNone(
            result["cohort_summary"]["violation_bucket"],
            msg="120-day-old violation must NOT contribute. Window is 90d.",
        )

    # ──────────────────────────────────────────────────────────
    # Disclosure text tiering
    # ──────────────────────────────────────────────────────────

    def test_disclosure_text_l1_no_wildcard(self):
        """L1 + strict phase match → mentions phase + violation bucket."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        # Active + 20 peers all have phase=mep + crane violations
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("3000000", "20260510",
                            violation_description="Crane unsafe"),
        ]
        for i in range(20):
            pid = f"P_{i+1}"
            bin_id = f"3{i+1:06d}"
            db.projects.docs.append({
                "_id": pid, "nyc_bin": bin_id, "is_deleted": False,
            })
            db.daily_logs.docs.append({
                "project_id": pid, "date": "2026-05-15",
                "phase": "mep", "is_deleted": False,
            })
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_description="Crane unsafe"),
            )
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 1)
        text = result["disclosure_text"]
        # Borough title-cased + MEP acronym per casing hotfix.
        self.assertIn("Brooklyn", text)
        self.assertIn("General Construction", text)
        self.assertIn("MEP", text)
        self.assertIn("safety_hazards", text)

    def test_disclosure_text_l2(self):
        """L2 disclosure mentions phase but NOT violation bucket."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        # Same setup as l1_under_14 — fall to L2.
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        db.socrata_ecb_violations_historical.docs = [
            _seed_violation("3000000", "20260510",
                            violation_description="Crane unsafe"),
        ]
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 2)
        text = result["disclosure_text"]
        # Borough title-cased + MEP acronym per casing hotfix.
        self.assertIn("Brooklyn", text)
        self.assertIn("MEP", text)
        self.assertNotIn("safety_hazards", text)

    def test_disclosure_text_l3(self):
        """L3 disclosure mentions 'closest schedule position' phrasing."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
            "peer_stats_cache": {"peer_criteria": {
                "cohort_median_duration_days": 100.0,
            }},
        }
        # Project has phase=mep, 5 peers no phase data → all L1/L2 with
        # wildcard → meet 14? No, only 5 BROOKLYN peers (we set up 5).
        # 5 < 14 so cascade to L3. But wildcard at L2 means peers with
        # unknown phase already match. Test setup intent: 5 BROOKLYN/GC
        # + 0 QUEENS = no fall-through to L3 by phase. We need only 5
        # candidates total in the pool (matching borough+work_type) to
        # force L3 with under-14.
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
            _seed_permit("3000001", "BROOKLYN", "General Construction",
                         "2026-04-10T00:00:00.000"),
            _seed_permit("3000002", "BROOKLYN", "General Construction",
                         "2026-04-11T00:00:00.000"),
        ]
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["layer_used"], 3)
        text = result["disclosure_text"]
        self.assertIn("closest schedule position", text)

    # ──────────────────────────────────────────────────────────
    # Edge cases
    # ──────────────────────────────────────────────────────────

    def test_empty_pool_returns_zero_matches(self):
        """No peers in socrata_permits_historical → empty cohort,
        all three layers return 0."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        # Only the active project's permit exists; no peers.
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["n_matches"], 0)
        self.assertEqual(result["peers"], [])
        # Layer is 3 (terminal — exhausted cascade returns the deepest
        # layer's [empty] result).
        self.assertEqual(result["layer_used"], 3)

    def test_project_with_null_work_type_returns_empty_cohort(self):
        """If the active project has no Initial Permit → can't classify
        into a cohort → return empty result with explicit signalling."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        # No permits at all — project's work_type undefinable.
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertEqual(result["n_matches"], 0)

    # ──────────────────────────────────────────────────────────
    # Hotfix — disclosure_text casing (Phase 1 Week 8 PR-B hotfix)
    # Production storage is ALL-CAPS for borough (PLUTO convention)
    # and lowercase for phase enum. disclosure_text is pre-rendered
    # for direct FE insertion per Stage 2.A L8 — must be GC-readable
    # per PR #15D.1 C5 lock.
    # ──────────────────────────────────────────────────────────

    def _seed_full_cohort(self, db, *, project, n_peers=20,
                          peer_borough="BROOKLYN",
                          peer_work_type="General Construction"):
        """Helper: seed an L1-friendly cohort so disclosure_text renders
        with all the bells (borough + work_type + phase + bucket).

        Active + peers all get a recent crane violation so L1's
        recent_violation_bucket filter fires with bucket=safety_hazards
        rather than bucket=None (which would render the ugly 'with
        recent None violations' substring)."""
        # Active project permit + crane violation
        db.socrata_permits_historical.docs.append(
            _seed_permit(project["nyc_bin"], peer_borough,
                         peer_work_type, "2026-04-15T00:00:00.000")
        )
        db.socrata_ecb_violations_historical.docs.append(
            _seed_violation(project["nyc_bin"], "20260510",
                            violation_description="Crane unsafe operation"),
        )
        # 20 peers in same cohort with matching violations
        for i in range(n_peers):
            bin_id = f"3{i+1:06d}"
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, peer_borough,
                             peer_work_type, "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_description="Crane unsafe operation"),
            )

    def test_disclosure_text_borough_title_cased(self):
        """BROOKLYN storage → 'Brooklyn' in disclosure_text. Mirrors
        the existing frontend boroughLabel() convention so backend-
        pre-rendered prose matches frontend-rendered prose elsewhere."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        self._seed_full_cohort(db, project=project)
        result = _run(compute_peer_cohort(db, project, now=now))
        text = result["disclosure_text"]
        self.assertIn("Brooklyn", text,
                      msg=f"Borough must render as 'Brooklyn' "
                          f"(title-case) in disclosure. Got: {text!r}")
        self.assertNotIn(
            "BROOKLYN", text,
            msg=f"BROOKLYN (uppercase storage form) must NOT appear "
                f"in disclosure. Got: {text!r}",
        )

    def test_disclosure_text_staten_island_title_cased(self):
        """Multi-word borough — 'STATEN ISLAND' → 'Staten Island'.
        Both words capitalized per title-case rule."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "5000000", "borough": "STATEN ISLAND",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        self._seed_full_cohort(db, project=project,
                               peer_borough="STATEN ISLAND")
        result = _run(compute_peer_cohort(db, project, now=now))
        text = result["disclosure_text"]
        self.assertIn("Staten Island", text,
                      msg=f"Multi-word borough must render as "
                          f"'Staten Island' (title-case both words). "
                          f"Got: {text!r}")
        self.assertNotIn("STATEN ISLAND", text)

    def test_disclosure_text_mep_phase_uppercased(self):
        """The 'mep' phase enum (lowercase storage) renders as 'MEP'
        (acronym uppercase per PR #37 L7 lock). Other phase enums
        stay lowercase. Requires strict-match peers so the L1 phase-
        naming branch fires (the wildcard variant says 'phase data
        limited' and elides the phase name)."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        # Active + 20 peers with matching phase=mep + crane violations
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "mep", "is_deleted": False},
        ]
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        db.socrata_ecb_violations_historical.docs.append(
            _seed_violation("3000000", "20260510",
                            violation_description="Crane unsafe"),
        )
        for i in range(20):
            pid = f"P_{i+1}"
            bin_id = f"3{i+1:06d}"
            db.projects.docs.append({
                "_id": pid, "nyc_bin": bin_id, "is_deleted": False,
            })
            db.daily_logs.docs.append({
                "project_id": pid, "date": "2026-05-15",
                "phase": "mep", "is_deleted": False,
            })
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_description="Crane unsafe"),
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        text = result["disclosure_text"]
        self.assertIn(
            "MEP", text,
            msg=f"phase=mep must render as 'MEP' (acronym uppercase). "
                f"Got: {text!r}",
        )

    def test_phase_wildcard_flag_when_both_phases_unknown(self):
        """Phase 1 Week 8 PR-B hotfix — when project.phase = 'unknown'
        AND peer.phase = 'unknown' (both sides — Menahan's actual case
        in production), the wildcard tracker must still set
        phase_wildcard_expanded = True. The L4 wildcard clause fires
        because both sides are 'unknown'; the prior tracker missed this
        because `phase != entry['phase']` is False when both equal
        'unknown' → wildcard_used stayed False."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.5},
        }
        # No daily_log for active → project.phase resolves to "unknown".
        # Peers have no daily_logs either → peer.phase = "unknown" default.
        # 20 peers in same borough/work_type, no violations → L1 fires
        # with project bucket=None and peer bucket=None.
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        for i in range(20):
            db.socrata_permits_historical.docs.append(
                _seed_permit(f"3{i+1:06d}", "BROOKLYN",
                             "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        # Either L1 or L2 should fire; either way, wildcard expanded
        # because BOTH sides are the 'unknown' sentinel.
        self.assertTrue(
            result["cohort_summary"]["phase_wildcard_expanded"],
            msg=(
                "Both project.phase='unknown' AND peer.phase='unknown' "
                "is a wildcard match per L4 (cannot meaningfully say "
                "they 'strictly match' on phase). Flag must be True. "
                f"Got: {result['cohort_summary']!r}"
            ),
        )

    def test_phase_wildcard_flag_when_project_phase_unknown_peer_specific(self):
        """When project.phase = 'unknown' but peer.phase is a specific
        enum ('mep'), L4 wildcard fires via the 'unknown'-clause.
        Tracker must record this even though the OTHER side (peer) has
        a real phase value."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.7},
        }
        # No daily_log for active → project.phase = "unknown".
        db.socrata_permits_historical.docs = [
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000"),
        ]
        # 20 peers WITH phase=mep daily_logs → peer.phase = "mep"
        for i in range(20):
            pid = f"P_{i+1}"
            bin_id = f"3{i+1:06d}"
            db.projects.docs.append({
                "_id": pid, "nyc_bin": bin_id, "is_deleted": False,
            })
            db.daily_logs.docs.append({
                "project_id": pid, "date": "2026-05-15",
                "phase": "mep", "is_deleted": False,
            })
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        self.assertTrue(
            result["cohort_summary"]["phase_wildcard_expanded"],
            msg=(
                "project.phase='unknown' + peer.phase='mep' matches via "
                "L4 wildcard ('unknown' clause). Flag must be True. "
                f"Got: {result['cohort_summary']!r}"
            ),
        )

    def test_disclosure_text_foundation_phase_lowercased(self):
        """Non-acronym phase enums stay lowercase ('foundation',
        'superstructure', etc.). Only MEP gets the special-case
        uppercase treatment. Same strict-match cohort setup as the
        MEP test so the phase-naming L1 branch fires."""
        self._require()
        db = _StubDb()
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        project = {
            "_id": "P_A", "nyc_bin": "3000000", "borough": "BROOKLYN",
            "prediction_cache": {"schedule_position_ratio": 0.1},
        }
        db.projects.docs = [
            {"_id": "P_A", "nyc_bin": "3000000", "is_deleted": False},
        ]
        db.daily_logs.docs = [
            {"project_id": "P_A", "date": "2026-05-19",
             "phase": "foundation", "is_deleted": False},
        ]
        db.socrata_permits_historical.docs.append(
            _seed_permit("3000000", "BROOKLYN", "General Construction",
                         "2026-04-15T00:00:00.000")
        )
        db.socrata_ecb_violations_historical.docs.append(
            _seed_violation("3000000", "20260510",
                            violation_description="Crane unsafe"),
        )
        for i in range(20):
            pid = f"P_{i+1}"
            bin_id = f"3{i+1:06d}"
            db.projects.docs.append({
                "_id": pid, "nyc_bin": bin_id, "is_deleted": False,
            })
            db.daily_logs.docs.append({
                "project_id": pid, "date": "2026-05-15",
                "phase": "foundation", "is_deleted": False,
            })
            db.socrata_permits_historical.docs.append(
                _seed_permit(bin_id, "BROOKLYN", "General Construction",
                             "2026-04-10T00:00:00.000")
            )
            db.socrata_ecb_violations_historical.docs.append(
                _seed_violation(bin_id, "20260512",
                                violation_description="Crane unsafe"),
            )
        result = _run(compute_peer_cohort(db, project, now=now))
        text = result["disclosure_text"]
        self.assertIn(
            "foundation", text,
            msg=f"phase=foundation must render as 'foundation' "
                f"(lowercase, NOT 'Foundation'). Got: {text!r}",
        )
        self.assertNotIn(
            "Foundation", text,
            msg=f"Non-acronym phases must stay lowercase. 'Foundation' "
                f"(title-cased) must NOT appear. Got: {text!r}",
        )


if __name__ == "__main__":
    unittest.main()
