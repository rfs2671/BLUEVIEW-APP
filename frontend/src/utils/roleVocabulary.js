/**
 * THE ROLES USER MANAGEMENT OFFERS, AND WHAT EACH ONE IS CALLED ON SCREEN.
 *
 * ── WHY A MODULE AND NOT TWO LISTS OF BUTTONS ───────────────────────────────
 *
 * Because that is what it was, and the duplication is what went wrong. The Add
 * modal and the Edit modal in app/admin/users.jsx each carried their own pair
 * of hand-written <Pressable> role buttons — the same two roles, the same two
 * labels, written twice. Adding a role meant editing both, and nothing in the
 * suite could enumerate either: a test could only read the JSX with a regex.
 *
 * Same reasoning as src/utils/cpConfinement.js, and the same failure it was
 * extracted after: a rule that lives inline in a component is a rule nothing
 * can ask a question about.
 *
 * ── THE FOUR, AND THE ORDER ─────────────────────────────────────────────────
 *
 * Operator ruling: Admin, Site Manager / PM, Superintendent, CP. Most
 * privileged first, which is also the order the server prints them in its 422.
 *
 * WORKER IS GONE. It was the second button on both pickers and the model
 * default on the server, so it was also what a request with no role produced.
 * A worker in this product is a row in db.workers with a roster entry and a
 * check-in history; it was never an account that logs in and reaches a screen.
 *
 * THIS LIST IS NOT THE GATE. `assert_assignable_role` in backend/server.py is.
 * Deleting a button stops the app sending a value and stops nothing else — the
 * two are held in step by roleVocabulary.test.cjs, which reads both files.
 *
 * ── `value` IS THE WIRE FORMAT ──────────────────────────────────────────────
 *
 * It is what goes in the request body and what comes back on the user document,
 * so it must match the server's string exactly. `label` is for humans and may
 * be changed freely; `blurb` is the one line under the picker that says what
 * the role can do, because "PM" and "CP" are three-letter words an admin is
 * expected to guess the meaning of otherwise.
 */
import { DATE_DISPLAY_FORMAT, parseStoredDate } from './dateEntry';

/** The role that holds a DOB registration, and the only one with licence fields. */
export const ROLE_SUPERINTENDENT = 'superintendent';

/** Site Manager / PM. Admin powers on assigned projects; signs nothing. */
export const ROLE_PM = 'pm';

export const ASSIGNABLE_ROLES = [
  {
    value: 'admin',
    label: 'Admin',
    blurb: 'Full access to this company, including user management.',
  },
  {
    value: ROLE_PM,
    label: 'Site Manager / PM',
    blurb: 'Admin powers on assigned projects only. Cannot create projects. '
      + 'Daily logs are view-only — may add photographs, may not sign.',
  },
  {
    value: ROLE_SUPERINTENDENT,
    label: 'Superintendent',
    blurb: 'Everything a CP has, plus the construction superintendent log and '
      + 'a DOB registration on this account.',
  },
  {
    value: 'cp',
    label: 'CP',
    blurb: 'Competent person. Files the logs for the projects assigned to them.',
  },
];

/** Just the wire values, in order. */
export const ASSIGNABLE_ROLE_VALUES = ASSIGNABLE_ROLES.map((r) => r.value);

/**
 * THE THREE A COMPANY ADMIN MANAGES. Mirrors `ADMIN_MANAGED_ROLES` on the server.
 *
 * Operator ruling: User Management, opened by a company admin, is the list of
 * the Site Managers, superintendents and CPs of his own company. Admin accounts
 * are the platform operator's, in the owner panel.
 */
export const ADMIN_MANAGED_ROLE_VALUES = ['pm', ROLE_SUPERINTENDENT, 'cp'];

