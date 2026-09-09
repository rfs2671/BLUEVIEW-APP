/**
 * ITEMS 4 AND 5 ARE OFFERED FROM THE CP'S SAFETY OBSERVATIONS.
 *
 * THE OPERATOR'S RULING: an unsafe condition is a FACT ABOUT THE SITE, not
 * about him -- the same reasoning that lets item 2 adopt the CP's summary and
 * that stops item 3 adopting anything. So the superintendent is offered what
 * the competent person recorded, and signing it is the attestation.
 *
 * THE SOURCE IS `data.observations` ON THE FILED DAILY JOBSITE LOG, read
 * through `filedDailyRecord` -- the same document items 2 and 8 already read,
 * through the same chain rule. See dailyLogRecord.js for why that is
 * `chainHead` rather than `rows[0]` and why an unsigned draft is not a record.
 *
 * ── WHAT AN OBSERVATION ACTUALLY HOLDS, MEASURED ────────────────────────────
 *
 * FOUR KEYS, AND ONLY EVER FOUR. Across every observation row in production,
 * filed and draft:
 *
 *     5  description
 *     5  responsible_party
 *     5  remedy
 *     5  corrected_immediately
 *
 * THERE IS NO LOCATION, and `findingGaps` requires one -- "a finding that
 * names no location is not a record of an unsafe condition, a reader cannot
 * return to it". So AN OFFERED FINDING IS NEVER COMPLETE. He must supply
 * WHERE before the step will pass, which is the honest outcome: the CP's
 * observation form never asked where, and inventing a location would be worse
 * than an empty box he has to fill.
 *
 * ── `remedy` IS DELIBERATELY NOT MAPPED TO `order_given`, AND THE DATA IS WHY ─
 *
 * Item 5 is ORDERS AND NOTICES GIVEN -- what the superintendent directed.
 * `remedy` is the corrective action on the CP's own form, and TWO OF THE FIVE
 * ROWS IN PRODUCTION HOLD THE LITERAL WORD "Corrected":
 *
 *     {"description": "No hard hats", "responsible_party": "ODD CONSTRUCTION",
 *      "remedy": "Corrected", "corrected_immediately": null}
 *
 * Filing that into item 5 would put "Corrected" on a BC 3301.13.13 record as
 * an order the superintendent gave. The field is being used for the correction
 * STATE by the men filling it, so it cannot be read as an order. Item 5 stays
 * his to write.
 *
 * ── AND `corrected_immediately` IS A BOOLEAN WHERE THE CS LOG REFUSES ONE ────
 *
 * csFindings declares three answers because "'Not corrected' and 'not
 * corrected YET' are different statements about the same site". Only `true`
 * maps: it means CORRECTED. `false` cannot be told apart from NOT_YET, and
 * `null` -- which is FOUR OF THE FIVE PRODUCTION ROWS, because the CP's toggle
 * only ever writes `true` -- is not an answer at all.
 *
 * So anything but `true` leaves `corrected` UNANSWERED, and the submit gate
 * names it. That is the same refusal `corrected: null` already carries: an
 * omission here reads as "no", so it is never defaulted.
 *
 * ── WHAT IS ACTUALLY ADOPTED, THEN ──────────────────────────────────────────
 *
 *     description        -> condition   item 4, what was seen
 *     responsible_party  -> order_to    who an order would go to
 *     corrected_immediately === true -> CORRECTED
 *
 * `order_to` without an `order_given` never reaches item 5:
 * `deriveConditionAndOrderBlocks` filters orders on the order text. So a
 * responsible party carried across is a convenience on the row and not a claim
 * on the document.
 *
 * ── NO PROVENANCE FLAG, AND THIS IS THE PART TO OVERTURN IF IT IS WRONG ─────
 *
 * Item 2 carries `source: adopted|own` because its summary CAN BE FILED
 * UNTOUCHED -- the CP's sentence reaching a signed record with nothing of the
 * superintendent's in it. That cannot happen here: every offered row is
 * missing its location, and usually its correction state, so HIS HAND IS ON
 * EVERY ROW THAT REACHES THE DOCUMENT. A per-row `adopted` flag computed the
 * way item 2 computes its own would read `own` on essentially every filed row,
 * which is a field that always says the same thing.
 *
 * The visibility half of item 2's reasoning is kept and is the part that
 * matters at the signature: the screen says the rows came from the CP's log,
 * because "a sentence that appeared in the box with nothing saying where it
 * came from is a sentence he will sign as his own account of the day".
 */

import { filedDailyRecord } from './dailyLogRecord';
import { CORRECTED } from './csFindings';

const text = (v) => String(v ?? '').trim();

/**
 * The CP's observations for this date as finding-shaped rows, or [].
 *
 * A BLANK OBSERVATION IS DROPPED, and production has one: a row reading
 * `{"description": "", "responsible_party": "", "remedy": "",
 * "corrected_immediately": null}` on 2026-03-10. Offering it would put an
 * empty finding on the superintendent's screen that the gate then refuses,
 * for a row the CP never filled in either.
 *
 * KEYED ON THE DESCRIPTION alone, because that is the one field item 4 needs.
 * A row with a responsible party and no description describes nothing.
 */
export function adoptableFindings(rows) {
  const record = filedDailyRecord(rows);
  if (!record) return [];
  const obs = (record.data || {}).observations;
  return (Array.isArray(obs) ? obs : [])
    .filter((o) => text(o?.description))
    .map((o, i) => ({
      // STABLE WITHIN THE OFFER, and distinct from the `m_${Date.now()}` ids
      // the manual add button mints. React keys these rows and two rows
      // sharing a key is a swapped TextInput.
      id: `adopted_${i}`,
      location: '',
      observed_at: '',
      condition: text(o.description),
      order_given: '',
      order_to: text(o.responsible_party),
      // ONLY `true`. See the header: `false` cannot be told apart from
      // "not yet", and `null` is four of the five rows in production.
      corrected: o.corrected_immediately === true ? CORRECTED : null,
    }));
}

/**
 * Is any row on screen still the CONDITION TEXT that was offered?
 *
 * DRIVES THE NOTE, AND ONLY THE NOTE. It is the same comparison
 * `progressSource` makes for item 2 -- against the text that was OFFERED, not
 * against the CP's log as it stands now -- narrowed to the ONE FIELD THAT IS
 * ACTUALLY ADOPTED. Editing the location does not un-adopt an observation;
 * rewriting what was seen does.
 *
 * SESSION-SCOPED, DELIBERATELY. Nothing is stored, so reopening a saved draft
 * shows no note. That follows from filing no provenance flag (see the header),
 * and it is honest rather than lossy: by the time a draft is saved he has had
 * to supply the location on every row, so the rows are already part his.
 */
export function anyFindingStillAdopted(findings, offered) {
  const offeredText = new Set(
    (Array.isArray(offered) ? offered : [])
      .map((f) => text(f?.condition)).filter(Boolean),
  );
  if (!offeredText.size) return false;
  return (Array.isArray(findings) ? findings : [])
    .some((f) => offeredText.has(text(f?.condition)));
}

export default adoptableFindings;
