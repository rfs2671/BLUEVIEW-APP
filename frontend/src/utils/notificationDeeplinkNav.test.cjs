/**
 * A NOTIFICATION THAT NAMES A DESTINATION MUST REACH IT.
 *
 * Two independent halves of one defect, and either alone is enough to strand
 * the reader:
 *
 *   THE TAP WENT NOWHERE. NotificationsList.jsx rendered every row inside a
 *   Pressable whose onPress was `handleMarkRead(item)` and nothing else. The
 *   file's own header promised "Mark-read on click + deeplink follow"; the
 *   follow was never written, and the component did not so much as import
 *   useRouter. Every notification in the app was a dead card.
 *
 *   THE DESTINATION DID NOT EXIST. The checkin_needs_trade dispatch in
 *   server.py passed deeplink_anchor="workforce", so the stored deeplink read
 *   `/project/{id}#workforce`. The string "workforce" had ZERO matches
 *   anywhere under frontend/ — no screen, no section, no anchor. Even once the
 *   tap navigated, it would have landed on the project page beside a fragment
 *   nothing renders.
 *
 * So the notification told an admin to go fix a worker record and then handed
 * him a route to nowhere. This file pins BOTH halves, and pins them from the
 * two sources that actually disagree: the backend that writes the deeplink and
 * the frontend that has to resolve it.
 *
 * WHY THE FRAGMENT IS STRIPPED rather than honoured: expo-router has no
 * fragment routing. `router.push('/project/P1#predictions')` does not match
 * `/project/[id]` — the hash is part of the matched string. A deeplink that
 * carries an anchor must still open its SCREEN.
 *
 * Run:  node src/utils/notificationDeeplinkNav.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');
const APP = path.join(FRONTEND, 'app');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const eq = (a, b, label) => ok(
  a === b,
  `${label}${a === b ? '' : ` — got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`}`,
);

// ── A. The resolver, EXECUTED ───────────────────────────────────────────────
// Not grepped. The rule that decides where a tap lands is run against the
// strings the backend actually stores.
console.log('\nnotificationDeeplink.js — the stored deeplink becomes a route');

const RESOLVER = path.join(__dirname, 'notificationDeeplink.js');
let notificationRoute = null;
if (!fs.existsSync(RESOLVER)) {
  ok(false, 'src/utils/notificationDeeplink.js exists (nothing turns a stored '
    + 'deeplink into a route the router can take)');
} else {
  const { loadEsm } = require('./esmHarness.cjs');
  ({ notificationRoute } = loadEsm('src/utils/notificationDeeplink.js'));
  ok(typeof notificationRoute === 'function', 'it exports notificationRoute');
}

if (typeof notificationRoute === 'function') {
  eq(notificationRoute('/project/P1/trades'), '/project/P1/trades',
    'a plain route passes through unchanged');
  eq(notificationRoute('/project/P1#predictions'), '/project/P1',
    'the fragment is stripped — expo-router matches paths, not hashes, so an '
    + 'anchored deeplink still opens its screen');
  eq(notificationRoute('/project/P1'), '/project/P1',
    'a deeplink with no anchor is already a route');

  // A notification is server-supplied data. It never becomes an escape hatch
  // out of the app.
  eq(notificationRoute('https://example.com/phish'), null,
    'an absolute URL is refused — a notification cannot navigate off-app');
  eq(notificationRoute('//example.com/phish'), null,
    'a protocol-relative URL is refused too');
  eq(notificationRoute('project/P1'), null, 'a relative path is refused');
  eq(notificationRoute(''), null, 'empty string yields no destination');
  eq(notificationRoute(null), null, 'null yields no destination');
  eq(notificationRoute(undefined), null, 'undefined yields no destination');
  eq(notificationRoute(42), null, 'a non-string yields no destination');
  eq(notificationRoute('#workforce'), null,
    'a bare fragment is not a destination');
}

// ── B. The tap follows it ───────────────────────────────────────────────────
console.log('\nNotificationsList.jsx — the row navigates');

const list = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'NotificationsList.jsx'), 'utf8',
);

ok(/import \{ useRouter \} from 'expo-router';/.test(list),
  'the component imports useRouter — it had no navigation of any kind');
ok(/const router = useRouter\(\);/.test(list),
  'and holds a router');
ok(/import \{ notificationRoute \} from '\.\.\/utils\/notificationDeeplink';/.test(list),
  'the destination is resolved by the shared rule, not re-derived inline');

// The press handler, read as a unit. Mark-read is not enough; a row that only
// marks read is precisely the defect.
const openFn = (() => {
  const start = list.indexOf('const handleOpen');
  if (start < 0) return '';
  const end = list.indexOf('const handleMarkAllRead', start);
  return end < 0 ? list.slice(start) : list.slice(start, end);
})();
ok(openFn.length > 0,
  'a single press handler exists (handleOpen) — mark-read AND follow');
ok(/notificationRoute\(item\??\.deeplink\)/.test(openFn),
  'it resolves item.deeplink, the field the server already stores');
ok(/router\.push\(/.test(openFn),
  'and pushes it');
ok(/handleMarkRead\(item\)/.test(openFn),
  'mark-read is kept — following a deeplink must not lose the read receipt');

// A notification with no deeplink still marks read and does not crash.
ok(/if \(to\) router\.push\(to\);/.test(openFn)
  || /to && router\.push\(to\)/.test(openFn),
  'navigation is conditional — a notification with no destination still marks '
  + 'read instead of pushing undefined');

// Both render paths (inline preview and full list) go through it.
const presses = list.match(/onPress=\{\(\) => handle(Open|MarkRead)\(item\)\}/g) || [];
ok(presses.length === 2 && presses.every((p) => /handleOpen/.test(p)),
  'BOTH modes — inline preview and full list — use the navigating handler '
  + `(found: ${JSON.stringify(presses)})`);

// ── C. The generated destination resolves ───────────────────────────────────
// The half a frontend-only test can never see: the backend writes the string,
// the frontend has to find a screen for it.
console.log('\nserver.py — checkin_needs_trade names a screen that exists');

const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');

/** Every dispatch_notification(...) block that carries this kind. */
function dispatchesForKind(kind) {
  const needle = `kind="${kind}"`;
  const out = [];
  let i = server.indexOf(needle);
  while (i >= 0) {
    let block = server.slice(i, i + 2000);
    const next = block.indexOf('dispatch_notification(', 1);
    if (next > 0) block = block.slice(0, next);
    out.push(block);
    i = server.indexOf(needle, i + needle.length);
  }
  return out;
}

