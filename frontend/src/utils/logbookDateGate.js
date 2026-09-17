/**
 * A DATE ON A FILED LOG IS A DATE, OR IT IS NOTHING — the device's half.
 *
 * ── WHAT WENT WRONG, AND WHERE THE TWO HALVES SIT ───────────────────────────
 *
 * The stepper's date field used to hand the log `''` for anything that was not
 * yet a real calendar day. A CP who typed `13/45/2029`, or who started editing
 * a good `2029-07-21` and stopped at `07/2`, saw his text and an error on
 * screen while the RECORD kept nothing — and nothing stopped him filing it.
 * The log then said the date was blank, on a signed legal document.
 *
 *   KEPT      src/utils/dateEntry.js hands the host ISO or THE TEXT HE TYPED.
 *             Nothing is discarded, and a good value is never replaced by ''
 *             because an edit was left unfinished.
 *   REFUSED   server.py refuses a SUBMIT carrying a non-empty date that is not
 *             a real ISO date (SUBMIT_INVALID_DATE), naming the field and
 *             quoting the value.
 *
 * This module is what the DEVICE knows about the second half: which fields the
 * server will read, so the CP is stopped on the screen that can fix it instead
 * of meeting a refusal after he has signed — and so an OFFLINE submit is
 * caught at all, since the drain would otherwise queue a log the server will
 * refuse forever with only a banner to show for it.
 *
 * ── WHY THE FIELD LIST IS REPEATED HERE, AND WHAT KEEPS IT TRUE ─────────────
 *
 * The gate's population is DERIVED on the server from the sheet's own
 * declaration (backend/lib/legal_render/schema.py, `date_fields`). A phone
 * cannot read that file, so the paths are repeated here as DATA — and a mirror
 * nothing compares is a mirror that drifts. `backend/tests/
 * test_a_date_on_a_filed_log_is_a_date.py` reads this declaration and asserts
 * it names exactly the fields the schema declares, which is the same shape
 * MAINTENANCE_QUESTIONS is held to against the renderer's copy of its labels.
 *
 * MID-ENTRY NOTHING HERE BLOCKS. The steppers MARK an incomplete step and
 * never gate it; a CP on site is never trapped in a field. These functions are
 * asked at the moment of FILING, which is the moment the record becomes legal.
 */
import { parseStoredDate, DATE_DISPLAY_FORMAT } from './dateEntry';

/**
 * THE MIRROR. Per log type, every date field the filed sheet declares.
 *
 *   container  the repeating list the field lives in ('' for a field that sits
 *              directly on the payload), matching the server's `rows` path
 *              minus its `data.` prefix
 *   key        the key inside the row, or the dotted path on the payload
 *   labelKey   the screen's own i18n key for the field, so the sentence he
 *              reads names the field the way his form does. The server sends
 *              the SHEET's label ('Mfg Date') for the same field; both are
 *              that field's name, and the client owns the wording it renders.
 *   requires   the keys that make a row a row, ORed — the sheet drops a seeded
 *              row that satisfies none of them, so its half-typed date never
 *              reaches the document and is not refused. `_row_survives` on the
 *              server, `row_requires` in the declaration.
 *
 * NOT THE LOG'S OWN DATE. That is the route's parameter, never typed, and no
 * screen has a field for it.
 */
export const LOGBOOK_DATE_FIELDS = Object.freeze({
  fall_protection: [
    { container: 'activities', key: 'manufacture_date', labelKey: 'colMfgDate', requires: ['worker_name'] },
  ],
  osha_log: [
    { container: 'entries', key: 'expiration', labelKey: 'colExpiration', requires: ['worker_name'] },
  ],
  scaffold_maintenance: [
    { container: '', key: 'general_info.installation_date', labelKey: 'fInstalled', requires: [] },
    { container: '', key: 'general_info.expiration_date', labelKey: 'fExpires', requires: [] },
  ],
});

/** A dotted path into a payload. Missing is undefined, never a throw. */
function dotted(obj, path) {
  let cur = obj;
  for (const part of String(path).split('.')) {
    if (!cur || typeof cur !== 'object') return undefined;
    cur = cur[part];
  }
  return cur;
}

const isBlank = (v) => v === null || v === undefined
  || (typeof v === 'string' && v.trim() === '');

/**
 * Is this stored value a real ISO calendar day? The server's own question.
 *
 * `parseStoredDate` is WIDER than this on purpose — it also reads '07/212029'
 * so a stored legacy value can be SHOWN for confirmation. What may be FILED is
 * narrower: ISO exactly. So this asks for the ISO kind, not merely for a value
 * the reader could make sense of.
 */
export function isFilableDate(value) {
  const p = parseStoredDate(value);
  return p.kind === 'iso' && !!p.iso;
}

