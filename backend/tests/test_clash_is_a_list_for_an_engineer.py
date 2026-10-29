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


NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
A, A2 = "a103", "a102"
S_REF = {"page_id": "s104", "sheet_number": "S-104.00", "file_name": "ST.pdf", "page_number": 8}
A_REF = {"page_id": A, "sheet_number": "A-103.00", "file_name": "AR.pdf", "page_number": 14,
         "sheet_title": "FOURTH FLOOR PLAN"}
# SW 1 as T3 places it on A-103.00: 9 x 177 pt (6 in x 9'-10"), end posts at each end
FRAME = [[1626.78, 702.69], [1635.78, 702.69], [1635.78, 879.69], [1626.78, 879.69]]
TOP = [[1626.96, 702.69], [1635.6, 702.69], [1635.6, 712.47], [1626.96, 712.47]]
BOT = [[1626.96, 869.97], [1635.6, 869.97], [1635.6, 879.69], [1626.96, 879.69]]
PT_IN = 1.5                          # 1/4" = 1'-0": one real inch is 1.5 pt


def srow(element, polygon, *, tag="SW 1", track="filed", a=A, end=None, drawn_as="at_level",
         refused=None, note=None, level="FLOOR_4"):
    a_ref = dict(A_REF, page_id=a)
    return {"emit_version": 1, "track": track, "level": level, "element": element, "tag": tag,
            "label": f"S-104.00 {tag} ({element.replace('_', ' ')})" if tag else f"S-104.00 {element}",
            "s_sheet": S_REF, "a_sheet": a_ref, "polygon_a": polygon,
            "placement": "placed" if polygon else "refused", "refused": refused,
            "registration": {"dx": 6.3, "dy": -242.49, "anchors": 209, "margin": 1.916, "usable": True},
            "structure_note": note,
            "attrs": {"drawn_as": drawn_as if element != "hold_down" else None, "end": end,
                      "zone_from": "post at the end member" if end else None}}


def structure(track="filed", a=A, note=None, drawn_as="at_level", level="FLOOR_4"):
    return [srow("shear_wall", FRAME, track=track, a=a, note=note, drawn_as=drawn_as, level=level),
            srow("hold_down", TOP, track=track, a=a, end="top", note=note, level=level),
            srow("hold_down", BOT, track=track, a=a, end="bottom", note=note, level=level)]


def pipes(segments=(), curves=(), *, track="filed", a=A, sheet="P-204.00", refused=None):
    placed = refused is None
    return {"record_type": "pipe_segments", "track": track, "plumbing_sheet": sheet,
            "plumbing_page_id": "p204", "arch_page_id": a,
            "a_sheet": dict(A_REF, page_id=a),
            "segments": [list(s) for s in segments] if placed else None,
            "curves": [[list(map(list, c[0])), c[1]] for c in curves] if placed else None,
            "registration": {"dx": -25.51, "dy": -66.04, "margin": 3.64, "usable": True},
            "placement_refused": refused}


def stack(x, y, r=2.25, tag="V-3", track="filed", a=A, footprint=True, why=None):
    return {"record_type": "stack", "track": track, "plumbing_sheet": "P-204.00",
            "plumbing_page_id": "p204", "tag_id": tag, "a_sheet": dict(A_REF, page_id=a),
            "arch_page_id": a, "status": "located" if footprint else "no_stack",
            "footprint_arch": ({"type": "circle", "x": x, "y": y, "r": r, "frame": "arch_page_pt"}
                               if footprint else None),
            "pipe_systems": ["vent"], "placement_refused": why,
            "registration": {"margin": 3.64, "usable": True}}


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
    {"sheet_number": "A-103.00", "sheet_title": "FOURTH FLOOR PLAN", "file_name": "AR - 3.28.25.pdf",
     "page_number": 14, "page_id": "6adf9c5dbbd592e9bb0e5256"},
    {"sheet_number": "S-104.00", "sheet_title": "4TH FLOOR FRAMING PLAN", "file_name": "ST - 7.29.26.pdf",
     "page_number": 8, "page_id": "6ab066318cb050f05e5360e9"},
    {"sheet_number": "S-301.00", "sheet_title": "SHEAR WALL SCHEDULE AND DETAILS",
     "file_name": "ST - 7.29.26.pdf", "page_number": 11, "page_id": "6ab066e68cb050f05e5361b6"},
    {"sheet_number": "S-302.00", "sheet_title": "SHEAR WALL SCHEDULE AND DETAILS",
     "file_name": "ST - 7.29.26.pdf", "page_number": 12, "page_id": "6ab0666a8cb050f05e53617d"},
    {"sheet_number": "P-204.00", "sheet_title": "FOURTH FLOOR SANITARY & STORM PLAN",
     "file_name": "PL - 6.29.26.pdf", "page_number": 12, "page_id": "6ab0640c8cb050f05e535f24"},
]


