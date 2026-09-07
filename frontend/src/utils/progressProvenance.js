/**
 * WHERE ITEM 2'S TEXT CAME FROM.
 *
 * BC 3301.13.13 item 2, verbatim: "The general progress of work at the job
 * site, including a summary of that day's work activity." It sits on a log the
 * CONSTRUCTION SUPERINTENDENT maintains and signs. The CP's daily jobsite log
 * is a different document, signed by a different person in a different
 * capacity, so text in the CP's record is not text in the CS's log and the
 * item cannot be dropped on the grounds that the information exists elsewhere.
 *
 * BUT NOTHING REQUIRES HIM TO HAVE COMPOSED THE SENTENCE. Compare item 2 with
 * item 3 one line down: item 3 is expressly "the CONSTRUCTION SUPERINTENDENT'S
 * activities", item 2 is a fact about the site. Adopting the CP's summary into
 * the CS's log, which he then signs and dates, puts the required information in
 * the required document. Signing it is the attestation.
 *
 * ── SO THE DOCUMENT RECORDS WHICH IT WAS ────────────────────────────────────
 *
 * `adopted`  the autofill from the CP's daily jobsite log, left as it arrived
 * `own`      he changed it, or he wrote it with nothing to adopt
 * (absent)   no summary at all -- the block is empty and says nothing
 *
 * `superintendent_log.py` declared this flag and argued for it before the
 * client existed, on the grounds that RETROFITTING PROVENANCE ONTO FILED
 * RECORDS IS IMPOSSIBLE. The client half then never landed, so every log filed
 * in the interim resolves to `unmarked` -- exactly the outcome the argument was
 * written to prevent. One such record exists (2026-09-04). This is the half
 * that was missing.
 *
 * ── AND IT MATTERS FROM THE SUNSET ──────────────────────────────────────────
 *
 * DOB Service Notice of 2025-12-18: the competent-person allowance sunsets on
 * 2027-01-01, after which the CS must be at the site whenever work is
 * occurring. From that date he is the WITNESS rather than the summariser and
 * the derivation inverts. An unmarked item 2 cannot afterwards be told apart
 * from one he wrote himself, and once the two logs can disagree, that
 * difference is the whole finding.
 *
 * ── WHY THESE ARE FUNCTIONS AND NOT INLINE ──────────────────────────────────
 *
 * `progressSource` is asked in three places on one screen -- building the
 * document, deciding whether to show the adopted note, and re-deriving the
 * flag when a stored draft is reopened. Three copies of a rule about what a
 * filed compliance record claims is how the OSHA register's row rule and the
 * pre-shift sheet each came to print two different things.
 */

import { filedDailyRecord } from './dailyLogRecord';

// THE STRINGS THE SERVER RESOLVES. `item_provenance` in
// backend/lib/logbook/superintendent_log.py reads exactly these two and treats
// anything else as `unmarked`, so a typo here does not error -- it silently
// files an unmarked record, which is the failure that already happened once.
// progressProvenance.test.cjs asserts both against the Python.
export const PROVENANCE_ADOPTED = 'adopted';
export const PROVENANCE_OWN = 'own';

/**
 * The CP's filed summary for this date, or '' if there is nothing to adopt.
 *
 * THROUGH `filedDailyRecord`, NOT A PICKER OF ITS OWN. Item 8's default asks
 * the same question about the same document -- which daily log IS the record
 * for this date -- and both answers are wrong in the same way if the wrong
 * link of an amended chain is taken. See dailyLogRecord.js for why that is
 * chainHead rather than rows[0], and why an unsigned draft is not a record.
 */
export function adoptableSummary(rows) {
  const record = filedDailyRecord(rows);
  if (!record) return '';
  const text = ((record.data || {}).general_description) || '';
  return String(text).trim();
}

/**
 * `adopted` | `own` | null, from what is in the box and what was offered.
 *
 * COMPARED AGAINST THE TEXT THAT WAS ADOPTED, not against the CP's log as it
 * stands now. The flag has to be true at the moment of filing; deriving it
 * later from a record that can still change is the thing `item_provenance`'s
 * docstring explicitly refuses.
 *
 * NULL FOR AN EMPTY BOX. An empty item 2 writes `{}` and claims nothing --
 * stamping `own` on a blank would assert he wrote something.
 *
 * `own` WHEN THERE WAS NOTHING TO ADOPT. If the CP filed no daily log, or the
 * read failed, whatever he types is his own account and the document should
 * say so. That is not a guess: no text was ever offered to him.
 */
export function progressSource(summary, adoptedText) {
  const s = String(summary || '').trim();
  if (!s) return null;
  const a = String(adoptedText || '').trim();
  return (a && s === a) ? PROVENANCE_ADOPTED : PROVENANCE_OWN;
}

/**
 * The item 2 block this screen files.
 *
 * ONE BUILDER, so the flag cannot be written on one path and forgotten on
 * another. `{}` for an empty summary, unchanged from before this existed.
 */
export function progressBlock(summary, adoptedText) {
  const s = String(summary || '').trim();
  if (!s) return {};
  return { summary: s, source: progressSource(s, adoptedText) };
}

/**
 * What `adoptedText` should be when a stored document is reopened.
 *
 * THE STORED FLAG IS THE ONLY EVIDENCE, and it is enough. A log that says
 * `adopted` says its own summary IS the adopted text, so reopening it and
 * leaving the box alone keeps `adopted`, and the first edit flips it to `own`
 * -- which is the behaviour on the first visit too.
 *
 * A LOG SAYING `own`, OR SAYING NOTHING, ADOPTS NOTHING. Returning its summary
 * here would mean reopening a log he wrote himself, changing not one
 * character, and filing it as adopted from a record it never came from.
 */
export function adoptedTextFromStored(block) {
  const b = (block && typeof block === 'object') ? block : {};
  if (String(b.source || '') !== PROVENANCE_ADOPTED) return '';
  return String(b.summary || '').trim();
}

export default {
  PROVENANCE_ADOPTED, PROVENANCE_OWN,
  adoptableSummary, progressSource, progressBlock, adoptedTextFromStored,
};
