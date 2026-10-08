/**
 * WHAT CHANGES WHEN AN ACCOUNT BECOMES A SUPERINTENDENT, SAID BEFORE IT DOES.
 *
 * ── WHY THERE IS A CONFIRMATION AT ALL ──────────────────────────────────────
 *
 * Because `PUT /admin/users/{id}` with `{role: "superintendent"}` is one line of
 * wiring and five measurable consequences, and four of them are things the
 * account LOSES. An admin who reads "Make superintendent" and taps it has every
 * reason to expect a capability being added.
 *
 * ── AND WHY THE SENTENCES ARE HERE AND NOT IN THE JSX ───────────────────────
 *
 * Same reason as retentionCopy.js, cpConfinement.js and roleVocabulary.js: a
 * rule written inline in a component is a rule nothing can ask a question
 * about. superintendentPromotion.test.cjs enumerates these two lists and
 * asserts each claim against the code that makes it true — against
 * `_PENDING_LINK_ROLES`, `PLAN_PREFETCH_ROLES`, `update_admin_user`,
 * `EMAIL_EXCLUDED_ROLES` and `_refuse_if_not_the_superintendent`. That is the
 * difference between a list of consequences somebody audited once and a list
 * that fails when it stops being true.
 *
 * ── THE REGISTER ────────────────────────────────────────────────────────────
 *
 * Read in a site office, on a phone, by somebody who is not a developer. Plain
 * verbs, no marketing, and each line names the thing it is about rather than
 * alluding to it. NOT A FEATURE LIST: the point of the second half is that the
 * one question an admin actually asks — "will this break his ability to file?"
 * — is answered out loud, because it is the fear that stops a correct change
 * being made.
 *
 * ── IT DESCRIBES ONE JOURNEY: cp → superintendent ───────────────────────────
 *
 * NOT "ANY ROLE → superintendent", and the difference is not pedantry. Three of
 * the lines below are false from `pm`: a Site Manager's email is NOT already
 * suppressed, so promotion would start suppressing it where this says nothing
 * moves; and he has neither the WhatsApp binding nor the emergency check-in
 * point, so two of the stated losses are not losses. `canBecomeSuperintendent`
 * in roleVocabulary.js is what holds the caller to `cp`, and it carries the same
 * reason. Widening the affordance means re-measuring these sentences first.
 *
 * NOT THE GATE, AND NOT A PERMISSION MODEL. Every sentence below describes a
 * refusal or a behaviour that lives in backend/server.py or app/_layout.jsx.
 * This file persuades nobody of anything; it reports.
 */

/** Newline. Spelled this way so the sentences above read as one block. */
const NL = String.fromCharCode(10);

/**
 * WHAT THE ACCOUNT LOSES AND GAINS. Losses first, because they are the ones an
 * admin would not predict, and the order is roughly how much they cost him.
 */
export const PROMOTION_CHANGES = [
  // `set_user_cs_registrations` writes `assigned_projects` as the whole
  // registered set — not a merge — so the first save on the Registration sheet
  // drops every assignment he is not registered on. NYC DOB allows a CS one
  // job, so that is usually the point; it is still a change an admin must
  // expect rather than discover.
  'His projects are set by Registration instead of Assign. The Assign button '
  + 'comes off his card: ticking a job under Registration is what assigns it. '
  + 'The first time you save Registration his project list becomes exactly the '
  + 'jobs you ticked, so anything else he is assigned to now comes off.',
  // `_require_link_role` admits owner, admin and cp. Superintendent is not on
  // it, and neither is the on-demand checklist check in the webhook.
  'He can no longer connect a WhatsApp group to a project, or ask the bot in a '
  + 'group for a checklist.',
  // `bootstrap_checkin_point` / `remove_cp_checkin_point`: a company admin or a
  // cp. This is the CP's own fix for the day no chip on the job will read.
  'He can no longer create or remove an emergency check-in point — the QR gate '
  + 'a CP mints himself when no chip on the job will read.',
  // PLAN_PREFETCH_ROLES in app/_layout.jsx. Said out loud because it spends
  // somebody else's data allowance on a device the admin is not holding.
  'His phone starts downloading the plans for his jobs in the background, so '
  + 'they open with no signal. It uses his data.',
];

/**
 * WHAT DOES NOT CHANGE — and this half is not padding.
 *
 * The filing right is the first line because it is the question. "Will
 * promoting him stop him filing?" is the obvious fear, the answer is no, and
 * leaving it unsaid is what makes a correct change not get made.
 */
export const PROMOTION_UNCHANGED = [
  // `_refuse_if_not_the_superintendent` reads `cs_registrations` and never
  // `role` — the dual-capacity man who is both the registered CS and the
  // competent person on his own job holds whichever role, and files either way.
  'Who may file the construction superintendent log. That is decided by the '
  + 'registration on the project and never by the role, so he can file exactly '
  + 'what he can file today.',
  // EMAIL_EXCLUDED_ROLES already holds both. Stated rather than omitted,
  // because an admin left to wonder assumes the worst about a role change.
  'System email. CPs and superintendents are both left out of it, so nothing '
  + 'starts or stops arriving.',
  // app/_layout.jsx holds both roles to the same paths and the same home.
  'Where he lands when he signs in, and which screens he can reach.',
];

/**
 * The confirmation an admin reads before the role is written.
 *
 * `hasLicenceNumber` DECIDES WHETHER THE NEXT STEP IS STATED. A
 * non-superintendent account structurally holds no DOB registration number —
 * `create_admin_user` pops the fields for every other role and
 * `update_admin_user` `$unset`s them on a demotion — so in practice the
 * "record one" line is always the one shown. The other branch is not dead
 * weight: a row predating those rules would otherwise be handed advice to type
 * a number already on the account, which reads as a save that failed.
 *
 * NO TITLE ARGUMENT, DELIBERATELY. On web this body goes to `window.confirm`,
 * which has no title, so the first line has to name the act by itself.
 */
export function promoteToSuperintendentBody(name, { hasLicenceNumber = false } = {}) {
  const who = String(name || '').trim() || 'This user';
  const bullet = (line) => `- ${line}`;
  const parts = [
    `Make ${who} a superintendent, so he can hold a DOB construction `
    + 'superintendent registration.',
    'What changes:',
    PROMOTION_CHANGES.map(bullet).join(NL),
    'What does not change:',
    PROMOTION_UNCHANGED.map(bullet).join(NL),
  ];
  if (!hasLicenceNumber) {
    parts.push(
      'Next: record his DOB registration number. A registration cannot be '
      + 'saved without one, because the one-job rule is checked on the '
      + 'registration number.',
    );
  }
  // THE UNDO IS NAMED AND SO IS ITS COST. `update_admin_user` $unsets
  // SUPERINTENDENT_LICENCE_FIELDS the moment the role stops being
  // superintendent, so "just set it back" is not a clean reversal — the number,
  // the expiry and the card come off the account with it. It does NOT touch
  // `cs_registrations`, which is why the registrations are named as surviving.
  parts.push(
    'You can set the role back under Edit at any time. That clears the DOB '
    + 'number, the expiry and the card from the account again; it does not '
    + 'touch the registrations themselves.',
  );
  return parts.join(NL + NL);
}

export default promoteToSuperintendentBody;
