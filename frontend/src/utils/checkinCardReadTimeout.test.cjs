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

// ANCHORED ON THE NAME, NOT THE SIGNATURE. The full parameter list was the
// anchor until `timeoutMs` was added to it, at which point this file stopped
// running at all — a hard crash, which at least is loud. The name is the part
// that identifies the function; the parameters are the part that changes.
const apiSrc = extractFn('async function api(');

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

  // ── THE TWO iPhones, REPRODUCED ────────────────────────────────────────
  //
  // FOLLOW THE STRING. `Request failed` is produced in exactly two places and
  // BOTH are on the `!res.ok` branch — a body that is not JSON, and an empty
  // detail. A fetch REJECTION never produces it; that path carries the
  // browser's own wording. So the two rows recorded on 2026-09-15 got a
  // RESPONSE: a non-2xx with a non-JSON body, which on this stack is the
  // platform edge's HTML error page after the app failed to answer in time.
  //
  // It carried no code, so the card step could not classify it and the worker
  // was left with raw English and a photo he could not retake.
  ok(garbage && garbage.code === 'GATEWAY_NO_ANSWER',
    'an edge 502 with an HTML body is classified, not left codeless — this is '
    + 'the exact shape the two iPhone rows recorded');
  const edge504 = await thrown({
    ok: false, status: 504, json: async () => { throw new Error('html'); },
  });
  ok(edge504 && edge504.code === 'GATEWAY_NO_ANSWER', 'a 504 is classified too');
  // AND IT DOES NOT STEAL A CODE THE SERVER SENT. CARD_READ_UNAVAILABLE is
  // itself a 502; the server's own answer must win.
  const serverSaid = await thrown({
    ok: false,
    status: 502,
    json: async () => ({ detail: { code: 'CARD_READ_UNAVAILABLE', message: 'x' } }),
  });
  ok(serverSaid && serverSaid.code === 'CARD_READ_UNAVAILABLE',
    'a code the server sent is never overwritten by the gateway fallback');
  // AND A 4xx IS NOT A GATEWAY. A 400 is an answer about the request.
  const badRequest = await thrown({
    ok: false, status: 400, json: async () => ({ detail: 'Bad image' }),
  });
  ok(badRequest && badRequest.code === undefined,
    'a 4xx is an answer, not a missing one, and stays codeless');

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
  // THE INVARIANT IS "DID AN ANSWER ARRIVE", NOT "IS IT THE TIMEOUT CODE".
  //
  // This block used to read `every non-timeout entry has retake === false`,
  // which was true when CARD_READ_TIMEOUT was the only no-answer case. It is
  // not any more: the client's own ceiling and a dropped connection are both
  // "no answer arrived" and both must go back to the camera. Written as the
  // rule, so the next code added is classified rather than grandfathered.
  const NO_ANSWER = [
    'CARD_READ_TIMEOUT', 'CLIENT_TIMEOUT', 'CLIENT_NETWORK', 'GATEWAY_NO_ANSWER',
  ];
  NO_ANSWER.forEach((code) => {
    const v = CARD_CODES[code];
    ok(!!v && v.retake === true,
      `${code} means no answer arrived, so it puts the worker back at the camera`);
  });
  const answered = Object.entries(CARD_CODES).filter(([c]) => !NO_ANSWER.includes(c));
  ok(answered.length > 0 && answered.every(([, v]) => v.retake === false),
    'a card failure the provider ANSWERED sends the worker to manual entry');
  // EVERY entry is classified. A code with no `retake` at all is falsy, which
  // reads as "manual entry" — a silent default on the branch that decides
  // whether the worker gets a way back to the camera.
  ok(Object.values(CARD_CODES).every((v) => typeof v.retake === 'boolean'),
    'every card code states its retake disposition explicitly');
  ok(/t\(known\.msg\)/.test(handler),
    'the message comes from the page translations, not from the server');

  // ── 2b. THE CLIENT CEILING EXCEEDS THE SERVER BUDGET ────────────────────
  //
  // THE DEFECT, FROM THE DATA: two iPhone gate failures on 2026-09-15 recorded
  // `Request failed` rather than the server's own sentence, i.e. something
  // gave up before the handler answered while a paid vision call was still
  // running.
  //
  // BOTH NUMBERS ARE READ OUT OF THE TWO FILES AND COMPARED. Hardcoding either
  // side would let a future server budget increase pass this test while
  // re-creating the exact race — the invariant is the relationship, not the
  // values. (See: "assert the invariant, not both sides".)
  const attemptTimeout = parseFloat(
    (serverSrc.match(/^OSHA_VISION_ATTEMPT_TIMEOUT = ([\d.]+)/m) || [])[1]);
  const attempts = parseInt(
    (serverSrc.match(/^OSHA_VISION_ATTEMPTS = (\d+)/m) || [])[1], 10);
  const clientMs = parseInt(
    (src.match(/const CARD_UPLOAD_TIMEOUT_MS = (\d+);/) || [])[1], 10);
  ok(Number.isFinite(attemptTimeout) && Number.isFinite(attempts),
    'the server budget is readable from server.py');
  ok(Number.isFinite(clientMs),
    'the gate page declares CARD_UPLOAD_TIMEOUT_MS instead of leaving the '
    + 'ceiling to whatever the browser happens to default to');
  const serverMs = attemptTimeout * attempts * 1000;
  ok(clientMs > serverMs,
    `the client ceiling (${clientMs} ms) outlives the server budget `
    + `(${attempts} x ${attemptTimeout} s = ${serverMs} ms)`);
  // AND NOT BY A HAIR. A margin under 10 s is a tie in practice once the
  // upload of the image itself and the platform edge are counted.
  ok(clientMs - serverMs >= 10000,
    `the margin is ${(clientMs - serverMs) / 1000}s, enough for the upload `
    + 'and the edge, not just for the model call');

  // THE CEILING IS ACTUALLY APPLIED TO THE CARD UPLOAD, not merely declared.
  ok(/api\('\/checkin\/upload-osha'[\s\S]{0,900}?CARD_UPLOAD_TIMEOUT_MS\)/.test(src),
    'the card upload passes CARD_UPLOAD_TIMEOUT_MS to api()');

  // AND api() HONOURS IT. The shipped function is run with a fetch that never
  // settles; the abort must surface as a tagged, retry-able error rather than
  // as a promise that hangs for as long as the browser feels like.
  const apiWithTimeout = new Function(
    'API_BASE', 'fetch', 'AbortController', 'setTimeout', 'clearTimeout',
    `${apiSrc}\nreturn api;`,
  )('', (url, opts) => new Promise((resolve, reject) => {
    // A fetch that only ever settles by being aborted — the hung provider.
    opts.signal.addEventListener('abort', () => {
      const e = new Error('The operation was aborted.');
      e.name = 'AbortError';
      reject(e);
    });
  }), AbortController, setTimeout, clearTimeout);

  let aborted = null;
  try {
    await apiWithTimeout('/checkin/upload-osha', 'POST', { image: 'x' }, 30);
  } catch (e) {
    aborted = e;
  }
  ok(aborted instanceof Error, 'a hung request rejects instead of hanging forever');
  ok(aborted && aborted.network === true,
    'a client timeout is a TRANSPORT failure — the server said nothing');
  ok(aborted && aborted.code === 'CLIENT_TIMEOUT',
    'a client timeout carries a code, so the card step never falls through to '
    + 'the raw-English branch that showed the empty string');
  ok(!!CARD_CODES[aborted && aborted.code],
    'the code api() produces on its own timeout is one the page answers');

  // A PLAIN TRANSPORT FAILURE IS TAGGED TOO, and differently — we did not stop
  // waiting, the connection went.
  const apiThatDrops = new Function('API_BASE', 'fetch', `${apiSrc}\nreturn api;`)(
    '', async () => { throw new TypeError('Load failed'); });
  let dropped = null;
  try {
    await apiThatDrops('/checkin/upload-osha', 'POST', { image: 'x' });
  } catch (e) {
    dropped = e;
  }
  ok(dropped && dropped.code === 'CLIENT_NETWORK',
    'a dropped connection is tagged CLIENT_NETWORK, not left codeless');
  ok(dropped && dropped.network === true,
    'a dropped connection is still marked as a transport failure');

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

  // EVERY msg THE MAP NAMES MUST EXIST IN BOTH LANGUAGES. Derived from the map
  // rather than listed here, so a code added next week is covered by this
  // assertion on the day it is added. ELEVEN OF ELEVEN recorded gate failures
  // are lang='es'; a key that exists only in English falls back through t() to
  // English, silently, for the only people who actually hit this screen.
  const msgKeys = [...new Set(Object.values(CARD_CODES).map((v) => v.msg))];
  ok(msgKeys.length > 0, `the map names ${msgKeys.length} translation keys`);
  msgKeys.forEach((key) => {
    const enHas = new RegExp(`\\n\\s*${key}:\\s*'[^']{40,}'`).test(en);
    const esHas = new RegExp(`\\n\\s*${key}:\\s*'[^']{40,}'`).test(es);
    ok(enHas, `English has a real ${key} sentence`);
    ok(esHas, `Spanish has a real ${key} sentence`);
  });

  // AND EVERY "NO ANSWER" SENTENCE NAMES THE RETRY, in both languages. The
  // outage's message named no way out at all; a retry the copy does not
  // mention is a retry the worker does not know he has.
  NO_ANSWER.forEach((code) => {
    const key = (CARD_CODES[code] || {}).msg;
    if (!key) return;
    const enS = (en.match(new RegExp(`${key}:\\s*'([^']*)'`)) || [])[1] || '';
    const esS = (es.match(new RegExp(`${key}:\\s*'([^']*)'`)) || [])[1] || '';
    ok(/photo/i.test(enS), `English ${key} points at the photo area again`);
    ok(/foto/i.test(esS), `Spanish ${key} points at the photo area again`);
  });

  // ── 4. AND NO MESSAGE ENDS IN A DANGLING REASON ─────────────────────────
  //
  // `t('readCardFailed') + ': ' + reason` is the shape that printed
  // "Could not read card: " for four days. It survives ONLY on the fallback
  // branch, for a failure this page does not recognise, where `reason` is at
  // least a real browser message.
  //
  // THIS ASSERTION WAS PASSING ON THE EMPTY STRING. It anchored on
  // `e.code === 'CARD_READ_TIMEOUT'`, a literal that has never appeared in
  // checkin.html — the page branches through a MAP, not an equality. Both
  // indexOf calls returned -1, `slice` produced '', and the regex tested
  // nothing. A green tick for a check that never ran. It now anchors on the
  // `if (known) {` block, which is the real coded-failure branch, and FAILS
  // when that anchor is missing instead of passing quietly.
  const knownAt = handler.indexOf('if (known) {');
  ok(knownAt >= 0, 'the coded-failure branch is present (anchor for the next check)');
  const knownBranch = knownAt < 0
    ? ' SENTINEL: anchor missing, this must fail'
    : handler.slice(knownAt, matchBalancedIn(handler, handler.indexOf('{', knownAt)) + 1);
  ok(knownAt >= 0 && !/\+ ': ' \+ reason/.test(knownBranch),
    'a coded failure never interpolates the server reason into the worker\'s message');
  // AND IT REACHES THE WORKER IN HIS OWN LANGUAGE, not the server's English.
  ok(knownAt >= 0 && /showError\(t\(known\.msg\)/.test(knownBranch),
    'a coded failure shows copy this page owns, in the worker\'s language');
  // The raw reason is not thrown away — it goes where an operator can read it.
  ok(knownAt >= 0 && /reportGateFailure\(known\.kind/.test(knownBranch),
    'the raw reason still reaches the gate telemetry under the code\'s own kind');
  // AND THE CAMERA IS GIVEN BACK when the disposition says so. This is the
  // difference between "try again" and a photo the worker cannot replace.
  ok(knownAt >= 0 && /if \(known\.retake\) resetCardCameraZone\(\);/.test(knownBranch),
    'a no-answer failure puts the camera zone back so there is a way to retry');

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
