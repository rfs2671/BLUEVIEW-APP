import NetInfo from '@react-native-community/netinfo';
import { logbooksAPI } from './api';
import {
  getPendingKeys, readDraft, setDraftBackendId, clearPending,
} from './logbookDrafts';

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
 *     initiated and that failed; an abandoned draft is never auto-sent.
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

const PREFIX = 'logbook_draft:';
// Handled by dailyLogsAPI with a different payload shape — see note above.
const SKIP_LOG_TYPES = new Set(['daily_log', 'site_daily_log']);

/** `logbook_draft:{projectId}:{logType}:{date}[:{workerId}]` -> parts, or null. */
export function parseDraftKey(key) {
  if (typeof key !== 'string' || !key.startsWith(PREFIX)) return null;
  const parts = key.slice(PREFIX.length).split(':');
  if (parts.length < 3) return null;
  const [projectId, logType, date, workerId] = parts;
  if (!projectId || !logType || !date) return null;
  return { projectId, logType, date, workerId: workerId || null };
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

  const body = {
    data: draft.data || {},
    cp_signature: draft.cp_signature,
    cp_name: draft.cp_name,
    status: draft.status || 'draft',
  };

  // Re-apply the freeze server-side once the content has landed, so a log signed
  // offline is locked on the server too. Best-effort: the content is already
  // safe, and an immediate type auto-locks on `status: submitted` anyway — this
  // is what covers the END_OF_DAY logs, whose freeze is an explicit /finalize.
  const applyRemoteFreeze = async (id) => {
    if (!draft.finalized || !id) return;
    try { await logbooksAPI.finalize(id); } catch (_e) { /* already locked, or retry next drain */ }
  };

  try {
    if (draft.backend_id) {
      await logbooksAPI.update(draft.backend_id, body);
      await applyRemoteFreeze(draft.backend_id);
      await clearPending(key);
      return { key, ok: true, mode: 'update' };
    }
    const created = await logbooksAPI.create({
      project_id: parsed.projectId,
      log_type: parsed.logType,
      date: parsed.date,
      ...body,
    });
    const newId = created?.id || created?._id;
    if (newId) await setDraftBackendId(key, newId);
    await applyRemoteFreeze(newId);
    await clearPending(key);
    return { key, ok: true, mode: 'create' };
  } catch (e) {
    // Still offline, or the server refused. Leave it pending and try later.
    return { key, ok: false, reason: e?.message || 'push-failed' };
  }
}

/** Drain every pending logbook draft. Safe to call repeatedly. */
export async function syncPendingDrafts() {
  let keys = [];
  try { keys = await getPendingKeys(); } catch (_e) { return { attempted: 0, synced: 0 }; }
  if (!keys.length) return { attempted: 0, synced: 0 };

  let synced = 0;
  for (const key of keys) {
    const r = await pushOne(key);
    if (r.ok) synced += 1;
  }
  if (synced) console.log(`[draftSync] pushed ${synced}/${keys.length} pending draft(s)`);
  return { attempted: keys.length, synced };
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
