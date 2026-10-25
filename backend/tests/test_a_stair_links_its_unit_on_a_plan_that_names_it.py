"""A STAIR LINKS ITS UNIT TO THE SAME UNIT ON A PLAN THAT NAMES IT.

On the filed AR set (3.28.25) the mezzanine A-104.00 prints 4A-4D itself, so
#747's seeding - which fills a plan that names no units - skipped it, every
duplex on the filed track stayed half an apartment, and "4A has 3 exhaust
fans" refused there. Ruling 2026-10-24: when the plan a stair reaches prints
its own unit tags, link source unit U to the unit tagged U on that plan,
only if ALL hold:
  1. the target is the plan the existing seeding rule picks (series + title
     ordinal check);
  2. exactly one unit is tagged U on the target;
  3. registration is usable on both sheets;
  4. the stair's registered landing point falls inside U's region there;
  5. any LOWER / UPPER words agree (lower level LOWER or none, upper level
     UPPER or none); a contradiction refuses.
Any condition failing: no link, and the whole-apartment count refuses as
before. Every stair between the two sheets for U must pass - one end
refusing is a contradiction, not outvoted.

Measured 2026-10-24 (local, fixture PDFs): A-103 -> A-104 registers at
(0.00, -0.00), 1603 anchors, usable; A-103 -> M-103 1195 and A-104 -> M-104
836 anchors, usable; each of 4A-4D holds one stair (UP on A-103, DN on
A-104), lands inside the same unit on the other sheet (30 pt in from the
wall by the public stair core for 4A/4B, 15 pt for 4C/4D, by render), and
says LOWER on A-103 and UPPER on A-104. All four link.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_glyph_pass as G  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from tests.test_a_located_count_is_complete_or_refused import (  # noqa: E402
    PID, _census, _floor, _numbered, _pages)
from tests.test_a_sheet_it_cannot_place_still_counts import (  # noqa: E402
    EF, PTAC, FAMS, QTY, _sheet_scope)
from tests import test_a_located_count_is_complete_or_refused as _LC  # noqa: E402

_LC.FLOORS.setdefault("104", ("MEZZANINE FLOOR HVAC PLANS", ["4A", "4B", "4C", "4D"]))
_LC.FLOORS.setdefault("105", ("ROOF HVAC PLANS", []))


def _present():
    assert hasattr(G, "link_refusal"), \
        "no stair links its unit to a plan that names it in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── the rule, on built floors ─────────────────────────────────────────────

class _Member:
    """A membership map of rectangles: tag -> (x0, y0, x1, y1)."""

    def __init__(self, rects):
        self.rects = rects

    def at(self, x, y):
        for t, (x0, y0, x1, y1) in self.rects.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return t
        return ""


RECTS = {"4A": (1100, 560, 1300, 800), "4B": (1100, 820, 1300, 1060)}


def _floor_(sheet, title, *, stairs=None, words=("LOWER",), tags=("4A", "4B"),
            printed=None, incomplete=None, partner=True):
    """A floor as the pass's pre-pass leaves it: units, membership map,
    level words and stair labels in 4A, and its partner registration."""
    ml = {t: [] for t in tags}
    for w in words:
        ml.setdefault("4A", []).append(f"level word {w} at (1127, 590)")
    for lab, x, y in (stairs or []):
        ml.setdefault("4A", []).append(f"stair label {lab} at ({round(x)}, {round(y)})")
    printed = printed if printed is not None else [(t, 1127.0, 600.0 if t == "4A" else 900.0)
                                                   for t in tags]
    return {"arch_p": {"sheet_number": sheet, "sheet_title": title}, "a_sheet": sheet,
            "m_sheet": "M" + sheet[1:], "data": {"words": list(printed)},
            "units": {"tags": list(tags), "multi_level": ml},
            "space": {"units": {t: object() for t in tags if t in RECTS},
                      "refused": [], "incomplete": dict(incomplete or {})},
            "member": _Member({t: r for t, r in RECTS.items() if t in tags}),
            "stairs": {"4A": list(stairs)} if stairs else {},
            "partner_reg": {"usable": partner, "refused": None if partner else "under half"}}


def _pair(**kw):
    """A-103.00 4A with one stair UP at (1244, 691); A-104.00 4A with one DN
    at (1151, 631). `kw` overrides either side: src_* / tgt_*."""
    s = {k[4:]: v for k, v in kw.items() if k.startswith("src_")}
    t = {k[4:]: v for k, v in kw.items() if k.startswith("tgt_")}
    src = _floor_("A-103.00", "FOURTH FLOOR PLAN", **dict(
        dict(stairs=[("UP", 1244.0, 691.0)], words=("LOWER",)), **s))
    tgt = _floor_(kw.get("tgt_sheet", "A-104.00"), kw.get("tgt_title", "MEZZANINE PLAN"),
                  **dict(dict(stairs=[("DN", 1151.0, 631.0)], words=("UPPER",)),
                         **{k: v for k, v in t.items() if k not in ("sheet", "title")}))
    return src, tgt


def _reg(usable=True, dx=0.0, dy=0.0):
    return {"dx": dx, "dy": dy, "usable": usable, "refused": None if usable else "under half"}


def _seed(floors, reg=None):
    with patch("lib.plan_sheet.register", lambda a, b: reg or _reg()):
        return G.seed_from_stairs(floors, lambda p: None, 56.0)


def _linked(f, u="4A"):
    return [e for e in f["units"]["multi_level"].get(u, []) if "linked from" in e]


class EveryConditionHolds(unittest.TestCase):

    def test_the_unit_is_linked_on_both_sheets_from_both_ends(self):
        _present()
        src, tgt = _pair()
        notes = _seed([src, tgt])
        self.assertEqual(_linked(tgt), ["linked from A-103.00: stair label UP at (1244, 691)"], notes)
        self.assertEqual(_linked(src), ["linked from A-104.00: stair label DN at (1151, 631)"], notes)
        self.assertIn("stair label UP at (1244, 691) reaches A-104.00",
                      src["units"]["multi_level"]["4A"])
        self.assertIn("stair label DN at (1151, 631) reaches A-103.00",
                      tgt["units"]["multi_level"]["4A"])
        self.assertEqual(src["units"]["linked"]["4A"][0]["lands"], [1244.0, 691.0])
        # a link is not a seed: the target keeps its own reading
        self.assertEqual(tgt["units"]["tags"], ["4A", "4B"])
        self.assertNotIn("seeded", tgt["units"])

    def test_no_level_words_at_all_is_agreement(self):
        _present()
        src, tgt = _pair(src_words=(), tgt_words=())
        _seed([src, tgt])
        self.assertTrue(_linked(tgt))


class AnyConditionFailingRefuses(unittest.TestCase):
    """One method per condition: each leaves both sheets unlinked."""

    def _refused(self, src, tgt, why, reg=None):
        notes = _seed([src, tgt], reg)
        self.assertEqual(_linked(tgt), [], notes)
        self.assertEqual(_linked(src), [], notes)
        self.assertFalse(any(e.endswith(" reaches A-104.00") or e.endswith(" reaches A-103.00")
                             for f in (src, tgt) for e in f["units"]["multi_level"].get("4A", [])),
                         notes)
        self.assertTrue(any(why in n for n in notes), notes)
        return notes

    # 1 - the seeding rule's target
    def test_1_a_title_that_contradicts_the_series(self):
        _present()
        src, tgt = _pair(tgt_title="SIXTH FLOOR PLAN")
        self._refused(src, tgt, "the title and the series disagree")

    def test_1_no_plan_the_stair_reaches(self):
        _present()
        src, tgt = _pair(tgt_sheet="A-106.00", tgt_title="MEZZANINE PLAN")
        self._refused(src, tgt, "no plan A-104")

    # 2 - exactly one unit tagged U
    def test_2_the_target_names_no_such_unit(self):
        _present()
        src, tgt = _pair(tgt_tags=("4B",), tgt_stairs=None)
        self._refused(src, tgt, "A-104.00 names no unit 4A")

    def test_2_the_unit_has_no_region_of_its_own(self):
        _present()
        src, tgt = _pair(tgt_incomplete={"4A": "its label at (820, 1282) is in no room"})
        self._refused(src, tgt, "4A has no region of its own on A-104.00")

    def test_2_the_tag_is_printed_in_two_units(self):
        _present()
        src, tgt = _pair(tgt_printed=[("4A", 1127.0, 600.0), ("4A", 1127.0, 900.0),
                                      ("4B", 1127.0, 950.0)])
        self._refused(src, tgt, "prints 4A in more than one unit (4A, 4B)")

    # 3 - registration usable on both sheets
    def test_3_source_to_target_does_not_register(self):
        _present()
        src, tgt = _pair()
        self._refused(src, tgt, "A-103.00 -> A-104.00 does not register", reg=_reg(usable=False))

    def test_3_the_source_to_its_mechanical_partner_does_not_register(self):
        _present()
        src, tgt = _pair(src_partner=False)
        self._refused(src, tgt, "A-103.00 -> M-103.00 does not register")

    def test_3_the_target_to_its_mechanical_partner_does_not_register(self):
        _present()
        src, tgt = _pair(tgt_partner=False)
        self._refused(src, tgt, "A-104.00 -> M-104.00 does not register")

    # 4 - the landing point inside U's region
    def test_4_the_stair_lands_in_another_unit(self):
        _present()
        src, tgt = _pair()
        self._refused(src, tgt, "in 4B, not 4A", reg=_reg(dy=250.0))

    def test_4_the_stair_lands_in_no_unit(self):
        _present()
        src, tgt = _pair()
        self._refused(src, tgt, "in no unit, not 4A", reg=_reg(dx=400.0))

    # 5 - LOWER / UPPER agree
    def test_5_the_lower_level_says_upper(self):
        _present()
        src, tgt = _pair(src_words=("UPPER",))
        self._refused(src, tgt, "A-103.00 calls 4A UPPER, but the stair makes it the lower level")

    def test_5_the_upper_level_says_lower(self):
        _present()
        src, tgt = _pair(tgt_words=("LOWER",))
        self._refused(src, tgt, "A-104.00 calls 4A LOWER, but the stair makes it the upper level")

    def test_5_a_unit_that_says_both(self):
        _present()
        src, tgt = _pair(src_words=("LOWER", "UPPER"))
        self._refused(src, tgt, "A-103.00 calls 4A UPPER")

    # every stair between the two sheets must pass
    def test_one_end_refusing_is_no_link_from_either(self):
        _present()
        src, tgt = _pair(tgt_stairs=[("DN", 1151.0, 900.0)])   # A-104's DN sits in 4B there
        notes = _seed([src, tgt])
        self.assertEqual(_linked(tgt), [], notes)
        self.assertEqual(_linked(src), [], notes)
        self.assertTrue(any("not linked - every stair between the two sheets must pass, "
                            "and 1 of 2 refused" in n for n in notes), notes)


# ── the gate sums the linked apartment ─────────────────────────────────────

STAIRS = {"4A": (1244, 691), "4B": (1244, 893), "4C": (1505, 691), "4D": (1505, 893)}
DN = {"4A": (1151, 631), "4B": (1151, 953), "4C": (1598, 631), "4D": (1598, 953)}


def _filed(linked=True, upper_stair=True):
    """The filed track's fourth floor and mezzanine as the pass now writes
    them: both sheets name 4A-4D; A-103.00's symbols 1 EF-1 + 1 EF-2 per
    unit, A-104.00's 1 EF-1 per unit; with or without the link, and with or
    without a stair label of the upper unit's own (without one, the upper
    sheet's only link is "linked from")."""
    lower, upper = {}, {}
    for u in STAIRS:
        (x, y), (dx_, dy_) = STAIRS[u], DN[u]
        lower[u] = ["level word LOWER at (1127, 590)",
                    f"stair label UP at ({x}, {y})" + (" reaches A-104.00" if linked else "")]
        upper[u] = ["level word UPPER at (1127, 590)"]
        if upper_stair:
            upper[u].append(f"stair label DN at ({dx_}, {dy_})"
                            + (" reaches A-103.00" if linked else ""))
        if linked:
            if upper_stair:
                lower[u].append(f"linked from A-104.00: stair label DN at ({dx_}, {dy_})")
            upper[u].append(f"linked from A-103.00: stair label UP at ({x}, {y})")
    rows = _floor("103", EF, [(t, u) for u in STAIRS for t in ("EF-1", "EF-2")], multi=lower)
    rows += _floor("104", EF, [("EF-1", u) for u in STAIRS], multi=upper)
    rows += _sheet_scope("M-106.00", "BULKHEAD HVAC PLANS", PTAC, [("PTAC-1", 1)])
    rows = _numbered(rows)
    pages = _pages(rows)
    census = []
    for c in _census(rows, pages, FAMS):
        if c.get("kind") == "family":
            c = S.glyph_census("family", PID, pages, c["count"], family=c["family"],
                               tags=c["tags"], qty=QTY.get(c["family"]))
        census.append(c)
    return rows + census


