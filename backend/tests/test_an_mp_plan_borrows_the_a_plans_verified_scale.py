"""An M or P plan borrows its architectural plan's VERIFIED scale, and only
when their registration is usable (Roy, ruling 5, 2026-10-28: "M/P borrow
the A sheet's verified scale only when registration to it is usable";
lib.plan_scale.borrow).

Measured on 588 Boyland (bv-worktrees/Q5_mp_borrow_scale_measure.md): no
M plan verifies its own 1/4" note - M-100 to M-106 measure 0 to 6 printed
dimensions, none agreeing - and the P plans print theirs as SHX vectors, so
they have no note in the text layer at all. Their underlay IS the A plan:
the registration is a pure shift matching hundreds of corners within an
inch, which is the evidence the two share a paper scale.

What this guards, each a condition that can fail:

  * the registration must be USABLE. The roof is the case: the old 4pt
    search put A-105.01/M-105.00 21.8in off on 108 anchors where the true
    peak holds 239, and called it usable. register() now refuses that offset
    (under half the best peak), and a borrow resting on it is refused - a
    test below forces the old search and asserts the refusal;
  * the lender's viewport must have verified on its OWN dimensions: never an
    unverified one (A-105.x's 3/32" BULKHEAD PLAN), never a borrowed one;
  * only M or P borrows, and only from A - never S, never M from P;
  * one drawing to one: more than half the matched anchors must join one
    lender view to one borrower view;
  * the shift must bound the scale inside AGREE_TOL (2r/D over the joined
    anchors - clustered anchors bound nothing);
  * a note the borrower prints must agree; one that says "no scale" refuses.

WRITTEN TO FAIL BY ASSERTION ON A TREE WITHOUT THE CHANGE: every test reaches
the new names through `_need()`, which turns a missing name into an
AssertionError rather than an error at collection.
"""
from __future__ import annotations

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

from lib import plan_scale as ps  # noqa: E402
from lib import plan_sheet as PS  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

QUARTER, EIGHTH = 1.5, 0.75


def _need():
    for mod, name in ((ps, "borrow"), (PS, "matched_anchors")):
        assert hasattr(mod, name), f"{mod.__name__} has no {name}: an M/P plan cannot borrow a scale"
    assert "borrowed" in ps.Viewport.__dataclass_fields__, \
        "plan_scale.Viewport records no provenance for a borrowed scale"


# ── synthetic sheets: one drawing each, a body of ink over [100, 1000] ────

def _note(ppi, text='1/4" = 1\'-0"'):
    return ps.ScaleNote(text=text, bbox=(0, 0, 1, 1), pt_per_in=ppi,
                        ratio=72 / ppi if ppi else None, nts=ppi is None)


def _sheet(views):
    """views: [(box (x0, y0, x1, y1), Viewport kwargs)] - each box one body."""
    lab = np.zeros((400, 400), dtype=int)
    vps = []
    for k, (box, kw) in enumerate(views, start=1):
        x0, y0, x1, y1 = (int(v / ps.CELL_PT) for v in box)
        lab[y0:y1, x0:x1] = k
        vps.append(ps.Viewport(bbox=box, drawing_bbox=box, body=k, **kw))
    return ps.Sheet(viewports=vps, labels=lab, width=1200, height=1200)


def _lender(verified=True, ppi=QUARTER):
    return _sheet([((100, 100, 1000, 1000),
                    dict(title="FOURTH FLOOR PLAN", note=_note(ppi), verified=verified,
                         pt_per_in=ppi if verified else None, agreeing=75 if verified else 1,
                         refusal="" if verified else "1 of 9 measured dimensions agree"))])


def _borrower(note=None, verified=False):
    kw = dict(title="FOURTH FLOOR HVAC PLAN" if note else "", note=note, verified=verified,
              pt_per_in=note.pt_per_in if verified else None,
              refusal="" if verified else "0 of 0 measured dimensions agree")
    return _sheet([((100, 100, 1000, 1000), kw)])


