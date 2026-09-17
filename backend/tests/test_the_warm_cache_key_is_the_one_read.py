"""THE KEY THAT IS WARMED IS THE KEY THAT IS READ.

    python -m pytest backend/tests/test_the_warm_cache_key_is_the_one_read.py

── WHY THIS TEST EXISTS ────────────────────────────────────────────────────

#596 added an `actions/cache` step for the Playwright browser to the mount
smoke job. It never hit once. The stored entries showed why:

    251MB  ref=refs/pull/595/merge  key=ms-playwright-chromium-1.49.1-Linux
    250MB  ref=refs/pull/596/merge  key=ms-playwright-chromium-1.49.1-Linux

Two pull requests each saved their OWN copy of the same key, because GitHub
scopes a cache written on a PR ref to that PR's branch. Only a cache on
`refs/heads/main` is readable by every branch -- and nothing wrote one, because
#594 had already made `tests.yml` run on `pull_request` only.

`warm-playwright-cache.yml` puts that key on main. Its entire value depends on
one string matching another string in a different file. A typo, or a version
bump applied to one file and not the other, and the warm job cheerfully
populates a key nobody reads while every PR keeps paying the download -- with
no error anywhere, because both workflows still pass.

THE FAILURE MODE IS SILENT AND COSTS NOTHING VISIBLE, which is exactly the kind
this repo has learned to pin. So: the two keys are compared, and the pinned
version is compared against the version actually installed.

WHAT WOULD PROVE THIS WRONG: `gh api repos/<o>/<r>/actions/caches` showing
`ms-playwright-chromium-*` only on `refs/pull/...` refs and never on
`refs/heads/main`. That means the warm job is not running or not saving, and no
assertion here can see it -- this test proves the keys AGREE, not that the cache
is warm.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_YML = ROOT / ".github" / "workflows" / "tests.yml"
WARM_YML = ROOT / ".github" / "workflows" / "warm-playwright-cache.yml"

#: `key: ms-playwright-...` on its own line, whatever the indentation.
#
#: `.+?` AND NOT `\S+`. The key ends in `${{ runner.os }}`, which contains
#: SPACES, so a non-whitespace run captures `...-${{` and then fails to reach
#: end-of-line -- matching nothing at all. Both files then read as declaring no
#: key, and the comparison that follows raises IndexError instead of reporting.
#: My own control run caught it: the keys were identical and the test said they
#: were missing.
KEY_RE = re.compile(r"^\s*key:\s*(ms-playwright-.+?)\s*$", re.M)
#: the pinned version wherever playwright is invoked, e.g. playwright@1.49.1
PIN_RE = re.compile(r"playwright(?:-core)?@(\d+\.\d+\.\d+)")


def _read(p: Path) -> str:
    assert p.exists(), f"{p} is missing"
    return p.read_text(encoding="utf-8")


class TheWarmKeyMatchesTheReadKey(unittest.TestCase):
    def test_both_workflows_declare_a_playwright_cache_key(self):
        """A missing key on either side is the same defect as a mismatched one:
        the warm job would populate nothing, or the smoke job would read
        nothing, and both workflows would still be green."""
        for p in (TESTS_YML, WARM_YML):
            keys = KEY_RE.findall(_read(p))
            self.assertEqual(
                len(keys), 1,
                f"{p.name} should declare exactly one ms-playwright cache key, "
                f"found {len(keys)}: {keys}")

    def test_the_two_keys_are_identical(self):
        """THE ASSERTION THIS FILE IS FOR."""
        read_key = KEY_RE.findall(_read(TESTS_YML))[0]
        warm_key = KEY_RE.findall(_read(WARM_YML))[0]
        self.assertEqual(
            warm_key, read_key,
            "the warm job would populate a key the mount smoke never reads, so "
            "every PR would keep paying the browser download with nothing red "
            "to show for it")

    def test_the_key_carries_the_pinned_version(self):
        """A version bump in tests.yml that misses the key leaves the cache
        keyed on the OLD version -- a permanent hit on a stale browser, which
        is worse than a miss because the gate would run the wrong build."""
        body = _read(TESTS_YML)
        pins = set(PIN_RE.findall(body))
        self.assertEqual(
            len(pins), 1,
            f"tests.yml pins more than one playwright version: {sorted(pins)}")
        pin = pins.pop()
        key = KEY_RE.findall(body)[0]
        self.assertIn(
            pin, key,
            f"the cache key {key!r} does not name the pinned version {pin!r}")

    def test_the_warm_job_pins_the_same_version(self):
        warm = _read(WARM_YML)
        pins = set(PIN_RE.findall(warm))
        self.assertTrue(pins, "the warm job invokes no pinned playwright")
        self.assertEqual(
            pins, set(PIN_RE.findall(_read(TESTS_YML))),
            "the warm job would download a different browser build from the "
            "one the mount smoke runs")


class TheWarmJobRunsWhereTheCacheIsReadable(unittest.TestCase):
    """A cache is only shared from the DEFAULT branch. Warming it anywhere else
    reproduces the original defect exactly."""

    def test_it_is_triggered_on_main(self):
        warm = _read(WARM_YML)
        m = re.search(r"^on:(.*?)^[a-z]", warm, re.S | re.M)
        self.assertIsNotNone(m, "no `on:` block")
        block = m.group(1)
        self.assertIn("push:", block, "the warm job must run on a push")
        self.assertRegex(
            block, r"branches:\s*\[main\]",
            "the warm job must run on main -- a cache saved on any other "
            "branch is invisible to pull requests, which is the defect")

    def test_it_also_runs_on_a_schedule(self):
        """GitHub evicts a cache not READ for 7 days. The pinned version changes
        rarely, so without a heartbeat the entry expires in a quiet week."""
        block = re.search(r"^on:(.*?)^[a-z]", _read(WARM_YML), re.S | re.M).group(1)
        self.assertIn("schedule:", block)
        crons = re.findall(r"cron:\s*'([^']+)'", block)
        self.assertTrue(crons, "a schedule with no cron expression")
        # Day-of-week field present and not '*' => at most weekly, which is
        # inside the 7-day window. A monthly cron would let it expire.
        dow = crons[0].split()[-1]
        self.assertNotEqual(
            dow, "*",
            "a daily cron would work but is wasteful; a weekly one is inside "
            "the eviction window")

    def test_it_does_not_cancel_itself(self):
        """Cancelling this job leaves the cache unwritten -- the one thing it
        exists to do. Unlike the PR workflows, superseding is not safe here."""
        warm = _read(WARM_YML)
        self.assertRegex(
            warm, r"cancel-in-progress:\s*false",
            "the warm job must not be cancellable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
