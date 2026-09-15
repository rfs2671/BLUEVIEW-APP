/**
 * FIX 1 — flagged workers are surfaced with their SPECIFIC reason, and the
 * CP can act on them, on all three screens.
 *
 * Static guard over the real sources (same pattern as
 * reviewUnknownWiring.test.cjs — no test framework, no transpiler):
 *
 *   app/logbooks/preshift_signin.jsx  the pre-shift roster (TASK B)
 *   app/logbooks/index.jsx            CP home warning banner (TASK C)
 *   app/workers.jsx                   admin workers tab warning (TASK C)
 *
 * What is pinned:
 *   • the reason is always NAMED — never a generic "flagged"
 *   • expired / unknown SST get two real, visible, tap-only buttons
 *   • deny MARKS, it never removes: the row is never filtered out
 *   • no-trade reuses the roster the worker picks from at sign-in
 *     (trade_assignments), and there is exactly ONE picker
 *   • no trade-CHANGE affordance on a worker who already has one
 *   • the warning is SOFT — nothing gates Submit
 *   • a row with no checkin_id offers no action instead of a dead button
 *
 * Run:  node src/utils/fix1FlaggedWorkerSurfaces.test.cjs
 */

const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', '..', 'app');
const read = (...p) => fs.readFileSync(path.join(APP, ...p), 'utf8');

/**
 * COMMENTS OUT, and this file needed it the day it was written.
 *
 * The assertion below used to be `/'Unknown SST card'/.test(preshift)`. When
 * that string was replaced by real multi-state copy, the assertion KEPT
 * PASSING — because the replacement's header comment quotes the ternary it
 * removed, so the regex matched the DOCUMENTATION of the old behaviour instead
 * of the behaviour. That is the exact trap backend/tests/source_text.py exists
 * to close on the Python side, recorded there as having happened four times.
 *
 * So every assertion about preshift_signin.jsx below reads `preshift` with
 * comments and JSX comments removed. Conservative on purpose: block comments,
 * and lines whose first non-space characters are `//` or `*`. It does not try
 * to parse strings, so a `'https://…'` inside code survives intact.
 */
const stripComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n')
  .filter((l) => !/^\s*(\/\/|\*)/.test(l))
  .join('\n');

const preshift = stripComments(read('logbooks', 'preshift_signin.jsx'));
const cpHome = read('logbooks', 'index.jsx');
const workers = read('workers.jsx');
const signIn = read('checkin', '[project_id]', '[tag_id].jsx');
const review = read('logbooks', 'review.jsx');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Source of one function, from its declaration to a given terminator.
function block(src, opener, closer) {
  const start = src.indexOf(opener);
  if (start < 0) return '';
  const end = src.indexOf(closer, start + opener.length);
  return end < 0 ? src.slice(start) : src.slice(start, end);
}

// ── TASK B — the pre-shift roster ───────────────────────────────────────────
console.log('\npreshift_signin.jsx — flagged rows');

ok(/logbooksAPI\.getCheckinsForDate/.test(preshift),
  'roster still comes from /checkins-today (flagged workers are NOT filtered out)');
ok(!/\.filter\([^)]*sst_status/.test(preshift) && !/\.filter\([^)]*needs_trade/.test(preshift),
  'no filter removes a flagged worker from the roster');

// Each reason is named explicitly. A generic "flagged" label is the failure.
//
// INVERTED, AND IT WAS RIGHT TO BREAK. These two read:
//
//   ok(/'Expired SST card'/.test(preshift), "names the reason: 'Expired SST card'");
//   ok(/'Unknown SST card'/.test(preshift), "names the reason: 'Unknown SST card'");
//
// pinning the two literals a BINARY TERNARY could produce:
//
//   {f.sst_status === 'expired' ? 'Expired SST card' : 'Unknown SST card'}
//
// The intent -- name the reason, never print a generic "flagged" -- was right
// and is kept. The pin was wrong in the same way the ternary was: two strings
// for five statuses, so "Unknown SST card" was the answer to every question
// that was not `expired`, including four materially different production rows
// and any status added later. Pinning the literal here made that arrangement
// load-bearing.
//
// The strings now live in src/utils/sstFlagCopy.js and are asserted BY VALUE in
// sstFlagCopy.test.cjs and BY RENDER in sstCardFlagPaints.test.cjs, which
// executes the real component. What is asserted HERE is what this file is
// about: the screen still names reasons, from one shared definition, and never
// falls back to a generic label.
ok(/sstFlagCopy/.test(preshift),
  'the SST reason comes from the shared copy module, not an inline ternary');
