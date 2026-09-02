import { dailyLogsAPI } from './api';
import { registerDraftPusher } from './draftSync';

/**
 * THE DAILY LOG'S OWN PUSHER — the half draftSync could not write.
 *
 * WHAT IT FIXES. draftSync's reconnect drain refuses 'daily_log' and
 * 'site_daily_log' (SKIP_LOG_TYPES), and the refusal is correct: those two post
 * a flatter shape to dailyLogsAPI than the generic drain can rebuild from a
 * draft, and a compliance record assembled from a partial match is worse than
 * one that is late. But nothing ever told the SCREENS, and the screens said
 * "this log will sync when you are back online" — in a green success toast, on
 * a gate tablet, to a superintendent filing his required §3301.13.13 log. The
 * key went into the pending index and stayed there for the life of the install.
 *
 * WHY THIS IS ALLOWED TO PUSH WHAT THE DRAIN IS NOT. It does not reconstruct
 * anything. The screen builds its request body at submit time — the same object
 * it hands dailyLogsAPI on the online path, with the audit stamps taken at the
 * moment of the user's action — and records it in the draft as `push_body`.
 * This module sends THAT, verbatim. There is no mapping step here for a field
 * to be dropped from or invented in, which is the entire reason it is safe to
 * do what draftSync would not.
 *
 * REGISTERED AT APP START, NOT BY A SCREEN. The drain runs from a NetInfo
 * transition with nothing mounted — the superintendent is at the gate or the
 * app is in the background — so a pusher owned by a screen's lifecycle would be
 * absent at exactly the moment it is needed. app/_layout.jsx registers these
 * once, before setupDraftAutoSync, and the existing NetInfo listener is the
 * only trigger. Nothing here adds a second one.
 *
 * ONE FUNCTION FOR BOTH TYPES. The CP's daily log (app/daily-log.jsx,
 * 'daily_log') and the superintendent's (app/site/daily-logs.jsx,
 * 'site_daily_log') are different screens over the SAME endpoint with the same
 * body shape, and both were telling the same lie. Two registrations, one
 * implementation — a second copy would be a second thing to keep in step.
 */

/**
 * Send one recorded daily-log body.
 *
 * UPDATE WHEN THE DRAFT KNOWS A SERVER ID, CREATE OTHERWISE — the same branch
 * the screen takes, on the same id it persisted. Getting this backwards is how
 * a day ends up with two logs: a create fired because a load failed is exactly
 * the duplicate `backend_id` was introduced to stop.
 *
 * The body carries `project_id` and `date` for the create. The update endpoint
 * pops `project_id` before its `$set` (ownership is fixed at creation), so the
 * one body serves both calls without being edited here.
 *
 * THROWS on failure, deliberately: draftSync's caller owns the three-way split
 * between a server refusal, an unreachable server, and success, and it must be
 * made in one place for every log type.
 */
export async function pushDailyLogDraft({ draft, body }) {
  if (draft.backend_id) {
    await dailyLogsAPI.update(draft.backend_id, body);
    return { mode: 'update', backendId: draft.backend_id };
  }
  const created = await dailyLogsAPI.create(body);
  // A create with no id in the response still LANDED — the log is on the
  // server, and re-sending it on the next reconnect would file a duplicate. So
  // the key is cleared either way; the next successful load rebinds the id from
  // the server list, which is the same repair path a failed read already uses.
  return { mode: 'create', backendId: created?.id || created?._id || null };
}

/**
 * Wire both daily-log types into the reconnect drain. Call once at app start.
 * Returns an unregister fn (the drain then refuses these types again, exactly
 * as it did before this module existed).
 */
export function registerDailyLogPushers() {
  const offSite = registerDraftPusher('site_daily_log', pushDailyLogDraft);
  const offCp = registerDraftPusher('daily_log', pushDailyLogDraft);
  return () => { offSite(); offCp(); };
}
