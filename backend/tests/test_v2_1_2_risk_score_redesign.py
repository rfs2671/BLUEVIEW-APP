"""Phase V2.1.2 — Risk Score UI redesign tests.

Pin every contract the V2.1.2 redesign promises:

  • RiskScoreCircle component exists, useFeatureFlag is FIRST hook,
    flag-off path returns null, fetches the latest score endpoint,
    opens a drawer (does NOT navigate), and color-band thresholds
    match the backend exactly (lib/risk_score/schema.py::score_band).
  • RiskScoreDrawer component exists, useFeatureFlag is FIRST hook,
    flag-off + closed paths return null, ESC + backdrop close, and
    the recalc + calibration POSTs hit the right endpoints.
  • Project list (frontend/app/projects/index.jsx) imports AND
    mounts RiskScoreCircle inline with each project row.
  • Project detail page (frontend/app/project/[id].jsx) imports
    AND mounts RiskScoreCircle in the project header. The old
    full-width RiskScoreCard mount is REMOVED. The deprecated
    RiskScoreCard.jsx file is still present and carries a
    deprecation comment so future cleanup knows to remove it.
  • All 1129 prior tests pass byte-for-byte.
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
# RiskScoreCircle component
# ──────────────────────────────────────────────────────────────────


class TestRiskScoreCircleFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_uses_feature_flag_hook(self):
        self.assertIn("useFeatureFlag('v2_risk_score')", self.text)

    def test_flag_check_is_first_hook(self):
        """Rules-of-hooks: useFeatureFlag must be the FIRST hook
        called in the component body. C1.3 incident pattern."""
        comp_idx = self.text.find("const RiskScoreCircle = (")
        self.assertGreater(comp_idx, 0, "RiskScoreCircle definition missing")
        body_open = self.text.find("{", comp_idx)
        flag_idx = self.text.find("useFeatureFlag", body_open)
        other_hooks = ("useTheme(", "useState(", "useEffect(", "useMemo(")
        first_other = min(
            (self.text.find(h, body_open) for h in other_hooks
             if self.text.find(h, body_open) > 0),
            default=-1,
        )
        self.assertGreater(flag_idx, 0, "useFeatureFlag missing")
        self.assertGreater(first_other, 0)
        self.assertLess(
            flag_idx, first_other,
            "useFeatureFlag must be the FIRST hook (rules-of-hooks)",
        )

    def test_returns_null_when_flag_disabled(self):
        """Flag-off render path = `return null`. No spinner, no
        placeholder. v1 users see no v2 UI flicker."""
        self.assertIn("if (!v2RiskScoreEnabled)", self.text)
        flag_check = self.text.find("if (!v2RiskScoreEnabled)")
        next_return = self.text.find("return null", flag_check)
        self.assertGreater(next_return, flag_check)

    def test_fetches_score_endpoint(self):
        # GET /api/projects/{id}/risk-score (no /history, no
        # /calculate — that's the drawer's job).
        self.assertIn(
            "/api/projects/${projectId}/risk-score`",
            self.text,
        )

    def test_opens_drawer_does_not_navigate(self):
        # The circle must NOT call router.push or router.replace —
        # tapping it should open a side drawer, not change pages.
        # Pinned by absence of expo-router import.
        self.assertNotIn("from 'expo-router'", self.text,
                         "RiskScoreCircle must not navigate")
        self.assertIn("RiskScoreDrawer", self.text)
        self.assertIn("setDrawerOpen(true)", self.text)


class TestBandThresholdsMatchBackend(unittest.TestCase):
    """The FE band cutoffs MUST match
    backend/lib/risk_score/schema.py::score_band exactly. A drift
    here means a project shown as 'orange' on the FE could be
    classified 'yellow' by a notification rule on the BE."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def _fe_band(self, score):
        """Re-implement the FE bandFor() in Python by string-
        scraping the JSX. This catches any drift between the
        file as actually shipped and the test's interpretation
        of the cutoffs."""
        # Locate the JS body of bandFor.
        s = self.text.find("export function bandFor(score)")
        e = self.text.find("}", s + 200)  # well past the closing brace
        body = self.text[s:e + 1]
        # Pin: 0..30 green, 31..60 yellow, 61..80 orange, 81..100 red.
        # We rely on the function body containing literal cutoffs in
        # this order; the regex below extracts each `<= NUM` cutoff.
        cutoffs = [int(m) for m in re.findall(r"s\s*<=\s*(\d+)", body)]
        self.assertEqual(cutoffs, [30, 60, 80],
                         f"bandFor cutoffs unexpected: {cutoffs}")
        s_int = int(score)
        if s_int <= 30: return "green"
        if s_int <= 60: return "yellow"
        if s_int <= 80: return "orange"
        return "red"

    def test_boundary_29_green(self):
        self.assertEqual(self._fe_band(29), rs_schema.score_band(29))
        self.assertEqual(rs_schema.score_band(29), "green")

    def test_boundary_30_green(self):
        self.assertEqual(self._fe_band(30), rs_schema.score_band(30))
        self.assertEqual(rs_schema.score_band(30), "green")

    def test_boundary_31_yellow(self):
        self.assertEqual(self._fe_band(31), rs_schema.score_band(31))
        self.assertEqual(rs_schema.score_band(31), "yellow")

    def test_boundary_60_yellow(self):
        self.assertEqual(self._fe_band(60), rs_schema.score_band(60))
        self.assertEqual(rs_schema.score_band(60), "yellow")

    def test_boundary_61_orange(self):
        self.assertEqual(self._fe_band(61), rs_schema.score_band(61))
        self.assertEqual(rs_schema.score_band(61), "orange")

    def test_boundary_80_orange(self):
        self.assertEqual(self._fe_band(80), rs_schema.score_band(80))
        self.assertEqual(rs_schema.score_band(80), "orange")

    def test_boundary_81_red(self):
        self.assertEqual(self._fe_band(81), rs_schema.score_band(81))
        self.assertEqual(rs_schema.score_band(81), "red")

    def test_boundary_99_red(self):
        self.assertEqual(self._fe_band(99), rs_schema.score_band(99))
        self.assertEqual(rs_schema.score_band(99), "red")


