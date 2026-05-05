"""Phase B3 — frontend invariants for the customer onboarding flow,
empty states, first-poll banner, and inline tooltips.

Frontend invariant tests are static-file string checks. They catch
the cheap regressions (a future commit that re-introduces a
hardcoded color, drops a step from the flow, removes an empty
state, or unwires a tooltip) without requiring a JS test runner.
Live visual verification is the operator-action checklist.

Pinned surfaces:
  • app/onboarding.jsx (the 4-step flow)
  • app/_layout.jsx (RouteGuard onboarding redirect)
  • app/index.jsx (empty state + first-poll banner)
  • src/components/ActivityFeed.jsx (empty-state copy + filter
    group tooltips)
  • app/project/[id]/permit-renewal.jsx (renewals empty state)
  • app/project/[id]/dob-logs.jsx (track_dob_status tooltip)
  • app/settings/notifications.jsx ("What does this mean?" links)
  • src/utils/api.js (onboardingAPI surface)
  • src/utils/signalKindHelp.js (per-kind help dictionary)
  • src/components/InfoTooltip.jsx (tooltip primitive)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_FRONTEND = _REPO / "frontend"


# ──────────────────────────────────────────────────────────────────
# /onboarding route — 4-step flow
# ──────────────────────────────────────────────────────────────────


class TestOnboardingRoute(unittest.TestCase):
    """The /onboarding route uses the LeveLog design system and
    surfaces all four steps with progressive submit + skip."""

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "app" / "onboarding.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_file_present(self):
        self.assertTrue(self.path.exists())

    def test_uses_design_system(self):
        """AnimatedBackground + GlassCard + GlassButton + useTheme
        — no bespoke chrome."""
        self.assertIn("AnimatedBackground", self.text)
        self.assertIn("GlassCard", self.text)
        self.assertIn("GlassButton", self.text)
        self.assertIn("GlassInput", self.text)
        self.assertIn("useTheme", self.text)

    def test_uses_theme_tokens(self):
        self.assertIn("from '../src/styles/theme'", self.text)
        self.assertIn("typography", self.text)
        self.assertIn("spacing", self.text)
        self.assertIn("borderRadius", self.text)

    def test_four_step_progress(self):
        self.assertIn("STEP_KEYS = ['1', '2', '3', '4']", self.text)
        self.assertIn("TOTAL_STEPS = 4", self.text)
        # Every step has its own metadata block (numeric object keys).
        self.assertIn("STEP_META", self.text)
        for s in ("\n  1: {", "\n  2: {", "\n  3: {", "\n  4: {"):
            self.assertIn(s, self.text)

    def test_step_titles_match_spec(self):
        # The literal step copy is part of the contract.
        self.assertIn("Tell us about your company", self.text)
        self.assertIn("Add your first project", self.text)
        self.assertIn("Add filing reps (optional)", self.text)
        self.assertIn("How should we notify you?", self.text)

    def test_uses_onboarding_api(self):
        self.assertIn("onboardingAPI", self.text)
        # Each step's submit hits the right endpoint.
        self.assertIn("/api/onboarding/company", self.text)
        self.assertIn("/api/onboarding/project", self.text)
        self.assertIn("/api/onboarding/filing-reps", self.text)
        self.assertIn("/api/users/me/notification-preferences", self.text)

    def test_uses_existing_presets(self):
        """Step 4 reuses the B1b.1 PRESETS shape rather than
        re-inventing notification preferences."""
        self.assertIn("notificationPresets", self.text)
        self.assertIn("buildPresetPrefs", self.text)

    def test_skip_path_present_for_each_step(self):
        # "I'll do this later" / "Skip this step" / "Use Critical only"
        self.assertIn("I'll do this later", self.text)
        self.assertIn("Skip this step", self.text)

    def test_advance_step_via_patch(self):
        self.assertIn("patchStep", self.text)
        self.assertIn("'completed'", self.text)
        self.assertIn("'skipped'", self.text)

    def test_mobile_breakpoint(self):
        self.assertIn("MOBILE_BREAKPOINT = 768", self.text)


# ──────────────────────────────────────────────────────────────────
# RouteGuard onboarding gate
# ──────────────────────────────────────────────────────────────────


class TestRouteGuardOnboardingGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "app" / "_layout.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_guard_helper_present(self):
        self.assertIn("_userInOnboarding", self.text)
        self.assertIn("_ONBOARDING_IN_FLIGHT_STEPS", self.text)

    def test_redirects_to_onboarding(self):
        self.assertIn("router.replace('/onboarding')", self.text)

    def test_excludes_site_devices_and_cps(self):
        """Onboarding gate must not interfere with site_device or CP
        role redirects."""
        self.assertIn("!isSiteDevice", self.text)
        self.assertIn("!isCp", self.text)


# ──────────────────────────────────────────────────────────────────
# api.js — onboardingAPI surface
# ──────────────────────────────────────────────────────────────────


class TestOnboardingAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "src" / "utils" / "api.js"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_onboarding_api_exported(self):
        self.assertIn("export const onboardingAPI", self.text)

    def test_get_status_method(self):
        self.assertIn("'/api/users/me/onboarding-status'", self.text)
        self.assertIn("getStatus:", self.text)

    def test_patch_step_method(self):
        self.assertIn("'/api/users/me/onboarding-step'", self.text)
        self.assertIn("patchStep:", self.text)


# ──────────────────────────────────────────────────────────────────
# Dashboard — empty state + first-poll banner
# ──────────────────────────────────────────────────────────────────


class TestDashboardEmptyStateAndBanner(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "app" / "index.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_empty_state_copy(self):
        """Welcome copy + 'Add Project' CTA when projects.length === 0
        for owners/admins."""
        self.assertIn("Welcome to LeveLog", self.text)
        self.assertIn("Add your first project to start monitoring", self.text)
        # CTA button title.
        self.assertIn('title="Add Project"', self.text)

    def test_empty_state_renders_only_for_admin_owner(self):
        """Workers shouldn't see an Add Project CTA they can't act on."""
        self.assertIn("'admin'", self.text)
        self.assertIn("'owner'", self.text)
        self.assertIn("showProjectsEmptyState", self.text)

    def test_first_poll_banner_uses_project_fields(self):
        self.assertIn("first_poll_completed_at", self.text)
        self.assertIn("first_poll_summary", self.text)

    def test_first_poll_banner_24h_window(self):
        # The 24h window is the contract per spec.
        self.assertIn("24 * 60 * 60 * 1000", self.text)

    def test_first_poll_banner_dismissal_persists(self):
        """Dismissal stored in AsyncStorage so it doesn't reappear
        on the user's next session."""
        self.assertIn("AsyncStorage", self.text)
        self.assertIn("bv_first_poll_dismissed", self.text)

    def test_first_poll_banner_cta(self):
        self.assertIn("View activity →", self.text)
        self.assertIn("/activity", self.text)


