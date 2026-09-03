/**
 * WHAT A FILED LOG IS, READ OFF THE SERVER'S COPY.
 *
 * A filed record is not being composed. Rendering it as a disabled five-step
 * form is what made the photograph panel read as an exception bolted onto an
 * editor — so the locked editor route renders THIS instead: what was filed,
 * who signed it and when, and, only where the type has them, the photographs.
 *
 * EVERYTHING HERE IS PURE AND TAKES A SERVER DOCUMENT. Not reconciled local
 * state: a filed-but-unlocked log has been merged against the roster in the
 * editor and `withActivityIds` has minted ids for rows that never had one, and
 * a photograph aimed at an invented id reaches nothing. The document this
 * reads is the one the append route will be pointed at.
 *
 * ── THE PHOTOGRAPHS RULE, WHICH IS THE PART THAT GOES WRONG ─────────────────
 *
 * Three states, and the first two are NOT the same fact:
 *
 *   1. the TYPE's schema cannot carry photographs   -> NO SECTION AT ALL
 *   2. the type can, and none are attached          -> section, says so, Add
 *   3. the type can, and some are                   -> the photographs, Add
 *
 * State 1 is ABSENCE, and it has to be. An absent section makes no claim; an
 * empty section claims "this record has a place for photographs and it is
 * empty". On a toolbox talk that is false — there is no such place and the
 * record is complete — so ten of twelve filed records would show a
 * manufactured gap to whoever is reading them, which is the opposite of what a
 * filed view is for. Same rule as SST_UNSPECIFIED (the label says what the
 * card states and nothing more) and as SiteReadinessNotice returning null
 * rather than printing "everything is fine".
 *
 * AND THE DECISION IS THE LOG TYPE'S, NEVER `data`'s. A daily_jobsite whose
 * activities array is missing is a DIFFERENT FACT from a toolbox talk having
 * no such concept. Deciding state 1 from "activities is absent or empty" would
 * conflate them, and a reader that cannot tell those apart is exactly the
 * defect shape this repo has shipped before — a keep-set that could see one of
 * two list formats, a reader naming a field no writer produces.
 */

/**
 * THE TWO TYPES WHOSE ROWS CARRY `photos[]`. A SCHEMA FACT, written down once.
 *
 * daily_jobsite  — dailyJobsiteModel, activities[].photos[]
 * fall_protection — fallProtectionModel EMPTY_ROW carries `photos` and
 *                   `activity_id`, and draftBody wraps the rows as
 *                   `{ activities: rows }` precisely so the photo machinery
 *                   (R2 key, the report's positional URL) is shared.
 *
 * The other eleven registered types have no such field, and adding a thirteenth
 * type must be a DECISION recorded here rather than an inheritance — which is
 * why filedLogSummary.test.cjs holds the complete other side by name and
 * checks it against LOGBOOK_TYPE_REGISTRY in server.py.
 */
export const PHOTO_CARRYING_LOG_TYPES = Object.freeze([
  'daily_jobsite',
  'fall_protection',
]);

/** Can THIS LOG TYPE carry activity photographs? Asks the type, never the data. */
export function typeCarriesActivityPhotos(logType) {
  if (typeof logType !== 'string' || !logType) return false;
  return PHOTO_CARRYING_LOG_TYPES.includes(logType);
}

/** The server's activity rows, or [] — never local state's. */
export function serverActivities(log) {
  const rows = log && log.data && log.data.activities;
  return Array.isArray(rows) ? rows : [];
}

/**
 * A row's human label, built from whichever identifying fields the type has.
 *
 * daily_jobsite names a crew (company / trade / work); fall_protection names a
 * worker and a piece of equipment. One function rather than two so a third
 * type cannot arrive with an unlabelled row — an unlabelled row on a
 * photographs screen is a photograph aimed at nothing in particular.
 */
