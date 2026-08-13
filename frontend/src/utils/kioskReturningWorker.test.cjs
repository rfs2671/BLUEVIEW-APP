/**
 * THE SILENT REROUTE at the gate.
 *
 * A returning worker holding a valid SST expiring 2030 was dropped back onto
 * the registration screen with NO MESSAGE, over and over, and neither he nor
 * the CP could see why. Production: project 6a5f63bc147407d3261df2c7, worker
 * 6a6c93b14929115cffffbb0a, roster pair 'Concrete / Cement' / 'AAZ' matching
 * his workers doc EXACTLY.
 *
 * TWO CORRECT RULES THAT COMBINED INTO A WRONG ONE.
 *
 *   backend/server.py lookup_worker returns trade/company from
 *   worker_project_trades and NEVER falls back to the workers document — a
 *   value from another project is silently wrong. A worker with no pairing on
 *   this project therefore gets null for both. That is right.
 *
 *   checkin.html re-matches the stored pair against the roster so a renamed or
 *   deleted entry routes to the picker instead of a backend 400. That is also
 *   right.
 *
 *   Together: rosterKey(null) is '', the match missed, and every unpaired
 *   worker was rerouted as though his trade had been DELETED — in silence.
 *
 * The kiosk is a standalone HTML page with no module system and no renderer
 * here, so the guard is executed by extracting the real branch and running it
 * against stubs, and the copy is asserted against the real TRANSLATIONS maps.
 *
 * Run:  node src/utils/kioskReturningWorker.test.cjs
 */
const fs = require('fs');
const path = require('path');

const KIOSK = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(KIOSK, 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The real rosterKey, lifted from the page ────────────────────────────────
const rosterKeySrc = src.slice(src.indexOf('function rosterKey(v) {'));
// eslint-disable-next-line no-new-func
const rosterKey = new Function(`${rosterKeySrc.slice(0, rosterKeySrc.indexOf('\n}') + 2)}
  return rosterKey;`)();

console.log('\n-- rosterKey, the shipped one --');
ok(rosterKey(null) === '', 'rosterKey(null) is the empty string — the whole bug in one line');
ok(rosterKey(undefined) === '', 'and so is undefined');
ok(rosterKey('  Concrete / Cement ') === 'concrete / cement', 'it strips and lowercases');

// ── The decision, executed ──────────────────────────────────────────────────
// Mirrors the shipped expression; asserted below to still match the source.
function decide(worker, tradeAssignments) {
  const hasStoredPair = Boolean(rosterKey(worker.trade))
    && Boolean(rosterKey(worker.company));
  if (tradeAssignments.length) {
    const stillOnRoster = hasStoredPair && tradeAssignments.some(
      (a) => rosterKey(a.trade) === rosterKey(worker.trade)
        && rosterKey(a.company) === rosterKey(worker.company),
    );
    if (!stillOnRoster) {
      return { reroute: true, key: hasStoredPair ? 'tradeOffRoster' : 'tradeNotRecorded' };
    }
  }
  return { reroute: false, key: null };
}

const ROSTER = [{ trade: 'Concrete / Cement', company: 'AAZ' }];

console.log('\n-- the three cases, kept apart --');

// 1. THE PRODUCTION CASE. No pairing on this project, so lookup-worker sends
//    nulls even though his workers doc is correct.
const unpaired = decide({ name: 'Segundo Pilamunga', trade: null, company: null }, ROSTER);
ok(unpaired.reroute === true, 'an unpaired worker still goes to the picker — that is the intended flow');
ok(unpaired.key === 'tradeNotRecorded',
  'but he is told his trade is NOT RECORDED, not that it was removed');

// 2. A real pair the admin renamed or deleted — what FEATURE 1.5 was for.
const offRoster = decide({ trade: 'Demolition', company: 'Vanguard' }, ROSTER);
ok(offRoster.reroute === true, 'a stale pair still reroutes');
ok(offRoster.key === 'tradeOffRoster', 'and he is told it is no longer on the project');

// 3. THE MAN WHO SHOULD NOT BE STOPPED AT ALL.
const paired = decide({ trade: 'Concrete / Cement', company: 'AAZ' }, ROSTER);
ok(paired.reroute === false, 'a matching pair proceeds to orientation and signature');
ok(rosterKey(' concrete / cement ') === rosterKey('Concrete / Cement'),
  'and the match still absorbs case and whitespace');

// 4. An empty roster SKIPS the check entirely — it cannot reroute anyone.
ok(decide({ trade: null, company: null }, []).reroute === false,
  'no roster configured means no reroute — nothing may stop a man for an admin gap');

console.log('\n-- and no exit is silent --');

const fn = src.slice(src.indexOf('async function quickCheckIn'));
const guard = fn.slice(0, fn.indexOf("showLoading("));
ok(/showError\(t\(hasStoredPair \? 'tradeOffRoster' : 'tradeNotRecorded'\), true\)/.test(guard),
  'the reroute surfaces a reason, persistently');
ok(guard.indexOf('showError(') < guard.lastIndexOf('return;'),
  'and it surfaces BEFORE returning');
ok(/const hasStoredPair = Boolean\(rosterKey\(returningWorker\.trade\)\)/.test(guard),
  'the shipped guard computes hasStoredPair — the executed copy above matches it');
ok(/stillOnRoster = hasStoredPair &&/.test(guard),
  'and a missing pair can never be counted as "on roster"');

// THE RULE THAT MUST NOT BE UNDONE.
ok(!/returningWorker\.trade\s*\|\|\s*worker\./.test(src)
  && !/lookup\.workerDoc/.test(src),
  'the kiosk does NOT fall back to the workers doc — the per-project rule stands');

console.log('\n-- the copy exists in both languages --');
for (const k of ['tradeNotRecorded', 'tradeOffRoster']) {
  const hits = src.match(new RegExp(`^\\s+${k}: '`, 'gm')) || [];
  ok(hits.length === 2, `${k}: present in EN and ES (found ${hits.length})`);
}
// checkin.html is a standalone page and owns its own map — asserted by
// src/i18n/i18n.test.cjs too. Keep it that way.
ok(/const TRANSLATIONS = \{/.test(src) && !/src\/i18n/.test(src),
  'and it still owns its own TRANSLATIONS map');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