const blocks = dispatchesForKind('checkin_needs_trade');
ok(blocks.length === 2,
  `both checkin_needs_trade dispatch sites are found (got ${blocks.length})`);

/**
 * Rebuild the deeplink exactly as lib/notifications_inbox._build_deeplink
 * does, then resolve it against the shipped routes.
 */
function screenFileFor(route) {
  // /project/P1/trades -> app/project/[id]/trades.jsx
  const parts = route.split('/').filter(Boolean);
  if (parts[0] !== 'project') return null;
  const rest = parts.slice(2);
  const base = path.join(APP, 'project', '[id]');
  if (rest.length === 0) return `${base}.jsx`;
  return path.join(base, `${rest.join(path.sep)}.jsx`);
}

blocks.forEach((block, n) => {
  const site = `dispatch #${n + 1}`;
  const sub = /deeplink_path="([^"]+)"/.exec(block);
  const anchor = /deeplink_anchor="([^"]+)"/.exec(block);

  ok(!!(sub || anchor), `${site}: carries a destination at all`);

  const route = sub ? `/project/{id}/${sub[1]}` : '/project/{id}';
  const file = screenFileFor(route);
  ok(!!file && fs.existsSync(file),
    `${site}: ${route} resolves to a real screen`
    + `${file && !fs.existsSync(file) ? ` (no such file: ${path.relative(REPO, file)})` : ''}`);

  // An anchor is only honest if SOMETHING in the app renders it. "workforce"
  // rendered nowhere, which is how a deeplink to nothing shipped.
  //
  // SHIPPED SOURCE ONLY. The first cut of this walk searched all of frontend/
  // and PASSED on the unmodified tree — because THIS FILE is under frontend/
  // and names the anchor in its own prose. A guard that its own text satisfies
  // proves nothing, so *.test.* is excluded.
  if (anchor) {
    const a = anchor[1];
    const hits = [];
    (function walk(dir) {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
        const p = path.join(dir, e.name);
        if (e.isDirectory()) { walk(p); continue; }
        if (/\.test\.(cjs|js|jsx)$/.test(e.name)) continue;
        if (/\.(jsx?|cjs|ts|tsx)$/.test(e.name)
          && fs.readFileSync(p, 'utf8').includes(a)) hits.push(p);
      }
    }(APP));
    (function walk(dir) {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
        const p = path.join(dir, e.name);
        if (e.isDirectory()) { walk(p); continue; }
        if (/\.test\.(cjs|js|jsx)$/.test(e.name)) continue;
        if (/\.(jsx?|cjs|ts|tsx)$/.test(e.name)
          && fs.readFileSync(p, 'utf8').includes(a)) hits.push(p);
      }
    }(path.join(FRONTEND, 'src')));
    ok(hits.length > 0,
      `${site}: the anchor "${a}" is rendered somewhere in shipped frontend `
      + 'source (an anchor no screen defines is a deeplink to nothing)');
  }

  ok(!/deeplink_anchor="workforce"/.test(block),
    `${site}: does not point at "workforce" — the string has zero matches in `
    + 'frontend/, so it was never a destination');
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
