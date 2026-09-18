"""A RATE LIMIT IS THE ONE FAILURE THAT WAITING HELPS.

MEASURED ON THE RE-INDEX OF 2026-09-18, 18:48-21:11Z: 55 of 91 failed section
calls were `ProviderStatus:429`, and a further 24 were `BudgetExhausted` spent
re-asking straight into them. 53 of 129 pages lost a section, against 33 the
night before.

The shape of it matters more than the totals. The first 40 pages lost NOTHING
— #605's retry works perfectly when the provider answers — and then two
windows, 19:25-19:58 and 20:42-20:43, took every page inside them. The
refusals track the CLOCK, not the file: `AR - 3.28.25.pdf` had 8 pages refused
and 18 not, same file, same sheets, minutes apart. Concurrency was ruled out
(200 allowed per model, the indexer peaks at nine) and so was request rate
(14 rapid probe calls all returned 200 while the indexer was losing sections).

So a 429 is weather. Re-asking on the spot cannot succeed, and the budget it
spends belongs to the sections behind it.

── WHAT IS DELIBERATELY NOT MEASURED HERE ────────────────────────────────────

None of those 55 refusals left a body or a header behind, because the raise
site discarded them. So no number in this file is tuned to an observed
Retry-After, and the tests say what the numbers ARE rather than that they are
right. When a real refusal is captured, `retry_after` is obeyed and these
become the fallback they were always meant to be.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_extract as pe  # noqa: E402


class WhatTheProviderAsksForWins(unittest.TestCase):

    def test_a_stated_wait_is_obeyed(self):
        """A number we chose can only be a guess about a limit we cannot see."""
        self.assertEqual(pe.retry_wait_seconds(1, 7.0), 7.0)
        self.assertEqual(pe.retry_wait_seconds(3, 1.5), 1.5)

    def test_a_stated_wait_is_still_bounded_by_the_page(self):
        """A provider asking for five minutes is telling us this page is not
        being indexed in this pass."""
        self.assertEqual(pe.retry_wait_seconds(1, 300.0),
                         pe.RETRY_WAIT_CAP_SECONDS)

    def test_silence_is_not_a_stated_wait(self):
        """`None` means it did not say, which is not 'wait no time'."""
        self.assertGreater(pe.retry_wait_seconds(1, None, lambda: 0.5), 0.0)


class TheWaitGrowsAndIsJittered(unittest.TestCase):

    def test_it_doubles(self):
        mid = (lambda: 0.5)
        self.assertAlmostEqual(pe.retry_wait_seconds(1, None, mid), 2.0)
        self.assertAlmostEqual(pe.retry_wait_seconds(2, None, mid), 4.0)
        self.assertAlmostEqual(pe.retry_wait_seconds(3, None, mid), 8.0)

    def test_jitter_spreads_it_both_ways(self):
        low = pe.retry_wait_seconds(1, None, lambda: 0.0)
        high = pe.retry_wait_seconds(1, None, lambda: 1.0)
        self.assertLess(low, 2.0)
        self.assertGreater(high, 2.0)
        self.assertAlmostEqual((low + high) / 2, 2.0)

    def test_jitter_is_a_fraction_and_not_a_constant(self):
        """A fleet that all woke at t+2.0 would rebuild the burst it is
        backing off from, so the spread has to scale with the wait."""
        spread_1 = (pe.retry_wait_seconds(1, None, lambda: 1.0)
                    - pe.retry_wait_seconds(1, None, lambda: 0.0))
        spread_3 = (pe.retry_wait_seconds(3, None, lambda: 1.0)
                    - pe.retry_wait_seconds(3, None, lambda: 0.0))
        self.assertGreater(spread_3, spread_1)

    def test_it_never_exceeds_the_page_cap(self):
        for attempt in range(1, 12):
            self.assertLessEqual(pe.retry_wait_seconds(attempt, None, lambda: 1.0),
                                 pe.RETRY_WAIT_CAP_SECONDS)


class _Page:
    """Drives extract_page with a provider that refuses on demand."""

    def __init__(self, refuse_with, refuse_sections):
        self.refuse_with = refuse_with
        self.refuse_sections = set(refuse_sections)
        self.asked: list = []
        self.slept: list = []

    async def vlm_call(self, _image, prompt, _max_tokens):
        name = next((s for s in pe.SECTIONS if s in prompt), prompt[:20])
        self.asked.append(name)
        if name in self.refuse_sections:
            raise self.refuse_with()
        return ('{"notes": []}', "stop")


class _Refused(RuntimeError):
    status = 429
    retry_after = None


class _RefusedWithAWait(RuntimeError):
    status = 429
    retry_after = 3.0


class _RefusedForALongTime(RuntimeError):
    """9s asked for, five sections: the third ask would carry the page past
    the 20s cap. Sized deliberately - at 3s apiece the five sections total 15s
    and NOTHING degrades, which is correct and tests nothing."""
    status = 429
    retry_after = 9.0


class _TimedOut(RuntimeError):
    pass


class OnlyARateLimitIsWaitedOut(unittest.TestCase):

    def _run(self, exc, sections):
        page = _Page(exc, sections)
        slept: list = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        real = pe.sleep
        pe.sleep = fake_sleep
        try:
            out = asyncio.run(pe.extract_page(
                image_b64="x", page_text="", boilerplate=frozenset(),
                vlm_call=page.vlm_call))
        finally:
            pe.sleep = real
        return out, slept

    def test_a_429_is_waited_out_before_the_second_ask(self):
        out, slept = self._run(_Refused, ["notes"])
        self.assertTrue(slept, "a rate-limited section was re-asked with no wait")
        self.assertTrue(any(str(f).startswith("waited:")
                            for f in out["flags"].get("notes") or []))

    def test_a_timeout_is_not_waited_out(self):
        """Waiting out a timeout spends the page budget for no reason: the
        model was slow on THIS page, not refusing everyone."""
        _out, slept = self._run(_TimedOut, ["notes"])
        self.assertEqual(slept, [])

    def test_a_stated_retry_after_is_what_gets_slept(self):
        _out, slept = self._run(_RefusedWithAWait, ["notes"])
        self.assertEqual(slept, [3.0])


class AThrottledPageDegradesInsteadOfBurning(unittest.TestCase):

    def test_the_page_stops_waiting_once_it_has_waited_enough(self):
        """The whole point of the cap. A page that sat out the window would
        starve every page behind it, which is the #605 failure in a new
        costume."""
        page = _Page(_RefusedForALongTime, list(pe.SECTIONS))
        slept: list = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        real = pe.sleep
        pe.sleep = fake_sleep
        try:
            out = asyncio.run(pe.extract_page(
                image_b64="x", page_text="", boilerplate=frozenset(),
                vlm_call=page.vlm_call))
        finally:
            pe.sleep = real

        self.assertLessEqual(sum(slept), pe.RETRY_WAIT_CAP_SECONDS)
        gave_up = [n for n, fl in out["flags"].items()
                   if "rate_limited_gave_up" in (fl or [])]
        self.assertTrue(gave_up,
                        "every section waited; nothing degraded")

    def test_giving_up_says_so_on_the_page(self):
        page = _Page(_RefusedForALongTime, list(pe.SECTIONS))

        async def fake_sleep(_seconds):
            return None

        real = pe.sleep
        pe.sleep = fake_sleep
        try:
            out = asyncio.run(pe.extract_page(
                image_b64="x", page_text="", boilerplate=frozenset(),
                vlm_call=page.vlm_call))
        finally:
            pe.sleep = real
        printed = [f for fl in out["flags"].values() for f in (fl or [])]
        self.assertTrue(any("rate_limited_gave_up" == f for f in printed))


class TheExponentCountsThePagesRefusalsNotTheSections(unittest.TestCase):
    """A section is re-asked ONCE, so an attempt counter tied to the section
    would be 1 every time and the backoff would be a flat two seconds wearing
    the word 'exponential'. Each further refusal on the same page is further
    evidence the window has not passed."""

    def test_the_second_throttled_section_waits_longer_than_the_first(self):
        page = _Page(_Refused, list(pe.SECTIONS)[:3])
        slept: list = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        real = pe.sleep
        pe.sleep = fake_sleep
        try:
            asyncio.run(pe.extract_page(
                image_b64="x", page_text="", boilerplate=frozenset(),
                vlm_call=page.vlm_call))
        finally:
            pe.sleep = real
        self.assertGreaterEqual(len(slept), 2, f"expected several waits: {slept}")
        self.assertGreater(slept[1], slept[0],
                           f"the backoff did not grow: {slept}")


if __name__ == "__main__":
    unittest.main()
