/**
 * A blank tag is NdefFormatable, not Ndef.
 *
 * WHAT THE DEVICE SAID, after three source-reasoned hypotheses died:
 *
 *   dispatchTag: TAG: Tech [android.nfc.tech.NfcV, android.nfc.tech.NdefFormatable]
 *   parseIntent ... action android.nfc.action.TAG_DISCOVERED
 *   ReactNativeJS: 'NFC register error:', [Error: unsupported tag api]
 *
 * The OS dispatched the tag and the app parsed the intent — so this was never
 * Android 17, never the New Architecture, and never the SDK 54 migration. The
 * tag advertises `NdefFormatable` and the helper only ever asked for `Ndef`,
 * so `Ndef.get(tag)` returned null, there was no tech handle, and
 * `writeNdefMessage` reported "unsupported tag api" — an error naming the
 * write when the real gap was having nothing to write THROUGH.
 *
 * This write path has never been able to program a virgin tag. It predates
 * every part of the migration.
 *
 *   node frontend/src/utils/nfcWriteTech.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'nfcHelper.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}
/** A function's body, so an assertion cannot pass on a different function. */
function body(name) {
  const head = `export async function ${name}(`;
  const i = SRC.indexOf(head);
  if (i < 0) return '';
  return SRC.slice(i, SRC.indexOf('\n}', i));
}

console.log('\n-- both write techs are requested, formatable first --');
{
  // BRANCHED BY PLATFORM since the iOS entitlement fix. Android is what was
  // device-verified; iOS asks for Ndef alone over a TAG session, which polls
  // ISO14443 and ISO15693 both and connects to whichever turns up.
  ok(/: \[NfcTech\.NdefFormatable, NfcTech\.Ndef\];/.test(SRC),
    'ANDROID gets NdefFormatable FIRST — the two are mutually exclusive in '
    + 'practice, so a blank tag lands on format and a written tag falls '
    + 'through to write');
  ok(/\? \[NfcTech\.Ndef\]/.test(SRC),
    'and iOS gets Ndef alone — NdefFormatable is an Android tech that iOS '
    + 'would only ever resolve through a fallthrough');
}

console.log('\n-- the branch is on what was ACQUIRED, not on a guess --');
{
  // requestTechnology takes an array, tries each in order, and resolves to the
  // NAME of the one it got. Branching on that is branching on observed fact.
  const w = body('writeThroughTech') || SRC.slice(SRC.indexOf('async function writeThroughTech'));
  ok(w.length > 50, 'ANCHOR: the write helper exists');
  ok(/tech === 'NdefFormatable'/.test(w),
    'formats when the acquired tech is NdefFormatable');
  ok(/ndefFormatableHandlerAndroid\.formatNdef\(bytes\)/.test(w),
    'via formatNdef — which writes the message AS PART OF formatting, so a '
    + 'virgin tag is formatted and populated in one operation');
  ok(/ndefHandler\.writeNdefMessage\(bytes\)/.test(w),
    'and writes normally otherwise');
}

console.log('\n-- both writers use it, and neither hardcodes Ndef --');
{
  for (const fn of ['writeNfcTag', 'registerNfcTag']) {
    const b = body(fn);
    ok(b.length > 200, `ANCHOR: ${fn} body is non-empty`);
    ok(/requestTechnology\(WRITE_TECHS\)/.test(b),
      `${fn} requests BOTH techs`);
    ok(!/requestTechnology\(NfcTech\.Ndef\)/.test(b),
      `${fn} no longer asks for Ndef alone — the thing that could not write a `
      + 'blank tag');
    ok(/await writeThroughTech\(tech, bytes\)/.test(b),
      `${fn} writes through the acquired tech`);
  }
}

console.log('\n-- the UID is read before the branch --');
{
  // Both paths need it: it is what gets registered server-side whether the tag
  // was formatted or already written.
  const b = body('registerNfcTag');
  const uid = b.indexOf('NfcManager.getTag()');
  const write = b.indexOf('writeThroughTech');
  ok(uid > -1 && write > -1, 'ANCHOR: both steps are present');
  ok(uid < write, 'getTag() comes before the write, not inside a branch');
}

console.log('\n-- the failure names the tech it had --');
{
  // Three rounds went to a bare "unsupported tag api", which named the write
  // and not the missing handle. The next failure will say which handle it had.
  for (const fn of ['writeNfcTag', 'registerNfcTag']) {
    const b = body(fn);
    ok(/\(tech: \$\{tech\}\)/.test(b), `${fn} puts the acquired tech in the error`);
    ok(/no tech acquired/.test(b),
      `${fn} distinguishes "acquired nothing" from "acquired the wrong one" — `
      + 'those are different failures and were confused for three rounds');
    ok(/console\.warn\([^)]*tech, ex\)/.test(b),
      `${fn} logs the tech alongside the exception`);
  }
}

console.log('\n-- the READ path is deliberately untouched --');
{
  // Reading is a legitimately different flow. One shared abstraction over two
  // different intents is how the wrong path gets taken silently.
  const r = body('readNfcTag');
  ok(r.length > 100, 'ANCHOR: readNfcTag body is non-empty');
  ok(/requestTechnology\(NfcTech\.Ndef\)/.test(r),
    'readNfcTag still asks for Ndef alone — a tag with nothing on it has '
    + 'nothing to read, and formatting during a READ would write to a tag the '
    + 'caller only asked to inspect');
  ok(!/writeThroughTech|formatNdef/.test(r),
    'and it cannot reach either write path');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
