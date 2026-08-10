/**
 * THE ACTIVITY PHOTO CAP — 10 PER SUBCONTRACTOR, AGGREGATED.
 *
 * It used to be 5 PER ROW while the message on screen said "per subcontractor",
 * so a sub with three activity rows could attach 15 photos and be told the limit
 * was 5. Both halves were wrong. The cap is now what the message always claimed.
 *
 * The rulings this file pins, and why each matters:
 *
 *   • one bucket of 10 per distinct subcontractor_id, shared across every row
 *     that names it — the aggregation that did not exist before
 *   • each row with NO roster id gets its OWN 10, never shared with another
 *     unbound row
 *   • each blank-company row gets its OWN 10, never merged with another blank
 *
 * The last two are not a loophole. A CP with three crews the admin has not put
 * on the roster yet is facing an admin failure; a shared bucket would confiscate
 * the evidence he is able to collect as a penalty for someone else's unfinished
 * data entry. When the roster catches up the rows collapse into the real
 * subcontractor bucket on their own.
 *
 * Everything runs the REAL shipped source: the constant, the three bucket
 * helpers and the capture updater are extracted from daily_jobsite.jsx by brace
 * matching and evaluated (the technique src/utils/checkinCardGate.test.cjs
 * uses). Nothing here is a hand-copy of the logic under test.
 *
 * Run:  node src/utils/activityPhotoCap.test.cjs
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
function declAt(text, anchor, open, close) {
  const at = text.indexOf(anchor);
  if (at < 0) throw new Error(`anchor not found: ${anchor}`);
  const openIdx = at + anchor.length - 1;
  if (text[openIdx] !== open) throw new Error(`anchor must end with ${open}: ${anchor}`);
  return {
    decl: text.slice(at, matchBalanced(text, openIdx, open, close) + 1),
    block: text.slice(openIdx, matchBalanced(text, openIdx, open, close) + 1),
  };
}

const capLine = (() => {
  const m = src.match(/^const MAX_PHOTOS_PER_SUBCONTRACTOR = \d+;$/m);
  if (!m) throw new Error('MAX_PHOTOS_PER_SUBCONTRACTOR not found');
  return m[0];
})();
const bucketKeySrc = declAt(src, 'const photoBucketKey = (activity, index) => {', '{', '}').decl;
const inBucketSrc = declAt(src, 'const photosInBucket = (rows, index) => {', '{', '}').decl;
const remainingSrc = declAt(src, 'const bucketRemaining = (rows, index) => Math.max(', '(', ')').decl;

// eslint-disable-next-line no-new-func
const C = new Function(`
  ${capLine}
  ${bucketKeySrc}
  ${inBucketSrc}
  ${remainingSrc};
  return { MAX_PHOTOS_PER_SUBCONTRACTOR, photoBucketKey, photosInBucket, bucketRemaining };
`)();
const { MAX_PHOTOS_PER_SUBCONTRACTOR: MAX, photoBucketKey, photosInBucket, bucketRemaining } = C;

// The capture updater out of handleCameraCapture — the path that actually
// appends a photo when the CP fires the shutter.
const captureSrc = declAt(src, 'const handleCameraCapture = (uri, report) => {', '{', '}').decl;
const updaterBody = declAt(captureSrc, 'setActivities(prev => {', '{', '}').block;
// eslint-disable-next-line no-new-func
const applyShot = new Function('bucketRemaining', 'target', 'shot', 'prev',
  `return ((prev) => ${updaterBody})(prev);`);

let shotSeq = 0;
/** Fire the shutter once at `index`; returns the rows the screen would hold. */
const shoot = (rows, index) => applyShot(
  bucketRemaining, index, { id: `cap_${(shotSeq += 1)}`, uri: 'file:///x.jpg', pending: true }, rows,
);
/** Fire it `n` times, returning the final rows. */
const shootN = (rows, index, n) => {
  let cur = rows;
  for (let k = 0; k < n; k += 1) cur = shoot(cur, index);
  return cur;
};
const total = (rows) => rows.reduce((a, r) => a + (r.photos || []).length, 0);

