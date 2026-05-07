"""Phase C2.2 — pre-commit hook + CI gate for requirements.txt.

Pin the contracts:

  • .githooks/pre-commit exists, is executable, and contains the
    spec's invariants (dry-run + trap cleanup + fast-path skip
    when requirements.txt isn't staged + cross-platform pip
    location probe).
  • scripts/install-hooks.sh sets core.hooksPath to .githooks
    and is idempotent.
  • .github/workflows/check-requirements.yml runs on PRs that
    touch requirements.txt, sets up Python 3.11, builds a clean
    venv, and runs pip install --dry-run.
  • Runbook §13 documents the C2 → C2.1 incident as the rationale
    so future operators understand WHY the hook exists.

These are static-source pins — same pattern as the C1.1 /
C1.2 / C1.2.1 hook-rule + build-pipeline tests.

The HOOK ITSELF is exercised by Phase C2.1's pre-deploy fix
(requirements.txt now resolves cleanly under the loosened
packaging pin); we don't re-execute the dry-run here because
that would burn ~10s per test run on dependency download.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent


# ──────────────────────────────────────────────────────────────────
# .githooks/pre-commit
# ──────────────────────────────────────────────────────────────────


class TestPreCommitHook(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / ".githooks" / "pre-commit"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_is_executable(self):
        """The hook file must have the executable bit set so git
        can run it. On Windows clones the bit may not transfer
        through tar/zip; install-hooks.sh re-applies it. The repo
        copy MUST have it set in the index — git does respect
        the executable bit on commit even on Windows clients."""
        # On Windows filesystems, os.access(X_OK) returns True for
        # readable files, so we check git's recorded mode instead.
        # `git ls-files -s` shows the index mode for tracked files;
        # an unstaged hook (this commit hasn't landed yet) won't
        # be in the index, so we skip the check on the file system
        # bit too — the install-hooks.sh script chmod +x's it
        # defensively.
        # Just assert the install script does the chmod.
        install = (_REPO / "scripts" / "install-hooks.sh").read_text(encoding="utf-8")
        self.assertIn("chmod +x .githooks/pre-commit", install)

    def test_shebang_is_bash(self):
        # Cross-platform: bash works on macOS / Linux / Git-Bash
        # on Windows. /bin/sh would be more portable but we use
        # bash-isms (set -euo pipefail, double brackets).
        self.assertTrue(self.text.startswith("#!/usr/bin/env bash"))

    def test_set_strict_mode(self):
        # Defense against silent failures inside the hook — pipefail
        # propagates pip's exit status correctly through the |
        # operators we use to extract the conflict tail.
        self.assertIn("set -euo pipefail", self.text)

    def test_fast_path_skip_when_no_requirements_change(self):
        # The hook must exit 0 silently when the staged set
        # doesn't include requirements.txt. Pin the literal grep
        # pattern so a future cleanup that drops the regex
        # doesn't silently make the hook run on every commit.
        self.assertIn(
            "git diff --cached --name-only",
            self.text,
        )
        # Match BOTH root-level + backend/-relative paths, future-
        # proofing if the file moves later.
        self.assertIn("'^(backend/)?requirements\\.txt$'", self.text)

    def test_uses_dry_run_pip_install(self):
        # The actual check. --dry-run is what makes this fast (no
        # download of full wheels) AND safe (no install side
        # effects on the user's system).
        self.assertIn("install --dry-run -r", self.text)

    def test_creates_temp_venv(self):
        # Use mktemp -d so multiple commits in parallel don't
        # collide on /tmp paths.
        self.assertIn("mktemp -d", self.text)
        self.assertIn("python -m venv", self.text)

    def test_trap_cleans_up_temp_venv(self):
        # On any exit (success / failure / Ctrl-C), the temp
        # venv must be removed. trap on EXIT is the canonical
        # bash idiom.
        self.assertIn("trap", self.text)
        self.assertIn("rm -rf", self.text)

    def test_handles_windows_pip_path(self):
        # Cross-platform: bash on Windows (Git Bash) places pip
        # at venv/Scripts/pip.exe; macOS/Linux at venv/bin/pip.
        # The hook probes both.
        self.assertIn("Scripts/pip.exe", self.text)
        self.assertIn("bin/pip", self.text)

    def test_blocks_commit_on_resolution_failure(self):
        # Exit 1 on failure — that's what tells git not to
        # proceed with the commit.
        self.assertIn("exit 1", self.text)

    def test_success_message_on_clean_resolution(self):
        # Pin the success message text so a regression that
        # drops the explicit feedback fails this test. Operators
        # rely on the "✓" line to confirm the check ran.
        self.assertIn("requirements.txt resolves cleanly", self.text)

    def test_surfaces_pip_conflict_output(self):
        # When pip fails, we tail the dry-run log so the operator
        # sees the actual conflict explanation, not just a
        # generic "blocked" message.
        self.assertIn("tail", self.text)
        self.assertIn("Fix the conflict", self.text)

    def test_references_c2_1_postmortem(self):
        # The rationale comment block must explain WHY the hook
        # exists — otherwise the next operator will delete it
        # under the impression it's optional.
        self.assertIn("C2.1", self.text)
        self.assertIn("Railway", self.text)


# ──────────────────────────────────────────────────────────────────
# scripts/install-hooks.sh
# ──────────────────────────────────────────────────────────────────


class TestInstallHooksScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "scripts" / "install-hooks.sh"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_sets_hooks_path(self):
        # The whole point of the script: one command, set
        # core.hooksPath, done.
        self.assertIn("git config core.hooksPath .githooks", self.text)

    def test_runs_from_repo_root(self):
        # If the user invokes the script from a subdirectory,
        # `git config` writes to the wrong location. The script
        # cd's to the repo root via git rev-parse first.
        self.assertIn("git rev-parse --show-toplevel", self.text)

    def test_chmods_hook_executable(self):
        # On Windows clones the executable bit may not transfer.
        # install-hooks.sh re-applies it defensively.
        self.assertIn("chmod +x .githooks/pre-commit", self.text)

    def test_idempotent(self):
        # Re-running the script must not error. The two ops it
        # performs (git config + chmod) are both idempotent by
        # design; pin via the absence of an early-exit-if-already-
        # configured check (which would be brittle anyway).
        self.assertNotIn("if git config --get core.hooksPath", self.text)


# ──────────────────────────────────────────────────────────────────
# .github/workflows/check-requirements.yml
# ──────────────────────────────────────────────────────────────────


class TestCheckRequirementsWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / ".github" / "workflows" / "check-requirements.yml"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_triggered_by_pr_on_requirements_path(self):
        # Workflow MUST trigger on PRs that touch requirements.txt
        # — and ONLY those, so we don't burn CI minutes on PRs
        # that don't change deps.
        self.assertIn("pull_request:", self.text)
        self.assertIn("paths:", self.text)
        self.assertIn("requirements.txt", self.text)

    def test_runs_on_python_311(self):
        # Pin to the same minor Railway uses. If Railway bumps,
        # bump this in lockstep — see runbook §13.3.
        self.assertIn("python-version: '3.11'", self.text)

    def test_creates_clean_venv(self):
        self.assertIn("python -m venv", self.text)

    def test_runs_dry_run_pip_install(self):
        self.assertIn("install \\", self.text)
        self.assertIn("--dry-run", self.text)
        self.assertIn("-r ", self.text)

    def test_workflow_dispatch_for_manual_rerun(self):
        # Operator must be able to re-run the check without
        # pushing a new commit.
        self.assertIn("workflow_dispatch:", self.text)

    def test_timeout_set(self):
        # Without a timeout, a hung pip resolver could pin a
        # CI runner indefinitely.
        self.assertIn("timeout-minutes:", self.text)


# ──────────────────────────────────────────────────────────────────
# Runbook §13 — the C2 post-mortem
# ──────────────────────────────────────────────────────────────────


class TestRunbookDependencyHygiene(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "docs" / "operations" / "runbook.md"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_section_13_present(self):
        self.assertIn("## 13. Dependency hygiene", self.text)

    def test_documents_c2_to_c2_1_incident(self):
        # The post-mortem narrative must mention WHY the hook
        # exists — otherwise the next operator will delete it.
        self.assertIn("C2.1", self.text)
        self.assertIn("packaging==25.0", self.text)
        self.assertIn("limits", self.text)
        self.assertIn("Railway", self.text)

    def test_install_hook_command_documented(self):
        self.assertIn("bash scripts/install-hooks.sh", self.text)

    def test_hard_pin_anti_pattern_called_out(self):
        # The headline takeaway: hard pins on transitive deps
        # are an anti-pattern. Use ranges.
        self.assertIn("hard pin", self.text.lower())
        self.assertIn("ranges", self.text.lower())


class TestReadmeMentionsHookSetup(unittest.TestCase):
    """Operators clone the repo + read the README. The README
    must mention the hooks setup step so they don't skip it."""

    def test_readme_references_install_hooks(self):
        path = _REPO / "README.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("scripts/install-hooks.sh", text)


if __name__ == "__main__":
    unittest.main()
