"""A DOOR DRAWN ON A LAYER NAMED TO REMOVE IS A SET-HEALTH FLAG.

Queue item 25. Operator (Roy), 2026-10-28: "25 yes, follow-up" - to "In the
owner's set, the added doors and window are drawn on a layer named 'TO
REMOVE'. Should that be flagged as a set-health problem?"

MEASURED (bv-worktrees/Q25, every sheet of both tracks): the only removal-
named layer on any architectural plan is `XR FLOOR PLANS|TO REMOVE`, on the
owner's A-100.00, A-101.00, A-102.00 and A-104.00. Offered beside A-Door /
A-Glaz, its ink is the drawn opening of exactly three tags - 1A's post-CO
bedroom door F, closet G and lower W1 on A-100.00. On A-101/A-102 it is a
bedroom partition no tag reaches (F's own door is nearer); the mezzanine's
draws doors with no tag at all.

Rules under test:
  - a tag whose nearest drawn object, removal ink included, is the removal
    layer's is named in one item per (sheet, track, layer);
  - removal ink NEAR a tag whose own opening is nearer is not a flag, and
    removal ink no tag reaches is not one either;
  - the item names the sheet, the set, the layer and the tags;
  - A FLAG, NOT A BINDING: the rows are byte-identical with or without the
    layer, and the count gate reads the same with or without the item.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_emit as E  # noqa: E402
from lib import plan_openings as P  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_set_health as H  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

KIND = "drawn_on_removal_layer"
INT, WIN = "INTERIOR DOOR SCHEDULE", "WINDOW SCHEDULE"
FAMS = {INT: {"tags": list("ABCDEFG"), "kind": "door", "sheet": "A-400.00"},
        WIN: {"tags": ["W1", "W2", "W3"], "kind": "window", "sheet": "A-400.00"}}
LABEL = "the owner's post-CO set, 6/9/26"
RM = "XR FLOOR PLANS|TO REMOVE"


def _present():
    """On a tree without the flag this is the failure - an assertion, never
    an ImportError."""
    assert hasattr(P, "removal_layer_health") and hasattr(P, "removal_layer_tags"), \
        "lib.plan_openings reads no removal layer in this tree"
    assert getattr(H, "DRAWN_ON_REMOVAL_LAYER", None) == KIND, \
        "lib.plan_set_health has no drawn_on_removal_layer item in this tree"


# ── a synthetic plan, laid out as the owner's A-100.00 ────────────────────

def _path(layer, pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"layer": layer, "items": [("l", pts[i], pts[i + 1]) for i in range(len(pts) - 1)],
            "rect": (min(xs), min(ys), max(xs), max(ys)), "colour": (0, 0, 0)}


def _box(layer, x0, y0, x1, y1):
    return _path(layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


class _Page:
    def __init__(self, drawings, words):
        self.drawings, self.words = drawings, words

    def close(self):
        pass


def _tag(text, x, y, layer="XR FLOOR PLANS|A-DOOR-IDEN"):
    return _box(layer, x - 6, y - 6, x + 6, y + 6), (text, x, y)


def _plan(removal=RM):
    """1A: E owns its bath door; F, G and the lower W1 are drawn only on
    `removal`; the upper W1 owns its glazing, with a removal partition 40 pt
    past it; and a removal cluster no tag reaches (the mezzanine's)."""
    tags = [_tag("E", 200, 100), _tag("F", 100, 100), _tag("G", 100, 300),
            _tag("W1", 400, 100, "XR FLOOR PLANS|A-WINDOW-IDEN"),
            _tag("W1", 400, 300, "XR FLOOR PLANS|A-WINDOW-IDEN")]
    drawings = [d for d, _w in tags]
    drawings += [_box("XR FLOOR PLANS|A-Door", 190, 115, 215, 135),     # E's door
                 _box("XR FLOOR PLANS|A-Glaz", 390, 112, 410, 118),     # upper W1's window
                 _box(removal, 90, 115, 115, 135),                      # F's door
                 _box(removal, 90, 315, 115, 335),                      # G's closet
                 _box(removal, 390, 312, 410, 318),                     # lower W1's window
                 _box(removal, 370, 140, 430, 150),                     # a partition
                 _box(removal, 800, 800, 830, 830)]                     # no tag reaches it
    return _Page(drawings, [w for _d, w in tags])


def _arch(track="post_co"):
    return {"project_id": "p1", "company_id": "c1", "file_id": f"f-{track}", "file_hash": "h",
            "file_name": "Owners set - 6.9.26.pdf", "page_id": f"pg-a100-{track}",
            "page_number": 1, "sheet_number": "A-100.00", "sheet_title": "FIRST FLOOR PLAN",
            "discipline": "architectural", "drawing_track": track,
            "drawing_track_label": LABEL if track == "post_co" else None}


def _run(page, track="post_co"):
    floors = [{"arch_p": _arch(track), "a_sheet": "A-100.00",
               "units": {"tags": None, "why": "test: sheet scope"}, "space": None}]
    return P.run_openings(floors, lambda _p: page, FAMS, track=track)


class _Units:
    """A membership map that puts everything in 1A."""

    def unit_of_normal(self, x, y):
        return "1A", "inside"


def _flags(health):
    return [h for h in health if h.get("kind") == KIND]


def _one(items):
    """The single flag - an assertion, never an IndexError, when it is absent."""
    assert len(items) == 1, f"expected one removal-layer flag, got {len(items)}: {items}"
    return items[0]


# ══════════════════════════════════════════════════════════════════════════

class TheRemovalLayerIsRead(unittest.TestCase):

    def test_the_tags_drawn_only_on_to_remove_are_named(self):
        _present()
        got = P.removal_layer_tags(_plan(), FAMS)
        self.assertEqual(sorted((h["text"], h["at"]) for h in got),
                         [("F", (100, 100)), ("G", (100, 300)), ("W1", (400, 300))])
        self.assertEqual({h["layer"] for h in got}, {RM})

    def test_removal_ink_beside_a_tag_whose_own_opening_is_nearer_is_no_flag(self):
        """A-101/A-102: the removal partition is in reach of a tag that
        owns its own opening. The upper W1 and E are never named."""
        _present()
        named = {(h["text"], h["at"]) for h in P.removal_layer_tags(_plan(), FAMS)}
        self.assertNotIn(("W1", (400, 100)), named)
        self.assertNotIn(("E", (200, 100)), named)

    def test_removal_ink_no_tag_reaches_is_no_flag(self):
        """The mezzanine's: ink on TO REMOVE, no tag - nothing to name."""
        _present()
        page = _Page([_box(RM, 800, 800, 830, 830), _box(RM, 90, 115, 115, 135)], [])
        self.assertEqual(P.removal_layer_health(page, "A-104.00", FAMS, track="post_co"), [])

    def test_a_layer_not_named_for_removal_is_no_flag(self):
        _present()
        for other in ("XR FLOOR PLANS|A-WALL", "XR FLOOR PLANS|TO REMOVE NOTES",
                      "XR FLOOR PLANS|A-HATCH-NEW"):
            self.assertEqual(P.removal_layer_tags(_plan(other), FAMS), [], other)

    def test_the_layer_is_matched_whatever_the_xref_prefix_or_case(self):
        _present()
        for name in ("TO REMOVE", "XR FLOOR PLANS|TO REMOVE", "x|to remove"):
            self.assertEqual(len(P.removal_layer_tags(_plan(name), FAMS)), 3, name)


class TheItemNamesSheetSetLayerAndTags(unittest.TestCase):

    def test_the_owners_a100_text(self):
        _present()
        recs = {WIN: [{"tag": "W1", "unit": "1A", "label_at": (400, 100)}]}
        got = P.removal_layer_health(_plan(), "A-100.00", FAMS, track="post_co", label=LABEL,
                                     units=_Units(), records=recs)
        self.assertEqual(len(got), 1)
        it = got[0]
        self.assertEqual(it["detail"],
                         "A-100.00 (the owner's post-CO set, 6/9/26): 1A's F, G and a W1 are "
                         "drawn on layer TO REMOVE; their symbols are not on the door/window layers")
        self.assertEqual((it["kind"], it["sheet"], it["subject"], it["track"], it["layer"]),
                         (KIND, "A-100.00", "TO REMOVE", "post_co", RM))
        self.assertEqual([(t["tag"], t["unit"]) for t in it["tags"]],
                         [("F", "1A"), ("G", "1A"), ("W1", "1A")])

    def test_with_no_membership_map_the_tags_are_named_without_a_unit(self):
        _present()
        got = P.removal_layer_health(_plan(), "A-100.00", FAMS, track="post_co", label=LABEL)
        self.assertEqual(_one(got)["detail"],
                         "A-100.00 (the owner's post-CO set, 6/9/26): tags F, G and W1 are drawn "
                         "on layer TO REMOVE; their symbols are not on the door/window layers")

    def test_the_track_is_the_pass_track_and_the_sheet_the_plan(self):
        _present()
        for track in ("filed", "post_co"):
            items = _flags(_run(_plan(), track)["health"])
            self.assertEqual([(i["sheet"], i["track"]) for i in items], [("A-100.00", track)])
            want = LABEL if track == "post_co" else "filed set"
            self.assertTrue(items[0]["detail"].startswith(f"A-100.00 ({want}): "), items[0]["detail"])

    def test_one_tag_reads_singular(self):
        _present()
        page = _Page([_tag("F", 100, 100)[0], _box(RM, 90, 115, 115, 135)], [("F", 100, 100)])
        got = P.removal_layer_health(page, "A-100.00", FAMS, track="post_co", label=LABEL)
        self.assertEqual(_one(got)["detail"],
                         "A-100.00 (the owner's post-CO set, 6/9/26): tag F is drawn on layer "
                         "TO REMOVE; its symbol is not on the door/window layers")


class AFlagNotABinding(unittest.TestCase):

    def test_run_openings_rows_are_identical_with_or_without_the_layer(self):
        """The same plan with the layer renamed to one no reading uses: every
        row byte for byte, and the health differs by the flag alone."""
        _present()
        a, b = _run(_plan()), _run(_plan("XR FLOOR PLANS|A-WALL-PATT"))
        dump = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
        self.assertEqual(dump(a["rows"]), dump(b["rows"]))
        self.assertEqual(dump(a["summary"]), dump(b["summary"]))
        self.assertEqual(_flags(b["health"]), [])
        self.assertEqual(len(_flags(a["health"])), 1)
        self.assertEqual(dump([h for h in a["health"] if h.get("kind") != KIND]), dump(b["health"]))

    def test_the_tags_on_the_removal_layer_are_still_contested_or_unread(self):
        """The pass's reading of F, G and the lower W1 is unchanged: F took
        E's door, G and the lower W1 have no door/window symbol in reach."""
        _present()
        got = P.floor_records(_plan(), FAMS, None, "refused: test")
        by = {(r["label_text"], r["label_at"]): r for rs in got["records"].values() for r in rs}
        self.assertIn("E's", by[("F", (100, 100))]["reason"])
        self.assertEqual(by[("G", (100, 300))]["glyph_status"], "unread")
        self.assertEqual(by[("W1", (400, 300))]["glyph_status"], "unread")
        self.assertNotIn("nearest door/window symbol",
                         by[("W1", (400, 100))]["reason"] or "")   # it owns its window

    def test_the_gate_reads_the_same_with_or_without_the_item(self):
        """A floor the gate CAN bind (E owns its door, F is contested and
        counts on its floor, W1 owns its window): every claim binds or
        refuses as it did, the item beside the rows."""
        _present()
        tags = [_tag("E", 200, 100), _tag("F", 100, 100),
                _tag("W1", 400, 100, "XR FLOOR PLANS|A-WINDOW-IDEN")]
        page = _Page([d for d, _w in tags] + [_box("XR FLOOR PLANS|A-Door", 190, 115, 215, 135),
                                              _box("XR FLOOR PLANS|A-Glaz", 390, 112, 410, 118),
                                              _box(RM, 90, 115, 115, 135)],
                     [w for _d, w in tags])
        out = _run(page)
        items = [dict(h, record_type="set_health") for h in _flags(out["health"])]
        self.assertEqual([t["tag"] for t in _one(items)["tags"]], ["F"])
        rows = out["rows"]
        for i, r in enumerate(rows):
            r["ordinal"] = i
        pages = sorted({r["page_id"] for r in rows})
        cens = []
        for name in (INT, WIN):
            c = S.glyph_census("family", "p1", pages, 0, family=name, tags=FAMS[name]["tags"],
                               track="post_co", scope=S.OPENING)
            c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
            cens.append(c)
        c = S.glyph_census("refusals", "p1", pages, 0, track="post_co", scope=S.OPENING)
        c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
        recs = rows + cens + [c]
        bound = 0
        for claim in ("There is 1 type E door.", "There is 1 type F door.",
                      "There is 1 type F door per the owner's set.", "There are 2 interior doors.",
                      "There is 1 W1.", "There are 2 W1.", "There are 2 type F doors."):
            without = S.answer_is_grounded(claim, recs, intent="count")
            self.assertEqual(without, S.answer_is_grounded(claim, recs + items, intent="count"),
                             claim)
            bound += bool(without[0])
        self.assertEqual(bound, 5, "the world binds what it should, or the test proves nothing")

    def test_the_model_is_shown_it(self):
        _present()
        item = dict(_one(P.removal_layer_health(_plan(), "A-100.00", FAMS, track="post_co",
                                                label=LABEL)), record_type="set_health")
        self.assertIn(item["detail"], S.render_set_health([item]))

    def test_it_is_queued_for_review_as_a_set_health_problem(self):
        _present()
        from datetime import datetime, timezone
        from lib import review_queue as Q
        item = _one(P.removal_layer_health(_plan(), "A-100.00", FAMS, track="post_co",
                                           label=LABEL))
        q = Q.from_set_health("c1", "p1", item, now=datetime.now(timezone.utc))
        self.assertIsNotNone(q)
        self.assertEqual(q["reason"], Q.REASON_SET_HEALTH_FAILED)


# ── the drawings themselves ────────────────────────────────────────────────

def _page(name, number):
    from lib.plan_page import PlanPage
    return PlanPage(str(require_pdf(name)), number)


class OnTheBoylandSet(unittest.TestCase):

    def test_owners_a100_names_f_g_and_the_lower_w1(self):
        _present()
        got = P.removal_layer_health(_page("Owners set - 6.9.26.pdf", 1), "A-100.00", FAMS,
                                     track="post_co", label=LABEL)
        self.assertEqual(len(got), 1)
        self.assertEqual([(t["tag"], t["at"]) for t in got[0]["tags"]],
                         [("F", [988.0, 641.3]), ("G", [979.0, 752.3]), ("W1", [739.0, 714.8])])
        self.assertEqual(got[0]["layer"], RM)

    def test_no_other_plan_of_either_track_is_flagged(self):
        _present()
        for name, number in (("Owners set - 6.9.26.pdf", 2), ("Owners set - 6.9.26.pdf", 3),
                             ("Owners set - 6.9.26.pdf", 4), ("Owners set - 6.9.26.pdf", 5),
                             ("Owners set - 6.9.26.pdf", 6), ("AR - 8.18.26.pdf", 6),
                             ("AR - 8.18.26.pdf", 7), ("AR - 3.28.25.pdf", 12),
                             ("AR - 3.28.25.pdf", 13), ("AR - 3.28.25.pdf", 14),
                             ("AR - 3.28.25.pdf", 15)):
            self.assertEqual(P.removal_layer_tags(_page(name, number), FAMS), [], (name, number))


if __name__ == "__main__":
    unittest.main()
