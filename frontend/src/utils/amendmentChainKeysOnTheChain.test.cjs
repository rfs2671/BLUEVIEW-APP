/**
 * THE COLLAPSE KEYS ON THE CHAIN, NOT ON THE WORKER — and the inspector's
 * list says which record is current.
 *
 * ── G2, MEASURED ─────────────────────────────────────────────────────────
 *
 * `chainKey` reads `data.worker_id` / `data.worker_name`. On production that
 * resolves for `subcontractor_orientation` (96 documents) and NO OTHER TYPE:
 * daily_jobsite 64, toolbox_talk 69, preshift_signin 55, osha_log 44,
 * scaffold_maintenance 14 and site_superintendent_log 11 all returned null and
 * were passed through UNCOLLAPSED by `collapseChains`. 32 of the 47 live
 * amendment children are those types. So the one helper written to stop a
 * chain rendering flat only ever stopped it for one type in thirteen.
 *
 * `parent_logbook_id` is what `amend_logbook` writes, for every type, and
 * nothing in this codebase grouped by it. That is the missing primitive and
 * this file is about it.
 *
 * ── WHAT MUST NOT CHANGE ─────────────────────────────────────────────────
 *
 * THE ORIENTATION GROUPING. It is per WORKER today and stays per worker: the
 * group is keyed on the ROOT's `chainKey` when it has one. A worker whose
 * orientation was filed twice as two unlinked originals stays one row, as he
 * is today. Keying on the chain alone would split him — a live behaviour
 * change on the orientation editor, inside a change meant to fix the other
 * twelve types.
 *
 * THE REFUSAL TO PICK A WINNER. `_open_corrections` was written because 588
 * Thomas has two competing UNSIGNED children of one parent and showing one of
 * them would be a silent choice. That refusal is preserved, and extended to
 * the case it could not see: two FILED children, where the newest-first
 * tie-break picks one and nothing said the other was ever filed.
 *
 * Run:  node src/utils/amendmentChainKeysOnTheChain.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

// AN ABSENT LIST MUST READ AS A FAILURE, NOT AS AN EMPTY ONE — and must not
// throw. A control run against the unmodified module has no
// `_competing_records` at all, and `undefined.length` ends the process at the
// first section that touches it, so every later section goes unmeasured and a
// nine-line control stands in for a forty-line one. This reports the absence
// and lets the rest of the file run.
const listOf = (v) => (Array.isArray(v) ? v : null);
const lenIs = (v, n) => {
  const a = listOf(v);
  return a !== null && a.length === n;
};

// A source assertion that counts the comment saying a thing was fixed is not
// an assertion. Prose goes first, everywhere below.
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

// The module, transpiled rather than sliced out of a screen.
const babel = require('@babel/core');
const MODULE = path.join(FRONTEND, 'src', 'utils', 'amendmentChain.js');
const { code } = babel.transformSync(fs.readFileSync(MODULE, 'utf8'), {
  filename: MODULE,
  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false,
  babelrc: false,
});
const M = {};
// eslint-disable-next-line no-new-func
new Function('exports', 'module', 'require', code)(M, { exports: M }, require);

// ── the documents, in the shapes the server returns ────────────────────────
//
// NOTE WHAT IS NOT ON THEM. A daily jobsite log carries no `data.worker_id`
// and no `data.worker_name`, which is the entire G2 defect: `chainKey` returns
// null for it and `collapseChains` passed it through.
const filed = (id, at, over = {}) => ({
  id, log_type: 'daily_jobsite', date: '2026-09-02',
  status: 'submitted', is_locked: true, created_at: at,
  data: { weather: 'Sunny' }, ...over,
});
const child = (id, parent, at, over = {}) =>
  filed(id, at, { is_amendment: true, parent_logbook_id: parent, ...over });
const draftChild = (id, parent, at, over = {}) =>
  child(id, parent, at, { status: 'draft', is_locked: false, ...over });

console.log('\n1. A TYPE WITH NO WORKER KEY NOW COLLAPSES');
{
  const rows = [
    filed('orig', '2026-09-02T08:00:00Z'),
    child('amd', 'orig', '2026-09-02T10:00:00Z'),
  ];
  ok(M.chainKey(rows[0]) === null,
    'the worker key still returns null for a daily jobsite log');
  const out = M.collapseChains(rows);
  ok(out.length === 1, 'and the chain is one row anyway — keyed on the chain');
  ok(out[0].id === 'amd', 'the head is the filed amendment');
  ok(out[0]._chain_length === 2, 'and it says how many documents it is made of');
}

console.log('\n2. EVERY TYPE THE WORKER KEY NEVER REACHED');
{
  const types = ['daily_jobsite', 'toolbox_talk', 'preshift_signin',
    'osha_log', 'scaffold_maintenance', 'site_superintendent_log'];
  const rows = [];
  types.forEach((t) => {
    rows.push(filed(`${t}_o`, '2026-09-02T08:00:00Z', { log_type: t }));
    rows.push(child(`${t}_a`, `${t}_o`, '2026-09-02T09:00:00Z', { log_type: t }));
  });
  const out = M.collapseChains(rows);
  ok(out.length === types.length,
    `${types.length} records from ${rows.length} documents`);
  ok(out.every((h) => h.id.endsWith('_a')), 'each one is its chain\'s head');
}

console.log('\n3. FOUR DEEP, AND A PARENT THAT IS ITSELF AN AMENDMENT');
{
  // Production's histogram reaches depth 4, and 11 live children have a parent
  // that is itself an amendment. A walk that read one link and stopped would
  // draw the inspector two records again, one link further down.
  const rows = [
    filed('l1', '2026-09-02T08:00:00Z'),
    child('l2', 'l1', '2026-09-02T09:00:00Z'),
    child('l3', 'l2', '2026-09-02T10:00:00Z'),
    child('l4', 'l3', '2026-09-02T11:00:00Z'),
  ];
  const out = M.collapseChains(rows);
  ok(out.length === 1, 'four documents, one record');
  ok(out[0].id === 'l4', 'and the head is the deepest filed link');
  ok(out[0]._chain_length === 4, 'the length is the whole chain');
}

console.log('\n4. THE ORDER IT ARRIVES IN IS NOT THE ORDER OF THE CHAIN');
{
  const out = M.collapseChains([
    child('l3', 'l2', '2026-09-02T10:00:00Z'),
    filed('l1', '2026-09-02T08:00:00Z'),
    child('l2', 'l1', '2026-09-02T09:00:00Z'),
  ]);
  ok(out.length === 1 && out[0].id === 'l3',
    'a grandchild that arrives before its parent still finds the root');
}

console.log('\n5. A FILED FORK IS NAMED, NOT SILENTLY RESOLVED');
{
  const rows = [
    filed('orig', '2026-09-02T08:00:00Z'),
    child('fork_a', 'orig', '2026-09-02T10:00:00Z'),
    child('fork_b', 'orig', '2026-09-02T11:00:00Z'),
  ];
  const h = M.chainHead(rows);
  ok(h.id === 'fork_b', 'the tie-break is unchanged and still deterministic');
  ok(lenIs(h._competing_records, 1)
    && h._competing_records[0].id === 'fork_a',
    'and the correction it did not pick is reported rather than dropped');
  ok(lenIs(h._open_corrections, 0),
    'nothing is open — which is exactly why _open_corrections could not see this');
}

console.log('\n6. THE UNSIGNED FORK REFUSAL IS PRESERVED');
{
  // 588 Thomas, 2026-08-14: two unsigned children of one parent, 26s apart.
  const rows = [
    filed('p1', '2026-08-14T20:00:00Z'),
    draftChild('c1', 'p1', '2026-08-14T20:23:11Z'),
    draftChild('c2', 'p1', '2026-08-14T20:23:37Z'),
  ];
  const h = M.chainHead(rows);
  ok(h.id === 'p1', 'an unsigned amendment is an intention, not the record');
  ok(lenIs(h._open_corrections, 2), 'BOTH open children are still reported');
  ok(lenIs(h._competing_records, 0),
    'and neither is called a filed competitor');
}

console.log('\n7. A LINEAR CHAIN OF ANY DEPTH HAS NO COMPETITORS');
{
  const h = M.chainHead([
    filed('l1', '2026-09-02T08:00:00Z'),
    child('l2', 'l1', '2026-09-02T09:00:00Z'),
    child('l3', 'l2', '2026-09-02T10:00:00Z'),
    child('l4', 'l3', '2026-09-02T11:00:00Z'),
  ]);
  ok(lenIs(h._competing_records, 0),
    'every filed link is an ancestor of the head, so none competes with it');
}

console.log('\n8. THE ORIENTATION GROUPING IS UNCHANGED');
{
  const W = (wid) => ({ worker_id: wid, worker_name: `Worker ${wid}` });
  const orient = (id, wid, at, over = {}) => ({
    id, log_type: 'subcontractor_orientation', date: '2026-08-31',
    status: 'submitted', is_locked: true, created_at: at, data: W(wid), ...over,
  });

  // Two men, one row each.
  const two = M.collapseChains([
    orient('a', 'W1', '2026-08-31T12:00:00Z'),
    orient('b', 'W2', '2026-08-31T12:00:00Z'),
  ]);
  ok(two.length === 2, 'two workers stay two rows');

  // ONE MAN, TWO UNLINKED ORIGINALS. Grouped by worker today; keying on the
  // chain alone would split him, which is a behaviour change this is not.
  const same = M.collapseChains([
    orient('a1', 'W1', '2026-08-31T12:00:00Z'),
    orient('a2', 'W1', '2026-08-31T13:00:00Z'),
  ]);
  ok(same.length === 1, 'one man with two unlinked originals is still one row');
  ok(lenIs(same[0]._competing_records, 0),
    'and neither original is reported as a correction competing with the other');

  // The operator's original report: six rows for one man.
  const six = M.collapseChains([
    orient('p', 'W1', '2026-08-31T12:43:06Z'),
    orient('a1', 'W1', '2026-08-31T17:02:27Z', { is_amendment: true, parent_logbook_id: 'p' }),
    orient('a2', 'W1', '2026-08-31T17:03:30Z', { is_amendment: true, parent_logbook_id: 'a1' }),
    orient('a3', 'W1', '2026-08-31T17:05:02Z', { is_amendment: true, parent_logbook_id: 'a2' }),
    orient('d1', 'W1', '2026-08-31T17:09:58Z', { is_amendment: true, parent_logbook_id: 'a3', status: 'draft', is_locked: false }),
    orient('d2', 'W1', '2026-08-31T17:10:47Z', { is_amendment: true, parent_logbook_id: 'a3', status: 'draft', is_locked: false }),
  ]);
  ok(six.length === 1 && six[0]._chain_length === 6,
    'six documents, one row, and it remembers the six');
  ok(six[0].id === 'a3', 'the head is the deepest SIGNED link');
  ok(lenIs(six[0]._open_corrections, 2),
    'the two open corrections are both still reported');
}

console.log('\n9. NOTHING IS EVER DROPPED TO MAKE A LIST TIDY');
{
  const orphan = M.collapseChains([
    child('lonely', 'a_parent_not_in_this_list', '2026-09-02T10:00:00Z'),
  ]);
  ok(orphan.length === 1 && orphan[0].id === 'lonely',
    'an amendment whose parent is absent becomes its own root and is SHOWN');

  const unkeyable = M.collapseChains([
    { log_type: 'daily_jobsite', status: 'submitted', is_locked: true },
  ]);
  ok(unkeyable.length === 1,
    'and a row with no id and no worker is passed through, not lost');

  // A self-parent, or a pair naming each other, is a write nobody has ruled
  // out. An infinite loop here is a frozen screen on the tablet.
  const a = child('a', 'b', '2026-09-02T08:00:00Z');
  const b = child('b', 'a', '2026-09-02T09:00:00Z');
  const cycled = M.collapseChains([a, b]);
  ok(cycled.length >= 1, 'a cycle returns rather than hanging');
  ok(cycled.reduce((n, h) => n + (h._chain_length || 1), 0) === 2,
    'and no document is lost to it');
}

console.log('\n10. THE CP\'S STATUS PILL NOW MATCHES THE RULE IT DOCUMENTS');
{
  // `logTypeStatus` says, in its own words, that the question is "is every
  // worker's CURRENT record filed?" and that reading Draft over a signed day
  // "would tell a CP his signed day is unfinished". It asks that question
  // through `collapseChains` — so for the twelve types the worker key never
  // reached, it was not asking it at all: an original plus an unsigned
  // amendment came back as two unkeyed rows, one of them a draft, and the
  // pill read Draft over a filed record.
  const rows = [
    filed('orig', '2026-09-02T08:00:00Z'),
    draftChild('amd', 'orig', '2026-09-02T10:00:00Z'),
  ];
  ok(M.logTypeStatus(rows) === 'submitted',
    'a filed daily log with an open correction reads SUBMITTED, not Draft');

  // AND IT MUST NOT BECOME "ANY DRAFT EXISTS" IN THE OTHER DIRECTION. A day
  // whose only record is an unfiled draft is genuinely unfinished.
  ok(M.logTypeStatus([
    filed('d', '2026-09-02T08:00:00Z', { status: 'draft', is_locked: false }),
  ]) === 'draft', 'and a genuinely unfiled record still reads Draft');
}

console.log('\n11. THE INSPECTOR\'S LIST SAYS WHICH RECORD IS CURRENT');
{
  // G1's other half. Before this, `is_amendment`, `AMENDED` and
  // `amendmentReason` appeared ZERO times in this file and every link of a
  // chain drew its own card.
  const SCREEN = stripComments(read('app', 'site', 'logbooks.jsx'));

  ok(/AmendmentMarker/.test(SCREEN), 'the screen has an amendment marker');
  ok(/log\.amendment_sentence/.test(SCREEN),
    'it prints the sentence the SERVER composed');
  ok(/_chain_length/.test(SCREEN), 'and reads how many documents the record is');
  ok(/_competing_records/.test(SCREEN), 'and surfaces a fork as a fork');

  // ABOVE THE CONTENT. An inspector must know he is reading the current
  // version before he reads a field of it. Sliced between two anchors that
  // both exist exactly once, so the bound cannot silently widen to the file.
  const anchor = '<AmendmentMarker log={log} />';
  const content = '{renderLogContent(log)}';
  ok(SCREEN.split(anchor).length === 2, 'the marker is rendered exactly once');
  ok(SCREEN.split(content).length === 2, 'and the content exactly once');
  // BOTH PRESENT, THEN ORDERED. `indexOf` returns -1 for a string that is not
  // there, and -1 is less than every real offset — so an ordering test written
  // as `indexOf(a) < indexOf(b)` PASSES when the marker does not exist at all.
  // It passed against the unmodified screen, which is a reading no absence
  // could have failed.
  const iMark = SCREEN.indexOf(anchor);
  const iContent = SCREEN.indexOf(content);
  ok(iMark > -1 && iContent > -1 && iMark < iContent,
    'the marker is drawn before the record\'s contents');

  // THE RULE IS NOT RE-DERIVED ON THE DEVICE. A second supersession rule on
  // the tablet is how the screen and the PDF come to disagree about one
  // record. The screen reads three fields; it does not pick a head.
  ok(!/collapseChains|chainHead/.test(SCREEN),
    'the screen does not re-collapse what the server already collapsed');
}

console.log(failures === 0 ? '\nPASS\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
