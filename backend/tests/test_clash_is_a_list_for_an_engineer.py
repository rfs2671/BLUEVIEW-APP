"""CLASH v1 (lib.plan_clash): plumbing against shear walls and braced frames,
as a list of flags "for engineer review" - never pass/fail, never clear.

Roy (2026-10-29): "(a) pipe segments passing through a shear wall or braced
frame (separately for those in the hold-down zone), (b) stacks/risers inside
or within 2 in of a frame. Benchmark: the 70 segments / 15 in hold-down zones
on P-204 vs SW 1 must be found. Every flag gets an overlay crop; label "flag
for engineer review"."

Sections 1-4 are pure (CI). Section 5 reads the Boyland drawings (fixture
PDFs: skipped, and warned, without them) and is the benchmark, end to end
through lib.plan_structural and lib.plan_stacks.

Each test fails on origin/main by ASSERTION (_present), not by an import
error: the module is imported lazily.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from tests.fixture_pdfs import require as require_pdf  # noqa: E402

try:
    from lib import plan_clash as C  # noqa: E402
except ImportError:                  # origin/main: the tests fail by assertion
    C = None


def _present():
    assert C is not None, "there is no lib.plan_clash: no clash is looked for at all"


def _present_tol():
    """Roy's tolerance rule exists: fails by assertion on a module that predates it."""
    _present()
    assert hasattr(C, "KIND_TOLERANCE") and hasattr(C, "residual_for"), (
        "lib.plan_clash has no tolerance rule: an overlap smaller than the registration residual "
        "still reads as a clash")


NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
A, A2 = "a103", "a102"
S_REF = {"page_id": "s104", "file_id": "f-st", "sheet_number": "S-104.00", "file_name": "ST.pdf", "page_number": 8}
A_REF = {"page_id": A, "file_id": "f-ar", "sheet_number": "A-103.00", "file_name": "AR.pdf", "page_number": 14,
         "sheet_title": "FOURTH FLOOR PLAN"}
# SW 1 as T3 places it on A-103.00: 9 x 177 pt (6 in x 9'-10"), end posts at each end
FRAME = [[1626.78, 702.69], [1635.78, 702.69], [1635.78, 879.69], [1626.78, 879.69]]
TOP = [[1626.96, 702.69], [1635.6, 702.69], [1635.6, 712.47], [1626.96, 712.47]]
BOT = [[1626.96, 869.97], [1635.6, 869.97], [1635.6, 879.69], [1626.96, 879.69]]
PT_IN = 1.5                          # 1/4" = 1'-0": one real inch is 1.5 pt


def srow(element, polygon, *, tag="SW 1", track="filed", a=A, end=None, drawn_as="at_level",
         refused=None, note=None, level="FLOOR_4", s_max=None, s_rms=0.3):
    a_ref = dict(A_REF, page_id=a)
    reg = {"dx": 6.3, "dy": -242.49, "anchors": 209, "margin": 1.916, "usable": True}
    if s_max is not None:           # the S->A registration's own residuals (absent unless asked for)
        reg.update(rms_in=s_rms, max_in=s_max)
    return {"emit_version": 1, "track": track, "level": level, "element": element, "tag": tag,
            "label": f"S-104.00 {tag} ({element.replace('_', ' ')})" if tag else f"S-104.00 {element}",
            "s_sheet": S_REF, "a_sheet": a_ref, "polygon_a": polygon,
            "placement": "placed" if polygon else "refused", "refused": refused,
            "registration": reg,
            "structure_note": note,
            "attrs": {"drawn_as": drawn_as if element != "hold_down" else None, "end": end,
                      "zone_from": "post at the end member" if end else None}}


PAIR_S104_A103 = {"s": "S-104.00", "a": "A-103.00", "level": "FLOOR_4",
                  "s_sheet": {"file_id": "f-st", "page_number": 8, "sheet_number": "S-104.00"},
                  "a_sheet": {"file_id": "f-ar", "page_number": 14, "sheet_number": "A-103.00"},
                  "registration": {"rms_in": 0.356, "max_in": 0.999, "margin": 9.9}}


def structure(track="filed", a=A, note=None, drawn_as="at_level", level="FLOOR_4", s_max=None, s_rms=0.3):
    kw = dict(track=track, a=a, note=note, level=level, s_max=s_max, s_rms=s_rms)
    return [srow("shear_wall", FRAME, drawn_as=drawn_as, **kw),
            srow("hold_down", TOP, end="top", **kw),
            srow("hold_down", BOT, end="bottom", **kw)]


def _preg(p_max, p_rms, margin=3.64):
    reg = {"dx": -25.51, "dy": -66.04, "margin": margin, "usable": True}
    if p_max is not None:
        reg.update(rms_in=p_rms, max_in=p_max)
    return reg


def pipes(segments=(), curves=(), *, track="filed", a=A, sheet="P-204.00", refused=None,
          p_max=None, p_rms=0.08):
    placed = refused is None
    return {"record_type": "pipe_segments", "track": track, "plumbing_sheet": sheet,
            "plumbing_page_id": "p204", "arch_page_id": a,
            "a_sheet": dict(A_REF, page_id=a),
            "segments": [list(s) for s in segments] if placed else None,
            "curves": [[list(map(list, c[0])), c[1]] for c in curves] if placed else None,
            "registration": _preg(p_max, p_rms),
            "placement_refused": refused}


def stack(x, y, r=2.25, tag="V-3", track="filed", a=A, footprint=True, why=None, sheet="P-204.00",
          p_max=None, p_rms=0.08):
    return {"record_type": "stack", "track": track, "plumbing_sheet": sheet,
            "plumbing_page_id": "p204", "tag_id": tag, "a_sheet": dict(A_REF, page_id=a),
            "arch_page_id": a, "status": "located" if footprint else "no_stack",
            "footprint_arch": ({"type": "circle", "x": x, "y": y, "r": r, "frame": "arch_page_pt"}
                               if footprint else None),
            "pipe_systems": ["vent"], "placement_refused": why,
            "registration": {"margin": 3.64, "usable": True, **(
                {"rms_in": p_rms, "max_in": p_max} if p_max is not None else {})}}


def flags(res, kind=None):
    return [f for f in res["flags"] if kind is None or f["kind"] == kind]


def one(seq):
    """The one item - by ASSERTION, so a missing or extra flag is a test
    failure, never an unpacking error."""
    seq = list(seq)
    assert len(seq) == 1, f"expected exactly one, got {len(seq)}: {seq}"
    return seq[0]


# ══════════════════════════════════════════════════════════════════════════
# 1. (a) pipe pieces through a frame, and the hold-down split
# ══════════════════════════════════════════════════════════════════════════

