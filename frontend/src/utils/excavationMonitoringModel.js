/**
 * The Excavation Monitoring Log — the cut, the buildings beside it, and what
 * the vibration monitor read.
 *
 * WHY A MODULE. Same reason as scaffoldMaintenanceModel and oshaLogModel: the
 * frontend suite has no renderer, so logic left in a component can only be
 * grepped while logic in a module can be EXECUTED. Everything here decides what
 * a DOB inspector reads off a filed document.
 *
 * THE PAYLOAD SHAPE IS FROZEN — nine top-level keys, flat:
 *
 *   excavation_depth  soil_type  protection_system
 *   groundwater_observed  atmospheric_testing
 *   vibration_threshold  vibration_current  vibration_over_threshold
 *   adjacent_buildings[]
 *
 * Three surfaces read them by key: the PDF renderer (backend/server.py:13349),
 * the combined report (:19636) and the kiosk inspector
 * (app/site/logbooks.jsx:924). A key renamed here empties a section on a filed
 * document, so portedFormPayloads.test.cjs checks every key against those
 * renderers' OWN reads pulled out of the source.
 *
 * ── TWO DERIVED VALUES, AND THEY ARE DERIVED IN ONE PLACE ────────────────────
 *
 * `delta` (per building) and `vibration_over_threshold` are COMPUTED, not
 * typed. The screen this replaces computed them in its save handler only — so
 * the debounced AUTOSAVE wrote a draft with no `vibration_over_threshold` at
 * all and with deltas missing from every row. That matters because the offline
 * drain pushes the DRAFT: a permit that reached the server through the drain
 * rather than through Submit arrived without the flag, and server.py:13371
 * gates the whole Status line on `has(data, "vibration_over_threshold")` — so
 * the filed PDF read "— Not recorded" over two perfectly good readings.
 *
 * draftBody derives both, so the autosave, the flush and the submit all build
 * the identical payload and there is no third shape for the drain to find.
 *
 * ── TWO REAL BOOLEANS, NOT A SPARSE MAP ─────────────────────────────────────
 *
 * groundwater_observed and atmospheric_testing are ordinary booleans seeded
 * FALSE, and both renderers read them that way — the combined report says so at
 * :19669-19670 and prints a bare Yes/No with no not-recorded branch. They are
 * deliberately NOT run through checklistMap: this form's two switches have two
 * states, and giving them a third would file "Not recorded" into a renderer
 * that has no way to print it.
 */

/** Every top-level key that travels, in the order the document prints them. */
export const DETAIL_FIELDS = Object.freeze([
  // excavation_depth is a raw number — the editor captures no unit, and both
  // renderers say so where they print it. Nothing here adds one.
  { key: 'excavation_depth', labelKey: 'fDepth', kind: 'number' },
]);

export const SOIL_TYPE_OPTIONS = Object.freeze(['Rock', 'Hard Clay', 'Soft Clay', 'Sand', 'Fill']);
export const PROTECTION_SYSTEM_OPTIONS = Object.freeze(['Sloping', 'Shoring', 'Shield']);

/** The two plain booleans, and the labels they are asked under. */
export const CONDITION_FLAGS = Object.freeze([
  { key: 'groundwater_observed', labelKey: 'fGroundwater' },
  { key: 'atmospheric_testing', labelKey: 'fAtmospheric' },
]);

/** A blank excavation. */
export const EMPTY_DETAILS = () => ({
  excavation_depth: '',
  soil_type: '',
  protection_system: '',
  vibration_threshold: '',
  vibration_current: '',
  groundwater_observed: false,
  atmospheric_testing: false,
});

/**
 * One monitoring point.
 *
 * `delta` is NOT seeded: it is derived at payload time from the two readings.
 * A seeded empty delta would be indistinguishable from a computed one and
 * would let a row with no readings look like a row whose readings agreed.
 */
export const EMPTY_ADJACENT_BUILDING = () => ({
  address: '',
  baseline_reading: '',
  current_reading: '',
});

/** The four fields the renderers test a row's emptiness by. */
export const BUILDING_KEYS = Object.freeze(['address', 'baseline_reading', 'current_reading', 'delta']);

/**
 * Movement between the two readings, to three decimals.
 *
 * ABSOLUTE, as it has always been: the document's column is "Movement (Δ)" and
 * a settlement of 0.004 down is the same finding as 0.004 up. Unparseable
 * either side yields '' — a blank, never a 0, because "no reading" and "no
 * movement" are opposite findings on an excavation record.
 */
export function calcDelta(baseline, current) {
  const b = parseFloat(baseline);
  const c = parseFloat(current);
  if (Number.isNaN(b) || Number.isNaN(c)) return '';
  return Math.abs(c - b).toFixed(3);
}

