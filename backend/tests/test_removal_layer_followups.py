"""REMOVAL-LAYER FOLLOW-UPS: rulings 37, 38, 39 and 40 (Roy, 2026-10-28).

  37 yes  a SHEET-level set-health item for removal-layer ink that carries
          no tag (the owner's mezzanine: 80 objects on TO REMOVE);
  38 yes  the CAD status suffix -DEMO (A-WALL-DEMO) is a removal layer too;
          an EXISTING layer (-EXST, EXISTING) never is;
  39 yes  the plans under an open set question are checked as well (the
          A.1.x plans of "588 THOMAS BOYLAND ST SET_UPDATED .pdf", the
          gas-change Roof Plan);
  40 no   the flag never refuses an answer.

MEASURED (bv-worktrees/TR2/_lane, all 165 pages of the 12 local fixture
PDFs): the new predicate matches `XR FLOOR PLANS|TO REMOVE` (owner's A-100.00,
A-101.00, A-102.00, A-104.00), `A-DEMO` and `...|A-DEMO` (plumbing legends),
`...$A-STEP-DEMO` (a site-safety section) - and not `...|P-Pipe-Existing`.
On the owner's plans the ink no tag names is 13 paths on A-100.00 (beside F,
G and the lower W1's 13), 12 on A-101.00 and A-102.00, 80 on A-104.00. The
A.1.x plans carry 25-33 CAD layers each and no removal layer.

ONE PREDICATE. lib.plan_space_layers.is_removal_layer decides for every
reading; plan_openings imports it rather than keeping a pattern of its own.
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

from lib import plan_openings as P  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_set_health as H  # noqa: E402
from lib import plan_set_questions as Q  # noqa: E402
from lib import plan_space_layers as SL  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

TAGS, INK = "drawn_on_removal_layer", "removal_layer_ink"
INT, WIN = "INTERIOR DOOR SCHEDULE", "WINDOW SCHEDULE"
FAMS = {INT: {"tags": list("ABCDEFG"), "kind": "door", "sheet": "A-400.00"},
        WIN: {"tags": ["W1", "W2", "W3"], "kind": "window", "sheet": "A-400.00"}}
LABEL = "the owner's post-CO set, 6/9/26"
RM = "XR FLOOR PLANS|TO REMOVE"


def _present():
    """On a tree without the follow-ups this is the failure - an assertion,
    never an ImportError or AttributeError."""
    assert callable(getattr(SL, "is_removal_layer", None)), \
        "lib.plan_space_layers has no shared removal-layer predicate in this tree"
    assert getattr(H, "REMOVAL_LAYER_INK", None) == INK, \
        "lib.plan_set_health has no removal_layer_ink item in this tree"
    assert callable(getattr(P, "removal_layer_items", None)), \
        "lib.plan_openings writes no sheet-level removal item in this tree"


# ── synthetic plans (the shapes of test_a_door_drawn_to_be_removed_is_flagged) ──

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
    """F, G and the lower W1 drawn only on `removal`; E and the upper W1 own
    theirs; a partition on `removal` and a cluster no tag reaches."""
    tags = [_tag("E", 200, 100), _tag("F", 100, 100), _tag("G", 100, 300),
            _tag("W1", 400, 100, "XR FLOOR PLANS|A-WINDOW-IDEN"),
            _tag("W1", 400, 300, "XR FLOOR PLANS|A-WINDOW-IDEN")]
    drawings = [d for d, _w in tags]
    drawings += [_box("XR FLOOR PLANS|A-Door", 190, 115, 215, 135),
                 _box("XR FLOOR PLANS|A-Glaz", 390, 112, 410, 118),
                 _box(removal, 90, 115, 115, 135),         # F's door
                 _box(removal, 90, 315, 115, 335),         # G's closet
                 _box(removal, 390, 312, 410, 318),        # lower W1's window
                 _box(removal, 370, 140, 430, 150),        # a partition
                 _box(removal, 800, 800, 830, 830)]        # no tag reaches it
    return _Page(drawings, [w for _d, w in tags])


def _mezzanine(removal=RM):
    """The owner's A-104.00: removal ink, no tag anywhere."""
    return _Page([_box(removal, 800, 800, 830, 830), _box(removal, 900, 800, 930, 830)], [])


