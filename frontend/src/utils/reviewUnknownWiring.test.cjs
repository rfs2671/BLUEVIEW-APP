/**
 * PR B — unknown-SST is wired to a render path, and the dead TRANSLATIONS key
 * that nothing could ever produce is removed. No dead strings.
 *
 * Static guard over the real sources:
 *   src/i18n/{en,es}.js — reason_EXTRACTION_INCOMPLETE removed (backend never
 *                 emits it); unknownSst + the reason_* keys are DEFINED, in
 *                 both locales.
 *   review.jsx  — those keys are CONSUMED (t('unknownSst'),
 *                 t(`reason_${...}`)); the unknown flag + Admit path exist.
 *   checkins.jsx — the site view reads sst_status === 'unknown' and its frozen
 *                 sst_unknown_reason.
 *
 * The definition half used to live in a local TRANSLATIONS map inside
 * review.jsx; it moved to src/i18n verbatim, so those assertions now read the
 * catalogues. The consumption half still reads review.jsx.
 *
 * Run:  node src/utils/reviewUnknownWiring.test.cjs
 */

const fs = require('fs');
const path = require('path');

const review = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'logbooks', 'review.jsx'), 'utf8');
const catalogues = ['en', 'es'].map((loc) => ({
  loc,
  src: fs.readFileSync(path.join(__dirname, '..', 'i18n', `${loc}.js`), 'utf8'),
}));
const checkins = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'site', 'checkins.jsx'), 'utf8');
const workerDetail = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'workers', '[id].jsx'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── src/i18n — the strings themselves ──
// FLIPPED, not dropped. `review` is EN-only by ruling: it is the CP's approve /
// send-home / assign-trade decision surface on a legal record. The definitions
// are asserted in EN; the ES catalogue is asserted to carry NO review namespace
// at all, so a well-meant translation cannot quietly reappear. Both catalogues
// are still checked for the dead reason code.
const EN_SRC = catalogues.find((c) => c.loc === 'en').src;
const ES_SRC = catalogues.find((c) => c.loc === 'es').src;
for (const { loc, src } of catalogues) {
  ok(!/reason_EXTRACTION_INCOMPLETE/.test(src),
    `i18n/${loc}: dead reason_EXTRACTION_INCOMPLETE removed (never produced)`);
}
ok(/unknownSst:/.test(EN_SRC), 'i18n/en: unknownSst is defined');
ok(/admittedUnverified:/.test(EN_SRC), 'i18n/en: admittedUnverified is defined');
ok(/\badmit:/.test(EN_SRC), "i18n/en: 'admit' label is defined (not 'Approve')");
ok(!/^\s*review:\s*\{/m.test(ES_SRC),
  'i18n/es: the review namespace is ABSENT — a CP decision on a legal record is English');
ok(!/reason_EXTRACTION_INCOMPLETE/.test(review),
  'review.jsx: no leftover reference to the dead reason code');

// ── review.jsx — the render path that consumes them ──
ok(/t\('unknownSst'\)/.test(review),
  "review.jsx: unknownSst is consumed via t('unknownSst')");
ok(/t\(`reason_\$\{/.test(review),
  'review.jsx: reason_* keys consumed via t(`reason_${code}`) render path');
ok(/reasons\.includes\('unknown_sst'\)/.test(review),
  "review.jsx: reads the 'unknown_sst' flag_reason");
ok(/t\('admittedUnverified'\)/.test(review),
  'review.jsx: Admit records entry-only (admittedUnverified used)');
ok(/t\('admit'\)/.test(review),
  "review.jsx: 'admit' label used (not 'Approve')");

// The still-present reason_* keys must all be reachable via the generic lookup —
// there is exactly one consumption site and it is a template, so every key is
// wired. Assert the produced codes each have a key, in both locales.
for (const code of ['CLASS_UNVERIFIED', 'EXPIRY_IMPLAUSIBLE', 'EXPIRY_UNPARSEABLE',
                     'EXPIRY_CONFLICT', 'DUPLICATE_SST']) {
  // EN only — see above. The guard is unchanged in substance: a backend code
  // with no mapped copy renders as the raw key to the CP, and that still fails.
  ok(new RegExp(`reason_${code}:`).test(EN_SRC),
    `i18n/en: reason_${code} present (backend can produce it)`);
}

// ── checkins.jsx (site view) ──
ok(/sst_status === 'unknown'/.test(checkins),
  "checkins.jsx: site view treats sst_status === 'unknown'");
ok(/sst_unknown_reason/.test(checkins),
  'checkins.jsx: reads the frozen sst_unknown_reason (class/expiry/both)');
ok(/isUnknownSst/.test(checkins),
  'checkins.jsx: isUnknownSst card present');

// ── workers/[id].jsx (cert-level flag surface) ──
ok(/needs_review|review_reason/.test(workerDetail),
  'workers/[id].jsx: consumes cert needs_review/review_reason');
ok(/flaggedCerts/.test(workerDetail) && /Credential needs review/.test(workerDetail),
  'workers/[id].jsx: renders the "Credential needs review" surface (not a dead promise)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
