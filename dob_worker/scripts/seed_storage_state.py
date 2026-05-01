"""MR.11.1 — Operator helper: seed warm-session storage_state for a GC.

Why this exists
───────────────
DOB NOW (and the NYC.ID auth layer it sits behind) is fronted by
Akamai Bot Manager. A cold connection from a residential IP via
headless Chromium gets challenged with a 403 + JS challenge page
before the worker can even reach the login form. The MR.11 smoke
run hit this on first contact.

The standard mitigation is to seed the BrowserContext's
storage_state with cookies obtained from a real human login —
once Akamai has a trusted-fingerprint session, subsequent visits
from the same context (cookies + nav fingerprint) often pass
through silently. This script runs Playwright in non-headless
mode so the operator can log in by hand, then dumps the
post-login storage_state to the path lib/browser_context.py
loads on next worker run.

Where to run
────────────
**On the host Python interpreter — NOT inside the dob_worker
Docker container.** Reason: non-headless Chromium needs a real
display server. On Windows the container has no X server; on
macOS the same; on Linux it's possible with X forwarding but
fragile. Just run on host.

Prerequisites (one-time):
    pip install playwright
    playwright install chromium

Usage:
    python dob_worker/scripts/seed_storage_state.py <gc_license_number>

Where <gc_license_number> matches `companies.gc_license_number` for
the GC you're seeding. The output file lands at
~/.levelog/agent-storage/<gc_license_number>/current.json — the
SAME path the worker container's /storage bind-mount exposes to
lib/browser_context.py:get_storage_state_path().

Operator flow:
    1. Run the command above.
    2. Chromium window opens, navigates to DOB NOW.
    3. Click NYC.ID login, type your DOB NOW credentials,
       complete any 2FA / CAPTCHA the human-facing site presents.
    4. Wait until you're on the post-login dashboard with your
       permit list visible.
    5. Press Enter in the terminal (or Ctrl+C — both work) to
       save the session and close the browser.
    6. Subsequent `docker compose up -d dob_worker` runs will
       load this storage_state automatically when filing for
       this GC's permits.

Idempotency: re-running this script overwrites
current.json. No backup of the prior file (rotation is the
worker's job — see lib/browser_context.py:rotate). If you need
to roll back to a known-good session, restore from
previous.json manually.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional


# Default storage_state root on host. Matches the bind-mount SOURCE
# in docker-compose.yml: ${LEVELOG_AGENT_STORAGE_DIR:-./storage-host-fallback}
# This is the HOST path the worker container's /storage volume
# mounts FROM. The operator's setup (per dob_worker/README.md step 6)
# sets LEVELOG_AGENT_STORAGE_DIR=~/.levelog/agent-storage in their
# shell, and that's the directory we write to.
DEFAULT_STORAGE_DIR_HOST = Path.home() / ".levelog" / "agent-storage"

LANDING_URL = "https://a810-dobnow.nyc.gov/Publish/Index.html"


# MR.11.2 fix: the prior version of this script honored
# STORAGE_STATE_DIR (the IN-CONTAINER worker env var, value=/storage)
# before falling back to the host home-dir default. When the operator
# ran the host script in a shell that had STORAGE_STATE_DIR=/storage
# leaked from sourcing dob_worker/.env.local, the script wrote to
# the literal Windows path C:\storage\<gc>\current.json — which the
# worker container DOESN'T see because /storage inside the container
# is the bind-mount target, with the SOURCE being whatever
# LEVELOG_AGENT_STORAGE_DIR points at on the host. So the seeded
# file landed in a directory the worker would never read from.
#
# The fix below resolves to LEVELOG_AGENT_STORAGE_DIR (the host
# env var the operator already has set per MR.5 setup step 6),
# falling back to ~/.levelog/agent-storage. STORAGE_STATE_DIR is
# explicitly IGNORED here — that variable describes the worker's
# in-container path and is irrelevant to where the host-run seed
# script should write.
def resolve_storage_dir() -> Path:
    """Pick the storage_state root on the HOST filesystem (the
    bind-mount source the worker container reads).

    Resolution order:
      1. LEVELOG_AGENT_STORAGE_DIR env var — the canonical host
         path the operator's setup configured (MR.5 step 6).
      2. ~/.levelog/agent-storage — the documented default.

    NOT consulted (explicitly): STORAGE_STATE_DIR. That variable
    describes the path INSIDE the worker container (/storage) and
    is wrong for the host-run seed script. See the MR.11.2 commit
    body for the bug history."""
    explicit = os.environ.get("LEVELOG_AGENT_STORAGE_DIR")
    if explicit:
        return Path(explicit)
    return DEFAULT_STORAGE_DIR_HOST


def detect_misplaced_legacy_seed(gc_license_number: str, new_path: Path) -> Optional[Path]:
    """MR.11.2 — if the operator's PRIOR seed run wrote to the
    literal /storage host path (the bug), detect that file and tell
    the operator to move it manually.

    Returns the legacy path if a file exists there AND no file
    exists at the new resolved path. None otherwise (no
    relocation needed, or the operator already moved it).

    We do NOT auto-mv because Windows path handling is brittle and
    a botched move could lose the (real, hard-won, manually-logged-
    in) cookies. Better to make the operator do it explicitly."""
    # The literal Windows path the bug produced when STORAGE_STATE_DIR
    # was leaked into the host shell as /storage.
    if os.name == "nt":
        legacy_root = Path("C:/storage")
    else:
        legacy_root = Path("/storage")
    legacy_path = legacy_root / gc_license_number / "current.json"
    if legacy_path.exists() and not new_path.exists():
        return legacy_path
    return None


def parse_args(argv=None) -> argparse.Namespace:
    """Argparse — split out as a pure function for unit-test
    coverage that doesn't need to import Playwright."""
    parser = argparse.ArgumentParser(
        description=(
            "Seed Playwright storage_state via manual operator "
            "login. One-time per GC; output is reused by the "
            "dob_worker handler on subsequent filings."
        ),
    )
    parser.add_argument(
        "gc_license_number",
        help=(
            "GC license number — matches companies.gc_license_number. "
            "Used as the directory name under STORAGE_STATE_DIR; "
            "must be filesystem-safe (no slashes)."
        ),
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help=(
            "Override storage_state root directory. Defaults to "
            "~/.levelog/agent-storage on host or /storage in container. "
            "Equivalent: STORAGE_STATE_DIR env var."
        ),
    )
    parser.add_argument(
        "--landing-url",
        default=LANDING_URL,
        help="Initial URL to navigate to. Defaults to DOB NOW.",
    )
    parser.add_argument(
        "--output-name",
        default="current.json",
        help=(
            "Filename within the GC's directory. Defaults to "
            "current.json (matches what lib/browser_context.py loads)."
        ),
    )
    return parser.parse_args(argv)