class TheGateCountsTheLinkedApartmentWhole(unittest.TestCase):

    def test_linked_from_is_a_link(self):
        _present()
        self.assertEqual(S._LEVEL_LINK.findall("linked from A-103.00: stair label UP at (1, 2)"),
                         ["A-103.00"])

    def test_4a_has_3_exhaust_fans_on_the_filed_set(self):
        _present()
        recs = _filed()
        self.assertTrue(_ok("4A has 3 exhaust fans.", recs))
        self.assertTrue(_ok("4D has 2 EF-1.", recs))
        self.assertFalse(_ok("4A has 2 exhaust fans.", recs))

    def test_a_link_from_one_end_alone_is_followed(self):
        """The upper unit prints no stair of its own: "linked from" is the
        only thing on the mezzanine that says where the apartment goes."""
        _present()
        recs = _filed(upper_stair=False)
        self.assertTrue(_ok("4A has 3 exhaust fans.", recs))
        self.assertFalse(_ok("4A has 2 exhaust fans.", recs))

    def test_unlinked_it_still_refuses(self):
        _present()
        recs = _filed(linked=False)
        for s in ("4A has 3 exhaust fans.", "4A has 2 exhaust fans.", "4A has 1 exhaust fan."):
            self.assertFalse(_ok(s, recs), s)


