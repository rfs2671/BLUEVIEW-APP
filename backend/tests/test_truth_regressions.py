"""Adversarial repros. Each test ASSERTS THE HONEST BEHAVIOUR, so a FAIL = a confirmed defect.

Copied from an independent reviewer's reproductions, every case kept. Adapted:
the import path, and the fixture's level token "floor_3" is the real token
"FLOOR_3" (the one W.level_asked and the schedule reader produce; with the
lowercase token the inspection-activity case could never match any level).

CONTROL: against origin/feat/progress-integrated all 24 fail (22 tests, the
negation case parametrized 9 ways). The fixes, and a test of each from the
other side, are in tests/test_truth_fixes.py. Run with PYTHONUTF8=1."""
import sys, os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from lib import inspection_reports as IR, evidence as E, evidence_sources as ES, project_progress as PPG
from lib import forecast as F, work_state as W, photo_place as PL, dob_signoffs as DS

TODAY = date(2026, 11, 10)


# ---- 1. a correction later in the SAME message is not read ----
def test_same_message_correction_flips_failed_to_passed():
    own = "Plumbing rough on 3 passed. Actually no, the inspector failed it."
    v = IR.validate_statement(own, "Plumbing rough on 3 passed", "passed")
    assert v["result"] is None, v


# ---- 2. per-floor split: floor 2's sentence's result stored for floor 3 ----
def test_result_for_floor_2_stored_for_floor_3():
    own = "Plumbing rough passed on 2. Floor 3 failed."
    v = IR.validate_statement(own, "Plumbing rough passed on 2", "passed")
    levels = W.levels_named("2, 3")
    floor_ok = bool(levels) and all(W.level_said(lv, own) for lv in levels)   # server.py:56892
    stored_on = levels if (v["agree"] and floor_ok and not v["question"]) else []
    assert W.level_asked("3") not in stored_on, (v, stored_on)


def test_floor_said_by_a_headcount():
    assert not W.level_said(W.level_asked("3"), "plumbing rough passed, 3 guys from the plumber were there")


# ---- 3. negation / doubt the reader misses ----
@pytest.mark.parametrize("own", [
    "I doubt plumbing rough passed", "nothing passed today, plumbing rough", "nobody passed plumbing rough",
    "whether plumbing rough passed I can't say", "unless plumbing rough passed we wait",
    "plumbing rough passed (not)", "plumbing rough passed lol jk", "plumbing rough was anything but passed",
    "I wish plumbing rough passed",
])
def test_negation_or_doubt_stored_as_passed(own):
    v = IR.validate_statement(own, own, "passed")
    assert v["result"] is None, (own, v)


# ---- 4. a later UNDATED failure is hidden by an earlier DATED pass ----
def _row(result, said_at, inspected_on=None, rid="r"):
    return {"_id": rid, "status": "attested", "gate": "gate_plumbing_rough", "levels": ["FLOOR_3"], "result": result,
            "validated_result": result, "inspected_on": inspected_on, "created_at": said_at, "reporter_name": "Joe",
            "quote": "x"}


def test_undated_later_failure_hidden_in_progress_cell():
    rows = [_row("passed", datetime(2026, 11, 3, 15, tzinfo=timezone.utc), "2026-11-03", "a"),
            _row("failed", datetime(2026, 11, 9, 15, tzinfo=timezone.utc), None, "b")]
    items, _ = ES.from_inspections(rows, "p")
    c = PPG.cell(items, "FLOOR_3", "gate_plumbing_rough", TODAY)
    ws = IR.gate_read(IR.current_state(rows), "gate_plumbing_rough", "FLOOR_3")["status"]
    model = PPG.build(items, today=TODAY, project={"building_stories": 3}, job="588")
    print("project_progress:", c["status"], c["bucket"], "| work_state:", ws, "| conflicts:", model["conflicts"])
    assert c["bucket"] != "done"


# ---- 5. forecast prints the REPORT day as the inspection day ----
def test_forecast_marker_date_is_report_day():
    rows = [_row("passed", datetime(2026, 11, 9, 15, tzinfo=timezone.utc), None, "a")]
    it = F.items_from_inspection_reports(rows, "p")[0]
    print(F._marker_words(F._marker(it)))
    assert it["on"] is None, it["on"]


# ---- 6. date never checked against the words ----
def test_date_not_in_words_is_accepted():
    d, problem = IR.clean_date("2026-11-03", TODAY, "passed")   # their words: "plumbing rough on 3 passed"
    line = IR.noted_line("Joe", "plumbing rough", ["Floor 3"], "passed", d)
    print(line)
    assert problem is not None or "Nov 3" not in line


# ---- 7. documents ----
def test_checkbox_signoff_failed_box_ticked():
    ocr = "PLUMBING ROUGH INSPECTION\nFLOOR 3\n[ ] PASSED\n[X] FAILED\nINSPECTOR J. SMITH"
    v = IR.validate_document(ocr, "PASSED", "passed")
    print(v)
    assert v["result"] is None


def test_no_ocr_model_checks_itself():
    v = IR.validate_document("", "RESULT: PASSED", "passed")
    print(v["source"], v["result"])
    assert v["result"] is None


