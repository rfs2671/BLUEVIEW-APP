"""MR.14 (commit 2b) — signal_kind classifier.

Derives the v1-monitoring signal_kind from a dob_log doc's
record_type + status fields. The classifier output drives:
  • UI plain-English templates (lib/dob_signal_templates.py)
  • Notification routing (lib/dob_signal_notifications.py)
  • Activity feed filtering

Pure function. No Mongo, no I/O. Deterministic for a given input
shape. Each branch independently testable.

The full set of signal_kind values produced:

  permit:
    permit_issued, permit_expired, permit_revoked, permit_renewed
  job_status (DOB NOW filings):
    filing_approved, filing_disapproved, filing_withdrawn,
    filing_pending
  violation:
    violation_dob, violation_ecb, violation_open, violation_resolved
  swo (stop work order):
    stop_work_full, stop_work_partial
  complaint:
    complaint_dob, complaint_311
  inspection:
    inspection_scheduled, inspection_passed, inspection_failed,
    final_signoff
  cofo (Certificate of Occupancy):
    cofo_temporary, cofo_final
    (cofo_pending is a known kind but NOT produced here — the only
     dataset feeding record_type='cofo' publishes issued certificates
     only. See _classify_cofo.)
  facade_fisp / boiler / elevator (compliance filings):
    facade_fisp, boiler_inspection, elevator_inspection
  license_renewal_due (filing rep + GC license):
    license_renewal_due

Fallback: if no specific kind matches, returns the record_type
itself (same as commit 2a's placeholder behavior).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


# ── Permit ────────────────────────────────────────────────────────


def _classify_permit(log: dict) -> str:
    status = (log.get("current_status") or "").upper()
    if "EXPIRED" in status:
        return "permit_expired"
    if "REVOKED" in status:
        return "permit_revoked"
    if "RENEWED" in status:
        return "permit_renewed"
    if "ISSUED" in status or "ACTIVE" in status:
        return "permit_issued"
    # Unknown status → fall back to record_type so the UI still
    # renders SOMETHING. Templates have a generic permit fallback.
    return "permit"


# ── Job filings (DOB NOW) ─────────────────────────────────────────


def _classify_job_status(log: dict) -> str:
    status = (log.get("current_status") or "").upper()
    # ORDER MATTERS — check DISAPPROVED before APPROVED.
    # "DISAPPROVED" contains "APPROV" as a substring, so a naive
    # "APPROV" check first would mis-classify disapprovals as approvals.
    if "DISAPPROV" in status or "REJECT" in status:
        return "filing_disapproved"
    if "WITHDRAW" in status:
        return "filing_withdrawn"
    if "APPROV" in status:
        return "filing_approved"
    if "PENDING" in status or "REVIEW" in status:
        return "filing_pending"
    return "job_status"


# ── Violation ─────────────────────────────────────────────────────


_ECB_HINTS = ("ECB", "OATH", "ENVIRONMENTAL CONTROL")


def _classify_violation(log: dict) -> str:
    """ECB/OATH violations are civil-penalty hearings; DOB
    violations are inspector-issued infractions. Different audience
    actions, different templates."""
    status = (log.get("current_status") or "").upper()
    resolution = (log.get("resolution_state") or "").lower()
    violation_subtype = (log.get("violation_subtype") or "").upper()
    notice_type = (log.get("notice_type") or "").upper()
    description = (log.get("description") or "").upper()

    # Resolution-state takes precedence over status: a violation
    # certified/dismissed/paid is a resolved-violation regardless
    # of how the status text reads on the source dataset.
    if resolution in {"certified", "dismissed", "paid", "resolved"}:
        return "violation_resolved"

    is_ecb = (
        violation_subtype == "ECB"
        or any(h in notice_type for h in _ECB_HINTS)
        or any(h in description for h in _ECB_HINTS)
        or bool(log.get("ecb_violation_number"))
    )
    if is_ecb:
        return "violation_ecb"

    # Active DOB violation. "DOB" is the common case.
    return "violation_dob"


# ── Stop Work Order ───────────────────────────────────────────────


def _classify_swo(log: dict) -> str:
    """SWOs come from two paths:
      • Legacy text-match on violation records (record_type='swo'
        was stamped at scrape time when description contained
        'FULL STOP WORK' or similar).
      • New 3usq-5cid Stop Work Orders dataset (commit 2b).
    Either way, we discriminate full vs. partial via violation_subtype
    or description text.
    """
    subtype = (log.get("violation_subtype") or "").upper()
    description = (log.get("description") or "").upper()
    if subtype == "SWO_PARTIAL" or "PARTIAL" in description:
        return "stop_work_partial"
    return "stop_work_full"


# ── Complaint ─────────────────────────────────────────────────────


def _classify_complaint(log: dict) -> str:
    """DOB-routed complaints (eabe-havv) vs. general 311 (erm2-nwe9)."""
    source = (log.get("source") or log.get("complaint_source") or "").lower()
    if source == "311":
        return "complaint_311"
    return "complaint_dob"


# ── Inspection ────────────────────────────────────────────────────


_FINAL_INSPECTION_MARKERS = ("FINAL", "SIGN OFF", "SIGN-OFF", "SIGNOFF")


def _classify_inspection(log: dict) -> str:
    """An inspection is one of:
      • inspection_scheduled — date is in the future, no result yet
      • inspection_passed    — disposition shows pass / approved
      • inspection_failed    — disposition shows fail / rejected
      • final_signoff        — type contains 'Final' or 'Sign Off'
                               regardless of pass/fail
    Final signoff outranks pass/fail because it's the milestone
    the GC actually cares about.
    """
    inspection_type = (log.get("inspection_type") or "").upper()
    if any(m in inspection_type for m in _FINAL_INSPECTION_MARKERS):
        return "final_signoff"

    status = (log.get("current_status") or "").upper()
    if "PASS" in status or "APPROVED" in status:
        return "inspection_passed"
    if "FAIL" in status or "REJECT" in status or "DISAPPROV" in status:
        return "inspection_failed"

    # If we have a future inspection_date and no disposition yet,
    # it's scheduled. The dataset stores inspection_date for both
    # past + future inspections; we infer "scheduled" by date >= today.
    insp_date = log.get("inspection_date")
    if insp_date:
        try:
            d = (
                datetime.fromisoformat(insp_date)
                if isinstance(insp_date, str)
                else insp_date
            )
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= datetime.now(timezone.utc):
                return "inspection_scheduled"
        except (ValueError, TypeError):
            pass

    # Default: kind unknown; let the template fall back to a generic
    # "inspection update" rendering.
    return "inspection"


# ── Certificate of Occupancy ──────────────────────────────────────


def _classify_cofo(log: dict) -> str:
    """A CofO renewal is not a completion.

    Classified from `cofo_type` — which the ingest extractor fills from
    the dataset's `c_of_o_filing_type` (server.py `_extract_cofo_fields`)
    — and NEVER from `current_status`.

    WHY NOT STATUS. On the live dataset (pkdm-hqz6, 81,264 rows verified
    2026-09-02) `c_of_o_status` is the CONSTANT string 'CO Issued'. Every
    row. The ingest path uppercases it to 'CO ISSUED', so the old first
    branch here — `"ISSUED" in status` — matched all 81,264 and labelled
    every certificate `cofo_final`, i.e. "the project is officially
    complete". 46,842 of those are renewals of a temporary CO, which is
    the opposite of complete. `cofo_temporary` and `cofo_pending` were
    unreachable. Nobody noticed because the CofO query answered HTTP 400
    on every call from the day the feature shipped until 7c4f983, so no
    cofo row was ever ingested to be misclassified.

    THE LIVE FILING TYPES, and their counts:
        Renewal Without Change  46,842  → cofo_temporary
        Final                   18,922  → cofo_final
        Initial                  8,869  → cofo_temporary
        Renewal With Change      6,607  → cofo_temporary
        (column absent)             24  → cofo  (see below)

    WHY THOSE THREE ARE "TEMPORARY". The dataset has no column that says
    "temporary" and the string "TCO" appears nowhere in it, so this is
    read off the lifecycle rather than off a label:
      • BIN 2092338 in c_of_o_sequence order is
        `Initial > Renewal Without Change > Final`. A certificate that is
        renewed and then superseded by one marked Final was not final.
      • BIN 3335884 carries 64 rows, all renewals, 2021-04 → 2026-08 at a
        30-90 day cadence, no Final. That is the TCO renewal treadmill; a
        final CO is not renewed 64 times.

    ORDER MATTERS, and the direction of the fail-safe is deliberate:
    non-final is checked FIRST. If DOB ever ships a filing type naming
    both (a "Renewal — Final"), under-claiming completion is the harmless
    error and over-claiming it is the one that just cost us 46,842 rows.

    THE FALLBACK IS REACHABLE, not decoration: 24 live rows have no
    `c_of_o_filing_type` at all. They are ordinary issued certificates
    with real numbers and dates (e.g. BIN 4220272, '4220272-0000007'),
    so they must not be dropped — but nothing in them says final, so we
    return the generic `cofo` and claim neither way.

    NO `cofo_pending` BRANCH. There cannot be one. pkdm-hqz6 publishes
    only certificates that have been ISSUED — `c_of_o_status` has exactly
    one distinct value across the whole dataset — so a "filed but not yet
    issued" row does not exist here to classify. The old branch tested
    status text that no row can carry. The kind is kept in
    KNOWN_SIGNAL_KINDS (it has a template and a notification policy, and
    a different dataset could legitimately feed it), but this classifier
    can no longer pretend to produce it.
    """
    filing_type = (log.get("cofo_type") or "").upper().strip()

    # Temporary: the initial TCO and every renewal of it.
    if filing_type.startswith("RENEWAL") or filing_type == "INITIAL":
        return "cofo_temporary"

    # The one filing type that means the project is done.
    if filing_type == "FINAL":
        return "cofo_final"

    # Absent or unrecognised filing type — a real certificate whose
    # finality the dataset does not state. Say nothing rather than guess.
    return "cofo"


# ── Compliance filings ────────────────────────────────────────────
# These are simpler — record_type alone is enough since each
# dataset is single-purpose. Status drives the template's tone
# (overdue / due-soon / current).


def _classify_compliance(log: dict, kind: str) -> str:
    """For compliance filings (FISP / Boiler / Elevator), the
    signal_kind is the kind itself; status nuance is handled by
    the template. Returns one of:
      • facade_fisp
      • boiler_inspection
      • elevator_inspection
    """
    return kind


# ── License renewals ──────────────────────────────────────────────


def _classify_license_renewal(log: dict) -> str:
    return "license_renewal_due"


# ── Top-level dispatcher ──────────────────────────────────────────


def classify_signal_kind(log: dict) -> str:
    """Top-level dispatch on record_type. Returns the placeholder
    record_type when no specific signal_kind applies (preserves
    commit 2a's behavior for unknown shapes).

    Caller (insertion path in server.py) sets dob_log["signal_kind"]
    to whatever this returns. Tests pin every branch.
    """
    rt = (log.get("record_type") or "").lower().strip()

    if rt == "permit":
        return _classify_permit(log)
    if rt == "job_status":
        return _classify_job_status(log)
    if rt == "violation":
        return _classify_violation(log)
    if rt == "swo":
        return _classify_swo(log)
    if rt == "complaint":
        return _classify_complaint(log)
    if rt == "inspection":
        return _classify_inspection(log)
    if rt == "cofo":
        return _classify_cofo(log)
    if rt == "facade_fisp":
        return _classify_compliance(log, "facade_fisp")
    if rt == "boiler":
        return _classify_compliance(log, "boiler_inspection")
    if rt == "elevator":
        return _classify_compliance(log, "elevator_inspection")
    if rt == "license_renewal":
        return _classify_license_renewal(log)

    # Unknown record_type → mirror it as the signal_kind. Templates
    # have a generic fallback for unknown kinds.
    return rt or "unknown"


# Set of all known signal_kind values. Used by tests for coverage
# checks and by the templates module to enforce one-template-per-kind.
KNOWN_SIGNAL_KINDS = frozenset({
    # permit
    "permit_issued", "permit_expired", "permit_revoked", "permit_renewed",
    "permit",  # fallback
    # job_status
    "filing_approved", "filing_disapproved", "filing_withdrawn",
    "filing_pending", "job_status",  # fallback
    # violation
    "violation_dob", "violation_ecb", "violation_open", "violation_resolved",
    # swo
    "stop_work_full", "stop_work_partial",
    # complaint
    "complaint_dob", "complaint_311",
    # inspection
    "inspection_scheduled", "inspection_passed", "inspection_failed",
    "final_signoff", "inspection",  # fallback
    # cofo
    "cofo_temporary", "cofo_final", "cofo_pending", "cofo",  # fallback
    # compliance
    "facade_fisp", "boiler_inspection", "elevator_inspection",
    # license
    "license_renewal_due",
})
