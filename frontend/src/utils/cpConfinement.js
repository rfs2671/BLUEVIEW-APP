/**
 * WHERE A CP IS ALLOWED TO BE — AND THE ROUTES THAT WERE LEFT OUT OF IT.
 *
 * ── THE OUTAGE THIS FILE IS THE FIX FOR ─────────────────────────────────────
 *
 * From 2026-09-01 to 2026-09-03 no CP could sign anything. He tapped Sign,
 * watched a spinner for about two seconds, and arrived on his home screen. He
 * was not declining consent — HE WAS NEVER ASKED. Eight hours of server logs
 * carry 33 GETs of /api/esra-consent and zero POSTs: the consent route mounted,
 * read the agreement, and was redirected away before it painted a word of it.
 *
 * RouteGuard confines a CP to a fixed set of paths and sends him to /logbooks
 * from anywhere else. `/consent` was added to the app in #308 and pushed to by
 * all thirteen signing screens in b1f1ec5; it was never added HERE. So the
 * consent gate pushed him onto a route this rule immediately bounced him off,
 * and his own home screen was the destination — which is why it read as a
 * spinner and a homecoming rather than as an error.
 *
 * IT WAS A CLOSED LOOP. /consent is the only screen that can record a consent,
 * so being bounced off it meant `ensure()` could never return true again.
 *
 * ── WHY THE RULE IS A MODULE AND NOT FOUR LINES IN THE LAYOUT ───────────────
 *
 * Because that is how it stayed invisible for two days. The list lived inline
 * in app/_layout.jsx as a boolean expression inside an effect inside a
 * component that renders null. Nothing in the suite could execute it, nothing
 * enumerated it, and the thirteen screens that started pushing to /consent had
 * no reason to look at it. The mount smoke mounts /consent STANDALONE and was
 * green throughout: the route renders perfectly well on its own and only dies
 * under the guard, as an owner rather than a CP. The site-device arm was moved
 * out for the same reason and after the same class of bug — see
 * inspectorConfinement.js.
 *
 * Pure and enumerable, so cpConfinement.test.cjs can ask about every route a
 * CP is expected to reach rather than reading a regex over the layout.
 *
 * ── AND A SECOND OMISSION OF THE SAME SHAPE, FOUND LOOKING FOR ONE ──────────
 *
 * `/settings` was matched EXACTLY. app/settings.jsx renders a "Notification
 * Preferences" card to every role — it is not behind the isAdmin gate the
 * company cards are behind — and it pushes to `/settings/notifications`. So a
 * CP who tapped it was bounced to /logbooks, silently, the same way. Fixed
 * here rather than left for the next outage to find.
 *
 * MATCHING IS ON PATH SEGMENTS, NOT ON `startsWith`. `/logbooks` was a raw
 * startsWith, which would also have admitted a route called /logbooks-archive.
 * A subpath match requires the boundary, so this is looser where it was wrongly
 * tight and tighter where it was loosely right.
 *
 * ── THE CONFINEMENT IS STILL A CONFINEMENT ──────────────────────────────────
 *
 * A CP still cannot reach admin routes, the owner console, the dashboard,
 * projects, workers or reports. Nothing here widens it beyond the screens the
 * application itself sends him to.
 */

export const CP_HOME = '/logbooks';

/**
 * The paths a CP may occupy.
 *
 * `subpaths` admits everything beneath the path as well, on a SEGMENT boundary
 * — `/settings` matches `/settings/notifications` but never `/settings-admin`.
 */
export const CP_ALLOWED = [
  // An editor per log type lives under here.
  { path: '/logbooks', subpaths: true },
  { path: '/documents', subpaths: false },
  // SUBPATHS, because settings.jsx shows every role a Notification Preferences
  // card that pushes to /settings/notifications, which pushes on to
  // /settings/notifications/project/<id>. Exact-matching this bounced a CP off
  // his own notification settings — the consent bug's smaller twin.
  { path: '/settings', subpaths: true },
  { path: '/login', subpaths: false },
  // THE AGREEMENT TO SIGN ELECTRONICALLY. Not a place he navigates to — the
  // signing gate pushes him here, and it is the only screen that can clear the
  // gate. Omitting it did not hide a screen, it made every signature on the
  // platform impossible. See the header.
  { path: '/consent', subpaths: false },
];

/**
 * A CP with no company assignment: every company-gated endpoint 403s, so he is
 * held tighter still and told to ask his admin.
 *
 * /consent IS ON THIS LIST TOO. The consent record is keyed on the person and
 * not on a company — POST /api/esra-consent takes the subject from the token —
 * so it is one of the few things he can still usefully do, and bouncing him off
 * it would reproduce the same silent block for the narrower population.
 */
export const CP_NO_COMPANY_SAFE = ['/logbooks', '/login', '/settings', '/consent'];

/** Does `path` equal `base`, or sit beneath it on a segment boundary? */
const under = (path, base) => path === base || path.startsWith(`${base}/`);

/** May a CP be on this path? */
export function cpPathAllowed(pathname) {
  const path = typeof pathname === 'string' ? pathname : '';
  return CP_ALLOWED.some(({ path: p, subpaths }) => (subpaths ? under(path, p) : path === p));
}

/** May a CP with no company_id be on this path? */
export function cpNoCompanyPathAllowed(pathname) {
  const path = typeof pathname === 'string' ? pathname : '';
  return CP_NO_COMPANY_SAFE.some((p) => under(path, p));
}

export default cpPathAllowed;
