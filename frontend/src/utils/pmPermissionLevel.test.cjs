/**
 * THE PM'S PERMISSION LEVEL, ON THE APP SIDE.
 *
 *   "Assigned jobs only" (default)  pm_access: "assigned" (or missing)
 *   "Same as admin"                 pm_access: "full"
 *
 * A full-access PM is a company admin to every screen (isCompanyAdmin) but
 * not to user management or the admin password route (isAccountAdmin). The
 * user's card reads "PM · assigned jobs" / "PM · full access". The server is
 * the boundary; these are the courtesy half and must say the same thing.
 *
 * Run:  node src/utils/pmPermissionLevel.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8').split('\r\n').join('\n');

const V = loadEsm('src/utils/roleVocabulary.js');

// AuthContext imports React and storage; the three predicates are plain
// functions, so they are lifted out of the source and run as written.
const AUTH = read('src', 'context', 'AuthContext.js');
const fnSrc = (name) => {
  const m = AUTH.match(new RegExp(`export function ${name}\\(user\\) \\{[\\s\\S]*?\\n\\}`));
  if (!m) throw new Error(`${name} not found in AuthContext.js`);
  return m[0].replace(/^export /, '');
};
// eslint-disable-next-line no-new-func
const A = new Function(`${fnSrc('isPlatformOperator')}\n${fnSrc('isAccountAdmin')}\n`
  + `${fnSrc('isFullAccessPm')}\n${fnSrc('isCompanyAdmin')}\n`
  + 'return { isPlatformOperator, isAccountAdmin, isFullAccessPm, isCompanyAdmin };')();

let failures = 0;
const check = (name, fn) => {
  try { fn(); console.log(`  ok  ${name}`); } catch (e) {
    failures += 1; console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const eq = (a, b, what) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${what}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

const ADMIN = { role: 'admin' };
const PM_ASSIGNED = { role: 'pm', pm_access: 'assigned' };
const PM_LEGACY = { role: 'pm' };                 // before the migration ran
const PM_FULL = { role: 'pm', pm_access: 'full' };
const CP_WITH_FIELD = { role: 'cp', pm_access: 'full' };

console.log('\nPM permission level\n');

check('two levels, assigned first (the default)', () => {
  eq(V.PM_ACCESS_LEVELS.map((l) => [l.value, l.label]),
    [['assigned', 'Assigned jobs only'], ['full', 'Same as admin']], 'levels');
  ok(V.PM_ACCESS_LEVELS.every((l) => l.blurb.length > 20), 'each level says what it does');
});

check('the card label', () => {
  eq(V.userCardRoleLabel(PM_ASSIGNED), 'PM · assigned jobs', 'assigned');
  eq(V.userCardRoleLabel(PM_LEGACY), 'PM · assigned jobs', 'missing field reads as assigned');
  eq(V.userCardRoleLabel(PM_FULL), 'PM · full access', 'full');
  eq(V.userCardRoleLabel(ADMIN), 'Admin', 'admin unchanged');
  eq(V.userCardRoleLabel(CP_WITH_FIELD), 'CP', 'the field means nothing off a PM');
});

check('pmAccessLevel', () => {
  eq([PM_ASSIGNED, PM_LEGACY, PM_FULL, ADMIN, CP_WITH_FIELD, null].map(V.pmAccessLevel),
    ['assigned', 'assigned', 'full', null, null, null], 'levels');
});

check('a full-access PM is a company admin, not an account admin', () => {
  eq([ADMIN, PM_FULL, PM_ASSIGNED, PM_LEGACY, CP_WITH_FIELD].map(A.isCompanyAdmin),
    [true, true, false, false, false], 'isCompanyAdmin');
  eq([ADMIN, PM_FULL, PM_ASSIGNED].map(A.isAccountAdmin), [true, false, false], 'isAccountAdmin');
  ok(A.isCompanyAdmin({ role: 'owner', is_platform_operator: true }), 'the operator stays');
});

check('the Users screen: card label, picker, payloads', () => {
  const screen = read('app', 'admin', 'users.jsx');
  ok(/\{userCardRoleLabel\(userItem\)\}/.test(screen), 'the card shows userCardRoleLabel');
  ok(/formRole === ROLE_PM \? renderPmAccessPicker\(\) : null/.test(screen), 'the picker shows for a PM');
  ok(/if \(formRole === ROLE_PM\) payload\.pm_access = formPmAccess;/.test(screen), 'create sends it');
  ok(/if \(formRole === ROLE_PM\) updatePayload\.pm_access = formPmAccess;/.test(screen), 'edit sends it');
  ok(/const isAdmin = user\?\.role === 'admin';/.test(screen), 'the screen stays an admin\'s');
});

check('user management and the admin password stay with an admin', () => {
  const home = read('app', 'index.jsx');
  ok(/isAccountAdmin\(user\)\s*\n?\s*\? adminActions : adminActions\.filter\(\(a\) => a\.path !== '\/admin\/users'\)/.test(home),
    'User Mgmt tile only for an admin');
  ok(!/\(isAdmin \? adminActions : pmActions\)|\(admin \? adminActions : pmActions\)/.test(home),
    'no tile list bypasses adminActionsFor');
  ok(/\{isAccountAdmin\(user\) && \(/.test(read('src', 'components', 'FloatingNav.js')), 'nav password');
  ok(/\{isAccountAdmin\(user\) && \(\s*<>\s*<Text style=\{s\.sectionLabel\}>SECURITY/.test(read('app', 'settings.jsx')),
    'settings password');
});

check('screens that said role === "admin" now ask isCompanyAdmin', () => {
  for (const f of [['app', 'admin', 'site-devices.jsx'], ['app', 'admin', 'integrations.jsx'],
    ['app', 'project', '[id]', 'trades.jsx']]) {
    const src = read(...f);
    ok(!/user\?\.role === 'admin'/.test(src), `${f.join('/')} still checks role === 'admin'`);
    ok(/isCompanyAdmin\(user\)/.test(src), `${f.join('/')} does not ask isCompanyAdmin`);
  }
  ok(/isCompanyAdmin\(user\) \|\| String\(user\?\.role \|\| ''\)\.trim\(\)\.toLowerCase\(\) === 'pm'/
    .test(read('app', 'project', '[id]', 'trades.jsx')), 'any PM may edit a job\'s subs');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
