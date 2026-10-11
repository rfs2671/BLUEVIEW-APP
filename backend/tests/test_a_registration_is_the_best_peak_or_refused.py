"""A REGISTRATION IS THE BEST PEAK OR IT IS REFUSED.

plan_sheet.best_translation searched offsets on a 4pt grid while matching
corners within 1.5pt (one real inch). Every registration peak measured on
588 Boyland is NARROW - 2pt off the true offset the count falls to 4-16% of
its height - so the grid could step over a sheet's true alignment and settle
on a coincidental one. Measured 2026-10-10 with an exact 1pt sweep of every
pair the pass registers:

  A-100.01..A-104.00 / M-100..M-104   on the true peak (< 1in)
  A-105.01 / M-105.00 (the roof)      108 anchors, 21.8in off; true 239
  A-103.00 / S-104.00 (structural)     95 anchors, 30in off;   true 204

and register() called both USABLE: its residuals are taken over anchors
matched within an inch, so they pass for any offset (the roof's wrong peak
had the LOWER rms). The roof's wrong offset is in production: two of its
three WH-1 rows were refused for a reason the true offset does not give.

Rulings (operator, 2026-10-10):
  1. the search step is no larger than the 1.5pt match radius;
  2. anchor spread is measured against the PLAN (the wall layer), not the
     viewport - and it is a condition, not the discriminator;
  3. no fixed margin: every registration records the anchors its offset
     holds and the best peak found, and placement is refused when the
     offset holds under HALF the best.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_sheet as PS  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402


def _present():
    assert hasattr(PS, "offset_census"), \
        "register() still takes the 4pt grid's answer with nothing to check it against"


# ── a synthetic pair whose true offset falls BETWEEN 4pt samples ──────────

def _pair(wall=True):
    """200 arch corners; the mech sheet holds all of them at the true offset
    and 30 of them again at a DECOY offset that sits exactly on the old 4pt
    grid. Two far mech corners move the bounding-box seed so the true offset
    is (2, 2) pt off every 4pt sample - 2.8pt, beyond the 1.5pt radius."""
    rng = np.random.default_rng(7)
    A = np.round(rng.uniform([0, 0], [1200, 700], size=(200, 2)), 2)
    true = np.array([40.0, -30.0])
    B = A + true
    seed_wanted = true + 2.0                       # true - seed = (-2, -2)
    # widen B's box so its centre moves by +2 in each axis
    lo, hi = B.min(0), B.max(0)
    B = np.vstack([B, [hi[0] + 4.0, hi[1] + 4.0], [lo[0], hi[1] + 4.0]])
    seed = (B.min(0) + B.max(0)) / 2 - (A.min(0) + A.max(0)) / 2   # the search's own seed
    assert np.allclose(seed, seed_wanted), seed
    inner = A[(A[:, 0] > 100) & (A[:, 0] < 1100) & (A[:, 1] > 100) & (A[:, 1] < 600)][:30]
    decoy = seed + np.array([8.0, 0.0])            # on the 4pt grid
    B = np.vstack([B, inner + decoy])
    att = ([((A[:, 0].min(), A[:, 1].min(), A[:, 0].max(), A[:, 1].max()), "A-WALL")]
           if wall else [((0, 0, 10, 0), "A-ANNO-TEXT")])
    return {"corners": A, "att": att}, {"corners": B, "att": []}, true, decoy


def _old_step(A, B, **kw):
    return _BT(A, B, coarse_pt=4.0, **kw)


_BT = PS.best_translation


class TheSearchDoesNotStepOverANarrowPeak(unittest.TestCase):

    def test_the_true_offset_between_old_samples_is_found(self):
        arch, mech, true, _ = _pair()
        r = PS.register(arch, mech)
        self.assertLess(np.hypot(r["dx"] - true[0], r["dy"] - true[1]), 0.5, r)
        self.assertEqual(r["anchors"], 200)
        self.assertTrue(r["usable"], r.get("refused"))

    def test_the_census_finds_it_another_way(self):
        _present()
        arch, mech, true, _ = _pair()
        n, (x, y) = PS.offset_census(arch["corners"], mech["corners"])
        self.assertEqual(n, 200)
        self.assertLessEqual(max(abs(x - true[0]), abs(y - true[1])), 1.0)

    def test_the_default_step_is_the_match_radius(self):
        """Ruling 1, held at the call site register() uses."""
        _present()
        seen = {}
        real = PS.best_translation

        def spy(A, B, **kw):
            seen.update(kw)
            return real(A, B, **kw)
        arch, mech, _, _ = _pair()
        with patch.object(PS, "best_translation", spy):
            PS.register(arch, mech)
        self.assertIsNone(seen.get("coarse_pt"), "register() must not widen the step")
        # ...and the step it then gets is the radius: on main the default was
        # 4.0pt, so register() passing nothing still searched at 4pt
        default = inspect.signature(PS.best_translation).parameters["coarse_pt"].default
        self.assertIsNone(default, f"best_translation's default step is {default}pt, "
                                   "not the match radius")


class AnOffsetUnderHalfTheBestPeakIsRefused(unittest.TestCase):

    def test_the_old_step_lands_on_the_decoy_and_is_refused(self):
        """The guard fires on exactly the failure that happened: the 4pt grid
        takes the decoy (30 anchors) while the census holds 200."""
        _present()
        arch, mech, _, decoy = _pair()
        with patch.object(PS, "best_translation", _old_step):
            r = PS.register(arch, mech)
        self.assertLess(np.hypot(r["dx"] - decoy[0], r["dy"] - decoy[1]), 1.0, r)
        self.assertFalse(r["usable"])
        self.assertEqual(r["best_peak_anchors"], 200)
        self.assertIn("under half", r["refused"])

    def test_every_registration_records_both_readings(self):
        _present()
        arch, mech, _, _ = _pair()
        r = PS.register(arch, mech)
        for k in ("anchors", "best_peak_anchors", "best_peak", "spread", "refused"):
            self.assertIn(k, r)
        row_reg = {k: r.get(k) for k in ("dx", "dy", "anchors", "rms_in", "max_in", "usable",
                                         "best_peak_anchors", "best_peak", "spread", "refused")}
        self.assertGreaterEqual(E.EMIT_VERSION, 4)
        page = {"project_id": "p", "page_id": "m", "page_number": 1, "sheet_number": "M-103.00"}
        result = {"registration": r, "records": [
            {"tag": "EF-1", "unit": None, "glyph_status": "resolved", "placement": "refused",
             "label_text": "EF-1", "label_box": None, "label_at": (1, 1)}]}
        (row,) = E.glyph_rows(result, mech=page, arch={**page, "sheet_number": "A-103.00"},
                              family="EXHAUST FAN SCHEDULE", pass_key="k", units={},
                              widest_door={})
        self.assertEqual(row["payload"]["registration"], row_reg)
        self.assertEqual(row["payload"]["emit_version"], E.EMIT_VERSION)


class SpreadIsMeasuredAgainstThePlan(unittest.TestCase):

    def test_spread_is_over_the_wall_layer(self):
        _present()
        arch, mech, _, _ = _pair()
        r = PS.register(arch, mech)
        self.assertGreater(min(r["spread"]), 0.95)

    def test_no_wall_layer_no_spread_and_refused(self):
        """The fallback: long segments span 0.39 on every Boyland sheet (tables
        and dimension lines are long too), so without a wall layer the plan
        has no measurable extent, and placement is refused, saying why."""
        _present()
        arch, mech, _, _ = _pair(wall=False)
        r = PS.register(arch, mech)
        self.assertIsNone(r["spread"])
        self.assertFalse(r["usable"])
        self.assertIn("no wall layer", r["refused"])


# ── the two measured failures, on the real sheets ─────────────────────────

def _sheet(name, page):
    from lib.plan_page import PlanPage
    pg = PlanPage(str(require_pdf(name)), page)
    try:
        return PS.load_sheet(pg)
    finally:
        pg.close()


class TheMeasuredFailuresLandOnTheirTruePeak(unittest.TestCase):
    """True peaks from the exact 1pt sweep (bv measurement, 2026-10-10),
    each confirmed by overlay: walls coincide at the true offset."""

    # ONE METHOD PER CASE, NO subTest: pytest reports a test whose subtests
    # failed as PASSED beside the subtest failures - a control run read green.
    S104 = ("Owners set - 6.9.26.pdf", 4, "ST - 7.29.26.pdf", 8, (6.1, -242.5), 204,
            (6.33, -287.38))
    ROOF = ("AR - 8.18.26.pdf", 7, "MH - 7.2.26.pdf", 7, (-26.75, -45.12), 239,
            (5.99, -45.0))

    def _lands(self, case):
        af, ap, mf, mp, true, n_true, was = case
        r = PS.register(_sheet(af, ap), _sheet(mf, mp))
        off = np.hypot(r["dx"] - true[0], r["dy"] - true[1])
        self.assertLess(off, 1.5, f"{mf}: ({r['dx']:.2f}, {r['dy']:.2f}), was {was}, "
                                  f"true {true}")
        self.assertGreaterEqual(r["anchors"], 0.95 * n_true)
        self.assertTrue(r["usable"], r.get("refused"))

    def _old_refused(self, case):
        _present()
        af, ap, mf, mp, true, n_true, was = case
        with patch.object(PS, "best_translation", _old_step):
            r = PS.register(_sheet(af, ap), _sheet(mf, mp))
        self.assertLess(np.hypot(r["dx"] - was[0], r["dy"] - was[1]), 1.0)
        self.assertFalse(r["usable"])
        self.assertIn("under half", r["refused"])

    def test_s104_on_a103_lands_on_its_true_peak(self):
        self._lands(self.S104)

    def test_the_roof_lands_on_its_true_peak(self):
        self._lands(self.ROOF)

    def test_s104_old_answer_is_now_refused(self):
        self._old_refused(self.S104)

    def test_the_roof_old_answer_is_now_refused(self):
        self._old_refused(self.ROOF)

    def test_a_floor_that_was_right_stays_right(self):
        """A-103.00 / M-103.00 was on its true peak: same offset, accepted."""
        arch = _sheet("Owners set - 6.9.26.pdf", 4)
        mech = _sheet("MH - 7.2.26.pdf", 5)
        r = PS.register(arch, mech)
        self.assertLess(np.hypot(r["dx"] + 25.25, r["dy"] + 51.01), 1.5)
        self.assertTrue(r["usable"], r.get("refused"))


if __name__ == "__main__":
    unittest.main()
