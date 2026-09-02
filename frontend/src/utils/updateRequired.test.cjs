/**
 * WHAT A REFUSED DEVICE SHOWS THE PERSON HOLDING IT.
 *
 * clientVersion.test.cjs pins the ADVISORY half: a strip of grey text that
 * says "this version is out of date", explicitly non-blocking, because a
 * compliance app that stops a CP filing his day because its own update
 * pipeline fell behind has substituted one failure for a worse one.
 *
 * This is the other half, and it is a different situation, not a stronger
 * version of the same one. The server has REFUSED — 426 on every authenticated
 * request. Nothing the CP does will work. He is not being warned about a
 * future problem; he is looking at an app where every screen fails. The choice
 * is not "block or don't block", it is "one sentence that names the cause, or
 * a dozen screens each showing its own generic error".
 *
 * SO THE STATE IS ENTERED ONLY BY AN ACTUAL 426, never by a guess. No version
 * arithmetic runs here at all — the client does not decide it is too old, it
 * is TOLD, by the one party that knows what the floor is. That keeps the
 * fail-open property whole across the wire: the server ships with no floor,
 * therefore no 426 is ever sent, therefore this state is unreachable today.
 *
 * Run:  node src/utils/updateRequired.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── the module under test ──────────────────────────────────────────────────
const modPath = path.join(UTILS, 'updateRequired.js');
ok(fs.existsSync(modPath), 'src/utils/updateRequired.js exists');
if (!fs.existsSync(modPath)) {
  console.log(`\n${passed} passed, ${failed} failed`);
  console.log('FAILURES ABOVE');
  process.exit(1);
}

const src = fs.readFileSync(modPath, 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export /gm, '');
// eslint-disable-next-line no-new-func
const mod = new Function(`${src}; return {
  parseUpdateRequired, noteUpdateRequired, isUpdateRequired,
  getUpdateRequired, resetUpdateRequired, registerUpdateRequiredHandler,
};`)();

const {
  parseUpdateRequired, noteUpdateRequired, isUpdateRequired,
  getUpdateRequired, resetUpdateRequired, registerUpdateRequiredHandler,
} = mod;

console.log('\n-- nothing is required until the server says so --');

resetUpdateRequired();
ok(isUpdateRequired() === false, 'a fresh app is not in the update-required state');
ok(getUpdateRequired() === null, '...and has no detail to render');

console.log('\n-- only a 426 counts --');

for (const [err, why] of [
  [null, 'a null error'],
  [undefined, 'an undefined error'],
  [{}, 'an error with no response — a network failure'],
  [{ response: { status: 401 } }, 'a 401, which means log in again'],
  [{ response: { status: 403 } }, 'a 403, which means the wrong role'],
  [{ response: { status: 429 } }, 'a 429, which means slow down'],
  [{ response: { status: 500 } }, 'a 500, which means the server broke'],
  [{ response: { status: 404 } }, 'a 404'],
  [{ response: { status: 200 } }, 'a success'],
]) {
  ok(parseUpdateRequired(err) === null,
    `silent for ${why} — a client that guesses "too old" from any failure `
    + 'will eventually blank itself out over an unrelated outage');
}

const real = {
  response: {
    status: 426,
    data: {
      detail: {
        error: 'client_update_required',
        minimum_supported: '1.3.0',
        reported: '1.2.0',
      },
    },
  },
};
const parsed = parseUpdateRequired(real);
ok(parsed !== null, 'a 426 is recognised');
ok(parsed && parsed.minimumSupported === '1.3.0', '...and carries the floor');
ok(parsed && parsed.reported === '1.2.0', '...and what this install reported');

console.log('\n-- a 426 with a body this client did not expect --');

// An older/newer server, a proxy that rewrote the body, an HTML error page.
// The STATUS is the signal; the body is decoration. Refusing to enter the
// state because a field is missing would leave the cascade of opaque errors
// in place, which is the thing being fixed.
for (const [body, why] of [
  [undefined, 'no body at all'],
  [{}, 'an empty body'],
  [{ detail: 'Upgrade Required' }, 'a plain-string detail from FastAPI'],
  [{ detail: {} }, 'an empty detail object'],
  ['<html>426</html>', 'an HTML error page from a proxy'],
]) {
  const p = parseUpdateRequired({ response: { status: 426, data: body } });
  ok(p !== null, `still recognised with ${why} — the status is the signal`);
  ok(p && p.minimumSupported === null && p.reported === null,
    `...and reports unknown rather than inventing values (${why})`);
}

console.log('\n-- it latches, and it notifies exactly once --');

resetUpdateRequired();
let calls = 0;
let seen = null;
registerUpdateRequiredHandler((d) => { calls += 1; seen = d; });

noteUpdateRequired(real);
ok(isUpdateRequired() === true, 'a 426 puts the app in the update-required state');
ok(calls === 1, 'the handler fired');
ok(seen && seen.minimumSupported === '1.3.0', '...with the detail');

// Every subsequent request 426s too. The point of latching is that the app
// shows ONE sentence, not one per in-flight request.
noteUpdateRequired(real);
noteUpdateRequired(real);
ok(calls === 1,
  'the 2nd and 3rd 426 do not re-fire — a screen with six parallel fetches '
  + 'must not raise six notices');
ok(isUpdateRequired() === true, 'and the state stays set');

console.log('\n-- a non-426 never sets it --');

resetUpdateRequired();
noteUpdateRequired({ response: { status: 500 } });
noteUpdateRequired({ response: { status: 401 } });
noteUpdateRequired(new Error('Network Error'));
ok(isUpdateRequired() === false,
  'THE FAIL-OPEN PROPERTY, CLIENT SIDE. The server ships with no floor, so no '
  + '426 is ever sent, so this screen is unreachable — an outage must not be '
  + 'able to reach it by accident');

registerUpdateRequiredHandler(null);
resetUpdateRequired();

console.log('\n-- the wiring --');

const api = fs.readFileSync(path.join(UTILS, 'api.js'), 'utf8');

ok(/noteUpdateRequired/.test(api),
  'the response interceptor routes errors through it — one place, so no call '
  + 'site has to know what 426 means');
ok(/X-Client-Version/.test(api),
  'and every request still reports the version the server judges');

// The 401 branch calls clearAuth(). A 426 that fell through it would log the
// user out on top of everything else, and the sentence he needs would be
// replaced by a login screen that also cannot work.
const handler = api.slice(api.indexOf('apiClient.interceptors.response.use'));
const four26 = handler.indexOf('426');
const clear = handler.indexOf('clearAuth');
ok(four26 !== -1, 'the response interceptor knows about 426');
ok(four26 === -1 || clear === -1 || !/status === 426[\s\S]{0,200}clearAuth/.test(handler),
  'a 426 does not clear auth — being out of date is not being logged out');

console.log('\n-- the surface --');

const noticePath = path.join(FRONTEND, 'src', 'components', 'UpdateRequiredNotice.jsx');
ok(fs.existsSync(noticePath), 'there is a component that says it in words');

if (fs.existsSync(noticePath)) {
  const notice = fs.readFileSync(noticePath, 'utf8');
  ok(/isUpdateRequired|registerUpdateRequiredHandler/.test(notice),
    'it reads the latched state rather than doing its own version arithmetic');
  ok(/update/i.test(notice) && /Text/.test(notice),
    'it renders text naming the cause');
  // ANCHORED TO THE CALL AND THE IMPORT, not to the bare word. A first draft
  // used /isBehindMinimum/ and failed on the COMMENT in the component
  // explaining why it does not call it — the assertion matched its own prose,
  // which is a documented recurring fault in this codebase.
  ok(!/isBehindMinimum\s*\(/.test(notice) && !/from\s+'.*clientVersion'/.test(notice),
    'it does NOT judge the install itself — the advisory strip owns that, and '
    + 'two components reaching opposite verdicts about the same phone is the '
    + 'confusion this whole area exists to end');

  const layout = fs.readFileSync(path.join(FRONTEND, 'app', '_layout.jsx'), 'utf8');
  ok(/UpdateRequiredNotice/.test(layout),
    'and it is mounted at the root, above every screen — otherwise each screen '
    + 'still shows its own opaque error and nothing has been fixed');
}

console.log('\n-- the advisory strip is untouched --');

const marker = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'BuildMarker.jsx'), 'utf8');
ok(!/Modal|blocking|disabled/.test(marker),
  'BuildMarker stays non-blocking — a warning about a future problem and a '
  + 'server refusing every request are different situations and get different '
  + 'treatment');
ok(!/noteUpdateRequired|isUpdateRequired/.test(marker),
  '...and does not reach into the refusal state');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
