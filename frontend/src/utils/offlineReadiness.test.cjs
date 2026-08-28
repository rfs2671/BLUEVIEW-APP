/**
 * THE PLANS SCREEN SAYS WHETHER THE CP IS READY TO GO UNDERGROUND.
 *
 * The cache mechanism was never broken — documentDirectory over the evictable
 * cacheDirectory, real pdf.js builds staged, cache-first list render, honest
 * per-file refusal. What was missing was any way to know whether it had
 * happened. Five silent failure modes and nothing on screen for any of them.
 *
 * THE STATE IS COMPUTED FROM THE DISK, NEVER STORED. A "saved" flag goes stale
 * the moment a drawing changes in Dropbox and bumps its cache_version — and it
 * would then promise something untrue at the exact moment it matters. Because
 * the cached filename encodes {fileId}.{cache_version}, a changed file is
 * automatically a miss, and that is asserted directly.
 *
 * AND THE FOURTH STATE. A project that has never synced under a build that
 * records run state reads UNCHECKED, not "not saved". Telling a CP his plans
 * are missing when they may be entirely on his device is worse than saying
 * nothing, and on the day this ships every project is in that state.
 *
 * Run:  node src/utils/offlineReadiness.test.cjs
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

const _cache = new Map();
function load(rel) {
  const file = path.join(__dirname, rel);
  if (!fs.existsSync(file)) {
    ok(false, `src/utils/${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
  if (_cache.has(file)) return _cache.get(file);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  _cache.set(file, m);
  // RESOLVE RELATIVE IMPORTS FOR REAL. offlineReadiness.js imports
  // ./dropboxSyncState, which is also ESM and which a plain require() cannot
  // parse. It is compiled and evaluated too, so these assertions run against
  // the SHIPPED rule for what a trustworthy list is rather than a stub that
  // could drift from it.
  const shim = (spec) => {
    if (!spec.startsWith('.')) return require(spec);
    const target = spec.endsWith('.js') ? spec : `${spec}.js`;
    const rel2 = path.relative(__dirname, path.join(path.dirname(file), target));
    return load(rel2.split(path.sep).join('/'));
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, shim);
  return m;
}

const R = load('offlineReadiness.js');
const {
  readinessOf, saveQueue, isSavable, isUnsavable, megabytes, hasRoomFor,
  HEADROOM_BYTES, READY_UNCHECKED, READY_ALL, READY_PARTIAL, READY_NONE,
} = R;

{
  const required = { readinessOf, saveQueue, isSavable, isUnsavable, hasRoomFor };
  let missing = 0;
  for (const [n, f] of Object.entries(required)) {
    const present = typeof f === 'function';
    ok(present, `offlineReadiness exports ${n}`);
    if (!present) missing += 1;
  }
  if (missing) { console.log(`\n  ${passed} passed, ${failed} failed`); process.exit(1); }
}

const MB = 1048576;
const nameOf = (f) => `${f.id}.${f.cache_version ?? 0}.pdf`;
const pdf = (id, over) => ({
  id, name: `${id}.pdf`, cache_version: 1, size: 2 * MB,
  r2_url: `/api/projects/p1/files/${id}/content`, ...over,
});
const COMPLETE = { status: 'complete', expected: 3, synced: 3, failed: 0 };

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE FOURTH STATE — never checked is not "not saved".
// ═══════════════════════════════════════════════════════════════════════════
{
  const files = [pdf('a'), pdf('b')];
  const none = new Set();

  const never = readinessOf({ files, cachedNames: none, nameOf, sync: null });
  ok(never.state === READY_UNCHECKED,
    'a project that has never synced reads UNCHECKED, not NONE');
  ok(never.neverSynced === true, 'and reports that it has never synced');

  // Even with everything on disk, an untrustworthy list cannot claim readiness.
  const all = new Set(files.map(nameOf));
  const stillUnchecked = readinessOf({ files, cachedNames: all, nameOf, sync: null });
  ok(stillUnchecked.state === READY_UNCHECKED,
    'ALL FILES ON DISK still reads UNCHECKED when the list is unverified — '
    + '"all saved" over a list that may be a subset is the lie #252 exists to stop');

  const midSync = readinessOf({
    files, cachedNames: all, nameOf,
    sync: { status: 'running', started_at: new Date().toISOString() },
  });
  ok(midSync.state === READY_UNCHECKED, 'a sync in flight reads UNCHECKED');

  const lostFiles = readinessOf({
    files, cachedNames: all, nameOf,
    sync: { status: 'complete', expected: 5, synced: 3, failed: 2 },
  });
  ok(lostFiles.state === READY_UNCHECKED,
    'a sync that finished having LOST files cannot certify the list either');
  ok(lostFiles.neverSynced === false,
    'but it is distinguished from never-synced, because the copy differs');
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE COUNT COMES FROM THE DISK.
// ═══════════════════════════════════════════════════════════════════════════
{
  const files = [pdf('a'), pdf('b'), pdf('c')];

  const r0 = readinessOf({ files, cachedNames: new Set(), nameOf, sync: COMPLETE });
  ok(r0.state === READY_NONE && r0.saved === 0 && r0.savable === 3,
    'nothing on disk reads NONE');

  const r1 = readinessOf({ files, cachedNames: new Set([nameOf(files[0])]), nameOf, sync: COMPLETE });
  ok(r1.state === READY_PARTIAL && r1.saved === 1, 'one of three reads PARTIAL');
  ok(r1.bytesRemaining === 4 * MB, 'and totals the bytes still to fetch');

  const rAll = readinessOf({ files, cachedNames: new Set(files.map(nameOf)), nameOf, sync: COMPLETE });
  ok(rAll.state === READY_ALL && rAll.saved === 3, 'all three reads ALL');
  ok(rAll.bytesRemaining === 0, 'with nothing left to fetch');

  // STALENESS IS FREE, and it is the reason the count must come from the disk.
  const changed = [{ ...files[0], cache_version: 2 }, files[1], files[2]];
  const stale = readinessOf({
    files: changed, cachedNames: new Set(files.map(nameOf)), nameOf, sync: COMPLETE,
  });
  ok(stale.state === READY_PARTIAL && stale.saved === 2,
    'a drawing that CHANGED in Dropbox drops back to not-saved automatically — '
    + 'the version is in the filename, so a stale copy is a miss');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. UNSAVABLE FILES COME OUT OF THE DENOMINATOR.
// ═══════════════════════════════════════════════════════════════════════════
{
  const broken = pdf('x', { r2_url: '' });   // R2 upload failed during the sync
  const files = [pdf('a'), pdf('b'), broken];

  ok(isUnsavable(broken), 'a PDF with no URL is unsavable');
  ok(!isSavable(broken), 'and is not savable');

  const r = readinessOf({
    files, cachedNames: new Set([nameOf(files[0]), nameOf(files[1])]), nameOf, sync: COMPLETE,
  });
  ok(r.savable === 2, 'the unsavable file is OUT of the denominator');
  ok(r.unsavable === 1, 'and is reported separately, with its own count');
  ok(r.state === READY_ALL,
    'SO A CLEAN STATE IS REACHABLE. Leaving it in would mean the count could '
    + 'never be satisfied, and a number that can never be satisfied is ignored');

  ok(saveQueue({ files, cachedNames: new Set(), nameOf }).length === 2,
    'and Save all never queues a file it cannot fetch');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. NON-PDFs ARE NOT PART OF THE PROMISE.
// ═══════════════════════════════════════════════════════════════════════════
{
  const docx = { id: 'd', name: 'schedule.docx', cache_version: 1, size: MB, r2_url: '/x' };
  ok(!isSavable(docx) && !isUnsavable(docx),
    'a .docx is neither — it opens in another app over the network and has no '
    + 'offline story, so counting it would make the promise unkeepable');
  const r = readinessOf({ files: [pdf('a'), docx], cachedNames: new Set([nameOf(pdf('a'))]), nameOf, sync: COMPLETE });
  ok(r.savable === 1 && r.state === READY_ALL, 'and it does not hold the project back');
}

// ═══════════════════════════════════════════════════════════════════════════
// 5. SAVE ALL: UNCAPPED, IN SCREEN ORDER, SKIPPING WHAT IS ALREADY THERE.
// ═══════════════════════════════════════════════════════════════════════════
{
  const many = Array.from({ length: 40 }, (_, i) => pdf(`f${i}`));
  const q = saveQueue({ files: many, cachedNames: new Set(), nameOf });
  ok(q.length === 40, 'Save all is UNCAPPED — the 15 limit is the background warm only');
  ok(q[0].id === 'f0' && q[39].id === 'f39',
    'and preserves screen order: what he is looking at lands first');

  const half = new Set(many.slice(0, 20).map(nameOf));
  ok(saveQueue({ files: many, cachedNames: half, nameOf }).length === 20,
    'already-saved files are skipped, which is what makes a retry cheap');
}

// ═══════════════════════════════════════════════════════════════════════════
// 6. DISK SPACE — REFUSED BEFORE THE FIRST BYTE, AND UNKNOWN NEVER BLOCKS.
// ═══════════════════════════════════════════════════════════════════════════
ok(hasRoomFor(10 * MB, 500 * MB) === true, 'plenty of room passes');
ok(hasRoomFor(10 * MB, 20 * MB) === false, 'not enough room is refused');
ok(hasRoomFor(10 * MB, 10 * MB + HEADROOM_BYTES) === false,
  'the headroom margin is required, not just the raw size');
ok(hasRoomFor(10 * MB, null) === null,
  'UNDETERMINED free space returns null, never false');
ok(hasRoomFor(10 * MB, undefined) === null, 'and so does undefined');
ok(hasRoomFor(10 * MB, 'lots') === null, 'and so does a non-number');

ok(megabytes(0) === 1 && megabytes(1) === 1,
  'a non-zero size never rounds to "0 MB", which would read as nothing to do');
ok(megabytes(5 * MB) === 5, 'and whole megabytes otherwise');

// ═══════════════════════════════════════════════════════════════════════════
// 7. THE SCREEN READS THE DISK AND DOES NOT STORE A FLAG.
// ═══════════════════════════════════════════════════════════════════════════
{
  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'projects', '[id]', 'construction-plans.jsx'), 'utf8');
  const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });

  const seen = new Set();
  let readsDisk = false;
  let usesModel = false;
  let checksRoom = false;
  let uncappedSave = false;
  (function walk(n) {
    if (!n || typeof n !== 'object' || seen.has(n)) return;
    seen.add(n);
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier') {
      if (n.callee.name === 'listCachedDocs') readsDisk = true;
      if (n.callee.name === 'readinessOf') usesModel = true;
      if (n.callee.name === 'hasRoomFor') checksRoom = true;
      if (n.callee.name === 'saveQueue') uncappedSave = true;
    }
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v);
    }
  }(tree));

  ok(readsDisk, 'the screen enumerates the cache directory');
  ok(usesModel, 'and derives the strip through readinessOf, not its own arithmetic');
  ok(checksRoom, 'and checks disk space before starting');
  ok(uncappedSave, 'and builds its queue through saveQueue');

  // The background warm keeps its cap; Save all must not inherit it.
  ok(/warmDocCache\([\s\S]{0,120}?limit: 15/.test(screen),
    'the background warm still carries its limit');
  const saveAll = screen.slice(screen.indexOf('const handleSaveAll'),
    screen.indexOf('const adoptFiles'));
  ok(!/limit:/.test(saveAll), 'and handleSaveAll carries no limit of its own');
  ok(/Not checked yet/.test(screen), 'the fourth state has copy on screen');
  ok(!/not saved on this device[\s\S]{0,80}Not checked/i.test(screen),
    'and it is not phrased as "not saved"');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
