/**
 * A SCREEN MAY ONLY PROMISE A SYNC THE DRAIN CAN ACTUALLY PERFORM.
 *
 * THE DEFECT. `site/daily-logs.jsx` is the superintendent's required
 * §3301.13.13 daily log, filled in at the gate tablet. When the server push
 * failed it called `markPending(key)`, raised the pending badge, and showed a
 * GREEN SUCCESS toast:
 *
 *     "Saved on this device — No connection — this log will sync when you are
 *      back online."
 *
 * Nothing will ever sync it. `draftSync.js` holds
 *
 *     const SKIP_LOG_TYPES = new Set(['daily_log', 'site_daily_log'])
 *
 * and the reconnect drain reads the pending index, sees `site_daily_log`, and
 * returns `skipped-type`. The key sits in the index forever. The ONLY recovery
 * is a human reopening that exact date and pressing Save again — and the tablet
 * has just told him he does not need to.
 *
 * `app/daily-log.jsx` is the same defect on the CP's own daily log: log type
 * `daily_log`, also skipped, also a success toast reading "will sync when you
 * reconnect", and a persistent banner repeating it.
 *
 * THE SKIP IS NOT THE BUG. It is deliberate and its reasoning is sound: daily
 * logs post a flatter shape to `dailyLogsAPI`, and inventing a compliance
 * payload from a partial match risks writing a malformed record. The bug is
 * that nothing told the SCREENS, and the screens promise otherwise.
 *
 * THE INVARIANT THIS PINS, which survives both halves of the fix:
 *
 *     a screen may promise an unattended sync for its log type IF AND ONLY IF
 *     the reconnect drain will actually push that type.
 *
 * Pre-fix that is false and this file fails. After the honesty fix it is true
 * because the promise is gone. After the per-screen pusher lands it is true
 * again because the capability is real — and this file's model of "drainable"
 * grows the registry term at that moment, in the same commit that builds it.
 * A test whose expectation is derived from the shipped source, rather than
 * written down beside it, cannot drift away from what the app does.
 *
 * ANCHORED SLICES, NON-EMPTY FIRST. Every marker-derived subject below is
 * asserted non-empty before anything is asserted ABOUT it — a negative
 * assertion over an empty string passes and says nothing. See
 * assertionsCanFail.test.cjs.
 *
 * Run:  node src/utils/dailyLogSyncPromise.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8');
// Comments are stripped from the SCREENS. Both of them carry prose explaining
// these very branches, and the prose says "sync" and "queued" all over — a bare
// grep would match the explanation while the toast went back to lying.
const strip = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');

// ── WHAT THE DRAIN CAN ACTUALLY DO, read out of the drain ────────────────────
const drainSrc = read('src', 'utils', 'draftSync.js');
ok(drainSrc.length > 0, 'draftSync.js read and non-empty');

const skipLiteral = (drainSrc.match(/const SKIP_LOG_TYPES = new Set\(\[([^\]]*)\]\)/) || [, ''])[1];
ok(skipLiteral.length > 0, 'located the SKIP_LOG_TYPES literal in draftSync.js');
const SKIPPED = new Set(
  [...skipLiteral.matchAll(/'([^']+)'/g)].map((m) => m[1]),
);
ok(SKIPPED.size > 0, `SKIP_LOG_TYPES parsed and non-empty (${[...SKIPPED].join(', ')})`);

// The drain must still REFUSE a skipped type rather than guessing at it. The
// skip is the safe half of this defect and removing it is not the fix.
ok(/if \(SKIP_LOG_TYPES\.has\(parsed\.logType\)\)/.test(drainSrc),
  'the drain still consults SKIP_LOG_TYPES before pushing anything');

// STEP 2 HAS NOT LANDED. There is no way for a screen to hand the drain its own
// pusher, so "drainable" is exactly "not skipped". When the registry is built,
// this assertion flips and the definition below grows a second term — in the
// same commit, so the two can never disagree.
const registryPresent = /export function registerDraftPusher\(/.test(drainSrc);
ok(registryPresent === false,
  'no per-screen pusher registry exists yet — so a skipped type cannot sync by '
  + 'any route, and no screen may say it will');

/** Will the reconnect drain push this log type unattended? */
const drainable = (logType) => !SKIPPED.has(logType);

