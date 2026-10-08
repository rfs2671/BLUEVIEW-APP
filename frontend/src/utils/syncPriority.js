/**
 * WHO GETS THE LINK WHEN AN INSPECTOR IS STANDING THERE.
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. It has
 * one radio and two jobs that both want it: the inspector-facing read happening
 * NOW, and the background fill that makes the dead zone survivable later.
 *
 * ── THE DEFECT THIS EXISTS FOR, MEASURED ───────────────────────────────────
 *
 * `SiteManifestSync` (app/_layout.jsx) mounts the moment the project id
 * resolves — on open — and `setupSiteManifestSync` fired its first run
 * IMMEDIATELY. That run downloads up to DOWNLOADS_PER_RUN = 500 files
 * sequentially; on 588 Thomas the queue is ~105 MB, including a 31.7 MB and a
 * 24.9 MB plan set. The site logbooks screen's own list request was issued into
 * that, and the two shared one jobsite uplink. The list did not merely load
 * slowly: it loaded slowly BECAUSE the device was busy pre-loading documents
 * nobody had asked for.
 *
 * ── WHY NOT SIMPLY TURN THE FILL OFF ───────────────────────────────────────
 *
 * Because the fill IS the device. A gate tablet that holds nothing is a tablet
 * that shows an inspector nothing the first time the cellar kills the signal,
 * and the operator's ruling is explicit that the offline guarantee is the
 * product. Nothing here changes WHETHER anything is fetched. It changes WHO
 * GOES FIRST.
 *
 * ── AND NOT A DELAY, EITHER ────────────────────────────────────────────────
 *
 * "Wait fifteen seconds before filling" is a guess about how long a list takes,
 * and a guess is wrong on both sides: too short and it still competes, too long
 * and a tablet nobody touches sits idle on a good link. So the foreground READ
 * claims this gate for exactly as long as it is actually reading, and the fill
 * waits on the claim — the real event, not a stand-in for it.
 *
 * ── THE CAP IS THE PART THAT CANNOT BE LEFT OUT ────────────────────────────
 *
 * A gate is a deadlock waiting to be written. A screen that unmounts mid-read,
 * a promise that never settles, a claim leaked by a thrown error: any of them
 * would stop the tablet filling FOR EVER, and nothing on the device would say
 * so until an inspector asked for a document in a cellar. So `awaitQuiet` takes
 * a timeout and ALWAYS resolves: the fill is deferred, never cancelled. The
 * worst case of a leaked claim is one deferral's delay, not a tablet that
 * quietly stopped being a record.
 */

// The live claims. An array rather than a counter so a leak can be NAMED —
// `foregroundLabels()` is what a diagnostic prints when a fill is late, and
// "the list request never released" is a finding, while "claims = 1" is not.
let claims = [];

// Resolvers parked by awaitQuiet, drained when the last claim is released.
let waiters = [];

/**
 * Claim the link for a foreground read. Returns the release function.
 *
 * IDEMPOTENT RELEASE, because the caller releases in a `finally` and may also
 * release on an early return. Releasing twice must not drop somebody else's
 * claim.
 */
export function claimForeground(label) {
  const token = { label: String(label || 'foreground'), at: Date.now() };
  claims.push(token);
  let released = false;
  return function release() {
    if (released) return false;
    released = true;
    const i = claims.indexOf(token);
    if (i >= 0) claims.splice(i, 1);
    if (claims.length === 0) {
      const pending = waiters;
      waiters = [];
      for (const settle of pending) {
        try { settle('quiet'); } catch (_e) { /* one bad waiter is not the rest */ }
      }
    }
    return true;
  };
}

/** How many foreground reads are in flight. */
export function foregroundClaims() {
  return claims.length;
}

/** What they are, for a diagnostic that has to name a leak. */
export function foregroundLabels() {
  return claims.map((c) => c.label);
}

/**
 * Wait until no foreground read is in flight, or until `timeoutMs` — whichever
 * comes first. ALWAYS resolves, and the resolution says WHICH:
 *
 *   'idle'     nothing was claimed; the caller never waited at all
 *   'quiet'    the last claim was released
 *   'timeout'  the cap fired. The caller PROCEEDS. See the note above.
 */
export function awaitQuiet(timeoutMs) {
  if (claims.length === 0) return Promise.resolve('idle');
  const ms = Number(timeoutMs);
  return new Promise((resolve) => {
    let done = false;
    let timer = null;
    const settle = (why) => {
      if (done) return;
      done = true;
      if (timer) { clearTimeout(timer); timer = null; }
      resolve(why);
    };
    if (Number.isFinite(ms) && ms > 0) {
      timer = setTimeout(() => {
        const i = waiters.indexOf(settle);
        if (i >= 0) waiters.splice(i, 1);
        settle('timeout');
      }, ms);
      // ── NOT `unref`ed, AND THAT WAS A REAL BUG FOR ONE COMMIT ────────────
      //
      // It looked like good hygiene: "a deferral must never hold a device
      // awake on its own account." What it actually does on Node — where this
      // module's own gate is tested — is let the process exit with the timer
      // pending, so `awaitQuiet` NEVER RESOLVES and the fill waiting on it
      // never runs. A timer that can be skipped is not a cap, and a cap is the
      // only thing standing between a leaked claim and a tablet that stopped
      // filling. Eight to twenty seconds of a pending timer is not a battery
      // problem on a mains-powered tablet bolted to a gate.
    }
    waiters.push(settle);
  });
}

/** Test seam. Not called by the app: a leaked claim between two test cases
 *  would make the next one's assertion about deferral pass for the wrong
 *  reason. */
export function __resetSyncPriority() {
  claims = [];
  const pending = waiters;
  waiters = [];
  for (const settle of pending) {
    try { settle('quiet'); } catch (_e) { /* ignored */ }
  }
}

export default {
  claimForeground,
  foregroundClaims,
  foregroundLabels,
  awaitQuiet,
  __resetSyncPriority,
};
