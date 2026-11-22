"""THE PROGRESS BOARD ON A TALL BUILDING, AND DATES THAT SAY WHAT THEY ARE (2026-11-22).

Measured on the deployed engine (b4d09ac) with a 42-floor demo job, at the
width a Letter page prints at: the one-table board had 46 columns of 6.7 px
and 706 cells of text ran over or onto their neighbours; at 9 floor columns,
23. A 60-floor job: 1,276. The board is now one table only up to
BOARD_ONE_TABLE_MAX floor columns and printed in bands of floors above that.

Dates: a schedule file NEWER than the period reported printed its counts as
if they were the period's; a period that had not ended printed nothing to
say so and looked for "coming up" after a day that had not come; "floors 26,
27, 28, 29, 34, 35 and 36"; a log id ending in a date printed as "(-11-05)";
lists were cut with nothing to say they were.

Pure: no database, no network, no model.
"""

import re
import unittest
from datetime import date, datetime, timedelta, timezone

from lib import progress_report as P
from lib import progress_report_render as RR
from lib import progress_stages as ST
from lib import schedule_plan

NOW = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)


def _rows(floors: int, end: date):
    """One framing line and one electrical line per floor, a floor a day, the last ones inside the last week."""
    out = []
    for f in range(1, floors + 1):
        d = end - timedelta(days=floors - f)
        out.append({"date": d, "company": "Plumbline Framing", "trade": "Carpentry", "work": "Framing",
                    "where": f"Floor {f}", "floors": [f], "photos": []})
        out.append({"date": d, "company": "Brightway Electric", "trade": "Electrical", "work": "Conduit",
                    "where": f"Floor {f}", "floors": [f], "photos": []})
    return out


def _rep(floors: int, elsewhere: bool = False):
    end = date(2026, 11, 15)
    rows = _rows(floors, end)
    if elsewhere:
        rows.append({"date": end, "company": "Kestrel Concrete", "trade": "Concrete", "work": "Concrete pour",
                     "where": "Top deck", "floors": [], "photos": []})
    return {"progress": ST.build(rows, end=end, period_start=end - timedelta(days=13)), "end": end}


def _tables(html: str):
    return re.findall(r"<table class='board[^']*'>.*?</table>", html, flags=re.S)


def _cells_in_row(table: str):
    row = re.findall(r"<tr>.*?</tr>", table, flags=re.S)[0]
    return len(re.findall(r"<th", row))


