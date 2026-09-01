/**
 * EVERY SCREEN THAT SIGNS ASKS FIRST — and a fourteenth cannot ship without.
 *
 * ── WHY A CENSUS ────────────────────────────────────────────────────────────
 *
 * The gate is one line per editor. One line is easy to add and just as easy to
 * omit, and an omission is invisible: the screen works, the log files, the
 * signature lands. Nothing fails. The only symptom is a compliance record
 * signed without a recorded agreement — which is the exact defect that
 * accumulated 248 times before anyone noticed, because nothing was counting.
 *
 * So this counts. It walks app/ for every call to recordSignatureEvent and
 * requires each one to sit behind `consent.ensure()`. A new editor is caught
 * by construction rather than by review.
 *
 * ── AND IT CHECKS ORDER, NOT JUST PRESENCE ──────────────────────────────────
 *
 * A gate placed after the signature is applied is not a gate. Each file must
 * reach `ensure()` BEFORE it reaches the write that persists a signature.
 *
 *   node src/utils/consentGateCensus.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const APP = path.join(FRONTEND, 'app');

/** Comments stripped — every file here documents its own gate at length. */
const CODE = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

const walk = (d, out = []) => {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.jsx?$/.test(e.name)) out.push(p);
  }
  return out;
};

const signing = walk(APP)
  .map((f) => [path.relative(APP, f).split(path.sep).join('/'),
    CODE(fs.readFileSync(f, 'utf8').split('\r\n').join('\n'))])
  .filter(([, src]) => /recordSignatureEvent\s*\(/.test(src));

console.log('\n1. THE CENSUS');
{
  ok(signing.length === 13,
    `ANCHOR: 13 screens apply a signature (${signing.length}) — `
    + `${signing.map(([f]) => f.replace('logbooks/', '')).join(', ')}`);
}

console.log('\n2. EVERY ONE OF THEM ASKS');
{
  for (const [file, src] of signing) {
    ok(/consent\.ensure\(\)/.test(src), `${file} calls consent.ensure()`);
  }
}

console.log('\n3. AND ASKS BEFORE IT SIGNS');
{
  // MEASURED INSIDE THE HANDLER, not across the file.
  //
  // The first version of this compared `indexOf('consent.ensure()')` with
  // `indexOf('persistAndPush(')` over the whole source and reported all twelve
  // editors as broken. They were not: persistAndPush is DEFINED near the top of
  // the file and CALLED near the bottom, so the comparison was measuring the
  // position of a definition against the position of a call. A positional
  // check standing in for an ordering property — the same shape this codebase
  // keeps finding, and it failed loudly here only by luck.
  //
  // What matters is that nothing in the handler persists a signature before the
  // handler asks. So: slice from the start of the enclosing handler to the
  // gate, and require that slice to be clean.
  const WRITES = [
    'persistAndPush(', 'writeDraft(', 'logbooksAPI.create(', 'logbooksAPI.update(',
  ];
  for (const [file, src] of signing) {
    const gate = src.indexOf('consent.ensure()');
    if (gate < 0) { ok(false, `${file}: no gate to place`); continue; }
    // The nearest declaration at component indent, searching backwards.
    const before = src.slice(0, gate);
    const handlerStart = Math.max(
      before.lastIndexOf('\n  const '),
      before.lastIndexOf('\n  async function '),
    );
    const slice = src.slice(handlerStart < 0 ? 0 : handlerStart, gate);
    const early = WRITES.filter((w) => slice.includes(w));
    ok(early.length === 0,
      `${file}: nothing persists a signature before the gate`
      + (early.length ? ` — found ${JSON.stringify(early)}` : ''));
  }
}

console.log('\n3b. AND A DRAFT IS NOT A SIGNATURE');
{
  // preshift_signin's ONE handler serves both buttons — Save Draft and Submit
  // & Sign — so its gate has to be conditional. Gating the draft would stop a
  // CP saving his work for a reason that has nothing to do with drafts, and
  // would do it at a gate, on the sheet with the worst signal on site.
  //
  // A control run caught the absence of this: widening the condition to gate
  // everything passed every other assertion in the file.
  const [, preshift] = signing.find(([f]) => f.endsWith('preshift_signin.jsx'));
  ok(/if \(submitStatus === 'submitted' && !\(await consent\.ensure\(\)\)\) return;/
    .test(preshift),
  'preshift_signin gates the SUBMIT only, never the draft save');

  // The orientation editor has two signing entry points and one handler they
  // both reach. Gating that handler covers both; gating a caller would not.
  const [, orient] = signing.find(([f]) => f.endsWith('subcontractor_orientation.jsx'));
  const gateAt = orient.indexOf('consent.ensure()');
  const handlerAt = orient.indexOf('const handleSignExisting');
  ok(handlerAt >= 0 && gateAt > handlerAt,
    'the orientation gate sits in handleSignExisting, which both entry points reach');
}

console.log('\n4. THE GATE ITSELF');
{
  const hook = CODE(fs.readFileSync(
    path.join(FRONTEND, 'src', 'hooks', 'useEsraConsent.js'), 'utf8'));

  ok(/router\.push\('\/consent'\)/.test(hook) && !/router\.replace/.test(hook),
    'it PUSHES to the agreement, so the editor stays mounted beneath it');

  // THE CACHE IS CONSULTED ONLY WHEN THE SERVER COULD NOT ANSWER. Consulting
  // it against a server "no" could only ever overturn a real refusal with a
  // stale yes — the cache holds nothing else.
  ok(/if \(next === UNKNOWN\) \{[\s\S]{0,200}readConsent\(userId\)/.test(hook),
    'the remembered consent is read ONLY on UNKNOWN, never against a server no');
  ok(hook.indexOf('canSign(next)') < hook.indexOf('readConsent(userId)'),
    'and only after the server has been given the chance to answer');
}

console.log('\n5. ONLY A YES IS EVER REMEMBERED');
{
  // The stub is held so the test can plant a CORRUPT entry directly — the
  // module has no writer that could produce one, which is the point.
  const mem = new Map();
  const store = {
    setItem: async (k, v) => { mem.set(k, v); },
    getItem: async (k) => (mem.has(k) ? mem.get(k) : null),
    removeItem: async (k) => { mem.delete(k); },
  };
  const C = loadEsm('src/utils/consentCache.js', {
    stubs: { '@react-native-async-storage/async-storage': store },
  });
  C.__store = store;

  const run = async () => {
    ok(await C.readConsent('u1') === null,
      'nothing remembered reads as null — NOT as a refusal');
    await C.rememberConsent('u1', '2026-08-30.1');
    const got = await C.readConsent('u1');
    ok(got && got.version === '2026-08-30.1', 'a yes is remembered, with its version');
    ok(await C.readConsent('u2') === null,
      'and it is keyed per person — another account inherits nothing');

    // THE POINT OF THE WHOLE MODULE. There is no writer of a negative, so a
    // refusal can never be cached and can never lock a man out offline.
    const src = CODE(fs.readFileSync(
      path.join(FRONTEND, 'src', 'utils', 'consentCache.js'), 'utf8'));
    const setters = src.match(/setItem\(/g) || [];
    ok(setters.length === 1,
      `exactly one writer (${setters.length}) — there is no path that stores a no`);
    ok(!/false|declined|denied/i.test(src.replace(/return false;/g, '')),
      'and nothing in it names a negative state to store');

    // A MALFORMED ENTRY IS NOT A YES. The cache is permission to sign; it has
    // to be readable to be believed. A control run made a corrupt entry count
    // as consent and every other assertion here still passed.
    const store = C.__store;
    await store.setItem('esra_consent_ok:u3', 'not json at all');
    ok(await C.readConsent('u3') === null, 'unparseable is nothing remembered');
    await store.setItem('esra_consent_ok:u4', '"a string"');
    ok(await C.readConsent('u4') === null, 'a non-object is nothing remembered');
    await store.setItem('esra_consent_ok:u5', 'null');
    ok(await C.readConsent('u5') === null, 'a literal null is nothing remembered');

    await C.forgetConsent('u1');
    ok(await C.readConsent('u1') === null, 'and it can be forgotten');
  };

  run().then(() => {
    console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
    process.exit(failures === 0 ? 0 : 1);
  });
}
