/**
 * A WEEKLY LOG IS NOT DUE EVERY DAY.
 *
 * ── THE DEFECT ───────────────────────────────────────────────────────────────
 *
 * The logbook list renders `required_logbooks` and asks `todayLogs[type]` for
 * each tile's status. That read is BY DATE. `toolbox_talk` is weekly, so on
 * every day except the one it was filed the tile read "pending" and the
 * completion bar counted it against the CP.
 *
 * MEASURED ON PRODUCTION. 588 Thomas filed 33 toolbox talks across 35 working
 * days — a weekly obligation performed five times over, because a red tile
 * every morning is an instruction. 857 Prescott is the same defect with the
 * opposite outcome: 2 filings, 8 red days out of 10, and a CP who learned to
 * ignore it.
 *
 * The SERVER already knew better — `daily_required_logbooks` keeps weekly and
 * as-needed types out of the nightly deficiency sweep, on the written reasoning
 * that counting them "invents a deficiency out of a frequency". The screen had
 * no equivalent. It has one now: the required-logbooks payload carries
 * `periods`, and this reads it.
 *
 * ── THE WEEK IS MONDAY TO FRIDAY ─────────────────────────────────────────────
 *
 * Operator ruling, enforced server-side in lib/logbook/weekly_cadence.py. A
 * weekend worker who did not attend that week's talk re-opens it, and the row
 * names him — so the CP is told who he has to speak to, rather than told to
 * repeat a talk he has already given.
 *
 * ── AND AN AS-NEEDED LOG IS NOT DUE AT ALL UNTIL SOMEBODY NEEDS IT ───────────
 *
 * The same channel now carries `subcontractor_orientation`, which is as_needed:
 * due when a worker has checked in on the project and has no orientation on it,
 * and not otherwise. It was Pending on all three live projects every morning
 * while ZERO workers anywhere were waiting for one, and it inflated the
 * completion count by a sixth item that was not due.
 *
 * Its row asserts no cadence — `period_start` and `period_end` are null on it —
 * because nothing has defined one and a period would be an invention. What it
 * asserts is coverage. `hot_work` is as_needed too and NO ROW IS EMITTED FOR IT,
 * because no server rule says when a hot-work permit log is due; see the
 * fail-open note below for why that silence is safe.
 *
 * ── FAILS OPEN ───────────────────────────────────────────────────────────────
 *
 * No `periods` key, no row for a type, a malformed row: every one of them falls
 * back to the by-date status the screen used before this existed. An older
 * server must not make a required log vanish from a CP's count, and a cadence
 * hint is never worth a blank tile.
 */

/** `periods` from the required-logbooks payload, keyed by log type. */
export function logbookPeriods(payload) {
  const rows = payload && Array.isArray(payload.periods) ? payload.periods : [];
  const out = {};
  rows.forEach((row) => {
    if (row && typeof row.log_type === 'string') out[row.log_type] = row;
  });
  return out;
}

/** The period row for a type, or null. */
export const periodFor = (periods, logType) => (
  (periods && periods[logType]) || null
);

/**
 * Is this type satisfied for the period it is due in?
 *
 * `null` means THE QUESTION DOES NOT APPLY — a daily log, or a server that does
 * not send periods — and the caller keeps its by-date answer. `true` / `false`
 * are answers about the period and nothing else.
 */
export function periodSatisfied(periods, logType) {
  const row = periodFor(periods, logType);
  if (!row || typeof row.satisfied !== 'boolean') return null;
  return row.satisfied;
}

/**
 * The tile's status, given what the by-date read says.
 *
 * ORDER MATTERS AND IT IS NOT SYMMETRIC. A log filed TODAY reads submitted
 * whatever the period says — he did it, and the screen must not argue. It is
 * only the "nothing today" case the period is allowed to speak to, which is the
 * case the old read got wrong.
 */
export function cadenceStatus(periods, logType, todayStatus) {
  if (todayStatus === 'submitted' || todayStatus === 'draft') return todayStatus;
  const satisfied = periodSatisfied(periods, logType);
  if (satisfied === true) return 'period_done';
  return todayStatus;
}

/**
 * The line under a weekly tile, or null.
 *
 * NAMES THE MEN WHEN THE WEEKEND RE-OPENED IT. "Due again" tells a CP to give a
 * talk; "Due again — 2 weekend workers were not at this week's talk" tells him
 * what to do and why, and stops him reading it as the app having lost the one
 * he gave on Tuesday.
 */
export function cadenceLabel(periods, logType) {
  const row = periodFor(periods, logType);
  if (!row) return null;
  // ── AN AS-NEEDED LOG HAS NO WEEK ───────────────────────────────────────────
  //
  // The weekly wording below ("Done this week", "Due this week") is a CADENCE
  // claim, and `subcontractor_orientation` has no cadence — its row carries
  // period_start/period_end of null precisely so nothing asserts one. It is due
  // because a named worker checked in without an orientation, and that is what
  // the CP has to be told: not that a period elapsed, but who he has to sit
  // down with.
  //
  // THE SATISFIED CASE IS ALMOST UNREACHABLE from the logbook list, which drops
  // a satisfied as-needed tile entirely. It is written anyway because this
  // module is not that screen's private helper, and a label that would read
  // "Done this week" about a log filed in March is worse than one nobody sees.
  if (row.frequency === 'as_needed') {
    if (row.satisfied) return 'Nobody on site is waiting for one';
    const n = typeof row.uncovered_worker_count === 'number'
      ? row.uncovered_worker_count
      : (Array.isArray(row.uncovered_workers) ? row.uncovered_workers.length : 0);
    if (n <= 0) return 'Due — a worker on site has no orientation';
    const who = Array.isArray(row.uncovered_workers) && row.uncovered_workers.length
      ? ` — ${row.uncovered_workers.slice(0, 3).join(', ')}`
        + (n > 3 ? ` and ${n - 3} more` : '')
      : '';
    return `Due — ${n} worker${n === 1 ? '' : 's'} on site `
      + `${n === 1 ? 'has' : 'have'} no orientation${who}`;
  }
  if (row.satisfied) {
    const on = Array.isArray(row.filed_on) && row.filed_on.length > 0
      ? row.filed_on[row.filed_on.length - 1] : null;
    return on ? `Done this week — filed ${on}` : 'Done this week';
  }
  const missed = Array.isArray(row.uncovered_weekend_workers)
    ? row.uncovered_weekend_workers.length : 0;
  if (row.due_reason === 'WEEKEND_WORKER_NOT_COVERED' && missed > 0) {
    return `Due again — ${missed} weekend worker${missed === 1 ? '' : 's'} `
      + 'were not at this week’s talk';
  }
  return 'Due this week';
}

export default {
  logbookPeriods,
  periodFor,
  periodSatisfied,
  cadenceStatus,
  cadenceLabel,
};
