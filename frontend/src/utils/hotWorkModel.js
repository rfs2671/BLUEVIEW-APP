/**
 * The Hot Work Permit — what is being burned, by whom, between when and when,
 * and who is watching for fire afterwards.
 *
 * WHY A MODULE. Same reason as scaffoldMaintenanceModel and oshaLogModel: the
 * frontend suite has no renderer, so logic left in a component can only be
 * grepped while logic in a module can be EXECUTED. Everything here decides what
 * an FDNY or DOB inspector reads off a filed permit.
 *
 * THE PAYLOAD SHAPE IS FROZEN — nine top-level keys, flat:
 *
 *   work_type  location  worker_name  worker_cert_number
 *   start_time  end_time  fire_watch_end_time  fire_watch_name
 *   precautions{}
 *
 * Three surfaces read them by key: the PDF renderer (backend/server.py:13256),
 * the combined report (:19502) and the kiosk inspector
 * (app/site/logbooks.jsx:826). portedFormPayloads.test.cjs checks every key
 * against those renderers' OWN reads pulled out of the source.
 *
 * ── THE DEVICE ASKED A DIFFERENT QUESTION THAN THE DOCUMENT PRINTED ─────────
 *
 * The screen this replaces labelled two precautions differently from every
 * reader of the permit:
 *
 *   device                                 filed document
 *   "Area Cleared of Combustibles (35ft)"  "Area Cleared of Combustibles (35 ft)"
 *   "Combustibles Covered/Protected"       "Combustibles Covered / Protected"
 *
 * Small, and it printed for real on every filed permit: both server renderers
 * and the kiosk agree on the right-hand column and only the editor disagreed,
 * so the CP ticked one sentence and the inspector read another. The labels
 * below are the renderers' own strings, and the test asserts all three agree
 * word for word.
 *
 * ── fire_watch_end_time IS DERIVED AND SAYS SO ──────────────────────────────
 *
 * The permit captures NO real fire-watch end time. It is computed as work end
 * plus 30 minutes, and all three readers label it as the computed default it is
 * — FDNY can require 60. Nothing here asserts it as a recorded watch-until, and
 * an unparseable end time yields '' rather than a guess.
 */
import { parseClock, toClock } from '../components/logbookStepper/TimeField';

export const WORK_TYPE_OPTIONS = Object.freeze([
  'Welding', 'Cutting', 'Brazing', 'Soldering', 'Other',
]);

// work_type is an enum label; location, worker_name and fire_watch_name are
// short entries the renderers sentence-case; worker_cert_number is an
// IDENTIFIER printed raw. Nothing here transforms any of them.
export const DETAIL_FIELDS = Object.freeze([
  { key: 'location', labelKey: 'fLocation', kind: 'text' },
  { key: 'worker_name', labelKey: 'fWorkerName', kind: 'text' },
  { key: 'worker_cert_number', labelKey: 'fWorkerCert', kind: 'text' },
]);

// ── The seven precautions, in the order the CP walks them ────────────────────
// Label text is duplicated in backend/server.py:13260-13268, again at
// :19509-19517, and again as the kiosk's p_* catalogue keys, because those
// renderers print filed permits with no access to this bundle. The test asserts
// all of them agree, key for key and word for word.
export const PRECAUTION_ITEMS = Object.freeze([
  { key: 'area_cleared', label: 'Area Cleared of Combustibles (35 ft)' },
  { key: 'fire_extinguisher_present', label: 'Fire Extinguisher Present' },
  { key: 'sprinklers_operational', label: 'Sprinklers Operational' },
  { key: 'combustibles_covered', label: 'Combustibles Covered / Protected' },
  { key: 'fire_watch_assigned', label: 'Fire Watch Assigned' },
  { key: 'ventilation_adequate', label: 'Ventilation Adequate' },
  { key: 'permit_posted', label: 'Permit Posted at Location' },
]);

