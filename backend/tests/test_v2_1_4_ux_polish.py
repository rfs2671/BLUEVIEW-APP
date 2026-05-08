"""Phase V2.1.4 — UX polish tests.

Pin every contract the V2.1.4 polish promises:

  • Navbar pill (FloatingNav) sizes to content. The pre-V2.1.4
    `width: '100%'` made the pill stretch the full container
    width and left visible empty space after the last nav item.
    Test asserts the new sizing rule is in source.
  • RiskScoreCircle now renders THREE text elements:
      - Title "DOB Risk Score" above the circle (always present,
        in every state — score / loading / no-score).
      - Score number inside the circle (existing behavior).
      - Band word below the circle: "LOW RISK" / "MODERATE RISK"
        / "HIGH RISK" / "CRITICAL RISK" matching the band, OR
        "PENDING" when there's no score yet.
    Color-band mapping must match backend
    lib/risk_score/schema.py::score_band exactly.
  • RiskScoreDrawer header reads "DOB Risk Score" so the drawer
    visually continues the gauge the operator just clicked.
    The drawer body shows the same band-word ("LOW RISK" etc.)
    prominently below the score.
  • Static-source pins catch accidental removal of the title or
    band-word constants.
  • All 1165 prior tests pass byte-for-byte.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from lib.risk_score import schema as rs_schema  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# Navbar pill width
# ──────────────────────────────────────────────────────────────────


class TestFloatingNavPillSizing(unittest.TestCase):
    """Pre-V2.1.4 the FloatingNav `innerContainer` had
    `width: '100%'` which stretched the pill to fill the full
    container width — leaving visible empty space after the
    "Settings" item. V2.1.4 swaps to `alignSelf: 'center'` so
    the pill sizes to its content."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "FloatingNav.js"
        )
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_inner_container_does_not_force_full_width(self):
        # Locate the innerContainer style block and assert it
        # does NOT contain the old `width: '100%'` rule on a
        # non-comment line. That is the rule that caused the
        # visual empty-space issue. We strip comments before
        # checking so the V2.1.4 explanation comment (which
        # references the old rule by name) doesn't false-fire.
        idx = self.text.find("innerContainer:")
        self.assertGreater(idx, 0, "innerContainer style missing")
        end = self.text.find("},", idx)
        block = self.text[idx:end]
        non_comment_lines = [
            ln for ln in block.splitlines()
            if not ln.strip().startswith("//")
        ]
        non_comment_block = "\n".join(non_comment_lines)
        self.assertNotIn(
            "width: '100%'", non_comment_block,
            "innerContainer should not force full width post-V2.1.4",
        )

    def test_inner_container_uses_align_self_center(self):
        # The replacement must use alignSelf:'center' so the
        # parent's alignItems:'center' centers the pill while
        # letting it size to content.
        idx = self.text.find("innerContainer:")
        end = self.text.find("},", idx)
        block = self.text[idx:end]
        self.assertIn(
            "alignSelf: 'center'", block,
            "innerContainer must use alignSelf:'center' to size to content",
        )

    def test_max_width_preserved(self):
        # The maxWidth:700 cap is the safety net for very wide
        # viewports — keep it so the pill doesn't span ultrawide
        # monitors if a future spec adds a 7th nav item.
        idx = self.text.find("innerContainer:")
        end = self.text.find("},", idx)
        block = self.text[idx:end]
        self.assertIn("maxWidth: 700", block)


# ──────────────────────────────────────────────────────────────────
# RiskScoreCircle labels
# ──────────────────────────────────────────────────────────────────


