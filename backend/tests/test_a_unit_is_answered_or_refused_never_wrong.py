"""EVERY ITEM IS ANSWERED RIGHT OR REFUSED - NEVER ANSWERED WRONG.

The product metric for "which apartment does this exhaust fan / PTAC serve":
per item, correct / wrong / UNKNOWN / refused.

THE GATE IS ZERO WRONG ON THE LAYER PATH (operator ruling 2026-10-06). The
geometric fallback is REPORTED, NOT GATED: it is the pipeline the layer path
replaces, and its fail-safe refuses rather than guesses. Its one known wrong:
A-100.01's EF-2(100) in 1D. The symbol is right - on the fan, since #657 -
and the frozen geometric map assigns 1D's kitchen counter strip to 1C. The
layer path answers 1D.

TRUTH IS PINNED from render reads of each sheet (2026-09-21/22), not computed
from any pipeline, and KEYED BY THE LABEL: (tag, the label's position on the
MECHANICAL sheet) -> the space the item serves. 47 items on three floors.

It used to be keyed by the item's position on the architectural sheet,
matched within 40pt. That position is the pipeline's own answer: when #657
moved each symbol from its label onto its equipment, positions moved up to
28in and the window stopped matching. The printed label does not move.

Scored 2026-10-06 on lib.plan_page after #657:
    layers path   47 correct, 0 wrong
    geometry path A-103.00 16/16, A-100.01 12 + 1 wrong, A-101.00 18 refused

Covered here:
  - the 47 truths on the PRIMARY (CAD-layer) path - gated;
  - the FALLBACK, by stripping every drawing's layer from the page - reported;
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
    from lib.plan_page import PlanPage
except ImportError:                      # pragma: no cover
    T = PlanPage = None

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

#: PINNED from render reads: (tag, label x, label y ON THE MECHANICAL SHEET)
#: -> the space the item serves. The label is what the sheet printed; it does
#: not move when the symbol finder changes.
TRUTH = {
    "A-103.00": [("EF-2", 1089.0, 438.4, "4A"), ("EF-2", 1618.2, 439.5, "4C"),
                 ("EF-1", 1647.7, 647.2, "4C"), ("EF-1", 1050.1, 655.0, "4A"),
                 ("EF-1", 1643.1, 830.1, "4D"), ("EF-1", 1050.1, 832.5, "4B"),
                 ("EF-2", 1617.3, 1040.9, "4D"), ("EF-2", 1089.5, 1041.1, "4B"),
                 ("PTAC-3", 1923.2, 507.6, "4C"), ("PTAC-3", 783.2, 508.2, "4A"),
                 ("PTAC-1", 1922.4, 660.9, "4C"), ("PTAC-1", 782.4, 666.3, "4A"),
                 ("PTAC-1", 1922.5, 813.3, "4D"), ("PTAC-1", 782.6, 820.3, "4B"),
                 ("PTAC-3", 1923.2, 967.5, "4D"), ("PTAC-3", 783.2, 968.7, "4B")],
    "A-100.01": [("EF-2", 1571.9, 560.9, "1C"), ("EF-1", 1068.7, 606.8, "1A"),
                 ("EF-2", 1189.0, 637.7, "1A"), ("EF-2", 1673.1, 703.9, "1D"),
                 ("EF-1", 1536.6, 740.0, "1C"), ("EF-1", 1130.3, 798.4, "1B"),
                 ("EF-2", 1159.2, 910.1, "1B"), ("EF-1", 1563.4, 918.7, "1D"),
                 ("PTAC-3", 782.3, 517.4, "1A"), ("PTAC-3", 1922.4, 584.6, "1C"),
                 ("PTAC-1", 781.2, 634.4, "non-unit:BIKE ROOM"),
                 ("PTAC-2", 1922.1, 758.6, "1D"), ("PTAC-3", 782.1, 821.2, "1B")],
    "A-101.00": [("EF-1", 1631.6, 645.9, "2C"), ("EF-1", 1067.5, 646.8, "2A"),
                 ("EF-2", 1546.3, 690.2, "2C"), ("EF-2", 1150.7, 690.3, "2A"),
                 ("EF-2", 1150.7, 803.7, "2B"), ("EF-2", 1546.2, 805.0, "2D"),
                 ("EF-1", 1071.2, 849.1, "2B"), ("EF-1", 1632.6, 849.7, "2D"),
                 ("PTAC-2", 965.3, 470.7, "2A"), ("PTAC-2", 1647.2, 470.8, "2C"),
                 ("PTAC-1", 1923.3, 514.0, "2C"), ("PTAC-1", 783.1, 514.6, "2A"),
                 ("PTAC-1", 1923.2, 667.1, "2C"), ("PTAC-1", 783.2, 672.6, "2A"),
                 ("PTAC-1", 1923.2, 819.8, "2D"), ("PTAC-1", 783.0, 826.4, "2B"),
                 ("PTAC-3", 1923.8, 973.7, "2D"), ("PTAC-3", 783.7, 974.8, "2B")],
}

#: a label is found where it was printed: OCR on the same render is
#: deterministic, and two labels of one tag are never this close
LABEL_MATCH_PT = 12.0


class _StrippedLayers:
    """The page with every drawing's CAD layer removed - a sheet exported
    flat, as another office might. Everything else is the real page."""

    def __init__(self, page):
        self._p = page

    def __getattr__(self, name):
        return getattr(self._p, name)

    @property
    def drawings(self):
        return [dict(d, layer="") for d in self._p.drawings]


_CACHE = {}


def _run(floor, eq, stripped=False):
    assert T is not None, "lib.plan_takeoff is not in this tree"
    key = (floor, eq, stripped)
    if key not in _CACHE:
        (afn, apn), (mfn, mpn), units = FLOORS[floor]
        a = PlanPage(require_pdf(afn), apn)
        m = PlanPage(require_pdf(mfn), mpn)
        tags, corr = EF if eq == "EF" else PTAC
        _CACHE[key] = T.run_takeoff(_StrippedLayers(a) if stripped else a, m,
                                    tags, corr, units, WIDEST_DOOR_IN)
    return _CACHE[key]


def _score(floor, stripped=False):
    """{verdict: n} and the non-correct details, against the pinned truth,
    each item matched to its truth BY ITS LABEL."""
    items = [r for eq in ("EF", "PTAC")
             for r in _run(floor, eq, stripped)["records"] if r.get("tag")]
    truth = TRUTH[floor]
    used, out, bad = set(), {"correct": 0, "wrong": 0, "unknown": 0,
                             "refused": 0, "unmatched": 0}, []
    for r in items:
        x, y = r["label_at"]
        best = min(((max(abs(tx - x), abs(ty - y)), i) for i, (tg, tx, ty, _u)
                    in enumerate(truth) if tg == r["tag"] and i not in used),
                   default=None)
        if best is None or best[0] > LABEL_MATCH_PT:
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
    """THE GATE: every item on the layer path answered, and answered right."""

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


class TheFallbackIsReportedNotGated(unittest.TestCase):
    """A sheet exported without layers goes to the geometric pipeline. Its
    score is PRINTED, not asserted (operator ruling 2026-10-06): it is what
    the layer path replaces. What is asserted is that it IS the fallback,
    and that every item was matched to its label - a report over items it
    never found would be a report of nothing."""

    def _report(self, floor, n):
        s, bad = _score(floor, stripped=True)
        res = _run(floor, "EF", stripped=True)
        print(f"\n{floor} geometry fallback: {s}  not correct: {bad}")
        self.assertEqual(res["method"], "geometry")
        self.assertEqual(res["fallback_reason"], "no wall layer")
        self.assertEqual((s["unmatched"], s["missed"]), (0, 0), bad)
        self.assertEqual(sum(s[k] for k in ("correct", "wrong", "unknown",
                                            "refused")), n)

    def test_a103(self):
        self._report("A-103.00", 16)

    def test_a100(self):
        self._report("A-100.01", 13)

    def test_a101(self):
        self._report("A-101.00", 18)


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
