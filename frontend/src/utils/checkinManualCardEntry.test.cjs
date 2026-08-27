/**
 * THE WORKER WHOSE CARD WILL NOT READ MUST STILL GET THROUGH STEP 1.
 *
 * On 588 Thomas two men failed at the card photo and were sent back to the
 * phone screen with no message. The cause was not OCR: it was that
 * `#btnStep1Next` shipped `disabled` and the ONLY line in checkin.html that
 * ever cleared it lived inside handleOcrOutcome() — reachable only from a card
 * photo that survived FileReader, canvas compression AND the OCR round-trip.
 * The always-visible "can't photograph the card? type it instead" fields could
 * not be typed past, because nothing but a successful OCR enabled the button.
 *
 * These tests hold that shut. In order:
 *   1. the markup does not re-acquire `disabled`   (FAILS against main)
 *   2. no photo + a typed card number ADVANCES
 *   3. no photo + nothing typed is refused, and SAYS SO
 *   4. compressImage settles (null) instead of hanging (FAILS against main)
 *   5. a FileReader error reaches handleOcrOutcome(null) (FAILS against main)
 *   6. the OCR-failure toast is persistent, not 4 seconds (FAILS against main)
 *   7. every silent path reports a gate failure server-side (FAILS vs main)
 *
 * ON (2), PRECISELY: goStep() was ALWAYS correct — it has accepted typed card
 * details since the photo-optional fix, and this assertion passes against main
 * too. The defect was never goStep's logic, it was that goStep was UNREACHABLE:
 * the only control that calls it was disabled. So (2) proves the manual path
 * works and (1) proves it can be reached, and it takes both to describe the
 * incident. Do not delete (1) as redundant markup-checking — it is the half
 * that regressed.
 *
 * Harness follows checkinCardGate.test.cjs: read the REAL backend/checkin.html
 * and evaluate the shipped functions VERBATIM. Nothing here is a hand-copy of
 * the logic — if the shape changes, extraction tracks it or throws loudly.
 *
 * Run:  node src/utils/checkinManualCardEntry.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', '..', 'backend', 'checkin.html');
const src = fs.readFileSync(file, 'utf8');

// ── extraction helpers (same contract as checkinCardGate.test.cjs) ──────────
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
const tick = () => new Promise((r) => setTimeout(r, 0));

// ── a minimal DOM good enough for the extracted functions ──────────────────
function makeDom(values) {
  const els = {};
  const get = (id) => {
    if (!els[id]) {
      els[id] = {
        id,
        // A real <input>.value is ALWAYS a string, never undefined. The stub
        // has to match that or it tests a DOM the browser never produces.
        value: ((values || {})[id]) == null ? '' : String((values || {})[id]),
        innerHTML: '',
        style: {},
        disabled: false,
        classList: { add() {}, remove() {}, toggle() {} },
        focus() {},
        dataset: {},
      };
    }
    return els[id];
  };
  return {
    getElementById: get,
    querySelector: () => null,
    querySelectorAll: () => [],
    _els: els,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE MARKUP. This is the single line that caused the incident.
// ═══════════════════════════════════════════════════════════════════════════
const btnAt = src.indexOf('id="btnStep1Next"');
if (btnAt < 0) throw new Error('btnStep1Next not found in checkin.html');
const btnTagOpen = src.lastIndexOf('<button', btnAt);
const btnTag = src.slice(btnTagOpen, src.indexOf('>', btnAt) + 1);

ok(!/\bdisabled\b/.test(btnTag),
  'step-1 Next button ships WITHOUT `disabled`');

// ═══════════════════════════════════════════════════════════════════════════
// 2 + 3. THE HEADLINE. goStep(2) is the single gate; typing the card number
//        must be a real way through it, with no photo and no OCR at all.
// ═══════════════════════════════════════════════════════════════════════════
const goStepSrc = extractFn('function goStep(step)');
const hasManualSrc = extractFn('function hasManualCardDetails()');

function runGoStep({ regName, regCardNumber, regExpiration }) {
  const document = makeDom({ regName, regCardNumber, regExpiration });
  const errors = [];
  const revealed = [];
  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'showError', 't', 'oshaImage', 'oshaData',
    'getSelectedAssignment', 'noTradesConfigured', 'revealStep',
    `${hasManualSrc}\n${goStepSrc}\nreturn goStep;`,
  );
  const goStep = build(
    document,
    (m) => errors.push(m),
    (k) => k,
    null,              // oshaImage  — NO photo was ever taken
    null,              // oshaData   — OCR never produced anything
    () => null,        // getSelectedAssignment
    true,              // noTradesConfigured
    (s) => revealed.push(s),
  );
  goStep(2);
  return { errors, revealed };
}

// THE ONE THAT WOULD HAVE PREVENTED TODAY. Jose Luna's worn card: OCR read
// nothing, no usable photo, card number typed off the card face by hand.
const typed = runGoStep({ regName: 'Jose Luna', regCardNumber: 'X2L5QYKYEJ' });
ok(typed.revealed.length === 1 && typed.revealed[0] === 2,
  'no photo + typed card number -> ADVANCES to step 2');
ok(typed.errors.length === 0,
  'no photo + typed card number -> no error shown');

// Expiration alone is also enough (hasManualCardDetails accepts either).
const typedExp = runGoStep({ regName: 'Armando Shaw', regExpiration: '05/06/2031' });
ok(typedExp.revealed.length === 1 && typedExp.revealed[0] === 2,
  'no photo + typed expiration only -> ADVANCES to step 2');

// And the gate still holds: nothing photographed, nothing typed, no entry.
const empty = runGoStep({ regName: 'Jose Luna' });
ok(empty.revealed.length === 0,
  'no photo + nothing typed -> does NOT advance');
ok(empty.errors.length === 1 && empty.errors[0] === 'needCardOrManual',
  'no photo + nothing typed -> tells the worker to photograph OR type');

// A missing name is still refused, and named.
const noName = runGoStep({ regName: '   ', regCardNumber: 'X2L5QYKYEJ' });
ok(noName.revealed.length === 0 && noName.errors[0] === 'enterName',
  'blank name -> refused with enterName');

(async function main() {

// ═══════════════════════════════════════════════════════════════════════════
// 4. compressImage SETTLES. It had no onerror, so an undecodable frame left
//    the promise pending forever — the fully silent failure.
// ═══════════════════════════════════════════════════════════════════════════
const compressSrc = extractFn('function compressImage(dataUrl, maxWidth, quality)');

async function compressWith(behaviour) {
  class FakeImage {
    set src(_v) {
      setTimeout(() => {
        // NO onerror ON MAIN. Calling it unguarded would throw and abort the
        // whole run; doing nothing is exactly what main's compressImage does
        // with a bad frame — it never settles — so the race below reports the
        // hang as a clean FAIL instead of a stack trace.
        if (behaviour === 'error') {
          if (typeof this.onerror === 'function') this.onerror(new Error('decode failed'));
          return;
        }
        // A THROW INSIDE img.onload DOES NOT CRASH A BROWSER — it surfaces as an
        // uncaught error and the promise simply never settles. Node would abort
        // the process instead, which would hide the assertion. Swallowing here
        // models the browser, and "never settles" is precisely the finding the
        // race below is asserting against.
        try { this.onload(); } catch (e) { /* browser: uncaught, promise hangs */ }
      }, 0);
    }
  }
  const document = {
    createElement: () => ({
      width: 0,
      height: 0,
      getContext: () => ({ drawImage() {} }),
      toDataURL: () => (behaviour === 'throw' ? (() => { throw new Error('oom'); })() : 'data:image/jpeg;base64,OK'),
    }),
  };
  // eslint-disable-next-line no-new-func
  const build = new Function('Image', 'document', `${compressSrc}\nreturn compressImage;`);
  return build(FakeImage, document)('data:image/jpeg;base64,XX', 1600, 0.85);
}

