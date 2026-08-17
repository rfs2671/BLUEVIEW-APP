/**
 * The Concrete Operations Log — a pour, its slump tests, and the formwork the
 * concrete went into.
 *
 * WHY A MODULE. Same reason as scaffoldMaintenanceModel and oshaLogModel: the
 * frontend suite has no renderer, so logic left in a component can only be
 * grepped while logic in a module can be EXECUTED. Everything here decides what
 * a DOB inspector reads off a filed document.
 *
 * THE PAYLOAD SHAPE IS FROZEN — eight top-level keys, flat:
 *
 *   pour_location  concrete_supplier  mix_design  volume_ordered
 *   weather_conditions  temperature  slump_tests[]  formwork_checklist{}
 *
 * Three surfaces read them by key and none of them would crash on a rename:
 * the PDF renderer (backend/server.py:13411), the combined report (:19928) and
 * the kiosk inspector (app/site/logbooks.jsx:981). A key renamed here empties a
 * section on a filed document and nothing on the device ever shows it, so
 * portedFormPayloads.test.cjs checks every key against those renderers' OWN
 * reads pulled out of the source rather than a list typed alongside this one.
 *
 * `pass` IS TRI-STATE and stays that way. EMPTY_SLUMP_TEST seeds it null, and
 * both renderers print null as nothing — never as a Fail the CP did not record.
 * applySlumpResult is the only thing that sets it.
 */
import { recordedCount, allRecorded } from './checklistMap';

// ── The pour — the five typed fields, in the order the document prints them ──
//
// `kind` drives the control, not the storage: every value is stored and sent as
// a STRING, because that is what the renderers print.
//
// volume_ordered and temperature are UNIT-LESS as entered — the editor captures
// no unit and both renderers say so where they print them. Nothing here adds
// one, because a unit this form never asked for would be a fabrication.
export const DETAIL_FIELDS = Object.freeze([
  { key: 'pour_location', labelKey: 'fPourLocation', kind: 'text' },
  { key: 'concrete_supplier', labelKey: 'fSupplier', kind: 'text' },
  { key: 'mix_design', labelKey: 'fMixDesign', kind: 'text' },
  { key: 'volume_ordered', labelKey: 'fVolumeOrdered', kind: 'text' },
  { key: 'temperature', labelKey: 'fTemperature', kind: 'text' },
]);

/** The weather chips, unchanged from the form this replaces. */
export const WEATHER_OPTIONS = Object.freeze([
  'Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy',
]);

/** The six scalar keys that travel at the top of the payload. */
export const DETAIL_KEYS = Object.freeze(
  [...DETAIL_FIELDS.map((f) => f.key), 'weather_conditions'],
);

// ── Formwork inspection — four items ────────────────────────────────────────
// Label text is duplicated in backend/server.py:13415-13420 and again at
// :19932-19937 because those renderers print filed documents with no access to
// this bundle. The test asserts the lists agree, key for key and word for word.
export const FORMWORK_ITEMS = Object.freeze([
  { key: 'shores_plumb', label: 'Shores Plumb' },
  { key: 'bracing_adequate', label: 'Bracing Adequate' },
  { key: 'formwork_clean', label: 'Formwork Clean' },
  { key: 'no_gaps', label: 'No Gaps' },
]);

/** YES / NO, the two words the "Confirmed" column prints. */
export const CONFIRM_OPTIONS = Object.freeze([
  { label: 'YES', value: true },
  { label: 'NO', value: false },
]);

/** A blank pour. Nothing is seeded with an answer. */
export const EMPTY_DETAILS = () => ({
  pour_location: '',
  concrete_supplier: '',
  mix_design: '',
  volume_ordered: '',
  weather_conditions: '',
  temperature: '',
});

/** One slump test. `pass` starts null — unrecorded, which is not a Fail. */
export const EMPTY_SLUMP_TEST = () => ({
  time: '',
  value: '',
  pass: null,
});

