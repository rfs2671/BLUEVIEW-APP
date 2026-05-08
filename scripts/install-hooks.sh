#!/usr/bin/env bash
#
# Phase C2.2 — enable the project's git hooks.
#
# Sets `git config core.hooksPath .githooks` so the .githooks/
# directory in this repo becomes the active hooks dir for this
# clone. Idempotent — safe to re-run.
#
# Why a script instead of telling people to run the one-liner:
# operators routinely forget. A single command they can copy-paste
# is easier to remember + easier to verify in the runbook.

set -euo pipefail

# Run from the repo root regardless of where the user invokes us
# from. `git rev-parse --show-toplevel` returns the repo root path.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "ERROR: not inside a git repository. Run this from inside the repo."
    exit 1
fi
cd "$REPO_ROOT"

if [ ! -d ".githooks" ]; then
    echo "ERROR: .githooks/ directory missing. Are you on the right branch?"
    exit 1
fi

git config core.hooksPath .githooks

# Make sure the hook is executable. Some clones (especially after
# `git clone --filter=...` or on Windows where chmod +x on a fresh
# clone is a noop) may have it as 0644.
chmod +x .githooks/pre-commit 2>/dev/null || true

echo "✓ Git hooks path set to .githooks"
echo
echo "  Verify with:  git config --get core.hooksPath"
echo "  Disable with: git config --unset core.hooksPath"
echo
echo "  The pre-commit hook now runs on every commit. It is fast (< 1s)"
echo "  for commits that don't touch requirements.txt, and runs a"
echo "  clean-venv pip resolution check (~5-10s) for commits that do."
echo
echo "  See docs/operations/runbook.md \"Dependency Hygiene\" for the"
echo "  Phase C2.1 post-mortem that motivated the hook."
