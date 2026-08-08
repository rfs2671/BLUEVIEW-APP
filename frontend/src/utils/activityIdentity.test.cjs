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
 * No test runner in this repo (see RiskScoreCircle.bandFor.test.cjs): the real
 * blocks are extracted from the .jsx by brace matching and evaluated against
 * stubs, the technique src/utils/checkinCardGate.test.cjs uses. Nothing below is
 * a hand-copy of the logic under test.
 *
 * Run:  node src/utils/activityIdentity.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const src = fs.readFileSync(SCREEN, 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── extraction ───────────────────────────────────────────────────────────────
function matchBalanced(text, openIdx, open, close) {
  let depth = 0;
  for (let i = openIdx; i < text.length; i += 1) {
    if (text[i] === open) depth += 1;
    else if (text[i] === close) {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new Error('unbalanced region');
}
/** Slice from `anchor` (which must END with `open`) to its matching `close`. */
function region(anchor, open, close) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`anchor not found in daily_jobsite.jsx: ${anchor}`);
  const openIdx = at + anchor.length - 1;
  if (src[openIdx] !== open) throw new Error(`anchor must end with ${open}: ${anchor}`);
  return src.slice(at, matchBalanced(src, openIdx, open, close) + 1);
}
/** Just the delimited region that `anchor` opens, without the anchor itself. */
function body(anchor, open, close) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`anchor not found in daily_jobsite.jsx: ${anchor}`);
  const openIdx = at + anchor.length - 1;
  return src.slice(openIdx, matchBalanced(src, openIdx, open, close) + 1);
}
/** The single line beginning at `anchor`. */
function line(anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`anchor not found in daily_jobsite.jsx: ${anchor}`);
  const end = src.indexOf('\n', at);
  return src.slice(at, end < 0 ? src.length : end);
}

const activitySeqSrc = line('let activitySeq = ');
const newActivityIdSrc = line('const newActivityId = ');
const rosterKeySrc = line('const rosterKey = ');
const emptyActivitySrc = region('const EMPTY_ACTIVITY = () => (', '(', ')');
const seedBodySrc = body('const autoActivities = rows.map((r, i) => {', '{', '}');

// The roster-map build is a plain block, not a delimited expression: take it
// from its first statement through the assignment that publishes it.
const rosterMapStart = src.indexOf('const idsByName = new Map();');
const rosterMapEnd = src.indexOf('rosterIdByCompanyRef.current = unique;');
if (rosterMapStart < 0 || rosterMapEnd < 0) throw new Error('roster-map block not found');
const rosterMapBlock = src.slice(
  rosterMapStart, rosterMapEnd + 'rosterIdByCompanyRef.current = unique;'.length,
);

const updateActivitySrc = (() => {
  const anchor = 'const updateActivity = (index, field, value) => {';
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error('updateActivity not found');
  const open = at + anchor.length - 1;
  return src.slice(at, matchBalanced(src, open, '{', '}') + 1);
})();

// ── evaluate the extracted blocks ────────────────────────────────────────────
// eslint-disable-next-line no-new-func
const ids = new Function(
  `${activitySeqSrc}\n${newActivityIdSrc}\n${rosterKeySrc}\nreturn { newActivityId, rosterKey };`)();
const { newActivityId, rosterKey } = ids;

// eslint-disable-next-line no-new-func
const EMPTY_ACTIVITY = new Function('newActivityId',
  `${emptyActivitySrc}\nreturn EMPTY_ACTIVITY;`)(newActivityId);

// eslint-disable-next-line no-new-func
const seedRow = new Function('newActivityId',
  `return (r, i) => ${seedBodySrc};`)(newActivityId);

/** Run the shipped roster-map build over a headcount response. */
// eslint-disable-next-line no-new-func
const buildRosterMap = new Function('headcount', 'rosterKey', `
  const rosterIdByCompanyRef = { current: null };
  ${rosterMapBlock}
  return rosterIdByCompanyRef.current;
`);

/** Run the shipped updateActivity over a rows array. */
function runUpdate(rows, index, field, value, rosterMap) {
  let state = rows;
  const env = {
    lastEditedRef: { current: null },
    rosterIdByCompanyRef: { current: rosterMap || new Map() },
    setActivities: (fn) => { state = fn(state); },
    rosterKey,
  };
  // eslint-disable-next-line no-new-func
  new Function('lastEditedRef', 'rosterIdByCompanyRef', 'setActivities', 'rosterKey',
    `${updateActivitySrc}\nreturn updateActivity;`)(
    env.lastEditedRef, env.rosterIdByCompanyRef, env.setActivities, env.rosterKey,
  )(index, field, value);
  return state;
}

