"""Where the source-PDF fixtures live, and saying so out loud when they don't.

── SEVEN TESTS THAT READ REAL DRAWINGS HAVE NEVER RUN IN CI ───────────────

They resolved their fixture as:

    PDFS = Path(__file__).resolve().parents[3] / "pdfs"

From `backend/tests/`, `parents[3]` is the directory CONTAINING the repo, not
the repo. On a GitHub runner the checkout lands at
`/home/runner/work/BLUEVIEW-APP/BLUEVIEW-APP`, so that expression points at
`/home/runner/work/BLUEVIEW-APP/pdfs` — a sibling of the checkout that
nothing creates. `.github/workflows/tests.yml` runs the full suite from a
bare `actions/checkout@v4`: no LFS, no artifact download, no fetch step.

COMMITTING THE FIXTURES WOULD NOT HAVE FIXED IT. A `pdfs/` directory at the
repo root lands at `parents[2]`; the expression looks at `parents[3]`. The
path points outside whatever gets checked out, so NO CLONE OF ANY KIND can
satisfy it — and the obvious fix would have added ~100 MB to the repo and
left the tests skipping exactly as before.

It worked locally only by coincidence of layout: a developer worktree that
happens to sit beside a `pdfs/` directory resolves it, and one that does not
silently skips. Two sessions running the same suite reported 8738 and 8768
passing and both were green.

── WHY A SKIP IS THE DANGEROUS PART, NOT THE MISSING FILE ─────────────────

A skip reads as green. The suite reported exactly what it was asked to
report, nothing malfunctioned, and nobody was wrong — and seven tests that
read real drawings were green-by-skip on every PR this repo has merged. That
is `an absence needs a warrant` turned on the suite itself: it refused to run
something and told nobody, and the refusal was indistinguishable from success
in the only output anyone reads.

So this module does two things, and the second is the point:

  1. finds the fixtures by anchoring to a REPO MARKER instead of counting
     parent directories, and looks in places a checkout can actually have
  2. WARNS AT IMPORT when they are absent, so the absence appears in pytest's
     warnings summary — which prints by default, unlike a skip reason, which
     needs `-rs`

Set `PLAN_FIXTURE_PDFS` to point anywhere else.
"""

from __future__ import annotations

import os
import unittest
import warnings
from pathlib import Path
from typing import List, Optional

#: An env var wins over everything, so a machine that keeps the drawings
#: somewhere particular does not have to move them.
ENV_VAR = "PLAN_FIXTURE_PDFS"


def repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up for a marker. NOT a parent count.

    `.git` is a DIRECTORY in a clone and a FILE in a worktree, and this repo
    is developed in worktrees, so both count. `backend/` alongside
    `frontend/` is the fallback for an export with no git metadata at all.
    """
    here = (start or Path(__file__)).resolve()
    for d in [here] + list(here.parents):
        if (d / ".git").exists():
            return d
        if (d / "backend").is_dir() and (d / "frontend").is_dir():
            return d
    return None


def search_paths() -> List[Path]:
    """Every place the fixtures may sit, in order. Reported when missing, so
    the message names what was tried rather than just what failed."""
    # AN EXPLICIT SETTING IS AUTHORITATIVE, NOT MERELY FIRST. If someone
    # names a directory and it is wrong, they must be told that — falling
    # through to a sibling that happens to exist would run the suite against
    # drawings they did not choose and report green, which is the same class
    # of silence this module exists to remove.
    env = os.environ.get(ENV_VAR)
    if env:
        return [Path(env).expanduser()]

    out: List[Path] = []
    root = repo_root()
    if root:
        # INSIDE the checkout first — the only kind of location CI could
        # ever satisfy, and the one the old expression could not express.
        out.append(root / "backend" / "tests" / "fixtures" / "pdfs")
        out.append(root / "fixtures" / "pdfs")
        # Beside the checkout: where they actually live on the machines this
        # has run on. Kept, but no longer the only possibility.
        out.append(root.parent / "pdfs")
    return out


def pdfs_dir() -> Optional[Path]:
    for p in search_paths():
        if p.is_dir():
            return p
    return None


#: Resolved once. A None here is the state the warning below describes.
PDFS = pdfs_dir()

if PDFS is None:
    warnings.warn(
        f"SOURCE PDF FIXTURES NOT FOUND — tests that read real drawings will "
        f"SKIP, and a skip is counted as green. Looked in: "
        f"{[str(p) for p in search_paths()] or '(no repo root found)'}. "
        f"Set {ENV_VAR} to the directory holding the source PDFs. "
        f"These fixtures are customer drawings and are deliberately not in "
        f"the repository, so CI has never run these tests.",
        stacklevel=2,
    )


def require(name: str) -> Path:
    """The fixture, or a skip that says WHERE it looked and HOW to fix it.

    The old message was "source PDF not present in this checkout" — true,
    unactionable, and wrong about the mechanism: it was never in any
    checkout, because the path pointed outside one.
    """
    if PDFS is None:
        raise unittest.SkipTest(
            f"no fixture directory: looked in "
            f"{[str(p) for p in search_paths()]}; set {ENV_VAR}")
    p = PDFS / name
    if not p.exists():
        raise unittest.SkipTest(
            f"{name!r} is not in {PDFS} (the directory exists, the file does "
            f"not); set {ENV_VAR} or add the file")
    return p


__all__ = ["ENV_VAR", "PDFS", "repo_root", "search_paths", "pdfs_dir",
           "require"]