ok(!/'Unknown SST card'/.test(preshift),
  'the one-size "Unknown SST card" string is GONE from the code (not merely '
  + 'from a comment — see stripComments above)');
ok(!/sst_status === 'expired' \?/.test(preshift),
  'and the binary ternary that produced it is gone with it');
ok(/<SstFlagLines/.test(preshift),
  'the reason line is rendered by the exported component the paint test runs');
ok(/>\s*No trade assigned\s*</.test(preshift), "names the reason: 'No trade assigned'");
ok(!/>\s*Flagged\s*</.test(preshift) && !/'Flagged'/.test(preshift),
  'never renders a generic "Flagged" label');

// Approve / deny — two real buttons, tap-only, both wired to /review.
const reviewFn = block(preshift, 'const handleReview', 'const handleAssignTrade');
ok(/checkinsAPI\.review\(f\.checkin_id, decision\)/.test(reviewFn),
  'approve/deny POSTs the existing /checkins/{id}/review endpoint');
ok(/handleReview\(key, 'approved'\)/.test(preshift), "approve button sends 'approved'");
ok(/handleReview\(key, 'sent_home'\)/.test(preshift), "deny button sends 'sent_home'");
ok(/>\s*Approve\s*</.test(preshift) && />\s*Deny\s*</.test(preshift),
  'both buttons are visible, labelled controls');
ok(!/setWorkers/.test(reviewFn),
  'DENY MARKS, NEVER REMOVES — handleReview never touches the worker list');

// Re-review stays possible: the buttons are not hidden once a decision exists.
ok(/f\.review_decision &&/.test(preshift) && !/f\.review_decision \?/.test(preshift),
  're-review stays available — a recorded decision annotates, it does not replace the buttons');

