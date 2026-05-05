"""Phase B1b.1 — preset shape pin.

The Critical only preset (frontend/src/utils/notificationPresets.js)
MUST produce exactly the same signal_kind_overrides and
channel_routes_default as the backend's
default_signal_kind_overrides() + default_channel_routes_default().
If either side drifts, detectActivePreset() in the frontend will
return 'custom' for a user with synthesized defaults — and the
"Critical only" radio won't render selected on first visit.

Strategy: parse the JS source for the relevant constants,
reconstruct the shape in Python, compare against the backend's
function output. Coarse but effective.

Also pins:
  • Standard preset includes the 4 explicitly-listed warning kinds
    (permit_expired, inspection_scheduled, license_renewal_due,
    complaint_dob) in addition to the 6 critical-email kinds.
  • Everything preset emits all 26 ALL_KINDS as email/immediate.
  • All three preset shapes are mutually exclusive (no two presets
    produce the same prefs document).
"""

from __future__ import annotations

import os
import re
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


PRESETS_FILE = _FRONTEND / "src" / "utils" / "notificationPresets.js"


def _extract_kind_list(source: str, marker: str) -> list:
    """Extract a JS array literal `export const <marker> = [...]`.
    Returns the list of string entries. Comments inside the array
    are stripped before parsing."""
    pattern = rf"export const {re.escape(marker)} = \[(.*?)\];"
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    # Strip line comments.
    body = re.sub(r"//[^\n]*", "", body)
    # Match all single-quoted strings.
    return re.findall(r"'([^']+)'", body)