# ---- 8. DOB ----
def test_dob_signoff_spread_across_work_types():
    rows = [
        {"record_type": "permit", "job_number": "B0001-I1", "raw_dob_id": "p1", "work_type": "Plumbing",
         "permit_status": "Signed-off", "signoff_date": "2026-10-01"},
        {"record_type": "permit", "job_number": "B0001-I1", "raw_dob_id": "p2", "work_type": "Sprinkler",
         "permit_status": "Permit Issued"},
    ]
    items, _ = ES.from_dob(rows, "p")
    print(sorted(i["node"] for i in items), "| dob_signoffs covers:", DS.signoffs(rows)[0]["covers"])
    assert "rough_sprinkler" not in [i["node"] for i in items]


def test_dob_job_status_original_filing_date_used_as_signoff_day():
    r = {"record_type": "job_status", "job_filing_number": "B0002-I1", "raw_dob_id": "j",
         "filing_status": "LOC Issued", "filing_date": "2025-01-03"}
    print(DS.signoff_line(DS.signoffs([r])[0]))
    assert DS.signoffs([r])[0]["date"] is None


# ---- 9. unknown place reported as "whole building" ----
def test_no_floor_signoff_reported_as_whole_building():
    row = dict(_row("passed", datetime(2026, 11, 9, 15, tzinfo=timezone.utc), None, "a"), levels=[])
    items, _ = ES.from_inspections([row], "p")
    model = PPG.build(items, today=TODAY, project={"building_stories": 4}, job="588")
    txt = PPG.as_text(model)
    print([ln for ln in txt.splitlines() if "uilding" in ln][:3])
    assert "about the building" not in txt


# ---- 10. pour log outside the 90-day window -> "late" + a downstream ESTIMATE ----
def test_window_absence_moves_a_date():
    pour = {"_id": "L1", "log_type": "concrete_operations", "status": "submitted", "date": "2026-07-01",
            "data": {"pour_location": "3rd floor slab"}, "cp_name": "CP"}
    start = TODAY - timedelta(days=89)                      # server.py _forecast_inputs: WORK_STATE_DAYS = 90
    items, cov = ES.collect("p", start=start, end=TODAY, logbooks=[pour])
    full, _ = ES.collect("p", start=None, end=TODAY, logbooks=[pour])
    sched = {"activities": [
        {"id": "A1", "name": "Floor 3 slab", "baseline_finish": "2026-07-05", "predecessors": []},
        {"id": "A2", "name": "Drywall floor 3", "baseline_start": "2026-07-10", "baseline_finish": "2026-08-30",
         "predecessors": [{"id": "A1", "type": "FS", "lag": 0, "lag_unit": "days"}]}]}
    fc = F.forecast(sched, items, [], today=TODAY, project_id="p")
    txt = F.status_text(fc)
    print("window items:", len(items), "| unwindowed:", [(i["node"], i["kind"], i["claim"]) for i in full])
    print([ln for ln in txt.splitlines() if "ESTIMATE" in ln or "Floor 3 slab" in ln])
    assert not fc["plan_vs_actual"][0]["past_planned_finish_no_done"]


# ---- 11. a schedule INSPECTION activity never matches a reported inspection ----
def test_inspection_activity_ignores_reported_pass():
    rows = [_row("passed", datetime(2026, 11, 3, 15, tzinfo=timezone.utc), "2026-11-03", "a")]
    items, _ = ES.from_inspections(rows, "p")
    sched = {"activities": [{"id": "I3", "name": "Plumbing rough inspection floor 3", "baseline_finish": "2026-11-05"}]}
    fc = F.forecast(sched, items, [], today=TODAY, project_id="p")
    r = fc["plan_vs_actual"][0]
    print(r["nodes"], r["past_planned_finish_no_done"])
    assert not r["past_planned_finish_no_done"]


# ---- 12. a stair sign placed on the only level-titled sheet ----
def test_stair_sign_placed_on_cellar():
    spaces = PL.spaces_from_plan_rows([
        {"unit": "non-unit:STAIR 1", "sheet_title": "CELLAR FLOOR PLAN", "sheet_number": "A-100"},
        {"unit": "non-unit:STAIR 1", "sheet_title": "TYPICAL FLOOR PLAN 2-6", "sheet_number": "A-102"}])
    p = PL.infer({"where": "", "work": "framing", "visible_text": ["STAIR 1"]}, spaces)
    print(p["certainty"], p["level"])
    assert not (PL.is_sufficient(p) and p["level"])


# ---- 13. a newer UNRESOLVED statement is invisible behind an older pass ----
def test_newer_unresolved_hidden():
    rows = [_row("passed", datetime(2026, 11, 3, 15, tzinfo=timezone.utc), "2026-11-03", "a"),
            {**_row(None, datetime(2026, 11, 9, 15, tzinfo=timezone.utc), None, "b"), "status": "unresolved",
             "quote": "plumbing rough on 3 passed yesterday, failed today on retest"}]
    w = IR.words(IR.gate_read(IR.current_state(rows), "gate_plumbing_rough", "FLOOR_3"))
    print(w)
    assert "unresolved" in w.lower() or "retest" in w
