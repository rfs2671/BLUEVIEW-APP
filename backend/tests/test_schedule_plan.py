"""schedule_plan.assess: only what the schedule file supports."""

from __future__ import annotations

import json
from datetime import date

from lib.schedule_plan import assess, to_jsonable

PS, PE = date(2026, 10, 1), date(2026, 10, 14)  # the period asked for


def A(id, name, **kw):
    base = dict(id=id, wbs=None, name=name, level=1, kind="task", baseline_start=None, baseline_finish=None,
                current_start=None, current_finish=None, actual_start=None, actual_finish=None,
                percent_complete=None, duration_days=None)  # fmt: skip
    base.update(kw)
    return base


def doc(acts, data_date="2026-10-14", **kw):
    d = {"format": "xlsx", "source_name": "s.xlsx", "sha256": "0" * 64, "data_date": data_date,
         "project_name": None, "confidence": "structured", "activities": acts, "warnings": []}  # fmt: skip
    d.update(kw)
    return d


def run(acts, **kw):
    dd = kw.pop("data_date", "2026-10-14")
    return assess(doc(acts, data_date=dd, **kw.pop("docargs", {})), period_start=PS, period_end=PE, **kw)


def test_empty_or_undated_schedule_is_not_usable():
    out = run([A("1", "No dates")])
    assert out["usable"] is False and out["limitations"]
    assert out["counts"]["activities"] == 0 and out["milestones"]["overdue"] == []
    assert run([])["usable"] is False


def test_counts_are_of_activities_and_exclude_summaries():
    out = run([
        A("s", "Group", kind="summary", level=0, current_start="2026-09-01"),
        A("1", "Done by date", actual_start="2026-09-01", actual_finish="2026-09-05"),
        A("2", "Done by pct", percent_complete=100, current_start="2026-09-01"),
        A("3", "Going", actual_start="2026-10-01", percent_complete=30),
        A("4", "Later", current_start="2026-11-01"),
    ])
    assert out["counts"] == {"activities": 4, "complete": 2, "in_progress": 1, "not_started": 1}


def test_project_percent_only_from_summary_row_never_averaged():
    acts = [
        A("1", "A", percent_complete=100, current_finish="2026-09-01"),
        A("2", "B", percent_complete=50, current_finish="2026-09-01"),
        A("3", "C", percent_complete=0, current_finish="2026-09-01"),
    ]
    out = run(acts)
    assert out["project"]["reported_percent"] is None  # negative control: no project row
    with_row = [A("p", "Project", kind="summary", level=0, percent_complete=37.5)] + acts
    assert run(with_row)["project"]["reported_percent"] == 37.5
    no_pct = [A("p", "Project", kind="summary", level=0)] + acts
    assert run(no_pct)["project"]["reported_percent"] is None
    # two level-0 summary rows are phases, not "the project"
    phases = [A("p1", "Phase 1", kind="summary", level=0, percent_complete=10), A("1", "x", current_finish="2026-09-01"),
              A("p2", "Phase 2", kind="summary", level=0, percent_complete=90), A("2", "y", current_finish="2026-09-01")]  # fmt: skip
    assert run(phases)["project"]["reported_percent"] is None


def test_project_dates_and_variance_need_both_from_file():
    out = run([
        A("1", "a", baseline_finish="2026-11-01", current_finish="2026-11-10"),
        A("2", "b", baseline_finish="2026-12-01", current_finish="2026-12-20", actual_finish=None),
    ])
    p = out["project"]
    assert p["baseline_finish"] == date(2026, 12, 1) and p["forecast_finish"] == date(2026, 12, 20)
    assert p["variance_days"] == 19
    nob = run([A("1", "a", current_finish="2026-11-10")])
    assert nob["project"]["baseline_finish"] is None and nob["project"]["variance_days"] is None
    assert nob["project"]["forecast_finish"] == date(2026, 11, 10)
    assert any("no baseline" in s for s in nob["limitations"])
    assert any("no percent complete" in s for s in nob["limitations"])


def test_project_summary_row_dates_win():
    acts = [A("p", "Project", kind="summary", level=0, baseline_finish="2027-01-01", current_finish="2027-02-01"),
            A("1", "a", baseline_finish="2026-11-01", current_finish="2026-11-10")]  # fmt: skip
    p = run(acts)["project"]
    assert (p["baseline_finish"], p["forecast_finish"], p["variance_days"]) == (date(2027, 1, 1), date(2027, 2, 1), 31)


