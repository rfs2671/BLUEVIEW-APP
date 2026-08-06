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

/** Human copy for a failed load, so screens don't invent their own wording. */
export function fetchFailureMessage(status) {
  if (status === 'offline') return 'Unavailable offline — reconnect to load this.';
  if (status === 'error') return 'Could not load. Pull to refresh or try again.';
  return '';
}
