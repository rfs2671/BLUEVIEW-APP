/**
 * THE PHOTO IS THE DEFAULT AND TYPING THE CARD IS A DELIBERATE SECOND CHOICE.
 *
 * ── WHAT THIS IS NOT UNDOING ────────────────────────────────────────────────
 *
 * checkin.html has said since the photo-optional fix that the card fields stay
 * ALWAYS VISIBLE, and its reason was right: a worker with no camera or a
 * damaged card must be able to type the card without first producing a photo,
 * and hiding those fields behind a successful OCR is what made a dead end.
 * Every assertion in checkinManualCardEntry.test.cjs still holds and is not
 * repeated here.
 *
 * WHAT CHANGED IS THE ORDER. Presented side by side, a camera tile and four
 * empty inputs are an EQUAL CHOICE and typing is the faster one — so manual
 * entry became the path of least resistance for workers whose card would have
 * photographed fine. A typed card is a CLAIM about a credential; a
 * photographed one is EVIDENCE of it, kept in R2 where a reviewer can look at
 * it. They are not equal.
 *
 * So the fields are collapsed behind one button, and this file asserts the
 * three things that makes true and the one thing it must not break:
 *
 *   1. they ship collapsed, and the button that opens them exists   (FAILS vs main)
 *   2. ANY read outcome opens them — success or failure: no dead end (FAILS vs main)
 *   3. a typed value is posted as `manual_entry`, so the server can
 *      never mistake a claim for a reading                          (FAILS vs main)
 *   4. a READ value is NOT posted as manual_entry — the control, without
 *      which (3) could pass by flagging everybody
 *
 * ── AND THE BUSY READER ─────────────────────────────────────────────────────
 *
 * CARD_READ_BUSY is the code the server now returns when the vision provider
 * is still answering 429 after a retry and a backoff. It must be in
 * CARD_CODES, and it must be `retake: true` — an unrecognised code falls into
 * the fallback branch, which is raw English prose on a bilingual page and the
 * one branch that never gives the worker his camera back.
 *
 * Harness follows checkinManualCardEntry.test.cjs: read the REAL
 * backend/checkin.html and evaluate the shipped functions VERBATIM.
 *
 * Run:  node src/utils/checkinManualEntryIsSecondChoice.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(file, 'utf8');

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

function extractFn(anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`${anchor} not found in checkin.html`);
  const braceOpen = src.indexOf('{', at);
  const braceClose = matchBalanced(src, braceOpen, '{', '}');
  return src.slice(at, braceClose + 1);
}

// ── FOR THE FUNCTIONS THIS CHANGE ADDS, AND ONLY THOSE ─────────────────────
//
// `extractFn` throws when a function is missing, deliberately — that is the
// contract keeping this style of test from quietly exercising a different
// function than the one that ships. But a CONTROL RUN against main needs
// NUMBERS, and a throw at the first absent function aborts the run and leaves
// twenty assertions unreached, which reads as "the fix was not needed here".
//
// So the functions this change INTRODUCES are extracted permissively and their
// absence is recorded as a FAIL. Functions that already ship (showOcrResults,
// buildCardPayload, hasManualCardDetails) still use `extractFn` and still
// throw: if one of those disappears, this file is testing a page it does not
// understand and should stop rather than report.
function extractNewFn(anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return null;
  return extractFn(anchor);
}

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// A DOM stub that models the ONE browser behaviour these functions turn on:
// classList membership, and `dataset` as a real per-element bag.
function makeDom(spec) {
  const els = {};
  const get = (id) => {
    if (!els[id]) {
      const s = (spec || {})[id] || {};
      const classes = new Set(s.classes || []);
      els[id] = {
        id,
        value: s.value == null ? '' : String(s.value),
        dataset: Object.assign({}, s.dataset),
        style: {},
        disabled: false,
        focused: false,
        classList: {
          add: (c) => classes.add(c),
          remove: (c) => classes.delete(c),
          contains: (c) => classes.has(c),
          toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        },
        focus() { this.focused = true; },
        _classes: classes,
      };
    }
    return els[id];
  };
  return { getElementById: get, querySelector: () => null, querySelectorAll: () => [], _els: els };
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE MARKUP: collapsed, with a control that opens it.
// ═══════════════════════════════════════════════════════════════════════════
const blockAt = src.indexOf('id="manualCardFields"');
ok(blockAt >= 0, 'the card detail fields are wrapped in #manualCardFields');
if (blockAt >= 0) {
  const divOpen = src.lastIndexOf('<div', blockAt);
  const tag = src.slice(divOpen, src.indexOf('>', blockAt) + 1);
  ok(/class="[^"]*\bhidden\b/.test(tag),
    '#manualCardFields ships COLLAPSED — the photo is the default');
}
const btnAt = src.indexOf('id="btnManualEntry"');
ok(btnAt >= 0, 'a control exists to open it deliberately');
ok(/onclick="chooseManualEntry\(\)"/.test(src),
  'and it calls chooseManualEntry()');
// GUARDED ON btnAt, and that guard is not decoration: without it
// `src.lastIndexOf('<', -1)` returns 0, the "tag" becomes the whole document,
// and the three assertions below PASS VACUOUSLY on a page that has no such
// button at all. Measured — they did, on the control run.
if (btnAt >= 0) {
  // IT IS A BUTTON, NOT A NOTE. The old surface was a `manual-note` div — a
  // caption, styled like the advisory notes elsewhere on the page — and a
  // caption is a thing workers were measured not reading.
  const btnTagOpen = src.lastIndexOf('<', btnAt);
  ok(src.slice(btnTagOpen, btnAt).indexOf('button') >= 0,
    'the manual-entry control is a <button>, not a styled note');
  // ...AND IT IS QUIETER THAN `Next`. If it carried .btn-primary the screen
  // would be back to presenting two equal options.
  const btnTag = src.slice(btnTagOpen, src.indexOf('>', btnAt) + 1);
  ok(!/btn-primary/.test(btnTag),
    'the manual-entry control is not styled as a primary action');
  ok(/btn-manual/.test(btnTag) && /\.btn-manual\{/.test(src),
    'it carries .btn-manual, and .btn-manual is defined');
} else {
  ok(false, 'the manual-entry control is a <button>, not a styled note');
  ok(false, 'the manual-entry control is not styled as a primary action');
  ok(false, 'it carries .btn-manual, and .btn-manual is defined');
}

// The three fields that were always visible are INSIDE the collapsed block —
// checked by position, because a field left outside it is still an equal
// option and the assertion above would not notice.
const blockEnd = src.indexOf('<!-- /#manualCardFields -->');
ok(blockEnd > blockAt, 'the collapsed block is closed and marked');
for (const id of ['regCardNumber', 'regCardClass', 'regIssued', 'regExpiration']) {
  const at = src.indexOf(`id="${id}"`);
  ok(at > blockAt && at < blockEnd, `${id} is inside the collapsed block`);
}
// AND THE NAME AND PHONE ARE NOT. They are not card details and a worker must
// always be able to type them.
for (const id of ['regName', 'regPhone']) {
  const at = src.indexOf(`id="${id}"`);
  ok(at < blockAt, `${id} is NOT collapsed — it is not a card detail`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. NO DEAD END: any read outcome opens the fields.
// ═══════════════════════════════════════════════════════════════════════════
const showOcrSrc = extractFn('function showOcrResults(data)');
const hasManualSrc = extractFn('function hasManualCardDetails()');
const presetSrc = extractFn('function presetCardClass(raw)');
const buildCardSrc = extractFn('function buildCardPayload()');
const setOcrSrc = extractNewFn('function setOcrField(id, raw)');
const revealSrc = extractNewFn('function revealManualCardFields()');
const chooseSrc = extractNewFn('function chooseManualEntry()');
const selfRepSrc = extractNewFn('function cardDetailsAreSelfReported()');
for (const [name, got] of [['setOcrField', setOcrSrc],
  ['revealManualCardFields', revealSrc], ['chooseManualEntry', chooseSrc],
  ['cardDetailsAreSelfReported', selfRepSrc]]) {
  ok(!!got, `checkin.html defines ${name}()`);
}
// EVERY ASSERTION BELOW NEEDS ALL FOUR. Reporting them absent once (above) is
// the finding; running twenty more assertions against `null` would be twenty
// more copies of the same one.
const HAVE_NEW = !!(setOcrSrc && revealSrc && chooseSrc && selfRepSrc);
function skipRest(labels) {
  for (const label of labels) ok(false, label);
}
// ═══════════════════════════════════════════════════════════════════════════
// 6. CARD_READ_BUSY is known, and it sends him back to the camera.
// ═══════════════════════════════════════════════════════════════════════════
const codesAt = src.indexOf('const CARD_CODES = {');
const codesSrc = src.slice(codesAt, matchBalanced(src, src.indexOf('{', codesAt), '{', '}') + 1);
ok(/CARD_READ_BUSY:/.test(codesSrc),
  'CARD_READ_BUSY is in CARD_CODES (an unknown code hits the prose fallback)');
const busyRow = (codesSrc.match(/CARD_READ_BUSY:\s*\{[^}]*\}/) || [''])[0];
ok(/retake:\s*true/.test(busyRow),
  'CARD_READ_BUSY is retake:true — busy is not down, so the camera is the '
  + 'right place to send him');
ok(/msg:\s*'cardReaderBusy'/.test(busyRow),
  'and it renders copy this page owns, not the server\'s English');
for (const loc of ['en', 'es']) {
  // BILINGUAL OR IT IS NOT SHIPPED. Every code in this map renders copy from
  // both catalogues; a key present in one is a worker reading the other
  // language his own error in English.
  const catAt = src.indexOf(`  ${loc}: {`, src.indexOf('const TRANSLATIONS'));
  const cat = src.slice(catAt, matchBalanced(src, src.indexOf('{', catAt), '{', '}') + 1);
  ok(/cardReaderBusy:/.test(cat), `cardReaderBusy is defined in ${loc}`);
}

// And the registration refusal is answered by CODE, not by matching the
// server's English prose — which is how BACKEND_ERROR_MAP has to work and
// exactly what breaks when a sentence is reworded.
ok(/CARD_EVIDENCE_REQUIRED:\s*'needCardOrManual'/.test(src),
  'CARD_EVIDENCE_REQUIRED maps to the page\'s own bilingual copy');
ok(/const byCode = \(e && e\.code\) \? API_ERROR_CODES\[e\.code\] : null;/.test(src),
  'translateApiError checks the machine code before the English sentence');

// ==========================================================================
// THE BEHAVIOURAL ASSERTIONS NEED THE FOUR NEW FUNCTIONS. Their absence
// is already reported once, above; running the rest against `null` would
// be the same finding twenty more times with a stack trace on top.
// ==========================================================================
if (HAVE_NEW) {
const OCR_NULLISH_SRC = (src.match(/const OCR_NULLISH = [^;]+;/) || [
  'throw new Error("OCR_NULLISH is gone from checkin.html");'])[0];

function runShowOcr(data, spec) {
  const document = makeDom(spec);
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document',
    `${OCR_NULLISH_SRC}
     ${setOcrSrc}\n${presetSrc}\n${revealSrc}\n${showOcrSrc}
     return showOcrResults;`,
  );
  build(document)(data);
  return document;
}

// A CLEAN READ still shows the fields — he must be able to correct a misread.
let dom = runShowOcr(
  { name: 'Angel Lopez', sst_number: 'RUQ24T3LVF', issued: '03/01/2026',
    expiration: '03/01/2031', card_class: 'Worker' },
  { manualCardFields: { classes: ['hidden'] } });
ok(!dom._els.manualCardFields.classList.contains('hidden'),
  'a CLEAN read opens the fields (so a misread value can be corrected)');
ok(dom._els.regCardNumber.value === 'RUQ24T3LVF',
  'a clean read still prefills the card number');

// A TOTAL FAILURE — the model answering the string "null" for every field —
// must also open them. This is the shape that once scored as a complete read.
dom = runShowOcr(
  { name: 'null', sst_number: 'null', issued: 'null', expiration: 'null' },
  { manualCardFields: { classes: ['hidden'] } });
ok(!dom._els.manualCardFields.classList.contains('hidden'),
  'a FAILED read opens the fields too — there is no dead end');
ok(dom._els.regCardNumber.value === '',
  "the model's word for nothing is not written into the field");
ok(dom._els.regCardNumber.dataset.src === undefined,
  'and an unfilled field is NOT stamped as an OCR read');

// ═══════════════════════════════════════════════════════════════════════════
// 3 + 4. THE MARKER. A typed value is a claim; a read value is not.
// ═══════════════════════════════════════════════════════════════════════════
function runSelfReported(spec, oshaImage) {
  const document = makeDom(spec);
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'oshaImage',
    `${hasManualSrc}\n${selfRepSrc}\nreturn cardDetailsAreSelfReported;`,
  );
  return build(document, oshaImage)();
}

ok(runSelfReported({ regCardNumber: { value: 'RUQ24T3LVF' } }, null) === true,
  'no photo + a typed number -> self-reported');
ok(runSelfReported({ regExpiration: { value: '03/01/2031' } }, null) === true,
  'no photo + a typed expiry -> self-reported');
ok(runSelfReported({
  regCardNumber: { value: 'RUQ24T3LVF', dataset: { src: 'ocr' } },
  regIssued: { value: '03/01/2026', dataset: { src: 'ocr' } },
  regExpiration: { value: '03/01/2031', dataset: { src: 'ocr' } },
}, 'data:image/jpeg;base64,XX') === false,
  'A CLEAN OCR READ IS NOT SELF-REPORTED — the control, without which the '
  + 'marker would flag the whole workforce');
ok(runSelfReported({
  regCardNumber: { value: 'RUQ24T3LVF', dataset: { src: 'ocr' } },
  regExpiration: { value: '03/01/2031', dataset: { src: 'worker' } },
}, 'data:image/jpeg;base64,XX') === true,
  'a CORRECTED expiry on an otherwise-read card -> self-reported (it is his '
  + 'statement about that field)');
ok(runSelfReported({}, null) === false,
  'nothing typed and no photo is not a self-report — it is no card at all, '
  + 'which goStep(2) and the server both refuse');

// ── and it reaches the payload ──
// `buildCardSrc` is extracted with the other shipped functions above.
function runBuildCard(spec, oshaData, oshaImage) {
  const document = makeDom(spec);
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'oshaData', 'oshaImage',
    `${hasManualSrc}\n${selfRepSrc}\n${buildCardSrc}\nreturn buildCardPayload;`,
  );
  return build(document, oshaData, oshaImage)();
}

let card = runBuildCard(
  { regCardNumber: { value: 'CKALD4CRD7' }, regExpiration: { value: '06/24/2027' } },
  null, null);
ok(card.osha_data.manual_entry === true,
  'a typed card posts manual_entry: true');
ok(card.osha_data.sst_number === 'CKALD4CRD7' && card.osha_number === 'CKALD4CRD7',
  'and the typed values still ride the payload exactly as before');

card = runBuildCard({
  regCardNumber: { value: 'RUQ24T3LVF', dataset: { src: 'ocr' } },
  regIssued: { value: '03/01/2026', dataset: { src: 'ocr' } },
  regExpiration: { value: '03/01/2031', dataset: { src: 'ocr' } },
  regCardClass: { value: 'Worker', dataset: { src: 'ocr' } },
}, { name: 'Angel Lopez', card_dominant_color: 'BLUE' },
   'data:image/jpeg;base64,XX');
ok(card.osha_data.manual_entry === undefined,
  'a READ card posts NO manual_entry marker');
ok(card.osha_data.class_source === undefined,
  'and no self_reported class marker either — the control for the control');

// ═══════════════════════════════════════════════════════════════════════════
// 5. chooseManualEntry: opens, spends the offer, lands the caret.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  const document = makeDom({
    manualCardFields: { classes: ['hidden'] },
    btnManualEntry: { classes: [] },
  });
  // eslint-disable-next-line no-new-func
  const build = new Function('document',
    `${revealSrc}\n${chooseSrc}\nreturn chooseManualEntry;`);
  build(document)();
  ok(!document._els.manualCardFields.classList.contains('hidden'),
    'chooseManualEntry() opens the fields');
  ok(document._els.btnManualEntry.classList.contains('hidden'),
    'and hides its own button — a control that does nothing reads as an '
    + 'unfinished step');
  ok(document._els.regCardNumber.focused === true,
    'and puts the caret in the card number field');
})();

}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
