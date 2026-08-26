/**
 * IS THIS LOG STILL OPEN FOR EDITING?
 *
 * One rule, shared, because three editors carried a copy of a DIFFERENT rule
 * and it reopened filed records.
 *
 * WHAT THEY HAD:
 *
 *     const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
 *
 * That is the FREEZE MODEL for IMMEDIATE types, lifted from the server's
 * dedupe filter — `if is_immediate_preshift(...): dedupe_filter["is_locked"] =
 * {"$ne": True}` — where its comment explains it: "an IMMEDIATE log is never
 * reopened. Once signed (locked) it is a closed record, so a later same-day
 * filing is a NEW DISCRETE LOG (the 11am orientation, the post-alteration
 * scaffold inspection), not an edit."
 *
 * THE CLIENT COPIED THE EXCLUSION AND DROPPED THE CONDITION. The server applies
 * it only to immediate types, and the same comment says why: "END_OF_DAY logs
 * deliberately keep the 423 — the daily narrative is one record per day;
 * corrections go through /amend." The client applied it to every type,
 * including daily_jobsite.
 *
 * An END_OF_DAY log is not locked when it is submitted: the sweep freezes it
 * overnight, and only if its signature is affirmed. So `!is_locked` selected
 * the filed daily narrative and handed it to the editor as an editable draft.
 * Two records at 588 Thomas were overwritten that way on 2026-08-25 — and the
 * CP changed nothing. Opening the log is enough: hydrate sets fourteen fields,
 * all of them in the autosave deps, and there is no dirty tracking.
 *
 * THE RULE IS OPENNESS, NOT THE LOCK. A submitted log is finished whether or
 * not the freeze has caught up with it. `status !== 'submitted' && !is_locked`
 * says that in one place, and it keeps the immediate-type behaviour exactly:
 * a submitted immediate log is locked, so it was already excluded, and it stays
 * excluded — the editor shows it read-only and the server's dedupe mints the
 * next instance.
 */

/**
 * True when a log may still be edited in place.
 *
 * Both halves are required. `status !== 'submitted'` is the fact that matters;
 * `!is_locked` stays because a locked log is closed regardless of what its
 * status field says, and because a legacy row may carry one without the other.
 */
export function isOpenForEditing(log) {
  if (!log || typeof log !== 'object') return false;
  return log.status !== 'submitted' && !log.is_locked;
}

/**
 * Pick the log the editor should load, and say whether it is read-only.
 *
 * Returns `{ log, readOnly }`. `log` is the first still-open log, or the day's
 * first log when none is open; `readOnly` is true whenever the chosen log is
 * not open for editing.
 *
 * The caller sets its `locked` state from `readOnly`, which drives
 * `pointerEvents='none'` over the whole form AND makes LogbookLockBar render
 * its FINALIZED banner with Amend — the correction path. That matters: refusing
 * re-entry without offering an amendment would replace a silent overwrite with
 * a dead end.
 */
export function chooseEditableLog(logs) {
  const arr = Array.isArray(logs) ? logs : [];
  const open = arr.find(isOpenForEditing);
  const log = open || arr[0] || null;
  return { log, readOnly: !!log && !isOpenForEditing(log) };
}

export default isOpenForEditing;
