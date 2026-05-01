"""Shared Chromium launch + context configuration.

Why this exists
───────────────
DOB NOW is fronted by Akamai Bot Manager. Akamai fingerprints
sessions across MANY axes — not just cookies — and any drift
between the browser used to seed a warm session (operator's
non-headless interactive run via scripts/seed_storage_state.py)
and the browser used at filing time (worker's headless run via
handlers/dob_now_filing.py) gets flagged. Even when the seeded
cookies are present, a TLS/JA3 fingerprint mismatch, viewport
size drift, or a different user-agent string is enough to fail
the Bot Manager's "is this the same browser identity that earned
these cookies?" check.

Today's MR.11.2 smoke run hit Akamai 403 despite the seeded
session being on disk and loaded into the BrowserContext. Root
cause: the seed script and the handler launched Chromium with
DIFFERENT args, default user-agents (operator: real Chrome on
Windows; worker: HeadlessChrome), and different viewport defaults.

This module is the single source of truth for both, so the two
paths produce identical browser fingerprints. Add a flag here,
both scripts pick it up.

Two helpers:
  • get_launch_args(headless=...) — kwargs for chromium.launch()
  • get_context_args()             — kwargs for browser.new_context()

The seed script overrides only `headless` (False — operator needs
to see the window). The handler keeps the default (True — runs
unattended in the worker container). Everything else matches.
"""

from __future__ import annotations

from typing import Any, Dict


# Pin to a current Chrome stable major. Update when the
# fingerprint becomes stale (Akamai expects a "current" UA;
# pinning to a 2-year-old version is itself a red flag). The
# string is identical across seed + worker so Akamai's
# "different UA from the cookie-issuing browser" check passes.
#
# Choice: 130.0.0.0 (Chrome stable as of 2026-04). The trailing
# .0.0 keeps the patch-level non-specific so the UA doesn't have
# to chase point releases.
CHROME_VERSION = "130.0.0.0"
USER_AGENT = (
    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    f"AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{CHROME_VERSION} Safari/537.36"
)

# 1080p — common, non-suspicious. Mobile / tablet sizes would
# trigger DOB NOW's responsive-mode CSS which the seed and worker
# don't actually want; full-desktop ensures both see identical
# layouts so the seed's cookies match the worker's queries.
VIEWPORT = {"width": 1920, "height": 1080}

# NYC.gov is a US-locale site; non-US locale would also be a
# fingerprint mismatch.
LOCALE = "en-US"
TIMEZONE_ID = "America/New_York"

# Mirror real Chrome on Windows.
EXTRA_HTTP_HEADERS: Dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
}

# Chromium launch flags. Each one earns its keep:
#  --no-sandbox                          — required when running as
#                                          root inside the Docker
#                                          container (no user
#                                          namespace).
#  --disable-blink-features=Automation…  — hides the
#                                          navigator.webdriver=true
#                                          marker that Bot Manager
#                                          checks early.
#  --disable-features=IsolateOrigins,…   — disables Site Isolation,
#                                          which leaks process-
#                                          per-origin behavior that
#                                          headless Chromium handles
#                                          differently than real
#                                          Chrome (a known fingerprint
#                                          vector).
#  --disable-dev-shm-usage               — avoids the small /dev/shm
#                                          tmpfs Docker provides;
#                                          unrelated to fingerprinting
#                                          but prevents OOM crashes
#                                          mid-flow that would look
#                                          like a Chromium bug.
#  --headless=new                        — ONLY appended when headless
#                                          is True. Chromium's new
#                                          headless mode (109+) renders
#                                          via the same code path as
#                                          headed Chrome, so it
#                                          presents far fewer headless-
#                                          specific markers (no missing
#                                          plugins, real window dims,
#                                          full canvas/WebGL surfaces).
_BASE_LAUNCH_FLAGS = (
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-dev-shm-usage",
)


def get_launch_args(*, headless: bool = True) -> Dict[str, Any]:
    """Return kwargs for `await playwright.chromium.launch(**...)`.

    Pass `headless=False` from the seed script (operator needs the
    visible browser window). Default True for the worker handler.

    The `--headless=new` arg is added automatically when headless=True
    so the worker uses Chromium's new headless mode (Chromium 109+),
    which produces a fingerprint nearly identical to headed Chrome.
    The legacy `--headless` flag (the default before "new" mode) is
    avoided entirely because it's the easy-mode tell for Bot Manager.
    """
    args = list(_BASE_LAUNCH_FLAGS)
    if headless:
        args.append("--headless=new")
    return {
        "headless": headless,
        "args": args,
    }


def get_context_args() -> Dict[str, Any]:
    """Return kwargs for `await browser.new_context(**...)`. Same
    UA / viewport / locale / timezone for seed AND worker so Akamai
    sees one browser identity across both runs.

    Caller (lib/browser_context.with_browser_context) merges these
    with `storage_state=<path>` so the seeded cookies join the rest
    of the fingerprint without the caller needing to know about
    these defaults."""
    return {
        "user_agent": USER_AGENT,
        "viewport": dict(VIEWPORT),  # copy so mutation doesn't leak
        "locale": LOCALE,
        "timezone_id": TIMEZONE_ID,
        "extra_http_headers": dict(EXTRA_HTTP_HEADERS),
    }
