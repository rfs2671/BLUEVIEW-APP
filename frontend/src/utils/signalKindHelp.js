/**
 * Phase B3 — plain-English explanations for every signal_kind.
 *
 * Used by:
 *   • Activity feed filter group tooltips (group-level "what's in this category")
 *   • Per-signal_kind "What does this mean?" links in advanced
 *     notification preferences
 *   • Any future surface that needs human-readable signal copy
 *
 * Source of truth for the kind list: lib/notification_preferences.py
 * (ALL_DEFAULT_SIGNAL_KINDS — kept in lockstep with frontend
 * notificationPresets.ALL_KINDS).
 *
 * Copy guidance: each entry is one sentence, plain English, written
 * for a GC who isn't deep in DOB jargon. Skip "the DOB" prefix —
 * the surface implies it.
 */

export const SIGNAL_KIND_HELP = {
  // ── Permits ──────────────────────────────────────────────────────
  permit_issued:
    'A new work permit was issued for your project (e.g. plumbing, sprinkler, general construction).',
  permit_expired:
    "A work permit expired without being renewed. Work covered by that permit must stop until it's renewed or replaced.",
  permit_revoked:
    'DOB revoked a permit on your project. This usually follows a violation or stop-work order.',
  permit_renewed:
    'An existing permit was renewed. The new expiration date applies to the same scope of work.',

  // ── Job Filings ──────────────────────────────────────────────────
  filing_approved:
    'A job filing (DOB application) was approved. Permits can now be issued against it.',
  filing_disapproved:
    'A job filing was disapproved by DOB. Your filing rep needs to address the comments before it can move forward.',
  filing_withdrawn:
    "A job filing was withdrawn — usually voluntarily by the applicant. The associated job won't proceed unless it's re-filed.",
  filing_pending:
    'A new job filing is in DOB review. No action required yet; you\'ll see it move to approved or disapproved.',

  // ── Violations ───────────────────────────────────────────────────
  violation_dob:
    'DOB issued a violation against your project. There may be a fine and a required remedy by a deadline.',
  violation_ecb:
    "An Environmental Control Board (ECB) violation was issued. ECB hearings carry their own fines and can compound if you don't appear.",
  violation_resolved:
    'A previously open violation was marked resolved or dismissed.',

  // ── Stop Work Orders ─────────────────────────────────────────────
  stop_work_full:
    'A FULL stop-work order was issued — all work on the site must stop until the order is rescinded.',
  stop_work_partial:
    'A PARTIAL stop-work order was issued — only the cited scope of work must stop. Other trades can continue.',

  // ── Complaints ───────────────────────────────────────────────────
  complaint_dob:
    'A DOB complaint was filed (often anonymous) about activity at your project. DOB will inspect and decide whether to issue a violation.',
  complaint_311:
    'A 311 complaint was filed about your project. 311 routes construction-related complaints to DOB or another agency for follow-up.',

  // ── Inspections ──────────────────────────────────────────────────
  inspection_scheduled:
    'A DOB inspection was scheduled for your project. Make sure the relevant trades are present.',
  inspection_passed:
    'An inspection passed. The inspected scope of work is signed off.',
  inspection_failed:
    'An inspection failed. The inspector noted defects that must be remedied before re-inspection.',
  final_signoff:
    'A final inspection signed off — usually the last DOB step before a Certificate of Occupancy can issue.',

  // ── Certificate of Occupancy ─────────────────────────────────────
  cofo_temporary:
    'A Temporary Certificate of Occupancy (TCO) was issued. The building can be occupied temporarily; conditions and an expiration apply.',
  cofo_final:
    'A FINAL Certificate of Occupancy was issued. The building is approved for permanent occupancy.',
  cofo_pending:
    'A CofO application is in DOB review.',

  // ── Compliance filings ───────────────────────────────────────────
  facade_fisp:
    "A Facade Inspection (FISP / Local Law 11) is approaching its filing window. Required for buildings over 6 stories — missing the window triggers DOB violations.",
  boiler_inspection:
    "A boiler inspection is due. Required annually for most low-pressure boilers; missing it triggers a Class 2 violation.",
  elevator_inspection:
    "An elevator inspection is due. Annual periodic inspection required by DOB; missing it triggers a Class 2 violation.",

  // ── License renewals ─────────────────────────────────────────────
  license_renewal_due:
    'A license you hold (GC, plumbing, etc.) is approaching its renewal deadline.',
};

export const SIGNAL_KIND_GROUP_HELP = {
  Permits:
    "Work permits issued by DOB for your project — the documents that authorize specific trades to work on site. Sub-permits (plumbing, sprinkler, GC, etc.) appear here individually.",
  'Job Filings':
    "DOB applications (jobs) for the work you plan to do. Each filing moves through review (pending → approved or disapproved); permits can only issue against an approved filing.",
  Violations:
    "DOB and ECB violations issued against your project. Each carries a fine and (usually) a required remedy by a deadline.",
  'Stop Work Orders':
    "Orders that halt some or all work on your site until the underlying issue is resolved. FULL stops everything; PARTIAL stops only the cited scope.",
  Complaints:
    "DOB and 311 complaints about your project. DOB inspects most complaints and decides whether to issue a violation.",
  Inspections:
    "DOB inspection events — scheduled, passed, failed, and final signoff. Failed inspections must be remedied before re-inspection.",
  Compliance:
    "Periodic compliance filings: Facade (FISP/LL11), boiler, elevator inspections, and CofO applications. Each has its own filing window and a violation if you miss it.",
  License:
    "License renewal reminders — GC, plumbing, and other trade licenses that are tied to your filings.",
};
