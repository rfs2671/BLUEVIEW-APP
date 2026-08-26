import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { logbooksAPI } from './api';
import {
  getPendingKeys, readDraft, setDraftBackendId, clearPending, writeDraft,
  uploadPendingActivityPhotos,
} from './logbookDrafts';
import { isAffirmedSignature } from './signatureAffirmed';

/**
 * RECONNECT DRAIN for logbook drafts — the missing half of "draft + sync".
 *
 * The gap this closes: markPending() only RECORDED a key in
 * `logbook_pending_push`, and getPendingKeys() had no consumer. So a failed
 * push left the draft safe on-device but nothing ever re-sent it — the CP had
 * to open that exact log and save again. "Syncs when you reconnect" was not
 * actually built. This is it.
 *
 * SAFETY — what this will and will not push:
 *   • Only keys in the pending index. Those are pushes the user ALREADY
 *     initiated; an abandoned draft is never auto-sent. TWO SOURCES put a key
 *     there, and both are an act of the user's: a push he made that failed,
 *     and an AMENDMENT he asked the server to create (adoptAmendment). The
 *     second is queued from the moment it is adopted because its corrections
 *     live nowhere but the device until it is signed, which may be days.
 *   • Never an EMPTY payload over an existing document — see pushOne.
 *   • Only the STANDARD logbook types, whose payload reconstructs EXACTLY from
 *     what the editors send: create/update {project_id, log_type, date, data,
 *     cp_signature, cp_name, status}. The draft stores precisely those fields
 *     and the key encodes project/type/date, so nothing is guessed.
 *   • DAILY-LOG types ('daily_log', 'site_daily_log') are deliberately SKIPPED:
 *     they post a different, flatter shape to dailyLogsAPI, and inventing a
 *     compliance payload from a partial match is not worth the risk of writing
 *     a malformed record. They stay safe on-device and re-push on the next
 *     manual save. Wiring them needs a per-screen pusher — see the report.
 *
 * A push that fails again just stays pending; the key is only cleared on a
 * confirmed success.
 */

// THE DUPLICATE IS GONE. It read: "Duplicated from signatureAffirmed.js ON
// PURPOSE: this module is loaded by its tests with `new Function` over the
// stripped source, so every import has to be hand-stubbed by each harness. One
// three-line predicate is cheaper than five stubs, and signatureAffirmed.test
// asserts the two definitions still agree."
//
// The harness was the only reason, and it no longer strips imports — see
// esmHarness.cjs, which resolves a relative import for real and stubs only the
// react-native and expo packages plain node cannot load. So the drain now
// imports the same predicate the PDF renderer, the submit gates and the pad
// ask, and there is nothing left to keep in step.
//
// Keeping them in step was string equality, and it would not have survived the
// next change: the moment the shared predicate also requires INK, a
// character-identical copy is impossible without duplicating a second
// predicate too.

const PREFIX = 'logbook_draft:';
// Handled by dailyLogsAPI with a different payload shape — see note above.
const SKIP_LOG_TYPES = new Set(['daily_log', 'site_daily_log']);
// { [logbookId]: { code, key, at } } — the last finalize the SERVER refused for
// that logbook. See recordFinalizeError below for why this exists.
const FINALIZE_ERROR_KEY = 'logbook_finalize_errors';

/** `logbook_draft:{projectId}:{logType}:{date}[:{workerId}]` -> parts, or null. */
export function parseDraftKey(key) {
  if (typeof key !== 'string' || !key.startsWith(PREFIX)) return null;
  const parts = key.slice(PREFIX.length).split(':');
  if (parts.length < 3) return null;
  const [projectId, logType, date, workerId] = parts;
  if (!projectId || !logType || !date) return null;
  return { projectId, logType, date, workerId: workerId || null };
}

/**
 * Pull the finalize completeness-gate CODE out of an axios error.
 *
 * The server rejects an incomplete finalize with `detail: {"code": "..."}` and
 * no prose (backend/server.py:14638-14645) — it names the condition, the client
 * owns the wording. Anything else (offline, 403, 500, a prose `detail`) returns
 * null so the caller shows the generic bilingual message; the server's English
 * `detail` is deliberately never returned from here, so it can never be
 * rendered.
 */
