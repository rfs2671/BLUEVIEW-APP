/**
 * ONE FINDING, WRITTEN TO TWO STATUTORY ITEMS.
 *
 * BC 3301.13.13 lists unsafe conditions (§4) and orders given (§5) as separate
 * items. They are ONE THING THAT HAPPENS: he saw something and he did
 * something about it. Two free-text boxes produce "see above" in one of them,
 * which satisfies neither item and is worse than a blank because it looks
 * answered.
 *
 * So the CP enters findings — one per thing he saw — and this derives both
 * item blocks from them. The structure is what makes both items real: a
 * finding carries WHERE, WHEN, WHAT WAS SEEN (item 4), WHAT WAS ORDERED, TO
 * WHOM (item 5), and WHETHER IT WAS CORRECTED.
 *
 * "NOTHING TO REPORT" COVERS BOTH ITEMS AND SAYS SO. A single affirmation
 * setting `none_to_report` on two statutory items is defensible only if the
 * control names both, because the CP is attesting twice with one tap. The
 * screen's label does; this module refuses to derive an attestation that was
 * not made.
 *
 * IT NEVER INVENTS AN ATTESTATION. A finding with a condition but no order
 * makes item 4 PRESENT and leaves item 5 unanswered — it does not quietly mark
 * item 5 "none to report", because "I saw something and did nothing" is a
 * statement he has to make himself.
 */

const text = (v) => String(v ?? '').trim();

/**
 * WAS IT CORRECTED? THREE ANSWERS, AND NEVER A BLANK.
 *
 * A boolean cannot say this. "Not corrected" and "not corrected YET" are
 * different statements about the same site: one says he found something and
 * left it standing, the other says the work is under way. Collapsing them
 * forces him to assert whichever is less wrong, on a licensed signature.
 *
 * AND `null` IS NOT THE THIRD ANSWER. An unanswered field is the same shape as
 * a false one to every reader downstream — the defect family this project keeps
 * finding, where absence gets read as a claim. So `NOT_YET` is a POSITIVE
 * answer he chooses, and an untouched row is refused by the gate rather than
 * filed with a gap.
 */
export const CORRECTED = 'corrected';
export const NOT_CORRECTED = 'not_corrected';
export const NOT_YET = 'not_yet';
export const CORRECTION_STATES = Object.freeze([CORRECTED, NOT_CORRECTED, NOT_YET]);

/** True only for one of the three declared answers — never for null or ''. */
export const isCorrectionState = (v) => CORRECTION_STATES.includes(v);

/** A blank finding, as the editor holds it. */
export const emptyFinding = () => ({
  id: `f_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  location: '',
  observed_at: '',
  condition: '',   // item 4 — what was seen
  order_given: '', // item 5 — what was ordered
  order_to: '',    // item 5 — who it was given to
  // UNANSWERED, and it stays unanswered until he says. `findingGaps` refuses
  // the row rather than letting it reach the document with a silent default.
  corrected: null,
});

/** Has the CP put anything in this row at all? */
export const findingIsEmpty = (f) => !f || !(
  text(f.location) || text(f.observed_at) || text(f.condition)
  || text(f.order_given) || text(f.order_to) || isCorrectionState(f.corrected)
);

/**
 * WHAT 1 RCNY 3301-04(f) NEEDS FROM A FINDING, and it is not "some text".
 * A finding that names no location is not a record of an unsafe condition —
 * a reader cannot return to it. The editor blocks the step on this rather
 * than filing a finding nobody can act on.
 */
export const findingGaps = (f) => {
  const gaps = [];
  if (!text(f.condition)) gaps.push('what you saw');
  if (!text(f.location)) gaps.push('where');
  // NEVER A BLANK. Whether it was put right is the question the reader of a
  // 3301.13.13 log is actually asking, and it is the one field where an
  // omission reads as an answer — a missing "corrected" looks like "no".
  if (!isCorrectionState(f.corrected)) gaps.push('whether it was corrected');
  return gaps;
};

/**
 * Derive items 4 and 5 from the findings.
 *
 * `noneToReport` is the CP's single affirmation covering BOTH items. It is
 * honoured only when there are no findings — a list with entries in it and a
 * "nothing to report" tick is a contradiction, and the entries win because
 * they are the more specific statement.
 */
export function deriveConditionAndOrderBlocks(findings, noneToReport) {
  const rows = (findings || []).filter((f) => !findingIsEmpty(f));

  if (rows.length === 0) {
    const attested = noneToReport === true;
    return {
      unsafe_conditions: attested ? { none_to_report: true } : {},
      orders_given: attested ? { none_to_report: true } : {},
    };
  }

  const conditions = rows
    .filter((f) => text(f.condition))
    .map((f) => ({
      location: text(f.location),
      observed_at: text(f.observed_at),
      condition: text(f.condition),
      corrected: isCorrectionState(f.corrected) ? f.corrected : null,
    }));

  const orders = rows
    .filter((f) => text(f.order_given))
    .map((f) => ({
      location: text(f.location),
      observed_at: text(f.observed_at),
      order: text(f.order_given),
      given_to: text(f.order_to),
      condition: text(f.condition),
      corrected: isCorrectionState(f.corrected) ? f.corrected : null,
    }));

  return {
    // An item with entries is PRESENT. An item with NEITHER entries nor an
    // affirmation stays unanswered and the submit gate names it — which is
    // correct: he logged a condition and recorded no order, and only he can
    // say whether that was because none was needed.
    unsafe_conditions: conditions.length ? { entries: conditions } : {},
    orders_given: orders.length ? { entries: orders } : {},
  };
}

export default deriveConditionAndOrderBlocks;
