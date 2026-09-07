/**
 * WHICH daily_jobsite DOCUMENT IS THE RECORD FOR A DATE.
 *
 * TWO CONSUMERS ON ONE SCREEN, WHICH IS WHY IT IS NOT INLINE. The
 * superintendent log asks this question twice about the same document:
 *
 *   item 2  adopts the CP's summary of the day (progressProvenance.js)
 *   item 8  defaults the designated competent person (designatedCp.js)
 *
 * Both answers are wrong in the same way if the wrong link of an amended chain
 * is picked, and both end up on a signed BC 3301.13.13 record. Two copies of
 * this rule is how the OSHA register's row rule and the pre-shift sheet each
 * came to print different things from one stored document.
 *
 * ── IT IS chainHead, NOT rows[0] ────────────────────────────────────────────
 *
 * `GET /logbooks/project/{id}?log_type=&date=` returns EVERY LINK of an
 * amended chain, so `rows[0]` adopts whichever the server happened to list
 * first. `chainHead` is the rule this codebase already applies in two other
 * places and mirrors `_filed_log` on the server: the newest FILED link, with
 * withdrawn links out of the chain entirely, because a correction that was
 * taken back corrected nothing.
 *
 * ── AND A DRAFT IS NOT A RECORD ─────────────────────────────────────────────
 *
 * `chainHead` returns an unsigned original when nothing in the chain is filed
 * -- that is correct for its own callers, who are showing a CP his own work in
 * progress. It is wrong here. The CP's unsigned draft is not his account of the
 * day: he has not stood behind it, and it can still change. Reading it would
 * put text, or a man's name, onto a signed statutory record on the strength of
 * something nobody filed.
 */

import { chainHead } from './amendmentChain';

/** The log type the superintendent log derives from. */
export const SOURCE_LOG_TYPE = 'daily_jobsite';

/**
 * The filed daily jobsite log for a date, or null.
 *
 * `rows` is whatever `logbooksAPI.getByProject(project, 'daily_jobsite', date)`
 * returned. A failed read arrives here as `[]` or a non-array and yields null,
 * which every caller must read as "nothing was offered" rather than "nothing
 * happened that day".
 */
export function filedDailyRecord(rows) {
  const head = chainHead(Array.isArray(rows) ? rows : []);
  if (!head) return null;
  // `is_locked` OR `status === 'submitted'`, the same pair `isFiled` uses
  // inside chainHead. An END_OF_DAY log is submitted-and-unlocked until the
  // overnight sweep freezes it, so keying on the lock alone would treat every
  // day as unfiled until 3am -- an answer that depends on what time you ask.
  const filed = !!(head.is_locked || head.status === 'submitted');
  return filed ? head : null;
}

export default filedDailyRecord;
