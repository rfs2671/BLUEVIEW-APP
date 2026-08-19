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
ok(iPrimary !== -1, 'the ranked band still renders');

// ── THE BAND IS GONE, AND TWO OF THE THREE GUARDS WITH IT ──────────────────
//
// #177 separated two bands with a heading, because four ranked chips and twelve
// always-available ones in one flex container read as sixteen boxes. The
// operator's correction landed one level up: that band was offering every crew
// another sub's work, so it is REMOVED rather than tidied.
//
// "never capped" and "never folded" described a band that no longer exists.
// Re-pointed rather than deleted — what replaces them is that none of it came
// back.
ok(!/always\.map/.test(src), 'no always-available band renders on a crew card');
ok(!/chipBandHeading/.test(src), 'and the heading that separated it went with it');
ok(!/siteActivityQuestion/.test(src), 'and its question is gone from the card');

// "Other" REJOINED THE ONE REMAINING CONTAINER. It lived INSIDE the always
// band, so removing that band must not have taken it along — and it must still
// be reachable without scrolling.
ok(/chipOther/.test(src), 'Other survives the band it happened to live in');
{
  const iOther = src.indexOf("t('chipOther')");
  ok(iOther > iPrimary && !/<\/View>/.test(src.slice(iPrimary, iOther)),
    'and sits in the SAME container as the ranked chips — always visible');
}

// ── THE GUARD THAT STILL HOLDS, AND MATTERS MORE THAN BEFORE ───────────────
//
// The four-slot cap was never the defect and must not be "fixed" in a future
// round. It matters MORE now: the ten de-special-cased activities compete for
// those four slots on the crews whose taxonomy holds them.
{
  const model = fs.readFileSync(path.join(__dirname, 'dailyJobsiteModel.js'), 'utf8');
  ok(/primary = suggested\.slice\(0, CHIP_SLOTS\)/.test(model)
    && /primary = tradeCatalog\.slice\(0, CHIP_SLOTS\)/.test(model),
    'the four-slot cap is unchanged on every branch');
  ok(/return \{ primary, rest, basis, hidden: rest\.length \};/.test(model),
    'composeChipBands returns { primary, rest, basis } — always is gone');
  ok(!/band === .always_available./.test(model),
    "and nothing filters on the dead band, which would hide a crew's own work");
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