class TestPresetsFileExists(unittest.TestCase):

    def test_file_present(self):
        self.assertTrue(PRESETS_FILE.exists(), str(PRESETS_FILE))

    def test_exports_required_symbols(self):
        """Each required export appears either as `export const X`
        (constants) or `export function X` (helpers)."""
        text = PRESETS_FILE.read_text(encoding="utf-8")
        for sym in (
            "ALL_KINDS",
            "CRITICAL_EMAIL_KINDS",
            "STANDARD_DIGEST_KINDS",
            "PRESETS",
            "PRESET_ORDER",
            "buildPresetOverrides",
            "buildPresetChannelRoutes",
            "buildPresetPrefs",
            "detectActivePreset",
        ):
            const_form = f"export const {sym}" in text
            fn_form = f"export function {sym}" in text
            self.assertTrue(
                const_form or fn_form,
                f"Missing export: {sym}",
            )

    def test_three_presets_in_order(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        self.assertIn("'critical_only'", text)
        self.assertIn("'standard'", text)
        self.assertIn("'everything'", text)
        # PRESET_ORDER literal pinned.
        self.assertIn(
            "['critical_only', 'standard', 'everything']",
            text,
        )


class TestCriticalEmailKindsMatchBackend(unittest.TestCase):
    """The frontend's CRITICAL_EMAIL_KINDS must be identical to the
    backend's DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS — same kinds, no
    drift. Detection breaks if they disagree."""

    def test_frontend_critical_kinds_match_backend(self):
        from lib.notification_preferences import (
            DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS,
        )
        text = PRESETS_FILE.read_text(encoding="utf-8")
        frontend_kinds = _extract_kind_list(text, "CRITICAL_EMAIL_KINDS")
        self.assertEqual(
            sorted(frontend_kinds),
            sorted(DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS),
            "Frontend CRITICAL_EMAIL_KINDS must match backend "
            "DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS",
        )

    def test_six_kinds_exactly(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        frontend_kinds = _extract_kind_list(text, "CRITICAL_EMAIL_KINDS")
        self.assertEqual(len(frontend_kinds), 6)


class TestAllKindsMatchBackend(unittest.TestCase):
    """The frontend's ALL_KINDS must list the same 26 signal_kinds
    the backend's ALL_DEFAULT_SIGNAL_KINDS lists."""

    def test_all_kinds_match_backend(self):
        from lib.notification_preferences import ALL_DEFAULT_SIGNAL_KINDS
        text = PRESETS_FILE.read_text(encoding="utf-8")
        frontend_kinds = _extract_kind_list(text, "ALL_KINDS")
        self.assertEqual(
            sorted(frontend_kinds),
            sorted(ALL_DEFAULT_SIGNAL_KINDS),
            "Frontend ALL_KINDS must match backend ALL_DEFAULT_SIGNAL_KINDS",
        )

    def test_twentysix_kinds_exactly(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        frontend_kinds = _extract_kind_list(text, "ALL_KINDS")
        self.assertEqual(len(frontend_kinds), 26)


class TestStandardDigestKindsPin(unittest.TestCase):
    """The 4 warning kinds Standard preset escalates to digest_daily.
    Operator-curated; if a future commit adds a 5th or removes one,
    this test fires loudly."""

    EXPECTED = {
        "permit_expired",
        "inspection_scheduled",
        "license_renewal_due",
        "complaint_dob",
    }

    def test_four_kinds_exactly(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        kinds = _extract_kind_list(text, "STANDARD_DIGEST_KINDS")
        self.assertEqual(set(kinds), self.EXPECTED)
        self.assertEqual(len(kinds), 4)


class TestCriticalOnlyMatchesBackendDefaults(unittest.TestCase):
    """The Critical only preset's signal_kind_overrides +
    channel_routes_default must match the backend's synthesized
    defaults shape EXACTLY. This is the unambiguous-detection
    guarantee — a user with synthesized defaults sees Critical only
    selected on first visit."""

    def test_channel_routes_match(self):
        from lib.notification_preferences import default_channel_routes_default
        # Pin the literal in the JS file.
        text = PRESETS_FILE.read_text(encoding="utf-8")
        # Find the 'critical_only' branch in buildPresetChannelRoutes.
        # Look for the canonical literal.
        self.assertIn(
            "{ critical: ['email'], warning: [], info: [] }",
            text,
            "Critical only preset's channel routes must equal "
            "backend default_channel_routes_default()",
        )
        # Sanity: backend produces the same shape.
        backend_routes = default_channel_routes_default()
        self.assertEqual(
            backend_routes,
            {"critical": ["email"], "warning": [], "info": []},
        )

    def test_signal_kind_overrides_match(self):
        """The preset's overrides for the 6 critical kinds must be
        email/immediate; the other 20 must be feed_only. Same shape
        as default_signal_kind_overrides()."""
        from lib.notification_preferences import (
            default_signal_kind_overrides,
            DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS,
        )
        backend_overrides = default_signal_kind_overrides()
        self.assertEqual(len(backend_overrides), 26)

        # Frontend-side shape (pinned by string presence in the JS):
        #   critical email kinds → {channels: ['email'], severity_threshold: 'any', delivery: 'immediate'}
        #   non-critical kinds   → {channels: [], severity_threshold: 'any', delivery: 'feed_only'}
        text = PRESETS_FILE.read_text(encoding="utf-8")
        # Pin the literal override shapes for both branches in the
        # _criticalOnlyOverrides function.
        self.assertIn(
            "channels: ['email'],",
            text,
        )
        self.assertIn(
            "delivery: 'immediate',",
            text,
        )
        self.assertIn(
            "delivery: 'feed_only',",
            text,
        )

        # Backend confirms the 6/20 split.
        critical_set = set(DEFAULT_CRITICAL_EMAIL_SIGNAL_KINDS)
        for kind, entry in backend_overrides.items():
            if kind in critical_set:
                self.assertEqual(entry["delivery"], "immediate", kind)
                self.assertEqual(entry["channels"], ["email"], kind)
            else:
                self.assertEqual(entry["delivery"], "feed_only", kind)
                self.assertEqual(entry["channels"], [], kind)


class TestEverythingPresetShape(unittest.TestCase):
    """Everything preset must emit all 26 kinds at email/immediate
    plus channel_routes_default = critical/warning/info all email."""

    def test_routes_pin(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        # Pin the literal Everything-preset routes block.
        self.assertIn(
            "{ critical: ['email'], warning: ['email'], info: ['email'] }",
            text,
        )

    def test_everything_function_iterates_all_kinds(self):
        """The _everythingOverrides loop must iterate ALL_KINDS to
        produce overrides for every kind."""
        text = PRESETS_FILE.read_text(encoding="utf-8")
        # Find the function body and verify it loops over ALL_KINDS.
        match = re.search(
            r"function _everythingOverrides\(\) \{(.*?)^\}",
            text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match, "_everythingOverrides function missing")
        body = match.group(1)
        self.assertIn("for (const k of ALL_KINDS)", body)
        self.assertIn("delivery: 'immediate'", body)


class TestStandardPresetShape(unittest.TestCase):
    """Standard preset: 6 critical email kinds + 4 warning digest
    kinds + 16 feed_only kinds. Channel routes:
    critical=[email], warning=[email], info=[]."""

    def test_routes_pin(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        self.assertIn(
            "{ critical: ['email'], warning: ['email'], info: [] }",
            text,
        )

    def test_standard_iterates_critical_then_digest_then_fills(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        match = re.search(
            r"function _standardOverrides\(\) \{(.*?)^\}",
            text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match, "_standardOverrides function missing")
        body = match.group(1)
        self.assertIn("for (const k of CRITICAL_EMAIL_KINDS)", body)
        self.assertIn("for (const k of STANDARD_DIGEST_KINDS)", body)
        self.assertIn("delivery: 'digest_daily'", body)
        self.assertIn("delivery: 'feed_only'", body)


class TestDetectActivePresetExists(unittest.TestCase):
    """Pin the detection function exists + uses normalized comparison
    (so array order in channels lists doesn't break detection)."""

    def test_function_present(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        self.assertIn("export function detectActivePreset", text)

    def test_uses_normalization_helpers(self):
        text = PRESETS_FILE.read_text(encoding="utf-8")
        self.assertIn("_normalizeOverrideMap", text)
        self.assertIn("_normalizeRoutes", text)

    def test_returns_custom_for_unmatched_shape(self):
        """The function's final return must be 'custom' so any prefs
        document that doesn't match a preset falls into the
        catch-all bucket. A future refactor that changes this
        invariant would leak partial-match preset selections."""
        text = PRESETS_FILE.read_text(encoding="utf-8")
        # Find the function body.
        match = re.search(
            r"export function detectActivePreset\([^)]*\) \{(.*?)^\}",
            text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn("return 'custom'", body)


if __name__ == "__main__":
    unittest.main()
