/**
 * INSPECTOR MODE CONFINED THE TABLET TO HALF ITS OWN SCOPE.
 *
 * Operator ruling: "the gate tablet's scope is DOCUMENTS and LOGBOOKS ONLY.
 * It exists so a DOB inspector visiting site can read the record."
 *
 * Inspector Mode (src/context/InspectorLockContext.jsx) is the control that
 * delivers that ruling: the superintendent taps "Hand to Inspector (read-only)"
 * and the route gate in app/_layout.jsx confines the device. But the gate read
 *
 *     inspectorLocked && pathname !== '/site/logbooks' && pathname !== '/login'
 *
 * — LOGBOOKS ONLY. `/site/documents` was redirected away like any write screen,
 * and because `/site` is redirected too, the site home (the only place the
 * Documents tile lives) never rendered while locked either. An inspector handed
 * the tablet could not reach the plans, permits or agreements AT ALL, on the
 * one device that exists so he can read them.
 *
 * The two screens that are NOT in the ruled scope — /site/daily-logs (files the
 * daily log) and /site/checkins (records expired-SST approve / send-home
 * decisions) — are WRITE paths and stay outside the lock. This test pins that:
 * widening the lock to admit documents must not admit either of them.
 *
 * Run:  node src/utils/inspectorScope.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const APP = path.join(UTILS, '..', '..', 'app');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function readOr(p, label) {
  try { return fs.readFileSync(p, 'utf8'); }
  catch (_e) { ok(false, `${label}: file not readable -> ${p}`); return ''; }
}

// Load the ESM util into this CommonJS test the way checkinFields.test.cjs
// does — strip the export keywords and evaluate. A MISSING module records
// failures below rather than throwing, so the run reports every assertion.
function loadScope() {
  const p = path.join(UTILS, 'inspectorScope.js');
  if (!fs.existsSync(p)) return null;
  const src = fs.readFileSync(p, 'utf8')
    .replace(/^export default[\s\S]*$/m, '')
    .replace(/^export /gm, '');
  // eslint-disable-next-line no-new-func
  return new Function(`${src}; return { INSPECTOR_LANDING, INSPECTOR_ALLOWED_PATHS, isInspectorAllowedPath };`)();
}

let S = null;
try { S = loadScope(); }
catch (e) { console.log(`  (inspectorScope.js failed to evaluate: ${e.message})`); }

const layout = readOr(path.join(APP, '_layout.jsx'), '_layout.jsx');
const docs = readOr(path.join(APP, 'site', 'documents.jsx'), 'site/documents.jsx');
const logbooks = readOr(path.join(APP, 'site', 'logbooks.jsx'), 'site/logbooks.jsx');

// ===================================================================
// A. The finding — what the old two-term gate did to the ruled scope
// ===================================================================
console.log('\n-- the finding --');

// The gate verbatim as it stood, expressed as "does this path get redirected".
const OLD_REDIRECTS = (p) => p !== '/site/logbooks' && p !== '/login';

ok(OLD_REDIRECTS('/site/documents') === true,
  'THE FINDING: while locked, the old gate REDIRECTED /site/documents away — '
  + 'documents is half the ruled scope and was unreachable');
ok(OLD_REDIRECTS('/site') === true,
  'and /site was redirected too, so the site home carrying the Documents tile '
  + 'never rendered while locked — there was no route to documents at all');

// ===================================================================
// B. One definition of the inspector's scope
// ===================================================================
console.log('\n-- src/utils/inspectorScope.js --');

ok(!!S, 'src/utils/inspectorScope.js exists and evaluates');

const allowed = (S && S.INSPECTOR_ALLOWED_PATHS) || [];
const isAllowed = (S && S.isInspectorAllowedPath) || (() => undefined);

ok(Array.isArray(allowed) && allowed.length === 3,
  'INSPECTOR_ALLOWED_PATHS names exactly three paths — the ruled scope plus /login');
for (const p of ['/site/logbooks', '/site/documents', '/login']) {
  ok(allowed.includes(p), `INSPECTOR_ALLOWED_PATHS includes ${p}`);
}

ok(S && S.INSPECTOR_LANDING === '/site/logbooks',
  'INSPECTOR_LANDING is /site/logbooks — the screen that carries the Exit control');

console.log('\n-- what a locked device may reach --');

ok(isAllowed('/site/logbooks') === true, '/site/logbooks — the record');
ok(isAllowed('/site/documents') === true,
  '/site/documents — THE FIX: the other half of the ruled scope is reachable');
ok(isAllowed('/login') === true, '/login — a logout is still possible');

console.log('\n-- what a locked device may NOT reach --');

ok(isAllowed('/site/daily-logs') === false,
  '/site/daily-logs stays out — it FILES a daily log (dailyLogsAPI.create/update)');
ok(isAllowed('/site/checkins') === false,
  '/site/checkins stays out — it RECORDS approve / send-home decisions (checkinsAPI.review)');
ok(isAllowed('/site') === false,
  '/site stays out — the home offers the two write tiles');
ok(isAllowed('/projects') === false, 'nothing outside /site is reachable');
ok(isAllowed('/site/logbooks/extra') === false,
  'not a prefix match — only the named paths, so a future child route is not admitted by accident');

console.log('\n-- shapes usePathname can hand it --');

ok(isAllowed('/site/documents/') === true, 'a trailing slash is the same path');
ok(isAllowed('') === false && isAllowed(null) === false && isAllowed(undefined) === false,
  'an empty or absent pathname is never allowed');

// ===================================================================
// C. The route gate uses that one definition
// ===================================================================
console.log('\n-- app/_layout.jsx --');

ok(/from\s+'\.\.\/src\/utils\/inspectorScope'/.test(layout),
  '_layout.jsx imports the scope module rather than restating the paths');
ok(/inspectorLocked\s*&&\s*!isInspectorAllowedPath\(pathname\)/.test(layout),
  'the locked branch tests the shared predicate');
ok(!/inspectorLocked\s*&&\s*pathname\s*!==\s*'\/site\/logbooks'/.test(layout),
  'the hard-coded logbooks-only test is gone — it is what excluded documents');
ok(/router\.replace\(INSPECTOR_LANDING\)/.test(layout),
  'a refused path lands on INSPECTOR_LANDING, not a second copy of the string');

// ===================================================================
// D. Documents is reachable AND has no escape hatch while locked
// ===================================================================
console.log('\n-- app/site/documents.jsx --');

ok(/useInspectorLock/.test(docs),
  'documents.jsx reads the lock — it is now a screen an inspector can be on');
ok(/\{!isLocked\s*&&[\s\S]{0,400}?router\.push\('\/site'\)/.test(docs),
  'the Home button is hidden while locked — /site is not in the inspector scope');
ok(/\{!isLocked\s*&&[\s\S]{0,400}?handleLogout/.test(docs),
  'the logout control is hidden while locked — Inspector Mode carries no logout '
  + 'on logbooks either, and an inspector must not be able to sign the tablet out');
ok(/isLocked\s*&&[\s\S]{0,600}?\/site\/logbooks/.test(docs),
  'while locked, documents offers a way back to Log Books — the screen that '
  + 'carries "Exit Inspector Mode", so the super is never stranded');

// ===================================================================
// E. Logbooks offers the other half of the scope while locked
// ===================================================================
console.log('\n-- app/site/logbooks.jsx --');

ok(/isLocked\s*&&[\s\S]{0,1200}?\/site\/documents/.test(logbooks),
  'the Inspector Mode banner offers /site/documents — without it the widened '
  + 'gate would admit a path nothing navigates to');

console.log(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
