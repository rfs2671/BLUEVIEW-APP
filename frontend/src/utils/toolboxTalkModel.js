/**
 * The toolbox talk — NYC DOB §3301.12.3 / OSHA 29 CFR 1926.21.
 *
 * WHY A MODULE. The frontend suite has no renderer, so logic inside a component
 * can only be grepped while logic in a module can be EXECUTED. Everything here
 * decides what lands on a signed attendance record.
 *
 * THE PAYLOAD SHAPE IS FROZEN — `{location, company_name, type_of_work,
 * meeting_time, performed_by, checked_topics, attendees}`, rendered by
 * backend/server.py's toolbox branch in both PDF renderers and displayed by
 * app/site/logbooks.jsx. A renamed key blanks a section on a filed document, so
 * toolboxTalkModel.test.cjs asserts the set against the renderer's own reads.
 *
 * THE ATTENDEE ROSTER IS NOT A WORKER ATTESTATION. Workers are not required to
 * sign a toolbox talk: the CP's signature over the roster is the sole legal
 * anchor. `signed` is the CP's presence tick, `gate_confirmed` is the worker's
 * voluntary tap at the gate, and NEITHER is a signature — which is why
 * `signature` is hardcoded null on a built row.
 */

import { withGateSnapshot, reconcileRoster } from './rosterReconcile';

// The five topic groups, verbatim. Labels are what prints on the filed PDF.
export const TOPICS = Object.freeze({
  'PPE': [
    { key: 'hard_hats', label: 'Hard Hats' },
    { key: 'safety_boots', label: 'Safety Boots' },
    { key: 'safety_glasses', label: 'Safety Glasses' },
    { key: 'harness', label: 'Harness' },
    { key: 'gloves', label: 'Gloves' },
    { key: 'covid19', label: 'Covid-19' },
  ],
  'Fall Protection': [
    { key: 'ladder_safety', label: 'Ladder Safety' },
    { key: 'harness_fp', label: 'Harness' },
    { key: 'guard_rails', label: 'Guard Rails' },
    { key: 'slopes', label: 'Slopes' },
  ],
  'Hazards': [
    { key: 'tripping_hazards', label: 'Tripping Hazards' },
    { key: 'fire_hazards', label: 'Fire Hazards' },
    { key: 'egress', label: 'Egress' },
    { key: 'flammables', label: 'Flammables' },
  ],
  'Equipment': [
    { key: 'electric_tool_safety', label: 'Electric Tool Safety' },
    { key: 'scaffold_safety', label: 'Scaffold Safety' },
    { key: 'excavator', label: 'Excavator' },
    { key: 'generator', label: 'Generator' },
  ],
  'Public Safety': [
    { key: 'flags_man_regulations', label: 'Flags / Man Regulations' },
    { key: 'sidewalk', label: 'Side Walk' },
    { key: 'street_safety', label: 'Street Safety' },
    { key: 'adjacent_property', label: 'Adjacent Property' },
  ],
});

export const TOPIC_GROUPS = Object.freeze(Object.keys(TOPICS));

/** Every topic key, flat. The renderer prints whichever are true. */
export const ALL_TOPIC_KEYS = Object.freeze(
  TOPIC_GROUPS.flatMap((g) => TOPICS[g].map((t) => t.key)),
);

// What the GATE supplies on an attendee row and the CP can then change. A
// field differing from its snapshot proves he edited it — see rosterReconcile.
export const TOOLBOX_GATE_FIELDS = Object.freeze(['name', 'title', 'company']);
// `signed` is the CP's presence tick. The gate never sets it, so a tick is
// proof the row is his.
export const TOOLBOX_ANSWER_FIELDS = Object.freeze(['signed']);

/** The keys every attendee row carries, for the payload-survival assertion. */
export const ATTENDEE_KEYS = Object.freeze([
  'worker_id', 'name', 'title', 'company', 'time',
  'gate_confirmed', 'gate_confirmed_at', 'signed', 'signature',
]);

/** A hand-added attendee. No worker_id — the app cannot identify him. */
export const EMPTY_ATTENDEE = () => ({
  worker_id: null,
  name: '',
  title: '',
  company: '',
  time: '',
  gate_confirmed: false,
  gate_confirmed_at: null,
  signed: false,
  signature: null,
});

