/**
 * ACTIVITY ROW IDENTITY on daily_jobsite's data.activities[].
 *
 * Rows had no identity at all: they were addressed by their INDEX in the array,
 * which changes the moment a row is added or reordered. Two fields fix that and
 * both are asserted here against the REAL shipped source:
 *
 *   activity_id       — stable per-row id, minted on the device (a row can be
 *                       created with no signal, so it cannot be server-owned).
 *   subcontractor_id  — the project roster row id (project.trade_assignments[].id,
 *                       minted server-side as `srv_<uuid4hex>`), carried through
 *                       GET /daily-headcount.
 *
 * The hard rule is that absence is represented HONESTLY. A row the CP enters as
 * "Other", a row whose company the admin has not put on the roster yet, and a
 * row with no company at all all carry NO subcontractor_id. A placeholder id
 * there would merge unrelated subs — into one photo bucket, and into one line of
 * a signed compliance record.
 *
 * WHERE THE CODE MOVED. The U1 stepper rebuild lifted all of this out of the
 * .jsx and into src/utils/dailyJobsiteModel.js, so that decisions landing in a
 * signed record could be EXECUTED by a test instead of extracted from a
 * component by brace matching. Every guarantee below is the same one this file
 * always made; only the address changed. Three of them are unchanged
 * source-level greps, and those still read the screen.
 *
 * Two behaviours are stronger than before and are asserted as such:
 *   * the roster index is keyed on (company, TRADE), so a company working two
 *     trades no longer has to be dropped as ambiguous — it has two rows and
 *     two ids, and each resolves exactly.
 *   * seeding no longer writes the trade into work_description (Finding C).
 *
 * No test runner in this repo (see RiskScoreCircle.bandFor.test.cjs): the ESM
 * model is read, stripped and evaluated. Nothing below is a hand-copy.
 *
 * Run:  node src/utils/activityIdentity.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const MODEL = path.join(__dirname, 'dailyJobsiteModel.js');
const src = fs.readFileSync(SCREEN, 'utf8');
const modelSrc = fs.readFileSync(MODEL, 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const noComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

// ── Load the model ───────────────────────────────────────────────────────────
const M = new Function(`
  ${modelSrc.replace(/^export default [\s\S]*$/m, '').replace(/^export (const|function|let) /gm, '$1 ')}
  return { EMPTY_ACTIVITY, newActivityId, rosterKey, buildCrewsFromRoster,
           rosterIdIndex, resolveRosterId, isUnboundCrew };
`)();

// ── 1. EMPTY_ACTIVITY ────────────────────────────────────────────────────────
{
  const a = M.EMPTY_ACTIVITY();
  const b = M.EMPTY_ACTIVITY();
  ok(typeof a.activity_id === 'string' && a.activity_id.length > 0,
    'EMPTY_ACTIVITY: mints a non-empty activity_id');
  ok(Object.prototype.hasOwnProperty.call(a, 'subcontractor_id'),
    'EMPTY_ACTIVITY: declares subcontractor_id');
  ok(a.subcontractor_id === null,
    'EMPTY_ACTIVITY: a hand-added row starts with NO roster identity');
  ok(a.activity_id !== b.activity_id, 'EMPTY_ACTIVITY: two rows never share an id');

  const many = new Set(Array.from({ length: 500 }, () => M.EMPTY_ACTIVITY().activity_id));
  ok(many.size === 500, 'ids stay unique across 500 rows minted in the same millisecond');

  for (const f of ['crew_id', 'company', 'num_workers', 'work_description',
    'work_locations', 'photos']) {
    ok(Object.prototype.hasOwnProperty.call(a, f), `EMPTY_ACTIVITY: still carries ${f}`);
  }
}

// ── 2. Seeding from the gate roster ──────────────────────────────────────────
const HEADCOUNT = [
  { sub_name: 'Acme Co', trade: 'Carpenter', worker_count_today: 4, subcontractor_id: 'srv_acme1' },
  { sub_name: 'Volt LLC', trade: 'Electrical', worker_count_today: 2, subcontractor_id: 'srv_v' },
];
const worker = (over) => ({
  worker_id: `w${Math.random()}`, worker_name: 'X', company: 'Acme Co',
  trade: 'Carpenter', check_in_time: '2026-03-04T12:00:00Z', ...over,
});

{
  const rows = M.buildCrewsFromRoster(
    [worker(), worker(), worker(), worker()], HEADCOUNT,
  );
  const row = rows[0];
  ok(typeof row.activity_id === 'string' && row.activity_id.length > 0,
    'seed: every seeded row gets an activity_id');
  ok(row.subcontractor_id === 'srv_acme1',
    'seed: the roster id from /daily-headcount is carried onto the row');
  ok(row.company === 'Acme Co' && row.num_workers === '4',
    'seed: company and headcount are carried');
  ok(row.work_description === '',
    'seed: the TRADE IS NOT written into work_description (Finding C)');
}

{
  const rows = M.buildCrewsFromRoster(
    [worker(), worker({ company: 'Volt LLC', trade: 'Electrical' })], HEADCOUNT,
  );
  ok(rows[0].activity_id !== rows[1].activity_id, 'seed: two seeded rows never share an id');
}

{
  const [unrostered] = M.buildCrewsFromRoster(
    [worker({ company: 'Ghost Co', trade: 'Masonry' })], HEADCOUNT,
  );
  ok(unrostered.subcontractor_id === null,
    'seed: a company absent from the roster gets NULL, never a fabricated id');
  ok(typeof unrostered.activity_id === 'string' && unrostered.activity_id.length > 0,
    'seed: ...but it still gets a row identity');
  ok(M.isUnboundCrew(unrostered), 'seed: and is flagged unbound for an admin');
}

{
  const [missingKey] = M.buildCrewsFromRoster(
    [worker()], [{ sub_name: 'Acme Co', trade: 'Carpenter', worker_count_today: 1 }],
  );
  ok(missingKey.subcontractor_id === null,
    'seed: a headcount row with no subcontractor_id yields null, not undefined-as-id');
}

{
  const [unassigned] = M.buildCrewsFromRoster(
    [worker({ company: 'UNASSIGNED', trade: '' })], HEADCOUNT,
  );
  ok(unassigned.company === '',
    'seed: the UNASSIGNED sentinel is blanked, never stamped on the 3301-02');
  ok(unassigned.subcontractor_id === null,
    'seed: a blanked company keeps NO roster id — the two must agree');
}

// ── 3. The roster index ──────────────────────────────────────────────────────
{
  const map = M.rosterIdIndex(HEADCOUNT);
  ok(map.get('acme co|carpenter') === 'srv_acme1' && map.get('volt llc|electrical') === 'srv_v',
    'roster map: normalized (company, trade) resolves to the roster id');

  // STRONGER THAN BEFORE. The old index was keyed on company alone, so a
  // company working two trades had two ids and had to be dropped as ambiguous.
  // Keying on the pair removes the ambiguity instead of surrendering to it.
  const twoTrades = M.rosterIdIndex([
    { sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: 'srv_a' },
    { sub_name: 'Acme Co', trade: 'Drywall', subcontractor_id: 'srv_b' },
  ]);
  ok(twoTrades.get('acme co|carpenter') === 'srv_a'
    && twoTrades.get('acme co|drywall') === 'srv_b',
  'roster map: one company on two trades resolves EXACTLY, not ambiguously');

  const noIds = M.rosterIdIndex([{ sub_name: 'Acme Co', trade: 'Carpenter' }]);
  ok(noIds.size === 0, 'roster map: rows with no roster id contribute nothing');
  ok(M.rosterIdIndex(null).size === 0, 'roster map: a failed headcount read yields an empty map');
}

// ── 4. The one surviving binding path: a hand-added crew ────────────────────
//
// `applyCompanyCorrection` is GONE — assigning a company or trade does not
// belong on the daily log. What still has to resolve is the crew the CP adds
// because the gate missed it, and the rule is unchanged: bind only on an exact
// normalized (company, trade) match, and answer NULL whenever it is not
// certain. A row carrying one sub's id under another's name would share that
// sub's photo bucket and be reported against them.
{
  const ids = M.rosterIdIndex(HEADCOUNT);
  ok(M.resolveRosterId('Volt LLC', 'Electrical', ids) === 'srv_v',
    'add-crew: a company that IS on the roster binds to its own id');
  ok(M.resolveRosterId('Ghost Co', 'Carpenter', ids) === null,
    'add-crew: a company that is NOT on the roster resolves to null');
  ok(M.resolveRosterId('', 'Carpenter', ids) === null,
    'add-crew: no company means no binding');
  ok(M.resolveRosterId('  acme co  ', 'CARPENTER', ids) === 'srv_acme1',
    'add-crew: case and whitespace still resolve to the same sub');
  ok(M.resolveRosterId('Acme Co', 'Electrical', ids) === null,
    'add-crew: right company, WRONG trade is a different roster row — null, not a guess');
  ok(M.resolveRosterId('Acme Co', 'Carpenter', null) === null,
    'add-crew: no roster at all resolves to null and does not throw');
}

// ── 5. Gate provenance survives; the correction trail does not ──────────────
{
  const seeded = M.buildCrewsFromRoster([worker()], HEADCOUNT)[0];
  ok(seeded.company_gate === 'Acme Co',
    'company_gate records what the GATE said, so the two records can be compared');
  ok(!('company_corrected_by' in seeded) && !('company_corrected_at' in seeded),
    'the dead correction-trail keys are gone from the seeded row');
  const hand = M.EMPTY_ACTIVITY();
  ok(hand.company_gate === null,
    'a hand-added row has no gate value and does not invent one');
  ok(!('company_corrected_by' in hand) && !('company_corrected_at' in hand),
    'nor does a blank row carry the dead keys');

  const legacy = { crew_id: 'C1', company: 'Old Co', photos: [] };
  ok(legacy.activity_id === undefined && legacy.subcontractor_id === undefined,
    'legacy: a row stored before these fields existed simply has neither');
}

// ── 6. The source itself ─────────────────────────────────────────────────────
const emptyActivitySrc = (() => {
  const at = modelSrc.indexOf('const EMPTY_ACTIVITY = () => ({');
  return modelSrc.slice(at, modelSrc.indexOf('});', at));
})();
const seedSrc = (() => {
  const at = modelSrc.indexOf('function buildCrewsFromRoster');
  return modelSrc.slice(at, modelSrc.indexOf('\nexport function rosterIdIndex', at));
})();

ok(/activity_id: newActivityId\(\)/.test(emptyActivitySrc),
  'source: EMPTY_ACTIVITY mints its activity_id inline');
ok(/\.\.\.EMPTY_ACTIVITY\(\)/.test(seedSrc),
  'source: the seed path builds every row through EMPTY_ACTIVITY, so each is minted an id');
ok(/subcontractor_id: rosterIds\.get\(key\) \|\| null/.test(seedSrc),
  'source: the seed path resolves the roster id or falls to null — no third option');

// The client must never mint anything that could be mistaken for a
// server-minted roster id.
ok(!/srv_/.test(noComments(seedSrc)) && !/srv_/.test(noComments(emptyActivitySrc)),
  'source: the client never mints anything that looks like a server roster id');
ok(/const newActivityId = \(\) => `act_/.test(modelSrc),
  'source: client-minted ids carry their own `act_` prefix');

// Both fields have to actually REACH the server and the offline draft. Each is
// carried by a spread of the whole row, so a new field cannot be forgotten.
ok(/\.\.\.act,\s*[\r\n]\s*photos: \(act\.photos \|\| \[\]\)\.map\(photoForPayload\)/.test(src),
  'source: the payload spreads the whole activity, so both new fields reach the server');
const draftsSrc = fs.readFileSync(path.join(__dirname, 'logbookDrafts.js'), 'utf8');
ok(/\.\.\.a,\s*[\r\n]\s*photos: await Promise\.all/.test(draftsSrc),
  'source: persistActivityPhotos spreads the activity too, so the offline draft keeps both fields');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
