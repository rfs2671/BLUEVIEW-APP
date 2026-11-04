"""A light fixture is counted by its TAG and the drawing beside it (lane T6).

No RCP on 588 Thomas S Boyland prints a legend swatch for a light fixture
(T2 refused them all); every RCP prints a tag - L1, L2, L4, L5, DS - beside
each fixture. Operator ruling 74: count by the tag. lib.plan_light_fixtures:

  * a TAG WITH NO FIXTURE DRAWING beside it is refused, never counted;
  * a SHEET WITH NO TAGS is refused at sheet scope, never "zero fixtures";
  * a COUNT THAT DISAGREES WITH A PRINTED TOTAL STATES NEITHER;
  * it is not a counting basis for the chat gate, and a stored count is a
    "not verified" takeoff line and a review item until the sub-bid
    benchmark (rulings 77, 78 as for T2).

Unit worlds are synthetic pages; the last class reads the fixture PDFs
(skipped without them).
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402


def _lf(*names):
    """The module, with the names a test needs - an assertion, not an
    ImportError, when it is missing (so the control fails by assertion)."""
    try:
        m = importlib.import_module("lib.plan_light_fixtures")
    except ImportError as e:  # pragma: no cover - the control
        raise AssertionError(f"lib.plan_light_fixtures is missing: {e}")
    for n in names:
        assert hasattr(m, n), f"lib.plan_light_fixtures has no {n}"
    return m


# ── a synthetic page ───────────────────────────────────────────────────────

BLACK = (0, 0, 0)


def circle(cx, cy, r, layer="E-LITE", colour=BLACK):
    k = 0.5523 * r
    p = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)]
    items = [("c", p[0], (cx + r, cy + k), (cx + k, cy + r), p[1]),
             ("c", p[1], (cx - k, cy + r), (cx - r, cy + k), p[2]),
             ("c", p[2], (cx - r, cy - k), (cx - k, cy - r), p[3]),
             ("c", p[3], (cx + k, cy - r), (cx + r, cy - k), p[0])]
    return {"items": items, "rect": (cx - r, cy - r, cx + r, cy + r), "layer": layer, "colour": colour}


def rect(x0, y0, x1, y1, layer="E-LITE", colour=BLACK):
    a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
    return {"items": [("l", a, b), ("l", b, c), ("l", c, d), ("l", d, a)],
            "rect": (x0, y0, x1, y1), "layer": layer, "colour": colour}


def line(x0, y0, x1, y1, layer="A-WALL"):
    return {"items": [("l", (x0, y0), (x1, y1))], "rect": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
            "layer": layer, "colour": BLACK}


def word(t, x0, y0, h=8.0, w=None):
    w = w if w is not None else 0.6 * h * len(t)
    return (t, x0, y0, x0 + w, y0 + h, "ltr")


def downlight(cx, cy):
    """L2's drawing: two concentric circles."""
    return [circle(cx, cy, 4.5), circle(cx, cy, 3.0)]


def linear(cx, cy):
    """L4's drawing: a lens inside its housing."""
    return [rect(cx - 8.6, cy - 2.4, cx + 8.6, cy + 2.4), rect(cx - 7.7, cy - 1.45, cx + 7.7, cy + 1.45)]


def tagged(tag, cx, cy, draw):
    """A fixture at (cx, cy) with its tag printed just below it."""
    return draw(cx, cy), word(tag, cx - 5, cy + 6)


class Page:
    def __init__(self, drawings, words, width=2000.0, height=1400.0):
        self.drawings, self.directed_word_boxes = list(drawings), list(words)
        self.width, self.height = width, height


def world(extra_d=(), extra_w=(), title="FIRST FLOOR RCP PLAN"):
    """Three L2 and two L4 fixtures, each tagged, above a drawing title."""
    d, w = [], []
    for cx in (100, 200, 300):
        dd, ww = tagged("L2", cx, 100, downlight)
        d += dd
        w.append(ww)
    for cx in (150, 250):
        dd, ww = tagged("L4", cx, 200, linear)
        d += dd
        w.append(ww)
    d += list(extra_d)
    w += list(extra_w)
    tw = []
    x = 60.0
    for t in title.split():
        tw.append(word(t, x, 400, h=8))
        x += 0.6 * 8 * len(t) + 4
    return Page(d, w + tw)


