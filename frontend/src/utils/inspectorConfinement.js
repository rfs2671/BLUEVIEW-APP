/**
 * WHERE A SITE DEVICE IS ALLOWED TO BE, INCLUDING BEFORE ANYTHING IS KNOWN.
 *
 * Inspector Mode is a device-local confinement: the superintendent taps "Hand
 * to Inspector (read-only)" and the tablet is held to /site/logbooks until he
 * taps out of it. The flag is persisted in AsyncStorage so it survives a
 * restart — which is the point, because the restart is when the tablet is out
 * of his hands.
 *
 * THE WINDOW THIS CLOSES. InspectorLockProvider starts `isLocked = false,
 * loading = true` and then reads the flag off disk. RouteGuard destructured
 * `isLocked` and never `loading`, so between mount and hydration it read a
 * false meaning "nothing has been read yet" as though it meant "this device is
 * not locked" — and then ACTED on it, because the site arm's
 * `router.replace('/site')` is the thing that puts the tablet on the full
 * dashboard in the first place. Every cold boot opened that window, and the
 * confinement snapped shut one tick later, which is exactly late enough to be
 * useless.
 *
 * UNKNOWN IS TREATED AS LOCKED. The two mistakes are not symmetrical: holding
 * an unlocked device on the read-only tab for one hydration tick costs a
 * frame, while showing the dashboard, the check-in roster and the daily logs
 * to whoever the tablet was handed to is the thing the feature exists to
 * prevent.
 *
 * AND THE HOLD RELEASES ITSELF. `heldForLock` records that the guard was the
 * one that moved the device, so when hydration comes back "unlocked" it puts
 * it back on the dashboard instead of stranding every tablet on logbooks after
 * every restart. Without that bookkeeping the fail-closed default would be a
 * worse bug than the hole it closes.
 *
 * Pure, so app/_layout.jsx holds no rule of its own and
 * inspectorConfinement.test.cjs can enumerate the matrix.
 */

export const LOGBOOKS = '/site/logbooks';
export const DASHBOARD = '/site';
export const LOGIN = '/login';

/**
 * @returns {{ target: string|null, heldForLock: boolean }}
 *   target — the path to replace to, or null to stay put.
 *   heldForLock — the next value of the caller's ref.
 */
export function siteDeviceTarget({
  pathname,
  isLocked = false,
  lockLoading = false,
  heldForLock = false,
} = {}) {
  const path = typeof pathname === 'string' ? pathname : '';

  // ALWAYS REACHABLE. A confinement that can also strand the superintendent
  // outside his own logout is not a UI toggle, it is a brick.
  if (path === LOGIN) return { target: null, heldForLock };

  if (lockLoading) {
    if (path === LOGBOOKS) return { target: null, heldForLock };
    return { target: LOGBOOKS, heldForLock: true };
  }

  if (isLocked) {
    // Straight to logbooks from wherever it woke — never via the dashboard,
    // which is the surface being withheld.
    return { target: path === LOGBOOKS ? null : LOGBOOKS, heldForLock: false };
  }

  // Hydration came back unlocked. Undo the hold, and ONLY the hold: a
  // superintendent who navigated to logbooks himself is left where he is.
  if (heldForLock && path === LOGBOOKS) {
    return { target: DASHBOARD, heldForLock: false };
  }

  return {
    target: path.startsWith(DASHBOARD) ? null : DASHBOARD,
    heldForLock: false,
  };
}

export default siteDeviceTarget;