// ── 1. EMPTY_ACTIVITY declares both fields ───────────────────────────────────
{
  const a = EMPTY_ACTIVITY();
  ok(typeof a.activity_id === 'string' && a.activity_id.length > 0,
    'EMPTY_ACTIVITY: a manually added row is minted an activity_id');
  ok(Object.prototype.hasOwnProperty.call(a, 'subcontractor_id'),
    'EMPTY_ACTIVITY: subcontractor_id is declared on the row');
  ok(a.subcontractor_id === null,
    'EMPTY_ACTIVITY: an "Other"/unbound row carries NO roster id — null, not a placeholder');

  const b = EMPTY_ACTIVITY();
  ok(a.activity_id !== b.activity_id,
    'EMPTY_ACTIVITY: two hand-added rows get DIFFERENT ids');

  const many = new Set(Array.from({ length: 500 }, () => EMPTY_ACTIVITY().activity_id));
  ok(many.size === 500,
    'activity_id: 500 rows minted back-to-back are all distinct (the id is not just a timestamp)');

  // The old shape must survive untouched — the 3301-02 renderers read these.
  for (const f of ['crew_id', 'company', 'num_workers', 'work_description', 'work_locations', 'photos']) {
    ok(Object.prototype.hasOwnProperty.call(a, f), `EMPTY_ACTIVITY: still carries ${f}`);
  }
}

// ── 2. The auto-seed path sets both, from the headcount row ──────────────────
{
  const row = seedRow(
    { sub_name: 'Acme Co', trade: 'Carpenter', worker_count_today: 4, subcontractor_id: 'srv_acme1' }, 0,
  );
  ok(typeof row.activity_id === 'string' && row.activity_id.length > 0,
    'seed: an auto-populated row is minted an activity_id too');
  ok(row.subcontractor_id === 'srv_acme1',
    'seed: the roster id from /daily-headcount reaches the row');
  ok(row.company === 'Acme Co' && row.num_workers === '4' && row.work_description === 'Carpenter',
    'seed: the existing fields are unchanged');

  const rows = [
    seedRow({ sub_name: 'Acme Co', trade: 'Carpenter', worker_count_today: 1, subcontractor_id: 'srv_a' }, 0),
    seedRow({ sub_name: 'Volt LLC', trade: 'Electrician', worker_count_today: 2, subcontractor_id: 'srv_v' }, 1),
  ];
  ok(rows[0].activity_id !== rows[1].activity_id,
    'seed: two seeded rows get different activity_ids');
}

// ── 3. Absence is honest, never fabricated ───────────────────────────────────
{
  const unrostered = seedRow(
    { sub_name: 'Ghost Crew', trade: 'Demolition', worker_count_today: 3, subcontractor_id: null }, 0,
  );
  ok(unrostered.subcontractor_id === null,
    'seed: a sub the admin has not entered yet carries NO roster id');
  ok(typeof unrostered.activity_id === 'string' && unrostered.activity_id.length > 0,
    'seed: ...but it still gets an activity_id, so it is still addressable');

  const missingKey = seedRow({ sub_name: 'Ghost Crew', trade: 'Demolition', worker_count_today: 3 }, 0);
  ok(missingKey.subcontractor_id === null,
    'seed: an older server response with no subcontractor_id key yields null, not undefined-as-an-id');

  // 'UNASSIGNED' is a sentinel, not a company: the company is blanked, so the
  // roster id must go with it or the two would disagree.
  const unassigned = seedRow(
    { sub_name: 'UNASSIGNED', trade: '', worker_count_today: 2, subcontractor_id: 'srv_leaked' }, 0,
  );
  ok(unassigned.company === '',
    'seed: UNASSIGNED is still blanked to "pending assignment", not stamped on the form');
  ok(unassigned.subcontractor_id === null,
    'seed: a blanked company drops the roster id — a row cannot be bound to a sub it does not name');
}

// ── 4. The company -> roster id map only keeps UNAMBIGUOUS names ─────────────
{
  const map = buildRosterMap([
    { sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: 'srv_a' },
    { sub_name: 'Volt LLC', trade: 'Electrician', subcontractor_id: 'srv_v' },
  ], rosterKey);
  ok(map.get('acme co') === 'srv_a' && map.get('volt llc') === 'srv_v',
    'roster map: an unambiguous company name resolves to its roster id');

  const ambiguous = buildRosterMap([
    { sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: 'srv_a_carp' },
    { sub_name: 'Acme Co', trade: 'Laborer', subcontractor_id: 'srv_a_lab' },
  ], rosterKey);
  ok(!ambiguous.has('acme co'),
    'roster map: a company working TWO trades is two roster rows — the name is ambiguous and is NOT guessed at');

  const noIds = buildRosterMap([
    { sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: null },
    { sub_name: 'UNASSIGNED', trade: '', subcontractor_id: null },
  ], rosterKey);
  ok(noIds.size === 0, 'roster map: rows with no roster id contribute nothing');
}