VOCAB = ["L1", "L2", "L3", "L4", "L5", "DS"]


def count(page, vocab=VOCAB):
    return _lf("count_sheet").count_sheet(page, vocab, title_edge=1800.0)


def status(res):
    out = {}
    for t in res["tags"]:
        out.setdefault((t["tag"], t["status"]), 0)
        out[(t["tag"], t["status"])] += 1
    return out


# ── 1. a tag and the drawing beside it ─────────────────────────────────────

class ATagAndItsDrawing(unittest.TestCase):

    def test_each_tag_is_counted_with_the_drawing_beside_it(self):
        res = count(world())
        self.assertNotIn("refused", res)
        self.assertEqual(res["counts"], {"FIRST FLOOR RCP PLAN": {"L2": 3, "L4": 2}})
        self.assertEqual({tuple(t["levels"]) for t in res["tags"]}, {(1,)})

    def test_a_tag_with_no_fixture_drawing_is_refused(self):
        m = _lf("NO_DRAWING")
        # an L2 printed in an empty part of the sheet; the nearest drawing is
        # 60pt away - far beyond the tag's own text height
        res = count(world(extra_w=[word("L2", 600, 600)]))
        lone = [t for t in res["tags"] if t["box"][0] == 600]
        self.assertEqual(len(lone), 1)
        self.assertEqual(lone[0]["status"], "refused")
        self.assertEqual(lone[0]["why"], m.NO_DRAWING)
        self.assertEqual(res["counts"]["FIRST FLOOR RCP PLAN"]["L2"], 3)

    def test_one_drawing_beside_two_tags_counts_for_neither(self):
        # a second L2 printed beside the first fixture: which is whose is not said
        res = count(world(extra_w=[word("L2", 104, 96)]))
        self.assertEqual(status(res).get(("L2", "refused")), 2, status(res))
        self.assertEqual(res["counts"]["FIRST FLOOR RCP PLAN"]["L2"], 2)

    def test_a_nearer_drawing_of_another_block_is_passed_over(self):
        # an exhaust box sits right on one L4 tag; that L4's own lens is above
        # it, and the other two L4 tags say which block an L4 is
        d3, w3 = tagged("L4", 350, 200, linear)
        res = count(world(extra_d=[rect(244, 205.5, 256, 212)] + d3, extra_w=[w3]))
        l4 = [t for t in res["tags"] if t["tag"] == "L4"]
        self.assertTrue(all(t["status"] == "counted" for t in l4), l4)
        self.assertTrue(all(t["drawing_box"][3] - t["drawing_box"][1] < 5 for t in l4))

    def test_a_tag_beside_only_another_block_is_refused(self):
        m = _lf("OTHER_DRAWING")
        # a fourth L2 whose only neighbour is an exhaust box
        res = count(world(extra_d=[rect(495, 95, 505, 105)], extra_w=[word("L2", 495, 106)]))
        t = [t for t in res["tags"] if t["box"][0] == 495][0]
        self.assertEqual(t["status"], "refused")
        self.assertIn("is not the drawing its other 3 L2 tags sit beside", t["why"])

    def test_a_fixture_drawn_with_no_tag_is_listed_never_counted(self):
        res = count(world(extra_d=downlight(400, 100)))
        self.assertEqual([u["could_be"] for u in res["untagged"]], [["L2"]])
        self.assertEqual(res["counts"]["FIRST FLOOR RCP PLAN"]["L2"], 3)

    def test_a_block_at_another_insertion_scale_is_the_same_block(self):
        # RCP-001.00's roof L4 is 1.125x the floors'
        big = [rect(400 - 9.7, 197.3, 400 + 9.7, 202.7), rect(400 - 8.6, 198.4, 400 + 8.6, 201.6)]
        res = count(world(extra_d=big, extra_w=[word("L4", 395, 206)]))
        self.assertEqual(status(res), {("L2", "counted"): 3, ("L4", "counted"): 3})

    def test_a_tag_printed_twice_is_one_tag(self):
        res = count(world(extra_w=[word("L2", 95, 106)]))
        self.assertEqual(status(res), {("L2", "counted"): 3, ("L4", "counted"): 2})


# ── 2. which words are tags ────────────────────────────────────────────────

