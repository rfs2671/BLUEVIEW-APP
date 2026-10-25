"""THE FRONTEND WAITS FOR THE BACKEND (.github/scripts/backend_deploy.py).

On 2026-10-21 Railway paused deploys after #826 while Vercel and the EAS OTA
kept shipping, so the web build and every phone called endpoints the backend
did not have. These tests hold the gate's decisions against a REAL git history
(a throwaway repo) and its loops against a fake clock, and check the workflows
actually run the gate before they publish.
"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "backend_deploy", REPO / ".github" / "scripts" / "backend_deploy.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class _Repo:
    """main: a -- b -- c (first-parent), each commit at a set time."""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.sha = {}
        for i, name in enumerate("abc"):
            Path(self.dir, name).write_text(name)
            self.git("add", name)
            when = (T0 + timedelta(minutes=10 * i)).isoformat()
            self.git("commit", "-q", "-m", name, env={"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when})
            self.sha[name] = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args, env=None):
        return subprocess.run(["git", "-C", self.dir, *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    def runner(self, *args):
        if args and args[0] == "fetch":       # no remote in the throwaway repo
            return subprocess.CompletedProcess(args, 1, "", "")
        return self.git(*args)


class IncludesIsAncestryNotEquality(unittest.TestCase):

    def setUp(self):
        self.r = _Repo()

    def test_the_same_commit_and_a_later_one_include_it(self):
        s = self.r.sha
        self.assertTrue(gate.includes(s["b"], s["b"], self.r.runner))
        self.assertTrue(gate.includes(s["c"], s["b"], self.r.runner),
                        "Railway may skip straight to a later merge")

    def test_an_earlier_one_does_not(self):
        s = self.r.sha
        self.assertFalse(gate.includes(s["a"], s["b"], self.r.runner))

    def test_nothing_readable_or_an_unknown_commit_includes_nothing(self):
        self.assertFalse(gate.includes(None, self.r.sha["a"], self.r.runner))
        self.assertFalse(gate.includes("f" * 40, self.r.sha["a"], self.r.runner))


class TheWaitPublishesOnlyOnceTheBackendHasIt(unittest.TestCase):

    def setUp(self):
        self.r = _Repo()

    def _wait(self, served, timeout=1200):
        clock = {"t": 0.0}
        reads = iter(served)
        last = [None]

        def read():
            last[0] = next(reads, last[0])
            return last[0]

        def sleep(sec):
            clock["t"] += sec

        out = []
        rc = gate.wait(self.r.sha["c"], timeout, 30, read=read, git=self.r.runner,
                       sleep=sleep, clock=lambda: clock["t"], say=out.append)
        return rc, clock["t"], out

    def test_it_waits_through_older_builds_and_passes_when_the_merge_lands(self):
        s = self.r.sha
        rc, waited, _ = self._wait([s["a"], None, s["b"], s["c"]])
        self.assertEqual(rc, 0)
        self.assertEqual(waited, 90)

    def test_it_fails_after_the_timeout_and_says_nothing_was_published(self):
        rc, waited, out = self._wait([self.r.sha["b"]], timeout=1200)
        self.assertEqual(rc, 1)
        self.assertGreaterEqual(waited, 1200)
        self.assertLess(waited, 1200 + 31)
        self.assertIn("NOT published", out[-1])


class TheLagAlarm(unittest.TestCase):

    def setUp(self):
        self.r = _Repo()

    def _lag(self, served, now):
        out = []
        rc = gate.lag(30, "main", read=lambda: served, git=self.r.runner, now=now, say=out.append)
        return rc, out[-1]

    def test_fully_deployed_is_green(self):
        self.assertEqual(self._lag(self.r.sha["c"], T0 + timedelta(hours=5))[0], 0)

    def test_the_OLDEST_undeployed_merge_decides(self):
        # Deployed a; b merged at +10, c at +20. At +45, c is 25 min old but b is
        # 35: red, and it names b.
        rc, msg = self._lag(self.r.sha["a"], T0 + timedelta(minutes=45))
        self.assertEqual(rc, 1)
        self.assertIn(self.r.sha["b"][:12], msg)

    def test_inside_thirty_minutes_is_green(self):
        rc, _ = self._lag(self.r.sha["b"], T0 + timedelta(minutes=45))   # c is 25 min old
        self.assertEqual(rc, 0)

    def test_an_unreadable_version_counts_as_behind(self):
        rc, _ = self._lag(None, T0 + timedelta(hours=1))
        self.assertEqual(rc, 1)


def _wf(name):
    return yaml.safe_load((REPO / ".github" / "workflows" / name).read_text(encoding="utf-8"))


class TheWorkflowsRunTheGateBeforeTheyPublish(unittest.TestCase):

    def test_the_ota_waits_for_the_backend_before_eas_update(self):
        wf = _wf("ota-update.yml")
        job = wf["jobs"]["update"]
        steps = job["steps"]
        names = [s.get("name", "") for s in steps]
        gate_i = names.index("Wait for the backend to serve this commit")
        publish_i = names.index("Publish update")
        self.assertLess(gate_i, publish_i)
        g = steps[gate_i]
        self.assertIn("backend_deploy.py wait", g["run"])
        self.assertIn("--timeout 1200", g["run"])
        self.assertIn("production", g["if"])
        self.assertEqual(steps[0]["with"]["fetch-depth"], 0)
        self.assertTrue(wf["concurrency"]["cancel-in-progress"])
        self.assertGreater(job["timeout-minutes"], 20)

    def test_the_web_deploy_fires_the_hook_only_after_the_wait(self):
        run = _wf("web-deploy.yml")["jobs"]["deploy"]["steps"][1]["run"]
        self.assertLess(run.index("backend_deploy.py wait"), run.index('curl -fsS -X POST "$HOOK"'))
        self.assertIn('= "$TARGET" ]', run, "fires only if main did not move during the wait")

    def test_the_lag_alarm_is_scheduled_and_fails_the_job(self):
        wf = _wf("backend-deploy-lag.yml")
        on = wf.get("on") or wf.get(True)          # PyYAML reads `on:` as True
        self.assertTrue(on["schedule"][0]["cron"])
        run = wf["jobs"]["lag"]["steps"][1]["run"]
        self.assertIn("lag --max-minutes 30", run)
        self.assertIn("pipefail", run, "tee must not swallow the failure")


if __name__ == "__main__":
    unittest.main()
