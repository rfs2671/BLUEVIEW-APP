"""EVERY ITEM IS ANSWERED RIGHT OR REFUSED - NEVER ANSWERED WRONG.

The product metric for "which apartment does this exhaust fan / PTAC serve":
per item, correct / wrong / UNKNOWN / refused. The bar is ZERO WRONG.

TRUTH IS PINNED from render reads of each sheet (2026-09-21/22), not computed
from any pipeline: (tag, position on the architectural sheet) -> the space the
item serves. 47 items on three floors of the Boyland set.

Scored before this port (scratch, identical code):
    layers path   47 correct, 0 wrong
    geometry path 29 correct, 0 wrong, 18 refused (A-101.00: units merge)

Covered here:
  - the 47 truths on the PRIMARY (CAD-layer) path;
  - the FALLBACK, by stripping every drawing's layer from the page: A-103.00
    and A-100.01 still correct, A-101.00 fully refused, zero wrong;
  - the fail-safe cases (9) that the geometric path's merged A-101.00 state,
    the M-100.00 prose/near-miss labels and the bike room pinned.

Needs the source-PDF fixtures (tests/fixture_pdfs.py) and the OCR engine.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

try:                                     # absent on main: tests FAIL, not error
    from lib import plan_takeoff as T
except ImportError:                      # pragma: no cover
    T = None

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

EF = (["EF-1", "EF-2"], {"EF-1": "50", "EF-2": "100"})   # M-200.00 schedule
PTAC = (["PTAC-1", "PTAC-2", "PTAC-3"], {})               # no rating column
WIDEST_DOOR_IN = 56.0                                     # A-400.00: D1 4'-8"

FLOORS = {
    "A-103.00": (("Owners set - 6.9.26.pdf", 4), ("MH - 7.2.26.pdf", 5),
                 ("4A", "4B", "4C", "4D")),
    "A-100.01": (("AR - 8.18.26.pdf", 6), ("MH - 7.2.26.pdf", 2),
                 ("1A", "1B", "1C", "1D")),
    "A-101.00": (("Owners set - 6.9.26.pdf", 2), ("MH - 7.2.26.pdf", 3),
                 ("2A", "2B", "2C", "2D")),
}

#: PINNED from render reads: (tag, x, y on the architectural sheet) -> space
TRUTH = {
    "A-103.00": [("EF-2", 1108, 530, "4A"), ("EF-1", 1080, 710, "4A"),
                 ("EF-1", 1078, 874, "4B"), ("EF-2", 1119, 1080, "4B"),
                 ("EF-2", 1634, 516, "4C"), ("EF-1", 1679, 701, "4C"),
                 ("EF-1", 1676, 872, "4D"), ("EF-2", 1630, 1077, "4D"),
                 ("PTAC-3", 760, 552, "4A"), ("PTAC-1", 760, 709, "4A"),
                 ("PTAC-1", 760, 862, "4B"), ("PTAC-3", 760, 1007, "4B"),
                 ("PTAC-3", 2000, 567, "4C"), ("PTAC-1", 1999, 712, "4C"),
                 ("PTAC-1", 1999, 858, "4D"), ("PTAC-3", 1999, 1016, "4D")],
    "A-100.01": [("EF-1", 1095, 680, "1A"), ("EF-2", 1208, 711, "1A"),
                 ("EF-1", 1159, 822, "1B"), ("EF-2", 1183, 978, "1B"),
                 ("EF-2", 1598, 587, "1C"), ("EF-1", 1571, 814, "1C"),
                 ("EF-2", 1710, 754, "1D"), ("EF-1", 1593, 941, "1D"),
                 ("PTAC-3", 762, 571, "1A"),
                 ("PTAC-1", 783, 663, "non-unit:BIKE ROOM"),
                 ("PTAC-3", 759, 840, "1B"), ("PTAC-3", 1996, 632, "1C"),
                 ("PTAC-2", 1989, 804, "1D")],
    "A-101.00": [("EF-1", 1094, 675, "2A"), ("EF-2", 1170, 776, "2A"),
                 ("EF-2", 1167, 807, "2B"), ("EF-1", 1109, 916, "2B"),
                 ("EF-1", 1661, 674, "2C"), ("EF-2", 1585, 763, "2C"),
                 ("EF-2", 1582, 814, "2D"), ("EF-1", 1659, 920, "2D"),
                 ("PTAC-2", 999, 470, "2A"), ("PTAC-1", 761, 555, "2A"),
                 ("PTAC-1", 761, 711, "2A"), ("PTAC-1", 761, 864, "2B"),
                 ("PTAC-3", 759, 1010, "2B"), ("PTAC-2", 1661, 529, "2C"),
                 ("PTAC-1", 2000, 567, "2C"), ("PTAC-1", 1999, 708, "2C"),
                 ("PTAC-1", 1999, 858, "2D"), ("PTAC-3", 2000, 1013, "2D")],
}


class _StrippedLayers:
    """The page with every drawing's CAD layer removed - a sheet exported
    flat, as another office might. Everything else is the real page."""

    def __init__(self, page):
        self._p = page

    def __getattr__(self, name):
        return getattr(self._p, name)

    def get_drawings(self, *a, **k):
        return [dict(d, layer="") for d in self._p.get_drawings(*a, **k)]


_CACHE = {}


def _run(floor, eq, stripped=False):
    assert T is not None, "lib.plan_takeoff is not in this tree"
    key = (floor, eq, stripped)
    if key not in _CACHE:
        import fitz
        (afn, apn), (mfn, mpn), units = FLOORS[floor]
        a = fitz.open(require_pdf(afn))[apn - 1]
        m = fitz.open(require_pdf(mfn))[mpn - 1]
        tags, corr = EF if eq == "EF" else PTAC
        _CACHE[key] = T.run_takeoff(_StrippedLayers(a) if stripped else a, m,
                                    tags, corr, units, WIDEST_DOOR_IN)
    return _CACHE[key]


def _score(floor, stripped=False):
    """{verdict: n} and the non-correct details, against the pinned truth."""
    items = [r for eq in ("EF", "PTAC")
             for r in _run(floor, eq, stripped)["records"] if r.get("tag")]
    truth = TRUTH[floor]
    used, out, bad = set(), {"correct": 0, "wrong": 0, "unknown": 0,
                             "refused": 0, "unmatched": 0}, []
    for r in items:
        x, y = r["at_arch"]
        best = min(((abs(tx - x) + abs(ty - y), i) for i, (tg, tx, ty, _u)
                    in enumerate(truth) if tg == r["tag"] and i not in used),
                   default=None)
        if best is None or best[0] > 40:
            out["unmatched"] += 1
            bad.append((r["tag"], (round(x), round(y)), r["unit"], "unmatched"))
            continue
        used.add(best[1])
        want = truth[best[1]][3]
        if r["unit"] is None:
            v = "unknown" if "UNKNOWN" in (r.get("reason") or "") else "refused"
        else:
            v = "correct" if r["unit"] == want else "wrong"
        out[v] += 1
        if v != "correct":
            bad.append((r["tag"], (round(x), round(y)), r["unit"], v, want))
    out["missed"] = len(truth) - len(used)
    return out, bad


class TheFortySevenTruthsOnTheLayerPath(unittest.TestCase):

    def _floor(self, floor, n):
        s, bad = _score(floor)
        print(f"\n{floor} layers: {s}")
        self.assertEqual(_run(floor, "EF")["method"], "layers")
        self.assertEqual(s["wrong"], 0, bad)
        self.assertEqual(s["correct"], n, bad)

    def test_a103(self):
        self._floor("A-103.00", 16)

    def test_a100(self):
        self._floor("A-100.01", 13)

    def test_a101(self):
        self._floor("A-101.00", 18)


class StrippedLayersFallBackToGeometry(unittest.TestCase):
    """A sheet exported without layers: correct via geometry, or refused."""

    def test_a103_correct_via_geometry(self):
        s, bad = _score("A-103.00", stripped=True)
        res = _run("A-103.00", "EF", stripped=True)
        self.assertEqual(res["method"], "geometry")
        self.assertEqual(res["fallback_reason"], "no wall layer")
        self.assertEqual((s["wrong"], s["correct"]), (0, 16), bad)

    def test_a100_correct_via_geometry(self):
        s, bad = _score("A-100.01", stripped=True)
        self.assertEqual((s["wrong"], s["correct"]), (0, 13), bad)

    def test_a101_fully_refused_never_wrong(self):
        s, bad = _score("A-101.00", stripped=True)
        self.assertEqual(s["wrong"], 0, bad)
        self.assertEqual(s["correct"], 0)
        self.assertEqual(s["refused"] + s["unknown"], 18, bad)


# ── the fail-safe cases (formerly scratch test_failsafe, 9) ───────────────

def _placed(res):
    return [r for r in res["records"] if r.get("tag")]


class AMergedRegionIsRefused(unittest.TestCase):
    """Geometry path on A-101.00: every unit and the corridor are one region."""

    def test_a101_every_item_is_refused(self):
        items = _placed(_run("A-101.00", "EF", True)) + \
            _placed(_run("A-101.00", "PTAC", True))
        self.assertEqual(len(items), 18)                  # 8 EF + 10 PTAC
        self.assertEqual([r["unit"] for r in items], [None] * 18)
        self.assertTrue(all(r["glyph_status"] == "unplaced" for r in items))
        self.assertTrue(all(r["reason"] for r in items))

    def test_a101_per_unit_split_is_unavailable_and_names_the_tags(self):
        for eq in ("EF", "PTAC"):
            res = _run("A-101.00", eq, True)
            self.assertIsNone(res["per_unit"])
            for t in ("2A", "2B", "2C"):
                self.assertIn(t, res["unavailable"] or "", (eq, res["unavailable"]))


class TwoPerUnitOnA103(unittest.TestCase):

    def test_ef(self):
        res = _run("A-103.00", "EF")
        self.assertEqual(res["total"], 8)
        self.assertEqual(res["per_unit"], {"4A": 2, "4B": 2, "4C": 2, "4D": 2})

    def test_ptac(self):
        res = _run("A-103.00", "PTAC")
        self.assertEqual(res["total"], 8)
        self.assertEqual(res["per_unit"], {"4A": 2, "4B": 2, "4C": 2, "4D": 2})


class A100PlacesNormally(unittest.TestCase):

    def test_ef_and_ptac_complete_and_nothing_refused(self):
        for eq in ("EF", "PTAC"):
            res = _run("A-100.01", eq)
            self.assertEqual(res["incomplete"], {}, eq)
            self.assertFalse([r for r in _placed(res)
                              if (r.get("reason") or "").startswith("refused: ")], eq)

    def test_1b_kitchen_fan_is_counted(self):
        """1B's kitchen fan label read `EE-2(100)` (E for F)."""
        res = _run("A-100.01", "EF")
        self.assertEqual([r["unit"] for r in _placed(res)
                          if r["tag"] == "EF-2"].count("1B"), 1)
        self.assertEqual(res["per_unit"], {"1A": 2, "1B": 2, "1C": 2, "1D": 2})

    def test_bike_room_ptac_is_non_unit(self):
        res = _run("A-100.01", "PTAC")
        self.assertEqual(res["total"], 5)
        self.assertEqual(res["per_unit"], {"1A": 1, "1B": 1, "1C": 1, "1D": 1,
                                           "non-unit:BIKE ROOM": 1})


class TheProseFilterIsTheLabelsInTagTest(unittest.TestCase):

    def test_verbatim_near_misses_pass_and_notes_drop(self):
        assert T is not None, "lib.plan_takeoff is not in this tree"
        tags, corr = EF
        self.assertTrue(T.tag_only("EE-2(100)", tags, corr))
        self.assertTrue(T.tag_only("EF=2(100)", tags, corr))
        self.assertTrue(T.tag_only("EF+1(50)", tags, corr))
        self.assertFalse(T.tag_only("CKDRAFT DAMPER FOR EF-1 FAN.", tags, corr))
        self.assertFalse(T.tag_only("ACKDRAFT DAMPER FOR EF-2 FAN.", tags, corr))


if __name__ == "__main__":
    unittest.main()
