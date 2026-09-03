/**
 * ALWAYS ASK THE SERVER, EVEN WHEN A DRAFT EXISTS.
 *
 * ── THE DEFECT ────────────────────────────────────────────────────────────
 *
 * Every logbook editor is local-first, and the branch that makes it so returned
 * before the server was ever asked:
 *
 *     const draft = await readDraft(_key);
 *     if (draft?.data && Object.keys(draft.data).length) {
 *       ... hydrate(draft.data);
 *       setLoading(false);
 *       return;                     // the server document is NEVER fetched
 *     }
 *
 * No `fetchState` lived on that path because there was no fetch. The CP saw
 * device content, the server might hold an amended or corrected document, and
 * the screen was visually identical either way. Then `persistAndPush` PUT the
 * whole draft into `update_logbook`, which applies `data` as a wholesale `$set`
 * — so a server-side correction was reverted, silently, by a CP who did nothing
 * but open his log.
 *
 * The collision was already known and already half-fixed. logbookDrafts.js
 * documents that parent and amendment share ONE key (project, logType, date),
 * and that "for months the amendment a CP was handed could not be reached".
 * amendmentAdopt.js closed that for the FINALIZED case, on server confirmation.
 * AN UNFINALIZED DRAFT OVER A CHANGED SERVER DOCUMENT WAS COVERED BY NOTHING.
 *
 * ── WHAT THIS MODULE IS, AND IS NOT ───────────────────────────────────────
 *
 * It is the fetch and the comparison, and it stops there. It returns a verdict;
 * it applies nothing, discards nothing, and merges nothing. THE CONFLICT UI —
 * merge, diff, pick-a-side — IS OUT OF SCOPE AND AWAITS ITS OWN DESIGN. What
 * the callers do with a conflict today is the minimum: do not present the draft
 * as the record, do not overwrite the server from it, and keep the CP's work.
 *
 * ── WHY THE POLICY IS IN ONE FILE ─────────────────────────────────────────
 *
 * Eleven editors hand-roll their load, and the defect above existed identically
 * in all eleven because the last fix was copy-pasted eleven times. Each editor
 * gets a CALL here, not a copy of the reasoning. When the tolerance changes, or
 * a fourth conflict signal is found, or the conflict UI finally lands, one file
 * changes and eleven screens follow.
 *
 * ── AND WHY A FAILED FETCH IS NOT A CONFLICT ──────────────────────────────
 *
 * The early return exists so a CP with no signal can open his log, and that
 * must not regress. `settleFetch` never throws and answers 'ok' | 'offline' |
 * 'error'; anything but 'ok' means NO COMPARISON WAS POSSIBLE. It does not mean
 * the server wins. Reading a dead radio as "your draft is stale" would lock
 * every CP in a dead zone out of his own paperwork, which is a worse failure
 * than the one being fixed.
 */

import { logbooksAPI } from './api';
import { settleFetch } from './offlineState';
import { chooseEditableLog } from './logbookEditable';

/**
 * How far apart two clocks may be before a gap counts as evidence.
 *
 * THIS COMPARISON SPANS TWO CLOCKS. The draft stamp is `Date.now()` on the
 * handset; the server stamp is the server's own. Handset clocks drift, and a
 * CP's phone is not an NTP client he thinks about. Without a tolerance, a
 * device running two minutes slow would report EVERY draft as stale and every
 * editor would open blocked — turning a wrong clock into an inability to work.
 *
 * WHICH DIRECTION THIS ERRS, DELIBERATELY: under-reporting. A skew smaller than
 * the tolerance is called agreement, so a genuine but very recent server change
 * can still be missed. That leaves the original defect open in a narrow window
 * and closes it everywhere else — the opposite trade (over-reporting) would
 * take the log away from a CP who has done nothing wrong, on the strength of a
 * clock.
 *
 * THE PROPER FIX IS NOT A TOLERANCE. It is a watermark: the draft recording the
 * server's `updated_at` as of its last agreement with the server, so the
 * question becomes "has the server moved since we last agreed" and no clock
 * comparison is needed at all. That is a storage-format change and it belongs
 * with the conflict UI design, not ahead of it. The two skew-free signals below
 * are what carry the load in the meantime.
 */
