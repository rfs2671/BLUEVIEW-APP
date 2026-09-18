/**
 * PR B — unknown-SST is wired to a render path. THE RULE IS A BICONDITIONAL:
 * a reason_* key exists exactly when the backend can produce that code. No
 * dead strings, and no produced code left without copy.
 *
 * reason_EXTRACTION_INCOMPLETE was this file's worked example of the first
 * half and has since CHANGED SIDES — derive_cert_review now emits it where it
 * used to raise the review flag and name nothing. The assertion was flipped
 * rather than deleted; see the note beside it. That is the shape to follow if
 * another code moves: an assertion removed is a rule nobody checks any more.
 *
 * Static guard over the real sources:
 *   src/i18n/{en,es}.js — unknownSst + the reason_* keys are DEFINED in EN,
 *                 one per code the backend can emit. ES carries no review
 *                 namespace at all, by ruling.
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
// ── reason_EXTRACTION_INCOMPLETE CHANGED SIDES, AND THE RULE DID NOT ────────
// This asserted the key was ABSENT, on the stated ground that the backend
// never produced it. That was true and is no longer: derive_cert_review could
// return needs_review=true with review_reason=null when the NAME, NUMBER or
// EXPIRY was the missing field -- a reviewer told to review and not told what
// to look at -- and it now emits EXTRACTION_INCOMPLETE there, the code
// WorkerCertification.review_reason had declared all along.
//
// THE RULE IS UNCHANGED: no dead strings, and no produced code without copy.
// A key exists exactly when the backend can produce it, so a code that starts
// being produced moves from one side of that rule to the other. Flipped rather
// than deleted -- an assertion removed is a rule nobody is checking any more,
// and this one is still doing work in the other direction.
ok(/reason_EXTRACTION_INCOMPLETE:/.test(EN_SRC),
  'i18n/en: reason_EXTRACTION_INCOMPLETE present (backend can now produce it)');
// ES keeps NOTHING: the review namespace is absent there by ruling, so this key
// must not appear either. Same sentence the loop used to make, now scoped to
// the catalogue the ruling actually applies to.
ok(!/reason_EXTRACTION_INCOMPLETE/.test(ES_SRC),
  'i18n/es: no reason_* copy at all — the review namespace is EN-only by ruling');
ok(/unknownSst:/.test(EN_SRC), 'i18n/en: unknownSst is defined');
ok(/admittedUnverified:/.test(EN_SRC), 'i18n/en: admittedUnverified is defined');
ok(/\badmit:/.test(EN_SRC), "i18n/en: 'admit' label is defined (not 'Approve')");
ok(!/^\s*review:\s*\{/m.test(ES_SRC),
  'i18n/es: the review namespace is ABSENT — a CP decision on a legal record is English');
// Still ABSENT here, and for a reason that outlived the code's dead phase:
// review.jsx has exactly ONE consumption site and it is the generic
// t(`reason_${code}`) template below. A reason code named literally on this
// screen would be a second, divergent path -- which is what the check has
// really been guarding since it was written.
ok(!/reason_EXTRACTION_INCOMPLETE/.test(review),
  'review.jsx: names no reason code literally — the generic lookup is the only path');

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
                     'EXPIRY_CONFLICT', 'DUPLICATE_SST',
                     // Newly produced — see the note at the top of this file.
                     'EXTRACTION_INCOMPLETE',
                     // Newly produced by evaluate_cert_expiry: "no expiry
                     // reached the record at all", which used to arrive as
                     // review_reason null on a row nobody was asked to look at.
                     'EXPIRY_MISSING']) {
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
