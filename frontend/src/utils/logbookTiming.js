import { markFinalized } from './logbookDrafts';

/**
 * THE FREEZE MODEL (counsel-defined). Two behaviors, and which applies to a log
 * is a LEGAL classification — not a UI preference.
 *
 *   IMMEDIATE (9) — THE SIGNATURE IS THE FREEZE. Signing finalizes the record in
 *     one action; there is no separate "Finalize" step and the log is never
 *     reopened. New information later in the day becomes a NEW DISCRETE LOG (an
 *     11am orientation, a post-alteration scaffold inspection) — the create-new
 *     flow, never an unlock. Corrections go through the amendment-as-child path
 *     (linked child + required reason).
 *
 *   END_OF_DAY (2) — THE DAILY NARRATIVE. daily_jobsite and ssc_daily_safety_log
 *     stay open and accumulating all day (deliveries, visitors, progress);
 *     intermediate saves do NOT freeze them. They freeze once, at the end-of-day
 *     "Submit and Sign" — the small batch set.
 *
 * The BACKEND is authoritative: /logbook-types serves timing_class,
 * is_batchable, freeze_on_sign and freeze_on_finalize per type, and
 * create/update_logbook enforce the lock server-side. This mirror exists so the
 * UI (and the OFFLINE path, which has no server to ask) applies the same rule.
 * If the two ever disagree, the server wins.
 */

/**
 * THIS LIST WENT STALE THE DAY A TWELFTH LOG TYPE SHIPPED, and nothing said so.
 *
 * fall_protection is `immediate` on the server and was missing here, so
 * freezeIfImmediate returned false for it: the record still locked when the
 * push landed, but the ON-DEVICE freeze — the only one that exists with no
 * signal, and the entire reason this mirror is written down — did not happen.
 * The comment above says "if the two ever disagree, the server wins", and that
 * is true everywhere EXCEPT the offline path, which is the path this file is
 * for.
 *
 * logbookTiming.test.cjs now reads LOGBOOK_TIMING_CLASS out of server.py and
 * compares the two lists, so the next type cannot ship half-mirrored.
 */
export const IMMEDIATE_LOG_TYPES = Object.freeze([
  'preshift_signin',
  'toolbox_talk',
  'subcontractor_orientation',
  'osha_log',
  'scaffold_maintenance',
  'hot_work',
  'concrete_operations',
  'crane_operations',
  'excavation_monitoring',
  'fall_protection',
]);

/** The daily narrative logs — open all day, frozen by the EOD Submit & Sign. */
export const END_OF_DAY_LOG_TYPES = Object.freeze([
  'daily_jobsite',
  'ssc_daily_safety_log',
]);

export function isImmediateLog(logType) {
  return IMMEDIATE_LOG_TYPES.includes(logType);
}

/** True when this type may be swept into the end-of-day batch sign. */
export function isBatchable(logType) {
  return !isImmediateLog(logType);
}

/**
 * Call on a SUBMIT (signature) of an IMMEDIATE log. Freezes the on-device draft
 * so the record is locked even with no network — these are below-grade pre-work
 * logs (excavation, concrete, scaffold), so the freeze cannot depend on a server
 * round-trip. The server applies the same lock when the push lands.
 *
 * Returns true if it froze, so the caller can flip its own `locked` state.
 */
export async function freezeIfImmediate(draftKeyStr, logType) {
  if (!isImmediateLog(logType) || !draftKeyStr) return false;
  try {
    await markFinalized(draftKeyStr);
  } catch (_e) {
    // Never let a local-freeze bookkeeping failure block the CP's submit — the
    // server lock still applies once the push lands.
  }
  return true;
}
