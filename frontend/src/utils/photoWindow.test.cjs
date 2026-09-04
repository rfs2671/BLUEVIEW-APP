/**
 * THE PHOTO CONTROLS DISAPPEAR WHEN THE DAY ENDS. THEY DO NOT FAIL ON TAP.
 *
 * THE RULING. A photograph may be added to or removed from a log until the end
 * of that log's day; after that the set is closed. END OF DAY is 03:00
 * America/New_York on the day AFTER the log's `date` — the instant the
 * end-of-day sweep already runs, so "the photo set closed" and "the record
 * froze" are one event rather than two boundaries three hours apart.
 *
 * THE SERVER OWNS THE RULE. logbook_photo_window_is_open in backend/server.py
 * evaluates it against the STORED document and answers 409
 * PHOTO_WINDOW_CLOSED. Nothing here is trusted by anything.
 *
 * WHAT THIS FILE IS FOR IS THE OPERATOR'S OTHER REQUIREMENT: controls
 * DISAPPEAR, never fail on tap. A button that throws an error when pressed is
 * worse than a button that is not there. So the device carries a mirror of the
 * boundary, and these assertions are about the mirror being faithful.
 *
 * AND IT HAS TO WORK IN A CELLAR. That is why the boundary is derived from
 * `date` — a 'YYYY-MM-DD' string on every logbook object the client already
 * caches — and from the device's own clock, rather than from a filing instant
 * or a server round-trip. A phone with no signal for two days still answers.
 * There is no `filed_at` on the wire to anchor to anyway.
 *
 *   node frontend/src/utils/photoWindow.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');

// Relative imports are followed and transpiled too: the module under test gets
// its ONE zone conversion from ./dates, and a bare require would hit that
// file's raw `export`. Packages still go to node's own resolution.
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

const {
  isPhotoWindowOpen, photoWindowDay, isOpenForPhotoAppend, isOpenForEditing,
} = loadModule('src/utils/logbookEditable.js');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

const utc = (y, m, d, hh = 0, mm = 0) => new Date(Date.UTC(y, m - 1, d, hh, mm));

// 2026-08-12 is EDT (UTC-4): 03:00 Eastern on the 13th is 07:00 UTC.
const EDT_0259 = utc(2026, 8, 13, 6, 59);
const EDT_0300 = utc(2026, 8, 13, 7, 0);
// 2026-01-15 is EST (UTC-5): 03:00 Eastern on the 16th is 08:00 UTC.
const EST_0259 = utc(2026, 1, 16, 7, 59);
const EST_0300 = utc(2026, 1, 16, 8, 0);

const FILED = (date) => ({ id: 'f', status: 'submitted', is_locked: false, date });

console.log('\n-- the window day is the sweep boundary, not midnight --');
{
  ok(photoWindowDay(EDT_0259) === '2026-08-12',
    'at 02:59 Eastern the previous day is still the open one');
  ok(photoWindowDay(EDT_0300) === '2026-08-13',
    'and it rolls at 03:00 Eastern — the hour the freeze sweep runs');
  ok(photoWindowDay(utc(2026, 8, 13, 4, 30)) === '2026-08-12',
    'MIDNIGHT EASTERN CLOSES NOTHING. This is the whole difference between the '
    + "boundary the system observes and the operator's first instinct");
  ok(photoWindowDay(EST_0259) === '2026-01-15' && photoWindowDay(EST_0300) === '2026-01-16',
    'the same boundary holds in STANDARD time — if the shift were computed '
    + 'from a hardcoded offset instead of the zone, one of these would be wrong');
}

console.log('\n-- open until that boundary, closed after --');
{
  ok(isPhotoWindowOpen(FILED('2026-08-12'), utc(2026, 8, 12, 18)) === true,
    "today's log is open");
  ok(isPhotoWindowOpen(FILED('2026-08-12'), EDT_0259) === true,
    "yesterday's log is still open at 02:59");
  ok(isPhotoWindowOpen(FILED('2026-08-12'), EDT_0300) === false,
    'and closed at 03:00');
  ok(isPhotoWindowOpen(FILED('2026-08-01'), utc(2026, 8, 13, 12)) === false,
    'an older log is closed');

  // The operator's own objection to the midnight rule, answered: filed at
  // 23:00 Eastern on the 12th, which is 03:00 UTC on the 13th.
  const filedAt2300 = utc(2026, 8, 13, 3, 0);
  ok(isPhotoWindowOpen(FILED('2026-08-12'), filedAt2300) === true
    && isPhotoWindowOpen(FILED('2026-08-12'),
      new Date(filedAt2300.getTime() + 3.9 * 3600e3)) === true
    && isPhotoWindowOpen(FILED('2026-08-12'),
      new Date(filedAt2300.getTime() + 4 * 3600e3)) === false,
    'THE 23:00 FILER GETS FOUR HOURS, not the one hour a midnight rule gives him');
}

console.log('\n-- the log filed at 02:00 --');
{
  const at0200 = utc(2026, 8, 13, 6, 0);
  ok(isPhotoWindowOpen(FILED('2026-08-13'), at0200) === true
    && isPhotoWindowOpen(FILED('2026-08-13'), utc(2026, 8, 14, 6, 59)) === true
    && isPhotoWindowOpen(FILED('2026-08-13'), utc(2026, 8, 14, 7, 0)) === false,
    'stamped with TODAY it has about twenty-five hours ahead of it');
  ok(isPhotoWindowOpen(FILED('2026-08-12'), at0200) === true,
    'and the NIGHT-SHIFT WRITE-UP — filed at 02:00 for the shift that ended '
    + 'last night — gets an hour. Under a midnight rule his window would '
    + 'already have been shut at the moment he filed, forever');
  ok(isPhotoWindowOpen(FILED('2026-08-12'), EDT_0300) === false,
    'that hour then ends like every other');
}

console.log('\n-- a clock, not a permission model --');
{
  // No per-photo rule, no added_after_filing predicate, no chain-walk. Status
  // and lock are other guards' business; if any of these diverged the clock
  // would have become a policy.
  const shapes = [
    { status: 'draft', is_locked: false },
    { status: 'submitted', is_locked: false },
    { status: 'submitted', is_locked: true },
    { status: 'withdrawn', is_locked: false },
  ];
  ok(shapes.every((s) => isPhotoWindowOpen({ ...s, date: '2026-08-12' }, EDT_0259) === true),
    'every status and lock combination is OPEN inside the window');
  ok(shapes.every((s) => isPhotoWindowOpen({ ...s, date: '2026-08-12' }, EDT_0300) === false),
    'and every one of them is CLOSED after it');
  ok(isPhotoWindowOpen({
    date: '2026-08-12',
    photos: [{ added_after_filing: true }],
  }, EDT_0300) === false, 'no photo field is consulted — added_after_filing is a '
    + 'RECORD of what the server did, and the ruling forbids it becoming a predicate');
}

console.log('\n-- it fails closed, exactly as the server does --');
{
  for (const bad of [undefined, null, '', 0, []]) {
    ok(isPhotoWindowOpen(bad) === false, `a non-document is closed (${JSON.stringify(bad)})`);
  }
  for (const bad of [undefined, null, '', '   ', 'not-a-date', '08/12/2026', '2026-8-12', 20260812]) {
    ok(isPhotoWindowOpen({ status: 'submitted', date: bad }, utc(2026, 8, 12, 18)) === false,
      `an unusable date is closed (${JSON.stringify(bad)})`);
  }
  ok(isPhotoWindowOpen(FILED('2026-08-12T00:00:00+00:00'), utc(2026, 8, 12, 18)) === true,
    'but a DATETIME in `date` is read rather than refused — a legacy row '
    + "carries one, and failing it closed would refuse today's log");
}

console.log('\n-- the append affordance carries the window --');
{
  ok(isOpenForPhotoAppend(FILED('2026-08-12'), EDT_0259) === true,
    'a filed log inside its window offers photographs — unchanged behaviour');
  ok(isOpenForPhotoAppend(FILED('2026-08-12'), EDT_0300) === false,
    'THE AFFORDANCE VANISHES when the day ends. This is the requirement: the '
    + 'control disappears rather than failing on tap');
  ok(isOpenForPhotoAppend({ id: 'd', status: 'draft', is_locked: false, date: '2026-08-12' },
    EDT_0259) === false,
    'a DRAFT is still refused inside the window — the ordinary camera is the '
    + "way in, and the append route would be overwritten by the editor's next PUT");
  ok(isOpenForEditing(FILED('2026-08-12')) === false,
    'and the editing rule is untouched by any of this');
}

console.log('\n-- the read path is untouched: closing the set is not hiding it --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'app/logbooks/photos.jsx'), 'utf8');
  ok(/isOpenForPhotoAppend\(/.test(src),
    'the photos screen still gates on the shared predicate, so it inherits the '
    + 'window with no date logic of its own');
  ok(!/isPhotoWindowOpen|photoWindowDay|America\/New_York/.test(src),
    'and it does NOT re-derive the boundary — one copy of the rule per side');
}

console.log('\n-- one zone conversion, one shift, shared with the server --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'src/utils/logbookEditable.js'), 'utf8');
  ok(/easternDate/.test(src) && !/America\/New_York/.test(src),
    'easternDate from utils/dates.js is the only zone conversion — an inline '
    + 'Intl call here would be a second copy of the boundary');
  ok(/3\s*\*\s*60\s*\*\s*60\s*\*\s*1000/.test(src),
    'the three-hour shift is the server\'s _PHOTO_WINDOW_GRACE_HOURS, and '
    + 'test_photo_window_rule.py asserts this same number from the other side');
}

console.log('\n-- the entry row disappears too, so the screen is never reached --');
{
  const src = fs.readFileSync(path.join(FRONTEND, 'app/logbooks/index.jsx'), 'utf8');
  ok(/isPhotoWindowOpen\(/.test(src),
    'filedPhotoTarget asks the window, so the Photographs row vanishes — the '
    + 'case being caught is the APP LEFT RUNNING OVERNIGHT, where todayLogs '
    + "still holds yesterday's fetch after 03:00");
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