/**
 * The roles THIS principal may hand out.
 *
 * ── WHY THE PICKER HAD TO MOVE WITH THE LIST FILTER ─────────────────────────
 *
 * `GET /admin/users` now shows a company admin only the three roles he manages,
 * and he is not one of them. Leave "Admin" on the picker and he can create an
 * account that VANISHES on the next refresh — which is exactly the defect #576
 * fixed from the client end (`.filter(u => u.role !== 'admin')`, "created users
 * don't vanish"), arriving again from the other end. A product may refuse an
 * act or hide its result; doing both is the bug.
 *
 * TAKES A BOOLEAN AND NOT A USER, deliberately. This module is a leaf — the
 * role vocabulary and nothing else — and importing `isPlatformOperator` from
 * AuthContext would drag api.js, axios and NetInfo into a file whose whole
 * value is that it can be loaded and asked questions. The caller already holds
 * the principal; it passes the answer, not the object.
 *
 * AND IT IS STILL NOT THE GATE. `assert_role_assignable_by` in
 * backend/server.py is: deleting a button stops the app sending a value and
 * stops nothing else. A client that ignores this gets a 403 naming who may
 * create an admin.
 */
export function rolesAssignableBy(isOperator) {
  if (isOperator === true) return ASSIGNABLE_ROLES;
  return ASSIGNABLE_ROLES.filter(
    (r) => ADMIN_MANAGED_ROLE_VALUES.includes(r.value),
  );
}

/**
 * The label for a stored role — including roles this picker does NOT offer.
 *
 * A LIST SCREEN RENDERS WHAT THE DATABASE HOLDS, not what the picker can write.
 * `worker` exists on accounts created before the ruling; a lookup that returned
 * '' for them would print an empty badge on a real row. The role string itself
 * is the fallback, upper-cased, which is what the badge did before this module
 * existed.
 *
 * ── 'owner' STAYS HERE, AND IT IS THE ONE PLACE IN THE APP IT DOES ─────────
 *
 * The role is retired: no writer mints it, no gate reads it, and the platform
 * operator is `is_platform_operator` and never a role string. But RETIRING A
 * ROLE DOES NOT REWRITE THE ROWS THAT HOLD IT. Every account created by
 * self-serve signup before this change still carries it — including, right
 * now, the operator's own — and a user list renders the database rather than
 * the vocabulary.
 *
 * Deleting this line would not make those rows disappear. It would make them
 * fall through to the upper-cased fallback and print "OWNER", which is the
 * same fact rendered worse. IT COMES OUT WHEN THE ACCOUNTS ARE MIGRATED, not
 * before, and a test that finds no user holding the role is what says so.
 *
 * THAT IS ALSO WHY THIS IS NOT THE GATE, and never was: `ASSIGNABLE_ROLES`
 * above governs what may be WRITTEN, this governs what may be READ, and the
 * two lists are allowed to disagree for exactly as long as old rows exist.
 */
export function roleLabel(role) {
  const v = String(role || '').trim().toLowerCase();
  const known = ASSIGNABLE_ROLES.find((r) => r.value === v);
  if (known) return known.label;
  if (v === 'owner') return 'Owner';
  // What self-serve signup produces now. Not assignable, so it is not in the
  // picker — but it IS what most new rows will hold, so a list screen needs a
  // label for it or every prospect reads as "DEMO".
  if (v === 'demo') return 'Demo';
  if (v === 'site_device') return 'Site Device';
  return v ? v.toUpperCase() : 'UNKNOWN';
}

/** Does this role carry a DOB registration? */
export function roleHasLicence(role) {
  return String(role || '').trim().toLowerCase() === ROLE_SUPERINTENDENT;
}

