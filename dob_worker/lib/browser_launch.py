"""Shared Chromium launch + context configuration.

MR.13 status (2026-05-03)
─────────────────────────
The dob_now_filing handler runs **real Chrome** (not bundled
Chromium) launched headed inside the worker container's Xvfb
virtual display. See docs/architecture/akamai-bypass-decision.md
for the full decision trail (warm cookies → fingerprint match →
preserve-on-failure → residential proxy → cloudflared → Bright
Data Browser API → real Chrome local).

The MR.12 Bright Data path was implemented and removed: Bright
Data classifies *.gov domains as restricted and blocks them at
the proxy layer (industry-wide pattern across managed-stealth-
API providers). The pivot to MR.13 is "real Chrome on operator's
laptop, paced at v1 volume" — capped at ≤2 filings/day across
≤20 GCs to stay below Akamai's "many-users-from-one-IP" heuristic.

The load-bearing change vs. pre-MR.12 is `channel="chrome"` —
Playwright launches the OS's installed Chrome instead of the
bundled `playwright-chromium` build. Bundled Chromium has a JA3
TLS fingerprint Akamai's threat-intel feeds know about; real
Chrome does not.

Helpers
───────
  • get_launch_args(headless=...)  — kwargs for chromium.launch()
                                      including channel="chrome".
  • get_context_args()             — kwargs for browser.new_context().
  • get_proxy_args()               — optional Webshare proxy kwargs
                                      from WEBSHARE_PROXY_URL env var.
                                      Layered as a fallback to mask
                                      operator's residential IP if
                                      Akamai starts flagging it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse


# ── Chromium / real-Chrome launch config ──────────────────────────


# Pin to a current Chrome stable major. Update when the
# fingerprint becomes stale (Akamai expects a "current" UA;
# pinning to a 2-year-old version is itself a red flag). The
# string is identical across seed + worker so Akamai's
# "different UA from the cookie-issuing browser" check passes.
#
# Choice: 130.0.0.0 (Chrome stable as of 2026-04). The trailing
# .0.0 keeps the patch-level non-specific so the UA doesn't have
# to chase point releases.
#
# NOTE (MR.13): when channel="chrome" is in effect, Playwright
# uses whatever real Chrome is installed in the container. The
# real Chrome's UA may differ slightly from this constant — but
# Playwright respects an explicit user_agent kwarg in new_context
# regardless of the underlying browser binary, so the wire UA
# stays consistent for fingerprint-matching with the seed run.
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

# Chrome launch flags. Each one earns its keep:
#  --no-sandbox                          — required when running as
#                                          root inside the Docker
#                                          container (no user
#                                          namespace).
#  --disable-blink-features=Automation…  — hides the
#                                          navigator.webdriver=true
#                                          marker that Bot Manager
#                                          checks early.
#  --disable-features=IsolateOrigins,…   — disables Site Isolation
#                                          (leaks process-per-origin
#                                          behavior that bundled
#                                          headless Chromium handles
#                                          differently from real
#                                          Chrome — less relevant
#                                          under MR.13 since we ARE
#                                          real Chrome, but cheap).
#  --disable-dev-shm-usage               — avoids the small /dev/shm
#                                          tmpfs Docker provides;
#                                          unrelated to fingerprinting
#                                          but prevents OOM crashes
#                                          mid-flow.
#
# MR.13 — note we DO NOT include `--headless=new`. The worker now
# launches Chrome headed (`headless=False`) inside the container's
# Xvfb virtual display. Headed Chrome has the smallest possible
# detection surface — no headless-specific markers at all.
_BASE_LAUNCH_FLAGS = (
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-dev-shm-usage",
)


def get_launch_args(*, headless: bool = False) -> Dict[str, Any]:
    """Return kwargs for `await playwright.chromium.launch(**...)`.

    MR.13 default is `headless=False` because the worker runs Chrome
    inside Xvfb (entrypoint.sh starts the virtual display before
    invoking the worker process). Headed Chrome under Xvfb has a
    fingerprint indistinguishable from a human's desktop Chrome —
    that's the whole reason MR.13 works.

    The seed script passes `headless=False` for the same reason
    plus the obvious one (operator needs to interact with the
    browser to log in).

    `channel="chrome"` is the load-bearing flag. It tells Playwright
    to use the OS's installed Chrome (apt google-chrome-stable in the
    worker container) instead of Playwright's bundled
    playwright-chromium. The bundled build has a JA3 TLS fingerprint
    Akamai's threat-intel feeds recognize; real Chrome does not.

    Requires Chrome to be installed in the worker container — see
    Dockerfile (apt-get install google-chrome-stable).
    """
    return {
        "channel": "chrome",
        "headless": headless,
        "args": list(_BASE_LAUNCH_FLAGS),
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


# ── Optional Webshare proxy fallback (MR.13) ──────────────────────


WEBSHARE_PROXY_ENV_VAR = "WEBSHARE_PROXY_URL"


def get_proxy_args() -> Optional[Dict[str, str]]:
    """Convert WEBSHARE_PROXY_URL into the dict shape Playwright's
    chromium.launch() expects, or None if the env var is unset.

    Format expected:
        http://username:password@host:port

    Returns Playwright shape:
        {"server": "http://host:port", "username": "...", "password": "..."}

    Why the dict-form (not just `server` with inline creds): Chromium
    IGNORES inline credentials in the `server=` field — CONNECT goes
    out without Proxy-Authorization, Webshare returns 407, and
    Playwright surfaces it as a 30-second `page.goto` timeout. Same
    quirk handlers/bis_scrape.py hit during BIS work; this helper
    factors out the parsing.

    Returns None if WEBSHARE_PROXY_URL is unset — caller must check
    and conditionally include in launch kwargs:

        proxy = get_proxy_args()
        if proxy is not None:
            launch_kwargs["proxy"] = proxy

    MR.13 status: optional fallback. The default v1 path is direct
    egress from operator's residential IP. If Akamai starts
    flagging that IP, layering Webshare adds a different residential
    IP between operator and DOB NOW.
    """
    raw = os.environ.get(WEBSHARE_PROXY_ENV_VAR, "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        # Malformed; fall back to handing Playwright the raw string
        # and let it surface whatever error it surfaces.
        return {"server": raw}
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port}"
    cfg: Dict[str, str] = {"server": server}
    if parsed.username:
        cfg["username"] = parsed.username
    if parsed.password:
        cfg["password"] = parsed.password
    return cfg
