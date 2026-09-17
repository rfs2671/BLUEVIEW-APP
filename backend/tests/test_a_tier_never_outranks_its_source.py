"""A number a model saw in a picture wore the badge of a printed cell.

Found in the live corpus on 2026-09-17, after the re-index that was supposed
to be the last one before the eval. M-200.00 carried `PTAC-1 count 21` TWICE:

    [ocr_grid_cell ] element  PTAC-1 - count 21 - ROOMS PTAC UNITS SCHEDULE
    [schedule_cell ] element  PTAC-1 - count 21 - ROOMS PTAC UNITS SCHEDULE

The second came from a schedule the VISION MODEL read off the image.
`elements_from_evidence` mapped `ocr_grid` to `ocr_schedule_qty` and
EVERYTHING ELSE to `schedule_qty`, and "everything else" includes vision. So
the weakest evidence in the system arrived at `schedule_cell`, the strongest
tier there is, and `best_per_attribute` would have preferred it over the OCR'd
cell that was actually read from the grid.

The number was right. That is not the point — it is the same machinery that
produced `41`, and nothing downstream could tell the two apart.

THE RULE: A TIER MAY NEVER OUTRANK ITS SOURCE.

A source may sit lower than its floor — a loose text-layer line is
`text_layer`, not `tag_legend` — but never higher. `emit` enforces it, rather
than trusting every call site, because the call site is what got it wrong.
"""

import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_extract as pe  # noqa: E402
from lib import plan_records as pr  # noqa: E402
from lib import plan_text as pt  # noqa: E402

PAGE = {"sheet_number": "M-200.00", "page_number": 9}
PTAC = {"name": "ROOMS PTAC UNITS SCHEDULE", "columns": ["UNIT NO.", "QTY"],
        "rows": [["PTAC-1", "21"]], "bbox": [63, 53, 958, 211]}


def records_for(schedule_source):
    sched = dict(PTAC)
    if schedule_source:
        sched["source"] = schedule_source
    fields = dict(pe.EMPTY_FIELDS, sheet_number="M-200.00", schedules=[sched])
    fields["elements"] = pt.elements_from_evidence([], [sched], [])
    return pr.build_records(fields, page=PAGE, raw_text="")


def element_of(schedule_source):
    return [r for r in records_for(schedule_source)
            if r["record_type"] == "element"][0]


class TheDefectItself(unittest.TestCase):

    def test_a_quantity_from_a_vision_read_schedule_is_not_a_schedule_cell(self):
        r = element_of("vision")
        self.assertEqual(r["payload"]["count_basis"], pe.TIER_VISION)
        self.assertEqual(r["tier"], pe.TIER_VISION)
        self.assertEqual(r["source"], "vision")
        self.assertNotEqual(r["tier"], pe.TIER_SCHEDULE_CELL)

    def test_the_ocr_copy_keeps_its_own_tier(self):
        r = element_of("ocr_grid")
        self.assertEqual(r["payload"]["count_basis"], "ocr_schedule_qty")
        self.assertEqual(r["tier"], pe.TIER_OCR_GRID)
        self.assertEqual(r["source"], "ocr_grid")

    def test_a_real_text_layer_schedule_is_still_the_strongest(self):
        r = element_of(None)
        self.assertEqual(r["payload"]["count_basis"], "schedule_qty")
        self.assertEqual(r["tier"], pe.TIER_SCHEDULE_CELL)
        self.assertEqual(r["source"], "table_finder")

    def test_ptac_1_survives_once_when_both_readings_are_present(self):
        # Both schedules on one page, as M-200.00 actually had them. Two
        # records exist — nothing is destroyed — but retrieval keeps the
        # OCR'd one, because it now outranks the vision copy.
        from lib import plan_search as ps
        sheets = [dict(PTAC, source="vision"), dict(PTAC, source="ocr_grid")]
        fields = dict(pe.EMPTY_FIELDS, sheet_number="M-200.00", schedules=sheets)
        fields["elements"] = pt.elements_from_evidence([], sheets, [])
        recs = [r for r in pr.build_records(fields, page=PAGE, raw_text="")
                if r["record_type"] == "element"]
        self.assertEqual(len(recs), 2)
        kept = ps.best_per_attribute(ps.rank(recs, ps.search_terms("ptac")))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["tier"], pe.TIER_OCR_GRID)


