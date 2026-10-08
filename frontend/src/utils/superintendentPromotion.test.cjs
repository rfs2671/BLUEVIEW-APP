/**
 * THE ON-RAMP TO THE ROLE GATE, AND THE PROMISES THE CONFIRMATION MAKES.
 *
 * ── WHAT IS BEING TESTED, AND WHY IT IS NOT "A BUTTON APPEARS" ──────────────
 *
 * `_assert_superintendent_under_admin` refuses a CS registration unless the
 * account holds `role == "superintendent"`, and it says so: "Change the role
 * first." The gate is correct and it stays. What was missing was a PATH: on a
 * cp row User Management showed no Registration control and no hint that a role
 * change was the thing standing in the way.
 *
 * The affordance is three lines of wiring. THE SUBSTANCE IS THE SENTENCES IT
 * SHOWS FIRST, because promotion is not a free tick-box — the account loses
 * powers, gains a background download, and has its project list taken over by
 * Registration. An admin who reads a cheerful confirmation and taps it has made
 * a change he can only partly undo.
 *
 * ── SO EVERY CLAIM IN THE COPY IS ASSERTED AGAINST THE CODE THAT MAKES IT ───
 *
 * This is the point of the file. Section 4 does not check that the copy is
 * well-written; it checks that each thing the copy TELLS AN ADMIN WILL HAPPEN
 * is still true of backend/server.py, backend/lib/notifications.py and
 * app/_layout.jsx. Add `superintendent` to `_PENDING_LINK_ROLES` and this file
 * fails, naming the sentence that has become a lie — which is the only way a
 * hand-audited list of consequences does not quietly expire.
 *
 * WHAT WOULD MAKE THIS FAIL, deliberately:
 *   - the role gate being relaxed instead of satisfied (section 2),
 *   - the promotion PATCH growing an `assigned_projects` field, which the
 *     server 422s in the same breath as the role (section 3),
 *   - the ordinary role editor being removed, making promotion one-way (5),
 *   - any of the five consequences in the copy ceasing to be true (4).
 *
 * Run:  node src/utils/superintendentPromotion.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');

function readOrNull(...p) {
  try {
    return fs.readFileSync(path.join(...p), 'utf8').split('\r\n').join('\n');
  } catch (_e) {
    return null;
  }
}

/**
 * JS/JSX WITH THE PROSE REMOVED.
 *
 * This codebase comments heavily and on purpose, and an assertion over raw
 * source counts the comment that SAYS a thing was done as the thing being done.
 * `(?<!:)` keeps `https://` out of the line-comment pattern.
 */
const JS_CODE = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

/**
 * PYTHON WITH THE PROSE REMOVED — DOCSTRINGS INCLUDED, AND THEY ARE THE REASON.
 *
 * `_refuse_if_not_the_superintendent`'s own docstring contains the string
 * `role == "superintendent"` in order to explain that the gate is NOT that. An
 * absence assertion over the raw file would read that explanation as the defect
 * it warns about.
 */
