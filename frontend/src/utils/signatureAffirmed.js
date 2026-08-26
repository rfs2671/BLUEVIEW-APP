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

/**
 * THE FIELDS THAT BELONG TO ONE DOCUMENT AND MUST NEVER RIDE A CREDENTIAL.
 *
 * The profile signature is a REUSABLE CREDENTIAL. Every field below records
 * something about a single act of attestation on a single record, so carrying
 * any of them onto the next document makes that document assert something
 * nobody did.
 *
 * A LIST, NOT THREE LITERALS, AND THAT IS THE POINT. useCpProfile's strip was
 * written as `const { affirmed, affirmedAt, ...rest }` when the attestation had
 * two fields. `affirmedLang` was added to the attestation later, by a different
 * commit, and nobody widened the strip - so a credential kept carrying it and
 * two logs filed on 2026-08-25 asserted the signer was shown English on a
 * document he never affirmed at all. The omission was invisible because the
 * strip named its fields inline.
 *
 * So the strip now DERIVES from this list. Adding a field to the attestation
 * means adding it here, and the strip widens with it - the failure mode is a
 * missing entry in one obvious place rather than a silent divergence between
 * two files.
 *
 * `timestamp` is DELIBERATELY ABSENT and is a separate decision. It is also
 * carried (it is why both of those logs claim 2026-08-19T15:01:10.726Z, the
 * credential's capture instant), but it is what SignaturePad renders beside an
 * inherited signature, so removing it changes what the CP sees rather than only
 * what the record claims. Reported, not bundled in here.
 */
export const PER_DOCUMENT_SIGNATURE_FIELDS = Object.freeze([
  'affirmed',
  'affirmedAt',
  'affirmedLang',
]);

/**
 * A reusable credential: the signature with every per-document stamp removed.
 *
 * Lives here rather than in useCpProfile because the rule is the same one this
 * module already owns - what makes a signature belong to a document.
 */
export function toCredential(sig) {
  if (!sig || typeof sig !== 'object') return sig;
  const credential = { ...sig };
  for (const field of PER_DOCUMENT_SIGNATURE_FIELDS) delete credential[field];
  return credential;
}

/** True only for a signature affirmed for the document being signed. */
export function isAffirmedSignature(sig) {
  return !!(sig && typeof sig === 'object' && sig.affirmed === true);
}

/**
 * IS THERE ACTUALLY INK ON THIS SIGNATURE?
 *
 * The second question, and it lives here because it is the same question this
 * module already owns — what makes a signature real for a document. Three
 * places asked "is there a signature OBJECT" when they meant "is there ink",
 * and an object is not ink:
 *
 *   affirmationHintKey     `sig ? ...`               `{}` is truthy
 *   SignaturePad           `!!existingSignature`     so is `{}`
 *   server.py:18817        `{"$ne": None}`           `{}` is not null either
 *
 * WHAT THAT COST. With `existingSignature = {}` — the shape an old bundle
 * wrote, and what production actually held — the pad set isSigned true,
 * rendered the literal text "✓ Signed" because there were no paths to draw,
 * and offered AFFIRM. handleAffirm spreads the base object and stamps
 * `affirmed: true` / `affirmedAt` onto it, so the tap produced a signature
 * that was affirmed and contained NOTHING. That object satisfies
 * isAffirmedSignature, passes the submit gate, and reaches the PDF renderer,
 * which finds no `data` and no `paths`, falls through to its signer-only
 * branch, and prints
 *
 *     CP Signature: <name> (signed)
 *     ✓ AFFIRMED for this document        <- in green
 *
 * on a record filed with the DOB. The app minted an attestation nobody made,
 * and the tap that did it was the one the CP dashboard told him to make.
 *
 * THE TWO SHAPES THAT ARE REAL INK, and there are only two:
 *
 *   paths: [...]   SignaturePad's vector output. handleConfirm writes
 *                  `pathsRef.current`, and `canConfirm` requires
 *                  `paths.length > 0`, so a confirmed signature always has at
 *                  least one stroke. An EMPTY array is therefore not "a
 *                  signature with no strokes" — it is no signature.
 *   data: "..."    a base64 raster. The legacy/pre-rendered path, and what
 *                  handleAffirm wraps a bare string into. render_signature_html
 *                  checks the same two fields in the same order.
 *
 * A bare string IS a signature: the renderer treats `isinstance(sig, str)` as a
 * base64 image, and the pad wraps it as `{ data: sig }`. An empty one is not.
 *
 * NOT A REPLACEMENT FOR isAffirmedSignature. Ink says a mark exists; affirmed
 * says the signer adopted it for THIS document. Both are required, they fail
 * for different reasons, and the CP is told a different thing in each case.
 */
export function hasSignatureInk(sig) {
  if (!sig) return false;
  if (typeof sig === 'string') return sig.length > 0;
  if (typeof sig !== 'object') return false;
  if (Array.isArray(sig.paths) && sig.paths.length > 0) return true;
  return typeof sig.data === 'string' && sig.data.length > 0;
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
  // INK, NOT PRESENCE. This read `sig ?`, and `{}` is truthy — so the shape
  // production actually held was called "unaffirmed" and the CP was told to
  // "tap your signature above to affirm it" over an empty pad. There is
  // nothing to affirm without ink, and the only thing that fixes it is
  // signing, so an inkless signature asks for exactly that.
  return hasSignatureInk(sig) ? 'submitNeedsAffirmation' : 'submitNeedsSignature';
}

export default isAffirmedSignature;
