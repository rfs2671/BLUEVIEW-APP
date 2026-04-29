// Pinned NYC DOB rule citations referenced from the renewal-detail UI.
// Display layer only — do NOT use these strings as keys for behavior
// logic. Authoritative business rules live server-side in
// backend/lib/eligibility_v2.py.

/**
 * Citation for the manual-renewal requirement that fires when a permit
 * crosses the 1-year-since-issuance ceiling (MANUAL_1YR_CEILING
 * strategy in eligibility_v2.py → action.kind === "manual_renewal_dob_now").
 * The $130 fee is set in the DOB Schedule of Fees; the renewal trigger
 * is statutory.
 *
 * Canonical sources:
 *
 *   Rule (fee schedule):
 *     1 RCNY § 101-03 — "Fees Payable to the Department of Buildings"
 *     https://www.nyc.gov/assets/buildings/rules/1_RCNY_101-03.pdf
 *
 *   Statute (renewal trigger / permit expiration):
 *     NYC Admin Code § 28-105.9 — Expiration of permits
 *     https://nycadmincode.readthedocs.io/t28/c01/art105/
 *
 * NOTE: The exact fee-table subsection of § 101-03 (which line item in
 * the schedule of fees maps to the $130 work-permit-renewal entry)
 * was NOT verified against a paper copy when this constant was pinned
 * — the official NYC PDF was unreachable from the research environment
 * (returned 403). The rule-level citation here is correct; before MR.4
 * ships the pre-filled form generator that needs to reference the
 * precise fee-table cell, confirm the subsection against a printed
 * copy of the rule and update both this constant and the form
 * generator's authority comment.
 *
 * The user's original hypothesis pointed to 1 RCNY § 101-14; that
 * section is "Categories of Work That May or May Not Require a Permit"
 * — unrelated to renewal/fees. Renewal fees are in § 101-03.
 */
export const MANUAL_RENEWAL_RULE_CITATION =
  '1 RCNY § 101-03 (DOB Schedule of Fees) — see also NYC Admin Code § 28-105.9';
