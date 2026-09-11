#!/usr/bin/env python3
"""A COMMIT MESSAGE THAT DESCRIBES A CHANGE THE COMMIT DOES NOT CARRY.

THE INCIDENT. A fix was written in a worktree and not committed. A control run
then swapped the pre-fix file in and restored with
`git checkout HEAD -- backend/server.py` -- but HEAD was still the commit
BEFORE the fix, so the restore re-applied the defect and destroyed the work.
The commit that followed carried only a test file while its message described
the server change in detail. A full suite then ran for eight minutes and
reported one failure, which read as "my new test is wrong" rather than "my
change is missing".

Twice in one day, by the author of the rule forbidding it, written that
morning. That is not forgetting. The reflex arrives before the knowledge, so
the guard has to fire while you are typing rather than when you read back.

── WHY commit-msg AND NOT pre-commit ───────────────────────────────────────

`pre-commit` runs BEFORE the message exists. For `git commit` with no `-m` the
message is composed afterwards, so a pre-commit hook has nothing to compare the
diff against. `commit-msg` is handed the path of the message file and can
refuse. The repo already has a `pre-commit` hook for a different job; this is
its sibling, not its replacement.

── WHAT IT REFUSES, AND WHY IT REFUSES SO LITTLE ───────────────────────────

The obvious rule -- "refuse when the message names a path the diff does not
touch" -- was MEASURED against the last 80 commits of this repository before
it was written. Ten messages name a path; FIVE of those name a path they do
not touch, deliberately: they cite `docs/audits/check-harness.md` for a rule,
or `scripts/find-unpinned-palette-keys.cjs` as the gate that would have caught
something. A 50% refusal rate on real history is not a guard, it is a thing
people disable, and the citation habit it would punish is one of the more
valuable things about these messages.

So the blocking rules are the two with no measured false positives:

  UNSTAGED   the message names a file that has UNCOMMITTED CHANGES and is not
             in the index. You described it and did not add it. There is no
             reading of that which is correct.

  UNTRACKED  the message names a path git does not know and the commit does
             not add. A stale or mistyped path -- 6 of 120 historical commits
             cite one, and in every case the file existed when it was written
             and was deleted later, so at commit time this is ~0%.

And the third is printed, never enforced: the paths a message cites that this
commit does not touch. Seen while typing, it is the line that would have said
"backend/server.py is not in this commit". Enforced, it is the 50%.

Run the tests:  python scripts/commit_msg_guard.py --selftest
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Iterable, List, Tuple

#: A path shaped like one of this repo's own, with an extension. Deliberately
#: anchored on the top-level directory names rather than "anything with a
#: slash": prose here says "a/b" and "and/or" often enough that a loose
#: pattern would spend its credibility on noise.
_TOP = r"(?:backend|frontend|docs|dob_worker|scripts|\.github)"
PATH_RE = re.compile(rf"\b{_TOP}/[A-Za-z0-9_.\[\]/-]+\.[A-Za-z]{{1,6}}\b")

BLOCK_UNSTAGED = "unstaged"
BLOCK_UNTRACKED = "untracked"
NOTE_UNTOUCHED = "untouched"


def cited_paths(message: str) -> List[str]:
    """Every repo-shaped path a message names, comments and prose alike.

    COMMENT LINES ARE DROPPED FIRST. `git commit` appends the whole status
    block to the template as `#` lines -- which names every modified file --
    so a scan of the raw file would cite exactly the paths the author did not
    write, and the guard would be reading git's own output as the author's
    claim.
    """
    body = "\n".join(l for l in message.splitlines() if not l.lstrip().startswith("#"))
    seen, out = set(), []
    for m in PATH_RE.findall(body):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def evaluate(message: str, staged: Iterable[str], dirty_unstaged: Iterable[str],
             tracked: Iterable[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """(blocking problems, non-blocking notes). PURE, so it is testable."""
    staged, dirty_unstaged, tracked = set(staged), set(dirty_unstaged), set(tracked)
    problems: List[Tuple[str, str]] = []
    notes: List[str] = []
    for path in cited_paths(message):
        if path in staged:
            continue
        if path in dirty_unstaged:
            problems.append((BLOCK_UNSTAGED, path))
        elif path not in tracked:
            problems.append((BLOCK_UNTRACKED, path))
        else:
            notes.append(path)
    return problems, notes


def _git(*args: str) -> List[str]:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             check=True).stdout
    except Exception:
        return []
    return [l for l in out.splitlines() if l.strip()]


def main(argv: List[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    if len(argv) < 2:
        return 0
    try:
        message = open(argv[1], encoding="utf-8", errors="replace").read()
    except OSError:
        # A guard that cannot read the message must not block the commit: it
        # has learned nothing, and failing closed here would make every commit
        # hostage to this file.
        return 0

    problems, notes = evaluate(
        message,
        staged=_git("diff", "--cached", "--name-only"),
        dirty_unstaged=_git("diff", "--name-only"),
        tracked=_git("ls-files"),
    )

    if notes:
        sys.stderr.write(
            "\n  note: this message cites files the commit does not touch:\n")
        for p in notes:
            sys.stderr.write(f"          {p}\n")
        sys.stderr.write(
            "        (fine if you are citing them; check none is missing work)\n")

    if not problems:
        return 0

    sys.stderr.write("\n  COMMIT REFUSED -- the message describes work this "
                     "commit does not carry.\n\n")
    for kind, path in problems:
        if kind == BLOCK_UNSTAGED:
            sys.stderr.write(
                f"    {path}\n"
                "        named in the message, HAS uncommitted changes, and is "
                "not staged.\n"
                "        `git add` it, or take it out of the message.\n")
        else:
            sys.stderr.write(
                f"    {path}\n"
                "        named in the message and git does not know this path.\n"
                "        A stale path, a typo -- or work that was reverted out "
                "from under you.\n")
    sys.stderr.write(
        "\n  This exists because a commit once described a server change it "
        "did not\n  contain, after a `git checkout HEAD --` restore against an "
        "uncommitted tree.\n  See docs/audits/check-harness.md section 14.\n\n"
        "  To commit anyway: git commit --no-verify\n\n")
    return 1


def _selftest() -> int:
    """Executed cases, because a guard nobody can run is a paragraph."""
    passed = failed = 0

    def ok(cond, label):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}")

    tracked = {"backend/server.py", "docs/audits/check-harness.md",
               "backend/tests/test_x.py"}

    # THE INCIDENT ITSELF.
    p, n = evaluate("rewrites backend/server.py to gate the read",
                    staged={"backend/tests/test_x.py"},
                    dirty_unstaged={"backend/server.py"}, tracked=tracked)
    ok(p == [(BLOCK_UNSTAGED, "backend/server.py")],
       "a named file with unstaged changes REFUSES the commit")

    # THE CITATION HABIT THIS REPO LIVES BY -- must never block.
    p, n = evaluate("see docs/audits/check-harness.md for the rule",
                    staged={"backend/server.py"}, dirty_unstaged=set(),
                    tracked=tracked)
    ok(p == [] and n == ["docs/audits/check-harness.md"],
       "citing a clean, untouched file is a NOTE and never a refusal")

    p, _ = evaluate("touches backend/server.py", staged={"backend/server.py"},
                    dirty_unstaged=set(), tracked=tracked)
    ok(p == [], "a file that IS staged raises nothing")

    p, _ = evaluate("fixes backend/nope/gone.py", staged={"backend/server.py"},
                    dirty_unstaged=set(), tracked=tracked)
    ok(p == [(BLOCK_UNTRACKED, "backend/nope/gone.py")],
       "a path git does not know is refused")

    p, _ = evaluate("adds backend/tests/test_new.py",
                    staged={"backend/tests/test_new.py"},
                    dirty_unstaged=set(), tracked=tracked)
    ok(p == [], "a NEW file is fine when it is staged")

    # git's own status block must not be read as the author's claim.
    msg = ("a small fix\n\n"
           "# Changes not staged for commit:\n"
           "#\tmodified:   backend/server.py\n")
    p, n = evaluate(msg, staged={"backend/tests/test_x.py"},
                    dirty_unstaged={"backend/server.py"}, tracked=tracked)
    ok(p == [] and n == [],
       "the commented status block is not mistaken for the message")

    ok(cited_paths("and/or this and that") == [],
       "prose with a slash is not a path")
    ok(cited_paths("backend/server.py and backend/server.py") ==
       ["backend/server.py"], "a path named twice is reported once")

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