class PipesThroughAFrame(unittest.TestCase):

    def test_a_piece_inside_is_flagged_and_one_beside_is_not(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary"),
                                           (1640.0, 750.0, 1640.0, 790.0, "sanitary")])])
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual([p["index"] for p in f["pieces"]], [0])
        self.assertEqual(f["counts"]["pieces"], 1)

    def test_a_pipe_straight_through_the_wall_is_flagged(self):
        """Both ends outside, the middle inside: a pipe crossing the frame.
        A test of the drawn points alone would miss it."""
        _present()
        res = C.check(structure(), [pipes([(1600.0, 790.0, 1660.0, 790.0, "vent")])])
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual(f["system"], "vent")

    def test_a_curved_piece_is_one_piece(self):
        _present()
        arc = [[1629.0, 760.0], [1630.0, 761.0], [1631.0, 762.0], [1632.0, 763.0]]
        res = C.check(structure(), [pipes(curves=[(arc, "sanitary")])])
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual((f["counts"]["curved"], f["counts"]["straight"]), (1, 0))

    def test_one_flag_per_system(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary"),
                                           (1632.0, 750.0, 1632.0, 790.0, "vent")])])
        self.assertEqual(sorted(f["system"] for f in flags(res, C.KIND_PIPE)), ["sanitary", "vent"])

    def test_hold_down_pieces_are_listed_separately(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 705.0, 1631.0, 708.0, "sanitary"),   # in the post
                                           (1631.0, 750.0, 1631.0, 790.0, "sanitary")])])  # mid-wall
        p = one(flags(res, C.KIND_PIPE))
        h = one(flags(res, C.KIND_HOLD_DOWN))
        self.assertEqual(p["counts"]["pieces"], 2)
        self.assertEqual(p["counts"]["in_hold_down_zone"], 1)
        self.assertEqual([x["index"] for x in h["pieces"]], [0])
        self.assertEqual(h["pieces"][0]["hold_down_end"], "top")
        self.assertEqual(h["pieces"][0]["hold_down_in"], 0.0)

    def test_the_zone_is_the_end_post_plus_two_inches(self):
        """T3's zone is the post with no buffer; C1 applies TOL_WALL_SIDE_IN."""
        _present()
        self.assertEqual(C.TOL_IN, 2.0)
        y_post_edge = 712.47
        near = (1631.0, y_post_edge + 1.0 * PT_IN, 1631.0, 760.0, "vent")    # 1 in off the post
        far = (1632.0, y_post_edge + 2.5 * PT_IN, 1632.0, 760.0, "vent")     # 2.5 in off
        res = C.check(structure(), [pipes([near, far])])
        h = one(flags(res, C.KIND_HOLD_DOWN))
        self.assertEqual([x["index"] for x in h["pieces"]], [0])
        self.assertAlmostEqual(h["pieces"][0]["hold_down_in"], 1.0, places=1)
        self.assertEqual(h["counts"]["touching_end_post"], 0)

    def test_pipes_on_another_plan_or_track_are_not_joined(self):
        """The join is (track, a_sheet.page_id): a pipe at the same
        coordinates on another A page or another track is another place."""
        _present()
        seg = [(1631.0, 750.0, 1631.0, 790.0, "sanitary")]
        res = C.check(structure(), [pipes(seg, a=A2), pipes(seg, track="post_co")])
        self.assertEqual(flags(res), [])

    def test_a_bearing_wall_is_not_a_frame(self):
        _present()
        rows = [srow("bearing_wall", FRAME, tag=None)]
        res = C.check(rows, [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary")])])
        self.assertEqual(flags(res), [])

    def test_an_untagged_braced_frame_is_a_frame(self):
        _present()
        rows = [srow("braced_frame", FRAME, tag=None)]
        res = C.check(rows, [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary")])])
        f = one(flags(res, C.KIND_PIPE))
        self.assertIn("no hold-down zone", f["frame"]["hold_down_note"])


# ══════════════════════════════════════════════════════════════════════════
# 2. (b) stacks inside or within 2 in of a frame
# ══════════════════════════════════════════════════════════════════════════

class StacksAtAFrame(unittest.TestCase):

    def test_inside_crossing_near_and_away(self):
        _present()
        east = 1635.78
        rows = [stack(1630.30, 736.39, tag="V-3"),                       # inside
                stack(1633.42, 810.25, tag="V-4"),                       # inside, rim 0.07 in off the face
                stack(east + 1.0, 760.0, tag="X-1"),                     # rim across the face
                stack(east + 2.25 + 1.5 * PT_IN, 770.0, tag="X-2"),      # rim 1.5 in off the face
                stack(east + 2.25 + 2.5 * PT_IN, 780.0, tag="X-3")]      # rim 2.5 in off: not flagged
        res = C.check(structure(), [pipes()] + rows)
        f = one(flags(res, C.KIND_STACK))
        got = {s["tag_id"]: s for s in f["stacks"]}
        self.assertEqual(sorted(got), ["V-3", "V-4", "X-1", "X-2"])
        self.assertEqual(got["V-3"]["relation"], "inside")
        self.assertEqual(got["V-4"]["relation"], "inside")
        self.assertLess(got["V-4"]["edge_clearance_in"], 0.25)
        self.assertEqual(got["X-1"]["relation"], "crosses edge")
        self.assertEqual(got["X-2"]["relation"], "outside")
        self.assertAlmostEqual(got["X-2"]["distance_in"], 1.5, places=1)

    def test_the_tolerance_is_from_the_rim_not_the_centre(self):
        """A 4.5pt riser whose rim is 1 in off the face is within 2 in, though
        its centre is 2.5 in away."""
        _present()
        res = C.check(structure(), [stack(1635.78 + 2.25 + PT_IN, 760.0, tag="R-1")])
        f = one(flags(res, C.KIND_STACK))
        self.assertAlmostEqual(f["stacks"][0]["distance_in"], 1.0, places=1)


# ══════════════════════════════════════════════════════════════════════════
# 3. never silence, never a verdict, never the storey below
# ══════════════════════════════════════════════════════════════════════════

VERDICT = re.compile(r"\b(pass(ed|es)?|fail(ed|s)?|clear(ed)?|ok|no clash|compliant)\b", re.I)


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from _strings(v)


class NeverSilentNeverAVerdict(unittest.TestCase):

    def test_a_frame_drawn_below_is_skipped_with_its_zones(self):
        """T3: the roof plan's dashed walls are the storey under it."""
        _present()
        res = C.check(structure(drawn_as="below", level="ROOF"),
                      [pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")]), stack(1630.3, 736.4)])
        self.assertEqual(flags(res), [])
        self.assertEqual(len(res["skipped"]), 1)
        self.assertIn("below", res["skipped"][0]["why"])

    def test_a_refused_frame_is_not_checked_with_its_reason(self):
        _present()
        rows = [srow("shear_wall", None, refused="the offset is 9.4pt from the best peak")]
        res = C.check(rows, [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary")])])
        self.assertEqual(flags(res), [])
        n = one([n for n in res["not_checked"] if n["what"] == "frame"])
        self.assertIn("9.4pt from the best peak", n["reason"])
        self.assertEqual(n["status"], "not checked")

    def test_refused_pipes_and_stacks_are_not_checked_with_their_reasons(self):
        _present()
        res = C.check(structure(), [
            pipes(refused="P-200.00: title names no level", sheet="P-200.00"),
            stack(0, 0, footprint=False, tag="S-4", why=None),
            dict(stack(0, 0, footprint=False, tag="S-3"),
                 placement_refused="P-200.00: title names no level")])
        whats = sorted((n["what"], n["label"]) for n in res["not_checked"])
        self.assertIn(("pipes", "P-200.00 pipes"), whats)
        self.assertIn(("stack", "P-204.00 S-4"), whats)
        self.assertIn(("stack", "P-204.00 S-3"), whats)
        self.assertTrue(all(n["reason"] for n in res["not_checked"]))

    def test_a_frame_no_plumbing_reached_is_not_checked(self):
        _present()
        res = C.check(structure(), [pipes([(1, 1, 2, 2, "sanitary")], a=A2)])
        names = [(n["what"], n["label"]) for n in res["not_checked"]]
        self.assertIn(("frame", "S-104.00 SW 1 (shear wall)"), names)
        self.assertIn(("pipes", "P-204.00 pipes"), names)

    def test_every_flag_says_flag_for_engineer_review_and_nothing_says_a_verdict(self):
        _present()
        self.assertEqual(C.FLAG_LABEL, "flag for engineer review")
        res = C.check(structure() + structure(track="post_co", note="structure per filed set "
                                              "S-104.00; the owner's set has no structural sheets"),
                      [pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")]), stack(1630.3, 736.4),
                       pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")], track="post_co"),
                       pipes(refused="no level", sheet="P-200.00")])
        self.assertTrue(res["flags"])
        for f in res["flags"]:
            self.assertEqual(f["label"], C.FLAG_LABEL)
        for s in _strings(res):
            self.assertIsNone(VERDICT.search(s), s)
        for item in C.review_items(res["flags"], "co", "proj", now=NOW):
            self.assertTrue(item["evidence"]["detail"].startswith(C.FLAG_LABEL), item["evidence"])

    def test_every_owners_set_flag_carries_the_structure_note(self):
        _present()
        note = "structure per filed set S-104.00; the owner's set has no structural sheets"
        res = C.check(structure(track="post_co", note=note),
                      [pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")], track="post_co"),
                       stack(1630.3, 736.4, track="post_co")])
        self.assertEqual(len(res["flags"]), 3)
        for f in res["flags"]:
            self.assertEqual(f["structure_note"], note)
        for item in C.review_items(res["flags"], "co", "proj", now=NOW):
            self.assertIn(note, item["evidence"]["detail"])

    def test_both_margins_are_on_every_flag(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary")])])
        f = one(flags(res))
        self.assertEqual(f["registration_margins"], {"s_to_a": 1.916, "p_to_a": 3.64})


# ══════════════════════════════════════════════════════════════════════════
# 3b. RULING 116: a stack one floor draws off the line the others agree on is
#     a DRAWING INCONSISTENCY, not a clash; RULING 117: P-200 is below the slab
# ══════════════════════════════════════════════════════════════════════════

V4_AGREED = (1631.7, 846.0)
V4_DRAWN = (1633.4, 810.3)               # 35.7 pt = 23.8 in up the wall
OFFSET_ARM = (1635.7, 810.3, 1638.0, 810.3, "vent")       # touches V-4's rim as drawn
SPARE_PIPE = (1631.0, 750.0, 1631.0, 790.0, "vent")       # a pipe in the wall, nowhere near V-4
VOTERS = ("P-201.00", "P-202.00", "P-203.00")


def _floors(*sheets, at=V4_AGREED, tag="V-4", track="filed"):
    """V-4 as the other floors draw it, on A pages with no frame (they only vote)."""
    return [stack(at[0], at[1], tag=tag, sheet=sh, track=track, a=f"a-{sh}") for sh in sheets]


class RulingOneHundredSixteen(unittest.TestCase):

    def _res(self, floors=VOTERS, extra=()):
        return C.check(structure(), [pipes([OFFSET_ARM, SPARE_PIPE]), stack(*V4_DRAWN, tag="V-4")]
                       + _floors(*floors) + list(extra))

    def test_a_stack_one_floor_draws_off_the_line_is_an_inconsistency_not_a_clash(self):
        _present()
        res = self._res()
        self.assertEqual(flags(res, C.KIND_STACK), [])
        it = one(res["inconsistencies"])
        self.assertEqual(it["message"], "V-4 drawn 23.8 in off its stack position on P-204.00; "
                                        "other floors agree")
        self.assertEqual(it["kind"], C.KIND_INCONSISTENCY)
        self.assertEqual(it["label"], C.FLAG_LABEL)
        self.assertEqual(it["agreed"]["sheets"], list(VOTERS))
        self.assertEqual(res["summary"]["inconsistencies"], 1)

    def test_the_pipes_drawn_on_the_offset_stack_move_with_it_and_none_are_lost(self):
        _present()
        res = self._res()
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual([p["index"] for p in f["pieces"]], [1])          # the spare pipe stays flagged
        it = one(res["inconsistencies"])
        self.assertEqual([p["index"] for p in it["reclassified_pieces"]], [0])
        self.assertEqual(it["counts"]["reclassified_pieces"], 1)
        self.assertEqual(res["summary"]["reclassified_pieces"], 1)
        # as drawn the wall holds both pieces; flagged + reclassified is that total
        plain = C.check(structure(), [pipes([OFFSET_ARM, SPARE_PIPE])])
        self.assertEqual(one(flags(plain, C.KIND_PIPE))["counts"]["pieces"],
                         f["counts"]["pieces"] + it["counts"]["reclassified_pieces"])

    def test_pipes_that_exist_only_because_of_the_offset_move_with_it(self):
        """A piece that does not touch the stack, but is the agreeing floor's piece moved by the
        offset, exists only because the stack was drawn there. A piece the agreeing floor draws
        in the same place is the same pipe on every floor and stays flagged."""
        _present()
        ox, oy = V4_DRAWN[0] - V4_AGREED[0], V4_DRAWN[1] - V4_AGREED[1]
        beside = (1631.0, 860.0, 1631.0, 870.0, "sanitary")                  # on P-203
        moved = (beside[0] + ox, beside[1] + oy, beside[2] + ox, beside[3] + oy, "sanitary")  # on P-204
        repeat = (1630.0, 770.0, 1630.0, 780.0, "vent")        # on both floors, where P-203 also has
        back = (repeat[0] - ox, repeat[1] - oy, repeat[2] - ox, repeat[3] - oy, "vent")      # its offset twin
        res = C.check(structure(), [pipes([OFFSET_ARM, SPARE_PIPE, moved, repeat]),
                                    stack(*V4_DRAWN, tag="V-4"),
                                    pipes([beside, SPARE_PIPE, repeat, back], a="a-P-203.00",
                                          sheet="P-203.00")] + _floors(*VOTERS))
        it = one(res["inconsistencies"])
        self.assertEqual(sorted(p["index"] for p in it["reclassified_pieces"]), [0, 2])
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual([p["index"] for p in f["pieces"]], [1, 3])

    def test_the_agreed_position_is_stated_on_the_item(self):
        _present()
        it = one(self._res()["inconsistencies"])
        self.assertEqual(it["agreed"]["relation"], "inside")
        self.assertIn("inside", it["detail"])
        self.assertIn("ruling 116", it["detail"])

    def test_floors_that_disagree_with_each_other_reclassify_nothing(self):
        """No agreed line, no inconsistency: the stack stays a flag where it is drawn."""
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")]
                      + _floors("P-201.00", at=(1631.7, 846.0)) + _floors("P-202.00", at=(1631.7, 780.0)))
        self.assertEqual(res["inconsistencies"], [])
        self.assertEqual(len(one(flags(res, C.KIND_STACK))["stacks"]), 1)

    def test_one_other_floor_is_not_enough_to_agree(self):
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")] + _floors("P-201.00"))
        self.assertEqual(res["inconsistencies"], [])
        self.assertEqual(len(one(flags(res, C.KIND_STACK))["stacks"]), 1)

    def test_the_agreeing_floors_must_outnumber_the_ones_that_repeat_the_offset(self):
        """Two floors on each line is a tie, not an agreement."""
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")] + _floors("P-201.00", "P-202.00")
                      + _floors("P-205.00", at=V4_DRAWN))
        self.assertEqual(res["inconsistencies"], [])

    def test_other_floors_split_evenly_agree_on_nothing(self):
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")]
                      + _floors("P-201.00", "P-202.00") + _floors("P-203.00", "P-206.00", at=(1631.7, 780.0)))
        self.assertEqual(res["inconsistencies"], [])
        self.assertEqual(len(one(flags(res, C.KIND_STACK))["stacks"]), 1)

    def test_a_sheet_that_repeats_the_offset_is_named_and_may_be_outvoted(self):
        _present()
        res = self._res(extra=_floors("P-205.00", at=V4_DRAWN))
        it = one(res["inconsistencies"])
        self.assertEqual(it["same_position_on"], ["P-205.00"])
        self.assertIn("P-205.00", it["detail"])

    def test_within_two_inches_is_the_same_position(self):
        _present()
        near = (V4_AGREED[0], V4_AGREED[1] + 1.5 * PT_IN)
        res = C.check(structure(), [stack(*near, tag="V-4")] + _floors(*VOTERS))
        self.assertEqual(res["inconsistencies"], [])

    def test_another_track_does_not_vote(self):
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")] + _floors(*VOTERS, track="post_co"))
        self.assertEqual(res["inconsistencies"], [])

    def test_another_tag_does_not_vote(self):
        _present()
        res = C.check(structure(), [stack(*V4_DRAWN, tag="V-4")] + _floors(*VOTERS, tag="V-5"))
        self.assertEqual(res["inconsistencies"], [])

    def test_a_stack_away_from_every_frame_has_no_item(self):
        """The rule reclassifies a CLASH; a stack nowhere near a frame never was one."""
        _present()
        res = C.check(structure(), [stack(1200.0, 810.3, tag="V-4")] + _floors(*VOTERS))
        self.assertEqual(res["inconsistencies"], [])

    def test_a_consistent_stack_is_still_a_clash_flag(self):
        _present()
        res = C.check(structure(), [stack(*V4_AGREED, tag="V-4")] + _floors(*VOTERS))
        self.assertEqual(res["inconsistencies"], [])
        self.assertEqual(one(flags(res, C.KIND_STACK))["stacks"][0]["tag_id"], "V-4")

    def test_v3_beside_it_stays_a_flag(self):
        _present()
        res = self._res(extra=[stack(1630.30, 736.39, tag="V-3")])
        f = one(flags(res, C.KIND_STACK))
        self.assertEqual([s["tag_id"] for s in f["stacks"]], ["V-3"])

    def test_the_inconsistency_is_stored_and_carries_no_verdict(self):
        _present()
        res = self._res()
        rows = C.rows_for_store(res, project_id="proj", company_id="co")
        self.assertIn("clash_inconsistency", [r["record_type"] for r in rows])
        for s in _strings(res["inconsistencies"]):
            self.assertIsNone(VERDICT.search(s), s)


class RulingOneHundredSeventeen(unittest.TestCase):

    P200 = "P-200.00: title 'FIRST UNDERGROUND FLOOR SANITARY & STORM PLAN' names no level"

    def test_p200_is_below_slab_skipped_never_a_storey_clash_never_silent(self):
        _present()
        res = C.check(structure(), [pipes([SPARE_PIPE]),
                                    pipes(refused=self.P200, sheet="P-200.00"),
                                    dict(stack(0, 0, footprint=False, tag="S-3", sheet="P-200.00"),
                                         placement_refused=self.P200)])
        self.assertEqual({f["plumbing"]["sheet_number"] for f in res["flags"]}, {"P-204.00"})
        self.assertEqual([n for n in res["not_checked"] if "P-200" in str(n.get("label"))], [])
        sk = one([k for k in res["skipped"] if "P-200.00" in k["what"]])
        self.assertIn("below-slab", sk["why"])
        self.assertIn("no cellar", sk["why"])
        self.assertEqual((sk["pipe_rows"], sk["stack_rows"]), (1, 1))
        self.assertEqual(sk["level"], "below slab")

    def test_a_placed_below_slab_row_inside_a_frame_is_skipped_not_flagged(self):
        """lib.plan_stacks now PLACES P-200's rows on the first-floor A plan
        (for the registration offset) and writes level BELOW_SLAB on them. A
        stack and a pipe through the first-floor frame, on those rows, are
        under the slab: skipped by the level, never flagged, never a ruling
        116 comparison."""
        _present()
        slab_stack = dict(stack(1630.30, 736.39, tag="S-1", sheet="P-200.00"), level="BELOW_SLAB")
        slab_pipe = dict(pipes([(1600.0, 790.0, 1660.0, 790.0, "sanitary")], sheet="P-200.00"),
                         level="BELOW_SLAB")
        res = C.check(structure(), [pipes([SPARE_PIPE]), slab_stack, slab_pipe])
        self.assertEqual([f for f in res["flags"] if f["plumbing"]["sheet_number"] == "P-200.00"], [])
        self.assertEqual([f for f in res["flags"] if f["kind"] == C.KIND_STACK], [])
        self.assertEqual(res["inconsistencies"], [])
        self.assertEqual([n for n in res["not_checked"] if "P-200" in str(n.get("label"))], [])
        sk = one([k for k in res["skipped"] if "P-200.00" in k["what"]])
        self.assertEqual((sk["pipe_rows"], sk["stack_rows"]), (1, 1))
        self.assertEqual(sk["level"], "below slab")
        self.assertIn("no cellar", sk["why"])
        # the same row WITHOUT the level is a storey's row and IS flagged
        res2 = C.check(structure(), [pipes([SPARE_PIPE]), dict(slab_stack, level=None)])
        self.assertEqual(len(flags(res2, C.KIND_STACK)), 1)

    def test_a_sheet_refused_for_another_reason_stays_not_checked(self):
        _present()
        res = C.check(structure(), [pipes([SPARE_PIPE]),
                                    pipes(refused="P-207.00: 0 architectural plans titled at level BULKHEAD",
                                          sheet="P-207.00")])
        self.assertIn(("pipes", "P-207.00 pipes"), [(n["what"], n["label"]) for n in res["not_checked"]])
        self.assertEqual([k for k in res["skipped"] if "P-207" in k["what"]], [])


# ══════════════════════════════════════════════════════════════════════════
# 3c. ROY 2026-10-30: an entry whose OVERLAP is smaller than the sheet's
#     registration RESIDUAL reads "within drawing tolerance, verify on site"
# ══════════════════════════════════════════════════════════════════════════

def clip(overlap_in, y=750.0, system="sanitary"):
    """A horizontal piece running out past the east face (x = 1635.78) at y: it overlaps the
    frame by (1635.78 - x) / 1.5 in, the shortest slide that takes it off the frame."""
    x = 1635.78 - overlap_in * PT_IN
    return (x, y, 1640.0, y, system)


DEEP = (1631.0, 750.0, 1631.0, 790.0, "sanitary")    # runs down the wall, 4.2 pt (2.8 in) in from the west face
P_MAX, S_MAX = 0.8, 0.9                               # the residual: 0.8 + 0.9 = 1.7 in


def tol_items(res, of_kind=None):
    return [t for t in res["within_tolerance"] if of_kind is None or t["of_kind"] == of_kind]


class WithinDrawingTolerance(unittest.TestCase):

    def _res(self, segs, *, p_max=P_MAX, s_max=S_MAX, p_rms=0.08, s_rms=0.3, extra=()):
        return C.check(structure(s_max=s_max, s_rms=s_rms),
                       [pipes(segs, p_max=p_max, p_rms=p_rms)] + list(extra))

    # -- the overlap, a number in inches on every flag ---------------------------------------

    def test_a_pipe_pieces_overlap_is_how_far_it_must_slide_to_leave_the_frame(self):
        _present_tol()
        for want in (0.5, 1.2, 2.0):
            res = self._res([clip(want)], p_max=None, s_max=None)       # no residual: nothing moves
            f = one(flags(res, C.KIND_PIPE))
            self.assertAlmostEqual(f["overlap_in"], want, places=1)
            self.assertAlmostEqual(f["pieces"][0]["overlap_in"], want, places=1)
        res = self._res([DEEP], p_max=None, s_max=None)
        self.assertAlmostEqual(one(flags(res, C.KIND_PIPE))["overlap_in"], 2.81, places=2)

    def test_a_stacks_overlap_is_its_reach_past_the_nearest_face_not_its_rim_clearance(self):
        """V-4 at its agreed position: inside SW 1, rim 1.22 in from the face. It REACHES 1.22 in + its
        3 in diameter = 4.22 in past that face; the 1.22 is how far in it starts, not its overlap."""
        _present_tol()
        res = C.check(structure(s_max=0.987), [stack(*V4_AGREED, tag="V-4", p_max=0.972)])
        f = one(flags(res, C.KIND_STACK))
        s = f["stacks"][0]
        self.assertAlmostEqual(s["edge_clearance_in"], 1.22, places=2)
        self.assertAlmostEqual(s["overlap_in"], 4.22, places=2)
        self.assertEqual(f["overlap_in"], s["overlap_in"])

    def test_a_stack_beside_the_frame_overlaps_by_nothing_and_one_crossing_the_face_by_its_depth(self):
        _present_tol()
        east = 1635.78
        res = C.check(structure(), [stack(east + 2.25 + PT_IN, 760.0, tag="X-2"),      # rim 1 in off
                                    stack(east + 0.75, 770.0, tag="X-1")])             # centre 0.5 in out
        got = {s["tag_id"]: s["overlap_in"] for s in one(flags(res, C.KIND_STACK))["stacks"]}
        self.assertEqual(got["X-2"], 0.0)
        self.assertAlmostEqual(got["X-1"], 1.0, places=2)           # 1.5 in radius - 0.5 in

    def test_a_hold_down_pieces_overlap_is_against_the_end_post(self):
        _present_tol()
        near = (1631.0, 714.0, 1631.0, 730.0, "sanitary")            # 1 in below the post, in the zone
        deep = (1631.0, 703.0, 1631.0, 720.0, "sanitary")            # runs into the post
        res = self._res([near, deep], p_max=None, s_max=None)
        got = {p["index"]: p for p in one(flags(res, C.KIND_HOLD_DOWN))["pieces"]}
        self.assertEqual(got[0]["overlap_in"], 0.0)
        self.assertAlmostEqual(got[1]["overlap_in"], 2.69, places=2)

    # -- the residual: both pairs, the sum of the maxima --------------------------------------

    def test_the_residual_is_the_sum_of_both_registrations_worst_anchor_residual(self):
        _present_tol()
        res = self._res([DEEP])
        f = one(flags(res, C.KIND_PIPE))
        self.assertAlmostEqual(f["residual_in"], 1.7, places=3)
        self.assertEqual(f["residual"]["p_to_a_max_in"], 0.8)
        self.assertEqual(f["residual"]["s_to_a_max_in"], 0.9)
        self.assertEqual(f["residual"]["p_to_a_rms_in"], 0.08)
        self.assertEqual(f["residual"]["s_to_a_rms_in"], 0.3)
        self.assertEqual(f["residual"]["rule"], C.RESIDUAL_RULE)
        self.assertEqual(f["pieces"][0]["residual_in"], f["residual_in"])

    def test_it_takes_both_residuals_not_one_and_the_max_not_the_rms(self):
        """Overlap 1.2 in: over the P residual (0.8) and over the S residual (0.9), under their sum
        (1.7) - and over the sum of the two rms (0.1)."""
        _present_tol()
        res = self._res([clip(1.2)], p_rms=0.05, s_rms=0.05)
        self.assertEqual(flags(res), [])
        t = one(tol_items(res))
        self.assertAlmostEqual(t["overlap_in"], 1.2, places=1)
        self.assertAlmostEqual(t["residual_in"], 1.7, places=3)

    def test_an_overlap_over_the_residual_stays_a_flag_and_equal_is_not_smaller(self):
        _present_tol()
        res = self._res([clip(1.9)])
        self.assertEqual(tol_items(res), [])
        self.assertAlmostEqual(one(flags(res, C.KIND_PIPE))["overlap_in"], 1.9, places=1)
        self.assertTrue(C.within_tolerance(1.69, {"residual_in": 1.7}))
        self.assertFalse(C.within_tolerance(1.7, {"residual_in": 1.7}))
        self.assertFalse(C.within_tolerance(0.0, None))

    def test_a_row_without_its_residual_is_never_softened(self):
        """No max_in on the frame row (T3's rows carry none until with_s_residuals), or on the
        sheet's: the rule does not apply and the entry stays a flag, saying so."""
        _present_tol()
        for kw in ({"s_max": None}, {"p_max": None}):
            res = self._res([clip(0.3)], **kw)
            self.assertEqual(tol_items(res), [], kw)
            f = one(flags(res, C.KIND_PIPE))
            self.assertIsNone(f["residual_in"])
            self.assertIn("not applied", f["residual_rule"])

    # -- the rule: a separate kind, listed with both numbers, never dropped -------------------

    def test_a_piece_inside_the_residual_is_a_tolerance_item_not_a_clash_flag(self):
        _present_tol()
        res = self._res([clip(0.5), DEEP])
        f = one(flags(res, C.KIND_PIPE))
        self.assertEqual([p["index"] for p in f["pieces"]], [1])
        t = one(tol_items(res))
        self.assertEqual(t["kind"], C.KIND_TOLERANCE)
        self.assertEqual(t["of_kind"], C.KIND_PIPE)
        self.assertEqual(t["label"], C.TOLERANCE_LABEL)
        self.assertEqual(C.TOLERANCE_LABEL, "within drawing tolerance, verify on site")
        self.assertEqual([p["index"] for p in t["pieces"]], [0])
        self.assertAlmostEqual(t["overlap_in"], 0.5, places=1)
        self.assertAlmostEqual(t["residual_in"], 1.7, places=3)
        self.assertAlmostEqual(t["pieces"][0]["overlap_in"], 0.5, places=1)
        self.assertAlmostEqual(t["pieces"][0]["residual_in"], 1.7, places=3)
        self.assertEqual(t["system"], "sanitary")

    def test_nothing_is_dropped_every_drawn_piece_is_a_flag_or_a_tolerance_item(self):
        _present_tol()
        segs = [clip(0.5), clip(1.1, y=760.0), DEEP, clip(1.9, y=770.0)]
        res = self._res(segs)
        got = sorted(p["index"] for f in flags(res, C.KIND_PIPE) for p in f["pieces"]) \
            + sorted(p["index"] for t in tol_items(res, C.KIND_PIPE) for p in t["pieces"])
        self.assertEqual(sorted(got), [0, 1, 2, 3])
        self.assertEqual(sum(f["counts"]["pieces"] for f in flags(res, C.KIND_PIPE)), 2)
        self.assertEqual(sum(t["counts"]["pieces"] for t in tol_items(res)), 2)
        self.assertEqual(res["summary"]["within_tolerance"], 1)
        self.assertEqual(res["summary"]["within_tolerance_by_track_kind"], {"filed|pipe_through_frame": 1})

    def test_a_tolerance_item_never_says_flag_for_engineer_review_or_a_verdict(self):
        _present_tol()
        res = self._res([clip(0.5)], extra=[stack(1635.78 + 0.75, 770.0, tag="X-1", p_max=P_MAX)])
        self.assertTrue(tol_items(res))
        for t in res["within_tolerance"]:
            for s in _strings(t):
                self.assertNotIn(C.FLAG_LABEL, s)
                self.assertIsNone(VERDICT.search(s), s)

    def test_tolerance_items_are_stored_and_make_no_clash_queue_item(self):
        _present_tol()
        res = self._res([clip(0.5), DEEP])
        rows = C.rows_for_store(res, project_id="proj", company_id="co")
        self.assertEqual(sorted(r["record_type"] for r in rows),
                         ["clash_flag", "clash_within_tolerance"])
        self.assertEqual(len(C.review_items(res["flags"], "co", "proj", now=NOW)), 1)

    def test_a_stack_inside_the_residual_is_a_tolerance_item_and_one_beside_it_stays_a_flag(self):
        _present_tol()
        res = C.check(structure(s_max=S_MAX), [stack(1635.78 + 0.75, 770.0, tag="X-1", p_max=P_MAX),
                                                stack(1630.3, 736.4, tag="V-3", p_max=P_MAX)])
        f = one(flags(res, C.KIND_STACK))
        self.assertEqual([s["tag_id"] for s in f["stacks"]], ["V-3"])
        t = one(tol_items(res, C.KIND_STACK))
        self.assertEqual([s["tag_id"] for s in t["stacks"]], ["X-1"])
        self.assertAlmostEqual(t["overlap_in"], 1.0, places=2)
        self.assertAlmostEqual(t["residual_in"], 1.7, places=3)
        self.assertEqual(t["label"], C.TOLERANCE_LABEL)

    def test_v4_at_its_agreed_position_is_a_flag_its_overlap_is_over_the_residual(self):
        """P-202's and S-102's own numbers (max_in 0.972 and 0.987, residual 1.959): V-4 reaches
        4.22 in into SW 1. Its rim stands 1.22 in inside the face, which is under the residual -
        but a stack inside a wall is inside it at every position the residual allows."""
        _present_tol()
        res = C.check(structure(s_max=0.987), [stack(*V4_AGREED, tag="V-4", p_max=0.972)])
        self.assertEqual(tol_items(res), [])
        f = one(flags(res, C.KIND_STACK))
        self.assertAlmostEqual(f["residual_in"], 1.959, places=3)
        self.assertGreater(f["overlap_in"], f["residual_in"])

    def test_a_hold_down_piece_not_touching_the_post_is_within_tolerance_one_in_it_is_not(self):
        _present_tol()
        near = (1631.0, 714.0, 1631.0, 730.0, "sanitary")
        deep = (1631.0, 703.0, 1631.0, 720.0, "sanitary")
        res = self._res([near, deep])
        f = one(flags(res, C.KIND_HOLD_DOWN))
        self.assertEqual([p["index"] for p in f["pieces"]], [1])
        t = one(tol_items(res, C.KIND_HOLD_DOWN))
        self.assertEqual([p["index"] for p in t["pieces"]], [0])
        self.assertEqual(t["pieces"][0]["overlap_in"], 0.0)
        # both stay in the frame flag: 2.8 in deep in the wall
        self.assertEqual(sorted(p["index"] for p in one(flags(res, C.KIND_PIPE))["pieces"]), [0, 1])

    def test_the_owners_set_tolerance_items_carry_the_structure_note(self):
        _present_tol()
        note = "structure per filed set S-104.00; the owner's set has no structural sheets"
        res = C.check(structure(track="post_co", note=note, s_max=S_MAX),
                      [pipes([clip(0.5)], track="post_co", p_max=P_MAX)])
        self.assertEqual(one(tol_items(res))["structure_note"], note)

    # -- inputs -------------------------------------------------------------------------------

    def test_with_s_residuals_fills_a_rows_max_from_its_pair_and_touches_nothing_else(self):
        _present_tol()
        rows = structure()
        before = [dict(r["registration"]) for r in rows]
        pairs = [PAIR_S104_A103]
        got = C.with_s_residuals(rows, pairs)
        self.assertEqual([r["registration"] for r in rows], before)          # the input is not changed
        for g, r in zip(got, rows):
            self.assertEqual(g["registration"].get("max_in"), 0.999)
            self.assertEqual(g["registration"].get("rms_in"), 0.356)
            self.assertEqual(g["registration"]["margin"], r["registration"]["margin"])
            self.assertEqual(g["polygon_a"], r["polygon_a"])
        # a row with its own, or with no pair, is left as it was
        own = structure(s_max=0.5)
        self.assertEqual(C.with_s_residuals(own, pairs)[0]["registration"].get("max_in"), 0.5)
        self.assertEqual(C.with_s_residuals(rows, [])[0]["registration"], before[0])

    def test_the_residual_join_is_the_page_not_the_sheet_name(self):
        """The cached pair called the gas-change first floor A-100.01; the rows call it A-100.00.
        Same file, same page: the residual must still reach the rows (the name-keyed join lost it,
        so every FIRST-FLOOR flag was judged with no S residual)."""
        _present_tol()
        rows = structure()                                       # a_sheet: AR.pdf p14, "A-103.00"
        renamed = dict(PAIR_S104_A103, a="A-100.01",
                       a_sheet=dict(PAIR_S104_A103["a_sheet"], sheet_number="A-100.01"))
        got = C.with_s_residuals(rows, [renamed])
        self.assertEqual([g["registration"].get("max_in") for g in got], [0.999] * 3)

    def test_two_pages_that_share_a_sheet_name_are_not_joined(self):
        """3.28.25 and the gas change both carry an A-100.00; same names, different pages: the pair
        registered to the OTHER file's sheet must not hand its residual to these rows."""
        _present_tol()
        rows = structure()
        other_file = dict(PAIR_S104_A103, a_sheet=dict(PAIR_S104_A103["a_sheet"], file_id="f-other"))
        other_page = dict(PAIR_S104_A103, a_sheet=dict(PAIR_S104_A103["a_sheet"], page_number=2))
        for pair in (other_file, other_page):
            got = C.with_s_residuals(rows, [pair])
            self.assertTrue(all(g["registration"].get("max_in") is None for g in got), pair)

    def test_a_pair_with_no_page_refs_joins_nothing(self):
        """A cache from before the pairs kept their page refs is matched on NO name: its rows get no
        residual, and a row with no residual is never softened to a tolerance item."""
        _present_tol()
        bare = {"s": "S-104.00", "a": "A-103.00", "level": "FLOOR_4",
                "registration": {"rms_in": 0.356, "max_in": 0.999, "margin": 9.9}}
        got = C.with_s_residuals(structure(), [bare])
        self.assertTrue(all(g["registration"].get("max_in") is None for g in got))

    def test_penetration_depth_is_the_shortest_slide_out(self):
        _present_tol()
        d = lambda pts_, poly=FRAME: C.inches(C.penetration_depth(pts_, poly))      # noqa: E731
        self.assertAlmostEqual(d([[1620, 750], [1640, 750]]), 8.81, places=2)      # across: slide it off the end
        self.assertAlmostEqual(d([[1620, 704], [1640, 704]]), 0.87, places=2)      # across, near the end face
        self.assertAlmostEqual(d([[1631, 750], [1631, 790]]), 2.81, places=2)      # along the wall
        self.assertEqual(d([[1636, 750], [1640, 750]]), 0.0)                       # beside it
        self.assertEqual(d([[1635.78, 750], [1640, 750]]), 0.0)                    # touching
        self.assertAlmostEqual(C.inches(C.circle_penetration(1631.28, 800, 2.25, FRAME)), 4.5, places=2)


class TheRoofIsNotChecked(unittest.TestCase):
    """Production's filed roof stacks (P-105, P-206) are placed on no plan: the registration is
    refused against the gas-change roof. They are listed as not checked, with the stored reason."""

    WHY = "registration not usable: two peaks tie: 53 anchors at (6.2, -279.1) and 53 at (-0.8, -283.1)"

    def test_unplaced_roof_stacks_and_pipes_are_not_checked_with_their_reason(self):
        _present_tol()
        roof = "a-roof"
        rows = []
        for sheet, tag in (("P-105.00", "CW-1-4"), ("P-105.00", "G-1"), ("P-206.00", "V-3-4")):
            r = stack(0, 0, tag=tag, sheet=sheet, a=roof, footprint=False, why=self.WHY)
            r["status"] = "located"                       # lib.plan_stacks: located, then not placed
            rows.append(r)
        rows.append(pipes(refused=self.WHY, sheet="P-105.00", a=roof))
        res = C.check(structure(drawn_as="below", level="ROOF", a=roof), rows)
        self.assertEqual(res["flags"], [])
        self.assertEqual(res["within_tolerance"], [])
        stacks = [n for n in res["not_checked"] if n["what"] == "stack"]
        self.assertEqual(sorted(n["label"] for n in stacks),
                         ["P-105.00 CW-1-4", "P-105.00 G-1", "P-206.00 V-3-4"])
        for n in stacks:
            self.assertEqual(n["status"], "not checked")
            self.assertIn(self.WHY, n["reason"])
        pipes_nc = [n for n in res["not_checked"] if n["what"] == "pipes"]
        self.assertEqual(len(pipes_nc), 1)
        self.assertIn(self.WHY, pipes_nc[0]["reason"])
        self.assertEqual(res["summary"]["not_checked"], 4)
        self.assertEqual(len(res["skipped"]), 1)          # the roof's walls are drawn below


# ══════════════════════════════════════════════════════════════════════════
# 4. the review queue items and the stored rows (designed, not written)
# ══════════════════════════════════════════════════════════════════════════

class QueueAndStore(unittest.TestCase):

    def test_one_from_clash_item_per_flag_and_stable(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")]),
                                    stack(1630.3, 736.4)])
        items = C.review_items(res["flags"], "co", "proj", now=NOW)
        self.assertEqual(len(items), len(res["flags"]))
        self.assertEqual(len({i["_id"] for i in items}), len(items))
        self.assertTrue(all(i["kind"] == "clash" for i in items))
        again = C.review_items(C.check(structure(), [pipes([(1631.0, 705.0, 1631.0, 790.0, "vent")]),
                                                     stack(1630.3, 736.4)])["flags"], "co", "proj", now=NOW)
        self.assertEqual([i["_id"] for i in items], [i["_id"] for i in again])
        hd = [i for i in items if "hold-down zone" in i["evidence"]["a"] + i["evidence"]["b"]]
        self.assertEqual(len(hd), 1)
        self.assertEqual(sorted(items[0]["evidence"]["sheets"]), ["A-103.00", "P-204.00", "S-104.00"])

    def test_rows_for_store_keep_flags_and_not_checked(self):
        _present()
        res = C.check(structure(), [pipes([(1631.0, 750.0, 1631.0, 790.0, "sanitary")]),
                                    pipes(refused="no level", sheet="P-200.00")])
        rows = C.rows_for_store(res, project_id="proj", company_id="co")
        self.assertEqual(sorted(r["record_type"] for r in rows), ["clash_flag", "clash_not_checked"])
        self.assertTrue(all(r["project_id"] == "proj" and r["company_id"] == "co" for r in rows))
        self.assertEqual(C.COLLECTION, "plan_clash")


# ══════════════════════════════════════════════════════════════════════════
# 5. THE BENCHMARK on the Boyland drawings: P-204.00 vs S-104.00 SW 1 on A-103.00
# ══════════════════════════════════════════════════════════════════════════

#: the filed track's own index rows (production, find()-only probe 2026-10-29)
BENCH_PAGES = [
    {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN", "file_name": "AR - 3.28.25.pdf", "file_id": "f-ar328",
     "page_number": 14, "page_id": "6adf9c5dbbd592e9bb0e5256"},
    {"sheet_number": "S-104.00", "sheet_title": "4TH FLOOR FRAMING PLAN", "file_name": "ST - 7.29.26.pdf", "file_id": "f-st729",
     "page_number": 8, "page_id": "6ab066318cb050f05e5360e9"},
    {"sheet_number": "S-301.00", "sheet_title": "SHEAR WALL SCHEDULE AND DETAILS",
     "file_name": "ST - 7.29.26.pdf", "file_id": "f-st729", "page_number": 11, "page_id": "6ab066e68cb050f05e5361b6"},
    {"sheet_number": "S-302.00", "sheet_title": "SHEAR WALL SCHEDULE AND DETAILS",
     "file_name": "ST - 7.29.26.pdf", "file_id": "f-st729", "page_number": 12, "page_id": "6ab0666a8cb050f05e53617d"},
    {"sheet_number": "P-204.00", "sheet_title": "FOURTH FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "file_id": "f-pl629", "page_number": 12, "page_id": "6ab0640c8cb050f05e535f24"},
]


#: the other floors' sheets, read only so that V-4's position on each can vote (ruling 116)
FLOOR_PAGES = [
    {"sheet_number": "A-100.01", "sheet_title": "FIRST FLOOR PLAN", "file_name": "AR - 8.18.26.pdf", "file_id": "f-AR81826pdf",
     "page_number": 6, "page_id": "6ab05f0a8cb050f05e535ba9"},
    {"sheet_number": "A-101.00", "sheet_title": "SECOND FLOOR PLAN", "file_name": "AR - 3.28.25.pdf", "file_id": "f-ar328",
     "page_number": 12, "page_id": "6adf9c37bbd592e9bb0e524a"},
    {"sheet_number": "A-102.00", "sheet_title": "THIRD FLOOR PLAN", "file_name": "AR - 3.28.25.pdf", "file_id": "f-ar328",
     "page_number": 13, "page_id": "6adf9c50bbd592e9bb0e524f"},
    {"sheet_number": "A-104.00", "sheet_title": "MEZZANINE PLAN", "file_name": "AR - 3.28.25.pdf", "file_id": "f-ar328",
     "page_number": 15, "page_id": "6adf9c68bbd592e9bb0e525e"},
    {"sheet_number": "P-201.00", "sheet_title": "FIRST FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "file_id": "f-pl629", "page_number": 9, "page_id": "6ab063d38cb050f05e535ef8"},
    {"sheet_number": "P-202.00", "sheet_title": "SECOND FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "file_id": "f-pl629", "page_number": 10, "page_id": "6ab0640e8cb050f05e535f26"},
    {"sheet_number": "P-203.00", "sheet_title": "THIRD FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "file_id": "f-pl629", "page_number": 11, "page_id": "6ab0640d8cb050f05e535f25"},
    {"sheet_number": "P-205.00", "sheet_title": "MEZZANINE FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "file_id": "f-pl629", "page_number": 13, "page_id": "6ab0644a8cb050f05e535f30"},
]


class TheBenchmark(unittest.TestCase):
    """Measured 2026-10-29 (bv-worktrees/C1_clash_measure.md): AS DRAWN, 70
    sanitary/vent pieces in SW 1 (34 straight + 36 curved); 15 touch its end
    posts (7 + 8; 8 at the top, 7 at the bottom) - T3's and T4's numbers - and
    29 are within the end post + 2 in. V-3 inside the frame.

    Ruling 116: P-204 draws V-4 23.8 in off the line P-201..P-203 agree on, so
    V-4 and the 15 pieces that exist only because it was drawn there (the run
    of pipework around the riser: P-203's pieces moved by the offset - V-4's
    vent circle and arm, the sanitary and vent circles beside it, and their
    arms) are an inconsistency item, not flags: 55 flagged + 15 reclassified =
    the 70 as drawn. None of the 15 is in a hold-down zone."""

    res = None

    @classmethod
    def _run(cls):
        if cls.res is None:
            from lib import plan_stacks, plan_structural
            from lib.plan_page import PlanPage

            def open_page(p):
                return PlanPage(str(require_pdf(p["file_name"])), int(p["page_number"]))
            st = plan_structural.run_track(BENCH_PAGES, open_page, track="filed")
            pl = plan_stacks.run_stacks([("filed", BENCH_PAGES + FLOOR_PAGES)], open_page, None, 56.0,
                                        place=False)
            cls._pairs = st["summary"]["pairs"]
            cls._rows = C.with_s_residuals(st["rows"], cls._pairs)
            cls.res = C.check(cls._rows, pl["rows"])
        return cls.res

    def _sw1(self, kind):
        return [f for f in self._run()["flags"] if f["kind"] == kind and f["frame"]["tag"] == "SW 1"
                and f["plumbing"]["sheet_number"].startswith("P-204")]

    def _sw1_tol(self, kind):
        return [f for f in self._run()["within_tolerance"] if f["of_kind"] == kind
                and f["frame"]["tag"] == "SW 1" and f["plumbing"]["sheet_number"].startswith("P-204")]

    def _v4(self):
        return one([i for i in self._run()["inconsistencies"] if i["stack"]["tag_id"] == "V-4"
                    and i["stack"]["plumbing_sheet"].startswith("P-204")])

    def test_every_pair_keeps_its_page_and_every_row_gets_its_s_residual(self):
        """run_track's own summary pairs carry (file id, page) for both sheets, and through them every
        placed row of the track receives its S->A residual (none is left to the 'no residual' path)."""
        _present_tol()
        require_pdf("PL - 6.29.26.pdf")
        self._run()
        for p in self._pairs:
            self.assertIsNotNone(C.page_key(p.get("s_sheet")), p["s"])
            self.assertIsNotNone(C.page_key(p.get("a_sheet")), p["a"])
        rows = [r for r in self._rows if r.get("placement") == "placed"]
        self.assertTrue(rows)
        self.assertEqual([r["label"] for r in rows if r["registration"].get("max_in") is None], [])

    def test_seventy_pieces_in_sw1_as_drawn_thirty_seven_flagged_eighteen_within_tolerance_fifteen_reclassified(self):
        """70 as drawn = 15 reclassified (ruling 116) + 37 flagged + 18 within drawing tolerance
        (their overlap, 0.03 to 1.57 in, is under P-204's and S-104's residual of 1.809 in)."""
        _present_tol()
        require_pdf("PL - 6.29.26.pdf")
        sv = [f for f in self._sw1(C.KIND_PIPE) if f["system"] in ("sanitary", "vent")]
        tv = [f for f in self._sw1_tol(C.KIND_PIPE) if f["system"] in ("sanitary", "vent")]
        v4 = self._v4()
        flagged = sum(f["counts"]["pieces"] for f in sv)
        within = sum(f["counts"]["pieces"] for f in tv)
        self.assertEqual(flagged, 37)
        self.assertEqual(within, 18)
        self.assertEqual(v4["counts"]["reclassified_pieces"], 15)
        self.assertEqual(flagged + within + v4["counts"]["reclassified_pieces"], 70)
        self.assertEqual(sum(f["counts"]["straight"] for f in sv + tv) + v4["counts"]["straight"], 34)
        self.assertEqual(sum(f["counts"]["curved"] for f in sv + tv) + v4["counts"]["curved"], 36)
        for f in sv:
            self.assertGreaterEqual(f["overlap_in"], f["residual_in"])
            self.assertAlmostEqual(f["residual_in"], 1.809, places=3)
        for f in tv:
            self.assertLess(f["overlap_in"], f["residual_in"])
            self.assertEqual(f["label"], C.TOLERANCE_LABEL)

    def test_the_fifteen_reclassified_pieces_are_the_run_around_v4(self):
        _present_tol()
        require_pdf("PL - 6.29.26.pdf")
        got = sorted((p["system"], p["piece"], p["index"]) for p in self._v4()["reclassified_pieces"])
        self.assertEqual(got, sorted(
            [("sanitary", "curved", i) for i in (26, 27, 28, 29)] + [("sanitary", "straight", 21)]
            + [("vent", "curved", i) for i in (30, 31, 32, 33, 42, 43, 44)]
            + [("vent", "straight", i) for i in (23, 34, 35)]))

    def test_fifteen_touch_the_end_posts_and_twenty_nine_are_within_two_inches(self):
        """The zone as drawn is unchanged: 15 touch the end posts (7 + 8; 8 top) and 29 are within
        the post + 2 in. Against the residual only 4 of the 29 run into a post by more than 1.809 in
        (all four touch it); the other 25, 11 of them touching it, are within drawing tolerance."""
        _present_tol()
        require_pdf("PL - 6.29.26.pdf")
        flagged = [p for f in self._sw1(C.KIND_HOLD_DOWN) for p in f["pieces"]]
        within = [p for f in self._sw1_tol(C.KIND_HOLD_DOWN) for p in f["pieces"]]
        pieces = flagged + within
        touching = [p for p in pieces if p["hold_down_in"] == 0]
        self.assertEqual(len(touching), 15)
        self.assertEqual(sum(1 for p in touching if p["piece"] == "straight"), 7)
        self.assertEqual(sum(1 for p in touching if p["hold_down_end"] == "top"), 8)
        self.assertEqual(len(pieces), 29)
        self.assertTrue(all(0 <= p["hold_down_in"] <= 2.0 for p in pieces))
        self.assertEqual((len(flagged), len(within)), (4, 25))
        self.assertEqual(sum(1 for p in flagged if p["hold_down_in"] == 0), 4)
        self.assertEqual(sum(1 for p in within if p["hold_down_in"] == 0), 11)
        self.assertTrue(all(p["overlap_in"] >= 1.809 for p in flagged))
        self.assertTrue(all(p["overlap_in"] < 1.809 for p in within))
        self.assertEqual(self._v4()["counts"]["in_hold_down_zone"], 0)

    def test_v3_is_a_flag_inside_the_frame_and_v4_is_an_inconsistency(self):
        """By WHERE the stacks are (T4's measured A points) for V-3, not the tag
        text; V-4 by its tag, which the rule needs (it compares a tag across floors)."""
        _present_tol()
        require_pdf("PL - 6.29.26.pdf")
        f = one(self._sw1(C.KIND_STACK))
        self.assertEqual(len(f["stacks"]), 1, [(s["tag_id"], s["x"], s["y"]) for s in f["stacks"]])
        v3 = f["stacks"][0]
        self.assertLess(abs(v3["x"] - 1630.30), 1)
        self.assertLess(abs(v3["y"] - 736.39), 1)
        self.assertEqual(v3["relation"], "inside", v3)
        self.assertGreater(v3["overlap_in"], v3["residual"]["residual_in"])         # stays a flag
        self.assertEqual(f["label"], C.FLAG_LABEL)
        v4 = self._v4()
        self.assertEqual(v4["message"], "V-4 drawn 23.8 in off its stack position on P-204.00; "
                                        "other floors agree")
        self.assertEqual(v4["agreed"]["sheets"], ["P-201.00", "P-202.00", "P-203.00"])
        self.assertEqual(v4["agreed"]["relation"], "inside")


if __name__ == "__main__":
    unittest.main()
