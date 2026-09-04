"""THE PHOTO SET CLOSES AT THE END OF THAT LOG'S DAY.

THE RULING. A photograph may be added to or removed from a log until the end of
that log's day. After that the photo set is closed -- no removal, no append, no
exceptions. It is a CLOCK, not a permission model: there is no per-photo rule,
no `added_after_filing` predicate, no chain-walk and no tombstone. Who you are
and whether the log is signed do not enter into it.

END OF DAY IS THE SWEEP'S OWN BOUNDARY: 03:00 America/New_York on the day AFTER
the log's `date`. Not midnight. `sweep_stale_end_of_day_logs` is what already
decides a daily narrative is over, and it runs on
`CronTrigger(hour=3, minute=0, timezone="America/New_York")` -- so 03:00 is the
instant the record actually stops being live, and a midnight rule would invent a
SECOND end-of-day three hours earlier than the one the system observes.

It also buys the two cases the operator named. A log filed at 23:00 gets four
hours instead of one. And the night-shift CP who files at 02:00 for the shift
that ended last night (`date` = yesterday) gets an hour -- where a midnight rule
would have shut his window BEFORE HE PRESSED SUBMIT, leaving him a log he could
never attach a photograph to and no action that could change that.

THE ARITHMETIC IS A STRING COMPARISON, ON PURPOSE:

    window_day(now) = eastern_date(now - 3 hours)
    open  <=>  logbook["date"] >= window_day(now)

Subtracting three hours is a pure UTC subtraction and the only timezone call is
`eastern_date`, which both halves of the system already have. Everything after
that compares 'YYYY-MM-DD' strings, so the backend and
frontend/src/utils/logbookEditable.js cannot drift, and DST cannot move the
answer -- there is no offset anywhere to be wrong about.

FAIL CLOSED ON A LOG WITH NO DATE. A logbook without one is not a thing the
create path can produce (it is the dedupe key), and of the two ways to be wrong,
refusing a photograph is recoverable by a conversation while appending to a
closed compliance record is not.

WHY THE REFUSAL IS 409 AND NOT 423. 423 says "locked", and the log frequently is
not: `sweep_stale_end_of_day_logs` deliberately declines to freeze a stale
UNSIGNED narrative, so those sit `is_locked: false` forever. 409 follows the
convention this file's neighbours already set -- FILED_LOG_DATA_IMMUTABLE,
FILED_LOG_PHOTO_CAPTURE_REFUSED, LOGBOOK_WITHDRAWN -- where the server names the
condition and the client owns the wording.

AND WHY 4xx AT ALL IS LOAD-BEARING. `shouldQueueError` in
frontend/src/utils/filedPhotoQueue.js retains a queued photograph on 5xx or a
network failure and DROPS it on any 4xx. A 5xx here would make a phone in the
field retry a photograph for a permanently closed log at every app launch,
forever.

    python -m pytest tests/test_photo_window_rule.py -q
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
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

from tests.test_filed_log_photo_append import (  # noqa: E402
    _FakeR2, _filed_log, _post,
)


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# 2026-08-12 is EDT (UTC-4), so 03:00 Eastern is 07:00 UTC that morning.
EDT_0259 = _utc(2026, 8, 13, 6, 59)   # 02:59 Eastern on the 13th
EDT_0300 = _utc(2026, 8, 13, 7, 0)    # 03:00 Eastern on the 13th

# 2026-01-15 is EST (UTC-5), so 03:00 Eastern is 08:00 UTC.
EST_0259 = _utc(2026, 1, 16, 7, 59)
EST_0300 = _utc(2026, 1, 16, 8, 0)


# ══════════════════════════════════════════════════════════════════════════
#  1. THE BOUNDARY ITSELF
# ══════════════════════════════════════════════════════════════════════════

class TheWindowDayIsTheSweepsOwnBoundary(unittest.TestCase):

    def test_window_day_is_the_eastern_date_three_hours_ago(self):
        # 02:59 Eastern on the 13th: three hours earlier is 23:59 on the 12th,
        # so the day whose photo sets are still open is still the 12th.
        self.assertEqual(server.logbook_photo_window_day(EDT_0259), "2026-08-12")

    def test_it_rolls_at_0300_eastern_not_at_midnight(self):
        self.assertEqual(server.logbook_photo_window_day(EDT_0300), "2026-08-13")

    def test_the_same_boundary_holds_in_standard_time(self):
        # EST is UTC-5 rather than UTC-4. If the boundary were computed from a
        # hardcoded offset instead of the zone, one of these two would be wrong.
        self.assertEqual(server.logbook_photo_window_day(EST_0259), "2026-01-15")
        self.assertEqual(server.logbook_photo_window_day(EST_0300), "2026-01-16")

    def test_midnight_eastern_does_not_close_anything(self):
        # THE WHOLE POINT of choosing the sweep's boundary over the operator's
        # first instinct. At 00:30 Eastern on the 13th the 12th is still open.
        self.assertEqual(
            server.logbook_photo_window_day(_utc(2026, 8, 13, 4, 30)), "2026-08-12")


class TheWindowIsOpenUntilThatBoundary(unittest.TestCase):

    def test_todays_log_is_open(self):
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-12"}, now=_utc(2026, 8, 12, 18)))

    def test_yesterdays_log_is_open_until_0300(self):
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-12"}, now=EDT_0259))

    def test_yesterdays_log_is_closed_at_0300(self):
        self.assertFalse(server.logbook_photo_window_is_open(
            {"date": "2026-08-12"}, now=EDT_0300))

    def test_an_older_log_is_closed_at_every_hour(self):
        for hh in range(0, 24):
            with self.subTest(hour=hh):
                self.assertFalse(server.logbook_photo_window_is_open(
                    {"date": "2026-08-01"}, now=_utc(2026, 8, 13, hh)))

    def test_the_23_00_filer_gets_four_hours_not_one(self):
        # Filed at 23:00 Eastern on the 12th (03:00 UTC on the 13th). The
        # operator's own objection to the midnight rule, answered.
        filed_at = _utc(2026, 8, 13, 3, 0)
        log = {"date": "2026-08-12"}
        self.assertTrue(server.logbook_photo_window_is_open(log, now=filed_at))
        self.assertTrue(server.logbook_photo_window_is_open(
            log, now=filed_at + timedelta(hours=3, minutes=59)))
        self.assertFalse(server.logbook_photo_window_is_open(
            log, now=filed_at + timedelta(hours=4)))


class TheLogFiledAtTwoInTheMorning(unittest.TestCase):
    """The case the operator asked to be spelled out."""

    def test_stamped_with_today_it_has_a_full_day_ahead_of_it(self):
        # 02:00 Eastern on the 13th, log dated the 13th. window_day is the 12th,
        # so "2026-08-13" >= "2026-08-12" -- open, and open until 03:00 on the
        # 14th: about twenty-five hours.
        at_0200 = _utc(2026, 8, 13, 6, 0)
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-13"}, now=at_0200))
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-13"}, now=_utc(2026, 8, 14, 6, 59)))
        self.assertFalse(server.logbook_photo_window_is_open(
            {"date": "2026-08-13"}, now=_utc(2026, 8, 14, 7, 0)))

    def test_the_night_shift_writeup_gets_an_hour_rather_than_nothing(self):
        # 02:00 Eastern on the 13th, log dated the 12th -- the shift that ended
        # last night. Open for one more hour. Under a midnight rule this window
        # would already have been shut at the moment he filed.
        at_0200 = _utc(2026, 8, 13, 6, 0)
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-12"}, now=at_0200))
        self.assertFalse(server.logbook_photo_window_is_open(
            {"date": "2026-08-12"}, now=EDT_0300))


class ItIsAClockAndNotAPermissionModel(unittest.TestCase):

    def test_status_and_lock_do_not_enter_into_it(self):
        # A draft, a submitted log and a frozen log dated the same day all get
        # the same answer, in both directions. If any of these diverged, the
        # rule would have become a permission model.
        for extra in ({"status": "draft", "is_locked": False},
                      {"status": "submitted", "is_locked": False},
                      {"status": "submitted", "is_locked": True},
                      {"status": "withdrawn"}):
            with self.subTest(**extra):
                open_log = dict(extra, date="2026-08-12")
                self.assertTrue(server.logbook_photo_window_is_open(
                    open_log, now=EDT_0259))
                self.assertFalse(server.logbook_photo_window_is_open(
                    open_log, now=EDT_0300))

    def test_no_photo_field_is_consulted(self):
        # `added_after_filing` is a RECORD of what the server did, and the
        # ruling forbids it becoming a PREDICATE. The window never sees a photo.
        log = {"date": "2026-08-12", "data": {"activities": [
            {"activity_id": "a", "photos": [{"added_after_filing": True}]}]}}
        self.assertFalse(server.logbook_photo_window_is_open(log, now=EDT_0300))

    def test_log_type_does_not_enter_into_it(self):
        # One rule for every type. The ruling says "that log's day", not
        # "end-of-day logs only", and LOGBOOK_TIMING_CLASS is not consulted.
        for lt in ("daily_jobsite", "fall_protection", "site_superintendent_log",
                   "ssc_daily_safety_log", "hot_work"):
            with self.subTest(log_type=lt):
                self.assertFalse(server.logbook_photo_window_is_open(
                    {"date": "2026-08-12", "log_type": lt}, now=EDT_0300))


class ItFailsClosed(unittest.TestCase):

    def test_a_log_with_no_date_is_closed(self):
        for doc in ({}, {"date": None}, {"date": ""}, {"date": "   "}):
            with self.subTest(doc=doc):
                self.assertFalse(server.logbook_photo_window_is_open(
                    doc, now=_utc(2026, 8, 12, 18)))

    def test_an_unparseable_date_is_closed(self):
        for bad in ("not-a-date", "08/12/2026", "2026-8-12", 20260812, []):
            with self.subTest(bad=bad):
                self.assertFalse(server.logbook_photo_window_is_open(
                    {"date": bad}, now=_utc(2026, 8, 12, 18)))

    def test_a_non_document_is_closed(self):
        for junk in (None, "", [], 0):
            with self.subTest(junk=junk):
                self.assertFalse(server.logbook_photo_window_is_open(
                    junk, now=_utc(2026, 8, 12, 18)))

    def test_a_datetime_date_field_is_read_not_rejected(self):
        # Some legacy rows carry a datetime rather than the 'YYYY-MM-DD' string.
        # Failing those closed would refuse a photograph for a log that is
        # plainly today's, so the leading ten characters are taken.
        self.assertTrue(server.logbook_photo_window_is_open(
            {"date": "2026-08-12T00:00:00+00:00"}, now=_utc(2026, 8, 12, 18)))


# ══════════════════════════════════════════════════════════════════════════
#  2. THE ENDPOINT REFUSES AFTER CLOSE
#
#  These drive the real route through the doubles in
#  test_filed_log_photo_append. They use dates far enough in the past that the
#  wall clock cannot make them flap, and today's Eastern date for the open case
#  -- which is inside the window at every hour, since window_day is never
#  later than today.
# ══════════════════════════════════════════════════════════════════════════

class TheAppendEndpointRefusesAfterClose(unittest.TestCase):

    def test_a_stale_log_is_refused_409_photo_window_closed(self):
        resp, lb = _post(_filed_log(date="2026-08-12"))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "PHOTO_WINDOW_CLOSED")

    def test_the_refusal_names_the_day_that_ended(self):
        resp, _ = _post(_filed_log(date="2026-08-12"))
        self.assertEqual(resp.json()["detail"].get("closed_after"), "2026-08-12")

    def test_it_is_4xx_so_the_offline_queue_stops_retrying(self):
        # filedPhotoQueue.shouldQueueError retains on 5xx and drops on 4xx. A
        # 5xx here would retry a closed log forever on every app launch.
        resp, _ = _post(_filed_log(date="2026-08-12"))
        self.assertTrue(400 <= resp.status_code < 500, resp.status_code)

    def test_it_is_not_423(self):
        # 423 says "locked". A stale UNSIGNED narrative is never locked -- the
        # sweep declines to freeze it -- so 423 would be a false statement about
        # the document in exactly the case this gate exists for.
        resp, _ = _post(_filed_log(date="2026-08-12", status="draft",
                                   is_locked=False, cp_signature={}))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "PHOTO_WINDOW_CLOSED")

    def test_nothing_is_written_to_the_document(self):
        doc = _filed_log(date="2026-08-12")
        before = len(((doc["data"])["activities"])[1]["photos"])
        _, lb = _post(doc)
        after = ((lb.doc.get("data") or {}).get("activities") or [])[1].get("photos") or []
        self.assertEqual(len(after), before)
        self.assertNotIn("updated_at_touched", lb.doc)

    def test_nothing_is_put_in_r2(self):
        # THE REFUSAL COSTS NO STORAGE AND NO TRANSFER, which is the ordering
        # principle upload_logbook_photo already states -- and it matters more
        # here than there, because nothing in this system ever reclaims an
        # orphaned object (see docs/audits/photo-window-rule.md).
        r2 = _FakeR2()
        resp, _ = _post(_filed_log(date="2026-08-12"), r2=r2)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(r2.puts, [])

    def test_a_log_with_no_date_is_refused(self):
        resp, _ = _post(_filed_log(date=None))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "PHOTO_WINDOW_CLOSED")

    def test_todays_log_still_appends(self):
        # The feature is not broken by the gate: the whole of
        # test_filed_log_photo_append rides on this staying true.
        r2 = _FakeR2()
        resp, _ = _post(_filed_log(date=server.eastern_date()), r2=r2)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(r2.puts), 1)


class TheGateSitsAboveTheBytes(unittest.TestCase):

    def test_an_oversized_photo_for_a_closed_log_is_refused_for_the_window(self):
        # If the window check sat below the file read, this would be a 400 about
        # the size -- and the server would have read 16MB off the wire to say so.
        big = b"\xff\xd8\xff\xe0" + b"\x00" * (16 * 1024 * 1024)
        resp, _ = _post(_filed_log(date="2026-08-12"), content=big)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "PHOTO_WINDOW_CLOSED")

    def test_a_non_image_for_a_closed_log_is_refused_for_the_window(self):
        resp, _ = _post(_filed_log(date="2026-08-12"),
                        content=b"%PDF-1.4\nnot a photograph")
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "PHOTO_WINDOW_CLOSED")


class TheRefusalsThatComeFirstStillCome(unittest.TestCase):
    """Authorization and identity are decided BEFORE the clock.

    A caller who may not see the log must not learn from a 409 that the log
    exists and what day it is on -- the window refusal names a date, and that is
    a fact about the record.
    """

    def test_an_outsider_gets_404_not_the_window_refusal(self):
        outsider = {"_id": "x", "id": "x", "role": "cp", "company_id": "other_co",
                    "account_status": "approved", "assigned_projects": []}
        resp, _ = _post(_filed_log(date="2026-08-12"), user=outsider)
        self.assertNotEqual(resp.status_code, 409)
        self.assertIn(resp.status_code, (403, 404), resp.text)


# ══════════════════════════════════════════════════════════════════════════
#  3. THE CLIENT CARRIES THE SAME BOUNDARY
# ══════════════════════════════════════════════════════════════════════════

class TheDeviceComputesTheSameDay(unittest.TestCase):
    """The affordance half is a MIRROR of the rule, and mirrors drift.

    A source-text check, not an import: the client rule lives in a JS module
    this suite cannot execute. What it pins is the one number both sides encode
    -- the three-hour shift -- so a change to the boundary on one side cannot
    ship without the other.
    """

    def _editable_js(self):
        p = (_BACKEND.parent / "frontend" / "src" / "utils" / "logbookEditable.js")
        return p.read_text(encoding="utf-8")

    def test_the_client_shifts_by_three_hours_too(self):
        src = self._editable_js()
        self.assertIn("photoWindowDay", src)
        self.assertRegex(
            src, r"3\s*\*\s*60\s*\*\s*60\s*\*\s*1000",
            "the client's window shift is not the server's three hours")

    def test_the_client_compares_dates_and_does_not_reimplement_the_zone(self):
        src = self._editable_js()
        # easternDate from utils/dates.js is the ONE zone conversion. An inline
        # Intl call here would be a second copy of the boundary.
        self.assertIn("easternDate", src)
        self.assertNotIn("America/New_York", src)

    def test_the_append_predicate_carries_the_window(self):
        src = self._editable_js()
        m = src.split("export function isOpenForPhotoAppend")[1]
        self.assertIn("isPhotoWindowOpen", m.split("\n}")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
