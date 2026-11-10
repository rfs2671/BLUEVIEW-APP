"""EVERY PROGRESS SOURCE AS EVIDENCE, AT ITS OWN RUNG AND NO HIGHER.

The phrases are real lines of 588 Thomas S Boyland St's daily logs ("Blocking",
"Roof MEP", "Vapour barrier", "Outer bldg", "MEP rough-in", "Excavation",
"Stucco"). The DOB rows are the public NYC Open Data rows for BIN 3430621 /
588 (w9ak-ipjd job filings, rbx6-tga4 permits; the S4/S8/fence/demo permits
carry the lot's earlier BIN 3255362), in the two shapes dob_logs holds them:
as stored today, and with the fields PR #1008 adds (signoff_date,
work_on_floor, work_types). Only filing fields are kept. B01141294-S5
(plumbing) and -S7 (sprinkler) are "Permit Entire" with no sign-off; their
other fields are not in hand and are left out rather than made up.

The pour log, the punch item, the inspection reports, the superintendent's
log and the check-ins are written in the shapes their writers store
(lib/legal_render/schema.py concrete_operations, server._punch_set_status,
lib/inspection_reports.new_row + audit, lib/logbook/superintendent_log item
11, db.checkins); their contents are made up for the test.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import evidence as E  # noqa: E402
from lib import evidence_sources as S  # noqa: E402
from lib import inspection_reports as IR  # noqa: E402
from lib import work_nodes as N  # noqa: E402
from lib import work_state as W  # noqa: E402

PID = "proj588"
TODAY = date(2026, 11, 9)
START, END = date(2026, 10, 27), date(2026, 11, 9)
BIN_588 = "3430621"


def _act(work, where="floors 1-4", day=date(2026, 11, 5), company="Arkon Framers", trade="Carpenter", log="L1"):
    return {"date": day, "company": company, "trade": trade, "work": work, "where": where, "log_id": log,
            "amended": False}


def _pic(key, where="floor 3", work="Stucco", day="2026-11-05", description="Fresh stucco on the rear wall.",
         log="L1", tags=()):
    return {"short": key[:8], "photo_key": key, "where": where, "work": work, "date": day, "view": "building_side_or_rear",
            "quality": 8.0, "description": description, "tags": list(tags), "sub": "Stucco Pros", "log_id": log,
            "project_id": PID, "kind": "photo"}


# ── THE PUBLIC 588 DOB ROWS ────────────────────────────────────────────────

def _permit(number, work_type, status, bin_=BIN_588, **extra):
    return {"record_type": "permit", "raw_dob_id": f"{number}:{work_type}", "job_number": number, "work_type": work_type,
            "permit_status": status, "current_status": status, "bin": bin_, "project_id": PID,
            "detected_at": datetime(2026, 11, 9, tzinfo=timezone.utc), **extra}


def _filing(number, status, description, **extra):
    return {"record_type": "job_status", "raw_dob_id": number, "job_filing_number": number, "filing_status": status,
            "current_status": status, "job_description": description, "bin": BIN_588, "project_id": PID,
            "detected_at": datetime(2026, 11, 9, tzinfo=timezone.utc), **extra}


S4_FLOORS = "Floor Number(s)-1-SO-5912-B01141294-I1, Floor Number(s)-1-SO-9991-B01141294-I1"

#: As dob_logs holds them TODAY: no signoff_date, no work_on_floor, no work-type flags.
STORED_TODAY = [
    _permit("B01075600-I1", "Full Demolition", "Signed-off", bin_="3255362"),
    _permit("B01141294-S4", "Earth Work", "Signed-off", bin_="3255362"),
    _permit("B01141294-S4", "Foundation", "Signed-off", bin_="3255362"),
    _permit("B01141294-S8", "Support of Excavation", "Signed-off", bin_="3255362"),
    _permit("B01074863-I1", "Construction Fence", "Signed-off", bin_="3255362"),
    _filing("B01141294-I1", "Permit Entire", "PROPOSING NEW 4 STORY RESIDENTIAL BUILDING."),
    _filing("B01141294-S5", "Permit Entire", "PLUMBING"),
    _filing("B01141294-S7", "Permit Entire", "SPRINKLER"),
]

#: With PR #1008's fields, from the same public rows.
WITH_1008 = [
    _filing("B01075600-I1", "LOC Issued", "Full demolition to a two story house", signoff_date="2026-07-08T00:00:00.000",
            work_types="full demolition"),
    _filing("B01074863-I1", "LOC Issued", "PROPOSED 8FT CONSTRUCTION FENCE. NO CHANGE TO USE, EGRESS OR OCCUPANCY "
            "UNDER THIS APPLICATION.", signoff_date="2026-07-22T00:00:00.000", work_on_floor="Sidewalk",
            work_types="construction fence"),
    _filing("B01141294-S8", "LOC Issued", "SOE SPECIFICATIONS FILED IN CONJUNCTION WITH GC APPLICATION JOB #B01141294-I1",
            signoff_date="2026-10-29T00:00:00.000", work_on_floor=S4_FLOORS),
    _filing("B01141294-S4", "LOC Issued", "FOUNDATION AND EARTHWORK SPECIFICATIONS FILED IN CONJUNCTION WITH GC "
            "APPLICATION B01141294-I1", signoff_date="2026-11-05T00:00:00.000", work_on_floor=S4_FLOORS,
            work_types="foundation, earthwork"),
    _filing("B01141294-S5", "Permit Entire", "PLUMBING"),
    _filing("B01141294-S7", "Permit Entire", "SPRINKLER"),
]


def _dob(rows, bins=(BIN_588,)):
    return S.from_dob(rows, PID, bins=bins)


def _by(items, **want):
    return [i for i in items if all(i[k] == v for k, v in want.items())]


# ── THE KIND OF WORK ───────────────────────────────────────────────────────

class The588Phrases(unittest.TestCase):

    def test_each_real_phrase_reads_as_its_own_work(self):
        for phrase, want in (("Blocking", (["framing"], False)),
                             ("Roof MEP", (list(W.ROUGH_MEP), True)),
                             ("Vapour barrier", (["insulation"], False)),
                             ("MEP rough-in", (list(W.ROUGH_MEP), True)),
                             ("Excavation", (["excavation_soe"], False)),
                             ("Stucco", (["facade_envelope"], False))):
            with self.subTest(phrase=phrase):
                self.assertEqual(W.classify(phrase), want)

    def test_outer_bldg_is_a_place_not_a_kind_of_work(self):
        self.assertEqual(W.classify("Outer bldg"), ([], False))

    def test_roof_mep_is_on_the_roof_and_is_not_roofing(self):
        self.assertEqual(W.places_in("Roof MEP")["levels"], ["ROOF"])
        self.assertEqual(N.classify("Roof MEP"), ([], False))
        self.assertEqual(N.classify("Roofing"), (["roofing"], False))

    def test_whole_words_only(self):
        for phrase in ("Demonstrate", "Soeur", "Windowsill", "Slabbed", "Fenceless"):
            with self.subTest(phrase=phrase):
                self.assertEqual(N.classify(phrase), ([], False))

    def test_the_new_nodes_are_data_with_no_approved_sequence(self):
        self.assertTrue(all(status == N.TEMPLATE_UNAPPROVED for _a, _b, status in N.SEQUENCE))
        self.assertTrue({a for a, _b, _s in N.SEQUENCE} | {b for _a, b, _s in N.SEQUENCE} <= set(N.NODES))
        from app.scheduling.graph_v1 import build_graph_v1
        self.assertFalse(set(N.NODES) & {n.id for n in build_graph_v1().nodes}, "graph_v1 is not edited")
        self.assertFalse(N.is_progress("site_protection"))


# ── FILED DAILY LOGS: reported ─────────────────────────────────────────────

class DailyLogRows(unittest.TestCase):

    def test_a_row_naming_four_floors_is_shared(self):
        items, cov = S.from_daily_logs([_act("Blocking")], PID)
        self.assertEqual(len(items), 1)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["node"], i["shared"]), ("reported", "in_progress", "framing", True))
        self.assertEqual(i["levels"], ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"])
        self.assertEqual(cov["shared"], 1)

    def test_a_row_naming_one_floor_is_not_shared(self):
        i = S.from_daily_logs([_act("Blocking", where="floor 3")], PID)[0][0]
        self.assertEqual((i["levels"], i["shared"]), (["FLOOR_3"], False))

    def test_site_work_now_counts_and_a_place_does_not(self):
        items, cov = S.from_daily_logs([_act("Excavation", where=""), _act("Outer bldg", where="")], PID)
        self.assertEqual([i["node"] for i in items], ["excavation_soe"])
        self.assertEqual(cov["not_matched"], [("Outer bldg", 1)])

    def test_a_generic_row_says_so_and_never_says_done(self):
        items, _ = S.from_daily_logs([_act("MEP rough-in", where="floor 2")], PID)
        self.assertEqual({i["node"] for i in items}, set(W.ROUGH_MEP))
        self.assertTrue(all(i["claim"] == "in_progress" and "trade only" in i["note"] for i in items))


# ── PHOTOS: observed ───────────────────────────────────────────────────────

class Photos(unittest.TestCase):

    def test_a_photo_on_one_floor_observes_what_it_shows_there(self):
        items, cov = S.from_photos([_pic("k/a.jpg")], PID)
        self.assertEqual(len(items), 1)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["node"], i["levels"]), ("observed", "in_progress", "facade_envelope",
                                                                           ["FLOOR_3"]))
        self.assertEqual(cov["placed_on_one_level"], 1)

    def test_a_photo_filed_for_several_floors_has_no_level(self):
        i = S.from_photos([_pic("k/b.jpg", where="floors 1-4")], PID)[0][0]
        self.assertEqual(i["levels"], [])
        self.assertIn("none chosen", i["note"])

    def test_only_what_the_description_shows_never_the_crew_rows_words(self):
        items, cov = S.from_photos([_pic("k/c.jpg", work="Stucco", description="A dark interior corridor.")], PID)
        self.assertEqual(items, [])
        self.assertEqual(cov["shows_known_work"], 0)

    def test_a_photo_never_says_done(self):
        items, _ = S.from_photos([_pic("k/d.jpg", description="Finished stucco, scaffold struck.")], PID)
        self.assertTrue(items)
        self.assertTrue(all(i["claim"] != "done" for i in items))


# ── INSPECTION REPORTS: attested ───────────────────────────────────────────

def _report(result, status=IR.ATTESTED, validated=True, levels=("FLOOR_3",), gate=IR.PLUMBING_ROUGH, rid="r1",
            quote="plumbing rough passed on 3"):
    row = IR.new_row(project_id=PID, company_id="co", gate=gate, inspection="plumbing rough", levels=list(levels),
                     space=None, result=result, inspected_on="2026-11-04", inspector=None, reporter_user_id="u1",
                     reporter_name="Chris", source="text", quote=quote, message_id=rid,
                     created_at=datetime(2026, 11, 4, 15, tzinfo=timezone.utc), status=status, row_id=rid)
    if validated:
        row.update(IR.audit({"model_result": result, "result": result if status != IR.UNRESOLVED else None,
                             "read": [result] if result else [], "unclear": [], "agree": status != IR.UNRESOLVED,
                             "reason": None, "span": quote, "source": "statement"}))
    return row


class Inspections(unittest.TestCase):

    def test_a_validated_pass_is_attested_done(self):
        items, cov = S.from_inspections([_report("passed")], PID)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["node"], i["levels"], i["by"]),
                         ("attested", "done", IR.PLUMBING_ROUGH, ["FLOOR_3"], "Chris"))
        self.assertEqual(i["on"], date(2026, 11, 4))
        self.assertEqual(cov["validated"], 1)

    def test_a_failure_stays_a_failure(self):
        i = S.from_inspections([_report("failed", quote="plumbing rough failed on 3")], PID)[0][0]
        self.assertEqual(i["claim"], "failed")
        self.assertEqual(E.status([i]), "failed_attested")

    def test_an_unresolved_report_claims_nothing_and_is_counted(self):
        items, cov = S.from_inspections([_report(None, status=IR.UNRESOLVED, rid="u")], PID)
        self.assertEqual(items, [])
        self.assertEqual((cov["rows"], cov["unresolved"]), (1, 1))

    def test_a_result_never_read_back_from_the_words_claims_nothing(self):
        items, cov = S.from_inspections([_report("passed", validated=False)], PID)
        self.assertEqual(items, [])
        self.assertEqual(cov["not_validated"], 1)

    def test_a_report_on_several_floors_is_shared(self):
        i = S.from_inspections([_report("passed", levels=("FLOOR_2", "FLOOR_3"))], PID)[0][0]
        self.assertTrue(i["shared"])


# ── DOB SIGN-OFFS: verified ────────────────────────────────────────────────

class DobSignoffs(unittest.TestCase):

    def test_the_588_sign_offs_with_pr_1008s_fields(self):
        items, cov = _dob(WITH_1008)
        got = sorted((i["ref"], i["node"], i["on"]) for i in items)
        self.assertEqual(got, [
            ("B01074863-I1", "site_protection", date(2026, 7, 22)),
            ("B01075600-I1", "demolition", date(2026, 7, 8)),
            ("B01141294-S4", "excavation_soe", date(2026, 11, 5)),
            ("B01141294-S4", "foundation", date(2026, 11, 5)),
            ("B01141294-S8", "excavation_soe", date(2026, 10, 29)),
        ])
        self.assertTrue(all((i["kind"], i["claim"], i["source"]) == ("verified", "done", "dob_logs") for i in items))
        self.assertEqual(sorted(cov["not_signed_off"]), ["B01141294-S5", "B01141294-S7"])

    def test_a_filing_with_no_sign_off_claims_nothing(self):
        items, _ = _dob(WITH_1008)
        self.assertEqual(_by(items, ref="B01141294-S5") + _by(items, ref="B01141294-S7"), [])
        self.assertEqual(_by(items, node="rough_sprinkler") + _by(items, node="rough_dwv"), [])

    def test_a_sign_off_covers_the_filings_scope_and_says_so(self):
        items, _ = _dob(WITH_1008)
        demo = _by(items, ref="B01075600-I1")[0]
        self.assertEqual(demo["levels"], [])
        self.assertIn("covers the filing's scope, building-wide", demo["note"])
        soe = _by(items, ref="B01141294-S8")[0]
        self.assertEqual(soe["levels"], ["FLOOR_1"], "DOB's work_on_floor names Floor 1")
        self.assertIn("DOB lists the filing's work on Floor 1", soe["note"])
        self.assertIn("read from the filing's description", soe["note"])

    def test_a_construction_fence_is_site_protection_not_progress(self):
        fence = _by(_dob(WITH_1008)[0], ref="B01074863-I1")[0]
        self.assertEqual(fence["levels"], [])
        self.assertIn("not construction progress", fence["note"])
        self.assertIn("DOB lists: Sidewalk", fence["note"])

    def test_the_rows_as_stored_today_with_no_sign_off_date(self):
        items, cov = _dob(STORED_TODAY)
        self.assertEqual(sorted((i["ref"], i["node"]) for i in items), [
            ("B01074863-I1", "site_protection"), ("B01075600-I1", "demolition"), ("B01141294-S4", "excavation_soe"),
            ("B01141294-S4", "foundation"), ("B01141294-S8", "excavation_soe")])
        self.assertTrue(all(i["on"] is None and "sign-off date is not on the stored record" in i["note"] for i in items))
        self.assertEqual(sorted(cov["not_signed_off"]), ["B01141294-I1", "B01141294-S5", "B01141294-S7"])

    def test_both_shapes_together_are_one_item_per_filing_and_work(self):
        items, _ = _dob(STORED_TODAY + WITH_1008)
        self.assertEqual(len(items), 5)
        self.assertEqual(_by(items, ref="B01141294-S4", node="foundation")[0]["on"], date(2026, 11, 5))

    def test_words_that_are_not_a_sign_off(self):
        for status in ("QA Review for LOC", "NOT SIGNED OFF", "Permit Entire", "Permit Issued", "Approved"):
            with self.subTest(status=status):
                self.assertFalse(S.signoff_words(status))
        for status in ("LOC Issued", "Signed-off", "Full Demolition Signed-off", "Job is complete", "Complete"):
            with self.subTest(status=status):
                self.assertTrue(S.signoff_words(status))

    def test_a_permits_newest_row_is_its_state(self):
        # A permit is a new dob_logs row per change: Permit Issued in August, Signed-off later.
        signed = _permit("B01141294-S8", "Support of Excavation", "Signed-off")
        issued = {**signed, "permit_status": "Permit Issued", "current_status": "Permit Issued",
                  "detected_at": datetime(2026, 8, 4, tzinfo=timezone.utc)}
        self.assertEqual([i["node"] for i in _dob([signed, issued])[0]], ["excavation_soe"])
        self.assertEqual(_dob([{**signed, "detected_at": datetime(2026, 8, 4, tzinfo=timezone.utc)},
                               {**issued, "detected_at": datetime(2026, 11, 9, tzinfo=timezone.utc)}])[0], [])

    def test_another_buildings_filing_is_left_out(self):
        items, cov = _dob([_permit("B09999999-I1", "Foundation", "Signed-off", bin_="3000001")])
        self.assertEqual(items, [])
        self.assertEqual(cov["other_building"], 1)

    def test_the_work_type_wins_over_the_description(self):
        # Real: B01141294-S6 is a Mechanical Systems permit described as "PLUMBING SPECIFICATIONS".
        row = _permit("B01141294-S6", "Mechanical Systems", "Signed-off",
                      job_description="PLUMBING SPECIFICATIONS FILED IN CONJUNCTION WITH GC APPLICATION B01141294-I1")
        self.assertEqual([i["node"] for i in _dob([row])[0]], ["rough_duct"])

    def test_dob_names_no_level_it_does_not_list(self):
        self.assertEqual(S.dob_levels("Floor Number(s)-1-SO-5912-B01141294-I1, Mezzanine-4-SO-3947-, Roof-SO-4975"),
                         ["FLOOR_1", "MEZZANINE", "ROOF"])
        self.assertEqual(S.dob_levels("Sidewalk"), [])
        self.assertEqual(S.dob_nodes("NON-STRUCTURAL"), [])
        self.assertEqual(S.dob_nodes("protection / mechanical methods"), [])


# ── POUR LOGS: confirmed ───────────────────────────────────────────────────

def _pour(location, status="submitted", day="2026-11-03", slumps=(), lid="pour1"):
    return {"_id": lid, "log_type": "concrete_operations", "project_id": PID, "date": day, "status": status,
            "is_locked": status == "submitted", "cp_name": "Ana Sotelo",
            "data": {"pour_location": location, "concrete_supplier": "X", "slump_tests": list(slumps)}}


class Pours(unittest.TestCase):

    def test_a_slab_pour_at_a_level_is_confirmed_done_there(self):
        items, _ = S.from_pours([_pour("3rd floor slab")], PID)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["node"], i["levels"], i["by"]),
                         ("confirmed", "done", "superstructure", ["FLOOR_3"], "Ana Sotelo"))
        self.assertEqual(E.status(items), "done_confirmed")

    def test_a_deck_pour_counts_as_a_slab(self):
        self.assertEqual(S.pour_claim("Roof deck"), ("superstructure", "done", ["ROOF"]))

    def test_a_topping_or_partial_pour_is_in_progress(self):
        for loc in ("Topping slab 4th floor", "2nd floor slab east half", "Partial pour floor 2 slab"):
            with self.subTest(loc=loc):
                self.assertEqual(S.pour_claim(loc)[1], "in_progress")

    def test_a_location_with_no_level_gives_no_level_and_no_done(self):
        items, cov = S.from_pours([_pour("Slab")], PID)
        self.assertEqual((items[0]["levels"], items[0]["claim"]), ([], "in_progress"))
        self.assertEqual(cov["no_level"], 1)

    def test_a_footing_pour_is_foundation_in_progress(self):
        self.assertEqual(S.pour_claim("Footings")[:2], ("foundation", "in_progress"))

    def test_an_unfiled_pour_log_claims_nothing(self):
        items, cov = S.from_pours([_pour("3rd floor slab", status="draft")], PID)
        self.assertEqual(items, [])
        self.assertEqual(cov["not_filed"], 1)

    def test_a_failed_slump_is_said(self):
        i = S.from_pours([_pour("3rd floor slab", slumps=[{"time": "9:00", "value": "7", "pass": False}])], PID)[0][0]
        self.assertIn("1 failed slump test", i["note"])


# ── CLOSED PUNCH ITEMS: confirmed ──────────────────────────────────────────

def _punch(status="closed", floor="4", area="Apt 4D", closed_by="u-super"):
    return {"_id": f"{PID}:P-588-23", "pid": "P-588-23", "project_id": PID, "text": "Tile chipped", "floor": floor,
            "area": area, "trade": "tile", "status": status, "closed_by": closed_by if status == "closed" else None,
            "closed_at": datetime(2026, 11, 6, 14, tzinfo=timezone.utc) if status == "closed" else None,
            "assignee": {"name": "Joe", "company": "Tile Co"}}


class Punch(unittest.TestCase):

    def test_a_closed_item_is_done_for_that_item_only(self):
        items, _ = S.from_punch([_punch()], PID)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["node"], i["levels"], i["space"]),
                         ("confirmed", "done", None, ["FLOOR_4"], "4D"))
        self.assertIn("this item only, not the package of work", i["note"])
        self.assertEqual(E.about(items, node="finishes"), [], "never the package")

    def test_an_item_waiting_to_be_checked_claims_nothing(self):
        self.assertEqual(S.from_punch([_punch(status="ready_to_check")], PID)[0], [])

    def test_an_item_with_no_floor_has_no_level(self):
        self.assertEqual(S.from_punch([_punch(floor="?", area="?")], PID)[0][0]["levels"], [])


# ── THE SUPERINTENDENT'S LOG: attested ─────────────────────────────────────

class Superintendent(unittest.TestCase):

    def test_his_daily_inspection_is_kept_in_his_words_as_presence(self):
        lg = {"_id": "cs1", "log_type": "site_superintendent_log", "date": "2026-11-04", "status": "submitted",
              "is_locked": True, "cp_name": "Marcus Hale",
              "data": {"daily_inspection": {"location": "3rd floor and roof", "result": "guardrails ok"}}}
        items, _ = S.from_superintendent([lg], PID)
        i = items[0]
        self.assertEqual((i["kind"], i["claim"], i["by"], i["node"]), ("attested", "present", "Marcus Hale", None))
        self.assertEqual(i["quote"], "3rd floor and roof - guardrails ok")
        self.assertEqual((i["levels"], i["shared"]), (["FLOOR_3", "ROOF"], True))


# ── CHECK-INS: present ─────────────────────────────────────────────────────

class Checkins(unittest.TestCase):

    def test_one_item_per_company_per_day_and_never_progress(self):
        at = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        rows = [{"worker_id": "w1", "worker_company": "Arkon Framers", "check_in_time": at},
                {"worker_id": "w2", "worker_company": "Arkon Framers", "check_in_time": at + timedelta(hours=1)},
                {"worker_id": "w3", "worker_company": "Power Direct", "check_in_time": at}]
        items, _ = S.from_checkins(rows, PID)
        self.assertEqual(sorted((i["sub"], i["claim"], i["node"]) for i in items),
                         [("Arkon Framers", "present", None), ("Power Direct", "present", None)])
        self.assertIn("2 worker(s)", _by(items, sub="Arkon Framers")[0]["note"])


# ── THE SCHEDULE FILE: reported, by the file ───────────────────────────────

class ScheduleFile(unittest.TestCase):

    def test_the_files_actuals_and_its_stated_percent_only(self):
        sched = {"activities": [
            {"id": "A1", "name": "Excavation", "kind": "task", "actual_start": "2026-08-01", "actual_finish": "2026-09-15"},
            {"id": "A2", "name": "Framing Floor 3", "kind": "task", "actual_start": "2026-10-20", "percent_complete": 40},
            {"id": "A3", "name": "Drywall Floor 3", "kind": "task", "baseline_finish": "2026-12-01"}]}
        items, cov = S.from_schedule(sched, PID)
        self.assertEqual(sorted((i["ref"], i["claim"], i["node"]) for i in items),
                         [("A1", "done", "excavation_soe"), ("A2", "started", "framing")])
        a2 = _by(items, ref="A2")[0]
        self.assertEqual((a2["source"], a2["kind"], a2["stated_percent"], a2["levels"]),
                         ("schedule_file", "reported", 40.0, ["FLOOR_3"]))
        self.assertIn("the schedule file states 40%", a2["note"])
        self.assertEqual(cov["with_actuals"], 2)


# ── ALL TOGETHER ───────────────────────────────────────────────────────────

def _everything(**over):
    kw = dict(start=START, end=END,
              activities=[_act("Blocking"), _act("Excavation", where="", day=date(2026, 10, 1))],
              photo_index=[_pic("k/a.jpg")], inspections=[_report("passed"), _report(None, status=IR.UNRESOLVED, rid="u")],
              dob_rows=WITH_1008, bins=(BIN_588,), logbooks=[_pour("3rd floor slab")], punch_items=[_punch()],
              checkins=[{"worker_id": "w1", "worker_company": "Arkon Framers",
                         "check_in_time": datetime(2026, 11, 5, 12, tzinfo=timezone.utc)}])
    kw.update(over)
    return S.collect(PID, **kw)


class Collect(unittest.TestCase):

    def test_the_fixture_counts_by_kind(self):
        items, cov = _everything()
        self.assertEqual(cov["by_kind"], {"reported": 2, "observed": 1, "attested": 1, "verified": 5, "confirmed": 2})
        self.assertEqual(cov["by_source"]["dob_logs"], 5)

    def test_a_crew_row_before_the_window_is_left_out_and_a_sign_off_is_not(self):
        items, cov = _everything()
        self.assertEqual(_by(items, source="daily_log", node="excavation_soe"), [])
        self.assertEqual(cov["daily_log"]["outside_window"], 1)
        self.assertEqual(len(_by(items, source="dob_logs", ref="B01075600-I1")), 1, "July sign-off still holds")

    def test_nothing_after_the_window(self):
        items, _ = _everything(end=date(2026, 11, 1))
        self.assertEqual(_by(items, ref="B01141294-S4"), [], "signed off Nov 5")

    def test_an_unreadable_source_is_named(self):
        _items, cov = _everything(unreadable=["punch_items"])
        self.assertEqual(cov["unreadable"], ["punch_items"])

    def test_the_shape_is_evidence_items(self):
        items, _ = _everything()
        keys = set(E.item("reported", "present", source="x", ref="r", project_id=PID))
        self.assertTrue(all(set(i) == keys for i in items))
        self.assertTrue(all(i["stated_percent"] is None and i["kind"] != "estimate" for i in items))


# ── THE SERVER LOADER ──────────────────────────────────────────────────────

class TheLoader(unittest.TestCase):

    def _run(self, db):
        import server
        project = {"_id": PID, "company_id": "co", "nyc_bin": BIN_588}
        src = {"logbooks": [{"_id": "L1", "date": "2026-11-05", "status": "submitted", "is_locked": True,
                             "data": {"activities": [{"company": "Arkon Framers", "work_description": "Blocking",
                                                      "work_locations": "floor 3", "num_workers": 4}]}}],
               "checkins": [], "dob_rows": WITH_1008, "project_bins": [BIN_588], "schedule": None}

        async def rows(*a, **k):
            return src

        async def place(pid):
            return {}, {}
        with patch.object(server, "db", db), patch.object(server, "_report_rows", rows), \
                patch.object(server, "_photo_place_context", place):
            return asyncio.run(server._progress_evidence(project, "co", START, END))

    def test_it_reads_every_source_and_hands_back_items_and_coverage(self):
        from tests._fake_mongo import FakeDb
        import server
        db = FakeDb()
        db[server.PHOTO_INDEX].rows.append(_pic("k/a.jpg"))
        db[server.INSPECTION_REPORTS].rows.append({**_report("passed"), "company_id": "co"})
        db.logbooks.rows += [_pour("3rd floor slab"), _pour("4th floor slab", status="draft", lid="pour2")]
        db.punch_items.rows.append(_punch())
        items, cov = self._run(db)
        self.assertEqual(cov["by_source"], {"daily_log": 1, "photo_index": 1, "inspection_reports": 1, "dob_logs": 5,
                                            "concrete_operations": 1, "punch_items": 1})
        self.assertEqual(cov["unreadable"], [])
        self.assertEqual(_by(items, source="daily_log")[0]["levels"], ["FLOOR_3"])

    def test_an_amended_pour_log_counts_once_as_amended(self):
        from tests._fake_mongo import FakeDb
        import server
        db = FakeDb()
        original = _pour("3rd floor slab", lid="pour1")
        amended = {**_pour("3rd floor slab east half", lid="pour1a"), "is_amendment": True, "parent_logbook_id": "pour1",
                   "created_at": datetime(2026, 11, 4, tzinfo=timezone.utc)}
        db.logbooks.rows += [original, amended]
        items, _ = self._run(db)
        pours = _by(items, source="concrete_operations")
        self.assertEqual([(p["ref"], p["claim"]) for p in pours], [("pour1a", "in_progress")])

    def test_a_source_that_cannot_be_read_is_unknown_not_empty(self):
        from tests._fake_mongo import FakeDb
        import server
        db = FakeDb()

        def boom(*a, **k):
            raise RuntimeError("down")
        db.punch_items.find = boom
        _items, cov = self._run(db)
        self.assertEqual(cov["unreadable"], ["punch_items"])


if __name__ == "__main__":
    unittest.main()
