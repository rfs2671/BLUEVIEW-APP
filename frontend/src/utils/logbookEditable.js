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

import { easternDate } from './dates';

/**
 * True when a log may still be edited in place.
 *
 * Both halves are required. `status !== 'submitted'` is the fact that matters;
 * `!is_locked` stays because a locked log is closed regardless of what its
 * status field says, and because a legacy row may carry one without the other.
 */
export function isOpenForEditing(log) {
  if (!log || typeof log !== 'object') return false;
  // A WITHDRAWN CORRECTION IS CLOSED, and neither of the two clauses below
  // says so: `status` is 'withdrawn', not 'submitted', and nothing locked it.
  // The server refuses a PUT to one (409 LOGBOOK_WITHDRAWN), so without this
  // the CP would open a correction he took back, fill it in, and be refused at
  // the save. Third value the rule has to know about, in the one place the
  // rule is written.
  if (log.status === 'withdrawn') return false;
  return log.status !== 'submitted' && !log.is_locked;
}

/**
 * THE LAST NEW YORK DAY WHOSE PHOTO SETS ARE STILL OPEN.
 *
 * `easternDate(now - 3h)`. This is the AFFORDANCE HALF of a rule the server
 * owns — logbook_photo_window_is_open in backend/server.py, which is evaluated
 * against the STORED document and is the only thing that decides anything. This
 * copy exists so the controls DISAPPEAR instead of failing on tap: a button that
 * throws an error when pressed is worse than a button that is not there.
 *
 * WHY 03:00 AND NOT MIDNIGHT: it is the instant the end-of-day sweep runs, so
 * "the photo set closed" and "the record froze" are one event with one
 * explanation rather than two boundaries three hours apart. The server comment
 * carries the whole argument; this is deliberately a mirror and not a second
 * derivation of it.
 *
 * IT WORKS WITH NO NETWORK, which is the reason the boundary is derived from
 * `date` rather than from a filing instant. `date` is a 'YYYY-MM-DD' string on
 * every logbook object the client already holds and caches, so a phone that has
 * been in a cellar for two days still answers correctly. Nothing is asked of the
 * server, and the server's clock is never needed.
 *
 * THE ARITHMETIC IS A UTC SUBTRACTION AND THEN A STRING COMPARE. easternDate
 * from utils/dates.js is the ONE zone conversion — an inline Intl call here
 * would be a second copy of the boundary, and two copies of a rule are two
 * rules the moment one is edited.
 */
const PHOTO_WINDOW_GRACE_MS = 3 * 60 * 60 * 1000;

export function photoWindowDay(now = new Date()) {
  return easternDate(new Date(now.getTime() - PHOTO_WINDOW_GRACE_MS));
}

/**
 * True while this log's photographs may still be added to or removed.
 *
 * FAILS CLOSED on a log with no usable `date`, matching the server exactly. The
 * operator's requirement is that a control never fails on tap, and an absent
 * date is the only case where the device cannot answer — hiding the control is
 * the failure mode that honours the requirement, and the server would refuse
 * anyway.
 */
export function isPhotoWindowOpen(log, now = new Date()) {
  if (!log || typeof log !== 'object') return false;
  const day = String(log.date || '').trim().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  return day >= photoWindowDay(now);
}

/**
 * True when a PHOTOGRAPH may still be added to a log that is closed to editing.
 *
 * THE ONE EXCEPTION TO THE RULE ABOVE, AND IT IS WRITTEN HERE SO THE TWO ARE
 * READ TOGETHER. A photograph is not DOB-required daily log content — BC
 * 3301.2 does not ask for one — so treating a photo addition as an amendment
 * to a filed compliance record is wrong on the merits. The statutory content
 * the CP attested to does not move; a later photograph of that same work is
 * appended in place.
 *
 * IT IS THE COMPLEMENT, NOT A WIDENING. A log is open for editing or open for
 * photo append, never both, and never neither once it exists. On a DRAFT this
 * is false on purpose: the ordinary camera is right there, and the append route
 * writes straight into the stored document, so a draft appended to that way
 * would be overwritten by the editor's own next PUT.
 *
 * The affordance it gates renders OUTSIDE LogbookStepper's pointerEvents='none'
 * wrapper. That wrapper is untouched — this is why the exception is a separate
 * subtree rather than a hole in the wrapper: "no per-field flags to miss" stays
 * true by construction.
 */
export function isOpenForPhotoAppend(log, now = new Date()) {
  if (!log || typeof log !== 'object') return false;
  // AND THE DAY MUST NOT BE OVER. The exception above says a photograph is not
  // an amendment; it never said the set stays open forever. The clock is the
  // other half of that sentence, and it is asked HERE so the four screens that
  // gate on this predicate — the entry row on logbooks/index, the photos screen
  // guard, its per-row add buttons, and FiledLogView's button — all lose the
  // affordance together, without any of them learning about dates.
  if (!isPhotoWindowOpen(log, now)) return false;
  return !isOpenForEditing(log);
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
