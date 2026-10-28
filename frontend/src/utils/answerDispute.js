/**
 * "Wrong?" on an assistant answer (POST /api/answers/{answer_log_id}/dispute).
 *
 * The person only ever learns that it was flagged: the reply is
 * {"status": "Flagged for review"} and nothing here shows a review state,
 * an approve / deny, or who reviews it.
 */

export const FLAGGED = 'Flagged for review';
export const SEND_FAILED = 'Couldn’t send — try again';
export const NOTE_PLACEHOLDER = 'What’s wrong? (optional)';
export const NOTE_MAX = 2000;

/** The endpoint for one answer. */
export function disputePath(answerLogId) {
  return `/api/answers/${encodeURIComponent(String(answerLogId))}/dispute`;
}

/** The body: `{note}` when they wrote something, else empty. */
export function disputeBody(note) {
  const n = typeof note === 'string' ? note.trim().slice(0, NOTE_MAX) : '';
  return n ? { note: n } : {};
}

/** Only an answer the backend logged (it has an id) can be disputed. */
export function disputable(answerLogId) {
  return typeof answerLogId === 'string' && answerLogId.trim().length > 0;
}

// The answers flagged in this session: a flagged answer stays flagged while
// the app is open, even if its card is drawn again.
const flagged = new Set();
export const isFlagged = (id) => flagged.has(String(id));
export const markFlagged = (id) => { flagged.add(String(id)); };
export const _resetFlagged = () => flagged.clear();