class TestBands(unittest.TestCase):
    def test_bands_are_the_fewest_and_equal(self):
        self.assertEqual([len(b) for b in RR.board_bands(list(range(1, 9)))], [8])
        self.assertEqual([len(b) for b in RR.board_bands(list(range(1, 31)))], [30])
        self.assertEqual([len(b) for b in RR.board_bands(list(range(1, 43)))], [21, 21])
        self.assertEqual([len(b) for b in RR.board_bands(list(range(1, 61)))], [30, 30])
        self.assertEqual([len(b) for b in RR.board_bands(list(range(1, 62)))], [21, 21, 19])
        self.assertEqual(RR.board_bands([]), [])

    def test_every_floor_is_in_exactly_one_band(self):
        for n in (1, 7, 8, 9, 29, 30, 31, 42, 60, 61, 99):
            floors = list(range(1, n + 1))
            self.assertEqual([f for b in RR.board_bands(floors) for f in b], floors, n)
            self.assertTrue(all(len(b) <= RR.BAND_LETTERS_MAX for b in RR.board_bands(floors)), n)

    def test_a_small_job_keeps_the_one_table(self):
        html = RR._board_section(_rep(RR.BOARD_ONE_TABLE_MAX))
        tables = _tables(html)
        self.assertEqual(len(tables), 1)
        self.assertIn("<th>Fl 1</th>", tables[0])
        self.assertIn("Estimate", tables[0])
        self.assertNotIn("class='bandhead'", html)

    def test_the_other_column_counts_toward_the_limit(self):
        # seven floors and an "Other" column are eight columns: banded
        html = RR._board_section(_rep(RR.BOARD_ONE_TABLE_MAX, elsewhere=True))
        self.assertIn("bandhead", html)
        self.assertIn("Not tied to a floor", html)
        self.assertIn("at Top deck", html)

    def test_no_band_is_wider_than_the_page_allows(self):
        for n in (8, 9, 30, 42, 60, 99):
            html = RR._board_section(_rep(n))
            bands = [t for t in _tables(html) if "board band" in t]
            self.assertTrue(bands, n)
            for t in bands:
                self.assertLessEqual(_cells_in_row(t) - 1, RR.BAND_LETTERS_MAX, n)
            # every floor has its column head once
            heads = [int(x) for t in bands for x in re.findall(r"<th>(\d+)</th>", t)]
            self.assertEqual(heads, list(range(1, n + 1)), n)

    def test_words_while_they_fit_then_letters_with_a_key(self):
        few = RR._board_section(_rep(9))
        self.assertIn(">Active</td>", few)
        many = RR._board_section(_rep(42))
        self.assertNotIn(">Active</td>", many)
        self.assertIn(">A</td>", many)
        self.assertIn("<b>D</b> Done", many)          # the key to the letters is printed
        self.assertIn("<b>A</b> Active", many)

    def test_the_estimate_is_printed_once_per_kind_of_work(self):
        html = RR._board_section(_rep(42))
        est = [t for t in _tables(html) if "board est" in t]
        self.assertEqual(len(est), 1)
        self.assertEqual(est[0].count("class='est'><b>about"), 2)
        self.assertIn("Not measured on site", html)        # the basis statement stays

    def test_the_same_kinds_of_work_in_every_band(self):
        html = RR._board_section(_rep(60))
        bands = [t for t in _tables(html) if "board band" in t]
        self.assertEqual(len(bands), 2)
        names = [re.findall(r"<td class='work'>([^<]+)</td>", t) for t in bands]
        self.assertEqual(names[0], names[1])


class TestFloorsInWords(unittest.TestCase):
    def test_runs(self):
        self.assertEqual(ST.floors_words([26, 27, 28, 29, 34, 35, 36]), "floors 26–29 and 34–36")
        self.assertEqual(ST.floors_words([1, 2, 3, 4]), "floors 1–4")
        self.assertEqual(ST.floors_words([1, 2]), "floors 1–2")
        self.assertEqual(ST.floors_words([1, 3]), "floors 1 and 3")
        self.assertEqual(ST.floors_words([3]), "floor 3")
        self.assertEqual(ST.floors_words([]), "")
        self.assertEqual(P.floors_label([2, 5]), "floors 2, 5")
        self.assertEqual(P.floors_label([1, 2, 3, 7, 8]), "floors 1–3, 7–8")
        self.assertEqual(P.floors_label([1, 2, 3, 4]), "floors 1–4")


def _doc(data_date: date):
    return {"data_date": data_date.isoformat(), "activities": [
        {"id": "1", "name": "Concrete floor 1", "kind": "task", "baseline_start": "2026-08-03", "baseline_finish": "2026-08-07",
         "current_start": "2026-08-03", "current_finish": "2026-08-07", "actual_start": "2026-08-03",
         "actual_finish": "2026-08-07", "percent_complete": 100},
        {"id": "2", "name": "Concrete floor 2", "kind": "task", "baseline_start": "2026-10-05", "baseline_finish": "2026-10-09",
         "current_start": "2026-10-12", "current_finish": "2026-10-16", "actual_start": "2026-10-12",
         "actual_finish": "2026-10-16", "percent_complete": 100},
        {"id": "3", "name": "Topping out", "kind": "milestone", "baseline_finish": "2026-12-04", "current_finish": "2026-12-11"},
    ]}