# ── on the real sheets ─────────────────────────────────────────────────────

class OnTheFiledSheets(unittest.TestCase):
    """The filed A-103.00 and A-104.00 (AR 3.28.25 p14, p15) with M-103.00
    and M-104.00 (MH 7.2.26 p5, p6), through the pass's own pre-pass reading
    and seed_from_stairs. Loaded once, inside the first test: a presence
    check in setUpClass reports as an ERROR, not a failure by assertion."""

    _done = False

    @classmethod
    def _load(cls):
        if cls._done:
            return
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        from lib.plan_takeoff import Units
        from lib import plan_derive as D
        ar, mh = str(require_pdf("AR - 3.28.25.pdf")), str(require_pdf("MH - 7.2.26.pdf"))
        cls.pages = {}

        def open_page(p):
            k = (p["f"], p["n"])
            if k not in cls.pages:
                cls.pages[k] = PlanPage(p["f"], p["n"])
            return cls.pages[k]
        cls.floors = []
        for n, m, sheet, title in ((14, 5, "A-103.00", "FOURTH FLOOR PLAN"),
                                   (15, 6, "A-104.00", "MEZZANINE PLAN")):
            arch_p = {"f": ar, "n": n, "sheet_number": sheet, "sheet_title": title}
            pg = open_page(arch_p)
            data = load_sheet(pg)
            u = D.unit_tags(data["words"], data["corners"])
            sp = build_space(pg, u["tags"], 56.0, data)
            member = Units(sp["units"], sp["lo"], sp["cell_pt"], sp["refused"], sp, sp["tags"])
            cls.floors.append({
                "arch_p": arch_p, "mech_p": {"f": mh, "n": m}, "a_sheet": sheet,
                "m_sheet": "M" + sheet[1:], "data": data, "space": sp, "member": member,
                "units": dict(u, multi_level=D.multi_level_units(pg.directed_words, member.at,
                                                                 u["tags"])),
                "stairs": D.unit_stairs(pg.directed_words, member.at, u["tags"])})
        cls.notes = G.seed_from_stairs(cls.floors, open_page, 56.0)
        cls._done = True

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "pages", {}).values():
            p.close()

    def test_all_four_duplexes_link_from_both_ends(self):
        _present()
        self._load()
        a103, a104 = self.floors
        for u, (x, y) in STAIRS.items():
            self.assertEqual(_linked(a104, u),
                             [f"linked from A-103.00: stair label UP at ({x}, {y})"], self.notes)
            self.assertEqual(_linked(a103, u),
                             [f"linked from A-104.00: stair label DN at ({DN[u][0]}, {DN[u][1]})"],
                             self.notes)
        self.assertEqual(a104["units"]["tags"], ["4A", "4B", "4C", "4D"])
        self.assertFalse(any("not linked" in n for n in self.notes), self.notes)

    def test_both_partner_registrations_were_read_and_usable(self):
        _present()
        self._load()
        for f in self.floors:
            self.assertTrue(f["partner_reg"]["usable"], f["a_sheet"])

    def test_each_landing_point_is_inside_its_unit(self):
        _present()
        self._load()
        a103, a104 = self.floors
        for src, tgt in ((a103, a104), (a104, a103)):
            for u, links in src["units"]["linked"].items():
                (link,) = links
                self.assertEqual(tgt["member"].at(*link["lands"]), u, (src["a_sheet"], u))


if __name__ == "__main__":
    unittest.main()
