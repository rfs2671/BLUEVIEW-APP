"""Permit renewal eligibility — v2 logic.

Implements the spec from ~/.claude/plans/permit-renewal-v3.md:
  - §1.1 renewal_strategy resolution (auto-extend vs manual tracks)
  - §3.1 effective expiry as min(GL, WC, DBL, License, IssueDate+365d)
  - §3.2 BIS 31-day look-ahead vs DOB NOW end-of-day extension
  - §6   sidewalk shed 90-day cap (LL48/2024)

Designed as a set of pure functions taking (permit, company, today)
plus a top-level `evaluate()` that ties them together. All inputs
are dicts (Mongo docs); no DB access from inside this module.
The dispatcher in eligibility_dispatcher.py is responsible for
fetching the docs and passing them in.

This module is loaded under shadow mode (writes to a parallel
collection) before live cutover. See eligibility_shadow.py for the
old-vs-new diff classifier.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from lib.fee_schedule import get_fee


# ── Result shape constants ──────────────────────────────────────────

RenewalStrategy = Literal[
    "AUTO_EXTEND_DOB_NOW",     # B/M/Q/X/R-prefix DOB NOW, end-of-day extension on COI/license update
    "AUTO_EXTEND_BIS_31D",     # numeric BIS legacy, 31-day look-ahead
    "MANUAL_90D_SHED",         # any sidewalk shed permit (LL48/2024)
    "MANUAL_1YR_CEILING",      # effective_expiry hits issuance + 365d
    "MANUAL_LAPSED",           # GL/WC/DBL/license already expired
    "AWAITING_EXTENSION",      # COI/license updated within last 48h, Socrata lag tolerance
]

LimitingKind = Literal[
    "shed_cap", "annual_ceiling", "license", "insurance", "unknown",
]


# ── Helpers ─────────────────────────────────────────────────────────

def _utc(dt) -> Optional[datetime]:
    """Coerce strings or naive datetimes to UTC-aware. None passes through."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            from dateutil import parser as dp
            parsed = dp.parse(dt)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except Exception:
            return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return None


def _find_insurance(company: dict, ins_type: str) -> Optional[dict]:
    """Return the first record matching ins_type. Companies typically
    hold one record per type — the dedupe is enforced by the manual-entry
    UI and the upcoming COI upload flow."""
    for r in company.get("gc_insurance_records") or []:
        if isinstance(r, dict) and r.get("insurance_type") == ins_type:
            return r
    return None


# ── §3.1 effective expiry ───────────────────────────────────────────

INSURANCE_TYPES = [
    ("general_liability", "General Liability"),
    ("workers_comp",      "Workers' Comp"),
    ("disability",        "Disability"),
]


def compute_effective_permit_expiry(
    permit: dict,
    company: dict,
) -> Tuple[Optional[datetime], str, LimitingKind]:
    """Earliest of GL/WC/DBL/License/IssueDate+365d.

    For sidewalk sheds, returns (issuance + 90d, ..., 'shed_cap') ALWAYS
    — insurance/license expirations don't gate shed permit expiration;
    the 90d cap is independent (LL48/2024).

    Returns (date, label, kind). All three None-equivalents if no data.
    """
    issuance = _utc(permit.get("issuance_date"))

    if (permit.get("permit_class") or "").lower() == "sidewalk_shed":
        if issuance is None:
            return (None, "no issuance date for shed permit", "unknown")
        return (
            issuance + timedelta(days=90),
            "90-day shed cap (LL48/2024)",
            "shed_cap",
        )

    candidates: List[Tuple[datetime, str, LimitingKind]] = []

    if issuance:
        candidates.append((
            issuance + timedelta(days=365),
            "1-year issuance ceiling",
            "annual_ceiling",
        ))

    license_exp = _utc(company.get("gc_license_expiration"))
    if license_exp:
        candidates.append((license_exp, "GC License", "license"))

    for ins_key, label in INSURANCE_TYPES:
        rec = _find_insurance(company, ins_key)
        if rec:
            exp = _utc(rec.get("expiration_date"))
            if exp:
                candidates.append((exp, label, "insurance"))

    if not candidates:
        return (None, "no expiry data", "unknown")

    chosen = min(candidates, key=lambda c: c[0])
    return chosen