class TestScheduleDates(unittest.TestCase):
    def test_a_file_newer_than_the_period_says_so(self):
        plan = schedule_plan.assess(_doc(date(2026, 11, 17)), period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                                    today=date(2026, 11, 18))
        self.assertEqual(plan["after_period_days"], 48)
        self.assertEqual(plan["after_today_days"], 0)
        self.assertTrue(any("48 days after the end of this period" in s and "as of that later date" in s
                            for s in plan["limitations"]))
        self.assertIn("48 days after this period ended", P.schedule_date_words(plan))
        html = RR._schedule_section({"schedule": plan, "work": []})
        self.assertIn("48 days after this period ended", html)
        self.assertIn("not as of the period's last day", html)
        self.assertIn("48 days after this period ended", RR._schedule_card({"schedule": plan}))

    def test_a_file_inside_the_period_says_nothing_extra(self):
        plan = schedule_plan.assess(_doc(date(2026, 9, 29)), period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                                    today=date(2026, 10, 1))
        self.assertEqual(plan["after_period_days"], 0)
        self.assertEqual(P.schedule_date_words(plan), "")
        self.assertNotIn("after this period ended", RR._schedule_section({"schedule": plan, "work": []}))

    def test_a_data_date_after_the_day_of_the_report_is_flagged(self):
        plan = schedule_plan.assess(_doc(date(2026, 11, 25)), period_start=date(2026, 11, 5), period_end=date(2026, 11, 18),
                                    today=date(2026, 11, 18))
        self.assertEqual(plan["after_today_days"], 7)
        self.assertTrue(any("after the day this report was prepared" in s for s in plan["limitations"]))
        self.assertIn("after the day this report was prepared", RR._schedule_section({"schedule": plan, "work": []}))

    def test_totals_behind_the_cut_lists(self):
        plan = schedule_plan.assess(_doc(date(2026, 9, 29)), period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
        self.assertEqual(plan["deviations_total"], len(plan["deviations"]))
        self.assertEqual(plan["scheduled_total"], len(plan["scheduled_in_period"]))


def _checkin(d: date, who: str, co: str):
    return {"worker_id": who, "worker_name": who, "worker_company": co,
            "check_in_time": datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)}


def _log(d: date, log_id: str):
    return {"_id": log_id, "log_type": "daily_jobsite", "status": "submitted", "date": d.isoformat(),
            "data": {"activities": [{"company": "Plumbline Framing", "trade": "Carpentry", "num_workers": 2,
                                     "work_description": "Framing", "work_locations": "Floor 2", "photos": []}]}}