export const SKEW_TOLERANCE_MS = 2 * 60 * 1000;

/**
 * HOW LONG THE DRAFT MAY BE HELD OFF THE SCREEN WAITING FOR THIS ANSWER.
 *
 * THE OFFLINE REGRESSION THIS EXISTS TO PREVENT. The branch this call sits on
 * used to return with no network access at all, and apiClient's default ceiling
 * is 25 SECONDS — chosen for the slowest legitimate endpoint in the app, and
 * far too long to hold a form the device already has. Airplane mode rejects at
 * once, but a jobsite basement or a captive portal is a hanging socket, and
 * without a bound here a CP with no signal would meet a spinner over his own
 * saved draft for the better part of half a minute. That is a worse screen than
 * the one being fixed.
 *
 * A DEADLINE, NOT A CANCELLATION. The request is left to finish or die on its
 * own; only the WAIT is abandoned. What the caller gets back is 'offline',
 * which is the same verdict settleFetch already reports for a timeout
 * (isOfflineError matches ECONNABORTED) and means what it says: no comparison
 * was possible. It never means the server won.
 *
 * A CONFLICT MISSED THIS WAY IS THE SAFE MISS: the screen behaves exactly as it
 * did before this change, which is the status quo, rather than blocking a CP
 * out of his log on the strength of a slow radio.
 */
export const COMPARE_DEADLINE_MS = 8000;

/**
 * Milliseconds since epoch, or null for anything that is not a usable instant.
 *
 * The two sides arrive in different shapes and neither may be coerced blindly:
 * the draft carries a number (writeDraft's `Date.now()`), and the server carries
 * whatever FastAPI serialised `updated_at` into — `serialize_id` marks naive
 * Mongo datetimes as UTC before returning them, so it is an ISO-8601 string with
 * an offset. `Date.parse` of a malformed value is NaN, and NaN silently loses
 * every comparison it takes part in; it is turned into null here so the caller
 * sees "unknown" instead of "old".
 */
