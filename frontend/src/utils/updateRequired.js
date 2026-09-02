/**
 * THE SERVER HAS REFUSED THIS INSTALL, AND THE APP SAYS SO ONCE.
 *
 * `clientVersion.js` answers "does this install look old" and the BuildMarker
 * strip renders that as a line of grey text, deliberately non-blocking: a
 * compliance app that stops a CP filing his day because its own update
 * pipeline fell behind has substituted one failure for a worse one.
 *
 * This is a different situation, not a stronger version of that one. A 426
 * means the backend is refusing every authenticated request. Nothing the CP
 * does will work. He is not being warned about a future problem; he is holding
 * a phone where every screen fails for a reason none of them can name. The
 * choice here is not "block or don't block" — the app is already blocked. It
 * is "one sentence that names the cause, or twelve screens each showing its
 * own generic error".
 *
 * THIS MODULE NEVER GUESSES. No version arithmetic runs here at all: the state
 * is entered only by an actual 426 from the server, which is the only party
 * that knows what the floor is. That is what keeps the fail-open property
 * whole across the wire — the server ships with no floor configured, so no 426
 * is ever sent, so this screen is unreachable today. An unrelated outage, a
 * proxy, a 500 storm must not be able to reach it by accident.
 *
 * IT LATCHES. Once refused, every in-flight request is also refused; a screen
 * with six parallel fetches must raise one notice, not six.
 */

// { minimumSupported, reported } once refused, null until then.
let _state = null;
let _handler = null;

/**
 * The refusal detail from an axios error, or null when this is not a refusal.
 *
 * THE STATUS IS THE SIGNAL; the body is decoration. An older server, a proxy
 * that rewrote the response, or an HTML error page still means "refused" —
 * declining to enter the state because a field is missing would leave the
 * cascade of opaque errors in place, which is the thing being fixed. Unknown
 * fields come back null rather than invented.
 */
export function parseUpdateRequired(err) {
  if (!err || !err.response || err.response.status !== 426) return null;
  const data = err.response.data;
  const detail = data && typeof data === 'object' ? data.detail : null;
  const body = detail && typeof detail === 'object' ? detail : {};
  return {
    minimumSupported: typeof body.minimum_supported === 'string' && body.minimum_supported
      ? body.minimum_supported
      : null,
    reported: typeof body.reported === 'string' && body.reported
      ? body.reported
      : null,
  };
}

/** Called by the api.js response interceptor for every failure. No-op unless
 *  the failure is a 426, and no-op again once the state is already latched. */
export function noteUpdateRequired(err) {
  if (_state) return;
  const parsed = parseUpdateRequired(err);
  if (!parsed) return;
  _state = parsed;
  if (typeof _handler === 'function') {
    try { _handler(parsed); } catch (_e) { /* never let the error path throw */ }
  }
}

export function isUpdateRequired() {
  return _state !== null;
}

export function getUpdateRequired() {
  return _state;
}

/** The root notice registers here so it can re-render the moment the first
 *  426 lands, rather than waiting for whatever the next navigation is. */
export function registerUpdateRequiredHandler(fn) {
  _handler = typeof fn === 'function' ? fn : null;
}

/** Tests only — and a deliberate escape hatch is better than a test that pokes
 *  at module internals it cannot see. Nothing in the app calls this: there is
 *  no recovery from a refusal except installing a newer build, which restarts
 *  the process anyway. */
export function resetUpdateRequired() {
  _state = null;
}

export default {
  parseUpdateRequired,
  noteUpdateRequired,
  isUpdateRequired,
  getUpdateRequired,
  registerUpdateRequiredHandler,
  resetUpdateRequired,
};