def _arch(sheet, track="post_co", page_number=1, file_name="Owners set - 6.9.26.pdf",
          title="FIRST FLOOR PLAN"):
    return {"project_id": "p1", "company_id": "c1", "file_id": f"f-{file_name}",
            "file_hash": f"h-{file_name}", "file_name": file_name,
            "page_id": f"pg-{sheet}-{track}", "page_number": page_number,
            "sheet_number": sheet, "sheet_title": title, "discipline": "architectural",
            "drawing_track": track,
            "drawing_track_label": LABEL if track == "post_co" else None}


def _run_floor(page, sheet="A-104.00", track="post_co"):
    floors = [{"arch_p": _arch(sheet, track), "a_sheet": sheet,
               "units": {"tags": None, "why": "test: sheet scope"}, "space": None}]
    return P.run_openings(floors, lambda _p: page, FAMS, track=track)


SET_FILE = "588 THOMAS BOYLAND ST SET_UPDATED .pdf"


def _run_question(page, answer=None):
    """A.1.1 and A.1.3 of the second architect's file: refused plans whose
    numbers are not in the plan series - one open set question on the filed
    track. `page` is A.1.3; A.1.1 draws nothing."""
    a11 = _arch("A.1.1", "filed", 11, SET_FILE, "FLOOR PLAN")
    a13 = _arch("A.1.3", "filed", 13, SET_FILE, "FLOOR PLAN")
    refused = [(a11, "not in the plan series"), (a13, "not in the plan series")]
    qid = Q.detect("p1", "filed", refused)[0]["id"]
    answers = {qid: answer} if answer else None
    pages = {"A.1.1": _Page([], []), "A.1.3": page}
    return P.run_openings([], lambda p: pages[p["sheet_number"]], FAMS, track="filed",
                          refused=refused, answers=answers), qid


def _kind(health, kind):
    return [h for h in health if h.get("kind") == kind]


def _one(items):
    assert len(items) == 1, f"expected one item, got {len(items)}: {items}"
    return items[0]


# ══ 38: the -DEMO suffix is a removal layer; an EXISTING layer never is ═════

class Ruling38TheMatcher(unittest.TestCase):

    REMOVAL = ("TO REMOVE", "XR FLOOR PLANS|TO REMOVE", "x|to remove", "A-WALL-DEMO",
               "XR FLOOR PLANS|A-WALL-DEMO", "A-DOOR-DEMO", "A-GLAZ-DEMO", "a-wall-demo",
               "A-DEMO", "X-(24X36)-(P-200) Sanitary & Storm Notes|A-DEMO",
               "PDF86_Xr-Section$0$A-STEP-DEMO")
    EXISTING = ("A-WALL-EXST", "XR FLOOR PLANS|A-WALL-EXST", "A-DOOR-EXST", "EXISTING",
                "A-WALL-EXISTING", "XR|EXISTING WALLS",
                "X-(24X36)-(P-100) Domestic Water & Gas Notes|P-Pipe-Existing")
    NEITHER = ("A-WALL", "XR FLOOR PLANS|A-Door", "TO REMOVE NOTES", "A-HATCH-NEW",
               "A-DEMOLITION NOTES", "")

    def test_to_remove_and_the_demo_suffix_match(self):
        _present()
        for name in self.REMOVAL:
            self.assertTrue(SL.is_removal_layer(name), name)

    def test_no_existing_layer_matches(self):
        _present()
        for name in self.EXISTING + self.NEITHER:
            self.assertFalse(SL.is_removal_layer(name), name)

    def test_the_openings_pass_reads_a_demo_layer_as_removal_ink(self):
        _present()
        for name in ("XR FLOOR PLANS|A-WALL-DEMO", "A-DEMO"):
            got = P.removal_layer_tags(_plan(name), FAMS)
            self.assertEqual(sorted(h["text"] for h in got), ["F", "G", "W1"], name)
        for name in ("XR FLOOR PLANS|A-WALL-EXST", "X|P-Pipe-Existing"):
            self.assertEqual(P.removal_layer_tags(_plan(name), FAMS), [], name)
            self.assertEqual(_kind(_run_floor(_plan(name), "A-100.00")["health"], INK), [], name)

    def test_a_door_demo_layer_is_removal_ink_not_the_tags_own_door(self):
        """A-DOOR-DEMO is a door layer by name: offered as a symbol it would be
        the opening's own door and never flagged."""
        _present()
        got = P.removal_layer_tags(_plan("XR FLOOR PLANS|A-DOOR-DEMO"), FAMS)
        self.assertEqual(sorted(h["text"] for h in got), ["F", "G", "W1"])

    def test_one_predicate_every_reading_shares(self):
        _present()
        self.assertIs(P.is_removal_layer, SL.is_removal_layer)
        self.assertIs(P.REMOVAL_LAYER, SL.REMOVAL_LAYER)


