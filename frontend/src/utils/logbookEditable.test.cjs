/**
 * A filed log is not reopened for editing.
 *
 * THE DEFECT. Three editors carried `arr.find((l) => !l.is_locked)` — the
 * server's FREEZE MODEL for IMMEDIATE types, with its type condition dropped.
 * The server applies that exclusion only when `is_immediate_preshift(...)`, and
 * says why: "END_OF_DAY logs deliberately keep the 423 — the daily narrative is
 * one record per day; corrections go through /amend."
 *
 * An END_OF_DAY log is not locked when submitted (the sweep freezes it
 * overnight, and only if affirmed), so `!is_locked` selected the FILED daily
 * narrative and handed it to the editor as an editable draft. Two records at
 * 588 Thomas were overwritten on 2026-08-25 — and the CP changed nothing.
 * Opening is enough: hydrate sets fourteen fields, all in the autosave deps,
 * with no dirty tracking.
 *
 * THE READ-ONLY FALLBACK IS HALF THE FIX. Refusing re-entry without an
 * amendment path would replace a silent overwrite with a dead end. Setting
 * `locked` does both: `pointerEvents='none'` over the form, and
 * LogbookLockBar's `if (locked)` branch renders the FINALIZED banner WITH
 * Amend. amend_logbook requires only a reason — it does not require the
 * original to be locked — so that path works on exactly these documents.
 *
 * IT ALSO STOPS THE LOCAL BLEED. The same branch calls markFinalized(), which
 * is `writeDraft(key, { finalized: true })`, and writeDraft refuses to edit a
 * finalized draft's content. So the load-induced autosave can no longer rewrite
 * the device's draft — which is what was queueing a pending key that then
 * drained into the server.
 *
 *   node frontend/src/utils/logbookEditable.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');

// RELATIVE IMPORTS ARE FOLLOWED, not handed to node's require. The module under
// test imports ./dates for its one Eastern conversion, and a bare require would
// hit that file's raw `export` and die -- so each relative specifier is
// transpiled the same way and memoised. Node's own resolution is still used for
// everything else (packages), which is what keeps this a loader and not a
// bundler.
const _cache = new Map();
function loadFile(file) {
  if (_cache.has(file)) return _cache.get(file);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  _cache.set(file, mod.exports);
  const localRequire = (spec) => {
    if (!spec.startsWith('.')) return require(spec);
    const base = path.resolve(path.dirname(file), spec);
    const hit = [base, `${base}.js`, `${base}.jsx`, path.join(base, 'index.js')]
      .find((p) => fs.existsSync(p) && fs.statSync(p).isFile());
    if (!hit) throw new Error(`cannot resolve ${spec} from ${file}`);
    return loadFile(hit);
  };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, localRequire);
  _cache.set(file, mod.exports);
  return mod.exports;
}

function loadModule(rel) {
  return loadFile(path.join(FRONTEND, rel));
}

const { isOpenForEditing, chooseEditableLog } = loadModule('src/utils/logbookEditable.js');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

const DRAFT = { id: 'd', status: 'draft', is_locked: false };
// The shape that was reopened: filed, and the freeze has not caught up.
const FILED_UNLOCKED = { id: 'f', status: 'submitted', is_locked: false };
const LOCKED = { id: 'l', status: 'submitted', is_locked: true };

console.log('\n-- openness, not the lock --');
{
  ok(isOpenForEditing(DRAFT) === true, 'a draft is open');
  ok(isOpenForEditing(FILED_UNLOCKED) === false,
    'a SUBMITTED log is closed even with is_locked false — this is the case '
    + '`!l.is_locked` got wrong, and the one that overwrote two records');
  ok(isOpenForEditing(LOCKED) === false, 'a locked log is closed');
  ok(isOpenForEditing({ status: 'draft', is_locked: true }) === false,
    'and a locked DRAFT is closed too — the lock is decisive on its own, '
    + 'because a legacy row may carry one without the other');
  ok(isOpenForEditing(null) === false && isOpenForEditing(undefined) === false,
    'nothing is not open');
}

console.log('\n-- the day\'s log is chosen, and marked read-only when filed --');
{
  const filed = chooseEditableLog([FILED_UNLOCKED]);
  ok(filed.log === FILED_UNLOCKED, 'the filed log is still LOADED — the CP has '
    + 'to be able to read what he filed');
  ok(filed.readOnly === true,
    'but read-only. The caller sets `locked` from this, which drives '
    + "pointerEvents='none' AND the LockBar's FINALIZED banner with Amend");

  const draft = chooseEditableLog([DRAFT]);
  ok(draft.log === DRAFT && draft.readOnly === false,
    'an open draft loads editable, unchanged');

  ok(chooseEditableLog([]).log === null,
    'no logs -> nothing chosen, and the editor creates one');
  ok(chooseEditableLog([]).readOnly === false,
    'and an absent log is not "read-only" — there is nothing to protect');
}

console.log('\n-- an OPEN log is preferred over a filed one --');
{
  // The recurring-instance case: a filed instance plus a fresh draft.
  const r = chooseEditableLog([LOCKED, DRAFT]);
  ok(r.log === DRAFT && r.readOnly === false,
    'the draft is selected past the locked instance — unchanged behaviour');

  const r2 = chooseEditableLog([FILED_UNLOCKED, DRAFT]);
  ok(r2.log === DRAFT && r2.readOnly === false,
    'and past a submitted-unlocked one too');
}

console.log('\n-- immediate types: same outcome as before --');
{
  // A submitted IMMEDIATE log is locked (update_logbook sets is_locked when
  // status becomes submitted and is_immediate_preshift). So it was already
  // excluded by `!is_locked`, and it stays excluded here. The editor shows it
  // read-only; the SERVER's dedupe filter mints the next instance, because a
  // locked row no longer matches.
  const r = chooseEditableLog([LOCKED]);
  ok(r.log === LOCKED && r.readOnly === true,
    'a submitted immediate log loads read-only — identical to the old '
    + '`arr.find(!is_locked) || arr[0]` outcome, so the next-instance flow is '
    + 'untouched');

  // Two filed instances and nothing open: still read-only, never editable.
  const r2 = chooseEditableLog([LOCKED, { id: 'l2', status: 'submitted', is_locked: true }]);
  ok(r2.readOnly === true, 'and so does a second one');
}

console.log('\n-- all three editors use the shared rule --');
{
  const EDITORS = [
    'app/logbooks/toolbox_talk.jsx',
    'app/logbooks/daily_jobsite.jsx',
    'app/logbooks/preshift_signin.jsx',
  ];
  for (const f of EDITORS) {
    const src = fs.readFileSync(path.join(FRONTEND, f), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
    const name = path.basename(f);
    ok(/chooseEditableLog\(/.test(src), `${name} uses the shared rule`);
    ok(!/find\(\s*\(?l\)?\s*=>\s*!l\.is_locked\s*\)/.test(src),
      `${name} no longer selects on the lock alone`);
    ok(/if \(readOnly\) \{[\s\S]{0,80}setLocked\(true\)/.test(src)
      || /if \(readOnly\) \{\s*setLocked\(true\)/.test(src),
      `${name} sets locked from readOnly, so the form goes pointerEvents:none `
      + 'and the LockBar offers Amend');
    ok(/markFinalized\(/.test(src),
      `${name} still latches the local draft — writeDraft refuses to edit a `
      + 'finalized one, which is what stops the load-induced autosave');
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