def _anchors(n=300, lo=150, hi=950, shift=(0.0, 0.0), seed=3):
    rng = np.random.default_rng(seed)
    A = rng.uniform(lo, hi, size=(n, 2))
    return A, A + np.asarray(shift) + rng.uniform(-0.4, 0.4, size=(n, 2))


USABLE = {"dx": 0.0, "dy": 0.0, "anchors": 300, "best_peak_anchors": 300,
          "best_peak": [0.0, 0.0], "spread": [0.95, 0.9], "rms_in": 0.2, "max_in": 0.4,
          "usable": True, "refused": None}
REFUSED = dict(USABLE, anchors=108, best_peak_anchors=239, usable=False,
               refused="the offset holds 108 anchors, under half the 239 of the best peak")


def _borrow(borrower="M-103.00", lender="A-103.00", b=None, a=None, reg_=USABLE, pts=None):
    _need()
    A, B = _anchors() if pts is None else pts
    return ps.borrow(borrower, b or _borrower(), lender, a or _lender(), reg_, A, B)


class AnMPPlanBorrows(unittest.TestCase):

    def test_an_m_plan_with_no_scale_of_its_own_borrows_the_a_plans(self):
        v, res = _borrow()
        self.assertEqual(res["status"], "borrowed", res.get("why"))
        self.assertEqual(res["pt_per_in"], QUARTER)
        self.assertEqual(v.pt_per_in, QUARTER)
        self.assertFalse(v.verified, "a borrowed scale is not the drawing's own verification")
        self.assertAlmostEqual(v.real_inches(18.0), 12.0)

    def test_the_provenance_names_the_lender_and_the_registration(self):
        v, res = _borrow()
        prov = v.borrowed
        self.assertEqual(prov["sheet"], "A-103.00")
        self.assertEqual(prov["viewport"], "FOURTH FLOOR PLAN")
        self.assertEqual(prov["note"], '1/4" = 1\'-0"')
        self.assertEqual(prov["agreeing"], 75)
        self.assertEqual(prov["registration"]["anchors"], 300)
        self.assertEqual(prov["registration"]["best_peak_anchors"], 300)
        self.assertTrue(prov["registration"]["usable"])
        self.assertEqual(prov["anchors_in_view"], 300)
        self.assertLessEqual(prov["scale_bound"], ps.AGREE_TOL)
        self.assertEqual(res["from"]["sheet"], "A-103.00")

    def test_a_p_plan_with_no_note_in_its_text_layer_borrows(self):
        v, res = _borrow(borrower="P-204.00")
        self.assertEqual(res["status"], "borrowed", res.get("why"))

    def test_a_printed_note_that_agrees_still_borrows(self):
        v, res = _borrow(b=_borrower(note=_note(QUARTER)))
        self.assertEqual(res["status"], "borrowed", res.get("why"))

    def test_a_plan_that_verifies_on_its_own_keeps_its_own(self):
        v, res = _borrow(b=_borrower(note=_note(QUARTER), verified=True))
        self.assertEqual(res["status"], "own")
        self.assertIsNone(v.borrowed)


class OnlyWhenTheRegistrationIsUsable(unittest.TestCase):

    def test_an_unusable_registration_lends_nothing(self):
        v, res = _borrow(reg_=REFUSED)
        self.assertIsNone(v)
        self.assertEqual(res["status"], "refused")
        self.assertIn("not usable", res["why"])
        self.assertIn("under half", res["why"])


class OnlyAVerifiedAPlanLends(unittest.TestCase):

    def test_an_unverified_a_view_lends_nothing(self):
        v, res = _borrow(a=_lender(verified=False))
        self.assertIsNone(v)
        self.assertIn("no scale of its own", res["why"])

    def test_a_borrowed_scale_is_never_lent_on(self):
        a = _lender()
        a.viewports[0].verified = False
        a.viewports[0].borrowed = {"sheet": "A-999.00"}
        v, res = _borrow(a=a)
        self.assertIsNone(v)
        self.assertIn("no scale of its own", res["why"])