class TestRiskScoreCircleTitle(unittest.TestCase):
    """V2.1.4 added a "DOB Risk Score" title above the circle so
    new users know what the number means without having to
    interpret an unlabeled gauge."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_title_constant_exported(self):
        # The title is a named export so the drawer can reuse the
        # exact same string. Pin the export AND the literal value.
        self.assertIn(
            "export const RISK_SCORE_TITLE = 'DOB Risk Score';",
            self.text,
        )

    def test_title_rendered_in_jsx(self):
        # The title <Text>{RISK_SCORE_TITLE}</Text> renders the
        # constant. The exact ">{RISK_SCORE_TITLE}<" closing
        # boundary distinguishes the JSX render from the
        # template-literal `${RISK_SCORE_TITLE}` used in the
        # accessibility label.
        self.assertIn(">\n          {RISK_SCORE_TITLE}\n        </Text>",
                      self.text)

    def test_title_uses_muted_color(self):
        # The title sits above the score number; muted color
        # ensures the score itself is the focal element.
        # Find the JSX render of the title (not the accessibility-
        # label template literal) and assert its color binding.
        marker = ">\n          {RISK_SCORE_TITLE}\n        </Text>"
        idx = self.text.find(marker)
        self.assertGreater(idx, 0, "title JSX render not found")
        # Walk back to the opening <Text and check the style prop.
        # 320 chars covers the inline style array.
        chunk = self.text[max(0, idx - 320): idx]
        self.assertIn("colors.text.muted", chunk,
                      "title color should be colors.text.muted")


class TestRiskScoreCircleBandWords(unittest.TestCase):
    """The band word now reads as a verdict — "LOW RISK" /
    "MODERATE RISK" / etc. — instead of the abbreviation the
    operator's compliance staff had to learn."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def _band_label_for(self, score):
        """Re-implement the FE band-label mapping in Python by
        scraping the BAND_* constants. Catches drift between the
        file as actually shipped and the test's expectation."""
        bands = {}
        for name in ("BAND_GREEN", "BAND_YELLOW", "BAND_ORANGE", "BAND_RED"):
            m = re.search(
                rf"const\s+{name}\s*=\s*\{{[^}}]*label:\s*'([^']+)'",
                self.text,
            )
            self.assertIsNotNone(m, f"{name} not found")
            bands[name] = m.group(1)
        # Map by backend's band classification.
        be_band = rs_schema.score_band(score)
        return bands["BAND_" + be_band.upper()]

    def test_band_label_low_risk(self):
        # All values that the backend classifies as green should
        # produce "LOW RISK" on the FE.
        for v in (0, 1, 15, 29, 30):
            self.assertEqual(self._band_label_for(v), "LOW RISK")

    def test_band_label_moderate_risk(self):
        for v in (31, 45, 60):
            self.assertEqual(self._band_label_for(v), "MODERATE RISK")

    def test_band_label_high_risk(self):
        for v in (61, 70, 80):
            self.assertEqual(self._band_label_for(v), "HIGH RISK")

    def test_band_label_critical_risk(self):
        for v in (81, 90, 99, 100):
            self.assertEqual(self._band_label_for(v), "CRITICAL RISK")

    def test_band_word_color_matches_band_fg(self):
        # The band word renders in the band's foreground color.
        # Pinned via the inline style binding `color: bandWordColor`
        # which resolves to `band.fg` when there's a score.
        self.assertIn("color: bandWordColor", self.text)
        # And bandWordColor is `fgColor` when hasScore is true,
        # `colors.text.muted` otherwise. Pin both branches.
        m = re.search(
            r"const\s+bandWordColor\s*=\s*hasScore\s*\?\s*([^:]+)\s*:\s*([^;]+);",
            self.text,
        )
        self.assertIsNotNone(m, "bandWordColor ternary not found")
        self.assertIn("fgColor", m.group(1))
        self.assertIn("colors.text.muted", m.group(2))


