/**
 * THE TREE'S TWO NUMBERS COME FROM ONE LIST, AND IT DOES NOT CLAIM TWO FILES
 * WHERE THERE IS ONE OBJECT.
 *
 * Two guarantees are held here, both of them about the screen not saying more
 * than it knows:
 *
 *   1. `treeHeadline` derives the file count AND the folder count from the
 *      array handed to it. `POST /sync-dropbox` also returns a `file_count`,
 *      taken from a recursive Dropbox listing while the copy into project_files
 *      is still running (#242). Borrowing it for half the sentence would make
 *      "412 files in 9 folders" true of nothing — 412 from Dropbox, 9 from the
 *      rows that had arrived. The count climbing as rows arrive is correct.
 *
 *   2. `collidingNames` finds rows that share a filename. The sync writes R2
 *      under `{company}/{project}/{filename}` from a RECURSIVE listing, so
 *      `A/plan.pdf` and `B/plan.pdf` are two rows over ONE object. A flat list
 *      hid that; a tree renders them in two folders, which is a stronger claim
 *      than the data supports. The key fix is the backend's — until then the
 *      screen must not assert distinctness.
 *
 * Run:  node src/utils/dropboxTree.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function load(rel) {
  const file = path.join(__dirname, rel);
  if (!fs.existsSync(file)) {
    ok(false, `src/utils/${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    console.log('  (stopping: the shared tree module is not in this tree)');
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

const M = load('dropboxTree.js');
const {
  UNFILED, folderPathOf, folderLabel, groupByFolder, treeCounts,
  collidingNames, isColliding, treeHeadline, formatSyncedAt, COLLISION_NOTE,
} = M;

{
  const required = {
    folderPathOf, folderLabel, groupByFolder, treeCounts, collidingNames,
    isColliding, treeHeadline, formatSyncedAt,
  };
  let missing = 0;
  for (const [name, fn] of Object.entries(required)) {
    const present = typeof fn === 'function';
    ok(present, `dropboxTree exports ${name}`);
    if (!present) missing += 1;
  }
  if (missing > 0) {
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
}

const f = (p, name) => ({ path: p, name: name || p.split('/').pop() });

// ═══════════════════════════════════════════════════════════════════════════
// 1. Folder identity is the FULL path, not the parent's name.
// ═══════════════════════════════════════════════════════════════════════════
ok(folderPathOf(f('/Job/Approved/Plans/a.pdf')) === 'Job/Approved/Plans',
  'folderPathOf keeps the whole path above the file');

ok(folderPathOf(f('/Job/Approved/Plans/a.pdf'))
   !== folderPathOf(f('/Job/Superseded/Plans/a.pdf')),
  'two folders both named "Plans" stay two folders');

ok(folderPathOf(f('a.pdf')) === UNFILED,
  'a file with no folder above it lands in the root group');

ok(folderLabel(UNFILED) === 'Project root',
  'the root group has a name, not a blank');

// ═══════════════════════════════════════════════════════════════════════════
// 2. Grouping is deterministic, and root-level files sort last.
// ═══════════════════════════════════════════════════════════════════════════
{
  const files = [
    f('/Job/B/two.pdf'), f('/loose.pdf'), f('/Job/A/one.pdf'), f('/Job/B/one.pdf'),
  ];
  const groups = groupByFolder(files);
  ok(groups.length === 3, 'three distinct folders group into three entries');
  ok(groups[0][0] === 'Job/A' && groups[1][0] === 'Job/B',
    'folders sort alphabetically');
  ok(groups[2][0] === UNFILED, 'root-level files sort last');
  ok(groups[1][1].map((x) => x.name).join() === 'one.pdf,two.pdf',
    'files sort alphabetically inside a folder');

  const again = groupByFolder([...files].reverse());
  ok(JSON.stringify(again.map((g) => g[0])) === JSON.stringify(groups.map((g) => g[0])),
    'input order does not change the rendered order');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. BOTH numbers come from the one list.
// ═══════════════════════════════════════════════════════════════════════════
{
  const files = [
    f('/Job/A/one.pdf'), f('/Job/A/two.pdf'), f('/Job/B/three.pdf'), f('/loose.pdf'),
  ];
  const counts = treeCounts(files);
  ok(counts.files === 4, 'file count is the rows in the list');
  ok(counts.folders === 3, 'folder count is the groups the tree renders');

  const line = treeHeadline(files, '2026-08-28T19:04:00Z');
  ok(/^4 files in 3 folders · last synced /.test(line),
    `headline states both numbers and the sync time (got: ${line})`);

  // The count climbing as rows arrive is the honest behaviour — the headline
  // describes the tree below it, and half of it must never come from the sync
  // response's recursive Dropbox count.
  const partial = treeHeadline(files.slice(0, 2), '2026-08-28T19:04:00Z');
  ok(/^2 files in 1 folder · /.test(partial),
    `a partially-synced list reports what it holds (got: ${partial})`);

  ok(/1 folder ·/.test(partial) && !/1 folders/.test(partial),
    'singular folder is not "1 folders"');
  ok(/^1 file in /.test(treeHeadline([f('/A/x.pdf')], null)),
    'singular file is not "1 files"');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. Never synced says so; it does not drop the clause.
// ═══════════════════════════════════════════════════════════════════════════
ok(/never synced$/.test(treeHeadline([f('/A/x.pdf')], null)),
  'a folder that has never synced says so rather than omitting the clause');
ok(/never synced$/.test(treeHeadline([], undefined)),
  'an absent timestamp is never rendered as a silent success');
ok(formatSyncedAt('not a date') === null,
  'an unparseable timestamp yields null rather than "Invalid Date"');
ok(/never synced$/.test(treeHeadline([f('/A/x.pdf')], 'not a date')),
  'an unparseable timestamp falls back to the honest clause');

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE R2 COLLISION. Same filename in two folders is one object.
// ═══════════════════════════════════════════════════════════════════════════
{
  const files = [
    f('/Job/A/plan.pdf'), f('/Job/B/plan.pdf'), f('/Job/A/other.pdf'),
  ];
  const colliding = collidingNames(files);
  ok(colliding.has('plan.pdf'),
    'two rows sharing a filename are found');
  ok(!colliding.has('other.pdf'),
    'a unique filename is not flagged');
  ok(isColliding(f('/Job/B/plan.pdf'), colliding),
    'both rows of a collision are flagged, not just the second');

  // Dropbox matches case-insensitively and the R2 key is built from `name`.
  const mixed = collidingNames([f('/A/Plan.pdf'), f('/B/plan.pdf')]);
  ok(mixed.has('plan.pdf'),
    'a collision differing only in case is still a collision');

  ok(collidingNames([f('/A/one.pdf'), f('/B/two.pdf')]).size === 0,
    'a tree with no repeated filenames flags nothing');

  // The note must state the CONSEQUENCE. A reader cannot act on an R2 key.
  ok(/open the same document/i.test(COLLISION_NOTE),
    'the collision note says what the reader will actually experience');
  ok(!/r2|bucket|key/i.test(COLLISION_NOTE),
    'the collision note does not explain storage internals at the reader');
}

// ═══════════════════════════════════════════════════════════════════════════
// 6. Degenerate input does not throw. These lists arrive from the network and
//    from a device cache, and a malformed row must not blank the screen.
// ═══════════════════════════════════════════════════════════════════════════
{
  let threw = false;
  try {
    groupByFolder(null);
    groupByFolder([null, undefined, {}, { path: null }]);
    treeCounts(undefined);
    collidingNames(null);
    treeHeadline(null, null);
  } catch (e) { threw = true; }
  ok(!threw, 'null, undefined and malformed rows are survived, not thrown on');
  ok(treeCounts(null).files === 0 && treeCounts(null).folders === 0,
    'an absent list counts as nothing rather than reporting a stale number');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
