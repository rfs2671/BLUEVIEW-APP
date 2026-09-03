/**
 * What the CP is told about a flagged SST card, and what he confirms when he
 * says he checked it.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ITEM 2 — WHY THIS IS A MODULE AND NOT A TERNARY
 *
 * It was a ternary. `preshift_signin.jsx` read:
 *
 *     {f.sst_status === 'expired' ? 'Expired SST card' : 'Unknown SST card'}
 *
 * Two branches for five statuses, so every value that was not `expired` --
 * including any added later -- claimed the same sentence. Four genuinely
 * different production rows all printed "Unknown SST card":
 *
 *   SST_LIMITED     XCAS2DYB8G  exp 2028-02-26  CLASS_UNVERIFIED
 *   SST_UNSPECIFIED (no number) (no expiry)     CLASS_UNVERIFIED
 *   SST_UNSPECIFIED TYPN6JCNJ1  (no expiry)     EXPIRY_UNPARSEABLE
 *   SST_FULL        4YU1RY8KKM  fully classified, colour-derived class
 *
 * The CP cannot act on "unknown". He can act on "the expiry date could not be
 * read" and on "the card class was read from the colour".
 *
 * TWO VOCABULARIES, AND THE CHOICE BETWEEN THEM
 *
 *   review_reason        lives on the cert in db.workers. LIVE and granular.
 *   sst_unknown_reason   lives on the check-in row. FROZEN at check-in and
 *                        coarse: CLASS | EXPIRY | BOTH.
 *
 * review_reason LEADS. Not preference -- capability. sst_unknown_reason derives
 * its class half as `type not in SST_CLASS_TYPES` (server.py ~:14130), which is
 * FALSE for two of the four rows above (SST_LIMITED is a member; so is
 * SST_FULL), so the frozen field is null for both and structurally cannot name
 * them. review_reason names all four. It is also the vocabulary the admin
 * review screen already renders -- app/logbooks/review.jsx maps the flagged
 * endpoint's `sst_review_reason` through t(`reason_${code}`) -- so the CP's
 * gate screen and the admin's queue now describe the same card the same way.
 *
 * sst_unknown_reason STILL FILLS IN, because review_reason holds exactly ONE
 * code and the expiry gate OVERWRITES the resolver's class code when both fire
 * (server.py ~:3032). A row that is both class-unreadable and expiry-unreadable
 * records only EXPIRY_UNPARSEABLE; `BOTH` restores the class fact that write
 * dropped. Neither field is complete. The pair is.
 *
 * NOTHING IS COLLAPSED THAT THE DATA CANNOT SEPARATE. CLASS_UNVERIFIED is
 * stored both for a class OCR could not read and for a class it read fine that
 * belongs to a dead scheme, and the code does not say which. So the sentence is
 * "could not be CONFIRMED" -- true of both -- rather than "could not be READ",
 * which is false of the second. Where neither vocabulary says anything the copy
 * says "class OR expiry", and does not pretend to know which.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ITEM 1 — THE ATTESTATION WORDING IS RULED
 *
 * The CP is attesting that he SAW THE PHYSICAL CARD. That is a different claim
 * from dismissing a warning, and the words are ruled accordingly: the control
 * says "I checked this card" and never approve / dismiss / ignore / override /
 * acknowledge. The scope note SHOWS the card number rather than merely storing
 * it, because the clearance is keyed to that number and dies with it -- the
 * same join key the OSHA register's Review column uses. And there is a refusal
 * path: if the only way out of the dialog is to affirm, the attestation is
 * worthless.
 */

// ── Statuses ────────────────────────────────────────────────────────────────
// A value not listed here returns null rather than borrowing another state's
// sentence. That inheritance IS the defect being fixed, so the replacement must
// not reproduce it for the next status somebody adds.
const TITLES = {
  expired: 'Expired SST card',
  unknown: 'SST card not confirmed',
  missing: 'No SST card on file',
  expiring_soon: 'SST card expiring soon',
};

// ── The two halves of a reason, as clauses ──────────────────────────────────
const CLASS_CLAUSE = {
  unconfirmed: 'the card class could not be confirmed',
  colour: 'the card class was read from the card colour and has not been '
    + 'confirmed against the card',
  conflict: 'the card colour and the printed class do not agree',
  dead: 'this card class is no longer issued',
};

const EXPIRY_CLAUSE = {
  unread: 'the expiry date could not be read',
  implausible: 'the expiry date read from the card is not a possible date',
  disagree: 'two scans of this card disagree on the expiry date',
  unconfirmed: 'the expiry date could not be confirmed',
};

// review_reason -> which half it speaks about, and how.
const FROM_REVIEW_REASON = {
  CLASS_UNVERIFIED: { cls: 'unconfirmed' },
  CLASS_FROM_COLOR_UNCONFIRMED: { cls: 'colour' },
  CLASS_CONFLICTED: { cls: 'conflict' },
  CLASS_EXPIRED_SCHEME: { cls: 'dead' },
  EXPIRY_UNPARSEABLE: { exp: 'unread' },
  EXPIRY_IMPLAUSIBLE: { exp: 'implausible' },
  EXPIRY_CONFLICT: { exp: 'disagree' },
};

