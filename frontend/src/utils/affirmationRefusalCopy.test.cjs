/**
 * The refusal names the tap that fixes it.
 *
 * THE DEFECT. Affirmation enforcement — a submit gate that asks whether the
 * signature is affirmed FOR THIS DOCUMENT rather than merely present — emits
 * SUBMIT_MISSING_CP_SIGNATURE, whose copy reads "This log is not signed. Sign
 * it before submitting." The CP is looking at his own signature on the screen.
 * The credential IS there; the affirmation of THIS record is what is missing;
 * and signing again does not fix it, because the pad re-stamps the same
 * unaffirmed credential. He is told to repeat the one action that cannot work.
 *
 * THE ORDER MATTERS, AND THIS FILE PINS IT. gateCopy falls back to
 * genericError for a code it does not know:
 *
 *     const copy = t(`code_${code}`);
 *     return copy && copy !== key ? copy : t('genericError');
 *
 * So a server emitting the new code BEFORE this bundle ships turns a specific
 * refusal into "This log could not be finalized. Please try again." on every
 * device that has not fetched the update — and the device still writing an
 * unaffirmed signature is the one least likely to be current. Copy first,
 * server second. TheServerDoesNotEmitItYet below is that pin, and it inverts
 * when the server switch lands rather than being quietly deleted, so the
 * pairing stays visible.
 *
 *   node frontend/src/utils/affirmationRefusalCopy.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

function loadModule(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports.default || mod.exports;
}

const en = loadModule('src/i18n/en.js');
const es = loadModule('src/i18n/es.js');
const F = en.finalize;

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

// gateCopy, verbatim from LogbookLockBar.jsx:63 and the ten editors carrying
// the same four lines over the same namespace. Reproduced rather than imported
// because it is a closure over useT declared inside a component.
function gateCopy(code) {
  if (!code) return F.genericError;
  const key = `code_${code}`;
  const copy = F[key];
  return copy && copy !== key ? copy : F.genericError;
}

const NOT_AFFIRMED = 'SUBMIT_SIGNATURE_NOT_AFFIRMED';

console.log('\n-- the code resolves to copy, not to the generic --');
{
  const copy = gateCopy(NOT_AFFIRMED);
  ok(copy !== F.genericError,
    'the new code has copy. Without it the CP gets "could not be finalized, '
    + 'please try again" and no idea which tap fixes it');
  ok(typeof copy === 'string' && copy.length > 0, 'and it is a real string');
}

console.log('\n-- it names AFFIRM as the action --');
{
  const copy = gateCopy(NOT_AFFIRMED);
  ok(/affirm/i.test(copy), 'the copy names affirming');
  ok(/tap/i.test(copy),
    'and names the gesture. The affirmation is a tap on the signature already '
    + 'on screen, not a menu item he has to go looking for');
}

console.log('\n-- and it does NOT send him back to the pad --');
{
  const copy = gateCopy(NOT_AFFIRMED);
  ok(!/not signed/i.test(copy),
    'it does not claim the log is unsigned. It is signed, which is precisely '
    + 'why the old copy misled him');
  ok(/do not need to sign again|without signing again/i.test(copy),
    'and it says so outright. Re-signing re-stamps the SAME unaffirmed '
    + 'credential, so a CP following the old instruction loops');
}

console.log('\n-- the two refusals are distinguishable --');
{
  ok(F.code_SUBMIT_MISSING_CP_SIGNATURE !== F[`code_${NOT_AFFIRMED}`],
    'a missing signature and an unaffirmed one do not share wording');
  ok(/sign it before submitting/i.test(F.code_SUBMIT_MISSING_CP_SIGNATURE),
    'and the genuinely-unsigned case still says Sign, unchanged');
}

console.log('\n-- consistent with the hint the pad already shows --');
{
  // submitNeedsAffirmation is the in-pad hint for this same condition. The
  // refusal a CP meets AFTER tapping Submit must not contradict the hint he
  // was shown before it.
  ok(/affirm/i.test(F.submitNeedsAffirmation), 'the pad hint names affirming');
  ok(/tap/i.test(F.submitNeedsAffirmation),
    'and the same gesture, so the two read as one instruction');
}

console.log('\n-- EN-only, by the rule the catalogue already states --');
{
  // i18n.test.cjs lists `finalize` in EN_ONLY_NAMESPACES and asserts it is
  // ABSENT from es.js; es.js says why in its own header. A logbook is a legal
  // record filed with the DOB and read in English, and Spanish belongs where a
  // WORKER signs. A Spanish key here would fail that test, so this pins the
  // choice rather than leaving it looking like an oversight.
  ok(es.finalize === undefined,
    'es.js still declares no finalize namespace — unchanged by this PR');
}

console.log('\n-- ORDERING: the server does not emit it yet --');
{
  const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
  ok(!server.includes(NOT_AFFIRMED),
    'the server still emits SUBMIT_MISSING_CP_SIGNATURE. INVERT THIS when the '
    + 'server switch lands — it exists so that landing it FIRST is a red check, '
    + 'because a server ahead of the bundle shows genericError on every device '
    + 'that has not fetched this update');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
