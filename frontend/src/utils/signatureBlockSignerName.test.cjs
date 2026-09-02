/**
 * THE INSPECTOR'S COPY OF A SIGNED LOG SHOWED NEITHER AN IMAGE NOR A NAME.
 *
 * `SignatureBlock` in app/site/logbooks.jsx read one spelling:
 *
 *     signerName = signature.signer_name || '';
 *
 * SignaturePad — the only thing in the app that makes a signature — writes the
 * other:
 *
 *     const sigData = { paths, signerName: signerName?.trim(), timestamp, ... };
 *
 * snake_case reader, camelCase writer. A reader naming a field no writer
 * produces, so `signerName` was ALWAYS `''`.
 *
 * WHY THAT LEFT THE BLOCK COMPLETELY EMPTY rather than merely unlabelled. The
 * component has two branches and the name is the fallback for both:
 *
 *     {base64Data && typeof base64Data === 'string' ? <Image .../>
 *       : signerName ? <Text>{signerName} (signed)</Text> : null}
 *
 * `base64Data` is `signature.data || signature.paths`. A drawn signature has
 * no `.data` — it has `.paths`, an ARRAY of stroke arrays — so the string test
 * fails and the image branch is skipped. Then the name branch was empty too.
 * Two independent conditions, both false, and the whole thing collapsed to the
 * bare label: "COMPETENT PERSON" over nothing. On the screen a site inspector
 * uses to read a filed compliance record.
 *
 * WHAT IS FIXED HERE AND WHAT IS NOT. The NAME only:
 *
 *     signerName = signature.signer_name || signature.signerName || '';
 *
 * BOTH spellings, not a swap. Documents already in the collection carry
 * either: SignaturePad has always written `signerName`, and server.py's own
 * renderer at render_signature_html reads `sig.get("signer_name") or
 * sig.get("signerName")` — the same both-spellings read, which is the
 * precedent this follows rather than invents.
 *
 * The IMAGE branch is deliberately left alone. Drawing a `paths` array needs a
 * vector renderer (the backend has one — `_signature_paths_to_svg` — and React
 * Native has no <svg>), which is a rendering decision, not a field-name bug.
 * The name branch is what makes the block legible in the meantime, and it is
 * asserted below that the name branch is the one that runs for a `paths`
 * signature — because if the image branch ever starts matching, this test
 * should say so.
 *
 * HOW THIS TEST WORKS. It does not grep. It slices the REAL derivation out of
 * the shipped screen — everything between the component's opening line and its
 * `return (` is plain JavaScript, no JSX — and executes it against real
 * signature objects. A regex would pass against a comment; this runs the code.
 *
 * Run:  node src/utils/signatureBlockSignerName.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const SCREEN = read('app', 'site', 'logbooks.jsx');
const PAD = read('src', 'components', 'SignaturePad.js');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

// ── Lift the shipped derivation out of the screen and run it ───────────────
const OPEN = 'const SignatureBlock = ({ signature, label }) => {';
const start = SCREEN.indexOf(OPEN);
if (start < 0) {
  console.log('FAIL  SignatureBlock not found in app/site/logbooks.jsx — '
    + 'the component was renamed or resignatured; retarget this test.');
  process.exit(1);
}
const bodyStart = start + OPEN.length;
const retAt = SCREEN.indexOf('return (', bodyStart);
const PRELUDE = SCREEN.slice(bodyStart, retAt);

// Everything before the JSX must stay plain JS for this to be honest.
ok(!/[<]View|[<]Text|[<]Image/.test(PRELUDE),
  'the sliced prelude is plain JS — no JSX smuggled into the derivation');

// eslint-disable-next-line no-new-func
const derive = new Function('signature', `${PRELUDE}\nreturn { base64Data, signerName };`);

// ── What SignaturePad actually emits ───────────────────────────────────────
// Copied in shape, and the shape is asserted against the real source below so
// this fixture cannot drift away from the writer.
const DRAWN = {
  paths: [[{ x: 1, y: 2 }, { x: 3, y: 4 }]],
  signerName: 'Roy Fishman',
  timestamp: '2026-08-19T15:01:10.726Z',
  affirmed: true,
  affirmedAt: '2026-08-19T15:01:10.726Z',
  affirmedLang: 'en',
};

console.log('\n1. THE WRITER STILL WRITES camelCase');
{
  const code = PAD
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');
  ok(/signerName: signerName\?\.trim\(\)/.test(code),
    'SignaturePad emits `signerName`, by name — the half the reader missed');
  ok(!/signer_name/.test(code),
    'and never `signer_name` — there is no writer of the snake spelling here');
  ok(/paths: pathsRef\.current/.test(code),
    'and the ink is `paths`, an array — not a base64 string');
}

console.log('\n2. THE NAME IS READ FROM WHAT THE PAD WROTE');
{
  ok(derive(DRAWN).signerName === 'Roy Fishman',
    'a signature carrying `signerName` renders the name');
}

console.log('\n3. AND THE LEGACY SPELLING STILL WORKS');
{
  // Filed documents may carry either. server.py reads both; so must this.
  ok(derive({ data: 'AAAA', signer_name: 'Casey Legacy' }).signerName === 'Casey Legacy',
    'a stored `signer_name` still renders — this is a widening, not a swap');
  ok(derive({ paths: [[{ x: 0, y: 0 }]], signer_name: 'Both', signerName: 'Both' })
    .signerName === 'Both',
    'a document carrying both spellings agrees with itself');
  ok(derive({ paths: [[{ x: 0, y: 0 }]] }).signerName === '',
    'an unnamed signature is still the empty string, not `undefined`');
  ok(derive('AAAAbase64').signerName === '' && derive('AAAAbase64').base64Data === 'AAAAbase64',
    'a bare base64 string signature is unchanged');
}

console.log('\n4. THE NAME BRANCH IS THE ONE THAT RUNS FOR DRAWN INK');
{
  // The exact condition from the shipped JSX, evaluated rather than matched.
  const { base64Data, signerName } = derive(DRAWN);
  const imageBranch = Boolean(base64Data) && typeof base64Data === 'string';
  ok(imageBranch === false,
    'the image branch is skipped: `paths` is an array, and it requires a string');
  ok(signerName !== '',
    'so the name branch is what the inspector sees — and it is no longer empty');

  // The label expression, same source, same result.
  const label = 'Competent Person';
  ok(`${label}${signerName ? ` — ${signerName}` : ''}` === 'Competent Person — Roy Fishman',
    'the heading names the signer instead of standing alone');

  // A base64 signature must still take the image branch — the widening of the
  // name read must not have disturbed the branch that already worked.
  const b64 = derive({ data: 'AAAA', signerName: 'Roy Fishman' });
  ok(typeof b64.base64Data === 'string' && b64.base64Data === 'AAAA',
    'and a base64 signature still reaches the image');
}

console.log('\n5. THE READ IS IN THE SOURCE, BOTH SPELLINGS');
{
  const code = PRELUDE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(/signature\.signer_name/.test(code) && /signature\.signerName/.test(code),
    'both spellings are read — dropping either would break a real document');
}

console.log(failures ? `\n${failures} FAILURE(S)\n` : '\nAll assertions passed.\n');
process.exit(failures ? 1 : 0);
