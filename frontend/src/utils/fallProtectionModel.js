/**
 * THE FALL PROTECTION EQUIPMENT LOG — harnesses, lanyards, SRLs, anchors, and
 * what an inspection of each one found.
 *
 * ── WHAT THIS LOG IS, AND WHAT IT IS NOT ───────────────────────────────────
 *
 * OSHA 1926.502(d)(21) mandates the INSPECTION — equipment inspected prior to
 * each use for wear, damage and other deterioration. It does NOT mandate a
 * written record of each one. The documented periodic inspection comes from
 * ANSI Z359, which is an industry consensus standard and not law.
 *
 * So this log is STRONGLY ADVISABLE AND INDUSTRY STANDARD, and the app says
 * exactly that. It carries NO `dob_reference` — the key is absent from its
 * registry entry rather than set to "", so nothing can render a citation that
 * does not exist. Calling it legally required would be the same unsourced
 * claim this whole exercise was opened to remove.
 *
 * ── WHY A MODULE ───────────────────────────────────────────────────────────
 *
 * The frontend suite has no renderer: logic inside a component can only be
 * grepped, logic in a module can be EXECUTED. Every function below decides
 * something that reaches a signed record, so every function below is tested
 * for real — the same reason oshaLogModel.js and concreteOperationsModel.js
 * exist.
 *
 * ── THE PAYLOAD SHAPE, AND WHY THE ROWS LIVE UNDER `activities` ────────────
 *
 * `data.activities[]`, each row carrying `photos[]` in the daily_jobsite photo
 * shape. That container name is not decoration: `get_logbook_activity_photo`
 * — the ONE production read of a logbook photo, the thing every <img> on the
 * report points at — indexes `data.activities[ai].photos[pi]`. Storing these
 * rows anywhere else would mean either no photos on the report or a second
 * photo reader, and device round 6 item 5 exists precisely because a second
 * reader is how the record and its photos drift apart.
 *
 * The row keys are this log's own; only the container and the photo entries
 * are shared.
 */

import { entryNamesWorker } from './oshaLogModel';

/**
 * A ROW MUST CARRY A WORKER — the same rule, not a third copy of it.
 *
 * Group 1 applied this to the OSHA register and the toolbox roster: a row with
 * an equipment serial, an inspection result and no name asserts something
 * about a man the document does not identify. On this log it is worse than on
 * the register, because the assertion is that somebody's fall-arrest equipment
 * was inspected and passed.
 *
 * Imported rather than reimplemented. `worker_name` is the field on both, so
 * the predicate transfers exactly; if that rule ever changes it changes once.
 */
export const rowNamesWorker = entryNamesWorker;

/** The equipment this log covers. Free text is deliberately NOT offered — the
 *  set is closed and short, and the trade-picker backlog exists because fields
 *  the app already knows the answers to were offered as free text. */
export const EQUIPMENT_TYPES = Object.freeze([
  'Harness', 'Lanyard', 'SRL', 'Anchor', 'Lifeline', 'Connector',
]);

/**
 * THREE STATES, NOT A TICK.
 *
 * "Removed from service" is not a worse Fail: a failed component that stays on
 * the rack is a different fact from one that has been taken out of use, and an
 * inspector reads them differently. Stored verbatim as one of these strings.
 */
export const RESULTS = Object.freeze(['Pass', 'Fail', 'Removed from service']);

/** The two results that make a defect, an action and a photo mandatory. */
export const ADVERSE_RESULTS = Object.freeze(['Fail', 'Removed from service']);

export const isAdverse = (result) => ADVERSE_RESULTS.includes(
  String(result ?? '').trim(),
);

/**
 * The keys every row carries. Exported so a test can assert the payload the
 * screen builds still matches what the renderers read, rather than a copy of
 * this list that drifted.
 */
export const ROW_KEYS = Object.freeze([
  'activity_id', 'worker_id', 'worker_name', 'company', 'equipment_type',
  'equipment_id', 'manufacture_date', 'result', 'defect_found',
  'impact_loaded', 'action_taken', 'anchor_point', 'photos',
]);

