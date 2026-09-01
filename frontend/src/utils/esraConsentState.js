/**
 * MAY THIS PERSON SIGN YET, AND IF NOT, WHY NOT?
 *
 * ── WHY A CONSENT GATE AT ALL ───────────────────────────────────────────────
 *
 * Buildings Bulletin 2024-007 § V.5 requires that all involved parties clearly
 * intend to sign electronically and agree to conduct transactions
 * electronically. The backend has recorded that agreement since #308 —
 * `lib/esra_consent.py`, `GET/POST /api/esra-consent` — and NOTHING HAS EVER
 * ASKED FOR IT. `has_current_esra_consent` was called only by its own tests,
 * and no screen mentioned consent.
 *
 * RETROFITTING CANNOT REACH BACKWARDS. A consent recorded in October does not
 * describe a signature applied in September; the agreement has to exist before
 * the signature it is about. Every entry signed before this gate exists is
 * signed without recorded consent, permanently, and no later migration fixes
 * it. That is why this ships before the toggle is turned on rather than after.
 *
 * ── FOUR STATES, AND "UNKNOWN" IS NOT "NO" ──────────────────────────────────
 *
 * The distinction this codebase keeps relearning: the ABSENCE of an answer is
 * not an answer. `cs_attribution` keeps NO_REGISTRATION apart from
 * NOT_REGISTERED_CS for the same reason, and collapsing that pair is what
 * produced 285 false flags.
 *
 *   READY        agreed, to the wording currently in force
 *   NOT_AGREED   the server answered, and the answer is that they have not
 *   STALE        agreed to EARLIER wording — an agreement to different words
 *   UNKNOWN      the question could not be asked (outage, offline, refused)
 *
 * ── UNKNOWN FAILS CLOSED, AND THAT IS A CHOICE WITH A COST ──────────────────
 *
 * A signature applied while we cannot tell whether consent exists is exactly
 * the defect this module was written to remove, so it does not proceed. The
 * cost is real: an outage stops a statutory filing. Three things make it
 * bearable, and if any of them stops being true this decision must be re-taken:
 *
 *   1. the editor is ONLINE-ONLY today, so a signature already required a
 *      reachable server — this adds no new failure mode
 *   2. his work is preserved; the gate refuses the SIGNATURE, not the form
 *   3. the reason is NAMED on screen with a retry, so it is a wait and not a
 *      wall
 *
 * WHEN THE LOG GOES LOCAL-FIRST THIS BECOMES WRONG. A superintendent in a
 * cellar would then be able to fill and freeze a log offline, and this gate
 * would block the one case offline support exists for. The answer then is a
 * consent state cached from the last successful read — which is a different
 * design, and deliberately not this one.
 */

export const READY = 'ready';
export const NOT_AGREED = 'not_agreed';
export const STALE = 'stale';
export const UNKNOWN = 'unknown';

/**
 * HE WAS ASKED AND SAID NO.
 *
 * A FIFTH STATE, not a flavour of NOT_AGREED, because the two produce
 * different screens: one asks a question, the other states a consequence.
 * Presenting the same question identically after a refusal is a loop, and the
 * refusal is itself a fact about the record — "asked on the 2nd, said no" is
 * a different statement from "no consent on file", which is also what an
 * admin who never sent the invitation produces.
 *
 * IT IS NOT A LOCK. He may agree at any time; the screen says so, and the
 * agreement's own wording promises he can withdraw. A one-tap permanent block
 * would be a state the product has no exit from.
 */
export const DECLINED = 'declined';

/**
 * Read the server's answer into one of the four states.
 *
 * `payload` is the body of GET /api/esra-consent, or null/undefined when the
 * call failed. It is deliberately NOT given the error: the distinction that
 * matters here is answered-versus-not, and a caller that mapped particular
 * HTTP codes to particular states would be inventing a contract the endpoint
 * does not publish.
 */
export function consentState(payload) {
  if (!payload || typeof payload !== 'object') return UNKNOWN;

  // `is_current` is the server's own answer to "agreed to the wording in force
  // NOW", computed by consent_is_current(). It is read rather than recomputed
  // from the two version fields, so the client cannot disagree with the server
  // about the one thing the POST will check.
  //
  // CHECKED BEFORE THE DECLINE, and the order is the rule: a man who declined
  // in March and agreed in April has AGREED. A decline is a fact that was true
  // when it was recorded, not a standing veto, so it must never outrank a
  // current consent.
  if (payload.is_current === true) return READY;

  // Asked, and refused. Reported apart from NOT_AGREED because the screens
  // differ: one asks, the other states a consequence and offers paper.
  if (payload.has_declined === true) return DECLINED;

  // Agreed to SOMETHING, but not the current wording. Reported apart from
  // never-agreed because what a person is asked differs: one is being asked
  // for the first time, the other is being asked again because the words
  // changed, and telling the second group they never agreed is false.
  if (payload.has_consented === true) return STALE;

  if (payload.has_consented === false) return NOT_AGREED;

  // A body that answers neither question. Not treated as "no" — an endpoint
  // returning a shape this does not recognise has told us nothing.
  return UNKNOWN;
}

/** Does this state permit a signature to be applied? Only one does. */
export const canSign = (state) => state === READY;

/**
 * Which wording to send back with the agreement.
 *
 * ALWAYS THE SERVER'S CURRENT VERSION, never the one the user previously
 * agreed to. The POST refuses a stale version with ESRA_CONSENT_VERSION_STALE
 * precisely so an agreement is never recorded against text nobody was shown,
 * and echoing `agreed_version` would walk into that refusal on the STALE path
 * — the one path where re-agreeing is the whole point.
 */
export const versionToAgree = (payload) => (
  payload && typeof payload === 'object' ? payload.current_version : undefined
);

/**
 * The copy key for a state. THE SERVER NAMES THE CONDITION, THE CLIENT OWNS
 * THE WORDING — the same rule LogbookLockBar's gateCopy follows.
 */
export function consentCopyKey(state) {
  switch (state) {
    case NOT_AGREED: return 'consentNeeded';
    case STALE: return 'consentChanged';
    case UNKNOWN: return 'consentUnavailable';
    case DECLINED: return 'consentDeclined';
    case READY: return 'consentAlready';
    default: return 'consentNeeded';
  }
}

/**
 * Is there a wording to put in front of him, and a decision to take?
 *
 * DECLINED IS STILL ASKABLE. The refusal is stated first, but the agreement
 * has to remain on the page beneath it — a dead end he cannot reverse is not
 * what was asked for, and the wording itself promises he can withdraw, which
 * only means something if he can also change his mind the other way.
 *
 * UNKNOWN IS NOT. Recording a decision we could not first read back is how a
 * duplicate or a contradiction gets written.
 */
export const isAskable = (state, text) => (
  state !== UNKNOWN && typeof text === 'string' && text.trim().length > 0
);

/**
 * Copy for a refusal CODE from POST /api/esra-consent.
 *
 * The server names the condition and never sends prose; `translate` returns
 * the KEY on a miss, which is how an unmapped code is detected. A code this
 * build has never heard of falls back to the generic rather than rendering
 * `code_SOMETHING_NEW` at a superintendent — the same shape as
 * LogbookLockBar's gateCopy and checkin.html's BLOCK_LABELS.
 */
export function consentGateCopy(translate, code) {
  if (!code) return '';
  const key = `code_${code}`;
  const copy = translate(key);
  return copy && copy !== key ? copy : translate('genericError');
}

export default consentState;