/**
 * The sentence printed beside a superintendent's row about his DOB registration.
 *
 * TAKES THE SERVER'S VERDICT AND DOES NOT RECOMPUTE IT. `licence` is the
 * {state, expires_on, days_remaining} block the server derives on every read —
 * see `superintendent_licence_state`. A second date calculation here would be a
 * second answer to "has it expired", and the two would disagree on the day it
 * matters, across a timezone.
 *
 * RETURNS null WHEN THERE IS NOTHING TO SAY. A row with no badge is the normal
 * state for a licence with months left; a badge that says "valid" on every row
 * is noise that trains an admin to stop reading badges.
 *
 * 'unknown' DOES GET A BADGE, AND THAT IS THE POINT OF THE FOURTH STATE. A
 * superintendent with no expiry recorded is a licence NOBODY HAS CHECKED —
 * Michael Cespedes is in exactly that state the moment he is promoted — and
 * silence would render it identically to one with two years left.
 *
 * ── THE SENTENCE USED TO NAME A FACT NOBODY HAD MEASURED ────────────────────
 *
 * `state === 'unknown'` rendered as "No DOB registration recorded", and the
 * state was derived from `dob_registration_expiry` ALONE. Michael's account
 * carried the registration number 32299 — the operator typed it and the save
 * landed — and an expiry of '07/212029', which is '07/21/2029' with a slash
 * missing. Unparseable expiry → `unknown` → a screen telling the operator his
 * registration number was not recorded, three feet from the number.
 *
 * SO THE VERDICT NOW CARRIES BOTH FACTS and this function reads both.
 * `registered` answers about the NUMBER (from his account or from an active
 * cs_registrations row, per the ruling); `state` answers about the EXPIRY, and
 * 'unreadable' is its own state so a typo and an empty field stop being the
 * same sentence.
 *
 * `registered === false` WINS OVER EVERY DATE VERDICT. Without a number there
 * is no registration for a date to be about, so "expires in 9 days" would be
 * this screen asserting a registration nobody recorded. `!== false` rather
 * than falsiness for the field itself: an older deploy returns no `registered`
 * key at all, and ABSENT MUST NOT READ AS UNREGISTERED — that would badge
 * every superintendent in the product during a rollout.
 */
export function licenceSentence(licence) {
  const state = String((licence || {}).state || '').toLowerCase();
  const days = (licence || {}).days_remaining;
  if (licence && licence.registered === false) {
    return { tone: 'warning', text: 'No DOB registration recorded' };
  }
  if (state === 'expired') {
    return { tone: 'error', text: 'DOB registration EXPIRED' };
  }
  if (state === 'unreadable') {
    // THE STORED VALUE IS IN THE SENTENCE. Told only that something is
    // unreadable, an admin has to open the edit form to find out what; shown
    // '07/212029' he can see the missing slash from the list.
    //
    // IT NAMES THE FORMAT THE PERSON TYPES, not the one the server stores.
    // This used to say "re-enter it as YYYY-MM-DD", which was right while the
    // field took typed ISO. The field is the shared DateInput now and types
    // MM/DD/YYYY; following the old sentence would put 2029-07-21 into a box
    // that reads it as month 20.
    //
    // AND WHEN THE EDIT FORM CAN READ IT, IT SAYS SO. '07/212029' opens in Edit
    // as 07/21/2029 for confirmation (dateEntry.parseStoredDate), so "re-enter"
    // would have him retype a date the form is already showing him. This reads
    // the stored STRING's shape; it is not a second verdict on the date — the
    // server's `unreadable` still decides that the badge appears at all.
    const raw = String((licence || {}).expires_on || '').trim();
    const read = parseStoredDate(raw);
    let text;
    if (read.iso) {
      text = `DOB registration expiry stored as "${raw}" — open Edit to confirm it as ${read.display}`;
    } else if (raw) {
      text = `DOB registration expiry unreadable: "${raw}" — open Edit and enter it as ${DATE_DISPLAY_FORMAT}`;
    } else {
      text = `DOB registration expiry unreadable — open Edit and enter it as ${DATE_DISPLAY_FORMAT}`;
    }
    return { tone: 'error', text };
  }
  if (state === 'expiring') {
    // "in 0 days" is not a sentence. It lapses today.
    return {
      tone: 'warning',
      text: days === 0
        ? 'DOB registration expires today'
        : `DOB registration expires in ${days} day${days === 1 ? '' : 's'}`,
    };
  }
  if (state === 'unknown') {
    // A REGISTRATION NUMBER AND NO EXPIRY. A different sentence from the one
    // above, because it is a different missing fact — and the old wording here
    // is what made Michael's row lie.
    return { tone: 'warning', text: 'DOB registration expiry not recorded' };
  }
  return null;
}

export default ASSIGNABLE_ROLES;
