"""Phase B1b — frontend invariants pinned via static-file checks.

We don't have a JSX test runner wired into the Python test suite.
The closest thing we can do is read the source files + assert key
contracts hold:

  • The notifications page exists at the expected Expo Router path.
  • The page imports the constants module + the API client.
  • The page calls the three relevant endpoints.
  • The page renders the SMS toggle as disabled (not a working
    channel today).
  • The constants module exports all 25 signal_kinds across 9
    families — matching the classifier in
    lib/dob_signal_classifier.py.
  • settings.jsx links to the new /settings/notifications route.

These pins fire when a future commit accidentally removes a piece
of the wiring without testing it. They are NOT a substitute for
actually loading the page in a browser; they catch the cheap
regressions.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_FRONTEND = _REPO / "frontend"

sys.path.insert(0, str(_BACKEND))


PREFS_PAGE = _FRONTEND / "app" / "settings" / "notifications.jsx"
SETTINGS_PAGE = _FRONTEND / "app" / "settings.jsx"
SIGNAL_KINDS_CONST = _FRONTEND / "src" / "constants" / "signalKinds.js"


class TestPreferencesPageExists(unittest.TestCase):

    def test_file_present(self):
        self.assertTrue(PREFS_PAGE.exists(), str(PREFS_PAGE))

    def test_imports_constants_module(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("from '../../src/constants/signalKinds'", text)

    def test_imports_api_client(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("from '../../src/utils/api'", text)

    def test_calls_get_my_preferences(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("/api/users/me/notification-preferences", text)

    def test_calls_recent_signals(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("/api/users/me/recent-signals", text)


class TestSmsRenderedAsDisabled(unittest.TestCase):
    """SMS is a schema placeholder in B1a (no real backend). The UI
    must label it disabled / "coming soon" so we don't promise a
    delivery channel we can't honor."""

    def test_sms_channel_disabled_in_constant_list(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        # The SMS row in CHANNEL_TOGGLES must be enabled: false.
        # Anchored on the literal toggle entry shape so a refactor
        # that flips it surfaces here.
        self.assertIn("key: 'sms'", text)
        # The disabled-flag context is a few lines below the key
        # in CHANNEL_TOGGLES; we look for the combination across
        # a small window.
        sms_idx = text.find("key: 'sms'")
        self.assertGreater(sms_idx, 0)
        sms_window = text[sms_idx:sms_idx + 200]
        self.assertIn("enabled: false", sms_window)


class TestSettingsNavLink(unittest.TestCase):

    def test_settings_page_links_to_notifications(self):
        text = SETTINGS_PAGE.read_text(encoding="utf-8")
        self.assertIn("router.push('/settings/notifications')", text)


class TestSignalKindsConstants(unittest.TestCase):
    """The constants file is the single source of truth for the UI's
    signal taxonomy. Pin all 26 kinds + 9 families so a typo in a
    future edit fails this test rather than silently missing a row
    on the settings page. (The Phase B1b spec header said "~25";
    the explicit family list expanded to 26.)"""

    EXPECTED_KEYS = {
        # permits
        "permit_issued", "permit_expired", "permit_revoked", "permit_renewed",
        # filings
        "filing_approved", "filing_disapproved", "filing_withdrawn", "filing_pending",
        # violations
        "violation_dob", "violation_ecb", "violation_resolved",
        # swo
        "stop_work_full", "stop_work_partial",
        # complaints
        "complaint_dob", "complaint_311",
        # inspections
        "inspection_scheduled", "inspection_passed", "inspection_failed", "final_signoff",
        # cofo
        "cofo_temporary", "cofo_final", "cofo_pending",
        # compliance filings
        "facade_fisp", "boiler_inspection", "elevator_inspection",
        # license renewals
        "license_renewal_due",
    }

    EXPECTED_FAMILIES = {
        "permits", "filings", "violations", "swo", "complaints",
        "inspections", "cofo", "compliance_filings", "license_renewals",
    }

    def test_file_present(self):
        self.assertTrue(SIGNAL_KINDS_CONST.exists(), str(SIGNAL_KINDS_CONST))

    def test_all_expected_signal_kinds_present(self):
        text = SIGNAL_KINDS_CONST.read_text(encoding="utf-8")
        for key in self.EXPECTED_KEYS:
            self.assertIn(
                f"key: '{key}'", text,
                f"signal_kind {key!r} missing from signalKinds.js",
            )

    def test_all_expected_families_present(self):
        text = SIGNAL_KINDS_CONST.read_text(encoding="utf-8")
        for fam in self.EXPECTED_FAMILIES:
            self.assertIn(
                f"key: '{fam}'", text,
                f"family {fam!r} missing from signalKinds.js",
            )

    def test_kind_count_matches(self):
        # Count `key: '<kind>'` occurrences inside the SIGNAL_FAMILIES
        # block. This is a coarse pin — a future refactor that uses
        # a different shape needs to update the test, but it catches
        # accidental drops.
        text = SIGNAL_KINDS_CONST.read_text(encoding="utf-8")
        # Count occurrences of "key: '" inside signal kind entries.
        # Each family + each kind contributes one. 9 families + 26
        # kinds = 35 expected.
        n = text.count("key: '")
        self.assertEqual(
            n, 9 + 26,
            f"Expected 35 'key: ...' entries (9 families + 26 kinds); found {n}",
        )


class TestPreferencesPageStructure(unittest.TestCase):
    """Pins the high-level structure described in the spec."""

    def test_page_has_save_handler(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("const handleSave", text)

    def test_page_has_reset_unsaved_handler(self):
        """B1b.1 — Reset to last-saved (the dirty-edits revert).
        Distinct from Reset to anchor preset, which uses
        handleResetToAnchor below."""
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("const handleResetUnsaved", text)

    def test_page_has_dirty_tracking(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        # The dirty flag is what enables/disables the Save button.
        # A future refactor that drops it (and always-enables Save)
        # would silently re-introduce the "user clicks save with no
        # changes" UX bug.
        self.assertIn("const dirty = useMemo", text)

    def test_page_has_mobile_breakpoint(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("MOBILE_BREAKPOINT", text)
        self.assertIn("isMobile", text)


# ── B1b.1 progressive-disclosure structure ────────────────────────


class TestProgressiveDisclosure(unittest.TestCase):
    """Pins the B1b.1 layout: preset radio cards + collapsible
    advanced section + Reset-to-anchor flow."""

    def test_page_imports_presets_module(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("from '../../src/utils/notificationPresets'", text)

    def test_page_uses_detect_active_preset(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("detectActivePreset", text)

    def test_page_uses_build_preset_prefs(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("buildPresetPrefs", text)

    def test_page_renders_preset_cards(self):
        """The PresetRadioCard component renders one card per preset
        in PRESET_ORDER."""
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("PresetRadioCard", text)
        self.assertIn("PRESET_ORDER.map", text)

    def test_page_has_anchor_preset_state(self):
        """anchorPreset is the user's intended preset; drives the
        Reset-to-<preset> link inside Advanced even after the user
        customizes per-signal settings."""
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("anchorPreset", text)
        self.assertIn("setAnchorPreset", text)

    def test_page_has_handle_preset_select(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("const handlePresetSelect", text)

    def test_page_has_handle_reset_to_anchor(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("const handleResetToAnchor", text)

    def test_page_has_advanced_section_state(self):
        """Advanced section is collapsible. Closed by default
        unless live preset is custom (handled in load callback)."""
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("advancedOpen", text)
        self.assertIn("setAdvancedOpen", text)

    def test_page_has_customize_link(self):
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("Customize per signal type", text)

    def test_page_has_simplified_title(self):
        """Header copy update — 'Choose how we notify you' replaces
        the wordier 'Notification Preferences' for the in-page H1."""
        text = PREFS_PAGE.read_text(encoding="utf-8")
        self.assertIn("Choose how we notify you", text)


if __name__ == "__main__":
    unittest.main()
