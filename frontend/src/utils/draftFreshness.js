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
 * ── THE RESOLUTION HALF, AND THE RULING BEHIND IT ─────────────────────────
 *
 * The header above was written when this module was only the detection half,
 * and it says the conflict UI "awaits its own design". IT HAS ONE NOW, and it
 * is one sentence: THE CP'S DRAFT WINS. It is the most recent authorship and
 * he is the one who made it. He is SHOWN that the server copy changed, and
 * then he is allowed to file his own work over it.
 *
 * That replaces a placeholder, not a safety property. `Submit is dead` and
 * `persistAndPush refuses` were never the decision — they were the absence of
 * one, held in place until somebody chose. Leaving a CP with a red banner, a
 * grey button and an instruction to email his safety admin is not a policy; it
 * is an outage with prose around it.
 *
 * ── WHAT DID NOT CHANGE: NEVER SILENTLY ───────────────────────────────────
 *
 * `update_logbook` applies `data` as a wholesale `$set`, so filing his draft
 * genuinely reverts the server's change. The ruling permits that. It does NOT
 * permit it happening as a side effect of pressing the same button he always
 * presses. So the override is a SEPARATE, DELIBERATE ACT: the banner states
 * the fact, names the fields that differ where it can, and Submit stays dead
 * until he acknowledges it. One press cannot both learn the fact and act on
 * it.
 *
 * THE ACKNOWLEDGEMENT RIDES ON THE VERDICT OBJECT, and that is load-bearing
 * rather than convenient. Every editor already holds the verdict in one piece
 * of state and already clears it at the top of each load — so an acknowledgement
 * stored on it is re-armed by the code that re-runs the comparison, and there
 * is no second flag anywhere that can be left true across a fresh fetch. A CP
 * who acknowledges a conflict, backgrounds the app, and comes back to a
 * DIFFERENT server change must be shown that one too.
 */

/**
 * WHICH VERDICTS HE MAY OVERRIDE — AND WHY THE OTHER TWO ARE NOT ON THIS LIST.
 *
 * The ruling is about an UNFILED server change: someone edited a draft-state
 * document out from under him, and between two unfiled versions the most recent
 * author wins. `server-newer` is exactly that case and it is the only one.
 *
 * `server-locked` and `server-filed` are not a newer draft — they are a
 * COMPLIANCE RECORD. A filed log is a statutory artifact that has been signed;
 * overwriting it with a stale local draft is the 588 Thomas overwrite of
 * 2026-08-25 that this whole line of work exists to stop, and it is what
 * FILED_LOG_DATA_IMMUTABLE was added to refuse. Extending "the CP's draft wins"
 * to them would not be applying the ruling, it would be reversing the fix.
 *
 * AND THE SERVER REFUSES THEM ANYWAY — 423 on a finalized log, 409
 * FILED_LOG_DATA_IMMUTABLE on a filed one. Re-enabling Submit for those two
 * would not give him his log; it would give him a button that fails, after he
 * signed, with an error code instead of an explanation. The honest screen is
 * the one that says so BEFORE he signs and points him at Amend, which is the
 * mechanism that exists for correcting a filed record and preserves both
 * versions instead of destroying one.
 */
export const OVERRIDABLE_REASONS = Object.freeze(['server-newer']);

/**
 * May this conflict be overridden by the CP at all?
 *
 * Anything that is not a conflict is trivially not blocking. A conflict whose
 * reason is unrecognised is treated as NOT overridable — an unknown verdict is
 * the one case where guessing in the permissive direction risks the overwrite
 * this module exists to prevent, so a fourth reason added later is refused by
 * default until somebody decides about it here.
 */
export function isOverridable(verdict) {
  if (!verdict || !verdict.conflict) return false;
  return OVERRIDABLE_REASONS.indexOf(verdict.reason) !== -1;
}

/**
 * THE ONE GATE. Should the save path refuse this push?
 *
 * Used by both the Submit button and by `persistAndPush` itself, so a dead
 * button and a refused save can never disagree about what is permitted. The
 * button is the affordance; this is the guard, and the guard is the one that
 * matters — every editor keeps its own call so a future caller that is not a
 * button is covered too.
 *
 *   no conflict          -> false. The ordinary case, and every offline read.
 *   not overridable      -> true, always. server-locked / server-filed.
 *   overridable, unacked -> true. He has not been shown the fact yet, or has
 *                          been shown it and not answered.
 *   overridable, acked   -> FALSE. The ruling. His draft is filed and the
 *                          server change is replaced, because he said so.
 */
