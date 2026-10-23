"""Is the backend serving a commit that INCLUDES this one? Stdlib only.

WHY. On 2026-10-21 Railway paused deploys platform-wide after #826. Vercel and
the EAS OTA kept shipping on every merge, so the web build and every phone ran
code that called endpoints the backend did not have yet (the schedule screen
404'd). The frontend must not go live ahead of the backend it talks to.

TWO MODES

  wait  --sha S [--timeout 1200] [--interval 30]
        Poll /api/version until the deployed commit has S as an ancestor (or
        IS S). Exit 0 then; exit 1 on timeout. "Includes", not "equals":
        Railway can skip straight to a later merge, and an exact match would
        then never come.

  lag   [--max-minutes 30] [--ref origin/main]
        Exit 1 when the OLDEST first-parent commit on the ref that the deployed
        commit does not include was merged more than N minutes ago. The oldest,
        not the newest: one fresh merge must not hide one two hours stale.

Run from a checkout with full history (actions/checkout fetch-depth: 0). The
deployed commit is fetched if the clone does not have it; a commit that cannot
be found includes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

API_BASE = os.environ.get("API_BASE", "https://api.levelog.com").rstrip("/")


def deployed_commit(api_base: str = API_BASE, timeout: float = 10.0) -> Optional[str]:
    """The `commit` /api/version reports, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(f"{api_base}/api/version", timeout=timeout) as r:
            sha = str(json.load(r).get("commit") or "").strip()
            return sha or None
    except Exception:
        return None


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def have_commit(sha: str, git: Callable = _git) -> bool:
    if git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        return True
    git("fetch", "--quiet", "origin", sha)
    return git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def includes(deployed: Optional[str], sha: str, git: Callable = _git) -> bool:
    """True when the deployed commit is `sha` or has it as an ancestor."""
    if not deployed or not have_commit(deployed, git):
        return False
    return git("merge-base", "--is-ancestor", sha, deployed).returncode == 0


def wait(sha: str, timeout: int, interval: int, *, read: Callable = deployed_commit,
         git: Callable = _git, sleep: Callable = time.sleep,
         clock: Callable = time.monotonic, say: Callable = print) -> int:
    deadline = clock() + timeout
    while True:
        live = read()
        if includes(live, sha, git):
            say(f"backend serves {live[:12]}, which includes {sha[:12]}")
            return 0
        left = deadline - clock()
        say(f"backend serves {(live or 'nothing readable')[:12]}; waiting for {sha[:12]} "
            f"({max(0, int(left))}s left)")
        if left <= 0:
            say(f"::error::The backend never served a commit that includes {sha[:12]} "
                f"within {timeout}s (live: {(live or 'unreadable')[:12]}). The frontend "
                "is NOT published: it would call a backend that does not have this "
                "change. Re-run this job once /api/version shows it.")
            return 1
        sleep(min(interval, max(1, left)))


def oldest_undeployed(deployed: Optional[str], ref: str, git: Callable = _git):
    """(sha, merged_at) of the oldest first-parent commit on `ref` that the
    deployed commit does not include, or None when it includes them all."""
    if deployed and have_commit(deployed, git):
        out = git("rev-list", "--first-parent", "--reverse", f"{deployed}..{ref}").stdout.split()
        if not out:
            return None
        sha = out[0]
    else:
        # Unknown deployed commit: everything recent is suspect; report the tip.
        sha = git("rev-parse", ref).stdout.strip()
    ts = int(git("show", "-s", "--format=%ct", sha).stdout.strip() or 0)
    return sha, datetime.fromtimestamp(ts, timezone.utc)


def lag(max_minutes: int, ref: str, *, read: Callable = deployed_commit,
        git: Callable = _git, now: Optional[datetime] = None, say: Callable = print) -> int:
    live = read()
    behind = oldest_undeployed(live, ref, git)
    if behind is None:
        say(f"backend serves {live[:12]}: {ref} is fully deployed")
        return 0
    sha, merged_at = behind
    age = ((now or datetime.now(timezone.utc)) - merged_at).total_seconds() / 60
    if age <= max_minutes:
        say(f"backend serves {(live or 'unreadable')[:12]}; {sha[:12]} merged "
            f"{age:.0f} min ago, inside the {max_minutes}-minute allowance")
        return 0
    say(f"::error::BACKEND DEPLOY IS BEHIND MAIN. {sha[:12]} was merged {age:.0f} min ago "
        f"and /api/version still serves {(live or 'nothing readable')[:12]}. Do not merge "
        "frontend changes until it catches up; check Railway.")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--sha", required=True)
    w.add_argument("--timeout", type=int, default=1200)
    w.add_argument("--interval", type=int, default=30)
    g = sub.add_parser("lag")
    g.add_argument("--max-minutes", type=int, default=30)
    g.add_argument("--ref", default="origin/main")
    a = ap.parse_args(argv)
    if a.mode == "wait":
        return wait(a.sha, a.timeout, a.interval)
    return lag(a.max_minutes, a.ref)


if __name__ == "__main__":
    sys.exit(main())