/**
 * SUBMIT_ as well as FINALIZE_. The submit-time gate on create_logbook /
 * update_logbook uses the same convention as the finalize gate — a machine code
 * in `detail.code`, no prose — so one extractor serves both. The export name is
 * unchanged because it is the name every caller and test already uses; what
 * widened is the set of gates the server can refuse at, not the mechanism.
 */
const GATE_CODE = /^(?:FINALIZE|SUBMIT)_[A-Z_]+$/;

export function finalizeErrorCode(e) {
  const detail = e?.response?.data?.detail;
  const code = detail && typeof detail === 'object' ? detail.code : null;
  return typeof code === 'string' && GATE_CODE.test(code) ? code : null;
}

/**
 * Did the SERVER judge this request, or did it never arrive?
 *
 * A 4xx is a refusal: the server looked at the log and said no, and it will keep
 * saying no until the log changes. Anything else — no response at all, a 5xx —
 * is not a judgement and must never be reported to the CP as one. Mirrors the
 * three-way split daily_jobsite.jsx makes on the foreground finalize path.
 */
function isServerRefusal(e) {
  const status = e?.response?.status;
  return typeof status === 'number' && status >= 400 && status < 500;
}

/**
 * WHY THIS EXISTS — the drain has no screen.
 *
 * syncPendingDrafts runs from a NetInfo transition and at startup (see
 * setupDraftAutoSync below), with no component mounted and no toast context, so
 * a rejection here cannot be shown at the moment it happens. It used to be
 * swallowed outright, which meant a log the CP signed and froze OFFLINE could be
 * refused by the server's completeness gate forever with NOTHING on screen ever
 * saying so — the device shows FINALIZED, the server has no locked record.
 *
 * So the rejection is recorded against the logbook id and surfaced at the next
 * screen interaction instead: LogbookLockBar reads it for the log being viewed
 * and renders a persistent banner. Keyed by logbook id, not by draft key, so the
 * banner can only ever appear on the log it belongs to. Cleared on the first
 * finalize that succeeds, from either path.
 *
 * EXPORTED, because the drain is no longer the only writer. An editor that
 * takes a refusal in the foreground shows a toast — and a toast is gone in four
 * seconds, so if the CP walks off the screen the refusal has left no trace and
 * the log reads as merely unfinalized. Recording it here as well means the SAME
 * durable banner LogbookLockBar already renders for a background refusal also
 * survives a foreground one. Storage key and record shape are unchanged; the
 * two writers are indistinguishable to the reader by design.
 */
export async function recordFinalizeError(logId, code, key, source = 'drain') {
  if (!logId) return;
  try {
    const raw = await AsyncStorage.getItem(FINALIZE_ERROR_KEY);
    const map = raw ? JSON.parse(raw) : {};
    map[String(logId)] = { code: code || null, key, at: Date.now(), source };
    await AsyncStorage.setItem(FINALIZE_ERROR_KEY, JSON.stringify(map));
  } catch (_e) { /* non-fatal — the draft is still pending either way */ }
}

/** The recorded rejection for a logbook, or null. */
export async function readFinalizeError(logId) {
  if (!logId) return null;
  try {
    const raw = await AsyncStorage.getItem(FINALIZE_ERROR_KEY);
    if (!raw) return null;
    return JSON.parse(raw)[String(logId)] || null;
  } catch (_e) {
    return null;
  }
}

/** Drop the record — the log finalized, so the banner must go. */
export async function clearFinalizeError(logId) {
  if (!logId) return;
  try {
    const raw = await AsyncStorage.getItem(FINALIZE_ERROR_KEY);
    if (!raw) return;
    const map = JSON.parse(raw);
    if (!(String(logId) in map)) return;
    delete map[String(logId)];
    await AsyncStorage.setItem(FINALIZE_ERROR_KEY, JSON.stringify(map));
  } catch (_e) { /* non-fatal */ }
}

