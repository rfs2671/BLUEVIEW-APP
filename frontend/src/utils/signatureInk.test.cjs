/**
 * An empty signature is UNSIGNED, everywhere.
 *
 * THE DEFECT. Three places asked "is there a signature OBJECT" when the
 * question was "is there ink", and `{}` — the shape an old bundle wrote, and
 * what production actually held — is truthy, and is not null:
 *
 *   affirmationHintKey     `sig ? ...`             -> "tap your signature to affirm"
 *   SignaturePad           `!!existingSignature`   -> isSigned true
 *   server.py:18817        `{"$ne": None}`         -> classified "unaffirmed"
 *
 * WHAT THAT BUILT. The pad locked itself over a signature that did not exist.
 * With no paths to draw it rendered the literal text "✓ Signed", and because
 * isAffirmed was false it offered AFFIRM. handleAffirm spreads the base object
 * and stamps `affirmed: true` / `affirmedAt`, so the tap produced a signature
 * that was affirmed and contained nothing. That object satisfies
 * isAffirmedSignature, passes the submit gate, and reaches
 * render_signature_html, which finds no `data` and no `paths`, falls to its
 * signer-only branch, and prints
 *
 *     CP Signature: <name> (signed)
 *     ✓ AFFIRMED for this document        <- in green
 *
 * on a record filed with the DOB. The app minted an attestation nobody made,
 * and the tap that did it was the one the CP dashboard told him to make.
 *
 * THIS FILE IS FRONTEND ONLY. The server query at 18817 is unchanged and is
 * sequenced separately; a test below pins that so the two are not confused.
 *
 *   node frontend/src/utils/signatureInk.test.cjs
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
  return mod.exports;
}

const {
  hasSignatureInk, isAffirmedSignature, affirmationHintKey,
} = loadModule('src/utils/signatureAffirmed.js');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

// THE SHAPE PRODUCTION HELD.
const EMPTY = {};
// The inherited credential: a real drawing, never affirmed for this document.
const INHERITED = { paths: [[{ x: 1, y: 2 }]], signerName: 'Roy Fishman', timestamp: '2026-08-19T15:01:10.726Z' };
const AFFIRMED = { ...INHERITED, affirmed: true, affirmedAt: '2026-08-26T12:00:00Z' };

console.log('\n-- the predicate --');
{
  // Checked first so a missing export reads as one named failure rather than a
  // TypeError stack over every assertion below it.
  ok(typeof hasSignatureInk === 'function',
    'signatureAffirmed exports hasSignatureInk — it lives beside '
    + 'isAffirmedSignature because they are the two halves of the same '
    + 'question: is there a mark, and did the signer adopt it for this record');
  if (typeof hasSignatureInk !== 'function') {
    console.log('\n1 passed, 1 failed');
    process.exit(1);
  }
  ok(hasSignatureInk(EMPTY) === false,
    'an empty object has no ink. THE CASE THAT COST: `{}` is truthy and is not '
    + 'null, so it satisfied every presence check in the app');
  ok(hasSignatureInk(null) === false && hasSignatureInk(undefined) === false,
    'and nothing has no ink');
  ok(hasSignatureInk({ paths: [] }) === false,
    'an EMPTY paths array is not "a signature with no strokes", it is no '
    + 'signature — canConfirm requires paths.length > 0, so a real one always '
    + 'carries at least one stroke');
  ok(hasSignatureInk({ data: '' }) === false, 'nor is an empty data string');
  ok(hasSignatureInk('') === false, 'nor is an empty bare string');

  ok(hasSignatureInk(INHERITED) === true, 'vector paths are ink');
  ok(hasSignatureInk({ data: 'iVBORw0KGgo=' }) === true, 'a base64 raster is ink');
  ok(hasSignatureInk('iVBORw0KGgo=') === true,
    'and so is a bare base64 string — render_signature_html treats a str as an '
    + 'image, and handleAffirm wraps one as { data: sig }');

  ok(hasSignatureInk({ paths: 'not-an-array' }) === false,
    'a non-array paths is not ink. PathRenderer calls paths.map, so anything '
    + 'else would crash the pad rather than draw');
  ok(hasSignatureInk({ signerName: 'Roy Fishman', affirmed: true }) === false,
    'A NAME AND A STAMP ARE NOT A SIGNATURE. This is the exact object '
    + 'handleAffirm used to build out of {}, and the one the PDF printed as '
    + 'AFFIRMED in green');
}

console.log('\n-- ink and affirmation are different questions --');
{
  ok(hasSignatureInk(INHERITED) === true && isAffirmedSignature(INHERITED) === false,
    'ink without affirmation: he signed before, never adopted it for this doc');
  ok(hasSignatureInk({ affirmed: true }) === false && isAffirmedSignature({ affirmed: true }) === true,
    'affirmation without ink: the forged shape. NEITHER predicate alone is '
    + 'enough, which is why both live in one module');
  ok(hasSignatureInk(AFFIRMED) === true && isAffirmedSignature(AFFIRMED) === true,
    'a real affirmed signature satisfies both');
}

console.log('\n-- the hint asks for the tap that actually helps --');
{
  ok(affirmationHintKey(EMPTY, true) === 'submitNeedsSignature',
    'AN EMPTY SIGNATURE ASKS HIM TO SIGN. It used to return '
    + 'submitNeedsAffirmation — "tap your signature above to affirm it" — over '
    + 'an empty pad');
  ok(affirmationHintKey({ paths: [] }, true) === 'submitNeedsSignature',
    'and so does an empty stroke list');
  ok(affirmationHintKey(INHERITED, true) === 'submitNeedsAffirmation',
    'a real inherited signature still asks him to affirm — unchanged, and the '
    + 'case the copy was written for');
  ok(affirmationHintKey(AFFIRMED, true) === null, 'an affirmed one asks nothing');
  ok(affirmationHintKey(EMPTY, false) === 'submitSignatureLoading',
    'and the loading state still wins while the profile is resolving, so a '
    + 'slow fetch never tells him to sign something he already has');
}

console.log('\n-- the pad treats an inkless signature as unsigned --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'src/components/SignaturePad.js'), 'utf8');
  const stripped = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');

  ok(!/!!existingSignature/.test(stripped),
    'no presence check on existingSignature survives anywhere in the pad');

  ok(/useState\(autoLock \? hasSignatureInk\(existingSignature\) : false\)/.test(stripped),
    'isSigned is gated on ink. THIS IS THE ONE THAT RENDERED "✓ Signed" and '
    + 'offered Affirm — the Affirm button is behind `isSigned && !isAffirmed`, '
    + 'so an unsigned pad cannot show it');
  ok(/useRef\(hasSignatureInk\(existingSignature\)\)/.test(stripped),
    'and so is isSignedRef, which is what the panResponder consults — a '
    + 'mismatch would lock the draw surface under a pad that reads as unsigned');
  ok(/if \(hasSignatureInk\(existingSignature\)\) \{[\s\S]{0,200}setIsSigned\(true\)/.test(stripped),
    'and the late-arrival effect too. THE PATH THAT ACTUALLY FIRED IN THE '
    + 'FIELD: the cached credential resolves after mount, so initial state saw '
    + 'null and this effect saw the signature');
  ok(/useState\(\s*hasSignatureInk\(existingSignature\) \? existingSignature : null,?\s*\)/.test(stripped),
    'and signatureData never holds an inkless object — it is what handleAffirm '
    + 'spreads, so it is the raw material the bad attestation was built from');
}

console.log('\n-- handleAffirm refuses if it is ever reached --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'src/components/SignaturePad.js'), 'utf8');
  const i = src.indexOf('const handleAffirm');
  ok(i > -1, 'handleAffirm exists');
  // COMMENTS STRIPPED. The ordering assertion below searches for `affirmed:
  // true`, and the comment explaining the guard quotes that literal — so an
  // unstripped body matches the prose and passes whatever the code does.
  const body = src.slice(i, src.indexOf('}, [signatureData', i))
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');

  ok(/if \(!hasSignatureInk\(base\)\) return;/.test(body),
    'it refuses on no ink');
  ok(body.indexOf('if (!hasSignatureInk(base)) return;') < body.indexOf('affirmed: true'),
    'AND IT REFUSES BEFORE THE STAMP. Nothing downstream asks again: past this '
    + 'line the object is affirmed, isAffirmedSignature says yes, the submit '
    + 'gate lets it through, and the PDF prints it in green');
  ok(/const base = /.test(body) && body.indexOf('const base =') < body.indexOf('hasSignatureInk(base)'),
    'and it checks `base`, not the raw state, so a bare string wrapped as '
    + '{ data: sig } is judged on the same rule');
}

console.log('\n-- the PDF branch this closes --');
{
  // render_signature_html: no `data`, no drawable `paths`, but a signer name ->
  // "<name> (signed)" plus the affirmation banner. The banner is green whenever
  // _is_affirmed_signature passes, and it does not ask about ink. The frontend
  // fix is what stops such an object being MINTED; this pins that the branch it
  // would land in is still there and still unguarded, so nobody assumes the
  // server got a matching fix in this PR.
  const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
  const i = server.indexOf('def render_signature_html');
  const body = server.slice(i, server.indexOf('def _filed_log', i));
  ok(/\(signed\)/.test(body),
    'the signer-only branch still exists — the server half is NOT in this PR');
  ok(/if not sig:\s*\n\s*return ""/.test(body),
    'and it still only short-circuits on a FALSY sig, which `{}` is not in '
    + 'Python either');
}

console.log('\n-- scope: the server query is untouched --');
{
  const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
  ok(server.includes('"cp_signature": {"$ne": None},'),
    'the attestation_gaps query still classifies {} as unaffirmed. INVERT WHEN '
    + 'THE SERVER HALF LANDS — it is sequenced separately and deliberately, and '
    + 'this pins that a frontend-only PR did not quietly change it');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
