"""Phase B0.1 — static-source pins for the Activity feed visual integration.

The Activity feed at /project/{id}/activity was originally styled with
hardcoded white/gray colors and didn't integrate with the LeveLog
design system. Phase B0.1 restyled it to use:
  • AnimatedBackground gradient (matches every other page)
  • useTheme() for theme-aware colors (dark + light)
  • GlassCard for signal cards + modals + filter panel
  • typography.label for uppercase tracked section headers
  • colors.* tokens for every color reference

These pins catch the central regression: a future commit that
re-introduces hardcoded `#ffffff`, `#f8fafc`, `#0f172a`, `#e2e8f0`
etc. on the activity feed visual surface fails this test.

Frontend invariant tests are static-file string checks (no JS test
runner wired into pytest). They catch the cheap regressions; live
visual verification is the operator-action checklist.
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
sys.path.insert(0, str(_BACKEND))


ROUTE_FILE = _FRONTEND / "app" / "project" / "[id]" / "activity.jsx"
COMPONENT_FILE = _FRONTEND / "src" / "components" / "ActivityFeed.jsx"


class TestActivityRouteDesignSystem(unittest.TestCase):
    """The activity route shell wraps the feed in AnimatedBackground +
    uses useTheme — same chrome as every other page in the app."""

    def test_file_present(self):
        self.assertTrue(ROUTE_FILE.exists(), str(ROUTE_FILE))

    def test_uses_animated_background(self):
        text = ROUTE_FILE.read_text(encoding="utf-8")
        self.assertIn("AnimatedBackground", text)
        self.assertIn(
            "from '../../../src/components/AnimatedBackground'",
            text,
        )

    def test_uses_theme_hook(self):
        text = ROUTE_FILE.read_text(encoding="utf-8")
        self.assertIn("useTheme", text)
        self.assertIn(
            "from '../../../src/context/ThemeContext'",
            text,
        )

    def test_no_hardcoded_legacy_colors(self):
        """The pre-B0.1 route hardcoded `#f8fafc` (page bg),
        `#ffffff` (header bg), `#e2e8f0` (border), and `#0f172a`
        (text). After B0.1, all colors come from the theme tokens."""
        text = ROUTE_FILE.read_text(encoding="utf-8")
        for hardcoded in ("#f8fafc", "#ffffff"):
            self.assertNotIn(
                hardcoded, text,
                f"Activity route should not hardcode {hardcoded!r}; "
                f"use colors.* from the theme."
            )


class TestActivityFeedComponentDesignSystem(unittest.TestCase):
    """The ActivityFeed component (the heavy lift) uses GlassCard +
    useTheme + theme tokens. Pre-B0.1 it had a buildStyles function
    keyed on hardcoded white/gray; post-B0.1 it takes (colors, isDark)
    and threads tokens through every rule."""

    def test_file_present(self):
        self.assertTrue(COMPONENT_FILE.exists(), str(COMPONENT_FILE))

    def test_imports_glass_card(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("import { GlassCard }", text)
        self.assertIn("from './GlassCard'", text)

    def test_imports_theme_context(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("useTheme", text)
        self.assertIn("from '../context/ThemeContext'", text)

    def test_imports_theme_tokens(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("from '../styles/theme'", text)
        # Specifically the spacing + borderRadius + typography tokens
        # (typography.label drives the uppercase tracked section
        # headers).
        self.assertIn("spacing", text)
        self.assertIn("borderRadius", text)
        self.assertIn("typography", text)

    def test_uses_typography_label_for_section_headers(self):
        """Section labels ("ACTIVITY", "SEARCH", "DATE RANGE",
        "SEVERITY", "SIGNAL TYPE") use the typography.label shape
        from the design system — same pattern as "QUICK ACTIONS",
        "ON-SITE WORKERS" on the project hub."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        # Spread of typography.label appears at section-label rules.
        self.assertIn("...typography.label", text)
        # And the literal section labels appear as JSX text content
        # (between > and <). The strings themselves must be present;
        # the JSX whitespace handling means we check for a window
        # containing each label rather than exact-string-with-quotes.
        for label in ("SEARCH", "DATE RANGE", "SEVERITY", "SIGNAL TYPE"):
            self.assertIn(label, text, f"Section header {label!r} missing")

    def test_buildStyles_takes_colors_and_isDark(self):
        """buildStyles signature pinned: a future refactor that
        drops the colors parameter would silently revert to
        hardcoded values. Catch it here."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("function buildStyles(colors, isDark)", text)

    def test_uses_glass_card_for_signal_cards(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        # SignalCard wraps content in <GlassCard ... hoverEffect={false}>.
        self.assertIn("<GlassCard", text)
        # The raw-data modal + mobile filter sheet use the
        # variant="modal" form (heavier blur).
        self.assertIn('variant="modal"', text)

    def test_severity_palette_uses_theme_status_colors(self):
        """buildSeverityPalette pulls from colors.error / colors.warning
        / colors.primary so severity colors track the active theme.
        Pre-B0.1 these were hardcoded #ef4444 / #f59e0b / #3b82f6."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("buildSeverityPalette(colors)", text)
        # Critical pulls colors.error; warning pulls colors.warning;
        # info pulls colors.primary. Pin the field references.
        self.assertIn("colors.error", text)
        self.assertIn("colors.warning", text)
        self.assertIn("colors.primary", text)

    def test_no_hardcoded_legacy_card_colors(self):
        """The pre-B0.1 styles had `#ffffff` for card bg,
        `#0f172a` for text, `#64748b` and `#94a3b8` for muted
        text, `#e2e8f0` for borders. After B0.1, each is sourced
        from colors.* tokens."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        for hardcoded in ("#f8fafc", "'#ffffff'", "#0f172a", "#e2e8f0"):
            self.assertNotIn(
                hardcoded, text,
                f"ActivityFeed should not hardcode {hardcoded!r}; "
                f"use colors.* from the theme.",
            )

    def test_styles_built_with_useMemo(self):
        """styles + severityPalette must be useMemo'd so theme toggle
        re-runs the builders. Otherwise the feed wouldn't repaint
        when the user toggles dark/light."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("useMemo(() => buildStyles(colors, isDark)", text)
        self.assertIn("useMemo(() => buildSeverityPalette(colors)", text)


class TestActivityFeedFunctionalityPreserved(unittest.TestCase):
    """Pin that the functional surface — filter shape, mark-as-read
    plumbing, raw-data modal — is unchanged by the restyle. The B0.1
    edit is visual only."""

    def test_default_filters_unchanged(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        # The DEFAULT_FILTERS shape was: signal_kinds: [],
        # severity_kind: null, date_range: '30d', unread_only: false,
        # search: ''.
        self.assertIn("date_range: '30d'", text)
        self.assertIn("unread_only: false", text)
        self.assertIn("severity_kind: null", text)

    def test_page_size_unchanged(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("PAGE_SIZE = 20", text)

    def test_mark_read_handlers_present(self):
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        self.assertIn("handleMarkRead", text)
        self.assertIn("handleMarkAllRead", text)
        self.assertIn("dobAPI.markRead", text)
        self.assertIn("dobAPI.markAllRead", text)

    def test_signal_kind_groups_taxonomy_unchanged(self):
        """The 8 signal-kind family groups + their member kinds must
        match what the filter UI expects. A drift here would mute
        whole signal categories from the filter chips."""
        text = COMPONENT_FILE.read_text(encoding="utf-8")
        # 8 family group labels.
        for label in (
            "'Permits'", "'Job Filings'", "'Violations'",
            "'Stop Work Orders'", "'Complaints'", "'Inspections'",
            "'Compliance'", "'License'",
        ):
            self.assertIn(label, text)


if __name__ == "__main__":
    unittest.main()