export function activityRowLabel(row) {
  if (!row || typeof row !== 'object') return '';
  const parts = [
    row.company || row.sub_name || row.worker_name,
    row.trade || row.equipment_type,
    row.work_description,
    row.work_locations,
  ];
  return parts
    .map((x) => (Array.isArray(x) ? x.join(', ') : String(x == null ? '' : x)).trim())
    .filter(Boolean)
    .join(' · ');
}

/**
 * THE PHOTOGRAPHS SECTION, or null. The ONE place the three states are decided.
 *
 * Returns null for state 1. Otherwise:
 *   { present: true, empty, photoCount, remediable, rows: [...] }
 * where each row is
 *   { activity_id, activity_index, label, can_add, photos: [{...photo,
 *     photo_index}] }
 *
 * THE INDEXES ARE THE SERVER DOCUMENT'S and they are carried rather than left
 * to whoever renders. /api/reports/logbook-photo/{id}/{ai}/{pi} is POSITIONAL,
 * so an index recomputed off a filtered or re-ordered list points at a
 * different photograph — on a signed compliance record.
 *
 * `can_add` IS FALSE FOR A ROW WITH NO `activity_id`, and its identity is
 * reported as null rather than substituted. The append route matches the ROW
 * on that id, so sending anything else aims the push at nothing; the server
 * refuses those rows by name (409 ACTIVITY_HAS_NO_IDENTITY) and says the
 * refusal is `remediable` via backfill_activity_id.py. `remediable` here is
 * that same machine fact, computed from the document, so the screen can tell
 * the CP there is something to ask an administrator for instead of showing him
 * a dead end.
 */
export function photographsSection(log) {
  const logType = log && typeof log === 'object' ? log.log_type : null;
  // STATE 1 — decided by the TYPE, before `data` is looked at at all.
  if (!typeCarriesActivityPhotos(logType)) return null;

  const rows = serverActivities(log).map((row, activity_index) => {
    const raw = row && typeof row === 'object' ? row : {};
    const id = String(raw.activity_id || '').trim();
    const photos = (Array.isArray(raw.photos) ? raw.photos : [])
      .map((p, photo_index) => ({ ...(p && typeof p === 'object' ? p : {}), photo_index }));
    return {
      activity_id: id || null,
      activity_index,
      label: activityRowLabel(raw),
      can_add: Boolean(id),
      photos,
    };
  });

  const photoCount = rows.reduce((n, r) => n + r.photos.length, 0);
  return {
    present: true,
    empty: photoCount === 0,
    photoCount,
    // The whole-log fact, so the screen says it once instead of per row.
    remediable: rows.some((r) => !r.can_add),
    rows,
  };
}

// ── THE CONTENT SUMMARY ─────────────────────────────────────────────────────

/**
 * NEVER RENDERED AS CONTENT, whatever a document happens to carry.
 *
 * `activities` is not here: it is rendered as ROWS, below. The rest are things
 * that are either not content (a signature is attested metadata, rendered by
 * filedAttestation) or that must never be drawn as a field: a base64 blob is
 * hundreds of kilobytes of nonsense in a value slot, and an R2 key is an
 * internal address.
 */
const NEVER_A_FIELD = /^(activities|photos|cp_signature|signature|signatures|worker_signature|worker_signatures)$/;
const NEVER_A_FIELD_SUFFIX = /(_base64|_r2_key|_uri)$/;

const skippableKey = (key) => (
  NEVER_A_FIELD.test(key) || NEVER_A_FIELD_SUFFIX.test(key)
);

