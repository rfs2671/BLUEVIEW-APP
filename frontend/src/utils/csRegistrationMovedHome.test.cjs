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
const DASH = read('app', 'index.jsx');
const DASH_CODE = CODE(DASH);
const SMOKE = read('scripts', 'smoke-mount.cjs');

/** THE TAB IS GONE, SO IT IS NOT READ AT MODULE LOAD ANY MORE. This was
 *  `read('app','admin','superintendent.jsx')` at the top of the file, which
 *  after the deletion throws ENOENT and aborts the whole run — fourteen
 *  assertions lost to report one. Existence is now a question an assertion
 *  asks, not a precondition of the file loading. */
const exists = (...p) => fs.existsSync(path.join(FRONTEND, ...p));

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

check('it says why Save is blocked with no registration number', () => {
  // WHITESPACE-INSENSITIVE. The sentence is wrapped across JSX source lines,
  // so a literal-space regex matches the intent and not the file — the first
  // version of this assertion went red on a line break while the copy was
  // exactly right.
  const flat = USERS.replace(/\s+/g, ' ');
  // "REGISTRATION", NOT "LICENCE": DOB issues a construction superintendent
  // a registration number (operator's ruling, 2026-10-08).
  ok(/one-job rule is checked on the registration number/i.test(flat),
    'a 422 the admin has to decode is the only explanation');
});

check('a refusal that carries {code, message} shows the message', () => {
  // 409 CS_LOG_IS_ON: unassigning the only registration on a project whose
  // superintendent log is on. Its detail is an object; passing it to the
  // toast whole printed "[object Object]".
  ok(/detail\?\.code === 'CS_LOG_IS_ON'/.test(USERS),
    'the save handler does not recognise the live-log refusal');
  ok(/typeof detail === 'string' \? detail : detail\?\.message/.test(USERS),
    'the save handler hands an object detail to the toast');
});

check('the one-job warning is surfaced and not swallowed', () => {
  const save = body(USERS_CODE, 'const handleSaveCsRegistrations =');
  ok(save.includes('conflict_warnings'), 'the conflict warning is dropped');
  ok(/toast\.error\('One-job rule'/.test(save),
    'the conflict warning is not shown to the admin');
});

// ── 5. THE OLD TAB IS GONE, AND REGISTRATION HAS ONE DOOR ───────────────────
//
// ── WHAT THIS SECTION USED TO ASSERT, AND WHOSE RULING CHANGED IT ──────────
//
// It asserted the tab was NARROWED rather than removed — four checks:
//
//     'the tab names the case it is kept for'        /no LeveLog account/i
//                                                    /joint site/i      on TAB
//     'the tab points at User Management ...'        /User Management/i on TAB
//     'the tab records that retiring it is still owed'
//                                        /[Rr]etiring this tab is owed/ on TAB
//     'the dashboard tile no longer reads as the main superintendent screen'
//                                        /Outside supers/ AND
//                                        /admin\/superintendent/ on DASH
//
// The reasoning was recorded here and it was: the ruling was to retire the tab
// once an external-superintendent entry existed on the project screen; that
// entry was not built, so the tab stayed, and meanwhile the one thing that
// must not happen was two screens offering the same job with nothing saying
// which to use.
//
// OPERATOR RULING, 2026-10-08, AND IT WITHDRAWS THE CASE ITSELF rather than
// declaring the owed section built: "OUTSIDE SUPERS: DELETE THE TAB. There is
// no such case. A superintendent with no account cannot file any logbook, so
// recording one serves nothing. Zero such registrations exist platform-wide."
// The census agreed: ONE cs_registrations row exists, on 588 Thomas S Boyland,
// linked to a `superintendent` account. Zero unlinked rows, ever.
//
// SO THE ASSERTION INVERTS. The two that pinned the tab's copy and the one
// that pinned the tile's label can have no subject; what replaces them is the
// stronger claim the four of them were a proxy for — THERE IS ONE DOOR, and it
// is the one sections 1 to 4 above test. Those are untouched: every assertion
// about the seed, the licence never being sent, the role gate and the copy
// stands exactly as written, because what moved is where the registration is
// made and not how.
//
// WHAT THE SERVER KEEPS, DELIBERATELY, AND IT IS NOT TESTED HERE: the
// `cs_registrations` collection, `_register_cs_on_project`, the BC 3301.13.13
// filing gate, the activation gate and `cs_attribution_for` are all unchanged.
// Michael Cespedes's 588 Thomas registration still governs who may file, and
// that is asserted on the server side, where the gate is —
// backend/tests/test_the_registration_still_governs.py.

check('the outside-supers screen is gone', () => {
  ok(!exists('app', 'admin', 'superintendent.jsx'),
    'app/admin/superintendent.jsx is still here — a second place to make a '
    + 'registration, which is the condition sections 1-4 exist to rule out');
});

check('the dashboard tile is gone', () => {
  // BOTH HALVES. A tile whose label was dropped but whose path survived would
  // leave the route linked from the grid under a neighbour's name; a path
  // dropped with the label left behind renders a tile that navigates nowhere.
  //
  // ON DASH_CODE, NOT DASH, AND THIS ASSERTION FOUND OUT WHY ON ITS CONTROL
  // RUN. It read the raw source first and went red on the removal itself: the
  // comment left in app/index.jsx where the tile was says "NO 'Outside supers'
  // TILE", exactly as the Device Check removal's does, so a raw scan counted
  // the sentence recording the deletion as the thing deleted. The subject is
  // the code.
  ok(!/Outside supers/.test(DASH_CODE),
    'the "Outside supers" tile is still here');
  ok(!/admin\/superintendent/.test(DASH_CODE),
    'the dashboard still routes to admin/superintendent');
  // And the label it carried BEFORE it was narrowed must not come back as the
  // repair — that is the twin this file's sections 1-4 were written against.
  ok(!/title: 'Superintendents'/.test(DASH_CODE),
    'the tile came back under its original name');
});

check('no screen navigates to admin/superintendent any more', () => {
  // A ROUTE WITH NO LINK IS NOT SHIPPED, and the converse is what this asks: a
  // link with no route mounts the unmatched screen. app/index.jsx is checked
  // above by name; this is every other file under app/, so a second entry
  // point added anywhere fails here rather than at a tap.
  const offenders = [];
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { walk(full); continue; }
      if (!/\.(jsx?|tsx?)$/.test(e.name)) continue;
      // COMMENTS STRIPPED. Several files below name the deleted screen in
      // prose as the example of a UI pattern — FormSheet.jsx and users.jsx
      // both do — and a banned-path scan that counted those would be
      // measuring the comment saying it was removed.
      const src = CODE(fs.readFileSync(full, 'utf8'));
      if (/admin\/superintendent/.test(src)) {
        offenders.push(path.relative(FRONTEND, full));
      }
    }
  };
  walk(path.join(FRONTEND, 'app'));
  ok(offenders.length === 0,
    `these still reach the deleted screen: ${offenders.join(', ')}`);
});

