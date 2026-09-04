/**
 * Unit tests for the card-photo OCR RETAKE GATE in backend/checkin.html
 * (FEATURE 2, items 7 + 8).
 *
 * The gate decides whether a card photo is good enough to keep or must be
 * retaken. The rule under test:
 *   - Gate ONLY on `name` AND `sst_number`. Either missing/empty -> retake.
 *   - Do NOT gate on `card_class` (new field, never run against a real card —
 *     gating on it could loop every worker to the ceiling).
 *   - Do NOT gate on `expiration` (a legible card often omits it; it's typed).
 *
 * checkin.html is a single backend-served HTML file with no module exports and
 * no JS test runner in this repo. Following the api.pagination.test.cjs harness,
 * this test reads the REAL checkin.html, extracts the shipped
 * OCR_CRITICAL_FIELDS array and ocrMissingCriticalFields() VERBATIM, and
 * evaluates just those. If their shape changes, extraction tracks it or throws
 * loudly — it is never a hand-copy of the logic.
 *
 * Run:  node src/utils/checkinCardGate.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(file, 'utf8');

// Extract a balanced (…) region starting at the given open char index.
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

// 1. The const OCR_CRITICAL_FIELDS = [ ... ]; literal.
const constAnchor = 'const OCR_CRITICAL_FIELDS = [';
const constAt = src.indexOf(constAnchor);
if (constAt < 0) throw new Error('OCR_CRITICAL_FIELDS not found in checkin.html');
const arrOpen = src.indexOf('[', constAt);
const arrClose = matchBalanced(src, arrOpen, '[', ']');
const constSrc = src.slice(constAt, arrClose + 1) + ';';

// 2. The function ocrMissingCriticalFields(data) { ... } body.
const fnAnchor = 'function ocrMissingCriticalFields(data)';
const fnAt = src.indexOf(fnAnchor);
if (fnAt < 0) throw new Error('ocrMissingCriticalFields not found in checkin.html');
const braceOpen = src.indexOf('{', fnAt);
const braceClose = matchBalanced(src, braceOpen, '{', '}');
const fnSrc = src.slice(fnAt, braceClose + 1);

// Build a callable with the extracted const in its scope.
// 3. The nullish-token set and the blank predicate the function now calls.
//    EXTRACTED, NOT REIMPLEMENTED. This file exists to run the SHIPPED code,
//    and when ocrMissingCriticalFields grew a helper the build threw
//    ReferenceError at the first call rather than quietly testing a stand-in.
//    That is the extraction doing its job; a source grep would have passed.
const setAnchor = 'const OCR_NULLISH = new Set([';
const setAt = src.indexOf(setAnchor);
if (setAt < 0) throw new Error('OCR_NULLISH not found in checkin.html');
const setOpen = src.indexOf('[', src.indexOf('(', setAt));
const setClose = matchBalanced(src, setOpen, '[', ']');
const setSrc = src.slice(setAt, src.indexOf(';', setClose) + 1);

const blankAnchor = 'function ocrValueIsBlank(v)';
const blankAt = src.indexOf(blankAnchor);
if (blankAt < 0) throw new Error('ocrValueIsBlank not found in checkin.html');
const blankOpen = src.indexOf('{', blankAt);
const blankClose = matchBalanced(src, blankOpen, '{', '}');
const blankSrc = src.slice(blankAt, blankClose + 1);

// eslint-disable-next-line no-new-func
const build = new Function(`${constSrc}\n${setSrc}\n${blankSrc}\n${fnSrc}\nreturn { OCR_CRITICAL_FIELDS, OCR_NULLISH, ocrValueIsBlank, ocrMissingCriticalFields };`);
const { OCR_CRITICAL_FIELDS, OCR_NULLISH, ocrValueIsBlank, ocrMissingCriticalFields } = build();

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const keysOf = (arr) => arr.map((f) => f.key);
const eq = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// The gate is exactly [name, sst_number] — no card_class, no expiration.
ok(eq(keysOf(OCR_CRITICAL_FIELDS), ['name', 'sst_number']),
  'gate fields are exactly [name, sst_number]');
ok(!keysOf(OCR_CRITICAL_FIELDS).includes('card_class'),
  'card_class is NOT a gate field (item 8)');
ok(!keysOf(OCR_CRITICAL_FIELDS).includes('expiration'),
  'expiration is NOT a gate field (item 7)');
ok(OCR_CRITICAL_FIELDS.every((f) => typeof f.labelKey === 'string' && f.labelKey),
  'every gate field carries an i18n labelKey');

// Clean read → nothing missing → no retake.
ok(eq(keysOf(ocrMissingCriticalFields({ name: 'Jane', sst_number: 'SST123' })), []),
  'name + number present -> no retake');

// Missing name -> retake on name.
ok(eq(keysOf(ocrMissingCriticalFields({ name: null, sst_number: 'SST123' })), ['name']),
  'missing name -> retake (name)');
ok(eq(keysOf(ocrMissingCriticalFields({ name: '   ', sst_number: 'SST123' })), ['name']),
  'whitespace-only name -> retake (name)');

// Missing sst_number -> retake on sst_number.
ok(eq(keysOf(ocrMissingCriticalFields({ name: 'Jane', sst_number: '' })), ['sst_number']),
  'missing card number -> retake (sst_number)');

// Missing card_class ONLY -> NO retake (item 8).
ok(eq(keysOf(ocrMissingCriticalFields({ name: 'Jane', sst_number: 'SST123', card_class: null })), []),
  'missing card_class only -> NO retake');

// Missing expiration ONLY -> NO retake (item 7).
ok(eq(keysOf(ocrMissingCriticalFields({ name: 'Jane', sst_number: 'SST123', expiration: null })), []),
  'missing expiration only -> NO retake');

// Both missing -> both flagged.
ok(eq(keysOf(ocrMissingCriticalFields({})), ['name', 'sst_number']),
  'empty OCR -> both critical fields flagged');

// Null OCR blob -> both flagged, no throw.
let threw = false;
let out;
try { out = ocrMissingCriticalFields(null); } catch (e) { threw = true; }
ok(!threw && eq(keysOf(out), ['name', 'sst_number']),
  'null OCR -> both flagged (no throw)');


// -- "null" IS NOT A READ FIELD -------------------------------------------
//
// The model is told "set the field to null if you cannot read it" and it
// sometimes answers with the STRING. It is truthy and it trims to "null", so
// the old predicate scored A TOTAL OCR FAILURE AS A COMPLETE READ: no retake
// offered, manual entry never opened, and the card submitted with every field
// saying the word null.

for (const token of ['null', 'NULL', 'None', 'n/a', 'N/A', 'na', 'nil',
                     '-', '--', 'undefined', '', '   ']) {
  ok(ocrValueIsBlank(token), JSON.stringify(token) + ' is not a read value');
}
ok(ocrValueIsBlank(null) && ocrValueIsBlank(undefined), 'null/undefined are blank');

// THE NEGATIVE HALF, so this cannot pass by calling everything blank -- and
// the names are chosen to sit next to the tokens: Nathan, Nan, Nils, NA-4471.
for (const real of ['Jose Ramirez', '12345', '0', 'Nathan', 'Nan Zhou',
                    'Nils Andersen', 'NA-4471']) {
  ok(!ocrValueIsBlank(real), JSON.stringify(real) + ' IS a read value');
}

ok(eq(keysOf(ocrMissingCriticalFields({ name: 'null', sst_number: 'null' })),
      ['name', 'sst_number']),
  'a card that read null on both fields is MISSING both -- a retake, not a pass');
ok(ocrMissingCriticalFields({ name: 'Jose Ramirez', sst_number: '12345' }).length === 0,
  'and a real read still scores clean');

// ONE ADDRESS WITH THE SERVER. lib/ocr_text.py carries the same set, and the
// two sides agreeing on what "nothing was read" means is the point of having
// a rule rather than two predicates that drift.
const pySrc = fs.readFileSync(
  path.join(__dirname, '..', '..', '..', 'backend', 'lib', 'ocr_text.py'), 'utf8');
const pyOpen = pySrc.indexOf('_NULLISH = {');
const pyBlock = pyOpen < 0 ? '' : pySrc.slice(pyOpen, pySrc.indexOf('}', pyOpen));
ok(pyBlock.length > 0, 'read the server-side token set');
for (const token of OCR_NULLISH) {
  ok(pyBlock.indexOf('"' + token + '"') >= 0,
    'the server _NULLISH also carries ' + JSON.stringify(token));
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
