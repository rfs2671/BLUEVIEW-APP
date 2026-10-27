"""ROOF DRAINS: A PLAN-ONLY FAMILY, COUNTED PER TAG.

Ruling (operator, 2026-10-26), verbatim:

    "Roof drains: plan-only family allowed at sheet scope when a detail/note
    in the set names the object (P-400 detail, SD1-2 note), labeled "located
    on P-206; no schedule lists them". Bind per tag only: RD-1 (roof drain,
    J.R. Smith detention) and RD-2 (overflow). A combined total refuses; the
    render states 2 + 2. SD1-2's "2" is a printed figure for RD-1: agree
    binds, disagree withholds both. Includes rotation-aware sweep + fix for
    SLOPE DN arrows crossing labels."

Measured 2026-10-26 on P-206.00 (PL - 6.29.26.pdf p14, /Rotate 270): four
drains by eye, 2 x RD-1 and 2 x RD-2, each a round symbol on the layer
P-Fixt-Dran-Roof-Roun. The plain sweep reads both RD-2 labels but neither
RD-1 - the SLOPE DN arrows, a grey pen, cross them - and snaps FD-1 (a floor
drain) to RD-1 with one letter corrected: RD-1 1 + RD-2 1, the RD-1 "right"
only by cancelling. Ink-only, exact reads, symbol never the grey pen: all
four, each within 2 pt of its drain.

The gate cases below build the records exactly as search_plans hands them
over: the rows of the pass, a census per family carrying what the set says
(lib.plan_only at question time), and the records that name the object. The
real-sheet cases read P-206.00 itself.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from lib import plan_takeoff as T  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

PID = "6a5f63bc147407d3261df2c7"
FAM = "ROOF DRAINS"
TAGS = ["RD-1", "RD-2"]
SD12 = ("2 J.R. Smith Special Purpose (Model 1010-83) Roof Drains @ 3.57gpm "
        "@3\" Detention")
P206 = {"project_id": PID, "company_id": "c", "file_id": "f-pl", "file_hash": "h",
        "file_name": "PL - 6.29.26.pdf", "page_id": "p206", "page_number": 14,
        "sheet_number": "P-206.00", "sheet_title": "ROOF SANITARY & STORM PLAN",
        "discipline": "plumbing"}


def _P():
    """lib.plan_only, or a FAILED assertion (never an ImportError) when this
    tree has no plan-only family."""
    try:
        from lib import plan_only as P
    except ImportError:
        P = None
    assert P is not None and hasattr(P, "families"), \
        "no plan-only family in this tree (lib.plan_only)"
    assert "plan_only" in inspect.signature(S.glyph_census).parameters, \
        "the census cannot carry a plan-only family in this tree"
    return P


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── what the set prints (as production holds it, 2026-10-26) ─────────────

def _set_records(sd12=SD12, detail=True, note=True):
    rough_in = {"record_type": "schedule", "tier": "ocr_grid_cell", "sheet_number": "P-400.00",
                "file_name": "PL - 6.29.26.pdf", "page_number": 20, "page_id": "p400",
                "quote": "PLUMBING ROUGH-IN SCHEDULE ...",
                "payload": {"name": "PLUMBING ROUGH-IN SCHEDULE",
                            "columns": ["FIXTURES", "ABBR", "H.W.", "C.W.", "WASTE", "VENT"],
                            "rows": [["LAVATORIES", "LAV", '1/2"', '1/2"', '1-1/4"', '1-1/4"'],
                                     ["FLOOR RDRAINS", "FD", "", "", '3",4"', '2"'],
                                     ["ROOF DRAIN", "RD-1", "", "", "SEE SD-1&SD-2", ""],
                                     ["OVERFLOWROOFDRAIN", "RD-2", "", "", "SEE SD-1&SD-2", ""]]}}
    out = [rough_in,
           # never a naming: a legend glyph on the architectural roof plan, and a vision read
           {"record_type": "legend_entry", "tier": "tag_legend", "sheet_number": "A-105.01",
            "quote": "FLOOR/AREA/ROOF DRAIN", "page_number": 7, "file_name": "AR - 8.18.26.pdf"},
           {"record_type": "element", "tier": "vision_read", "sheet_number": "F",
            "quote": "roof drain - count 2 - in the site plan", "page_number": 3,
            "file_name": "SD1-2 - 4.1.25.pdf", "payload": {"count_if_stated": 2}}]
    if detail:
        out.append({"record_type": "text", "tier": "text_layer", "sheet_number": "P-400.00",
                    "file_name": "PL - 6.29.26.pdf", "page_number": 20,
                    "quote": "SCALE: NONE ROOF DRAIN DETAIL"})
    if note:
        out.append({"record_type": "dimension", "tier": "text_layer", "sheet_number": "1 OF 1",
                    "file_name": "SD1-2 - 4.1.25.pdf", "page_number": 4, "quote": sd12})
    return out


# ── the rows the pass writes: one per located label, at sheet scope ───────

def _rows(located=(("RD-1", 1010, 703), ("RD-2", 1010, 742), ("RD-1", 1694, 707),
                   ("RD-2", 1693, 741)), plan_only=None):
    res = {"records": [{"tag": t, "unit": None, "glyph_status": "resolved",
                        "placement": "refused", "how": "refused: sheet scope",
                        "reason": "refused: sheet scope", "label_at": (x, y),
                        "label_box": (x - 9, y - 6, x + 9, y + 6), "label_text": t,
                        "symbol_at": (x - 23 if x < 1300 else x + 22, y + 4),
                        "symbol_bbox": None, "at_arch": None}
                       for t, x, y in located]}
    rows = E.glyph_rows(res, mech=P206, arch=None, family=FAM,
                        pass_key=f"plan-only|P-206.00|{FAM}", units={"tags": []},
                        widest_door={}, mech_count=len(located))
    for r in rows:
        r["payload"]["track"] = "filed"
        if plan_only is not None:
            r["payload"]["plan_only"] = plan_only
    return rows


def _records(rows=None, set_records=None, plan_only="derive"):
    P = _P()
    set_records = _set_records() if set_records is None else set_records
    rows = _rows() if rows is None else rows
    fam = P.families(set_records).get(FAM) if plan_only == "derive" else plan_only
    pages = sorted({r["page_id"] for r in rows} | {"p400"})
    probe = S.glyph_census("family", PID, pages, 0, family=FAM, tags=TAGS, track="filed")
    n = sum(S.glyph_in_census(r, probe) for r in rows)
    census = S.glyph_census("family", PID, pages, n, family=FAM, tags=TAGS, track="filed",
                            plan_only=fam)
    ref = S.glyph_census("refusals", PID, pages, 0, track="filed")
    ref["count"] = sum(S.glyph_in_census(r, ref) for r in rows)
    return rows + [census, ref] + set_records


class PerTagOnly(unittest.TestCase):

    def test_each_tag_binds_its_own_count(self):
        recs = _records()
        for s in ("RD-1: 2.", "There are 2 RD-2.", "There are 2 overflow roof drains.",
                  "The overflow drains number 2.", "There are 2 RD-1 roof drains on P-206."):
            self.assertTrue(_ok(s, recs), s)

    def test_a_wrong_figure_for_a_tag_refuses(self):
        recs = _records()
        self.assertTrue(_ok("RD-1: 2.", recs))
        for s in ("RD-1: 3.", "There are 1 RD-2.", "There are 4 overflow drains.", "RD-1: 4."):
            self.assertFalse(_ok(s, recs), s)

    def test_a_combined_total_refuses_whatever_its_value(self):
        recs = _records()
        self.assertTrue(_ok("There are 2 RD-2.", recs), "the per-tag figure must bind here")
        for v in range(0, 9):
            for s in (f"There are {v} roof drains.", f"The roof drains number {v}."):
                self.assertFalse(_ok(s, recs), s)

    def test_a_floor_or_unit_figure_refuses(self):
        """Sheet scope: located on its plan, placed nowhere."""
        recs = _records()
        self.assertTrue(_ok("There are 2 RD-1.", recs))
        for s in ("The roof has 2 RD-1.", "Each unit has 2 RD-1.", "4A has 2 RD-2.",
                  "The fourth floor has 2 RD-2."):
            self.assertFalse(_ok(s, recs), s)


class TheNoteMustAgree(unittest.TestCase):

    def test_sd12_agrees_and_rd1_binds(self):
        P = _P()
        fam = P.families(_set_records())[FAM]
        self.assertEqual([p["value"] for p in fam["printed"].get("RD-1", [])], ["2"],
                         "SD1-2's 2 is RD-1's printed figure")
        self.assertNotIn("RD-2", fam["printed"])
        self.assertTrue(_ok("RD-1: 2.", _records()))

    def test_sd12_disagrees_and_both_are_withheld(self):
        P = _P()
        mutated = _set_records(sd12=SD12.replace("2 J.R.", "3 J.R.", 1))
        self.assertEqual([p["value"] for p in P.families(mutated)[FAM]["printed"]["RD-1"]], ["3"])
        recs = _records(set_records=mutated)
        self.assertFalse(_ok("RD-1: 2.", recs), "the located 2 is withheld")
        self.assertFalse(_ok("RD-1: 3.", recs), "the printed 3 is withheld")
        self.assertTrue(_ok("RD-2: 2.", recs), "RD-2 has no printed figure to disagree with")
        self.assertIn("THEY DISAGREE", S.render_glyph_evidence(recs))


class TheRender(unittest.TestCase):

    def test_it_states_two_plus_two_with_the_label(self):
        out = S.render_glyph_evidence(_records())
        self.assertIn("RD-1 2 + RD-2 2", out)
        self.assertIn("located on P-206.00; no schedule lists them", out)
        self.assertIn("never one total", out)
        self.assertNotIn("4 in all", out)


class NoFamilyUnlessTheSetNamesIt(unittest.TestCase):

    def test_without_a_detail_or_note_there_is_no_family(self):
        P = _P()
        self.assertIn(FAM, P.families(_set_records()))
        self.assertEqual(P.families(_set_records(detail=False, note=False)), {},
                         "a legend glyph and a vision read do not name it")

    def test_one_naming_is_enough(self):
        P = _P()
        self.assertIn(FAM, P.families(_set_records(note=False)))
        self.assertIn(FAM, P.families(_set_records(detail=False)))

    def test_rows_without_a_naming_bind_nothing(self):
        """The rows of a pass, read when the set no longer names the object."""
        P = _P()
        named = P.families(_set_records())[FAM]
        self.assertTrue(_ok("RD-1: 2.", _records(plan_only=named)))
        bare = dict(named, named_by=[])
        recs = _records(plan_only=bare, set_records=_set_records(detail=False, note=False))
        for s in ("RD-1: 2.", "RD-2: 2.", "There are 2 overflow drains."):
            self.assertFalse(_ok(s, recs), s)
        self.assertIn("NOT COUNTED", S.render_glyph_evidence(recs))


class ScheduleFamiliesAreUntouched(unittest.TestCase):

    def test_a_clause_about_the_roof_still_names_its_schedule(self):
        """'roof' is a level and the object's first word: a plan-only family
        is named by its object, so 'the roof has 1 SAF-1' / '... exhaust
        fans' stay the schedules' own."""
        _P()
        recs = _records()
        recs.append(S.glyph_census("family", PID, ["p206"], 0, family="EXHAUST FAN SCHEDULE",
                                   tags=["EF-1", "EF-2"], track="filed"))
        book = S.glyph_books(recs).totals
        self.assertEqual([(f.name, t) for f, t in S._clause_subjects("the roof has 2 exhaust fans", book)],
                         [("EXHAUST FAN SCHEDULE", ["EF-1", "EF-2"])])
        self.assertEqual([(f.name, t) for f, t in S._clause_subjects("there are 2 overflow drains", book)],
                         [(FAM, ["RD-2"])])
        self.assertEqual(S._clause_subjects("there are 3 floor drains", book), [])


# ══════════════════════════════════════════════════════════════════════════
# P-206.00 itself
# ══════════════════════════════════════════════════════════════════════════

#: Tiles on the full sweep's 140 pt grid, so a region sweep reads exactly the
#: crops the whole-sheet sweep reads around each pair of drains.
LEFT, RIGHT = (980, 560, 1140, 860), (1540, 560, 1840, 860)
#: PASSIVE RECREATION (twice) and a 42" PARAPET, for the frame.
WORDS = (1400, 280, 1740, 720)


def _drain_centres(pg):
    """The round roof-drain symbols, by their own CAD layer: the truth."""
    cl = []
    for d in pg.drawings:
        if "DRAN-ROOF" not in (d.get("layer") or "").upper():
            continue
        x0, y0, x1, y1 = d["rect"]
        for c in cl:
            if abs(c[0] - (x0 + x1) / 2) < 12 and abs(c[1] - (y0 + y1) / 2) < 12:
                c[2] += [x0, x1]; c[3] += [y0, y1]
                break
        else:
            cl.append([(x0 + x1) / 2, (y0 + y1) / 2, [x0, x1], [y0, y1]])
    return [((min(c[2]) + max(c[2])) / 2, (min(c[3]) + max(c[3])) / 2) for c in cl]


class OnP206(unittest.TestCase):
    """PL - 6.29.26.pdf p14: the roof sanitary & storm plan, /Rotate 270."""

    @classmethod
    def setUpClass(cls):
        from lib import plan_ocr
        ok, why = plan_ocr.probe()
        if not ok:
            raise unittest.SkipTest(f"no OCR engine: {why}")
        cls.pdf = str(require_pdf("PL - 6.29.26.pdf"))
        from lib.plan_page import PlanPage
        from lib.plan_sheet import load_sheet
        cls.pg = PlanPage(cls.pdf, 14)
        cls.segs = load_sheet(cls.pg)["segs"]
        cls.plain, cls.ink, cls.words, cls.broken = [], [], [], None
        try:
            for region in (LEFT, RIGHT):
                cls.plain += T.sweep(cls.pg, cls.segs, region=region)
                cls.ink += T.sweep(cls.pg, cls.segs, ink_below=120, region=region)
            cls.words = T.sweep(cls.pg, cls.segs, region=WORDS)
        except (TypeError, ValueError) as e:    # a tree whose sweep cannot do this
            cls.broken = f"{type(e).__name__}: {e}"

    def setUp(self):
        self.assertEqual(self.pg.rotation, 270, "the fixture no longer guards a rotated page")
        self.assertIsNone(self.broken, "this tree cannot sweep the rotated page by region "
                                       "and ink")

    def _exact(self, reads):
        return _P().exact_label_reads(reads, TAGS)

    def test_the_slope_dn_crossed_rd1_labels_are_read(self):
        P = _P()
        got = [(r[0], r[1], r[2]) for r in self._exact(self.plain + self.ink)]
        rd1 = [(round(x), round(y)) for t, x, y in got if P.mend_hyphen(t).upper() == "RD-1"]
        for want in ((1010, 703), (1694, 707)):
            self.assertTrue(any(abs(x - want[0]) <= 10 and abs(y - want[1]) <= 6 for x, y in rd1),
                            f"RD-1 at {want} is not read; RD-1 reads {rd1}")
        # THE CONTROL: unfiltered, neither RD-1 is read - the arrows are the cause
        plain_rd1 = [r for r in self._exact(self.plain) if P.mend_hyphen(r[0]).upper() == "RD-1"]
        self.assertEqual(plain_rd1, [], "the plain sweep reads an RD-1 now: the fixture moved")

    def test_a_near_miss_is_not_a_roof_drain(self):
        """FD-1 (a floor drain) is one letter from RD-1; it is never taken."""
        self.assertEqual(self._exact([("FD-1", 1500.0, 624.0, (1490, 618, 1510, 630))]), [])

    def test_the_drains_are_placed_where_they_are_drawn(self):
        P = _P()
        assert "ink_below" in inspect.signature(T.run_takeoff).parameters, \
            "run_takeoff cannot keep the lighter pen out of the symbol in this tree"
        res = T.run_takeoff(None, self.pg, TAGS, {}, [], None,
                            reads=self._exact(self.plain + self.ink),
                            unplaced_reason="refused: sheet scope", ink_below=P.INK_BELOW)
        recs = res["records"]
        self.assertEqual(res["labels_by_tag"], {"RD-1": 2, "RD-2": 2})
        truth = _drain_centres(self.pg)
        self.assertEqual(len(truth), 4)
        hit = {}
        for r in recs:
            x, y = r["symbol_at"]
            near = [i for i, (tx, ty) in enumerate(truth) if abs(tx - x) <= 3 and abs(ty - y) <= 3]
            self.assertEqual(len(near), 1, f"{r['tag']} symbol at ({x:.1f}, {y:.1f}) is on no drain")
            hit[near[0]] = r["tag"]
        self.assertEqual(len(hit), 4, "two labels landed on one drain")
        # the upper drain of each pair is RD-1, the lower RD-2
        for i, (tx, ty) in enumerate(truth):
            pair = [t for t in truth if abs(t[0] - tx) < 40]
            self.assertEqual(hit[i], "RD-1" if ty == min(p[1] for p in pair) else "RD-2")

    def test_the_frame_holds_here_and_not_unrotated(self):
        ok, why = T.frame_check(self.pg, self.words, WORDS)
        self.assertTrue(ok, why)
        W = self.pg.height                    # /Rotate 270: display (x, y) is page (W - y, x)
        unrot = [(t, W - y, x, (W - b[3], b[0], W - b[1], b[2])) for t, x, y, b in self.words]
        self.assertFalse(T.frame_check(self.pg, unrot, WORDS)[0])

    def test_the_pass_writes_the_four_drains_and_the_gate_binds_them(self):
        """run_plan_only end to end on the real page - the sweeps limited to
        the two pairs of drains - then the gate on what it wrote."""
        P = _P()
        from lib.plan_glyph_pass import run_plan_only
        from lib.plan_page import PlanPage
        real = T.sweep

        def regional(pg, segs, ink_below=None, region=None):
            return [r for reg in (LEFT, RIGHT) for r in real(pg, segs, ink_below=ink_below, region=reg)]
        fam = P.families(_set_records())[FAM]
        pages = [P206,
                 dict(P206, page_id="p105", page_number=7, sheet_number="P-105.00",
                      sheet_title="ROOF FLOOR DOMESTIC WATER & GAS PLANS"),
                 dict(P206, page_id="p302", page_number=18, sheet_number="P-302.00",
                      sheet_title="STORM RISER DIAGRAM")]
        with patch("lib.plan_takeoff.sweep", regional):
            rows, note = run_plan_only(FAM, fam, pages, lambda p: PlanPage(self.pdf, p["page_number"]),
                                       {"inches": None})
        self.assertEqual(note["plans"], ["P-206.00"])
        self.assertEqual(sorted(r["label"] for r in rows), ["RD-1", "RD-1", "RD-2", "RD-2"])
        for r in rows:
            self.assertEqual(r["sheet_number"], "P-206.00")
            self.assertIsNone(r["unit"])
            self.assertEqual(r["payload"]["mech_count"], 4)
            self.assertEqual(r["payload"]["plan_only"]["label"],
                             "located on P-206.00; no schedule lists them")
        for r in rows:
            r["payload"]["track"] = "filed"
        recs = _records(rows=rows)
        self.assertTrue(_ok("RD-1: 2. RD-2: 2.", recs))
        self.assertFalse(_ok("There are 4 roof drains.", recs))
        self.assertIn("RD-1 2 + RD-2 2", S.render_glyph_evidence(recs))


class ARotatedPageThatDoesNotRegisterIsRefused(unittest.TestCase):

    def test_reads_off_their_own_words_refuse_the_sheet(self):
        """The whole-sheet sweep of a rotated page checks its frame: here
        the page's text layer prints PARAPET three times and no read finds
        any of them where it is printed."""
        from PIL import Image
        assert hasattr(T, "frame_check"), "no frame check in this tree"

        class Rotated:
            rotation, width, height = 270, 400.0, 300.0
            directed_words = [("PARAPET", 50.0, 50.0, "ltr"), ("PARAPET", 150.0, 50.0, "ltr"),
                              ("PARAPET", 250.0, 50.0, "ltr")]

            @staticmethod
            def render(clip, dpi):
                return Image.new("RGB", (40, 40), "white")
        with patch.object(T, "_read", lambda png: []):
            with self.assertRaises(ValueError):
                T.sweep(Rotated, [])
        # a sheet with no rotation is swept as it always was: never checked
        Rotated.rotation = 0
        with patch.object(T, "_read", lambda png: []):
            self.assertEqual(T.sweep(Rotated, []), [])


if __name__ == "__main__":
    unittest.main()
