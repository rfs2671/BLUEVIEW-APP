/**
 * THE CS REGISTRATION IS MADE WHERE THE LICENCE LIVES.
 *
 * ── WHAT MOVED ──────────────────────────────────────────────────────────────
 *
 * The old admin tab asked an admin to type the man's NAME and his DOB LICENCE
 * NUMBER again for every project he is on — the same two facts re-entered per
 * jobsite, with nothing reconciling the copies and no answer to which is right.
 * They are facts about a PERSON. They live on his user record, and the
 * "Registration" control on his row in User Management writes the
 * `cs_registrations` rows from them.
 *
 * WHAT DID NOT MOVE is the row itself: it is still the filing gate for
 * BC 3301.13.13, the one-job rule is the same server code, and a de-selected
 * project is SOFT-deleted because the row is the provenance of every log filed
 * under it.
 *
 * ── THE TWO THINGS THIS SCREEN COULD GET WRONG, BOTH SILENT ─────────────────
 *
 * SEEDING THE PICKER FROM THE WRONG PLACE. The multi-select's initial value is
 * what a save DE-SELECTS. Seeded from `assigned_projects` — which the client
 * already has, so it is the tempting shortcut — the first save would register
 * him on every project he is assigned to and retire nothing; seeded from an
 * empty array while the read is still in flight, a quick save would retire
 * everything. It must be seeded from the server's `registered_project_ids` and
 * from nothing else, which is why the modal opens on a spinner.
 *
 * SENDING THE LICENCE. If the number went up with the request, this would be
 * the old screen at a new URL: two places to type one licence.
 *
 * Run:  node src/utils/csRegistrationMovedHome.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

/** Comments and JSX comments out. Several assertions below are about what the
 *  code DOES, and this file's subjects explain themselves at length. */
const CODE = (s) => s
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const USERS = read('app', 'admin', 'users.jsx');
const USERS_CODE = CODE(USERS);
const API = CODE(read('src', 'utils', 'api.js'));
const TAB = read('app', 'admin', 'superintendent.jsx');
const DASH = read('app', 'index.jsx');

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
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

/** The balanced-brace body that follows an anchor. Returns '' when absent, so
 *  a renamed function fails by name rather than aborting the run. */
function body(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return '';
  const open = src.indexOf('{', at);
  if (open < 0) return '';
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(open, i + 1);
    }
  }
  return '';
}

console.log('\ncs registration moved home\n');

// ── 1. THE SEED ─────────────────────────────────────────────────────────────

check('the picker is seeded from the server, not from assigned_projects', () => {
  const open = body(USERS_CODE, 'const openCsModal =');
  ok(open, 'openCsModal is gone');
  ok(open.includes('getCsRegistrations'), 'it does not read the current rows');
  ok(open.includes('registered_project_ids'),
    'it does not seed from registered_project_ids');
  ok(!open.includes('assigned_projects'),
    'it seeds from assigned_projects — the first save would register him on '
    + 'every project he is assigned to');
});

check('a failed read closes the modal instead of showing an empty selection', () => {
  // An empty selection the admin then saves is the delete-everything case.
  const open = body(USERS_CODE, 'const openCsModal =');
  ok(/catch[\s\S]*setShowCsModal\(false\)/.test(open),
    'the catch does not close the modal');
});

check('Save is disabled while the read is in flight', () => {
  ok(/disabled=\{csSaving \|\| csLoading \|\| !csState\?\.licence_number\}/
    .test(USERS_CODE), 'Save can be pressed before the current rows are known');
});

// ── 2. THE LICENCE IS NEVER SENT ────────────────────────────────────────────

check('the save sends project ids and nothing else', () => {
  const save = body(USERS_CODE, 'const handleSaveCsRegistrations =');
  ok(save, 'handleSaveCsRegistrations is gone');
  ok(save.includes('setCsRegistrations(selectedUser.id, csSelected)'),
    'the save does not pass the selection alone');
  for (const leak of ['dob_superintendent_number', 'licence_number',
    'license_number', 'full_name']) {
    ok(!save.includes(leak), `the save sends ${leak}`);
  }
});

check('the api wrapper posts project_ids only', () => {
  const fn = body(API, 'setCsRegistrations: async (userId, projectIds)');
  ok(fn, 'setCsRegistrations is gone');
  ok(fn.includes('project_ids: projectIds'), 'it does not send project_ids');
  ok(!/licen[cs]e/i.test(fn), 'it sends a licence');
});

// ── 3. ONLY THE ROLE THAT HOLDS A REGISTRATION ──────────────────────────────

check('the Registration button is gated on the role', () => {
  ok(USERS_CODE.includes('roleHasLicence(userItem.role)'),
    'every role is offered a CS registration button');
  ok(USERS_CODE.includes('openCsModal(userItem)'), 'the button opens nothing');
});

// ── 4. WHAT THE SCREEN MUST SAY ─────────────────────────────────────────────

check('it says a de-selection retires rather than deletes', () => {
  // The row is the provenance of every log filed under it. An admin unticking
  // a box must not believe he is erasing a compliance record — nor that he is
  // leaving the registration in force.
  ok(/retires that registration/i.test(USERS),
    'the modal does not say what unticking does');
  ok(/stay attributable/i.test(USERS),
    'the modal does not say the record is kept');
});

check('it names the registrations this screen cannot touch', () => {
  // A row on a project he is not assigned to cannot appear in the picker, and
  // the server deliberately leaves it alone. Without this the list would
  // silently omit a live registration and read as the whole truth.
  ok(USERS_CODE.includes('registered_elsewhere'),
    'the modal ignores registrations outside his assignments');
});

check('it says why Save is blocked with no licence number', () => {
  // WHITESPACE-INSENSITIVE. The sentence is wrapped across JSX source lines,
  // so a literal-space regex matches the intent and not the file — the first
  // version of this assertion went red on a line break while the copy was
  // exactly right.
  const flat = USERS.replace(/\s+/g, ' ');
  ok(/one-job rule is checked on the licence number/i.test(flat),
    'a 422 the admin has to decode is the only explanation');
});

check('the one-job warning is surfaced and not swallowed', () => {
  const save = body(USERS_CODE, 'const handleSaveCsRegistrations =');
  ok(save.includes('conflict_warnings'), 'the conflict warning is dropped');
  ok(/toast\.error\('One-job rule'/.test(save),
    'the conflict warning is not shown to the admin');
});

// ── 5. THE OLD TAB IS NARROWED, NOT SILENTLY LEFT AS A TWIN ─────────────────
//
// The ruling was to retire it once an external-superintendent entry exists on
// the project screen. That entry is not built, so the tab stays — and the one
// thing that must not happen meanwhile is two screens offering the same job
// with nothing saying which to use.

check('the tab names the case it is kept for', () => {
  ok(/no LeveLog account/i.test(TAB), 'the tab does not say who it is for');
  ok(/joint site/i.test(TAB), 'the tab does not name the joint-site case');
});

check('the tab points at User Management for everyone else', () => {
  ok(/User Management/i.test(TAB),
    'an admin is left to guess which of the two screens to use');
});

check('the tab records that retiring it is still owed', () => {
  ok(/[Rr]etiring this tab is owed/.test(TAB),
    'nothing in the file says the tab is on its way out');
});

check('the dashboard tile no longer reads as the main superintendent screen', () => {
  ok(!/title: 'Superintendents'/.test(DASH),
    'the tile still claims to be THE superintendent screen');
  ok(/Outside supers/.test(DASH), 'the tile does not name the narrowed case');
  ok(/admin\/superintendent/.test(DASH), 'the tile no longer reaches the screen');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