check('no icon import is orphaned by the removed tile', () => {
  // `HardHat` was imported by app/index.jsx FOR THAT TILE AND NOTHING ELSE —
  // unlike `Smartphone`, which the Device Check removal deliberately kept
  // because the Site Devices tile shares it. An unused lucide import is not a
  // crash, which is why a mount smoke cannot catch it.
  const uses = (DASH_CODE.match(/\bHardHat\b/g) || []).length;
  ok(uses === 0,
    `HardHat is still named ${uses} time(s) in app/index.jsx with no tile `
    + 'left to use it');
});

// ── 6. csUserPicker.test.cjs WENT WITH THE SCREEN, AND WHAT IT SAID ─────────
//
// That file read `app/admin/superintendent.jsx` at module load and tested the
// picker that linked a registration to an account — nineteen assertions in five
// sections: the link is written on create AND on edit ('' never sent as an id);
// no role filter on the user list; three link states on the card (unlinked,
// dangling, linked) each with its own colour token; no default selection, email
// beside every name, a failed user load stated rather than rendered as an empty
// list; and the three-way destructure of its Promise.all.
//
// IT IS DELETED RATHER THAN RE-POINTED, because its subject was the PICKER —
// choosing WHICH account a registration names — and that is precisely the
// capability the ruling withdraws. There is no second file to aim it at.
//
// TWO OF ITS CLAIMS SURVIVE AS SERVER RULES, and they are asserted where the
// rule now lives, not restated here:
//
//   THE LINK IS ALWAYS WRITTEN. `set_user_cs_registrations` passes
//   `user_id=str(user_id)` unconditionally, so User Management cannot produce
//   the unlinked row the picker made possible. Asserted in
//   backend/tests/test_the_registration_still_governs.py.
//
//   NO ROLE FILTER — AND THIS ONE IS NOW VIOLATED BY THE SURVIVING PATH, which
//   is recorded here because it is a consequence of the deletion and not a
//   defect introduced by it. That file's header said filtering by role "would
//   hide the one person this control exists to link — the same mistake as
//   gating the log on role == 'superintendent'".
//   `_assert_superintendent_under_admin` 422s unless `role == "superintendent"`,
//   and a non-superintendent account cannot hold `dob_superintendent_number`
//   (popped on create, refused on update), so User Management can register ONLY
//   a `superintendent`-role account. The filing gate itself is unchanged and
//   still keys on the registration rather than the role. Michael Cespedes holds
//   `superintendent` today so the live case is covered; PR #683 is the
//   affordance for promoting a CP into the role.

check('the mount smoke carries no route for the deleted screen', () => {
  // IT NEVER DID, and that is the assertion. The ruling expected this list to
  // lose an entry and drop from 38 paths / 76 mounts; `/admin/superintendent`
  // was never in ROUTES, so the count is UNCHANGED at 38/76 and the screen
  // never had an executed mount in CI. Pinned from the absent side so that
  // re-adding the path — which after the deletion fails the job outright, the
  // way /admin/device-capabilities did at 76/78 — is caught here first.
  ok(!/admin\/superintendent/.test(CODE(SMOKE)),
    'the smoke list routes at a screen that does not exist; it will mount the '
    + 'unmatched screen and fail the job');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
