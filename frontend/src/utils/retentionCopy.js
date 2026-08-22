/**
 * ONE SENTENCE, TWO AUDIENCES.
 *
 * The retention guarantee is said to the person losing the account and to the
 * admin ending it. It was written twice — once in settings, once in the admin
 * confirm — and two wordings of one guarantee is how they drift. The next
 * person to soften one will not know the other exists, and then the app tells
 * two different stories about what happens to a filed attestation.
 *
 * So there is one sentence here, and the only thing that varies is who is being
 * spoken to. Not a template of fragments: the same clauses, in the same order,
 * with the subject swapped.
 *
 * WHY THE WORDING IS WHAT IT IS:
 *
 *   "NYC DOB record-keeping requires..." names the REASON. "Kept for
 *   compliance" names a category and tells him only that a policy exists; a
 *   man reading this deserves to know why his signature outlives his account.
 *
 *   "not yours to erase and we will not delete them" refuses plainly. Anything
 *   softer implies erasure might happen later, which would be a lie.
 *
 *   "They keep your name on them, because a filed attestation has to say who
 *   made it" is the clause people want to cut, and it is the one that must
 *   stay. Blank the name and the attestation is orphaned — a document
 *   asserting an inspection was fine, signed by nobody. He would otherwise
 *   discover this from a PDF, months later.
 *
 * Third person uses they/them. The app does not know anyone's pronouns, and a
 * guess in a legal-retention notice is a worse error than the neutral form.
 */

/**
 * The retention sentence.
 *
 * @param {string|null} name  Omit for the account holder (second person).
 *                            Pass a name for the admin (third person).
 */
export function retentionSentence(name) {
  if (!name) {
    return 'Logbooks, daily logs, signatures and check-ins you filed are '
      + 'construction compliance documents. NYC DOB record-keeping requires '
      + 'the site to keep them, and they remain with the project — they '
      + 'are not yours to erase and we will not delete them. They keep your '
      + 'name on them, because a filed attestation has to say who made it.';
  }
  return `Logbooks, daily logs, signatures and check-ins ${name} filed are `
    + 'construction compliance documents. NYC DOB record-keeping requires '
    + 'the site to keep them, and they remain with the project — they '
    + 'are not theirs to erase and we will not delete them. They keep their '
    + 'name on them, because a filed attestation has to say who made it.';
}

/**
 * The one warning that can still save a signed record.
 *
 * A CP carries unsynced signed logbooks on his handset. Once his token stops
 * authenticating, the reconnect drain takes a 401 — which the client correctly
 * reads as a server refusal, so the drafts stay on the phone, bannered as
 * "refused", and never land. Said to whoever is in a position to act on it.
 */
export function drainWarning(name) {
  if (!name) {
    return 'Open any logbook still showing as unsynced and let it finish. '
      + 'Work that has not reached the server yet cannot be recovered once '
      + 'your access ends.';
  }
  return `If ${name} has unsynced work on their phone it will not reach the `
    + 'server after this. Ask them to open the app on a connection before you '
    + 'continue.';
}

/** What is actually removed. Same clause, same order, subject swapped. */
export function accessRemovedSentence(name) {
  if (!name) {
    return 'Your account and your access to LeveLog will be removed. You will '
      + 'not be able to sign in.';
  }
  return `${name}'s account and access to LeveLog will be removed. They will `
    + 'not be able to sign in.';
}
