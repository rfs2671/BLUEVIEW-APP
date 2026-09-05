/**
 * THE TRAINER ON AN ORIENTATION IS PICKED. HE IS NOT TYPED BY DEFAULT.
 *
 * `cp_name` on a subcontractor orientation is the §3301.2 attestation that a
 * named COMPETENT PERSON delivered the training. It is the one log type of
 * eleven where that name is not derived server-side — the trainer may
 * legitimately differ from the man filing — so it was a free-text box, and the
 * box is on the record: 219 filed documents carry the CP's name as the
 * lowercase string "michael" where his account holds "Michael Cespedes", and
 * 25 more carry the digit "2".
 *
 * "2" is the assertion this file is really about. No normaliser anywhere could
 * repair it into a name, because it never was one; it is a keystroke that was
 * filed as evidence that a named competent person gave safety training. So the
 * fix is upstream, the same one `+ Add Row` got on the pre-shift sheet:
 *
 *   1. the default path is a PICK, and the name comes off a company account
 *      spelled the way that account spells it;
 *   2. free text survives ONE TAP FURTHER IN, inside the picker — nothing
 *      blocks a filing, because a subcontractor's competent person may have
 *      delivered the orientation and have no account here;
 *   3. a FAILED READ IS NOT AN EMPTY LIST — offline must never render as "no
 *      competent persons exist", which is a claim about the company and would
 *      push the CP straight back to the keyboard;
 *   4. NO IDENTITY REFERENCE IS WRITTEN ONTO THE DOCUMENT. Unlike the
 *      pre-shift row, which carries worker_id, the picked account's id stays
 *      in component state: the 244 documents already filed could never carry a
 *      cp_user_id, so an absent one would mean either "typed by hand" or
 *      "filed before the field existed". Absent-versus-empty, declined here
 *      for the same reason it was declined there.
 *
 * AND BOTH ENTRY POINTS ARE COVERED. This screen sets cp_name in two places —
 * the create form and the inline panel that signs an existing orientation and
 * FREEZES it. Fixing one would have left the defect class alive on the same
 * screen.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const PICKER = path.join(ROOT, 'src', 'components', 'CompetentPersonPicker.jsx');
const SCREEN = path.join(ROOT, 'app', 'logbooks', 'subcontractor_orientation.jsx');
const PAD = path.join(ROOT, 'src', 'components', 'SignaturePad.js');

let failures = 0;
function ok(name, cond, detail) {
  if (cond) { console.log(`  ok  ${name}`); return; }
  failures += 1;
  console.error(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
}

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

function readOrNull(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (_e) { return null; }
}

function bail(msg) {
  console.error(`\ncompetentPersonPicker: ${msg}`);
  process.exit(1);
}

// ── THE NON-EMPTY GUARD ─────────────────────────────────────────────────────
// Every assertion below is a regex or a slice over these three files. A missing
// or truncated file would satisfy the absence-shaped ones vacuously and report
// a pass over nothing, so the sizes are asserted before anything is read into a
// pattern. A DELETED PICKER IS THE FAILURE THIS CATCHES: without it, "no
// provenance field is written onto the document" passes loudest of all.
const pickerSrc = readOrNull(PICKER);
const screenSrc = readOrNull(SCREEN);
const padSrc = readOrNull(PAD);

ok('the picker component exists', pickerSrc !== null, `${PICKER} is not readable`);
ok('the orientation screen exists', screenSrc !== null, `${SCREEN} is not readable`);
ok('SignaturePad exists', padSrc !== null, `${PAD} is not readable`);
if (pickerSrc === null || screenSrc === null || padSrc === null) {
  bail('a file under test is missing — nothing below could mean anything');
}
ok('the picker is not a stub', pickerSrc.length > 2000, `only ${pickerSrc.length} bytes`);
ok('the screen is not a stub', screenSrc.length > 20000, `only ${screenSrc.length} bytes`);

// ── THE PICKER'S DATA RULES, EXECUTED ───────────────────────────────────────
// Lifted and run rather than grepped: who the CP is shown, and whether two
// accounts for one man both survive, are BEHAVIOUR. A regex over the source
// would assert spelling.
//
// NO TRANSPILER, the same constraint workerPicker.test.cjs works under: these
// are plain ES with no JSX, so they run as written once `export` is dropped.
// @babel/preset-env is not installed, and a test that needs an absent preset
// fails on its harness instead of on its subject.
function slice(src, from, to) {
  const a = src.indexOf(from);
  const b = src.indexOf(to);
  if (a < 0 || b < 0 || b <= a) return null;
  return src.slice(a, b);
}

const rolesSrc = slice(pickerSrc,
  'export const TRAINER_ELIGIBLE_ROLES',
  'export async function fetchCompetentPersons');
const sameSrc = slice(pickerSrc,
  'export function isSamePerson',
  'export function filterCompetentPersons');
const filterSrc = slice(pickerSrc,
  'export function filterCompetentPersons',
  'export default function CompetentPersonPicker');

ok('the eligibility rule is present to lift', rolesSrc !== null);
ok('the identity rule is present to lift', sameSrc !== null);
ok('the filter is present to lift', filterSrc !== null);
if (rolesSrc === null || sameSrc === null || filterSrc === null) {
  bail('could not lift the picker\'s data rules — the behaviour tests cannot run');
}

const mod = { exports: {} };
const TAIL = '\n;module.exports = { TRAINER_ELIGIBLE_ROLES, isTrainerEligible, '
  + 'isSamePerson, filterCompetentPersons };';
// eslint-disable-next-line no-new-func
new Function('module', 'exports',
  (rolesSrc + sameSrc + filterSrc).replace(/^export /gm, '') + TAIL)(mod, mod.exports);
const { isTrainerEligible, isSamePerson, filterCompetentPersons } = mod.exports;

// WHO MAY BE NAMED AS THE TRAINER. A laborer is not a competent person and a
// provisioned tablet is not a man; naming either in a §3301.2 attestation
// would be a worse defect than the typing this replaces.
ok('a competent person is eligible', isTrainerEligible({ role: 'cp' }) === true);
ok('a superintendent is eligible', isTrainerEligible({ role: 'superintendent' }) === true);
ok('an owner is eligible', isTrainerEligible({ role: 'owner' }) === true,
  'self-serve signup makes every founding account an owner — excluding them '
  + 'would empty the list for a small company and push the CP to type');
ok('an admin is eligible', isTrainerEligible({ role: 'admin' }) === true);
ok('a WORKER is not eligible', isTrainerEligible({ role: 'worker' }) === false,
  'a laborer named as the man who delivered the orientation is a false '
  + 'attestation, not a spelling improvement');
ok('a SITE DEVICE is not eligible', isTrainerEligible({ role: 'site_device' }) === false,
  'a provisioned tablet cannot deliver an orientation');
ok('an unknown role is not eligible', isTrainerEligible({ role: 'ssc' }) === false);
ok('a roleless row is not eligible', isTrainerEligible({}) === false);
ok('a null row does not throw', isTrainerEligible(null) === false);

const PEOPLE = [
  { id: 'u1', name: 'Michael Cespedes', email: 'michael@arkon.com', role: 'cp' },
  { id: 'u2', name: 'Michael Cespedes', email: 'm.cespedes@arkon.com', role: 'cp' },
  { id: 'u3', name: 'Jose Castaneda', email: 'jose@arkon.com', role: 'superintendent' },
  { id: 'u4', name: 'Segundo Pilamunga', email: 'segundo@aaz.com', role: 'owner' },
];

ok('an empty query shows everyone', filterCompetentPersons(PEOPLE, '').length === 4);
ok('it matches on name', filterCompetentPersons(PEOPLE, 'segundo').length === 1);
ok('it matches on email', filterCompetentPersons(PEOPLE, 'aaz.com').length === 1);
ok('it is case-insensitive', filterCompetentPersons(PEOPLE, 'MICHAEL').length === 2);

// THE SAME RULING AS THE WORKER PICKER, AND IT HOLDS FOR ACCOUNTS TOO. Two
// accounts for one man both survive a query matching both. The CP is the only
// person who knows they are the same man, and a picker that showed one would
// perform in the UI a merge nothing downstream is permitted to make.
ok('BOTH accounts for one man survive a query matching both',
  filterCompetentPersons(PEOPLE, 'cespedes').length === 2,
  'the picker collapsed a duplicate account');

// The other direction: it must actually filter, or every assertion above is
// satisfied by a function that returns its input.
ok('a query that matches nobody returns nothing',
  filterCompetentPersons(PEOPLE, 'zzzz').length === 0);
ok('and it is not just returning the input array',
  filterCompetentPersons(PEOPLE, 'segundo')[0].name === 'Segundo Pilamunga');
ok('a null list does not throw', filterCompetentPersons(null, 'x').length === 0);

// ── "IS THIS ME", WHICH DECIDES WHETHER THE PROFILE IS WRITTEN ──────────────
// autoSave stores cp_name AND the signature CREDENTIAL as the device user's
// reusable profile. Getting this wrong in one direction costs a convenience
// refresh; in the other it stores another man's name and the signature drawn
// by his hand as this user's own.
const ME = { id: 'u1', _id: 'u1', email: 'michael@arkon.com', name: 'Michael Cespedes' };

ok('picking yourself is recognised by id',
  isSamePerson({ id: 'u1', email: 'x@y.com' }, ME) === true);
ok('picking someone else is not', isSamePerson({ id: 'u9', email: 'j@arkon.com' }, ME) === false);

// THE ID SPELLINGS DO NOT ALWAYS LINE UP. company-roster returns the
// stringified Mongo _id; the auth user is whatever /auth/me returned, and this
// app reads it as BOTH `id` and `_id` elsewhere. A CP who picks HIMSELF must
// not quietly stop getting his own profile saved over that.
ok('an account carrying only _id still matches',
  isSamePerson({ id: 'u1' }, { _id: 'u1' }) === true);
ok('email is the third key when no id lines up',
  isSamePerson({ id: 'abc', email: 'Michael@Arkon.com' }, { id: '', email: 'michael@arkon.com' }) === true,
  'a CP picking himself would otherwise lose his own profile refresh');
ok('and the email match is case- and space-insensitive',
  isSamePerson({ email: '  MICHAEL@ARKON.COM ' }, ME) === true);

// IT FAILS CLOSED. Unsure means "do not write the profile".
ok('two rows with nothing in common are not the same man',
  isSamePerson({ id: '', email: '' }, ME) === false);
ok('an empty id does not match an empty id',
  isSamePerson({ id: '' }, { id: '' }) === false,
  'blank-equals-blank would make every unidentifiable pick read as the filer');
ok('a null pick is not the filer', isSamePerson(null, ME) === false);
ok('a null account is not matched', isSamePerson({ id: 'u1' }, null) === false);

// ── THE PICKER'S REFUSALS ───────────────────────────────────────────────────
const picker = stripComments(pickerSrc);

ok('a failed read is not shown as an empty list',
  /setFailed\(true\)/.test(picker) && /Could not load/.test(picker),
  'offline would otherwise read as "no competent persons exist" — a claim '
  + 'about the company — and push the CP to type, which is the exact thing '
  + 'this component exists to prevent');
ok('offline and empty are distinguishable states',
  /!failed && rows\.length === 0/.test(picker),
  'the "none registered" copy must be reachable only when the server answered');
ok('the source is the company roster',
  /usersAPI\.companyRoster\(\)/.test(picker));
ok('free text is reachable from inside the picker',
  /onManual/.test(picker));

// ── THE SCREEN'S WIRING ─────────────────────────────────────────────────────
const screen = stripComments(screenSrc);

ok('the picker is imported',
  /from '\.\.\/\.\.\/src\/components\/CompetentPersonPicker'/.test(screen));

// BOTH ENTRY POINTS. This screen writes cp_name in two places and each one
// files the same §3301.2 attestation onto the same document.
const pickerMounts = (screen.match(/<CompetentPersonPicker/g) || []).length;
ok('the picker is mounted at BOTH places cp_name is set', pickerMounts === 2,
  `found ${pickerMounts} — the create form and the inline sign panel each set `
  + 'cp_name, and fixing one leaves the defect class alive on the same screen');

ok('a picked trainer\'s name comes off the record',
  /setNewCpName\(person\.name/.test(screen),
  'without this the pick is decoration and the keyboard is still the source');
ok('and the inline sign panel takes its name off the record too',
  /setCpName\(person\.name/.test(screen));

// THE NAME BOX IS SHUT BY DEFAULT. An open TextInput sitting under the picked
// name would leave free text at zero taps and the pick at one, which is the
// wrong way round.
const lockMounts = (screen.match(/nameLocked=\{!/g) || []).length;
ok('the signer name box is locked at both pads', lockMounts === 2,
  `found ${lockMounts}`);
ok('SignaturePad honours the lock',
  /isSigned \|\| nameLocked/.test(stripComments(padSrc)),
  'the prop is passed but the pad still renders an open TextInput');
ok('and the lock defaults to false for the other twelve mounters',
  /nameLocked = false/.test(padSrc),
  'a default of true would silently freeze the name field on every other '
  + 'screen that signs');

// NOTHING BLOCKS A FILING. Free text is moved, not removed.
ok('free text is still reachable on the create form',
  /const enterTrainerByHand = /.test(screen));
ok('and taking it unlocks the name box',
  /enterTrainerByHand[\s\S]{0,200}setTrainerManual\(true\)/.test(screen));
ok('the inline panel has the same escape',
  /setManual\(true\)/.test(screen));

// ── NO PROVENANCE FIELD ON THE FILED DOCUMENT, per ruling ───────────────────
// Asserted over the payload the screen actually posts, not over the whole file
// — the picked id lives in component state on purpose and naming it here would
// be a spelling test.
const created = screen.slice(screen.indexOf('const handleCreateNew'),
  screen.indexOf('const toggleNewChecklistItem'));
ok('the create path is present to inspect', created.length > 500);
for (const banned of ['cp_user_id', 'cp_name_source', 'trainer_id', 'entered_manually', 'provenance']) {
  ok(`no ${banned} field is filed on the document`, !created.includes(banned),
    'the 244 documents already filed could never carry it, so an absent value '
    + 'would mean either "typed" or "filed before the field existed"');
}

// ── THE FILER'S PROFILE IS NOT THE TRAINER'S ────────────────────────────────
// autoSave writes cp_name AND the signature CREDENTIAL back as this device
// user's reusable profile, which pre-fills every logbook he opens next. Making
// "name another man" the easy path without this guard would have stored a
// trainer's name — and a signature drawn by the trainer's hand — as the
// filer's own, with nothing on screen saying so.
ok('the create path guards the profile write-back',
  /if \(trainerIsSelf\(\)\) \{\s*await autoSave/.test(screen),
  'a picked trainer\'s name would otherwise become the filer\'s saved profile');
ok('an unpicked name still saves the profile exactly as before',
  /!trainerPicked \|\| isSamePerson\(trainerPicked, user\)/.test(screen),
  'the ordinary case — the filer is the trainer — must not change behaviour');
ok('the inline sign panel guards it too',
  /if \(!picked \|\| isSamePerson\(picked, user\)\) \{\s*await innerAutoSave/.test(screen));

// ONE RULE, NOT TWO. Both halves of this screen ask "is this me", and a screen
// whose halves disagreed would write the profile on one path and not the other.
ok('both guards call the same shared rule',
  (screen.match(/isSamePerson\(/g) || []).length === 2
  && /import CompetentPersonPicker, \{ isSamePerson \}/.test(screen),
  'the identity rule must not be hand-rolled twice');

if (failures) {
  console.error(`\ncompetentPersonPicker: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