export function submitRefused(verdict) {
  if (!verdict || !verdict.conflict) return false;
  if (!isOverridable(verdict)) return true;
  return verdict.acknowledged !== true;
}

/**
 * Is this value "nothing"? Used only by the field comparison below.
 *
 * A draft is JSON on the device and the server document is JSON off the wire,
 * and the two round-trips disagree about absence in ways that mean nothing to
 * a CP: a key the draft never wrote is `undefined`, the same key cleared in the
 * UI is `''`, and Mongo may hand back `null`. Reporting "Notes changed" because
 * one side spelled empty differently would bury the one field that really did
 * change under a list of noise, which is the same failure as not listing
 * anything at all.
 */
function isEmptyValue(v) {
  if (v === null || v === undefined || v === '') return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.keys(v).length === 0;
  return false;
}

/**
 * Deep value equality, depth-bounded.
 *
 * Object keys are compared as a SET, because neither JSON round-trip promises
 * an order and a reordered key is not a change the CP made. Beyond the depth
 * cap the values are reported as DIFFERENT rather than equal: this list is
 * informational and over-reporting one deeply-nested field is recoverable,
 * while a silent "equal" on unexamined data is the class of bug this whole
 * change is about. The cap also means no input can make this run away — draft
 * data is JSON and cannot hold a cycle, but nothing here depends on that.
 */
function sameValue(a, b, depth = 0) {
  if (a === b) return true;
  if (isEmptyValue(a) && isEmptyValue(b)) return true;
  if (depth > 6) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b)) return false;
    if (a.length !== b.length) return false;
    return a.every((x, i) => sameValue(x, b[i], depth + 1));
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a).filter((k) => !isEmptyValue(a[k])).sort();
    const kb = Object.keys(b).filter((k) => !isEmptyValue(b[k])).sort();
    if (ka.length !== kb.length) return false;
    if (ka.some((k, i) => k !== kb[i])) return false;
    return ka.every((k) => sameValue(a[k], b[k], depth + 1));
  }
  return false;
}

/**
 * WHICH FIELDS DIFFER — and it costs nothing, because both documents are here.
 *
 * This is not a diff tool and it is not the conflict UI. It is the cheap half
 * of "show him what changed": `compareDraftToServer` already holds the draft it
 * was handed and the server document it fetched, so naming the top-level keys
 * that disagree is a loop, not a design. The two sides ARE the same shape —
 * the save path PUTs `draft.data` straight into `update_logbook` as a wholesale
 * `$set`, which is the very defect being managed here, so `serverLog.data` is
 * the same object the draft would have overwritten it with.
 *
 * NULL IS NOT AN EMPTY LIST, and the caller must keep them apart. `null` means
 * NO COMPARISON WAS POSSIBLE — one side carried no `data` at all — and the
 * banner must fall back to the plain statement of the fact. `[]` means the two
 * were compared and no top-level field differs, which is a real and reachable
 * answer: the server document may have been touched in a way that moved
 * `updated_at` without changing `data`.
 *
 * AND THE FACT NEVER DEPENDS ON THIS. The verdict comes from the stamps and
 * the status flags; this only decorates it. A null list, an empty list and a
 * long list all produce the same warning, because "the server copy changed" is
 * true in all three.
 */
export function changedFields(draft, serverLog) {
  const a = draft && draft.data;
  const b = serverLog && serverLog.data;
  if (!a || typeof a !== 'object' || Array.isArray(a)) return null;
  if (!b || typeof b !== 'object' || Array.isArray(b)) return null;
  const keys = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
  return keys.filter((k) => !sameValue(a[k], b[k]));
}

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
  // No documents to compare, so no field list — null, not []. See changedFields.
  changed: null,
  // Nothing to acknowledge. Present on every shape this module returns so a
  // caller never has to distinguish "not acknowledged" from "no such field".
  acknowledged: false,
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
    // COMPUTED ONLY WHEN THERE IS SOMETHING TO SAY. On a clean comparison the
    // banner never renders, so the field list would be work nobody reads.
    changed: verdict.conflict ? changedFields(draft, log) : null,
    // He has not been shown anything yet. Set to true only by the editor, in
    // response to the CP's own press, and cleared with the verdict on reload.
    acknowledged: false,
  };
}

export default compareDraftToServer;