# ══ 37: removal ink no tag names is a sheet-level item ══════════════════════

class Ruling37TheSheetItem(unittest.TestCase):

    def test_the_mezzanine_text(self):
        _present()
        got = P.removal_layer_items(_mezzanine(), "A-104.00", FAMS, track="post_co",
                                    label=LABEL)
        it = _one(got)
        self.assertEqual(it["detail"],
                         "A-104.00 (the owner's post-CO set, 6/9/26): 2 objects are drawn on "
                         "layer TO REMOVE and no door or window tag names them")
        self.assertEqual((it["kind"], it["sheet"], it["subject"], it["track"], it["layer"],
                          it["objects"], it["tagged_objects"]),
                         (INK, "A-104.00", "TO REMOVE", "post_co", RM, 2, 0))
        self.assertEqual(it["box"], [800.0, 800.0, 930.0, 830.0])

    def test_beside_tagged_openings_it_counts_the_rest(self):
        """A-100.00: F, G and the lower W1 are the tag item's; the partition
        and the far cluster are the sheet item's."""
        _present()
        got = P.removal_layer_items(_plan(), "A-100.00", FAMS, track="post_co", label=LABEL)
        self.assertEqual([i["kind"] for i in got], [TAGS, INK])
        ink = got[1]
        self.assertEqual(ink["detail"],
                         "A-100.00 (the owner's post-CO set, 6/9/26): 2 more objects are drawn "
                         "on layer TO REMOVE and no door or window tag names them")
        self.assertEqual((ink["objects"], ink["tagged_objects"]), (2, 3))
        # the server's dedupe (kind, sheet, subject, track) keeps both
        self.assertEqual(H.dedupe(got), got)

    def test_one_object_reads_singular(self):
        _present()
        page = _Page([_box(RM, 800, 800, 830, 830)], [])
        it = _one(P.removal_layer_items(page, "A-104.00", FAMS, track="post_co", label=LABEL))
        self.assertEqual(it["detail"],
                         "A-104.00 (the owner's post-CO set, 6/9/26): 1 object is drawn on "
                         "layer TO REMOVE and no door or window tag names it")

    def test_every_removal_object_a_tag_names_is_no_sheet_item(self):
        _present()
        page = _Page([_tag("F", 100, 100)[0], _box(RM, 90, 115, 115, 135)], [("F", 100, 100)])
        got = P.removal_layer_items(page, "A-100.00", FAMS, track="post_co", label=LABEL)
        self.assertEqual([i["kind"] for i in got], [TAGS])

    def test_run_openings_writes_it_for_the_floor(self):
        _present()
        for track, want in (("post_co", LABEL), ("filed", "filed set")):
            it = _one(_kind(_run_floor(_mezzanine(), track=track)["health"], INK))
            self.assertEqual((it["sheet"], it["track"]), ("A-104.00", track))
            self.assertTrue(it["detail"].startswith(f"A-104.00 ({want}): 2 objects"), it["detail"])

    def test_the_rows_are_what_they_were(self):
        _present()
        a, b = _run_floor(_plan(), "A-100.00"), _run_floor(_plan("XR FLOOR PLANS|A-HATCH"),
                                                           "A-100.00")
        dump = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
        self.assertEqual(dump(a["rows"]), dump(b["rows"]))
        self.assertEqual(dump(a["summary"]), dump(b["summary"]))
        self.assertEqual(len(_kind(a["health"], INK)), 1)
        self.assertEqual(_kind(b["health"], INK), [])

    def test_it_is_queued_at_normal_priority_apart_from_the_tag_item(self):
        """Ruling 41: normal priority. Its review key is not the tag item's
        on the same sheet and layer."""
        _present()
        from datetime import datetime, timezone
        from lib import review_queue as RQ
        now = datetime.now(timezone.utc)
        got = P.removal_layer_items(_plan(), "A-100.00", FAMS, track="post_co", label=LABEL)
        tag, ink = _one(_kind(got, TAGS)), _one(_kind(got, INK))
        qi, qt = RQ.from_set_health("c1", "p1", ink, now=now), \
            RQ.from_set_health("c1", "p1", tag, now=now)
        self.assertEqual(qi["reason"], RQ.REASON_SET_HEALTH_FAILED)
        self.assertEqual(qi["priority"], RQ.PRIORITY_NORMAL)
        self.assertNotEqual(qi["_id"], qt["_id"])

    def test_the_model_is_shown_it(self):
        _present()
        it = dict(_one(P.removal_layer_items(_mezzanine(), "A-104.00", FAMS, track="post_co",
                                             label=LABEL)), record_type="set_health")
        self.assertIn(it["detail"], S.render_set_health([it]))


