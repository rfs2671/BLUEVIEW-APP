/**
 * THE AFFIRMATION LANGUAGE IS FROZEN ONTO THE SIGNATURE.
 *
 * A person signs a sentence. Which language that sentence was in is evidence
 * about what they were shown, so it is recorded next to affirmedAt —
 * subcontractor_orientation.jsx already does the same thing with
 * language_provided.
 *
 * THE HAZARD THIS PINS. The pad's language toggle stays usable AFTER signing.
 * If affirmedLang tracked live toggle state, the record would silently rewrite
 * what it claims a person was shown — a document that changes after the fact,
 * which is worse than recording nothing. So the value is captured inside the
 * affirm handlers and never read back out of state.
 *
 * Both handlers are extracted VERBATIM from the shipped component by brace
 * matching (the technique src/utils/checkinCardGate.test.cjs uses) and executed
 * against stubs. Nothing here re-implements the logic under test.
 *
 * Run:  node src/utils/signatureAffirmedLang.test.cjs
 */
const fs = require('fs');
const path = require('path');

const babel = require('@babel/core');

const PAD = path.join(__dirname, '..', 'components', 'SignaturePad.js');
const padSrc = fs.readFileSync(PAD, 'utf8');

/**
 * THE REAL hasSignatureInk, loaded rather than stubbed.
 *
 * handleAffirm now refuses on no ink, so the extracted body closes over that
 * predicate. A stub here would let this harness pass while the shipped guard
 * did something else — and "nothing here re-implements the logic under test"
 * is the rule this file was written under.
 */
function loadSignatureAffirmed() {
  const file = path.join(__dirname, 'signatureAffirmed.js');
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}
const { hasSignatureInk } = loadSignatureAffirmed();

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** The body of `const <name> = useCallback(() => { ... }` , brace matched. */
function extractHandler(name) {
  const start = padSrc.indexOf(`const ${name} = useCallback(() => {`);
  if (start === -1) return null;
  const open = padSrc.indexOf('{', padSrc.indexOf('=> {', start));
  let depth = 0;
  for (let i = open; i < padSrc.length; i += 1) {
    if (padSrc[i] === '{') depth += 1;
    else if (padSrc[i] === '}') {
      depth -= 1;
      if (depth === 0) return padSrc.slice(open + 1, i);
    }
  }
  return null;
}

const affirmBody = extractHandler('handleAffirm');
const confirmBody = extractHandler('handleConfirm');
ok(!!affirmBody, 'handleAffirm extracted from the shipped source');
ok(!!confirmBody, 'handleConfirm extracted from the shipped source');

/** Run a handler body with an injected closure. Returns what it emitted. */
function runHandler(body, closure) {
  const emitted = [];
  const env = {
    ...closure,
    hasSignatureInk,
    onSignatureCapture: (sig) => emitted.push(sig),
    setSignatureData: () => {},
    setIsAffirmed: () => {},
    setIsSigned: () => {},
    isSignedRef: { current: false },
  };
  const names = Object.keys(env);
  // eslint-disable-next-line no-new-func
  new Function(...names, body)(...names.map((n) => env[n]));
  return emitted;
}

// ── 1. what the signer was shown is what gets recorded ──────────────────────
{
  const emitted = runHandler(affirmBody, {
    signatureData: { paths: [[1, 2]] },
    signerName: 'Carl CP',
    activeLang: 'es',
  });
  ok(emitted.length === 1, 'affirm: emits exactly one signature');
  ok(emitted[0].affirmedLang === 'es',
    'affirm: a Spanish affirmation records affirmedLang "es"');
  ok(typeof emitted[0].affirmedAt === 'string' && emitted[0].affirmedAt.length > 0,
    'affirm: still stamps affirmedAt beside it');
  ok(emitted[0].affirmed === true, 'affirm: still marks the document affirmed');
}
{
  const emitted = runHandler(confirmBody, {
    canConfirm: true,
    pathsRef: { current: [[3, 4]] },
    signerName: 'Carl CP',
    activeLang: 'es',
  });
  ok(emitted.length === 1 && emitted[0].affirmedLang === 'es',
    'fresh draw: a Spanish signature records affirmedLang "es" too');
}

