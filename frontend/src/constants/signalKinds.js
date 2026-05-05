/**
 * Phase B1b — signal_kind labels + family groupings + tooltips.
 *
 * Mirrors the classifier in backend/lib/dob_signal_classifier.py.
 * The 25 signal_kind values are grouped into 9 families for the
 * preferences UI. Order within each family is the recommended
 * display order (most actionable / common first).
 *
 * Each entry:
 *   key:           the signal_kind string the backend emits.
 *   label:         plain English, suitable for a settings row.
 *   defaultSeverity: matches the canonical severity emitted by
 *                  lib/dob_signal_templates.py — used to render the
 *                  severity badge alongside the label.
 *   tooltip:       1-2 sentence explanation. Operator-tested copy:
 *                  no DOB jargon without inline parenthetical.
 *
 * Each family:
 *   key:    short id, used in collapsed-state keys.
 *   label:  display heading.
 *   blurb:  optional 1-line description shown beneath the heading.
 *   kinds:  array of signal_kind entries.
 */

export const SIGNAL_FAMILIES = [
  {
    key: 'permits',
    label: 'Permits',
    blurb: 'Lifecycle of work permits at DOB.',
    kinds: [
      {
        key: 'permit_issued',
        label: 'Permit issued',
        defaultSeverity: 'info',
        tooltip:
          'A new work permit was issued by NYC DOB. Informational — confirms your filing went through.',
      },
      {
        key: 'permit_expired',
        label: 'Permit expired',
        defaultSeverity: 'critical',
        tooltip:
          'A work permit reached its expiration date without being renewed. Critical: continued work without an active permit can result in a stop-work order.',
      },
      {
        key: 'permit_revoked',
        label: 'Permit revoked',
        defaultSeverity: 'critical',
        tooltip:
          'NYC DOB revoked a permit (typically tied to violations or fraud findings). Critical: work must stop immediately.',
      },
      {
        key: 'permit_renewed',
        label: 'Permit renewed',
        defaultSeverity: 'info',
        tooltip:
          'A renewal was approved at DOB. Informational — confirms a Start Renewal flow you completed.',
      },
    ],
  },
  {
    key: 'filings',
    label: 'Filings',
    blurb: 'Status of permit applications going through DOB NOW review.',
    kinds: [
      {
        key: 'filing_approved',
        label: 'Filing approved',
        defaultSeverity: 'info',
        tooltip:
          'A permit application moved to "Approved" in DOB NOW. Informational — the permit issuance follows shortly.',
      },
      {
        key: 'filing_disapproved',
        label: 'Filing disapproved',
        defaultSeverity: 'critical',
        tooltip:
          'DOB rejected a permit application; you will need to refile or address the disapproval reason. Critical: work cannot start until resolved.',
      },
      {
        key: 'filing_withdrawn',
        label: 'Filing withdrawn',
        defaultSeverity: 'warning',
        tooltip:
          'An application was withdrawn (often by the applicant). Warning: confirm this was intentional — accidental withdrawals delay work.',
      },
      {
        key: 'filing_pending',
        label: 'Filing pending review',
        defaultSeverity: 'info',
        tooltip:
          'A submitted application is waiting on DOB review. Informational — typical processing window is 5-10 business days.',
      },
    ],
  },
  {
    key: 'violations',
    label: 'Violations',
    blurb: 'DOB-issued violations and ECB/OATH summonses.',
    kinds: [
      {
        key: 'violation_dob',
        label: 'DOB violation issued',
        defaultSeverity: 'critical',
        tooltip:
          'A DOB inspector issued a violation against the property. Critical: civil penalty likely; review the violation record.',
      },
      {
        key: 'violation_ecb',
        label: 'ECB / OATH summons',
        defaultSeverity: 'critical',
        tooltip:
          'An Environmental Control Board (ECB) summons has been filed for OATH (Office of Administrative Trials and Hearings) review. Critical: hearing dates are time-sensitive.',
      },
      {
        key: 'violation_resolved',
        label: 'Violation resolved',
        defaultSeverity: 'info',
        tooltip:
          'A previously open violation has been certified, dismissed, or paid. Informational — confirms remediation worked.',
      },
    ],
  },
  {
    key: 'swo',
    label: 'Stop Work Orders',
    blurb: 'Active orders halting work on the property.',
    kinds: [
      {
        key: 'stop_work_full',
        label: 'Full stop work order',
        defaultSeverity: 'critical',
        tooltip:
          'DOB issued a full stop work order: ALL work on the property must cease. Critical: continuing work compounds penalties.',
      },
      {
        key: 'stop_work_partial',
        label: 'Partial stop work order',
        defaultSeverity: 'critical',
        tooltip:
          'DOB issued a partial stop work order against specific trades or areas. Critical: scope is limited but penalties for non-compliance are not.',
      },
    ],
  },
  {
    key: 'complaints',
    label: 'Complaints',
    blurb: 'DOB complaints + 311 construction-related calls.',
    kinds: [
      {
        key: 'complaint_dob',
        label: 'DOB complaint',
        defaultSeverity: 'warning',
        tooltip:
          'Someone filed a complaint with DOB about the project. Warning: a DOB inspector may visit; review the complaint and prepare a response.',
      },
      {
        key: 'complaint_311',
        label: '311 complaint',
        defaultSeverity: 'info',
        tooltip:
          'A 311 call was logged for construction-related issues at the address. Informational unless the volume escalates.',
      },
    ],
  },
  {
    key: 'inspections',
    label: 'Inspections',
    blurb: 'DOB-scheduled and completed inspections.',
    kinds: [
      {
        key: 'inspection_scheduled',
        label: 'Inspection scheduled',
        defaultSeverity: 'warning',
        tooltip:
          'A DOB inspection has been scheduled. Warning: ensure site access and required documentation are ready.',
      },
      {
        key: 'inspection_passed',
        label: 'Inspection passed',
        defaultSeverity: 'info',
        tooltip:
          'A DOB inspection was completed and passed. Informational — milestone progress.',
      },
      {
        key: 'inspection_failed',
        label: 'Inspection failed',
        defaultSeverity: 'critical',
        tooltip:
          'A DOB inspection failed. Critical: the failure reasons must be addressed before the next inspection cycle; expect a re-inspection fee.',
      },
      {
        key: 'final_signoff',
        label: 'Final sign-off',
        defaultSeverity: 'critical',
        tooltip:
          'Final DOB sign-off was issued (or denied). Critical milestone either way — sign-off enables CofO; denial means more work.',
      },
    ],
  },
  {
    key: 'cofo',
    label: 'Certificate of Occupancy',
    blurb: 'CofO and Temporary CofO (TCO) issuance status.',
    kinds: [
      {
        key: 'cofo_temporary',
        label: 'Temporary CofO (TCO) issued',
        defaultSeverity: 'info',
        tooltip:
          'A Temporary Certificate of Occupancy was issued. Informational — building can be occupied for a limited period; final CofO is still required.',
      },
      {
        key: 'cofo_final',
        label: 'Final CofO issued',
        defaultSeverity: 'critical',
        tooltip:
          'Final Certificate of Occupancy was issued. Critical milestone — the building is fully cleared for occupancy.',
      },
      {
        key: 'cofo_pending',
        label: 'CofO application pending',
        defaultSeverity: 'warning',
        tooltip:
          'A CofO application is in DOB review. Warning: typical processing varies; track progress for occupancy planning.',
      },
    ],
  },
  {
    key: 'compliance_filings',
    label: 'Compliance Filings',
    blurb: 'FISP façade, boiler, and elevator inspection cycles.',
    kinds: [
      {
        key: 'facade_fisp',
        label: 'Façade (FISP) inspection',
        defaultSeverity: 'warning',
        tooltip:
          'Façade Inspection Safety Program (FISP) cycle event for the building. Warning: required for buildings 6+ stories; non-filing carries civil penalties.',
      },
      {
        key: 'boiler_inspection',
        label: 'Boiler inspection',
        defaultSeverity: 'warning',
        tooltip:
          'Annual boiler inspection event. Warning: required for fuel-burning equipment; missed filings accrue penalties.',
      },
      {
        key: 'elevator_inspection',
        label: 'Elevator inspection',
        defaultSeverity: 'warning',
        tooltip:
          'Elevator periodic inspection event. Warning: required annually; expired inspections require building shutdown of the unit.',
      },
    ],
  },
  {
    key: 'license_renewals',
    label: 'License Renewals',
    blurb: 'GC license + filing rep license expiration warnings.',
    kinds: [
      {
        key: 'license_renewal_due',
        label: 'License renewal due',
        defaultSeverity: 'warning',
        tooltip:
          'A GC or filing rep license renewal is approaching. Warning: filing without an active license is rejected at DOB.',
      },
    ],
  },
];

// Flat lookup: signal_kind → {family, label, defaultSeverity, tooltip}.
export const SIGNAL_KIND_INDEX = (() => {
  const out = {};
  for (const fam of SIGNAL_FAMILIES) {
    for (const kind of fam.kinds) {
      out[kind.key] = { family: fam.key, ...kind };
    }
  }
  return out;
})();

// Total signal_kinds — used by tests + the UI header copy.
export const TOTAL_SIGNAL_KINDS = Object.keys(SIGNAL_KIND_INDEX).length;

// Severity → display palette. Mirrors lib/dob_signal_templates.py
// SEVERITY_INFO/WARNING/CRITICAL colors used by the activity feed.
export const SEVERITY_PALETTE = {
  info: { color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)', label: 'Info' },
  warning: { color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', label: 'Warning' },
  critical: { color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)', label: 'Critical' },
};
