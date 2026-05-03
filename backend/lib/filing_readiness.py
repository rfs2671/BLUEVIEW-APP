"""MR.3 — Filing readiness checker service.

Deterministic pre-flight check that takes a permit_renewal doc and
returns a structured "are we ready to file?" report. Pure backend
service, tested in isolation. No UI, no queue integration, no agent
dispatch — that's MR.6 onward.

Consumers:
  - GET /api/permit-renewals/{id}/filing-readiness (this commit)
  - MR.6's enqueue-filing endpoint will call this to refuse jobs
    that would fail due to missing data (saves the local Docker
    worker from wasting cycles on guaranteed-failure runs)

Contract:
  - 10 checks, each its own pure function with a deterministic output.
  - Order matters: check 1 (permit_renewal_exists) short-circuits the
    whole report on failure because subsequent checks depend on the
    renewal record. Checks 2-10 each handle missing references
    gracefully (produce fail/warn of their own; no exceptions).
  - The function does NOT mutate state. No Mongo writes. No external
    API calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


# ── Constants ──────────────────────────────────────────────────────

# Action kinds the local filing agent will eventually handle. For
# MR.3, only manual_renewal_dob_now is in scope; other kinds get a
# warn with detail. As MR.5+ ships handlers for additional kinds,
# add them here.
ACTIONABLE_ACTION_KINDS: set = {
    "manual_renewal_dob_now",
}

# work_type → acceptable license_class mapping. SURFACE-LEVEL
# REGULATORY: this is the starter mapping; the actual NYC DOB rules
# governing which license classes can pull which permit work types
# are codified across multiple RCNY sections + Administrative Code
# titles. The mapping below is a starting point that should be
# reviewed against authoritative sources before MR.6 ships filings
# at any scale.
#
# Format: work_type prefix (case-insensitive substring match) → list
# of acceptable license_class values, in priority order. Anything
# not in this dict triggers a warn — caller verifies the primary
# filing_rep is appropriate manually.
#
# "GC" appearing in many lists captures the regulatory pattern that
# a licensed General Contractor can pull most work-type permits in
# practice (subject to scope), but a trade-specific license is
# preferred when available — hence the warn-when-GC-substituted-for-
# trade-specific behavior in check_license_class_appropriate.
WORK_TYPE_LICENSE_CLASS_MAP: Dict[str, List[str]] = {
    "plumbing": ["Plumber", "GC"],
    "sprinklers": ["Master Fire Suppression Contractor", "GC"],
    "fire suppression": ["Master Fire Suppression Contractor", "GC"],
    "electrical": ["Electrician", "GC"],
    "construction": ["GC"],
    "general construction": ["GC"],
    "gc": ["GC"],
}


# ── Models ─────────────────────────────────────────────────────────

class ReadinessCheck(BaseModel):
    """A single check's outcome.

    name: stable identifier (e.g. 'filing_rep_present') — safe to
          program against in tests / consumers.
    status: 'pass' / 'fail' / 'warn'. 'fail' blocks readiness;
          'warn' surfaces a concern but doesn't block.
    detail: human-readable detail. Surfaced verbatim in the
          blockers/warnings arrays of the report.
    """
    name: str
    status: str
    detail: str


class FilingReadinessReport(BaseModel):
    ready: bool
    permit_renewal_id: str
    checks: List[ReadinessCheck]
    blockers: List[str]
    warnings: List[str]


# ── ID + helper boilerplate ────────────────────────────────────────

def _to_oid(s):
    """Mirrors the same helper in permit_renewal.py + the dispatcher.
    Inlined here so the module has no dependency on the larger
    permit_renewal namespace."""
    from bson import ObjectId
    if isinstance(s, ObjectId):
        return s
    try:
        return ObjectId(str(s))
    except Exception:
        return s


def _terminal_statuses() -> set:
    """RenewalStatus.{COMPLETED, FAILED} as raw strings. Avoids a
    cyclic import on the larger server module."""
    return {"completed", "failed"}


# MR.13 — re-export the bypass helper from the shared lib so any
# future days-based readiness check defined in this file inherits
# the same env-var override (ELIGIBILITY_BYPASS_DAYS_REMAINING).
# Currently filing_readiness has no days-window check; keeping this
# import-of-record so a future check picks up the bypass without a
# second source of truth.
from lib.eligibility_v2 import (  # noqa: E402, F401
    get_effective_renewal_window_days,
)


# ── Individual checks (pure functions) ─────────────────────────────
# Each returns a single ReadinessCheck. None of these raise — they
# encode failure modes as ReadinessCheck(status='fail') so the
# report builder can run them all unconditionally and return a
# complete picture even when references are missing.

def _check_permit_dob_log_exists(permit: Optional[dict]) -> ReadinessCheck:
    if not permit:
        return ReadinessCheck(
            name="permit_dob_log_exists",
            status="fail",
            detail="Referenced dob_log not found — orphaned renewal record cannot be filed.",
        )
    if permit.get("is_deleted"):
        return ReadinessCheck(
            name="permit_dob_log_exists",
            status="fail",
            detail="Referenced dob_log is soft-deleted — cannot file against a deleted permit.",
        )
    return ReadinessCheck(
        name="permit_dob_log_exists",
        status="pass",
        detail="dob_log resolves and is active.",
    )


def _check_project_exists(project: Optional[dict]) -> ReadinessCheck:
    if not project:
        return ReadinessCheck(
            name="project_exists",
            status="fail",
            detail="Referenced project not found.",
        )
    if project.get("is_deleted"):
        return ReadinessCheck(
            name="project_exists",
            status="fail",
            detail="Referenced project is soft-deleted.",
        )
    return ReadinessCheck(
        name="project_exists",
        status="pass",
        detail="Project resolves and is active.",
    )


def _check_company_exists(company: Optional[dict]) -> ReadinessCheck:
    if not company:
        return ReadinessCheck(
            name="company_exists",
            status="fail",
            detail="Referenced company not found.",
        )
    if company.get("is_deleted"):
        return ReadinessCheck(
            name="company_exists",
            status="fail",
            detail="Referenced company is soft-deleted.",
        )
    return ReadinessCheck(
        name="company_exists",
        status="pass",
        detail="Company resolves and is active.",
    )


def _check_filing_reps_present(company: Optional[dict]) -> ReadinessCheck:
    reps = (company or {}).get("filing_reps") or []
    if len(reps) == 0:
        return ReadinessCheck(
            name="filing_reps_present",
            status="fail",
            detail="No filing representatives configured for this company. Add one in the owner portal.",
        )
    return ReadinessCheck(
        name="filing_reps_present",
        status="pass",
        detail=f"{len(reps)} filing representative(s) configured.",
    )


def _check_primary_filing_rep_present(company: Optional[dict]) -> ReadinessCheck:
    reps = (company or {}).get("filing_reps") or []
    primaries = [r for r in reps if r.get("is_primary")]
    if len(primaries) == 0:
        if len(reps) == 0:
            # No reps at all — already covered by filing_reps_present;
            # don't double-blocker.
            return ReadinessCheck(
                name="primary_filing_rep_present",
                status="fail",
                detail="No filing representatives — primary cannot be selected.",
            )
        return ReadinessCheck(
            name="primary_filing_rep_present",
            status="warn",
            detail="No primary filing representative set; caller will default to the first entry.",
        )
    if len(primaries) > 1:
        return ReadinessCheck(
            name="primary_filing_rep_present",
            status="fail",
            detail=(
                f"Data integrity issue: {len(primaries)} filing representatives "
                "marked is_primary=true. Exactly one is expected."
            ),
        )
    return ReadinessCheck(
        name="primary_filing_rep_present",
        status="pass",
        detail=f"Primary filing representative: {primaries[0].get('name', '?')}.",
    )


def _resolve_acting_rep(company: Optional[dict]) -> Optional[dict]:
    """Returns the rep we'd file under: primary if set, else first
    non-empty rep, else None. Used by license-class check to pick
    which rep to evaluate against work_type."""
    reps = (company or {}).get("filing_reps") or []
    if not reps:
        return None
    primaries = [r for r in reps if r.get("is_primary")]
    if len(primaries) == 1:
        return primaries[0]
    if len(primaries) > 1:
        # Data integrity issue caught upstream; pick the first
        # primary deterministically so this check still runs.
        return primaries[0]
    return reps[0]


def _check_license_class_appropriate(
    company: Optional[dict],
    permit: Optional[dict],
) -> ReadinessCheck:
    rep = _resolve_acting_rep(company)
    if not rep:
        return ReadinessCheck(
            name="license_class_appropriate",
            status="fail",
            detail="Cannot evaluate license-class fit: no filing representative resolves.",
        )
    if not permit:
        return ReadinessCheck(
            name="license_class_appropriate",
            status="fail",
            detail="Cannot evaluate license-class fit: dob_log missing.",
        )

    work_type = (permit.get("work_type") or "").strip().lower()
    rep_class = rep.get("license_class") or ""

    if not work_type:
        return ReadinessCheck(
            name="license_class_appropriate",
            status="warn",
            detail=(
                "Permit has no work_type — cannot verify license-class fit. "
                "Confirm primary filing representative is appropriate manually."
            ),
        )

    # Substring match against the mapping keys (case-insensitive).
    matched_key = None
    for key in WORK_TYPE_LICENSE_CLASS_MAP:
        if key in work_type:
            matched_key = key
            break

    if matched_key is None:
        return ReadinessCheck(
            name="license_class_appropriate",
            status="warn",
            detail=(
                f"No license-class mapping for work_type '{permit.get('work_type')}'; "
                "verify primary filing representative is appropriate."
            ),
        )

    acceptable = WORK_TYPE_LICENSE_CLASS_MAP[matched_key]
    if rep_class not in acceptable:
        return ReadinessCheck(
            name="license_class_appropriate",
            status="fail",
            detail=(
                f"Primary filing representative is '{rep_class}'; work_type "
                f"'{permit.get('work_type')}' requires one of {acceptable}."
            ),
        )

    # GC substituting for a trade-specific class → warn, not pass.
    # Only triggers when the FIRST entry in the acceptable list is
    # NOT 'GC' (i.e., a trade-specific class is preferred) AND the
    # rep is GC.
    if acceptable[0] != "GC" and rep_class == "GC":
        return ReadinessCheck(
            name="license_class_appropriate",
            status="warn",
            detail=(
                f"Primary filing representative is GC; work_type "
                f"'{permit.get('work_type')}' typically prefers a {acceptable[0]} "
                "license. GC is acceptable but verify scope."
            ),
        )

    return ReadinessCheck(
        name="license_class_appropriate",
        status="pass",
        detail=f"Primary filing representative's license_class '{rep_class}' fits work_type '{permit.get('work_type')}'.",
    )


def _check_v2_keys_present(renewal: dict) -> ReadinessCheck:
    missing: List[str] = []
    for k in ("renewal_strategy", "effective_expiry", "limiting_factor", "action"):
        if renewal.get(k) is None:
            missing.append(k)
    if missing:
        return ReadinessCheck(
            name="v2_keys_present",
            status="fail",
            detail=(
                f"Missing v2 enrichment keys: {missing}. Re-prepare the renewal "
                "or run scripts/backfill_renewal_v2_keys.py to populate."
            ),
        )
    return ReadinessCheck(
        name="v2_keys_present",
        status="pass",
        detail="All v2 enrichment keys populated.",
    )


def _check_issuance_date_present(renewal: dict) -> ReadinessCheck:
    if not renewal.get("issuance_date"):
        return ReadinessCheck(
            name="issuance_date_present",
            status="fail",
            detail=(
                "Issuance date missing — run backfill_renewal_v2_keys.py with "
                "the latest schema."
            ),
        )
    return ReadinessCheck(
        name="issuance_date_present",
        status="pass",
        detail=f"Issuance date populated: {renewal.get('issuance_date')}.",
    )


def _check_action_kind_actionable(renewal: dict) -> ReadinessCheck:
    action = renewal.get("action") or {}
    kind = action.get("kind")
    if not kind:
        return ReadinessCheck(
            name="action_kind_actionable",
            status="fail",
            detail="No action.kind on renewal — cannot dispatch a filing.",
        )
    if kind in ACTIONABLE_ACTION_KINDS:
        return ReadinessCheck(
            name="action_kind_actionable",
            status="pass",
            detail=f"action.kind '{kind}' is in the supported set.",
        )
    return ReadinessCheck(
        name="action_kind_actionable",
        status="warn",
        detail=(
            f"Action kind '{kind}' is not yet supported by the local filing agent. "
            f"Currently supported: {sorted(ACTIONABLE_ACTION_KINDS)}."
        ),
    )


# ── Top-level orchestrator ─────────────────────────────────────────

async def check_filing_readiness(
    db,
    permit_renewal_id: str,
) -> FilingReadinessReport:
    """Run all 10 checks against the given renewal and return a
    structured report. Pure: no Mongo writes, no external IO beyond
    the four read queries (renewal, dob_log, project, company)."""
    checks: List[ReadinessCheck] = []

    # Check 1: permit_renewal_exists. Short-circuits the whole
    # report if the renewal can't be loaded or is in a terminal
    # state — every downstream check depends on the renewal record.
    renewal = await db.permit_renewals.find_one(
        {"_id": _to_oid(permit_renewal_id)}
    )
    if not renewal:
        c = ReadinessCheck(
            name="permit_renewal_exists",
            status="fail",
            detail="Renewal record not found.",
        )
        return FilingReadinessReport(
            ready=False,
            permit_renewal_id=permit_renewal_id,
            checks=[c],
            blockers=[c.detail],
            warnings=[],
        )
    if renewal.get("is_deleted"):
        c = ReadinessCheck(
            name="permit_renewal_exists",
            status="fail",
            detail="Renewal record is soft-deleted.",
        )
        return FilingReadinessReport(
            ready=False,
            permit_renewal_id=permit_renewal_id,
            checks=[c],
            blockers=[c.detail],
            warnings=[],
        )
    if (renewal.get("status") or "").lower() in _terminal_statuses():
        c = ReadinessCheck(
            name="permit_renewal_exists",
            status="fail",
            detail=f"Renewal is in terminal status '{renewal.get('status')}' — cannot file.",
        )
        return FilingReadinessReport(
            ready=False,
            permit_renewal_id=permit_renewal_id,
            checks=[c],
            blockers=[c.detail],
            warnings=[],
        )
    checks.append(ReadinessCheck(
        name="permit_renewal_exists",
        status="pass",
        detail=f"Renewal active in status '{renewal.get('status')}'.",
    ))

    # Load dependencies once, reuse across downstream checks.
    permit = await db.dob_logs.find_one({
        "_id": _to_oid(renewal.get("permit_dob_log_id")),
    }) if renewal.get("permit_dob_log_id") else None
    project = await db.projects.find_one({
        "_id": _to_oid(renewal.get("project_id")),
    }) if renewal.get("project_id") else None
    company = await db.companies.find_one({
        "_id": _to_oid(renewal.get("company_id")),
    }) if renewal.get("company_id") else None

    # Checks 2-10. Each is independent; missing references produce
    # fail/warn of their own without raising.
    checks.append(_check_permit_dob_log_exists(permit))
    checks.append(_check_project_exists(project))
    checks.append(_check_company_exists(company))
    checks.append(_check_filing_reps_present(company))
    checks.append(_check_primary_filing_rep_present(company))
    checks.append(_check_license_class_appropriate(company, permit))
    checks.append(_check_v2_keys_present(renewal))
    checks.append(_check_issuance_date_present(renewal))
    checks.append(_check_action_kind_actionable(renewal))

    blockers = [c.detail for c in checks if c.status == "fail"]
    warnings = [c.detail for c in checks if c.status == "warn"]

    return FilingReadinessReport(
        ready=len(blockers) == 0,
        permit_renewal_id=permit_renewal_id,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
    )
