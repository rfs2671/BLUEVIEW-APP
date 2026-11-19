/**
 * Log Books for everyone who READS THE LOGS AND ADDS PHOTOGRAPHS.
 *
 * The server's ruling (ROLES_THAT_FILE_LOGBOOKS in backend/server.py, operator
 * ruling 2026-11-18): only the SUPERINTENDENT and the CP fill in and sign a
 * log. A Site Manager / PM at EITHER level ("Assigned jobs only" and "Same as
 * admin") and a company admin may read a log and add photographs to it, and
 * may not create, edit, sign, finalize or amend one. This module is the
 * client's copy of that one rule, asked by every place that would otherwise
 * invite a reader to write.
 *
 * AN ALLOW-LIST, LIKE THE SERVER'S. It used to answer "a PM not on Same as
 * admin", which left the full PM and the admin a form the ruling withholds.
 * The site device is not a reader: its screens live under app/site and the
 * server lets it through this gate unchanged.
 *
 * WHICH JOBS. A PM on "Assigned jobs only" lists his assigned_projects and
 * nothing else; "Same as admin" and an admin list every job the company runs.
 * The same split the server's project_access_ok makes, so the picker cannot
 * offer a job that 403s.
 */

import { ROLE_PM, pmAccessLevel, PM_ACCESS_FULL } from './roleVocabulary';

/** The people who fill in and sign a log. Mirrors ROLES_THAT_FILE_LOGBOOKS. */
export const ROLES_THAT_FILE_LOGBOOKS = ['superintendent', 'cp'];
const LOGBOOK_DEVICE_ROLE = 'site_device';

function roleOf(user) {
  return String((user || {}).role || '').trim().toLowerCase();
}

function isPm(user) {
  return roleOf(user) === ROLE_PM;
}

/**
 * True for a signed-in principal whose logbooks are view-only (plus
 * photographs): everyone but the superintendent, the CP and the gate tablet.
 * No user yet (auth still loading) answers false, as before.
 */
export function readsLogbooksOnly(user) {
  if (!user) return false;
  const role = roleOf(user);
  return !ROLES_THAT_FILE_LOGBOOKS.includes(role) && role !== LOGBOOK_DEVICE_ROLE;
}

/** The project tile, and the PM's own nav on the hub: every PM. */
export function canOpenLogBooksTile(user) {
  return isPm(user);
}

/**
 * The jobs his Log Books picker lists. Only a PM on "Assigned jobs only" is
 * narrowed; everyone else passes through unchanged — an admin and a "Same as
 * admin" PM see every job, and the screen's own CP rule still applies to a CP.
 */
export function pmLogbookProjects(user, list) {
  const arr = Array.isArray(list) ? list : [];
  if (!isPm(user) || pmAccessLevel(user) === PM_ACCESS_FULL) return arr;
  const mine = new Set(((user || {}).assigned_projects || []).map(String));
  return arr.filter((p) => mine.has(String(p.id || p._id)));
}

/**
 * Whether a tile opens for a reader. A FILED log opens to the read-only filed
 * view (and its photographs); an unfiled one is the filer's work in progress,
 * and the editor would let a reader type into a form the server refuses to
 * save.
 */
export function pmMayOpen(status) {
  return status === 'submitted';
}

// English, then Spanish: the people who read these are on site.
export const PM_LOGBOOKS_NOTE =
  'View-only. You can read filed logs and add photographs to today’s. '
  + 'Filing is done by the superintendent or the CP. / '
  + 'Solo lectura. Puede leer los registros presentados y añadir fotos a los de hoy. '
  + 'Los registros los llena el superintendente o el CP.';

export const PM_NOT_FILED_TITLE = 'Not filed yet / Aún no presentado';
export const PM_NOT_FILED_BODY =
  'You can read this log once it is filed. Filing is done by the superintendent or the CP. / '
  + 'Podrá leer este registro cuando se presente. Lo llena el superintendente o el CP.';
