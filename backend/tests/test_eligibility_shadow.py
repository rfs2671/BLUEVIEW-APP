"""Tests for the shadow-mode diff classifier.

Cat 1 (identity), Cat 2 (expected), Cat 3 (severity), Cat 5 (crash)
each have a representative test. Cat 4 (performance) is just latency
recording — covered implicitly in the integration test.

Specific guard: legacy 0 → v2 1 with strategy AWAITING_EXTENSION must
NOT fire as a Cat 3 escalation. That's the carve-out from the step-5
contract refinement and the most likely shape of bug if a future
refactor breaks the comparator.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import eligibility_shadow  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _permit(**kw):
    base = {
        "_id": "permit_test",
        "record_type": "permit",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "issuance_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "expiration_date": datetime(2027, 1, 1, tzinfo=timezone.utc),
        "job_number": "B12345-I1",
    }
    base.update(kw)
    return base


def _legacy_result_eligible(**kw):
    base = {
        "permit_id": "permit_test",
        "project_id": "p1",
        "expiration_date": "2027-01-01T00:00:00+00:00",
        "blocking_reasons": [],
        "insurance_flags": [],
        "insurance_not_entered": False,
        "gc_license": {"license_number": "626198"},
        "issuance_date": "2026-01-01T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _v2_result(**kw):
    base = {
        "permit_id": "permit_test",
        "project_id": "p1",
        "filing_system": "DOB_NOW",
        "permit_class": "standard",
        "renewal_strategy": "AUTO_EXTEND_DOB_NOW",
        "calendar_expiry": "2027-01-01T00:00:00+00:00",
        "effective_expiry": "2026-09-01T00:00:00+00:00",
        "limiting_factor": {
            "label": "General Liability",
            "kind": "insurance",
            "expires_in_days": 128,
        },
        "action": {"kind": "monitor", "fee_cents": 0},
        "blocking_reasons": [],
        "insurance_not_entered": False,
        "issuance_date": "2026-01-01T00:00:00+00:00",
        "permittee_license_number": "626198",
    }
    base.update(kw)
    return base


class TestRunOne(unittest.TestCase):
    today = datetime(2026, 4, 26, tzinfo=timezone.utc)

    def _run_with(self, legacy_returns, v2_returns):
        async def legacy_callable(p, pj, c, t):
            if isinstance(legacy_returns, Exception):
                raise legacy_returns
            return legacy_returns

        async def v2_callable(d, p, pj, c, t):
            if isinstance(v2_returns, Exception):
                raise v2_returns
            return v2_returns

        return _run(eligibility_shadow.run_one(
            db=None,
            legacy_callable=legacy_callable,
            v2_callable=v2_callable,
            permit=_permit(),
            project={"_id": "p1"},
            company={"gc_license_number": "626198"},
            today=self.today,
        ))

    # ── Cat 1: identity diffs ──────────────────────────────────────
    # Identity fields are compared against the SOURCE-OF-TRUTH input
    # docs (permit, company), not against the legacy result. Legacy's
    # RenewalEligibility doesn't surface fields like issuance_date,
    # so reading from the legacy output would produce false positives.

    def test_identity_diff_when_v2_disagrees_with_permit_doc(self):
        """v2 output must match the permit doc's calendar expiry."""
        legacy = _legacy_result_eligible()
        v2 = _v2_result(calendar_expiry="2099-01-01T00:00:00+00:00")  # wrong
        doc = self._run_with(legacy, v2)
        identity_diffs = [d for d in doc["divergences"] if d["category"] == "identity"]
        cal_diffs = [d for d in identity_diffs if d["field"] == "calendar_expiry"]
        self.assertEqual(len(cal_diffs), 1)
        # `old_value` is now the permit doc's expiration_date, not the
        # legacy result's expiration_date field.
        self.assertEqual(
            cal_diffs[0]["old_value"],
            datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

    def test_identity_match_when_v2_matches_permit_doc(self):
        """v2 reading the same calendar_expiry as the permit doc → no diff."""
        legacy = _legacy_result_eligible()
        v2 = _v2_result(calendar_expiry="2027-01-01T00:00:00+00:00")
        doc = self._run_with(legacy, v2)
        cal_diffs = [
            d for d in doc["divergences"]
            if d["category"] == "identity" and d["field"] == "calendar_expiry"
        ]
        self.assertEqual(cal_diffs, [])

    def test_identity_match_on_license_number_from_company(self):
        """v2 license number must match company.gc_license_number."""
        legacy = _legacy_result_eligible()
        v2 = _v2_result(permittee_license_number="626198")
        doc = self._run_with(legacy, v2)
        diffs = [
            d for d in doc["divergences"]
            if d["category"] == "identity" and d["field"] == "permittee_license_number"
        ]
        self.assertEqual(diffs, [])

    # ── Cat 2: expected divergences ────────────────────────────────

    def test_expected_divergence_effective_expiry_for_shed(self):
        permit_doc = _permit(
            permit_class="sidewalk_shed",
            issuance_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expiration_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        legacy = _legacy_result_eligible(expiration_date="2026-07-01T00:00:00+00:00")
        v2 = _v2_result(
            permit_class="sidewalk_shed",
            renewal_strategy="MANUAL_90D_SHED",
            calendar_expiry="2026-07-01T00:00:00+00:00",
            effective_expiry="2026-04-01T00:00:00+00:00",
            limiting_factor={
                "label": "90-day shed cap (LL48/2024)",
                "kind": "shed_cap",
                "expires_in_days": -25,
            },
        )

        async def legacy_callable(p, pj, c, t):
            return legacy

        async def v2_callable(d, p, pj, c, t):
            return v2

        doc = _run(eligibility_shadow.run_one(
            db=None,
            legacy_callable=legacy_callable,
            v2_callable=v2_callable,
            permit=permit_doc,
            project={"_id": "p1"},
            company={"gc_license_number": "626198"},
            today=self.today,
        ))

        expected = [d for d in doc["divergences"] if d["category"] == "expected"]
        # effective_expiry shift, renewal_strategy new taxonomy,
        # action.kind new taxonomy, limiting_factor.label new taxonomy.
        kinds = {d.get("kind") for d in expected if d["field"] == "effective_expiry"}
        self.assertIn("shed_90d_cap", kinds)

    def test_expected_divergence_sub_class_other_when_unattributable(self):
        legacy = _legacy_result_eligible(expiration_date="2027-01-01T00:00:00+00:00")
        # Genuinely unattributable: the effective_expiry shifts BUT the
        # permit is not shed, not BIS, not AWAITING_EXTENSION, and the
        # limiting_kind is "unknown" — none of the explicit sub-classes
        # apply. Lands in `other` with example_detail for the report.
        v2 = _v2_result(
            calendar_expiry="2027-01-01T00:00:00+00:00",
            effective_expiry="2026-06-01T00:00:00+00:00",
            renewal_strategy="AUTO_EXTEND_DOB_NOW",
            permit_class="standard",
            filing_system="DOB_NOW",
            limiting_factor={"label": "X", "kind": "unknown", "expires_in_days": 0},
        )
        doc = self._run_with(legacy, v2)
        eff = [d for d in doc["divergences"]
               if d["field"] == "effective_expiry" and d.get("kind") == "other"]
        self.assertEqual(len(eff), 1)
        self.assertIn("example_detail", eff[0])

    # ── Cat 3: severity escalation ─────────────────────────────────

    def test_severity_escalation_old_eligible_new_blocked(self):
        legacy = _legacy_result_eligible()  # tier 0
        v2 = _v2_result(
            renewal_strategy="MANUAL_LAPSED",
            blocking_reasons=["lapsed insurance"],
        )  # tier 3
        doc = self._run_with(legacy, v2)
        sev = [d for d in doc["divergences"] if d["category"] == "severity"]
        self.assertEqual(len(sev), 1)
        self.assertEqual(sev[0]["direction"], "escalation")
        self.assertEqual(sev[0]["old_value"], 0)
        self.assertEqual(sev[0]["new_value"], 3)

    def test_severity_deescalation_old_blocked_new_eligible(self):
        legacy = _legacy_result_eligible(
            blocking_reasons=["GC License not found"],
        )  # tier 3
        v2 = _v2_result()  # tier 0 (AUTO_EXTEND_DOB_NOW, no blocks)
        doc = self._run_with(legacy, v2)
        sev = [d for d in doc["divergences"] if d["category"] == "severity"]
        self.assertEqual(len(sev), 1)
        self.assertEqual(sev[0]["direction"], "deescalation")

    def test_awaiting_extension_carveout_does_not_fire_as_severity(self):
        """The high-stakes guard: legacy 0 → v2 1 with strategy
        AWAITING_EXTENSION must be classified as Cat 2 expected, NOT
        Cat 3 escalation. Otherwise every Socrata-lag permit in the
        next 48hr would land in the review queue."""
        legacy = _legacy_result_eligible()  # tier 0
        v2 = _v2_result(
            renewal_strategy="AWAITING_EXTENSION",
            limiting_factor={
                "label": "Workers' Comp",
                "kind": "insurance",
                "expires_in_days": 1,
            },
        )  # tier 1
        doc = self._run_with(legacy, v2)
        sev = [d for d in doc["divergences"] if d["category"] == "severity"]
        self.assertEqual(sev, [], "AWAITING_EXTENSION must NOT fire severity diff")
        # Should appear in Cat 2 with the right sub-class.
        eff = [d for d in doc["divergences"]
               if d["field"] == "effective_expiry"
               and d.get("kind") == "awaiting_extension_window"]
        self.assertEqual(len(eff), 1)

    # ── Cat 5: crashes ─────────────────────────────────────────────

    def test_v2_crash_recorded_as_cat5(self):
        legacy = _legacy_result_eligible()
        v2 = ValueError("boom")
        doc = self._run_with(legacy, v2)
        crashes = [d for d in doc["divergences"] if d["category"] == "crash"]
        self.assertEqual(len(crashes), 1)
        self.assertEqual(crashes[0]["side"], "v2")
        self.assertTrue(doc["new_crashed"])
        self.assertFalse(doc["old_crashed"])

    def test_legacy_crash_recorded_as_cat5(self):
        legacy = RuntimeError("legacy bug")
        v2 = _v2_result()
        doc = self._run_with(legacy, v2)
        crashes = [d for d in doc["divergences"] if d["category"] == "crash"]
        self.assertEqual(len(crashes), 1)
        self.assertEqual(crashes[0]["side"], "legacy")
        self.assertTrue(doc["old_crashed"])

    # ── Cat 4: latency captured ───────────────────────────────────

    def test_latency_recorded(self):
        legacy = _legacy_result_eligible()
        v2 = _v2_result()
        doc = self._run_with(legacy, v2)
        self.assertIsInstance(doc["old_latency_ms"], float)
        self.assertIsInstance(doc["new_latency_ms"], float)
        self.assertGreaterEqual(doc["old_latency_ms"], 0.0)
        self.assertGreaterEqual(doc["new_latency_ms"], 0.0)


class TestModeValidation(unittest.TestCase):
    """Fail-fast on invalid env values per the step-5 non-negotiable."""

    def test_valid_modes_accepted(self):
        import os
        from lib import eligibility_dispatcher

        for mode in ("off", "shadow", "live"):
            os.environ["ELIGIBILITY_REWRITE_MODE"] = mode
            self.assertEqual(eligibility_dispatcher.get_mode(), mode)

        # Trailing whitespace / case tolerated, deliberate.
        os.environ["ELIGIBILITY_REWRITE_MODE"] = "  SHADOW  "
        self.assertEqual(eligibility_dispatcher.get_mode(), "shadow")

    def test_invalid_mode_raises_at_startup(self):
        import os
        from lib import eligibility_dispatcher

        os.environ["ELIGIBILITY_REWRITE_MODE"] = "shadwo"  # typo
        with self.assertRaises(RuntimeError) as ctx:
            eligibility_dispatcher.assert_valid_mode_at_startup()
        self.assertIn("invalid", str(ctx.exception))
        self.assertIn("shadwo", str(ctx.exception))

    def test_default_off_when_unset(self):
        import os
        from lib import eligibility_dispatcher

        os.environ.pop("ELIGIBILITY_REWRITE_MODE", None)
        self.assertEqual(eligibility_dispatcher.get_mode(), "off")


if __name__ == "__main__":
    unittest.main()