const PY_CODE = (src) => src
  .replace(/"""[\s\S]*?"""/g, '')
  .replace(/^\s*#.*$/gm, '');

const SERVER_RAW = readOrNull(REPO, 'backend', 'server.py');
const NOTIFS_RAW = readOrNull(REPO, 'backend', 'lib', 'notifications.py');
const USERS_RAW = readOrNull(FRONTEND, 'app', 'admin', 'users.jsx');
const LAYOUT_RAW = readOrNull(FRONTEND, 'app', '_layout.jsx');

let failures = 0;
const ok = (label, cond, hint) => {
  if (cond) { console.log(`  ok  ${label}`); return; }
  failures += 1;
  console.log(`FAIL  ${label}${hint ? `\n        ${hint}` : ''}`);
};

/**
 * The slice of a python file that is one function body.
 *
 * ANCHORED ON BOTH ENDS, because a leftmost-match regex over 60k lines of
 * server.py answers about whichever occurrence comes first — the failure mode
 * the suite has already been bitten by. A slice that could not be located is
 * reported rather than silently yielding '' and passing every absence test in
 * it.
 */
function pyFunction(src, name, label) {
  const start = src.indexOf(`async def ${name}(`) >= 0
    ? src.indexOf(`async def ${name}(`)
    : src.indexOf(`def ${name}(`);
  ok(`ANCHOR: ${label} was located in server.py`, start > 0);
  if (start <= 0) return '';
  const rest = src.slice(start + 10);
  const nextDef = rest.search(/\n(?:@api_router|async def |def )/);
  const body = nextDef > 0 ? rest.slice(0, nextDef) : rest;
  ok(`ANCHOR: ${label} is non-empty (${body.length} chars)`, body.length > 200);
  return body;
}

console.log('\n-- 1. the subjects exist at all --');
ok('ANCHOR: backend/server.py is readable', !!SERVER_RAW && SERVER_RAW.length > 100000);
ok('ANCHOR: backend/lib/notifications.py is readable', !!NOTIFS_RAW);
ok('ANCHOR: app/admin/users.jsx is readable', !!USERS_RAW && USERS_RAW.length > 10000);
ok('ANCHOR: app/_layout.jsx is readable', !!LAYOUT_RAW && LAYOUT_RAW.length > 10000);

const SERVER = PY_CODE(SERVER_RAW || '');
const NOTIFS = PY_CODE(NOTIFS_RAW || '');
const USERS = JS_CODE(USERS_RAW || '');
const LAYOUT = JS_CODE(LAYOUT_RAW || '');

const COPY = loadEsm('src/utils/superintendentPromotionCopy.js');
const VOCAB = loadEsm('src/utils/roleVocabulary.js');

const BODY = COPY.promoteToSuperintendentBody('Michael Cespedes', {
  hasLicenceNumber: false,
});
const BODY_WITH_LICENCE = COPY.promoteToSuperintendentBody('Michael Cespedes', {
  hasLicenceNumber: true,
});

console.log('\n-- 2. THE GATE IS SATISFIED, NOT WEAKENED --');
{
  // The whole ruling is that no backend code changes. If the 422 this screen
  // now gives the admin a way to satisfy were ever relaxed, the affordance
  // would be a second, worse path to a door standing open — and this file is
  // the only place that reads both sides.
  const gate = pyFunction(SERVER, '_assert_superintendent_under_admin',
    'the CS registration role gate');
  ok('the role gate still refuses a non-superintendent',
    /!=\s*ROLE_SUPERINTENDENT/.test(gate) && /status_code=422/.test(gate),
    'the gate was relaxed instead of satisfied — the on-ramp is now pointless '
    + 'and the licence/registration coupling below it is unguarded');
  ok('and it still tells the admin to change the role first',
    /Change the/.test(gate) && /role first/.test(gate),
    'the affordance exists to answer this exact sentence');

  const setter = pyFunction(SERVER, 'set_user_cs_registrations',
    'the registration writer');
  ok('a registration still requires a DOB number on the account',
    /dob_superintendent_number/.test(setter) && /status_code=422/.test(setter),
    'if this went away the copy must stop telling the admin to record one');
}

console.log('\n-- 3. THE PROMOTION PATCH CARRIES THE ROLE AND NOTHING ELSE --');
{
  // THIS IS THE ONE THAT BITES. `update_admin_user` derives `_target_role` from
  // `update_data.get("role") or existing_user.get("role")`, so a single PATCH
  // that sets role=superintendent AND assigned_projects is refused 422 — the
  // role it validates against is the one being WRITTEN, not the stored one.
  const put = pyFunction(SERVER, 'update_admin_user', 'the user update route');
  ok('ANCHOR: the route still refuses assigned_projects for this role',
    /_target_role\s*==\s*ROLE_SUPERINTENDENT/.test(put)
    && /status_code=422/.test(put),
    'if this refusal is gone the assertion below is checking nothing');
  ok('and it decides that from the role being WRITTEN, not the stored one',
    /_target_role\s*=\s*str\(\s*\n?\s*update_data\.get\("role"\)/.test(put)
      || /update_data\.get\("role"\)\s*or\s*existing_user\.get\("role"\)/.test(put),
    'the one-patch hazard this test exists for depends on this');

  const patch = USERS.match(/adminUsersAPI\.update\(\s*[A-Za-z.?]+\s*,\s*\{[^}]*\}/g) || [];
  const promote = patch.filter((p) => /ROLE_SUPERINTENDENT/.test(p));
  ok('the screen sends a promotion patch at all', promote.length === 1,
    `expected exactly one role-only update call, found ${promote.length}`);
  ok('and it carries no other field',
    promote.length === 1 && !/assigned_projects|dob_|name:|email:/.test(promote[0]),
    'a patch that sets the role AND assigned_projects is 422d by the server, '
    + 'so the admin would see a refusal about projects he never touched');

  // ── AND THE HAND-OFF CANNOT LAND ON THE WRONG ACCOUNT ───────────────────
  //
  // The promotion opens the Edit sheet and, on save, the Registration sheet.
  // That hand-off is remembered across one sheet, and a REMEMBERED INTENT THAT
  // ONLY SAYS "YES" is one that can be spent on whatever comes next — here, a
  // CS Registration sheet opening on an unrelated account the admin edited
  // afterwards. It holds the id and the hand-off compares it.
  ok('the Edit→Registration hand-off is keyed on the account, not a boolean',
    /setRegisterAfterEdit\(userItem\.id\)/.test(USERS)
    && /chained === chainTarget\.id/.test(USERS),
    'a boolean can only say that some promotion once happened');
  ok('and nothing sets it to a bare true',
    !/setRegisterAfterEdit\(true\)/.test(USERS));
}

console.log('\n-- 4. EVERY CONSEQUENCE THE COPY NAMES IS STILL TRUE --');
{
  // ── 4a. WHATSAPP ────────────────────────────────────────────────────────
  const link = SERVER.match(/_PENDING_LINK_ROLES\s*=\s*\(([^)]*)\)/);
  ok('ANCHOR: _PENDING_LINK_ROLES was located', !!link);
  ok('a superintendent cannot connect a WhatsApp group',
    !!link && !/superintendent/.test(link[1]) && /"cp"|'cp'/.test(link[1]),
    'the copy says he loses this; it must stop saying so');
  ok('and the copy says so', /WhatsApp/.test(BODY));

  // ── 4b. PLAN PREFETCH ───────────────────────────────────────────────────
  const prefetch = LAYOUT.match(/PLAN_PREFETCH_ROLES\s*=\s*new Set\(\[([^\]]*)\]\)/);
  ok('ANCHOR: PLAN_PREFETCH_ROLES was located', !!prefetch);
  ok('a superintendent prefetches plans and a cp does not',
    !!prefetch && /superintendent/.test(prefetch[1]) && !/'cp'/.test(prefetch[1]),
    'the copy warns about a background download that starts');
  ok('and the copy says so', /plans/i.test(BODY));

  // ── 4c. ASSIGN BECOMES REGISTRATION ─────────────────────────────────────
  ok('the copy names Registration as the replacement for Assign',
    /Registration/.test(BODY) && /Assign/.test(BODY));
  ok('and it warns that the first save REPLACES the project list',
    /replace|exactly the jobs|comes off/i.test(BODY),
    'set_user_cs_registrations writes assigned_projects = the registered set, '
    + 'so a promoted CP loses assignments he is not registered on');
  const setter = SERVER.slice(SERVER.indexOf('async def set_user_cs_registrations('));
  ok('ANCHOR: and the writer really does derive the whole list',
    /resulting\s*=\s*sorted\(\(\(current \| wanted\) - set\(removed\)\)/
      .test(setter.slice(0, 20000)),
    'if it merged with the existing assignments the warning is wrong');

  // ── 4d. THE EMERGENCY CHECK-IN POINT ────────────────────────────────────
  //
  // NOT IN THE OPERATOR'S LIST. A CP may mint and remove a provisional QR
  // check-in point on his own job for the day no chip will read; a
  // superintendent is neither a company admin nor a cp, so he loses it.
  const bootstrap = pyFunction(SERVER, 'bootstrap_checkin_point',
    'the emergency check-in point writer');
  const removal = pyFunction(SERVER, 'remove_cp_checkin_point',
    'the emergency check-in point removal');
  ok('an emergency check-in point is a company admin or a cp, nobody else',
    /role\s*!=\s*"cp"/.test(bootstrap) && /role\s*!=\s*"cp"/.test(removal)
    && !/superintendent/.test(bootstrap) && !/superintendent/.test(removal),
    'the copy says he loses this');
  ok('and the copy says so', /check-in point/.test(BODY));

  // ── 4e. EMAIL DOES NOT MOVE ─────────────────────────────────────────────
  const excluded = NOTIFS.match(/EMAIL_EXCLUDED_ROLES\s*=\s*frozenset\(\{([^}]*)\}\)/);
  ok('ANCHOR: EMAIL_EXCLUDED_ROLES was located', !!excluded);
  ok('both roles are excluded from email, so nothing moves',
    !!excluded && /"cp"/.test(excluded[1]) && /"superintendent"/.test(excluded[1]),
    'the copy tells the admin email is unchanged rather than leaving him to '
    + 'wonder; if one role leaves this set that sentence is wrong');
  ok('and the copy says so', /email/i.test(BODY));

  // ── 4f. THE FILING RIGHT DOES NOT MOVE — the reassuring half ────────────
  const refuse = pyFunction(SERVER, '_refuse_if_not_the_superintendent',
    'the BC 3301.13.13 filing gate');
  ok('the filing gate reads the registration and never the role',
    /_cs_filing_check\(/.test(refuse) && !/role/.test(refuse),
    'a role test here would make the copy\'s most important promise false — '
    + 'and would lock out the dual-capacity CP it was written for');
  ok('and the copy says the filing right does not move',
    /\bfile\b/.test(BODY) && /never by the role|not by the role/.test(BODY));

  // ── 4g. WHERE HE LANDS DOES NOT MOVE ────────────────────────────────────
  ok('both roles are held to the same paths',
    /const isCp = user\?\.role === 'cp' \|\| user\?\.role === 'superintendent'/
      .test(LAYOUT),
    'the copy tells the admin his screens do not change');
}

console.log('\n-- 5. REVERSIBLE, AND THE REVERSAL IS NOT FREE EITHER --');
{
  ok('the copy says the role can be set back',
    /set the role back|change the role back/i.test(BODY));
  ok('and that setting it back clears the licence fields',
    /clears|removes/i.test(BODY) && /expiry/i.test(BODY),
    'update_admin_user $unsets SUPERINTENDENT_LICENCE_FIELDS on demotion, so '
    + '"just set it back" is not a clean undo and must not read as one');
  const put = SERVER.slice(SERVER.indexOf('async def update_admin_user('));
  ok('ANCHOR: and the demotion really does unset them',
    /_unset_licence = \{\s*\n?\s*f: "" for f in SUPERINTENDENT_LICENCE_FIELDS/
      .test(put.slice(0, 12000)));
  ok('the ordinary role editor is still on the screen',
    /renderRolePicker\(\)/.test(USERS),
    'an affordance that replaced the role picker would be a one-way door');

  // ── AND THE OTHER PLACE THIS ROLE IS DESCRIBED SAYS THE SAME THING ──────
  //
  // The picker blurb read "Everything a CP has, plus the construction
  // superintendent log", which is false in three measured ways — the WhatsApp
  // group binding, the on-demand checklist and the emergency check-in point all
  // come off. An admin reading the blurb and an admin reading the confirmation
  // must not be told different things about one role; two wordings of one fact
  // is how they drift apart.
  const blurb = VOCAB.ASSIGNABLE_ROLES
    .find((r) => r.value === VOCAB.ROLE_SUPERINTENDENT).blurb;
  ok('the role picker does not claim a superintendent keeps every CP power',
    !/everything a cp/i.test(blurb),
    `the blurb overstates the role: "${blurb}"`);
  ok('and it names Registration as where his projects come from',
    /Registration/.test(blurb));
}

console.log('\n-- 6. OFFERED ONLY WHERE IT APPLIES --');
{
  ok('a cp can be made a superintendent',
    VOCAB.canBecomeSuperintendent('cp') === true);

  // ── THE SITE MANAGER IS EXCLUDED, AND IT IS THE COPY THAT EXCLUDES HIM ───
  //
  // This was written as "every role a company admin manages" and the
  // measurement below is what corrected it. THREE OF THE CONFIRMATION'S CLAIMS
  // ARE FALSE FROM `pm`, and the assertions that prove it are right here so the
  // exclusion cannot be read as arbitrary tidying and deleted as such.
  ok('a Site Manager is NOT offered it',
    VOCAB.canBecomeSuperintendent('pm') === false,
    'the confirmation states the consequences of promotion FROM cp');
  {
    const excluded = NOTIFS.match(/EMAIL_EXCLUDED_ROLES\s*=\s*frozenset\(\{([^}]*)\}\)/);
    ok('because a pm is NOT already excluded from email — his mail would start '
      + 'being suppressed, and the copy says email does not move',
    !!excluded && !/"pm"/.test(excluded[1]));
    const link = SERVER.match(/_PENDING_LINK_ROLES\s*=\s*\(([^)]*)\)/);
    ok('and a pm has no WhatsApp group binding to lose in the first place',
      !!link && !/"pm"|'pm'/.test(link[1]));
    const admins = SERVER.match(/COMPANY_ADMIN_ROLES\s*=\s*\(([^)]*)\)/);
    ok('and no emergency check-in point either: that is admin or cp, and a pm '
      + 'is neither',
    !!admins && !/"pm"|'pm'/.test(admins[1]));
  }

  ok('a superintendent is not offered it again',
    VOCAB.canBecomeSuperintendent('superintendent') === false);
  // A SITE DEVICE IS A TABLET BOLTED TO A HOARDING, NOT A PERSON, and the
  // server would NOT refuse this: assert_role_assignable_by validates the role
  // being written and asks nothing about the role being replaced. The client is
  // the only gate, which is exactly why it is tested.
  ok('a site device is not a person and is not offered it',
    VOCAB.canBecomeSuperintendent('site_device') === false);
  ok('nor is a demo account',
    VOCAB.canBecomeSuperintendent('demo') === false);
  ok('nor the retired owner role',
    VOCAB.canBecomeSuperintendent('owner') === false);
  ok('nor the retired worker role',
    VOCAB.canBecomeSuperintendent('worker') === false);
  // An admin promoted to superintendent would LOSE admin access — a single
  // role string holds one answer. That is a demotion wearing a promotion's
  // label and it is not what this control is for.
  ok('an admin is not offered it',
    VOCAB.canBecomeSuperintendent('admin') === false);
  ok('and an absent role answers no rather than throwing',
    VOCAB.canBecomeSuperintendent(null) === false
    && VOCAB.canBecomeSuperintendent('') === false
    && VOCAB.canBecomeSuperintendent(undefined) === false);
  ok('case and padding do not decide it',
    VOCAB.canBecomeSuperintendent('  CP ') === true);

  ok('the row asks the module rather than listing roles inline',
    /canBecomeSuperintendent\(/.test(USERS),
    'a hand-written role list in the JSX is the duplication roleVocabulary.js '
    + 'was extracted to end');
}