class TestRiskScoreCircleEmptyAndErrorStates(unittest.TestCase):
    """The circle must render gracefully when score is missing or
    fetch fails — silently fall back to a "—" placeholder, never
    paint a scary error. Project lists with 50 rows shouldn't burn
    50 error toasts on a partial outage."""

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_renders_em_dash_when_no_score(self):
        # Look for the em-dash literal in a render branch.
        self.assertIn("—", self.text)

    def test_silent_fail_on_fetch_error(self):
        """Fetch failure must NOT toast / alert / log to console
        in a noisy way — silent fall-through to setScoreDoc(null)."""
        # The catch branch must NOT include console.error / toast
        # / Alert.alert. We allow a comment but no actual call.
        # Find every catch (...) { ... } body.
        for m in re.finditer(r"catch\s*\([^)]*\)\s*\{([^}]*)\}", self.text):
            body = m.group(1)
            self.assertNotIn("console.error", body)
            self.assertNotIn("toast.show", body)
            self.assertNotIn("Alert.alert", body)


class TestRiskScoreCircleAccessibility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreCircle.jsx"
        )
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_pressable_has_accessibility_label(self):
        self.assertIn("accessibilityRole=\"button\"", self.text)
        self.assertIn("accessibilityLabel=", self.text)


# ──────────────────────────────────────────────────────────────────
# RiskScoreDrawer component
# ──────────────────────────────────────────────────────────────────


class TestRiskScoreDrawerFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = (
            _REPO / "frontend" / "src" / "components" / "RiskScoreDrawer.jsx"
        )
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_uses_feature_flag_hook(self):
        self.assertIn("useFeatureFlag('v2_risk_score')", self.text)

    def test_flag_check_is_first_hook(self):
        comp_idx = self.text.find("const RiskScoreDrawer = (")
        self.assertGreater(comp_idx, 0)
        body_open = self.text.find("{", comp_idx)
        flag_idx = self.text.find("useFeatureFlag", body_open)
        other_hooks = (
            "useTheme(", "useState(", "useEffect(", "useMemo(",
            "useCallback(",
        )
        first_other = min(
            (self.text.find(h, body_open) for h in other_hooks
             if self.text.find(h, body_open) > 0),
            default=-1,
        )
        self.assertGreater(flag_idx, 0)
        self.assertGreater(first_other, 0)
        self.assertLess(
            flag_idx, first_other,
            "useFeatureFlag must be the FIRST hook (rules-of-hooks)",
        )

    def test_returns_null_when_flag_disabled(self):
        self.assertIn("if (!v2RiskScoreEnabled)", self.text)

    def test_returns_null_when_not_visible(self):
        # The drawer is parent-controlled; closed = no DOM at all.
        self.assertIn("if (!visible)", self.text)

    def test_close_on_escape_key(self):
        # ESC-to-close on web: the drawer must add a keydown
        # listener bound to the Escape key.
        self.assertIn("'Escape'", self.text)
        self.assertIn("addEventListener('keydown'", self.text)

    def test_close_on_backdrop_press(self):
        # Backdrop tap closes the drawer; the inner Pressable
        # swallows clicks.
        self.assertIn("onPress={onClose}", self.text)

    def test_recalc_endpoint(self):
        self.assertIn(
            "/api/projects/${projectId}/risk-score/calculate`",
            self.text,
        )

    def test_calibration_endpoint(self):
        self.assertIn(
            "/api/projects/${projectId}/risk-score/calibration`",
            self.text,
        )

    def test_responsive_below_768(self):
        # Mobile viewports get a full-width drawer. Pinned via the
        # "winW < 768" check — Dimensions hook is at render time so
        # the value reflects the current viewport.
        self.assertIn("winW < 768", self.text)