/**
 * An ISO check-in timestamp as a short local clock ("7:12 AM").
 * A legacy non-ISO value is echoed rather than rendered "Invalid Date" on a
 * legal record.
 */
export function formatClock(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

/**
 * Today's check-ins → attendee rows, gate-stamped.
 *
 * A WORKER TURNED AWAY IS NOT AN ATTENDEE. A blocked row, or one sourced from
 * a cert_block alert, never reaches an ATTENDANCE roster — he was not at the
 * talk. Same filter the screen has always applied.
 */
export function buildAttendees(checkins) {
  return (Array.isArray(checkins) ? checkins : [])
    .filter((c) => c && c.blocked !== true && c.source !== 'cert_block')
    .map((c) => withGateSnapshot({
      worker_id: c.worker_id,
      // §3301.12.3 roster fields: name, title, company, time.
      name: c.worker_name || '',
      title: c.trade || '',
      company: c.company || '',
      time: c.check_in_time || '',
      // Optional gate confirmation. A worker who did NOT tap is still fully on
      // the roster — a courtesy marker, never a deficiency flag.
      gate_confirmed: c.toolbox_talk_confirmed === true,
      gate_confirmed_at: c.toolbox_talk_confirmed_at || null,
      // CP-tapped presence marker, not a signature.
      signed: false,
      // DELIBERATELY NULL. The worker's stored gate signature attests to the
      // §3301.11 site orientation, and app/site/logbooks.jsx renders any
      // non-null signature under "Worker Signatures" — carrying it here would
      // misrepresent its provenance on a toolbox-talk record.
      signature: null,
    }, TOOLBOX_GATE_FIELDS));
}

/**
 * Re-check a stored roster against today's check-ins.
 *
 * `fresh` null means the fetch failed (offline): everything is kept, because
 * the app must never drop a man because it could not reach the server. This is
 * the #130 behaviour and the port must not regress it — a stored payload that
 * is never re-checked is how a man who was refused at the gate stayed on a
 * signed sheet.
 */
export function reconcileAttendees(stored, fresh) {
  if (!Array.isArray(fresh)) return stored;
  return reconcileRoster({
    stored,
    fresh: buildAttendees(fresh),
    fields: TOOLBOX_GATE_FIELDS,
    answers: TOOLBOX_ANSWER_FIELDS,
  }).rows;
}

/** How many topics are ticked. */
export function topicCount(checkedTopics) {
  const t = (checkedTopics && typeof checkedTopics === 'object') ? checkedTopics : {};
  return ALL_TOPIC_KEYS.filter((k) => t[k] === true).length;
}

/** Attendees the renderer will actually print — it drops a nameless row. */
export function namedAttendees(attendees) {
  return (Array.isArray(attendees) ? attendees : [])
    .filter((a) => a && String(a.name || '').trim() !== '');
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates — a CP who
 * cannot complete a step must still be able to finish and sign.
 *
 * 1 the talk · 2 the topics · 3 who attended · 4 the signature.
 */
export function incompleteSteps({ location, performedBy, checkedTopics, attendees, cpSignature }) {
  const out = [];
  const anyDetail = [location, performedBy].some((v) => String(v ?? '').trim() !== '');
  if (!anyDetail) out.push(1);
  if (topicCount(checkedTopics) === 0) out.push(2);
  if (namedAttendees(attendees).length === 0) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/** The payload body. The ONE place the shape is decided. */
export function draftBody(f) {
  return {
    location: f.location || '',
    company_name: f.companyName || '',
    type_of_work: f.typeOfWork || '',
    meeting_time: f.meetingTime || '',
    performed_by: f.performedBy || '',
    checked_topics: f.checkedTopics || {},
    attendees: Array.isArray(f.attendees) ? f.attendees : [],
  };
}

export default {
  TOPICS,
  TOPIC_GROUPS,
  ALL_TOPIC_KEYS,
  TOOLBOX_GATE_FIELDS,
  TOOLBOX_ANSWER_FIELDS,
  ATTENDEE_KEYS,
  EMPTY_ATTENDEE,
  formatClock,
  buildAttendees,
  reconcileAttendees,
  topicCount,
  namedAttendees,
  incompleteSteps,
  draftBody,
};