// ── THE TWO DAILY-LOG SCREENS ────────────────────────────────────────────────
// Each is described by the markers it actually contains. Both are asserted to
// exist before they are sliced on, so a rename fails here loudly instead of
// yielding an empty subject that passes every negative check below.
const SCREENS = [
  {
    rel: path.join('app', 'site', 'daily-logs.jsx'),
    // The deferred-push branch: from the moment the key is queued to the close
    // of the outer catch.
    deferred: ['await markPending(key);', '} catch (error) {'],
    // The persistent pending badge — the else-arm of the three-state ternary.
    badge: [') : pendingSync ? (', ') : hasServerLog ? ('],
  },
  {
    rel: path.join('app', 'daily-log.jsx'),
    deferred: ['await markPending(key);', '} catch (error) {'],
    badge: ['{!localSaveFailed && draftPending && (', '<GlassCard style={s.section}>'],
  },
];

// A promise that the log will travel BY ITSELF. "back online" and "reconnect"
// are deliberately absent: honest copy tells him to save again once he has
// signal, and naming the moment is the useful half of that sentence.
const AUTOMATIC = /will sync|syncs when|will upload|will retry|stays queued|is queued|queued to (upload|sync|retry)|sync automatically|automatically when/i;
// The other half of the ruling: "your entry is gone" is equally wrong.
const SAFE_HERE = /on this device/i;
// What he must actually do, since nothing else will.
const SAVE_AGAIN = /save (it |them )?again/i;

for (const { rel, deferred, badge } of SCREENS) {
  const raw = read(...rel.split(path.sep));
  ok(raw.length > 0, `${rel}: source read and non-empty`);
  const src = strip(raw);

  const logType = (src.match(/const LOG_TYPE = '([^']+)';/) || [, ''])[1];
  ok(logType.length > 0, `${rel}: declares its LOG_TYPE`);
  ok(SKIPPED.has(logType),
    `${rel}: its log type (${logType}) is one the drain skips — that is the premise`);

  // ── the deferred-push branch ───────────────────────────────────────────────
  const dStart = src.indexOf(deferred[0]);
  const dEnd = src.indexOf(deferred[1], dStart);
  ok(dStart !== -1, `${rel}: found the queue call "${deferred[0]}"`);
  ok(dEnd > dStart, `${rel}: found its closing marker "${deferred[1]}" after it`);
  const branch = (dStart !== -1 && dEnd > dStart) ? src.slice(dStart, dEnd) : '';
  ok(branch.length > 100, `${rel}: the deferred-push branch slice is a real branch`);
  ok(branch.startsWith(deferred[0]), `${rel}: and it really starts at the queue call`);

  if (!drainable(logType)) {
    // A SUCCESS TOAST IS A CLAIM THAT NOTHING IS OUTSTANDING. This state needs
    // a human to come back and press Save, which is not a success.
    ok(!/toast\.success\(/.test(branch),
      `${rel}: the deferred push is NOT reported as a success — it needs him to act later`);
    const promises = branch.split('\n').filter((l) => AUTOMATIC.test(l));
    ok(promises.length === 0,
      `${rel}: promises no unattended sync for a type the drain refuses`
      + `${promises.length ? ` — ${JSON.stringify(promises.map((l) => l.trim()))}` : ''}`);
    ok(SAFE_HERE.test(branch),
      `${rel}: but still says the log IS on the device — "your entry is gone" is equally wrong`);
    ok(SAVE_AGAIN.test(branch),
      `${rel}: and names the one thing that actually files it — saving again`);
  } else {
    ok(AUTOMATIC.test(branch),
      `${rel}: the drain WILL push this type, so the screen may say so`);
  }

  // ── the persistent pending indicator ───────────────────────────────────────
  // The toast is gone in four seconds; this is what he reads afterwards, and it
  // carried the same promise.
  const bStart = src.indexOf(badge[0]);
  const bEnd = src.indexOf(badge[1], bStart);
  ok(bStart !== -1, `${rel}: found the pending badge marker "${badge[0]}"`);
  ok(bEnd > bStart, `${rel}: found its closing marker after it`);
  const badgeSlice = (bStart !== -1 && bEnd > bStart) ? src.slice(bStart, bEnd) : '';
  ok(badgeSlice.length > 50, `${rel}: the pending-badge slice is real`);

  if (!drainable(logType)) {
    const badgePromises = badgeSlice.split('\n').filter((l) => AUTOMATIC.test(l));
    ok(badgePromises.length === 0,
      `${rel}: the pending badge implies no automatic retry either`
      + `${badgePromises.length ? ` — ${JSON.stringify(badgePromises.map((l) => l.trim()))}` : ''}`);
    ok(/device/i.test(badgeSlice),
      `${rel}: while still telling him the work is here`);
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
