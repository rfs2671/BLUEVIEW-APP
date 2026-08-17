/**
 * The SSC / SSM Daily Safety Log — the site safety coordinator's daily
 * narrative.
 *
 * WHY A MODULE. Same reason as scaffoldMaintenanceModel and oshaLogModel: the
 * frontend suite has no renderer, so logic left in a component can only be
 * grepped while logic in a module can be EXECUTED. Everything here decides what
 * a DOB inspector reads off a filed document.
 *
 * THE PAYLOAD SHAPE IS FROZEN — thirteen top-level keys, flat:
 *
 *   project_address  ssp_number  weather  workers_on_site_count
 *   incidents_reported  safety_meetings_held  fire_protection_in_place
 *   housekeeping_satisfactory  ppe_compliance
 *   site_conditions  safety_violations_observed  corrective_actions_taken
 *   incident_details
 *
 * Three surfaces read them by key: the PDF renderer (backend/server.py:13526),
 * the combined report (:19893) and the kiosk inspector
 * (app/site/logbooks.jsx:1105). portedFormPayloads.test.cjs checks every key
 * against those renderers' OWN reads pulled out of the source.
 *
 * ── THIS IS AN END_OF_DAY LOG, NOT AN IMMEDIATE ONE ─────────────────────────
 *
 * LOGBOOK_TIMING_CLASS (server.py:2933) puts ssc_daily_safety_log with
 * daily_jobsite: the daily narrative stays open and accumulating all day and
 * freezes ONCE, at the end-of-day Submit and Sign. There is no
 * freezeIfImmediate here and there must not be — the freeze is an explicit
 * /finalize plus a local markFinalized, exactly as daily_jobsite does it.
 *
 * ── THE FIVE COMPLIANCE FLAGS ARE TWO-STATE, DELIBERATELY ──────────────────
 *
 * They are ordinary booleans seeded FALSE. The combined report prints a bare
 * Yes/No for them (server.py:19905) with no not-recorded branch and says so in
 * as many words — "Two-state ToggleRows (seeded false, always present)". They
 * are therefore NOT run through checklistMap: a third state would file
 * something that renderer has no way to print.
 *
 * Both PDF surfaces already qualify a rendered "No" as possibly an untouched
 * default rather than a deliberate negative finding, which is the honest
 * reading of a seeded false and is why the caveat line exists.
 */

/** The weather chips, unchanged from the form this replaces. */
export const WEATHER_OPTIONS = Object.freeze([
  'Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy',
]);

/**
 * Carried from the project record, not typed. The SSP number and the address
 * are properties of the JOB; retyping them daily is how they end up wrong.
 * They travel in the payload because all three renderers print them.
 */
export const PREFILLED_FIELDS = Object.freeze([
  { key: 'project_address', labelKey: 'fAddress' },
  { key: 'ssp_number', labelKey: 'fSsp' },
]);

// ── The five compliance flags, in the order the document prints them ────────
// Label text is duplicated in backend/server.py:13529-13535, again at
// :19897-19903, and again as the kiosk's s_* catalogue keys, because those
// renderers print filed documents with no access to this bundle. The test
// asserts all of them agree, key for key and word for word.
export const COMPLIANCE_FLAGS = Object.freeze([
  { key: 'incidents_reported', label: 'Incidents Reported' },
  { key: 'safety_meetings_held', label: 'Safety Meetings Held' },
  { key: 'fire_protection_in_place', label: 'Fire Protection in Place' },
  { key: 'housekeeping_satisfactory', label: 'Housekeeping Satisfactory' },
  { key: 'ppe_compliance', label: 'PPE Compliance' },
]);

// ── The narrative, in the order the document prints it ──────────────────────
// Same rule as the flags: these labels are printed verbatim by the PDF
// renderer's bold_para calls and by the kiosk.
export const NARRATIVE_FIELDS = Object.freeze([
  { key: 'site_conditions', label: 'Site Conditions' },
  { key: 'safety_violations_observed', label: 'Safety Violations Observed' },
  { key: 'corrective_actions_taken', label: 'Corrective Actions Taken' },
]);

/** The incident narrative, shown and printed only when one was reported. */
export const INCIDENT_DETAILS_LABEL = 'Incident Details';