/**
 * Over the limit?
 *
 * FALSE when either reading is unparseable — which is not the same claim as
 * "within threshold", and the renderers know it: both gate the Status line on
 * having BOTH readings and print "— Not recorded" otherwise
 * (server.py:13371, :19644). This returns the flag; they decide whether it is
 * meaningful.
 */
export function isOverThreshold(threshold, current) {
  const t = parseFloat(threshold);
  const c = parseFloat(current);
  if (Number.isNaN(t) || Number.isNaN(c)) return false;
  return c > t;
}

/** True only when the flag above is worth showing — the renderers' own rule. */
export function thresholdStatusIsMeaningful(threshold, current) {
  return String(threshold ?? '').trim() !== '' && String(current ?? '').trim() !== '';
}

/**
 * Does this row record a monitoring point?
 *
 * THE RENDERER'S OWN DROP RULE, restated: server.py:13391 skips a row with none
 * of the four fields set, the combined report (:19659) and the kiosk
 * (logbooks.jsx:936) use the same four.
 */
export function buildingHasContent(building) {
  if (!building || typeof building !== 'object') return false;
  return BUILDING_KEYS.some((k) => String(building[k] ?? '').trim() !== '');
}

/** Every row with its computed delta — the shape that goes in the payload. */
export function buildingsWithDelta(buildings) {
  return (Array.isArray(buildings) ? buildings : []).map((b) => ({
    ...b,
    delta: calcDelta(b?.baseline_reading, b?.current_reading),
  }));
}

/**
 * The rows that go on the FILED document. A draft keeps everything; it is only
 * at the moment of filing that an untouched seed row becomes a monitoring point
 * nobody surveyed.
 */
export function buildingsForFiling(buildings) {
  return buildingsWithDelta(buildings).filter(buildingHasContent);
}

/** How many points the CP has actually recorded. */
export function filledBuildingCount(buildings) {
  return buildingsForFiling(buildings).length;
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates.
 *
 * Step 1 the cut, step 2 the adjacent structures, step 3 vibration and
 * conditions, step 4 the signature.
 *
 * The two condition switches are NOT part of step 3's completeness: they are
 * booleans that are meaningfully false, so "off" is an answer and there is
 * nothing to be incomplete about.
 */
export function incompleteSteps({ details, adjacentBuildings, cpSignature }) {
  const out = [];
  const d = (details && typeof details === 'object') ? details : {};
  const anyDetail = ['excavation_depth', 'soil_type', 'protection_system']
    .some((k) => String(d[k] ?? '').trim() !== '');
  if (!anyDetail) out.push(1);
  if (filledBuildingCount(adjacentBuildings) === 0) out.push(2);
  if (!thresholdStatusIsMeaningful(d.vibration_threshold, d.vibration_current)) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/**
 * The payload body. The ONE place the shape is decided, and the ONE place the
 * two derived values are computed — see the header. `forFiling` trims the
 * abandoned rows; a draft passes false and keeps them.
 */
export function draftBody(details, adjacentBuildings, { forFiling = false } = {}) {
  const d = (details && typeof details === 'object') ? details : {};
  return {
    excavation_depth: d.excavation_depth ?? '',
    soil_type: d.soil_type ?? '',
    protection_system: d.protection_system ?? '',
    vibration_threshold: d.vibration_threshold ?? '',
    vibration_current: d.vibration_current ?? '',
    vibration_over_threshold: isOverThreshold(d.vibration_threshold, d.vibration_current),
    groundwater_observed: !!d.groundwater_observed,
    atmospheric_testing: !!d.atmospheric_testing,
    adjacent_buildings: forFiling
      ? buildingsForFiling(adjacentBuildings)
      : buildingsWithDelta(adjacentBuildings),
  };
}

/** The details a loaded document carries, narrowed to the keys this form owns. */
export function detailsFromData(data) {
  const src = (data && typeof data === 'object') ? data : {};
  const out = EMPTY_DETAILS();
  for (const k of Object.keys(out)) {
    if (typeof out[k] === 'boolean') out[k] = !!src[k];
    else out[k] = src[k] ?? '';
  }
  return out;
}

export default {
  DETAIL_FIELDS,
  SOIL_TYPE_OPTIONS,
  PROTECTION_SYSTEM_OPTIONS,
  CONDITION_FLAGS,
  EMPTY_DETAILS,
  EMPTY_ADJACENT_BUILDING,
  BUILDING_KEYS,
  calcDelta,
  isOverThreshold,
  thresholdStatusIsMeaningful,
  buildingHasContent,
  buildingsWithDelta,
  buildingsForFiling,
  filledBuildingCount,
  incompleteSteps,
  draftBody,
  detailsFromData,
};
