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
    // 'covid19' REMOVED — operator ruling, device round 4 finding 9. It is not
    // PPE and it is not a talk topic any more. The key is deliberately NOT
    // reinstated anywhere: an old filed record that carries `covid19: true` in
    // checked_topics still renders, because the PDF prints whatever keys are
    // true rather than looking them up here. Historical records are not
    // rewritten.
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

/**
 * WHERE A ROW CAME FROM. Three provenances, and they are three different
 * claims about the same man:
 *
 *   'gate'         he checked in TODAY. The gate says he was on site.
 *   'weekly_gap'   he worked THIS WEEK, not necessarily today, and the CP is
 *                  asserting he attended this talk.
 *   'manual'       the CP typed him in. The app knows nothing about him.
 *
 * A signed attendance sheet that cannot tell these apart is asserting the gate
 * vouched for a man it never saw. Operator ruling, device round 4.
 */
export const ATTENDEE_SOURCES = Object.freeze({
  GATE: 'gate', WEEKLY_GAP: 'weekly_gap', MANUAL: 'manual',
});

/** The keys every attendee row carries, for the payload-survival assertion. */
export const ATTENDEE_KEYS = Object.freeze([
  'worker_id', 'name', 'title', 'company', 'time',
  'gate_confirmed', 'gate_confirmed_at', 'signed', 'signature', 'added_from',
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
  added_from: ATTENDEE_SOURCES.MANUAL,
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
      added_from: ATTENDEE_SOURCES.GATE,
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

/**
 * Topic groups with NOTHING TICKED — the sentence the submit gate shows him.
 *
 * THE DEFECT THE COUNT HID. The gate asked `topicCount(checkedTopics) === 0`,
 * a TOTAL across all five groups, so five PPE ticks and nothing else satisfied
 * it: hard hats, boots, glasses, harness and gloves, and not one word about
 * working at height, the hazards on the site, the equipment running that day or
 * the public on the far side of the fence. The filed §3301.12.3 record read as
 * a complete talk. A total cannot tell "thorough about one thing" from
 * "covered everything", and those are the two cases that matter.
 *
 * PER TAB, because the tab IS the subject. The five groups are not a taxonomy
 * imposed on a list of topics — they are the five things a talk has to touch,
 * and the screen already puts each behind its own tab. A CP who never opened
 * Fall Protection never discussed it, and the record should not say he did.
 *
 * Returns the GROUP NAMES, which are the tab labels, so the sentence names the
 * tabs he has to open rather than a number he has to reconcile.
 */
export function emptyTopicGroups(checkedTopics) {
  const t = (checkedTopics && typeof checkedTopics === 'object') ? checkedTopics : {};
  return TOPIC_GROUPS.filter((g) => !TOPICS[g].some((x) => t[x.key] === true));
}

/** Attendees the renderer will actually print — it drops a nameless row. */
export function namedAttendees(attendees) {
  return (Array.isArray(attendees) ? attendees : [])
    .filter((a) => a && String(a.name || '').trim() !== '');
}

/**
 * Touched rows that WILL NOT BE FILED — the sentence the submit gate shows him.
 *
 * BOTH RENDERERS ALREADY DROP A NAMELESS ATTENDEE, so the row could reach the
 * STORED record and never the FILED one: an auditor reading the collection and
 * an inspector reading the PDF saw different sheets, and only the first showed
 * the row. And a nameless row is not blank — `signed` is the CP's Present mark
 * and `gate_confirmed` is the worker's own tap at the turnstile, so it carried
 * two ticks against a man the record cannot name.
 *
 * An untouched EMPTY_ATTENDEE is NOT reported: it says nothing, it has always
 * been dropped silently, and only a row he put something into is worth
 * stopping him for.
 */
export function unnamedAttendees(attendees) {
  const out = [];
  (Array.isArray(attendees) ? attendees : []).forEach((a, i) => {
    if (!a || typeof a !== 'object') return;
    if (String(a.name || '').trim() !== '') return;
    const held = [...TOOLBOX_GATE_FIELDS.filter((k) => k !== 'name'),
      'time'].map((k) => String(a[k] ?? '').trim()).filter(Boolean);
    const marked = !!a.signed || !!a.gate_confirmed;
    if (held.length === 0 && !marked) return;
    out.push({ row: i + 1, held: held.join(', '), marked });
  });
  return out;
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates — a CP who
 * cannot complete a step must still be able to finish and sign.
 *
 * 1 the talk · 2 the topics · 3 who attended · 4 the signature.
 */
/**
 * STEP 1 IS ALL-OR-NOTHING, by operator ruling (device round 4, finding 8).
 *
 * Every one of these five identifies the talk on a filed §3301.12.3 record —
 * where it happened, whose talk it was, what work it covered, when. A record
 * missing any of them is a record that cannot be placed. Two of them now
 * autofill (location, performed_by), so this asks the CP for three things he
 * is standing in the middle of.
 *
 * NOTE THE TENSION, deliberately accepted: everywhere else in this app an
 * incomplete step MARKS and never GATES, because a CP must be able to finish
 * his day. Step 1 is the exception the operator ruled — these are identity
 * fields, not observations, and none of them depends on anything he might not
 * have yet.
 *
 * Returns the FIELD NAMES still empty, so each control can mark itself rather
 * than the screen showing one blanket error.
 */
export const STEP_ONE_FIELDS = Object.freeze([
  'location', 'companyName', 'typeOfWork', 'meetingTime', 'performedBy',
]);

export function missingStepOneFields(f) {
  const v = f || {};
  return STEP_ONE_FIELDS.filter((k) => String(v[k] ?? '').trim() === '');
}

/**
 * The men who worked THIS WEEK, have not had a talk, and are not already on
 * today's roster — device round 4, ruling C.
 *
 * A toolbox talk is a WEEKLY obligation and the roster is built from TODAY's
 * check-ins, so a CP giving Thursday's talk was never offered the men who
 * worked Monday to Wednesday. Production: 26 worked the week, 13 were on site
 * the day. The card counted 13 he had no way to put on the sheet.
 *
 * `missing` is the notifications payload's `missing_toolbox_talk`. Anyone
 * already on the roster is filtered out BY WORKER ID and, failing that, by
 * normalised name — a man must not appear twice on an attendance record, and
 * the two lists come from different queries with no guarantee of the same
 * shape.
 */
export function weeklyGapWorkers(missing, attendees) {
  const rows = Array.isArray(missing) ? missing : [];
  const onSheet = new Set();
  for (const a of (Array.isArray(attendees) ? attendees : [])) {
    if (!a) continue;
    if (a.worker_id) onSheet.add(`id:${String(a.worker_id)}`);
    const n = String(a.name || '').trim().replace(/\s+/g, ' ').toLowerCase();
    if (n) onSheet.add(`name:${n}`);
  }
  const seen = new Set();
  return rows.filter((w) => {
    if (!w) return false;
    const id = w.worker_id ? `id:${String(w.worker_id)}` : '';
    const nm = String(w.worker_name || '').trim().replace(/\s+/g, ' ').toLowerCase();
    if (!id && !nm) return false;
    if ((id && onSheet.has(id)) || (nm && onSheet.has(`name:${nm}`))) return false;
    const k = id || `name:${nm}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/**
 * A weekly-gap worker as an attendee row.
 *
 * NO GATE SNAPSHOT and no `time`: the gate did not put him here and has nothing
 * to say about today. `added_from` records that this is the CP's assertion, and
 * `signed` starts FALSE — adding a man to the list is not the same as marking
 * him present, and the CP still has to say he was there.
 */
export function weeklyGapAttendee(w) {
  return {
    worker_id: (w && w.worker_id) || null,
    name: (w && w.worker_name) || '',
    title: (w && w.trade) || '',
    company: (w && w.company) || '',
    time: '',
    gate_confirmed: false,
    gate_confirmed_at: null,
    signed: false,
    signature: null,
    added_from: ATTENDEE_SOURCES.WEEKLY_GAP,
  };
}

export function incompleteSteps({
  location, companyName, typeOfWork, meetingTime, performedBy,
  checkedTopics, attendees, cpSignature,
}) {
  const out = [];
  if (missingStepOneFields({
    location, companyName, typeOfWork, meetingTime, performedBy,
  }).length > 0) out.push(1);
  // PER TAB, NOT A TOTAL. The pip and the submit gate read the same function,
  // so step 2 cannot mark complete while the gate is refusing.
  if (emptyTopicGroups(checkedTopics).length > 0) out.push(2);
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
    // NAMED ROWS ONLY WHEN FILING. A draft keeps everything, because a
    // half-typed attendee is ordinary work while the talk is happening; it is
    // only at the moment of filing that a nameless row becomes a man on a
    // signed attendance record who cannot be identified. Both renderers
    // already refuse to print one, so without this the STORED record and the
    // FILED record disagree — and only the stored one shows the row.
    attendees: f.forFiling
      ? namedAttendees(f.attendees)
      : (Array.isArray(f.attendees) ? f.attendees : []),
  };
}

export default {
  TOPICS,
  TOPIC_GROUPS,
  ALL_TOPIC_KEYS,
  TOOLBOX_GATE_FIELDS,
  TOOLBOX_ANSWER_FIELDS,
  ATTENDEE_KEYS,
  ATTENDEE_SOURCES,
  STEP_ONE_FIELDS,
  missingStepOneFields,
  weeklyGapWorkers,
  weeklyGapAttendee,
  EMPTY_ATTENDEE,
  formatClock,
  buildAttendees,
  reconcileAttendees,
  topicCount,
  namedAttendees,
  unnamedAttendees,
  incompleteSteps,
  emptyTopicGroups,
  draftBody,
};