/** A blank day. Every flag starts FALSE — see the header. */
export const EMPTY_DETAILS = () => ({
  project_address: '',
  ssp_number: '',
  weather: '',
  workers_on_site_count: '',
  incidents_reported: false,
  safety_meetings_held: false,
  fire_protection_in_place: false,
  housekeeping_satisfactory: false,
  ppe_compliance: false,
  site_conditions: '',
  safety_violations_observed: '',
  corrective_actions_taken: '',
  incident_details: '',
});

/**
 * Project record -> the form. Only the two keys this screen carries forward, so
 * a stray field on the project document cannot ride into a signed log.
 *
 * `location` is the fallback the screen has always used when `address` is
 * absent; a project with neither yields blanks rather than a crash.
 */
export function prefillFromProject(project) {
  const p = (project && typeof project === 'object') ? project : {};
  return {
    project_address: p.address || p.location || '',
    ssp_number: p.ssp_number || '',
  };
}

/**
 * Is the incident narrative on the document at all?
 *
 * THE RENDERERS' OWN RULE: incident detail is only meaningful when an incident
 * was reported — but if one WAS, a missing detail is an unanswered question,
 * not silence (server.py:13592, logbooks.jsx:1127). The screen shows the box
 * under exactly the same condition, so the CP is asked for everything the
 * document will print.
 */
export function incidentDetailsApply(details) {
  const d = (details && typeof details === 'object') ? details : {};
  return !!d.incidents_reported;
}

/** How many of the three narrative prompts have been written. */
export function narrativeWrittenCount(details) {
  const d = (details && typeof details === 'object') ? details : {};
  return NARRATIVE_FIELDS.filter((f) => String(d[f.key] ?? '').trim() !== '').length;
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates — an SSC who
 * cannot complete a step because the day is not over must still be able to
 * close it out.
 *
 * Step 1 the site, step 2 compliance, step 3 the narrative, step 4 the
 * signature.
 *
 * STEP 2 IS NEVER MARKED INCOMPLETE. The five flags are booleans that are
 * meaningfully false, so "off" is an answer and there is nothing to be
 * incomplete about — the same reason excavation_monitoring's two switches are
 * left out of its own step-3 rule.
 *
 * Step 3 is incomplete until all three narrative prompts are written, plus the
 * incident detail when an incident WAS reported: an unanswered prompt renders
 * "— Not recorded" on a filed DOB document, which is what the pip is for.
 */
export function incompleteSteps({ details, cpSignature }) {
  const out = [];
  const d = (details && typeof details === 'object') ? details : {};
  const anySite = ['project_address', 'ssp_number', 'weather', 'workers_on_site_count']
    .some((k) => String(d[k] ?? '').trim() !== '');
  if (!anySite) out.push(1);
  const narrativeDone = narrativeWrittenCount(d) === NARRATIVE_FIELDS.length
    && (!incidentDetailsApply(d) || String(d.incident_details ?? '').trim() !== '');
  if (!narrativeDone) out.push(3);
  if (!String(cpSignature || '').trim()) out.push(4);
  return out;
}

/**
 * The payload body. The ONE place the shape is decided.
 *
 * FLAT, and every key is always present — the renderers read
 * `data.get("site_conditions")` directly, and a key that only appears once it
 * is typed is a key that can go missing.
 *
 * incident_details is carried whether or not an incident was reported. The
 * renderers already decide when to PRINT it; dropping it here would delete a
 * detail the SSC typed before un-ticking the flag by mistake.
 */
export function draftBody(details) {
  const d = (details && typeof details === 'object') ? details : {};
  const out = EMPTY_DETAILS();
  for (const k of Object.keys(out)) {
    if (typeof out[k] === 'boolean') out[k] = !!d[k];
    else out[k] = d[k] ?? '';
  }
  return out;
}

/** The details a loaded document carries, narrowed to the thirteen this form owns. */
export function detailsFromData(data) {
  return draftBody(data);
}

export default {
  WEATHER_OPTIONS,
  PREFILLED_FIELDS,
  COMPLIANCE_FLAGS,
  NARRATIVE_FIELDS,
  INCIDENT_DETAILS_LABEL,
  EMPTY_DETAILS,
  prefillFromProject,
  incidentDetailsApply,
  narrativeWrittenCount,
  incompleteSteps,
  draftBody,
  detailsFromData,
};
