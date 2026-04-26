"""Tests for the renewal-digest threshold logic.

The cron itself is exercised end-to-end in test_coi_endpoints style
elsewhere (or manually via TestClient against a stubbed scheduler).
This file pins the threshold semantics — exact-equality firing,
no double-fire across days, sub-class detection per AlertKind.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.renewal_digest import (  # noqa: E402
    AlertKind,
    CADENCES,
    compute_company_alerts,
    digest_html,
    digest_subject,
)


def _company(**kw):
    base = {
        "_id": "co1",
        "name": "Acme GC",
        "license_class": "GC_LICENSED",
        "gc_license_expiration": None,
        "gc_insurance_records": [],
    }
    base.update(kw)
    return base


def _ins(insurance_type, exp):
    return {"insurance_type": insurance_type, "expiration_date": exp}


def _permit(**kw):
    base = {
        "_id": "p1",
        "project_id": "proj1",
        "project_name": "9 Menahan",
        "job_number": "B12345-I1",
        "issuance_date": None,
        "permit_class": "standard",
        "filing_system": "DOB_NOW",
    }
    base.update(kw)
    return base


def _today():
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


class TestInsuranceCadence(unittest.TestCase):
    """Insurance: T-30, T-14, T-7, T-5, T-0."""

    def _alerts_for_days_left(self, days_left):
        """Helper: insurance expires `days_left` from today."""
        today = _today()
        exp = (today + timedelta(days=days_left)).date().isoformat()
        company = _company(gc_insurance_records=[
            _ins("workers_comp", exp),
        ])
        return compute_company_alerts(
            company=company, permits=[], today=today,
        )

    def test_fires_at_exactly_30(self):
        alerts = self._alerts_for_days_left(30)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, AlertKind.INSURANCE)
        self.assertEqual(alerts[0].threshold_days, 30)

    def test_fires_at_exactly_14(self):
        alerts = self._alerts_for_days_left(14)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].threshold_days, 14)

    def test_fires_at_exactly_5(self):
        """T-5 = last call for auto-extension; this is the most
        operationally critical threshold for insurance."""
        alerts = self._alerts_for_days_left(5)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].threshold_days, 5)

    def test_fires_at_exactly_0_today_is_expiry(self):
        alerts = self._alerts_for_days_left(0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].threshold_days, 0)

    def test_does_not_fire_off_threshold(self):
        """29 days left does NOT fire (yesterday's threshold). 13
        days left does NOT fire (T-14 was yesterday). Boundary
        semantics: exact equality only."""
        for off_threshold in (29, 28, 13, 12, 6, 4, 1):
            alerts = self._alerts_for_days_left(off_threshold)
            self.assertEqual(
                alerts, [],
                f"days_left={off_threshold} should NOT fire any threshold",
            )

    def test_does_not_fire_when_already_expired(self):
        """Past-expiry shouldn't keep firing forever. After T-0 there's
        nothing to alert about — the permit is now MANUAL_LAPSED and
        the eligibility engine handles it."""
        alerts = self._alerts_for_days_left(-5)
        self.assertEqual(alerts, [])

    def test_label_per_insurance_type(self):
        today = _today()
        exp = (today + timedelta(days=14)).date().isoformat()
        company = _company(gc_insurance_records=[
            _ins("general_liability", exp),
            _ins("workers_comp", exp),
            _ins("disability", exp),
        ])
        alerts = compute_company_alerts(
            company=company, permits=[], today=today,
        )
        labels = sorted(a.expiry_label for a in alerts)
        self.assertEqual(labels, ["Disability", "General Liability", "Workers' Comp"])


class TestGcLicenseCadence(unittest.TestCase):
    """GC license: T-90, T-60, T-30, T-14. Different from insurance —
    license renewal window is wider per NYC DOB OPPN guidance."""

    def _alerts_for_days_left(self, days_left):
        today = _today()
        exp = (today + timedelta(days=days_left)).date().isoformat()
        company = _company(gc_license_expiration=exp)
        return compute_company_alerts(
            company=company, permits=[], today=today,
        )

    def test_fires_at_T_90(self):
        alerts = self._alerts_for_days_left(90)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, AlertKind.GC_LICENSE)
        self.assertEqual(alerts[0].threshold_days, 90)
        self.assertEqual(alerts[0].expiry_label, "GC License")

    def test_fires_at_T_14(self):
        alerts = self._alerts_for_days_left(14)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].threshold_days, 14)

    def test_does_not_fire_at_insurance_threshold_T_7(self):
        """7 isn't in the GC license cadence — should NOT fire."""
        alerts = self._alerts_for_days_left(7)
        self.assertEqual(alerts, [])


class TestPermit1YrCadence(unittest.TestCase):
    """Permit 1-year ceiling: T-30, T-14, T-7."""

    def _alerts_for_days_left(self, days_left):
        today = _today()
        # issuance + 365 should land days_left days from today.
        issuance = today + timedelta(days=days_left - 365)
        company = _company()
        permits = [_permit(issuance_date=issuance.isoformat())]
        return compute_company_alerts(
            company=company, permits=permits, today=today,
        )

    def test_fires_at_T_30(self):
        alerts = self._alerts_for_days_left(30)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, AlertKind.PERMIT_1YR)

    def test_fires_at_T_7(self):
        alerts = self._alerts_for_days_left(7)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].threshold_days, 7)

    def test_does_not_fire_at_5_or_0(self):
        """Permit 1yr cadence does NOT include T-5 or T-0 (insurance
        gets those because that's where auto-extension applies; 1yr
        ceiling is hard regardless)."""
        for off in (5, 4, 1, 0):
            alerts = self._alerts_for_days_left(off)
            self.assertEqual(alerts, [], f"days_left={off} should NOT fire")


