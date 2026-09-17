/**
 * THE ROLE PICKER AND THE SERVER'S ALLOW-LIST ARE ONE LIST, READ TWICE.
 *
 * ── WHAT THE PICKER IS AND IS NOT ───────────────────────────────────────────
 *
 * It is not a gate. `assert_assignable_role` in backend/server.py is; deleting
 * a button stops the app sending a value and stops nothing else. What the
 * picker CAN do is disagree with the gate, and both directions are a defect:
 *
 *   a role on the picker and not on the allow-list   the admin picks it, the
 *       request 422s, and the screen reports a server error for a button the
 *       screen itself drew.
 *   a role on the allow-list and not on the picker   the role is unreachable.
 *       Four complete, correct, invisible things shipped in one week this way.
 *
 * So the assertion is the IDENTITY of the two lists, read out of the two files,
 * rather than a hard-coded four in this test agreeing with itself.
 *
 * ── AND THE ONE THAT WAS WITHDRAWN ──────────────────────────────────────────
 *
 * "Worker" was the second button on BOTH modals and the model default on the
 * server, so it was also what a request omitting `role` produced. Its absence
 * is asserted by name in all three places.
 *
 * Run:  node src/utils/roleVocabulary.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');
const read = (...p) => fs.readFileSync(path.join(...p), 'utf8')
  .split('\r\n').join('\n');

const V = loadEsm('src/utils/roleVocabulary.js');
const SERVER = read(REPO, 'backend', 'server.py');
const SCREEN = read(FRONTEND, 'app', 'admin', 'users.jsx');

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failures += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const eq = (a, b, what) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${what}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

console.log('\nrole vocabulary\n');

// ── 1. THE TWO LISTS ARE THE SAME LIST ──────────────────────────────────────

/** The server's tuple, read out of its declaration. */
function serverAllowList() {
  const at = SERVER.indexOf('ASSIGNABLE_ROLES = (');
  ok(at >= 0, 'backend/server.py no longer declares ASSIGNABLE_ROLES');
  const body = SERVER.slice(at + 'ASSIGNABLE_ROLES = ('.length,
    SERVER.indexOf(')', at));
  // The tuple names ROLE_PM and ROLE_SUPERINTENDENT by constant rather than by
  // literal — resolve them from their own declarations so this test reads the
  // shipped values and not a copy of them.
  const constant = (name) => {
    const m = SERVER.match(new RegExp(`^${name} = "([a-z_]+)"`, 'm'));
    ok(m, `backend/server.py no longer declares ${name}`);
    return m[1];
  };
  return body.split(',').map((t) => t.trim()).filter(Boolean).map((t) => {
    if (t.startsWith('"') || t.startsWith("'")) return t.slice(1, -1);
    return constant(t);
  });
}

check('the picker offers exactly what the server will accept, in the same order', () => {
  eq(V.ASSIGNABLE_ROLE_VALUES, serverAllowList(), 'picker vs allow-list');
});

check('and it is the four the operator named', () => {
  eq(V.ASSIGNABLE_ROLE_VALUES, ['admin', 'pm', 'superintendent', 'cp'], 'the four');
});

// ── 2. WORKER IS GONE, IN ALL THREE PLACES ──────────────────────────────────

check('worker is not on the picker', () => {
  ok(!V.ASSIGNABLE_ROLE_VALUES.includes('worker'), 'worker is still offered');
});

check('worker is not on the server allow-list', () => {
  ok(!serverAllowList().includes('worker'), "the server still accepts 'worker'");
});

check('the screen no longer draws a Worker button', () => {
  ok(!/setFormRole\('worker'\)/.test(SCREEN), 'a Worker button survives in users.jsx');
});

check('owner is not assignable from the picker', () => {
  // It is what every self-serve signup receives and means "created this
  // company". An admin handing it out is a different act from a signup.
  ok(!V.ASSIGNABLE_ROLE_VALUES.includes('owner'), 'owner is offered');
});

