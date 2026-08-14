/**
 * OFFLINE vs EMPTY — the single discriminator every screen should use.
 *
 * The app-wide bug this exists to kill: every screen's fetch catch used to do
 * `setThings([])`, so a dead zone rendered the SAME confident empty state as a
 * genuinely empty server response ("No Documents", "No Submitted Logs", "0
 * workers on site"). On the Inspector Mode screen that is worse than an error —
 * it asserts to a DOB inspector that no records exist.
 *
 * Rule: a fetch failure is either
 *   • OFFLINE / unreachable  -> say so, or serve cache. NEVER an empty state.
 *   • a real server response -> the empty state is honest.
 *
 * How we tell them apart: axios rejects with NO `error.response` when the
 * request never reached a server (DNS/socket/timeout/airplane mode). If a
 * response object exists, the server answered — that is not an offline error.
 */

export function isOfflineError(error) {
  if (!error) return false;
  // A server answered (4xx/5xx) — not an offline failure.
  if (error.response) return false;
  const code = error.code || '';
  if (code === 'ERR_NETWORK' || code === 'ECONNABORTED' || code === 'ETIMEDOUT') return true;
  const msg = String(error.message || '').toLowerCase();
  if (msg.includes('network') || msg.includes('timeout') || msg.includes('failed to fetch')) return true;
  // axios rejection with a request but no response == never answered.
  if (error.request) return true;
  return false;
}

/**
 * Normalizes a fetch attempt into the three states a screen actually needs.
 * `status` is 'ok' | 'offline' | 'error'.
 *
 *   const r = await settleFetch(() => api.getThings());
 *   if (r.status === 'ok') setThings(r.data);
 *   else setFetchState(r.status);   // render <OfflineNotice mode={...}/>
 */
export async function settleFetch(fn) {
  try {
    return { status: 'ok', data: await fn(), error: null };
  } catch (error) {
    return {
      status: isOfflineError(error) ? 'offline' : 'error',
      data: null,
      error,
    };
  }
}

/**
 * What actually happened, in words the reader can act on.
 *
 * THE THIRD TIME THIS SESSION. A screen caught a failure, logged the real
 * error to a console nobody reads, and rendered one fixed sentence — so a 500,
 * a 403, a 404 and a client-side throw were indistinguishable. It cost a round
 * trip on the assign-project failure, on the silent gate reroute, and again on
 * the worker detail screen, where the server was returning a pydantic
 * ValidationError the whole time.
 *
 * NOT A STACK TRACE. Four outcomes a person can act on:
 *   offline        reconnect
 *   not found      it is gone, stop retrying
 *   no permission  ask someone with access
 *   server error   the server's own `detail`, which names the condition
 *
 * The server's `detail` is surfaced ONLY when it is a plain string. This
 * codebase's convention is that a refusal carries a machine CODE and the
 * client owns the wording (see the `finalize` namespace), and those codes are
 * dicts — rendering `{"code": "..."}` at a person would be worse than the
 * generic line. A dict falls through to the generic sentence.
 */
export function failureDetail(status, error, subject = 'this') {
  if (status === 'offline') {
    return `Unavailable offline — reconnect to load ${subject}.`;
  }
  const code = error?.response?.status;
  if (code === 404) {
    return `Not found. ${subject.charAt(0).toUpperCase()}${subject.slice(1)} may have been deleted.`;
  }
  if (code === 403) {
    return 'You do not have permission to view this. Ask an admin who does.';
  }
  if (code === 401) {
    return 'Your session has expired. Sign in again.';
  }
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return code ? `Server error (${code}): ${detail}` : detail;
  }
  if (code) {
    return `The server could not return this (${code}). Try again, and report it if it keeps happening.`;
  }
  // No response at all, and not classified as offline — a client-side throw.
  const msg = String(error?.message || '').trim();
  return msg
    ? `Could not load — ${msg}`
    : 'Could not load. Pull to refresh or try again.';
}

/**
 * Human copy for a failed load, so screens don't invent their own wording.
 *
 * SUPERSEDED BY failureDetail, and it has no callers left. It reads only the
 * STATUS, so a 500, a 403 and a 404 all produce the same sentence — which is
 * the defect failureDetail exists to fix. Kept rather than deleted because it
 * is an exported util and removing an export is a separate decision; do not
 * reach for it in new code.
 */
export function fetchFailureMessage(status) {
  if (status === 'offline') return 'Unavailable offline — reconnect to load this.';
  if (status === 'error') return 'Could not load. Pull to refresh or try again.';
  return '';
}
