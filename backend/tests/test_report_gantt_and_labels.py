"""THE LARGER REPORT: ONE SCHEDULE CHART, AND NO LABELS NOBODY CAN READ.

Nov 9, the owner, on the Oct 27 - Nov 9 report for 588: "What's that check new
and down? Advance? ... Lots of unclear messy information that nobody will read."
And: the report over a span of work is supposed to have a clear, minimalist
Gantt chart of schedule progress from the logbooks and the photos.

What the audit of that report found, and each is asserted:

  * All six CHECKs were accidents of a substring match: "Blocking" contains
    "block" (masonry), "Roof MEP" contains "roof" (facade), "Vapour barrier"
    contains "pour" (concrete).
  * ADVANCED only meant a floor number appeared in a log line.
  * "Slate Windows DOWN ... decreased to 4.3 from 9": the 9 was one day.
  * "Roof MEP - floors 1-4": every phrase of a crew row took the row's floors.
  * "Plumbing installed" under an insulation crew's photo: a stock caption for
    a sub whose kind of work is not known.

CONTROL: against origin/main's lib/progress_report.py and
lib/progress_report_render.py, 23 fail and 3 pass (run 2026-11-09).
"""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import progress_report as P  # noqa: E402
from lib import progress_report_render as RR  # noqa: E402
from tests import report_588 as F  # noqa: E402


def _report():
    return F.report(logbooks=F.logbooks() + F.previous_logbooks())


def _html(rep, images=None):
    return RR.render_html([rep], gc="", title="t", now=F.NOW, images=images or {})


def _act(work, floors="floors 1-4", day=9, company="BreezCo", trade="HVAC / Mechanical"):
    return {"date": date(2026, 10, day), "key": "b", "company": company, "trade": trade, "workers": 2,
            "work": work, "where": floors, "floors": P.floors_in(floors), "photos": [], "log": f"l{day}",
            "log_id": "x", "amended": False}


def _items(*acts, name="BreezCo", trade="HVAC / Mechanical"):
    got = P._work(list(acts), [], {"b": "b"}, [{"key": "b", "name": name, "trade": trade}], True)
    return {i["work"]: i for i in got[0]["items"]}


class TheLabelsAreGone(unittest.TestCase):

    def test_no_check_advanced_new_floor_up_or_down_is_printed(self):
        html = _html(_report())
        for label in (">CHECK<", ">ADVANCED<", ">UP<", ">DOWN<", "new: floor", "CHECK marks", "ADVANCED marks",
                      "does not match the"):
            with self.subTest(label=label):
                self.assertNotIn(label, html)

    def test_every_line_the_real_report_flagged_reaches_the_summary_as_filed(self):
        for work in ("Blocking", "Roof MEP", "Rooftop unit", "Vapour barrier"):
            with self.subTest(work=work):
                self.assertEqual(list(_items(_act(work))), [work])
                self.assertEqual(set(_items(_act(work))[work]) & {"trade_mismatch"}, set())

    def test_a_crew_seen_one_day_last_period_has_no_size_to_compare(self):
        s = {"name": "Slate Windows", "key": "s", "prev_days": 1, "avg": 4.3, "prev_avg": 9.0, "first": date(2026, 10, 9)}
        self.assertLess(s["prev_days"], P.CHANGE_MIN_PREV_DAYS)
        rep = _report()
        slate = dict(rep["subs"][0], name="Slate Windows", avg=4.3, prev_avg=9.0, prev_days=1, days=rep["subs"][0]["days"])
        rep = dict(rep, subs=[slate])
        self.assertNotIn("Slate Windows crew", " ".join(c["text"] for c in P.changes(rep)))


class WhereAWorkLineIs(unittest.TestCase):

    def test_a_line_that_names_its_place_takes_no_floors_from_its_row(self):
        items = _items(_act("Ductwork rough, Roof MEP"))
        self.assertEqual(items["Ductwork rough"]["floors"], [1, 2, 3, 4])
        self.assertEqual((items["Roof MEP"]["floors"], items["Roof MEP"]["place"]), ([], ""))

    def test_the_sentence_reads(self):
        got = P._work([_act("Ductwork rough, Roof MEP")], [], {"b": "b"},
                      [{"key": "b", "name": "BreezCo", "trade": "HVAC"}], True)
        self.assertEqual(RR._work_words(got[0]), "Ductwork rough · floors 1–4 · roof MEP")

    def test_no_description_says_so(self):
        self.assertEqual(RR._work_words(None), "No work description in the daily logs.")