class TheBenchmark(unittest.TestCase):
    """Measured 2026-10-29 (bv-worktrees/C1_clash_measure.md): 70 sanitary/vent
    pieces in SW 1 (34 straight + 36 curved); 15 touch its end posts as drawn
    (7 + 8; 8 at the top, 7 at the bottom) - T3's and T4's numbers - and 29
    are within the end post + 2 in. V-3 inside the frame, V-4 inside on its
    east face (rim 0.07 in off). Ruling 116 pending: V-4 is flagged where
    P-204 draws it."""

    res = None

    @classmethod
    def _run(cls):
        if cls.res is None:
            from lib import plan_stacks, plan_structural
            from lib.plan_page import PlanPage

            def open_page(p):
                return PlanPage(str(require_pdf(p["file_name"])), int(p["page_number"]))
            st = plan_structural.run_track(BENCH_PAGES, open_page, track="filed")
            pl = plan_stacks.run_stacks([("filed", BENCH_PAGES)], open_page, None, 56.0, place=False)
            cls.res = C.check(st["rows"], pl["rows"])
        return cls.res

    def _sw1(self, kind):
        return [f for f in self._run()["flags"] if f["kind"] == kind and f["frame"]["tag"] == "SW 1"
                and f["plumbing"]["sheet_number"].startswith("P-204")]

    def test_seventy_pieces_in_sw1(self):
        _present()
        require_pdf("PL - 6.29.26.pdf")
        got = self._sw1(C.KIND_PIPE)
        sv = [f for f in got if f["system"] in ("sanitary", "vent")]
        self.assertEqual(sum(f["counts"]["pieces"] for f in sv), 70)
        self.assertEqual(sum(f["counts"]["straight"] for f in sv), 34)
        self.assertEqual(sum(f["counts"]["curved"] for f in sv), 36)

    def test_fifteen_touch_the_end_posts_and_twenty_nine_are_within_two_inches(self):
        _present()
        require_pdf("PL - 6.29.26.pdf")
        pieces = [p for f in self._sw1(C.KIND_HOLD_DOWN) for p in f["pieces"]]
        touching = [p for p in pieces if p["hold_down_in"] == 0]
        self.assertEqual(len(touching), 15)
        self.assertEqual(sum(1 for p in touching if p["piece"] == "straight"), 7)
        self.assertEqual(sum(1 for p in touching if p["hold_down_end"] == "top"), 8)
        self.assertEqual(len(pieces), 29)
        self.assertTrue(all(0 <= p["hold_down_in"] <= 2.0 for p in pieces))

    def test_v3_inside_and_v4_on_the_east_face(self):
        """By WHERE the stacks are (T4's measured A points), not by the tag
        text: this run reads P-204 alone, and T4 votes SHX digits across the
        whole set (a lone "3" is the digit it pools to read)."""
        _present()
        require_pdf("PL - 6.29.26.pdf")
        f = one(self._sw1(C.KIND_STACK))
        at = lambda x, y: [s for s in f["stacks"] if abs(s["x"] - x) < 1 and abs(s["y"] - y) < 1]  # noqa: E731
        v3, v4 = one(at(1630.30, 736.39)), one(at(1633.42, 810.25))
        self.assertEqual(len(f["stacks"]), 2, [(s["tag_id"], s["x"], s["y"]) for s in f["stacks"]])
        self.assertEqual(v3["relation"], "inside", v3)
        self.assertEqual(v4["relation"], "inside", v4)
        self.assertLess(v4["edge_clearance_in"], 0.25, v4)
        self.assertEqual(f["label"], C.FLAG_LABEL)


if __name__ == "__main__":
    unittest.main()
