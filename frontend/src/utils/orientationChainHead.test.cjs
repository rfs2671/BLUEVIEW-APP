/**
 * One row per worker, showing the head of the chain.
 *
 * THE OPERATOR'S ORIGINAL REPORT. Angel Lopez showed SIX rows on 588 Thomas:
 * one orientation and five amendments of it, drawn as siblings with nothing
 * saying which was current. The list endpoint does not filter `is_amendment`
 * and the screen had no reference to it, so every link drew its own card. It
 * read as a duplication bug and was not one — it was a chain, rendered flat.
 *
 * THE HEAD IS THE DEEPEST SIGNED LINK, the same rule _filed_log applies on the
 * server. An unsigned amendment is an intention, not a correction.
 *
 * AND AN UNSIGNED HEAD MUST NOT READ AS THE RECORD. When the newest link is
 * unsigned the row carries the last SIGNED link's content and is flagged
 * `_open_correction` — saying "signed" would be false, and dropping it would
 * hide work the CP has to finish.
 *
 * Run:  node src/utils/orientationChainHead.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'subcontractor_orientation.jsx'), 'utf8',
).split('\r\n').join('\n');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

// The rule now lives in ONE module, imported by the orientation editor AND the
// reports tab. Transpiled rather than sliced out of a screen: a rule written
// twice is two rules the moment one is edited.
const babel = require('@babel/core');
const MODULE = path.join(FRONTEND, 'src', 'utils', 'amendmentChain.js');
const { code } = babel.transformSync(fs.readFileSync(MODULE, 'utf8'), {
  filename: MODULE,
  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false,
  babelrc: false,
});
const mod = {};
// eslint-disable-next-line no-new-func
new Function('exports', 'module', 'require', code)(mod, { exports: mod }, require);
const M = mod;

const row = (id, over = {}) => ({
  id, data: { worker_id: 'W1', worker_name: 'Angel Lopez' },
  created_at: over.at || '2026-08-31T12:43:06Z',
  status: 'draft', cp_signature: null, ...over,
});
const signed = (id, at) => row(id, { at, status: 'submitted', cp_signature: { d: 'ink' } });
const draft = (id, at) => row(id, { at });

console.log('\n1. SIX ROWS BECOME ONE');
{
  const chain = [
    signed('p', '2026-08-31T12:43:06Z'),
    signed('a1', '2026-08-31T17:02:27Z'),
    signed('a2', '2026-08-31T17:03:30Z'),
    signed('a3', '2026-08-31T17:05:02Z'),
    draft('d1', '2026-08-31T17:09:58Z'),
    draft('d2', '2026-08-31T17:10:47Z'),
  ];
  const out = M.collapseChains(chain);
  ok(out.length === 1, 'one row for one worker, not six');
  ok(out[0]._chain_length === 6, 'and it remembers how long the chain is');
}

console.log('\n2. THE HEAD IS THE DEEPEST SIGNED LINK');
{
  const h = M.chainHead([
    signed('p', '2026-08-31T12:43:06Z'),
    signed('a3', '2026-08-31T17:05:02Z'),
    signed('a1', '2026-08-31T17:02:27Z'),
  ]);
  ok(h.id === 'a3', 'the newest SIGNED link is the record');

  const withDrafts = M.chainHead([
    signed('a3', '2026-08-31T17:05:02Z'),
    draft('d2', '2026-08-31T17:10:47Z'),
  ]);
  ok(withDrafts.id === 'a3',
    'an unsigned amendment does NOT become the record just by being newer');
}

console.log('\n3. AN OPEN CORRECTION IS FLAGGED, NOT HIDDEN AND NOT PROMOTED');
{
  const h = M.chainHead([
    signed('a3', '2026-08-31T17:05:02Z'),
    draft('d1', '2026-08-31T17:09:58Z'),
    draft('d2', '2026-08-31T17:10:47Z'),
  ]);
  ok(h._open_corrections.length === 2,
    'BOTH open corrections are surfaced — the fork is shown, not resolved');
  ok(h._open_corrections[0].id === 'd2',
    'newest first, deterministically');
  ok(h.id === 'a3', 'while still showing the signed record as the content');
}

console.log('\n4. THE ORDINARY CASES');
{
  const onlyDraft = M.chainHead([draft('p', '2026-08-31T12:43:06Z')]);
  ok(onlyDraft.id === 'p' && onlyDraft._open_corrections.length === 0,
    'an unsigned ORIGINAL is not an open correction — it is a new orientation');

  const one = M.collapseChains([signed('p', '2026-08-31T12:43:06Z')]);
  ok(one.length === 1 && one[0]._chain_length === 1,
    'a worker with one record gets one row, chain length 1');

  ok(M.collapseChains([]).length === 0, 'an empty list is empty');
  ok(M.collapseChains(null).length === 0, 'a null list is empty');
}

console.log('\n5. IDENTITY — worker_id, name only as a FALLBACK');
{
  const filed = (id, wid, name, at) => ({
    id, data: { worker_id: wid, worker_name: name },
    created_at: at, status: 'submitted', cp_signature: { d: 'i' },
  });
  const a = filed('a', 'W1', 'Angel Lopez', '2026-08-31T12:00:00Z');
  const b = filed('b', 'W2', 'Angel Lopez', '2026-08-31T13:00:00Z');
  ok(M.collapseChains([a, b]).length === 2,
    'TWO MEN SHARING A NAME STAY TWO — merging them would put one man\'s '
    + 'orientation on another man\'s compliance record');

  const noId1 = { id: 'n1', data: { worker_name: 'Juan Lopez' },
    created_at: '2026-08-31T12:00:00Z', status: 'submitted', cp_signature: { d: 'i' } };
  const withId = filed('w', 'W9', 'Juan Lopez', '2026-08-31T14:00:00Z');
  ok(M.collapseChains([noId1, withId]).length === 2,
    'an id-less row is NEVER absorbed into an id-bearing chain by name alone');

  ok(M.chainKey(a) === 'id:W1', 'an id-bearing row keys on the id');
  ok(M.chainKey(noId1) === 'name:juan lopez', 'an id-less row falls back to name');
  ok(M.chainKey({ data: {} }) === null, 'a row with neither cannot be keyed');
}

console.log('\n6. NOTHING IS DROPPED');
{
  const noId = { id: 'x', data: {}, status: 'draft' };
  const out = M.collapseChains([signed('p', '2026-08-31T12:43:06Z'), noId]);
  ok(out.length === 2,
    'a row with no worker id cannot be chained and must still render');

  const two = M.collapseChains([
    { ...signed('p', '2026-08-31T12:43:06Z') },
    { id: 'q', data: { worker_id: 'W2', worker_name: 'Juan Lopez' },
      created_at: '2026-08-31T12:44:00Z', status: 'submitted', cp_signature: { d: 'i' } },
  ]);
  ok(two.length === 2, 'two workers still get two rows');
}

console.log('\n7. THE SCREEN SAYS IT');
{
  ok(/_open_corrections \|\| \[\]/.test(SRC), 'the row renders the open-correction state');
  ok(/Corrected \$\{orient\._chain_length - 1\} time/.test(SRC),
    'and the card states the chain depth, so an amended record does not read '
    + 'as an original');
  ok(/competing corrections open/.test(SRC)
     && /signing either supersedes the other/.test(SRC),
  'and a FORK is shown as competing, with what signing one does');
  ok(/Correction open — not signed yet/.test(SRC),
    'and says it is NOT signed, so it cannot read as the record');
  ok(/from '\.\.\/\.\.\/src\/utils\/amendmentChain'/.test(SRC),
    'the screen imports the shared rule rather than carrying its own copy');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
