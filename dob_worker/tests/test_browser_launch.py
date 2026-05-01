"""MR.11.3 — shared Chromium launch + context configuration tests.

Pure-function coverage. The whole point of lib/browser_launch.py is
that the seed script (scripts/seed_storage_state.py) and the worker
handler (handlers/dob_now_filing.py) produce IDENTICAL browser
fingerprints. These tests pin the contract so a future commit that
adds a worker-only flag (or an operator-only viewport) breaks
loudly instead of silently drifting Akamai's "same-browser?" check
out of alignment.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DOB_WORKER = _HERE.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestGetLaunchArgs(unittest.TestCase):

    def test_default_is_headless_with_new_mode_flag(self):
        from lib.browser_launch import get_launch_args
        result = get_launch_args()
        self.assertIs(result["headless"], True)
        # --headless=new is the Chromium 109+ mode that produces a
        # closer-to-real-Chrome fingerprint than legacy headless.
        self.assertIn("--headless=new", result["args"])

    def test_explicit_headless_false_omits_headless_flag(self):
        """The seed script overrides headless=False because the
        operator needs to interact with the window. In that mode
        --headless=new is wrong (we're not headless at all)."""
        from lib.browser_launch import get_launch_args
        result = get_launch_args(headless=False)
        self.assertIs(result["headless"], False)
        self.assertNotIn("--headless=new", result["args"])

    def test_base_flags_present_in_both_modes(self):
        from lib.browser_launch import get_launch_args
        required = (
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage",
        )
        for headless in (True, False):
            with self.subTest(headless=headless):
                args = get_launch_args(headless=headless)["args"]
                for flag in required:
                    self.assertIn(flag, args)

    def test_returned_args_list_is_independent(self):
        """Tweaking the result of one call must not leak into the
        next call — guards against shared-mutable-default footgun."""
        from lib.browser_launch import get_launch_args
        a = get_launch_args()
        a["args"].append("--injected")
        b = get_launch_args()
        self.assertNotIn("--injected", b["args"])


class TestGetContextArgs(unittest.TestCase):

    def test_user_agent_is_real_chrome_on_windows(self):
        from lib.browser_launch import get_context_args, CHROME_VERSION
        args = get_context_args()
        ua = args["user_agent"]
        # Real Chrome on Windows starts with Mozilla/5.0 and has
        # Windows NT 10.0 + the pinned Chrome version.
        self.assertTrue(ua.startswith("Mozilla/5.0 (Windows NT 10.0;"))
        self.assertIn(f"Chrome/{CHROME_VERSION}", ua)
        # Critical: it must NOT advertise HeadlessChrome — that's
        # the dead-giveaway tell Akamai checks first.
        self.assertNotIn("HeadlessChrome", ua)

    def test_viewport_is_full_desktop(self):
        from lib.browser_launch import get_context_args
        vp = get_context_args()["viewport"]
        self.assertEqual(vp["width"], 1920)
        self.assertEqual(vp["height"], 1080)

    def test_locale_and_timezone_match_nyc(self):
        from lib.browser_launch import get_context_args
        args = get_context_args()
        self.assertEqual(args["locale"], "en-US")
        self.assertEqual(args["timezone_id"], "America/New_York")

    def test_accept_language_header_matches_locale(self):
        from lib.browser_launch import get_context_args
        headers = get_context_args()["extra_http_headers"]
        # Real browsers send something like "en-US,en;q=0.9". The
        # test pins the exact value so Akamai sees byte-identical
        # headers from seed and worker.
        self.assertEqual(headers["Accept-Language"], "en-US,en;q=0.9")

    def test_returned_dicts_are_independent(self):
        """Mutating the returned viewport / headers must not leak
        into the next call — same shared-mutable concern."""
        from lib.browser_launch import get_context_args
        a = get_context_args()
        a["viewport"]["width"] = 1
        a["extra_http_headers"]["X-Tampered"] = "yes"
        b = get_context_args()
        self.assertEqual(b["viewport"]["width"], 1920)
        self.assertNotIn("X-Tampered", b["extra_http_headers"])


class TestSeedAndWorkerShareIdenticalFingerprint(unittest.TestCase):
    """The whole purpose of the module: the seed script and the
    worker MUST produce identical browser identity. Pin it
    explicitly so a future drift breaks this test, not just
    Akamai."""

    def test_user_agent_identical_across_modes(self):
        """Worker uses get_launch_args(headless=True) + get_context_args().
        Seed uses get_launch_args(headless=False) + get_context_args().
        The UA comes from get_context_args() and is the same object
        across both — this test makes the invariant explicit."""
        from lib.browser_launch import get_context_args
        worker_ua = get_context_args()["user_agent"]
        seed_ua = get_context_args()["user_agent"]
        self.assertEqual(worker_ua, seed_ua)

    def test_viewport_locale_timezone_identical(self):
        from lib.browser_launch import get_context_args
        a = get_context_args()
        b = get_context_args()
        self.assertEqual(a["viewport"], b["viewport"])
        self.assertEqual(a["locale"], b["locale"])
        self.assertEqual(a["timezone_id"], b["timezone_id"])

    def test_base_launch_flags_identical_across_headless_modes(self):
        """The non-headless flags (everything except --headless=new)
        must be byte-identical between seed and worker. If a
        worker-only flag sneaks in, this test surfaces it."""
        from lib.browser_launch import get_launch_args
        worker_flags = set(get_launch_args(headless=True)["args"]) - {"--headless=new"}
        seed_flags = set(get_launch_args(headless=False)["args"])
        self.assertEqual(worker_flags, seed_flags)


if __name__ == "__main__":
    unittest.main()
