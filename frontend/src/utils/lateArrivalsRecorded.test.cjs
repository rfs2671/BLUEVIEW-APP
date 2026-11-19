// Run: node src/utils/lateArrivalsRecorded.test.cjs
//
// A WORKER WHOSE CREW IS ALREADY ON THE SIGNED LOG IS RECORDED ON IT, NOT
// CORRECTED (backend/lib/late_arrivals.py, ruling 2026-11-18). The screens have
// two jobs here, and both are read from source:
//
//   1. Log Books tells the CP which of the two happened. A crew with no card
//      opens a correction and the card is a tap target; a man who was only
//      RECORDED gets a card with nothing to tap, because nothing needs signing.
//   2. The filed log lists who arrived after signing, apart from what was
//      attested, from the stored `late_arrivals` field.
//
// And every word of it exists in English and Spanish: the people reading it are
// on site, and the old card was English-only.
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');
let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

const en = loadEsm('src/i18n/en.js').default;
const es = loadEsm('src/i18n/es.js').default;

// ── the strings, in both languages ──
const KEYS = ['recordedTitle', 'recordedTitleOne', 'recordedBody', 'correctionTitle',
  'correctionTitleOne', 'correctionBody', 'newCrews', 'sectionTitle', 'sectionNote', 'checkedIn'];
ok(!!en.lateArrivals && !!es.lateArrivals, 'both catalogues carry a lateArrivals namespace');
for (const k of KEYS) {
  ok(typeof en.lateArrivals[k] === 'string' && en.lateArrivals[k].length > 0, `en.${k} exists`);
  ok(typeof es.lateArrivals[k] === 'string' && es.lateArrivals[k].length > 0, `es.${k} exists`);
  ok(en.lateArrivals[k] !== es.lateArrivals[k], `es.${k} is not the English copied across`);
}
ok(Object.keys(en.lateArrivals).sort().join() === Object.keys(es.lateArrivals).sort().join(),
  'the two namespaces have exactly the same keys');
for (const k of ['recordedTitle', 'correctionTitle']) {
  ok(en.lateArrivals[k].includes('{n}') && es.lateArrivals[k].includes('{n}'), `${k} keeps its {n} in both`);
}
ok(en.lateArrivals.correctionBody.includes('{crews}') && es.lateArrivals.correctionBody.includes('{crews}'),
  'correctionBody keeps its {crews} in both');
ok(/sign/i.test(en.lateArrivals.recordedBody) && /firmar/i.test(es.lateArrivals.recordedBody),
  'the recorded card says in both languages that nothing needs signing');

// ── Log Books: two cards, one tappable ──
const idx = read('app/logbooks/index.jsx');
ok(idx.includes("useT('lateArrivals')"), 'Log Books reads the lateArrivals namespace');
ok(!/arrived after the Daily Jobsite Log was signed/.test(idx),
  'the old hard-coded English card text is gone');
ok(idx.includes('recorded_workers'), 'Log Books reads recorded_workers from the answer');
const correction = idx.slice(idx.indexOf("(lateArrivals.late_workers || []).length > 0 && ("));
ok(/<GlassCard onPress=\{\(\) => handleOpenLog\('daily_jobsite'\)\}/.test(correction.slice(0, 200)),
  'the correction card still opens the daily log to sign it');
const recordedAt = idx.indexOf("(lateArrivals.recorded_workers || []).length > 0 && (");
ok(recordedAt > 0, 'a card exists for men who were only recorded');
const recordedCard = idx.slice(recordedAt, recordedAt + 220);
ok(/<GlassCard style=\{styles\.notifCard\}>/.test(recordedCard) && !/onPress/.test(recordedCard),
  'the recorded card has nothing to tap: there is nothing to sign');
ok(/late_workers \|\| \[\]\)\.length === 0/.test(idx),
  'the recorded card shows only when no correction is waiting (the correction takes everyone in)');

// ── the filed log lists them, apart from what was attested ──
const filed = read('src/components/logbookStepper/FiledLogView.jsx');
ok(filed.includes('doc.late_arrivals'), 'the filed view reads the stored late_arrivals');
ok(filed.includes("tLate('sectionTitle')") && filed.includes("tLate('sectionNote')"),
  'it titles the section and says it is not part of what was attested');
ok(filed.indexOf('lateRows.length > 0') < filed.indexOf('{!!photos && ('),
  'it sits above the photographs and below what was filed');
ok(!/late_arrivals/.test(filed.slice(0, filed.indexOf('export default function FiledLogView'))),
  'the field is not folded into the filed `data` summary');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