class TestShed90dCadence(unittest.TestCase):
    """Shed: T-60, T-30, T-14, T-7."""

    def _alerts_for_days_left(self, days_left):
        today = _today()
        # issuance + 90 should land days_left days from today.
        issuance = today + timedelta(days=days_left - 90)
        company = _company()
        permits = [_permit(
            permit_class="sidewalk_shed",
            issuance_date=issuance.isoformat(),
        )]
        return compute_company_alerts(
            company=company, permits=permits, today=today,
        )

    def test_fires_at_T_60(self):
        alerts = self._alerts_for_days_left(60)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, AlertKind.SHED_90D)

    def test_fires_at_T_7(self):
        alerts = self._alerts_for_days_left(7)
        self.assertEqual(len(alerts), 1)

    def test_shed_does_not_fall_into_1yr_track(self):
        """A sidewalk-shed permit must NOT also fire AlertKind.PERMIT_1YR
        — the shed track replaces the standard track, doesn't compound."""
        today = _today()
        issuance = today + timedelta(days=-30)  # 60 days into a 90d permit
        company = _company()
        permits = [_permit(
            permit_class="sidewalk_shed",
            issuance_date=issuance.isoformat(),
        )]
        alerts = compute_company_alerts(
            company=company, permits=permits, today=today,
        )
        # 60 days since issuance → 30 days until shed expiry. T-30 fires
        # for SHED_90D. PERMIT_1YR cadence at issuance+365 = 335 days
        # from today, which isn't a threshold either.
        kinds = [a.kind for a in alerts]
        self.assertEqual(kinds, [AlertKind.SHED_90D])


class TestIdempotency(unittest.TestCase):

    def test_idempotency_key_includes_threshold(self):
        """Same expiry, different threshold → different keys.
        T-30 alert today and T-14 alert 16 days later are
        independent. Use GC_LICENSE cadence values that actually
        appear in the cadence list (insurance is [30,14,7,5,0];
        gc_license is [90,60,30,14])."""
        today = _today()
        exp = (today + timedelta(days=30)).date().isoformat()
        a_today = compute_company_alerts(
            company=_company(gc_license_expiration=exp),
            permits=[], today=today,
        )
        self.assertEqual(len(a_today), 1, "T-30 should fire today")

        # 16 days later, same expiry → days_left=14 → T-14 fires.
        future = today + timedelta(days=16)
        a_future = compute_company_alerts(
            company=_company(gc_license_expiration=exp),
            permits=[], today=future,
        )
        self.assertEqual(len(a_future), 1, "T-14 should fire 16 days later")
        self.assertNotEqual(
            a_today[0].idempotency_key()["threshold_days"],
            a_future[0].idempotency_key()["threshold_days"],
        )

    def test_idempotency_key_per_permit(self):
        """Two permits crossing the same threshold today → two keys.
        The cron sends one digest containing both, but each gets its
        own idempotency row so re-runs don't double-mark."""
        today = _today()
        issuance = today + timedelta(days=-358)  # 7 days from ceiling
        company = _company()
        permits = [
            _permit(_id="p1", issuance_date=issuance.isoformat()),
            _permit(_id="p2", job_number="B22222", issuance_date=issuance.isoformat()),
        ]
        alerts = compute_company_alerts(
            company=company, permits=permits, today=today,
        )
        self.assertEqual(len(alerts), 2)
        self.assertNotEqual(
            alerts[0].idempotency_key(),
            alerts[1].idempotency_key(),
        )


class TestEmailFormatting(unittest.TestCase):

    def test_subject_for_no_alerts(self):
        subject = digest_subject([], "Acme")
        self.assertIn("Acme", subject)

    def test_subject_for_today_expiry_is_urgent(self):
        today = _today()
        exp = today.date().isoformat()
        company = _company(gc_insurance_records=[_ins("workers_comp", exp)])
        alerts = compute_company_alerts(
            company=company, permits=[], today=today,
        )
        subject = digest_subject(alerts, "Acme")
        self.assertIn("expired TODAY", subject)

    def test_html_renders_with_alerts(self):
        today = _today()
        exp = (today + timedelta(days=14)).date().isoformat()
        company = _company(gc_insurance_records=[_ins("workers_comp", exp)])
        alerts = compute_company_alerts(
            company=company, permits=[], today=today,
        )
        html = digest_html(alerts, "Acme")
        self.assertIn("Workers", html)
        self.assertIn("expires in 14 days", html)


class TestSuppression(unittest.TestCase):

    def test_no_alerts_when_no_data(self):
        """No insurance, no license, no permits → no alerts."""
        alerts = compute_company_alerts(
            company=_company(), permits=[], today=_today(),
        )
        self.assertEqual(alerts, [])

    def test_no_alerts_when_far_from_any_threshold(self):
        today = _today()
        exp = (today + timedelta(days=200)).date().isoformat()
        alerts = compute_company_alerts(
            company=_company(
                gc_license_expiration=exp,
                gc_insurance_records=[_ins("workers_comp", exp)],
            ),
            permits=[], today=today,
        )
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
