"""588 THOMAS FILED 33 TOOLBOX TALKS IN 35 WORKING DAYS.

── THE DEFECT, AND IT IS A NUMBER ──────────────────────────────────────────

`toolbox_talk` is weekly. The CP's logbook list renders `required_logbooks` and
asks `todayLogs[type]` for each tile's status, which is a by-DATE read — so on
every day except the one it was filed the tile said "pending" and the completion
bar counted it against him.

    588 Thomas   35 working days, 33 toolbox talks filed
    857 Prescott 10 working days,  2 filed, 8 red mornings

Two projects, two opposite outcomes, one cause: a red tile every morning is an
instruction, and a CP either obeys it five times a week or learns to ignore it.

THE SERVER ALREADY KNEW BETTER. `daily_required_logbooks` keeps weekly and
as-needed types out of the nightly deficiency sweep, on its own written
reasoning that counting them "invents a deficiency out of a frequency". The
screen had no equivalent. Now the payload carries `periods` and it does.

── THE WEEK IS MONDAY TO FRIDAY ────────────────────────────────────────────

Operator ruling. Saturday and Sunday belong to the week BEFORE them, which is
what `date.weekday()` already does (Mon=0 … Sun=6) — so no arithmetic here
decides it and no off-by-one can be introduced by editing a constant.

A talk given ON a Saturday still satisfies that Mon–Fri week: the week is when
the obligation falls, not when the talk may be given. That is why `week_span`
reaches Sunday while the reported period ends on Friday, and it is the single
most likely thing to be "simplified" into a bug.

── AND A WEEKEND WORKER RE-OPENS IT ────────────────────────────────────────

Operator ruling: a worker on site Saturday or Sunday who has not attended that
week's talk makes it due. That is the case a plain weekly rule swallows — a
crew called in on Saturday for a pour, on a week whose talk was given on
Tuesday to somebody else, is a crew nobody has spoken to.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.logbook.weekly_cadence import (  # noqa: E402
    NOT_FILED,
    WEEKEND_UNCOVERED,
    as_date,
    is_weekend,
    toolbox_period,
    week_span,
    work_week,
)

#: A real week: Monday 2026-09-14 … Sunday 2026-09-20. 588 Thomas filed a
#: daily log on every weekday of it.
MON, TUE, WED, THU, FRI, SAT, SUN = (
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
    "2026-09-18", "2026-09-19", "2026-09-20",
)
PREV_FRI = "2026-09-11"
NEXT_MON = "2026-09-21"


class TheWeekIsMondayToFriday(unittest.TestCase):

    def test_every_weekday_resolves_to_the_same_week(self):
        want = (date(2026, 9, 14), date(2026, 9, 18))
        for day in (MON, TUE, WED, THU, FRI):
            with self.subTest(day):
                self.assertEqual(work_week(day), want)

    def test_the_weekend_belongs_to_the_week_BEFORE_it(self):
        """A Saturday is the weekend OF a working week, not the start of the
        next one. If this ever reads 2026-09-21, a Saturday crew is being
        measured against a talk that has not been given yet."""
        want = (date(2026, 9, 14), date(2026, 9, 18))
        for day in (SAT, SUN):
            with self.subTest(day):
                self.assertEqual(work_week(day), want)

    def test_the_next_monday_starts_a_new_week(self):
        self.assertEqual(work_week(NEXT_MON),
                         (date(2026, 9, 21), date(2026, 9, 25)))

    def test_the_span_read_reaches_SUNDAY_though_the_period_ends_FRIDAY(self):
        """THE ONE THING MOST LIKELY TO BE SIMPLIFIED INTO A BUG.

        The period the CP is told about is Mon–Fri. The query that looks for a
        filed talk must reach Sunday, because a talk given on a Saturday still
        satisfies that week. Making them the same range loses it."""
        self.assertEqual(week_span(WED), (MON, SUN))
        row = toolbox_period(WED)
        self.assertEqual((row["period_start"], row["period_end"]), (MON, FRI))

    def test_is_weekend(self):
        for day, want in ((FRI, False), (SAT, True), (SUN, True), (MON, False)):
            with self.subTest(day):
                self.assertIs(is_weekend(day), want)

    def test_it_is_total_on_junk(self):
        """A cadence helper that raises takes down the screen a CP files a
        statutory record from."""
        for bad in (None, "", "not a date", "2026-13-45", 7, object()):
            with self.subTest(repr(bad)):
                self.assertIsNone(as_date(bad))
                self.assertIsNone(work_week(bad))
                self.assertIsNone(week_span(bad))
                self.assertEqual(toolbox_period(bad), {})


class OneTalkSatisfiesTheWeek(unittest.TestCase):

    def test_a_talk_on_tuesday_satisfies_wednesday(self):
        row = toolbox_period(WED, filed_dates=[TUE])
        self.assertTrue(row["satisfied"])
        self.assertIsNone(row["due_reason"])
        self.assertEqual(row["filed_on"], [TUE])

    def test_and_it_satisfies_every_other_day_of_that_week(self):
        """THE WHOLE DEFECT IN ONE ASSERTION. Before this, four of these five
        days rendered a pending tile and cost him a point on the bar."""
        for day in (MON, TUE, WED, THU, FRI):
            with self.subTest(day):
                self.assertTrue(toolbox_period(day, filed_dates=[TUE])["satisfied"])

    def test_a_talk_given_ON_A_SATURDAY_satisfies_that_week(self):
        self.assertTrue(toolbox_period(WED, filed_dates=[SAT])["satisfied"])

    def test_LAST_weeks_talk_does_not(self):
        row = toolbox_period(WED, filed_dates=[PREV_FRI])
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], NOT_FILED)
        self.assertEqual(row["filed_on"], [])

    def test_and_neither_does_NEXT_weeks(self):
        self.assertFalse(
            toolbox_period(WED, filed_dates=[NEXT_MON])["satisfied"])

    def test_nothing_filed_is_due(self):
        row = toolbox_period(WED)
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], NOT_FILED)


class AWeekendWorkerReOpensIt(unittest.TestCase):
    """THE CASE A PLAIN WEEKLY RULE SWALLOWS."""

    def test_a_weekend_worker_who_missed_the_talk_makes_it_due_again(self):
        row = toolbox_period(
            SAT, filed_dates=[TUE],
            weekend_worker_ids=["w1", "w2"], covered_worker_ids=["w1"])
        self.assertFalse(row["satisfied"])
        self.assertEqual(row["due_reason"], WEEKEND_UNCOVERED)

    def test_and_it_NAMES_him(self):
        """"Due again" tells a CP to give a talk. "Due again — w2 was not at
        it" tells him who he is talking to, and stops him reading the card as
        the app having lost the talk he gave on Tuesday."""
        row = toolbox_period(
            SAT, filed_dates=[TUE],
            weekend_worker_ids=["w1", "w2"], covered_worker_ids=["w1"])
        self.assertEqual(row["uncovered_weekend_workers"], ["w2"])

    def test_a_weekend_worker_who_WAS_at_it_changes_nothing(self):
        row = toolbox_period(
            SAT, filed_dates=[TUE],
            weekend_worker_ids=["w1"], covered_worker_ids=["w1", "w9"])
        self.assertTrue(row["satisfied"])
        self.assertEqual(row["uncovered_weekend_workers"], [])

    def test_an_uncovered_weekend_worker_with_NO_talk_reads_NOT_FILED(self):
        """ORDER OF THE TWO REASONS. With no talk at all the answer is "give
        one", not "these men missed the one you gave" — the second sentence
        describes a talk that does not exist."""
        row = toolbox_period(
            SAT, weekend_worker_ids=["w1"], covered_worker_ids=[])
        self.assertEqual(row["due_reason"], NOT_FILED)

    def test_a_WEEKDAY_absentee_does_not_re_open_it(self):
        """SCOPED TO THE WEEKEND, on purpose. A worker who joins on Wednesday
        and misses the talk is already listed in `missing_toolbox_talk`, which
        names every uncovered worker on the project. This rule answers a
        different question — whether the LOG is due again — and the operator
        scoped it to weekend work."""
        row = toolbox_period(WED, filed_dates=[TUE],
                             weekend_worker_ids=[], covered_worker_ids=[])
        self.assertTrue(row["satisfied"])

    def test_ids_are_compared_as_strings(self):
        """ObjectId on one side and str on the other is how a set difference
        silently reports everybody as uncovered."""
        row = toolbox_period(SAT, filed_dates=[TUE],
                             weekend_worker_ids=[123], covered_worker_ids=["123"])
        self.assertTrue(row["satisfied"])


class TheServerWiresItIn(unittest.TestCase):
    """The rule is pure; these assert it is REACHED."""

    def setUp(self):
        self.src = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_the_payload_carries_periods(self):
        self.assertIn('"periods": await _logbook_periods(', self.src)

    def test_the_read_uses_the_seven_day_span(self):
        """`week_span` is what reaches Sunday. A hand-built Mon–Fri range here
        would lose a talk given at the weekend and the period rule would never
        see it."""
        block = self.src[self.src.index("async def _toolbox_period_rows"):]
        block = block[:block.index("\n\n\n")]
        self.assertIn("monday, sunday = span", block)
        self.assertIn('"$gte": monday, "$lte": sunday', block)

    def test_the_weekend_read_uses_the_EASTERN_day_range(self):
        """`check_in_time` is a datetime and the logbook date is an Eastern day
        string. Building the weekend window from UTC midnight buckets a
        Saturday-evening check-in into Sunday — the bug this file's sibling
        helpers exist to prevent, and it has shipped thirteen times."""
        block = self.src[self.src.index("async def _toolbox_period_rows"):]
        block = block[:block.index("\n\n\n")]
        self.assertIn("get_day_range_est(iso)", block)

    def test_it_is_failure_isolated(self):
        """This is on the CP's critical path. A cadence hint is never worth a
        blank logbook list."""
        block = self.src[self.src.index("async def _logbook_periods"):]
        block = block[:block.index("async def _toolbox_period_rows")]
        self.assertIn("except Exception", block)
        self.assertIn("return []", block)

    def test_it_costs_nothing_on_a_project_without_the_type(self):
        """THE GUARD NOW NAMES THREE TYPES, and it used to name one, then two.

        `_logbook_periods` returned [] unless `toolbox_talk` was required.
        `subcontractor_orientation` is as_needed and got a row on the same
        channel; `hot_work` is as_needed too and got one when the operator
        ruled on when a hot-work log is due ("due only on days hot work
        happens... dated, not persistent").

        THE PROPERTY THIS TEST HAS ALWAYS HELD TO IS UNCHANGED: a project that
        requires none of them pays for no query, and each type's reads sit
        behind its own membership test so requiring one never pays for the
        others.

        THE GUARD IS A SET INTERSECTION NOW, not a chain of `not in`. Three
        `and`-ed negations is where a fourth gets forgotten, and the shape is
        asserted rather than the spelling of any one type -- the census below
        is what a new type has to move.
        """
        block = self.src[self.src.index("async def _logbook_periods"):]
        block = block[:block.index("async def _toolbox_period_rows")]
        guard = block.index('if not ({"toolbox_talk", '
                            '"subcontractor_orientation", "hot_work"} & set(req)):')
        for read in ("_toolbox_period_rows(project_id",
                     "_orientation_period_rows(project_id",
                     "_hot_work_period_rows("):
            with self.subTest(read=read):
                self.assertLess(guard, block.index(read))
        # Each type's reads still happen ONLY for a project that requires it.
        for key, read in (('if "toolbox_talk" in req:',
                           "_toolbox_period_rows(project_id"),
                          ('if "subcontractor_orientation" in req:',
                           "_orientation_period_rows(project_id"),
                          ('if "hot_work" in req:', "_hot_work_period_rows(")):
            with self.subTest(key=key):
                self.assertLess(block.index(key), block.index(read))


if __name__ == "__main__":
    unittest.main(verbosity=2)
