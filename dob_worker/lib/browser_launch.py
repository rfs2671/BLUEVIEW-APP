"""Shared Chromium launch + context configuration.

MR.12 status (2026-05-03)
─────────────────────────
The dob_now_filing handler PIVOTED off local Chromium to Bright
Data's Browser API for Akamai bypass — see
docs/architecture/akamai-bypass-decision.md for why
fingerprint-matching alone (which is what this module does) was
necessary but not sufficient.

The active dob_now_filing path now uses get_cdp_endpoint_url()
to dial Bright Data over CDP. The legacy local-Chromium helpers
get_launch_args() / get_context_args() are KEPT but used only by:
  • scripts/seed_storage_state.py (vestigial after MR.12; kept for
    any future warm-session use case on a non-Akamai site)
  • lib/browser_context.with_browser_context (vestigial in the
    active path; kept for any future per-GC local-Chromium handler)

Do not delete these helpers — they're correct, just not the
active path. Use get_cdp_endpoint_url() for new Akamai-protected
work.

Why the legacy helpers existed
──────────────────────────────
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

MR.11.3 made these match across seed+worker. It still 403'd —
because Akamai also inspects TLS ClientHello (JA3) and IP
reputation, neither of which a local Chromium can disguise.
Hence the MR.12 pivot.

Helpers
───────
  • get_cdp_endpoint_url()         — Bright Data Browser API URL
    (active dob_now_filing path).
  • get_launch_args(headless=...)  — legacy local-Chromium kwargs.
  • get_context_args()             — legacy new_context kwargs.
"""

from __future__ import annotations

import os
from typing import Any, Dict


# ── Bright Data Browser API (MR.12 — active path) ──────────────────


class BrightDataConfigError(RuntimeError):
    """Raised when BRIGHT_DATA_CDP_URL is missing/empty.

    Surfaced at handler entry as a fail-fast pre-flight check so
    the operator gets a clear error in the FilingJob audit log
    instead of a downstream Playwright connect timeout 30 seconds
    later. Caller is expected to translate this into
    HandlerResult(status='failed', detail='bright_data_cdp_url_missing').
    """


BRIGHT_DATA_ENV_VAR = "BRIGHT_DATA_CDP_URL"


def get_cdp_endpoint_url() -> str:
    """Return the Bright Data Browser API CDP endpoint URL.

    The URL is expected to be a websocket of the form:
        wss://brd-customer-hl_<id>-zone-<name>:<password>@brd.superproxy.io:9222

    Read from the BRIGHT_DATA_CDP_URL env var. Fails loud
    (BrightDataConfigError) when unset — the dob_now_filing
    handler cannot proceed without it post-MR.12.

    See docs/architecture/akamai-bypass-decision.md for context."""
    cdp_url = os.environ.get(BRIGHT_DATA_ENV_VAR, "").strip()
    if not cdp_url:
        raise BrightDataConfigError(
            f"{BRIGHT_DATA_ENV_VAR} is not set. The dob_now_filing handler "
            "uses Bright Data Browser API for Akamai bypass — local Chromium "
            "alone cannot pass DOB NOW's bot check. See "
            "dob_worker/README.md operator setup step 11 (Bright Data "
            "Browser API zone) and "
            "docs/architecture/akamai-bypass-decision.md for context."
        )
    return cdp_url


# ── Legacy: local Chromium fingerprint config (pre-MR.12) ──────────
# Kept for the seed script + with_browser_context. Not reached by
# the active dob_now_filing path.


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
