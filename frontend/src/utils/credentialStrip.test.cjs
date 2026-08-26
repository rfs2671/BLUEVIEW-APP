/**
 * A reusable credential carries no per-document attestation.
 *
 * WHAT HAPPENED. useCpProfile's strip was written as
 *
 *     const { affirmed, affirmedAt, ...credential } = sig;
 *
 * which was correct when the attestation had two fields. `affirmedLang` was
 * added to the attestation later, by a different commit, and nobody widened the
 * strip. So the CP's cached credential kept carrying it, and two logs filed on
 * 2026-08-25 (preshift_signin 12:12, toolbox_talk 12:15) stored:
 *
 *     timestamp:    '2026-08-19T15:01:10.726Z'   the credential's capture instant
 *     paths:        byte-identical to the 08-19 daily_jobsite signature
 *     affirmedLang: 'en'                          PRESENT
 *     affirmed:                                   ABSENT
 *     affirmedAt:                                 ABSENT
 *
 * A filed compliance record asserting the signer was shown English, on a
 * document he never affirmed at all.
 *
 * THE TEST IS KEYED OFF THE LIST, NOT OFF THREE LITERALS. Asserting
 * `affirmed`/`affirmedAt`/`affirmedLang` by name would reproduce the original
 * defect one field later: the next attestation field would ship, the strip
 * would miss it, and this test would still pass. So it reads
 * PER_DOCUMENT_SIGNATURE_FIELDS and asserts the strip removes EVERY member,
 * whatever the list becomes.
 *
 * BEHAVIOURAL, not textual. Most suites here read source as text; that cannot
 * tell a list-driven strip from a hardcoded one that happens to name the same
 * fields today. This transpiles the real module and runs it.
 *
 *   node frontend/src/utils/credentialStrip.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');

/** Load an ES module from source by transpiling it to CJS and evaluating it. */
function loadModule(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    // The ONE transform needed: ESM -> CJS. preset-env is not a dependency
    // here, and pulling one in for a test would be a heavier ask than the job.
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}

const SA = loadModule('src/utils/signatureAffirmed.js');
const FIELDS = SA.PER_DOCUMENT_SIGNATURE_FIELDS;
const toCredential = SA.toCredential;

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

console.log('\n-- the list is the contract --');
{
  ok(Array.isArray(FIELDS) && FIELDS.length > 0,
    `ANCHOR: PER_DOCUMENT_SIGNATURE_FIELDS is a non-empty list (${JSON.stringify(FIELDS)})`);
  ok(Object.isFrozen(FIELDS),
    'frozen — a caller cannot widen or narrow the rule at runtime');
  ok(FIELDS.includes('affirmedLang'),
    'affirmedLang IS a per-document field. It records what the signer was '
    + 'SHOWN, which is a fact about one act of signing, and carrying it made '
    + 'a filed log assert a language nobody affirmed in');
  ok(FIELDS.includes('affirmed') && FIELDS.includes('affirmedAt'),
    'alongside the two the original strip already named');
}

console.log('\n-- every member of the list is stripped, whatever the list becomes --');
{
  // Built FROM the list, so adding a field to the attestation and forgetting
  // the strip fails here rather than shipping.
  const attested = { paths: 'p', signerName: 'Roy Fishman', timestamp: 'T' };
  for (const f of FIELDS) attested[f] = 'SET';

  const credential = toCredential(attested);
  const leaked = FIELDS.filter((f) => f in credential);
  ok(leaked.length === 0,
    `no per-document field survives. Leaked: ${JSON.stringify(leaked)}`);

  ok(credential.paths === 'p' && credential.signerName === 'Roy Fishman',
    'and the CREDENTIAL half is kept — this strips an attestation, it does '
    + 'not discard the signature');
}

console.log('\n-- the exact production shape no longer survives a round trip --');
{
  // The 2026-08-19 signature, as stored, and what the 08-25 logs actually held.
  const affirmedOn0819 = {
    paths: 'PATHS-0819',
    signerName: 'Roy Fishman',
    timestamp: '2026-08-19T15:01:10.726Z',
    affirmed: true,
    affirmedAt: '2026-08-19T15:01:10.726Z',
    affirmedLang: 'en',
  };
  const credential = toCredential(affirmedOn0819);

  ok(!('affirmedLang' in credential),
    'affirmedLang is gone — this is the field that shipped on both 08-25 logs');
  ok(SA.isAffirmedSignature(affirmedOn0819) === true,
    'ANCHOR: the original WAS affirmed');
  ok(SA.isAffirmedSignature(credential) === false,
    'and the credential is NOT — so it cannot satisfy a submit gate, which is '
    + 'the whole purpose of stripping it');
}

console.log('\n-- timestamp is deliberately NOT stripped, and that is a live gap --');
{
  const credential = toCredential({ paths: 'p', timestamp: '2026-08-19T15:01:10.726Z' });
  ok(credential.timestamp === '2026-08-19T15:01:10.726Z',
    'timestamp SURVIVES, pinned deliberately rather than left ambiguous. It is '
    + 'why both 08-25 logs claim the 08-19 instant. Removing it changes what '
    + 'SignaturePad renders beside an inherited signature, so it is a separate '
    + 'decision — reported, not bundled in. If it is ever added to the list, '
    + 'this assertion is the one to invert');
}

console.log('\n-- useCpProfile no longer owns a second copy of the rule --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'src/hooks/useCpProfile.js'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(/toCredential/.test(code),
    'it delegates to the shared helper');
  ok(!/const\s*{\s*affirmed\s*,/.test(code),
    'and no longer destructures the fields inline — an inline list is what '
    + 'diverged from the attestation in the first place');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