// Codes that are about neither half. They are whole sentences and they stop
// there -- appending a class or expiry clause to them would read as though the
// duplicate were a property of the class.
const WHOLE_SENTENCE = {
  DUPLICATE_SST: 'This worker has two SST records that have not been resolved to one.',
  CARD_NUMBER_FORMAT: 'The card number does not match the expected format.',
  CARD_NOT_SST: 'The card that was scanned is not an SST card.',
};

const sentence = (clauses) => {
  const joined = clauses.join(', and ');
  return `${joined.charAt(0).toUpperCase()}${joined.slice(1)}.`;
};

/**
 * The reason line for an `unknown` SST, reconciling the two vocabularies.
 * Returns a sentence -- never '' and never a raw machine code.
 */
function unknownDetail(reviewReason, unknownReason) {
  const whole = WHOLE_SENTENCE[reviewReason];
  if (whole) return whole;

  const named = FROM_REVIEW_REASON[reviewReason] || {};
  // The live cert code leads; the frozen check-in code supplies only the half
  // it did not speak about.
  let cls = named.cls || null;
  let exp = named.exp || null;
  if (!cls && (unknownReason === 'CLASS' || unknownReason === 'BOTH')) cls = 'unconfirmed';
  if (!exp && (unknownReason === 'EXPIRY' || unknownReason === 'BOTH')) exp = 'unconfirmed';

  // NEITHER VOCABULARY SAID ANYTHING. `sst_unknown_reason` is only written when
  // sst_status === 'unknown' AND a cert existed, so a row from before that
  // write -- or one with no cert behind it at all -- lands here. It must not
  // render as though a reason were known.
  if (!cls && !exp) return 'The card class or the expiry date could not be confirmed.';

  // Both halves unknown for the same unremarkable reason: one clause, not the
  // same words twice.
  if (cls === 'unconfirmed' && exp === 'unconfirmed') {
    return 'The card class and the expiry date could not be confirmed.';
  }

  // The half the RECORD actually named goes first; the half recovered from the
  // frozen field follows it.
  const clauses = [];
  if (named.exp) clauses.push(EXPIRY_CLAUSE[exp]);
  if (named.cls) clauses.push(CLASS_CLAUSE[cls]);
  if (!named.exp && exp) clauses.push(EXPIRY_CLAUSE[exp]);
  if (!named.cls && cls) clauses.push(CLASS_CLAUSE[cls]);
  return sentence(clauses);
}

/**
 * @param {{sstStatus?: string, reviewReason?: string, unknownReason?: string}}
 * @returns {{title: string, detail: string}|null}
 *   null when this check-in raises nothing about the SST card.
 */
export function sstFlagCopy({ sstStatus, reviewReason, unknownReason } = {}) {
  const title = TITLES[sstStatus];
  if (!title) return null;
  if (sstStatus === 'unknown') {
    return { title, detail: unknownDetail(reviewReason, unknownReason) };
  }
  if (sstStatus === 'missing') {
    return { title, detail: 'No SST card has been recorded for this worker.' };
  }
  // `expired` and `expiring_soon` are complete claims on their own: the title
  // says the whole thing and a second line would only pad it.
  return { title, detail: '' };
}

// ── ITEM 1 — the attestation, ruled wording ─────────────────────────────────

/** What he confirms. NOT "approve", not "dismiss" -- what he SAW. */
export const CARD_CHECK_STATEMENT =
  "I have seen this worker's physical SST card. The name, card number and "
  + 'class on the card match what is shown here.';

/** Shown directly under the statement, with the number spelled out. */
export const cardCheckScopeNote = (cardNumber) =>
  `Recorded against card number ${cardNumber}. If this worker's card number `
  + 'changes, this check does not carry over and the card must be checked again.';

export const CARD_CHECK_AFFIRM = 'I checked this card';

/** THE WAY OUT THAT IS NOT AN AFFIRMATION. Nothing is recorded by it. */
export const CARD_CHECK_REFUSE = 'I could not check this card';

/**
 * There is nothing to attest against, so the control is not offered at all --
 * a clearance keyed on a null card number would carry to every future card.
 */
export const CARD_CHECK_NO_NUMBER =
  'No card number is recorded for this worker, so there is nothing to check '
  + 'the card against.';

/** Who, when, and against which card number. */
export function cardCheckedLine({ name, at, cardNumber } = {}) {
  const day = typeof at === 'string' ? at.slice(0, 10) : '';
  let who = 'Card checked';
  if (name) who += ` by ${name}`;
  if (day) who += ` on ${day}`;
  return `${who} — recorded against card number ${cardNumber}.`;
}

export default sstFlagCopy;