/**
 * A blank row.
 *
 * `activity_id` is the row id, and it is spelled that way ON PURPOSE:
 * uploadPendingActivityPhotos keys each photo's R2 folder off
 * `activity.activity_id` (`logbook-photos/{project}/{activity_id}/{photo
 * id}.jpg`), so naming it anything else would mean a second uploader. The
 * `fp_` prefix is what gives this log its own clear folders in the bucket
 * instead of scattering its photos among daily_jobsite's crew ids.
 *
 * `result` and `impact_loaded` seed NULL, not a value. An inspection nobody
 * performed must not read as a Pass, and "was this equipment impact loaded"
 * must not read as No — 1926.502(d)(19) makes an impact-loaded component
 * mandatory to remove from service, so a silent No is the answer that keeps
 * dangerous equipment in use.
 */
export const EMPTY_ROW = (mintId) => ({
  activity_id: `fp_${mintId}`,
  worker_id: null,
  worker_name: '',
  company: '',
  equipment_type: '',
  equipment_id: '',
  manufacture_date: '',
  result: null,
  defect_found: '',
  impact_loaded: null,
  action_taken: '',
  anchor_point: '',
  photos: [],
});

/**
 * ONE ROW PER WORKER ON SITE, pre-built from the gate roster.
 *
 * PICKED, NOT TYPED. The company and the worker name come off the check-in the
 * turnstile recorded, so the two fields the trade-picker backlog exists to fix
 * are never free text here. A CP may still add a row by hand for a man the
 * gate did not see, and that row starts with a null worker_id — the app cannot
 * identify him and does not pretend to.
 *
 * NOTHING IS SEEDED INTO `result`. A row exists because a man is on site, not
 * because his equipment was inspected.
 */
export function buildRowsFromCheckins(checkins, mintId) {
  const out = [];
  let n = 0;
  for (const c of (Array.isArray(checkins) ? checkins : [])) {
    if (!c || typeof c !== 'object') continue;
    if (!String(c.worker_name || '').trim()) continue;
    n += 1;
    out.push({
      ...EMPTY_ROW(`${mintId}_${n}`),
      worker_id: c.worker_id ?? null,
      worker_name: c.worker_name || '',
      company: c.company || '',
    });
  }
  return out;
}

/**
 * Answer the inspection result. Re-tapping the SELECTED value clears it.
 *
 * Generalised from applyChecklistAnswer (#153), which is boolean. The defect
 * that helper was written for is exactly this shape: a control whose only
 * "not recorded" state is the one the form opens in, with no way back to it,
 * so a CP who taps twice to undo files an answer he believes he cleared. Here
 * the stakes are higher than a checklist item — the stored value is a verdict
 * on fall-arrest equipment.
 *
 * CLEARING A RESULT CLEARS WHAT THE RESULT REQUIRED. Going Fail -> unrecorded
 * would otherwise strand a defect note and an action against no verdict, and
 * that reads on the filed document as a defect somebody declined to grade.
 */
export function applyResult(row, value) {
  const src = row && typeof row === 'object' ? row : {};
  const clearing = src.result === value;
  const next = { ...src, result: clearing ? null : value };
  if (clearing || !isAdverse(next.result)) {
    next.defect_found = '';
    next.action_taken = '';
  }
  return next;
}

/** Answer the impact-loading question. Tri-state, same re-tap-to-clear rule. */
export function applyImpactLoaded(row, value) {
  const src = row && typeof row === 'object' ? row : {};
  return { ...src, impact_loaded: src.impact_loaded === value ? null : value };
}

/** Has the CP put anything into this row beyond the roster seed? */
export function rowHasContent(row) {
  if (!row || typeof row !== 'object') return false;
  if (row.result !== null && row.result !== undefined) return true;
  if (row.impact_loaded !== null && row.impact_loaded !== undefined) return true;
  if (Array.isArray(row.photos) && row.photos.length > 0) return true;
  return ['worker_name', 'company', 'equipment_type', 'equipment_id',
    'manufacture_date', 'defect_found', 'action_taken', 'anchor_point']
    .some((k) => String(row[k] ?? '').trim() !== '');
}

/**
 * The rows that may be FILED: the ones that name a worker AND record a result.
 *
 * A row with a name and no verdict is the roster seed untouched — it says a
 * man was on site, which the pre-shift sheet already says, and it says nothing
 * about equipment. Filing it would put a blank inspection line on a document
 * whose entire subject is inspections.
 */
