"""Per-GC BrowserContext dispatch with storage_state rotation.

Per §2.5 of the permit-renewal v3 plan:
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


async def with_browser_context(browser, license_number: str, fn):
    """Run fn(context) inside a per-GC BrowserContext. Loads
    storage_state from disk if present, saves it back on success.
    Caller (handler) owns whatever fn does inside the context.

    `browser` is a Playwright Browser instance from the caller.
    `fn` is an async callable that takes a BrowserContext."""
    storage_path = get_storage_state_path(license_number)
    context_kwargs = {}
    if storage_path is not None:
        context_kwargs["storage_state"] = str(storage_path)

    context = await browser.new_context(**context_kwargs)
    try:
        result = await fn(context)
        # Persist updated state on success.
        await context.storage_state(path=str(_current_path(license_number)))
        increment_request_count(license_number)
        return result
    finally:
        await context.close()
