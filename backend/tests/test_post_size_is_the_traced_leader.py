"""A POST'S SIZE IS THE LABEL ITS LEADER IS TRACED TO, AND A SCHEDULE SIZE GOES ONLY TO A VERIFIED END POST.

Two rules in lib.plan_structural, measured in membersize/ and membersize_rev2/ on the Boyland framing plans:

  1. TRACED LEADER. The pass used to give a post the nearest size word within 40pt of its leader's far end. On
     S-102 that put "(2) 6J18" on a post whose leader is printed from "(2) 6SW16" (the 6J18 callout of the next
     post stood nearer). A size is now the label at the other end of the leader polyline that lands on the post
     (arrowhead apex within 3pt of exactly one post); no distance rule, no guess.
  2. END POSTS ONLY. Legend 7 sizes a post from S-301's END MEMBERS. 84 posts got that size; 72 are end posts of
     a frame whose SW tag is read from the plan and whose S-301 cell is one designation. 12 are not (8 SW 3 posts
     mid-frame; 4 roof posts of SW 1 / SW 2 where S-301 prints "-"): their size is now unknown, not a guess.

Each test fails on origin/main by ASSERTION, not by an import error.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402
from lib import plan_structural as T  # noqa: E402

TEXT = "SET_GENERAL_TEXT"             # a leader layer: no xref prefix
GRID = "X-REF|SET_GENERAL_GRID"
POSTL = "X-REF|SET_GENERAL_TEXT"       # the post symbol's layer (xref: not a leader)


def _d(items, layer):
    xs = [p[0] for it in items for p in it[1:]]
    ys = [p[1] for it in items for p in it[1:]]
    return {"items": items, "layer": layer, "rect": (min(xs), min(ys), max(xs), max(ys)), "colour": (0, 0, 0)}


def _post(x0, y0):
    """The built-up post symbol: a 9pt square, its middle stroke, and the H inside."""
    x1, y1 = x0 + 9, y0 + 9
    return [_d([("l", (x0, y0), (x1, y0)), ("l", (x1, y0), (x1, y1)), ("l", (x1, y1), (x0, y1)),
                ("l", (x0, y1), (x0, y0)), ("l", (x0 + 4.3, y0), (x0 + 4.3, y1))], POSTL),
            _d([("l", (x0 + 1, y0 + 1), (x0 + 4, y0 + 1)), ("l", (x0 + 1, y1 - 1), (x0 + 4, y1 - 1)),
                ("l", (x0 + 5, y0 + 1), (x0 + 8, y0 + 1)), ("l", (x0 + 5, y1 - 1), (x0 + 8, y1 - 1)),
                ("l", (x0 + 2, y0 + 1), (x0 + 2, y1 - 1))], POSTL)]


def _arrow(ax, ay, dx):
    """An arrowhead whose apex is (ax, ay), opening away from it by dx."""
    return _d([("l", (ax, ay), (ax + dx, ay - 3)), ("l", (ax + dx, ay - 3), (ax + dx, ay + 3)),
               ("l", (ax + dx, ay + 3), (ax, ay))], TEXT)


def _leader(x_from, x_to, y):
    return _d([("l", (x_from, y), (x_to, y))], TEXT)


class _Page:
    def __init__(self, drawings, words, w=2592.0, h=1728.0):
        self.drawings, self.directed_words, self.width, self.height = drawings, words, w, h


def _grid():
    return [_d([("l", (200, 150), (2000, 150))], GRID), _d([("l", (200, 880), (2000, 880))], GRID),
            _d([("l", (300, 100), (300, 900))], GRID), _d([("l", (1900, 100), (1900, 900))], GRID)]


def _label(x, y, mult, size):
    return [(mult, x, y, "ltr"), (size, x + 28, y, "ltr")]


def _sizes(page):
    return [e["attrs"]["size"] for e in T.read_elements(page)["elements"] if e["element"] == "post"]


def _post_with_leader(label_words, decoys=()):
    """A post at (700, 400); a leader from `label_words` to it, arrowhead on its edge."""
    dr = _grid() + _post(700, 400) + [_leader(556, 693, 404.5), _arrow(700.5, 404.5, -7)]
    return _Page(dr, list(label_words) + list(decoys))


class TheLeaderNamesThePost(unittest.TestCase):

    def test_the_size_is_the_label_the_leader_is_traced_to(self):
        """A different size word stands nearer the leader's far end (29pt) than the label (153pt): the
        nearest-word rule gave the post the decoy."""
        got = _sizes(_post_with_leader(_label(512, 404.5, "(2)", "6SW16"), decoys=[("6J18", 680, 430, "ltr")]))
        self.assertEqual(got, ["(2) 6SW16"])

    def test_the_element_says_it_came_by_leader(self):
        pg = _post_with_leader(_label(512, 404.5, "(2)", "6SW16"))
        post = [e for e in T.read_elements(pg)["elements"] if e["element"] == "post"][0]
        self.assertEqual(post["attrs"]["size_from"], "leader")

    def test_a_size_word_near_a_post_with_no_leader_is_nobodys_size(self):
        pg = _Page(_grid() + _post(700, 400), [("(2)", 660, 404, "ltr"), ("6J18", 688, 404, "ltr")])
        self.assertEqual(_sizes(pg), [None])

    def test_a_leader_with_no_arrowhead_binds_nothing(self):
        dr = _grid() + _post(700, 400) + [_leader(556, 693, 404.5)]
        self.assertEqual(_sizes(_Page(dr, _label(512, 404.5, "(2)", "6SW16"))), [None])

    def test_a_leader_that_stops_at_the_post_without_an_arrowhead_binds_nothing(self):
        dr = _grid() + _post(700, 400) + [_leader(556, 699, 404.5)]
        self.assertEqual(_sizes(_Page(dr, _label(512, 404.5, "(2)", "6SW16"))), [None])

    def test_an_apex_between_two_posts_binds_neither(self):
        dr = _grid() + _post(700, 400) + _post(700, 411) + [_leader(556, 693, 410.0), _arrow(700.5, 410.0, -7)]
        self.assertEqual(_sizes(_Page(dr, _label(512, 410.0, "(2)", "6SW16"))), [None, None])

    def test_an_arrowhead_on_no_post_binds_nothing(self):
        dr = _grid() + _post(700, 400) + [_leader(556, 600, 404.5), _arrow(607, 404.5, -7)]
        self.assertEqual(_sizes(_Page(dr, _label(512, 404.5, "(2)", "6SW16"))), [None])

    def test_two_different_labels_on_one_post_bind_nothing(self):
        dr = _grid() + _post(700, 400) + [_leader(556, 693, 404.5), _arrow(700.5, 404.5, -7)]
        # a second label, a second leader whose arrowhead lands on the same post from below
        dr += [_d([("l", (704.5, 440), (704.5, 416.5))], TEXT),
               _d([("l", (704.5, 409.5), (701.5, 416.5)), ("l", (701.5, 416.5), (707.5, 416.5)),
                   ("l", (707.5, 416.5), (704.5, 409.5))], TEXT)]
        words = _label(512, 404.5, "(2)", "6SW16") + _label(680, 450, "(2)", "6J18")
        self.assertEqual(_sizes(_Page(dr, words)), [None])

    def test_a_fan_out_leader_sizes_every_post_it_lands_on(self):
        dr = _grid() + _post(700, 400) + _post(700, 480)
        dr += [_leader(556, 650, 404.5), _arrow(700.5, 404.5, -7), _leader(650, 693, 404.5)]
        dr += [_d([("l", (650, 404.5), (650, 484.5))], TEXT), _leader(650, 693, 484.5), _arrow(700.5, 484.5, -7)]
        self.assertEqual(_sizes(_Page(dr, _label(512, 404.5, "(2)", "6SW16"))), ["(2) 6SW16", "(2) 6SW16"])


def _wall(tag, x0, y0, x1, y1, sched, label_xy=None):
    return {"element": "shear_wall", "tag": tag, "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "attrs": {"schedule": sched}, "evidence": {"label_xy": label_xy} if label_xy else {}}


def _p(x0, y0):
    return {"element": "post", "polygon": [[x0, y0], [x0 + 9, y0], [x0 + 9, y0 + 9], [x0, y0 + 9]],
            "attrs": {"size": None}}


EM = {"END MEMBERS": "(2) 6J14", "STUDS": '6J12 @ 16" O.C.'}


class AScheduleSizeGoesToAnEndPostOnly(unittest.TestCase):

    def test_an_end_post_takes_the_end_members(self):
        els = [_wall("SW 1", 0, 0, 9, 177, EM), _p(0, 0), _p(0, 168)]
        T.size_posts_from_schedule(els)
        self.assertEqual([e["attrs"]["size"] for e in els[1:]], ["(2) 6J14", "(2) 6J14"])
        self.assertEqual(els[1]["attrs"]["size_from"], "shear wall schedule, SW 1 end members")

    def test_a_post_in_the_middle_of_the_frame_is_unknown(self):
        els = [_wall("SW 3", 0, 0, 9, 177, EM), _p(0, 84)]
        T.size_posts_from_schedule(els)
        self.assertIsNone(els[1]["attrs"]["size"])
        self.assertIsNone(els[1]["attrs"].get("size_from"))

    def test_a_dash_in_the_schedule_is_no_designation(self):
        els = [_wall("SW 1", 0, 0, 9, 177, {"END MEMBERS": "-"}), _p(0, 0)]
        T.size_posts_from_schedule(els)
        self.assertIsNone(els[1]["attrs"]["size"])

    def test_two_end_member_cells_are_ambiguous(self):
        els = [_wall("SW 1", 0, 0, 9, 177, {"END MEMBERS": "(2) 6J14", "END MEMBER": "(3) 6J10"}), _p(0, 0)]
        T.size_posts_from_schedule(els)
        self.assertIsNone(els[1]["attrs"]["size"])

    def test_a_post_at_the_ends_of_two_frames_is_ambiguous(self):
        els = [_wall("SW 1", 0, 0, 9, 90, EM), _wall("SW 2", 0, 0, 90, 9, EM), _p(0, 0)]   # a corner of two frames
        T.size_posts_from_schedule(els)
        self.assertIsNone(els[2]["attrs"]["size"])
        els = [_wall("SW 1", 0, 0, 9, 90, EM), _p(0, 0)]
        T.size_posts_from_schedule(els)
        self.assertEqual(els[1]["attrs"]["size"], "(2) 6J14")

    def test_a_tag_as_near_a_second_frame_names_nothing(self):
        els = [_wall("SW 1", 0, 0, 9, 177, EM, label_xy=(15, 90)), _wall("SW 2", 40, 0, 49, 177, EM), _p(0, 0)]
        T.size_posts_from_schedule(els)                       # 6pt vs 25pt: its own frame, margin 19
        self.assertEqual(els[2]["attrs"]["size"], "(2) 6J14")
        els = [_wall("SW 1", 0, 0, 9, 177, EM, label_xy=(20, 90)), _wall("SW 2", 22, 0, 31, 177, EM), _p(0, 0)]
        T.size_posts_from_schedule(els)                       # 11pt vs 2pt: the tag could be either
        self.assertIsNone(els[2]["attrs"]["size"])

    def test_a_leader_size_is_never_replaced_by_the_schedule(self):
        els = [_wall("SW 1", 0, 0, 9, 177, EM), _p(0, 0)]
        els[1]["attrs"].update(size="(2) 6J16", size_from="leader")
        T.size_posts_from_schedule(els)
        self.assertEqual(els[1]["attrs"]["size"], "(2) 6J16")


# ── the Boyland set ───────────────────────────────────────────────────────

ST = "ST - 7.29.26.pdf"
LV = {5: "FLOOR_1", 6: "FLOOR_2", 7: "FLOOR_3", 8: "FLOOR_4", 9: "MEZZANINE", 10: "ROOF"}
#: (page, post x0, y0): the 12 posts the schedule sized without being verified end posts
NOT_END = [(5, 1209.7, 543.8), (6, 1279.3, 543.8), (7, 1279.3, 543.8), (8, 1279.3, 543.8), (9, 1279.3, 543.8),
           (10, 1279.3, 369.0), (10, 1279.3, 641.4), (10, 1279.3, 507.4),
           (10, 1024.3, 366.7), (10, 1024.3, 507.4), (10, 1633.3, 423.7), (10, 1633.3, 591.0)]
_CACHE = {}


def _read_set():
    if "els" in _CACHE:
        return _CACHE["els"]
    from lib.plan_page import PlanPage
    path = str(require_pdf(ST))
    pg = PlanPage(path, 11)
    try:
        sched = T.read_shear_wall_schedule(pg)["rows"]
    finally:
        pg.close()
    out = {}
    for n in range(5, 11):
        pg = PlanPage(path, n)
        try:
            els = T.read_elements(pg)["elements"]
        finally:
            pg.close()
        for e in els:
            if e["element"] == "shear_wall":
                e["attrs"]["schedule"] = sched.get((LV[n], e["tag"]))
        T.size_posts_from_schedule(els)
        out[n] = els
    _CACHE["els"] = out
    return out


def _post_at(els, x, y):
    return next(e for e in els if e["element"] == "post"
                and abs(e["polygon"][0][0] - x) < 0.2 and abs(e["polygon"][0][1] - y) < 0.2)


class OnTheBoylandSet(unittest.TestCase):

    def test_the_s102_post_is_6sw16_by_its_leader(self):
        """S-102 (ST p6): the post at S (1126.6, 543.8) is the first of the (2) 6SW16 leader's posts; the
        nearest-word rule gave it the next callout's "(2) 6J18"."""
        p = _post_at(_read_set()[6], 1126.6, 543.8)
        self.assertEqual(p["attrs"]["size"], "(2) 6SW16")
        self.assertEqual(p["attrs"]["size_from"], "leader")

    def test_119_posts_are_sized_by_leader(self):
        n = sum(1 for els in _read_set().values() for e in els
                if e["element"] == "post" and e["attrs"].get("size_from") == "leader")
        self.assertEqual(n, 119)

    def test_the_twelve_posts_that_are_not_verified_end_posts_are_unknown(self):
        els = _read_set()
        for pg, x, y in NOT_END:
            a = _post_at(els[pg], x, y)["attrs"]
            self.assertIsNone(a["size"], (pg, x, y, a))
            self.assertIsNone(a["size_from"], (pg, x, y, a))

    def test_72_end_posts_keep_the_schedule_size(self):
        n = sum(1 for els in _read_set().values() for e in els
                if e["element"] == "post" and str(e["attrs"].get("size_from") or "").startswith("shear wall schedule"))
        self.assertEqual(n, 72)


if __name__ == "__main__":
    unittest.main()
