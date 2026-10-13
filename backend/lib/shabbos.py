"""Shabbos and Yom Tov in New York: when chasing must be quiet.

"Shabbos / Yom Tov off" (a job's chase setting): no chasing or nudges from
ONE HOUR BEFORE candle-lighting on Friday (or erev Yom Tov) through ONE HOUR
AFTER nightfall at its end. Back-to-back days -- the two days of Yom Tov, Yom
Tov next to Shabbos -- are one quiet stretch.

Computed, no network:
  * sunset in New York City (NOAA's solar equations, 40.7128 N 74.0060 W);
  * candle-lighting = sunset - 18 min, nightfall = sunset + 42 min (Hebcal's
    New York defaults);
  * the Yom Tov days from the fixed Hebrew calendar (Dershowitz & Reingold,
    "Calendrical Calculations"), diaspora: Rosh Hashana (2), Yom Kippur,
    Sukkot (2), Shemini Atzeret / Simchat Torah (2), Pesach (2 + 2), Shavuot
    (2).

Pure: no database, no server import.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
LAT, LON = 40.7128, -74.0060
CANDLES_BEFORE_SUNSET = timedelta(minutes=18)
NIGHTFALL_AFTER_SUNSET = timedelta(minutes=42)
MARGIN = timedelta(hours=1)


# ── SUNSET (NOAA) ───────────────────────────────────────────────────────────

def sunset(day: date) -> datetime:
    """Sunset in New York City on `day` (an aware datetime, UTC)."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat = math.radians(LAT)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))
              - math.tan(lat) * math.tan(decl))
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    minutes = 720 - 4 * (LON - ha) - eqtime            # UTC minutes after midnight
    return datetime.combine(day, time(0), tzinfo=timezone.utc) + timedelta(minutes=minutes)


def candle_lighting(day: date) -> datetime:
    return sunset(day) - CANDLES_BEFORE_SUNSET


def nightfall(day: date) -> datetime:
    return sunset(day) + NIGHTFALL_AFTER_SUNSET


# ── THE HEBREW CALENDAR ─────────────────────────────────────────────────────

_HEBREW_EPOCH = -1373427            # R.D. of 1 Tishrei, year 1 (date.toordinal() is R.D.)


def _elapsed_days(y: int) -> int:
    months = (235 * y - 234) // 19
    parts = 12084 + 13753 * months
    days = 29 * months + parts // 25920
    return days + 1 if (3 * (days + 1)) % 7 < 3 else days


def _correction(y: int) -> int:
    ny0, ny1, ny2 = _elapsed_days(y - 1), _elapsed_days(y), _elapsed_days(y + 1)
    if ny2 - ny1 == 356:
        return 2
    if ny1 - ny0 == 382:
        return 1
    return 0


def _new_year(y: int) -> int:
    """R.D. of 1 Tishrei of Hebrew year `y`."""
    return _HEBREW_EPOCH + _elapsed_days(y) + _correction(y)


def _leap(y: int) -> bool:
    return (7 * y + 1) % 19 < 7


def _nisan_1(y: int) -> int:
    """R.D. of 1 Nisan of Hebrew year `y` (the spring after its Tishrei)."""
    length = _new_year(y + 1) - _new_year(y)
    cheshvan = 30 if length % 10 == 5 else 29
    kislev = 29 if length % 10 == 3 else 30
    return _new_year(y) + 30 + cheshvan + kislev + 29 + 30 + (30 if _leap(y) else 0) + 29


@lru_cache(maxsize=64)
def yom_tov_days(year: int) -> Tuple[date, ...]:
    """The Yom Tov days (no work) in Gregorian `year`, New York (diaspora)."""
    out = []
    for hy in (year + 3760, year + 3761):
        t = _new_year(hy)
        n = _nisan_1(hy)
        for rd in (t, t + 1, t + 9, t + 14, t + 15, t + 21, t + 22,      # RH, YK, Sukkot, ShA/ST
                   n + 14, n + 15, n + 20, n + 21,                        # Pesach
                   n + 59 + 5, n + 59 + 6):                               # Shavuot (6-7 Sivan)
            d = date.fromordinal(rd)
            if d.year == year:
                out.append(d)
    return tuple(sorted(set(out)))


def is_rest_day(day: date) -> bool:
    """Shabbos (Saturday) or a Yom Tov day."""
    return day.weekday() == 5 or day in yom_tov_days(day.year)


# ── THE QUIET WINDOW ────────────────────────────────────────────────────────

def window(day: date) -> Tuple[datetime, datetime]:
    """The quiet stretch around the rest day `day` -- extended over the rest
    days next to it: one hour before candle-lighting the evening before the
    first, through one hour after nightfall on the last."""
    first = last = day
    while is_rest_day(first - timedelta(days=1)):
        first -= timedelta(days=1)
    while is_rest_day(last + timedelta(days=1)):
        last += timedelta(days=1)
    return (candle_lighting(first - timedelta(days=1)) - MARGIN, nightfall(last) + MARGIN)


def is_quiet(at: datetime) -> bool:
    """Shabbos or Yom Tov (with the hour either side) at `at` in New York."""
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    today = at.astimezone(NY).date()
    for d in (today, today + timedelta(days=1)):
        if is_rest_day(d):
            start, end = window(d)
            if start <= at <= end:
                return True
    return False


def quiet_until(at: datetime) -> Optional[datetime]:
    """When the quiet stretch `at` falls in ends (one hour after nightfall
    on its last rest day), or None when `at` is not in one."""
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    today = at.astimezone(NY).date()
    for d in (today, today + timedelta(days=1)):
        if is_rest_day(d):
            start, end = window(d)
            if start <= at <= end:
                return end
    return None


def is_sunday(at: datetime) -> bool:
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return at.astimezone(NY).weekday() == 6


def times(day: date) -> List[str]:
    """For a reader: "Fri Oct 9: candles 6:03 PM, Sat Oct 10: nightfall 7:01 PM"."""
    s, e = window(day)
    return [f"quiet from {s.astimezone(NY):%a %b %-d %-I:%M %p}",
            f"to {e.astimezone(NY):%a %b %-d %-I:%M %p}"]
