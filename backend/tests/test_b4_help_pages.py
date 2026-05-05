"""Phase B4 — customer help pages + preset-radio tooltip delta.

Static-source pin tests for the /help/* tree and the inline tooltip
additions on top of B3.

Coverage:
  • All 5 help pages exist at the expected /help/<slug> path.
  • Each page uses the HelpPageShell component (AnimatedBackground
    + theme-aware chrome shared with B0.1 / B3 surfaces).
  • Each page contains the spec-mandated content sections.
  • The /help index page links to every topic page.
  • Preset-radio tooltips wired in BOTH settings/notifications.jsx
    AND onboarding.jsx (delta from B3).
  • Internal ops runbook present at docs/operations/runbook.md
    with the 8 expected sections.
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
_HELP = _FRONTEND / "app" / "help"


# ──────────────────────────────────────────────────────────────────
# Help index — landing page with 5 topic cards
# ──────────────────────────────────────────────────────────────────


class TestHelpIndex(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _HELP / "index.jsx"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_uses_help_page_shell(self):
        self.assertIn("HelpPageShell", self.text)

    def test_links_to_all_five_topic_pages(self):
        for path in (
            "/help/getting-started",
            "/help/faq",
            "/help/troubleshooting",
            "/help/notifications",
            "/help/permit-renewal",
        ):
            self.assertIn(path, self.text, f"Missing link to {path}")

    def test_uses_design_system(self):
        # GlassCard for cards, useTheme for theme-awareness.
        self.assertIn("GlassCard", self.text)
        self.assertIn("useTheme", self.text)


# ──────────────────────────────────────────────────────────────────
# Per-topic help pages — each must use the shared shell + cover
# the spec-mandated topics.
# ──────────────────────────────────────────────────────────────────


def _read_help(slug):
    p = _HELP / f"{slug}.jsx"
    if not p.exists():
        return None, None
    return p, p.read_text(encoding="utf-8")


class TestHelpGettingStarted(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path, cls.text = _read_help("getting-started")

    def test_file_present(self):
        self.assertIsNotNone(self.path, "getting-started.jsx missing")

    def test_uses_shell(self):
        self.assertIn("HelpPageShell", self.text)

    def test_covers_spec_sections(self):
        for section in (
            "What does LeveLog monitor?",
            "How often is data refreshed?",
            "First steps",
            "Expected timeline",
            "What about my filing reps?",
        ):
            self.assertIn(section, self.text, f"Missing section: {section!r}")

    def test_mentions_15_min_dob_and_30_min_311(self):
        self.assertIn("15 minutes", self.text)
        self.assertIn("30 minutes", self.text)


class TestHelpFAQ(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path, cls.text = _read_help("faq")

    def test_file_present(self):
        self.assertIsNotNone(self.path)

    def test_covers_spec_questions(self):
        for q in (
            "311 complaint and a DOB violation",
            "severity level",
            "reduce email volume",
            "Why didn't I get notified",
            "What if my permit expires",
            "Does LeveLog file my renewals",
            "licensed individual",
            "multiple users to my company",
        ):
            self.assertIn(q, self.text, f"Missing FAQ: {q!r}")

    def test_renewal_answer_says_no_to_auto_filing(self):
        # The "Does LeveLog file my renewals?" answer must clearly
        # say no — this is the most-misunderstood part of v1 scope.
        self.assertIn("Renewals are filed manually", self.text)


class TestHelpTroubleshooting(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path, cls.text = _read_help("troubleshooting")

    def test_file_present(self):
        self.assertIsNotNone(self.path)

    def test_covers_spec_scenarios(self):
        for s in (
            "I'm not seeing signals",
            "I'm getting too many emails",
            "I'm not getting emails",
            "Activity feed is empty",
            "Wrong project address",
            '"(none)"',
        ):
            self.assertIn(s, self.text, f"Missing scenario: {s!r}")


class TestHelpNotifications(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path, cls.text = _read_help("notifications")

    def test_file_present(self):
        self.assertIsNotNone(self.path)

    def test_covers_three_presets(self):
        self.assertIn("Critical only", self.text)
        self.assertIn("Standard", self.text)
        self.assertIn("Everything", self.text)

    def test_covers_per_project_overrides_and_preview(self):
        self.assertIn("Per-project overrides", self.text)
        self.assertIn("Preview", self.text)

    def test_sms_disclaimer_present(self):
        self.assertIn("SMS", self.text)
        self.assertIn("v1.1 roadmap", self.text)


class TestHelpPermitRenewal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path, cls.text = _read_help("permit-renewal")

    def test_file_present(self):
        self.assertIsNotNone(self.path)

    def test_describes_manual_filing(self):
        self.assertIn("DOB NOW", self.text)
        self.assertIn("manually", self.text)

    def test_pw2_copy_values_documented(self):
        self.assertIn("PW2", self.text)
        self.assertIn("Job number", self.text)

    def test_status_indicators_documented(self):
        # The badge taxonomy from STATUS_CONFIG in permit-renewal.jsx.
        for status in (
            "Renewal Ready",
            "Insurance Required",
            "License Issue",
            "Manual Renewal",
            "Awaiting GC",
            "Completed",
        ):
            self.assertIn(status, self.text, f"Missing status: {status!r}")


# ──────────────────────────────────────────────────────────────────
# HelpPageShell shared component
# ──────────────────────────────────────────────────────────────────


class TestHelpPageShell(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "src" / "components" / "HelpPageShell.jsx"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists())

    def test_uses_design_system(self):
        # Shell uses the same chrome as the activity feed (B0.1) +
        # onboarding (B3): AnimatedBackground + GlassCard + useTheme.
        self.assertIn("AnimatedBackground", self.text)
        self.assertIn("GlassCard", self.text)
        self.assertIn("useTheme", self.text)

    def test_exports_helpers(self):
        # Sub-components used by every help page.
        for name in ("HelpSection", "HelpParagraph", "HelpBullets", "HelpKbd"):
            self.assertIn(f"export function {name}", self.text)

    def test_back_button_present(self):
        # Each shell instance has a back button so deep-linked
        # help pages can return somewhere sane.
        self.assertIn("ArrowLeft", self.text)
        self.assertIn("router.back()", self.text)


# ──────────────────────────────────────────────────────────────────
# Preset-radio tooltip delta from B3
# ──────────────────────────────────────────────────────────────────


class TestPresetRadioTooltips(unittest.TestCase):
    """Phase B4: tooltip on each preset radio explaining its
    specific behavior in 1-2 sentences. Wired in BOTH the settings
    page (where presets are managed long-term) and onboarding step 4
    (where presets are first chosen)."""

    def test_settings_notifications_uses_tooltip(self):
        path = _FRONTEND / "app" / "settings" / "notifications.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("InfoTooltip", text)
        # Tooltip uses preset.bodyHelp — the existing 1-2 sentence
        # behavior copy from the B1b.1 PRESETS object.
        self.assertIn("preset.bodyHelp", text)

    def test_onboarding_step4_uses_tooltip(self):
        path = _FRONTEND / "app" / "onboarding.jsx"
        text = path.read_text(encoding="utf-8")
        self.assertIn("InfoTooltip", text)
        self.assertIn("preset.bodyHelp", text)


# ──────────────────────────────────────────────────────────────────
# Internal ops runbook
# ──────────────────────────────────────────────────────────────────


class TestInternalOpsRunbook(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "docs" / "operations" / "runbook.md"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present_at_correct_location(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_covers_all_eight_sections(self):
        for section in (
            "How to handle email-flood incidents",
            "How to investigate a customer issue",
            "How to add a new signal_kind",
            "How to debug DOB API failures",
            "Production deploy",
            "Database migration",
            "Audit script",
            "Onboarding flow",
        ):
            self.assertIn(section, self.text, f"Missing section: {section!r}")

    def test_kill_switch_documented(self):
        # The kill switch is the rip-cord for an email flood — must
        # be documented prominently with the env-var name.
        self.assertIn("NOTIFICATIONS_KILL_SWITCH", self.text)
        self.assertIn("Railway", self.text)

    def test_audit_script_path_documented(self):
        self.assertIn("backend/scripts/audit_production.py", self.text)

    def test_signal_kind_workflow_documented(self):
        # Adding a kind touches lib/notification_preferences,
        # classifier, templates, FE help copy, FE presets.
        self.assertIn("notification_preferences.py", self.text)
        self.assertIn("dob_signal_classifier.py", self.text)
        self.assertIn("dob_signal_templates.py", self.text)
        self.assertIn("signalKindHelp.js", self.text)

    def test_onboarding_debug_documented(self):
        # Manual completion + reset patterns for stuck users.
        self.assertIn('onboarding_step: "completed"', self.text)
        self.assertIn("Manual completion", self.text)


if __name__ == "__main__":
    unittest.main()
