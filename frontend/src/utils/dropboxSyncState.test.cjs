/**
 * THE OFFLINE LIST IS NOT WRITTEN FROM A MID-SYNC READ.
 *
 * POST /sync-dropbox returns as soon as the background task is SCHEDULED, so
 * the list read that follows it catches the sync partway through. The plans
 * screen cached that, which meant a CP's saved-for-offline list could be a
 * strict SUBSET of the project — and he found out in a cellar.
 *
 * THE DIRECTION THAT MATTERS MOST IS THE PERMISSIVE ONE. Withholding the cache
 * write buys protection for one short, known window. Withholding it forever —
 * because a process died and left a record at "running" — would leave a CP with
 * a list that never updates again, which is a worse version of the same bug.
 * So UNKNOWN lets him use what he has, and that is asserted directly rather
 * than left to follow from the implementation.
 *
 * Run:  node src/utils/dropboxSyncState.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const parser = require('@babel/parser');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function load(rel) {
  const file = path.join(__dirname, rel);
  // A MISSING MODULE IS A NAMED FAILURE, NOT A STACK TRACE. Against a tree
  // without this feature the readFileSync below throws and the run reports one
  // opaque error instead of the guarantee that is absent.
  if (!fs.existsSync(file)) {
    ok(false, `src/utils/${rel} exists`);
    console.log(`
  ${passed} passed, ${failed} failed`);
    console.log('  (stopping: the sync-state rule is not in this tree)');
    process.exit(1);
  }
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}

const M = load('dropboxSyncState.js');
const {
  syncRunState, mayCacheList, listIsComplete, SYNC_STALE_AFTER_MS,
  SYNC_NEVER, SYNC_RUNNING, SYNC_COMPLETE, SYNC_FAILED, SYNC_UNKNOWN,
} = M;

{
  const required = { syncRunState, mayCacheList, listIsComplete };
  let missing = 0;
  for (const [name, fn] of Object.entries(required)) {
    const present = typeof fn === 'function';
    ok(present, `dropboxSyncState exports ${name}`);
    if (!present) missing += 1;
  }
  if (missing > 0) {
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
}

// A fixed clock. Date.now() in a test is a timing dependency, and a suite that
// fails at midnight on someone else's machine is worse than no suite.
const NOW = Date.parse('2026-08-27T12:00:00.000Z');
const at = (msAgo) => new Date(NOW - msAgo).toISOString();

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE STATES.
// ═══════════════════════════════════════════════════════════════════════════
ok(syncRunState(null, NOW) === SYNC_NEVER, 'no summary at all reads NEVER');
ok(syncRunState(undefined, NOW) === SYNC_NEVER, 'undefined reads NEVER');
ok(syncRunState({}, NOW) === SYNC_NEVER, 'an empty summary reads NEVER');
ok(syncRunState('running', NOW) === SYNC_NEVER, 'a non-object reads NEVER');

ok(syncRunState({ status: 'complete' }, NOW) === SYNC_COMPLETE,
  'a completed run reads COMPLETE');
ok(syncRunState({ status: 'failed' }, NOW) === SYNC_FAILED,
  'a failed run reads FAILED');
ok(syncRunState({ status: 'running', started_at: at(60 * 1000) }, NOW) === SYNC_RUNNING,
  'a run started a minute ago reads RUNNING');

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE STALLED-RUN RULE, AND THE DIRECTION IT MUST FAIL IN.
// ═══════════════════════════════════════════════════════════════════════════
{
  const stale = { status: 'running', started_at: at(SYNC_STALE_AFTER_MS + 1000) };
  ok(syncRunState(stale, NOW) === SYNC_UNKNOWN,
    'a run older than the window reads UNKNOWN, not RUNNING');

  // THE ASSERTION THAT MATTERS: unknown must not block.
  ok(mayCacheList(stale, NOW) === true,
    'A STALE RUNNING RECORD DOES NOT BLOCK CACHING — unknown lets the man use '
    + 'what he has');

  const ancient = { status: 'running', started_at: at(1000 * 60 * 60 * 24 * 30) };
  ok(mayCacheList(ancient, NOW) === true,
    'and a record left running for a month does not block it either');

  // A record we cannot age must not be believed indefinitely.
  ok(syncRunState({ status: 'running' }, NOW) === SYNC_UNKNOWN,
    'a running record with no start time reads UNKNOWN');
  ok(syncRunState({ status: 'running', started_at: 'not a date' }, NOW) === SYNC_UNKNOWN,
    'an unparseable start time reads UNKNOWN');
  ok(mayCacheList({ status: 'running' }, NOW) === true,
    'and neither of those blocks caching');

  // The boundary itself.
  ok(syncRunState({ status: 'running', started_at: at(SYNC_STALE_AFTER_MS - 1000) }, NOW)
     === SYNC_RUNNING, 'just inside the window is still RUNNING');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. WHAT MAY OVERWRITE THE OFFLINE LIST.
// ═══════════════════════════════════════════════════════════════════════════
ok(mayCacheList({ status: 'running', started_at: at(1000) }, NOW) === false,
  'a sync genuinely in flight is the ONE case that withholds the write');

ok(mayCacheList(null, NOW) === true,
  'NEVER caches — no project carries a summary until its next sync, so this '
  + 'ships as a no-op for every project that exists today');
ok(mayCacheList({ status: 'complete' }, NOW) === true, 'COMPLETE caches');
ok(mayCacheList({ status: 'failed' }, NOW) === true,
  'FAILED caches — the sync is not going to write any more rows');

// ═══════════════════════════════════════════════════════════════════════════
// 4. "COMPLETE" IS A STRICTER QUESTION THAN "MAY CACHE".
//    PR 2's strip will tell a CP his plans are whole; a list missing three
//    drawings must never be described that way.
// ═══════════════════════════════════════════════════════════════════════════
ok(listIsComplete({ status: 'complete', expected: 15, synced: 15, failed: 0 }, NOW),
  'a run that got everything is complete');
ok(!listIsComplete({ status: 'complete', expected: 15, synced: 12, failed: 3 }, NOW),
  'a run that lost three files is NOT complete, even though it finished');
ok(!listIsComplete({ status: 'complete', expected: 15, synced: 15, failed: 2 }, NOW),
  'and a nonzero failure count alone disqualifies it');
ok(!listIsComplete({ status: 'running', started_at: at(1000) }, NOW),
  'an in-flight run is not complete');
ok(!listIsComplete({ status: 'running', started_at: at(SYNC_STALE_AFTER_MS + 1) }, NOW),
  'nor is a stalled one — unknown is not a promise');
ok(!listIsComplete(null, NOW), 'and neither is never-synced');
ok(!listIsComplete({ status: 'complete' }, NOW),
  'a completed run with no counts cannot claim completeness');
ok(listIsComplete({ status: 'complete', expected: 0, synced: 0, failed: 0 }, NOW),
  'an empty folder that synced cleanly IS complete');

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE SCREEN USES THE RULE, AND STILL WARMS THE BYTES.
// ═══════════════════════════════════════════════════════════════════════════
{
  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'projects', '[id]', 'construction-plans.jsx'),
    'utf8');
  const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });

  const seen = new Set();
  let usesRule = false;
  let cacheIsGuarded = false;
  let warmIsGuarded = false;
  let syncPassesFalse = false;

  (function walk(n) {
    if (!n || typeof n !== 'object' || seen.has(n)) return;
    seen.add(n);
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
        && n.callee.name === 'mayCacheList') usesRule = true;
    // `if (mayCache) cacheDocList(...)` — the write is behind the flag.
    if (n.type === 'IfStatement' && n.test && n.test.name === 'mayCache') {
      const body = n.consequent.type === 'BlockStatement' ? n.consequent.body : [n.consequent];
      for (const st of body) {
        const src = st.expression || st;
        if (src && src.type === 'CallExpression' && src.callee
            && src.callee.name === 'cacheDocList') cacheIsGuarded = true;
        if (src && src.type === 'CallExpression' && src.callee
            && src.callee.name === 'warmDocCache') warmIsGuarded = true;
      }
    }
    // handleSync passes mayCache: false without consulting anything.
    if (n.type === 'ObjectProperty' && n.key && n.key.name === 'mayCache'
        && n.value && n.value.type === 'BooleanLiteral' && n.value.value === false) {
      syncPassesFalse = true;
    }
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v);
    }
  }(tree));

  ok(usesRule, 'the screen decides with mayCacheList, not its own comparison');
  ok(cacheIsGuarded, 'cacheDocList is behind the guard');
  ok(!warmIsGuarded,
    'warmDocCache is NOT behind it — the files in a partial list are real files '
    + 'and pulling them down early costs nothing');
  ok(syncPassesFalse,
    'handleSync declines the write outright — it started the sync one line '
    + 'earlier, so asking the server would only race its own stamp');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
