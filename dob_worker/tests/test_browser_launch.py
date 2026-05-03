"""MR.13 — shared real-Chrome launch + context configuration tests.

Pure-function coverage. The whole point of lib/browser_launch.py is
that the seed script (scripts/seed_storage_state.py) and the worker
handler (handlers/dob_now_filing.py) produce IDENTICAL browser
fingerprints AND that both use real Chrome (channel="chrome") not
the bundled playwright-chromium. Pinned here so a future commit
that flips channel back to chromium, drops --no-sandbox, or
introduces a worker-only flag breaks loudly instead of silently
drifting Akamai's "same-browser?" check out of alignment.

MR.12 Bright Data tests removed: the handler no longer dials a
remote CDP endpoint; it launches local Chrome. The CDP-helper
test class was deleted (no dead-code coverage of removed paths).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DOB_WORKER = _HERE.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestGetLaunchArgs(unittest.TestCase):

    def test_default_is_headed_chrome_channel(self):
        """MR.13 default: channel='chrome' + headless=False. Real
        Chrome under Xvfb is what bypasses Akamai. Bundled
        chromium-headless-shell would NOT — pinned here."""
        from lib.browser_launch import get_launch_args
        result = get_launch_args()
        self.assertEqual(result["channel"], "chrome")
        self.assertIs(result["headless"], False)
        # MR.13 — no --headless=new flag. We're not headless at all.
        self.assertNotIn("--headless=new", result["args"])
        self.assertNotIn("--headless", result["args"])

    def test_explicit_headless_true_still_uses_chrome_channel(self):
        """If a future test path passes headless=True (e.g. a CI
        smoke test), channel stays "chrome" — the load-bearing
        choice is the binary, not the headless mode."""
        from lib.browser_launch import get_launch_args
        result = get_launch_args(headless=True)
        self.assertEqual(result["channel"], "chrome")
        self.assertIs(result["headless"], True)

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

    def test_channel_chrome_identical_across_modes(self):
        """MR.13 — both seed and worker MUST use channel='chrome'.
        If one drifts to bundled chromium, Akamai sees two different
        TLS fingerprints and rejects the worker."""
        from lib.browser_launch import get_launch_args
        self.assertEqual(get_launch_args(headless=True)["channel"], "chrome")
        self.assertEqual(get_launch_args(headless=False)["channel"], "chrome")

    def test_launch_flags_identical_across_modes(self):
        """All flags identical regardless of headless mode (MR.13
        doesn't add --headless=new at all)."""
        from lib.browser_launch import get_launch_args
        self.assertEqual(
            set(get_launch_args(headless=True)["args"]),
            set(get_launch_args(headless=False)["args"]),
        )


# ── MR.13 — Optional Webshare proxy fallback ──────────────────────


class TestGetProxyArgs(unittest.TestCase):
    """Optional proxy plumbing. Unset → None (default direct path).
    Set → Playwright's expected dict shape with separated
    username/password fields (Chromium ignores inline creds in
    `server=`; this is the war-story-encoded behavior)."""

    def setUp(self):
        # Capture so we restore in tearDown — env mutation MUST NOT
        # leak between tests.
        self._saved = os.environ.get("WEBSHARE_PROXY_URL")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("WEBSHARE_PROXY_URL", None)
        else:
            os.environ["WEBSHARE_PROXY_URL"] = self._saved

    def test_returns_none_when_unset(self):
        from lib.browser_launch import get_proxy_args
        os.environ.pop("WEBSHARE_PROXY_URL", None)
        self.assertIsNone(get_proxy_args())

    def test_returns_none_when_empty_string(self):
        from lib.browser_launch import get_proxy_args
        os.environ["WEBSHARE_PROXY_URL"] = ""
        self.assertIsNone(get_proxy_args())

    def test_returns_none_when_whitespace_only(self):
        from lib.browser_launch import get_proxy_args
        os.environ["WEBSHARE_PROXY_URL"] = "   \n  "
        self.assertIsNone(get_proxy_args())

    def test_parses_full_url_into_dict_shape(self):
        """Webshare URLs come in the form
        http://username:password@host:port. Chromium needs them
        split — server stripped of creds, username + password
        as separate keys."""
        from lib.browser_launch import get_proxy_args
        os.environ["WEBSHARE_PROXY_URL"] = (
            "http://user1:pass1@p.webshare.io:9999"
        )
        cfg = get_proxy_args()
        self.assertEqual(cfg["server"], "http://p.webshare.io:9999")
        self.assertEqual(cfg["username"], "user1")
        self.assertEqual(cfg["password"], "pass1")
        # Critical: creds NOT in server URL.
        self.assertNotIn("user1", cfg["server"])
        self.assertNotIn("pass1", cfg["server"])

    def test_parses_no_credentials(self):
        """A bare proxy URL without auth should still produce a
        valid Playwright shape — caller can use it as-is."""
        from lib.browser_launch import get_proxy_args
        os.environ["WEBSHARE_PROXY_URL"] = "http://p.example.com:8080"
        cfg = get_proxy_args()
        self.assertEqual(cfg["server"], "http://p.example.com:8080")
        self.assertNotIn("username", cfg)
        self.assertNotIn("password", cfg)


if __name__ == "__main__":
    unittest.main()
