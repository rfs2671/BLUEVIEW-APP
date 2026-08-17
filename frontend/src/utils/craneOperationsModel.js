/**
 * The Crane Operations Log — the crane, its operator, the fifteen pre-operation
 * checks, and every lift made.
 *
 * WHY A MODULE. Same reason as scaffoldMaintenanceModel and oshaLogModel: the
 * frontend suite has no renderer, so logic left in a component can only be
 * grepped while logic in a module can be EXECUTED. Everything here decides what
 * a DOB inspector reads off a filed document.
 *
 * THE PAYLOAD SHAPE IS FROZEN — six top-level keys, flat:
 *
 *   crane_type  crane_id  operator_name  operator_license
 *   pre_operation_checklist{}  load_entries[]
 *
 * Three surfaces read them by key and none of them would crash on a rename:
 * the PDF renderer (backend/server.py:13295), the combined report (:19552) and
 * the kiosk inspector (app/site/logbooks.jsx:866). A key renamed here empties a
 * section on a filed document and nothing on the device ever shows it, so
 * portedFormPayloads.test.cjs checks every key against those renderers' OWN
 * reads pulled out of the source rather than a list typed alongside this one.
 */
import { recordedCount, allRecorded } from './checklistMap';

// ── The crane and its operator ───────────────────────────────────────────────
//
// crane_type and operator_name are short entries the renderers sentence-case;
// crane_id and operator_license are IDENTIFIERS printed raw. Nothing here
// transforms any of them — what the CP typed is what is filed.
export const DETAIL_FIELDS = Object.freeze([
  { key: 'crane_type', labelKey: 'fCraneType', kind: 'text' },
  { key: 'crane_id', labelKey: 'fCraneId', kind: 'text' },
  { key: 'operator_name', labelKey: 'fOperatorName', kind: 'text' },
  { key: 'operator_license', labelKey: 'fOperatorLicense', kind: 'text' },
]);

export const DETAIL_KEYS = Object.freeze(DETAIL_FIELDS.map((f) => f.key));

// ── The fifteen pre-operation checks, in the order the operator walks them ───
// Label text is duplicated in backend/server.py:13299-13315 and again at
// :19556-19574 because those renderers print filed documents with no access to
// this bundle. The test asserts the lists agree, key for key and word for word.
export const PRE_OP_CHECKLIST_ITEMS = Object.freeze([
  { key: 'wire_ropes', label: 'Wire Ropes Inspected' },
  { key: 'hooks_latches', label: 'Hooks & Latches Secure' },
  { key: 'brakes', label: 'Brakes Functional' },
  { key: 'outriggers', label: 'Outriggers Deployed' },
  { key: 'load_chart', label: 'Load Chart Available' },
  { key: 'boom_condition', label: 'Boom Condition OK' },
  { key: 'anti_two_block', label: 'Anti Two-Block Device' },
  { key: 'fire_extinguisher', label: 'Fire Extinguisher Present' },
  { key: 'signals_reviewed', label: 'Signals Reviewed' },
  { key: 'area_barricaded', label: 'Area Barricaded' },
  { key: 'wind_speed_checked', label: 'Wind Speed Checked' },
  { key: 'power_lines_clear', label: 'Power Lines Clear' },
  { key: 'load_weight_known', label: 'Load Weight Known' },
  { key: 'rigging_inspected', label: 'Rigging Inspected' },
  { key: 'swing_radius_clear', label: 'Swing Radius Clear' },
]);

/** YES / NO, the two words the "Confirmed" column prints. */
export const CONFIRM_OPTIONS = Object.freeze([
  { label: 'YES', value: true },
  { label: 'NO', value: false },
]);

/** A blank crane. Nothing is seeded. */
export const EMPTY_DETAILS = () => ({
  crane_type: '',
  crane_id: '',
  operator_name: '',
  operator_license: '',
});

/**
 * One lift.
 *
 * load_weight and radius are UNIT-LESS strings exactly as the operator typed
 * them — the editor captures no unit and all three renderers say so where they
 * print the columns. Nothing here adds one.
 */
