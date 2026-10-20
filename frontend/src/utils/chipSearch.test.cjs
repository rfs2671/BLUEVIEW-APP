/**
 * Type-ahead over the whole activity catalogue: reach restored, clutter not.
 *
 * Run:  node src/utils/chipSearch.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } };
const eq = (a, b, l) => { const s = JSON.stringify(a) === JSON.stringify(b); ok(s, `${l}${s ? '' : ` — got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`}`); };

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8').split('\r\n').join('\n');
const raw = read('src', 'utils', 'dailyJobsiteModel.js');
const body = raw.replace(/^export default [\s\S]*$/m, '').replace(/^export (const|function|let) /gm, '$1 ');
// eslint-disable-next-line no-new-func
const M = new Function(`${body}\n return { searchChips };`)();

const CATALOGUE = [
  { id: 'shoring', label: 'shoring' }, { id: 'piles', label: 'piles' }, { id: 'site_prep', label: 'site prep' },
  { id: 'under_slab_mep', label: 'under-slab MEP' }, { id: 'pour_slab', label: 'pour slab' },
  { id: 'conc_mesh', label: 'mesh' }, { id: 'conc_slab_on_grade', label: 'slab on grade' },
  { id: 'pour_cellar_slab', label: 'pour cellar slab' }, { id: 'other', label: 'other' },
];

console.log('\n── nothing is listed until a person types ──');
eq(M.searchChips(CATALOGUE, ''), [], 'an empty query lists nothing');
eq(M.searchChips(CATALOGUE, 'p'), [], 'one letter lists nothing');
eq(M.searchChips(CATALOGUE, '   '), [], 'blanks list nothing');
eq(M.searchChips(CATALOGUE, null), [], 'null does not throw');

console.log('\n── what the first real backtest could not reach ──');
eq(M.searchChips(CATALOGUE, 'pil').map((c) => c.id), ['piles'], 'piles by "pil"');
eq(M.searchChips(CATALOGUE, 'shor').map((c) => c.id), ['shoring'], 'shoring by "shor"');
eq(M.searchChips(CATALOGUE, 'mesh').map((c) => c.id), ['conc_mesh'], 'mesh, which sat at position 28');
eq(M.searchChips(CATALOGUE, 'slab').map((c) => c.id),
  ['slab on grade', 'pour slab', 'under-slab MEP', 'pour cellar slab'].map((l) => CATALOGUE.find((c) => c.label === l).id),
  'slab: names that START with it first, then the shorter');
eq(M.searchChips(CATALOGUE, 'SLAB ON').map((c) => c.id), ['conc_slab_on_grade'], 'case does not matter; every word must match');

console.log('\n── the invariants ──');
ok(!M.searchChips(CATALOGUE, 'oth').some((c) => c.id === 'other'), 'the Other chip is never a result (it is always on the card)');
eq(M.searchChips(CATALOGUE, 'slab', ['pour_slab']).map((c) => c.id).includes('pour_slab'), false, 'a chip already on the card is not repeated');
eq(M.searchChips([{ id: 'x', label: 'slab' }, { id: 'x', label: 'slab' }], 'sl').length, 1, 'a chip appears once');
eq(M.searchChips([null, 5, { id: 1, label: 'slab' }, { id: 'a' }, { id: 'b', label: 'slab' }], 'slab').map((c) => c.id), ['b'], 'malformed entries are skipped, not thrown');
eq(M.searchChips('nonsense', 'slab'), [], 'a non-list catalogue is []');
eq(M.searchChips(Array.from({ length: 40 }, (_, i) => ({ id: `s${i}`, label: `slab ${i}` })), 'slab').length, 12, 'at most 12 results');
ok(M.searchChips([{ id: 'other:Foundation pile', label: 'Foundation pile' }], 'pile').length === 0, 'a remembered free-text entry is not a catalogue activity');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