const row = (over = {}) => ({
  activity_id: over.activity_id !== undefined ? over.activity_id : `act_${Math.random()}`,
  subcontractor_id: over.subcontractor_id !== undefined ? over.subcontractor_id : null,
  company: over.company !== undefined ? over.company : '',
  photos: over.photos || [],
});

// ── 0. The number itself ─────────────────────────────────────────────────────
ok(MAX === 10, `the cap is 10 per subcontractor (got ${MAX})`);

// ── 1. ONE subcontractor, THREE rows: 10 TOTAL, not 10 each ──────────────────
{
  const rows = [
    row({ subcontractor_id: 'srv_a', company: 'Acme Co' }),
    row({ subcontractor_id: 'srv_a', company: 'Acme Co' }),
    row({ subcontractor_id: 'srv_a', company: 'Acme Co' }),
  ];
  ok(bucketRemaining(rows, 0) === 10, 'three rows for one sub start with 10 between them');

  let cur = shootN(rows, 0, 4);
  ok(total(cur) === 4 && bucketRemaining(cur, 1) === 6,
    'photos taken on row 1 reduce the room on row 2 — the buckets are SHARED');

  cur = shootN(cur, 1, 4);
  cur = shootN(cur, 2, 2);
  ok(total(cur) === 10, 'the sub reaches exactly 10 across its three rows');
  ok(bucketRemaining(cur, 0) === 0 && bucketRemaining(cur, 1) === 0 && bucketRemaining(cur, 2) === 0,
    'and every one of its rows is now out of room');

  const eleventh = shoot(cur, 2);
  ok(total(eleventh) === 10, 'the 11th photo for that subcontractor is REFUSED');
  const eleventhElsewhere = shoot(cur, 0);
  ok(total(eleventhElsewhere) === 10,
    'and it cannot be smuggled in through a different row of the same sub');

  // The old bug, stated as a test: 3 rows x 5 was 15 while claiming 5.
  ok(total(cur) === 10 && total(cur) < 15,
    'the pre-fix behaviour (5 per row = 15 for three rows) is gone');
}

// ── 2. A DIFFERENT subcontractor is unaffected ───────────────────────────────
{
  const rows = [
    row({ subcontractor_id: 'srv_a', company: 'Acme Co' }),
    row({ subcontractor_id: 'srv_v', company: 'Volt LLC' }),
  ];
  const full = shootN(rows, 0, 10);
  ok((full[0].photos || []).length === 10 && bucketRemaining(full, 0) === 0,
    'Acme fills its 10');
  ok(bucketRemaining(full, 1) === 10,
    'Volt still has its full 10 — there is NO project-wide cap');

  const after = shoot(full, 1);
  ok((after[1].photos || []).length === 1,
    'a photo for a DIFFERENT sub is still allowed once the first sub is full');
}

// ── 3. TWO UNBOUND ("Other") ROWS DO NOT SHARE A BUCKET ──────────────────────
{
  const rows = [
    row({ activity_id: 'act_1', subcontractor_id: null, company: 'Other' }),
    row({ activity_id: 'act_2', subcontractor_id: null, company: 'Other' }),
  ];
  ok(photoBucketKey(rows[0], 0) !== photoBucketKey(rows[1], 1),
    'two unbound rows resolve to DIFFERENT buckets');

  const first = shootN(rows, 0, 10);
  ok((first[0].photos || []).length === 10, 'the first unbound row fills its own 10');
  ok(bucketRemaining(first, 1) === 10,
    'the second unbound row still has ALL 10 — no roster id is not "the same as no roster id"');

  const both = shootN(first, 1, 10);
  ok(total(both) === 20, 'two unbound rows hold 20 photos between them');
  ok(total(shoot(both, 0)) === 20 && total(shoot(both, 1)) === 20,
    'each is capped at its own 10 all the same');
}

