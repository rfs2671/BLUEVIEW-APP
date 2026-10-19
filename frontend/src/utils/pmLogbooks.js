/**
 * The Site Manager / PM in Log Books: READS THE LOGS, ADDS PHOTOGRAPHS.
 *
 * The server's ruling (ROLES_WITH_READ_ONLY_LOGBOOKS in backend/server.py):
 * a PM may read a log and add photographs to it, but may not create, edit,
 * finalize, amend or delete one. The app had no way in for him at all — his
 * nav and his project screen never linked to /logbooks — so this module is
 * the client's copy of that one rule, asked by every place that would
 * otherwise invite him to write.
 *
 * WHICH JOBS. "Assigned jobs only" is his assigned_projects and nothing else;
 * "Same as admin" is every job the company runs. The same split the server's
 * project_access_ok makes, so the picker cannot offer a job that 403s.
 */

import { ROLE_PM, pmAccessLevel, PM_ACCESS_FULL } from './roleVocabulary';

/** True for the role whose logbooks are view-only (plus photographs). */
export function readsLogbooksOnly(user) {
  return String((user || {}).role || '').trim().toLowerCase() === ROLE_PM;
}

/** The project tile: every PM, whatever his access level. */
export function canOpenLogBooksTile(user) {
  return readsLogbooksOnly(user);
}

/**
 * The jobs his Log Books picker lists. Non-PMs pass through unchanged — the
 * screen's own CP rule still applies to them.
 */
export function pmLogbookProjects(user, list) {
  const arr = Array.isArray(list) ? list : [];
  if (!readsLogbooksOnly(user)) return arr;
  if (pmAccessLevel(user) === PM_ACCESS_FULL) return arr;
  const mine = new Set(((user || {}).assigned_projects || []).map(String));
  return arr.filter((p) => mine.has(String(p.id || p._id)));
}

/**
 * Whether a tile opens for him. A FILED log opens to the read-only filed view
 * (and its photographs); an unfiled one is the CP's work in progress, and the
 * editor would let him type into a form the server refuses to save.
 */
export function pmMayOpen(status) {
  return status === 'submitted';
}

export const PM_LOGBOOKS_NOTE =
  'View-only. You can read filed logs and add photographs to today’s.';

export const PM_NOT_FILED_TITLE = 'Not filed yet';
export const PM_NOT_FILED_BODY =
  'You can read this log once it is filed. Filing is done by the CP or superintendent.';
