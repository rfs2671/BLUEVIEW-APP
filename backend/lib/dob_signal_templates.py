"""MR.14 (commit 2b) — plain-English templates for DOB signals.

One renderer per signal_kind. Output shape:
  {
    "title":        str,  # one line, includes emoji prefix
    "body":         str,  # 2-3 sentences, no DOB jargon
    "severity":     str,  # info / warning / critical
    "action_text":  str,  # 1 sentence concrete next step
  }

Audience: GC / PM / Site Manager who has never used DOB. Where
DOB jargon is unavoidable (PAA, FISP, CofO, TCO), inline parenthetical
explanation in plain English on first use.

The dispatcher render_signal() takes a signal_kind string + the
dob_log dict and routes to the per-kind renderer. Unknown kinds get
a generic fallback so the activity feed never crashes on a new
record_type the templates haven't been authored for yet.

Tests pin one canonical output per template — copy edits show up
in PR diffs as deliberate changes, not silent drift.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ── Severity constants ────────────────────────────────────────────


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


# ── Helpers ───────────────────────────────────────────────────────


def _date_short(value: Any) -> str:
    """Format a date-or-string as 'Mon May 8' (or empty if unparseable)."""
    if not value:
        return ""
    s = str(value)
    # Try ISO first.
    from datetime import datetime, timezone
    for fmt_in in ("%Y-%m-%dT%H:%M:%S.%f%z",
                   "%Y-%m-%dT%H:%M:%S%z",
                   "%Y-%m-%dT%H:%M:%S",
                   "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.split(".")[0] if "." in s else s.split("+")[0], fmt_in.replace(".%f", "").replace("%z", ""))
            return d.strftime("%a %b %-d") if hasattr(d, "strftime") else s[:10]
        except (ValueError, AttributeError):
            continue
    # Fallback.
    return s[:10]


def _safe_date_only(value: Any) -> str:
    """Return YYYY-MM-DD slice or empty string."""
    if not value:
        return ""
    s = str(value)
    return s[:10]


def _get(log: dict, *keys: str, default: str = "") -> str:
    """First non-empty value among the given keys."""
    for k in keys:
        v = log.get(k)
        if v not in (None, "", []):
            return str(v).strip()
    return default


# ── Permit templates ──────────────────────────────────────────────


def _render_permit_issued(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    work_type = _get(log, "work_type", "permit_type", default="this work")
    return {
        "title": f"✅ Permit issued — {work_type} (Job {job})",
        "body": (
            f"DOB issued the work permit for {work_type} on this project. "
            f"Work can begin once the contractor confirms posting and site readiness."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Confirm the permit is posted at the jobsite and the work-permit "
            "number is logged in your project records."
        ),
    }


def _render_permit_expired(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    work_type = _get(log, "work_type", "permit_type", default="this work")
    exp = _safe_date_only(log.get("expiration_date"))
    return {
        "title": f"⚠️ Permit expired — {work_type} (Job {job})",
        "body": (
            f"The work permit for {work_type} expired"
            + (f" on {exp}." if exp else ".")
            + " Continuing work without an active permit risks a "
              "Stop Work Order and ECB violations."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "File a permit renewal in DOB NOW today. If work continued "
            "past the expiration date, document it in your daily log."
        ),
    }


def _render_permit_revoked(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    work_type = _get(log, "work_type", "permit_type", default="this work")
    return {
        "title": f"🚫 Permit revoked — {work_type} (Job {job})",
        "body": (
            f"DOB revoked the work permit for {work_type}. Work covered "
            f"by this permit must stop immediately. A revocation usually "
            f"follows a serious safety finding or a paperwork issue DOB "
            f"flagged on review."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Stop work covered by this permit. Contact your expediter or "
            "DOB borough office to find out the revocation reason."
        ),
    }


def _render_permit_renewed(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    work_type = _get(log, "work_type", "permit_type", default="this work")
    new_exp = _safe_date_only(log.get("expiration_date"))
    return {
        "title": f"🔁 Permit renewed — {work_type} (Job {job})",
        "body": (
            f"DOB confirmed the renewal of the work permit for {work_type}. "
            f"New expiration date: {new_exp or 'TBD'}."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Post the renewed permit at the jobsite and update your project "
            "records with the new expiration date."
        ),
    }


# ── Job filing templates ──────────────────────────────────────────


def _render_filing_approved(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    return {
        "title": f"✅ Job filing approved (Job {job})",
        "body": (
            f"DOB approved the job filing. The next step is the work permit "
            f"itself — the GC's expediter requests it on DOB NOW."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Coordinate with your expediter to pull the work permit so "
            "trades can start work."
        ),
    }


def _render_filing_disapproved(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    return {
        "title": f"❌ Job filing disapproved (Job {job})",
        "body": (
            f"DOB disapproved the job filing. Reasons are usually listed in "
            f"the filing's objections section on DOB NOW. Disapproval blocks "
            f"the work permit from being pulled."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Have your expediter pull the objection sheet from DOB NOW and "
            "address each objection before re-submitting."
        ),
    }


def _render_filing_withdrawn(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    return {
        "title": f"🗂️ Job filing withdrawn (Job {job})",
        "body": (
            f"This job filing was withdrawn — usually because the project "
            f"changed scope or the team chose to refile. No work permit "
            f"can be issued under this filing."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Confirm with your expediter whether a replacement filing is "
            "in progress and update your project records."
        ),
    }


def _render_filing_pending(log: dict) -> Dict[str, Any]:
    job = _get(log, "job_filing_number", "job_number", default="?")
    return {
        "title": f"⏳ Job filing under DOB review (Job {job})",
        "body": (
            f"The filing is pending DOB plan-examiner review. Typical review "
            f"time is 2–6 weeks; expedited review is sometimes available."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "No action required — DOB will issue an approval or objection "
            "sheet when review is complete."
        ),
    }


# ── Violation templates ───────────────────────────────────────────


def _render_violation_dob(log: dict) -> Dict[str, Any]:
    vnum = _get(log, "violation_number", default="?")
    vtype = _get(log, "violation_type", default="DOB violation")
    return {
        "title": f"⚠️ DOB violation issued — {vtype} (#{vnum})",
        "body": (
            f"A DOB inspector issued a violation against this site. "
            f"DOB violations carry potential civil penalties and must be "
            f"certified-corrected to avoid escalation to ECB hearings."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Cure the violation per the notice's instructions, then file "
            "the AEU2 (certificate of correction) on DOB NOW."
        ),
    }


def _render_violation_ecb(log: dict) -> Dict[str, Any]:
    vnum = _get(log, "violation_number", default="?")
    hearing = _safe_date_only(log.get("disposition_date"))
    penalty = _get(log, "penalty_amount", default="")
    extra = f" Penalty: ${penalty}." if penalty else ""
    return {
        "title": f"⚖️ ECB/OATH violation (#{vnum})",
        "body": (
            f"This is an ECB/OATH violation — a civil-penalty matter that "
            f"goes to a hearing at the Office of Administrative Trials "
            f"and Hearings (OATH). Hearing date: {hearing or 'TBD'}.{extra}"
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Engage your attorney or expediter to attend the hearing or "
            "file a defense before the date."
        ),
    }


def _render_violation_resolved(log: dict) -> Dict[str, Any]:
    vnum = _get(log, "violation_number", default="?")
    return {
        "title": f"✓ Violation resolved (#{vnum})",
        "body": (
            f"This violation has been certified-corrected, dismissed, or "
            f"paid. No further action required, but keep the resolution "
            f"paperwork in case of future audit."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "File the resolution paperwork in your project compliance "
            "folder for the audit trail."
        ),
    }


# ── Stop Work Order templates ─────────────────────────────────────


def _render_stop_work_full(log: dict) -> Dict[str, Any]:
    issue_date = _safe_date_only(log.get("violation_date"))
    return {
        "title": f"🛑 Full Stop Work Order issued",
        "body": (
            f"DOB issued a Full Stop Work Order against this site"
            + (f" on {issue_date}" if issue_date else "")
            + ". ALL work must stop immediately. Continuing work past an "
              "SWO compounds penalties and exposes the GC to criminal liability."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Stop ALL work site-wide. Contact DOB borough office and your "
            "attorney to plan the rescission filing."
        ),
    }


def _render_stop_work_partial(log: dict) -> Dict[str, Any]:
    issue_date = _safe_date_only(log.get("violation_date"))
    return {
        "title": f"⛔ Partial Stop Work Order issued",
        "body": (
            f"DOB issued a Partial Stop Work Order"
            + (f" on {issue_date}" if issue_date else "")
            + ". Specific work scopes covered by the order must stop; "
              "other work can continue. Read the SWO notice carefully — "
              "operating outside the partial scope counts as full SWO violation."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Identify which trades/scopes are covered by the partial SWO "
            "and halt only those. Document the boundary in your daily log."
        ),
    }


# ── Complaint templates ───────────────────────────────────────────


def _render_complaint_dob(log: dict) -> Dict[str, Any]:
    cnum = _get(log, "complaint_number", default="?")
    ctype = _get(log, "complaint_type", "complaint_category", default="this complaint")
    return {
        "title": f"📞 DOB complaint received — {ctype}",
        "body": (
            f"DOB received a complaint (#{cnum}) about this site. DOB "
            f"complaints typically trigger an inspector visit within "
            f"24–48 hours for high-priority categories."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Brief the site team. Make sure the area named in the "
            "complaint is documented (photos, daily log) before the "
            "inspector arrives."
        ),
    }


def _render_complaint_311(log: dict) -> Dict[str, Any]:
    ctype = _get(log, "complaint_type", default="complaint")
    return {
        "title": f"📞 311 complaint — {ctype}",
        "body": (
            f"A 311 caller reported this complaint about the site. "
            f"311 complaints get routed to the relevant agency (DOB, FDNY, "
            f"NYPD) — not all reach DOB, but flagged ones may trigger "
            f"a follow-up."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Note the complaint in your daily log. Watch for an inspector "
            "follow-up over the next 1–3 days."
        ),
    }


# ── Inspection templates ──────────────────────────────────────────


def _render_inspection_scheduled(log: dict) -> Dict[str, Any]:
    insp_type = _get(log, "inspection_type", default="DOB inspection")
    when = _safe_date_only(log.get("inspection_date"))
    return {
        "title": f"🔍 {insp_type} scheduled" + (f" — {when}" if when else ""),
        "body": (
            f"A DOB inspector is scheduled to visit on {when or 'an upcoming day'}. "
            f"Inspections typically happen during business hours."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Confirm site is accessible, the relevant trade contractor is "
            "on-site, and any required forms (P-1, etc.) are signed and ready."
        ),
    }


def _render_inspection_passed(log: dict) -> Dict[str, Any]:
    insp_type = _get(log, "inspection_type", default="DOB inspection")
    return {
        "title": f"✅ {insp_type} passed",
        "body": (
            f"DOB inspector signed off on this inspection. Work in this "
            f"scope can proceed to the next phase."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Move to the next phase per your construction sequence."
        ),
    }


def _render_inspection_failed(log: dict) -> Dict[str, Any]:
    insp_type = _get(log, "inspection_type", default="DOB inspection")
    reason = _get(log, "inspection_result_description", default="")
    return {
        "title": f"❌ {insp_type} failed",
        "body": (
            f"DOB inspector failed this inspection."
            + (f" Reason noted: {reason}." if reason else "")
            + " Re-inspection is required before this phase can proceed; "
              "fail-on-record may also trigger DOB follow-up if not cured."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Address the failure reason, then schedule a re-inspection "
            "via DOB NOW."
        ),
    }


def _render_final_signoff(log: dict) -> Dict[str, Any]:
    insp_type = _get(log, "inspection_type", default="Final inspection")
    status = (log.get("current_status") or "").upper()
    passed = "PASS" in status or "APPROV" in status
    if passed:
        return {
            "title": f"🏁 {insp_type} — SIGNED OFF",
            "body": (
                f"DOB final-signed-off this scope. This is a major "
                f"milestone — the work is now considered complete by DOB."
            ),
            "severity": SEVERITY_INFO,
            "action_text": (
                "Confirm the sign-off appears on the DOB record and file "
                "the documentation with project closeout records."
            ),
        }
    return {
        "title": f"❌ {insp_type} — sign-off denied",
        "body": (
            f"DOB inspector did not sign off the final inspection. Cure "
            f"the deficiencies identified before re-scheduling, or the "
            f"work cannot be considered complete."
        ),
        "severity": SEVERITY_CRITICAL,
        "action_text": (
            "Address the deficiencies and re-schedule the final via DOB NOW."
        ),
    }


# ── Certificate of Occupancy templates ────────────────────────────


def _render_cofo_temporary(log: dict) -> Dict[str, Any]:
    return {
        "title": "🏛️ Temporary CofO issued",
        "body": (
            "DOB issued a Temporary Certificate of Occupancy (TCO — partial "
            "occupancy granted while remaining work continues). TCOs have "
            "an expiration date and must be renewed or upgraded to a final "
            "CofO."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Track the TCO expiration date and plan for final CofO filing "
            "before it lapses."
        ),
    }


def _render_cofo_final(log: dict) -> Dict[str, Any]:
    return {
        "title": "🏛️ Final CofO issued",
        "body": (
            "DOB issued the final Certificate of Occupancy — the project "
            "is officially complete and authorized for occupancy. This is "
            "the final compliance milestone."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Distribute the CofO to ownership, update LeveLog, and close "
            "out the project records."
        ),
    }


def _render_cofo_pending(log: dict) -> Dict[str, Any]:
    return {
        "title": "⏳ CofO under review",
        "body": (
            "The Certificate of Occupancy filing is in DOB review. Typical "
            "review time is 4–8 weeks depending on borough and complexity."
        ),
        "severity": SEVERITY_INFO,
        "action_text": (
            "Watch for objection notices from DOB; address any findings "
            "promptly to keep the review moving."
        ),
    }


# ── Compliance filings templates ──────────────────────────────────


def _render_facade_fisp(log: dict) -> Dict[str, Any]:
    cycle = _get(log, "cycle", "fisp_cycle", default="")
    return {
        "title": (
            f"🏢 Façade compliance filing (FISP)"
            + (f" — Cycle {cycle}" if cycle else "")
        ),
        "body": (
            "Façade Inspection Safety Program (FISP) — DOB-mandated "
            "every-5-year inspection of building façades for buildings "
            "taller than 6 stories. Reports are filed by a qualified "
            "exterior wall inspector."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Confirm FISP filing status with your QEWI (Qualified "
            "Exterior Wall Inspector). Late filings carry per-day penalties."
        ),
    }


def _render_boiler_inspection(log: dict) -> Dict[str, Any]:
    return {
        "title": "🔧 Boiler inspection compliance filing",
        "body": (
            "DOB-required annual boiler inspection. Buildings with high- "
            "or low-pressure boilers must file an inspection report each "
            "year. Late or missed filings carry penalties."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Confirm with your boiler inspector that the annual filing "
            "is complete or scheduled."
        ),
    }


def _render_elevator_inspection(log: dict) -> Dict[str, Any]:
    return {
        "title": "🛗 Elevator inspection compliance filing",
        "body": (
            "DOB-required elevator inspection. Annual inspections plus "
            "5-year category 1 inspections are mandatory; missed filings "
            "trigger penalties and can affect insurance."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Confirm the elevator inspection report is filed with DOB "
            "before the deadline."
        ),
    }


# ── License renewal template ──────────────────────────────────────


def _render_license_renewal_due(log: dict) -> Dict[str, Any]:
    license_holder = _get(log, "license_holder_name", default="A licensee")
    days_until = log.get("days_until_expiry")
    days_text = f"{days_until} days" if isinstance(days_until, (int, float)) else "soon"
    return {
        "title": f"📜 License renewal due — {license_holder}",
        "body": (
            f"A DOB license tied to this project expires in {days_text}. "
            f"Lapsed licenses block permit pulls and filings."
        ),
        "severity": SEVERITY_WARNING,
        "action_text": (
            "Confirm the licensee has the renewal in process. License "
            "renewal is filed by the license holder, not the GC."
        ),
    }


# ── Generic fallback ──────────────────────────────────────────────


def _render_generic(log: dict) -> Dict[str, Any]:
    """Used when signal_kind is unknown (new dataset added without
    a template, or classifier returned a fallback). Renders the raw
    summary so the activity feed never shows nothing."""
    summary = log.get("ai_summary") or "DOB record updated."
    next_action = log.get("next_action") or "Open Levelog to review the details."
    return {
        "title": f"🏗️ {summary[:80]}",
        "body": summary,
        "severity": SEVERITY_INFO,
        "action_text": next_action,
    }


# ── Dispatch registry ─────────────────────────────────────────────


SIGNAL_TEMPLATE_RENDERERS = {
    # permit
    "permit_issued":    _render_permit_issued,
    "permit_expired":   _render_permit_expired,
    "permit_revoked":   _render_permit_revoked,
    "permit_renewed":   _render_permit_renewed,
    # job filings
    "filing_approved":     _render_filing_approved,
    "filing_disapproved":  _render_filing_disapproved,
    "filing_withdrawn":    _render_filing_withdrawn,
    "filing_pending":      _render_filing_pending,
    # violations
    "violation_dob":       _render_violation_dob,
    "violation_ecb":       _render_violation_ecb,
    "violation_resolved":  _render_violation_resolved,
    # SWO
    "stop_work_full":      _render_stop_work_full,
    "stop_work_partial":   _render_stop_work_partial,
    # complaints
    "complaint_dob":  _render_complaint_dob,
    "complaint_311":  _render_complaint_311,
    # inspections
    "inspection_scheduled":  _render_inspection_scheduled,
    "inspection_passed":     _render_inspection_passed,
    "inspection_failed":     _render_inspection_failed,
    "final_signoff":         _render_final_signoff,
    # CofO
    "cofo_temporary":  _render_cofo_temporary,
    "cofo_final":      _render_cofo_final,
    "cofo_pending":    _render_cofo_pending,
    # compliance
    "facade_fisp":          _render_facade_fisp,
    "boiler_inspection":    _render_boiler_inspection,
    "elevator_inspection":  _render_elevator_inspection,
    # license
    "license_renewal_due":  _render_license_renewal_due,
}


def render_signal(signal_kind: str, log: dict) -> Dict[str, Any]:
    """Top-level dispatcher. Returns the rendered dict for the
    signal_kind, falling back to a generic renderer for unknown kinds."""
    renderer = SIGNAL_TEMPLATE_RENDERERS.get(signal_kind, _render_generic)
    return renderer(log or {})