/** YES / NO, the two words the "Confirmed" column prints. */
export const CONFIRM_OPTIONS = Object.freeze([
  { label: 'YES', value: true },
  { label: 'NO', value: false },
]);

/** How long after work ends the fire watch runs, by default. */
export const FIRE_WATCH_MINUTES = 30;

/** A blank permit. */
export const EMPTY_DETAILS = () => ({
  work_type: '',
  location: '',
  worker_name: '',
  worker_cert_number: '',
  start_time: '',
  end_time: '',
  fire_watch_name: '',
});

/**
 * Work end + 30 minutes.
 *
 * READS BOTH FORMATS AND WRITES THE PICKER'S. parseClock accepts the 24-hour
 * "HH:MM" this field held before it became a tap-only picker, so a permit
 * drafted on an older build still derives correctly; the value it RETURNS is
 * toClock's "hh:mm AM/PM", matching whatever the picker itself now writes, so
 * one permit never carries two spellings of a time.
 *
 * Wraps past midnight, because hot work does. An unparseable end time yields ''
 * — a blank the renderers print as an em dash, never a guessed watch-until.
 */
export function calcFireWatchEnd(endTime) {
  const p = parseClock(endTime);
  if (!p) return '';
  const total = (p.h24 * 60 + p.m + FIRE_WATCH_MINUTES) % (24 * 60);
  return toClock(Math.floor(total / 60), total % 60);
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates.
 *
 * Step 1 the work, step 2 the timing, step 3 the precautions, step 4 the
 * signature. Step 3 is incomplete until ALL SEVEN are answered: this is the
 * checklist that precedes striking an arc next to combustibles, and a
 * half-walked one is exactly what the pip exists to show.
 */
export function incompleteSteps({ details, precautions, cpSignature }) {
  const out = [];
  const d = (details && typeof details === 'object') ? details : {};
  const anyWork = ['work_type', 'location', 'worker_name', 'worker_cert_number']
    .some((k) => String(d[k] ?? '').trim() !== '');
  if (!anyWork) out.push(1);
  const anyTime = ['start_time', 'end_time', 'fire_watch_name']
    .some((k) => String(d[k] ?? '').trim() !== '');
  if (!anyTime) out.push(2);
  const p = (precautions && typeof precautions === 'object') ? precautions : {};
  const answered = PRECAUTION_ITEMS.filter(
    (it) => typeof p[it.key] === 'boolean',
  ).length;
  if (answered < PRECAUTION_ITEMS.length) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/**
 * The payload body. The ONE place the shape is decided, and the ONE place
 * fire_watch_end_time is derived — the screen this replaces computed it in a
 * render-scope const and then had to remember to include it in three separate
 * object literals.
 */
export function draftBody(details, precautions) {
  const d = (details && typeof details === 'object') ? details : {};
  return {
    work_type: d.work_type ?? '',
    location: d.location ?? '',
    worker_name: d.worker_name ?? '',
    worker_cert_number: d.worker_cert_number ?? '',
    start_time: d.start_time ?? '',
    end_time: d.end_time ?? '',
    fire_watch_end_time: calcFireWatchEnd(d.end_time),
    fire_watch_name: d.fire_watch_name ?? '',
    precautions: (precautions && typeof precautions === 'object') ? precautions : {},
  };
}

/** The details a loaded permit carries, narrowed to the keys this form owns. */
export function detailsFromData(data) {
  const src = (data && typeof data === 'object') ? data : {};
  const out = EMPTY_DETAILS();
  for (const k of Object.keys(out)) out[k] = src[k] ?? '';
  return out;
}

export default {
  WORK_TYPE_OPTIONS,
  DETAIL_FIELDS,
  PRECAUTION_ITEMS,
  CONFIRM_OPTIONS,
  FIRE_WATCH_MINUTES,
  EMPTY_DETAILS,
  calcFireWatchEnd,
  incompleteSteps,
  draftBody,
  detailsFromData,
};