# ── §3.2 auto-extension look-ahead ─────────────────────────────────

def auto_extension_lookahead_days(permit: dict) -> int:
    """DOB NOW = 0 (end-of-day after carrier submits COI to BIS).
    BIS legacy = 31-day look-ahead window. Per official DOB renewal docs.
    """
    return {"DOB_NOW": 0, "BIS": 31}.get((permit.get("filing_system") or "").upper(), 0)


# ── §1.1 strategy resolution + AWAITING_EXTENSION detection ────────

AWAITING_EXTENSION_WINDOW_HOURS = 48
RECENT_VERIFICATION_WINDOW_DAYS = 5  # COI/license update window before limiting expiry


def _detect_awaiting_extension(
    company: dict,
    limiting_kind: LimitingKind,
    limiting_expiry: Optional[datetime],
    today: datetime,
) -> bool:
    """True when an insurance/license update has just been verified by
    the DOB NOW Public Portal worker (`dob_now_verified_at` written
    within the last 48h) AND that update was within 5 days of the
    limiting expiry.

    Rationale (~/.claude/plans/permit-renewal-v3.md §1.1 step 3): when
    a carrier submits an updated COI to BIS, DOB NOW extends the
    permit end-of-day, but Socrata's mirror lags ~24-48h. During that
    window our `permit.expiration_date` reads stale. Marking the
    permit AWAITING_EXTENSION suppresses false-positive nags.

    Without dob_now_verified_at populated (worker not yet running),
    this never fires. Code path exists for when step 14 ships.
    """
    if limiting_kind not in ("insurance", "license"):
        return False
    if limiting_expiry is None:
        return False

    # Find the most recent verification timestamp on a record whose
    # expiration matches the limiting one.
    candidates: List[datetime] = []
    if limiting_kind == "license":
        synced = _utc(company.get("gc_license_last_synced"))
        if synced:
            candidates.append(synced)
    else:
        for rec in company.get("gc_insurance_records") or []:
            if not isinstance(rec, dict):
                continue
            verified = _utc(rec.get("dob_now_verified_at"))
            if verified is None:
                continue
            candidates.append(verified)

    if not candidates:
        return False

    most_recent = max(candidates)

    # Was the verification within the recent-update window before expiry?
    recent_update_window_start = limiting_expiry - timedelta(days=RECENT_VERIFICATION_WINDOW_DAYS)
    if not (recent_update_window_start <= most_recent):
        return False

    # And is that verification still inside the Socrata-lag window?
    if not (today <= most_recent + timedelta(hours=AWAITING_EXTENSION_WINDOW_HOURS)):
        return False

    return True


def resolve_renewal_strategy(
    permit: dict,
    company: dict,
    today: datetime,
    *,
    effective_expiry: Optional[datetime],
    limiting_kind: LimitingKind,
) -> RenewalStrategy:
    """Per §1.1 resolution table."""
    pclass = (permit.get("permit_class") or "").lower()

    # 1. Sheds always go to manual 90d track
    if pclass == "sidewalk_shed":
        return "MANUAL_90D_SHED"

    # 2. AWAITING_EXTENSION: COI/license just updated, Socrata lag in window
    if _detect_awaiting_extension(company, limiting_kind, effective_expiry, today):
        return "AWAITING_EXTENSION"

    # 3. Already lapsed
    if effective_expiry is not None and effective_expiry < today:
        return "MANUAL_LAPSED"

    # 4. Hit the 1-year ceiling
    if limiting_kind == "annual_ceiling":
        # Manual fee renewal required ONLY if the ceiling is the binding
        # constraint AND we're inside the renewal window. If ceiling is
        # binding but still far away, no immediate action.
        # The action layer decides timing; strategy is stable.
        return "MANUAL_1YR_CEILING"

    # 5. Otherwise auto-extend per filing system
    fs = (permit.get("filing_system") or "DOB_NOW").upper()
    if fs == "BIS":
        return "AUTO_EXTEND_BIS_31D"
    return "AUTO_EXTEND_DOB_NOW"


# ── Severity tier (4-step, see plan §3 + step-5 refinement) ────────

_HARD_BLOCK_STRATEGIES = {"MANUAL_LAPSED", "MANUAL_1YR_CEILING", "MANUAL_90D_SHED"}


