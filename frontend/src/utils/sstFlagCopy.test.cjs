/**
 * FOUR STATES RENDERED AS ONE MESSAGE.
 *
 * THE DEFECT. preshift_signin.jsx carried a binary ternary:
 *
 *     {f.sst_status === 'expired' ? 'Expired SST card' : 'Unknown SST card'}
 *
 * so everything that was not `expired` printed "Unknown SST card" -- including
 * any state added later. And the flag map admitted only `expired` and
 * `unknown`, so `missing` never reached the screen at all.
 *
 * The data distinguishes far more than two cases, in TWO PARALLEL VOCABULARIES:
 *
 *   review_reason        on the worker's SST cert. LIVE, granular, one code:
 *                        CLASS_UNVERIFIED / CLASS_FROM_COLOR_UNCONFIRMED /
 *                        CLASS_CONFLICTED / CLASS_EXPIRED_SCHEME /
 *                        EXPIRY_UNPARSEABLE / EXPIRY_IMPLAUSIBLE /
 *                        EXPIRY_CONFLICT / DUPLICATE_SST / CARD_NUMBER_FORMAT
 *   sst_unknown_reason   on the check-in row. FROZEN at check-in, coarse:
 *                        CLASS / EXPIRY / BOTH, and null unless
 *                        sst_status === 'unknown' AND a cert existed.
 *
 * WHICH ONE DRIVES THE COPY: review_reason, with sst_unknown_reason filling in
 * only what review_reason did not say. The reason is structural, not taste --
 * sst_unknown_reason derives `_class_unknown` as `type not in SST_CLASS_TYPES`
 * (server.py ~:14130), which is FALSE for two of the four real production
 * rows, so the frozen vocabulary is null for both and can never name them:
 *
 *   SST_LIMITED  — a dead card scheme; the type IS in SST_CLASS_TYPES
 *   SST_FULL     — fully classified, flagged only because class_source was
 *                  colour-derived
 *
 * review_reason names all four. It is also the vocabulary the admin review
 * screen already renders (app/logbooks/review.jsx, via t(`reason_${code}`) on
 * the flagged endpoint's `sst_review_reason`), so the CP's pre-shift screen and
 * the admin's review screen now say the same thing about the same card.
 *
 * AND review_reason IS LOSSY IN ONE DIRECTION, which is why the frozen field is
 * still read: when the expiry gate fires it OVERWRITES the resolver's class
 * reason (server.py ~:3032, `if reason is None and _res["review_reason"]`), so
 * a row that is BOTH class-unreadable and expiry-unreadable records only
 * EXPIRY_UNPARSEABLE. sst_unknown_reason === 'BOTH' recovers the class fact
 * that was dropped. Neither vocabulary is complete; the pair is.
 *
 * NOTHING IS COLLAPSED THAT CANNOT BE DISTINGUISHED. CLASS_UNVERIFIED covers
 * both "OCR could not read the class" and "the class read is a dead scheme",
 * and the stored code does not say which -- so the copy says "could not be
 * CONFIRMED", which is true of both, rather than "could not be READ", which is
 * false of the second.
 *
 * Run:  node src/utils/sstFlagCopy.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

function loadModule(abs) {
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), {
    filename: abs,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}

const M = loadModule(path.join(__dirname, 'sstFlagCopy.js'));
const { sstFlagCopy } = M;

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function eq(actual, expected, label) {
  ok(actual === expected, `${label}${actual === expected ? '' : `\n         got: ${JSON.stringify(actual)}\n         want: ${JSON.stringify(expected)}`}`);
}

// ── The FOUR REAL PRODUCTION ROWS, all four of which used to render the single
//    string "Unknown SST card". ────────────────────────────────────────────
const FIELD = {
  // SST_LIMITED, card XCAS2DYB8G, expires 2028-02-26, CLASS_UNVERIFIED.
  // A dead scheme: the class IS in SST_CLASS_TYPES, so sst_unknown_reason is
  // null and only review_reason has anything to say.
  deadScheme: { sstStatus: 'unknown', reviewReason: 'CLASS_UNVERIFIED', unknownReason: null },
  // SST_UNSPECIFIED, card_number NULL, expiration NULL, CLASS_UNVERIFIED.
  nothingRead: { sstStatus: 'unknown', reviewReason: 'CLASS_UNVERIFIED', unknownReason: 'BOTH' },
  // SST_UNSPECIFIED, card TYPN6JCNJ1, expiration NULL, EXPIRY_UNPARSEABLE.
  // His card number is fine and his EXPIRY did not parse -- the fact the
  // record names first.
  expiryUnread: { sstStatus: 'unknown', reviewReason: 'EXPIRY_UNPARSEABLE', unknownReason: 'BOTH' },
  // SST_FULL, card 4YU1RY8KKM, fully classified, flagged only because
  // class_source was colour-derived. sst_unknown_reason is null here too.
  colourOnly: { sstStatus: 'unknown', reviewReason: 'CLASS_FROM_COLOR_UNCONFIRMED', unknownReason: null },
};

console.log('\nthe four production rows are four different sentences');

const four = Object.entries(FIELD).map(([k, v]) => [k, sstFlagCopy(v)]);
for (const [k, c] of four) {
  ok(c && typeof c.title === 'string' && c.title.length > 0, `${k}: has a title`);
  ok(c && typeof c.detail === 'string' && c.detail.length > 0,
    `${k}: NAMES A REASON -- a non-empty detail line`);
}
const details = four.map(([, c]) => (c || {}).detail);
ok(new Set(details).size === 4,
  `all four details are distinct (${new Set(details).size} distinct of 4)`);
ok(four.every(([, c]) => c && c.detail !== 'Unknown SST card'),
  'none of them is the old single "Unknown SST card" string');

eq(sstFlagCopy(FIELD.deadScheme).detail,
  'The card class could not be confirmed.',
  'dead scheme: "confirmed", never "read" -- CLASS_UNVERIFIED cannot tell an '
  + 'unreadable class from a dead one');
eq(sstFlagCopy(FIELD.nothingRead).detail,
  'The card class and the expiry date could not be confirmed.',
  'nothing read: the frozen BOTH supplies the expiry half');
eq(sstFlagCopy(FIELD.expiryUnread).detail,
  'The expiry date could not be read, and the card class could not be confirmed.',
  'expiry unreadable: the recorded reason leads, the dropped class fact follows');
eq(sstFlagCopy(FIELD.colourOnly).detail,
  'The card class was read from the card colour and has not been confirmed '
  + 'against the card.',
  'colour-derived: the one state the CP can settle by looking at the card');

// ── The title separates the five sst_status values ─────────────────────────
console.log('\nsst_status has five values, not two');

eq(sstFlagCopy({ sstStatus: 'expired' }).title, 'Expired SST card', 'expired');
eq(sstFlagCopy({ sstStatus: 'unknown' }).title, 'SST card not confirmed', 'unknown');
eq(sstFlagCopy({ sstStatus: 'missing' }).title, 'No SST card on file', 'missing');
eq(sstFlagCopy({ sstStatus: 'expiring_soon' }).title, 'SST card expiring soon',
  'expiring_soon');
ok(sstFlagCopy({ sstStatus: 'valid' }) === null, 'valid raises nothing');
ok(sstFlagCopy({ sstStatus: null }) === null, 'no status raises nothing');
ok(sstFlagCopy({}) === null, 'an absent status raises nothing');
ok(sstFlagCopy({ sstStatus: 'expired' }).title !== sstFlagCopy({ sstStatus: 'unknown' }).title,
  'unknown never reads as expired');

// A STATE ADDED LATER MUST NOT INHERIT SOMEONE ELSE'S SENTENCE. That is the
// exact shape of the defect: the old ternary's else-branch claimed every
// value it had never heard of.
ok(sstFlagCopy({ sstStatus: 'suspended_by_dob' }) === null,
  'an unrecognised status renders NOTHING rather than borrowing "unknown"');

// ── The honest fallbacks ───────────────────────────────────────────────────
console.log('\nthe narrower true thing, never invented precision');

eq(sstFlagCopy({ sstStatus: 'unknown', reviewReason: null, unknownReason: null }).detail,
  'The card class or the expiry date could not be confirmed.',
  'no reason in either vocabulary: says OR -- it does not claim to know which');
eq(sstFlagCopy({ sstStatus: 'unknown', reviewReason: null, unknownReason: 'EXPIRY' }).detail,
  'The expiry date could not be confirmed.',
  'frozen reason alone still narrows it');
eq(sstFlagCopy({ sstStatus: 'unknown', reviewReason: null, unknownReason: 'CLASS' }).detail,
  'The card class could not be confirmed.',
  'frozen CLASS alone');
eq(sstFlagCopy({ sstStatus: 'unknown', reviewReason: 'WHAT_IS_THIS', unknownReason: null }).detail,
  'The card class or the expiry date could not be confirmed.',
  'a review_reason this bundle has never heard of falls back rather than '
  + 'printing a raw code at a CP');

// ── The rest of the live vocabulary, each with its own sentence ────────────
console.log('\nevery code the backend can produce has its own sentence');

const CODES = {
  CLASS_UNVERIFIED: 'The card class could not be confirmed.',
  CLASS_FROM_COLOR_UNCONFIRMED:
    'The card class was read from the card colour and has not been confirmed '
    + 'against the card.',
  CLASS_CONFLICTED: 'The card colour and the printed class do not agree.',
  CLASS_EXPIRED_SCHEME: 'This card class is no longer issued.',
  EXPIRY_UNPARSEABLE: 'The expiry date could not be read.',
  EXPIRY_IMPLAUSIBLE: 'The expiry date read from the card is not a possible date.',
  EXPIRY_CONFLICT: 'Two scans of this card disagree on the expiry date.',
  DUPLICATE_SST: 'This worker has two SST records that have not been resolved to one.',
  CARD_NUMBER_FORMAT: 'The card number does not match the expected format.',
  CARD_NOT_SST: 'The card that was scanned is not an SST card.',
  EXTRACTION_INCOMPLETE: 'Some details could not be read from this card.',
};
for (const [code, want] of Object.entries(CODES)) {
  eq(sstFlagCopy({ sstStatus: 'unknown', reviewReason: code, unknownReason: null }).detail,
    want, code);
}
ok(new Set(Object.values(CODES)).size === Object.keys(CODES).length,
  'no two codes share a sentence');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
