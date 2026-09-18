"""THE JS SUITE'S DEPENDENCIES ARE INSTALLED BEFORE IT RUNS.

    python -m pytest backend/tests/test_the_js_suite_gets_its_dependencies.py

── THE FAILURE THIS GUARDS, WHICH HAS ALREADY HAPPENED ONCE ────────────────

67 of the 178 frontend test files cannot run without `node_modules`: 40 require
`@babel/core` directly and 28 more reach it through `src/utils/esmHarness.cjs`.
They transpile real JSX and execute it, which is the strongest thing the
frontend suite does.

With no `node_modules` they die on "Cannot find module '@babel/core'". The
workflow's own comment records what that looked like the last time: the runner
halts on the FIRST non-zero exit, those files sorted after one that was already
failing, and so they had never executed in CI even once. They passed on
developers' machines purely because node_modules happened to exist there.

`npm ci` is the step that fixed it. Deleting it -- as an optimisation, in a
cost-trimming pass, or by moving the suite to a job that does not install --
would silently stop running a THIRD of the frontend suite, and the job would
stay green until the first surviving file failed.

── WHY THE ASSERTION IS ON THE STEPS AND NOT ON A COUNT ────────────────────

The count is what keeps going stale. This file asserts the ORDER of two steps,
which is the thing whose removal is silent, and derives the population only to
report it -- never to assert an exact number that will be wrong next week.

── WHAT WOULD PROVE THIS TEST WRONG ────────────────────────────────────────

It reads YAML. It cannot see that `npm ci` succeeded, or that the runner
actually executed all 178 files. A CI log showing "Cannot find module" is the
evidence that matters; this only proves the install is still declared, still in
the same job, and still ahead of the suite.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_YML = ROOT / ".github" / "workflows" / "tests.yml"
FRONTEND = ROOT / "frontend"

#: The frontend job's block: from `frontend-tests:` to the next job key.
JOB_RE = re.compile(r"^  frontend-tests:\s*$(.*?)^  [a-zA-Z0-9_-]+:\s*$",
                    re.S | re.M)


def _strip_yaml_comments(text: str) -> str:
    """Drop whole-line `#` comments.

    THIS IS NOT TIDINESS, IT IS THE DIFFERENCE BETWEEN A GUARD AND A PROP.
    The first version of this file asserted `"npm ci" in job` against the raw
    YAML. The comment block this change ADDED to the workflow explains why
    `npm ci` must not be removed -- and says "npm ci" twice while doing it. So
    the assertion matched its own prose: deleting the real step left the test
    green. Caught by running the control, not by reading it.

    Only whole-line comments are removed. An inline `#` inside a shell `run:`
    is part of the command, and cutting at it would corrupt the very lines
    being inspected.
    """
    return "\n".join(l for l in text.splitlines()
                     if not l.lstrip().startswith("#"))


def _job() -> str:
    """The frontend-tests job, PROSE REMOVED. Every assertion below reads this,
    never the raw file."""
    body = TESTS_YML.read_text(encoding="utf-8")
    m = JOB_RE.search(body)
    assert m, "tests.yml has no frontend-tests job"
    return _strip_yaml_comments(m.group(1))


def _files_needing_node_modules():
    """The census the workflow comment describes, run for real.

    DERIVED, NOT LISTED. A file added tomorrow that uses the shared harness is
    counted the day it is added. Returns paths relative to `frontend`.
    """
    out = set()
    for pattern in (r"require\(['\"]@babel/core", r"esmHarness"):
        try:
            r = subprocess.run(
                ["grep", "-rlE", pattern, "src", "app"],
                cwd=FRONTEND, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            # No grep (a bare Windows shell). Returning None makes the callers
            # SKIP rather than pass: a census that could not be taken must not
            # report an empty population, which would read as "nothing needs
            # node_modules" — the opposite of the truth.
            return None
        for line in r.stdout.splitlines():
            if re.search(r"test\.(cjs|js)$", line.strip()):
                out.add(line.strip())
    return out


class TheInstallStepIsStillThere(unittest.TestCase):
    def test_the_frontend_job_installs_dependencies(self):
        """THE ASSERTION THIS FILE IS FOR."""
        self.assertIn(
            "npm ci", _job(),
            "the frontend job stopped installing node_modules — 67 test files "
            "that transpile JSX will die on \"Cannot find module "
            "'@babel/core'\", and the runner halts on the first failure so "
            "the rest never run either")

    def test_the_install_comes_BEFORE_the_suite_runs(self):
        """Order, not just presence.

        An install step that runs after the suite is the same outage with a
        tidier log. The suite is invoked by a step that runs the .test.cjs
        files; the install must appear ahead of it in the step list.
        """
        job = _job()
        install_at = job.find("npm ci")
        self.assertNotEqual(install_at, -1, "no npm ci in the frontend job")
        # The step that actually executes the JS tests: it names the test glob.
        m = re.search(r"test\.cjs", job)
        self.assertIsNotNone(
            m, "the frontend job no longer names the .test.cjs suite — this "
               "test can no longer tell where the suite is invoked")
        self.assertLess(
            install_at, m.start(),
            "npm ci runs AFTER the JS suite: every file that transpiles JSX "
            "fails first and the install cannot help them")

    def test_the_suite_and_the_install_are_in_the_SAME_job(self):
        """A GitHub job gets its own runner and its own filesystem. Installing
        in one job does nothing for a suite that runs in another, and the
        symptom is identical to not installing at all."""
        job = _job()
        self.assertTrue(
            "npm ci" in job and "test.cjs" in job,
            "the install and the JS suite are no longer in one job, so the "
            "suite runs on a machine that never installed anything")


class TheCensusStillHasSubjects(unittest.TestCase):
    """The install step matters only while something needs it.

    NO EXACT COUNT IS ASSERTED. That number is what went stale twice in this
    file's own history ("26 of the 28", then "a closed set of two" against a
    real 67). What is asserted is that the population is not EMPTY -- because
    if it ever is, `npm ci` is dead weight and this file should say so rather
    than keep guarding nothing.
    """

    def test_something_still_needs_node_modules(self):
        files = _files_needing_node_modules()
        if files is None:
            self.skipTest("grep unavailable — the census cannot be taken here")
        self.assertTrue(
            files,
            "no frontend test transpiles JSX any more: npm ci in the frontend "
            "job is now unnecessary, and this test guards nothing. Remove "
            "both, together, deliberately.")

    def test_the_census_is_reportable(self):
        """Prints the population, so a reader gets the current number from a
        run rather than from a sentence somebody typed months ago."""
        files = _files_needing_node_modules()
        if files is None:
            self.skipTest("grep unavailable — the census cannot be taken here")
        total = len(list(FRONTEND.glob("src/**/*.test.cjs"))) + \
            len(list(FRONTEND.glob("app/**/*.test.cjs")))
        print(f"\n  frontend tests needing node_modules: {len(files)}"
              f" (of {total} .test.cjs under src/ and app/)")
        self.assertLessEqual(
            len(files), max(total, 1),
            "the census counted more dependent files than there are test "
            "files, so the census itself is wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
