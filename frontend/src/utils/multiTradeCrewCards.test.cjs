/**
 * One company, several trades: the crew card's chip set, "More work", and the
 * `work_trades` every saved activity row carries.
 *
 * THE REPORT (operator, 2026-11-18): "since theres one company doing multiple
 * stuff {painting sheetrock taping compound framing etc} when i look on the
 * cards to add sheetrock or stuff like that its nowhere to be added".
 *
 * A card is one (company, trade) of who checked in, and a worker holds ONE
 * trade per project. The card offered that one trade's chips; another trade's
 * were unreachable from it; the type-ahead searched only the sequence graph,
 * where "hang board", "prime" and "skim coat" do not exist and "sheetrock"
 * matches nothing. These run the shipped model functions.
 *
 * Run:  node src/utils/multiTradeCrewCards.test.cjs
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
const NAMES = ['composeChipBands', 'crewChipKey', 'workTradesFor', 'claimantsIndex',
  'catalogTradeChips', 'searchCatalog'];
// eslint-disable-next-line no-new-func
const M = new Function(`${body}\n return { ${NAMES.map((n) => `${n}: typeof ${n} === 'undefined' ? undefined : ${n}`).join(', ')} };`)();
const missing = NAMES.filter((n) => typeof M[n] !== 'function');
ok(missing.length === 0, `the model exports the multi-trade helpers${missing.length ? ` — missing ${missing.join(', ')}` : ''}`);
const call = (n, ...a) => { try { return typeof M[n] === 'function' ? M[n](...a) : undefined; } catch (e) { return `threw ${e.message}`; } };

// What GET activity-chips?trade=Framing&company=Acme returns now: the card's
// own trade first, then the company's other rostered trades (catalog band).
const chip = (id, label, band, workTrade, claimants) => ({
  id, label, band, work_trade: workTrade, catalog_trades: claimants || [workTrade],
});
const FRAMING_CARD = [
  chip('interior_framing', 'interior framing', 'catalog', 'Interior framing'),
  chip('iframe_metal_stud', 'metal stud framing', 'catalog', 'Interior framing'),
  chip('iframe_ceiling_drops', 'ceiling drops', 'catalog', 'Interior framing'),
  chip('blocking', 'blocking', 'catalog', 'Interior framing', ['Wood framing', 'Carpentry (rough)', 'Interior framing']),
  chip('wood_wall_framing', 'wall framing', 'catalog', 'Wood framing'),
  chip('drywall', 'drywall', 'catalog', 'Drywall'),
  chip('taping', 'taping', 'catalog', 'Drywall'),
  chip('dry_spackle_compound', 'spackle / compound', 'catalog', 'Drywall'),
  chip('paint', 'paint', 'catalog', 'Painting'),
  chip('paint_prime', 'prime', 'catalog', 'Painting'),
  { id: 'other', label: 'other', band: 'other', catalog_trades: [], work_trade: null },
];
const OWN = ['Interior framing', 'Wood framing'];
const COMPANY = ['Interior framing', 'Wood framing', 'Drywall', 'Painting'];

console.log('\n── the card: its own trade first, then its company\'s other trades ──');
{
  const r = call('composeChipBands', { chips: FRAMING_CARD, resolvedTrades: OWN, companyTrades: COMPANY, priorDate: '2026-11-17' }) || {};
  eq((r.primary || []).map((c) => c.id), ['interior_framing', 'iframe_metal_stud', 'iframe_ceiling_drops', 'blocking'],
    'the four inline are the card\'s OWN trade');
  eq(r.basis, 'trade', 'and they say they are the trade\'s list, not a ranking');
  const rest = (r.rest || []).map((c) => c.id);
  ['taping', 'dry_spackle_compound', 'drywall', 'paint', 'paint_prime', 'wood_wall_framing'].forEach((id) => {
    ok(rest.includes(id), `${id} is reachable from the card's expander`);
  });
  ok(!rest.includes('other'), 'Other is not in the expander (it is always on the card)');
  eq((r.restGroups || []).map((g) => g.trade), ['Wood framing', 'Drywall', 'Painting'],
    'the expander is grouped by trade, own trade first');
  eq((r.restGroups || []).map((g) => g.chips.length), [1, 3, 2], 'every remaining chip is in exactly one group');
}
{
  // A crew typed "Laborer" resolves to nothing; the server narrowed it to its
  // company's trades, and the card promotes them instead of folding everything.
  const r = call('composeChipBands', { chips: FRAMING_CARD.slice(5), resolvedTrades: [], companyTrades: ['Drywall', 'Painting'], priorDate: null }) || {};
  eq((r.primary || []).map((c) => c.id), ['drywall', 'taping', 'dry_spackle_compound', 'paint'],
    'an unresolved crew trade with a rostered company gets that company\'s work inline');
}
{
  // Unchanged: no company trades, no resolved trade -> the old fold.
  const r = call('composeChipBands', { chips: FRAMING_CARD, resolvedTrades: [], priorDate: null }) || {};
  eq((r.primary || []).length, 0, 'an untraded crew with no company still gets nothing promoted');
  const single = call('composeChipBands', { chips: FRAMING_CARD.slice(0, 4), resolvedTrades: ['Interior framing'], priorDate: null }) || {};
  eq((single.restGroups || []).length, 0, 'four own-trade chips fill the slots and leave nothing to group');
}

console.log('\n── the cache key separates companies ──');
eq(call('crewChipKey', 'Framing', ''), 'Framing', 'no company: keyed on the trade, exactly as before');
eq(call('crewChipKey', ' Framing ', null), 'Framing', 'trimmed');
eq(call('crewChipKey', '', ''), '', '\'\' is still the unfiltered list');
ok(call('crewChipKey', 'Framing', 'Acme') !== call('crewChipKey', 'Framing', 'Bolt'),
  'two Framing crews of two companies are two lists');
eq(call('crewChipKey', 'Framing', ' ACME '), call('crewChipKey', 'Framing', 'acme'),
  'the company matches the way the roster matches (rosterKey)');

console.log('\n── work_trades: what the saved row says the work WAS ──');
const claim = call('claimantsIndex', [FRAMING_CARD], [{ trade: 'Masonry', activities: [{ id: 'flashing', label: 'flashing', catalog_trades: ['Masonry', 'Roofing'] }] }]);
ok(claim instanceof Map && claim.get('taping')?.[0] === 'Drywall', 'claimants come from the chips the card holds');
ok(claim instanceof Map && claim.get('flashing')?.length === 2, 'and from the "More work" catalogue');
eq(call('workTradesFor', ['interior_framing', 'taping', 'paint_prime', 'dry_spackle_compound'], claim, [...OWN, ...COMPANY], OWN),
  ['Interior framing', 'Drywall', 'Painting'], 'distinct catalog trades, in chip order');
eq(call('workTradesFor', ['blocking'], claim, OWN, OWN), ['Interior framing'],
  'a node several trades claim goes to the first claimant in context');
eq(call('workTradesFor', ['blocking'], claim, [], []), ['Wood framing'], 'and to its first claimant with no context');
eq(call('workTradesFor', ['flashing'], claim, ['Roofing'], []), ['Roofing'], 'the trade it was picked under wins');
eq(call('workTradesFor', ['other:moved material'], claim, OWN, OWN), OWN, 'free text only: the card\'s own trade');
eq(call('workTradesFor', [], claim, OWN, OWN), [], 'nothing selected: no work trade');
eq(call('workTradesFor', null, null, 5, 'x'), [], 'garbage in, [] out — never throws');

console.log('\n── More work: any catalog trade, from any card ──');
const CATALOG = [
  { trade: 'Interior framing', aliases: ['interior framing', 'metal stud', 'framing'], activities: [
    { id: 'interior_framing', label: 'interior framing', catalog_trades: ['Interior framing'] },
    { id: 'iframe_metal_stud', label: 'metal stud framing', catalog_trades: ['Interior framing'] }] },
  { trade: 'Drywall', aliases: ['drywall', 'sheetrock', 'tape', 'masilla', 'compound'], activities: [
    { id: 'drywall', label: 'drywall', catalog_trades: ['Drywall'] },
    { id: 'taping', label: 'taping', catalog_trades: ['Drywall'] },
    { id: 'dry_spackle_compound', label: 'spackle / compound', catalog_trades: ['Drywall'] },
    { id: 'dry_hang_board', label: 'hang board', catalog_trades: ['Drywall'] },
    { id: 'patching', label: 'patching', catalog_trades: ['Foundation / Concrete', 'Drywall'] }] },
  { trade: 'Painting', aliases: ['painting', 'painter', 'pintura'], activities: [
    { id: 'paint', label: 'paint', catalog_trades: ['Painting'] },
    { id: 'paint_prime', label: 'prime', catalog_trades: ['Painting'] }] },
  { trade: 'General conditions', aliases: [], activities: [{ id: 'other', label: 'other', catalog_trades: [] }] },
];
const ids = (r) => (Array.isArray(r) ? r.map((c) => c.id) : []);
eq(ids(call('catalogTradeChips', CATALOG, 'Painting')), ['paint', 'paint_prime'], 'a picked trade lists its work');
eq((call('catalogTradeChips', CATALOG, 'Drywall') || []).map((c) => c.work_trade)[4], 'Drywall',
  'picked under Drywall, patching counts as Drywall');
eq(call('catalogTradeChips', CATALOG, 'Nope'), [], 'an unknown trade lists nothing');
ok(ids(call('searchCatalog', CATALOG, 'sheetrock')).includes('dry_hang_board'),
  '"sheetrock" finds the drywall crew\'s work (no label says sheetrock)');
ok(ids(call('searchCatalog', CATALOG, 'compound'))[0] === 'dry_spackle_compound', '"compound" finds spackle / compound first');
ok(ids(call('searchCatalog', CATALOG, 'masilla')).includes('dry_spackle_compound'), '"masilla" finds it in Spanish');
ok(ids(call('searchCatalog', CATALOG, 'tape')).includes('taping'), '"tape" finds taping');
ok(ids(call('searchCatalog', CATALOG, 'pintura')).includes('paint_prime'), '"pintura" finds the painting work');
eq(ids(call('searchCatalog', CATALOG, 'prim')), ['paint_prime'], 'a label match by its own words');
ok(!ids(call('searchCatalog', CATALOG, 'oth')).includes('other'), 'Other is never a result');
ok(!ids(call('searchCatalog', CATALOG, 'sheetrock', ['taping'])).includes('taping'), 'a chip already on the card is not repeated');
eq(call('searchCatalog', CATALOG, 's'), [], 'one letter lists nothing');
eq(call('searchCatalog', 'junk', 'taping'), [], 'a non-list catalogue is []');

console.log('\n── the screen wires it ──');
const screen = read('app', 'logbooks', 'daily_jobsite.jsx');
ok(/work_trades: rowWorkTrades\(act, act\.activity_ids \|\| \[\]\)/.test(screen),
  'every row in the save payload carries work_trades');
ok(/work_trades: rowWorkTrades\(a, ids, has \? null : pickedTrade\)/.test(screen),
  'and a chip tap stamps it on the row (so the autosaved draft carries it too)');
ok(/companyTrades: meta\?\.company_trades/.test(screen), 'the card passes its company\'s trades to the composer');
ok(/t\('chipsMoreWork'\)/.test(screen) && /catalogTradeChips\(tradeCatalog,/.test(screen),
  'the card renders "More work" from the whole catalogue');
ok(/searchCatalog\(tradeCatalog, typed, onCard\)/.test(screen), 'the type-ahead searches the whole catalogue');
const en = read('src', 'i18n', 'en.js');
ok(/chipsMoreWork: 'More work \/ Más trabajos'/.test(en), 'the control reads in English and Spanish');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