console.log('\n-- 7. THE ADMIN READS IT BEFORE IT HAPPENS --');
{
  ok('the body names the person',
    BODY.includes('Michael Cespedes'),
    'a confirmation about "this user" is one an admin cannot check');
  ok('the screen shows the body before the write',
    /promoteToSuperintendentBody\(/.test(USERS)
    && /window\.confirm\(/.test(USERS) && /Alert\.alert\(/.test(USERS),
    'the same two-platform shape the delete confirmation uses');
  // The next step is stated only when it IS the next step. A non-superintendent
  // account structurally holds no DOB number -- create pops the fields and the
  // demotion $unsets them -- so in practice this is always the case shown; the
  // other branch exists so a legacy row carrying one is not told to re-enter it.
  ok('with no DOB number on file, the copy says to record one',
    /registration number/i.test(BODY) && /one-job/i.test(BODY));
  ok('and with one on file it does not',
    !/record (his|the) DOB registration number/i.test(BODY_WITH_LICENCE),
    'advice to type a number that is already stored reads as a failed save');

  const changes = COPY.PROMOTION_CHANGES;
  const unchanged = COPY.PROMOTION_UNCHANGED;
  ok('the consequences are enumerable, not a paragraph',
    Array.isArray(changes) && Array.isArray(unchanged));
  ok('and both halves are present — what changes AND what does not',
    changes.length >= 4 && unchanged.length >= 3,
    `changes=${(changes || []).length} unchanged=${(unchanged || []).length}: `
    + 'a confirmation that lists only losses reads as a warning not to proceed');
  ok('every line is a sentence, not a fragment',
    [...changes, ...unchanged].every(
      (line) => typeof line === 'string' && line.length > 25 && /\.$/.test(line.trim()),
    ));
  ok('and every one of them reaches the body',
    [...changes, ...unchanged].every((line) => BODY.includes(line)),
    'a bullet defined and not rendered is a consequence nobody is told');
}

console.log(failures === 0
  ? '\nall passed'
  : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
