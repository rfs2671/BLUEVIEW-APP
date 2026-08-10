/**
 * The Daily Jobsite Log's decision logic, as pure functions.
 *
 * WHY THIS IS NOT IN THE SCREEN. Every rule below decides something that ends
 * up inside a SIGNED compliance record — who was on site, what a crew did,
 * whether a photo may be taken yet, what the PDF prints. Those rules need
 * tests that fail when they break, and the frontend suite here is a set of
 * dependency-free node harnesses (no renderer, no jsdom). Logic buried in a
 * component can only be asserted by grepping its source; logic in this module
 * can be EXECUTED. So the component owns rendering and this owns the answers.
 *
 * Nothing here imports React, react-native, or anything with a native module.
 * Keep it that way — `node src/utils/dailyJobsiteModel.test.cjs` runs it
 * directly.
 */

/**
 * The one normalization used to match a company/trade against the day's
 * roster. Mirrors _roster_key in backend/server.py (strip + casefold), so a
 * case-only or whitespace edit still resolves to the same subcontractor.
 */
export const rosterKey = (v) => String(v || '').trim().toLowerCase();

/**
 * The gate writes this literal when a worker's subcontractor is not on the
 * project roster (backend/server.py:9458-9462, :9471-9474). It is a
 * PLACEHOLDER, not a company, and it must never be stamped onto a 3301-02.
 */
export const UNASSIGNED_SENTINEL = 'unassigned';

export const isUnassignedCompany = (v) => {
  const k = rosterKey(v);
  return !k || k === UNASSIGNED_SENTINEL;
};

// Client-minted stable ids. Deliberately not server-owned: a row can be
// created with no signal at all (the whole point of the offline draft), so an
// id needing a round-trip would not exist for the rows that need it most.
let _activitySeq = 0;
export const newActivityId = () => `act_${Date.now()}_${(_activitySeq += 1)}`;

/**
 * ONE crew row, as it is written into data.activities[].
 *
 * The five keys the PDF renderers read positionally — crew_id, company,
 * num_workers, work_description, work_locations — are all present and are all
 * strings/numbers, because both renderers print them verbatim
 * (backend/server.py:12857-12861 and :17713-17719) and a new key is silently
 * invisible there. Everything else on the row is additive.
 */
export const EMPTY_ACTIVITY = () => ({
  activity_id: newActivityId(),
  // project.trade_assignments[].id. Null is the honest answer for a crew with
  // no roster identity; a placeholder would silently merge two unrelated subs.
  subcontractor_id: null,
  crew_id: '',
  company: '',
  num_workers: '',
  work_description: '',
  work_locations: '',
  photos: [],

  // ── additive, U1 ──────────────────────────────────────────────────────
  trade: '',
  // Provenance. A row the CP added by hand is NOT gate-sourced and must not
  // claim to be — the badge is a statement about where the number came from.
  gate_sourced: false,
  check_in_time: null,
  worker_ids: [],
  // Chip selections. The composed human-readable labels go into
  // work_description / work_locations so the signed PDF still renders; these
  // are what the sequence ranker reads back tomorrow.
  activity_ids: [],
  location_ids: [],
  // Company correction keeps BOTH values, attributed. company_gate is never
  // overwritten, so the signed log and the check-in record cannot contradict
  // each other.
  company_gate: null,
  company_corrected_by: null,
  company_corrected_at: null,
});

export const EMPTY_OBSERVATION = () => ({
  description: '',
  responsible_party: '',
  remedy: '',
  corrected_immediately: null,
});

/**
 * Build the day's crew rows from the per-worker gate roster.
 *
 * `workers` is /checkins-today's row shape; `headcount` is /daily-headcount,
 * used ONLY to bind subcontractor_id, which the per-worker endpoint does not
 * carry.
 *
 * THREE RULES THAT MATTER:
 *
 *  1. A TURNED-AWAY WORKER IS NOT ON SITE. Rows with blocked === true come
 *     from compliance_alerts (server.py pass 3) — they were refused at the
 *     gate and did no work. Counting them would overstate the headcount on a
 *     signed record. This also matches what /daily-headcount does today, so
 *     switching the roster source does not change the number.
 *
 *  2. A WORKER WITH NO CREW GETS HIS OWN ROW. He is a real man on site and the
 *     log has to say so. He cannot be merged with other unassigned workers —
 *     they are not a crew, they are separate people whose subcontractor the
 *     admin has not entered yet.
 *
 *  3. THE COMPANY IS NEVER THE SENTINEL. "UNASSIGNED" is seeded as empty, and
 *     the row is marked unbound rather than being stamped with a placeholder.
 */
