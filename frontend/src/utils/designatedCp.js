/**
 * WHICH COMPETENT PERSON ITEM 8 OPENS ON.
 *
 * THE OPERATOR'S POINT: a list is not an answer when two men are on site. Item
 * 8 is "the name of the competent person designated in accordance with Section
 * 3301.13.12", and a picker that opens on nothing — or on the first name
 * alphabetically — makes the superintendent choose from a list the app could
 * have narrowed to one.
 *
 * ── THE ANCHOR IS THE FILED DAILY JOBSITE LOG'S `created_by` ────────────────
 *
 * Three candidate sources were measured against production, not reasoned
 * about, and two lost:
 *
 *   cp_name on the daily log     A STRING. The 42 filed daily logs hold five
 *                                spellings for three accounts — 'michael' 33,
 *                                'Test CP' 8, 'Roy Fishman' 4, 'michael
 *                                Cespedes' 4, '2' 4. Matching that to a roster
 *                                row is a NAME MERGE, which is the one thing
 *                                filterCompetentPersons' own docstring refuses:
 *                                the UI must not decide two accounts are one
 *                                man. '2' appears four times.
 *
 *   signature_events             THE STRONGEST IDENTITY IN THE SYSTEM —
 *                                `signer.user_id` is server-set from the
 *                                authenticated session — AND IT CANNOT ANSWER
 *                                THE QUESTION. The collection carries no
 *                                project_id and no date, so it needs a join
 *                                through logbooks by document_id. Worse: 15
 *                                filed daily logs have NO cp_sign event at all
 *                                (#459's ledger-reach gap, from the other
 *                                side), so on those days it answers "nobody
 *                                signed" — a false negative on a statutory
 *                                item, the worst direction available.
 *                                `created_by` was present on all 15.
 *
 *   created_by on that log       AN ACCOUNT ID, on the document this screen
 *                                already fetches for item 2. It agreed with
 *                                `signer.user_id` on 38 of 38 rows where both
 *                                existed, with zero disagreements, and it is
 *                                unambiguous by construction: create_logbook
 *                                upserts on (project_id, company_id, log_type,
 *                                date), so there is one filed daily log per
 *                                project per day. Measured: 42 rows, 42
 *                                groups, one account each.
 *
 * ── WHY THE ANCHOR IS THE DAILY LOG AND NOT "ANYONE WHO FILED THAT DAY" ────
 *
 * 2026-08-17 on project 6a5f63bc has TWO distinct accounts, and it is not two
 * competent persons:
 *
 *     Michael Cespedes  (cp)     13 logs, including the daily jobsite log
 *     Meilich Friedman  (admin)   1 log — an osha_log
 *
 * One CP on the job and the admin filing an OSHA register from the office. A
 * rule reading "anyone who filed today" would have shown two candidates and
 * suppressed the default on a day with one unambiguous answer. Anchoring on
 * the CP's own §3301.2 daily record is immune to it: a back-office filing does
 * not move item 8.
 *
 * ── NO DEFAULT IS A REAL ANSWER, AND IT IS THE FALLBACK EVERYWHERE ─────────
 *
 * A wrong default on a statutory item is worse than no default, because a name
 * that looks right is not questioned — the same failure as the 219 filed rows
 * reading 'michael'. So this returns null, and the picker opens on nothing,
 * whenever the app does not know:
 *
 *   no filed daily log for the date   he may file before the CP does, or on a
 *                                     day the CP was absent — which is exactly
 *                                     the day item 8's "none designated"
 *                                     exists for
 *   the log carries no created_by     64 of 315 logbooks have none
 *   it resolves to no roster row      another company's account, a deleted
 *                                     user, an account without the role
 *   it resolves to more than one      cannot happen through a unique id, and
 *                                     is refused rather than tie-broken
 *
 * ── AND IT IS A PRESELECTION, NEVER A LOCK ─────────────────────────────────
 *
 * A value the app supplies and he does not check is a fabrication with his
 * signature under it — the same class as the departure-time stamp that was
 * removed from this screen. He can change it in one tap and type a name in
 * two.
 *
 * ── THE KNOWN WEAKNESS, WRITTEN DOWN ───────────────────────────────────────
 *
 * `created_by` is stamped when the draft is CREATED, not when it is SIGNED.
 * Those are different claims, and on a shared site device with two CPs — the
 * case this default exists for — one man creating a draft and another signing
 * it is the ordinary way they diverge. Measured, they never have (38 of 38).
 * The durable answer is a server-set `signed_by` on the logbook at finalize;
 * when it exists, `ANCHOR_FIELD` moves and nothing else here changes.
 */

import { filedDailyRecord } from './dailyLogRecord';
import { isSamePerson } from '../components/CompetentPersonPicker';

/**
 * The field on the filed daily log that names the account.
 *
 * NAMED RATHER THAN INLINE because it is the thing that changes when
 * `signed_by` lands: the anchor moves, the rule does not.
 */
export const ANCHOR_FIELD = 'created_by';

/**
 * The roster row item 8 should open on, or null.
 *
 * `rows`   what getByProject(project, 'daily_jobsite', date) returned
 * `roster` what the picker lists — the company's competent persons
 *
 * IDENTITY THROUGH `isSamePerson`, NOT A HAND-ROLLED COMPARISON. That rule
 * already exists for "is this picked person the account holding the phone",
 * and it asks the same question this does: do these two rows identify one
 * account. It handles the `id` / `_id` spelling split that this codebase reads
 * both ways, and it FAILS CLOSED — unsure means no match, which here means no
 * default, which is the direction that cannot put a wrong name on the record.
 */
export function designatedCpDefault(rows, roster) {
  const record = filedDailyRecord(rows);
  if (!record) return null;

  const account = String(record[ANCHOR_FIELD] || '').trim();
  if (!account) return null;

  const matches = (Array.isArray(roster) ? roster : [])
    .filter((r) => isSamePerson(r, { id: account }));

  // EXACTLY ONE, OR NOTHING. Two roster rows matching one account id cannot
  // happen through a unique id, so reaching here means something is wrong with
  // the roster — and a tiebreak invented at that moment is precisely the
  // silent wrong answer this whole module is arranged to avoid.
  return matches.length === 1 ? matches[0] : null;
}

export default designatedCpDefault;