/** Whether the sheet would print this row at all — `requires`, ORed. */
function rowWouldPrint(row, requires) {
  if (!requires || requires.length === 0) return true;
  return requires.some((k) => String((row && row[k]) ?? '').trim() !== '');
}

/**
 * Every date on this payload that the server will refuse, in the order the
 * screen shows them. Empty when there is nothing to fix.
 *
 * Each entry is `{ labelKey, key, container, row, value }`; `row` is 1-based
 * and null for a field that is not in a list, matching the server's detail so
 * the same copy renders either way.
 */
export function invalidLogDates(logType, data) {
  const fields = LOGBOOK_DATE_FIELDS[logType];
  if (!fields || !data || typeof data !== 'object') return [];
  const out = [];
  for (const f of fields) {
    if (f.container) {
      const rows = dotted(data, f.container);
      if (!Array.isArray(rows)) continue;
      rows.forEach((row, i) => {
        if (!row || typeof row !== 'object') return;
        if (!rowWouldPrint(row, f.requires)) return;
        const value = row[f.key];
        if (isBlank(value) || isFilableDate(value)) return;
        out.push({ ...f, row: i + 1, value });
      });
    } else {
      const value = dotted(data, f.key);
      if (isBlank(value) || isFilableDate(value)) continue;
      out.push({ ...f, row: null, value });
    }
  }
  return out;
}

/** The step a date field lives on. Step 1 on all three forms today. */
export const DATE_STEP = 1;

/**
 * What a bad date is quoted as in a sentence: verbatim, and bounded.
 *
 * The server bounds its own quote (LOGBOOK_DATE_QUOTE_MAX) because a date
 * field on a legacy draft can hold anything the old free-text field was given.
 * The pre-flight reads the value off the screen, so it bounds it here too, and
 * to the same length — the two sentences must not differ by a truncation.
 */
export const DATE_QUOTE_MAX = 64;

export function quoteDateValue(value) {
  const s = (typeof value === 'string' ? value : JSON.stringify(value) || '').trim();
  return s.length <= DATE_QUOTE_MAX ? s : `${s.slice(0, DATE_QUOTE_MAX - 1)}…`;
}

/** The slots the field-naming sentence carries. */
export const FIELD_SLOT = '{field}';
export const VALUE_SLOT = '{value}';

/**
 * Suffix of the variant that names the field and quotes the value.
 *
 * `_FIELD` AND NOT `_NAMED`, AND THAT IS NOT COSMETIC. csRefusalCopy reads
 * `code_X_NAMED` for ANY code as soon as a refusal travels with a
 * `registered_name`, so a `_NAMED` key here would be served as the sentence
 * for a superintendent refusal — a sentence about a date over a refusal about
 * who may file. csRefusalCopy.test.cjs caught exactly that.
 */
export const FIELD_SUFFIX = '_FIELD';

/**
 * The sentence for a bad date, or null when the copy is missing.
 *
 * `t` is a namespaced translator over `finalize` (useT('finalize')), which
 * returns the KEY on a miss — the same detection every gateCopy uses. Two keys
 * for the reason csRefusalCopy splits its pair: LogbookLockBar renders this
 * namespace from a code STORED with no detail beside it, so the bare
 * `code_SUBMIT_INVALID_DATE` must stay slot-free.
 */
export function dateRefusalCopy({ field, value }, t) {
  const key = `code_SUBMIT_INVALID_DATE${FIELD_SUFFIX}`;
  const copy = t(key);
  if (!copy || copy === key) return null;
  const name = String(field || '').trim();
  const shown = quoteDateValue(value);
  if (!name || !shown) return null;
  return String(copy).split(FIELD_SLOT).join(name).split(VALUE_SLOT).join(shown);
}

/**
 * The sentence for the SERVER's refusal, or null when this is not one.
 *
 * The detail carries `field` (the sheet's label) and `value` (the stored
 * string, already bounded). Read from the response only — the English
 * `message` a server sends is never rendered, which is the convention every
 * `code_*` entry follows.
 */
export function serverDateRefusalCopy(detail, t) {
  if (!detail || typeof detail !== 'object') return null;
  if (detail.code !== 'SUBMIT_INVALID_DATE') return null;
  return dateRefusalCopy({ field: detail.field, value: detail.value }, t);
}

/** The pre-flight sentence, from the screen's own label for the field. */
export function preflightDateCopy(offender, t, tField) {
  if (!offender) return null;
  const label = tField ? tField(offender.labelKey) : offender.labelKey;
  return dateRefusalCopy({ field: label, value: offender.value }, t);
}

export default {
  LOGBOOK_DATE_FIELDS,
  FIELD_SUFFIX,
  DATE_STEP,
  DATE_QUOTE_MAX,
  DATE_DISPLAY_FORMAT,
  isFilableDate,
  invalidLogDates,
  quoteDateValue,
  dateRefusalCopy,
  serverDateRefusalCopy,
  preflightDateCopy,
};
