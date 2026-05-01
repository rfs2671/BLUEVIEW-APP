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


# Default storage_state root on host. Matches the bind-mount source
# in docker-compose.yml: ${LEVELOG_AGENT_STORAGE_DIR:-./storage-host-fallback}
# where the operator setup sets LEVELOG_AGENT_STORAGE_DIR to
# ~/.levelog/agent-storage. The script picks the same default so
# the saved file is exactly where the worker will load it from.
DEFAULT_STORAGE_DIR_HOST = Path.home() / ".levelog" / "agent-storage"
# When running INSIDE the worker container (not the recommended
# path, but supported for ops who have an X11 forwarding setup),
# the bind-mount lives at /storage.
DEFAULT_STORAGE_DIR_CONTAINER = Path("/storage")

LANDING_URL = "https://a810-dobnow.nyc.gov/Publish/Index.html"


def resolve_storage_dir() -> Path:
    """Pick the right storage_state root for the current
    environment. Honors STORAGE_STATE_DIR env var if set;
    otherwise picks the host or container default based on
    which directory exists and is writable."""
    explicit = os.environ.get("STORAGE_STATE_DIR")
    if explicit:
        return Path(explicit)
    # Container default first — if /storage exists, we're probably
    # inside the worker image.
    if DEFAULT_STORAGE_DIR_CONTAINER.exists():
        return DEFAULT_STORAGE_DIR_CONTAINER
    return DEFAULT_STORAGE_DIR_HOST


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


async def main(argv=None) -> int:
    args = parse_args(argv)
    output_path = output_path_for(args)
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

    async with async_playwright() as pw:
        # Non-headless so the operator can interact with the
        # window. Args mirror the production handler's stealth
        # flags so the seeded fingerprint matches what the
        # worker will replay.
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            # FRESH context — explicitly do NOT pre-load any
            # existing storage_state. The whole point is to
            # capture a brand-new session.
            context = await browser.new_context()
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
