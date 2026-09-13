"""THE ONLY WAY A MULTI-PART EDIT IS APPLIED TO THIS REPOSITORY.

── WHY THIS IS A MODULE AND NOT A PRACTICE ──────────────────────────────────

Three times in one session a scripted edit reported success for work it did not
do:

    a `str.replace` with no assertion on the count -- matched nothing, returned
        the string unchanged, and the registry line was never added
    a script whose SECOND section raised, leaving sections 3 and 4 unapplied,
        reported as landed in a commit message and a pull request body
    the same shape again, one round later, on a different file

Every one was found by reading the code afterwards rather than by a check. The
common cause is not carelessness with the edit; it is that **the evidence of a
section not running is the ABSENCE of its own output**, and absence is the one
thing a reader does not notice.

A convention would not have stopped any of them, because all three were written
by somebody who knew the convention. So this is a module with an exit code.

── WHAT IT GUARANTEES ───────────────────────────────────────────────────────

  * Every section is attempted, INDEPENDENTLY. One failure does not silence
    the rest, so the ledger is complete rather than truncated at the first
    problem.
  * Every outcome is NAMED: APPLIED, ALREADY (the target text is already in
    place, which is a success, not a miss), MISSED, or AMBIGUOUS.
  * ALREADY AND MISSED ARE NEVER CONFLATED. The first version of this ledger
    did conflate them and reported two false alarms on its first run -- the
    same ambiguity in miniature.
  * The file is written only if it still PARSES.
  * The process exits NON-ZERO if anything missed, so a caller that ignores
    the ledger still cannot report success.

── USE ──────────────────────────────────────────────────────────────────────

    from tools.apply_patch import Patch
    p = Patch()
    p.sub("server.py", OLD, NEW, "what this change is")
    p.raise_if_incomplete()          # prints the ledger, exits non-zero
"""

from __future__ import annotations

import ast
import io
import sys
from typing import List, Tuple

APPLIED = "APPLIED"
ALREADY = "ALREADY"
MISSED = "MISSED"
AMBIGUOUS = "AMBIGUOUS"


class Patch:
    def __init__(self) -> None:
        self.ledger: List[Tuple[str, str, str]] = []

    # ── ONE EDIT ─────────────────────────────────────────────────────────
    def sub(self, path: str, old: str, new: str, name: str) -> None:
        """Replace `old` with `new` exactly once, or say why not.

        `new` ALREADY PRESENT IS A SUCCESS. A patch re-run after a partial
        failure must be able to finish the job, and a section that is already
        in place is not a problem -- reporting it as one is how the previous
        ledger produced two false alarms and sent its author looking for bugs
        that were not there.
        """
        try:
            src = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            self.ledger.append((MISSED, name, f"{path}: {exc.__class__.__name__}"))
            return

        n = src.count(old)
        if n == 0:
            if new and new in src:
                self.ledger.append((ALREADY, name, _short(path)))
            else:
                self.ledger.append((MISSED, name, f"{_short(path)}: no match"))
            return
        if n > 1:
            self.ledger.append(
                (AMBIGUOUS, name, f"{_short(path)}: {n} matches -- anchor it"))
            return

        out = src.replace(old, new, 1)
        if path.endswith(".py"):
            try:
                ast.parse(out)
            except SyntaxError as exc:
                self.ledger.append((MISSED, name, f"{_short(path)}: {exc}"))
                return
        io.open(path, "w", encoding="utf-8", newline="").write(out)
        self.ledger.append((APPLIED, name, _short(path)))

    # ── THE VERDICT ──────────────────────────────────────────────────────
    def raise_if_incomplete(self) -> None:
        print("-- PATCH LEDGER --")
        bad = 0
        for state, name, where in self.ledger:
            print(f"  {state:9} {name:52} {where}")
            if state in (MISSED, AMBIGUOUS):
                bad += 1
        ok = len(self.ledger) - bad
        print(f"\n  {ok} applied or already in place, {bad} NOT APPLIED")
        if bad:
            print("\n  NOTHING HERE IS DONE. Do not report any part of this "
                  "patch as landed until this line reads zero.")
            sys.exit(1)


def _short(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1]
