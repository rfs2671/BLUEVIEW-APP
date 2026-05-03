"""MR.14 (commit 2b) — plain-English template renderers.

One canonical-output test per template so copy edits are visible
in PR diffs as deliberate changes. Plus coverage check ensuring
every signal_kind from the classifier has a renderer.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── Coverage check ────────────────────────────────────────────────


class TestTemplateCoverage(unittest.TestCase):
    """Every signal_kind the classifier produces (excluding generic
    fallbacks like 'permit', 'inspection', 'cofo', 'unknown') MUST
    have a registered renderer. Generic fallbacks fall through to
    _render_generic by design and don't need explicit registration."""

    def test_every_specific_signal_kind_has_renderer(self):
        from lib.dob_signal_classifier import KNOWN_SIGNAL_KINDS
        from lib.dob_signal_templates import SIGNAL_TEMPLATE_RENDERERS
        # Generic fallbacks deliberately go to _render_generic.
        FALLBACK_KINDS = {
            "permit", "job_status", "inspection", "cofo", "unknown",
            "violation_open",  # listed in KNOWN but no specific renderer needed
        }
        specific_kinds = set(KNOWN_SIGNAL_KINDS) - FALLBACK_KINDS
        registered = set(SIGNAL_TEMPLATE_RENDERERS.keys())
        missing = specific_kinds - registered
        self.assertEqual(
            missing, set(),
            f"signal_kinds without templates: {missing}",
        )

    def test_render_signal_returns_required_shape(self):
        """Every template output must include title/body/severity/action_text."""
        from lib.dob_signal_templates import (
            SIGNAL_TEMPLATE_RENDERERS,
            render_signal,
        )
        for kind, renderer in SIGNAL_TEMPLATE_RENDERERS.items():
            with self.subTest(kind=kind):
                out = render_signal(kind, {})
                for required in ("title", "body", "severity", "action_text"):
                    self.assertIn(required, out, f"{kind} missing {required}")
                    self.assertIsInstance(out[required], str)
                    self.assertTrue(out[required], f"{kind}.{required} empty")


# ── Pinned canonical outputs ──────────────────────────────────────
#
# Each template gets ONE pinned output. Copy edits show up in PR
# diffs as deliberate changes. If you change a template's wording,
# update the pinned string here in the same PR — the diff is the
# review artifact for "yes I meant this change."


