"""Per-GC BrowserContext dispatch with storage_state rotation.

MR.12 status (2026-05-03)
─────────────────────────
NOT called from the active dob_now_filing handler path. The MR.12
pivot moved that handler to Bright Data Browser API via CDP, where:
  - Session/cookie identity is managed by Bright Data per-connection.
  - Identity is rotated per-session by design — persisting cookies
    between runs would DEFEAT the rotation that bypasses Akamai.
  - There's no concept of a "per-GC stable identity to Akamai"
    because the IP, fingerprint, and cookies all rotate.

This module is preserved for:
  - scripts/seed_storage_state.py (vestigial after MR.12; usable for
    any future warm-session need on a non-Akamai-protected site)
  - any future local-Chromium handler that wants per-GC isolation
  - the existing test suite (back-compat; tests still pass against
    the unchanged contract)

bis_scrape.py launches its own local Chromium inline and does NOT
use this module (never has) — the BIS site is not Akamai-protected
and doesn't need session warming.

DO NOT delete this file. It's correct; it's just not the active
dob_now_filing path post-MR.12.

Per §2.5 of the permit-renewal v3 plan (PRE-MR.12 design)
─────────────────────────────────────────────────────────
  - One Chromium browser per worker container, N contexts (one per GC).
  - Each context loads its GC's storage_state from disk if present;
    creates a fresh state for first-time GCs.
  - storage_state rotation: every 200 requests OR 7 days, keep
    current + previous, fall back if current gets challenged.
  - storage_state files live in STORAGE_STATE_DIR (bind-mounted at
    /storage in the container, ~/.levelog/agent-storage on the host).

Naming: storage_state files are keyed by GC license_number to give
each GC a stable identity to Akamai. Layout under STORAGE_STATE_DIR:

    {license_number}/current.json
    {license_number}/previous.json
    {license_number}/meta.json   ← rotation counter + timestamps

This module manages load/save/rotate. Actual Chromium launch is the
caller's concern (dob_worker.py boot).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


STORAGE_STATE_DIR = Path(os.environ.get("STORAGE_STATE_DIR", "/storage"))
ROTATE_AFTER_REQUESTS = int(os.environ.get("ROTATE_AFTER_REQUESTS", "200"))
ROTATE_AFTER_DAYS = int(os.environ.get("ROTATE_AFTER_DAYS", "7"))


def _gc_dir(license_number: str) -> Path:
    """Per-GC subdirectory inside STORAGE_STATE_DIR. Creates if absent."""
    d = STORAGE_STATE_DIR / license_number
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(license_number: str) -> Path:
    return _gc_dir(license_number) / "meta.json"


def _current_path(license_number: str) -> Path:
    return _gc_dir(license_number) / "current.json"


def _previous_path(license_number: str) -> Path:
    return _gc_dir(license_number) / "previous.json"


def load_meta(license_number: str) -> Dict[str, Any]:
    """Return rotation metadata. Initializes a default doc on first
    access (request_count=0, created_at=now)."""
    p = _meta_path(license_number)
    if not p.exists():
        meta = {
            "license_number": license_number,
            "request_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_rotated_at": None,
        }
        p.write_text(json.dumps(meta))
        return meta
    return json.loads(p.read_text())


def save_meta(license_number: str, meta: Dict[str, Any]) -> None:
    _meta_path(license_number).write_text(json.dumps(meta))


def get_storage_state_path(license_number: str) -> Optional[Path]:
    """Return the path Playwright should load as the BrowserContext's
    storage_state. Returns None if no state exists yet (caller passes
    storage_state=None and Chromium starts a fresh session)."""
    p = _current_path(license_number)
    return p if p.exists() else None


def needs_rotation(license_number: str) -> bool:
    """True if the current storage_state should be rotated. Triggered
    by request count OR age, whichever fires first."""
    meta = load_meta(license_number)
    if meta["request_count"] >= ROTATE_AFTER_REQUESTS:
        return True
    last = meta.get("last_rotated_at") or meta.get("created_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return True  # malformed → rotate defensively
        age_days = (datetime.now(timezone.utc) - last_dt).days
        if age_days >= ROTATE_AFTER_DAYS:
            return True
    return False


def increment_request_count(license_number: str) -> None:
    meta = load_meta(license_number)
    meta["request_count"] = meta.get("request_count", 0) + 1
    save_meta(license_number, meta)


def rotate(license_number: str) -> None:
    """Promote current.json → previous.json; reset request_count.
    Caller is responsible for re-authoring current.json from a fresh
    Chromium session afterward (typically by saving the storage_state
    after a successful navigation cycle)."""
    cur = _current_path(license_number)
    if cur.exists():
        shutil.copy2(cur, _previous_path(license_number))
        cur.unlink()
    meta = load_meta(license_number)
    meta["request_count"] = 0
    meta["last_rotated_at"] = datetime.now(timezone.utc).isoformat()
    save_meta(license_number, meta)
    logger.info("[storage_state] rotated for %s", license_number)


def fall_back_to_previous(license_number: str) -> bool:
    """When current.json gets a challenge, fall back to the previous
    profile if available. Returns True if a fallback happened."""
    prev = _previous_path(license_number)
    if not prev.exists():
        return False
    cur = _current_path(license_number)
    if cur.exists():
        cur.unlink()
    shutil.copy2(prev, cur)
    logger.warning(
        "[storage_state] fell back to previous profile for %s", license_number,
    )
    return True


# MR.11.3 — statuses that MUST NOT trigger the post-fn storage_state
# save. The earlier behavior saved unconditionally, which corrupted
# the operator's hand-seeded cookies whenever a run failed (Akamai
# 403, login error, cancellation): the BrowserContext at that point
# holds whatever cookies Akamai's block-page set, NOT the trusted
# session, and writing those over current.json progressively
# degraded the seed.
#
# Default is opt-in-to-save: if the fn returns something we don't
# recognize as success-shaped, fall through to the old save path
# (preserves backward compat for non-handler callers like tests
# that return a string). Explicit failure / cancellation skips.
_SKIP_SAVE_STATUSES = frozenset({"failed", "cancelled"})


def _result_status(result) -> Optional[str]:
    """Extract `.status` from a HandlerResult-like object OR a dict.
    Returns None if the result isn't shaped like one — caller treats
    None as 'unknown, default to save' (back-compat for non-handler
    fn callers like the test suite)."""
    if result is None:
        return None
    # HandlerResult dataclass — has .status attribute.
    status = getattr(result, "status", None)
    if isinstance(status, str):
        return status
    # Plain dict — handler dispatcher converts via .to_dict() in some
    # paths; tolerate that shape too.
    if isinstance(result, dict):
        s = result.get("status")
        if isinstance(s, str):
            return s
    return None


async def with_browser_context(browser, license_number: str, fn):
    """Run fn(context) inside a per-GC BrowserContext. Loads
    storage_state from disk if present; saves it back ONLY when fn
    returned a result whose status is not "failed" / "cancelled".
    Caller (handler) owns whatever fn does inside the context.

    `browser` is a Playwright Browser instance from the caller.
    `fn` is an async callable that takes a BrowserContext.

    Save-gate (MR.11.3): on failure / cancellation, the context's
    cookie jar reflects whatever the failure left behind (Akamai
    block-page cookies for akamai_challenge, partial-login state
    for login_failed, etc.). Saving those would overwrite the
    trusted seeded session. We skip the save and log a warning so
    the operator can correlate "cookies not refreshed" with the
    upstream failure.

    Fingerprint (MR.11.3): every per-GC context inherits the same
    user-agent / viewport / locale / timezone from
    lib/browser_launch.get_context_args() so its identity matches
    the browser the operator used to seed. Without this, Akamai
    rejects worker runs even when the cookies are intact."""
    # Lazy import — keeps unit tests that don't exercise the launch
    # config from having to import every browser-launch detail.
    from lib.browser_launch import get_context_args

    storage_path = get_storage_state_path(license_number)
    context_kwargs: Dict[str, Any] = dict(get_context_args())
    loaded_cookies = 0
    if storage_path is not None:
        context_kwargs["storage_state"] = str(storage_path)
        # Best-effort cookie count for the load log line. Counting
        # before Playwright loads it is cheap and lets the operator
        # correlate "loaded N cookies, run failed" without docker
        # exec'ing into the container to inspect the file.
        try:
            data = json.loads(storage_path.read_text(encoding="utf-8"))
            loaded_cookies = len(data.get("cookies") or [])
        except Exception:
            loaded_cookies = 0
        logger.info(
            "[storage_state] loaded %d cookies for license=%s from %s",
            loaded_cookies, license_number, storage_path,
        )
    else:
        logger.info(
            "[storage_state] no seeded session for license=%s — "
            "starting fresh BrowserContext",
            license_number,
        )

    context = await browser.new_context(**context_kwargs)
    try:
        result = await fn(context)
        status = _result_status(result)
        if status in _SKIP_SAVE_STATUSES:
            # Don't overwrite the trusted seed with post-failure
            # cookies. Counter still increments (the attempt
            # happened) so rotation pacing is accurate.
            logger.warning(
                "[storage_state] save SKIPPED for license=%s "
                "(handler status=%r — preserving prior seed)",
                license_number, status,
            )
        else:
            await context.storage_state(path=str(_current_path(license_number)))
            # Re-read the just-saved file for the success log line.
            saved_cookies = 0
            try:
                cur = _current_path(license_number)
                data = json.loads(cur.read_text(encoding="utf-8"))
                saved_cookies = len(data.get("cookies") or [])
            except Exception:
                saved_cookies = 0
            logger.info(
                "[storage_state] saved %d cookies for license=%s "
                "(handler status=%r)",
                saved_cookies, license_number, status,
            )
        increment_request_count(license_number)
        return result
    finally:
        await context.close()