class OnlyMOrPFromA(unittest.TestCase):

    def test_structural_does_not_borrow(self):
        v, res = _borrow(borrower="S-104.00")
        self.assertIsNone(v)
        self.assertIn("only M/P", res["why"])

    def test_nothing_borrows_from_a_non_architectural_sheet(self):
        for lender in ("P-103.00", "M-103.00", "S-104.00"):
            v, res = _borrow(borrower="M-103.00", lender=lender)
            self.assertIsNone(v, lender)
            self.assertIn("only from A", res["why"])

    def test_an_a_plan_does_not_borrow_from_another(self):
        v, res = _borrow(borrower="A-104.00")
        self.assertIsNone(v)


class TheBorrowItselfMustHold(unittest.TestCase):

    def test_anchors_split_between_two_views_lend_nothing(self):
        _need()
        a = _sheet([((100, 100, 500, 1000), dict(title="ROOF PLAN", note=_note(QUARTER),
                                                 verified=True, pt_per_in=QUARTER, agreeing=35)),
                    ((600, 100, 1000, 1000), dict(title="BULKHEAD PLAN", note=_note(QUARTER),
                                                  verified=True, pt_per_in=QUARTER, agreeing=9))])
        A = np.vstack([_anchors(150, 150, 450, seed=1)[0], _anchors(150, 650, 950, seed=2)[0]])
        v, res = ps.borrow("M-105.00", _borrower(), "A-105.01", a, USABLE, A, A.copy())
        self.assertIsNone(v)
        self.assertIn("one drawing to one", res["why"])

    def test_clustered_anchors_do_not_bound_the_scale(self):
        """30 anchors inside 20pt, worst residual 0.5pt: 2r/D = 5%."""
        _need()
        A, B = _anchors(30, 500, 520, seed=5)
        B = A.copy()
        B[0] += 0.5
        v, res = ps.borrow("M-103.00", _borrower(), "A-103.00", _lender(), USABLE, A, B)
        self.assertIsNone(v)
        self.assertIn("bounds the scale only", res["why"])

    def test_a_printed_note_that_contradicts_refuses(self):
        v, res = _borrow(b=_borrower(note=_note(EIGHTH, '1/8" = 1\'-0"')))
        self.assertIsNone(v)
        self.assertIn("contradict", res["why"])

    def test_a_note_that_says_no_scale_refuses(self):
        v, res = _borrow(b=_borrower(note=_note(None, "N.T.S.")))
        self.assertIsNone(v)
        self.assertIn("no scale", res["why"])

    def test_an_unscaled_viewport_still_refuses_a_length(self):
        _need()
        v = ps.Viewport(bbox=(0, 0, 1, 1), drawing_bbox=(0, 0, 1, 1), pt_per_in=QUARTER,
                        refusal="0 of 0 measured dimensions agree")
        with self.assertRaises(ValueError):
            v.real_inches(18.0)


# ── the real sheets ───────────────────────────────────────────────────────

_CACHE = {}


def _read(name, page):
    if (name, page) not in _CACHE:
        from lib.plan_page import PlanPage
        pg = PlanPage(str(require_pdf(name)), page)
        try:
            _CACHE[(name, page)] = (PS.load_sheet(pg), ps.read_sheet(pg))
        finally:
            pg.close()
    return _CACHE[(name, page)]


def _old_step(A, B, **kw):
    return _BT(A, B, coarse_pt=4.0, **kw)


_BT = PS.best_translation

ROOF_A, ROOF_M = ("AR - 8.18.26.pdf", 7, "A-105.01"), ("MH - 7.2.26.pdf", 7, "M-105.00")


