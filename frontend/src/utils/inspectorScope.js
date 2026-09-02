/**
 * THE INSPECTOR'S SCOPE — one definition, used by the route gate.
 *
 * Operator ruling: the gate tablet's scope is DOCUMENTS and LOGBOOKS. It
 * exists so a DOB inspector visiting site can read the record.
 *
 * Inspector Mode (src/context/InspectorLockContext.jsx) is what delivers that
 * ruling on a device the superintendent also uses: he taps "Hand to Inspector
 * (read-only)" on /site and hands the tablet over, and the gate in
 * app/_layout.jsx confines the app until he taps "Exit Inspector Mode".
 *
 * THE GATE USED TO NAME ONE PATH. It read
 *
 *     inspectorLocked && pathname !== '/site/logbooks' && pathname !== '/login'
 *
 * so /site/documents was bounced like any write screen — and /site with it, so
 * the site home carrying the Documents tile never rendered either. An inspector
 * holding the tablet could not reach the plans, permits or agreements at all,
 * on the device that exists so he can read them. The list below is the ruled
 * scope, stated once.
 *
 * WHAT IS DELIBERATELY ABSENT. /site/daily-logs and /site/checkins are WRITE
 * paths — the first files the daily log through dailyLogsAPI.create/update and
 * captures the superintendent and competent-person signatures, the second
 * records approve / send-home decisions on expired-SST check-ins through
 * checkinsAPI.review. They belong to the superintendent, not the inspector, and
 * the lock is what separates the two uses of one tablet. Adding a path here
 * hands it to whoever is holding the device, so add nothing that writes.
 *
 * EXACT PATHS, NOT PREFIXES. A prefix rule would admit any future child route
 * of an allowed screen without anyone deciding it should be in scope.
 */

/** Where a refused path lands: the read-only tab that carries "Exit Inspector Mode". */
export const INSPECTOR_LANDING = '/site/logbooks';

/** The ruled scope, plus /login so a logout is still possible. */
export const INSPECTOR_ALLOWED_PATHS = Object.freeze([
  '/site/logbooks',
  '/site/documents',
  '/login',
]);

/**
 * May a device under Inspector Mode be on this path?
 *
 * `pathname` is what expo-router's usePathname() reports — no query string. A
 * trailing slash is the same route, and anything that is not a non-empty string
 * is refused rather than treated as the root.
 */
export function isInspectorAllowedPath(pathname) {
  if (typeof pathname !== 'string' || pathname === '') return false;
  const normalized = pathname.replace(/\/+$/, '') || '/';
  return INSPECTOR_ALLOWED_PATHS.includes(normalized);
}

export default {
  INSPECTOR_LANDING,
  INSPECTOR_ALLOWED_PATHS,
  isInspectorAllowedPath,
};