export function toMillis(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (v instanceof Date) {
    const t = v.getTime();
    return Number.isFinite(t) ? t : null;
  }
  if (typeof v === 'string') {
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

/** When the on-device draft last changed, or null if it was never stamped. */
export const draftStamp = (draft) => toMillis(draft && draft.updated_at);

/**
 * When the server document last changed.
 *
 * `created_at` is the fallback because a document written once and never
 * updated may carry only that — and a create IS a change to compare against.
 */
export function serverStamp(doc) {
  if (!doc || typeof doc !== 'object') return null;
  const u = toMillis(doc.updated_at);
  return u !== null ? u : toMillis(doc.created_at);
}

/**
 * Do these two documents disagree, and on what evidence?
 *
 * Returns { conflict, reason, draftAt, serverAt }. Three reasons, in the order
 * they are tested, because the first two need no clock at all:
 *
 *   'server-locked'  the server document is FINALIZED and the draft is not.
 *                    A filed record is immutable (update_logbook answers 423)
 *                    and a draft that thinks otherwise is stale by definition.
 *                    Note this is NOT the amendment case: adoptAmendment runs
 *                    first, on a FINALIZED draft, and discards it when the
 *                    server confirms an editable child. This is the reverse —
 *                    the server froze and the device never heard.
 *
 *   'server-filed'   the server document is SUBMITTED and the draft is not.
 *                    An END_OF_DAY log is submitted but not locked until the
 *                    overnight sweep, which is the window in which two
 *                    daily_jobsite records at 588 Thomas were overwritten on
 *                    2026-08-25 by a CP who changed nothing. The server refuses
 *                    the data write now (409 FILED_LOG_DATA_IMMUTABLE); this is
 *                    the client learning it before the CP signs, rather than
 *                    after.
 *
 *   'server-newer'   the timestamps say so, by more than SKEW_TOLERANCE_MS.
 *
 * A null stamp on EITHER side is unknown, not old: no verdict is reached and
 * the draft opens as it always did.
 */
export function compareStamps(draft, serverLog) {
  const draftAt = draftStamp(draft);
  const serverAt = serverStamp(serverLog);
  const base = { draftAt, serverAt };

  const finalizedLocally = !!(draft && draft.finalized);
  if (serverLog && serverLog.is_locked === true && !finalizedLocally) {
    return { ...base, conflict: true, reason: 'server-locked' };
  }
  const draftStatus = (draft && draft.status) || 'draft';
  if (serverLog && serverLog.status === 'submitted' && draftStatus !== 'submitted') {
    return { ...base, conflict: true, reason: 'server-filed' };
  }
  if (draftAt === null || serverAt === null) {
    return { ...base, conflict: false, reason: null };
  }
  if (serverAt - draftAt > SKEW_TOLERANCE_MS) {
    return { ...base, conflict: true, reason: 'server-newer' };
  }
  return { ...base, conflict: false, reason: null };
}

/**
 * Whether a stamp comparison was even possible.
 *
 * Split out from `conflict` on purpose. "The draft is current" and "we could
 * not tell" are different statements, and collapsing them is how the original
 * defect read as normal operation for months.
 */
export function isComparable(draft, serverLog) {
  if (!serverLog) return false;
  if (serverLog.is_locked === true || serverLog.status === 'submitted') return true;
  return draftStamp(draft) !== null && serverStamp(serverLog) !== null;
}

const NO_COMPARISON = (fetchState) => ({
  fetchState,
  comparable: false,
  conflict: false,
  reason: null,
  serverLog: null,
  serverReadOnly: false,
  draftAt: null,
  serverAt: null,
});

/**
 * Fetch the day's server document and compare it to the draft in hand.
 *
 * NEVER THROWS, and never rejects. The editors' local-first branch has no catch
 * of its own around this call, and a throw here would take the whole load down
 * — the CP would meet a blank form standing over a draft that exists, which is
 * the one outcome worse than the defect being fixed.
 *
 * `serverLog` is handed back UNAPPLIED. This module does not hydrate, does not
 * discard, and does not choose. The caller shows the draft and says the server
 * disagrees; deciding between them is the conflict UI, and it is not built.
 */
export async function compareDraftToServer({
  draft, projectId, logType, date,
  // Injectable so the suite can prove the deadline without waiting on it.
  deadlineMs = COMPARE_DEADLINE_MS,
}) {
  if (!projectId || !logType) return NO_COMPARISON('ok');

  // BOUNDED. See COMPARE_DEADLINE_MS: the draft must not be held off the screen
  // by a socket that is never going to answer. Promise.race, not an abort — the
  // request is harmless once nobody is waiting on it, and settleFetch has
  // already swallowed its rejection either way.
  let timer;
  const deadline = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ status: 'offline', data: null, error: null }), deadlineMs);
  });
  const r = await Promise.race([
    settleFetch(() => logbooksAPI.getByProject(projectId, logType, date)),
    deadline,
  ]);
  clearTimeout(timer);
  // 'offline' or 'error' — NOT a conflict. See the header: a dead radio is not
  // evidence about the server, and the draft must still open.
  if (r.status !== 'ok') return NO_COMPARISON(r.status);

  const docs = Array.isArray(r.data) ? r.data : [];
  // The SAME chooser the server path below the early return already uses, so
  // the document compared against is the document the editor would have loaded.
  // Picking a different one would make the comparison answer a question nobody
  // asked.
  const { log, readOnly } = chooseEditableLog(docs);
  if (!log) return NO_COMPARISON('ok');

  const verdict = compareStamps(draft, log);
  return {
    fetchState: 'ok',
    comparable: isComparable(draft, log),
    conflict: verdict.conflict,
    reason: verdict.reason,
    serverLog: log,
    serverReadOnly: readOnly,
    draftAt: verdict.draftAt,
    serverAt: verdict.serverAt,
  };
}

export default compareDraftToServer;
