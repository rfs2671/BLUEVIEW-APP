"""Shadow-mode comparator for the permit-renewal eligibility rewrite.

Runs old + new logic with the SAME pre-fetched (permit, project,
company) tuple, classifies the diff into one of five categories per
the contract in step 5, writes a doc to `eligibility_shadow`. Used
for the 48hr cutover decision before flipping ELIGIBILITY_REWRITE_MODE
from "shadow" to "live".

The five categories — see ~/.claude/plans/permit-renewal-v3.md and
the step-5 contract pasted into the conversation:

  Cat 1 — IDENTITY    : passthrough fields that must match exactly
  Cat 2 — EXPECTED    : fields that should differ (the whole point)
  Cat 3 — SEVERITY    : escalation/de-escalation, individual review
  Cat 4 — PERFORMANCE : latency tracking
  Cat 5 — CRASH       : exceptions either side, blocks cutover
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ── Diff classification helpers ────────────────────────────────────

IDENTITY_FIELDS = [
    "permit_id",
    "calendar_expiry",
    "issuance_date",
    "permittee_license_number",
]


def _normalize(value: Any) -> Any:
    """Coerce datetime/iso-string/None to a comparable form so e.g.
    naive vs aware UTC datetimes don't show as a false diff. Mirrors
    the same tolerance we used in the fee_schedule migration.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, str):
        try:
            from dateutil import parser as dp
            parsed = dp.parse(value)
            v = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return value
    return value


def _eq(a: Any, b: Any) -> bool:
    return _normalize(a) == _normalize(b)


def _legacy_severity_tier(legacy_result) -> int:
    """Map legacy RenewalEligibility (Pydantic) into the same 0/1/2/3
    scale eligibility_v2.severity_tier produces.

    Legacy never produces tier 1 (no AWAITING_EXTENSION concept) — that
    asymmetry is the whole reason we add `awaiting_extension_window`
    as an expected Cat 2 sub-class instead of letting it fire as a
    Cat 3 escalation.
    """
    if hasattr(legacy_result, "model_dump"):
        d = legacy_result.model_dump()
    elif hasattr(legacy_result, "dict"):
        d = legacy_result.dict()
    elif isinstance(legacy_result, dict):
        d = legacy_result
    else:
        return 3  # unknown shape — treat as pessimistic block

    blocking = d.get("blocking_reasons") or []
    if blocking:
        return 3
    if d.get("insurance_not_entered"):
        return 2
    return 0


# ── Sub-class rules for Cat 2 effective_expiry divergences ─────────

