"""Eligibility dispatcher — env-var routed.

Three modes via ELIGIBILITY_REWRITE_MODE:
  - "off"    (default) : legacy logic only. UI sees legacy result.
  - "shadow"           : both run; legacy drives UI; v2 runs in
                         background and writes to eligibility_shadow.
  - "live"             : v2 drives UI; legacy retired (the dispatcher
                         doesn't even invoke it).

Cutover plan:
  1. Deploy with mode="off" — no behavior change, no shadow writes.
  2. Flip to "shadow" in Railway env. Cron sweeps every 30min.
  3. After 48hr, run scripts/eligibility_shadow_report.py. Verify
     Cat 1 == 0 and Cat 5 == 0. Resolve any Cat 3 review queue items.
  4. Flip to "live". Confirm UI works against v2 result.
  5. Delete legacy code in a follow-up PR.

Every public callsite of the legacy `check_renewal_eligibility`
imports from here instead. The dispatcher fetches (permit, project,
company) once and passes the SAME tuple to both inner functions —
this is the snapshot-of-input determinism point 6 from step 5.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger(__name__)


VALID_MODES = {"off", "shadow", "live"}
_MODE_ENV = "ELIGIBILITY_REWRITE_MODE"


def get_mode() -> str:
    """Read ELIGIBILITY_REWRITE_MODE. Fail-fast on typos."""
    mode = os.environ.get(_MODE_ENV, "off").lower().strip()
    if mode not in VALID_MODES:
        raise RuntimeError(
            f"{_MODE_ENV}={mode!r} is invalid. Must be one of "
            f"{sorted(VALID_MODES)}. A typo here would silently default "
            f"to 'off' (the worst case — you think shadow is running, "
            f"it isn't, you cut over after 48h of zero data)."
        )
    return mode


def assert_valid_mode_at_startup() -> str:
    """Call once during FastAPI startup. Any typo crashes the process
    immediately rather than booting in 'off' mode silently. Returns
    the validated mode for logging."""
    mode = get_mode()
    logger.info(f"[eligibility] dispatcher booted in mode={mode!r}")
    return mode


# ── ID helpers (shared with permit_renewal.py) ─────────────────────

def _to_oid(s):
    from bson import ObjectId
    if isinstance(s, ObjectId):
        return s
    try:
        return ObjectId(str(s))
    except Exception:
        return s


# ── Dispatcher ──────────────────────────────────────────────────────

async def check_renewal_eligibility(
    db,
    permit_dob_log_id: str,
    project_id: str,
    company_name: str,
    company_id: Optional[str] = None,
):
    """Public entry point. Replaces the legacy function of the same name.
    Existing callsites continue to work unchanged.

    In "off" mode, this is a thin pass-through to legacy.
    In "shadow", we ALSO run v2 and persist a shadow record, but UI
                  always sees the legacy result.
    In "live",  we run only v2 and return a RenewalEligibility-shaped
                 result built from its dict output.
    """
    from permit_renewal import _check_renewal_eligibility_legacy_inner
    from lib import eligibility_v2

    mode = get_mode()
    today = datetime.now(timezone.utc)

    # Pre-fetch the three docs ONCE so both inners see identical state.
    permit = await db.dob_logs.find_one({"_id": _to_oid(permit_dob_log_id)})
    project = await db.projects.find_one({"_id": _to_oid(project_id)})
    resolved_company_id = company_id or (project.get("company_id") if project else None)
    company = (
        await db.companies.find_one({"_id": _to_oid(resolved_company_id), "is_deleted": {"$ne": True}})
        if resolved_company_id else None
    )

    # Legacy needs company_name as a positional fallback when it
    # resolves the GC license; preserve that arg path.
    async def _legacy(p, pj, co, t):
        return await _check_renewal_eligibility_legacy_inner(
            db, p, pj, company_name, co, today=t,
        )

    async def _v2(d, p, pj, co, t):
        return await eligibility_v2.evaluate(d, p, pj, co or {}, today=t)

    if mode == "off":
        return await _legacy(permit, project, company, today)

    if mode == "live":
        v2_result = await _v2(db, permit, project, company, today)
        return _v2_to_renewal_eligibility(v2_result, project_id=project_id, permit_id=permit_dob_log_id)

    # mode == "shadow"
    from lib import eligibility_shadow

    shadow_doc = await eligibility_shadow.run_one(
        db,
        legacy_callable=_legacy,
        v2_callable=_v2,
        permit=permit,
        project=project,
        company=company or {},
        today=today,
    )
    try:
        await db.eligibility_shadow.insert_one(shadow_doc)
    except Exception as e:
        logger.warning(f"[eligibility] failed to write shadow doc: {e}")

    # In shadow mode, UI sees legacy. If legacy crashed AND v2 worked,
    # we still want a result for the UI — fall back to v2 in that
    # specific case rather than 500 the request.
    if shadow_doc.get("old_crashed") and not shadow_doc.get("new_crashed"):
        logger.warning(
            f"[eligibility] shadow: legacy crashed for permit "
            f"{shadow_doc.get('permit_id')}, falling back to v2 for UI"
        )
        v2_result = await _v2(db, permit, project, company, today)
        return _v2_to_renewal_eligibility(v2_result, project_id=project_id, permit_id=permit_dob_log_id)

    return await _legacy(permit, project, company, today)


def _v2_to_renewal_eligibility(v2_result: dict, *, project_id: str, permit_id: str):
    """Adapt the v2 dict to the RenewalEligibility Pydantic shape so
    `live` mode is a drop-in replacement on the existing UI contract.

    As of step 6 commit 2.1, also passes the v2-enriched fields
    (effective_expiry, renewal_strategy, limiting_factor, action)
    through to the response so the frontend can render them. Legacy
    mode and shadow mode's normal path leave these as None — the
    frontend MUST handle absence gracefully."""
    from permit_renewal import RenewalEligibility, GCLicenseInfo

    eligible = (
        v2_result.get("renewal_strategy") in ("AUTO_EXTEND_DOB_NOW", "AUTO_EXTEND_BIS_31D", "AWAITING_EXTENSION")
        and not v2_result.get("blocking_reasons")
        and not v2_result.get("insurance_not_entered")
    )

    days_until = (v2_result.get("limiting_factor") or {}).get("expires_in_days")

    return RenewalEligibility(
        eligible=bool(eligible),
        permit_id=permit_id,
        project_id=project_id,
        job_number=None,
        permit_type=None,
        expiration_date=v2_result.get("calendar_expiry"),
        days_until_expiry=days_until,
        renewal_path="dob_now" if (v2_result.get("filing_system") == "DOB_NOW") else "bis_legacy",
        paa_required=False,
        gc_license=GCLicenseInfo(
            license_number=v2_result.get("permittee_license_number"),
        ),
        blocking_reasons=v2_result.get("blocking_reasons") or [],
        insurance_flags=[],
        insurance_not_entered=bool(v2_result.get("insurance_not_entered")),
        # ── v2 enrichment passthrough ──
        effective_expiry=v2_result.get("effective_expiry"),
        renewal_strategy=v2_result.get("renewal_strategy"),
        limiting_factor=v2_result.get("limiting_factor"),
        action=v2_result.get("action"),
    )
