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
 */
export function licenceSentence(licence) {
  const state = String((licence || {}).state || '').toLowerCase();
  const days = (licence || {}).days_remaining;
  if (state === 'expired') {
    return { tone: 'error', text: 'DOB registration EXPIRED' };
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
    return { tone: 'warning', text: 'No DOB registration recorded' };
  }
  return null;
}

export default ASSIGNABLE_ROLES;
