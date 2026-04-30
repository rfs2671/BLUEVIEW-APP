"""MR.4 — PW2 field mapper service.

Deterministic backend service that takes a permit_renewal doc and
returns a JSON map of field-name → typed value pairs the local
Playwright agent will type into DOB NOW's PW2 form. NOT a PDF
generator — JSON only. The agent uses this map to drive form-fill,
then submits via DOB NOW under the GC's session.

Pure: no Mongo writes, no external API calls, no dispatcher calls.
Same shape as MR.3's filing_readiness — read four refs, transform,
return a Pydantic model.

Architectural notes (revisit before MR.5+ ships):

1. PW2 field NAMES below are working keys, not authoritative DOB
   form field IDs. The local agent in MR.5 will need to map these
   keys to actual DOM selectors / labels on DOB NOW. A name-
   translation layer at the agent boundary is the natural place to
   handle that — MR.4's output is intentionally agent-agnostic.

2. `Pw2FieldMap.permit_class` carries the FORM-PATH discriminator
   ("DOB_NOW" / "BIS" / "standard"), which is distinct from
   dob_log's `permit_class` taxonomy ("standard" / "sidewalk_shed"
   / "fence" / "bldrs_pavement" — the work-permit category). The
   field name overlap is per the MR.4 spec; the output value is
   derived from `dob_log.filing_system`. Both axes are useful but
   only the form-path one is exposed in this output. If MR.5 needs
   the work-permit-category discriminator separately, it can read
   dob_log.permit_class directly via the renewal_id.

3. The full work-permit number with the -PL/-SP/-FB suffix
   (e.g. "B00736930-S1-PL") is NOT a stored field on dob_logs.
   `work_permit_number` is therefore marked unmappable when only
   `job_number` is available. A future backend commit could
   construct it from job_number + a permit_type letter-code mapping,
   but that mapping needs DOB-authoritative source. For MR.4, the
   agent in MR.5 can query DOB NOW for the full identifier
   separately, or operate against `job_number` + `work_type` and
   let DOB NOW's form route by those.

4. ACTIONABLE_ACTION_KINDS for which MR.4 produces a complete
   field map: {"manual_renewal_dob_now"}. Other kinds
   (manual_renewal_lapsed, shed_renewal) get attachments_required
   tweaks per the MR.4 spec but the rest of the field map is the
   same — they share most data with manual_renewal_dob_now.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ── Constants ──────────────────────────────────────────────────────

# action.kind → human-readable renewal_type label that the PW2 form
# expects in its renewal-type select.
RENEWAL_TYPE_LABELS: Dict[str, str] = {
    "manual_renewal_dob_now":  "1-Year Ceiling Renewal",
    "manual_renewal_lapsed":   "Lapsed Permit Renewal",
    "shed_renewal":            "Sidewalk Shed Renewal",
}

# Always-required attachment regardless of action.kind.
ALWAYS_REQUIRED_ATTACHMENTS: List[str] = [
    "Current Certificate of Insurance (GL/WC/DBL)",
]

# Per-action.kind additional attachments.
ATTACHMENT_RULES: Dict[str, List[str]] = {
    "manual_renewal_dob_now": [],  # renewal of approved work — no PE/RA seal needed
    "manual_renewal_lapsed":  ["Reason for lapse statement"],
    "shed_renewal":           ["PE/RA-stamped progress report"],
}

# Constant fee — manual renewals at the 1-year ceiling are $130 per
# 1 RCNY § 101-03 (DOB Schedule of Fees). See
# frontend/src/constants/dobRules.js for the canonical citation.
RENEWAL_FEE_AMOUNT_USD = "130.00"


# ── Models ─────────────────────────────────────────────────────────

class FieldValue(BaseModel):
    """A single PW2 field's typed value.

    value: literal string the agent types into the form.
    field_type: hint for the agent's input handling. One of:
        text | date | select | checkbox | signature_required
    source: provenance of the value. One of:
        permit_renewal | dob_log | company | filing_rep | constant | computed
    """
    value: str
    field_type: str
    source: str


class Pw2FieldMap(BaseModel):
    permit_renewal_id: str
    # Form-path discriminator — see architectural note 2 above.
    permit_class: str
    fields: Dict[str, FieldValue]
    attachments_required: List[str]
    notes: List[str]
    unmappable_fields: List[str]


# ── ID helper (mirrors filing_readiness.py) ────────────────────────

def _to_oid(s):
    from bson import ObjectId
    if isinstance(s, ObjectId):
        return s
    try:
        return ObjectId(str(s))
    except Exception:
        return s


# ── Helper: pick the acting filing_rep ─────────────────────────────

def _pick_acting_rep(company: Optional[dict]) -> Optional[dict]:
    """Resolves which filing_rep MR.4 maps applicant_* fields from.
    Primary if exactly one is_primary; first entry as fallback (with
    a note returned by the caller); None if no reps."""
    reps = (company or {}).get("filing_reps") or []
    if not reps:
        return None
    primaries = [r for r in reps if r.get("is_primary")]
    if len(primaries) == 1:
        return primaries[0]
    if len(primaries) > 1:
        # Data integrity issue (filing_readiness flags this with
        # status=fail); pick the first deterministically so the
        # mapper still produces something.
        return primaries[0]
    return reps[0]


# ── Field-builder helpers ──────────────────────────────────────────

def _add_or_unmappable(
    fields: Dict[str, FieldValue],
    unmappable: List[str],
    *,
    name: str,
    value: Optional[Any],
    field_type: str,
    source: str,
    reason_when_missing: str,
) -> None:
    """If value is non-empty after str() coercion, push as a
    FieldValue. Otherwise record an unmappable-fields entry with
    the given reason."""
    coerced = "" if value is None else str(value).strip()
    if coerced:
        fields[name] = FieldValue(value=coerced, field_type=field_type, source=source)
    else:
        unmappable.append(f"{name}: {reason_when_missing}")


def _resolve_form_path(filing_system: Optional[str]) -> str:
    """Map dob_log.filing_system to the Pw2FieldMap.permit_class
    discriminator. See architectural note 2."""
    if not filing_system:
        return "standard"
    fs = filing_system.strip().upper()
    if fs == "DOB_NOW":
        return "DOB_NOW"
    if fs == "BIS":
        return "BIS"
    return "standard"


# ── Top-level orchestrator ─────────────────────────────────────────

async def map_pw2_fields(
    db,
    permit_renewal_id: str,
) -> Pw2FieldMap:
    """Build the PW2 field map for the given renewal. Pure: four
    read queries (renewal, dob_log, project, company), no writes,
    no external IO."""
    fields: Dict[str, FieldValue] = {}
    notes: List[str] = []
    unmappable: List[str] = []

    renewal = await db.permit_renewals.find_one(
        {"_id": _to_oid(permit_renewal_id)}
    )
    if not renewal:
        # Caller (the endpoint) should 404 before reaching us; this
        # is defensive. Return a minimal map so the function never
        # raises on a missing input.
        return Pw2FieldMap(
            permit_renewal_id=permit_renewal_id,
            permit_class="standard",
            fields={},
            attachments_required=[],
            notes=["Renewal record not found."],
            unmappable_fields=["all_fields: renewal record not found"],
        )

    permit = await db.dob_logs.find_one({
        "_id": _to_oid(renewal.get("permit_dob_log_id")),
    }) if renewal.get("permit_dob_log_id") else None
    project = await db.projects.find_one({
        "_id": _to_oid(renewal.get("project_id")),
    }) if renewal.get("project_id") else None
    company = await db.companies.find_one({
        "_id": _to_oid(renewal.get("company_id")),
    }) if renewal.get("company_id") else None

    permit_class = _resolve_form_path((permit or {}).get("filing_system"))

    # ── Job / permit identification ────────────────────────────────
    _add_or_unmappable(
        fields, unmappable,
        name="job_filing_number",
        value=(permit or {}).get("job_number") or renewal.get("job_number"),
        field_type="text",
        source="dob_log",
        reason_when_missing="dob_log missing or job_number not set",
    )

    # work_permit_number is NOT a stored field — see architectural
    # note 3. We don't have the canonical -PL/-SP/-FB suffix without
    # an authoritative letter-code mapping. Surface as unmappable so
    # MR.5+ can decide the lookup strategy.
    unmappable.append(
        "work_permit_number: not stored on dob_logs; canonical -PL/-SP/-FB "
        "suffix requires a permit_type letter-code mapping that's not "
        "yet sourced from DOB. Agent should query DOB NOW for the full "
        "identifier or use job_number + work_type to route."
    )

    _add_or_unmappable(
        fields, unmappable,
        name="work_type",
        value=(permit or {}).get("work_type"),
        field_type="select",
        source="dob_log",
        reason_when_missing="dob_log missing or work_type not set",
    )

    _add_or_unmappable(
        fields, unmappable,
        name="permit_subtype",
        value=(permit or {}).get("permit_subtype"),
        field_type="select",
        source="dob_log",
        reason_when_missing="dob_log permit_subtype not set",
    )

    # ── Location / property ────────────────────────────────────────
    _add_or_unmappable(
        fields, unmappable,
        name="bin",
        value=(project or {}).get("nyc_bin") or (permit or {}).get("nyc_bin"),
        field_type="text",
        source="permit_renewal",
        reason_when_missing="project.nyc_bin and dob_log.nyc_bin both missing",
    )
    _add_or_unmappable(
        fields, unmappable,
        name="bbl",
        value=(project or {}).get("bbl"),
        field_type="text",
        source="permit_renewal",
        reason_when_missing="project record missing BBL",
    )
    _add_or_unmappable(
        fields, unmappable,
        name="project_address",
        value=(project or {}).get("address") or renewal.get("project_address"),
        field_type="text",
        source="permit_renewal",
        reason_when_missing="project record missing address",
    )

    # ── Applicant (filing_rep) ─────────────────────────────────────
    rep = _pick_acting_rep(company)
    if not rep:
        # No filing_reps configured at all. Fail every applicant_*
        # field with a single root-cause reason — easier for the
        # operator to action than 4 redundant per-field messages.
        for name in (
            "applicant_name",
            "applicant_license_number",
            "applicant_license_class",
            "applicant_email",
        ):
            unmappable.append(
                f"{name}: no filing representatives configured for company"
            )
    else:
        # If there's no is_primary set and we fell back to first
        # rep, the operator should know.
        reps_list = (company or {}).get("filing_reps") or []
        primaries = [r for r in reps_list if r.get("is_primary")]
        if len(primaries) == 0 and reps_list:
            notes.append(
                "No primary filing representative set; defaulting to "
                f"first entry ({rep.get('name')}). Set a primary in the "
                "owner portal to control filing routing explicitly."
            )
        elif len(primaries) > 1:
            notes.append(
                f"Data integrity issue: {len(primaries)} filing "
                "representatives marked is_primary=true. Defaulted to the "
                "first match. Resolve in the owner portal."
            )

        _add_or_unmappable(
            fields, unmappable,
            name="applicant_name",
            value=rep.get("name"),
            field_type="text",
            source="filing_rep",
            reason_when_missing="primary filing rep has no name",
        )
        _add_or_unmappable(
            fields, unmappable,
            name="applicant_license_number",
            value=rep.get("license_number"),
            field_type="text",
            source="filing_rep",
            reason_when_missing="primary filing rep has no license_number",
        )
        _add_or_unmappable(
            fields, unmappable,
            name="applicant_license_class",
            value=rep.get("license_class"),
            field_type="select",
            source="filing_rep",
            reason_when_missing="primary filing rep has no license_class",
        )
        _add_or_unmappable(
            fields, unmappable,
            name="applicant_email",
            value=rep.get("email"),
            field_type="text",
            source="filing_rep",
            reason_when_missing="primary filing rep has no email",
        )

    # ── Company (the GC business) ──────────────────────────────────
    _add_or_unmappable(
        fields, unmappable,
        name="applicant_business_name",
        value=(company or {}).get("name") or (company or {}).get("gc_business_name"),
        field_type="text",
        source="company",
        reason_when_missing="company record missing name",
    )
    _add_or_unmappable(
        fields, unmappable,
        name="gc_license_number",
        value=(company or {}).get("gc_license_number"),
        field_type="text",
        source="company",
        reason_when_missing="company has no gc_license_number on file",
    )

    # ── Permit dates ───────────────────────────────────────────────
    _add_or_unmappable(
        fields, unmappable,
        name="current_expiration_date",
        value=renewal.get("current_expiration"),
        field_type="date",
        source="permit_renewal",
        reason_when_missing="renewal.current_expiration not set",
    )
    _add_or_unmappable(
        fields, unmappable,
        name="issuance_date",
        value=renewal.get("issuance_date"),
        field_type="date",
        source="permit_renewal",
        reason_when_missing=(
            "renewal.issuance_date not set — re-run "
            "scripts/backfill_renewal_v2_keys.py post-MR.1.6 "
            "(commit 50bf481) to populate"
        ),
    )
    _add_or_unmappable(
        fields, unmappable,
        name="effective_expiry",
        value=renewal.get("effective_expiry"),
        field_type="date",
        source="permit_renewal",
        reason_when_missing=(
            "renewal.effective_expiry not set — re-run backfill "
            "or re-prepare to populate v2 keys"
        ),
    )

    # ── Renewal-type (action.kind-driven) ──────────────────────────
    action = renewal.get("action") or {}
    action_kind = action.get("kind") or ""
    renewal_type_label = RENEWAL_TYPE_LABELS.get(action_kind)
    if renewal_type_label:
        fields["renewal_type"] = FieldValue(
            value=renewal_type_label,
            field_type="select",
            source="computed",
        )
    else:
        unmappable.append(
            f"renewal_type: action.kind '{action_kind or '(missing)'}' has no "
            f"renewal_type label mapping. Known kinds: "
            f"{sorted(RENEWAL_TYPE_LABELS.keys())}."
        )

    # ── Constant: fee ──────────────────────────────────────────────
    fields["renewal_fee_amount"] = FieldValue(
        value=RENEWAL_FEE_AMOUNT_USD,
        field_type="text",
        source="constant",
    )

    # ── Attachments ────────────────────────────────────────────────
    attachments_required = list(ALWAYS_REQUIRED_ATTACHMENTS)
    attachments_required.extend(ATTACHMENT_RULES.get(action_kind, []))

    # ── Notes (operator/agent hints) ───────────────────────────────
    notes.append(
        "PW2 fee paid directly to DOB at time of submission "
        "($130 via DOB NOW eFiling)."
    )
    notes.append(
        "Filing must be submitted under the licensed individual's "
        "NYC.ID, not LeveLog credentials."
    )
    if action_kind == "shed_renewal":
        notes.append(
            "Confirm PE/RA progress report is current within 30 days "
            "of filing."
        )

    # Form-path note when not DOB_NOW.
    if permit_class == "BIS":
        notes.append(
            "BIS legacy filing path detected (filing_system=BIS). "
            "MR.4's field map is currently optimized for the DOB_NOW "
            "form layout; BIS paper-form path requires additional "
            "fields not yet mapped here. Operator should consult an "
            "expediter for BIS renewals until MR.x adds full BIS "
            "support."
        )
    elif permit_class == "standard":
        notes.append(
            "Form-path discriminator unresolved (filing_system not set). "
            "Defaulting to DOB_NOW behavior. Verify before submission."
        )

    return Pw2FieldMap(
        permit_renewal_id=permit_renewal_id,
        permit_class=permit_class,
        fields=fields,
        attachments_required=attachments_required,
        notes=notes,
        unmappable_fields=unmappable,
    )