// ── 2. THE RULING'S TEST — sign in Spanish, flip to English, value holds ────
{
  // Sign while the pad is showing Spanish.
  const signed = runHandler(affirmBody, {
    signatureData: { paths: [[1, 2]] },
    signerName: 'Carl CP',
    activeLang: 'es',
  })[0];
  ok(signed.affirmedLang === 'es', 'signed in Spanish');

  // Now the CP flips the toggle to English. The pad re-renders with a new
  // activeLang; the signature already emitted must not move with it.
  const afterToggle = runHandler(affirmBody, {
    signatureData: signed,          // the record as it stands
    signerName: 'Carl CP',
    activeLang: 'en',               // toggle flipped
  });
  ok(signed.affirmedLang === 'es',
    'flipping the toggle does NOT rewrite the signature already recorded');
  ok(typeof signed.affirmedLang === 'string',
    'the recorded value is a plain string, not a live reference to state');

  // And re-affirming IS a new act, so it legitimately records the new language.
  ok(afterToggle[0].affirmedLang === 'en',
    're-affirming after the flip records "en" — a new affirmation, newly shown');
  // Asserted structurally, not by comparing the two timestamps: both calls run
  // inside the same millisecond here, so toISOString() returns the same string
  // and an inequality check would fail on a correct implementation. What is
  // actually being pinned is that each affirmation computes its OWN `now`
  // rather than inheriting the previous one through the object spread.
  ok(/const now = new Date\(\)\.toISOString\(\);/.test(affirmBody),
    're-affirming computes a FRESH affirmedAt rather than inheriting the old one');
  ok(/timestamp: now,\s*affirmed: true,\s*affirmedAt: now,/.test(affirmBody),
    're-affirming overwrites the spread base with the fresh stamp');
}

// ── 3. it is written ONCE, never recomputed on render ───────────────────────
const writes = (padSrc.match(/affirmedLang:/g) || []).length;
ok(writes === 2, `affirmedLang is written in exactly the 2 affirm handlers (got ${writes})`);
ok(!/affirmedLang\s*=/.test(padSrc),
  'affirmedLang is never reassigned after it is stamped');
// Anything that READ it back into the rendered value would let the toggle
// rewrite history. The only permitted reads are none.
ok(!/signatureData\??\.affirmedLang/.test(padSrc),
  'the render path never reads affirmedLang back out of state');

// ── 4. the value can never be undefined ────────────────────────────────────
// "shown in en" is a fact; undefined is not. activeLang resolves through the
// app locale so there is always a concrete answer.
ok(/const activeLang = lang \?\? padLang \?\? appLocale;/.test(padSrc),
  'activeLang resolves to a concrete locale, so affirmedLang is never undefined');
{
  // FIXTURE CORRECTED. This passed `signatureData: {}` and called it "an
  // untouched pad". An untouched pad is exactly what handleAffirm now REFUSES:
  // `{}` has no ink, and stamping affirmed onto it produced the attestation
  // that printed "✓ AFFIRMED for this document" in green over a blank. The
  // claim under test — affirmedLang is a concrete locale, never undefined — is
  // unchanged, and is now made against a signature that exists.
  const emitted = runHandler(affirmBody, {
    signatureData: { paths: [[1, 2]] },
    signerName: 'X',
    activeLang: 'en',            // the resolved default
  });
  ok(emitted[0].affirmedLang === 'en', 'a resolved default records "en", not undefined');
}

// ── 5. an inkless signature is never affirmed ──────────────────────────────
// The guard, executed against the shipped handler rather than read out of it.
{
  const emitted = runHandler(affirmBody, {
    signatureData: {},
    signerName: 'X',
    activeLang: 'en',
  });
  ok(emitted.length === 0,
    'handleAffirm emits NOTHING for an empty signature. It used to emit '
    + '{ signerName, timestamp, affirmed: true, affirmedAt, affirmedLang } — '
    + 'affirmed, and containing no signature');
}
{
  const emitted = runHandler(affirmBody, {
    signatureData: { paths: [] },
    signerName: 'X',
    activeLang: 'en',
  });
  ok(emitted.length === 0, 'nor for an empty stroke list');
}
{
  // Unchanged behaviour, pinned so the guard cannot be widened by accident: a
  // real inherited credential is still affirmable, which is the entire point
  // of the Affirm button.
  const emitted = runHandler(affirmBody, {
    signatureData: { paths: [[1, 2]], signerName: 'Roy', timestamp: '2026-08-19T15:01:10.726Z' },
    signerName: 'Roy',
    activeLang: 'en',
  });
  ok(emitted.length === 1 && emitted[0].affirmed === true,
    'and a REAL inherited credential still affirms — the guard refuses empty '
    + 'signatures, not inherited ones');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('ALL PASSED');