/**
 * Take down the ON THIS DEVICE ONLY banner once the push has landed.
 *
 * BOTH HANDLES, and that is the point. The editor records the banner against
 * `existingLogId || draftKey`, so an offline CREATE — the case that most needs
 * the banner — is recorded against the KEY, because no server id existed yet.
 * Clearing by id alone would leave that one up forever, and a banner that
 * cannot come down is how a CP learns to read past all of them.
 */
async function clearUnsyncedBanner(key, logId) {
  await clearFinalizeError(key);
  if (logId) await clearFinalizeError(logId);
}

async function pushOne(key) {
  const parsed = parseDraftKey(key);
  if (!parsed) return { key, ok: false, reason: 'unparseable-key' };
  if (SKIP_LOG_TYPES.has(parsed.logType)) return { key, ok: false, reason: 'skipped-type' };

  const draft = await readDraft(key);
  if (!draft) {
    // The draft is gone; stop tracking the key so it can't leak forever.
    await clearPending(key);
    return { key, ok: false, reason: 'no-draft' };
  }
  // NOTE — a `finalized` draft is NOT skipped. It used to be, and that was a
  // data-loss bug: a log signed and FROZEN OFFLINE (the whole point of
  // sign-freeze for below-grade pre-work) is finalized locally BEFORE it has
  // ever reached the server, so skipping it here silently dropped a signed
  // compliance record from the sync queue forever. Being in the pending index
  // IS the proof its push has not landed, so it must be sent. After the content
  // lands we apply the server-side lock too, so the freeze survives the round
  // trip. (A draft whose push already succeeded was cleared from the index and
  // never reaches this code, so there is no re-push of an already-locked doc.)

  // ── PHOTOS FIRST ────────────────────────────────────────────────────────
  // A daily_jobsite draft can hold photos whose upload never landed: taken in
  // a dead zone, or dropped mid-upload. Each is a real file in
  // documentDirectory with `upload_pending` on its row, and THIS is what gets
  // them into R2 — before the content push, so the document the server
  // receives NAMES its photos instead of describing them as pending.
  //
  // It also closes a hole that predates the R2 work: this drain has always
  // pushed `draft.data`, and the draft has never stored base64, so a log that
  // only ever reached the server through the drain arrived with photo entries
  // that carried no image data at all.
  //
  // A photo that still has not uploaded leaves the key PENDING below, even
  // when the content push succeeds. Nothing else would ever retry it.
  let data = draft.data || {};
  let photosStillPending = false;
  if (Array.isArray(data.activities)) {
    const shipped = await uploadPendingActivityPhotos(parsed.projectId, data.activities);
    if (shipped.uploaded > 0) {
      data = { ...data, activities: shipped.activities };
      await writeDraft(key, { data });
    }
    photosStillPending = shipped.remaining > 0;
  }

  const body = {
    data,
    cp_signature: draft.cp_signature,
    cp_name: draft.cp_name,
    status: draft.status || 'draft',
  };

  // ── A DRAFT THAT SAYS NOTHING NEVER OVERWRITES A DOCUMENT THAT DOES ──────
  // update_logbook takes `data` verbatim, so pushing `{}` blanks the stored
  // record. That is reachable now: a key is queued the moment an amendment is
  // ADOPTED (see adoptAmendment), and at that instant the local draft is a
  // freshly bound shell — no content yet, while the server's child already
  // holds the whole log copied from its parent. A drain in that window would
  // empty the very document the amendment exists to correct.
  //
  // Left PENDING rather than cleared: the draft has nothing to send YET, which
  // is not a failure and not a completed push. The next drain, after the CP has
  // actually typed something, sends it. A CREATE is unaffected — an empty
  // create writes an empty record and destroys nothing.
  if (draft.backend_id && Object.keys(data || {}).length === 0) {
    return { key, ok: false, reason: 'empty-draft', logId: draft.backend_id };
  }

  // ── DO NOT PUSH AN UNSIGNED SUBMIT ──────────────────────────────────────
  // The draft stores `status` and `cp_signature` independently (logbookDrafts
  // writeDraft), so a form with no signature guard could write
  // `status: 'submitted', cp_signature: null` and this drain would replay it
  // verbatim. For an IMMEDIATE type the server locks on `status: submitted`, so
  // that replay is how an unsigned log becomes a permanent record with nobody
  // watching. Caught here rather than left to the server gate for one reason:
  // the key must stay pending and the refusal must be recorded, and doing it
  // before the request means the CP gets the same durable banner whether or not
  // he ever had signal. The draft is untouched and still editable — signing the
  // log rewrites it and the next drain sends it.
  //
  // AFFIRMED, not merely present. `!body.cp_signature` is the same predicate
  // the nine forms used to gate on, and production held `cp_signature: {}` —
  // an empty object, truthy, which satisfied it. The drain must ask the
  // question the PDF renderer asks, or a draft the CP can no longer submit
  // still drains through behind him. Same rule as the injury/PPE drain gate
  // below and for the same reason.
  if (body.status === 'submitted' && !isAffirmedSignature(body.cp_signature)) {
    const target = draft.backend_id || key;
    await recordFinalizeError(target, 'SUBMIT_MISSING_CP_SIGNATURE', key);
    return { key, ok: false, reason: 'unsigned-submit', code: 'SUBMIT_MISSING_CP_SIGNATURE', logId: draft.backend_id || null };
  }

  // THE SAME REPLAY, FOR INCOMPLETE CONTENT — option B, as ruled.
  //
  // #127 made injury and PPE required on the pre-shift sheet, client-side. A
  // client gate cannot reach THIS path by construction: a draft written on an
  // older build, or before the OTA was applied, drains straight through with
  // both answers null and the server accepts it (preshift_signin has no server
  // gate, deliberately — a refusal must never meet a CP mid-shift).
  //
  // Refusing HERE rather than server-side is what keeps that promise: the
  // drain runs in the background, after he has left the screen, so it cannot
  // stop a man at the gate. And it fails into a state that already exists —
  // durable banner, editable draft, indefinite retry — so it invents no new
  // failure mode. `clearPending` is not called, exactly as above.
  //
  // ONLY ROWS WITH A NAME, matching the client gate: a blank spare row is not
  // a worker. An old payload with no `workers` array at all is not this gate's
  // business and passes through.
  if (body.status === 'submitted' && parsed && parsed.logType === 'preshift_signin') {
    const _rows = (body.data && Array.isArray(body.data.workers)) ? body.data.workers : [];
    const _unanswered = _rows.filter((w) => w && String(w.name || '').trim()
      && (w.had_injury === null || w.had_injury === undefined
        || w.inspected_ppe === null || w.inspected_ppe === undefined)).length;
    if (_unanswered > 0) {
      const target = draft.backend_id || key;
      await recordFinalizeError(target, 'SUBMIT_INCOMPLETE_WORKER_ANSWERS', key);
      return {
        key, ok: false, reason: 'incomplete-worker-answers',
        code: 'SUBMIT_INCOMPLETE_WORKER_ANSWERS', logId: draft.backend_id || null,
      };
    }
  }

  // Re-apply the freeze server-side once the content has landed, so a log signed
  // offline is locked on the server too. This covers the END_OF_DAY logs, whose
  // freeze is an explicit /finalize (an immediate type auto-locks on
  // `status: submitted` anyway).
  //
  // NO LONGER BEST-EFFORT. This was `catch (_e) {}` and then the caller cleared
  // the pending key regardless, so a server that REFUSED the freeze produced a
  // silent, permanent divergence: locked on the device, unlocked and unrecorded
  // on the server, and dropped from the retry queue so nothing would ever try
  // again. A refusal now (a) is recorded for the UI to surface and (b) fails the
  // push, which leaves the key PENDING — the content update above is idempotent,
  // so the next drain re-sends it and retries the freeze. Retry behaviour is
  // otherwise unchanged; there is still no cap.
  const applyRemoteFreeze = async (id) => {
    if (!draft.finalized || !id) return { ok: true, code: null };
    try {
      await logbooksAPI.finalize(id);
      await clearFinalizeError(id);
      return { ok: true, code: null };
    } catch (e) {
      const code = finalizeErrorCode(e);
      await recordFinalizeError(id, code, key);
      return { ok: false, code };
    }
  };

  try {
    if (draft.backend_id) {
      await logbooksAPI.update(draft.backend_id, body);
      const frozen = await applyRemoteFreeze(draft.backend_id);
      if (!frozen.ok) {
        return { key, ok: false, reason: 'finalize-refused', code: frozen.code, logId: draft.backend_id };
      }
      if (!photosStillPending) await clearPending(key);
      await clearUnsyncedBanner(key, draft.backend_id);
      return { key, ok: true, mode: 'update', photosPending: photosStillPending };
    }
    const created = await logbooksAPI.create({
      project_id: parsed.projectId,
      log_type: parsed.logType,
      date: parsed.date,
      ...body,
    });
    const newId = created?.id || created?._id;
    if (newId) await setDraftBackendId(key, newId);
    const frozen = await applyRemoteFreeze(newId);
    if (!frozen.ok) {
      return { key, ok: false, reason: 'finalize-refused', code: frozen.code, logId: newId };
    }
    if (!photosStillPending) await clearPending(key);
    await clearUnsyncedBanner(key, newId);
    return { key, ok: true, mode: 'create', photosPending: photosStillPending };
  } catch (e) {
    // Still offline, or the server REFUSED. Those are not the same thing and
    // must not look the same to the CP.
    //
    // This used to return {ok:false} and nothing else, which left the key
    // pending with NOTHING on any screen ever saying why — the same silent
    // shape the finalize path was fixed for. A 4xx is a judgement the server
    // will keep making, so it is recorded and surfaced; anything else (no
    // response, a 5xx) is genuinely retryable and stays quiet, because claiming
    // a refusal that did not happen is its own kind of lie.
    //
    // Recorded against backend_id when the log exists, and against the DRAFT
    // KEY when it does not — a rejected create has no logbook id to hang a
    // banner on, and the editor knows its own draft key. Same storage, same
    // record shape, same banner; only the lookup handle differs.
    if (isServerRefusal(e)) {
      const target = draft.backend_id || key;
      await recordFinalizeError(target, finalizeErrorCode(e), key);
      return {
        key, ok: false, reason: 'push-refused',
        code: finalizeErrorCode(e), logId: draft.backend_id || null,
      };
    }
    return { key, ok: false, reason: e?.message || 'push-failed' };
  }
}