/** `general_description` -> `General Description`. */
export function humanizeKey(key) {
  return String(key || '')
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * One stored value as one printable string, or null when there is nothing to
 * print. NULL MEANS OMIT THE FIELD ENTIRELY — a filed view shows what was
 * filed, and a column of dashes for everything left blank is a manufactured
 * gap of exactly the kind the photographs rule above exists to avoid.
 */
export function formatFiledValue(v) {
  if (v === null || v === undefined) return null;
  // A boolean printed raw reads as an error on a record. `false` is a real
  // answer here — "site safety orange: No" — so it is rendered, not dropped.
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : null;
  if (typeof v === 'string') return v.trim() || null;
  if (Array.isArray(v)) {
    const flat = v
      .filter((x) => x !== null && x !== undefined && typeof x !== 'object')
      .map((x) => (typeof x === 'boolean' ? (x ? 'Yes' : 'No') : String(x).trim()))
      .filter(Boolean);
    return flat.length ? flat.join(', ') : null;
  }
  return null;
}

const isPlainObject = (v) => (
  v !== null && typeof v === 'object' && !Array.isArray(v)
);

function fieldsFrom(obj, prefix = '', depth = 0) {
  const out = [];
  if (!isPlainObject(obj)) return out;
  for (const key of Object.keys(obj)) {
    if (skippableKey(key)) continue;
    const value = obj[key];
    if (isPlainObject(value)) {
      // ONE LEVEL ONLY. Deeper than that and the label stops naming anything
      // a reader recognises, which is worse than not printing it.
      if (depth >= 1) continue;
      out.push(...fieldsFrom(value, `${prefix}${humanizeKey(key)} · `, depth + 1));
      continue;
    }
    const printable = formatFiledValue(value);
    if (printable === null) continue;
    out.push({ key, label: `${prefix}${humanizeKey(key)}`, value: printable });
  }
  return out;
}

/**
 * What was filed, as printable fields and row groups.
 *
 * Returns `{ fields, groups }`:
 *   fields  [{ key, label, value }]                       — the scalar content
 *   groups  [{ key, label, rows: [{ label, fields }] }]    — arrays of records
 *
 * Any array of objects becomes a group, not just `activities`: several types
 * store their rows under their own name, and a generic reader is the only
 * thing that can render twelve filed types without twelve bespoke views. The
 * photographs inside those rows are stripped here — the photographs section
 * owns those, and a base64 blob in a value slot is how a filed view goes from
 * readable to megabytes.
 */
export function summarizeFiledLog(log) {
  const data = log && log.data && typeof log.data === 'object' ? log.data : {};
  const fields = [];
  const groups = [];

  for (const key of Object.keys(data)) {
    const value = data[key];
    if (Array.isArray(value) && value.some(isPlainObject)) {
      const rows = value.filter(isPlainObject).map((row, i) => {
        const label = activityRowLabel(row) || `${humanizeKey(key)} ${i + 1}`;
        return { label, fields: fieldsFrom(row) };
      });
      if (rows.length) groups.push({ key, label: humanizeKey(key), rows });
      continue;
    }
    if (skippableKey(key)) continue;
    if (isPlainObject(value)) {
      fields.push(...fieldsFrom(value, `${humanizeKey(key)} · `, 1));
      continue;
    }
    const printable = formatFiledValue(value);
    if (printable === null) continue;
    fields.push({ key, label: humanizeKey(key), value: printable });
  }

  return { fields, groups };
}

/**
 * WHO SIGNED IT AND WHEN — and never more than the record supports.
 *
 * `signed` IS THE INK, NOT THE NAME. cp_name is prefilled from the CP's
 * profile long before anybody signs anything, so reading it as a signature
 * would print "Signed by Casey CP" over a record he never attested to. That is
 * a fabricated attestation on a compliance document, which is the single worst
 * thing this screen could do.
 */
export function filedAttestation(log) {
  const doc = log && typeof log === 'object' ? log : {};
  const sig = doc.cp_signature;
  const hasInk = Boolean(
    sig && (typeof sig === 'string'
      ? sig.trim()
      : (sig.ink || sig.data || sig.image || sig.signature_r2_key || sig.affirmed)),
  );
  const name = String(doc.cp_name || '').trim();
  return {
    signed: hasInk,
    signerName: hasInk && name ? name : null,
    filedAt: doc.updated_at || doc.submitted_at || doc.created_at || null,
    status: doc.status || null,
    isLocked: Boolean(doc.is_locked),
    isAmendment: Boolean(doc.is_amendment),
    amendmentReason: doc.is_amendment
      ? (String(doc.amendment_reason || '').trim() || null)
      : null,
  };
}

export default photographsSection;