export const EMPTY_LOAD_ENTRY = () => ({
  time: '',
  description: '',
  load_weight: '',
  radius: '',
});

/** The four fields the renderers test a row's emptiness by. */
export const LOAD_ENTRY_KEYS = Object.freeze(['time', 'description', 'load_weight', 'radius']);

/**
 * Does this row record a lift?
 *
 * THIS IS THE RENDERER'S OWN DROP RULE, restated: server.py:13322 skips a row
 * with none of the four fields set, the combined report (:19587) and the kiosk
 * (logbooks.jsx:871) use the same four. If the screen's rule disagreed, a filed
 * row would print where the CP saw none, or vanish where he saw one.
 */
export function loadEntryHasContent(entry) {
  if (!entry || typeof entry !== 'object') return false;
  return LOAD_ENTRY_KEYS.some((k) => String(entry[k] ?? '').trim() !== '');
}

/**
 * The rows that go on the FILED document. A draft keeps everything; it is only
 * at the moment of filing that an untouched seed row becomes a lift the crane
 * never made. Same rule osha_log files by, for the same reason.
 */
export function loadEntriesForFiling(entries) {
  return (Array.isArray(entries) ? entries : []).filter(loadEntryHasContent);
}

/** How many lifts the operator has actually recorded. */
export function filledLiftCount(entries) {
  return loadEntriesForFiling(entries).length;
}

/** How many of the fifteen checks carry an answer. A NO is an answer. */
export function preOpRecordedCount(checklist) {
  return recordedCount(checklist, PRE_OP_CHECKLIST_ITEMS);
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates — a CP who
 * cannot complete a step because the work has not happened must still be able
 * to finish and sign his day.
 *
 * Step 1 the crane, step 2 the pre-operation checks, step 3 the lifts, step 4
 * the signature. Step 2 is incomplete until ALL FIFTEEN are answered: this is
 * the check that precedes picking a load off the ground, and a half-walked
 * checklist is exactly the thing the pip exists to show.
 */
export function incompleteSteps({ details, preOpChecklist, loadEntries, cpSignature }) {
  const out = [];
  const d = (details && typeof details === 'object') ? details : {};
  const anyDetail = DETAIL_KEYS.some((k) => String(d[k] ?? '').trim() !== '');
  if (!anyDetail) out.push(1);
  if (!allRecorded(preOpChecklist, PRE_OP_CHECKLIST_ITEMS)) out.push(2);
  if (filledLiftCount(loadEntries) === 0) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/**
 * The payload body. The ONE place the shape is decided.
 *
 * FLAT, and every scalar key is always present — the renderers read
 * `d.get("crane_type")` directly, and a key that only appears once it is typed
 * is a key that can go missing.
 */
export function draftBody(details, preOpChecklist, loadEntries) {
  const d = (details && typeof details === 'object') ? details : {};
  const out = {};
  for (const k of DETAIL_KEYS) out[k] = d[k] ?? '';
  out.pre_operation_checklist = (preOpChecklist && typeof preOpChecklist === 'object')
    ? preOpChecklist : {};
  out.load_entries = Array.isArray(loadEntries) ? loadEntries : [];
  return out;
}

/** The details a loaded document carries, narrowed to the four this form owns. */
export function detailsFromData(data) {
  const src = (data && typeof data === 'object') ? data : {};
  const out = EMPTY_DETAILS();
  for (const k of DETAIL_KEYS) out[k] = src[k] ?? '';
  return out;
}

export default {
  DETAIL_FIELDS,
  DETAIL_KEYS,
  PRE_OP_CHECKLIST_ITEMS,
  CONFIRM_OPTIONS,
  EMPTY_DETAILS,
  EMPTY_LOAD_ENTRY,
  LOAD_ENTRY_KEYS,
  loadEntryHasContent,
  loadEntriesForFiling,
  filledLiftCount,
  preOpRecordedCount,
  incompleteSteps,
  draftBody,
  detailsFromData,
};