// ── 4. TWO BLANK-COMPANY ROWS DO NOT SHARE A BUCKET ──────────────────────────
{
  const rows = [
    row({ activity_id: 'act_1', subcontractor_id: null, company: '' }),
    row({ activity_id: 'act_2', subcontractor_id: null, company: '' }),
    row({ activity_id: 'act_3', subcontractor_id: null, company: '' }),
  ];
  ok(new Set(rows.map((r, i) => photoBucketKey(r, i))).size === 3,
    'three blank-company rows are three distinct buckets');
  const filled = shootN(shootN(shootN(rows, 0, 10), 1, 10), 2, 10);
  ok(total(filled) === 30,
    'THE CP WITH THREE CREWS THE ADMIN HAS NOT ENTERED: all three keep their evidence');
  ok(filled.every((r) => (r.photos || []).length === 10),
    'each blank row is still individually capped at 10');
}

// ── 5. Binding a row later collapses it into the real bucket ─────────────────
{
  const unbound = [
    row({ activity_id: 'act_1', subcontractor_id: null, company: '' }),
    row({ activity_id: 'act_2', subcontractor_id: null, company: '' }),
  ];
  const withPhotos = shootN(shootN(unbound, 0, 6), 1, 6);
  ok(total(withPhotos) === 12, 'twelve photos across two unbound rows');

  // The admin adds the sub; both rows now name it.
  const bound = withPhotos.map((r) => ({ ...r, subcontractor_id: 'srv_a', company: 'Acme Co' }));
  ok(photoBucketKey(bound[0], 0) === photoBucketKey(bound[1], 1),
    'once bound, the two rows share one bucket');
  ok(bucketRemaining(bound, 0) === 0,
    'the shared bucket is over its 10, so no MORE photos are accepted');
  ok(total(shoot(bound, 0)) === 12,
    'and nothing already captured is deleted — the cap refuses new photos, it never destroys evidence');
}

// ── 6. A stored row predating activity_id still works ────────────────────────
{
  const legacy = [
    { company: 'Acme Co', crew_id: 'C1', photos: [] },
    { company: 'Volt LLC', crew_id: 'C2', photos: [] },
  ];
  ok(photoBucketKey(legacy[0], 0) !== photoBucketKey(legacy[1], 1),
    'legacy rows with neither field fall back to their index — one bucket each, never merged');
  ok(bucketRemaining(legacy, 0) === 10 && bucketRemaining(legacy, 1) === 10,
    'a legacy row is not penalised: it gets a full bucket');
  const shot = shootN(legacy, 0, 12);
  ok((shot[0].photos || []).length === 10,
    'and it is capped at 10 like everything else');

  // Tolerating absence, all the way down.
  ok(photoBucketKey(undefined, 3) === 'row-index:3', 'a missing row does not throw');
  ok(photosInBucket(undefined, 0) === 0 && bucketRemaining(undefined, 0) === 10,
    'a missing rows array does not throw');
  ok(photosInBucket([{ subcontractor_id: 'srv_a' }], 0) === 0,
    'a row with no photos array counts as zero, not NaN');
  ok(bucketRemaining([{ subcontractor_id: 'srv_a', photos: new Array(25).fill({}) }], 0) === 0,
    'an over-full bucket reports 0 remaining, never a negative allowance');
}

// ── 7. TEN SUBCONTRACTORS AT TEN PHOTOS EACH = 100, ALL ALLOWED ──────────────
{
  let rows = Array.from({ length: 10 }, (_, i) => row({
    activity_id: `act_${i}`, subcontractor_id: `srv_${i}`, company: `Sub ${i}`,
  }));
  for (let i = 0; i < 10; i += 1) rows = shootN(rows, i, 10);
  ok(total(rows) === 100,
    'ten subcontractors at ten photos each: all 100 are accepted by the UI');
  ok(rows.every((r) => (r.photos || []).length === 10),
    '...ten on each, none over');
  for (let i = 0; i < 10; i += 1) rows = shoot(rows, i);
  ok(total(rows) === 100, 'an 11th for any of the ten is refused');
}