// Trade assignment — one picker, fed by the project trade roster.
const assignFn = block(preshift, 'const handleAssignTrade', 'const updateWorker');
ok(/checkinsAPI\.assignTrade\(/.test(assignFn),
  'no-trade POSTs the existing /checkins/{id}/assign-trade endpoint');
ok(/checkinsAPI\.getFlagged\(projectId\)/.test(preshift)
  && /flaggedData\?\.trade_assignments/.test(preshift),
  'trade options come from trade_assignments — the same roster the worker picks from at sign-in');
ok(/\(projectInfo\?\.trade_assignments \|\| \[\]\)\.map/.test(signIn),
  'sanity: the sign-in dropdown really is built from trade_assignments');
ok((preshift.match(/roster\.map\(/g) || []).length === 1
  && (preshift.match(/setRoster\(/g) || []).length === 1,
  'exactly ONE trade list rendered from ONE source — no second picker');
ok(/tradePickerFor === key/.test(preshift),
  'one picker open at a time, keyed by worker');

// INVERTED, AND IT DID ITS JOB. It read:
//
//   ok(/f\.needs_trade &&/.test(preshift) && !/Change trade|.../i.test(preshift),
//     'no "change trade" affordance — the picker only appears where NO trade
//      was captured');
//
// pinning the scope of the original assign-trade work: offer the picker only
// where the gate captured NOTHING, and never let a CP edit a trade already set.
//
// That scope turned out to be the defect. A worker who picked a VALID roster
// entry that was simply the WRONG one had no flag, no row and no route, so the
// pairing was corrected by hand in mongosh twice in one week. The operator
// ruled the gate lifted; the assertion inverts rather than being deleted, so
// the change of intent stays visible.
//
// WHAT STILL HOLDS is asserted above and unchanged: ONE roster from ONE source,
// one picker open at a time. Widening WHO can be corrected did not widen WHAT
// can be picked.
ok(/Change Trade/.test(preshift),
  'every row offers a trade change — a valid-but-wrong pairing is reachable');
ok(/f\.needs_trade \?/.test(preshift),
  'and needs_trade now chooses the LABEL (Assign vs Change) rather than '
  + 'deciding whether the picker exists at all');

// Honest degradation when there is no check-in row to act on.
ok(/const canAct = !!f\.checkin_id;/.test(preshift),
  'actions are gated on a real checkin_id');
ok(/No check-in record to review for this worker\./.test(preshift),
  'a row with no checkin_id says so instead of offering a dead button');

// SOFT: nothing about the flags reaches the save path.
const saveFn = block(preshift, 'const handleSave', 'const YesNoToggle');
ok(!/flags/.test(saveFn) && !/needs_trade/.test(saveFn) && !/sst_status/.test(saveFn),
  'SOFT warning — Submit is never gated on a flag, and no flag enters the payload');
ok(/onPress=\{\(\) => handleSave\('submitted'\)\}/.test(preshift),
  'Submit stays unconditional');

// Tap-only.
ok(!/PanResponder|Swipeable|onLongPress|GestureDetector|onSwipe/.test(preshift),
  'tap-only — no gesture handlers anywhere on this screen');

// The reason never becomes part of the record (full proof lives in
// backend/tests/test_fix1_no_reason_leak.py).
const rowLiteral = block(preshift, 'const buildWorkerList', 'setWorkers(list)');
ok(!/sst_status|review_decision|checkin_id|needs_trade|cert_warnings/.test(rowLiteral),
  'worker rows (== logbook data.workers[]) carry no flag state');
ok(/const \[flags, setFlags\] = useState\(\{\}\)/.test(preshift),
  'flag state is held separately from the worker rows');

// ── TASK C — CP home ────────────────────────────────────────────────────────
console.log('\nlogbooks/index.jsx — CP home banner');

ok(/function flaggedReasonSummary/.test(cpHome),
  'the banner builds its text from a per-reason summary');
ok(/expired SST card/.test(cpHome) && /unknown SST card/.test(cpHome)
  && /with no trade assigned/.test(cpHome),
  'all three specific reasons can be named');
ok(!/expired SST cards or workers with no trade assigned/.test(cpHome),
  'the old fixed sentence (printed whatever the real mix was) is gone');
ok(/rs\.includes\('expired_sst'\)/.test(cpHome)
  && /rs\.includes\('unknown_sst'\)/.test(cpHome)
  && /rs\.includes\('needs_trade'\)/.test(cpHome),
  "counts come from the flagged endpoint's existing flag_reasons");
ok(/rs\.includes\('expired_sst'\)/.test(cpHome) && /flag_reasons/.test(review),
  'sanity: flag_reasons is the same field the review screen reads');
ok(/flagged\.count > 0 &&/.test(cpHome),
  'SOFT — the banner only renders, it gates nothing');

// ── TASK C — admin workers tab ──────────────────────────────────────────────
console.log('\nworkers.jsx — admin sign-in log');

ok(/function checkinWarnings/.test(workers),
  'a per-check-in reason helper exists');
ok(/'Expired SST card'/.test(workers) && /'Unknown SST card'/.test(workers)
  && /'No trade assigned'/.test(workers),
  'all three reasons are named specifically');
ok(/sst_status === 'expired'/.test(workers)
  && /sst_status === 'unknown'/.test(workers)
  && /needs_trade_assignment/.test(workers),
  'reasons are read from fields the check-in row already carries');
ok(/review_decision === 'approved'/.test(workers),
  "a recorded decision is shown, including the 'sent home' mark");
ok(/fetchState === 'ok' && warningSummary\.length > 0/.test(workers),
  'the summary only renders on an ANSWERED fetch — never a claim from a failed read');
ok(!/blocked|compliance_alert/.test(workers),
  'the blocked population is not represented here (out of scope)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