class TheWordsUnderAPhoto(unittest.TestCase):
    CAND = {"key": "k", "date": date(2026, 10, 9), "where": "floor 2", "words": "x", "work": "x",
            "source": "daily log", "log_id": "x"}

    def _caption(self, sub, trade, seen):
        v = {"k": {"ok": True, "kind": "progress", "score": 8, "work": seen}}
        return P.pick_photos([dict(self.CAND, sub=sub, trade=trade)], v)[0]["caption"]

    def test_the_words_agree_with_whose_photo_it_is(self):
        self.assertEqual(self._caption("Quality Plumbing", "Plumber", "plumbing"), "Plumbing installed")

    def test_no_words_when_the_subs_kind_of_work_is_not_known(self):
        self.assertEqual(self._caption("A1", "Insulation", "plumbing"), "")
        self.assertEqual(self._caption("J&P Construction", "Stucco", "framing"), "")


class TheBars(unittest.TestCase):

    def test_a_weekend_does_not_break_a_bar(self):
        fri, mon = date(2026, 10, 30), date(2026, 11, 2)
        self.assertEqual(RR._gantt_bars([fri, mon]), [[fri, mon]])

    def test_a_working_day_with_nobody_there_does(self):
        mon, wed = date(2026, 11, 2), date(2026, 11, 4)
        self.assertEqual(RR._gantt_bars([mon, wed]), [[mon, mon], [wed, wed]])

    def test_the_axis_names_the_first_day(self):
        s = date(2026, 10, 27)
        end = s + timedelta(days=13)
        self.assertIn("Oct 27", RR._gantt_axis(s, end, RR._gantt_ticks(s, end)))

    def test_the_axis_is_mondays_and_months_on_a_long_report(self):
        s = date(2026, 10, 27)
        self.assertEqual(RR._gantt_ticks(s, s + timedelta(days=13)), [date(2026, 11, 2), date(2026, 11, 9)][:2])
        self.assertTrue(all(t.day == 1 for t in RR._gantt_ticks(s, s + timedelta(days=200))))


class TheChart(unittest.TestCase):

    def test_it_is_on_a_report_over_a_span_of_work(self):
        rep = _report()
        self.assertGreaterEqual((rep["end"] - rep["start"]).days + 1, RR.GANTT_MIN_DAYS)
        html = _html(rep)
        self.assertIn("Schedule progress", html)
        self.assertEqual(html.count("<td class='who'><span"), len(rep["subs"]))

    def test_the_earliest_start_is_on_top(self):
        rep = _report()
        html = RR._progress(rep, {})
        names = re.findall(r"<td class='who'><span class='name'>([^<]+)", html)
        firsts = {s["name"]: s["first"] for s in rep["subs"]}
        self.assertEqual([firsts[n.replace("&amp;", "&")] for n in names],
                         sorted(firsts[n.replace("&amp;", "&")] for n in names))

    def test_a_photo_in_the_report_is_a_dot_on_its_day_and_one_not_shown_is_not(self):
        rep = _report()
        s = rep["subs"][0]
        photo = {"key": "k1", "date": s["days"][0], "sub": s["name"]}
        rep = dict(rep, photos=[photo])
        self.assertEqual(RR._progress(rep, {"k1": "data:x"}).count("<circle"), 2, "the dot, and the legend's")
        self.assertEqual(RR._progress(rep, {}).count("<circle"), 0, "not in the report, not on the chart")

    def test_a_short_report_has_no_chart(self):
        rep = _report()
        rep = dict(rep, end=rep["start"] + timedelta(days=RR.GANTT_MIN_DAYS - 2))
        html = RR._progress(rep, {})
        self.assertNotIn("<svg", html)
        self.assertIn("Reported work", html)

    def test_it_never_draws_a_percent(self):
        self.assertNotIn("%", RR._progress(_report(), {}).replace("width=\"100%\"", ""))


if __name__ == "__main__":
    unittest.main()
