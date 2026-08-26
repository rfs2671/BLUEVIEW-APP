/**
 * THE AFFIRMATION GATE, executed.
 *
 * DEVICE ROUND 4, finding 4: three sections of one filed report carried
 * "UNAFFIRMED — inherited signature, not affirmed for this document", and the
 * CP had submitted all three without being stopped. Production settled what was
 * actually stored: `cp_signature: {}` on all three logs. An empty object.
 *
 * `!{}` is FALSE, so a signature containing nothing satisfied every submit gate
 * in the app. Three predicates were being asked of one object and disagreeing:
 *
 *   the gates      `!cpSignature`                  is anything there?
 *   the renderer   `sig.get("affirmed") is True`   did he affirm THIS document?
 *   useCpProfile   strips `affirmed` when caching  so it can never be inherited
 *
 * The renderer's is the right question. This file proves the gates now ask it,
 * on all nine IMMEDIATE types — the ones where the signature IS the freeze, so
 * a submit mints a locked legal record in one action and there is no second
 * chance to catch it.
 *
 * Run:  node src/utils/signatureAffirmed.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const SRC = path.join(UTILS, '..');
const APP_LOGBOOKS = path.join(SRC, '..', 'app', 'logbooks');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The real module, executed — not a hand-copy of the rule.
const MOD_SRC = fs.readFileSync(path.join(UTILS, 'signatureAffirmed.js'), 'utf8');
// eslint-disable-next-line no-new-func
const M = new Function(`${MOD_SRC
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (function|const) /gm, '$1 ')}
  return { isAffirmedSignature, affirmationHintKey };`)();

console.log('\n-- what counts as affirmed --');
ok(M.isAffirmedSignature({ affirmed: true }) === true,
  'a signature affirmed for this document passes');
ok(M.isAffirmedSignature({}) === false,
  'AN EMPTY OBJECT DOES NOT — this is the shape production actually held');
ok(M.isAffirmedSignature({ paths: [[{ x: 1, y: 1 }]], signerName: 'CP' }) === false,
  'a drawn credential with no affirmation stamp does not');
ok(M.isAffirmedSignature({ affirmed: false }) === false, 'an explicit false does not');
ok(M.isAffirmedSignature({ affirmed: 'true' }) === false,
  'and neither does the STRING "true" — identity, not truthiness');
ok(M.isAffirmedSignature('data:image/png;base64,iVBOR') === false,
  'a legacy base64 string is not affirmed — it predates the concept');
ok(M.isAffirmedSignature(null) === false && M.isAffirmedSignature(undefined) === false,
  'null and undefined are not affirmed');

console.log('\n-- the hint names the RIGHT fix --');
ok(M.affirmationHintKey({ affirmed: true }, true) === null,
  'an affirmed signature draws no hint at all');
ok(M.affirmationHintKey(null, false) === 'submitSignatureLoading',
  'a CP is never accused of being unsigned while his profile is still loading');
ok(M.affirmationHintKey(null, true) === 'submitNeedsSignature',
  'nothing on file -> sign the pad');
// INVERTED, AND THESE THREE ASSERTED THE DEFECT.
//
// They read:
//
//   affirmationHintKey({}, true)                      === 'submitNeedsAffirmation'
//   affirmationHintKey({paths: [], signerName}, true)  === 'submitNeedsAffirmation'
//   affirmationHintKey({}, true) !== affirmationHintKey(null, true)
//
// `{}` was picked as the fixture for "something on file". It is not something
// on file — it is an empty object with no ink, the shape an old bundle wrote,
// and calling it "unaffirmed" is what told a CP to "tap your signature above
// to affirm it" over an empty pad. Worse, the pad then OFFERED Affirm, and
// handleAffirm stamped `affirmed: true` onto nothing; the PDF printed
// "✓ AFFIRMED for this document" in green over a blank DOB filing.
//
// `paths: []` is the same mistake: a confirmed signature always carries at
// least one stroke, because canConfirm requires paths.length > 0.
//
// The INTENT below is unchanged and still right — a man looking at his own
// signature must never be told he has none. It is now pinned with a fixture
// that actually is one.
const INHERITED = { paths: [[{ x: 1, y: 2 }]], signerName: 'CP', timestamp: '2026-08-19T15:01:10.726Z' };

ok(M.affirmationHintKey({}, true) === 'submitNeedsSignature',
  'an EMPTY object asks him to SIGN. There is no ink to affirm, and affirming '
  + 'it would mint an attestation nobody made');
ok(M.affirmationHintKey({ paths: [] }, true) === 'submitNeedsSignature',
  'and so does an empty stroke list, for the same reason');
ok(M.affirmationHintKey(INHERITED, true) === 'submitNeedsAffirmation',
  'a REAL inherited credential gets the affirm sentence, not the sign sentence');
// Telling a man looking at his own signature that he has no signature is how
// he learns to ignore the hint.
ok(M.affirmationHintKey(INHERITED, true) !== M.affirmationHintKey(null, true),
  'the two states do not share one sentence');
ok(M.affirmationHintKey({}, true) === M.affirmationHintKey(null, true),
  'but an empty object and nothing DO — they are the same state, and treating '
  + 'them as different is the whole defect');

console.log('\n-- the renderer and the gate ask the same question --');
const serverSrc = fs.readFileSync(
  path.join(SRC, '..', '..', 'backend', 'server.py'), 'utf8');
// The rule moved into ONE named predicate on the server (device round 6, item
// 3): the page-1 compliance line has to ask the same question the per-section
// banner prints, and it used to ask `if _l.get("cp_signature")` — truthy for
// the `{}` production actually held. Two statements about one signature.
ok(/def _is_affirmed_signature\(sig\)[\s\S]{0,1400}?return isinstance\(sig, dict\) and sig\.get\("affirmed"\) is True/
  .test(serverSrc),
  'the server has ONE predicate and it tests `affirmed is True` on a dict');
ok(/affirmed = _is_affirmed_signature\(sig\)/.test(serverSrc),
  'and the PDF affirmation banner is one of its callers, not a second copy');
ok(/_is_affirmed_signature\(_doc\.get\("cp_signature"\)\)/.test(serverSrc),
  'so is the page-1 compliance count');
ok(/sig\.affirmed === true/.test(MOD_SRC),
  'and the client predicate is the same test, so the app cannot gate on one rule and print another');

console.log('\n-- SignaturePad no longer owns a private copy --');
const padSrc = fs.readFileSync(path.join(SRC, 'components', 'SignaturePad.js'), 'utf8');
// THE NAMED IMPORT, not the exact brace contents. This pinned
// `{ isAffirmedSignature }` literally and broke when hasSignatureInk was
// added to the same import — a syntax pin failing on a correct change.
ok(/import \{[^}]*isAffirmedSignature[^}]*\} from '\.\.\/utils\/signatureAffirmed'/.test(padSrc),
  'the pad imports the shared predicate');
ok(!/function sigIsAffirmed\(sig\) \{/.test(padSrc),
  'and its private definition is gone, not shadowing the shared one');

console.log('\n-- the drain\'s inline copy still agrees --');
const drainSrc = fs.readFileSync(path.join(UTILS, 'draftSync.js'), 'utf8');
const bodyOf = (src) => {
  const i = src.indexOf('function isAffirmedSignature(sig) {');
  return src.slice(i, src.indexOf('}', i) + 1).replace(/\s+/g, ' ');
};
ok(bodyOf(drainSrc) === bodyOf(MOD_SRC),
  'draftSync\'s deliberate duplicate is character-identical to the shared one');
ok(/status === 'submitted' && !isAffirmedSignature\(body\.cp_signature\)/.test(drainSrc),
  'and the drain refuses an UNAFFIRMED submit, not merely an absent one');

console.log('\n-- all nine IMMEDIATE forms gate on affirmation --');
const timingBlock = serverSrc.slice(
  serverSrc.indexOf('LOGBOOK_TIMING_CLASS = {'),
  serverSrc.indexOf('def logbook_timing_class'),
);
const IMMEDIATE = [...timingBlock.matchAll(/"([a-z_]+)":\s*"immediate"/g)].map((m) => m[1]);
// TEN with the fall-protection log: an equipment inspection is a point-in-time
// finding, so the signature is the freeze and a later inspection is a NEW
// record rather than an edit. Read out of server.py so the list cannot drift
// from the backend's; the count is the checkpoint that makes a new immediate
// type get a gate rather than inherit one by omission.
ok(IMMEDIATE.length === 10, `server.py declares 10 IMMEDIATE types (got ${IMMEDIATE.length})`);

// COMMENTS STRIPPED before the absence assertion. osha_log's own comment quotes
// the predicate it used to carry, and matching raw source made the file fail an
// assertion about code it no longer has — the self-referential match this
// project has hit twice before.
const stripped = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');

for (const t of IMMEDIATE) {
  const raw = fs.readFileSync(path.join(APP_LOGBOOKS, `${t}.jsx`), 'utf8');
  const src = stripped(raw);
  // Three spellings of one guarantee: a disabled button, the stepper's
  // submitDisabled (the form does not own its footer), or a DERIVED status,
  // which is stronger still — subcontractor_orientation has no draft to come
  // back to, so an unaffirmed sign simply is not a submit.
  const gated = new RegExp(
    "(disabled|submitDisabled)=\\{!isAffirmedSignature\\(cpSignature\\)"
    + "|const status = isAffirmedSignature\\(newCpSignature\\) \\? 'submitted' : 'draft'",
  ).test(src);
  ok(gated, `${t}: submit is gated on AFFIRMATION`);
  // The old predicate must be gone, not merely joined.
  ok(!/(disabled|submitDisabled)=\{!cpSignature/.test(src),
    `${t}: the presence-only predicate is gone, so {} cannot pass`);
  ok(/from '\.\.\/\.\.\/src\/utils\/signatureAffirmed'/.test(src),
    `${t}: uses the shared module rather than re-deriving the rule`);
}

console.log('\n-- and none of them is a dead end --');
for (const t of IMMEDIATE) {
  const src = fs.readFileSync(path.join(APP_LOGBOOKS, `${t}.jsx`), 'utf8');
  ok(/affirmationHintKey\(/.test(src), `${t}: says WHY submit is unavailable`);
  ok(/profileLoaded/.test(src),
    `${t}: and does not accuse the CP while his profile is still loading`);
}

// The three ported forms cannot render their own hint — they do not own the
// footer. Without this the prop would be write-only and the CP would meet a
// dead grey button with no sentence anywhere near it.
const chrome = fs.readFileSync(
  path.join(SRC, 'components', 'logbookStepper', 'LogbookStepper.jsx'), 'utf8');
ok(/submitHint = '',/.test(chrome), 'stepper: submitHint is a declared prop');
ok(/\{step === total && submitDisabled && !!submitHint && \(/.test(chrome),
  'stepper: the hint renders exactly when the button is dead on the submit step');
ok(/<Text style=\{s\.submitHint\}>\{submitHint\}<\/Text>/.test(chrome),
  'stepper: and it is rendered, not merely accepted');
const stepperStyles = fs.readFileSync(
  path.join(SRC, 'components', 'logbookStepper', 'styles.js'), 'utf8');
ok(/submitHint: \{/.test(stepperStyles), 'stepper: the hint has a style');
ok(!/submitHint:[\s\S]{0,120}#[0-9a-fA-F]{6}/.test(stepperStyles),
  'stepper: styled from tokens, no colour literal');

console.log('\n-- the copy exists, and stays EN-only --');
const en = fs.readFileSync(path.join(SRC, 'i18n', 'en.js'), 'utf8');
const es = fs.readFileSync(path.join(SRC, 'i18n', 'es.js'), 'utf8');
ok(/submitNeedsAffirmation:\s*'[^']+'/.test(en), 'submitNeedsAffirmation is in EN');
ok(!/submitNeedsAffirmation/.test(es),
  'and absent from ES — `finalize` is EN-only, CP-facing legal-record copy');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