/**
 * Does this row say anything?
 *
 * THIS IS THE RENDERER'S OWN DROP RULE, restated: server.py:13428 skips a row
 * with `not t and not v and p is None` and the combined report (:19952) and the
 * kiosk (logbooks.jsx:986) use the same three. If the screen's rule disagreed,
 * a filed row would print where the CP saw none, or vanish where he saw one.
 */
export function slumpHasContent(test) {
  if (!test || typeof test !== 'object') return false;
  return String(test.time ?? '').trim() !== ''
    || String(test.value ?? '').trim() !== ''
    || (test.pass !== null && test.pass !== undefined);
}

/**
 * The rows that go on the FILED document — the ones with content, and no
 * others. A draft keeps everything; it is only at the moment of filing that an
 * untouched seed row becomes a false entry on a compliance document. Same rule
 * osha_log files by, for the same reason.
 */
export function slumpTestsForFiling(tests) {
  return (Array.isArray(tests) ? tests : []).filter(slumpHasContent);
}

/**
 * Pass / Fail / neither.
 *
 * Re-tapping the CHOSEN result returns the row to null — the state it was
 * seeded in. Without that there is no way back: a mis-tapped Fail on a pour
 * record could only be removed by deleting the whole row.
 */
export function applySlumpResult(test, value) {
  const t = (test && typeof test === 'object') ? test : EMPTY_SLUMP_TEST();
  return { ...t, pass: t.pass === value ? null : value };
}

/** How many rows the CP has actually filled in. */
export function filledSlumpCount(tests) {
  return slumpTestsForFiling(tests).length;
}

/** How many of the four formwork items carry an answer. A NO is an answer. */
export function formworkRecordedCount(checklist) {
  return recordedCount(checklist, FORMWORK_ITEMS);
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates — a CP who
 * cannot complete a step because the work has not happened must still be able
 * to finish and sign his day.
 *
 * Step 1 the pour, step 2 the slump tests, step 3 the formwork, step 4 the
 * signature.
 */
export function incompleteSteps({ details, slumpTests, formworkChecklist, cpSignature }) {
  const out = [];
  const d = (details && typeof details === 'object') ? details : {};
  const anyDetail = DETAIL_KEYS.some((k) => String(d[k] ?? '').trim() !== '');
  if (!anyDetail) out.push(1);
  if (filledSlumpCount(slumpTests) === 0) out.push(2);
  if (!allRecorded(formworkChecklist, FORMWORK_ITEMS)) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/**
 * The payload body. The ONE place the shape is decided.
 *
 * FLAT, and every scalar key is always present — the renderers read
 * `data.get("pour_location")` directly, and a key that only appears once it is
 * typed is a key that can go missing.
 */
export function draftBody(details, slumpTests, formworkChecklist) {
  const d = (details && typeof details === 'object') ? details : {};
  const out = {};
  for (const k of DETAIL_KEYS) out[k] = d[k] ?? '';
  out.slump_tests = Array.isArray(slumpTests) ? slumpTests : [];
  out.formwork_checklist = (formworkChecklist && typeof formworkChecklist === 'object')
    ? formworkChecklist : {};
  return out;
}

/** The details a loaded document carries, narrowed to the six this form owns. */
export function detailsFromData(data) {
  const src = (data && typeof data === 'object') ? data : {};
  const out = EMPTY_DETAILS();
  for (const k of DETAIL_KEYS) out[k] = src[k] ?? '';
  return out;
}

export default {
  DETAIL_FIELDS,
  DETAIL_KEYS,
  WEATHER_OPTIONS,
  FORMWORK_ITEMS,
  CONFIRM_OPTIONS,
  EMPTY_DETAILS,
  EMPTY_SLUMP_TEST,
  slumpHasContent,
  slumpTestsForFiling,
  applySlumpResult,
  filledSlumpCount,
  formworkRecordedCount,
  incompleteSteps,
  draftBody,
  detailsFromData,
};