export function rowsForFiling(rows) {
  return (Array.isArray(rows) ? rows : []).filter(
    (r) => rowNamesWorker(r) && RESULTS.includes(String(r?.result ?? '').trim()),
  );
}

/**
 * Rows the CP touched that WILL NOT BE FILED, and why — the sentence the
 * submit gate shows him. Two reasons, and they need different fixes:
 *
 *   'unnamed'    an inspection recorded against nobody
 *   'no-result'  a row he started and left ungraded
 */
export function unfilableRows(rows) {
  const out = [];
  (Array.isArray(rows) ? rows : []).forEach((r, i) => {
    if (!rowHasContent(r)) return;
    if (rowsForFiling([r]).length > 0) return;
    out.push({
      row: i + 1,
      reason: rowNamesWorker(r) ? 'no-result' : 'unnamed',
      worker_name: String((r && r.worker_name) ?? '').trim(),
      equipment: [String((r && r.equipment_type) ?? '').trim(),
        String((r && r.equipment_id) ?? '').trim()].filter(Boolean).join(' '),
    });
  });
  return out;
}

/**
 * Rows graded Fail or Removed that are missing what those verdicts require.
 *
 * A DEFECT, AN ACTION AND A PHOTO. "Failed" with no defect named is the empty
 * record the tick was — the same finding the daily inspection note produced —
 * and on this log the photo is the part an inspector can actually check: a
 * cut webbing or a deployed indicator is visible, and a sentence about one is
 * an assertion. On a PASS the photo stays optional; there is nothing to show.
 *
 * Returns one entry per row with the list of what is missing, so the gate can
 * name the row AND the field rather than saying "something is incomplete".
 */
export function rowsMissingAdverseDetail(rows) {
  const out = [];
  (Array.isArray(rows) ? rows : []).forEach((r, i) => {
    if (!r || !isAdverse(r.result)) return;
    const missing = [];
    if (String(r.defect_found ?? '').trim() === '') missing.push('defect');
    if (String(r.action_taken ?? '').trim() === '') missing.push('action');
    if (!Array.isArray(r.photos) || r.photos.length === 0) missing.push('photo');
    if (missing.length > 0) {
      out.push({
        row: i + 1,
        worker_name: String(r.worker_name ?? '').trim(),
        result: String(r.result ?? '').trim(),
        missing,
      });
    }
  });
  return out;
}

/**
 * Rows recorded as impact loaded and NOT removed from service.
 *
 * 1926.502(d)(19) is not advisory: a component subjected to impact loading
 * must be immediately removed from service. This is the one place the app
 * knows a regulation was contradicted by the record in front of it, so it says
 * so — as a warning the CP must act on, never as a silent correction of what
 * he recorded.
 */
export function impactLoadedNotRemoved(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((r, i) => ({ r, row: i + 1 }))
    .filter(({ r }) => r && r.impact_loaded === true
      && String(r.result ?? '').trim() !== 'Removed from service')
    .map(({ r, row }) => ({
      row,
      worker_name: String(r.worker_name ?? '').trim(),
      result: String(r.result ?? '').trim(),
    }));
}

/**
 * Which steps the CP has LEFT incomplete. Never gates — the stepper marks, and
 * a CP who cannot complete a step must still be able to finish and sign.
 *
 * Step 1 is the register: incomplete when not one row will be filed.
 * Step 2 is the signature.
 */
export function incompleteSteps({ rows, cpSignature }) {
  const out = [];
  if (rowsForFiling(rows).length === 0) out.push(1);
  if (!String(cpSignature || '').trim()) out.push(2);
  return out;
}

/** The payload body. The ONE place the shape is decided. */
export function draftBody(rows) {
  return { activities: Array.isArray(rows) ? rows : [] };
}

export default {
  EQUIPMENT_TYPES,
  RESULTS,
  ADVERSE_RESULTS,
  isAdverse,
  ROW_KEYS,
  EMPTY_ROW,
  buildRowsFromCheckins,
  rowNamesWorker,
  applyResult,
  applyImpactLoaded,
  rowHasContent,
  rowsForFiling,
  unfilableRows,
  rowsMissingAdverseDetail,
  impactLoadedNotRemoved,
  incompleteSteps,
  draftBody,
};
