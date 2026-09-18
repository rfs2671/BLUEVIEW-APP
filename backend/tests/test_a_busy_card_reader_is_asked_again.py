"""A 429 IS THE PROVIDER SAYING "NOT NOW", AND THE GATE HEARD "NO".

── MEASURED, 2026-09-18 ────────────────────────────────────────────────────

Re-reading Angel Lopez's stored card against `Qwen/Qwen2.5-VL-32B-Instruct` on
DeepInfra returned `429 engine_overloaded` TWICE in a row. One of Amaury
Ayala's `gate_failures` rows is `Vision API error: 429`, so this is not a
laboratory finding: it is a live condition at a live gate.

WHAT THE CARD-READ PATH DID WITH IT. The attempt loop retries a call that DID
NOT ANSWER -- a timeout, a dropped connection -- and nothing else, on the
stated ground that "a provider that answered 'no' answers 'no' again and bills
for it twice". That reasoning is exactly right for a 400 and exactly wrong for
a 429: a 429 is not an answer about the request, it is the provider declining
to look at it, it is not billed, and the same photograph very probably succeeds
seconds later. The worker got `CARD_READ_UNAVAILABLE` -- copy that leads with
"the card reader is unavailable, enter your card number below" -- so a
transient queue at the provider quietly became a manually-entered card on a
§3301 compliance record.

THE RULE ALREADY EXISTS IN THIS FILE'S OWN CODEBASE. `_worth_asking_again`
(the plan-index path) says it: retry a timeout, a dropped connection, a 429 or
a 5xx; never a 4xx; and `test_a_timeout_is_not_a_fact_about_the_drawing.py`
pins it there. The card read is the one vision caller that did not use it.

── AND THE DATE FORMATS THE TWO READERS DISAGREE ON ────────────────────────

The second half of this file is about `parse_cert_date` and Juan Lopez's
`'10272029'`. See the class comment at TheEightDigitFormIsAcceptedNow for why
that string moves from the refused side to the accepted side without the rule
changing, and for the list of shapes the backend and the frontend still read
differently.

Run:  python -m pytest backend/tests/test_a_busy_card_reader_is_asked_again.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

NOW = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)

# The body DeepInfra actually returns beside the 429.
ENGINE_OVERLOADED = '{"error":{"message":"engine_overloaded","type":"overloaded"}}'

# A real card read, so a success on the retry is distinguishable from a success
# on nothing. Same provenance as test_card_read_hardening's fixture.
GOOD_BODY = {
    "choices": [{"message": {"content":
        '{"name":"Angel Lopez","sst_number":"RUQ24T3LVF","card_type":"SST",'
        '"card_class":"Worker","issued":"03/01/2026",'
        '"expiration":"03/01/2031","card_dominant_color":"BLUE"}'}}],
}


class _Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body if body is not None else GOOD_BODY
        self.text = text if text is not None else "{}"

    def json(self):
        return self._body


class _Request:
    class _C:
        host = "203.0.113.9"
    client = _C()
    headers = {"user-agent": "gate-tablet"}


def _read_card(outcomes):
    """Drive the real endpoint over a scripted sequence of provider outcomes.

    Returns (result_or_HTTPException, attempts, backoff_delays).

    NOTHING SLEEPS. The backoff is awaited through `server._vision_backoff`,
    which is replaced here by a recorder -- so the delays are ASSERTED rather
    than endured, and a run that added a real 8-second wait to the suite would
    show up as an empty list here instead of a slow test nobody notices.
    """
    attempts = []
    delays = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            attempts.append(1)
            out = outcomes[min(len(attempts) - 1, len(outcomes) - 1)]
            if isinstance(out, Exception):
                raise out
            return out

    async def _sleep(seconds):
        delays.append(seconds)

    async def _metered(*a, **k):
        return None

    with mock.patch.object(server, "ServerHttpClient", _Client), \
            mock.patch.object(server, "QWEN_API_KEY", "test-key"), \
            mock.patch.object(server, "record_vision_call", _metered), \
            mock.patch.object(server, "_vision_backoff", _sleep), \
            mock.patch.object(server, "_downscale_card_for_vision",
                              lambda b64: (b64, "image/jpeg", {})):
        try:
            got = asyncio.run(server.upload_osha_card(
                {"image": "AAAA", "content_type": "image/jpeg",
                 "project_id": "p_588_thomas"},
                _Request()))
        except HTTPException as exc:
            got = exc
    return got, len(attempts), delays


class ABusyProviderIsAskedAgain(unittest.TestCase):

    def test_a_429_is_retried(self):
        """THE HEADLINE. Twice in a row on a real card, 2026-09-18."""
        got, attempts, _d = _read_card(
            [_Resp(429, text=ENGINE_OVERLOADED), _Resp()])
        self.assertEqual(attempts, 2)
        self.assertNotIsInstance(got, HTTPException)

    def test_the_retrys_answer_is_the_one_that_is_used(self):
        """Asserted on a field only the model supplies. That the call happened
        twice proves the retry; that the card number reached the payload proves
        the retry's answer was not discarded with the first."""
        got, _a, _d = _read_card(
            [_Resp(429, text=ENGINE_OVERLOADED), _Resp()])
        self.assertEqual(got.sst_number, "RUQ24T3LVF")

    def test_it_WAITS_before_asking_again(self):
        """A retry fired immediately at a provider that just said "too many"
        is the same request arriving inside the same overloaded window. The
        backoff is the difference between a retry and a second failure."""
        _got, _a, delays = _read_card(
            [_Resp(429, text=ENGINE_OVERLOADED), _Resp()])
        self.assertEqual(len(delays), 1)
        self.assertGreater(delays[0], 0)

    def test_a_5xx_is_retried_too(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                _got, attempts, _d = _read_card([_Resp(status), _Resp()])
                self.assertEqual(attempts, 2)

    def test_a_BAD_MODEL_ID_is_not_retried(self):
        """404 means QWEN_MODEL names something the provider does not have --
        the exact state the old code default would have put every gate into.
        Asking again buys a second identical refusal and a second bill."""
        got, attempts, _d = _read_card([_Resp(404, text="model not found")])
        self.assertEqual(attempts, 1)
        self.assertIsInstance(got, HTTPException)

    def test_nor_a_bad_key_nor_a_rejected_image(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                _got, attempts, _d = _read_card([_Resp(status)])
                self.assertEqual(attempts, 1)

    def test_a_timeout_is_STILL_retried(self):
        """Unchanged. Asserted here so the new branch cannot have displaced
        the one that was already right."""
        _got, attempts, _d = _read_card(
            [httpx.ReadTimeout("no answer"), _Resp()])
        self.assertEqual(attempts, 2)

    def test_the_retry_is_BOUNDED(self):
        """A provider in a bad hour would otherwise hold a worker at the
        turnstile for as long as it kept saying 429."""
        _got, attempts, _d = _read_card([_Resp(429, text=ENGINE_OVERLOADED)])
        self.assertLessEqual(attempts, server.OSHA_VISION_ATTEMPTS)
        self.assertGreater(attempts, 1)


class WhenItIsStillBusyTheWorkerIsToldToTryAgain(unittest.TestCase):
    """NOT DROPPED INTO MANUAL ENTRY SILENTLY. `CARD_READ_UNAVAILABLE`'s copy
    leads with "enter your card number below", which is the right answer for a
    reader that is DOWN and the wrong one for a reader that is BUSY: it turns a
    thirty-second queue into a self-reported card on a compliance record."""

    def _detail(self, status, text=""):
        got, _a, _d = _read_card([_Resp(status, text=text)])
        self.assertIsInstance(got, HTTPException)
        return got

    def test_a_persistent_429_has_its_OWN_code(self):
        exc = self._detail(429, ENGINE_OVERLOADED)
        self.assertEqual(exc.detail["code"], server.CARD_READ_BUSY)

    def test_and_it_is_a_RETRYABLE_status_not_a_bad_gateway(self):
        """503 with the code, so a client that branches on the HTTP status
        alone still learns "come back", not "this failed"."""
        exc = self._detail(429, ENGINE_OVERLOADED)
        self.assertEqual(exc.status_code, 503)

    def test_the_sentence_tells_him_to_try_the_photo_again(self):
        exc = self._detail(429, ENGINE_OVERLOADED)
        self.assertIn("again", exc.detail["message"].lower())

    def test_a_reader_that_is_genuinely_DOWN_still_says_so(self):
        """THE CONTROL. If every non-200 became CARD_READ_BUSY, the worker
        whose provider is misconfigured would be told to wait for ever."""
        exc = self._detail(404, "model not found")
        self.assertEqual(exc.detail["code"], server.CARD_READ_UNAVAILABLE)

    def test_the_gate_page_knows_the_new_code(self):
        """A code the client does not recognise falls into checkin.html's
        fallback branch: raw English prose on a bilingual page, and the ONE
        branch there that never sends the worker back to the camera."""
        html = (Path(__file__).resolve().parent.parent / "checkin.html"
                ).read_text(encoding="utf-8")
        self.assertIn("CARD_READ_BUSY", html)


class TheRETRYRULEISNOTASECONDOPINION(unittest.TestCase):
    """ONE RULE, ONE PLACE. `_worth_asking_again` already decides this for the
    plan-index path and is pinned by its own file. A second predicate here
    would be two rules that agree until somebody changes one."""

    def test_the_card_read_asks_the_same_question_the_plan_index_asks(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertTrue(server.vision_status_is_retryable(status))
                self.assertTrue(server._worth_asking_again(
                    server.ProviderStatus(status)))
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                self.assertFalse(server.vision_status_is_retryable(status))
                self.assertFalse(server._worth_asking_again(
                    server.ProviderStatus(status)))

    def test_it_is_derived_from_that_rule_and_not_a_copy_of_it(self):
        """Read from the stripped source, so a comment claiming the two agree
        cannot satisfy the assertion."""
        from tests.source_text import code_of
        src = code_of("server.py")
        at = src.index("def vision_status_is_retryable")
        body = src[at:at + 400]
        self.assertIn("_worth_asking_again", body,
                      "the card path spells the retry rule a second time")


# ══ (d) THE EIGHT-DIGIT FORM, AND WHAT THE TWO READERS STILL DISAGREE ON ═══

class TheEightDigitFormIsAcceptedNow(unittest.TestCase):
    """JUAN LOPEZ'S `'10272029'`, AND THE RULE DID NOT CHANGE TO ADMIT IT.

    `parse_cert_date`'s rule is ACCEPT WHAT IS UNAMBIGUOUS BY CONSTRUCTION,
    REFUSE WHAT IS UNAMBIGUOUS ONLY BY CONVENTION -- and this string was on
    the refused side, on the stated ground that eight digits "do not say which
    field comes first, and under a different assumption they are 10 December
    7202".

    THAT SENTENCE IS TRUE OF EIGHT DIGITS AND FALSE OF EIGHT DIGITS WITH A
    BOUNDED YEAR, which is what PR #590 established on the frontend and what
    this accepts: with the year in 1900-2199, a YYYYMMDD string read as
    MMDDYYYY has a "month" of 19, 20 or 21, and there is no such month. No
    string is a valid date both ways, so the reading is forced by construction
    and no assumption is made. `10 December 7202` is refused BY THE BOUND, not
    by preference.

    `'062427'` AND `'05/35'` ARE UNAFFECTED AND STAY REFUSED. Six digits and
    five characters carry no four-digit year, so nothing makes them
    unambiguous: `062427` is 06/24/2027 or 06/24/1927 and ONE OF THOSE IS AN
    EXPIRED CARD. The line moved for one shape, for a reason, and the other
    two are still on the far side of it.
    """

    def test_juans_expiry_is_a_date(self):
        self.assertEqual(server.parse_cert_date("10272029"),
                         datetime(2029, 10, 27, tzinfo=timezone.utc))

    def test_the_optional_slashes_the_frontend_accepts_are_accepted(self):
        for raw in ("10272029", "10/272029", "1027/2029", "10/27/2029"):
            with self.subTest(raw=raw):
                self.assertEqual(server.parse_cert_date(raw),
                                 datetime(2029, 10, 27, tzinfo=timezone.utc))

    def test_the_YEAR_BOUND_is_what_does_the_work(self):
        """The whole argument in one assertion: reversed, the same digits are
        not a date, so the reading is not a choice."""
        self.assertIsNone(server.parse_cert_date("20291027"))

    def test_an_out_of_range_year_is_refused_on_the_EIGHT_DIGIT_form(self):
        for raw in ("10271027", "10278299"):
            with self.subTest(raw=raw):
                self.assertIsNone(server.parse_cert_date(raw))

    def test_a_non_calendar_day_is_refused(self):
        for raw in ("02302027", "13012027", "00012027", "01002027",
                    "02292027"):
            with self.subTest(raw=raw):
                self.assertIsNone(server.parse_cert_date(raw), raw)

    def test_the_OTHER_TWO_convention_only_shapes_stay_refused(self):
        for raw in ("062427", "05/35"):
            with self.subTest(raw=raw):
                self.assertIsNone(server.parse_cert_date(raw))

    def test_and_a_partial_read_is_still_not_a_date(self):
        """The Wilmer flake and its family. Eight digits is eight digits; none
        of these has them."""
        for raw in ("35", "05/", "2035", "2030", "27", "EXP", "/35", "05/3",
                    "20", "1272029"):
            with self.subTest(raw=raw):
                self.assertIsNone(server.parse_cert_date(raw), raw)

    def test_it_reaches_the_gate_and_the_row(self):
        """END TO END, on the boundary Juan's value actually crossed."""
        stored, suppressed, reason = server.evaluate_cert_expiry(
            "10272029", None, "SST_FULL", NOW)
        self.assertEqual(stored, datetime(2029, 10, 27, tzinfo=timezone.utc))
        self.assertEqual((suppressed, reason), (False, None))


class TheAcceptanceSurfaceIsPINNED(unittest.TestCase):
    """A COUNT, SO THE NEXT WIDENING IS A DELIBERATE ACT -- and the count has
    to cover the WHOLE surface now, not just the strptime tuple.

    `test_the_parser_accepts_exactly_two_formats` asserted
    `CERT_DATE_FORMATS == ("%m/%d/%Y", "%Y-%m-%d")`, which was the complete
    acceptance set when the parser was nothing but that loop. It no longer is,
    so that assertion would keep passing over a third, fourth and fifth shape
    added beside it -- a count that no longer counts anything. Both halves are
    pinned here.
    """

    def test_the_strptime_formats_are_still_exactly_two(self):
        self.assertEqual(tuple(server.CERT_DATE_FORMATS),
                         ("%m/%d/%Y", "%Y-%m-%d"))

    def test_and_there_is_exactly_one_other_shape(self):
        self.assertEqual(server.CERT_DATE_PADDED_US_RE.pattern,
                         r"^(\d{2})/?(\d{2})/?(\d{4})$")

    def test_the_year_bound_is_the_frontends_year_bound(self):
        """Read out of dateEntry.js, not retyped. A hardcoded 1900/2199 here
        would keep passing after the shared field changed, which is the drift
        the number exists to prevent."""
        js = (Path(__file__).resolve().parent.parent.parent / "frontend" /
              "src" / "utils" / "dateEntry.js").read_text(encoding="utf-8")
        import re
        lo = int(re.search(r"MIN_YEAR = (\d+)", js).group(1))
        hi = int(re.search(r"MAX_YEAR = (\d+)", js).group(1))
        self.assertEqual((server.CERT_DATE_MIN_YEAR, server.CERT_DATE_MAX_YEAR),
                         (lo, hi))

    def test_no_bare_year_format_has_arrived(self):
        self.assertNotIn("%Y", tuple(server.CERT_DATE_FORMATS))


class WhatTheTwoREADERSStillDisagreeOn(unittest.TestCase):
    """NOT A FIX -- A MEASUREMENT, KEPT WHERE IT CAN GO STALE LOUDLY.

    `parse_cert_date` WRITES a §3301 compliance record with no human looking;
    `parseStoredDate` only SHOWS a stored value to the person about to press
    Save, and dateEntry.js says so. So the two are allowed to differ, and the
    differences below are deliberate rather than pending. They are pinned so
    that a change to either side has to come here and restate the list.

    THE BACKEND IS WIDER ON THREE FAMILIES:
      unpadded month or day   '3/1/2026'    strptime's %m takes one digit
      unpadded ISO fields     '2026-3-1'    same, via %Y-%m-%d
      unbounded year          '03/01/0295'  and '01/01/9999'
    The year one is the live-adjacent one: a field has already been seen
    showing 07/22/0295, and this parser would store it.

    THE BACKEND IS NARROWER ON ONE:
      surrounding whitespace  ' 03/01/2026' the frontend trims, strptime does not
    """

    BACKEND_WIDER = ("3/1/2026", "2026-3-1", "03/01/0295", "01/01/9999")
    BACKEND_NARROWER = (" 03/01/2026", "2026-03-01 ")

    def test_the_wider_family_still_parses_here(self):
        for raw in self.BACKEND_WIDER:
            with self.subTest(raw=raw):
                self.assertIsNotNone(server.parse_cert_date(raw), raw)

    def test_the_narrower_family_still_does_not(self):
        for raw in self.BACKEND_NARROWER:
            with self.subTest(raw=raw):
                self.assertIsNone(server.parse_cert_date(raw), raw)

    def test_the_eight_digit_form_is_NO_LONGER_on_the_list(self):
        """The one this PR closed. Left as an assertion rather than deleted, so
        the list is a statement about the current gap and not a historical
        note."""
        self.assertIsNotNone(server.parse_cert_date("10272029"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
