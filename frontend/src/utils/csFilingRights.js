/**
 * WHOSE LOG IS THIS — read from the server, never guessed.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 *
 * The logbook list rendered `required_logbooks` verbatim.
 * `site_superintendent_log` enters that list when the PROJECT's
 * `superintendent_log_active` is true, which is a fact about the project and
 * asks nobody who the caller is. The filing gate on the server reads
 * `cs_registrations` and compares the SIGNER, which is a fact about the person.
 * No frontend file read `cs_registrations` at all — it cannot; that collection
 * is not exposed.
 *
 * So on 588 Thomas nine accounts saw the tile and eight of them were refused at
 * submit: an owner, four admins, a second owner, and a competent person
 * genuinely assigned to the project. The gate runs on create and on PUT ONLY AT
 * SUBMIT — drafts save clean, deliberately — so the refusal arrived after the
 * whole log was filled, at the end of the day, on a record BC 3301.13.13
 * requires completed before he leaves the site.
 *
 * ── WHAT THIS READS ─────────────────────────────────────────────────────────
 *
 * GET /projects/{id}/required-logbooks now answers the gate's question for the
 * caller who is asking, from the SAME server-side read the gate makes:
 *
 *     filing: [{log_type, may_file, registered_name, reason}]
 *
 * ── DEFAULT TRUE, AND IT IS NOT A DETAIL ────────────────────────────────────
 *
 * Every function here treats "no answer" as "he may file":
 *
 *   an older server that sends no `filing` key      -> may file
 *   a log type with no row                          -> may file
 *   a project that has registered NOBODY            -> may file
 *
 * The last one is the server's deliberate choice and this must not quietly
 * reverse it. `cs_filing_refused` refuses only NOT_REGISTERED_CS — the project
 * HAS named somebody and this is not him — because blocking a statutory log
 * over a field an admin never filled in punishes the superintendent for the
 * office's omission. A tile that claimed an owner the project has not named
 * would re-introduce that refusal in the UI, where there is no gate to argue
 * with. A tile that went quiet because the server is old would do it by
 * accident.
 *
 * ── AND THE WORDING COMES FROM ONE PLACE ────────────────────────────────────
 *
 * `whoFilesReason` returns the SAME sentence the submit refusal returns, built
 * by the same resolver over the same `finalize` copy. One condition must not be
 * described two ways depending on whether the client or the server noticed it.
 */
import { refusalCopy } from './csRefusalCopy';

/** The one log type whose filing belongs to a named person. */
export const CS_LOG_TYPE = 'site_superintendent_log';

/** `filing` from the required-logbooks payload, keyed by log type. */
export function filingRights(payload) {
  const rows = payload && Array.isArray(payload.filing) ? payload.filing : [];
  const out = {};
  rows.forEach((row) => {
    if (row && typeof row.log_type === 'string') out[row.log_type] = row;
  });
  return out;
}

/** The row for a type, only when it actually withholds the log. */
function withheld(rights, logType) {
  const row = rights && rights[logType];
  return row && row.may_file === false ? row : null;
}

/** May THIS caller file this log? Anything unknown answers yes — see header. */
export function mayFile(rights, logType) {
  return !withheld(rights, logType);
}

/** The man the project registered, or null. */
export function ownerName(rights, logType) {
  const row = withheld(rights, logType);
  const name = row && typeof row.registered_name === 'string'
    ? row.registered_name.trim() : '';
  return name || null;
}

/**
 * The line that replaces the tile's subtitle, or null when the log is his.
 *
 * THE SAME THREE-STATE SHAPE THE ACTIVATION ROWS ALREADY USE. "Off — an admin
 * switches this one on" exists because a CP hunting for the hot-work log needs
 * to know it EXISTS and who turns it on, not to find a dead control. A required
 * log he cannot file is the same problem with higher stakes: hiding the tile
 * would leave him unable to see that the document exists or learn who owns it.
 */
export function whoFilesLabel(rights, logType) {
  const row = withheld(rights, logType);
  if (!row) return null;
  const name = ownerName(rights, logType);
  return name
    ? `${name} files this one — it is his own record`
    // No name on the registration. Still not a dead end: it says the project
    // has named somebody, which is what makes the office the next stop.
    : 'The superintendent this project registered files this one';
}

/** The short title for the tap, naming him where there is a name. */
export function whoFilesTitle(rights, logType) {
  const name = ownerName(rights, logType);
  return name ? `${name} files this one` : 'Not yours to file';
}

/**
 * Why, in the words the SUBMIT refusal uses. `t` is a translator over the
 * `finalize` namespace (useT('finalize')).
 *
 * The filing row carries `registered_name`, which is the field
 * `refusalCopy` interpolates — so the row can be handed over as the detail
 * unchanged, and the sentence he reads on the tile is the sentence he would
 * have read after signing.
 */
export function whoFilesReason(rights, logType, t) {
  const row = withheld(rights, logType);
  return row ? refusalCopy(row.reason, row, t) : null;
}

export default {
  CS_LOG_TYPE,
  filingRights,
  mayFile,
  ownerName,
  whoFilesLabel,
  whoFilesTitle,
  whoFilesReason,
};
