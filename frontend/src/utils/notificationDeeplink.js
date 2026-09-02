/**
 * THE ROUTE A NOTIFICATION OPENS.
 *
 * The server stores a `deeplink` on every inbox row — `/project/{id}`,
 * `/project/{id}/trades`, sometimes with a `#section` fragment
 * (lib/notifications_inbox._build_deeplink). Nothing consumed it: every row in
 * NotificationsList was a Pressable that marked itself read and stopped there,
 * so a notification telling an admin to go fix a worker's missing trade
 * stranded him on the screen he was already looking at.
 *
 * TWO RULES, AND BOTH ARE ABOUT NOT LYING TO THE ROUTER.
 *
 * THE FRAGMENT IS DROPPED. expo-router matches the whole string, so
 * `router.push('/project/P1#predictions')` does not match `/project/[id]` —
 * it matches nothing, and the tap does nothing. An anchored deeplink still has
 * a screen; this returns the screen. (Scroll-into-view for the anchor is a
 * separate job nothing does today, and pretending otherwise by pushing the
 * hash would cost the navigation as well.)
 *
 * ONLY IN-APP PATHS. A deeplink is server-supplied data that arrives on a
 * screen and is handed straight to the router. Anything that is not a rooted
 * in-app path — an absolute URL, a protocol-relative `//host`, a bare relative
 * segment — yields no destination rather than a way out of the app.
 *
 * A null return is a legitimate answer, not an error: most notifications are
 * FYI, and a row with no destination must still mark itself read.
 */

export function notificationRoute(deeplink) {
  if (typeof deeplink !== 'string') return null;
  const raw = deeplink.trim();
  // Rooted in-app path only. '//host/x' is protocol-relative, not a path.
  if (!raw.startsWith('/') || raw.startsWith('//')) return null;
  const route = raw.split('#')[0].trim();
  // '/' is the app root, not somewhere a notification meaningfully sends you.
  if (route.length <= 1) return null;
  return route;
}

export default notificationRoute;
