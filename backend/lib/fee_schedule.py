"""DOB permit-renewal fee resolution.

Looks up the active fee rule from the `fee_schedule` Mongo collection
for a given (work_type, date) pair. Used by the renewal-eligibility
engine to compute `estimated_fee_cents` + `split_payment_breakdown`
for the frontend, instead of hardcoding a literal $130.

Why a Mongo collection (vs code constant or env var):
  - Time-bounded rules: LL128 of 2024 raised $100 → $130 effective
    2025-12-21. Future LLs will adjust again. Storing as data lets
    queries match by date without code changes.
  - Split-payment shape: LL128 introduced split rules per work-type-class
    (CO-change vs not vs electrical). Nested object → ugly in env vars.
  - Forward-compat: `applies_to` filter supports future shed-specific
    or work-type-specific overrides without schema migration.
  - Audit trail: a future admin endpoint can update without redeploy;
    git history of the seed migration is the v1 audit log.

Cache: 5-minute in-process. Cache bust hook (`bust_fee_cache`) for the
future admin update endpoint to call when fees are rotated, so admins
don't see stale data after their own write.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_CACHE_TTL_SECONDS = 300  # 5min — invalidated by bust_fee_cache() on admin writes
_cache: Dict[str, Any] = {"rules": None, "expires_at": 0.0}


def bust_fee_cache() -> None:
    """Force the next get_fee() call to re-read from Mongo.

    Call this from any admin endpoint that mutates the fee_schedule
    collection so admins don't see "I updated the fee but it's still
    showing the old one for 5min" — which has eaten support tickets
    on every other system that didn't wire this up.
    """
    _cache["rules"] = None
    _cache["expires_at"] = 0.0


def _utc(dt: datetime) -> datetime:
    """Coerce naive datetime to UTC-aware. Mongo can hand back either."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _matches_window(rule: dict, today: datetime) -> bool:
    """`effective_from <= today` AND (`effective_until` is None OR
    `today <= effective_until`). Inclusive on both ends — boundary
    days fall under the rule whose window contains them.
    """
    ef = rule.get("effective_from")
    eu = rule.get("effective_until")
    if ef is None:
        return False
    if _utc(ef) > today:
        return False
    if eu is not None and today > _utc(eu):
        return False
    return True


def _matches_applies_to(rule: dict, work_type: Optional[str]) -> bool:
    applies = rule.get("applies_to") or ["ALL"]
    if "ALL" in applies:
        return True
    if work_type and work_type.upper() in {a.upper() for a in applies}:
        return True
    return False


def _specificity(rule: dict, work_type: Optional[str]) -> int:
    """Higher = more specific. A rule whose `applies_to` lists the
    work_type explicitly beats a rule with just `["ALL"]`. Tied rules
    fall back to `effective_from` (most recent wins).
    """
    applies = rule.get("applies_to") or ["ALL"]
    if work_type and work_type.upper() in {a.upper() for a in applies if a != "ALL"}:
        return 2
    if "ALL" in applies:
        return 1
    return 0


def _resolve_split(rule: dict, work_type: Optional[str], co_change: bool) -> dict:
    """Pick the split sub-rule for the given work_type/co_change.

    Priority:
      1. If split_rules has an `"all"` key (legacy pre-LL128 shape) → use it.
      2. If work_type maps to electrical → use `"electrical"` if present.
      3. If co_change → `"non_electrical_co_change"`.
      4. Else → `"non_electrical_no_co_change"`.
      5. If none match → return rule's split_rules unchanged so callers
         can decide what to do with an unexpected shape.
    """
    sr = rule.get("split_rules") or {}
    if "all" in sr:
        return sr["all"]
    wt = (work_type or "").upper()
    if wt in {"EL", "EW", "EQ"} or wt.startswith("E"):
        if "electrical" in sr:
            return sr["electrical"]
    key = "non_electrical_co_change" if co_change else "non_electrical_no_co_change"
    if key in sr:
        return sr[key]
    return sr


def pick_active_rule(
    rules: List[dict],
    today: datetime,
    work_type: Optional[str] = None,
    *,
    co_change: bool = False,
) -> dict:
    """Pure function: find the single active rule for (today, work_type).

    Pulled out as a sync helper so the boundary-test cases can run
    without an event loop or a Mongo dependency. `get_fee` is a thin
    async wrapper around this + the cache.

    Raises RuntimeError if no rule matches.
    """
    today = _utc(today)
    matching = [
        r for r in rules
        if _matches_window(r, today) and _matches_applies_to(r, work_type)
    ]
    if not matching:
        raise RuntimeError(
            f"No fee_schedule rule active for date={today.isoformat()} "
            f"work_type={work_type!r}. Rules count={len(rules)}."
        )

    matching.sort(
        key=lambda r: (
            _specificity(r, work_type),
            _utc(r["effective_from"]),
        ),
        reverse=True,
    )
    chosen = matching[0]
    split = _resolve_split(chosen, work_type, co_change)
    return {
        "fee_cents": chosen.get("min_renewal_fee_cents"),
        "split": split,
        "rule_id": chosen.get("_id"),
        "applies_to": chosen.get("applies_to", ["ALL"]),
        "effective_from": chosen.get("effective_from"),
        "effective_until": chosen.get("effective_until"),
        "notes": chosen.get("notes"),
    }


async def get_fee(
    db,
    work_type: Optional[str] = None,
    today: Optional[datetime] = None,
    *,
    co_change: bool = False,
) -> dict:
    """Async wrapper: fetch (cached) rules, pick active, return resolved
    fee + split. `db` is the Motor AsyncIOMotorDatabase instance.

    Caches all rules for `_CACHE_TTL_SECONDS` (5min). Cache is busted
    proactively by `bust_fee_cache()` from the future admin endpoint.
    """
    today = today or datetime.now(timezone.utc)

    now_mono = time.monotonic()
    if _cache["rules"] is None or now_mono > _cache["expires_at"]:
        rules = await db.fee_schedule.find({}).to_list(50)
        _cache["rules"] = rules
        _cache["expires_at"] = now_mono + _CACHE_TTL_SECONDS

    return pick_active_rule(_cache["rules"], today, work_type, co_change=co_change)