const decodeFail = await Promise.race([
  compressWith('error'),
  new Promise((r) => setTimeout(() => r('__HUNG__'), 250)),
]);
ok(decodeFail === null, 'compressImage resolves null on decode error (does not hang)');

const throwFail = await Promise.race([
  compressWith('throw'),
  new Promise((r) => setTimeout(() => r('__HUNG__'), 250)),
]);
ok(throwFail === null, 'compressImage resolves null when the canvas throws');

const good = await compressWith('ok');
ok(typeof good === 'string' && good.startsWith('data:image/jpeg'),
  'compressImage still returns the frame on the happy path');

// ═══════════════════════════════════════════════════════════════════════════
// 5 + 6 + 7. handleOshaPhoto: every exit reaches handleOcrOutcome, tells the
//            worker, and records the failure.
// ═══════════════════════════════════════════════════════════════════════════
const handlerSrc = extractFn('async function handleOshaPhoto(input)');

async function runHandler({ mode }) {
  const outcomes = [];
  const errors = [];
  const reported = [];
  const document = makeDom({});

  class FakeFileReader {
    readAsDataURL() {
      setTimeout(() => {
        // Same reason as FakeImage: main has no reader.onerror, and a real
        // FileReader firing `error` at a handler that does not exist is a
        // no-op, not a throw. Modelling it as a no-op is what makes the
        // resulting assertion failure legible rather than a crash.
        if (mode === 'reader_error') {
          if (typeof this.onerror === 'function') this.onerror(new Error('read failed'));
          return;
        }
        // onload is async, so a throw inside it becomes a REJECTED PROMISE that
        // nobody awaits — the unhandled rejection this PR exists to remove. A
        // browser logs it and carries on; Node 20 kills the process. Attach a
        // catch so the run reaches its assertions, which is where that failure
        // is supposed to be reported.
        const r = this.onload({ target: { result: 'data:image/jpeg;base64,XX' } });
        if (r && typeof r.catch === 'function') r.catch(() => {});
      }, 0);
    }
  }

  const compressImage = async () => (mode === 'decode_null' ? null : 'data:image/jpeg;base64,OK');
  const api = async () => {
    if (mode === 'ocr_http_error') throw new Error('Vision API error: 502');
    return { name: 'Jose Luna', sst_number: 'X2L5QYKYEJ' };
  };

  // eslint-disable-next-line no-new-func
  const build = new Function(
    'document', 'FileReader', 'compressImage', 'cropImage', 'api', 't',
    'showLoading', 'hideLoading', 'showError', 'resetCardCameraZone',
    'handleOcrOutcome', 'reportGateFailure', 'showOcrResults',
    'ocrMissingCriticalFields', 'console',
    `let oshaImage = null; let oshaData = null;
     let ocrAttempts = 0; let ocrLastFailureReason = null;
     ${handlerSrc}
     return handleOshaPhoto;`,
  );
  const handleOshaPhoto = build(
    document, FakeFileReader, compressImage, async () => null, api,
    (k) => k,
    () => {}, () => {},
    (msg, persistent) => errors.push({ msg, persistent }),
    () => {},
    (missing) => outcomes.push(missing),
    (kind, detail) => reported.push({ kind, detail }),
    () => {},
    () => [],
    { error() {}, warn() {} },
  );

  // Against main the extracted handler references reportGateFailure, which
  // does not exist there — a ReferenceError inside an async onload, i.e. the
  // very unhandled rejection this PR fixes. Swallow it here so the assertions
  // below report what is missing instead of the runner dying on the first one.
  try {
    await handleOshaPhoto({ files: [{}] });
  } catch (e) { /* reported by the assertions */ }
  await tick(); await tick(); await tick();
  return { outcomes, errors, reported };
}