export function buildCrewsFromRoster(workers, headcount) {
  const rows = Array.isArray(workers) ? workers : [];
  const rosterIds = rosterIdIndex(headcount);

  const crews = new Map();   // key -> row
  const loose = [];          // one row per unassigned worker

  for (const w of rows) {
    if (!w || w.blocked === true) continue;   // rule 1
    const company = isUnassignedCompany(w.company) ? '' : String(w.company).trim();
    const trade = String(w.trade || '').trim();
    const at = parseInstant(w.check_in_time);

    if (!company) {
      // Rule 2 — his own row, never merged with another unassigned worker.
      loose.push({
        ...EMPTY_ACTIVITY(),
        company: '',
        trade,
        num_workers: '1',
        gate_sourced: true,
        check_in_time: at,
        worker_ids: w.worker_id ? [String(w.worker_id)] : [],
        worker_names: [String(w.worker_name || '').trim()].filter(Boolean),
      });
      continue;
    }

    const key = `${rosterKey(company)}|${rosterKey(trade)}`;
    let row = crews.get(key);
    if (!row) {
      row = {
        ...EMPTY_ACTIVITY(),
        company,
        company_gate: company,
        trade,
        num_workers: '0',
        gate_sourced: true,
        check_in_time: null,
        worker_ids: [],
        worker_names: [],
        subcontractor_id: rosterIds.get(key) || null,
      };
      crews.set(key, row);
    }
    row.num_workers = String((parseInt(row.num_workers, 10) || 0) + 1);
    if (w.worker_id) row.worker_ids.push(String(w.worker_id));
    const nm = String(w.worker_name || '').trim();
    if (nm) row.worker_names.push(nm);
    // Earliest arrival is the crew's check-in time. A crew trickles in; the
    // first man through the gate is when that crew was on site from.
    if (at && (!row.check_in_time || at < row.check_in_time)) row.check_in_time = at;
  }

  const ordered = [...crews.values()].sort((a, b) => (
    a.company.toLowerCase().localeCompare(b.company.toLowerCase())
    || a.trade.toLowerCase().localeCompare(b.trade.toLowerCase())
  ));
  const all = [...ordered, ...loose];
  // crew_id is the PDF's first column and must be stable and present.
  all.forEach((r, i) => { r.crew_id = `C${i + 1}`; });
  return all;
}

/** rosterKey(company)|rosterKey(trade) -> subcontractor_id, from /daily-headcount. */
export function rosterIdIndex(headcount) {
  const out = new Map();
  for (const r of (Array.isArray(headcount) ? headcount : [])) {
    const id = r?.subcontractor_id;
    if (!id) continue;
    out.set(`${rosterKey(r?.sub_name)}|${rosterKey(r?.trade)}`, id);
  }
  return out;
}

