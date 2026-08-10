"""eastern_date / eastern_today — the New York calendar day.

`datetime.now(timezone.utc).strftime("%Y-%m-%d")` reads as "just format the
date" and silently means "in UTC". From 20:00 EDT — 19:00 EST — that is
TOMORROW in New York.

The two range helpers (get_today_range_est / get_day_range_est) already bounded
Eastern days correctly, but both return DATETIMES. There was no date-only
companion, so every caller that wanted a day string reached for the UTC one.

Two different failures came out of that, and the second is the serious one:
  * in a QUERY the wrong day is read and the screen looks empty;
  * on a RECORD a logbook is FILED stamped with tomorrow's date. That persists,
    and an inspector reads it.

THESE TESTS PIN THE CLOCK. The defect is invisible before 20:00 Eastern, so a
test reading the real current time would pass all morning and prove nothing.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class EasternDatePinnedClock(unittest.TestCase):
    """Both DST regimes, at and around the boundary that broke."""

    # EDT (UTC-4): the UTC day rolls over at 20:00 Eastern.
    EDT = [
        ("2026-08-09T11:00:00Z", "2026-08-09", "07:00 EDT — shift start"),
        ("2026-08-09T23:59:00Z", "2026-08-09", "19:59 EDT — UTC still agrees"),
        ("2026-08-10T00:00:00Z", "2026-08-09", "20:00 EDT — UTC rolls, Eastern does NOT"),
        ("2026-08-10T01:00:00Z", "2026-08-09", "21:00 EDT — the hour that broke the roster"),
        ("2026-08-10T03:59:00Z", "2026-08-09", "23:59 EDT — same Eastern day"),
        ("2026-08-10T04:00:00Z", "2026-08-10", "00:00 EDT — Eastern midnight"),
    ]
    # EST (UTC-5): an hour earlier.
    EST = [
        ("2026-01-15T23:59:00Z", "2026-01-15", "18:59 EST — UTC agrees"),
        ("2026-01-16T00:00:00Z", "2026-01-15", "19:00 EST — UTC rolls, Eastern does NOT"),
        ("2026-01-16T04:59:00Z", "2026-01-15", "23:59 EST — same Eastern day"),
        ("2026-01-16T05:00:00Z", "2026-01-16", "00:00 EST — Eastern midnight"),
    ]

    def test_eastern_date_at_pinned_instants(self):
        for iso, want, why in self.EDT + self.EST:
            with self.subTest(why=why):
                self.assertEqual(server.eastern_date(_utc(iso)), want, why)

    def test_the_cases_actually_discriminate(self):
        """If UTC and Eastern agreed at these instants the suite would pass on
        the broken code too."""
        at_21 = _utc("2026-08-10T01:00:00Z")
        self.assertEqual(at_21.strftime("%Y-%m-%d"), "2026-08-10")
        self.assertEqual(server.eastern_date(at_21), "2026-08-09")

        at_19_est = _utc("2026-01-16T00:00:00Z")
        self.assertEqual(at_19_est.strftime("%Y-%m-%d"), "2026-01-16")
        self.assertEqual(server.eastern_date(at_19_est), "2026-01-15")

    def test_they_agree_in_the_morning_which_is_why_it_shipped(self):
        morning = _utc("2026-08-09T11:00:00Z")
        self.assertEqual(morning.strftime("%Y-%m-%d"), server.eastern_date(morning))

    def test_eastern_today_delegates_and_returns_a_calendar_day(self):
        today = server.eastern_today()
        self.assertRegex(today, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(today, server.eastern_date(datetime.now(timezone.utc)))

    def test_it_agrees_with_the_range_helper_that_already_existed(self):
        """eastern_date must name the same day get_day_range_est brackets —
        two helpers disagreeing about the boundary would be worse than one."""
        for iso, want, why in self.EDT + self.EST:
            with self.subTest(why=why):
                start, end = server.get_day_range_est(want)
                self.assertTrue(start <= _utc(iso) < end,
                                f"{iso} should fall inside the {want} Eastern day")


class Tier1_TheDateIsWrittenOntoARecord(unittest.TestCase):
    """register_and_checkin files an orientation logbook. Its `date` is a
    compliance record an inspector reads, not a lookup key."""

    def test_the_orientation_logbook_date_is_eastern(self):
        block = _SRC[_SRC.index('"log_type": "subcontractor_orientation"'):]
        block = block[:block.index("status")]
        self.assertIn('"date": eastern_date(now)', block)
        self.assertNotIn('"date": now.strftime', block)


class Tier2_TheDateIsOnlyQueriedWith(unittest.TestCase):

    def test_nightly_compliance_check_uses_eastern(self):
        i = _SRC.index("Nightly compliance check starting")
        block = _SRC[i:i + 600]
        self.assertIn("today = eastern_date(now)", block)
        self.assertNotIn('today = now.strftime("%Y-%m-%d")', block)

    def test_open_items_reads_todays_daily_log_in_eastern(self):
        i = _SRC.index("async def _handle_open_items")
        block = _SRC[i:i + 600]
        self.assertIn("today_str = eastern_today()", block)
        self.assertNotIn('today_str = datetime.now(timezone.utc).strftime', block)


class ConfirmedCorrectSitesAreUntouched(unittest.TestCase):
    """Not every UTC day string is a defect. These were checked and left."""

    def test_the_email_dedupe_key_is_still_utc(self):
        """An idempotency key only has to be unique per rotation. It is NOT a
        calendar date and must not be 'fixed' into one."""
        i = _SRC.index("re-send to the same recipient if the cron fires twice")
        block = _SRC[i:i + 400]
        self.assertIn('date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")', block)

    def test_the_zoneinfo_sites_still_prefer_eastern(self):
        """Four sites already did this correctly, with UTC only as an except
        fallback. Those fallbacks are legitimate and stay."""
        self.assertGreaterEqual(
            len(re.findall(r'astimezone\(ZoneInfo\("America/New_York"\)\)', _SRC)), 4
        )


class NoUnconvertedCalendarDatesRemain(unittest.TestCase):

    def test_no_utc_day_string_outside_the_known_exceptions(self):
        """A regression guard on the PATTERN, not on a file list — a new caller
        reaching for the UTC day fails here."""
        # Narrow on purpose. The defect is NOT "formats a date" — plenty of
        # lines legitimately format an expiry, a deadline or an already-Eastern
        # instant. It is specifically formatting the CURRENT UTC INSTANT as a
        # calendar day, which is what silently means "tomorrow" after 20:00
        # Eastern.
        CURRENT_UTC_AS_DAY = re.compile(
            r'^[^\n#]*(?:datetime\.now\(timezone\.utc\)|utcnow\(\)|(?<![\w.])now)'
            r'\.strftime\("%Y-%m-%d"\)'
        )
        offenders = []
        for m in CURRENT_UTC_AS_DAY.finditer(_SRC):
            line = m.group(0).strip()
            if "`" in line:
                continue          # prose in a docstring quoting the bad pattern
            if "astimezone" in line or "eastern" in line or "est_" in line or "_nt_" in line:
                continue          # already converted to Eastern before formatting
            if "date_key" in line:
                continue          # the idempotency key, asserted above
            offenders.append(line)
        self.assertEqual(offenders, [], f"UTC calendar dates left: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
