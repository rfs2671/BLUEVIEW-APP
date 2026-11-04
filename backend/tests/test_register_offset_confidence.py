"""REGISTER_OFFSET CONFIDENCE (lib.plan_registration_confidence): a MINIMUM
ANCHOR FRACTION and a MINIMUM MARGIN over the second peak, WIRED into
plan_sheet.register_offset (which refuses below either floor).

Before the wiring register_offset had no ratio threshold: the gas roof registered "usable" at 31
of 687 anchors with margin 1.10 (a wrong peak). The recorded numbers below are
the calibration set (regthresh/REPORT.md, registrations_table.csv): known-good
registrations from the pass-11 snapshot and the sprinkler lane, known-bad from
the frame test, the wrong-scale sprinkler runs and the M-106 roof run.

Each test fails on origin/main by ASSERTION (_present), not by ImportError: the
module is imported lazily."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

LIB = Path(__file__).resolve().parents[1] / "lib"
MOD = "lib.plan_registration_confidence"


def _present(tc):
    tc.assertIsNotNone(importlib.util.find_spec(MOD),
                       "lib/plan_registration_confidence.py does not exist")
    return importlib.import_module(MOD)


def reg(best, second, usable=True):
    return {"best_peak_anchors": best, "second_peak_anchors": second,
            "margin": round(best / second, 3) if second else None, "usable": usable}


# (label, best, second, corners_a, corners_b)
FIRST_FLOOR = ("gas A-100.00 vs 3.28.25 A-100.00", 1996, 442, 2003, 2007)
GOOD = [  # production + sprinkler: the registrations everything served rests on
    ("S-101 FLOOR_1 filed", 89, 53, 2007, 739), ("S-102 FLOOR_2", 128, 75, 2044, 813),
    ("S-103 FLOOR_3", 124, 73, 2036, 767), ("S-104 FLOOR_4", 205, 107, 2558, 885),
    ("S-105 MEZZ", 274, 134, 1785, 911), ("S-101 FLOOR_1 post_co", 89, 55, 1964, 739),
    ("P-100 -> A-100 gas", 1449, 431, 2007, 2987), ("P-103 -> A-103", 1741, 489, 2558, 3136),
    ("P-104 owner -> A-104", 1116, 429, 1602, 2671), ("P-105 owner roof", 782, 388, 1010, 1962),
    ("M-104 owner", 575, 212, 1602, 2281), ("M-100 gas", 907, 211, 2007, 2511),
    ("M-105 owner roof", 239, 115, 1010, 1659),
    ("SP-002 L1 3/16", 789, 103, 2003, 1037), ("SP-004 ROOF 3/16", 173, 60, 968, 428),
]
BAD_USABLE = [  # register_offset said usable=True; the geometry is wrong
    ("gas roof vs 3.28.25 A-105.00 (frame test)", 32, 29, 968, 687),
    ("SP-003 L4 at 1/8 in", 56, 50, 2558, 1168), ("SP-003 L3 at 1/4 in", 45, 39, 2036, 1040),
    ("M-106 vs 3.28.25 roof (104 v 103)", 104, 103, 968, 1222),
]
BAD_REFUSED = [("P-105 gas roof", 31, 29, 687, 1962), ("P-206 gas roof", 32, 31, 687, 1698),
               ("S-106 gas roof", 14, 13, 687, 592)]


class RegisterOffsetConfidence(unittest.TestCase):
    def conf(self, row, **kw):
        m = _present(self)
        _, best, second, ca, cb = row
        return m.confidence(reg(best, second), ca, cb, **kw)

    def test_the_gas_roof_wrong_peak_would_be_refused(self):
        for row in BAD_USABLE:
            with self.subTest(row[0]):
                self.assertTrue(self.conf(row)["would_refuse"], row[0])

    def test_the_first_floor_gas_frame_is_confident(self):
        c = self.conf(FIRST_FLOOR)
        self.assertTrue(c["confident"] and not c["would_refuse"], c)
        self.assertAlmostEqual(c["fraction"], 0.9965, places=3)

    def test_every_verified_registration_is_confident(self):
        for row in GOOD:
            with self.subTest(row[0]):
                c = self.conf(row)
                self.assertTrue(c["confident"], (row[0], c))

    def test_already_refused_stays_refused(self):
        m = _present(self)
        for label, best, second, ca, cb in BAD_REFUSED:
            c = m.confidence(reg(best, second, usable=False), ca, cb)
            self.assertTrue(c["would_refuse"] and c["already_refused"], label)
        # refused by register_offset for its own reason (R1/R2/R3) with strong
        # numbers: the floors never turn a refusal into a pass
        c = m.confidence(reg(1000, 200, usable=False), 1500, 1500)
        self.assertTrue(c["confident"] and c["would_refuse"] and c["already_refused"], c)

    def test_fraction_floor_alone_refuses(self):
        m = _present(self)
        c = m.confidence(reg(60, 10), 2000, 1000)       # margin 6.0, fraction 0.06
        self.assertTrue(c["margin_ok"] and not c["fraction_ok"] and c["would_refuse"], c)

    def test_margin_floor_alone_refuses(self):
        m = _present(self)
        c = m.confidence(reg(500, 495), 2000, 1000)     # fraction 0.5, margin 1.01
        self.assertTrue(c["fraction_ok"] and not c["margin_ok"] and c["would_refuse"], c)

    def test_denominator_is_the_smaller_sheet(self):
        m = _present(self)
        self.assertEqual(m.anchor_fraction(100, 1000, 500), 0.2)
        self.assertEqual(m.anchor_fraction(100, 500, 1000), 0.2)

    def test_no_second_peak_is_not_a_failure(self):
        m = _present(self)
        r = {"best_peak_anchors": 300, "second_peak_anchors": 0, "margin": None, "usable": True}
        self.assertTrue(m.confidence(r, 600, 700)["confident"])

    def test_missing_corner_counts_are_reported_not_passed(self):
        m = _present(self)
        c = m.confidence(reg(300, 100), 0, 700)
        self.assertFalse(c["confident"])
        self.assertTrue(any("unmeasured" in r for r in c["reasons"]), c)

    def test_boundaries_are_inclusive(self):
        m = _present(self)
        r = {"best_peak_anchors": 130, "second_peak_anchors": 100, "margin": 1.3, "usable": True}
        self.assertTrue(m.confidence(r, 1300, 1300, min_fraction=0.1, min_margin=1.3)["confident"])
        r["margin"] = 1.299
        self.assertFalse(m.confidence(r, 1300, 1300, min_fraction=0.1, min_margin=1.3)["confident"])

    def test_pure_does_not_mutate_the_registration(self):
        m = _present(self)
        r = reg(32, 29)
        before = dict(r)
        m.confidence(r, 968, 687)
        self.assertEqual(r, before)

    def test_thresholds_are_the_calibrated_pairs(self):
        m = _present(self)
        self.assertEqual((m.MIN_ANCHOR_FRACTION, m.MIN_MARGIN), (0.10, 1.30))
        self.assertEqual((m.PERMISSIVE_MIN_ANCHOR_FRACTION, m.PERMISSIVE_MIN_MARGIN), (0.06, 1.25))

    def test_permissive_pair_still_refuses_every_known_wrong_peak(self):
        m = _present(self)
        for row in BAD_USABLE:
            c = self.conf(row, min_fraction=m.PERMISSIVE_MIN_ANCHOR_FRACTION,
                          min_margin=m.PERMISSIVE_MIN_MARGIN)
            self.assertTrue(c["would_refuse"], row[0])

    def test_owner_roof_structure_is_the_documented_flip(self):
        """S-106 -> owner's A-105.00: 53 of 592 (0.0895), margin 1.514. The
        recommended pair refuses it, the permissive pair keeps it."""
        m = _present(self)
        row = ("S-106 owner roof", 53, 35, 1010, 592)
        self.assertTrue(self.conf(row)["would_refuse"])
        self.assertFalse(self.conf(row, min_fraction=m.PERMISSIVE_MIN_ANCHOR_FRACTION,
                                   min_margin=m.PERMISSIVE_MIN_MARGIN)["would_refuse"])

    def test_register_offset_applies_the_conservative_pair_and_records_corner_counts(self):
        """WIRED (replaces test_nothing_in_the_pipeline_calls_it):
        register_offset is the one caller; the result carries corners_arch /
        corners_other / anchor_fraction; no other lib module or server.py
        imports the module."""
        _present(self)
        from lib import plan_sheet as PS
        src = inspect.getsource(PS.register_offset)
        self.assertIn("confidence", src)
        for k in ("corners_arch", "corners_other", "anchor_fraction"):
            self.assertIn(k, src)
        callers = [p.name for p in LIB.glob("*.py")
                   if p.name not in ("plan_registration_confidence.py", "plan_sheet.py")
                   and re.search(r"plan_registration_confidence", p.read_text(encoding="utf-8"))]
        server = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        self.assertEqual(callers, [], callers)
        self.assertNotIn("plan_registration_confidence", server)

    def test_register_offset_records_counts_and_too_few_corners_is_refused(self):
        _present(self)
        import numpy as np
        from lib import plan_sheet as PS
        rng = np.random.default_rng(0)
        A = rng.uniform(0, 3000, (400, 2))
        good = PS.register_offset({"corners": A}, {"corners": A + np.array([10.0, 20.0])})
        self.assertTrue(good["usable"], good)
        self.assertEqual((good["corners_arch"], good["corners_other"]), (400, 400))
        self.assertGreaterEqual(good["anchor_fraction"], 0.10)
        tiny = PS.register_offset({"corners": A[:3]}, {"corners": A[:3]})
        self.assertFalse(tiny["usable"])
        self.assertEqual(tiny["corners_arch"], 3)

    def _pair(self, matched, n=400, seed=1):
        """Two sheets of n corners each; exactly `matched` of the arch corners
        reappear on the other sheet at one shared offset, the rest are
        unrelated, so the best peak holds ~`matched` anchors."""
        import numpy as np
        rng = np.random.default_rng(seed)
        A = rng.uniform(0, 3000, (n, 2))
        B = rng.uniform(0, 3000, (n, 2))
        B[:matched] = A[:matched] + np.array([10.0, 20.0])
        return {"corners": A}, {"corners": B}

    def test_a_low_anchor_fraction_is_refused_with_the_stated_reason(self):
        """RULING 1 (Roy): 39 of 400 (0.0975) is under the 0.10 floor and is
        REFUSED with the reason stated; 41 of 400 (0.1025), just above the
        floor, is accepted. Both have a clear single peak and >= MIN_ANCHORS,
        so ONLY the fraction floor separates them."""
        m = _present(self)
        from lib import plan_sheet as PS
        low = PS.register_offset(*self._pair(39))
        self.assertFalse(low["usable"], low)
        self.assertLess(low["anchor_fraction"], m.MIN_ANCHOR_FRACTION)
        self.assertIn("registration not confident: anchor fraction", low["refused"])
        self.assertIn(f"under {m.MIN_ANCHOR_FRACTION:.3f}", low["refused"])
        self.assertGreaterEqual(low["margin"], m.MIN_MARGIN)  # margin alone would pass
        self.assertGreaterEqual(low["anchors"], 8)
        self.assertEqual((low["corners_arch"], low["corners_other"]), (400, 400))
        ok = PS.register_offset(*self._pair(41))
        self.assertTrue(ok["usable"], ok)
        self.assertIsNone(ok["refused"])
        self.assertGreaterEqual(ok["anchor_fraction"], m.MIN_ANCHOR_FRACTION)

    def test_no_second_peak_is_an_unambiguous_margin_not_a_missing_one(self):
        m = _present(self)
        c = m.confidence({"best_peak_anchors": 50, "second_peak_anchors": 0, "margin": None,
                          "usable": True}, 100, 100)
        self.assertTrue(c["confident"], c)

    def test_a_missing_count_or_margin_fails_closed(self):
        m = _present(self)
        usable = {"best_peak_anchors": 50, "second_peak_anchors": 10, "margin": 5.0, "usable": True}
        self.assertTrue(m.confidence(usable, 100, 100)["confident"])
        for corners in ((0, 100), (100, 0), (None, 100)):
            c = m.confidence(usable, *corners)
            self.assertFalse(c["confident"], corners)
            self.assertTrue(c["would_refuse"])
            self.assertTrue(any("unmeasured" in r for r in c["reasons"]))
        c = m.confidence(dict(usable, margin=None, second_peak_anchors=None), 100, 100)
        self.assertFalse(c["confident"])
        self.assertFalse(m.confidence(dict(usable, best_peak_anchors=None), 100, 100)["confident"])


class RowVersionsMoveWithTheGate(unittest.TestCase):
    """Rows stored before the confidence gate carry no anchor_fraction; the
    row versions say which rows were written under the gate (Roy, 2026-11-04)."""

    def test_structure_and_stack_row_versions_are_bumped(self):
        from lib import plan_structural, plan_stacks
        self.assertGreaterEqual(plan_structural.EMIT_VERSION, 2)
        self.assertGreaterEqual(plan_stacks.ROW_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