def test_data_date_stale_days_and_limitations():
    acts = [A("1", "a", current_finish="2026-11-01")]
    fresh = run(acts, data_date="2026-10-14")
    assert fresh["as_of"] == date(2026, 10, 14) and fresh["stale_days"] == 0
    assert not any("days before the end of this period" in s for s in fresh["limitations"])
    old = run(acts, data_date="2026-09-20")
    assert old["stale_days"] == 24 and any("24 days before" in s for s in old["limitations"])
    ahead = run(acts, data_date="2026-10-20")
    assert ahead["stale_days"] == -6 and any("after the end of this period" in s for s in ahead["limitations"])
    none = run(acts, data_date=None)
    assert none["as_of"] is None and none["stale_days"] is None
    assert any("does not state a status/data date" in s for s in none["limitations"])
    superseded = run(acts, data_date="2026-09-20", today=date(2026, 10, 19))
    assert any("newer schedule may exist" in s for s in superseded["limitations"])


def test_pdf_extracted_limitation():
    out = run([A("1", "a", current_finish="2026-11-01")], docargs={"confidence": "extracted"})
    assert any("PDF" in s and "confirm" in s for s in out["limitations"])


def _ms(id, name, finish, **kw):
    return A(id, name, kind="milestone", current_start=finish, current_finish=finish, **kw)


def test_milestones_overdue_unconfirmed_upcoming_completed():
    acts = [
        _ms("c", "Completed in period", "2026-10-05", actual_finish="2026-10-06"),
        _ms("c0", "Completed before", "2026-09-01", actual_finish="2026-09-02"),
        _ms("o", "Overdue", "2026-10-02"),
        _ms("u", "Upcoming", "2026-10-30"),
        _ms("far", "Too far", "2026-11-20"),
        _ms("p", "Percent done", "2026-10-03", percent_complete=100),
        A("b", "Baseline only", kind="milestone", baseline_finish="2026-10-04"),
    ]
    m = run(acts, data_date="2026-10-14")["milestones"]
    ids = lambda k: [x["id"] for x in m[k]]  # noqa: E731
    assert ids("completed_in_period") == ["c"] and m["completed_in_period"][0]["date"] == date(2026, 10, 6)
    assert ids("overdue") == ["o", "b"]
    assert ids("upcoming") == ["u"]
    assert ids("unconfirmed") == []


def test_milestones_after_data_date_are_unconfirmed_not_overdue():
    acts = [_ms("a", "Before data date", "2026-10-05"), _ms("b", "After data date", "2026-10-10"),
            _ms("c", "Next month", "2026-10-25")]  # fmt: skip
    m = run(acts, data_date="2026-10-07")["milestones"]
    assert [x["id"] for x in m["overdue"]] == ["a"]
    assert [x["id"] for x in m["unconfirmed"]] == ["b"]
    assert [x["id"] for x in m["upcoming"]] == ["c"]


def test_no_data_date_means_nothing_is_called_overdue():
    m = run([_ms("a", "Old", "2026-09-05")], data_date=None)["milestones"]
    assert m["overdue"] == [] and [x["id"] for x in m["unconfirmed"]] == ["a"]


def test_deviation_threshold_six_days_no_seven_yes():
    acts = [
        A("6", "six", baseline_finish="2026-10-01", current_finish="2026-10-07"),
        A("7", "seven", baseline_finish="2026-10-01", current_finish="2026-10-08"),
        A("m", "ms", kind="milestone", baseline_finish="2026-10-01", current_finish="2026-10-20"),
        A("ls6", "late6", baseline_start="2026-10-01", actual_start="2026-10-07"),
        A("ls9", "late9", baseline_start="2026-10-01", actual_start="2026-10-10"),
        A("none", "no baseline", current_finish="2027-01-01"),  # nothing to compare: no deviation
        A("early", "early", baseline_finish="2026-10-20", current_finish="2026-10-01"),
    ]
    d = run(acts)["deviations"]
    assert [(x["id"], x["kind"], x["days"]) for x in d] == [
        ("m", "finish_slip_milestone", 19), ("ls9", "late_start", 9), ("7", "finish_slip", 7),
    ]
    assert d[2]["baseline"] == date(2026, 10, 1) and d[2]["current"] == date(2026, 10, 8)
    assert set(d[0]) == {"id", "name", "kind", "baseline", "current", "days"}  # no "cause"