class WhichWordsAreTags(unittest.TestCase):

    def test_a_sheet_with_no_tags_is_refused_at_sheet_scope(self):
        m = _lf("NO_TAGS", "fixture_rows")
        page = Page(downlight(100, 100) + linear(200, 200), [word("EX", 100, 106)])
        res = count(page)
        self.assertEqual(res.get("refused"), m.NO_TAGS)
        self.assertEqual(res["counts"], {})
        rows = m.fixture_rows(res, {"sheet_number": "RCP-002.00", "project_id": "p"})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["scope"], rows[0]["status"], rows[0]["count"]),
                         ("sheet", "refused", None))

    def test_a_set_with_no_lighting_schedule_counts_nothing(self):
        m = _lf("NO_VOCAB")
        res = count(world(), vocab=[])
        self.assertEqual(res["refused"], m.NO_VOCAB)

    def test_a_schedule_entry_is_not_a_tag(self):
        # L2 in a ruled table row (QUANTITY tables print the tag between rules)
        table = [line(500, 595, 700, 595), line(500, 605, 700, 605)]
        res = count(world(extra_d=table, extra_w=[word("L2", 560, 596)]))
        self.assertEqual(res["table_entries"], 1)
        self.assertFalse([t for t in res["tags"] if t["box"][0] == 560])

    def test_control_device_marks_are_not_fixture_tags(self):
        res = count(world(extra_w=[word("EX", 100, 120), word("A1", 300, 120)]))
        self.assertEqual({t["tag"] for t in res["tags"]}, {"L2", "L4"})

    def test_the_vocabulary_is_the_schedule_column_and_L_dash_1_is_L1(self):
        m = _lf("schedule_tags", "norm_tag")
        ws = [word("LIGHTING", 100, 100, h=10), word("SCHEDULE", 160, 100, h=10),
              word("TAG", 110, 130), word("DESCRIPTION", 150, 130),
              word("L-1", 110, 160), word("L-2", 110, 190), word("FIXTURE", 300, 130),
              word("#", 400, 130), word("OF", 410, 130), word("FIXTURE", 425, 130)]
        got = m.schedule_tags(ws)
        self.assertEqual(got["tags"], ["L-1", "L-2"])
        self.assertEqual(m.norm_tag("L-1"), "L1")
        # the plan's L2 is the schedule's L-2; L4 is in no schedule, so no tag
        res = count(world(), vocab=got["tags"])
        self.assertEqual(status(res), {("L2", "counted"): 3})

    def test_levels_of_a_typical_plan(self):
        m = _lf("levels_named")
        self.assertEqual(m.levels_named("SECOND FLOOR - THIRD FLOOR REFLECTED CEILING PLAN"), [2, 3])
        self.assertEqual(m.levels_named("ROOF RCP PLAN"), ["roof"])
        self.assertEqual(m.levels_named("MEZZANINE FLOOR RCP PLAN"), ["mezzanine"])


# ── 3. the printed totals: a disagreement states neither ───────────────────

def _res(tag, n, levels):
    return {"tags": [{"tag": tag, "status": "counted", "levels": levels, "title": "X",
                      "box": (0, 0, 1, 1), "drawing_box": [0, 0, 1, 1]} for _ in range(n)]}


def _tot(level, tag, qty, space="CORRIDOR", source="RCP-002.00", table="type x floor"):
    return {"level": level, "tag": tag, "qty": qty, "space": space, "source": source, "table": table}


