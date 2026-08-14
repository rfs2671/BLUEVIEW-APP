/**
 * IS THIS SIGNATURE AFFIRMED FOR *THIS* DOCUMENT?
 *
 * One predicate, shared, because three places were asking three different
 * questions about the same object and getting three different answers:
 *
 *   the submit gate   `!cpSignature`                    — is anything there?
 *   the PDF renderer  `sig.get("affirmed") is True`     — did he affirm it?
 *   useCpProfile      strips `affirmed` before caching  — correctly, so an
 *                                                         affirmation can never
 *                                                         be inherited
 *
 * So a CP whose profile carried a cached credential passed every gate in the
 * app while every document he filed printed "UNAFFIRMED — inherited signature".
 * Device round 4 found three such sections on one report.
 *
 * WORSE THAN INHERITED. The production data settled what was actually stored:
 * `cp_signature: {}` on all three logs — an empty object. `!{}` is FALSE, so a
 * signature containing NOTHING satisfied a presence gate. That is the shape
 * this predicate exists to refuse.
 *
 * The rule is the renderer's, verbatim: affirmed means the CP took an explicit
 * affirmative action ON THIS DOCUMENT and `affirmed === true` records it.
 * A string, an empty object, a legacy credential and an inherited profile
 * signature are all NOT affirmed — an honest deficiency, never a VERIFIED stamp
 * the signer never made for this record.
 *
 * Mirrors backend/server.py:_signature_affirmation_html. If that predicate ever
 * changes, this one changes with it or the app gates on one rule and prints
 * another.
 */

/** True only for a signature affirmed for the document being signed. */
export function isAffirmedSignature(sig) {
  return !!(sig && typeof sig === 'object' && sig.affirmed === true);
}

/**
 * Which `finalize` copy key explains why Submit is unavailable.
 *
 * THREE STATES, NOT TWO. A disabled button with no reason stops a CP at the
 * start of his shift, and "you have no signature" is the wrong sentence for a
 * man looking at his own signature on the screen — his credential IS there, it
 * is the affirmation of THIS document that is missing, and the fix is a
 * different tap. Telling him the wrong one is how a CP learns to distrust the
 * hint.
 *
 * Returns null when the signature is affirmed and no hint is due.
 */
export function affirmationHintKey(sig, profileLoaded) {
  if (isAffirmedSignature(sig)) return null;
  if (!profileLoaded) return 'submitSignatureLoading';
  // Something is stored but unaffirmed — including `{}`, which is what
  // production actually held. He signs the pad below, or taps Affirm.
  return sig ? 'submitNeedsAffirmation' : 'submitNeedsSignature';
}

export default isAffirmedSignature;