# ══ 39: the plans under an open set question are checked too ════════════════

class Ruling39SetQuestionPlans(unittest.TestCase):

    def test_an_open_question_plan_is_checked_and_marked(self):
        _present()
        out, qid = _run_question(_plan())
        tag, ink = _one(_kind(out["health"], TAGS)), _one(_kind(out["health"], INK))
        where = "A.1.3 (filed set; the A.1.x plans, an open set question): "
        self.assertEqual(tag["detail"],
                         where + "tags F, G and W1 are drawn on layer TO REMOVE; their "
                                 "symbols are not on the door/window layers")
        self.assertEqual(ink["detail"],
                         where + "2 more objects are drawn on layer TO REMOVE and no door "
                                 "or window tag names them")
        for it in (tag, ink):
            self.assertEqual((it["sheet"], it["track"], it[Q.ROW_KEY], it[Q.ROW_LABEL]),
                             ("A.1.3", "filed", qid, "the A.1.x plans"))

    def test_an_included_plan_is_checked_as_an_ordinary_plan(self):
        _present()
        out, _qid = _run_question(_mezzanine(), Q.INCLUDE)
        it = _one(_kind(out["health"], INK))
        self.assertEqual(it["detail"], "A.1.3 (filed set): 2 objects are drawn on layer "
                                       "TO REMOVE and no door or window tag names them")
        self.assertNotIn(Q.ROW_KEY, it)

    def test_an_excluded_plan_is_not_read(self):
        _present()
        out, _qid = _run_question(_plan(), Q.EXCLUDE)
        self.assertEqual(_kind(out["health"], TAGS) + _kind(out["health"], INK), [])

    def test_the_question_rows_are_what_they_were(self):
        _present()
        a, _ = _run_question(_plan())
        b, _ = _run_question(_plan("XR FLOOR PLANS|A-HATCH"))
        dump = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
        self.assertEqual(dump(a["rows"]), dump(b["rows"]))
        self.assertEqual(len(_kind(a["health"], TAGS)), 1)