class APrintedTotal(unittest.TestCase):

    def test_equal_agrees(self):
        m = _lf("cross_check")
        c = m.cross_check({"S": _res("L4", 2, [1])}, [_tot(1, "L4", 2, "STAIRS")])
        self.assertEqual([(x["where"], x["status"], x["count"], x["printed"]) for x in c],
                         [(1, "agrees", 2, 2), ("building", "agrees", 2, 2)])

    def test_more_drawn_than_a_spaces_total_is_not_checked_beyond_it(self):
        m = _lf("cross_check")
        c = m.cross_check({"S": _res("L2", 25, [1])}, [_tot(1, "L2", 11)])
        self.assertEqual(c[0]["status"], "not checked beyond its spaces")
        self.assertEqual((c[0]["count"], c[0]["printed"]), (25, 11))

    def test_a_count_that_disagrees_with_a_printed_total_states_neither(self):
        m = _lf("cross_check", "fixture_rows")
        c = m.cross_check({"S": _res("L4", 1, [2])}, [_tot(2, "L4", 2, "STAIRS")])
        floor = [x for x in c if x["where"] == 2][0]
        self.assertEqual(floor["status"], "conflict")
        self.assertIsNone(floor["count"])
        self.assertIsNone(floor["printed"])
        # and the stored row of that floor's drawing carries no count
        res = _res("L4", 1, [2])
        res["untagged"] = []
        rows = m.fixture_rows(res, {"sheet_number": "RCP-001.00"}, checks=c)
        self.assertEqual([(r["status"], r["count"]) for r in rows], [("conflict", None)])
        self.assertNotIn("positions", rows[0])

    def test_two_printed_totals_that_disagree_state_neither(self):
        m = _lf("cross_check")
        c = m.cross_check({"S": _res("L5", 2, [4])},
                          [_tot(4, "L5", 2), _tot(4, "L5", 3, "common space", "RCP-001.00", "per floor")])
        floor = [x for x in c if x["where"] == 4][0]
        self.assertEqual((floor["status"], floor["count"], floor["printed"]), ("conflict", None, None))

    def test_a_typical_plan_counts_on_each_level_it_names(self):
        m = _lf("floor_counts")
        fc = m.floor_counts({"A.3.2": _res("L1", 27, [2, 3])})
        self.assertEqual({k: v["count"] for k, v in fc.items()}, {(2, "L1"): 27, (3, "L1"): 27})
        self.assertTrue(fc[(2, "L1")]["typical"])


# ── 4. not a counting source; a not-verified takeoff line ──────────────────

class NotWiredToTheGate(unittest.TestCase):

    def test_the_basis_is_not_a_counting_basis(self):
        m = _lf("COUNT_BASIS")
        from lib import plan_search as S
        self.assertEqual(m.COUNT_BASIS, "fixture_tag")
        self.assertNotIn(m.COUNT_BASIS, S.COUNTING_BASES)

    def test_plan_search_never_names_the_module_or_the_basis(self):
        _lf()
        src = (Path(__file__).resolve().parents[1] / "lib" / "plan_search.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bplan_light_fixtures\b", src))
        self.assertIsNone(re.search(r"\bfixture_tag\b", src))

    def test_every_row_is_not_verified(self):
        m = _lf("fixture_rows", "NOT_VERIFIED")
        res = count(world(extra_d=downlight(400, 100), extra_w=[word("L2", 600, 600)]))
        rows = m.fixture_rows(res, {"sheet_number": "RCP-001.00", "project_id": "p"})
        self.assertTrue(rows)
        self.assertTrue(all(r["verified"] is False and r["verification"] == m.NOT_VERIFIED for r in rows))
        self.assertEqual(sorted(r["status"] for r in rows),
                         ["counted", "counted", "refused", "untagged"])


class ATakeoffLine(unittest.TestCase):

    def _rows(self):
        m = _lf("fixture_rows")
        res = count(world())
        return m.fixture_rows(res, {"sheet_number": "RCP-001.00", "project_id": "proj1",
                                    "file_id": "f-ar", "page_number": 25,
                                    "file_name": "AR - 3.28.25.pdf"})

    def test_each_count_is_a_not_verified_line_with_no_quantity(self):
        m = _lf("NOT_VERIFIED", "TRADE")
        from lib import plan_takeoff_export as X
        t = X.build([], (), {}, light_rows=self._rows())
        mine = [ln for ln in t.refused if ln.trade == m.TRADE]
        self.assertEqual(sorted(ln.tag for ln in mine), ["L2", "L4"])
        for ln in mine:
            self.assertIsNone(ln.qty)
            self.assertEqual(ln.reason, m.NOT_VERIFIED)
            self.assertEqual(ln.level, "FIRST FLOOR")
            self.assertIn("RCP-001.00", ln.source)
        self.assertFalse([ln for ln in t.lines if ln.trade == m.TRADE])

    def test_no_rows_no_change(self):
        _lf()
        from lib import plan_takeoff_export as X
        a, b = X.build([], (), {}), X.build([], (), {}, light_rows=[])
        self.assertEqual((a.lines, a.refused), (b.lines, b.refused))

    def test_each_line_queues_one_review_item(self):
        m = _lf("TRADE")
        from datetime import datetime, timezone
        from lib import plan_takeoff_export as X
        from lib import review_queue
        t = X.build([], (), {}, light_rows=self._rows())
        items = [review_queue.from_takeoff("co", "proj1", trade=ln.trade, item_name=f"{ln.item} {ln.tag}",
                                           scope=f"{ln.scope} {ln.level}", track=ln.set_label,
                                           reason=ln.reason, sheets=[ln.sheets],
                                           now=datetime.now(timezone.utc))
                 for ln in t.refused if ln.trade == m.TRADE]
        self.assertEqual(len({i["_id"] for i in items}), 2)
        self.assertTrue(all(i["reason"] == review_queue.REASON_TAKEOFF_REFUSED for i in items))


