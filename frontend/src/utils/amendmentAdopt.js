/**
 * THE AMENDMENT HAS TO REACH THE CP.
 *
 * Device round 5, finding 19, reproduced on a device: the CP filed a daily
 * jobsite log, tapped Amend, wrote a reason, and got a screen still marked
 * "FINALIZED — read-only". The logbook LIST said Draft. Both were telling the
 * truth about different sources.
 *
 * WHY. Every editor is local-first: it reads the on-device draft and returns
 * before touching the server, which is what makes the app work with no signal.
 * The draft key is (project, logType, date) — and `amend_logbook` copies all
 * three onto the child, so THE PARENT AND ITS AMENDMENT COLLIDE ON ONE KEY.
 * Submitting had stamped that key `finalized`, so every reopen read the frozen
 * parent and stopped. The child sat on the server, unlocked, unreachable.
 *
 * writeDraft's own comment justified its absolute lock with "corrections happen
 * through an amendment (a NEW key)". Nothing ever produced a new key. The lock
 * was safe to make absolute only because of an escape hatch that did not exist.
 *
 * WHAT THIS DOES. When a local draft says finalized, ask the server whether an
 * unlocked document exists for that (project, type, date). If one does, the
 * correction is real and the local record of the frozen parent is discarded —
 * the editor then falls through to its normal server path, which already
 * prefers the unlocked doc (`arr.find((l) => !l.is_locked)`). That path was
 * never wrong; nothing reached it.
 *
 * WHY NOT GIVE THE AMENDMENT ITS OWN KEY, which is what the old comment
 * promised: opening by key requires knowing the child's id, which requires the
 * server, which breaks the offline-first open the local-first branch exists
 * for. A CP with no signal must still open his log.
 *
 * OFFLINE IT DOES NOTHING. A failed fetch is not evidence that no amendment
 * exists, and it is certainly not evidence that one does — so the log stays
 * locked and the CP is told the truth: this record is frozen on this device.
 * Discarding on a hunch would delete the only offline copy of a filed log.
 */

import { logbooksAPI } from './api';
import { discardFinalizedDraft } from './logbookDrafts';

/**
 * Is this server document an editable amendment rather than the filed original?
 *
 * `is_locked` is the finalize flag; an amendment child is created unlocked and
 * unsigned (`amend_logbook` in backend/server.py). Anything locked is a filed
 * record and never something to adopt.
 */
export function isEditableChild(doc) {
  return !!(doc && typeof doc === 'object' && doc.is_locked !== true);
}

/** The editable amendment among a day's documents, or null. */
export function pickEditableChild(docs) {
  const list = Array.isArray(docs) ? docs : [];
  return list.find(isEditableChild) || null;
}

/**
 * Discard the local frozen draft IF the server confirms an editable amendment.
 *
 * Returns true when the caller should fall through to its server path, false
 * when it should keep the locked local draft. Never throws: a screen that
 * cannot load is worse than a screen that stays locked.
 */
export async function adoptAmendment({ key, projectId, logType, date }) {
  if (!key || !projectId || !logType) return false;
  let docs;
  try {
    docs = await logbooksAPI.getByProject(projectId, logType, date);
  } catch (_e) {
    return false;              // offline: no evidence either way, stay locked
  }
  if (!Array.isArray(docs) || docs.length === 0) return false;
  // A day with only ONE document has nothing to adopt — that document is the
  // log itself, and if the local draft says finalized while the server says
  // unlocked, the server is mid-write or this is a draft that was never filed.
  // Neither is an amendment, and neither is worth discarding a local record for.
  if (docs.length < 2) return false;
  if (!pickEditableChild(docs)) return false;
  return discardFinalizedDraft(key);
}

export default adoptAmendment;
