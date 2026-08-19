/**
 * THE TWO CHIP BANDS MUST NOT RENDER AS ONE LIST.
 *
 * Reported four times as "12-15 chips per crew" and the cap was working every
 * time: four ranked chips and up to twelve always-available ones rendered into
 * ONE flex-wrap container with nothing between them, so sixteen boxes read as
 * one list and a correct four-slot cap looked broken.
 *
 * Asserted on STRUCTURE, not on a string: that the two maps sit in different
 * containers with a heading between them.
 */
const fs = require('fs');
const path = require('path');

let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed++; console.log('  PASS ', l); } else { failed++; console.log('  FAIL ', l); } }

const APP = path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx');
const src = fs.readFileSync(APP, 'utf8');

const iPrimary = src.indexOf('{primary.map((c) => (');
const iAlways = src.indexOf('{always.map((c) => (');
ok(iPrimary !== -1 && iAlways > iPrimary, 'both bands render, ranked first');

const between = src.slice(iPrimary, iAlways);

// THE STRUCTURAL CLAIM: the primary container CLOSES before always opens, and
// a new one opens for it. Without this the two maps share a flex-wrap parent
// and the boxes run together.
ok(/<\/View>/.test(between), 'the ranked band CLOSES its container before the second band');
ok(/<View style=\{s\.chipWrap\}>/.test(between), 'and the second band opens its OWN container');
ok((between.match(/<\/View>/g) || []).length >= 1
  && (between.match(/<View style=\{s\.chipWrap\}>/g) || []).length >= 1,
  'so the two maps cannot share one flex-wrap parent');

// THE HEADING. A different QUESTION, not a section label — the band below
// answers "what else happened on site", not "more of this crew's work".
ok(/s\.chipBandHeading/.test(between), 'a heading sits between them');
ok(/t\('siteActivityQuestion'\)/.test(between), 'and it is its own question, from i18n');
ok(/always\.length > 0 &&/.test(between),
  'the heading is suppressed when the second band is empty, so no crew sees a heading over nothing');

// THE RULINGS THAT MUST NOT HAVE BEEN QUIETLY TRADED AWAY.
ok(!/always\.slice\(/.test(src),
  'always-available is NOT capped — it never competes for the four, by ruling');
ok(!/expandedChips\[[^\]]*\][\s\S]{0,80}always\.map/.test(src),
  'and NOT folded behind the expander — burying "rain / no work" on a rain day is worse');

// The four-slot cap itself is untouched; the fix was never a smaller cap.
const model = fs.readFileSync(path.join(__dirname, 'dailyJobsiteModel.js'), 'utf8');
ok(/primary = suggested\.slice\(0, CHIP_SLOTS\)/.test(model)
  && /primary = tradeCatalog\.slice\(0, CHIP_SLOTS\)/.test(model),
  'the four-slot cap is unchanged on every branch — it was never the defect');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
