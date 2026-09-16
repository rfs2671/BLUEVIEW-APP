/**
 * THE CLASS PICKER, THE WAY BACK TO A CARD SCAN, AND WHO FAILED FOR HOW LONG.
 *
 * All three live in backend/checkin.html — the SERVER-RENDERED gate page, which
 * ships with the BACKEND deploy and is NOT an EAS OTA. It is asserted from here
 * anyway, verbatim, because that is where this repo's JS harness lives.
 *
 * WHAT EACH BLOCK PINS, and what it does against main:
 *
 *  1. THE PICKER EXISTS.                                   (FAILS against main)
 *     Manual entry collapsed the card to three keys — sst_number, issued,
 *     expiration. There was no class field, so CLASS_UNVERIFIED was the
 *     guaranteed outcome of every manual entry, forever. Six of the twelve
 *     flagged certifications on the live company got there this way.
 *
 *  2. A PICKED CLASS IS MARKED AS THE WORKER'S OWN.        (FAILS against main)
 *     Without the marker the picked class reaches resolve_card_class as
 *     ordinary card text, comes back `text_only` with no review reason, and
 *     mints a CLEAN certification row out of a dropdown. The marker is the one
 *     thing that distinguishes a class the CARD said from one the WORKER said.
 *
 *  3. A CLASS THE CARD READ IS NOT MARKED.                 (passes on main too)
 *     The other half, and it is what keeps (2) from being a regression: OCR's
 *     own reading keeps the verdict it has always had.
 *
 *  4. THE RETURNING WORKER CAN GET BACK TO THE CARD STEP.  (FAILS against main)
 *     The gate skipped the card step for a returning worker, so his tap posted
 *     no osha_data and no image and the row was left untouched. The only route
 *     to a fresh read was registering as a NEW worker — which is how one man
 *     ended up with two worker documents.
 *
 *  5. AND IT IS A REQUEST, NOT A REFUSAL.                  (FAILS against main)
 *     `Check In Now` stays live beside the scan button. The gate does not stop
 *     a man working.
 *
 *  6. THE FAILURE REPORT CARRIES A NAME AND A WAIT.        (FAILS against main)
 *     Two men were turned away on 588 Thomas on 2026-09-15 and nobody knows
 *     who they were.
 *
 * Harness follows checkinManualCardEntry.test.cjs: read the REAL
 * backend/checkin.html and evaluate the shipped functions VERBATIM. Nothing
 * here is a hand-copy of the logic.
 *
 * Run:  node src/utils/checkinCardClassAndRescan.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(file, 'utf8');

// ── extraction helpers (same contract as checkinManualCardEntry.test.cjs) ───
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

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── a minimal DOM good enough for the extracted functions ──────────────────
function makeDom(values, datasets) {
  const els = {};
  const get = (id) => {
    if (!els[id]) {
      els[id] = {
        id,
        value: ((values || {})[id]) == null ? '' : String((values || {})[id]),
        innerHTML: '',
        textContent: '',
        style: {},
        disabled: false,
        hiddenClass: false,
        classList: {
          add(c) { if (c === 'hidden') els[id].hiddenClass = true; },
          remove(c) { if (c === 'hidden') els[id].hiddenClass = false; },
          toggle() {},
        },
        focus() {},
        dataset: Object.assign({}, (datasets || {})[id]),
      };
    }
    return els[id];
  };
  return {
    getElementById: get,
    querySelector: (sel) => get(sel),
    querySelectorAll: () => [],
    _els: els,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE MARKUP. The field that did not exist.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 1. the manual form has a class field --');

ok(/id="regCardClass"/.test(src),
  'step 1 ships a card-class control');

const selAt = src.indexOf('id="regCardClass"');
const selOpen = src.lastIndexOf('<select', selAt);
const selBlock = src.slice(selOpen, src.indexOf('</select>', selAt));

['Worker', 'Supervisor', 'Temporary'].forEach((v) => {
  ok(selBlock.indexOf(`value="${v}"`) >= 0,
    `the picker offers ${v}`);
});
ok(selBlock.indexOf('value="Limited"') < 0,
  'the picker does NOT offer the dead Limited class');
// The empty value must be FIRST, so "I'm not sure" is what an untouched form
// submits and a wrong pick is never the path of least resistance.
ok(/<option value=""/.test(selBlock.slice(0, selBlock.indexOf('value="Worker"'))),
  'the default option is the empty "I\'m not sure"');
ok(/onchange="this\.dataset\.src='worker'"/.test(selBlock),
  'touching the picker stamps the class as the WORKER\'S answer');

// The class must never gate step 1: it is a brand-new field that has never run
// against a real card, and gating on it would loop every worker to the ceiling.
const criticalAt = src.indexOf('const OCR_CRITICAL_FIELDS');
const criticalBlock = src.slice(criticalAt, src.indexOf('];', criticalAt));
ok(criticalBlock.indexOf('card_class') < 0,
  'card_class is NOT an OCR-critical field (it can never block a worker)');

// ═══════════════════════════════════════════════════════════════════════════
// 2 + 3. THE PAYLOAD. Who said this class?
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 2/3. a picked class is the worker\'s statement --');

const buildCardPayloadSrc = extractFn('function buildCardPayload()');

function runBuildCardPayload({ fields, dataset, oshaData }) {
  const document = makeDom(fields, { regCardClass: dataset || {} });
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'oshaData',
    `${buildCardPayloadSrc}\nreturn buildCardPayload;`,
  );
  return build(document, oshaData || null)();
}

// THE ONE THAT MATTERS. OCR failed entirely; the worker typed his card number
// and picked his class off the dropdown.
const manual = runBuildCardPayload({
  fields: {
    regCardNumber: 'X2L5QYKYEJ',
    regExpiration: '05/06/2031',
    regCardClass: 'Supervisor',
  },
  dataset: {},                 // never stamped 'ocr' — OCR read nothing
  oshaData: null,
});
ok(manual.osha_data.card_class === 'Supervisor',
  'a manually picked class REACHES the payload');
ok(manual.osha_data.class_source === 'self_reported',
  'and it is marked self_reported');

// OCR read the class and the worker left it alone.
const scanned = runBuildCardPayload({
  fields: { regCardNumber: 'X2L5QYKYEJ', regCardClass: 'Supervisor' },
  dataset: { src: 'ocr' },
  oshaData: { card_class: 'SST Supervisor', sst_number: 'X2L5QYKYEJ' },
});
ok(scanned.osha_data.class_source === undefined,
  'a class OCR read carries NO self_reported marker');

// OCR read it and the worker corrected it — that correction is his statement.
const corrected = runBuildCardPayload({
  fields: { regCardNumber: 'X2L5QYKYEJ', regCardClass: 'Worker' },
  dataset: { src: 'worker' },
  oshaData: { card_class: 'SST Supervisor' },
});
ok(corrected.osha_data.card_class === 'Worker'
  && corrected.osha_data.class_source === 'self_reported',
  'correcting a misread class is recorded as the worker\'s statement');

// "I'm not sure" adds nothing at all: today's behaviour, unchanged.
const unsure = runBuildCardPayload({
  fields: { regCardNumber: 'X2L5QYKYEJ', regCardClass: '' },
  dataset: {},
  oshaData: { card_class: null, sst_number: 'X2L5QYKYEJ' },
});
ok(!('class_source' in unsure.osha_data),
  '"I\'m not sure" adds no marker');
ok(unsure.osha_data.card_class == null,
  '"I\'m not sure" invents no class');

// The typed fields still override the OCR blob — the rule this replaces.
const overridden = runBuildCardPayload({
  fields: { regCardNumber: 'CORRECTED1', regExpiration: '01/02/2030' },
  dataset: {},
  oshaData: { sst_number: 'MISREAD', expiration: '01/02/2020', name: 'Luis' },
});
ok(overridden.osha_data.sst_number === 'CORRECTED1'
  && overridden.osha_data.expiration === '01/02/2030'
  && overridden.osha_data.name === 'Luis',
  'typed corrections still win over the OCR blob, and the rest survives');

// The preselect is a DISPLAY decision, and a reading it cannot place loses
// nothing: the picker stays empty and the OCR text still rides in the payload.
console.log('\n-- 3b. preselecting the picker from what OCR read --');
const presetSrc = extractFn('function presetCardClass(raw)');
function runPreset(raw) {
  const document = makeDom({}, { regCardClass: {} });
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'OCR_NULLISH',
    `${presetSrc}\nreturn presetCardClass;`,
  );
  build(document, new Set(['null', 'none', 'n/a', 'na', 'nil', '-', '--', 'undefined']))(raw);
  return document.getElementById('regCardClass');
}
ok(runPreset('SST Supervisor').value === 'Supervisor',
  'OCR "SST Supervisor" preselects Supervisor');
ok(runPreset('SST Supervisor').dataset.src === 'ocr',
  'and stamps the class as the CARD\'s answer');
ok(runPreset('Worker').value === 'Worker',
  'OCR "Worker" — the word on the 40-hour card — preselects Worker');
ok(runPreset('null').value === '' && runPreset('null').dataset.src === undefined,
  'the model\'s string "null" preselects NOTHING and stamps nothing');
ok(runPreset('Site Safety Manager').value === '',
  'a reading the picker cannot place leaves it on "I\'m not sure"');

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE WAY BACK TO THE CARD STEP.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 4. a returning worker can re-scan his card --');

ok(/id="btnRetScanCard"/.test(src),
  'the returning screen ships a card re-scan control');
ok(/startCardRescan\(\)/.test(src),
  'and it opens the card step');
ok(/needs_card_scan === true/.test(src),
  'shown ONLY when the server says the card needs looking at (strict ===)');

// goStep(2) SUBMITS instead of walking him to the trade step: he already has a
// trade, an orientation and a signature on file, and re-collecting them is how
// a re-scan turns into a second worker document for one man.
const goStepSrc = extractFn('function goStep(step)');
const hasManualSrc = extractFn('function hasManualCardDetails()');

function runGoStep({ fields, rescan }) {
  const document = makeDom(fields);
  const errors = [];
  const revealed = [];
  const submits = [];
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'showError', 't', 'oshaImage', 'oshaData',
    'getSelectedAssignment', 'noTradesConfigured', 'revealStep',
    'cardRescanOnly', 'quickCheckIn',
    `${hasManualSrc}\n${goStepSrc}\nreturn goStep;`,
  );
  build(
    document,
    (m) => errors.push(m),
    (k) => k,
    null, null,
    () => null,
    true,
    (s) => revealed.push(s),
    rescan,
    () => submits.push(1),
  )(2);
  return { errors, revealed, submits };
}

const rescanSubmit = runGoStep({
  fields: { regName: 'Jose David Hernandez Pena', regCardNumber: 'X2L5QYKYEJ' },
  rescan: true,
});
ok(rescanSubmit.submits.length === 1,
  'card re-scan + typed details -> SUBMITS the check-in');
ok(rescanSubmit.revealed.length === 0,
  'and does NOT march him back through the four registration steps');

// And a re-scan carrying nothing is refused by the SAME guard a registration
// is: a tap that posts no card evidence changes no row and looks like a fix.
const rescanEmpty = runGoStep({
  fields: { regName: 'Jose David Hernandez Pena' },
  rescan: true,
});
ok(rescanEmpty.submits.length === 0 && rescanEmpty.errors[0] === 'needCardOrManual',
  'a re-scan with no photo and nothing typed is refused, and says why');

// A NEW worker is untouched by any of this.
const normal = runGoStep({
  fields: { regName: 'Luis Ramirez', regCardNumber: 'X2L5QYKYEJ' },
  rescan: false,
});
ok(normal.revealed.length === 1 && normal.revealed[0] === 2 && normal.submits.length === 0,
  'a NEW worker still advances to step 2 exactly as before');

// ═══════════════════════════════════════════════════════════════════════════
// 5. IT IS A REQUEST, NOT A REFUSAL.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 5. the gate does not stop a man working --');

const retStart = src.indexOf('id="screenReturning"');
const retEnd = src.indexOf('id="screenRegister"');
const retMarkup = src.slice(retStart, retEnd);
ok(retMarkup.indexOf('onclick="quickCheckIn()"') >= 0,
  '`Check In Now` is still on the returning screen');
ok(retMarkup.indexOf('id="btnRetScanCard"') >= 0,
  'and the scan button is BESIDE it, not instead of it');
ok(retMarkup.indexOf('onclick="quickCheckIn()"') < retMarkup.indexOf('id="btnRetScanCard"'),
  'and it comes FIRST — checking in is the primary action');

// The card evidence reaches the server on the re-scan, or the whole button is
// theatre: build_worker_certifications leaves the row untouched when a check-in
// posts no osha_data.
const quickSrc = extractFn('async function quickCheckIn()');
ok(/osha_data:\s*\(_card && _card\.osha_data\)/.test(quickSrc),
  'quickCheckIn posts the card evidence when there is any');
ok(/osha_card_image:\s*oshaImage \|\| undefined/.test(quickSrc),
  'including the photo itself');
ok(/hasManualCardDetails\(\)/.test(quickSrc),
  'and it keys on the EVIDENCE, not on which screen he came from');

// ═══════════════════════════════════════════════════════════════════════════
// 6. WHO FAILED, AND FOR HOW LONG.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 6. a gate failure names a man and a duration --');

const reportSrc = extractFn('function reportGateFailure(kind, detail)');

function runReport({ typedName, waited }) {
  const document = makeDom({ regName: typedName });
  let posted = null;
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'projectId', 'tagId', 'ocrAttempts', 'currentLang',
    'deviceFingerprint', 'API_BASE', 'navigator', 'waitedMs',
    `${reportSrc}\nreturn reportGateFailure;`,
  );
  build(
    document, 'projA', 'tag1', 2, 'es', 'fc47338d687a0d', '/api',
    { sendBeacon: (url, blob) => { posted = blob; return true; } },
    () => waited,
  )('card_ocr_http_failed', 'Request failed');
  return JSON.parse(posted._body);
}

// makeDom's Blob stand-in: capture the JSON rather than the Blob.
global.Blob = function Blob(parts) { this._body = parts[0]; };

const named = runReport({ typedName: 'Luis Ramirez', waited: 38000 });
ok(named.name === 'Luis Ramirez',
  'the name he has already typed is reported');
ok(named.waited_ms === 38000,
  'and how long he waited before giving up');
ok(named.fingerprint_id === 'fc47338d687a0d' && named.ocr_attempts === 2,
  'and everything the row already carried still rides along');

const anonymous = runReport({ typedName: '', waited: null });
ok(anonymous.name === null,
  'a failure before he typed anything reports no name — nothing is looked up');
ok(anonymous.waited_ms === null,
  'and no invented duration');

// SCOPED TO ONE FIELD. The reversal of "no PII" buys the name and nothing else.
ok(!('phone' in named) && !('osha_number' in named) && !('image' in named),
  'no phone, no card number and no frame are posted');

// ═══════════════════════════════════════════════════════════════════════════
// 7. THE RE-SCAN UPLOAD RUNS UNDER #550'S CEILING TOO.
//
//    WHAT THIS ASSERTION USED TO SAY, and why it changed. It recorded that
//    `api()` set NO client-side timeout at all — no AbortController, no
//    AbortSignal — so the ceiling on a card upload was whatever the browser
//    chose. That was true when this file was written and it was the number
//    #550 was asking for. #550 has since landed and DECLARED one
//    (CARD_UPLOAD_TIMEOUT_MS = 75 s > the server's 2 x 22 s), so the fact is
//    no longer an absence and the test is no longer a note to another PR.
//
//    WHAT IT ASSERTS NOW IS THIS PR'S OWN EXPOSURE TO IT. The returning
//    worker's card re-scan does not add an upload path — it reuses
//    handleOshaPhoto — and that is the whole reason it was built on step 1
//    rather than on a new surface. This holds that shut: if the re-scan ever
//    grows its own upload, it would be the one card call on the page with no
//    ceiling, and a man re-scanning a flagged card would be the one man left
//    staring at a dead screen. #550's own gate cannot see that, because it
//    checks the number and the call site, not who reaches them.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 7. the re-scan inherits the declared upload ceiling --');

ok(/const CARD_UPLOAD_TIMEOUT_MS = \d+;/.test(src),
  'checkin.html declares a card-upload ceiling (#550)');

const uploadCalls = (src.match(/api\(\s*'\/checkin\/upload-osha'/g) || []).length;
ok(uploadCalls === 1,
  `the card upload has exactly ONE call site (found ${uploadCalls}) — the re-scan reuses it`);

const uploadAt = src.indexOf("api('/checkin/upload-osha'");
const uploadCall = src.slice(uploadAt, src.indexOf('oshaData = res;', uploadAt));
ok(/CARD_UPLOAD_TIMEOUT_MS\s*\)/.test(uploadCall),
  'and that call site passes the ceiling');

// The re-scan reaches the camera through the SAME control, so it cannot
// acquire a different upload without this count changing.
const handlerCalls = (src.match(/handleOshaPhoto\(/g) || []).length;
ok(handlerCalls >= 2,
  `handleOshaPhoto is the single card-capture entry point (${handlerCalls} references)`);
ok(!/api\([^)]*upload-osha[^)]*\)\s*;?\s*$/m.test(startCardRescanSrc()),
  'startCardRescan uploads nothing of its own — it opens the shared card step');

function startCardRescanSrc() { return extractFn('function startCardRescan()'); }

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
