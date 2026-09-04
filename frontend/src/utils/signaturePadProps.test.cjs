/**
 * EVERY SignaturePad MOUNT PASSES PROPS THE COMPONENT DECLARES.
 *
 * THE DEFECT. site_superintendent_log.jsx mounted it with `value` /
 * `onChange` / `name`. SignaturePad declares `existingSignature` /
 * `onSignatureCapture` / `signerName` / `onNameChange`. React passes unknown
 * props through and the destructure yields undefined, so nothing threw and
 * nothing worked:
 *
 *     value={signerName || ""}                              -> always ""
 *     onChangeText={(t) => onNameChange && onNameChange(t)}  -> a no-op
 *
 * A controlled input whose value is a constant and whose handler is undefined:
 * every keystroke discarded, the field re-renders empty. That is the "will not
 * accept typing" report, and it is ONE defect with the blank, not two. And
 * `onSignatureCapture` undefined meant the SIGNATURE could not be captured
 * either — the pad was inert end to end and Sign and Freeze was unreachable.
 *
 * fall_protection.jsx had it wearing a better disguise: `signerName` was
 * right, so the name DISPLAYED, while `onSignerNameChange` (not a prop) made
 * typing a no-op and `value`/`onChange` made signing impossible. It reads as
 * working right up until somebody tries to finish, which is why it was never
 * reported.
 *
 * BLAST RADIUS, MEASURED 2026-09-04:
 *
 *     db.logbooks.countDocuments({log_type: "site_superintendent_log"})  0
 *     db.logbooks.countDocuments({log_type: "fall_protection"})          0
 *
 * TWO STATUTORY LOGBOOKS, NEVER FILED BY ANYONE SINCE LAUNCH, and the cause is
 * three misspelled prop names on two screens. Nothing in the codebase could
 * see them: docs/audits/followups.md already records that the reader/writer
 * checker's frontend half "is a TEXT search that cannot distinguish a read
 * from a write". A prop name is exactly that — an interface between two files
 * that never import each other, checked by nobody.
 *
 * Run:  node src/utils/signaturePadProps.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function walk(dir, out) {
  out = out || [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name[0] === '.') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if ((e.name.endsWith('.jsx') || e.name.endsWith('.js')) && e.name.indexOf('.test.') === -1) out.push(p);
  }
  return out;
}

// The component's own declared props, read off its destructuring pattern.
const padSrc = fs.readFileSync(path.join(FRONTEND, 'src', 'components', 'SignaturePad.js'), 'utf8');
const open = padSrc.indexOf('const SignaturePad = ({');
const close = padSrc.indexOf('}) => {', open);
ok(open !== -1 && close !== -1, "read SignaturePad's own props off its signature");
const declared = new Set();
for (const line of padSrc.slice(open, close).split('\n')) {
  const t = line.trim();
  if (!t || t[0] === '/' || t[0] === '*') continue;
  const id = t.split('=')[0].split(',')[0].trim();
  if (id && /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(id)) declared.add(id);
}
ok(declared.size >= 8, `declared prop set is non-empty (${declared.size})`);
for (const must of ['signerName', 'onNameChange', 'existingSignature', 'onSignatureCapture']) {
  ok(declared.has(must), `SignaturePad still declares ${must}`);
}

// Every mount, and the props it passes.
const files = walk(path.join(FRONTEND, 'src')).concat(walk(path.join(FRONTEND, 'app')));
const bad = [];
let mounts = 0;
for (const f of files) {
  if (f.endsWith(path.join('components', 'SignaturePad.js'))) continue;
  const src = fs.readFileSync(f, 'utf8');
  let at = 0;
  for (;;) {
    const i = src.indexOf('<SignaturePad', at);
    if (i === -1) break;
    const j = src.indexOf('/>', i);
    if (j === -1) break;
    at = j + 2;
    mounts += 1;
    const block = src.slice(i + 13, j);
    const seen = new Set();
    for (const raw of block.split('\n')) {
      const t = raw.trim();
      if (!t || t.indexOf('{/*') === 0 || t.indexOf('//') === 0 || t[0] === '*') continue;
      const eq = t.indexOf('=');
      const id = (eq === -1 ? t : t.slice(0, eq)).trim();
      if (id && /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(id)) seen.add(id);
    }
    for (const prop of seen) {
      if (!declared.has(prop)) {
        bad.push(`${path.relative(FRONTEND, f)}:${src.slice(0, i).split('\n').length}  passes '${prop}'`);
      }
    }
  }
}

// NON-EMPTY FIRST. "No unknown props found" is exactly what a scanner that
// reached nothing returns, and three drafts of this file did precisely that
// before this line was added.
ok(mounts >= 15, `the scan reached its subject (${mounts} mounts found)`);
if (bad.length) { console.log('\n  UNKNOWN PROPS:'); for (const b of bad) console.log('    ' + b); }
ok(bad.length === 0, 'every SignaturePad mount passes only declared props');

// POSITIVE CONTROL on the detector, so it cannot pass by rejecting nothing.
ok(!declared.has('value') && !declared.has('onChange') && !declared.has('name'),
  'the three names the broken screens used are genuinely NOT props');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