class TestAPeriodThatHasNotEnded(unittest.TestCase):
    def setUp(self):
        days = [date(2026, 11, d) for d in (16, 17, 18)]
        self.now = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)       # 6 PM New York on the 18th
        self.kw = dict(job="Harbor Row Tower", address="demo", gc="demo", now=self.now,
                       checkins=[_checkin(d, w, "Plumbline Framing") for d in days for w in ("a", "b")],
                       logbooks=[_log(d, "log-" + d.isoformat()) for d in days],
                       events=[{"source": "city", "date": "2026-11-24", "kind": "hearing", "title": "OATH hearing (demo)"},
                               {"source": "city", "date": "2026-12-28", "kind": "hearing", "title": "Later hearing (demo)"}],
                       first_activity=date(2026, 11, 2))

    def test_the_report_says_the_period_is_in_progress(self):
        rep = P.compute(start=date(2026, 11, 1), end=date(2026, 11, 30), **self.kw)
        self.assertTrue(rep["in_progress"])
        self.assertEqual(rep["through"], date(2026, 11, 18))
        self.assertIn("to Nov 18 (the period has not ended)", rep["overview"][0])
        html = RR.render_html([rep], title="t", now=self.now)
        self.assertIn("Period in progress · records through Nov 18", html)
        self.assertIn("up to Nov 18, 2026", html)

    def test_coming_up_starts_where_the_records_stop(self):
        rep = P.compute(start=date(2026, 11, 1), end=date(2026, 11, 30), **self.kw)
        whats = [u["what"] for u in rep["upcoming"]]
        self.assertIn("OATH hearing (demo)", whats)                 # Nov 24: before the period's last day
        self.assertNotIn("Later hearing (demo)", whats)             # more than 30 days after Nov 18

    def test_a_finished_period_is_anchored_on_its_last_day_as_before(self):
        rep = P.compute(start=date(2026, 11, 2), end=date(2026, 11, 17), **self.kw)
        self.assertFalse(rep["in_progress"])
        self.assertEqual(rep["through"], date(2026, 11, 17))
        html = RR.render_html([rep], title="t", now=self.now)
        self.assertNotIn("Period in progress", html)

    def test_one_working_day_is_singular(self):
        rep = P.compute(start=date(2026, 11, 18), end=date(2026, 11, 18), **self.kw)
        self.assertIn("1 of 1 working day,", rep["overview"][0])
        self.assertIn("1 of 1 day ·", P.whatsapp_message(rep))
        self.assertTrue(any("1 of the 1 day with site activity" in n for n in rep["data_notes"]))

    def test_a_log_id_never_prints_as_a_piece_of_a_date(self):
        rep = P.compute(start=date(2026, 11, 16), end=date(2026, 11, 18), **self.kw)
        html = RR.render_html([rep], title="t", now=self.now)
        self.assertNotIn("(-11-1", html)
        self.assertEqual(RR._short_id("6734a1b2c3d4e5f6a7b8c9d0"), "b8c9d0")
        self.assertEqual(len(RR._short_id("log-2026-11-05")), 6)
        self.assertNotIn("-", RR._short_id("log-2026-11-05"))
        self.assertEqual(RR._short_id(""), "no id")


class TestListsSayWhenTheyAreCut(unittest.TestCase):
    def test_failed_inspection_items(self):
        insp = {"failed": 9, "failed_items": [{"item": "Fall protection", "date": date(2026, 9, d)} for d in (1, 2, 3, 4, 5, 6)]}
        self.assertTrue(P._failed_words(insp).endswith("and 6 more"))
        three = {"failed": 3, "failed_items": [{"item": "Fall protection", "date": date(2026, 9, d)} for d in (1, 2, 3)]}
        self.assertNotIn("more", P._failed_words(three))

    def test_by_floor_prints_every_floor(self):
        plan = {"usable": True, "as_of": date(2026, 11, 13), "stale_days": 2, "project": {}, "counts": {"activities": 42, "complete": 30},
                "milestones": {"completed_in_period": [], "overdue": [], "upcoming": [], "unconfirmed": []},
                "deviations": [], "scheduled_in_period": [], "groups": [],
                "floors": [{"floor": f, "complete": 1, "total": 1} for f in range(1, 43)]}
        html = RR._schedule_section({"schedule": plan, "work": []})
        heads = [int(x) for x in re.findall(r"<th class='n'>(\d+)</th>", html)]
        self.assertEqual(heads, list(range(1, 43)))          # it stopped at floor 14

    def test_milestones_not_listed_are_counted(self):
        m = lambda n: {"name": f"Milestone {n}", "date": date(2026, 9, 1), "baseline_finish": "2026-09-01", "current_finish": "2026-09-01"}
        plan = {"usable": True, "as_of": date(2026, 11, 13), "stale_days": 2, "project": {}, "counts": {"activities": 42, "complete": 30},
                "milestones": {"completed_in_period": [], "overdue": [m(n) for n in range(9)], "upcoming": [], "unconfirmed": []},
                "deviations": [], "scheduled_in_period": [], "groups": [], "floors": []}
        html = RR._schedule_section({"schedule": plan, "work": []})
        self.assertIn("3 more past due", html)


if __name__ == "__main__":
    unittest.main()
