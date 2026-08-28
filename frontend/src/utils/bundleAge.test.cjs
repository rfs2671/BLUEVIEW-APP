/**
 * "built 34 days ago" — the line that would have ended a day of investigation.
 *
 * A filed log rendered as a blank editable form on one phone and correctly on
 * another. Six source traces were built, all wrong, because the fault was in
 * code nobody was reading: that device ran a bundle older than the fix.
 * `BuildMarker` was rendering its update id at the bottom of the very screen
 * the operator was standing on, and nobody read it — an id is not a verdict.
 *
 * The behaviour worth protecting is mostly what this REFUSES to say: it never
 * claims "out of date", and it never invents an age for a bundle that shipped
 * inside the binary, because that is the stranded case itself.
 *
 * Run:  node src/utils/bundleAge.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// The module is ESM; strip the exports and evaluate it, the harness this
// suite uses elsewhere (see i18n.test.cjs).
const src = fs.readFileSync(path.join(UTILS, 'bundleAge.js'), 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export /gm, '');
// eslint-disable-next-line no-new-func
const { bundleAgeDays, bundleAgeLabel } = new Function(
  `${src}; return { bundleAgeDays, bundleAgeLabel };`)();

const NOW = new Date('2026-08-28T12:00:00Z');

console.log('\n-- the number --');

ok(bundleAgeDays('2026-08-28T09:00:00Z', NOW) === 0, 'same day is 0');
ok(bundleAgeDays('2026-08-27T09:00:00Z', NOW) === 1, 'yesterday is 1');
ok(bundleAgeDays('2026-07-25T12:00:00Z', NOW) === 34, '34 days is 34');
ok(bundleAgeDays(new Date('2026-07-29T00:00:00Z'), NOW) === 30,
  'a Date object works as well as a string');

console.log('\n-- what it refuses to guess --');

ok(bundleAgeDays(null, NOW) === null,
  'an EMBEDDED bundle has no createdAt and gets no age — that is the stranded '
  + 'case, and "built today" would state the opposite of the truth');
ok(bundleAgeDays(undefined, NOW) === null, 'undefined too');
ok(bundleAgeDays('', NOW) === null, 'empty string too');
ok(bundleAgeDays('not a date', NOW) === null, 'unparseable is unknown, not 0');
ok(bundleAgeLabel(null, NOW) === null, 'the label is absent, not "unknown"');

console.log('\n-- a skewed device clock --');

ok(bundleAgeDays('2026-08-31T12:00:00Z', NOW) === 0,
  'a FUTURE build date clamps to 0 rather than going negative — site phones '
  + 'drift, and "built -3 days ago" sends the reader after the wrong problem');

console.log('\n-- the words --');

ok(bundleAgeLabel('2026-08-28T09:00:00Z', NOW) === 'built today', 'today');
ok(bundleAgeLabel('2026-08-27T09:00:00Z', NOW) === 'built 1 day ago', 'singular day');
ok(bundleAgeLabel('2026-08-26T09:00:00Z', NOW) === 'built 2 days ago', 'plural days');
ok(bundleAgeLabel('2026-07-25T12:00:00Z', NOW) === 'built 34 days ago',
  'the exact line that would have ended the 2026-08-28 investigation');

ok(!/out of date|behind|stale|update/i.test(
  String(bundleAgeLabel('2026-01-01T00:00:00Z', NOW))),
  'it never claims the bundle is BEHIND — age is not staleness, and knowing '
  + 'what is current is a question this cannot answer');

console.log('\n-- both surfaces render it --');

const marker = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'BuildMarker.jsx'), 'utf8');
const settings = fs.readFileSync(
  path.join(FRONTEND, 'app', 'settings.jsx'), 'utf8');

for (const [name, code] of [['BuildMarker', marker], ['settings', settings]]) {
  ok(/bundleAgeLabel/.test(code), `${name} computes the age`);
  ok(/from '.*utils\/bundleAge'/.test(code), `${name} imports it from the one place`);
}
ok(/\{!!age && \(/.test(marker),
  'BuildMarker renders the line only when there IS an age — an embedded bundle '
  + 'shows its existing "embedded" wording and no invented age');
ok(/_jsAge \? ` — \$\{_jsAge\}` : ''/.test(settings),
  'settings appends it to the timestamp rather than replacing it — the exact '
  + 'time still matters when comparing two phones');

ok(!/checkForUpdateAsync|fetchUpdateAsync/.test(marker + settings),
  'NEITHER surface asks Expo whether an update exists. That question is scoped '
  + 'to the runtimeVersion the device is stranded on, so it answers "current" '
  + 'to exactly the phone this feature exists to catch');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
