"""A JOB THAT SKIPS ON A DRAFT MUST RUN WHEN THE DRAFT IS TAKEN READY.

    python -m pytest backend/tests/test_a_draft_taken_ready_runs_the_gates.py

── WHAT THIS EXISTS TO CATCH, MEASURED ─────────────────────────────────────

`tests.yml` skips three jobs on `github.event.pull_request.draft == false`:
the backend suite, the frontend suite and the mount smoke -- between them
every gate that executes anything. GitHub's default trigger types are
[opened, synchronize, reopened]. `ready_for_review` is NOT among them.

So a draft PR's heavy jobs were reported "skipping", and marking it ready
fired an event the workflow did not listen for. The skipped runs stayed
skipped. On #603 this was watched happening: marked ready at 07:26, all three
still "skipping" afterwards, and the only way to get a real run was to close
and reopen the PR so a `reopened` event fired.

THE REASON THIS IS A GATE AND NOT A NOTE: "skipping" is not red. A reviewable
PR shows a neutral grey tick beside every suite and a green merge button, and
an empty result is indistinguishable from a passing one at a glance. That is
the failure shape this repository keeps pinning -- a check that cannot fail is
not a check, and a check that never RUNS is the same thing with better
manners.

── WHAT WOULD PROVE THIS TEST WRONG ────────────────────────────────────────

It reads YAML, not GitHub. It cannot see that a run actually happened. If
`gh pr checks <n>` on a PR just taken out of draft still shows the three heavy
jobs as "skipping", this assertion is green and the defect is back by some
route the text does not describe -- a changed condition, a job moved to
another file, an org-level policy. The evidence is the PR, not this file.

── AND IT IS DELIBERATELY DERIVED, NOT TYPED ───────────────────────────────

The list of jobs below is not hard-coded. It is every job in the file whose
`if:` mentions `draft`, so a FOURTH job added with the same condition is
covered the day it is added rather than the day somebody remembers this file.
That is the lesson from the gate that named its own gap and said "audited by
hand": a census beats a list.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_YML = ROOT / ".github" / "workflows" / "tests.yml"

#: The `on:` block: from `on:` to the next top-level key.
ON_BLOCK_RE = re.compile(r"^on:\s*$(.*?)^[a-zA-Z]", re.S | re.M)
#: `types: [a, b, c]` anywhere inside it.
TYPES_RE = re.compile(r"^\s*types:\s*\[([^\]]*)\]", re.M)


def _read() -> str:
    assert TESTS_YML.exists(), f"{TESTS_YML} is missing"
    return TESTS_YML.read_text(encoding="utf-8")


def _on_block(body: str) -> str:
    m = ON_BLOCK_RE.search(body)
    assert m, "tests.yml has no `on:` block"
    return m.group(1)


def _jobs_gated_on_draft(body: str):
    """Every job whose `if:` mentions the draft flag, by job key.

    A CENSUS, NOT A LIST. Derived from the file so a job added later with the
    same condition is covered without anyone editing this test.
    """
    # Job keys are the two-space-indented mapping keys under `jobs:`.
    jobs = {}
    current = None
    for line in body.splitlines():
        m = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            jobs[current] = []
        elif current is not None and line.startswith("    "):
            jobs[current].append(line)
        elif line and not line.startswith(" "):
            current = None
    return {k: "\n".join(v) for k, v in jobs.items()
            if "draft" in "\n".join(v)}


class TheDraftGateHasTheTriggerItNeeds(unittest.TestCase):
    def test_some_job_actually_gates_on_draft(self):
        """THE PREMISE OF EVERY OTHER ASSERTION HERE.

        If nobody skips on drafts any more, the `types:` line below is
        harmless but pointless, and this file should be deleted rather than
        left asserting something nothing depends on. Failing here says so out
        loud instead of leaving three green tests guarding nothing.
        """
        gated = _jobs_gated_on_draft(_read())
        self.assertTrue(
            gated,
            "no job in tests.yml gates on draft any more — this test now "
            "guards nothing and should be removed with the gate")

    def test_ready_for_review_is_a_trigger_type(self):
        """THE ASSERTION THIS FILE IS FOR."""
        block = _on_block(_read())
        m = TYPES_RE.search(block)
        self.assertIsNotNone(
            m,
            "the pull_request trigger declares no `types:`, so it uses the "
            "default [opened, synchronize, reopened] — and a draft taken "
            "ready fires an event this workflow does not listen for. The "
            "heavy suites stay 'skipping' on a reviewable PR.")
        types = {t.strip() for t in m.group(1).split(",") if t.strip()}
        self.assertIn(
            "ready_for_review", types,
            f"`types:` is {sorted(types)} — taking a draft out of draft will "
            "not run the suites that skipped because it was a draft")

    def test_the_default_types_are_not_lost(self):
        """DECLARING `types:` REPLACES THE DEFAULTS, it does not extend them.

        Adding `ready_for_review` alone would fix the draft case and stop
        every push and every newly opened PR from running anything at all --
        a far larger hole than the one being closed.
        """
        block = _on_block(_read())
        m = TYPES_RE.search(block)
        # REPORT, DO NOT CRASH. With no `types:` at all this line used to raise
        # AttributeError on None, which is a failure that says nothing about
        # the workflow -- and a gate whose red is unreadable gets skimmed past.
        # The defaults are in force in that case, which satisfies this test's
        # own question; the sibling above is the one that fails, with a
        # sentence.
        if m is None:
            return
        types = {t.strip() for t in m.group(1).split(",") if t.strip()}
        for required in ("opened", "synchronize", "reopened"):
            self.assertIn(
                required, types,
                f"declaring `types:` dropped the default {required!r}: "
                "pull requests would stop being tested on that event")

    def test_the_gated_jobs_are_the_ones_that_execute_something(self):
        """A note for the next reader, asserted so it stays true.

        The three draft-gated jobs are the whole of this repository's
        executing coverage. If that census ever shrinks to nothing the gate
        above is cosmetic; if it grows, the derived list already covers it.
        """
        gated = _jobs_gated_on_draft(_read())
        self.assertGreaterEqual(
            len(gated), 3,
            f"only {sorted(gated)} gate on draft; this file's comment claims "
            "the backend suite, the frontend suite and the mount smoke all "
            "do — one of the two is now wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
