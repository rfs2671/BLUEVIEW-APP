"""THE COMMIT-MESSAGE GUARD, RUN RATHER THAN DESCRIBED.

A commit once described a server change it did not contain. The work had been
destroyed by a `git checkout HEAD -- <file>` restore against an UNCOMMITTED
tree, so the restore re-applied the defect instead of putting the fix back. The
full suite then ran green-but-for-two about a tree that no longer held the
change.

Twice in one day, by the author of the rule against it, written that morning.
The checklist item was not enough, so `scripts/commit_msg_guard.py` fires while
the message is being written. This file is how CI knows it still works.

WHY THE GUARD REFUSES SO LITTLE, asserted here as well as argued there: the
obvious rule -- refuse when the message names a path the diff does not touch --
was measured at a 50% false-positive rate against the last 80 commits, because
half of them cite a file deliberately. A guard at that rate is one people turn
off.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _ROOT / "scripts" / "commit_msg_guard.py"
_HOOK = _ROOT / ".githooks" / "commit-msg"


def _load():
    spec = importlib.util.spec_from_file_location("commit_msg_guard", _GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheGuardExistsAndRuns(unittest.TestCase):

    def test_the_guard_and_the_hook_are_both_present(self):
        self.assertTrue(_GUARD.is_file(), f"{_GUARD} is missing")
        self.assertTrue(_HOOK.is_file(), f"{_HOOK} is missing")

    def test_the_hook_invokes_the_guard_rather_than_restating_it(self):
        """Two copies of this rule would drift, and the shell copy is the one
        nobody can test."""
        text = _HOOK.read_text(encoding="utf-8")
        self.assertIn("commit_msg_guard.py", text)

    def test_the_hook_never_blocks_when_it_cannot_run(self):
        """A tree without the guard, or a machine without python, must still
        be able to commit. A guard that bricks the repository when it is
        half-installed is worse than none."""
        text = _HOOK.read_text(encoding="utf-8")
        self.assertIn('[ -f "$GUARD" ] || exit 0', text)
        self.assertIn("exit 0", text.rsplit("\n", 3)[-2] + "\n")

    def test_the_installer_makes_it_executable(self):
        sh = (_ROOT / "scripts" / "install-hooks.sh").read_text(encoding="utf-8")
        self.assertIn("chmod +x .githooks/commit-msg", sh)

    def test_its_own_selftest_passes(self):
        """The guard ships executable cases; run them rather than copy them."""
        r = subprocess.run([sys.executable, str(_GUARD), "--selftest"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 failed", r.stdout)


class TheRulesThemselves(unittest.TestCase):
    """Asserted here too, not only inside the guard: a self-test a suite never
    runs is a check that passes without running."""

    def setUp(self):
        self.m = _load()
        self.tracked = {"backend/server.py", "docs/audits/check-harness.md"}

    def test_THE_INCIDENT_is_refused(self):
        problems, _ = self.m.evaluate(
            "the project row is read only when the answer can depend on it\n\n"
            "backend/server.py now gates the read on _is_site_device.",
            staged={"backend/tests/test_x.py"},
            dirty_unstaged={"backend/server.py"}, tracked=self.tracked)
        self.assertEqual(problems, [(self.m.BLOCK_UNSTAGED, "backend/server.py")])

    def test_THE_CITATION_HABIT_is_never_refused(self):
        """Five of the last eighty commits cite a file they do not touch. If
        this ever blocks, the guard gets disabled and the incident rule goes
        with it."""
        problems, notes = self.m.evaluate(
            "assertTrue, not assertIn — see docs/audits/check-harness.md §12",
            staged={"backend/server.py"}, dirty_unstaged=set(),
            tracked=self.tracked)
        self.assertEqual(problems, [])
        self.assertEqual(notes, ["docs/audits/check-harness.md"])

    def test_gits_own_status_block_is_not_read_as_the_authors_claim(self):
        """`git commit` appends the status block as `#` lines, naming every
        modified file. Scanning the raw file would make the guard read git's
        output as the author's claim and refuse almost everything."""
        problems, notes = self.m.evaluate(
            "a small fix\n\n# Changes not staged for commit:\n"
            "#\tmodified:   backend/server.py\n",
            staged={"backend/tests/test_x.py"},
            dirty_unstaged={"backend/server.py"}, tracked=self.tracked)
        self.assertEqual((problems, notes), ([], []))

    def test_prose_with_a_slash_is_not_a_path(self):
        self.assertEqual(self.m.cited_paths("and/or, either/or, 50/50"), [])

    def test_a_staged_new_file_is_fine(self):
        problems, _ = self.m.evaluate(
            "adds backend/tests/test_new.py",
            staged={"backend/tests/test_new.py"}, dirty_unstaged=set(),
            tracked=self.tracked)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
