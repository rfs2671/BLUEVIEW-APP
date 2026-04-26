"""Boundary tests for the v2 permit-renewal eligibility logic.

Covers the strategy resolution table from §1.1 of the plan and the
effective-expiry math from §3.1, with particular focus on the
boundaries that aren't obvious from reading the code:
  - sidewalk shed 90-day cap independent of insurance/license
  - BIS legacy filing_system → 31-day look-ahead branching
  - AWAITING_EXTENSION trigger window (5d before expiry, 48h after verify)
  - 1-year ceiling vs insurance limiting
  - Lapsed (already past)

The dispatcher and shadow-mode plumbing are covered separately in
test_eligibility_shadow.py.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import eligibility_v2  # noqa: E402
from lib.eligibility_v2 import (  # noqa: E402
    compute_effective_permit_expiry,
    auto_extension_lookahead_days,
    resolve_renewal_strategy,
    severity_tier,
)


def _run(coro):
    return asyncio.run(coro)


def _permit(**kw):
    base = {
        "_id": "permit_test",
        "record_type": "permit",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "issuance_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "expiration_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "job_number": "B12345-I1",
        "work_type": "GC",
    }
    base.update(kw)
    return base


def _company(**kw):
    base = {
        "_id": "co_test",
        "name": "Acme",
        "gc_license_number": "626198",
        "gc_license_expiration": None,
        "gc_insurance_records": [],
    }
    base.update(kw)
    return base


def _ins(insurance_type, exp, **extra):
    rec = {"insurance_type": insurance_type, "expiration_date": exp}
    rec.update(extra)
    return rec


class TestEffectiveExpiry(unittest.TestCase):

    def test_shed_uses_90d_cap_regardless_of_insurance(self):
        """Sidewalk shed: effective_expiry = issuance + 90d ALWAYS,
        even if insurance/license expire later AND even if the
        permit's calendar expiration is much later."""
        permit = _permit(
            permit_class="sidewalk_shed",
            work_type="SH",
            issuance_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expiration_date=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        company = _company(
            gc_license_expiration=datetime(2030, 1, 1, tzinfo=timezone.utc),
            gc_insurance_records=[
                _ins("general_liability", datetime(2030, 6, 1, tzinfo=timezone.utc)),
            ],
        )
        date, label, kind = compute_effective_permit_expiry(permit, company)
        self.assertEqual(date, datetime(2026, 4, 1, tzinfo=timezone.utc))
        self.assertEqual(kind, "shed_cap")
        self.assertIn("90", label)

    def test_picks_earliest_insurance_when_binding(self):
        permit = _permit(
            issuance_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        company = _company(
            gc_license_expiration=datetime(2026, 12, 31, tzinfo=timezone.utc),
            gc_insurance_records=[
                _ins("general_liability", datetime(2026, 9, 1, tzinfo=timezone.utc)),
                _ins("workers_comp",      datetime(2026, 5, 30, tzinfo=timezone.utc)),
                _ins("disability",        datetime(2027, 1, 1, tzinfo=timezone.utc)),
            ],
        )
        date, label, kind = compute_effective_permit_expiry(permit, company)
        self.assertEqual(date, datetime(2026, 5, 30, tzinfo=timezone.utc))
        self.assertEqual(kind, "insurance")
        self.assertIn("Workers", label)

    def test_picks_annual_ceiling_when_binding(self):
        permit = _permit(
            issuance_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        company = _company(
            gc_license_expiration=datetime(2030, 1, 1, tzinfo=timezone.utc),
            gc_insurance_records=[
                _ins("general_liability", datetime(2027, 1, 1, tzinfo=timezone.utc)),
                _ins("workers_comp",      datetime(2028, 1, 1, tzinfo=timezone.utc)),
                _ins("disability",        datetime(2029, 1, 1, tzinfo=timezone.utc)),
            ],
        )
        date, label, kind = compute_effective_permit_expiry(permit, company)
        self.assertEqual(date, datetime(2026, 1, 1, tzinfo=timezone.utc))  # issuance + 365d
        self.assertEqual(kind, "annual_ceiling")

    def test_picks_license_when_binding(self):
        permit = _permit(
            issuance_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        company = _company(
            gc_license_expiration=datetime(2026, 3, 1, tzinfo=timezone.utc),
            gc_insurance_records=[
                _ins("general_liability", datetime(2027, 1, 1, tzinfo=timezone.utc)),
            ],
        )
        date, label, kind = compute_effective_permit_expiry(permit, company)
        self.assertEqual(date, datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(kind, "license")


class TestLookahead(unittest.TestCase):
    def test_dob_now_zero_lookahead(self):
        self.assertEqual(auto_extension_lookahead_days(_permit(filing_system="DOB_NOW")), 0)

    def test_bis_31d_lookahead(self):
        self.assertEqual(auto_extension_lookahead_days(_permit(filing_system="BIS")), 31)


class TestResolveStrategy(unittest.TestCase):
    today = datetime(2026, 4, 26, tzinfo=timezone.utc)

    def test_shed_always_manual_90d(self):
        permit = _permit(permit_class="sidewalk_shed")
        s = resolve_renewal_strategy(
            permit, _company(), self.today,
            effective_expiry=datetime(2026, 7, 1, tzinfo=timezone.utc),
            limiting_kind="shed_cap",
        )
        self.assertEqual(s, "MANUAL_90D_SHED")

    def test_lapsed_when_effective_in_past(self):
        s = resolve_renewal_strategy(
            _permit(), _company(), self.today,
            effective_expiry=datetime(2026, 4, 1, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertEqual(s, "MANUAL_LAPSED")

    def test_annual_ceiling_routes_to_manual(self):
        s = resolve_renewal_strategy(
            _permit(), _company(), self.today,
            effective_expiry=datetime(2026, 5, 1, tzinfo=timezone.utc),
            limiting_kind="annual_ceiling",
        )
        self.assertEqual(s, "MANUAL_1YR_CEILING")

    def test_dob_now_default(self):
        s = resolve_renewal_strategy(
            _permit(filing_system="DOB_NOW"), _company(), self.today,
            effective_expiry=datetime(2026, 7, 1, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertEqual(s, "AUTO_EXTEND_DOB_NOW")

    def test_bis_routes_to_bis_track(self):
        s = resolve_renewal_strategy(
            _permit(filing_system="BIS"), _company(), self.today,
            effective_expiry=datetime(2026, 7, 1, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertEqual(s, "AUTO_EXTEND_BIS_31D")


class TestAwaitingExtension(unittest.TestCase):
    """The 48hr Socrata-lag carve-out. Hard to get right; pin every
    relevant boundary so a future refactor doesn't silently break it."""
    today = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)

    def _company_with_recent_verify(
        self, *, ins_exp, verified_at,
    ):
        return _company(
            gc_insurance_records=[
                _ins(
                    "workers_comp",
                    ins_exp,
                    dob_now_verified_at=verified_at,
                ),
            ],
        )

    def test_fires_when_verified_within_48h_and_5d_before_expiry(self):
        # WC expires 2026-04-28; verified 2026-04-25 (3 days before
        # expiry, well within the 5d window); we are checking 2026-04-26
        # which is < verified + 48h. Should fire AWAITING_EXTENSION.
        company = self._company_with_recent_verify(
            ins_exp=datetime(2026, 4, 28, tzinfo=timezone.utc),
            verified_at=datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc),
        )
        s = resolve_renewal_strategy(
            _permit(), company, self.today,
            effective_expiry=datetime(2026, 4, 28, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertEqual(s, "AWAITING_EXTENSION")

    def test_does_not_fire_when_verified_too_long_ago(self):
        # Verified 3 days ago (>48h): Socrata should have caught up.
        company = self._company_with_recent_verify(
            ins_exp=datetime(2026, 4, 28, tzinfo=timezone.utc),
            verified_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )
        s = resolve_renewal_strategy(
            _permit(), company, self.today,
            effective_expiry=datetime(2026, 4, 28, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertNotEqual(s, "AWAITING_EXTENSION")

    def test_does_not_fire_when_verify_not_near_expiry(self):
        # Verified well before the 5d window (e.g. routine 7d cron).
        company = self._company_with_recent_verify(
            ins_exp=datetime(2026, 7, 1, tzinfo=timezone.utc),
            verified_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        )
        s = resolve_renewal_strategy(
            _permit(), company, self.today,
            effective_expiry=datetime(2026, 7, 1, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertNotEqual(s, "AWAITING_EXTENSION")

    def test_does_not_fire_when_no_verify_timestamp(self):
        company = _company(
            gc_insurance_records=[
                _ins("workers_comp", datetime(2026, 4, 28, tzinfo=timezone.utc)),
            ],
        )
        s = resolve_renewal_strategy(
            _permit(), company, self.today,
            effective_expiry=datetime(2026, 4, 28, tzinfo=timezone.utc),
            limiting_kind="insurance",
        )
        self.assertNotEqual(s, "AWAITING_EXTENSION")


class TestSeverityTier(unittest.TestCase):
    """The 4-step scale. Tier 1 is the v2-only AWAITING_EXTENSION
    case that must NOT collide with legacy tier 0 in the comparator."""

    def test_tier_0_eligible_no_warnings(self):
        r = {"renewal_strategy": "AUTO_EXTEND_DOB_NOW", "blocking_reasons": []}
        self.assertEqual(severity_tier(r), 0)

    def test_tier_1_awaiting_extension(self):
        r = {"renewal_strategy": "AWAITING_EXTENSION", "blocking_reasons": []}
        self.assertEqual(severity_tier(r), 1)

    def test_tier_2_insurance_not_entered(self):
        r = {
            "renewal_strategy": "AUTO_EXTEND_DOB_NOW",
            "insurance_not_entered": True,
            "blocking_reasons": [],
        }
        self.assertEqual(severity_tier(r), 2)

    def test_tier_3_manual_lapsed(self):
        r = {"renewal_strategy": "MANUAL_LAPSED", "blocking_reasons": []}
        self.assertEqual(severity_tier(r), 3)

    def test_tier_3_manual_shed(self):
        r = {"renewal_strategy": "MANUAL_90D_SHED", "blocking_reasons": []}
        self.assertEqual(severity_tier(r), 3)

    def test_tier_3_manual_1yr(self):
        r = {"renewal_strategy": "MANUAL_1YR_CEILING", "blocking_reasons": []}
        self.assertEqual(severity_tier(r), 3)

    def test_tier_3_blocking_reasons(self):
        r = {"renewal_strategy": "AUTO_EXTEND_DOB_NOW", "blocking_reasons": ["lapsed"]}
        self.assertEqual(severity_tier(r), 3)


class TestEvaluateEndToEnd(unittest.TestCase):

    def test_evaluate_returns_full_shape(self):
        # Insurance must bind (expire BEFORE the issuance+365d ceiling
        # AND before license expiry) so the strategy is AUTO_EXTEND_DOB_NOW,
        # not MANUAL_1YR_CEILING. Issuance 2026-01-01 → ceiling 2027-01-01;
        # insurance set to 2026-09-01 wins as the limiting factor.
        permit = _permit(
            issuance_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        project = {"_id": "p1"}
        company = _company(
            gc_license_expiration=datetime(2028, 1, 1, tzinfo=timezone.utc),
            gc_insurance_records=[
                _ins("general_liability", datetime(2026, 9, 1, tzinfo=timezone.utc)),
                _ins("workers_comp",      datetime(2026, 10, 1, tzinfo=timezone.utc)),
                _ins("disability",        datetime(2026, 11, 1, tzinfo=timezone.utc)),
            ],
        )

        class _StubDb:
            class fee_schedule:
                @staticmethod
                def find(_q):
                    class _Cursor:
                        async def to_list(self, _n):
                            return [{
                                "effective_from": datetime(2025, 12, 21, tzinfo=timezone.utc),
                                "effective_until": None,
                                "applies_to": ["ALL"],
                                "min_renewal_fee_cents": 13_000,
                                "split_rules": {"all": {"at_filing_pct": 100}},
                            }]
                    return _Cursor()

        from lib.fee_schedule import bust_fee_cache
        bust_fee_cache()

        result = _run(eligibility_v2.evaluate(
            _StubDb(), permit, project, company,
            today=datetime(2026, 4, 26, tzinfo=timezone.utc),
        ))

        self.assertEqual(result["permit_id"], "permit_test")
        self.assertEqual(result["renewal_strategy"], "AUTO_EXTEND_DOB_NOW")
        self.assertEqual(result["filing_system"], "DOB_NOW")
        self.assertEqual(result["permit_class"], "standard")
        self.assertEqual(result["limiting_factor"]["kind"], "insurance")
        self.assertIn("Liability", result["limiting_factor"]["label"])
        self.assertIsNotNone(result["effective_expiry"])
        self.assertEqual(result["action"]["fee_cents"], 0)


if __name__ == "__main__":
    unittest.main()
