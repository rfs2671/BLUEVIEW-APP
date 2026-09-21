"""A GUARD THAT SAYS NOTHING IS WORSE THAN THE CRASH IT REPLACED.

`_fetch_page_jpeg` had two branches that disagreed about whether `_r2_client`
could be None. The jpeg branch tested it and skipped silently; the source-PDF
fallback called `.get_object` on it and raised AttributeError, caught and
logged as `source pdf fetch failed`.

THE INCONSISTENCY IS WHAT MADE A BAD RUN READABLE. A benchmark of the refusal
warrant reported `0 overturns, reconciliation OK` on a run in which the
warrant never executed once — `_r2_client` is assigned in `startup_event`, and
a script that imports `server` never runs a FastAPI startup handler. The 23
accidental AttributeErrors in the log were the only evidence. The summary
block said nothing, and 0 == 0 passed.

So the obvious fix — guard the fallback — would have made it WORSE: a silent
None on both paths, no log line anywhere, and a summary identical to success.
These tests pin the thing that prevents that, which is not the guard but the
announcement.

WHY PER CALL AND NOT ONCE PER PROCESS: the count is the signal. Twenty-three
lines meant twenty-three attempts. A deduplicated warning would have said "R2
not configured" once and thrown away the number that made the run legible.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402

PAGE = {"page_jpeg_r2_key": "pages/abc.jpg", "file_id": "f1", "page_number": 7}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class WhenR2IsNotConfigured(unittest.TestCase):
    """The state every harness that imports `server` is in, always."""

    def _run(self, client, bucket, page=None):
        saved = (server._r2_client, server.R2_BUCKET_NAME)
        cap = _Capture()
        server.logger.addHandler(cap)
        try:
            server._r2_client = client
            server.R2_BUCKET_NAME = bucket
            got = asyncio.run(server._fetch_page_jpeg(
                dict(page if page is not None else PAGE)))
        finally:
            server.logger.removeHandler(cap)
            server._r2_client, server.R2_BUCKET_NAME = saved
        return got, cap.lines

    def test_no_client_returns_none_and_says_why(self):
        got, lines = self._run(None, "bucket")
        self.assertIsNone(got)
        said = [x for x in lines if "R2 NOT CONFIGURED" in x]
        self.assertEqual(len(said), 1, f"expected one warning, got {lines!r}")

    def test_no_bucket_is_the_same_failure(self):
        got, lines = self._run(object(), "")
        self.assertIsNone(got)
        self.assertTrue(any("R2 NOT CONFIGURED" in x for x in lines))

    def test_the_warning_names_which_half_is_missing(self):
        """`client=False bucket=True` and `client=True bucket=False` are
        different operational problems. A warning that cannot tell them apart
        sends someone to check the wrong thing."""
        _, no_client = self._run(None, "bucket")
        _, no_bucket = self._run(object(), "")
        self.assertNotEqual(
            [x for x in no_client if "R2 NOT CONFIGURED" in x],
            [x for x in no_bucket if "R2 NOT CONFIGURED" in x],
            "both states produced an identical message")

    def test_it_names_the_page_it_could_not_fetch(self):
        got, lines = self._run(None, "bucket")
        said = " ".join(lines)
        self.assertIn("f1", said)
        self.assertIn("7", said)

    def test_it_fires_once_per_call_because_the_count_is_the_signal(self):
        """NOT deduplicated. Twenty-three lines meant twenty-three attempts,
        and that number is what made the void benchmark run legible."""
        saved = (server._r2_client, server.R2_BUCKET_NAME)
        cap = _Capture()
        server.logger.addHandler(cap)
        try:
            server._r2_client = None
            server.R2_BUCKET_NAME = "bucket"
            for _ in range(3):
                asyncio.run(server._fetch_page_jpeg(dict(PAGE)))
        finally:
            server.logger.removeHandler(cap)
            server._r2_client, server.R2_BUCKET_NAME = saved
        self.assertEqual(
            len([x for x in cap.lines if "R2 NOT CONFIGURED" in x]), 3,
            "the warning is deduplicated; the count is the signal")

    def test_a_page_with_no_jpeg_key_still_announces(self):
        """The fallback path is the one that used to raise AttributeError.
        It must now reach the same announcement, not a different failure."""
        got, lines = self._run(None, "bucket",
                               page={"file_id": "f9", "page_number": 2})
        self.assertIsNone(got)
        self.assertTrue(any("R2 NOT CONFIGURED" in x for x in lines))
        self.assertFalse(
            any("source pdf fetch failed" in x for x in lines),
            "still reaching the unguarded fallback")


class TheGuardDidNotSwallowTheConfiguredPath(unittest.TestCase):
    """The failure mode of this change is a guard that is too eager."""

    def test_a_configured_client_is_not_short_circuited(self):
        class _Obj:
            def read(self):
                return b"JPEGBYTES"

        class _Client:
            def get_object(self, Bucket, Key):
                assert Bucket == "bucket" and Key == "pages/abc.jpg"
                return {"Body": _Obj()}

        saved = (server._r2_client, server.R2_BUCKET_NAME)
        try:
            server._r2_client = _Client()
            server.R2_BUCKET_NAME = "bucket"
            got = asyncio.run(server._fetch_page_jpeg(dict(PAGE)))
        finally:
            server._r2_client, server.R2_BUCKET_NAME = saved
        self.assertEqual(got, b"JPEGBYTES")


if __name__ == "__main__":
    unittest.main()