class TestPinnedTemplateOutputs(unittest.TestCase):

    def test_permit_issued(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("permit_issued", {
            "job_filing_number": "B00736930-S1",
            "work_type": "Plumbing",
        })
        self.assertEqual(
            out["title"],
            "✅ Permit issued — Plumbing (Job B00736930-S1)",
        )
        self.assertEqual(out["severity"], "info")
        self.assertIn("Work can begin", out["body"])

    def test_permit_expired(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("permit_expired", {
            "job_filing_number": "B00736930-S1",
            "work_type": "Plumbing",
            "expiration_date": "2026-04-30",
        })
        self.assertIn("Permit expired", out["title"])
        self.assertIn("2026-04-30", out["body"])
        self.assertEqual(out["severity"], "critical")

    def test_filing_disapproved(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("filing_disapproved", {
            "job_filing_number": "B00736930",
        })
        self.assertEqual(
            out["title"],
            "❌ Job filing disapproved (Job B00736930)",
        )
        self.assertEqual(out["severity"], "critical")

    def test_violation_dob(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("violation_dob", {
            "violation_number": "V12345",
            "violation_type": "Working without permit",
        })
        self.assertIn("DOB violation issued", out["title"])
        self.assertIn("V12345", out["title"])
        self.assertEqual(out["severity"], "critical")

    def test_violation_ecb(self):
        """ECB template explains plain-English what OATH is."""
        from lib.dob_signal_templates import render_signal
        out = render_signal("violation_ecb", {
            "violation_number": "E001234567",
            "disposition_date": "2026-06-15",
            "penalty_amount": "1500",
        })
        self.assertIn("OATH", out["body"])  # plain-English explanation
        self.assertIn("$1500", out["body"])
        self.assertEqual(out["severity"], "critical")

    def test_stop_work_full(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("stop_work_full", {"violation_date": "2026-05-03"})
        self.assertIn("🛑", out["title"])
        self.assertIn("ALL work must stop", out["body"])
        self.assertEqual(out["severity"], "critical")

    def test_stop_work_partial(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("stop_work_partial", {})
        self.assertIn("Partial Stop Work", out["title"])
        self.assertEqual(out["severity"], "critical")

    def test_complaint_dob(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("complaint_dob", {
            "complaint_number": "DOB123",
            "complaint_type": "Illegal Construction",
        })
        self.assertIn("Illegal Construction", out["title"])
        self.assertIn("DOB123", out["body"])

    def test_complaint_311(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("complaint_311", {
            "complaint_type": "Construction Equipment",
        })
        self.assertIn("311", out["title"])
        self.assertEqual(out["severity"], "info")

    def test_inspection_scheduled(self):
        """The example from operator's spec — the canonical 'good
        plain-English output' the whole product is judged against."""
        from lib.dob_signal_templates import render_signal
        out = render_signal("inspection_scheduled", {
            "inspection_type": "PL3 — Underground Plumbing",
            "inspection_date": "2026-05-08",
        })
        self.assertIn("PL3 — Underground Plumbing", out["title"])
        self.assertIn("2026-05-08", out["title"])
        self.assertIn("scheduled", out["title"])
        self.assertEqual(out["severity"], "info")

    def test_inspection_failed(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("inspection_failed", {
            "inspection_type": "Plumbing — Initial",
            "inspection_result_description": "Vent line not properly capped",
        })
        self.assertIn("failed", out["title"])
        self.assertIn("Vent line not properly capped", out["body"])
        self.assertEqual(out["severity"], "critical")

    def test_final_signoff_pass(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("final_signoff", {
            "inspection_type": "Plumbing — Final",
            "current_status": "PASSED",
        })
        self.assertIn("SIGNED OFF", out["title"])
        self.assertEqual(out["severity"], "info")

    def test_final_signoff_fail(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("final_signoff", {
            "inspection_type": "Plumbing — Final",
            "current_status": "FAILED",
        })
        self.assertIn("sign-off denied", out["title"])
        self.assertEqual(out["severity"], "critical")

    def test_cofo_temporary_explains_TCO(self):
        """CofO templates must explain the 'TCO' / 'CofO' jargon
        inline since target audience may not know the terms."""
        from lib.dob_signal_templates import render_signal
        out = render_signal("cofo_temporary", {})
        self.assertIn("TCO", out["body"])
        self.assertIn("partial occupancy", out["body"])

    def test_cofo_final(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("cofo_final", {})
        self.assertIn("Final CofO", out["title"])
        self.assertEqual(out["severity"], "info")

    def test_facade_fisp_explains_jargon(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("facade_fisp", {"cycle": "9B"})
        self.assertIn("FISP", out["title"])
        self.assertIn("Façade Inspection Safety Program", out["body"])

    def test_boiler_inspection(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("boiler_inspection", {})
        self.assertIn("Boiler", out["title"])

    def test_elevator_inspection(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("elevator_inspection", {})
        self.assertIn("Elevator", out["title"])

    def test_license_renewal_due(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("license_renewal_due", {
            "license_holder_name": "Jane Filer",
            "days_until_expiry": 14,
        })
        self.assertIn("Jane Filer", out["title"])
        self.assertIn("14 days", out["body"])

    def test_unknown_signal_kind_falls_back_to_generic(self):
        from lib.dob_signal_templates import render_signal
        out = render_signal("unknown_signal_kind_xyz", {
            "ai_summary": "Something weird happened",
        })
        # Generic renderer pulls from ai_summary.
        self.assertIn("Something weird happened", out["title"])


if __name__ == "__main__":
    unittest.main()
