/**
 * THE COLD-BOOT WINDOW WHERE A LOCKED TABLET IS NOT LOCKED.
 *
 * InspectorLockProvider starts `isLocked = false` and `loading = true`, then
 * reads the persisted flag off AsyncStorage. RouteGuard (app/_layout.jsx)
 * destructured `isLocked` and never `loading`, so between mount and hydration
 * it read a false that means "nothing has been read from disk yet" as though
 * it meant "this device is not locked" — and, worse, ACTED on it: the site
 * arm's `router.replace('/site')` is what puts the device on the full
 * dashboard. Every cold boot with the device in an inspector's hands opened
 * that window, and the confinement then snapped shut a frame later, which is
 * precisely late enough to be useless.
 *
 * UNKNOWN IS TREATED AS LOCKED, because the two mistakes are not symmetrical.
 * Holding an unlocked device on the read-only tab for one hydration tick costs
 * a frame; showing the dashboard, the check-in roster and the daily logs to
 * someone the superintendent handed the tablet to is the thing the feature
 * exists to prevent. The hold releases itself: `heldForLock` records that the
 * guard was the one that moved the device, so when hydration comes back
 * "unlocked" it puts it back on the dashboard rather than stranding it.
 *
 * Run:  node src/utils/inspectorConfinement.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function load(rel) {
  const file = path.join(__dirname, rel);
  if (!fs.existsSync(file)) {
    ok(false, `src/utils/${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}

const C = load('inspectorConfinement.js');
const { siteDeviceTarget, LOGBOOKS, DASHBOARD } = C;

if (typeof siteDeviceTarget !== 'function') {
  ok(false, 'inspectorConfinement exports siteDeviceTarget');
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(1);
}
ok(LOGBOOKS === '/site/logbooks', 'LOGBOOKS is the read-only tab');
ok(DASHBOARD === '/site', 'DASHBOARD is the full site home');

const at = (pathname, over = {}) => siteDeviceTarget({
  pathname, isLocked: false, lockLoading: false, heldForLock: false, ...over,
});

// ── The window ─────────────────────────────────────────────────────────────
console.log('\n── while the lock state is unknown, the device is treated as locked ──');
{
  const boot = at('/', { lockLoading: true });
  ok(boot.target === LOGBOOKS,
    'A COLD BOOT DOES NOT LAND ON THE DASHBOARD. This is the whole defect: '
    + 'the guard used to send the device to /site on a false it had not read');
  ok(boot.heldForLock === true,
    'and it records that IT moved the device, so it can undo that');

  ok(at('/site', { lockLoading: true }).target === LOGBOOKS,
    'a device already sitting on the dashboard is pulled off it');
  ok(at('/site/checkins', { lockLoading: true }).target === LOGBOOKS,
    'and off the check-in roster');
  ok(at(LOGBOOKS, { lockLoading: true }).target === null,
    'a device already on the read-only tab is not churned');
  ok(at(LOGBOOKS, { lockLoading: true }).heldForLock === false,
    'and it was not held there BY the guard, so there is nothing to release');
}

console.log('\n── and the hold releases itself ──');
{
  const released = at(LOGBOOKS, { lockLoading: false, isLocked: false, heldForLock: true });
  ok(released.target === DASHBOARD,
    'HYDRATION SAYS UNLOCKED, so the device the guard parked on logbooks '
    + 'goes to the dashboard. Without this the fix would strand every '
    + 'unlocked tablet on the read-only tab on every restart');
  ok(released.heldForLock === false, 'and the hold is spent');

  const own = at(LOGBOOKS, { lockLoading: false, isLocked: false, heldForLock: false });
  ok(own.target === null,
    'a superintendent who navigated to logbooks himself is left alone — the '
    + 'release fires only for a move the guard made');
}

console.log('\n── locked confines, unlocked does not ──');
{
  ok(at('/site', { isLocked: true }).target === LOGBOOKS, 'locked: off the dashboard');
  ok(at('/site/documents', { isLocked: true }).target === LOGBOOKS, 'locked: off documents');
  ok(at('/', { isLocked: true }).target === LOGBOOKS,
    'locked: a device that woke outside /site goes STRAIGHT to logbooks, not '
    + 'through the dashboard on the way');
  ok(at(LOGBOOKS, { isLocked: true }).target === null, 'locked: logbooks is where it stays');

  ok(at('/site').target === null, 'unlocked: the dashboard is allowed');
  ok(at('/site/daily-logs').target === null, 'unlocked: every /site tab is allowed');
  ok(at('/').target === DASHBOARD, 'unlocked: anything outside /site bounces to the dashboard');
  ok(at('/admin/users').target === DASHBOARD, 'unlocked: and admin routes certainly do');
}

console.log('\n── /login is always reachable ──');
{
  for (const state of [
    { lockLoading: true },
    { isLocked: true },
    { isLocked: false },
    { isLocked: true, heldForLock: true },
  ]) {
    ok(at('/login', state).target === null,
      `logout stays possible (${JSON.stringify(state)})`);
  }
}

console.log('\n── junk in ──');
{
  ok(at(undefined, { lockLoading: true }).target === LOGBOOKS,
    'no pathname yet, while unknown → the confined tab');
  ok(at(undefined).target === DASHBOARD, 'no pathname, unlocked → the dashboard');
  ok(at('').target === DASHBOARD, 'empty pathname → the dashboard');
}

// ── It is the rule the guard actually runs ─────────────────────────────────
console.log('\n── wired into the root layout ──');
{
  const layout = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', '_layout.jsx'), 'utf8');

  ok(/siteDeviceTarget/.test(layout),
    'RouteGuard routes site devices through this function rather than '
    + 'reimplementing the rule inline');

  const destructure = layout.match(/=\s*useInspectorLock\(\)/);
  ok(!!destructure, 'RouteGuard still reads the inspector lock');
  const line = layout.slice(0, destructure ? destructure.index : 0).split('\n').pop()
    + (destructure ? layout.slice(destructure.index).split('\n')[0] : '');
  ok(/\bloading\b/.test(line),
    'IT READS `loading`. Not reading it is the defect — the guard cannot '
    + 'tell "not locked" from "not read yet" without it. Line: ' + line.trim());

  const effectDeps = layout.match(/\}, \[isMounted[^\]]*\]\)/);
  ok(!!effectDeps && /inspectorLoading|lockLoading/.test(effectDeps[0]),
    'AND THE EFFECT RE-RUNS WHEN IT FLIPS. Left out of the dependency array '
    + 'the guard would hold the device on logbooks forever, having read the '
    + 'hydrated value exactly never. Deps: ' + (effectDeps ? effectDeps[0] : 'not found'));
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