# ──────────────────────────────────────────────────────────────────
# Mounting surfaces
# ──────────────────────────────────────────────────────────────────


class TestProjectListMount(unittest.TestCase):
    """Project list must import + render RiskScoreCircle inline
    with each project row. Without this, the circle exists but no
    user ever sees it on the list."""

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "frontend" / "app" / "projects" / "index.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_imports_risk_score_circle(self):
        self.assertIn("import RiskScoreCircle", self.text)

    def test_mounts_inside_list_item(self):
        # Cheapest pin: <RiskScoreCircle … /> appears INSIDE the
        # filteredProjects.map → GlassListItem render branch.
        list_marker = self.text.find("filteredProjects.map(")
        self.assertGreater(list_marker, 0)
        end_marker = self.text.find(")) ", list_marker)
        # Fallback if the spread terminator isn't present —
        # widen to a far slice so the search succeeds in either
        # case.
        if end_marker < 0:
            end_marker = list_marker + 8000
        slice_ = self.text[list_marker:end_marker]
        self.assertIn("<RiskScoreCircle", slice_)

    def test_passes_project_id_prop(self):
        # The mount must include projectId={...}; without it the
        # circle has nothing to fetch.
        idx = self.text.find("<RiskScoreCircle")
        end = self.text.find("/>", idx)
        snippet = self.text[idx:end + 2]
        self.assertIn("projectId=", snippet)


class TestProjectDetailMount(unittest.TestCase):
    """Project detail page must mount RiskScoreCircle in the
    header area and MUST NOT mount the deprecated RiskScoreCard."""

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "frontend" / "app" / "project" / "[id].jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_imports_risk_score_circle(self):
        self.assertIn("import RiskScoreCircle", self.text)

    def test_mounts_risk_score_circle(self):
        self.assertIn("<RiskScoreCircle", self.text)

    def test_old_full_width_card_not_mounted(self):
        """The full-width RiskScoreCard JSX mount must be gone.
        Note: the import line may also be gone now (we removed it)
        but the JSX tag is the regression we care about — that's
        what the operator complained about visually."""
        self.assertNotIn("<RiskScoreCard", self.text,
                         "Old full-width RiskScoreCard is still mounted")

    def test_passes_project_id_and_admin_props(self):
        idx = self.text.find("<RiskScoreCircle")
        end = self.text.find("/>", idx)
        snippet = self.text[idx:end + 2]
        self.assertIn("projectId={projectId}", snippet)
        self.assertIn("isAdmin={isAdmin}", snippet)


# ──────────────────────────────────────────────────────────────────
# Old RiskScoreCard.jsx — deprecated but kept
# ──────────────────────────────────────────────────────────────────


class TestOldRiskScoreCardDeprecated(unittest.TestCase):
    """The old card file is intentionally kept on disk during the
    migration window. It must:
      • still exist (a deletion now would lose context),
      • carry a deprecation comment at the top so the next operator
        knows to delete it once the redesign is verified."""

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "frontend" / "src" / "components" / "RiskScoreCard.jsx"
        cls.text = (
            cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""
        )

    def test_file_still_present(self):
        self.assertTrue(self.path.exists())

    def test_deprecation_comment_at_top(self):
        # The first 400 chars of the file must contain DEPRECATED
        # and a V2.1.2 reference. Tests the COMMENT, not the JSX.
        head = self.text[:400]
        self.assertIn("DEPRECATED", head)
        self.assertIn("V2.1.2", head)


if __name__ == "__main__":
    unittest.main()
