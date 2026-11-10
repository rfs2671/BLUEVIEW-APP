"""lib/intel_records.py: records-lane rows -> evidence items.

EVERY ROW HERE IS SYNTHETIC, written in the records lane's shape (type, date,
company, location_text, description, fields). Companies are made up.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import construction_inference as CI  # noqa: E402
from lib import intel_records as R  # noqa: E402
from tests.test_construction_inference import MODEL  # noqa: E402

TA = [{"id": "T1", "type": "project_meta", "company": "Pipe Co", "fields": {"kind": "roster_row_trade_assignment"},
       "quote": 'TA {"trade": "Plumber", "company": "Pipe Co"}'},
      {"id": "T2", "type": "project_meta", "company": "Mud Co", "fields": {"kind": "roster_row_trade_assignment"},
       "quote": 'TA {"trade": "Concrete / Cement", "company": "Mud Co"}'}]


def row(i, company, desc, loc, day="2026-02-02", **f):
    return {"id": i, "type": "daily_log_activity", "origin": "tool_output_from_production_probe", "date": day,
            "company": company, "location_text": loc, "description": desc, "crew_count": 3, "fields": f}


def items(rows):
    return R.items_from_records(TA + rows, MODEL, project_id="synthetic")[0]


class Dates(unittest.TestCase):

    def test_period_dates(self):
        self.assertEqual(R.period_dates("Oct 27–Nov 5"), (date(2026, 10, 27), date(2026, 11, 5)))
        self.assertEqual(R.period_dates("Oct 29–30"), (date(2026, 10, 29), date(2026, 10, 30)))
        self.assertEqual(R.period_dates("Nov 4"), (date(2026, 11, 4), date(2026, 11, 4)))
        self.assertEqual(R.period_dates("sometime"), (None, None))


class CrewRows(unittest.TestCase):

    def test_a_plumbers_mep_rough_in_is_plumbing(self):
        [i] = items([row("A", "Pipe Co", "MEP rough-in", "1st Floor, 2nd Floor")])
        self.assertEqual((i["kind"], i["node"], i["levels"], i["shared"]),
                         ("reported", "rough_plumbing", ["FLOOR_1", "FLOOR_2"], True))
        self.assertEqual(CI.filed_location(i), "1st Floor, 2nd Floor")

    def test_underground_is_below_the_ground_slab(self):
        [i] = items([row("B", "Pipe Co", "Underground plumbing", "Underground")])
        self.assertEqual((i["node"], i["levels"], i["space"]), ("underground_plumbing", ["FLOOR_1"], "below the ground slab"))

    def test_a_concrete_crews_vapour_barrier_is_the_slab(self):
        got = {i["node"] for i in items([row("C", "Mud Co", "Vapour barrier, slab on grade, mesh", "1st floor")])}
        self.assertEqual(got, {CI.SLAB_ON_GRADE})

    def test_a_phrase_naming_the_roof_is_placed_there_and_the_filing_kept(self):
        [i] = items([row("D", "Pipe Co", "Roof MEP", "floors 1–2")])
        self.assertEqual(i["levels"], ["ROOF"])
        self.assertEqual(CI.filed_location(i), "floors 1–2")

    def test_the_foundation_is_building_wide_not_a_storey(self):
        got = items([row("F", "Mud Co", "Footings", "Foundation footings")])
        self.assertTrue(got)
        self.assertTrue(all(i["levels"] == [] and i["candidates"] == [] and i["space"] == "foundation" for i in got))

    def test_a_floor_the_model_lacks_is_a_candidate_not_a_place(self):
        [i] = items([row("E", "Pipe Co", "Plumbing", "floor 7")])
        self.assertEqual((i["levels"], i["candidates"]), ([], ["FLOOR_7"]))

    def test_a_period_row_is_its_first_and_last_printed_days(self):
        r = {"id": "P", "type": "daily_log_activity", "company": "Pipe Co", "location_text": "floors 1–2",
             "description": "Domestic water rough", "fields": {"kind": "period_work_item", "dates": "Oct 27–Nov 5"}}
        got = sorted((i["on"], i["ref"]) for i in items([r]))
        self.assertEqual(got, [(date(2026, 10, 27), "P:first:rough_water"), (date(2026, 11, 5), "P:last:rough_water")])

    def test_a_photo_tile_is_observed(self):
        r = {"id": "T", "type": "photo", "date": "2026-02-03", "company": "Pipe Co", "location_text": "floor 2",
             "description": "Plumbing installed", "fields": {"kind": "report_visual_progress_tile"}}
        [i] = items([r])
        self.assertEqual((i["kind"], i["source"], i["levels"]), ("observed", "photo_index", ["FLOOR_2"]))

    def test_headcounts(self):
        g = {"id": "G", "type": "checkin_aggregate", "date": "2026-02-02", "fields": {"by_company": {"Pipe Co": 2}}}
        h = R.headcounts([row("A", "Pipe Co", "Plumbing", "1st floor"), g])
        self.assertEqual(h, [{"date": date(2026, 2, 2), "sub": "Pipe Co", "log_count": 3, "gate_count": 2,
                              "refs": ["A", "G"]}])


class BlindLeakage(unittest.TestCase):
    CUT = date(2026, 3, 1)

    def test_what_a_blind_run_may_not_see(self):
        late = row("L", "Pipe Co", "Plumbing", "1st floor", day="2026-03-02")
        captured_late = dict(row("C", "Pipe Co", "Plumbing", "1st floor"),
                             provenance={"transcript_timestamp": "2026-03-05T10:00:00Z"})
        result = dict(row("S", "Pipe Co", "Plumbing rough inspection passed", "1st floor"))
        bot = {"id": "B", "type": "whatsapp", "date": "2026-02-01", "fields": {"path": "job_agent"}}
        op = {"id": "O", "type": "inspection_statement", "origin": "operator_statement", "date": "2026-02-01"}
        gen = dict(row("G", "Pipe Co", "Plumbing", "1st floor"), provenance={"source_file": "x/progress_report_real.json"})
        ok = row("K", "Pipe Co", "Plumbing", "1st floor")
        kept, excluded = R.blind_records([late, captured_late, result, bot, op, gen, ok], self.CUT)
        self.assertEqual(sorted(r["id"] for r in kept), ["G", "K"])
        self.assertEqual({e["id"] for e in excluded}, {"L", "C", "S", "B", "O"})
        kept, _ = R.blind_records([gen, ok], self.CUT, strictness="strictest")
        self.assertEqual([r["id"] for r in kept], ["K"])

    def test_an_audit_flag_excludes(self):
        ok = row("K", "Pipe Co", "Plumbing", "1st floor")
        kept, ex = R.blind_records([ok], self.CUT, audit={"K": {"leaks_inspection_result": True}})
        self.assertEqual((kept, ex[0]["reasons"]), ([], ["audit leak flag: True"]))


class TheAudit(unittest.TestCase):
    """Synthetic audit_flags rows in the audit lane's shape (rec_id, dup_of,
    derived_class, is_original, leaks_inspection_result)."""

    def flags(self):
        return {"O": {"rec_id": "O", "is_original": True, "dup_of": None, "derived_class": "original_filed_row"},
                "D": {"rec_id": "D", "is_original": False, "dup_of": "O", "derived_class": "generated_report"},
                "G": {"rec_id": "G", "is_original": False, "dup_of": None, "derived_class": "generated_report"},
                "S": {"rec_id": "S", "is_original": False, "dup_of": None, "derived_class": "synthetic"}}

    def test_only_originals_are_evidence_and_derived_rows_are_summary_only(self):
        o = row("O", "Pipe Co", "MEP rough-in", "1st floor")
        d = dict(row("D", "Pipe Co", "MEP rough-in", "1st floor"))
        o_readme = dict(o, duplicate_of="D")            # the README kept the derived copy: ignored under the audit
        g = row("G", "Pipe Co", "Domestic water rough", "floors 1–2")
        s = row("S", "Pipe Co", "Plumbing", "2nd floor")
        got, meta = R.items_from_records(TA + [o_readme, d, g, s], MODEL, project_id="synthetic", audit=self.flags())
        self.assertEqual([i["ref"] for i in got], ["O:rough_plumbing"])
        self.assertEqual([x["ref"] for x in meta["summary_context"]], ["G:rough_water"])
        self.assertEqual(meta["summary_context"][0]["derived_class"], "generated_report")
        self.assertEqual(R.audit_class(self.flags()["S"]), "synthetic")

    def test_a_borderline_leak_flag_is_excluded_from_a_blind_run(self):
        k = row("K", "Pipe Co", "Underground plumbing inspection", "1st floor")
        _kept, ex = R.blind_records([k], date(2026, 3, 1),
                                    audit={"K": {"leaks_inspection_result": "borderline: filed log row mentions a DOB"}})
        self.assertEqual(ex[0]["reasons"], ["audit leak flag: borderline: filed log row mentions a DOB"])


class PublicRecords(unittest.TestCase):

    def test_a_signoff_is_verified_and_dob_now_rows_are_not_read_here(self):
        rows = [{"date": "2026-01-05", "kind": "signoff", "work_type": "full_demolition", "job_or_permit_no": "X-I1",
                 "status_text_verbatim": "LOC Issued", "source_dataset": "w9ak-ipjd"},
                {"date": "2026-01-06", "kind": "signoff", "work_type": "plumbing", "job_or_permit_no": "Y",
                 "source_dataset": "DOB NOW: Inspections (Accela)"}]
        [i] = R.items_from_public(rows)
        self.assertEqual((i["kind"], i["claim"], i["node"]), ("verified", "done", "demolition"))
        self.assertIn("paperwork date", i["note"])

    def test_dob_now_floor_table(self):
        doc = {"plumbing_permit_B01141294-S5-PL": {
            "floor_results_table_UNDATED": {"001": {"WS UND GRND": "CERTIFIED", "WS ROUGH": "PASSED"},
                                            "MEZ": {"GAS ROUGH": "PASSED"}},
            "completed_inspections": [{"id": "7681636", "resulted": "2026-01-02T08:30"},
                                      {"id": "7755632", "resulted": "2026-02-05T10:20"}]}}
        got = sorted((i["kind"], i["node"], tuple(i["levels"]), i["on"]) for i in R.items_from_dob_now(doc))
        self.assertEqual(got, [("confirmed", CI.UNDERGROUND_GATE, ("FLOOR_1",), date(2026, 1, 2)),
                               ("verified", "gate_plumbing_rough", ("FLOOR_1",), date(2026, 2, 5)),
                               ("verified", "gate_plumbing_rough", ("MEZZANINE",), date(2026, 2, 5))])


if __name__ == "__main__":
    unittest.main()
