/**
 * THE DAY'S STATE — worked, rained out, or shut down.
 *
 * WHY IT IS NOT A CHIP. "Rain — no work" and "shutdown" used to sit in the
 * always-available chip band on every crew card, carrying trade "gc". Both are
 * facts about THE DAY, not activities a crew performed, and the placement had
 * two consequences that only show on the day it matters:
 *
 *   - A day when nobody worked has no crew cards to hang them on, which is
 *     exactly the day a CP needs to record rain.
 *   - A site with no GC crew that day could not record either one at all.
 *
 * WHY IT IS ONE CONTROL AND NOT TWO BOOLEANS. A day cannot be both rained out
 * and shut down. Two independent flags would let a CP file that contradiction
 * and leave every renderer to decide which to believe.
 *
 * NEVER PRE-SELECTED AWAY FROM `worked`. The log must not assert a washout the
 * CP did not report.
 */

export const DAY_WORKED = 'worked';
export const DAY_RAIN = 'rain_no_work';
export const DAY_SHUTDOWN = 'shutdown';

/** Declaration order is display order. `worked` first: it is the default. */
export const DAY_STATES = Object.freeze([DAY_WORKED, DAY_RAIN, DAY_SHUTDOWN]);

const VALID = new Set(DAY_STATES);

/**
 * The stored value, normalised.
 *
 * Anything unrecognised — absent, null, junk, a legacy record written before
 * this field existed — reads as `worked`. That is the honest default: a log
 * that never carried a day state was a log about a day somebody worked.
 */
export const dayState = (v) => (VALID.has(String(v || '')) ? String(v) : DAY_WORKED);

/** True on a day the CP has said nobody worked. */
export const isNoWorkDay = (v) => dayState(v) !== DAY_WORKED;

/**
 * THE DAY STATE IS NOT AN ACTIVITY, and this is the rule that keeps it out of
 * the ranker.
 *
 * The sequence ranker reads yesterday's `activity_ids` to suggest today's
 * chips. Writing a "rain" pseudo-activity onto every crew would feed the graph
 * a day of work that never happened and poison the next day's suggestions for
 * every trade on the project. The day state lives in the day-level payload,
 * is read by the renderers, and is never written to a crew row.
 *
 * Exported as a predicate so the rule can be ASSERTED rather than trusted.
 */
export const isDayStateId = (id) => id === DAY_RAIN || id === DAY_SHUTDOWN;

/**
 * Does step 2 still have to ask each crew what it did?
 *
 * #167 blocks Next until every crew carries an activity and a location, so a
 * filed §3301.2 log can never name a crew and say nothing about it. On a
 * washout nothing happened, so that demand would block the CP from filing the
 * exact day the log exists to record.
 *
 * RELAXED FOR THE ACTIVITY/LOCATION REQUIREMENT ONLY. Everything else the gate
 * does is unchanged.
 */
export const crewWorkRequired = (v) => !isNoWorkDay(v);

/**
 * THE MORNING IS NOT ERASED.
 *
 * A CP who fills in two crews and then sets the day to rain has recorded a
 * half day. The day state DESCRIBES the day; it does not delete what he typed.
 * So there is deliberately no clearing function here, and the screen suppresses
 * the questions rather than blanking the answers — a visible field he is not
 * required to fill invites him to type something to make the card look
 * finished, and a cleared field loses work he did.
 *
 * True when a no-work day still carries work somebody described.
 */
export function retainedWork(activities, v) {
  if (!isNoWorkDay(v)) return [];
  return (Array.isArray(activities) ? activities : []).filter(
    (a) => String(a?.work_description || '').trim() !== ''
      || String(a?.work_locations || '').trim() !== '',
  );
}

export default {
  DAY_WORKED, DAY_RAIN, DAY_SHUTDOWN, DAY_STATES,
  dayState, isNoWorkDay, isDayStateId, crewWorkRequired, retainedWork,
};
