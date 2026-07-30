/**
 * PR A — per-document signature affirmation, client-side pure logic.
 *
 * Two invariants:
 *   - SignaturePad.sigIsAffirmed(sig): a signature counts as affirmed for the
 *     document in view ONLY when it carries sig.affirmed === true. An inherited
 *     profile credential (or a raw string) is NOT affirmed → renders UNAFFIRMED,
 *     never VERIFIED.
 *   - useCpProfile.stripAffirmation(sig): the reusable profile credential must
 *     never carry a per-document affirmation stamp, or the NEXT document would
 *     inherit affirmed:true and render VERIFIED without its own affirmation.
 *
 * Following the repo's source-extraction test pattern, this reads the REAL
 * component/hook source and evaluates the two shipped functions VERBATIM.
 *
 * Run:  node src/utils/signatureAffirmation.test.cjs
 */

const fs = require('fs');
const path = require('path');

function extractFn(file, fnName) {
  const src = fs.readFileSync(file, 'utf8');
  const anchor = `function ${fnName}(`;
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`${fnName} not found in ${path.basename(file)}`);
  const braceOpen = src.indexOf('{', at);
  let depth = 0;
  let i = braceOpen;
  for (; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') { depth -= 1; if (depth === 0) { i += 1; break; } }
  }
  const body = src.slice(at, i);
  // eslint-disable-next-line no-new-func
  return new Function(`${body}\nreturn ${fnName};`)();
}

const SIG = path.join(__dirname, '..', 'components', 'SignaturePad.js');
const HOOK = path.join(__dirname, '..', 'hooks', 'useCpProfile.js');

const sigIsAffirmed = extractFn(SIG, 'sigIsAffirmed');
const stripAffirmation = extractFn(HOOK, 'stripAffirmation');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── sigIsAffirmed ──
ok(sigIsAffirmed({ affirmed: true }) === true, 'affirmed:true -> affirmed');
ok(sigIsAffirmed({ paths: [], signerName: 'x', timestamp: 't' }) === false,
  'inherited credential (no affirmed) -> NOT affirmed');
ok(sigIsAffirmed({ affirmed: false }) === false, 'affirmed:false -> NOT affirmed');
ok(sigIsAffirmed(null) === false, 'null -> NOT affirmed');
ok(sigIsAffirmed('base64string') === false, 'raw string -> NOT affirmed');

// ── stripAffirmation ──
const affirmed = { paths: [[{ x: 1, y: 2 }]], signerName: 'Ada', timestamp: 't0', affirmed: true, affirmedAt: 't1' };
const stripped = stripAffirmation(affirmed);
ok(!('affirmed' in stripped), 'strip removes affirmed');
ok(!('affirmedAt' in stripped), 'strip removes affirmedAt');
ok(stripped.paths === affirmed.paths && stripped.signerName === 'Ada' && stripped.timestamp === 't0',
  'strip keeps paths/signerName/timestamp (the credential)');
// The stripped credential must itself read as UNAFFIRMED — proving no leak.
ok(sigIsAffirmed(stripped) === false, 'stripped credential is NOT affirmed (no profile leak)');
ok(stripAffirmation('rawstring') === 'rawstring', 'strip passes a raw string through');
ok(stripAffirmation(null) === null, 'strip passes null through');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
