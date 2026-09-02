/**
 * WHAT IS ALLOWED TO DESTROY A DEVICE'S CREDENTIALS.
 *
 * A gate tablet is not a phone. Nobody on the jobsite knows its password —
 * it was typed once by an admin at setup — so `clearAuth()` on a site device
 * is not "sign in again", it is "this tablet is finished until somebody
 * drives out with the credentials". And the tablet is the thing a DOB
 * inspector is handed. It holds a full offline cache of submitted logbooks,
 * plans and documents (docCache, projectCache, the cache-first list render on
 * every /site screen), all of it approved and downloaded long before the
 * session ran out.
 *
 * TWO ONE-LINE RULES USED TO THROW ALL OF THAT AWAY:
 *
 *   • api.js: ANY 401 from ANY request called clearAuth(). The Dropbox file
 *     listing raises 401 with "No refresh token. Please reconnect Dropbox."
 *     — a statement about DROPBOX'S token — and it silently deleted the
 *     user's own. Nothing on screen changed, because AuthContext only
 *     re-reads auth on mount, so the device looked fine right up until the
 *     next cold boot.
 *
 *   • AuthContext: a locally-decoded `exp` in the past threw, and the throw
 *     reached the outer catch, which calls clearAuth(). That runs BEFORE any
 *     network call, so being offline never protected it. Day 31, no signal,
 *     the tablet deleted its own credentials and then could not reach a
 *     single one of the records still on its disk.
 *
 * THE GOVERNING SENTENCE: an expired token grants nothing, so destroying it
 * protects nothing, and the cache it takes with it is the only thing left to
 * show. Expiry is a reason to stop FETCHING, not to stop READING.
 *
 * So credentials come off the disk on exactly one finding — the server, asked
 * directly, refused a token that is still live by its own clock. Every other
 * 401 is either corroborated first or ignored. Everything in here is a pure
 * function of its arguments so both call sites decide the same way and
 * sessionSurvival.test.cjs can enumerate the whole matrix.
 */

// ── Reading a token without trusting it ────────────────────────────────────
//
// This is the ONE decoder. AuthContext used to carry its own copy; two
// implementations of "is this session dead" that disagree would have the
// interceptor keeping a token the provider had already given up on.

export const decodeJwtPayload = (token) => {
  try {
    if (typeof token !== 'string') return null;
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => `%${`00${c.charCodeAt(0).toString(16)}`.slice(-2)}`)
        .join(''),
    );
    const payload = JSON.parse(json);
    return payload && typeof payload === 'object' ? payload : null;
  } catch (_e) {
    return null;
  }
};

export const tokenExpiresAtMs = (token) => {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== 'number' || !Number.isFinite(payload.exp)) {
    return null;
  }
  return payload.exp * 1000;
};

/**
 * True ONLY when the token says so itself.
 *
 * A token that will not parse, or that carries no `exp`, answers FALSE — not
 * because it is trustworthy but because "I cannot tell" must never resolve to
 * "throw it away". That conflation is the entire class of bug above.
 */
export const isTokenExpired = (token, nowMs = Date.now()) => {
  const expiresAt = tokenExpiresAtMs(token);
  if (expiresAt === null) return false;
  return expiresAt <= nowMs;
};

// ── The 401 verdict ────────────────────────────────────────────────────────

export const KEEP = 'keep';         // this 401 says nothing about our session
export const VERIFY = 'verify';     // ask the identity endpoint, then decide
export const REJECTED = 'rejected'; // the server refused a live token: log out

// The identity endpoint is the corroboration. A 401 from it is not evidence
// about the session, it IS the session's verdict.
const IDENTITY_PATH = '/api/auth/me';

// Endpoints that do not carry a session judgement at all. A wrong password at
// the login form answers 401 (server.py:5769) and used to wipe whatever was
// stored — which on a shared tablet is somebody else's live session.
const UNAUTHENTICATED_PATHS = ['/api/auth/login', '/api/auth/register'];

const pathOf = (url) => String(url || '').split('?')[0];

export const isIdentityRequest = (url) => pathOf(url).endsWith(IDENTITY_PATH);

export const isUnauthenticatedRequest = (url) => {
  const p = pathOf(url);
  return UNAUTHENTICATED_PATHS.some((known) => p.endsWith(known));
};

/**
 * KEEP / VERIFY / REJECTED for one 401, decided from the request and the
 * token on disk. Never performs I/O — the caller owns the corroborating call.
 */
export const unauthorizedVerdict = ({ url, token, nowMs = Date.now() } = {}) => {
  if (isUnauthenticatedRequest(url)) return KEEP;
  if (!token) return KEEP;                       // nothing stored to destroy

  // THE TABLET IN THE INSPECTOR'S HANDS. We already know this token is dead;
  // the server agreeing costs us the cache and tells us nothing new.
  if (isTokenExpired(token, nowMs)) return KEEP;

  if (isIdentityRequest(url)) return REJECTED;   // asked directly, refused
  return VERIFY;                                 // one 401 is not a verdict
};

// ── The token the server hands back ────────────────────────────────────────
//
// There is no refresh route; the server re-issues in a response header on any
// authenticated request whose token has started to age (server.py
// REISSUED_TOKEN_HEADER). Lowercase, because axios normalises header names on
// native and the fetch adapter on web does not always.

export const REFRESHED_TOKEN_HEADER = 'x-refreshed-token';

const headerValue = (headers, name) => {
  if (!headers) return null;
  if (typeof headers.get === 'function') return headers.get(name);
  const wanted = name.toLowerCase();
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === wanted) return headers[key];
  }
  return null;
};

/**
 * The token to store, or null.
 *
 * REFUSES ANYTHING IT CANNOT VERIFY IS AN IMPROVEMENT. A value that is not a
 * JWT, or one that is already expired, is dropped rather than written over a
 * token that is currently working — a replayed or truncated response must not
 * be able to strand a device that was fine.
 */
export const refreshedTokenFrom = (response, nowMs = Date.now()) => {
  try {
    const raw = headerValue(response && response.headers, REFRESHED_TOKEN_HEADER);
    if (!raw || typeof raw !== 'string') return null;
    const token = raw.trim();
    if (!token) return null;
    const expiresAt = tokenExpiresAtMs(token);
    if (expiresAt === null) return null;         // not a JWT, or undatable
    if (expiresAt <= nowMs) return null;         // never adopt a dead token
    return token;
  } catch (_e) {
    return null;
  }
};
