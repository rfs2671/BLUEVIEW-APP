"""THE MODEL IS THE SEMANTIC AUTHORITY, AND THE CLOSED SETS ARE CLOSED.

The renderer is not allowed to decide what a zero means, whether a company was
on site, or whether "no incidents" may be said. This file holds the model to
that: every judgement is made here, both closed sets are exhaustively
reachable, and a sixth state fails loudly rather than silently choosing copy.

ONE TEST HERE IS WORTH MORE THAN THE REST. A worker badges in at half past nine
in the evening Eastern; the UTC date is already tomorrow. He must appear on the
correct local report day. A probe in this repository got that wrong by slicing
a UTC timestamp to ten characters, and the wrong answer looked clean.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.report import location_vocabulary as lv  # noqa: E402
from lib.report import model as m  # noqa: E402


def _row(company="Arkon Builders", trade="Framers", status="checked_in",
         worker_id=None, name="A Worker"):
    return {"worker_company": company, "trade": trade, "status": status,
            "worker_id": worker_id, "worker_name": name}


def _activity(company="Arkon Builders", workers="6", where="1st floor",
              photos=None, trade=""):
    a = {"company": company, "work_locations": where, "trade": trade,
         "photos": photos or []}
    if workers is not None:
        a["num_workers"] = workers
    return a


# ══════════════════════════════════════════════════════════════════════════
#  THE FIVE RECONCILIATION STATES
# ══════════════════════════════════════════════════════════════════════════

class TheFiveStates(unittest.TestCase):

    CASES = {
        (6, 6): m.Reconciliation.ALIGNED,
        (7, 5): m.Reconciliation.VARIANCE,
        (7, 0): m.Reconciliation.LOG_ONLY,
        (0, 0): m.Reconciliation.LOG_ONLY,      # a RECORDED zero, not absent
        (None, 5): m.Reconciliation.GATE_ONLY,
        (None, 0): m.Reconciliation.NEITHER,
    }

    def test_each_pair_resolves_to_the_named_state(self):
        for (log, gate), expected in self.CASES.items():
            with self.subTest(log=log, gate=gate):
                self.assertIs(m.reconcile(log, gate), expected)

    def test_EVERY_MEMBER_IS_REACHABLE(self):
        """THE LOUD FAILURE. A sixth member added without a rule in `reconcile`
        never appears here, and this fails naming it -- rather than the
        renderer quietly never drawing it."""
        produced = {m.reconcile(log, gate)
                    for log in (None, 0, 1, 6, 7)
                    for gate in (0, 1, 5, 6)}
        self.assertEqual(
            produced, set(m.Reconciliation),
            "a Reconciliation member is unreachable from `reconcile`: "
            f"{set(m.Reconciliation) - produced}")

    def test_every_member_has_a_chip(self):
        for state in m.Reconciliation:
            self.assertIn(state, m.RECONCILIATION_CHIP, state)
            self.assertTrue(m.RECONCILIATION_CHIP[state])

    def test_every_member_has_a_statement_and_none_is_empty(self):
        for (log, gate), state in self.CASES.items():
            text = m.reconciliation_statement(state, log, gate)
            self.assertTrue(text.strip(), state)

    def test_the_numbers_are_never_suppressed(self):
        """A recorded seven against nobody at the gate prints the seven."""
        text = m.reconciliation_statement(m.Reconciliation.LOG_ONLY, 7, 0)
        self.assertIn("7 on daily log", text)
        self.assertIn("0 matched gate check-ins", text)

    def test_a_variance_prints_both_numbers_and_picks_neither(self):
        text = m.reconciliation_statement(m.Reconciliation.VARIANCE, 7, 5)
        self.assertIn("7 on daily log", text)
        self.assertIn("5 gate check-ins", text)


class ARecordedZeroIsNotAMissingCount(unittest.TestCase):
    """THE ONE THAT ALREADY BIT. AAZ on 2026-08-27 stores the literal "0" while
    carrying two photographs of AAZ framing. `if not num_workers` reads that as
    "not recorded", which is the softer and wrong claim, on the one row anybody
    was looking at."""

    def test_the_literal_zero_is_a_recorded_zero(self):
        self.assertEqual(m.log_headcount({"num_workers": "0"}), 0)
        self.assertEqual(m.log_headcount({"num_workers": 0}), 0)

    def test_an_empty_string_is_not_recorded(self):
        self.assertIsNone(m.log_headcount({"num_workers": ""}))
        self.assertIsNone(m.log_headcount({"num_workers": "   "}))

    def test_an_absent_key_is_not_recorded(self):
        self.assertIsNone(m.log_headcount({}))
        self.assertIsNone(m.log_headcount({"num_workers": None}))

    def test_a_recorded_zero_reaches_a_DIFFERENT_state_from_absent(self):
        zero = m.ActivityDisplayState(_activity(workers="0"), 0,
                                      m.GateDayState([]))
        absent = m.ActivityDisplayState(_activity(workers=""), 0,
                                        m.GateDayState([]))
        self.assertIs(zero.reconciliation, m.Reconciliation.LOG_ONLY)
        self.assertIs(absent.reconciliation, m.Reconciliation.NEITHER)
        self.assertIn("0 on daily log", zero.statement)
        self.assertIn("not recorded", absent.statement)


# ══════════════════════════════════════════════════════════════════════════
#  THE LOCATION SHAPE
# ══════════════════════════════════════════════════════════════════════════

class TheLocationShapeIsClosed(unittest.TestCase):

    def test_every_shape_is_reachable(self):
        produced = {m.location_shape(lv.resolve(v)) for v in (
            ["1st floor"], ["1st floor", "All areas"], ["T/O"], ["J"], [])}
        self.assertEqual(
            produced, set(m.LocationShape),
            "a LocationShape member is unreachable: "
            f"{set(m.LocationShape) - produced}")

    def test_scope_beside_an_area_is_its_own_shape(self):
        self.assertIs(m.location_shape(lv.resolve(["1st floor", "All areas"])),
                      m.LocationShape.AREAS_AND_SITEWIDE)


# ══════════════════════════════════════════════════════════════════════════
#  THE GATE DAY, AND THE ROLLOVER
# ══════════════════════════════════════════════════════════════════════════

class TheGateDay(unittest.TestCase):

    def test_check_ins_counts_badge_events_not_people(self):
        gate = m.GateDayState([_row(worker_id="w1"), _row(worker_id="w1")])
        self.assertEqual(gate.check_ins, 2)
        self.assertEqual(gate.on_site, 1, "one man badged twice became two")

    def test_company_counts_and_trades(self):
        gate = m.GateDayState([
            _row(company="Arkon Builders", trade="Framers", worker_id="w1"),
            _row(company="Arkon Builders", trade="Framers", worker_id="w2"),
            _row(company="Quality Plumbing", trade="Plumber", worker_id="w3")])
        self.assertEqual(gate.by_company,
                         {"Arkon Builders": 2, "Quality Plumbing": 1})
        self.assertEqual(gate.trades, ["Framers", "Plumber"])

    def test_UNASSIGNED_keeps_its_headcount_and_loses_its_name(self):
        """A database placeholder is not a contractor, and dropping the row
        would delete a man from the record of who was on site."""
        def display(s):
            return "Pending assignment" if s.upper() == "UNASSIGNED" else s
        gate = m.GateDayState([_row(company="UNASSIGNED", worker_id="w9")],
                              display_company=display)
        self.assertEqual(gate.by_company, {"Pending assignment": 1})
        self.assertEqual(gate.check_ins, 1)

    def test_a_checked_out_worker_is_a_check_in_but_not_on_site(self):
        gate = m.GateDayState([_row(status="checked_out", worker_id="w1")])
        self.assertEqual(gate.check_ins, 1)
        self.assertEqual(gate.on_site, 0)


class TheEasternDayWindowSurvivesTheUtcRollover(unittest.TestCase):
    """THE TEST THAT MATTERS MOST HERE.

    Half past nine in the evening in New York is already the next day in UTC.
    A worker who badges in then belongs on TODAY's report, and a filter that
    slices a UTC timestamp to ten characters puts him on tomorrow's -- which is
    exactly what a probe in this repository did, returning a clean and
    confident wrong answer.

    The window comes from `server.get_day_range_est`, the same function the
    report uses. A second copy of that arithmetic in the model would be the
    drift this whole file exists to prevent.
    """

    def setUp(self):
        import server
        self.window = server.get_day_range_est

    def test_the_window_is_timezone_aware(self):
        """ASSERTED, NOT BRANCHED ON. The first draft of this class handled
        both aware and naive bounds with a conditional, which would have
        quietly passed whichever shape arrived -- including a wrong one."""
        start, end = self.window("2026-08-27")
        self.assertIsNotNone(start.tzinfo)
        self.assertIsNotNone(end.tzinfo)

    def test_a_half_past_nine_check_in_stays_on_the_local_day(self):
        start, end = self.window("2026-08-27")
        # 21:30 EDT on the 27th is 01:30 UTC on the 28th.
        evening = datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc)
        self.assertTrue(
            start <= evening < end,
            "a 21:30 Eastern check-in fell outside its own report day; the "
            "UTC date had already rolled over")

    def test_and_the_UTC_date_really_has_rolled_over(self):
        """THE ANCHOR. Without it the test above could pass on an instant where
        no rollover happens, and prove nothing about the rollover."""
        evening = datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc)
        self.assertEqual(evening.strftime("%Y-%m-%d"), "2026-08-28")

    def test_the_first_minute_of_the_local_day_is_inside_it(self):
        start, end = self.window("2026-08-27")
        # 00:01 EDT on the 27th is 04:01 UTC on the 27th.
        self.assertTrue(
            start <= datetime(2026, 8, 27, 4, 1, tzinfo=timezone.utc) < end)

    def test_the_minute_before_it_is_not(self):
        start, _ = self.window("2026-08-27")
        # 23:59 EDT on the 26th is 03:59 UTC on the 27th: the same UTC DATE as
        # the report day, and outside it.
        before = datetime(2026, 8, 27, 3, 59, tzinfo=timezone.utc)
        self.assertLess(before, start)
        self.assertEqual(before.strftime("%Y-%m-%d"), "2026-08-27",
                         "the anchor: this instant shares the report day's UTC "
                         "date, so a UTC-date filter would wrongly include it")

    def test_the_window_is_not_a_calendar_day_of_UTC(self):
        start, end = self.window("2026-08-27")
        self.assertEqual(start.strftime("%H:%M"), "04:00")
        self.assertEqual((end - start), timedelta(hours=24))

    def test_it_follows_daylight_saving(self):
        """FIVE HOURS IN JANUARY, FOUR IN AUGUST. A hardcoded offset passes
        every summer test and is wrong for five months of the year -- the same
        class of error the roster clock already had to be corrected for."""
        self.assertEqual(self.window("2026-08-27")[0].strftime("%H:%M"), "04:00")
        self.assertEqual(self.window("2026-01-15")[0].strftime("%H:%M"), "05:00")


# ══════════════════════════════════════════════════════════════════════════
#  SAFETY, REQUIRED LOGS, AND THE ONE MODEL BOTH PAGES READ
# ══════════════════════════════════════════════════════════════════════════

class SafetyRefusesToInfer(unittest.TestCase):

    def test_no_superintendent_log_means_no_conclusion(self):
        s = m.SafetyState(None)
        self.assertFalse(s.reported)
        self.assertEqual(s.value, "—")
        self.assertIn("No safety conclusion", s.note)

    def test_it_never_says_no_incidents(self):
        """THE PHRASE, NOT THE WORD. `assertNotIn("incident", ...)` is a bare
        literal: it bans a substring, so it would also refuse an honest
        sentence saying incident reporting lives on the superintendent's log.
        The claim is about the CLAIM -- that nothing here asserts an absence of
        incidents -- so the banned strings are the assertions themselves.
        """
        for log, status in ((None, None), ({"_id": "x"}, None)):
            text = (m.SafetyState(log, status).note + " "
                    + m.SafetyState(log, status).value).lower()
            for claim in ("no incidents", "no incident ", "none reported",
                          "incident-free", "all clear"):
                self.assertNotIn(claim, text, claim)

    def test_a_filed_log_with_a_status_reports_it(self):
        s = m.SafetyState({"_id": "cs"}, "Clear")
        self.assertTrue(s.reported)
        self.assertEqual(s.value, "Clear")
        self.assertEqual(s.note, "")

    def test_a_filed_log_with_no_status_is_still_not_reported(self):
        s = m.SafetyState({"_id": "cs"}, None)
        self.assertFalse(s.reported)


class RequiredLogsKeepsTwoDenominators(unittest.TestCase):

    def setUp(self):
        self.state = m.RequiredLogsState(
            required=["daily_jobsite", "preshift_signin",
                      "site_superintendent_log", "osha_log",
                      "scaffold_maintenance", "toolbox_talk",
                      "subcontractor_orientation"],
            due=["daily_jobsite", "preshift_signin",
                 "site_superintendent_log", "osha_log",
                 "scaffold_maintenance"],
            filed=["daily_jobsite", "preshift_signin", "osha_log",
                   "toolbox_talk", "subcontractor_orientation"])

    def test_the_ratio_counts_only_what_was_owed(self):
        self.assertEqual(self.state.ratio, "3 of 5")

    def test_extras_are_counted_separately_and_never_added_in(self):
        self.assertEqual(len(self.state.extra), 2)
        self.assertNotIn("7", self.state.ratio)

    def test_the_outstanding_records_are_named(self):
        self.assertEqual(sorted(self.state.missing),
                         ["scaffold_maintenance", "site_superintendent_log"])


class BothPagesReadTheSameStatement(unittest.TestCase):
    """THE STRUCTURAL GUARANTEE. Page 2's bands are the same objects as Page
    1's rows, filtered to those with photographs -- not a parallel computation
    that happens to agree today."""

    def _model(self):
        gate = m.GateDayState([_row(company="Quality Plumbing", worker_id=f"w{i}")
                               for i in range(5)])
        acts = [m.ActivityDisplayState(
            _activity(company="Quality Plumbing", workers="7",
                      where="Underground",
                      photos=[{"a": 1}, {"b": 2}]), 0, gate)]
        return m.ReportDisplayModel(
            project={}, date="2026-08-27", gate=gate, activities=acts,
            safety=m.SafetyState(None),
            required_logs=m.RequiredLogsState([], [], []), weather=[])

    def test_the_band_is_the_same_object_as_the_row(self):
        model = self._model()
        self.assertIs(model.bands()[0], model.activities[0])

    def test_the_statement_is_one_string_not_two(self):
        model = self._model()
        self.assertEqual(model.bands()[0].statement,
                         model.activities[0].statement)
        self.assertIn("7 on daily log", model.activities[0].statement)
        self.assertIn("5 gate check-ins", model.activities[0].statement)

    def test_a_row_without_photographs_is_not_a_band(self):
        gate = m.GateDayState([])
        acts = [m.ActivityDisplayState(_activity(photos=[]), 0, gate)]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, acts,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(model.bands(), [])


class AdditionalGateWorkforce(unittest.TestCase):

    def test_a_company_at_the_gate_with_no_activity_row_is_listed(self):
        gate = m.GateDayState(
            [_row(company="Arkon Builders", worker_id="w1"),
             _row(company="MQ Steel", worker_id="w2"),
             _row(company="MQ Steel", worker_id="w3")])
        acts = [m.ActivityDisplayState(_activity(company="Arkon Builders"),
                                       0, gate)]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, acts,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(model.additional_gate, [("MQ Steel", 2)])

    def test_a_company_with_an_activity_row_is_not_listed_twice(self):
        gate = m.GateDayState([_row(company="Arkon Builders", worker_id="w1")])
        acts = [m.ActivityDisplayState(_activity(company="Arkon Builders"),
                                       0, gate)]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, acts,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(model.additional_gate, [])


class TheDayResolvesItsAreasOnce(unittest.TestCase):

    def test_a_floor_on_three_rows_is_one_area(self):
        gate = m.GateDayState([])
        acts = [m.ActivityDisplayState(_activity(where=w), i, gate)
                for i, w in enumerate(["1st floor", "First floor", "1 floor"])]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, acts,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(model.day_location().areas, ["L1"])

    def test_the_day_keeps_every_unmapped_string(self):
        gate = m.GateDayState([])
        acts = [m.ActivityDisplayState(_activity(where=w), i, gate)
                for i, w in enumerate(["1st floor", "J"])]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, acts,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        day = model.day_location()
        self.assertEqual(day.areas, ["L1"])
        self.assertEqual(day.unmapped, ["J"])
        self.assertAlmostEqual(day.coverage, 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
#  THREE STATES PRODUCTION HAS THAT NO MOCKUP DREW
# ══════════════════════════════════════════════════════════════════════════
#
# Found by running the model against four real project-days rather than
# against the record the design was drawn on. Each has a measured population.

class APlaceholderIsNotATrade(unittest.TestCase):
    """One check-in row on production carries UNASSIGNED as its TRADE, and on
    2026-08-16 it made the rail read six trades where five were recorded."""

    def test_it_is_excluded_from_the_count(self):
        gate = m.GateDayState([_row(trade="Framers", worker_id="w1"),
                               _row(trade="UNASSIGNED", worker_id="w2")])
        self.assertEqual(gate.trades, ["Framers"])

    def test_and_reported_rather_than_dropped(self):
        """Silently improving the number is the thing this report does not do."""
        gate = m.GateDayState([_row(trade="Framers", worker_id="w1"),
                               _row(trade="UNASSIGNED", worker_id="w2")])
        self.assertEqual(gate.trades_pending, 1)

    def test_the_worker_is_still_a_check_in(self):
        gate = m.GateDayState([_row(trade="UNASSIGNED", worker_id="w2")])
        self.assertEqual(gate.check_ins, 1)


class AnActivityRowWithNoCompany(unittest.TestCase):
    """11 of 112 activity rows carry no company. One of those carries a
    description AND photographs."""

    def test_a_row_with_substance_prints_and_names_the_gap(self):
        a = m.ActivityDisplayState(
            _activity(company="", workers=None, where="",
                      photos=[{"x": 1}]), 0, m.GateDayState([]))
        a.__class__  # attribute access only; the renderer does no more
        self.assertTrue(a.substantive)
        self.assertFalse(a.named)
        self.assertEqual(a.company_display, m.UNNAMED_CONTRACTOR)

    def test_a_row_carrying_only_a_headcount_still_prints(self):
        """Six rows are exactly this. The number is a record of men on the job
        and dropping it to tidy a heading would delete them."""
        a = m.ActivityDisplayState(_activity(company="", workers="3",
                                             where=""), 0, m.GateDayState([]))
        self.assertTrue(a.substantive)
        self.assertEqual(a.log_count, 3)

    def test_a_row_carrying_nothing_is_a_seed_row(self):
        a = m.ActivityDisplayState(_activity(company="", workers="", where=""),
                                   0, m.GateDayState([]))
        self.assertFalse(a.substantive)

    def test_the_model_drops_seed_rows_and_counts_them(self):
        gate = m.GateDayState([])
        rows = [m.ActivityDisplayState(_activity(company="", workers="",
                                                 where=""), 0, gate),
                m.ActivityDisplayState(_activity(), 1, gate)]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, rows,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(len(model.activities), 1)
        self.assertEqual(model.seed_rows_dropped, 1,
                         "the log had two rows and the report shows one, with "
                         "no record of why")

    def test_an_unnamed_row_does_not_claim_a_gate_company(self):
        """Additional Gate Workforce matches on the REAL name. An unnamed row
        must not absorb a company that has no activity documented."""
        gate = m.GateDayState([_row(company="MQ Steel", worker_id="w1")])
        rows = [m.ActivityDisplayState(
            _activity(company="", workers="2", where=""), 0, gate)]
        model = m.ReportDisplayModel({}, "2026-08-27", gate, rows,
                                     m.SafetyState(None),
                                     m.RequiredLogsState([], [], []), [])
        self.assertEqual(model.additional_gate, [("MQ Steel", 1)])