// ── 5. Retyping the company RE-RESOLVES the binding ──────────────────────────
{
  const map = buildRosterMap([
    { sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: 'srv_a' },
    { sub_name: 'Volt LLC', trade: 'Electrician', subcontractor_id: 'srv_v' },
  ], rosterKey);
  const seeded = seedRow(
    { sub_name: 'Acme Co', trade: 'Carpenter', worker_count_today: 1, subcontractor_id: 'srv_a' }, 0,
  );

  const renamed = runUpdate([seeded], 0, 'company', 'Volt LLC', map);
  ok(renamed[0].subcontractor_id === 'srv_v',
    'company edit: renaming the row to another roster sub rebinds it to THAT sub');

  const offRoster = runUpdate([seeded], 0, 'company', 'Some Other Outfit', map);
  ok(offRoster[0].subcontractor_id === null,
    'company edit: renaming to a company that is NOT on the roster drops the id — no fabricated binding');

  const cleared = runUpdate([seeded], 0, 'company', '', map);
  ok(cleared[0].subcontractor_id === null,
    'company edit: clearing the company drops the id too');

  const caseOnly = runUpdate([seeded], 0, 'company', '  ACME CO ', map);
  ok(caseOnly[0].subcontractor_id === 'srv_a',
    'company edit: case-only / whitespace edits still resolve (rosterKey mirrors the backend _roster_key)');

  const other = runUpdate([seeded], 0, 'work_description', 'shoring', map);
  ok(other[0].subcontractor_id === 'srv_a' && other[0].work_description === 'shoring',
    'company edit: editing a DIFFERENT field leaves the binding alone');

  ok(renamed[0].activity_id === seeded.activity_id,
    'company edit: the activity_id is stable across edits — that is the point of it');
}

// ── 6. A stored row predating both fields still works ────────────────────────
{
  const legacy = {
    crew_id: 'C1', company: 'Acme Co', num_workers: '3',
    work_description: 'shoring', work_locations: 'cellar', photos: [],
  };
  ok(legacy.activity_id === undefined && legacy.subcontractor_id === undefined,
    'legacy row: genuinely has neither field');

  const map = buildRosterMap(
    [{ sub_name: 'Acme Co', trade: 'Carpenter', subcontractor_id: 'srv_a' }], rosterKey,
  );
  const edited = runUpdate([legacy], 0, 'work_locations', 'roof', map);
  ok(edited[0].work_locations === 'roof' && edited[0].company === 'Acme Co',
    'legacy row: still editable — the update path does not require either field');
  ok(edited[0].activity_id === undefined,
    'legacy row: nothing is silently back-filled onto a stored compliance record');
}

// ── 7. The wiring in the screen source ───────────────────────────────────────
ok(/activity_id:\s*newActivityId\(\)/.test(emptyActivitySrc),
  'source: EMPTY_ACTIVITY mints its activity_id inline');
ok(/activity_id:\s*newActivityId\(\)/.test(seedBodySrc),
  'source: the seed path mints an activity_id per row');
ok(/subcontractor_id:\s*company\s*\?\s*\(r\.subcontractor_id\s*\|\|\s*null\)\s*:\s*null/.test(seedBodySrc),
  'source: the seed path ties the roster id to a non-empty company');
// Comments are stripped: both blocks DOCUMENT the server's `srv_` prefix, and a
// prose mention is not a mint.
const noComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
ok(!/srv_/.test(noComments(seedBodySrc)) && !/srv_/.test(noComments(emptyActivitySrc)),
  'source: the client never mints anything that looks like a server roster id');

// The save path must not drop either field on the way to the server.
// The base64 re-encode loop is gone - photos go to R2 as they are TAKEN and the
// document carries only the key - but the rule is the same one: the payload is
// built by spreading the WHOLE activity and replacing only `photos`, so a field
// added to a row (activity_id, subcontractor_id) reaches the server without
// anyone having to remember to list it.
const saveSpread = /_uploaded\.activities\.map\(\(act\) => \(\{\s*\.\.\.act,\s*photos:/.test(src);
ok(saveSpread,
  'source: handleSave spreads the whole activity, so both new fields reach the server');

const draftsSrc = fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'logbookDrafts.js'), 'utf8');
ok(/\.\.\.a,\s*[\r\n]\s*photos: await Promise\.all/.test(draftsSrc),
  'source: persistActivityPhotos spreads the activity too, so the offline draft keeps both fields');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