# ──────────────────────────────────────────────────────────────────
# Activity feed — empty-state copy + group tooltips
# ──────────────────────────────────────────────────────────────────


class TestActivityFeedB3Touches(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "src" / "components" / "ActivityFeed.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_empty_state_copy_polished(self):
        self.assertIn(
            "We're monitoring DOB. Your first signals will appear within 15 minutes.",
            self.text,
        )

    def test_filter_group_tooltips(self):
        self.assertIn("InfoTooltip", self.text)
        self.assertIn("SIGNAL_KIND_GROUP_HELP", self.text)
        self.assertIn("kindGroupHeader", self.text)


# ──────────────────────────────────────────────────────────────────
# Renewals empty-state copy
# ──────────────────────────────────────────────────────────────────


class TestRenewalsEmptyState(unittest.TestCase):

    def test_renewals_empty_copy(self):
        path = _FRONTEND / "app" / "project" / "[id]" / "permit-renewal.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            "When permits approach renewal, you'll see them here.",
            text,
        )


# ──────────────────────────────────────────────────────────────────
# track_dob_status tooltip
# ──────────────────────────────────────────────────────────────────


class TestTrackDobStatusTooltip(unittest.TestCase):

    def test_tooltip_wraps_toggle(self):
        path = _FRONTEND / "app" / "project" / "[id]" / "dob-logs.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("InfoTooltip", text)
        # Tooltip text mentions the 15-minute scan cadence.
        self.assertIn("every 15 minutes", text)


# ──────────────────────────────────────────────────────────────────
# "What does this mean?" links in advanced notification preferences
# ──────────────────────────────────────────────────────────────────


class TestNotificationPrefsHelpLinks(unittest.TestCase):

    def test_help_links_present(self):
        path = _FRONTEND / "app" / "settings" / "notifications.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("InfoTooltip", text)
        self.assertIn("SIGNAL_KIND_HELP", text)
        self.assertIn("What does this mean?", text)


# ──────────────────────────────────────────────────────────────────
# signalKindHelp dictionary covers all 26 kinds
# ──────────────────────────────────────────────────────────────────


class TestSignalKindHelpCoverage(unittest.TestCase):
    """Every signal_kind in the canonical preset list (B1b.1
    notificationPresets.ALL_KINDS — pinned to backend
    ALL_DEFAULT_SIGNAL_KINDS) has a plain-English help entry."""

    @classmethod
    def setUpClass(cls):
        path = _FRONTEND / "src" / "utils" / "signalKindHelp.js"
        cls.text = path.read_text(encoding="utf-8")

    def test_all_kinds_have_help(self):
        ALL_KINDS = [
            'permit_issued', 'permit_expired', 'permit_revoked', 'permit_renewed',
            'filing_approved', 'filing_disapproved', 'filing_withdrawn', 'filing_pending',
            'violation_dob', 'violation_ecb', 'violation_resolved',
            'stop_work_full', 'stop_work_partial',
            'complaint_dob', 'complaint_311',
            'inspection_scheduled', 'inspection_passed', 'inspection_failed', 'final_signoff',
            'cofo_temporary', 'cofo_final', 'cofo_pending',
            'facade_fisp', 'boiler_inspection', 'elevator_inspection',
            'license_renewal_due',
        ]
        for kind in ALL_KINDS:
            self.assertIn(f"{kind}:", self.text, f"Missing help for {kind!r}")

    def test_group_help_present(self):
        for label in (
            "Permits", "Job Filings", "Violations", "Stop Work Orders",
            "Complaints", "Inspections", "Compliance", "License",
        ):
            self.assertIn(f"{label!r}:" if " " in label else f"{label}:", self.text,
                          f"Missing group help for {label!r}")


# ──────────────────────────────────────────────────────────────────
# InfoTooltip primitive
# ──────────────────────────────────────────────────────────────────


class TestInfoTooltipPrimitive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "src" / "components" / "InfoTooltip.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_file_present(self):
        self.assertTrue(self.path.exists())

    def test_uses_design_system(self):
        self.assertIn("GlassCard", self.text)
        self.assertIn('variant="modal"', self.text)
        self.assertIn("useTheme", self.text)

    def test_supports_label_or_icon(self):
        # The component has two render paths: bare info icon, or
        # a "What does this mean?" link variant.
        self.assertIn("label ?", self.text)
        self.assertIn("Modal", self.text)


if __name__ == "__main__":
    unittest.main()