def output_path_for(args: argparse.Namespace) -> Path:
    """Compose the final filesystem path for the storage_state
    output. Pure function — testable without Playwright."""
    if args.storage_dir:
        root = Path(args.storage_dir)
    else:
        root = resolve_storage_dir()
    if "/" in args.gc_license_number or "\\" in args.gc_license_number:
        raise ValueError(
            "gc_license_number must not contain path separators"
        )
    return root / args.gc_license_number / args.output_name


async def _wait_for_operator_signal() -> None:
    """Block until the operator either presses Enter OR sends
    SIGINT (Ctrl+C). Cross-platform — Windows event loops don't
    support add_signal_handler reliably, so we use the
    Enter-key-via-executor pattern which works everywhere AND
    naturally lets KeyboardInterrupt propagate."""
    print()
    print("=" * 70)
    print("Browser is open. Complete the manual login now:")
    print("  1. Click the NYC.ID login button.")
    print("  2. Type your DOB NOW credentials.")
    print("  3. Complete any 2FA / CAPTCHA the site presents.")
    print("  4. Wait for the post-login dashboard to load.")
    print()
    print("When you can see your permit list:")
    print("  → Press Enter in THIS terminal (or Ctrl+C) to save "
          "the session.")
    print("=" * 70)
    print()
    loop = asyncio.get_event_loop()
    try:
        # run_in_executor lets us await a blocking input() call
        # without freezing the event loop or the browser.
        await loop.run_in_executor(None, sys.stdin.readline)
    except KeyboardInterrupt:
        # Both Enter and Ctrl+C are valid signals; both fall through
        # to the save path below. Suppress the traceback here.
        pass


def validate_storage_root(root: Path) -> Optional[str]:
    """Reject if the storage root doesn't exist OR isn't writable.
    Returns an error message string when invalid, None when OK.

    Why we don't auto-create: per MR.5 setup step 3 the operator
    is supposed to mkdir ~/.levelog/agent-storage explicitly. If
    the script silently mkdir'd it on first run, a typo'd
    LEVELOG_AGENT_STORAGE_DIR (e.g. pointing at a different drive
    that's currently disconnected) would create the wrong
    directory tree and the worker container's bind-mount would
    point at the typo, not the real path. Loud failure is better."""
    if not root.exists():
        return (
            f"storage root does not exist: {root}\n"
            f"Run the MR.5 setup step 3:\n"
            f"  PowerShell:\n"
            f"    New-Item -ItemType Directory -Path "
            f'"$env:USERPROFILE\\.levelog\\agent-storage" -Force\n'
            f"  bash:\n"
            f"    mkdir -p ~/.levelog/agent-storage\n"
            f"and re-run this script."
        )
    if not root.is_dir():
        return f"storage root is not a directory: {root}"
    # Check writable by probing — Path.access is unreliable on
    # Windows network drives, and os.access has known false-
    # positive issues with NTFS permissions. The probe is
    # authoritative.
    probe = root / ".seed_storage_state_writable_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as e:
        return f"storage root is not writable: {root} ({e})"
    return None


