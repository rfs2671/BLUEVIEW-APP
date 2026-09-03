/**
 * THE ROUTE THE SIGNING GATE SENDS HIM TO, AND THE GUARD THAT SENT HIM HOME.
 *
 * From 2026-09-01 to 2026-09-03 no CP on the platform could sign anything. He
 * tapped Sign, watched a spinner, and landed on his home screen without ever
 * being shown the agreement. Eight hours of logs: 33 GETs of /api/esra-consent,
 * ZERO POSTs. The route mounted and read, and was redirected away before it
 * painted.
 *
 * RouteGuard confines a CP to a fixed set of paths and replaces to /logbooks
 * from anywhere else. /consent was not on that set. The consent gate pushed him
 * onto a route the guard bounced, and /logbooks is his home screen — so the
 * symptom was a spinner and a homecoming rather than an error.
 *
 * WHAT THIS FILE IS FOR. The rule now lives in a pure module so it can be RUN.
 * Inline in app/_layout.jsx it was a boolean expression inside an effect inside
 * a component that renders null; the only thing in this repo that executes a
 * screen is the mount smoke, which is run locally and signs in as an OWNER, so
 * the CP arm was never once evaluated by any gate. This runs in CI on every
 * push and costs nothing.
 *
 * THE PAINT ITSELF IS PROVED ELSEWHERE. scripts/consent-paint.cjs mounts the
 * real route as a CP with no consent row, asserts the four paragraphs of the
 * agreement are on the page, and asserts the accept POST fires. This file
 * asserts the rule that made that impossible; it does not stand in for it.
 *
 * Run:  node src/utils/cpConfinement.test.cjs
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

const M = load('cpConfinement.js');

console.log('\n1. THE OUTAGE: /consent IS A PLACE A CP MAY BE');
{
  ok(M.cpPathAllowed('/consent') === true,
    '/consent is allowed — the gate pushes him here and it is the only screen '
    + 'that can clear the gate; leaving it off blocked every signature on the '
    + 'platform for two days');
  ok(M.cpNoCompanyPathAllowed('/consent') === true,
    'and for a CP with no company too — the consent record is keyed on the '
    + 'person, not the company, so it is one of the few things he can still do');
}

console.log('\n2. THE CONFINEMENT IS STILL A CONFINEMENT');
{
  // If these start passing, the fix has been widened into a hole. A CP must
  // not reach admin surfaces, and "allow /consent" is not "allow everything".
  [
    '/', '/admin/users', '/admin/site-devices', '/projects', '/project/p1',
    '/workers', '/reports', '/owner', '/checkin', '/site', '/site/logbooks',
    '/daily-log', '/checklists', '/onboarding', '/demo',
  ].forEach((p) => {
    ok(M.cpPathAllowed(p) === false, `${p} is still refused to a CP`);
  });
}

console.log('\n3. THE PATHS HE COULD ALREADY REACH, UNCHANGED');
{
  ok(M.cpPathAllowed('/logbooks') === true, '/logbooks');
  ok(M.cpPathAllowed('/logbooks/daily_jobsite') === true,
    '/logbooks/* — a prefix, because there is an editor per log type');
  ok(M.cpPathAllowed('/logbooks/site_superintendent_log') === true,
    'including the superintendent log, whose own gate has pushed to /consent '
    + 'since #308 and was bounced the whole time — nobody had opened it');
  ok(M.cpPathAllowed('/documents') === true, '/documents');
  ok(M.cpPathAllowed('/settings') === true, '/settings');
  ok(M.cpPathAllowed('/login') === true,
    '/login stays reachable, or a confined CP cannot even sign out');
}

console.log('\n4. THE SAME OMISSION, ONE SCREEN SMALLER');
{
  // app/settings.jsx renders "Notification Preferences" to EVERY role — it is
  // not behind the isAdmin gate the company cards are behind — and pushes to
  // /settings/notifications. The pre-fix rule matched '/settings' exactly, so a
  // CP who tapped it was bounced to /logbooks without a word. Same bug, same
  // guard, smaller blast radius, found looking for this one.
  ok(M.cpPathAllowed('/settings/notifications') === true,
    '/settings/notifications is reachable — settings.jsx offers it to a CP and '
    + 'exact-matching /settings bounced him off his own notification settings');
  ok(M.cpPathAllowed('/settings/notifications/project/p1') === true,
    'and the per-project page beneath it, which that screen pushes to');
  ok(M.cpNoCompanyPathAllowed('/settings/notifications') === true,
    'for a CP with no company too');
}

console.log('\n5. SUBPATHS MATCH ON A SEGMENT BOUNDARY, NOT ON startsWith');
{
  // The pre-fix rule used a raw startsWith for /logbooks, which would have
  // admitted a route named /logbooks-archive. Matching the boundary is looser
  // where the rule was wrongly tight and tighter where it was loosely right.
  ok(M.cpPathAllowed('/logbooks-archive') === false,
    '/logbooks-archive is NOT under /logbooks');
  ok(M.cpPathAllowed('/settings-admin') === false,
    '/settings-admin is NOT under /settings');
  ok(M.cpNoCompanyPathAllowed('/settings-admin') === false,
    'and the no-company arm draws the boundary too');
  ok(M.cpPathAllowed('/documents-internal') === false,
    '/documents takes no subpaths — it is a single screen');
  ok(M.cpPathAllowed('/consent-preview') === false,
    'and neither does /consent');
}

console.log('\n6. A PATHNAME THAT IS NOT A STRING IS NOT A PASS');
{
  // usePathname can hand back undefined for a frame. Treating that as allowed
  // would open the confinement for exactly as long as it is unknown, which is
  // the inspector-lock defect in a different arm.
  [undefined, null, 0, {}, []].forEach((v) => {
    ok(M.cpPathAllowed(v) === false, `${JSON.stringify(v) || String(v)} is refused`);
  });
}

console.log('\n7. AND THE LAYOUT ACTUALLY USES IT');
{
  const layout = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', '_layout.jsx'), 'utf8',
  );
  ok(/from '\.\.\/src\/utils\/cpConfinement'/.test(layout),
    'app/_layout.jsx imports the rule');
  ok(/cpPathAllowed\(pathname\)/.test(layout),
    'RouteGuard asks cpPathAllowed rather than reimplementing the list inline — '
    + 'inline is how it stayed invisible while twelve screens started pushing '
    + 'to a route it refused');
  ok(/cpNoCompanyPathAllowed\(pathname\)/.test(layout),
    'and the no-company arm asks too — two copies of a list is two chances to '
    + 'forget the same route');
  ok(!/pathname\s*===\s*'\/documents'/.test(layout),
    'the old inline expression is GONE, not left beside the new one where a '
    + 'later reader could restore it');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
