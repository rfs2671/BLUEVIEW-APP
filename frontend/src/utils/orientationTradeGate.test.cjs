/**
 * The client half of the orientation trade gate.
 *
 * THE RULE: a safety orientation can be CREATED without a trade, but not
 * SUBMITTED. The server enforces it (SUBMIT_MISSING_TRADE); this file asserts
 * that the screen behaves like a screen and not like a wall.
 *
 * The two things that make it usable rather than a dead end:
 *
 *   1. IT NAMES THE WORKER AND OFFERS THE FIX. The list can hold a dozen
 *      orientations. A refusal that says only "a trade is missing" tells the CP
 *      nothing he can act on, so the row itself says which worker and carries
 *      an Assign-trade control.
 *
 *   2. A REFUSAL IS NOT A DEFERRAL. handleSignExisting used to swallow EVERY
 *      push failure as "will sync on reconnect" and then freeze the record
 *      anyway — the same shape as the finalize bug daily_jobsite already fixed.
 *      Through that path a refused submit would leave the CP told it was
 *      signed, the record frozen on device, and nothing queued that could ever
 *      resolve it. The three outcomes are now split.
 *
 * Run:  node src/utils/orientationTradeGate.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'subcontractor_orientation.jsx');
const src = fs.readFileSync(SCREEN, 'utf8');
const serverSrc = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8',
);
const draftSync = fs.readFileSync(path.join(__dirname, 'draftSync.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Absence assertions run against code, never against prose that documents it. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');

function fnBody(name) {
  const start = code.indexOf(`const ${name} = async (`);
  if (start === -1) return '';
  const next = code.indexOf('\n  const ', start + 10);
  return code.slice(start, next === -1 ? code.length : next);
}
const signFn = fnBody('handleSignExisting');
const assignFn = fnBody('handleAssignTrade');

// ── The pre-flight guard ─────────────────────────────────────────────────────
console.log('\n── The CP is not asked to sign what the server will refuse ──');

ok(signFn.length > 0, 'handleSignExisting is present and extractable');
ok(/if \(!orientationTrade\(orientation\)\)/.test(signFn),
  'signing checks for a trade BEFORE the round trip');
ok(/setAssigningTrade\(\{ orientation, value: '' \}\)/.test(signFn),
  '...and opens the fix rather than just refusing');
ok(/return;/.test(signFn.slice(0, signFn.indexOf('const id'))),
  '...and returns without signing');
ok(/worker_name \|\| 'this worker'/.test(signFn),
  'the warning names the worker');

// The guard must not be the ONLY thing — the server is the real gate.
ok(/_submit_missing_trade_detail/.test(serverSrc),
  'the server-side gate exists and is the real one');
ok(/SUBMIT_MISSING_TRADE/.test(serverSrc), 'and raises the machine code');

// ── A refusal is not a deferral ──────────────────────────────────────────────
console.log('\n── A refusal is not a deferral ──');

ok(/const refused = typeof status === 'number' && status >= 400 && status < 500;/.test(signFn),
  'a 4xx is identified as a REFUSAL, not swallowed as offline');
ok(/const offline = isOfflineError\(pushErr\)/.test(signFn),
  'offline is decided by the app-wide predicate, not a second local one');
ok(/finalizeErrorCode\(pushErr\)/.test(signFn),
  'the machine code is read through the one reader that validates it');
ok(/code === 'SUBMIT_MISSING_TRADE'/.test(signFn),
  'and the trade refusal is handled by name');
ok(/detail\?\.worker_name/.test(signFn),
  'the worker the SERVER named is used, so the message points at the right row');

// The three outcomes must each return before the freeze.
const freezeAt = signFn.indexOf('freezeIfImmediate');
ok(freezeAt > -1, 'the freeze is still in this function');
const beforeFreeze = signFn.slice(0, freezeAt);
ok((beforeFreeze.match(/return;/g) || []).length >= 3,
  'the refusal and the 5xx paths both return BEFORE the record is frozen');
ok(/status: 'draft',/.test(beforeFreeze),
  'a refused submit rolls the draft back to draft — it stays editable');
ok(!/toast\.success/.test(beforeFreeze.slice(beforeFreeze.indexOf('refused'))),
  'nothing claims success on a refusal');

// Offline is untouched: it still freezes and still promises a sync.
ok(/will sync on reconnect/.test(signFn),
  'the genuinely-offline path keeps its deferral');

// ── The fix, on the row ──────────────────────────────────────────────────────
console.log('\n── The fix is offered where the problem is ──');

ok(/No trade assigned/.test(src), 'an unsigned trade-less row says so on the card');
ok(/cannot be signed until \{d\.worker_name \|\| 'this worker'\}/.test(src),
  '...naming the worker');
ok(/Assign trade/.test(src), '...and carries an Assign-trade control');
ok(/!String\(d\.worker_trade \|\| ''\)\.trim\(\)/.test(code),
  'the warning shows only when the trade is actually missing');
ok(/!isSigned && !isLocked && !String\(d\.worker_trade/.test(code),
  'and never on a row that is already signed or frozen');

ok(assignFn.length > 0, 'handleAssignTrade exists');
ok(/writeDraft\(key, \{ data: nextData, status: 'draft' \}\)/.test(assignFn),
  'assigning writes the on-device draft FIRST, so it survives with no signal');
ok(/status: 'draft'/.test(assignFn) && !/status: 'submitted'/.test(assignFn),
  'assigning a trade does NOT submit — the CP still signs afterwards');
ok(/markPending\(key\)/.test(assignFn),
  'an assignment that could not be pushed stays queued');
ok(/worker_trade: trade/.test(assignFn), 'and it writes the trade it was given');

// ── The gate check-in stays fail-open ────────────────────────────────────────
console.log('\n── The worker at the turnstile is never blocked ──');

ok(/"worker_trade": trade or ""/.test(serverSrc),
  'register_and_checkin still writes a trade-less orientation draft');
// Trailing comment tolerated — the line reads `"status": "draft",  # CP must
// add signature to submit`, and that comment is the reason this works.
ok(/"status": "draft",[^\n]*\n\s*"cp_signature": None/.test(serverSrc),
  '...as a DRAFT, which the submit gate deliberately does not police');

// ── The code plugs into the existing mechanism ───────────────────────────────
console.log('\n── Built on what was already there ──');

// THE BEHAVIOUR, NOT THE LITERAL. These two lines used to pin the regex TEXT
// and a copy of it, so they failed the moment FILED_ was added — a widening
// made for a good reason (#214's code carries neither existing prefix, which is
// exactly why the client could not hear it) breaking a test that was never
// about the alternation. What matters HERE is that SUBMIT_MISSING_TRADE goes
// through the same extractor as every other gate code, and that an unknown
// prefix still does not. Both now run the real pattern, read out of the module.
const gateSrc = /const GATE_CODE = \/(.+)\/;/.exec(draftSync);
ok(!!gateSrc, 'draftSync still validates gate codes with one pattern');
const GATE_CODE = gateSrc && new RegExp(gateSrc[1]);
ok(!!GATE_CODE && GATE_CODE.test('SUBMIT_MISSING_TRADE'),
  'SUBMIT_MISSING_TRADE matches it, so the drain can read it too');
ok(!!GATE_CODE && !GATE_CODE.test('SOMETHING_ELSE'),
  '...and a code that is not a gate code still does not');
ok(/SUBMIT_EMPTY_LOG/.test(serverSrc) && /SUBMIT_MISSING_CP_SIGNATURE/.test(serverSrc),
  'the two codes it sits alongside are untouched');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