// ── 8. Whitespace / falsy ids are not treated as identity ────────────────────
{
  const blanks = [
    row({ activity_id: 'act_1', subcontractor_id: '   ' }),
    row({ activity_id: 'act_2', subcontractor_id: '' }),
    row({ activity_id: 'act_3', subcontractor_id: null }),
    row({ activity_id: 'act_4', subcontractor_id: undefined }),
  ];
  ok(new Set(blanks.map((r, i) => photoBucketKey(r, i))).size === 4,
    'a whitespace / empty / null / undefined roster id is NOT an identity — four rows, four buckets');
  ok(photoBucketKey(row({ activity_id: 'a1', subcontractor_id: ' srv_a ' }), 0)
    === photoBucketKey(row({ activity_id: 'a2', subcontractor_id: 'srv_a' }), 1),
    'a padded roster id still resolves to the same bucket');
}

// ── 9. The wiring in the screen source ───────────────────────────────────────
ok(!/MAX_PHOTOS_PER_ACTIVITY/.test(src),
  'source: the old per-row constant is gone entirely');
const CAP_SITES = [
  ['pickActivityPhoto', 'const pickActivityPhoto = async (activityIndex) => {'],
  ['takeActivityPhoto', 'const takeActivityPhoto = async (activityIndex) => {'],
  ['handleCameraCapture', 'const handleCameraCapture = (uri, report) => {'],
];
for (const [name, anchor] of CAP_SITES) {
  const fnSrc = declAt(src, anchor, '{', '}').decl;
  ok((fnSrc.match(/bucketRemaining\(/g) || []).length >= 1,
    `source: ${name} enforces the cap through bucketRemaining`);
  ok(!/\.length >= MAX/.test(fnSrc) && !/photos \|\| \[\]\)\.length >= /.test(fnSrc),
    `source: ${name} no longer measures a single row's array`);
}
ok(/selectionLimit: remaining,/.test(src),
  'source: the gallery picker is limited to what the BUCKET has left, not the row');
ok(/photosInBucket\(activities, i\)\}\/\$\{MAX_PHOTOS_PER_SUBCONTRACTOR\}/.test(src),
  'source: the on-screen counter shows the bucket total over the real cap');
ok(/photoCapRowHint/.test(src),
  'source: a row whose bucket is full says so instead of silently losing its buttons');

// The message keeps its framing and finally tells the truth.
const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
const es = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'es.js'), 'utf8');
ok(/photoCapBody: 'Maximum \{n\} photos per subcontractor'/.test(en),
  'copy: the EN message keeps the "per subcontractor" framing it always had');
// A logbook is a legal record filed with the DOB, so it is written in English.
// Spanish belongs where a WORKER must understand what he is signing — the gate,
// and any worker signature line inside a logbook. This message is CP-facing, so
// it is EN-only BY RULING. Asserted as an absence, not skipped, so a well-meant
// translation cannot quietly reappear. (translate() falls back to English, so a
// Spanish-locale CP still reads it — see src/i18n/i18n.test.cjs.)
ok(!/photoCapBody:/.test(es),
  'copy: the ES catalogue does NOT carry this CP-facing message');
ok(!/dailyJobsite:\s*\{/.test(es),
  'copy: the whole dailyJobsite namespace is absent from the ES catalogue');
ok(/\{n\}/.test(en) && !/Maximum 10 photos/.test(en),
  'copy: the number is substituted from the constant, never hardcoded in the sentence');
ok(/capMessage = \(\) => t\('photoCapBody'\)\.replace\('\{n\}', String\(MAX_PHOTOS_PER_SUBCONTRACTOR\)\)/.test(src),
  'source: the substitution reads the enforced constant, so copy and cap cannot drift');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