async def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        output_path = output_path_for(args)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    storage_root = output_path.parent.parent  # <root>/<gc>/current.json -> <root>
    err = validate_storage_root(storage_root)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    # MR.11.2 — detect the misplaced-legacy-seed case: prior
    # version of this script wrote to a literal /storage path that
    # the worker doesn't read from. If the operator's prior session
    # is parked there, surface it BEFORE asking them to log in
    # again — they can mv the existing 26-cookie session in place
    # and skip the manual re-login.
    legacy = detect_misplaced_legacy_seed(
        args.gc_license_number, output_path,
    )
    if legacy is not None:
        print(
            f"\nWARNING: detected an existing storage_state at the "
            f"OLD broken path:\n  {legacy}\n\n"
            f"This file was written by a prior MR.11.1 seed run BEFORE "
            f"the path-resolution bug was fixed in MR.11.2. The worker "
            f"container does NOT read from there.\n\n"
            f"To preserve the existing logged-in session WITHOUT a "
            f"manual re-login, move the file:\n",
            file=sys.stderr,
        )
        print(f"  PowerShell:", file=sys.stderr)
        print(
            f"    New-Item -ItemType Directory -Path "
            f'"{output_path.parent}" -Force | Out-Null',
            file=sys.stderr,
        )
        print(
            f'    Move-Item -Path "{legacy}" -Destination '
            f'"{output_path}"',
            file=sys.stderr,
        )
        print(f"\n  bash:", file=sys.stderr)
        print(f"    mkdir -p {output_path.parent}", file=sys.stderr)
        print(f"    mv {legacy} {output_path}", file=sys.stderr)
        print(
            "\nThen re-run this script ONLY if you want to refresh "
            "the cookies (otherwise the moved file is sufficient — "
            "the worker will pick it up on next filing run).",
            file=sys.stderr,
        )
        print(
            "\nNot moving automatically — Windows path handling is "
            "brittle and a botched move could destroy the cookies "
            "you spent time logging in to obtain.",
            file=sys.stderr,
        )
        return 3

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[seed] Storage state will be written to: {output_path}")
    print(f"[seed] Landing URL: {args.landing_url}")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed in this environment.\n"
            "Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
            "then re-run this script.",
            file=sys.stderr,
        )
        return 2

    # MR.11.3 — share launch + context configuration with the worker
    # handler via lib/browser_launch. Different fingerprints between
    # the seed run and the worker run is the difference that made
    # Akamai reject the worker even with the seeded cookies present.
    # We override only `headless` (False — operator needs to see the
    # window); everything else (args, UA, viewport, locale, timezone,
    # extra_http_headers) matches the worker exactly.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.browser_launch import get_launch_args, get_context_args

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**get_launch_args(headless=False))
        try:
            # FRESH context — explicitly do NOT pre-load any
            # existing storage_state. The whole point is to
            # capture a brand-new session. UA/viewport/locale/etc
            # come from the shared get_context_args() so the
            # fingerprint matches the worker's per-GC context.
            context = await browser.new_context(**get_context_args())
            page = await context.new_page()
            try:
                await page.goto(args.landing_url, wait_until="domcontentloaded")
            except Exception as e:
                print(f"WARNING: initial goto raised: {e!r}", file=sys.stderr)
                print(
                    "Continuing anyway — operator can navigate manually "
                    "in the browser window.",
                    file=sys.stderr,
                )

            await _wait_for_operator_signal()

            print(f"[seed] Saving storage_state to {output_path}...")
            await context.storage_state(path=str(output_path))

            # Quick sanity: count cookies in the saved state so
            # the operator can tell at a glance that login worked.
            try:
                with output_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                cookie_count = len(data.get("cookies") or [])
                origin_count = len(data.get("origins") or [])
                print(
                    f"[seed] Saved {cookie_count} cookies across "
                    f"{origin_count} origin(s)."
                )
                if cookie_count == 0:
                    print(
                        "[seed] WARNING: zero cookies saved. The login "
                        "likely didn't complete — re-run after fully "
                        "logging in.",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(f"[seed] Could not summarize saved state: {e!r}",
                      file=sys.stderr)

            await context.close()
        finally:
            await browser.close()

    print("[seed] Done. The dob_worker container will now use this "
          "session on next filing run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
