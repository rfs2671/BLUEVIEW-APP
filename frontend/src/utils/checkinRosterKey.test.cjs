/**
 * Unit test for the returning-worker roster-match guard in backend/checkin.html
 * (FEATURE 1.5 / FIX 1).
 *
 * The re-prompt guard (`stillOnRoster`) must agree with the backend strict match
 * (server.py `_roster_key`) on case-only edits, leading/trailing whitespace,
 * internal whitespace, and renames — otherwise a case-only roster edit passes
 * one side and 400s on the other, dead-ending the worker (the fail-open
 * violation FIX 1 closes). Both sides key on ONE rule: strip + lowercase.
 *
 * Following the api.pagination.test.cjs harness, this reads the REAL
 * checkin.html and extracts rosterKey() VERBATIM, then reconstructs the
 * `stillOnRoster` some()-comparison over it. If rosterKey's shape changes,
 * extraction tracks it or throws loudly.
 *
 * Run:  node src/utils/checkinRosterKey.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(file, 'utf8');

function matchBalanced(text, openIdx, open, close) {
  let depth = 0;
  for (let i = openIdx; i < text.length; i += 1) {
    if (text[i] === open) depth += 1;
    else if (text[i] === close) {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new Error('unbalanced region');
}

const fnAnchor = 'function rosterKey(v)';
const fnAt = src.indexOf(fnAnchor);
if (fnAt < 0) throw new Error('rosterKey not found in checkin.html');
const braceOpen = src.indexOf('{', fnAt);
const braceClose = matchBalanced(src, braceOpen, '{', '}');
const fnSrc = src.slice(fnAt, braceClose + 1);

// Sanity: the shipped rule must be strip + lowercase, or we're asserting nothing.
if (!/\.trim\(\)\.toLowerCase\(\)/.test(fnSrc)) {
  throw new Error('rosterKey no longer strip+lowercase — update this test intentionally');
}

// eslint-disable-next-line no-new-func
const build = new Function(`${fnSrc}\nreturn rosterKey;`);
const rosterKey = build();

// Reconstruct the guard exactly as checkin.html applies it.
function stillOnRoster(roster, worker) {
  return roster.some(
    (a) =>
      rosterKey(a.trade) === rosterKey(worker.trade) &&
      rosterKey(a.company) === rosterKey(worker.company)
  );
}

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const WORKER = { trade: 'Concrete', company: 'AAZ' };

// Case-only edit -> still matches -> NO re-prompt (the FIX 1 case).
ok(stillOnRoster([{ trade: 'concrete', company: 'Aaz' }], WORKER) === true,
  'case-only roster edit -> stillOnRoster true (no re-prompt)');

// Leading/trailing whitespace -> stripped -> still matches -> NO re-prompt.
ok(stillOnRoster([{ trade: '  Concrete ', company: 'AAZ  ' }], WORKER) === true,
  'edge whitespace -> stillOnRoster true (no re-prompt)');

// Internal whitespace -> NOT stripped -> differs -> re-prompt.
ok(stillOnRoster([{ trade: 'Concrete', company: 'A A Z' }], WORKER) === false,
  'internal whitespace -> stillOnRoster false (re-prompt)');

// Rename -> differs -> re-prompt.
ok(stillOnRoster([{ trade: 'Concrete', company: 'AAZ Holdings' }], WORKER) === false,
  'rename -> stillOnRoster false (re-prompt)');

// The normalization key agrees on the four categories (mirrors _roster_key).
ok(rosterKey('AAZ') === rosterKey('Aaz'), 'key: case-insensitive');
ok(rosterKey('  AAZ ') === rosterKey('AAZ'), 'key: edge whitespace stripped');
ok(rosterKey('A A Z') !== rosterKey('AAZ'), 'key: internal whitespace preserved');
ok(rosterKey('AAZ') !== rosterKey('AAZ Holdings'), 'key: rename differs');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