# ══ 40: the flag never refuses an answer ═══════════════════════════════════

class Ruling40NeverRefuses(unittest.TestCase):

    def test_the_gate_reads_the_same_with_or_without_both_items(self):
        _present()
        tags = [_tag("E", 200, 100), _tag("F", 100, 100),
                _tag("W1", 400, 100, "XR FLOOR PLANS|A-WINDOW-IDEN")]
        page = _Page([d for d, _w in tags] + [_box("XR FLOOR PLANS|A-Door", 190, 115, 215, 135),
                                              _box("XR FLOOR PLANS|A-Glaz", 390, 112, 410, 118),
                                              _box(RM, 90, 115, 115, 135),
                                              _box(RM, 800, 800, 830, 830)],
                     [w for _d, w in tags])
        out = _run_floor(page, "A-100.00")
        items = [dict(h, record_type="set_health") for h in out["health"]
                 if h.get("kind") in (TAGS, INK)]
        self.assertEqual(sorted(i["kind"] for i in items), [TAGS, INK])
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


# ── the drawings themselves ────────────────────────────────────────────────

def _page(name, number):
    from lib.plan_page import PlanPage
    return PlanPage(str(require_pdf(name)), number)


OWNERS = "Owners set - 6.9.26.pdf"


class OnTheBoylandSet(unittest.TestCase):

    def test_the_owners_plans(self):
        """Every item the owner's four plans write, exactly."""
        _present()
        want = {
            1: ("A-100.00", [TAGS, INK], "13 more objects are drawn on layer TO REMOVE and no "
                                         "door or window tag names them"),
            2: ("A-101.00", [INK], "12 objects are drawn on layer TO REMOVE and no door or "
                                   "window tag names them"),
            3: ("A-102.00", [INK], "12 objects are drawn on layer TO REMOVE and no door or "
                                   "window tag names them"),
            5: ("A-104.00", [INK], "80 objects are drawn on layer TO REMOVE and no door or "
                                   "window tag names them"),
        }
        for number, (sheet, kinds, text) in want.items():
            got = P.removal_layer_items(_page(OWNERS, number), sheet, FAMS, track="post_co",
                                        label=LABEL)
            self.assertEqual([i["kind"] for i in got], kinds, sheet)
            self.assertEqual(got[-1]["detail"], f"{sheet} ({LABEL}): {text}", sheet)
        for number in (4, 6):
            self.assertEqual(P.removal_layer_items(_page(OWNERS, number), "x", FAMS,
                                                   track="post_co"), [], number)

    def test_the_a1x_plans_carry_no_removal_layer(self):
        """Ruling 39: the A.1.x plans are checked; they draw nothing on one."""
        _present()
        for number in range(11, 18):
            pg = _page("588 THOMAS BOYLAND ST SET_UPDATED.pdf", number)
            self.assertGreater(len({d.get("layer") for d in pg.drawings}), 5, number)
            self.assertEqual(P.removal_layer_items(pg, f"A.1.{number - 10}", FAMS,
                                                   track="filed"), [], number)

    def test_the_filed_plans_write_nothing(self):
        _present()
        for name, number in (("AR - 8.18.26.pdf", 6), ("AR - 8.18.26.pdf", 7),
                             ("AR - 3.28.25.pdf", 12), ("AR - 3.28.25.pdf", 13),
                             ("AR - 3.28.25.pdf", 14), ("AR - 3.28.25.pdf", 15)):
            self.assertEqual(P.removal_layer_items(_page(name, number), "x", FAMS,
                                                   track="filed"), [], (name, number))


if __name__ == "__main__":
    unittest.main()