// ── 3. ONE PICKER, RENDERED TWICE ───────────────────────────────────────────

check('the Add and Edit modals render the same picker', () => {
  const uses = (SCREEN.match(/renderRolePicker\(\)/g) || []).length;
  ok(uses === 2, `expected 2 uses of renderRolePicker, found ${uses}`);
  const decls = (SCREEN.match(/const renderRolePicker/g) || []).length;
  ok(decls === 1, `expected 1 declaration, found ${decls}`);
});

check('the picker is driven by the module and not by a second inline list', () => {
  // It maps `rolesAssignableBy(...)` rather than the raw list now — the module
  // is still the single source, and WHICH of its entries appear is the module's
  // answer too. What must never come back is a hand-written list of roles in
  // the JSX.
  ok(/rolesAssignableBy\(/.test(SCREEN),
    'users.jsx no longer asks the module which roles this principal may assign');
  ok(SCREEN.includes('rolePickerOptions.map('),
    'users.jsx no longer maps the module-derived list');
  ok(!/value:\s*'(admin|cp|pm|superintendent)'/.test(SCREEN),
    'a second inline role list is back in users.jsx');
});

// ── 3b. AND WHAT IT OFFERS DEPENDS ON WHO IS LOOKING ────────────────────────
//
// Operator ruling: a company admin manages PM, Superintendent and CP. Admin
// accounts are created by the platform operator in the owner panel.
//
// THE TWO HALVES OF THIS RULING ARE ONE CHANGE. `GET /admin/users` hides admin
// rows from a company admin; if the picker still offered "Admin" he could
// create an account and watch it vanish on the next refresh — the #576 defect
// ("created users don't vanish") arriving from the server end. A product may
// refuse an act or hide its result. Doing both is the bug.

check('a company admin is offered the three he manages, in order', () => {
  eq(V.rolesAssignableBy(false).map((r) => r.value),
    ['pm', 'superintendent', 'cp'], 'company admin picker');
});

check('and Admin is not among them', () => {
  ok(!V.rolesAssignableBy(false).some((r) => r.value === 'admin'),
    'a company admin is still offered Admin');
});

check('the platform operator keeps all four', () => {
  eq(V.rolesAssignableBy(true).map((r) => r.value),
    V.ASSIGNABLE_ROLE_VALUES, 'operator picker');
});

check('absent must not read as operator', () => {
  // `isPlatformOperator` returns `=== true` for exactly this reason: a cached
  // principal from disk, an older deploy or a site-device shape may carry no
  // flag at all, and `!== false` would make every one of those the operator.
  for (const notTrue of [undefined, null, 0, '', 'true', {}]) {
    ok(!V.rolesAssignableBy(notTrue).some((r) => r.value === 'admin'),
      `${JSON.stringify(notTrue)} was treated as the operator`);
  }
});

check('the three it offers are the three the server scopes the list to', () => {
  // THE IDENTITY, read out of both files. The picker and `ADMIN_MANAGED_ROLES`
  // are one list: a role the picker can write but the list filter hides is an
  // account that vanishes, and a role the filter shows but the picker cannot
  // write is a row nobody can create.
  const at = SERVER.indexOf('ADMIN_MANAGED_ROLES = (');
  ok(at >= 0, 'backend/server.py no longer declares ADMIN_MANAGED_ROLES');
  const body = SERVER.slice(at + 'ADMIN_MANAGED_ROLES = ('.length,
    SERVER.indexOf(')', at));
  const constant = (name) => {
    const m = SERVER.match(new RegExp(`^${name} = "([a-z_]+)"`, 'm'));
    ok(m, `backend/server.py no longer declares ${name}`);
    return m[1];
  };
  const server = body.split(',').map((t) => t.trim()).filter(Boolean)
    .map((t) => ((t.startsWith('"') || t.startsWith("'")) ? t.slice(1, -1) : constant(t)));
  eq(V.rolesAssignableBy(false).map((r) => r.value), server,
    'picker vs the server\'s managed-role scope');
});

// ── 4. EVERY ROLE IS EXPLAINED ──────────────────────────────────────────────

check('each role carries a label and a blurb', () => {
  for (const role of V.ASSIGNABLE_ROLES) {
    ok(role.label && role.label.length > 1, `${role.value} has no label`);
    ok(role.blurb && role.blurb.length > 20, `${role.value} has no blurb`);
  }
});

check('the labels are the operator\'s words', () => {
  const byValue = Object.fromEntries(V.ASSIGNABLE_ROLES.map((r) => [r.value, r.label]));
  eq(byValue.pm, 'Site Manager / PM', 'pm label');
  eq(byValue.superintendent, 'Superintendent', 'superintendent label');
  eq(byValue.cp, 'CP', 'cp label');
  eq(byValue.admin, 'Admin', 'admin label');
});

check('the blurb says what the Site Manager cannot do', () => {
  const pm = V.ASSIGNABLE_ROLES.find((r) => r.value === 'pm').blurb;
  for (const word of ['assigned', 'Cannot create projects', 'sign']) {
    ok(pm.includes(word), `the pm blurb does not mention ${word}`);
  }
});

// ── 5. A LIST SCREEN RENDERS WHAT THE DATABASE HOLDS ────────────────────────

check('roleLabel still names roles the picker cannot write', () => {
  // `owner` is on every self-serve signup and `worker` is on accounts created
  // before the ruling. A lookup returning '' for them prints an empty badge on
  // a real row.
  eq(V.roleLabel('owner'), 'Owner', 'owner');
  eq(V.roleLabel('worker'), 'WORKER', 'legacy worker');
  eq(V.roleLabel('site_device'), 'Site Device', 'site device');
  eq(V.roleLabel(''), 'UNKNOWN', 'empty');
  eq(V.roleLabel(null), 'UNKNOWN', 'null');
});

check('roleLabel normalises what the database holds', () => {
  eq(V.roleLabel(' CP '), 'CP', 'whitespace and case');
});

// ── 6. ONLY ONE ROLE HOLDS A LICENCE ────────────────────────────────────────

check('roleHasLicence is true for the superintendent alone', () => {
  ok(V.roleHasLicence('superintendent'), 'superintendent');
  for (const other of ['cp', 'admin', 'owner', 'pm', 'worker', '', null]) {
    ok(!V.roleHasLicence(other), `${other} was given a licence`);
  }
});

check('the licence fields only render for that role', () => {
  ok(SCREEN.includes('if (!roleHasLicence(formRole)) return null;'),
    'the licence block is not gated on the role');
});

// ── 7. THE BADGE ────────────────────────────────────────────────────────────

check('an expired registration reads as expired, loudly', () => {
  const note = V.licenceSentence({ state: 'expired', days_remaining: -3 });
  eq(note.tone, 'error', 'tone');
  ok(/EXPIRED/.test(note.text), note.text);
});

check('an expiring one names the number of days', () => {
  eq(V.licenceSentence({ state: 'expiring', days_remaining: 12 }).text,
    'DOB registration expires in 12 days', 'twelve days');
  eq(V.licenceSentence({ state: 'expiring', days_remaining: 1 }).text,
    'DOB registration expires in 1 day', 'singular');
});

check('"in 0 days" is not a sentence', () => {
  eq(V.licenceSentence({ state: 'expiring', days_remaining: 0 }).text,
    'DOB registration expires today', 'today');
});

check('an unrecorded registration gets a badge and a valid one does not', () => {
  // THE FOURTH STATE IS THE POINT. Silence for `unknown` would render a
  // licence nobody has checked identically to one with two years left —
  // and that is the state Michael is in the moment he is promoted.
  ok(V.licenceSentence({ state: 'unknown' }) !== null, 'unknown is silent');
  eq(V.licenceSentence({ state: 'ok', days_remaining: 400 }), null, 'ok is silent');
  eq(V.licenceSentence(null), null, 'no licence block at all');
  eq(V.licenceSentence(undefined), null, 'undefined');
});

// ── 7b. THE SENTENCE IS ABOUT THE FACT IT MEASURED ──────────────────────────
//
// WHAT PRODUCTION HELD. `dob_superintendent_number: '32299'` — the operator
// typed it and the save landed — and `dob_registration_expiry: '07/212029'`,
// which is '07/21/2029' with a slash missing. The old verdict was derived from
// the EXPIRY alone, so it came back `unknown`, and this function rendered
// `unknown` as "No DOB registration recorded". A sentence about the NUMBER,
// drawn from a measurement of the DATE, three feet from the number.

check('a recorded number never reads as "no registration recorded"', () => {
  const note = V.licenceSentence({
    state: 'unreadable', registered: true, number: '32299',
    expires_on: '07/212029',
  });
  ok(note !== null, 'silent about an unreadable date');
  ok(!/No DOB registration recorded/.test(note.text), note.text);
});

check('and the unreadable date names itself, so the typo is visible', () => {
  const note = V.licenceSentence({
    state: 'unreadable', registered: true, expires_on: '07/212029',
  });
  ok(note.text.includes('07/212029'), note.text);
  eq(note.tone, 'error', 'tone');
});

check('the badge no longer tells anyone to type YYYY-MM-DD', () => {
  // THE FIELD TYPES MM/DD/YYYY NOW. "re-enter it as YYYY-MM-DD" names the
  // storage format, which nobody types any more — following it would put
  // 2029-07-21 into a field that reads it as month 20.
  for (const raw of ['07/212029', 'soon', '']) {
    const note = V.licenceSentence({ state: 'unreadable', registered: true, expires_on: raw });
    ok(!note.text.includes('YYYY-MM-DD'), `${JSON.stringify(raw)}: ${note.text}`);
  }
});

check('a stored value the form can read says what it will be read as', () => {
  // Michael's '07/212029' opens in Edit as 07/21/2029 for confirmation, so
  // the badge says that — not "re-enter", which would have him retype a date
  // the form is already showing him.
  const note = V.licenceSentence({
    state: 'unreadable', registered: true, expires_on: '07/212029',
  });
  ok(note.text.includes('07/21/2029'), note.text);
  ok(/\bEdit\b/.test(note.text), `does not say where to confirm it: ${note.text}`);
});

check('a stored value nobody can read asks for the date in the typed format', () => {
  const note = V.licenceSentence({
    state: 'unreadable', registered: true, expires_on: 'soon',
  });
  ok(note.text.includes('"soon"'), note.text);
  ok(note.text.includes('MM/DD/YYYY'), note.text);
});

check('an absent expiry is a different sentence from an unreadable one', () => {
  const missing = V.licenceSentence({ state: 'unknown', registered: true });
  const garbled = V.licenceSentence({
    state: 'unreadable', registered: true, expires_on: 'soon',
  });
  ok(missing.text !== garbled.text,
    'a typo and an empty field still render identically');
  ok(!/No DOB registration recorded/.test(missing.text), missing.text);
});

check('no number at all is the one case that says so', () => {
  const note = V.licenceSentence({ state: 'unknown', registered: false });
  eq(note.text, 'No DOB registration recorded', 'unregistered');
});

check('and it wins over every date verdict', () => {
  // Without a number there is no registration for a date to be about, so
  // "expires in 9 days" would be the screen asserting one nobody recorded.
  eq(V.licenceSentence({ state: 'expiring', days_remaining: 9, registered: false }).text,
    'No DOB registration recorded', 'expiring, unregistered');
  eq(V.licenceSentence({ state: 'expired', registered: false }).text,
    'No DOB registration recorded', 'expired, unregistered');
});

check('an older deploy sending no `registered` key does not badge everybody', () => {
  // ABSENT MUST NOT READ AS UNREGISTERED. During a rollout the client can be
  // ahead of the server, and `registered == null` would put "No DOB
  // registration recorded" on every superintendent in the product.
  eq(V.licenceSentence({ state: 'ok', days_remaining: 400 }), null, 'ok, no key');
  const note = V.licenceSentence({ state: 'expired' });
  eq(note.text, 'DOB registration EXPIRED', 'expired, no key');
});

// ── 8. THE FORM REFUSES WHAT THE SERVER CANNOT READ BACK ────────────────────
//
// PR #584 checked this field with `licenceExpiryError`, which accepted TYPED
// ISO and nothing else. The field is now the shared DateInput, which types
// MM/DD/YYYY and hands the host ISO — so that validator would refuse every
// value the admin can type. It is gone, and the screen asks the one shared
// check in src/utils/dateEntry.js. Its calendar is dateEntry.test.cjs's.

const DE = loadEsm('src/utils/dateEntry.js');
const SCREEN_CODE = SCREEN.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');

check('roleVocabulary no longer carries a validator of its own', () => {
  ok(!('licenceExpiryError' in V), 'licenceExpiryError is still exported');
  ok(!('LICENCE_EXPIRY_FORMAT' in V), 'LICENCE_EXPIRY_FORMAT is still exported');
});

check('the screen blocks the save with the shared check, on both paths and the field', () => {
  // The field message is the courtesy; not sending it is what stops the value
  // reaching the database. Both handlers, because Edit is the route the real
  // typo came through.
  const calls = (SCREEN_CODE.match(/dateEntryError\(formDobExpiry\)/g) || []).length;
  ok(calls >= 2, `expected the create path and the edit path, found ${calls}`);
  ok(/<DateInput\b[^>]*value=\{formDobExpiry\}/.test(SCREEN_CODE),
    'the expiry is not a DateInput');
});

check('what the screen sends is the stored form, never the typed text', () => {
  const sends = SCREEN_CODE.match(/dob_registration_expiry\s*=\s*([^;]+);/g) || [];
  ok(sends.length >= 2, `expected two payload assignments, found ${sends.length}`);
  for (const s of sends) {
    ok(/toStoredDate\(formDobExpiry\)/.test(s), `sends something else: ${s}`);
  }
});

check('Michael\'s stored value passes the check and is sent as ISO', () => {
  // The ruling: parsed if unambiguous, shown for confirmation, and written
  // only on Save — as the date he meant.
  eq(DE.dateEntryError('07/212029'), null, 'refused');
  eq(DE.toStoredDate('07/212029'), '2029-07-21', 'sent');
});

check('what the check admits, the server\'s reader reads', () => {
  // THE IDENTITY, not two lists. `superintendent_licence_state` reads
  // strptime(raw[:10], "%Y-%m-%d"); whatever the form sends must match that
  // shape, or the badge says "unreadable" about a date the form accepted.
  ok(/strptime\(raw\[:10\], "%Y-%m-%d"\)/.test(SERVER),
    'the server reader changed; re-derive this identity');
  for (const raw of ['07/21/2029', '07212029', '07/212029', '2029-07-21', '02/29/2028', '12/31/2026']) {
    eq(DE.dateEntryError(raw), null, raw);
    ok(/^\d{4}-\d{2}-\d{2}$/.test(DE.toStoredDate(raw)), `${raw} -> ${DE.toStoredDate(raw)}`);
  }
  for (const raw of ['13/45/2029', '02/30/2029', '02/29/2027', 'soon', '07/2']) {
    ok(DE.dateEntryError(raw) !== null, `${raw} was accepted`);
    eq(DE.toStoredDate(raw), null, raw);
  }
});

check('the badge does not recompute the date', () => {
  // A second date calculation is a second answer to "has it expired", and the
  // two disagree on the day it matters, across a timezone. The verdict is the
  // server's.
  const src = read(FRONTEND, 'src', 'utils', 'roleVocabulary.js');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/new Date\(/.test(code), 'roleVocabulary.js computes a date of its own');
  ok(!/Date\.now\(/.test(code), 'roleVocabulary.js reads the clock');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
