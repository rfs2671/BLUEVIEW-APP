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

// MOVED. The predicate was private to SignaturePad, which is exactly why the
// nine submit gates could not use it and asked `!cpSignature` instead — a
// question `{}` answers yes to. It now lives in src/utils/signatureAffirmed.js
// and the pad aliases it. This file keeps asserting the RULE (and that
// useCpProfile still strips the stamp, so it can never be inherited); the gate
// side is signatureAffirmed.test.cjs.
const AFFIRMED_MOD = path.join(__dirname, 'signatureAffirmed.js');
const sigIsAffirmed = extractFn(AFFIRMED_MOD, 'isAffirmedSignature');
// The pad must still USE it, or the VERIFIED stamp it renders and the rule
// asserted here would drift apart.
const PAD_SRC = fs.readFileSync(SIG, 'utf8');
// MOVED, NOT DELETED. useCpProfile used to declare this inline as
// `function stripAffirmation(sig) { const { affirmed, affirmedAt, ...rest } }`
// — an inline field list that diverged from the attestation when affirmedLang
// shipped, which is how two logs on 2026-08-25 carried a language nobody
// affirmed in. The rule now lives beside the predicate that defines it, driven
// by PER_DOCUMENT_SIGNATURE_FIELDS, and the hook aliases it.
//
// LOADED, NOT TEXT-EXTRACTED. extractFn evaluates a function body in
// isolation, so it cannot see a module-level constant — which is precisely the
// limit that makes a list-driven rule untestable by text. This transpiles the
// real module and takes the real export.
const stripAffirmation = (() => {
  const babel = require('@babel/core');
  const { code } = babel.transformSync(fs.readFileSync(AFFIRMED_MOD, 'utf8'), {
    filename: AFFIRMED_MOD,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports.toCredential;
})();

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// THE NAMED IMPORT, not the exact brace contents. This pinned
// `{ isAffirmedSignature }` literally and broke when hasSignatureInk was
// added to the same import — a syntax pin failing on a correct change.
ok(/import \{[^}]*isAffirmedSignature[^}]*\} from '\.\.\/utils\/signatureAffirmed'/.test(PAD_SRC),
  'SignaturePad imports the shared predicate rather than owning a copy');
ok(/const sigIsAffirmed = isAffirmedSignature;/.test(PAD_SRC),
  'and its local name is an ALIAS, so every use in the pad is the shared rule');

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