const readerErr = await runHandler({ mode: 'reader_error' });
ok(readerErr.outcomes.length === 1 && readerErr.outcomes[0] === null,
  'FileReader error -> handleOcrOutcome(null)');
ok(readerErr.errors.length === 1 && readerErr.errors[0].persistent === true,
  'FileReader error -> worker is told, persistently');
ok(readerErr.reported.some((r) => r.kind === 'card_file_read_failed'),
  'FileReader error -> reported as card_file_read_failed');

const decodeNull = await runHandler({ mode: 'decode_null' });
ok(decodeNull.outcomes.length === 1 && decodeNull.outcomes[0] === null,
  'undecodable frame -> handleOcrOutcome(null)');
ok(decodeNull.errors.length === 1 && decodeNull.errors[0].persistent === true,
  'undecodable frame -> worker is told, persistently');
ok(decodeNull.reported.some((r) => r.kind === 'card_image_decode_failed'),
  'undecodable frame -> reported as card_image_decode_failed');

const httpErr = await runHandler({ mode: 'ocr_http_error' });
ok(httpErr.outcomes.length === 1 && httpErr.outcomes[0] === null,
  'OCR HTTP failure -> handleOcrOutcome(null)');
ok(httpErr.errors.length === 1 && httpErr.errors[0].persistent === true,
  'OCR HTTP failure toast is PERSISTENT, not a 4-second toast');
ok(httpErr.reported.some((r) => r.kind === 'card_ocr_http_failed'),
  'OCR HTTP failure -> reported as card_ocr_http_failed');

const happy = await runHandler({ mode: 'ok' });
ok(happy.outcomes.length === 1 && Array.isArray(happy.outcomes[0]),
  'clean read still reaches handleOcrOutcome with a missing-fields array');
ok(happy.errors.length === 0 && happy.reported.length === 0,
  'clean read shows no error and reports no failure');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');

})().catch((e) => { console.error(e); process.exit(1); });