/** ISO string / Date -> Date, or null. Never throws, never guesses. */
export function parseInstant(v) {
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v;
  if (typeof v !== 'string' || !v.trim()) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * Compose the chips a CP TAPPED into the sentence the PDF prints.
 *
 * THE POINT OF THE WHOLE CHANGE. The old screen wrote `work_description:
 * r.trade`, so a signed log asserted the Concrete crew performed "Concrete" —
 * the app wrote that, not the CP. An unselected activity is EMPTY here, never
 * guessed, and `trade` is not consulted at all.
 *
 * The composed string (rather than the ids alone) is what reaches the record
 * because both PDF renderers print work_description verbatim and would
 * otherwise show a blank column.
 */
export function composeSelection(selectedIds, chipsById) {
  const ids = Array.isArray(selectedIds) ? selectedIds : [];
  const labels = [];
  for (const id of ids) {
    const label = String(chipsById?.get?.(id) ?? chipsById?.[id] ?? '').trim();
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels.join(', ');
}

/**
 * May the camera open for this row yet?
 *
 * NO PHOTO WITHOUT ITS SUBJECT. The camera appears only once crew, activity
 * and location are all set, so every frame carries crew id, activity, location
 * and date before the shutter fires. A photo that cannot say what it is
 * evidence of is not evidence.
 */
export function cameraReady(activity) {
  if (!activity) return false;
  const hasCrew = Boolean(String(activity.company || '').trim())
    || Boolean(String(activity.crew_id || '').trim());
  const hasActivity = (activity.activity_ids || []).length > 0
    && Boolean(String(activity.work_description || '').trim());
  const hasLocation = (activity.location_ids || []).length > 0
    || Boolean(String(activity.work_locations || '').trim());
  return hasCrew && hasActivity && hasLocation;
}

/**
 * Correct a crew's company, KEEPING BOTH VALUES, attributed.
 *
 * The gate value is written once and never overwritten — re-correcting a row
 * that was already corrected must not lose what the gate actually recorded.
 * The roster binding is re-resolved because a row carrying Acme's id under a
 * different sub's name is a fabricated binding: it would share Acme's photo
 * bucket and be reported against Acme.
 */
export function applyCompanyCorrection(activity, nextCompany, opts = {}) {
  const { by = null, at = null, rosterIds = null } = opts;
  const clean = String(nextCompany || '').trim();
  const priorGate = activity.company_gate != null
    ? activity.company_gate
    : (activity.gate_sourced ? (activity.company || '') : null);
  const key = `${rosterKey(clean)}|${rosterKey(activity.trade)}`;
  return {
    ...activity,
    company: clean,
    company_gate: priorGate,
    company_corrected_by: by,
    company_corrected_at: at,
    subcontractor_id: rosterIds ? (rosterIds.get(key) || null) : null,
  };
}

/** True once this row names a sub the project roster does not know. */
export const isUnboundCrew = (activity) => Boolean(
  activity && String(activity.company || '').trim() && !activity.subcontractor_id,
);

/**
 * An observation cannot be saved without a corrective action.
 *
 * A logged hazard with no remedy is a record that something was seen and
 * nothing was done. `corrected_immediately` already exists on the row and
 * counts as the action being stated.
 */
export function observationComplete(obs) {
  if (!obs) return false;
  const described = Boolean(String(obs.description || '').trim());
  const remedied = Boolean(String(obs.remedy || '').trim())
    || obs.corrected_immediately === true;
  const owned = Boolean(String(obs.responsible_party || '').trim());
  return described && remedied && owned;
}

/** Which observations block the sign step, by index. */
export const incompleteObservations = (list) => (Array.isArray(list) ? list : [])
  .map((o, i) => (observationComplete(o) ? -1 : i))
  .filter((i) => i >= 0);

/**
 * Display a YYYY-MM-DD without a timezone touching it.
 *
 * NOT `new Date('2026-08-09').toLocaleDateString()`: that parses as UTC
 * midnight and then formats in the DEVICE's zone, so a phone west of Greenwich
 * renders the day BEFORE. The log's date is already a calendar day — no zone
 * is involved at either end, so none is introduced. Related: src/utils/dates.js.
 */
export function formatLogDate(dateStr) {
  const parts = String(dateStr || '').split('-').map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) {
    return String(dateStr || '');
  }
  const [y, m, d] = parts;
  const anchor = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  return anchor.toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    timeZone: 'UTC',
  });
}

/** A check-in instant as a short wall-clock time in New York. */
export function formatCheckInTime(value) {
  const d = parseInstant(value);
  if (!d) return null;
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York',
  });
}

/**
 * Is this step's work done? Drives the stepper's progress marks only — it
 * NEVER blocks moving on. A CP who cannot complete a step because the data is
 * not there must still be able to finish and sign his day.
 */
export function stepComplete(step, state) {
  const acts = state?.activities || [];
  switch (step) {
    case 1: return acts.length > 0;
    case 2: return acts.length > 0
      && acts.every((a) => String(a.work_description || '').trim());
    case 3: return incompleteObservations(state?.observations).length === 0;
    case 4: return Boolean(state?.weather);
    case 5: return Boolean(state?.cpSignature);
    default: return false;
  }
}

export default {
  rosterKey,
  isUnassignedCompany,
  newActivityId,
  EMPTY_ACTIVITY,
  EMPTY_OBSERVATION,
  buildCrewsFromRoster,
  rosterIdIndex,
  parseInstant,
  composeSelection,
  cameraReady,
  applyCompanyCorrection,
  isUnboundCrew,
  observationComplete,
  incompleteObservations,
  formatLogDate,
  formatCheckInTime,
  stepComplete,
};
