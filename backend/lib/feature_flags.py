"""Phase E1 — feature flag resolver + in-memory cache.

The runtime side of the v2-development infrastructure. Every callable
v2 surface check ends up here:

    if await is_feature_enabled(db, "v2_dashboard_redesign",
                                 user_id=str(user["id"]),
                                 company_id=user.get("company_id")):
        return new_dashboard()
    return legacy_dashboard()

A flag missing from the DB returns False — fail closed. The
collection schema, admin endpoints, and audit log live in
server.py; this module owns the resolution logic + cache only.

──────────────────────────────────────────────────────────────────
Resolution order (per spec §6)
──────────────────────────────────────────────────────────────────

  a) Flag absent from DB                           → False
  b) `enabled_globally` is True                    → True
  c) `company_id` ∈ enabled_for_companies          → True
  d) `user_id` ∈ enabled_for_users                 → True
  e) `enabled_percentage` > 0
       AND hash(user_id or company_id) % 100 < pct → True
  f) Otherwise                                     → False

The percentage bucketing is salted by the flag name so a customer
who's at percentile 42 for flag-A doesn't automatically also
land in flag-B's first 42% — independent rollouts shouldn't
correlate. Salting also gives the same identifier a stable bucket
across calls (deterministic — required by the spec test).

──────────────────────────────────────────────────────────────────
Cache (60s TTL per flag)
──────────────────────────────────────────────────────────────────

Module-level dict keyed by flag name → (doc | None, fetched_at).
Hit returns the doc; miss fetches from Mongo. TTL=60s. Admin write
endpoints call `cache_invalidate(flag)` to flush the affected
entry on the same process; multi-instance deploys see eventual
consistency up to 60s, which the spec accepts for v1.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Cache TTL — stored in seconds, applied via time.monotonic() for
# clock-skew immunity. Tunable via _set_cache_ttl_for_tests; the
# spec value is 60s.
_CACHE_TTL_SECONDS: float = 60.0

# Module-level cache: flag_name → (doc | None, fetched_at_monotonic).
# A None doc means "we already checked Mongo and the flag doesn't
# exist" — cached so repeated calls for unknown flags don't hit DB.
_CACHE: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {}
_CACHE_LOCK = threading.Lock()


# Sentinel returned by _cache_get on miss; distinguishes "not
# cached" from "cached as None (= flag absent from DB)".
class _Miss:
    pass


_MISS = _Miss()


def _cache_get(flag: str):
    """Return cached doc-or-None, or _MISS sentinel if not cached
    (or expired)."""
    with _CACHE_LOCK:
        entry = _CACHE.get(flag)
        if entry is None:
            return _MISS
        doc, fetched_at = entry
        if time.monotonic() - fetched_at > _CACHE_TTL_SECONDS:
            return _MISS
        return doc


def _cache_set(flag: str, doc: Optional[Dict[str, Any]]) -> None:
    with _CACHE_LOCK:
        _CACHE[flag] = (doc, time.monotonic())


def cache_invalidate(flag: Optional[str] = None) -> None:
    """Drop one flag's cache entry (call from admin write endpoints
    after the Mongo write succeeds). Pass None to nuke everything
    — used by tests + by an emergency lever if cache appears
    corrupted."""
    with _CACHE_LOCK:
        if flag is None:
            _CACHE.clear()
        else:
            _CACHE.pop(flag, None)


def _set_cache_ttl_for_tests(ttl_seconds: float) -> None:
    """Test-only helper. Production code should never touch this."""
    global _CACHE_TTL_SECONDS
    _CACHE_TTL_SECONDS = float(ttl_seconds)


def _percentage_bucket(identifier: str, *, salt: str = "") -> int:
    """Deterministic 0..99 bucket for an identifier.

    Salted by the flag name so a customer's bucket on flag-A is
    independent of their bucket on flag-B. Same identifier + same
    flag always returns the same bucket — required for stable
    percentage rollouts (a customer doesn't oscillate
    in/out as percentage ticks up).
    """
    payload = f"{salt}::{identifier}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:8], 16) % 100


async def _fetch_flag(db, flag: str) -> Optional[Dict[str, Any]]:
    """Mongo-backed cached read.

    `db` is the Motor database object — kept as a parameter (not
    a module-level import of server.db) so tests can pass a
    MagicMock without monkey-patching server.
    """
    cached = _cache_get(flag)
    if cached is not _MISS:
        return cached  # may be a doc OR None (cached negative)

    try:
        doc = await db.feature_flags.find_one({"flag": flag})
    except Exception as e:
        # Fail CLOSED on DB hiccups — never accidentally enable a
        # v2 feature because Mongo blipped. Log so ops can see
        # a sustained failure.
        logger.warning(
            f"[feature_flags] DB read failed for flag={flag!r}: {e!r}",
        )
        return None

    _cache_set(flag, doc)
    return doc


async def is_feature_enabled(
    db,
    flag: str,
    *,
    user_id: Optional[str] = None,
    company_id: Optional[str] = None,
) -> bool:
    """Return True iff the supplied user / company is in the
    flag's enabled set. See module docstring for the resolution
    order."""
    doc = await _fetch_flag(db, flag)
    if doc is None:
        return False  # (a) flag absent → fail closed

    # (b) global on
    if doc.get("enabled_globally"):
        return True

    # (c) company match
    if company_id:
        cmps = doc.get("enabled_for_companies") or []
        cid_str = str(company_id)
        for c in cmps:
            if str(c) == cid_str:
                return True

    # (d) user match
    if user_id:
        usrs = doc.get("enabled_for_users") or []
        uid_str = str(user_id)
        for u in usrs:
            if str(u) == uid_str:
                return True

    # (e) percentage rollout
    pct = doc.get("enabled_percentage") or 0
    try:
        pct = int(pct)
    except (TypeError, ValueError):
        pct = 0
    if pct > 0:
        # Use user_id when available (user-level rollout), fall
        # back to company_id (company-level rollout). If neither
        # is present, percentage rollout doesn't apply.
        identifier = user_id or company_id
        if identifier:
            bucket = _percentage_bucket(str(identifier), salt=flag)
            if bucket < pct:
                return True

    # (f) default
    return False


async def resolve_flags_for_user(
    db,
    *,
    user_id: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Dict[str, bool]:
    """Return {flag: bool} for every flag in the DB. Used by the
    GET /api/feature-flags/me endpoint so the frontend can hydrate
    its provider in one round-trip.

    Iterates the flags collection; for each flag, runs the same
    is_feature_enabled resolution. The collection should be small
    (dozens of flags max in practice) so this is a single query
    plus per-flag in-memory checks.
    """
    out: Dict[str, bool] = {}
    try:
        cursor = db.feature_flags.find({}, {"flag": 1})
        async for doc in cursor:
            name = doc.get("flag")
            if not name:
                continue
            out[name] = await is_feature_enabled(
                db, name,
                user_id=user_id, company_id=company_id,
            )
    except Exception as e:
        # Fail closed on collection-level errors — the caller
        # should treat an empty map as "no flags enabled".
        logger.warning(
            f"[feature_flags] resolve_flags_for_user failed: {e!r}",
        )
    return out


# ──────────────────────────────────────────────────────────────────
# Schema validation helpers (used by admin POST/PATCH endpoints)
# ──────────────────────────────────────────────────────────────────


VALID_ACTIONS = ("created", "updated", "deleted")


def normalize_flag_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a request payload into the canonical flag-doc shape.
    Drops unknown fields (defense against an attacker injecting
    extra keys into the doc) and applies sane defaults so the
    Mongo write doesn't see Nones where booleans/ints are expected.

    Caller still has to enforce the unique `flag` index — this
    function only cleans the data shape.
    """
    flag = (body.get("flag") or "").strip()
    if not flag:
        raise ValueError("flag name is required")

    enabled_globally = bool(body.get("enabled_globally") or False)

    # Validate types BEFORE applying defaults — `{} or []` evaluates
    # to `[]` (dict is falsy), so a `{}` payload would otherwise
    # silently coerce to an empty list. Be strict about the wire
    # contract; reject non-list inputs with an explicit error.
    raw_companies = body.get("enabled_for_companies", None)
    if raw_companies is not None and not isinstance(raw_companies, list):
        raise ValueError("enabled_for_companies must be a list")
    enabled_for_companies = [str(c) for c in (raw_companies or []) if c]

    raw_users = body.get("enabled_for_users", None)
    if raw_users is not None and not isinstance(raw_users, list):
        raise ValueError("enabled_for_users must be a list")
    enabled_for_users = [str(u) for u in (raw_users or []) if u]

    pct = body.get("enabled_percentage")
    if pct is None:
        pct = 0
    try:
        pct = int(pct)
    except (TypeError, ValueError):
        raise ValueError("enabled_percentage must be an integer")
    if pct < 0 or pct > 100:
        raise ValueError("enabled_percentage must be in [0, 100]")

    description = (body.get("description") or "").strip()

    return {
        "flag": flag,
        "enabled_globally": enabled_globally,
        "enabled_for_companies": enabled_for_companies,
        "enabled_for_users": enabled_for_users,
        "enabled_percentage": pct,
        "description": description,
    }
