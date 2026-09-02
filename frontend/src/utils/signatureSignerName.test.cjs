/**
 * THE SIGNER'S NAME, READ FROM THE KEY THAT IS ACTUALLY WRITTEN.
 *
 * A dead Pydantic model — `SignatureData` in server.py, whose only occurrence
 * in the backend was its own definition — declared `signer_name` and
 * `signed_at`. It validated nothing: `DailyLogCreate.superintendent_signature`
 * is a bare `Optional[Dict]`, so SignaturePad's real payload
 * ({paths, signerName, timestamp, affirmed, affirmedAt, affirmedLang}) was
 * stored verbatim. Every reader in the app was written against the
 * DECLARATION rather than the stored data, so each one read a key no writer
 * has ever written:
 *
 *   daily-log.jsx        prefill    the name vanished when a log was reopened
 *   daily-log.jsx        modal      the previous-log signature rendered blank
 *   site/daily-logs.jsx  both       the same two, on the superintendent's twin
 *   site/logbooks.jsx    block      the signature block lost its name
 *   server.py            the PDF    printed "Superintendent (Superintendent)"
 *
 * `signed_at` is written by NO writer anywhere, so every reader of it got
 * undefined and printed a bare "Signed:" with nothing after it.
 *
 * The stored shape is production and thousands of filed documents carry it.
 * The readers are what is wrong, and both spellings must be read because
 * legacy records may carry either — the precedent is render_signature_html's
 * `sig.get("signer_name") or sig.get("signerName") or ""`.
 *
 * Run:  node src/utils/signatureSignerName.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const APP = path.join(UTILS, '..', '..', 'app');

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
  return { signatureSignerName, signatureSignedAt };`)();

// EXACTLY what SignaturePad.js writes on confirm.
const REAL = {
  paths: [[{ x: 1, y: 2 }]],
  signerName: 'Roy Fishman',
  timestamp: '2026-08-19T15:01:10.726Z',
  affirmed: true,
  affirmedAt: '2026-08-19T15:30:00.000Z',
  affirmedLang: 'en',
};

console.log('\n-- the name comes back from the REAL payload --');
ok(M.signatureSignerName(REAL) === 'Roy Fishman',
  "SignaturePad's signerName is read — this is the whole defect");
ok(M.signatureSignerName({ signer_name: 'Legacy Lou' }) === 'Legacy Lou',
  'the legacy snake_case spelling still reads — filed documents carry it');
ok(M.signatureSignerName({ signer_name: 'Snake', signerName: 'Camel' }) === 'Snake',
  'snake_case wins when both are present, matching render_signature_html');

console.log('\n-- an absent name is BLANK, never a role label --');
ok(M.signatureSignerName({ paths: [[{ x: 1, y: 2 }]] }) === '',
  'a signature with no name returns empty, so callers can suppress the field');
ok(M.signatureSignerName({}) === '', 'an empty object has no signer');
ok(M.signatureSignerName(null) === '' && M.signatureSignerName(undefined) === '',
  'null and undefined are safe');
ok(M.signatureSignerName('data:image/png;base64,iVBOR') === '',
  'a legacy base64 string carries no name');

console.log('\n-- the signing time resolves the way the backend resolves it --');
ok(M.signatureSignedAt(REAL) === '2026-08-19T15:30:00.000Z',
  'affirmedAt wins — the moment the signer adopted THIS document');
ok(M.signatureSignedAt({ timestamp: '2026-08-19T15:01:10.726Z' })
  === '2026-08-19T15:01:10.726Z',
  'timestamp is the fallback when nothing was affirmed');
ok(M.signatureSignedAt({ signed_at: '2026-01-01T00:00:00Z' })
  === '2026-01-01T00:00:00Z',
  'a legacy signed_at is still honoured if some record carries one');
ok(M.signatureSignedAt({ paths: [] }) === '',
  'NO WRITER WRITES signed_at, so the common case must return empty...');
ok(M.signatureSignedAt(null) === '' && M.signatureSignedAt({}) === '',
  '...rather than undefined reaching formatTimestamp');

// ── The screens that were reading the dead keys ─────────────────────────────
//
// Asserted against source because these are React Native screens that need a
// device to render. The point is narrow and greppable: no screen may reach
// into a signature for `.signer_name` or `.signed_at` on its own again.

const SCREENS = [
  ['daily-log.jsx', path.join(APP, 'daily-log.jsx')],
  ['site/daily-logs.jsx', path.join(APP, 'site', 'daily-logs.jsx')],
  ['site/logbooks.jsx', path.join(APP, 'site', 'logbooks.jsx')],
];

console.log('\n-- no screen reads the dead keys by hand any more --');
for (const [label, file] of SCREENS) {
  const src = fs.readFileSync(file, 'utf8');
  ok(!/signature[A-Za-z_]*\??\.signer_name/.test(src)
     && !/_signature\.signer_name/.test(src),
    `${label}: no bare .signer_name read`);
  ok(!/_signature\.signed_at/.test(src)
     && !/signature\??\.signed_at/.test(src),
    `${label}: no bare .signed_at read`);
  ok(/signatureSignerName/.test(src),
    `${label}: uses the shared reader instead`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