class TestRiskScoreCircleNoScoreState(unittest.TestCase):
    """No-score-yet state: title still visible, circle shows em
    dash, band word reads "PENDING" in muted gray."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_pending_constant_exported(self):
        self.assertIn(
            "export const PENDING_LABEL = 'PENDING';",
            self.text,
        )

    def test_em_dash_present(self):
        # The circle's render branch for no-score uses the em
        # dash literal. Already pinned in V2.1.2; pin it here
        # too so the polish phase can't accidentally drop it.
        self.assertIn("—", self.text)

    def test_pending_used_in_band_word_branch(self):
        # The band-word ternary uses PENDING_LABEL when there's
        # no score AND we're not still loading.
        self.assertIn("PENDING_LABEL", self.text)
        # And specifically it appears in the bandWordText
        # ternary branch.
        m = re.search(
            r"bandWordText\s*=\s*hasScore\s*\?[^:]+:\s*\(loading\s*\?[^:]+:\s*([A-Za-z_]+)\)",
            self.text,
        )
        self.assertIsNotNone(m, "bandWordText ternary not found")
        self.assertEqual(m.group(1), "PENDING_LABEL")


class TestRiskScoreCircleLoadingState(unittest.TestCase):
    """Loading state: title still visible, circle shows ellipsis,
    band-word area is empty (no flicker between PENDING and the
    real label)."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_loading_branch_returns_empty_band_word(self):
        # bandWordText: hasScore ? band.label : (loading ? '' : PENDING_LABEL)
        # Pin the empty-string loading branch.
        m = re.search(
            r"bandWordText\s*=\s*hasScore\s*\?[^:]+:\s*\(loading\s*\?\s*'([^']*)'",
            self.text,
        )
        self.assertIsNotNone(m, "loading branch of bandWordText not found")
        self.assertEqual(m.group(1), "",
                         "loading state should produce empty band word")


class TestRiskScoreCircleResponsiveFonts(unittest.TestCase):
    """Compact font sizes for small (project-list, size=56)
    circles; larger fonts for the project-header (size=84)
    circle. Mobile gets the small variant via the same `compact`
    variable so we don't need a separate breakpoint."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_compact_threshold_present(self):
        self.assertIn("const compact = size < 70;", self.text)

    def test_title_font_compact_smaller(self):
        # titleFontSize: compact ? 9 : 11
        self.assertIn(
            "const titleFontSize    = compact ? 9  : 11;", self.text,
        )

    def test_band_word_font_compact_smaller(self):
        # bandWordFontSize: compact ? 8 : 10
        self.assertIn(
            "const bandWordFontSize = compact ? 8  : 10;", self.text,
        )


# ──────────────────────────────────────────────────────────────────
# RiskScoreDrawer header + body band word
# ──────────────────────────────────────────────────────────────────


class TestRiskScoreDrawerHeader(unittest.TestCase):
    """Drawer header now reads "DOB Risk Score" matching the
    circle's title — visual continuity from gauge → drawer."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreDrawer.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_imports_title_constant(self):
        # The drawer reuses the exact title constant from the
        # circle so a future rename auto-propagates.
        self.assertIn(
            "import { bandFor, RISK_SCORE_TITLE } from './RiskScoreCircle';",
            self.text,
        )

    def test_header_renders_title_constant(self):
        # The header <Text> uses the constant, uppercased.
        self.assertIn("RISK_SCORE_TITLE.toUpperCase()", self.text)

    def test_header_no_longer_renders_old_label(self):
        # The pre-V2.1.4 header read "RISK SCORE · LOW" /
        # "RISK SCORE · MODERATE" / etc. as a single string. The
        # new header is just the title; the band word moves to
        # a prominent line under the score number below.
        self.assertNotIn(
            "RISK SCORE${band ? ` · ${band.label}` : ''}",
            self.text,
        )


class TestRiskScoreDrawerBandWord(unittest.TestCase):
    """The drawer body now shows the band word ("LOW RISK" /
    "MODERATE RISK" / …) as a prominent line below the big score
    number, matching the circle's band word for visual
    continuity."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreDrawer.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_band_word_jsx_present(self):
        # <Text style={[styles.bandWord, ...]}>{band.label}</Text>
        self.assertIn("styles.bandWord", self.text)
        self.assertIn("{band.label}", self.text)

    def test_band_word_color_matches_band_fg(self):
        # Locate the bandWord <Text> and verify the inline style
        # binds color to bandFg (the band's foreground color).
        idx = self.text.find("styles.bandWord")
        self.assertGreater(idx, 0)
        chunk = self.text[idx: idx + 400]
        self.assertIn("color: bandFg", chunk)


if __name__ == "__main__":
    unittest.main()
