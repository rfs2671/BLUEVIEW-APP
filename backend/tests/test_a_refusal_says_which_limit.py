"""A REFUSAL HAS TO SAY WHICH LIMIT, OR IT TEACHES US NOTHING.

On 2026-09-18 a full re-index of 588 Thomas S Boyland Street lost a section on
32 of 129 pages. 46 of the 64 failed calls were `ProviderStatus:429` — the
provider refusing us — and the losses arrived as a cliff: the first 40 pages
lost nothing at all, then twenty consecutive pages lost a section each.

NOT ONE of those refusals survived. The raise site passed a status code and
dropped the response; the log line printed the same code; the page flag read
`call_failed:ProviderStatus:429`. When the question became WHICH limit had
been hit — requests per minute, tokens per minute, or the model simply being
full — there was nothing to read. A probe sent afterwards came back 200 with no
rate-limit headers at all, which proves only that the limit was not in force by
then.

The concurrency answer was already known: the account allows 200 per model and
the indexer peaks at nine. So the capture is not a nicety — it is the only
thing that can tell the backoff how long to wait, and whether the provider is
willing to say so itself.

── WHAT THESE TESTS HOLD ─────────────────────────────────────────────────────

  - Retry-After is read in BOTH forms the RFC allows, and its absence is None
    rather than zero, because "wait no time" and "did not say" ask for
    different behaviour from a backoff.
  - The capture cannot itself throw. A step that turns the provider's bad
    minute into our own exception is worse than no capture.
  - The flag on the page keeps its shape, so `flag_is_retryable` and every
    stale census built on it go on meaning what they meant.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import plan_extract  # noqa: E402


class _Resp:
    """The parts of a response the capture touches, and nothing else."""

    def __init__(self, headers=None, text="", explode_headers=False,
                 explode_text=False):
        self._headers = headers or {}
        self._text = text
        self._explode_headers = explode_headers
        self._explode_text = explode_text

    @property
    def headers(self):
        if self._explode_headers:
            raise RuntimeError("header access failed")
        return self._headers

    @property
    def text(self):
        if self._explode_text:
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad byte")
        return self._text


class RetryAfterIsReadInBothFormsTheRfcAllows(unittest.TestCase):

    def test_a_number_is_seconds(self):
        self.assertEqual(server._retry_after_seconds("30"), 30.0)
        self.assertEqual(server._retry_after_seconds(" 2.5 "), 2.5)

    def test_an_http_date_is_the_wait_until_then(self):
        when = datetime.now(timezone.utc) + timedelta(seconds=45)
        stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
        got = server._retry_after_seconds(stamp)
        self.assertIsNotNone(got, "an HTTP-date Retry-After was not read")
        self.assertTrue(30 <= got <= 60, f"expected about 45s, got {got}")

    def test_a_date_already_past_is_no_wait_not_a_negative_one(self):
        when = datetime.now(timezone.utc) - timedelta(seconds=120)
        stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.assertEqual(server._retry_after_seconds(stamp), 0.0)

    def test_silence_is_none_and_not_zero(self):
        """A backoff that reads 'did not say' as 'wait no time' re-asks into
        the same limit, which is the failure this whole change exists for."""
        for quiet in (None, "", "   "):
            self.assertIsNone(server._retry_after_seconds(quiet),
                              f"{quiet!r} should read as no instruction")

    def test_nonsense_is_none(self):
        self.assertIsNone(server._retry_after_seconds("soon"))
        self.assertIsNone(server._retry_after_seconds("Tue, 99 Zzz 2026"))


class TheCaptureKeepsWhatTheProviderSent(unittest.TestCase):

    def test_the_headers_that_name_a_limit_are_kept(self):
        resp = _Resp(headers={
            "retry-after": "17",
            "x-ratelimit-limit-tokens": "400000",
            "x-ratelimit-remaining-tokens": "0",
            "x-request-id": "req_abc123",
            "content-type": "application/json",
        }, text='{"error":{"message":"rate limit"}}')
        kept, wait, body = server._refusal_detail(resp)
        self.assertEqual(wait, 17.0)
        self.assertEqual(kept.get("x-ratelimit-remaining-tokens"), "0")
        self.assertEqual(kept.get("x-request-id"), "req_abc123")
        self.assertTrue("rate limit" in body, "the body was not kept")

    def test_a_header_the_provider_does_not_send_is_simply_absent(self):
        """DeepInfra sent no rate-limit header on any of 14 probed 200s. An
        empty capture is a finding, not a bug, and must not invent keys."""
        kept, wait, body = server._refusal_detail(_Resp(text="upstream busy"))
        self.assertEqual(kept, {})
        self.assertIsNone(wait)
        self.assertEqual(body, "upstream busy")

    def test_a_long_body_is_cut_to_a_log_line(self):
        _kept, _wait, body = server._refusal_detail(_Resp(text="x" * 5000))
        self.assertEqual(len(body), server._REFUSAL_BODY_CHARS)

    def test_capture_never_raises_even_when_the_response_is_broken(self):
        for resp in (_Resp(explode_headers=True, text="still readable"),
                     _Resp(headers={"retry-after": "5"}, explode_text=True),
                     _Resp(explode_headers=True, explode_text=True)):
            kept, wait, body = server._refusal_detail(resp)
            self.assertIsInstance(kept, dict)
            self.assertIsInstance(body, str)
            del wait


class TheExceptionCarriesItOnward(unittest.TestCase):

    def test_what_was_captured_reaches_the_decision(self):
        exc = server.ProviderStatus(
            429, detail="too many tokens", retry_after=12.0,
            headers={"retry-after": "12"})
        self.assertEqual(exc.status, 429)
        self.assertEqual(exc.retry_after, 12.0)
        self.assertEqual(exc.headers.get("retry-after"), "12")
        self.assertTrue("too many tokens" in str(exc))

    def test_the_old_shape_still_works(self):
        """Every existing caller builds these with a bare status."""
        exc = server.ProviderStatus(503)
        self.assertEqual(exc.status, 503)
        self.assertIsNone(exc.retry_after)
        self.assertEqual(exc.headers, {})

    def test_the_headers_are_copied_not_held(self):
        sent = {"retry-after": "9"}
        exc = server.ProviderStatus(429, headers=sent)
        sent["retry-after"] = "0"
        self.assertEqual(exc.headers.get("retry-after"), "9")

    def test_the_page_flag_keeps_its_shape(self):
        """`flag_is_retryable` and the stale census read this string."""
        self.assertEqual(
            plan_extract._call_failed_flag(
                server.ProviderStatus(429, retry_after=30.0,
                                      headers={"retry-after": "30"})),
            "call_failed:ProviderStatus:429")
        self.assertTrue(plan_extract.flag_is_retryable(
            ["call_failed:ProviderStatus:429"]))


class TheTwoOcrEnginesAreNotCalledTheSameThing(unittest.TestCase):
    """`ocr_not_configured` meant Textract — the full-page OCR for scans — and
    was read on 2026-09-18 as meaning plan_ocr/RapidOCR, which reads schedule
    grids and has a different dependency entirely. The misreading cost a
    Dockerfile investigation that could never have found anything."""

    def test_the_page_level_flag_names_the_page_level_engine(self):
        self.assertEqual(server._ocr_page_text.__module__, "server")
        src = Path(server.__file__).with_suffix(".py")
        text = src.read_text(encoding="utf-8", errors="replace")
        self.assertTrue('"page_ocr_not_configured"' in text,
                        "the page-OCR flag was not renamed")
        self.assertFalse('"ocr_not_configured"' in text,
                         "the ambiguous flag name is still in server.py")


if __name__ == "__main__":
    unittest.main()