def severity_tier(result: dict) -> int:
    """0 = eligible no warnings.
       1 = eligible with informational notice (AWAITING_EXTENSION).
       2 = soft prompt (insurance not entered, no hard block).
       3 = hard block (manual renewal required, OR blocking_reasons set).

    Order matters: hard-block strategies (MANUAL_*) outrank
    insurance_not_entered. A permit on MANUAL_1YR_CEILING with also no
    insurance entered is still a hard block — the soft insurance
    prompt doesn't reduce its severity. This was the bug surfaced in
    the step-5 dry-run (24 false 3→2 deescalations).
    """
    strategy = result.get("renewal_strategy")
    if strategy in _HARD_BLOCK_STRATEGIES:
        return 3
    if result.get("blocking_reasons"):
        return 3
    if strategy == "AWAITING_EXTENSION":
        return 1
    if result.get("insurance_not_entered"):
        return 2
    return 0


# ── Top-level evaluate ─────────────────────────────────────────────

async def evaluate(
    db,
    permit: dict,
    project: dict,
    company: dict,
    *,
    today: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the v2 eligibility result for a single permit.

    Returns a dict with the §3.3 frontend response shape. Dispatcher
    is responsible for shape conversion to RenewalEligibility on the
    UI path.
    """
    today = today or datetime.now(timezone.utc)

    permit_id = str(permit.get("_id"))
    project_id = str(project.get("_id")) if project else ""

    calendar_expiry = _utc(permit.get("expiration_date"))
    effective_expiry, limiting_label, limiting_kind = compute_effective_permit_expiry(permit, company)

    strategy = resolve_renewal_strategy(
        permit, company, today,
        effective_expiry=effective_expiry,
        limiting_kind=limiting_kind,
    )

    days_until_effective = None
    if effective_expiry is not None:
        days_until_effective = (effective_expiry - today).days

    # Are we missing insurance data the user could enter?
    has_any_insurance = any(
        _find_insurance(company, t)
        for t, _ in INSURANCE_TYPES
    )
    insurance_not_entered = (not has_any_insurance) and strategy != "MANUAL_90D_SHED"

    # Build action payload — kind drives the UI, fee_cents/split read
    # from the fee table per work_type and today.
    action = await _build_action(
        db, permit, strategy, effective_expiry, today,
        insurance_not_entered=insurance_not_entered,
    )

    blocking_reasons: List[str] = []

    # Permits with no parseable expiration data are uncomputable.
    # Legacy hard-blocks these with "No expiration date on permit record";
    # v2 must do the same so we don't show "auto-extend, no action" on
    # a permit we literally can't compute eligibility for. Surfaced by
    # the step-5 dry-run (electrical permits with eff=None, limiting=unknown).
    if effective_expiry is None and limiting_kind == "unknown" and (permit.get("permit_class") or "") != "sidewalk_shed":
        blocking_reasons.append(
            "Cannot determine permit expiration — missing expiration / "
            "issuance / insurance data. Re-sync from NYC Open Data or "
            "enter insurance dates in Settings."
        )

    if strategy == "MANUAL_LAPSED":
        blocking_reasons.append(
            f"{limiting_label} lapsed before renewal. "
            f"Manual renewal required ($130 fee) plus updated COI / license."
        )
    elif strategy == "MANUAL_1YR_CEILING":
        blocking_reasons.append(
            "Permit reaches the 1-year-since-issuance ceiling. "
            "Manual renewal required ($130 fee) regardless of insurance state."
        )
    elif strategy == "MANUAL_90D_SHED":
        if effective_expiry and effective_expiry < today:
            blocking_reasons.append(
                "Sidewalk shed permit expired. Per LL48/2024 each 90-day "
                "renewal requires a PE/RA progress report + $130 fee."
            )

    return {
        "permit_id": permit_id,
        "project_id": project_id,
        "filing_system": permit.get("filing_system"),
        "permit_class": permit.get("permit_class"),
        "renewal_strategy": strategy,
        "calendar_expiry": calendar_expiry.isoformat() if calendar_expiry else None,
        "effective_expiry": effective_expiry.isoformat() if effective_expiry else None,
        "limiting_factor": {
            "label": limiting_label,
            "kind":  limiting_kind,
            "expires_in_days": days_until_effective,
        },
        "action": action,
        "blocking_reasons": blocking_reasons,
        "insurance_not_entered": insurance_not_entered,
        "issuance_date": (
            _utc(permit.get("issuance_date")).isoformat()
            if _utc(permit.get("issuance_date")) else None
        ),
        "permittee_license_number": (company or {}).get("gc_license_number"),
    }


async def _build_action(
    db,
    permit: dict,
    strategy: RenewalStrategy,
    effective_expiry: Optional[datetime],
    today: datetime,
    *,
    insurance_not_entered: bool,
) -> Dict[str, Any]:
    """Action payload for the UI. Strategy drives the kind; fee table
    drives the dollar amounts."""
    if strategy == "AWAITING_EXTENSION":
        return {
            "kind": "awaiting_extension",
            "deadline_days": None,
            "instructions": [
                "Auto-extension expected. Updated COI/license submitted "
                "to DOB Licensing Unit; extension fires end-of-day after "
                "BIS update.",
                "New permit expiration will appear in 1-2 business days "
                "(Socrata data lag).",
            ],
            "fee_cents": 0,
            "fee_split": None,
        }

    if insurance_not_entered:
        return {
            "kind": "enter_insurance",
            "deadline_days": None,
            "instructions": [
                "No GL/WC/DBL insurance dates on file in LeveLog.",
                "Enter dates in Settings → Insurance & License so renewal "
                "eligibility can be computed.",
            ],
            "fee_cents": 0,
            "fee_split": None,
        }

    days_until = (effective_expiry - today).days if effective_expiry else None

    if strategy in ("AUTO_EXTEND_DOB_NOW", "AUTO_EXTEND_BIS_31D"):
        return {
            "kind": "submit_coi_update" if days_until is not None and days_until <= 30 else "monitor",
            "deadline_days": days_until,
            "instructions": [
                "Submit updated COI/license to DOB Licensing Unit at least "
                "5 days before the limiting date. After that, manual permit "
                "renewal ($130 fee + DOB NOW filing) will be required.",
            ] if days_until is not None and days_until <= 30 else [
                "No action needed. Permit auto-extends when COI/license is renewed.",
            ],
            "fee_cents": 0,
            "fee_split": None,
        }

    # Manual tracks: fetch fee from the fee table
    fee_cents = None
    fee_split = None
    try:
        fee_info = await get_fee(
            db,
            work_type=(permit.get("work_type") or ""),
            today=today,
        )
        fee_cents = fee_info.get("fee_cents")
        fee_split = fee_info.get("split")
    except Exception:
        # Fee lookup failures shouldn't kill eligibility — they just mean
        # the UI shows "fee TBD" and the user falls back to checking DOB
        # NOW directly. Logged at the dispatcher boundary.
        pass

    if strategy == "MANUAL_90D_SHED":
        return {
            "kind": "shed_renewal",
            "deadline_days": days_until,
            "instructions": [
                "Generate PE/RA progress report.",
                "Upload progress report PDF.",
                "Submit PW2 (or DOB NOW equivalent) with renewed dates.",
                f"Pay ${(fee_cents or 0) / 100:.0f} fee.",
                "Verify PW2 Stakeholder responses are present.",
            ],
            "fee_cents": fee_cents,
            "fee_split": fee_split,
        }

    if strategy == "MANUAL_1YR_CEILING":
        return {
            "kind": "manual_renewal_dob_now",
            "deadline_days": days_until,
            "instructions": [
                "Permit hits 1-year ceiling — manual renewal required.",
                "Log into DOB NOW with the licensee's NYC.ID.",
                "Locate the permit and select 'Renew Work Permit'.",
                f"Pay ${(fee_cents or 0) / 100:.0f} fee.",
            ],
            "fee_cents": fee_cents,
            "fee_split": fee_split,
        }

    if strategy == "MANUAL_LAPSED":
        return {
            "kind": "manual_renewal_lapsed",
            "deadline_days": days_until,
            "instructions": [
                "Insurance/license lapsed. Update with carrier first.",
                "Once updated at DOB Licensing Unit, file manual renewal at DOB NOW.",
                f"Pay ${(fee_cents or 0) / 100:.0f} fee.",
            ],
            "fee_cents": fee_cents,
            "fee_split": fee_split,
        }

    return {"kind": "unknown", "fee_cents": None, "fee_split": None}
