"""Working days: weekdays minus U.S. federal holidays, from the first activity."""
import unittest
from datetime import date

from lib import report_calendar as C


class WorkingDays(unittest.TestCase):
    def test_federal_holidays_2026(self):
        h = C.holidays(2026)
        self.assertEqual(h[date(2026, 9, 7)], "Labor Day")
        self.assertEqual(h[date(2026, 10, 12)], "Columbus Day")
        self.assertEqual(h[date(2026, 11, 26)], "Thanksgiving")
        self.assertEqual(h[date(2026, 12, 25)], "Christmas Day")

    def test_observed_when_on_a_weekend(self):
        self.assertIn(date(2026, 7, 3), C.holidays(2026))      # Jul 4 is a Saturday

    def test_a_week_has_five_days_unless_a_holiday(self):
        self.assertEqual(len(C.working_days(date(2026, 10, 5), date(2026, 10, 9))), 5)
        self.assertEqual(len(C.working_days(date(2026, 10, 5), date(2026, 10, 16))), 9)

    def test_a_holiday_that_was_worked_counts(self):
        d = date(2026, 10, 12)
        self.assertIn(d, C.working_days(date(2026, 10, 5), date(2026, 10, 16), worked=[d]))

    def test_nothing_before_the_first_activity(self):
        days = C.working_days(date(2026, 10, 1), date(2026, 10, 9), first_activity=date(2026, 10, 6))
        self.assertEqual(days[0], date(2026, 10, 6))

    def test_empty_range(self):
        self.assertEqual(C.working_days(date(2026, 10, 9), date(2026, 10, 1)), [])


if __name__ == "__main__":
    unittest.main()