def _borrow_real(a, m, reg_=None):
    _need()
    (adata, ash), (mdata, msh) = _read(a[0], a[1]), _read(m[0], m[1])
    r = PS.register(adata, mdata) if reg_ is None else reg_
    pa, pm = PS.matched_anchors(adata, mdata, r)
    return r, ps.borrow(m[2], msh, a[2], ash, r, pa, pm)


class TheRoofBorrowsOnlyFromItsTruePeak(unittest.TestCase):
    """M-105.00 on A-105.01: the roof, whose wrong peak was in production.
    A-105.01 holds a 3/32" BULKHEAD PLAN that does not verify above the 1/4"
    ROOF PLAN that does; only the roof plan may lend."""

    def test_at_the_true_peak_the_roof_borrows_from_the_roof_plan(self):
        r, (v, res) = _borrow_real(ROOF_A, ROOF_M)
        self.assertTrue(r["usable"], r.get("refused"))
        self.assertEqual(res["status"], "borrowed", res.get("why"))
        self.assertEqual(res["from"]["viewport"]["title"], "ROOF PLAN")
        self.assertEqual(res["pt_per_in"], QUARTER)
        self.assertEqual(v.borrowed["registration"]["anchors"], r["anchors"])

    def test_the_old_wrong_peak_lends_nothing(self):
        """The 4pt search's answer (5.99, -45.0): 108 anchors under the true
        239. register() refuses it, and so the borrow is refused - drop the
        usable condition and this borrows on a refused registration."""
        _need()
        (adata, _a), (mdata, _m) = _read(*ROOF_A[:2]), _read(*ROOF_M[:2])
        with patch.object(PS, "best_translation", _old_step):
            r = PS.register(adata, mdata)
        self.assertLess(np.hypot(r["dx"] - 5.99, r["dy"] + 45.0), 1.0, r)
        self.assertFalse(r["usable"])
        _r, (v, res) = _borrow_real(ROOF_A, ROOF_M, reg_=r)
        self.assertIsNone(v)
        self.assertEqual(res["status"], "refused")
        self.assertIn("under half", res["why"])


class TheGlyphPassRecordsEachMechanicalPlansScale(unittest.TestCase):
    """The reader: run_pass puts every pair's mechanical scale in its summary
    (plan_glyph_pass.mech_scale). M-103.00 on the filed A-103.00."""

    def test_m103_borrows_from_the_fourth_floor_plan(self):
        _need()
        from lib import plan_glyph_pass as gp
        self.assertTrue(hasattr(gp, "mech_scale"), "the glyph pass reads no mechanical scale")
        from lib.plan_page import PlanPage
        a_pdf, m_pdf = require_pdf("AR - 3.28.25.pdf"), require_pdf("MH - 7.2.26.pdf")
        pages = {"A": (a_pdf, 14), "M": (m_pdf, 5)}
        opened = []

        def open_page(p):
            pg = PlanPage(str(pages[p["k"]][0]), pages[p["k"]][1])
            opened.append(pg)
            return pg
        a_p, m_p = {"k": "A", "page_id": "a103"}, {"k": "M", "page_id": "m103"}
        try:
            f = {"arch_p": a_p, "mech_p": m_p, "a_sheet": "A-103.00", "m_sheet": "M-103.00",
                 "data": PS.load_sheet(open_page(a_p))}
            shared = {}
            res = gp.mech_scale(f, open_page, shared)
        finally:
            for pg in opened:
                pg.close()
        self.assertEqual(res["status"], "borrowed", res.get("why"))
        self.assertEqual(res["sheet"], "M-103.00")
        self.assertEqual(res["from"]["sheet"], "A-103.00")
        self.assertEqual(res["from"]["viewport"]["title"], "FOURTH FLOOR PLAN")
        self.assertEqual(res["pt_per_in"], QUARTER)
        self.assertTrue(res["registration"]["usable"])
        self.assertIn("m103", shared, "the mechanical read is not kept for the next track")


if __name__ == "__main__":
    unittest.main()