class ATierNeverOutranksItsSource(unittest.TestCase):

    def test_every_source_declares_the_best_tier_it_may_claim(self):
        for source, floor in pr.SOURCE_FLOOR.items():
            with self.subTest(source=source):
                self.assertIn(floor, pr.TIER_ORDER)

    def test_vision_is_pinned_to_the_bottom(self):
        # Nothing read off an image may outrank anything a person could check
        # against the page.
        self.assertEqual(pr.SOURCE_FLOOR["vision"], pe.TIER_VISION)
        self.assertEqual(pr.tier_rank(pe.TIER_VISION), len(pr.TIER_ORDER) - 1)

    def test_a_tier_above_its_source_is_pulled_down(self):
        for source, claimed in (("vision", pe.TIER_SCHEDULE_CELL),
                                ("vision", pe.TIER_TEXT_LAYER),
                                ("text_layer", pe.TIER_OCR_GRID),
                                ("ocr_grid", pe.TIER_SCHEDULE_CELL),
                                ("glyph_match", pe.TIER_SCHEDULE_CELL)):
            with self.subTest(source=source, claimed=claimed):
                got = pr.tier_for_source(claimed, source)
                self.assertEqual(got, pr.SOURCE_FLOOR[source])

    def test_a_tier_below_its_source_is_left_alone(self):
        # A loose line IS text_layer, not tag_legend. The rule is a ceiling.
        for source, claimed in (("text_layer", pe.TIER_TEXT_LAYER),
                                ("text_layer", pe.TIER_VISION),
                                ("table_finder", pe.TIER_TEXT_LAYER)):
            with self.subTest(source=source, claimed=claimed):
                self.assertEqual(pr.tier_for_source(claimed, source), claimed)

    def test_the_writer_enforces_it_rather_than_the_call_sites(self):
        src = inspect.getsource(pr.build_records)
        self.assertIn("tier = tier_for_source(tier, source)", src)

    def test_every_basis_maps_to_a_source_and_a_tier_that_agree(self):
        for basis, tier in pr.BASIS_TIERS.items():
            with self.subTest(basis=basis):
                source = pr.BASIS_SOURCES[basis]
                self.assertEqual(pr.tier_for_source(tier, source), tier,
                                 f"{basis} claims {tier} from {source}")

    def test_no_record_this_pipeline_writes_outranks_its_source(self):
        # The sweep, over every record type a page can yield at once.
        fields = dict(
            pe.EMPTY_FIELDS, sheet_number="M-200.00",
            schedules=[dict(PTAC), dict(PTAC, source="ocr_grid"),
                       dict(PTAC, source="vision")],
            notes=[{"number": "1", "text": "PROVIDE WALL SLEEVE"}],
            legend=[{"symbol": "AD", "meaning": "AREA DRAIN",
                     "tier": pe.TIER_TAG_LEGEND},
                    {"symbol": "PTAC-1", "meaning": "",
                     "label": "PACKAGE TERMINAL AIR CONDITIONER",
                     "tier": pe.TIER_VISION}],
            tag_counts=[{"tag": "AD", "count": 2}],
            callouts=[{"text": "SEE", "detail_number": "2",
                       "target_sheet": "A-301.00"}],
            dimensions=['3 1/2"'],
            text_blocks=[{"text": "GENERAL NOTES", "kind": "note"}],
        )
        fields["elements"] = pt.elements_from_evidence(
            fields["legend"], fields["schedules"], fields["tag_counts"])
        fields["elements"].append(
            {"name": "FLOOR/AREA/ROOF DRAIN", "tag": "", "count_if_stated": 2,
             "count_basis": "glyph_match", "glyph_scope": "family",
             "location_hint": "symbols matching the legend mark"})
        recs = pr.build_records(fields, page=PAGE, raw_text="AD = AREA DRAIN")
        self.assertGreater(len(recs), 10)
        for r in recs:
            with self.subTest(type=r["record_type"], source=r["source"]):
                floor = pr.SOURCE_FLOOR.get(r["source"])
                self.assertIsNotNone(
                    floor, f"source {r['source']!r} declares no floor")
                self.assertGreaterEqual(
                    pr.tier_rank(r["tier"]), pr.tier_rank(floor),
                    f"{r['record_type']} claims {r['tier']} from {r['source']}")

    def test_nothing_sourced_from_vision_is_ever_marked_verified(self):
        fields = dict(pe.EMPTY_FIELDS, sheet_number="M-200.00",
                      schedules=[dict(PTAC, source="vision")])
        fields["elements"] = pt.elements_from_evidence([], fields["schedules"], [])
        for r in pr.build_records(fields, page=PAGE, raw_text=""):
            if r["source"] == "vision":
                with self.subTest(type=r["record_type"]):
                    self.assertFalse(r["verified"])
                    self.assertIsNone(r["quote_span"])


if __name__ == "__main__":
    unittest.main()
