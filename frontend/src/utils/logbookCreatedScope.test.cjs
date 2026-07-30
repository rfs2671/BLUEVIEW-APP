/**
 * PR F — `const created` block-scope ReferenceError guard.
 *
 * Four logbook handleSave copies declared `const created` INSIDE the else block
 * and then referenced it at `docId = existingLogId || created?.id` OUTSIDE that
 * block. On the FIRST submit of a NEW log, existingLogId is falsy so evaluation
 * reaches `created` — which is out of scope → ReferenceError. The record IS
 * written, but the client throws, so recordSignatureEvent (which sits AFTER that
 * line) never fires and the CP is trained to press Submit twice.
 *
 * The fix hoists `let created = null` above the if/else (matching osha_log's
 * already-correct pattern). This static guard reads the REAL sources and asserts
 * for each fixed file that:
 *   - `let created` is declared, and BEFORE the `created?.id` reference; and
 *   - the buggy in-block `const created = await logbooksAPI.create` is gone; and
 *   - recordSignatureEvent is still wired (it must actually fire now).
 *
 * Run:  node src/utils/logbookCreatedScope.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FIXED = [
  'daily_jobsite',
  'toolbox_talk',
  'preshift_signin',
  'scaffold_maintenance',
];
// Already correct before PR F — guard that they stay correct.
const ALREADY_OK = ['osha_log'];

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function read(name) {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', `${name}.jsx`), 'utf8');
  // Strip line comments so the PR-F explanatory comment (which quotes the buggy
  // `created?.id` line) doesn't get mistaken for the actual code reference.
  return src.replace(/\/\/[^\n]*/g, '');
}

for (const name of [...FIXED, ...ALREADY_OK]) {
  const src = read(name);
  const letIdx = src.indexOf('let created');
  const refIdx = src.indexOf('created?.id');

  ok(letIdx >= 0, `${name}: declares 'let created' (hoisted, not block const)`);
  ok(!/const created = await logbooksAPI\.create/.test(src),
    `${name}: no buggy in-block 'const created = await ...create'`);
  if (refIdx >= 0) {
    ok(letIdx >= 0 && letIdx < refIdx,
      `${name}: 'let created' precedes the 'created?.id' reference (in scope)`);
  }
  ok(/recordSignatureEvent/.test(src),
    `${name}: recordSignatureEvent still wired (now reached on first submit)`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
