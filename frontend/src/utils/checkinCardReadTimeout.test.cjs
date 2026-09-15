/**
 * THE WORKER'S HALF OF THE EMPTY-REASON OUTAGE.
 *
 * For four days (2026-09-11 18:11 UTC -> 09-15) every card upload at every
 * gate failed, and the message on the worker's phone was:
 *
 *     Could not read card: OCR processing failed:  — Take a photo of your
 *     card, or fill in the card number or expiration date below.
 *
 * The reason between the two colons is EMPTY. The server interpolated
 * `str(e)` and `str(httpx.ReadTimeout())` is the empty string. A worker read
 * that as "my card is bad", retook the photo, failed again, and left.
 *
 * TWO THINGS HAD TO CHANGE ON THIS SIDE:
 *
 *   1. `api()` could only ever throw prose. The server now sends
 *      `detail: {code, message}` for card failures, so the page can BRANCH on
 *      a machine code instead of matching English — which is what
 *      BACKEND_ERROR_MAP already has to do, and exactly what breaks the first
 *      time a sentence is reworded.
 *
 *   2. A TIMEOUT AND AN UNREADABLE CARD NEED OPPOSITE ADVICE. A timeout means
 *      the reader did not answer and the same photo very probably works on the
 *      next tap, so the worker goes back to the camera. An unreadable card
 *      means the photo is the problem, so he goes to manual entry. They were
 *      the same message.
 *
 * checkin.html has no exports and no test runner, so — following
 * checkinCardGate.test.cjs — this reads the REAL file and extracts the SHIPPED
 * api() verbatim. It is never a hand-copy of the logic.
 *
 * Run:  node src/utils/checkinCardReadTimeout.test.cjs
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

function matchBalancedIn(text, openIdx) {
  return matchBalanced(text, openIdx, '{', '}');
}

function extractFn(anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`${anchor} not found in checkin.html`);
  const open = src.indexOf('{', at);
  return src.slice(at, matchBalanced(src, open, '{', '}') + 1);
}

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── 1. THE SHIPPED api(), RUN AGAINST FAKE RESPONSES ──────────────────────

const apiSrc = extractFn('async function api(path, method = \'GET\', body = null)');

function buildApi(fakeResponse) {
  // eslint-disable-next-line no-new-func
  const make = new Function(
    'API_BASE', 'fetch',
    `${apiSrc}\nreturn api;`,
  );
  return make('', async () => fakeResponse);
}

async function thrown(fakeResponse) {
  const api = buildApi(fakeResponse);
  try {
    await api('/checkin/upload-osha', 'POST', { image: 'x' });
  } catch (e) {
    return e;
  }
  return null;
}

(async () => {
  // A STRUCTURED DETAIL: code lifted onto the error, message readable.
  const timeout = await thrown({
    ok: false,
    status: 504,
    json: async () => ({
      detail: {
        code: 'CARD_READ_TIMEOUT',
        message: 'Could not read the card — the reader did not answer.',
      },
    }),
  });
  ok(timeout instanceof Error, 'a failed card read still throws an Error');
  ok(timeout && timeout.code === 'CARD_READ_TIMEOUT',
    'the machine code reaches the caller as err.code');
  ok(timeout && timeout.status === 504, 'the HTTP status reaches the caller');
  ok(timeout && /reader did not answer/.test(timeout.message),
    'the message is the sentence, not "[object Object]"');
  // THE REGRESSION THAT WOULD HAVE BEEN INVISIBLE: `new Error(someObject)`
  // produces the literal string "[object Object]" and throws nothing.
  ok(timeout && !/object Object/.test(timeout.message),
    'a structured detail is never shown to a worker as [object Object]');

  // A PLAIN STRING DETAIL STILL WORKS. Every other endpoint on this page
  // sends one, so the change had to be additive.
  const legacy = await thrown({
    ok: false,
    status: 400,
    json: async () => ({ detail: 'Invalid check-in point' }),
  });
  ok(legacy && legacy.message === 'Invalid check-in point',
    'a plain string detail is unchanged');
  ok(legacy && legacy.code === undefined,
    'a plain string detail carries no code');

  // AND A BODY THAT IS NOT JSON AT ALL. A gateway's HTML error page must not
  // crash the card step.
  const garbage = await thrown({
    ok: false,
    status: 502,
    json: async () => { throw new Error('not json'); },
  });
  ok(garbage && garbage.message === 'Request failed',
    'an unreadable error body falls back to a real sentence');

  // ── 2. THE CARD STEP BRANCHES ON THE CODE, NOT ON PROSE ─────────────────

  const handler = extractFn('async function handleOshaPhoto(input)');

  // THE MAP IS EXTRACTED AND EVALUATED, not grepped. Every code the SERVER can
  // send must be answered here; a code with no entry falls through to
  // `readCardFailed + ': ' + reason`, which is the English-only path that
  // printed the empty string for four days.
  const mapAt = handler.indexOf('const CARD_CODES = {');
  ok(mapAt >= 0, 'the card-code map is present');
  // `{}` WHEN IT IS ABSENT, so every assertion below FAILS rather than the
  // file throwing. A test that crashes takes every later assertion with it —
  // the failure mode the CI workflow header records, where two suites had
  // never executed in CI even once because a file before them exited non-zero.
  let CARD_CODES = {};
  if (mapAt >= 0) {
    const mapEnd = matchBalancedIn(handler, handler.indexOf('{', mapAt));
    // eslint-disable-next-line no-new-func
    CARD_CODES = new Function(
      `${handler.slice(mapAt, mapEnd + 1)};\nreturn CARD_CODES;`)();
  }

  // Read the codes the SERVER declares, so the two sides cannot drift.
  const serverSrc = fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'backend', 'server.py'), 'utf8');
  const serverCodes = (serverSrc.match(/^CARD_READ_[A-Z_]+ = "([A-Z_]+)"/gm) || [])
    .map((l) => l.split('"')[1]);
  ok(serverCodes.length >= 4, `the server declares ${serverCodes.length} card codes`);
  serverCodes.forEach((code) => {
    ok(!!CARD_CODES[code], `the page answers ${code} with its own copy`);
  });

  const timeoutEntry = CARD_CODES.CARD_READ_TIMEOUT || {};
  ok(timeoutEntry.kind === 'card_ocr_timeout',
    'a timeout is reported to the gate telemetry under its own kind');
  ok(timeoutEntry.msg === 'cardReadTimeout',
    'the timeout shows its own translated sentence');
  // A TIMEOUT GOES BACK TO THE CAMERA; EVERYTHING ELSE TO MANUAL ENTRY. The
  // reader not answering is transient; a provider that is down or that read
  // the frame and could not make it out is not fixed by another photo.
  ok(timeoutEntry.retake === true,
    'a timeout puts the worker back at the camera');
  const others = Object.entries(CARD_CODES).filter(([c]) => c !== 'CARD_READ_TIMEOUT');
  ok(others.length > 0 && others.every(([, v]) => v.retake === false),
    'every non-timeout card failure sends the worker to manual entry');
  ok(/t\(known\.msg\)/.test(handler),
    'the message comes from the page translations, not from the server');

  // ── 3. THE SENTENCE EXISTS IN BOTH LANGUAGES ────────────────────────────
  //
  // The gate is bilingual by rule; a key present only in English falls back to
  // English through t(), which is a silent half-translation.
  const enAt = src.indexOf('  en: {');
  const esAt = src.indexOf('  es: {');
  ok(enAt > 0 && esAt > enAt, 'both language blocks are present');
  const en = src.slice(enAt, esAt);
  const es = src.slice(esAt, src.indexOf('\n};', esAt));
  ok(/cardReadTimeout:\s*'[^']{40,}'/.test(en),
    'English has a real cardReadTimeout sentence');
  ok(/cardReadTimeout:\s*'[^']{40,}'/.test(es),
    'Spanish has a real cardReadTimeout sentence');
  // IT MUST NAME A WAY OUT. The outage's message named none.
  //
  // `(m || [])[1] || ''` rather than `m[1]`: when the key is MISSING this
  // assertion must FAIL, not throw. A test that crashes takes every assertion
  // after it with it — the exact failure mode the CI workflow header records
  // ("the runner halts on the FIRST non-zero exit, so two files had never
  // executed in CI even once").
  const enSentence = (en.match(/cardReadTimeout:\s*'([^']*)'/) || [])[1] || '';
  const esSentence = (es.match(/cardReadTimeout:\s*'([^']*)'/) || [])[1] || '';
  ok(/photo/i.test(enSentence),
    'the English sentence tells the worker what to do next');
  ok(/foto/i.test(esSentence),
    'the Spanish sentence tells the worker what to do next');

  // ── 4. AND NO MESSAGE ENDS IN A DANGLING REASON ─────────────────────────
  //
  // `t('readCardFailed') + ': ' + reason` is the shape that printed
  // "Could not read card: " for four days. It is still used for transport
  // failures, where `reason` is a real browser message — but the TIMEOUT path,
  // where the server's reason was the empty string, no longer goes near it.
  const timeoutBranch = handler.slice(
    handler.indexOf("e.code === 'CARD_READ_TIMEOUT'"),
    handler.indexOf('return;', handler.indexOf("e.code === 'CARD_READ_TIMEOUT'")),
  );
  ok(!/\+ ': ' \+ reason/.test(timeoutBranch),
    'the timeout message never interpolates an empty server reason');

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
