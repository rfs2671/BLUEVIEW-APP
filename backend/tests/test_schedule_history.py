"""schedule_history: finished-job schedules -> duration samples, and the ranges.

Every document here is SYNTHETIC and built in this file: no operator schedule
is in the repo. The rules under test are the module's docstring, one per test:
a sample needs BOTH actual dates, planned dates are never used as actuals,
milestones and summary rows are never samples, work that cannot be classified
is kept and counted but never guessed, and a range is refused below the
stated minimum of examples.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import progress_stages as S  # noqa: E402
from lib import schedule_history as H  # noqa: E402
from scripts import schedule_history_report as R  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def A(id, name, **kw):
    base = dict(id=id, wbs=None, name=name, level=1, kind="task", baseline_start=None, baseline_finish=None,
                current_start=None, current_finish=None, actual_start=None, actual_finish=None,
                percent_complete=None, duration_days=None)  # fmt: skip
    base.update(kw)
    return base


def done(id, name, start="2025-03-03", finish="2025-03-14", **kw):
    """A finished activity: both actual dates (default Mon 3 Mar - Fri 14 Mar 2025, 10 working days)."""
    return A(id, name, actual_start=start, actual_finish=finish, **kw)


def summary(id, name, level=0):
    return A(id, name, kind="summary", level=level)


def doc(acts, *, data_date="2025-12-31", source_name="job.xlsx", fmt="xlsx", **kw):
    d = {"format": fmt, "source_name": source_name, "sha256": hashlib.sha256(source_name.encode()).hexdigest(),
         "data_date": data_date, "project_name": None, "confidence": "structured", "activities": acts,
         "warnings": []}  # fmt: skip
    d.update(kw)
    return d


def samples(acts, job=None, **kw):
    return H.samples_of(doc(acts, **kw), job)["samples"]


def one(acts, job=None, **kw):
    out = samples(acts, job, **kw)
    assert len(out) == 1, out
    return out[0]


# ---------------------------------------------------------------- the ruler


def test_working_days_are_monday_to_friday_counted_inclusive():
    from datetime import date
    assert H.working_days(date(2025, 3, 3), date(2025, 3, 7)) == 5    # Mon..Fri
    assert H.working_days(date(2025, 3, 3), date(2025, 3, 10)) == 6   # Mon..next Mon
    assert H.working_days(date(2025, 3, 3), date(2025, 3, 3)) == 1    # one day
    assert H.working_days(date(2025, 3, 8), date(2025, 3, 9)) == 0    # a weekend
    assert H.working_days(date(2025, 3, 3), date(2025, 3, 21)) == 15


# ---------------------------------------------------------------- one sample


def test_a_finished_activity_becomes_one_sample_with_its_figures():
    s = one([done("A1", "Framing 3rd floor", finish="2025-03-21",
                  baseline_start="2025-03-03", baseline_finish="2025-03-14")],
            {"name": "12 Elm St", "storeys": 6, "building_type": "residential"}, source_name="elm.xlsx")
    assert s["status"] == H.CLASSIFIED and s["kind"] == "framing" and s["kind_label"] == S.LABEL["framing"]
    assert s["floors"] == [3] and s["floors_from"] == "name"
    assert s["planned_working_days"] == 10 and s["planned_from"] == "baseline_dates"
    assert s["actual_working_days"] == 15 and s["calendar_days"] == 19
    assert s["actual_over_planned"] == 1.5
    assert s["days_per_floor"] == 15
    assert s["source_name"] == "elm.xlsx" and s["job"] == "12 Elm St"
    assert s["storeys"] == 6 and s["building_type"] == "residential"
    assert s["actual_start"] == "2025-03-03" and s["actual_finish"] == "2025-03-21"


# ---------------------------------------------------------------- classification


@pytest.mark.parametrize("name,kind", [
    ("Framing 3rd floor", "framing"),
    ("Hang sheetrock - 2nd floor", "drywall"),
    ("Tape and spackle 4th floor", "taping"),
    ("Rough plumbing 2nd floor", "plumbing"),
    ("Set toilets 2nd floor", "plumbing_finish"),
    ("Electrical rough-in floor 5", "electrical"),
    ("Sprinkler branch lines 3rd floor", "sprinkler"),
    ("Excavation and footings", "excavation"),
    ("Roofing membrane", "roofing"),
    ("Paint 6th floor", "painting"),
])
def test_the_name_says_the_kind_of_work(name, kind):
    s = one([done("1", name)])
    assert (s["status"], s["kind"]) == (H.CLASSIFIED, kind)
    assert kind in S.LABEL  # a kind of work the progress board already knows, not a new list


def test_the_wbs_path_says_the_kind_when_the_name_does_not():
    acts = [summary("P", "Plumbing", level=0), done("1", "Floors 2-4", level=1),
            summary("E", "Electrical", level=0), done("2", "Rough-in 2nd floor", level=1)]
    a, b = samples(acts)
    assert (a["kind"], a["wbs_path"]) == ("plumbing", ["Plumbing"])
    assert (b["kind"], b["wbs_path"]) == ("electrical", ["Electrical"])


def test_the_nearest_wbs_heading_decides_only_when_the_name_names_no_trade():
    acts = [summary("X", "Job", level=0),
            summary("C", "Concrete superstructure", level=1),
            summary("S", "Steel stairs", level=2), done("1", "Section A 2nd floor", level=3),
            summary("W", "Windows", level=1), done("2", "Blocking 2nd floor", level=2),
            summary("I", "Interior fit-out", level=1), done("3", "Framing 2nd floor", level=2),
            summary("D", "Carpentry & drywall", level=1), done("4", "Framing 2nd floor", level=2)]
    a, b, c, d = samples(acts)
    assert a["kind"] == "steel"      # the nearest heading, not the outer "Concrete"
    assert b["kind"] == "windows"    # a weak word ("blocking") does not beat the heading it is under
    assert c["kind"] == "framing"    # the name's own word, under a heading that names no trade
    assert d["kind"] == "framing"    # ...and under one that names it among others


@pytest.mark.parametrize("heading,name,kinds", [
    (None, "Waterproof foundation walls", ["excavation", "flooring"]),  # the board would say flooring
    (None, "Bulkhead roofing", ["framing", "roofing"]),                 # the board would say framing
    ("Sprinkler", "Piping 3rd floor", ["plumbing", "sprinkler"]),       # the board would say plumbing
    ("Concrete superstructure", "Stairs 2nd floor", ["steel", "concrete"]),
])
def test_words_that_point_two_ways_are_not_picked_between(heading, name, kinds):
    acts = [summary("X", "Job", level=0), summary("H", heading, level=1)] if heading else []
    s = one(acts + [done("1", name, level=2)])
    assert s["status"] == H.SEVERAL and s["kind"] is None and s["kinds"] == kinds


def test_the_project_row_is_not_a_heading():
    acts = [summary("P", "Steel Tower at 12 Brick Lane", level=0), done("1", "Layout 2nd floor", level=1)]
    s = one(acts)
    assert s["status"] == H.UNCLASSIFIED and s["kind"] is None and s["wbs_path"] == []


def test_work_that_cannot_be_classified_is_kept_counted_and_never_guessed():
    res = H.samples_of(doc([done("1", "Install doors and hardware 2nd floor"), done("2", "Elevator cab"),
                            done("3", "Framing 2nd floor")]))
    assert [s["status"] for s in res["samples"]] == [H.UNCLASSIFIED, H.UNCLASSIFIED, H.CLASSIFIED]
    assert [s["kind"] for s in res["samples"]] == [None, None, "framing"]
    assert res["counts"]["by_status"][H.UNCLASSIFIED] == 2 and res["counts"]["by_status"][H.CLASSIFIED] == 1
    # kept: the figures are still there for the day the word lists learn the name
    assert res["samples"][0]["actual_working_days"] == 10 and res["samples"][0]["floors"] == [2]


def test_an_activity_naming_two_kinds_of_work_is_not_given_to_either():
    a, b = samples([done("1", "Frame and sheetrock 2nd floor"), done("2", "MEP rough-in 2nd floor")])
    assert a["status"] == H.SEVERAL and a["kind"] is None and a["kinds"] == ["framing", "drywall"]
    # "MEP" is three trades; the board's weak word would have called it HVAC
    assert b["status"] == H.SEVERAL and b["kind"] is None
    c, d = samples([summary("J", "Job"), summary("M", "MEP", level=1),
                    done("1", "Rough plumbing 2nd floor", level=2), done("2", "Rough-in 2nd floor", level=2)])
    assert c["kind"] == "plumbing"  # a real trade word under an MEP heading is still that trade
    assert d["status"] == H.SEVERAL and d["kind"] is None  # the heading alone names three trades


def test_rough_in_and_finish_of_one_trade_in_one_activity_are_two_kinds():
    s = one([done("1", "Plumbing rough-in and fixtures 2nd floor")])
    assert s["status"] == H.SEVERAL and s["kinds"] == ["plumbing", "plumbing_finish"]


@pytest.mark.parametrize("name", [
    "Window shop drawings", "Submit steel shop drawings", "Approve plumbing submittals", "Deliver windows",
    "Fabricate structural steel", "Order tile", "Plumbing inspection 2nd floor", "Sprinkler hydro test",
    "DOB electrical sign-off",
])
def test_paperwork_deliveries_and_inspections_are_not_building_work(name):
    s = one([done("1", name)])
    assert s["status"] == H.NOT_BUILDING and s["kind"] is None


def test_a_procurement_heading_covers_everything_under_it():
    s = one([summary("J", "Job"), summary("P", "Procurement", level=1), done("1", "Windows", level=2)])
    assert s["status"] == H.NOT_BUILDING and s["kind"] is None


# ---------------------------------------------------------------- floors


def test_a_range_of_floors_is_every_floor_in_it_and_the_days_are_shared():
    s = one([done("1", "Drywall floors 2-4", finish="2025-03-21")])  # 15 working days
    assert s["floors"] == [2, 3, 4] and s["days_per_floor"] == 5


@pytest.mark.parametrize("name,floors", [
    ("Taping Level 3", [3]), ("Taping L3", [3]), ("Taping 3rd Fl", [3]), ("Taping Floor 3", [3]),
    ("Taping first floor", [1]), ("Taping floors 5 & 6", [5, 6]),
])
def test_the_ways_a_schedule_writes_one_floor(name, floors):
    assert one([done("1", name)])["floors"] == floors


def test_the_floor_can_come_from_the_heading_and_says_so():
    s = one([summary("J", "Job"), summary("F", "3rd Floor", level=1), done("1", "Framing", level=2)])
    assert s["floors"] == [3] and s["floors_from"] == "wbs" and s["days_per_floor"] == 10


def test_floor_wording_the_readers_only_half_understand_gives_no_floor_at_all():
    # the shared reader returns [2] for the first and nothing for the second: a third of the floors
    # would triple the days per floor, so the sample keeps its days and states no floor
    res = H.samples_of(doc([done("1", "Tile floors 2, 3 & 4"), done("2", "Tile 2nd & 3rd floors")]))
    for s in res["samples"]:
        assert s["kind"] == "flooring"
        assert s["floors"] == [] and s["floors_unclear"] is True and s["days_per_floor"] is None
    assert res["counts"]["floors_unclear"] == 2


def test_no_floor_stated_means_no_per_floor_figure_even_when_storeys_are_known():
    s = one([done("1", "Roofing membrane")], {"name": "J", "storeys": 6, "gross_sqft": 30000})
    assert s["floors"] == [] and s["floors_unclear"] is False
    assert s["days_per_floor"] is None and s["days_per_1000_sqft"] is None  # never divided by the storeys


# ---------------------------------------------------------------- area


def test_days_per_1000_sqft_only_when_the_area_is_known():
    act = [done("1", "Framing floors 2-3", finish="2025-03-28")]  # 20 working days over 2 floors
    assert one(act)["days_per_1000_sqft"] is None
    assert one(act, {"name": "J", "storeys": 6})["days_per_1000_sqft"] is None
    by_footprint = one(act, {"name": "J", "footprint_sqft": 5000})
    assert by_footprint["days_per_1000_sqft"] == 2.0 and by_footprint["area_sqft"] == 10000
    by_gross = one(act, {"name": "J", "gross_sqft": 30000, "storeys": 6})
    assert by_gross["days_per_1000_sqft"] == 2.0
    assert one(act, {"name": "J", "gross_sqft": 30000})["days_per_1000_sqft"] is None  # no storeys: no floor area


# ---------------------------------------------------------------- what is not a sample


def test_a_missing_actual_date_means_no_sample():
    res = H.samples_of(doc([
        A("1", "Framing 2nd floor", actual_start="2025-03-03"),
        A("2", "Framing 3rd floor", actual_finish="2025-03-14"),
        A("3", "Framing 4th floor"),
        A("4", "Framing 5th floor", percent_complete=100),  # "100%" with no dates is not a duration
        done("5", "Framing 6th floor"),
    ]))
    assert [s["activity_id"] for s in res["samples"]] == ["5"]
    assert res["counts"]["activities"] == 5 and res["counts"]["finished"] == 1
    assert res["counts"]["no_sample"] == {"no_actual_dates": 2, "no_actual_finish": 1, "no_actual_start": 1,
                                          "dates_out_of_order": 0, "finish_after_status_date": 0}
    assert res["job_finished"] is False


def test_planned_dates_are_never_used_as_actuals():
    planned = dict(baseline_start="2025-03-03", baseline_finish="2025-03-14",
                   current_start="2025-03-10", current_finish="2025-03-21", duration_days=10.0)
    # every planned field filled, percent 100, no actual dates: nothing to learn a duration from
    assert samples([A("1", "Framing 2nd floor", percent_complete=100, **planned)]) == []
    # one actual date: the other is NOT taken from the plan
    assert samples([A("1", "Framing 2nd floor", actual_start="2025-03-10", **planned)]) == []
    assert samples([A("1", "Framing 2nd floor", actual_finish="2025-03-21", **planned)]) == []
    # both actual dates: the days are counted between THEM, whatever the plan says
    s = one([A("1", "Framing 2nd floor", actual_start="2025-04-07", actual_finish="2025-04-09", **planned)])
    assert (s["actual_start"], s["actual_finish"], s["actual_working_days"]) == ("2025-04-07", "2025-04-09", 3)
    assert s["planned_working_days"] == 10 and s["actual_over_planned"] == 0.3


def test_milestones_and_summary_rows_are_never_samples():
    dates = dict(actual_start="2025-03-03", actual_finish="2025-03-14")
    res = H.samples_of(doc([
        A("S", "Framing", kind="summary", level=0, **dates),
        A("M", "Framing complete 2nd floor", kind="milestone", level=1,
          actual_start="2025-03-14", actual_finish="2025-03-14"),
        A("1", "Framing 2nd floor", level=1, **dates),
    ]))
    assert [s["activity_id"] for s in res["samples"]] == ["1"]
    assert res["counts"]["summary_rows"] == 1 and res["counts"]["milestones"] == 1
    assert res["counts"]["activities"] == 1 and res["job_finished"] is True


def test_dates_that_cannot_be_true_are_not_samples():
    res = H.samples_of(doc([
        done("1", "Framing 2nd floor", start="2025-03-14", finish="2025-03-03"),   # finished before it started
        done("2", "Framing 3rd floor", start="2025-06-02", finish="2025-06-13"),   # "actual" after the status date
        done("3", "Framing 4th floor"),
    ], data_date="2025-05-01"))
    assert [s["activity_id"] for s in res["samples"]] == ["3"]
    assert res["counts"]["no_sample"]["dates_out_of_order"] == 1
    assert res["counts"]["no_sample"]["finish_after_status_date"] == 1
    # with no status date in the file there is nothing to check the finish against
    assert len(samples([done("2", "Framing 3rd floor", start="2025-06-02", finish="2025-06-13")], data_date=None)) == 1


# ---------------------------------------------------------------- the plan


def test_the_plan_is_the_baseline_and_only_dates_the_file_keeps_apart_from_the_actuals():
    # no baseline, and the scheduled dates equal the actual dates on every finished activity (what
    # MS Project and P6 do when an activity is finished): the file holds no separate plan
    same = dict(current_start="2025-03-03", current_finish="2025-03-14", duration_days=10.0)
    s = one([done("1", "Framing 2nd floor", **same)], fmt="msp_xml")
    assert s["planned_working_days"] is None and s["planned_from"] is None and s["actual_over_planned"] is None
    assert s["file_duration_days"] == 10.0  # carried as the file states it, used for nothing

    # no baseline, but the file keeps scheduled dates that differ from the actuals: they are its plan
    a, b = samples([
        done("1", "Framing 2nd floor", current_start="2025-03-03", current_finish="2025-03-14"),
        done("2", "Framing 3rd floor", finish="2025-03-21", current_start="2025-03-03", current_finish="2025-03-07"),
    ])
    assert (a["planned_from"], a["actual_over_planned"]) == ("scheduled_dates", 1.0)
    assert (b["planned_working_days"], b["actual_over_planned"]) == (5, 3.0)

    # a P6 file's original duration is its plan when the target dates are missing
    p6 = one([done("1", "Framing 2nd floor", duration_days=8.0)], fmt="xer")
    assert (p6["planned_working_days"], p6["planned_from"], p6["actual_over_planned"]) == (8.0, "file_duration", 1.25)
    # ...and for every other format a bare duration is never the plan (it may be the actual)
    assert one([done("1", "Framing 2nd floor", duration_days=8.0)], fmt="xlsx")["planned_working_days"] is None


# ---------------------------------------------------------------- several files of one job


def test_monthly_updates_of_one_job_count_each_activity_once_from_the_newest_file():
    march = H.samples_of(doc([done("A1", "Framing 2nd floor", finish="2025-03-13"),
                              A("A2", "Framing 3rd floor", actual_start="2025-03-17")],
                             data_date="2025-03-31", source_name="update-03.xlsx"), {"name": "Elm"})
    april = H.samples_of(doc([done("A1", "Framing 2nd floor", finish="2025-03-14"),   # corrected later
                              done("A2", "Framing 3rd floor", start="2025-03-17", finish="2025-04-04")],
                             data_date="2025-04-30", source_name="update-04.xlsx"), {"name": "Elm"})
    for order in ([march, april], [april, march]):
        merged = H.merge_updates(order)
        got = {s["activity_id"]: (s["source_name"], s["actual_finish"]) for s in merged["samples"]}
        assert got == {"A1": ("update-04.xlsx", "2025-03-14"), "A2": ("update-04.xlsx", "2025-04-04")}
        assert merged["counts"]["finished"] == 2 and merged["files"] == ["update-03.xlsx", "update-04.xlsx"]
        assert merged["job_finished"] is True  # as the newest file has it


def test_an_activity_only_the_older_update_has_is_kept():
    old = H.samples_of(doc([done("A1", "Demolition")], data_date="2025-03-31", source_name="a.xlsx"), {"name": "J"})
    new = H.samples_of(doc([done("A2", "Framing 2nd floor")], data_date="2025-04-30", source_name="b.xlsx"), {"name": "J"})
    assert sorted(s["activity_id"] for s in H.merge_updates([old, new])["samples"]) == ["A1", "A2"]


def test_two_jobs_that_share_most_activities_are_called_out():
    def job(name, shift):
        return H.samples_of(doc([done(str(i), f"Framing floor {i}", start="2025-03-03", finish=f"2025-03-{10 + i + shift:02d}")
                                 for i in range(1, 7)], source_name=f"{name}.xlsx"), {"name": name})["samples"]
    same = job("Elm rev A", 0) + job("Elm rev B", 0)
    assert H.overlapping_jobs(same) == [{"jobs": ["Elm rev A", "Elm rev B"], "shared": 6}]
    assert H.overlapping_jobs(job("Elm", 0) + job("Oak", 3)) == []


# ---------------------------------------------------------------- the summary


def _framing(job, days_list, **facts):
    """One finished framing activity per entry, each on its own floor, `days` working days long."""
    from datetime import date, timedelta
    acts = []
    for i, days in enumerate(days_list, 1):
        start = date(2025, 1, 6) + timedelta(weeks=3 * i)  # a Monday
        finish = start
        while H.working_days(start, finish) < days:
            finish += timedelta(days=1)
        acts.append(done(f"{job}-{i}", f"Framing floor {i}", start=start.isoformat(), finish=finish.isoformat(),
                         baseline_start=start.isoformat(), baseline_finish=(start + timedelta(days=4)).isoformat()))
    return H.samples_of(doc(acts, source_name=f"{job}.xlsx"), dict(name=job, **facts))["samples"]


def _kind(summ, key):
    return next(k for k in summ["kinds"] if k["kind"] == key)


def test_the_range_is_the_10th_and_90th_percentile_around_the_median():
    ss = _framing("Elm", [1, 2, 3, 4, 5]) + _framing("Oak", [6, 7, 8, 9, 10])
    summ = H.summarise(ss)
    k = _kind(summ, "framing")
    assert (k["samples"], k["jobs"]) == (10, 2)
    m = k["measures"]["days_per_floor"]
    assert m == {"n": 10, "jobs": 2, "enough": True, "p10": 1.9, "median": 5.5, "p90": 9.1}
    r = k["measures"]["actual_over_planned"]  # each was planned at 5 working days
    assert (r["n"], r["p10"], r["median"], r["p90"]) == (10, 0.38, 1.1, 1.82)
    assert k["ready"] is True and "framing" not in summ["too_few"]


def test_a_range_is_refused_below_the_stated_minimum_of_examples():
    assert H.MIN_SAMPLES == 10 and H.MIN_JOBS == 2
    ss = _framing("Elm", [1, 2, 3, 4, 5]) + _framing("Oak", [6, 7, 8, 9])  # nine
    summ = H.summarise(ss)
    m = _kind(summ, "framing")["measures"]["days_per_floor"]
    assert m == {"n": 9, "jobs": 2, "enough": False, "note": "not enough finished examples",
                 "note_es": "no hay suficientes ejemplos terminados"}
    assert not ({"p10", "median", "p90"} & m.keys())  # no number at all, not a weak one
    assert _kind(summ, "framing")["ready"] is False and "framing" in summ["too_few"]
    assert summ["min_samples"] == 10 and summ["min_jobs"] == 2
    # the minimum is the caller's to state, and the answer follows it
    assert _kind(H.summarise(ss, min_samples=9), "framing")["measures"]["days_per_floor"]["enough"] is True


def test_ten_examples_from_one_job_are_one_job_not_a_range_for_the_next():
    ss = _framing("Elm", list(range(1, 11)))
    m = _kind(H.summarise(ss), "framing")["measures"]["days_per_floor"]
    assert (m["n"], m["jobs"], m["enough"]) == (10, 1, False) and "median" not in m
    assert _kind(H.summarise(ss, min_jobs=1), "framing")["measures"]["days_per_floor"]["median"] == 5.5


def test_every_kind_of_work_is_listed_even_with_no_examples():
    summ = H.summarise(_framing("Elm", [3]))
    assert [k["kind"] for k in summ["kinds"]] == sorted(S.LABEL, key=lambda k: S.ORDER[k])
    assert _kind(summ, "plumbing")["samples"] == 0
    assert _kind(summ, "plumbing")["measures"]["days_per_floor"]["note"] == H.NOT_ENOUGH
    assert set(summ["too_few"]) == set(S.LABEL)


def test_unclassified_and_two_kind_activities_are_counted_beside_the_summary_never_in_it():
    ss = samples([done("1", "Install doors 2nd floor"), done("2", "Frame and sheetrock 2nd floor"),
                  done("3", "Deliver windows"), done("4", "Framing 2nd floor")])
    summ = H.summarise(ss)
    assert summ["samples"] == 4 and summ["classified"] == 1
    assert summ["not_summarised"] == {H.SEVERAL: 1, H.NOT_BUILDING: 1, H.UNCLASSIFIED: 1}
    assert sum(k["samples"] for k in summ["kinds"]) == 1


def test_per_1000_sqft_counts_only_the_examples_whose_area_is_known():
    ss = _framing("Elm", [1, 2, 3, 4, 5], footprint_sqft=1000) + _framing("Oak", [6, 7, 8, 9, 10])
    m = _kind(H.summarise(ss, min_samples=5, min_jobs=1), "framing")["measures"]
    assert (m["days_per_1000_sqft"]["n"], m["days_per_1000_sqft"]["median"]) == (5, 3.0)
    assert m["days_per_floor"]["n"] == 10


def test_work_with_no_floor_is_summarised_as_whole_activities_not_per_floor():
    def roof(job, days_list):
        return H.samples_of(
            doc([done(f"{job}{i}", "Roofing membrane", start="2025-03-03", finish=f"2025-03-{2 + d:02d}")
                 for i, d in enumerate(days_list)], source_name=f"{job}.xlsx"), {"name": job})["samples"]
    ss = roof("Elm", [1, 2, 3, 4, 5]) + roof("Oak", [1, 2, 3, 4, 5])  # Mon 3 Mar + d-1 days -> 1..5 working days
    k = _kind(H.summarise(ss), "roofing")
    assert k["measures"]["days_per_floor"]["n"] == 0
    assert (k["measures"]["days_no_floor"]["n"], k["measures"]["days_no_floor"]["median"]) == (10, 3.0)
    assert k["ready"] is True  # roofing is not built floor by floor (progress_stages.BUILDING_WIDE)
    # framing IS built floor by floor: whole-building framing rows do not make it ready
    frm = H.samples_of(doc([done(str(i), "Framing") for i in range(10)]), {"name": "Elm"})["samples"] \
        + H.samples_of(doc([done(str(i), "Framing") for i in range(10)], source_name="o.xlsx"), {"name": "Oak"})["samples"]
    k = _kind(H.summarise(frm), "framing")
    assert k["measures"]["days_no_floor"]["enough"] is True and k["ready"] is False


def test_one_floors_work_split_over_several_activities_is_also_measured_first_start_to_last_finish():
    acts = [done("1", "Frame walls 3rd floor", start="2025-03-03", finish="2025-03-07"),
            done("2", "Frame ceilings 3rd floor", start="2025-03-10", finish="2025-03-21"),
            done("3", "Framing floors 4-5", start="2025-03-24", finish="2025-04-04")]
    ss = H.samples_of(doc(acts), {"name": "Elm"})["samples"]
    m = _kind(H.summarise(ss, min_samples=1, min_jobs=1), "framing")["measures"]
    assert (m["floor_span_days"]["n"], m["floor_span_days"]["median"]) == (1, 15.0)  # floor 3: 3 Mar - 21 Mar
    assert m["days_per_floor"]["n"] == 3  # 5, 10 and 10/2


def test_the_most_common_unclassified_names_are_listed_without_their_floor():
    ss = samples([done(str(i), f"Install doors {n} floor") for i, n in enumerate(["2nd", "3rd", "4th"])]
                 + [done("9", "Elevator cab"), done("10", "Framing 2nd floor")])
    assert H.common_names(ss, H.UNCLASSIFIED) == [{"name": "install doors", "count": 3},
                                                  {"name": "elevator cab", "count": 1}]
    assert H.common_names(ss, H.UNCLASSIFIED, top=1) == [{"name": "install doors", "count": 3}]


# ---------------------------------------------------------------- pure, and read-only


def _imports(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


_FORBIDDEN = ("server", "motor", "pymongo", "requests", "httpx", "urllib", "socket", "http", "aiohttp",
              "openai", "anthropic", "boto3", "subprocess")


def test_the_module_and_the_script_touch_no_database_network_or_model():
    for rel in ("lib/schedule_history.py", "scripts/schedule_history_report.py"):
        names = _imports(BACKEND / rel)
        bad = sorted(n for n in names if n.split(".")[0] in _FORBIDDEN)
        assert bad == [], f"{rel} imports {bad}"
        assert names, rel
    lib = _imports(BACKEND / "lib/schedule_history.py")
    assert not {"os", "pathlib", "io", "json"} & {n.split(".")[0] for n in lib}  # the module reads no file
    assert "lib.progress_stages" in lib or "lib" in lib  # the board's matchers, not a second list


_CSV_HEAD = "ID,Task Name,Baseline Start,Baseline Finish,Actual Start,Actual Finish\n"


def _csv(rows):
    return (_CSV_HEAD + "".join(",".join(r) + "\n" for r in rows)).encode("utf-8")


def _framing_rows(n, days=5):
    from datetime import date, timedelta
    rows = []
    for i in range(1, n + 1):
        start = date(2025, 1, 6) + timedelta(weeks=2 * i)
        rows.append([f"A{i}", f"Framing floor {i}", start.isoformat(), (start + timedelta(days=4)).isoformat(),
                     start.isoformat(), (start + timedelta(days=days - 1 + (2 if days > 5 else 0))).isoformat()])
    return rows


def _tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_report_reads_a_folder_and_writes_one_json_file_elsewhere(tmp_path):
    src, out = tmp_path / "schedules", tmp_path / "out"
    (src / "12 Elm St").mkdir(parents=True)
    (src / "40 Oak Ave").mkdir()
    (src / "12 Elm St" / "final.csv").write_bytes(_csv(_framing_rows(5) + [["D1", "Install doors floor 2", "", "", "2025-06-02", "2025-06-06"]]))
    (src / "40 Oak Ave" / "final.csv").write_bytes(_csv(_framing_rows(5, days=8) + [["X1", "Punch list", "", "", "", ""]]))
    (src / "40 Oak Ave" / "old.mpp").write_bytes(b"\xd0\xcf\x11\xe0 not a real project file")
    (src / "notes.txt").write_bytes(b"call the plumber\n")
    (src / "job_facts.json").write_text(json.dumps({"12 elm st": {"storeys": 5, "footprint_sqft": 2000,
                                                                  "building_type": "residential"}}), encoding="utf-8")
    before = _tree(src)

    opened = []
    report = R.run(src, out, min_samples=10, min_jobs=2, progress=opened.append)
    assert opened == ["12 Elm St/final.csv", "40 Oak Ave/final.csv", "40 Oak Ave/old.mpp", "notes.txt"]

    assert _tree(src) == before  # the operator's folder is read, never changed
    written = list(out.iterdir())
    assert len(written) == 1 and written[0].suffix == ".json"
    assert json.loads(written[0].read_text(encoding="utf-8")) == json.loads(json.dumps(report))
    assert [(j["name"], j["finished"], j["activities"], j["job_finished"]) for j in report["jobs"]] == [
        ("12 Elm St", 6, 6, True), ("40 Oak Ave", 5, 6, False)]
    assert report["jobs"][0]["facts"]["storeys"] == 5 and report["jobs"][1]["facts"] == {}
    refused = {r["file"]: r["reason"] for r in report["files_refused"]}
    assert set(refused) == {"40 Oak Ave/old.mpp", "notes.txt"}
    assert "MS Project XML" in refused["40 Oak Ave/old.mpp"]
    assert len(report["files_read"]) == 2 and report["totals"]["finished"] == 11
    assert report["totals"]["by_status"][H.CLASSIFIED] == 10 and report["totals"]["by_status"][H.UNCLASSIFIED] == 1
    assert report["unclassified_names"] == [{"name": "install doors", "count": 1}]
    fr = next(k for k in report["summary"]["kinds"] if k["kind"] == "framing")
    assert fr["measures"]["days_per_floor"]["median"] == 6.5 and fr["measures"]["days_per_floor"]["jobs"] == 2
    assert fr["measures"]["days_per_1000_sqft"]["n"] == 5  # only Elm's area is known

    text = R.render(report)
    for needle in ("12 Elm St", "40 Oak Ave", "old.mpp", "install doors", "Framing", "not enough finished examples",
                   str(written[0])):
        assert needle in text, needle
    text.encode("ascii")  # prints on a Windows console


def test_the_report_refuses_to_write_inside_the_repo(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "a.csv").write_bytes(_csv(_framing_rows(2)))
    with pytest.raises(SystemExit) as e:
        R.run(tmp_path / "s", BACKEND / "scripts" / "_schedule_history_out")
    assert "outside the repo" in str(e.value)
    assert not (BACKEND / "scripts" / "_schedule_history_out").exists()


def test_the_same_file_twice_is_read_once_and_updates_in_one_folder_are_one_job(tmp_path):
    src = tmp_path / "s"
    (src / "Elm").mkdir(parents=True)
    data = _csv(_framing_rows(3))
    (src / "Elm" / "update 1.csv").write_bytes(data)
    (src / "Elm" / "update 1 (copy).csv").write_bytes(data)
    (src / "Elm" / "update 2.csv").write_bytes(_csv(_framing_rows(4)))
    report = R.run(src, tmp_path / "out")
    assert len(report["jobs"]) == 1 and report["jobs"][0]["finished"] == 4  # not 3 + 3 + 4
    assert report["files_refused"] == [{"file": "Elm/update 1.csv", "reason": "the same file as Elm/update 1 (copy).csv"}]
    assert report["jobs"][0]["files"] == ["Elm/update 1 (copy).csv", "Elm/update 2.csv"]
    assert report["totals"]["finished"] == 4