/** Drain every pending logbook draft. Safe to call repeatedly. */
export async function syncPendingDrafts() {
  let keys = [];
  try { keys = await getPendingKeys(); } catch (_e) { return { attempted: 0, synced: 0, finalizeRefused: 0 }; }
  if (!keys.length) return { attempted: 0, synced: 0, finalizeRefused: 0 };

  let synced = 0;
  let refused = 0;
  for (const key of keys) {
    const r = await pushOne(key);
    if (r.ok) synced += 1;
    else if (r.reason === 'finalize-refused' || r.reason === 'push-refused' || r.reason === 'unsigned-submit') {
      refused += 1;
      // Diagnostic only. The user-visible surface is the banner LogbookLockBar
      // renders from the record written above — this drain has no screen.
      console.warn(`[draftSync] ${r.reason} for ${r.logId || r.key} (${r.code || 'no code'}); staying pending`);
    }
  }
  if (synced) console.log(`[draftSync] pushed ${synced}/${keys.length} pending draft(s)`);
  return { attempted: keys.length, synced, finalizeRefused: refused };
}

/**
 * Drain on every offline -> online transition. Mirrors offlineQueue's
 * setupAutoQueueProcessing shape. Returns an unsubscribe fn.
 */
export function setupDraftAutoSync() {
  let wasOnline = true;
  const unsubscribe = NetInfo.addEventListener((state) => {
    const online = state.isConnected && state.isInternetReachable !== false;
    if (online && !wasOnline) {
      syncPendingDrafts().catch(() => {});
    }
    wasOnline = online;
  });
  // Also try once at startup: the app may have been killed while pending.
  syncPendingDrafts().catch(() => {});
  return unsubscribe;
}
