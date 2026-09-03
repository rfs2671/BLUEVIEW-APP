/**
 * WHAT A 401 IS ALLOWED TO DESTROY, AND WHAT AN EXPIRY IS ALLOWED TO DESTROY.
 *
 * Two rules used to be one line each, and both were wrong in the same
 * direction — they threw away the only copy of something.
 *
 *   api.js:169  — ANY 401 from ANY request called clearAuth(). The Dropbox
 *                 file listing raises 401 with "No refresh token. Please
 *                 reconnect Dropbox." That is a statement about DROPBOX'S
 *                 token, and it silently wiped the user's own. Nothing on
 *                 screen changed, because AuthContext only re-reads auth on
 *                 mount — so the device looked fine until the next cold boot,
 *                 which is when it landed on a login screen instead.
 *
 *   AuthContext — a locally-decoded expiry threw, and the throw reached the
 *                 outer catch that calls clearAuth(). A tablet 30 days offline
 *                 deleted its own credentials and then could not reach any of
 *                 the logbooks, plans and documents still sitting on its disk.
 *
 * THE GOVERNING SENTENCE IS THAT AN EXPIRED TOKEN GRANTS NOTHING, so deleting
 * it protects nothing, and on a gate tablet the cached record is the only
 * thing a DOB inspector can be shown. Credentials are destroyed on exactly one
 * finding: the server, asked directly, refused a token that is still live by
 * its own clock. Every other 401 is corroborated first or ignored.
 *
 * Run:  node src/utils/sessionSurvival.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function eq(actual, expected, label) {
  ok(Object.is(actual, expected), `${label} (got ${JSON.stringify(actual)})`);
}

function load(rel) {
  const file = path.join(__dirname, rel);
  if (!fs.existsSync(file)) {
    ok(false, `src/utils/${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}

const S = load('sessionSurvival.js');
const {
  decodeJwtPayload, tokenExpiresAtMs, isTokenExpired,
  REFRESHED_TOKEN_HEADER, refreshedTokenFrom,
  KEEP, VERIFY, REJECTED, unauthorizedVerdict,
} = S;

{
  const required = {
    decodeJwtPayload, tokenExpiresAtMs, isTokenExpired,
    refreshedTokenFrom, unauthorizedVerdict,
  };
  let missing = 0;
  for (const [n, f] of Object.entries(required)) {
    const present = typeof f === 'function';
    ok(present, `sessionSurvival exports ${n}`);
    if (!present) missing += 1;
  }
  for (const [n, v] of Object.entries({ KEEP, VERIFY, REJECTED, REFRESHED_TOKEN_HEADER })) {
    const present = typeof v === 'string' && v.length > 0;
    ok(present, `sessionSurvival exports ${n}`);
    if (!present) missing += 1;
  }
  if (missing) { console.log(`\n  ${passed} passed, ${failed} failed`); process.exit(1); }
}

// ── Fixtures ───────────────────────────────────────────────────────────────
const NOW = 1_800_000_000_000;               // a fixed "now" in ms
const HOUR = 3600 * 1000;
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const jwtOf = (payload) => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`;

const LIVE = jwtOf({ sub: 'dev1', site_mode: true, exp: (NOW + 20 * 24 * HOUR) / 1000 });
const DEAD = jwtOf({ sub: 'dev1', site_mode: true, exp: (NOW - 24 * HOUR) / 1000 });
const NO_EXP = jwtOf({ sub: 'dev1' });

// ── Reading the token ──────────────────────────────────────────────────────
console.log('\n── the token reads the same everywhere ──');
{
  eq(decodeJwtPayload(LIVE).sub, 'dev1', 'decodes the payload');
  eq(decodeJwtPayload('garbage'), null, 'garbage decodes to null, never throws');
  eq(decodeJwtPayload(null), null, 'null decodes to null');
  eq(decodeJwtPayload(''), null, 'empty string decodes to null');
  eq(decodeJwtPayload('a.b'), null, 'a two-segment string is not a JWT');

  eq(tokenExpiresAtMs(LIVE), NOW + 20 * 24 * HOUR, 'exp comes back in milliseconds');
  eq(tokenExpiresAtMs(NO_EXP), null, 'a payload with no exp has no expiry');

  eq(isTokenExpired(DEAD, NOW), true, 'a token past its exp is expired');
  eq(isTokenExpired(LIVE, NOW), false, 'a token inside its exp is not expired');
  ok(isTokenExpired(NO_EXP, NOW) === false,
    'NO EXP IS NOT AN EXPIRY. "I cannot tell" must not resolve to "throw it '
    + 'away" — that is the whole class of bug being fixed here');
  ok(isTokenExpired('garbage', NOW) === false,
    'an unreadable token is not a proven-dead token either');
}

// ── The 401 verdict ────────────────────────────────────────────────────────
console.log('\n── one 401 is not a verdict ──');
{
  eq(
    unauthorizedVerdict({ url: '/api/projects/p1/dropbox-files', token: LIVE, nowMs: NOW }),
    VERIFY,
    'A 401 FROM AN ORDINARY ENDPOINT IS CORROBORATED, NEVER ACTED ON. This '
    + 'is the Dropbox 401 that silently logged people out',
  );
  eq(
    unauthorizedVerdict({ url: '/api/auth/me', token: LIVE, nowMs: NOW }),
    REJECTED,
    'the identity endpoint IS the corroboration — a 401 there is the server '
    + 'refusing this exact token, and that is a real logout',
  );
  eq(
    unauthorizedVerdict({ url: '/api/auth/login', token: null, nowMs: NOW }),
    KEEP,
    'a wrong password at the login form is not a session verdict',
  );
  eq(
    unauthorizedVerdict({ url: '/api/auth/login', token: LIVE, nowMs: NOW }),
    KEEP,
    'and it stays not-a-verdict when a session happens to be stored',
  );
  eq(
    unauthorizedVerdict({ url: '/api/auth/register', token: null, nowMs: NOW }),
    KEEP,
    'nor is anything on the unauthenticated routes',
  );
  eq(
    unauthorizedVerdict({ url: '/api/logbooks/project/p1/submitted', token: null, nowMs: NOW }),
    KEEP,
    'with nothing stored there is nothing to destroy',
  );
}

console.log('\n── an expired token is never destroyed ──');
{
  eq(
    unauthorizedVerdict({ url: '/api/logbooks/project/p1/submitted', token: DEAD, nowMs: NOW }),
    KEEP,
    'THE TABLET IN THE INSPECTOR\'S HANDS. The token is dead, the server '
    + 'says so, and clearing it would take the cached logbooks with it',
  );
  eq(
    unauthorizedVerdict({ url: '/api/auth/me', token: DEAD, nowMs: NOW }),
    KEEP,
    'even from the identity endpoint: a 401 on a token we already know is '
    + 'expired tells us nothing we did not know, and costs the cache',
  );
  eq(
    unauthorizedVerdict({ url: '/api/anything', token: NO_EXP, nowMs: NOW }),
    VERIFY,
    'a token we cannot date is corroborated, not assumed dead and not '
    + 'assumed alive',
  );
}

// ── Adopting the re-issued token ───────────────────────────────────────────
console.log('\n── the token the server hands back ──');
{
  const res = (headers) => ({ headers });
  eq(refreshedTokenFrom(res({ [REFRESHED_TOKEN_HEADER]: LIVE })), LIVE,
    'a live token in the header is adopted');
  eq(refreshedTokenFrom(res({ 'X-Refreshed-Token': LIVE })), LIVE,
    'HEADER LOOKUP IS CASE-INSENSITIVE. axios lowercases on native and the '
    + 'fetch adapter on web does not always');
  eq(refreshedTokenFrom(res({})), null, 'no header, nothing to adopt');
  eq(refreshedTokenFrom(undefined), null, 'no response at all, nothing to adopt');
  eq(refreshedTokenFrom(res({ [REFRESHED_TOKEN_HEADER]: '' })), null,
    'an empty header is not a token');
  eq(refreshedTokenFrom(res({ [REFRESHED_TOKEN_HEADER]: 'not-a-jwt' })), null,
    'a header that is not a JWT is refused rather than written to disk');
  eq(refreshedTokenFrom(res({ [REFRESHED_TOKEN_HEADER]: DEAD }), NOW), null,
    'A DEAD TOKEN IS NEVER ADOPTED. A proxy replaying an old response must '
    + 'not be able to downgrade a device that is currently fine');
  eq(REFRESHED_TOKEN_HEADER, 'x-refreshed-token',
    'the header name matches the one the backend sets (server.py '
    + 'REISSUED_TOKEN_HEADER), compared lowercase');
}

// ── The shipped call sites ─────────────────────────────────────────────────
console.log('\n── the rules are the ones that actually run ──');
{
  const apiSrc = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
  const interceptor = apiSrc.slice(apiSrc.indexOf('interceptors.response.use'));

  ok(/unauthorizedVerdict|handleUnauthorized/.test(apiSrc),
    'api.js routes its 401 through this module rather than deciding inline');

  const arm = interceptor.slice(interceptor.indexOf('401'));
  ok(!/^\s*await clearAuth\(\);\s*$/m.test(arm.slice(0, 400)),
    'THE UNCONDITIONAL WIPE IS GONE. `if (401) await clearAuth()` is the '
    + 'defect in one line');

  ok(/refreshedTokenFrom|adoptRefreshedToken/.test(apiSrc),
    'api.js adopts the re-issued token off the success path — a header '
    + 'nobody reads moves no clock');

  const ctxSrc = fs.readFileSync(
    path.join(__dirname, '..', 'context', 'AuthContext.js'), 'utf8');
  // CODE ONLY. The comment that explains the removed throw quotes it, and a
  // grep that cannot tell the two apart would pass forever once someone
  // deleted the comment and reinstated the line.
  const ctxCode = ctxSrc
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((l) => !/^\s*(\/\/|\*)/.test(l))
    .join('\n');

  ok(/isTokenExpired|sessionSurvival/.test(ctxCode),
    'AuthContext judges expiry through this module, so the tablet and the '
    + 'interceptor cannot disagree about whether the session is dead');
  ok(!/throw new Error\('Token expired'\)/.test(ctxCode),
    'AND IT NO LONGER THROWS ON IT. That throw is what reached the outer '
    + 'catch and called clearAuth() on a tablet holding the only copy');
  ok(!/const decodeToken\s*=/.test(ctxCode),
    'AND ITS PRIVATE JWT DECODER IS GONE. Two decoders is two answers to '
    + '"is this session dead", and the one that wins is whichever ran first');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
