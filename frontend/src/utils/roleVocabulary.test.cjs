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
  ok(SCREEN.includes('ASSIGNABLE_ROLES.map('), 'users.jsx no longer maps the shared list');
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
