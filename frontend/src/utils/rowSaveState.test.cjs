/**
 * D3 B — the row-level save indicator.
 *
 * Ruled: a screen-level "Saving…" is decoration; per-row is a fact about that
 * row. The difficulty is that `writeDraft` persists the whole payload in ONE
 * AsyncStorage write, so there is no per-row persistence to report and a naive
 * per-row spinner is just the screen-level indicator drawn N times.
 *
 * The fact that IS per-row: has this row changed since the last write that
 * actually landed? That is derived, not asserted, and it is what a CP filling a
 * sign-in sheet wants to know about the man in front of him.
 *
 * THE CORRECTNESS CONDITION, and the thing most likely to be got wrong later:
 * the snapshot may only be taken when `writeDraft` RETURNED TRUE. It returns
 * false rather than throwing, so a caller that snapshots optimistically marks
 * every row saved on a device that is storing nothing — turning the per-row
 * marker into the same lie as "Saved automatically as you go", drawn once per
 * man. Asserted against the real screen source below, not just the helper.
 *
 * Run:  node src/utils/rowSaveState.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The real module, imports stripped, evaluated for real.
const src = fs.readFileSync(path.join(UTILS, 'rowSaveState.js'), 'utf8');
ok(src.length > 0, 'rowSaveState.js read and non-empty');
// eslint-disable-next-line no-new-func
const M = new Function(`${src.replace(/^export /gm, '')}
  return { rowKey, snapshotRows, unsavedRowKeys };`)();

console.log('\n── identity ──');

ok(M.rowKey({ id: 'a' }, 3) === 'id:a', 'a client-minted id is the identity');
ok(M.rowKey({ _local_id: 'b' }, 3) === 'id:b', '…or _local_id');
ok(M.rowKey({ worker_id: 'w' }, 3) === 'id:w', '…or worker_id');
ok(M.rowKey({ name: 'Jane' }, 3) === 'i:3', 'with no id it falls back to the index');
ok(M.rowKey(null, 2) === 'i:2', 'and a null row does not throw');
ok(M.rowKey({ id: '' }, 4) === 'i:4', 'an EMPTY id is not an id');
ok(M.rowKey({ id: 0 }, 4) === 'id:0', 'but 0 IS an id — a falsy id is still an id');

console.log('\n── what counts as unsaved ──');

const rows = [{ id: 'a', name: 'Jane' }, { id: 'b', name: 'Ali' }];
const snap = M.snapshotRows(rows);

ok(M.unsavedRowKeys(rows, snap).size === 0,
  'unchanged rows are saved');

{
  const edited = [{ id: 'a', name: 'Jane Q' }, { id: 'b', name: 'Ali' }];
  const u = M.unsavedRowKeys(edited, snap);
  ok(u.size === 1 && u.has('id:a'),
    'ONLY the edited row is unsaved — this is the whole point of per-row');
}
{
  const added = rows.concat([{ id: 'c', name: 'Sam' }]);
  const u = M.unsavedRowKeys(added, snap);
  ok(u.size === 1 && u.has('id:c'), 'a new row is unsaved');
}
{
  // Reordering must not report both rows as unsaved: identity is the id, not
  // the position. A positional key stops naming the same row the moment rows
  // move, and a sign-in sheet reorders as men arrive.
  const reordered = [rows[1], rows[0]];
  ok(M.unsavedRowKeys(reordered, snap).size === 0,
    'reordering rows with ids changes nothing');
}
{
  // Key order inside a row must not matter: React state updates rebuild objects
  // with different insertion order all the time while changing nothing typed.
  const respread = [{ name: 'Jane', id: 'a' }, { name: 'Ali', id: 'b' }];
  ok(M.unsavedRowKeys(respread, snap).size === 0,
    'a spread that reorders FIELDS does not report the row as unsaved');
}
{
  // Nested values are compared too — the answers on a pre-shift row are nested.
  const nestedSnap = M.snapshotRows([{ id: 'a', answers: { ppe: true, injury: false } }]);
  ok(M.unsavedRowKeys([{ id: 'a', answers: { injury: false, ppe: true } }], nestedSnap).size === 0,
    'nested key order does not matter either');
  ok(M.unsavedRowKeys([{ id: 'a', answers: { ppe: false, injury: false } }], nestedSnap).size === 1,
    'but a changed nested VALUE does');
}

console.log('\n── the no-snapshot case ──');

// A form that has just loaded a draft off disk has rows that ARE on disk.
// Returning "everything is unsaved" there would light up every row the moment
// the form opens, which is how a marker stops being read.
ok(M.unsavedRowKeys(rows, null).size === 0,
  'no snapshot yet reports NOTHING unsaved, not everything');
ok(M.unsavedRowKeys(rows, undefined).size === 0, '…and the same for undefined');
ok(M.unsavedRowKeys(null, snap).size === 0, 'a null row list does not throw');

console.log('\n── the wiring, on the real screen ──');

const screen = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'preshift_signin.jsx'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
ok(screen.length > 0, 'preshift_signin.jsx read and non-empty');

ok(/const \[savedSnapshot, setSavedSnapshot\] = useState\(null\);/.test(screen),
  'the screen owns a snapshot, seeded null');
ok(/const unsavedRows = unsavedRowKeys\(workers, savedSnapshot\);/.test(screen),
  'and derives the unsaved set from it');
ok(/unsavedRows\.has\(rowKey\(worker, index\)\)/.test(screen),
  'the marker renders per row, keyed by that row');

// THE CORRECTNESS CONDITION. Snapshot only on a confirmed write.
ok(/if \(_ok\) setSavedSnapshot\(snapshotRows\(workers\)\);/.test(screen),
  'the autosave snapshots ONLY when writeDraft returned true');
ok(/if \(localSaved\) setSavedSnapshot\(snapshotRows\(workers\)\);/.test(screen),
  'and so does the submit path');
// EXACTLY THREE SNAPSHOT SITES, and each one justified. Two are guarded by a
// write result; the third is the LOAD SEED, which is legitimately unguarded
// because it is not a write at all — it records that rows read off disk are
// already on disk. An earlier version of this test banned every unguarded
// snapshot and flagged the seed, which would have pushed the fix in the wrong
// direction: guarding the seed would light up every row on a freshly opened
// form.
const snapSites = (screen.match(/setSavedSnapshot\(snapshotRows\(/g) || []).length;
ok(snapSites === 3, `three snapshot sites: autosave, submit, load-seed (got ${snapSites})`);

// Seeded at load, or every row lights up on open.
ok(/if \(loading \|\| savedSnapshot !== null\) return;[\s]*setSavedSnapshot\(snapshotRows/
  .test(screen),
  'the seed sits behind the load guard, so a draft off disk reads as saved');

// NO PER-ROW SPINNER, and no per-row "Saved". A row is on disk or it is not,
// and the in-flight moment is a few milliseconds of an AsyncStorage write.
// Only the NEGATIVE state renders, so the marker means something when it is
// there. (The Save Draft BUTTON's own 'Saving...' label is a different thing
// entirely — a user-initiated action reporting itself — and is left alone.)
ok(/rowUnsavedBadge/.test(screen), 'the row marker exists');
ok(!/rowSavedBadge|rowSavingBadge/.test(screen),
  'and there is no positive or in-flight per-row state to dilute it');
{
  const i = screen.indexOf('unsavedRows.has(rowKey(worker, index))');
  ok(i > 0, 'located the per-row marker condition');
  const block = screen.slice(i, i + 400);
  ok(/Not saved/.test(block), 'it renders the negative state in words');
  ok(!/ActivityIndicator/.test(block), 'and not a spinner');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