# ── 5. on the drawings themselves (fixture PDFs; skipped without them) ──────

class OnTheBoylandDrawings(unittest.TestCase):

    @property
    def m(self):
        return _lf("schedule_tags", "count_sheet", "printed_totals", "cross_check")

    @property
    def P(self):
        from lib.plan_page import PlanPage
        return PlanPage

    def _filed(self):
        ar = str(require_pdf("AR - 3.28.25.pdf"))
        sched = self.P(ar, 26)
        vocab = self.m.schedule_tags(sched.directed_word_boxes)["tags"]
        rcp1 = self.P(ar, 25)
        return vocab, rcp1, sched

    def test_the_filed_sets_vocabulary_is_rcp002s_lighting_schedule(self):
        vocab, _r, _s = self._filed()
        self.assertEqual(vocab, ["L1", "L2", "L3", "L4", "L5", "DS"])

    def test_rcp001_counts_per_drawing(self):
        vocab, rcp1, _s = self._filed()
        res = self.m.count_sheet(rcp1, vocab)
        self.assertEqual(res["counts"], {
            "FIRST FLOOR RCP PLAN": {"L1": 5, "L2": 25, "L4": 2, "L5": 3, "DS": 4},
            "SECOND FLOOR RCP PLAN": {"L1": 4, "L2": 24, "L4": 2, "L5": 2},
            "THIRD FLOOR RCP PLAN": {"L1": 4, "L2": 24, "L4": 2, "L5": 2},
            "FOURTH FLOOR RCP PLAN": {"L1": 4, "L2": 19, "L4": 2, "L5": 2},
            "MEZZANINE FLOOR RCP PLAN": {"L4": 2},
            "ROOF RCP PLAN": {"L4": 2, "L5": 2, "DS": 2}})
        self.assertEqual(res["table_entries"], 20)
        self.assertFalse([t for t in res["tags"] if t["status"] != "counted"])
        self.assertEqual(res["untagged"], [])

    def test_rcp002s_printed_totals_agree_where_they_cover_the_fixture(self):
        vocab, rcp1, sched = self._filed()
        results = {"RCP-001.00": self.m.count_sheet(rcp1, vocab)}
        totals = (self.m.printed_totals(rcp1.directed_word_boxes, vocab, "RCP-001.00")
                  + self.m.printed_totals(sched.directed_word_boxes, vocab, "RCP-002.00"))
        b = {c["tag"]: c for c in self.m.cross_check(results, totals) if c["where"] == "building"}
        self.assertEqual({k: (b[k]["status"], b[k]["printed"]) for k in ("L4", "L5", "DS")},
                         {"L4": ("agrees", 12), "L5": ("agrees", 11), "DS": ("agrees", 6)})
        self.assertEqual((b["L2"]["status"], b["L2"]["count"], b["L2"]["printed"]),
                         ("not checked beyond its spaces", 92, 22))

    def test_rcp002_has_no_tags_and_is_refused_at_sheet_scope(self):
        vocab, _r, sched = self._filed()
        res = self.m.count_sheet(sched, vocab)
        self.assertEqual(res["refused"], self.m.NO_TAGS)

    def test_the_second_sets_first_floor(self):
        su = str(require_pdf("588 THOMAS BOYLAND ST SET_UPDATED.pdf"))
        sched = self.P(su, 25)
        got = self.m.schedule_tags(sched.directed_word_boxes)
        self.assertEqual(got["tags"], ["L-1", "L-2", "L-3", "L-4", "L-5"])
        res = self.m.count_sheet(self.P(su, 26), got["tags"])
        self.assertEqual(list(res["counts"].values()), [{"L1": 60}])
        self.assertEqual([t["levels"] for t in res["titles"]], [[1]])


if __name__ == "__main__":
    unittest.main()
