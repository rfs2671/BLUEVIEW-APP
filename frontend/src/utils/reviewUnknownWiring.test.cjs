/**
 * PR B — unknown-SST is wired to a render path, and the dead TRANSLATIONS key
 * that nothing could ever produce is removed. No dead strings.
 *
 * Static guard over the real sources:
 *   review.jsx  — reason_EXTRACTION_INCOMPLETE removed (backend never emits it);
 *                 unknownSst + the reason_* keys are CONSUMED (t('unknownSst'),
 *                 t(`reason_${...}`)); the unknown flag + Admit path exist.
 *   checkins.jsx — the site view reads sst_status === 'unknown' and its frozen
 *                 sst_unknown_reason.
 *
 * Run:  node src/utils/reviewUnknownWiring.test.cjs
 */

const fs = require('fs');
const path = require('path');

const review = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'logbooks', 'review.jsx'), 'utf8');
const checkins = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'site', 'checkins.jsx'), 'utf8');
const workerDetail = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'workers', '[id].jsx'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── review.jsx ──
ok(!/reason_EXTRACTION_INCOMPLETE/.test(review),
  'review.jsx: dead reason_EXTRACTION_INCOMPLETE removed (never produced)');
ok(/unknownSst:/.test(review) && /t\('unknownSst'\)/.test(review),
  "review.jsx: unknownSst is defined AND consumed via t('unknownSst')");
ok(/t\(`reason_\$\{/.test(review),
  'review.jsx: reason_* keys consumed via t(`reason_${code}`) render path');
ok(/reasons\.includes\('unknown_sst'\)/.test(review),
  "review.jsx: reads the 'unknown_sst' flag_reason");
ok(/admittedUnverified:/.test(review) && /t\('admittedUnverified'\)/.test(review),
  'review.jsx: Admit records entry-only (admittedUnverified defined + used)');
ok(/admit:/.test(review) && /t\('admit'\)/.test(review),
  "review.jsx: 'admit' label defined + used (not 'Approve')");

// The still-present reason_* keys must all be reachable via the generic lookup —
// there is exactly one consumption site and it is a template, so every key is
// wired. Assert the produced codes each have a key.
for (const code of ['CLASS_UNVERIFIED', 'EXPIRY_IMPLAUSIBLE', 'EXPIRY_UNPARSEABLE',
                     'EXPIRY_CONFLICT', 'DUPLICATE_SST']) {
  ok(new RegExp(`reason_${code}:`).test(review),
    `review.jsx: reason_${code} present (backend can produce it)`);
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
