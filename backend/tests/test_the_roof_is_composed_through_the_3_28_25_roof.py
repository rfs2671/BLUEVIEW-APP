"""THE ROOF IS COMPOSED THROUGH THE 3.28.25 ROOF (lib.plan_roof_frame).

Roy, 2026-11-01, ruling 3 (roof140 diagnosis): the gas-change roof (A-105.01,
AR 6.9.26 p2) is drawn at 5/16 in = 1 ft and prints no scale note; a pure
translation search against the 1/4 in roofs finds a wrong peak (33 of 687,
margin 1.10), so every P sheet's roof stacks were refused. The fix is a
RECORDED scale per viewport (seven measured spans, not a registration that
happened to pass) and the composed path P -> 3.28.25 roof -> gas roof, each
link behind the conservative pair, carrying the SUM of every link's worst-case
residual plus the 0.17 ft origin ambiguity.

Each test fails on origin/main by ASSERTION (_present / hasattr), not by an
import error: the modules are imported lazily. Fixture tests skip without the
PDFs (PLAN_FIXTURE_PDFS) and say so."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

MOD = "lib.plan_roof_frame"


def _present(tc):
    tc.assertIsNotNone(importlib.util.find_spec(MOD), "lib/plan_roof_frame.py does not exist")
    return importlib.import_module(MOD)


def _link(name, best, second, ca, cb, max_in=0.9, rms=0.2, usable=True, dx=0.0, dy=0.0):
    from lib import plan_roof_frame as rf
    r = {"dx": dx, "dy": dy, "anchors": best, "best_peak_anchors": best,
         "second_peak_anchors": second, "margin": round(best / second, 3) if second else None,
         "offset_from_best_pt": 0.0, "rms_in": rms, "max_in": max_in, "usable": usable,
         "refused": None if usable else "refused"}
    return r, rf.link_view(name, r, ca, cb)


class TheScaleIsRecordedWithItsEvidence(unittest.TestCase):
    def test_the_gas_roof_scale_is_derived_from_seven_spans(self):
        rf = _present(self)
        c = rf.scale_check()
        self.assertTrue(c["ok"])
        self.assertEqual(c["spans"], 7)
        self.assertAlmostEqual(c["ratio"], 1.2521, places=3)       # roof140: 1.2519-1.2523
        self.assertAlmostEqual(c["pt_per_ft"], 22.54, places=1)    # 5/16 in = 22.5 nominal
        self.assertLessEqual(c["spread"], 0.001)                   # stated uncertainty ~0.1%
        self.assertGreaterEqual(c["distinct"], 2)

    def test_a_span_that_disagrees_fails_the_check(self):
        rf = _present(self)
        keep = rf.SCALE_SPANS
        n, a, g = keep[0]
        try:
            rf.SCALE_SPANS = ((n, a, g * 1.005),) + keep[1:]
            self.assertFalse(rf.scale_check()["ok"])
        finally:
            rf.SCALE_SPANS = keep
        self.assertTrue(rf.scale_check()["ok"])

    def test_too_few_or_all_equal_spans_are_not_evidence(self):
        rf = _present(self)
        keep = rf.SCALE_SPANS
        try:
            rf.SCALE_SPANS = keep[:2]
            self.assertFalse(rf.scale_check()["ok"])
            rf.SCALE_SPANS = tuple(keep[0] for _ in range(5))      # copies of one length
            self.assertFalse(rf.scale_check()["ok"])
        finally:
            rf.SCALE_SPANS = keep

    def test_the_records_per_viewport(self):
        rf = _present(self)
        gas = rf.scale_record(rf.GAS_HASH, rf.GAS_PAGE, 1500.0, 900.0)
        self.assertIsNotNone(gas)
        self.assertTrue(gas.verified)
        self.assertAlmostEqual(gas.pt_per_ft, 22.54, places=1)
        self.assertEqual(gas.agreeing, 7)
        self.assertIn("ratio", gas.basis)
        roof = rf.scale_record(rf.REF_HASH, rf.REF_PAGE, 1500.0, 800.0)
        self.assertEqual((roof.title, roof.pt_per_ft, roof.verified), ("ROOF PLAN", 18.0, True))
        owner = rf.scale_record(rf.OWNER_HASH, rf.OWNER_PAGE, 1500.0, 800.0)
        self.assertEqual((owner.pt_per_ft, owner.verified), (18.0, True))

    def test_the_bulkhead_note_is_recorded_but_never_a_verified_scale(self):
        rf = _present(self)
        notes = [r for r in rf.RECORDS if r.title == "BULKHEAD PLAN"]
        self.assertEqual(len(notes), 2)                             # the 3.28.25 page and the owner's
        for r in notes:
            self.assertEqual((r.status, r.agreeing, r.pt_per_ft), ("noted", 0, 6.75))
            self.assertFalse(r.verified)
        # a point inside the bulkhead plan gets no scale from the roof record
        self.assertIsNone(rf.scale_record(rf.REF_HASH, rf.REF_PAGE, 400.0, 200.0))

    def test_apply_records_scales_only_viewports_without_a_scale_of_their_own(self):
        rf = _present(self)
        from lib import plan_scale as ps
        own = ps.Viewport(bbox=(0, 0, 1, 1), drawing_bbox=(207, 339, 2139, 1182), title="ROOF PLAN",
                          verified=True, pt_per_in=1.5, agreeing=27)
        bulk = ps.Viewport(bbox=(0, 0, 1, 1), drawing_bbox=(75, 105, 753, 357), title="BULKHEAD PLAN",
                           refusal="0 of 0 measured dimensions agree")
        sh = ps.Sheet(viewports=[bulk, own], labels=np.zeros((1, 1), int), width=1, height=1)
        out = rf.apply_records(sh, rf.REF_HASH, rf.REF_PAGE)
        self.assertFalse(out.viewports[0].verified)                  # noted: applied to nothing
        self.assertIsNone(out.viewports[0].recorded)
        self.assertIs(out.viewports[1], own)                         # its own dimensions stand
        gas_vp = ps.Viewport(bbox=(0, 0, 1, 1), drawing_bbox=(162, 306, 2586, 1359),
                             refusal="no title bar with a scale note in the text layer")
        sh2 = ps.Sheet(viewports=[gas_vp], labels=np.zeros((1, 1), int), width=1, height=1)
        g = rf.apply_records(sh2, rf.GAS_HASH, rf.GAS_PAGE).viewports[0]
        self.assertTrue(g.verified)
        self.assertAlmostEqual(g.pt_per_in * 12, 22.54, places=1)
        self.assertEqual(g.agreeing, 7)
        self.assertEqual(g.recorded["status"], "verified")
        other = rf.apply_records(sh2, "0" * 32, 2).viewports[0]       # any other page: untouched
        self.assertFalse(other.verified)

    def test_a_recorded_scale_is_never_lent(self):
        _present(self)
        from lib import plan_scale as ps
        src = inspect.getsource(ps.borrow)
        self.assertIn("va.recorded", src)


class TheWorstCaseIsSummedNotRms(unittest.TestCase):
    def test_every_links_max_is_added_then_the_origin(self):
        rf = _present(self)
        wc = rf.worst_case_in([0.92, 0.90])
        self.assertAlmostEqual(wc["sum_links_in"], 1.82, places=3)
        self.assertAlmostEqual(wc["origin_ambiguity_in"], 2.04, places=3)
        self.assertAlmostEqual(wc["total_in"], 3.86, places=3)
        self.assertGreater(wc["total_in"], math.hypot(0.92, 0.90) + 2.04)   # not root-sum-square

    def test_the_origin_ambiguity_is_the_envelope_inside_the_outer_wall(self):
        rf = _present(self)
        # 3.28.25 outer wall rectangle 70.0 x 35.67 ft vs the structural envelope 69.67 x 35.42 ft
        self.assertAlmostEqual(rf.origin_ambiguity_ft(), 0.17, places=2)
        self.assertEqual(rf.ORIGIN_AMBIGUITY_FT, 0.17)
        e, o = rf.ENVELOPE_PT, rf.OUTER_WALL_PT
        self.assertAlmostEqual((o[2] - o[0]) / 18, 70.0, places=2)
        self.assertAlmostEqual((e[2] - e[0]) / 18, 69.667, places=2)
        self.assertAlmostEqual((e[3] - e[1]) / 18, 35.417, places=2)

    def test_a_composed_registration_carries_both_links_and_the_origin(self):
        rf = _present(self)
        p = _link("P-105 -> 3.28.25 roof", 732, 388, 968, 1962, max_in=0.90, rms=0.04)
        g = _link("gas -> 3.28.25 roof", 365, 113, 943, 687, max_in=0.92, rms=0.19)
        c = rf.compose(p, g, rf.measured_ratio())
        self.assertTrue(c["usable"])
        self.assertAlmostEqual(c["max_in"], 0.90 + 0.92 + 2.04, places=3)
        self.assertEqual(c["composed"]["worst_case"]["links_in"], [0.9, 0.92])
        self.assertEqual(len(c["composed"]["links"]), 2)
        self.assertGreater(c["max_in"], max(0.90, 0.92) + 2.0)


class TheConservativePairGuardsEveryLink(unittest.TestCase):
    def test_s_106_stays_unplaced(self):
        rf = _present(self)
        s = _link("S-106 -> 3.28.25 roof", 48, 32, 592, 1500, max_in=0.96)     # 0.0811, margin 1.5
        g = _link("gas -> 3.28.25 roof", 365, 113, 943, 687)
        self.assertFalse(s[1]["accepted"])
        self.assertAlmostEqual(s[1]["fraction"], 0.0811, places=3)
        c = rf.compose(s, g, rf.measured_ratio())
        self.assertFalse(c["usable"])
        self.assertIn("anchor fraction", c["refused"])

    def test_a_thin_margin_refuses_either_link(self):
        rf = _present(self)
        good = _link("g", 365, 113, 943, 687)
        thin = _link("p", 745, 640, 968, 1700)                                  # margin 1.16
        self.assertFalse(rf.compose(thin, good, 1.2521)["usable"])
        self.assertFalse(rf.compose(good, thin, 1.2521)["usable"])

    def test_the_wrong_unit_scale_peak_is_refused(self):
        rf = _present(self)
        wrong = _link("gas at unit scale", 33, 30, 943, 687)                    # roof140 attempt 1
        good = _link("p", 732, 388, 968, 1962)
        self.assertFalse(wrong[1]["accepted"])
        self.assertFalse(rf.compose(good, wrong, 1.0)["usable"])

    def test_a_link_register_offset_refused_stays_refused(self):
        rf = _present(self)
        refused = _link("p", 900, 100, 968, 1000, usable=False)
        good = _link("g", 365, 113, 943, 687)
        self.assertFalse(rf.compose(refused, good, 1.2521)["usable"])

    def test_the_scale_evidence_must_hold(self):
        rf = _present(self)
        p, g = _link("p", 732, 388, 968, 1962), _link("g", 365, 113, 943, 687)
        c = rf.compose(p, g, 1.2521, scale_ok=False)
        self.assertFalse(c["usable"])
        self.assertIn("scale evidence", c["refused"])

    def test_only_plumbing_sheets_are_composed_and_sprinkler_roof_rows_stay_out(self):
        rf = _present(self)
        self.assertTrue(rf.composable("P-105.00"))
        self.assertTrue(rf.composable("P-206.00"))
        for sheet in ("SP-004.00", "S-106.00", "M-105.00", "M-106.00", "A-105.01", None):
            self.assertFalse(rf.composable(sheet), sheet)


def _scene(seed=7, n=420, ratio=None, d_gas=(-73.09, -95.31), d_p=(120.5, -40.25)):
    """ref roof corners; the gas sheet = (ref + d_gas) * ratio; a P sheet = ref + d_p."""
    from lib import plan_roof_frame as rf
    ratio = rf.measured_ratio() if ratio is None else ratio
    rng = np.random.default_rng(seed)
    ref = np.column_stack([rng.uniform(850, 2150, n), rng.uniform(480, 1100, n)])
    ref = np.round(ref * 4) / 4
    keep = rng.random(n) < 0.7
    gas = (ref[keep] + np.array(d_gas)) * ratio
    gas = np.vstack([gas, np.column_stack([rng.uniform(900, 2400, 120), rng.uniform(480, 1250, 120)])])
    p = ref[rng.random(n) < 0.8] + np.array(d_p)
    p = np.vstack([p, np.column_stack([rng.uniform(900, 2300, 150), rng.uniform(480, 1100, 150)])])
    return ({"corners": ref}, {"corners": gas}, {"corners": p}, ratio, d_gas, d_p)


class ASyntheticComposedPath(unittest.TestCase):
    def test_p_to_gas_through_the_reference_roof(self):
        rf = _present(self)
        from lib import plan_stacks as S
        ref, gas, p, ratio, d_gas, d_p = _scene()
        got = rf.compose_route(gas, p, ref, p_name="P-105.00")
        self.assertTrue(got["usable"], got["refused"])
        self.assertAlmostEqual(got["scale"], ratio, places=6)
        # a point on the reference roof, seen on the P sheet, lands on the gas roof
        r = np.array([1500.0, 800.0])
        on_p = r + np.array(d_p)
        gx, gy = S.to_arch(on_p[0], on_p[1], got)
        want = (r + np.array(d_gas)) * ratio
        self.assertLess(math.hypot(gx - want[0], gy - want[1]), 1.0)
        self.assertEqual(len(got["composed"]["links"]), 2)
        self.assertAlmostEqual(got["max_in"], sum(l["max_in"] for l in got["composed"]["links"]) + 2.04, places=2)
        # and the direct registration at unit scale is the wrong peak the diagnosis found
        from lib.plan_sheet import register_offset
        direct = register_offset(gas, p)
        from lib import plan_registration_confidence as conf
        self.assertTrue(conf.confidence(direct, len(gas["corners"]), len(p["corners"]))["would_refuse"])

    def test_the_wrong_scale_is_not_composed(self):
        rf = _present(self)
        ref, gas, p, ratio, *_ = _scene()
        # gas drawn at the nominal 1.25: 0.17% off; at 1.30 clearly wrong
        got = rf.compose(rf.p_to_ref(p, ref), rf.gas_to_ref(gas, ref, ratio=1.30), 1.30)
        self.assertFalse(got["usable"])

    def test_the_gas_link_is_shared_between_p_sheets(self):
        rf = _present(self)
        ref, gas, p, ratio, *_ = _scene()
        cache = {}
        calls = []

        def counting(a, b, **kw):
            from lib.plan_sheet import register_offset
            calls.append(len(b["corners"]))
            return register_offset(a, b, **kw)
        rf.compose_route(gas, p, ref, cache=cache, register=counting)
        rf.compose_route(gas, p, ref, cache=cache, register=counting)
        self.assertEqual(len(calls), 3)          # gas once, P twice

    def test_roof_position_in_feet_and_worst_case(self):
        rf = _present(self)
        x, y = rf.ENVELOPE_PT[0] + 18.0 * 10, rf.ENVELOPE_PT[3] - 18.0 * 5
        pos = rf.roof_position(x, y, "ref")
        self.assertEqual((pos["x_ft"], pos["y_ft"]), (10.0, 5.0))
        self.assertAlmostEqual(pos["worst_case_in"], 2.04, places=3)       # the origin alone
        g = {"dx": -73.09, "dy": -95.31, "max_in": 0.92}
        k = rf.measured_ratio()
        gp = rf.roof_position((x + g["dx"]) * k, (y + g["dy"]) * k, "gas", gas_link=g)
        self.assertEqual((gp["x_ft"], gp["y_ft"]), (10.0, 5.0))
        self.assertAlmostEqual(gp["worst_case_in"], 0.92 + 2.04, places=3)
        pl = {"dx": 120.5, "dy": -40.25, "max_in": 0.9}
        pp = rf.roof_position(x + 120.5, y - 40.25, "p", p_link=pl)
        self.assertEqual((pp["x_ft"], pp["y_ft"]), (10.0, 5.0))
        with self.assertRaises(ValueError):
            rf.roof_position(0, 0, "nowhere")


class TheStackStageTakesTheComposedPath(unittest.TestCase):
    def test_the_stage_has_the_hook(self):
        _present(self)
        from lib import plan_stacks as S
        self.assertTrue(hasattr(S, "_composed_pair"),
                        "origin/main has no composed roof path: the filed roof stacks are unplaced")
        self.assertIn("via_pages", inspect.signature(S.run_stacks).parameters)

    def test_a_plain_registration_view_is_what_it_was(self):
        _present(self)
        from lib import plan_stacks as S
        reg = {"dx": 1.0, "dy": 2.0, "anchors": 900, "best_peak_anchors": 900,
               "second_peak_anchors": 400, "margin": 2.25, "offset_from_best_pt": 0.0,
               "rms_in": 0.1, "max_in": 0.5, "usable": True}
        view = S._reg_view(reg, True, [])
        self.assertEqual(sorted(view), sorted(["dx", "dy", "anchors", "best_peak_anchors",
                                               "second_peak_anchors", "margin", "offset_from_best_pt",
                                               "rms_in", "max_in", "usable", "why_not"]))
        self.assertEqual(S.to_arch(10.0, 20.0, reg), (9.0, 18.0))

    def test_a_composed_stack_is_placed_scaled_and_carries_the_worst_case(self):
        rf = _present(self)
        from lib import plan_stacks as S
        p = _link("P-105.00 -> 3.28.25 roof", 732, 388, 968, 1962, max_in=0.90, dx=120.5, dy=-40.25)
        g = _link("gas -> 3.28.25 roof", 365, 113, 943, 687, max_in=0.92, dx=-73.09, dy=-95.31)
        comp = rf.compose(p, g, rf.measured_ratio())
        tag = {"id": "V-1", "letter": "V", "number": 1, "x": 1000.0, "y": 700.0,
               "leaders": [{"tip": (1010.0, 700.0),
                            "stack": {"x": 1620.5, "y": 659.75, "r": 4.0, "layers": ["P-VENT"],
                                      "systems": ["vent"]}}]}
        p_page = {"sheet_number": "P-105.00", "page_id": "p", "file_name": "PL", "page_number": 7}
        a_page = {"sheet_number": "A-105.01", "page_id": "a", "file_name": "AR", "page_number": 2,
                  "file_hash": rf.GAS_HASH}
        rows = S.stack_rows("filed", p_page, a_page, [tag], comp, True, [])
        row = rows[0]
        k = rf.measured_ratio()
        self.assertEqual(row["status"], "located")
        self.assertIsNone(row["placement_refused"])
        want = ((1620.5 - comp["dx"]) * k, (659.75 - comp["dy"]) * k)
        self.assertAlmostEqual(row["at_arch"][0], want[0], places=1)
        self.assertAlmostEqual(row["footprint_arch"]["r"], 4.0 * k, places=1)
        self.assertEqual(row["registration"]["composed"]["worst_case"]["total_in"], round(0.9 + 0.92 + 2.04, 3))
        self.assertAlmostEqual(row["registration"]["max_in"], 3.86, places=2)
        pos = row["composed_position"]
        self.assertAlmostEqual(pos["x_ft"], round((1620.5 - 120.5 - rf.ENVELOPE_PT[0]) / 18, 3), places=3)
        self.assertAlmostEqual(pos["worst_case_in"], 0.90 + 0.92 + 2.04, places=2)   # both links and the origin

    def test_a_refused_composition_leaves_the_direct_refusal(self):
        rf = _present(self)
        from lib import plan_stacks as S
        direct = {"dx": 415.0, "dy": 161.0, "usable": False}
        a = {"file_hash": rf.GAS_HASH, "page_number": rf.GAS_PAGE}
        # the 3.28.25 roof is not among the pages
        reg, ok, why = S._composed_pair(a, {"sheet_number": "P-105.00"}, {}, {}, direct, ["old"], [],
                                        lambda p: None, {})
        self.assertFalse(ok)
        self.assertIs(reg, direct)
        self.assertEqual(why[0], "old")
        self.assertIn("not among the project's pages", why[1])
        # an architectural page that is not the gas roof is never routed
        other = {"file_hash": rf.REF_HASH, "page_number": 11}
        reg, ok, why = S._composed_pair(other, {"sheet_number": "P-100.00"}, {}, {}, direct, ["old"],
                                        [{"file_hash": rf.REF_HASH, "page_number": rf.REF_PAGE}],
                                        lambda p: None, {})
        self.assertEqual((ok, why), (False, ["old"]))
        # a sprinkler or structural sheet is not composed
        reg, ok, why = S._composed_pair(a, {"sheet_number": "SP-004.00"}, {}, {}, direct, ["old"],
                                        [{"file_hash": rf.REF_HASH, "page_number": rf.REF_PAGE}],
                                        lambda p: None, {})
        self.assertEqual((ok, why), (False, ["old"]))

    def test_continuity_leaves_a_composed_roof_row_out(self):
        _present(self)
        from lib import plan_stacks as S
        base = {"status": "located", "track": "filed", "tag_id": "V-1", "plumbing_sheet": "P-104.00",
                "at_arch": (100.0, 100.0), "registration": {"usable": True}}
        roof = dict(base, plumbing_sheet="P-105.00", at_arch=(5000.0, 5000.0),
                    registration={"usable": True, "composed": {"links": []}})
        out = S.continuity([base, roof])
        self.assertEqual(out[0]["floors"], ["P-104.00"])
        self.assertTrue(out[0]["same_place"])

    def test_no_via_pages_means_no_composed_call(self):
        _present(self)
        from lib import plan_stacks as S
        src = inspect.getsource(S.run_stacks)
        self.assertIn("if not ok and not lv and via_pages:", src)


class TheServerHandsOverTheRoofPage(unittest.TestCase):
    def test_the_glyph_pass_gives_the_stack_stage_the_superseded_roof(self):
        _present(self)
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        i = src.index("_stacks.run_stacks, by_track, open_page")
        near = src[i - 1800:i + 200]
        self.assertIn("_roof_frame.REF_HASH", near)
        self.assertIn("document_page_index" in src and "_glyph_inputs(pid)", near)
        self.assertIn("via_pages or None", src[i:i + 200])   # none found: the stage is what it was


class OnTheRealRoofs(unittest.TestCase):
    """The roof140 numbers, re-measured on the PDFs through the shared
    register_offset (about a minute): skipped, and said so, without them."""

    @classmethod
    def setUpClass(cls):
        from tests.fixture_pdfs import require
        cls.pdf = {k: require(n) for k, n in (("ref", "AR - 3.28.25.pdf"),
                                              ("gas", "AR - 6.9.26 (Gas change).pdf"),
                                              ("pl", "PL - 6.29.26.pdf"), ("st", "ST - 7.29.26.pdf"))}

    def _sheet(self, key, page):
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        return load_sheet(PlanPage(str(self.pdf[key]), page))

    def test_the_roof_links_and_s_106(self):
        rf = _present(self)
        ref, gas = self._sheet("ref", 16), self._sheet("gas", 2)
        g_raw, g = rf.gas_to_ref(gas, ref)
        self.assertTrue(g["accepted"], g)
        self.assertGreaterEqual(g["best_peak_anchors"], 340)
        self.assertGreaterEqual(g["fraction"], 0.5)
        self.assertGreaterEqual(g["margin"], 3.0)
        self.assertLess(g["max_in"], 1.0)
        self.assertAlmostEqual(g["dx"], -73.09, delta=2.0)
        self.assertAlmostEqual(g["dy"], -95.31, delta=2.0)
        for page, name in ((7, "P-105.00"), (14, "P-206.00")):
            pr, pv = rf.p_to_ref(self._sheet("pl", page), ref, name=name)
            self.assertTrue(pv["accepted"], pv)
            self.assertGreaterEqual(pv["fraction"], 0.7)
            self.assertGreaterEqual(pv["margin"], 1.8)
        # S-106: 48 of 592 = 0.081 < 0.10 under the conservative pair
        sr, sv = rf.p_to_ref(self._sheet("st", 10), ref, name="S-106.00")
        self.assertFalse(sv["accepted"], sv)
        self.assertLess(sv["fraction"], 0.10)
        self.assertEqual(sv["corners"][1], 592)


if __name__ == "__main__":
    unittest.main()