def test_deviations_capped_to_eight_largest():
    acts = [A(str(i), f"t{i}", baseline_finish="2026-01-01", current_finish=f"2026-02-{i:02d}") for i in range(1, 16)]
    d = run(acts)["deviations"]
    assert len(d) == 8 and d[0]["days"] == 31 + 14


def test_scheduled_in_period_uses_current_else_baseline_and_caps():
    acts = [
        A("in", "Inside", current_start="2026-10-05", current_finish="2026-10-09", percent_complete=20),
        A("span", "Spans", current_start="2026-09-01", current_finish="2026-12-01"),
        A("base", "Baseline only", baseline_start="2026-10-10", baseline_finish="2026-10-20"),
        A("moved", "Moved out", baseline_start="2026-10-05", baseline_finish="2026-10-09",
          current_start="2026-11-05", current_finish="2026-11-09"),  # current wins: not in period
        A("before", "Before", current_start="2026-08-01", current_finish="2026-09-30"),
        A("none", "No dates"),
    ]
    s = run(acts)["scheduled_in_period"]
    assert [x["id"] for x in s] == ["span", "in", "base"]
    assert s[1]["percent_complete"] == 20
    many = [A(str(i), f"t{i}", current_start="2026-10-05", current_finish="2026-10-06") for i in range(40)]
    assert len(run(many)["scheduled_in_period"]) == 25


def test_groups_percent_only_when_summary_row_reports_it():
    acts = [
        A("p", "Project", kind="summary", level=0),
        A("g1", "Structure", kind="summary", level=1, percent_complete=60),
        A("1", "a", level=2, actual_finish="2026-09-01"),
        A("2", "b", level=2, current_finish="2026-11-01"),
        A("g2", "Fit-out", kind="summary", level=1),
        A("3", "c", level=2, percent_complete=90, current_finish="2026-11-01"),
        A("g3", "Empty", kind="summary", level=1),
    ]
    g = run(acts)["groups"]
    assert g == [{"name": "Structure", "percent": 60, "complete": 1, "total": 2},
                 {"name": "Fit-out", "percent": None, "complete": 0, "total": 1}]  # fmt: skip
    flat = run([A("1", "a", current_finish="2026-11-01")])["groups"]
    assert flat == []


def test_floors_need_three_tokens_and_report_counts_only():
    acts = [
        A("1", "Pour slab Floor 3", actual_finish="2026-09-20"),
        A("2", "Frame 3rd floor"),
        A("3", "MEP rough-in L3"),
        A("4", "Drywall level 4", percent_complete=100),
        A("5", "Floors 3-5 punch"),  # a range: not assigned to one floor
        A("6", "Floor 3 and 4 clean"),  # two floors: skipped
        A("7", "Fl 12 decking"),
        A("8", "Backfill"),
    ]
    f = run(acts)["floors"]
    assert f == [{"floor": 3, "complete": 1, "total": 3}, {"floor": 4, "complete": 1, "total": 1},
                 {"floor": 12, "complete": 0, "total": 1}]  # fmt: skip
    assert all("percent" not in x for x in f)
    assert run([A("1", "Floor 3 slab"), A("2", "Floor 4 slab")])["floors"] == []  # only 2 tokens


def test_to_jsonable_round_trips_through_json():
    acts = [_ms("a", "M", "2026-10-30"), A("1", "x", baseline_finish="2026-01-01", current_finish="2026-02-01")]
    out = run(acts)
    text = json.dumps(to_jsonable(out))
    back = json.loads(text)
    assert back["as_of"] == "2026-10-14"
    assert back["milestones"]["upcoming"][0]["date"] == "2026-10-30"
    assert back["deviations"][0]["baseline"] == "2026-01-01"


def test_end_to_end_with_import():
    from lib.schedule_import import parse_schedule

    csv_text = (
        "ID,Task Name,Start,Finish,Baseline Finish,Actual Start,Actual Finish,% Complete,Milestone\n"
        "1,Excavate,2026-09-01,2026-09-20,2026-09-10,2026-09-01,2026-09-20,100,\n"
        "2,Topping out,2026-10-09,2026-10-09,2026-10-01,,,,Y\n"
    )
    out = assess(parse_schedule("p.csv", csv_text.encode()), period_start=PS, period_end=PE)
    assert out["as_of"] is None and out["project"]["reported_percent"] is None
    assert out["deviations"][0]["days"] == 10
    assert [x["id"] for x in out["milestones"]["unconfirmed"]] == ["2"]