def _classify_effective_expiry_divergence(
    new_result: dict,
    legacy_calendar_expiry,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Pick a sub-kind for the report. legacy has no effective_expiry
    concept; we treat its calendar_expiry as the legacy proxy. Any
    shift earlier in the new result is attributed to a specific cause
    so the operator reading the report can verify the cause matches
    expectations.

    Sub-class precedence (most specific first):
      1. AWAITING_EXTENSION strategy + insurance/license limiting →
         awaiting_extension_window (48hr Socrata-lag handling, not a
         real divergence)
      2. permit_class == sidewalk_shed → shed_90d_cap
      3. filing_system == BIS → bis_31d_lookahead
      4. limiting_kind explains the shift cleanly:
           annual_ceiling → annual_ceiling_binding
           license       → license_binding
           insurance     → insurance_binding
      5. Same date, different label → limit_factor_relabel
      6. Unattributed → other (with example_detail for the report)

    The level-4 sub-classes were added after the dry-run showed 24
    "other" hits that were all annual_ceiling-binding cases. These
    are expected: v2 chooses the earlier of (calendar_expiry,
    issuance + 365d), legacy returned only calendar_expiry.

    Returns (sub_kind, example_payload). example_payload is None
    except for sub_kind == "other".
    """
    permit_class = (new_result.get("permit_class") or "").lower()
    filing_system = (new_result.get("filing_system") or "").upper()
    strategy = new_result.get("renewal_strategy")
    limiting_kind = (new_result.get("limiting_factor") or {}).get("kind")

    new_eff = _normalize(new_result.get("effective_expiry"))
    old_eff = _normalize(legacy_calendar_expiry)

    if strategy == "AWAITING_EXTENSION" and limiting_kind in ("insurance", "license"):
        return ("awaiting_extension_window", None)

    if permit_class == "sidewalk_shed" and new_eff != old_eff:
        return ("shed_90d_cap", None)

    if filing_system == "BIS" and new_eff != old_eff:
        return ("bis_31d_lookahead", None)

    if new_eff != old_eff:
        if limiting_kind == "annual_ceiling":
            return ("annual_ceiling_binding", None)
        if limiting_kind == "license":
            return ("license_binding", None)
        if limiting_kind == "insurance":
            return ("insurance_binding", None)

    if new_eff == old_eff:
        return ("limit_factor_relabel", None)

    return ("other", {
        "permit_class": permit_class,
        "filing_system": filing_system,
        "renewal_strategy": strategy,
        "limiting_kind": limiting_kind,
        "new_effective_expiry": new_eff,
        "legacy_calendar_expiry": old_eff,
    })


# ── Top-level shadow run for one permit ────────────────────────────

async def run_one(
    db,
    legacy_callable,
    v2_callable,
    *,
    permit: dict,
    project: dict,
    company: dict,
    today: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Run both legacy and v2 logic, classify divergences, return the
    shadow doc that should be inserted into `eligibility_shadow`.

    `legacy_callable(permit, project, company, today)` and
    `v2_callable(db, permit, project, company, today)` are the two
    inner functions. The dispatcher passes them in so this module
    has no knowledge of where the legacy logic lives.
    """
    today = today or datetime.now(timezone.utc)

    # ── Run legacy (timed, isolated) ──
    legacy_t0 = time.perf_counter()
    legacy_result = None
    legacy_error = None
    try:
        legacy_result = await legacy_callable(permit, project, company, today)
    except Exception as e:
        legacy_error = {
            "type": type(e).__name__,
            "message": str(e),
            "trace": traceback.format_exc()[-2000:],
        }
    legacy_latency_ms = (time.perf_counter() - legacy_t0) * 1000.0

    # ── Run v2 (timed, isolated) ──
    v2_t0 = time.perf_counter()
    v2_result = None
    v2_error = None
    try:
        v2_result = await v2_callable(db, permit, project, company, today)
    except Exception as e:
        v2_error = {
            "type": type(e).__name__,
            "message": str(e),
            "trace": traceback.format_exc()[-2000:],
        }
    v2_latency_ms = (time.perf_counter() - v2_t0) * 1000.0

    # ── Classify ──
    divergences: List[Dict[str, Any]] = []

    # Cat 5 — crashes block cutover
    if legacy_error or v2_error:
        if legacy_error:
            divergences.append({
                "field": "legacy_exception",
                "category": "crash",
                "side": "legacy",
                "exception": legacy_error,
            })
        if v2_error:
            divergences.append({
                "field": "v2_exception",
                "category": "crash",
                "side": "v2",
                "exception": v2_error,
            })
        return {
            "permit_id": str(permit.get("_id")),
            "ran_at": today,
            "old_result": _result_for_storage(legacy_result),
            "new_result": _result_for_storage(v2_result),
            "divergences": divergences,
            "old_latency_ms": legacy_latency_ms,
            "new_latency_ms": v2_latency_ms,
            "old_crashed": bool(legacy_error),
            "new_crashed": bool(v2_error),
        }

    legacy_dict = _coerce_result_to_dict(legacy_result)
    v2_dict = v2_result or {}

    # Cat 1 — identity passthroughs.
    # Compare against the SOURCE-OF-TRUTH input docs (permit + company),
    # not the legacy result. Legacy's RenewalEligibility doesn't surface
    # issuance_date or company-side license_number directly, so reading
    # them off the legacy output would always show false-positive
    # divergences. Both old and new logic should be reading these
    # passthroughs from the same upstream input.
    identity_sources = {
        "permit_id": str(permit.get("_id")),
        "calendar_expiry": permit.get("expiration_date"),
        "issuance_date": permit.get("issuance_date"),
        "permittee_license_number": (company or {}).get("gc_license_number"),
    }
    for field, source_value in identity_sources.items():
        new_v = v2_dict.get(field)
        if not _eq(source_value, new_v):
            divergences.append({
                "field": field,
                "category": "identity",
                "old_value": source_value,
                "new_value": new_v,
            })

    # Cat 2 — expected divergences
    new_eff = v2_dict.get("effective_expiry")
    old_eff_proxy = legacy_dict.get("expiration_date")  # legacy's nearest proxy
    if not _eq(new_eff, old_eff_proxy):
        sub_kind, example = _classify_effective_expiry_divergence(v2_dict, old_eff_proxy)
        entry = {
            "field": "effective_expiry",
            "category": "expected",
            "kind": sub_kind,
            "old_value": _normalize(old_eff_proxy),
            "new_value": _normalize(new_eff),
        }
        if example is not None:
            entry["example_detail"] = example
        divergences.append(entry)

    new_strategy = v2_dict.get("renewal_strategy")
    if new_strategy:
        divergences.append({
            "field": "renewal_strategy",
            "category": "expected",
            "kind": "new_taxonomy",
            "old_value": None,
            "new_value": new_strategy,
        })

    new_action_kind = (v2_dict.get("action") or {}).get("kind")
    if new_action_kind:
        divergences.append({
            "field": "action.kind",
            "category": "expected",
            "kind": "new_taxonomy",
            "old_value": None,
            "new_value": new_action_kind,
        })

    new_limit_label = (v2_dict.get("limiting_factor") or {}).get("label")
    if new_limit_label:
        divergences.append({
            "field": "limiting_factor.label",
            "category": "expected",
            "kind": "new_taxonomy",
            "old_value": None,
            "new_value": new_limit_label,
        })

    # Cat 3 — severity escalation / de-escalation
    # Compute both sides on the same 0/1/2/3 scale.
    from lib.eligibility_v2 import severity_tier as _v2_sev
    legacy_sev = _legacy_severity_tier(legacy_result)
    v2_sev = _v2_sev(v2_dict)

    # Carve-out: legacy 0 → v2 1 with strategy AWAITING_EXTENSION is
    # the expected promotion handled in Cat 2, NOT a Cat 3 escalation.
    is_awaiting_carveout = (
        legacy_sev == 0 and v2_sev == 1
        and new_strategy == "AWAITING_EXTENSION"
    )

    if legacy_sev != v2_sev and not is_awaiting_carveout:
        direction = "escalation" if v2_sev > legacy_sev else "deescalation"
        divergences.append({
            "field": "severity_tier",
            "category": "severity",
            "direction": direction,
            "old_value": legacy_sev,
            "new_value": v2_sev,
        })

    return {
        "permit_id": str(permit.get("_id")),
        "ran_at": today,
        "old_result": _result_for_storage(legacy_result),
        "new_result": _result_for_storage(v2_result),
        "divergences": divergences,
        "old_latency_ms": legacy_latency_ms,
        "new_latency_ms": v2_latency_ms,
        "old_crashed": False,
        "new_crashed": False,
    }


def _coerce_result_to_dict(result) -> dict:
    if result is None:
        return {}
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if isinstance(result, dict):
        return result
    return {}


def _resolve_legacy_field(legacy_dict: dict, field: str) -> Any:
    """Map step-5 contract field names to legacy result fields."""
    if field == "permit_id":
        return legacy_dict.get("permit_id")
    if field == "calendar_expiry":
        return legacy_dict.get("expiration_date")
    if field == "issuance_date":
        # Legacy didn't surface issuance_date directly. Return None;
        # v2's value also stays None for backfilled-only permits.
        # Cat 1 only fires when both sides have it AND they differ.
        return legacy_dict.get("issuance_date")
    if field == "permittee_license_number":
        gc = legacy_dict.get("gc_license") or {}
        if isinstance(gc, dict):
            return gc.get("license_number")
        return getattr(gc, "license_number", None)
    return None


def _result_for_storage(result) -> Optional[dict]:
    """Make Pydantic models / nested datetimes Mongo-safe."""
    if result is None:
        return None
    d = _coerce_result_to_dict(result)
    return _stringify_datetimes(d)


def _stringify_datetimes(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return _normalize(obj)
    if isinstance(obj, dict):
        return {k: _stringify_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_datetimes(x) for x in obj]
    return obj
