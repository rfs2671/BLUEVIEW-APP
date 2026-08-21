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

/**
 * THE SAME RULE, FOR TRADE. The gate writes "UNASSIGNED" into a check-in's
 * `trade` as well as its `company`, and only the company was ever sanitised —
 * so the placeholder rendered on Step 1 as though it were the man's trade.
 *
 * The three coercion sites are the no_roster and not_listed branches of
 * register-and-checkin and the no_roster branch of submit. Named rather than
 * cited by line: the addresses this comment used to carry (:10043, :10055,
 * :10687) had all drifted, and a comment pointing at the wrong lines is how
 * the next reader concludes the claim itself is false. Search
 * `or "UNASSIGNED"` in server.py.
 *
 * `cleanTrade` returns '' for the sentinel, matching what buildCrewsFromRoster
 * already does to company. Callers that DISPLAY it use `tradeLabel`, which
 * names the absence rather than leaving a gap: an empty cell on a record
 * somebody signs cannot be told from a question nobody asked.
 */
export const isUnassignedTrade = (v) => {
  const k = rosterKey(v);
  return !k || k === UNASSIGNED_SENTINEL;
};

export const cleanTrade = (v) => (isUnassignedTrade(v) ? '' : String(v).trim());

export const NO_TRADE_LABEL = 'No trade assigned';

export const tradeLabel = (v) => (cleanTrade(v) || NO_TRADE_LABEL);

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
  // GATE PROVENANCE, not a correction trail. Set once, at seed time, to the
  // company the gate actually recorded, so the signed log and the check-in
  // record can always be compared.
  //
  // It no longer has a companion `company_corrected_by` / `_at`: assigning a
  // company or trade does not belong on the daily log at all. A worker sets his
  // own at check-in, and a CP who has to fix it does so during safety
  // orientation — the first-time-on-site flow — not here. Those two keys had
  // exactly one writer, the correction flow, and died with it.
  company_gate: null,
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
    // Sanitised at the boundary, exactly as company is on the line above:
    // the sentinel must not travel into a crew row, a cache key, or
    // data.activities[].trade on a filed log.
    const trade = cleanTrade(w.trade);
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
 * The roster row a (company, trade) pair belongs to, or null.
 *
 * THE ONLY REMAINING BINDING PATH. `applyCompanyCorrection` lived here and is
 * gone: assigning a company or trade does not belong on the daily log. A
 * worker sets his own at check-in; a CP who has to fix one does it during
 * safety orientation. What survives is the hand-added crew — the CP naming a
 * crew the gate missed — which still has to resolve to a real roster row.
 *
 * NULL IS THE ANSWER WHENEVER IT IS NOT CERTAIN. A row carrying one sub's id
 * under another's name is a fabricated binding: it would share that sub's
 * photo bucket and be reported against them. Matching is on the same
 * strip+casefold rule the backend's _roster_key uses, so a case or whitespace
 * difference still resolves; anything else does not resolve at all.
 */
export function resolveRosterId(company, trade, rosterIds) {
  if (!rosterIds || typeof rosterIds.get !== 'function') return null;
  const name = rosterKey(company);
  if (!name) return null;   // no company, no identity
  return rosterIds.get(`${name}|${rosterKey(trade)}`) || null;
}

/**
 * Draft the day's general description from the TRADES of the chips the CP
 * actually tapped, across every crew.
 *
 * WHY TRADES AND NOT A PHASE. A phase line ("foundation prep") would read
 * better, but no phase attribute exists: the sequence rules carry
 * id/trade/scope/per_floor/is_structural/zone_scoped/requires and nothing
 * else, and the semantic phases exist only as SOURCE COMMENTS in
 * sequence_rules_v1.py. Deciding which of 86 nodes is "foundation" versus
 * "superstructure" is domain judgment, and that graph's own header says
 * RULE CONTENTS PENDING NYC DOB DOMAIN-EXPERT SIGN-OFF. `trade` is already on
 * every node, set by whoever authored the approved rules, so it is reportable
 * without anyone here inventing taxonomy. Weaker prose, but TRUE.
 *
 * (The other candidate, lib/ai/phase_inference.py, is weekly Gemini inference
 * at PROJECT granularity. It cannot say what this crew did today, and prose
 * generated into a signed legal record is a different risk class.)
 *
 * RULES:
 *   * EMPTY when nothing was tapped. Never guessed, never defaulted.
 *   * The "other" escape hatch is EXCLUDED even though its node reports trade
 *     "gc" — the chip stands for free text the CP typed, so its trade says
 *     nothing about the work.
 *   * Trades are de-duplicated and ordered by how many crews were doing them,
 *     so the biggest activity on site leads the sentence. Ties keep first-seen
 *     order, which makes the output deterministic and therefore testable.
 *
 * This is a DRAFT. The caller must show it to the CP and let him edit it
 * before he signs — he is attesting to the sentence, so the app may propose it
 * but may not put words he never read into the record.
 */
export const OTHER_CHIP_ID = 'other';

export function deriveGeneralDescription(activities, tradeById) {
  const rows = Array.isArray(activities) ? activities : [];
  const counts = new Map();       // trade -> crews doing it
  const order = [];               // first-seen order, for stable ties

  for (const a of rows) {
    const seenHere = new Set();   // one crew counts a trade once
    for (const id of (a?.activity_ids || [])) {
      if (id === OTHER_CHIP_ID) continue;          // free text, not a trade
      if (String(id).startsWith('other:')) continue;
      const raw = tradeById?.get?.(id) ?? tradeById?.[id];
      const trade = String(raw || '').trim().toLowerCase();
      if (!trade || seenHere.has(trade)) continue;
      seenHere.add(trade);
      if (!counts.has(trade)) { counts.set(trade, 0); order.push(trade); }
      counts.set(trade, counts.get(trade) + 1);
    }
  }

  if (order.length === 0) return '';
  const ranked = [...order].sort((a, b) => (
    counts.get(b) - counts.get(a) || order.indexOf(a) - order.indexOf(b)
  ));
  return ranked.join(', ');
}

/**
 * Is this row a worker who came through the gate with NO company?
 *
 * AN ACTIVITY ROW REPRESENTS A COMPANY'S WORK. A man with no company assignment
 * does not get one: giving him activity and location fields lets the CP log
 * work against nobody, and that is a line in a signed record that cannot be
 * true. He is a real person who was on site, so Step 1 shows him and flags him
 * for assignment — he is simply not a unit of work yet.
 *
 * He is NEVER blocked over it. Soft flag, not a gate.
 *
 * Identified by the absence of a company on a gate-sourced row. A hand-added
 * crew always has one (commitAddCrew refuses an empty company), so this cannot
 * catch a crew the CP typed in.
 *
 * ONCE HE IS ASSIGNED A COMPANY HE JOINS THAT COMPANY'S ROW rather than
 * creating a new one — that needs no code here, because buildCrewsFromRoster
 * keys crews on (company, trade) and he simply falls into the existing bucket
 * on the next roster read. Asserted in the tests so it cannot regress.
 */
export const isUnassignedWorkerRow = (activity) => Boolean(
  activity && activity.gate_sourced && !String(activity.company || '').trim(),
);

/** The rows that represent a company's work — the ones Step 2 asks about. */
export const workRows = (activities) => (Array.isArray(activities) ? activities : [])
  .filter((a) => !isUnassignedWorkerRow(a));

/**
 * Crews the CP has left with NO WORK DESCRIBED — the sentence the submit gate
 * shows him.
 *
 * THE RULE ALREADY EXISTED AND ONLY MARKED. stepComplete(2) says a step is
 * complete when every work row carries a description, and the step pip has been
 * reading it all along. Nothing stopped him signing: a filed §3301.2 daily log
 * could name four subcontractors on site and say what none of them did, and the
 * only trace was a pip he had already walked past.
 *
 * UNASSIGNED WORKERS ARE NOT CREWS. A man who checked in with no company gets
 * no activity card, so asking him for a work description would block every day
 * on which one person tapped in without a company assigned. workRows drops
 * those rows and this inherits that, so the two cannot drift.
 *
 * Returns the crew LABEL, because a row number means nothing on a screen that
 * lists crews by company.
 */
export function crewsWithoutWork(activities) {
  const rows = workRows(activities);
  const total = rows.length;
  return rows
    .map((a, i) => ({ a, n: i + 1 }))
    .map(({ a, n }) => {
      const missing = [];
      if (String(a?.work_description || '').trim() === '') missing.push('activity');
      // AND A LOCATION. A crew's activity with nowhere attached is half a
      // record: the §3301.2 table has a Location column, the photo caption is
      // built from it, and "formwork" with no floor tells an inspector which
      // trade was on site and nothing about where to look.
      if (String(a?.work_locations || '').trim() === '') missing.push('location');
      return {
        crew: String(a?.company || '').trim(),
        trade: String(a?.trade || '').trim(),
        // POSITION AND TOTAL. "Crew 3 of 5" tells him where to go; a bare
        // count makes him hunt down the list comparing what he sees against a
        // number. The position is within workRows, which is the list the step
        // actually renders — an unassigned-worker row has no card, so counting
        // it would point at a crew that is not on screen.
        row: n,
        total,
        missing,
      };
    })
    .filter((c) => c.missing.length > 0);
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

/* ── THE DAILY INSPECTIONS ─────────────────────────────────────────────────
 *
 * The nine items the CP walks. They used to be tick-chips under "Items
 * Inspected", which could only ever record THAT he looked — never what he
 * found. A tick beside "Fall Protections" on a filed DOB document reads as
 * "fall protections are fine", and there was no way for it to say otherwise.
 *
 * The row is therefore {result, note}:
 *
 *   result  'pass' | 'fail' | null   null means NOT WALKED, which is not the
 *                                    same as passed and must never render as
 *                                    one.
 *   note    string                   REQUIRED on a fail. A failed inspection
 *                                    with no note is the same empty record the
 *                                    tick was.
 *
 * NOT_WALKED IS A REAL STATE. The CP is not forced to walk all nine — the
 * gate is only that a fail carries its note. An unwalked item prints as not
 * inspected rather than being quietly dropped into the passed list.
 */
export const INSPECTION_PASS = 'pass';
export const INSPECTION_FAIL = 'fail';

export const EMPTY_INSPECTION = () => ({ result: null, note: '' });

/**
 * "OTHER" IS NOT A PASS/FAIL ITEM — device round 4, finding 13.
 *
 * The other eight name a specific thing to look at, so pass and fail mean
 * something about that thing. "Other" names nothing. A green "Passed: Other"
 * on a filed 3301-02 asserts that an unnamed inspection was fine — a claim
 * with no subject, which is exactly the emptiness the tick-chips were replaced
 * to remove.
 *
 * It carries the CP writing WHAT he inspected instead. Same {result, note}
 * shape, so nothing about the payload changes; `result` simply stays null and
 * the note is the record.
 */
export const OTHER_INSPECTION_KEY = 'other_checklist';
export const isOtherInspection = (key) => key === OTHER_INSPECTION_KEY;

/** One item's row, whatever shape the stored log used. See migrateChecklist. */
export const inspectionRow = (items, key) => {
  const row = (items || {})[key];
  if (row && typeof row === 'object') {
    return {
      result: row.result === INSPECTION_PASS || row.result === INSPECTION_FAIL
        ? row.result : null,
      note: String(row.note || ''),
    };
  }
  // LEGACY: a log filed while this was a tick-chip. `true` meant "inspected"
  // and carried no result, so it is reported as walked-with-no-result rather
  // than being upgraded to a pass nobody recorded.
  if (row === true) return { result: null, note: '', legacy_ticked: true };
  return EMPTY_INSPECTION();
};

/**
 * A fail must say what failed. Nothing else is required — an unwalked item is
 * allowed, and a pass needs no note.
 */
export const inspectionComplete = (row) => {
  const r = inspectionRow({ k: row }, 'k');
  if (r.result !== INSPECTION_FAIL) return true;
  return Boolean(String(r.note || '').trim());
};

/** Which inspection keys block the sign step. Keys, not indexes: the nine are
 *  a fixed named set, and an index would silently renumber if one is added. */
export const incompleteInspections = (items) => Object.keys(items || {})
  .filter((k) => !inspectionComplete((items || {})[k]));

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
    case 2: {
      // Only the rows Step 2 actually asks about. An unassigned worker gets no
      // activity card, so requiring a work description from him would leave
      // this step permanently incomplete the moment one man checks in without
      // a company.
      // ACTIVITY *AND* LOCATION — the same pair the Next gate asks for.
      //
      // This asked only for the description while crewsWithoutWork also
      // required a location, so a crew with work and no floor made the pip read
      // COMPLETE and the Next button sit dead. A CP stopped by something the
      // screen has just told him is finished learns to distrust the screen, and
      // that is the failure this pair is watched for.
      const work = workRows(acts);
      return work.length > 0 && work.every(
        (a) => String(a.work_description || '').trim()
          && String(a.work_locations || '').trim(),
      );
    }
    case 3: return incompleteObservations(state?.observations).length === 0;
    // Step 4 is the nine daily inspections. Weather moved to Step 1, where it
    // belongs with the other observed facts about the day; it was never
    // something Step 4 asked the CP for, so a fetch failure it could not fix
    // used to leave this step permanently marked incomplete.
    case 4: return incompleteInspections(state?.checklistItems).length === 0;
    case 5: return Boolean(state?.cpSignature);
    default: return false;
  }
}

/**
 * FOUR SLOTS PER CREW, composed — device round 4, finding 11, ruled.
 *
 * The card was offering the whole catalogue: 86 chips on a cold start, 78 with
 * a prior. Four is the cap the operator set, and it CANNOT be a top-four slice
 * of one band, because the bands answer different questions.
 *
 * THE RULINGS, each with the reason it was ruled:
 *
 *   ALL FIVE ON A COLD START. The project-start set is exactly five — site
 *   prep, excavation, shoring, underpinning, piles — and which one a cap of
 *   four would drop is alphabetical accident, not judgement. Five is a small
 *   enough overrun to be worth more than a tidy number.
 *
 *   ALWAYS-AVAILABLE NEVER COUNTS AGAINST THE FOUR. Site clean-up, material
 *   delivery, inspection, rain / no work are what ANY crew can log on ANY day.
 *   They are not this crew's ranked work, and burying "rain / no work" behind
 *   an expander on a rain day is worse than a longer list.
 *
 *   THE PRIOR ITSELF STAYS IN. The ranker re-emits yesterday's activity in the
 *   suggested band because work continues across days; dropping it to save a
 *   slot would make the CP re-find it every morning.
 *
 *   A TRADE WITH NO SEQUENCED SUCCESSORS SAYS SO. `suggested` is narrowed by
 *   intersection with the trade's nodes, and most trades' activities carry no
 *   edges in the sequence graph, so a carpentry crew with a real prior gets
 *   ZERO suggested chips. Its four then come from the trade catalogue in
 *   declaration order — which encodes nothing about yesterday. `basis` says
 *   which of the two happened so the card can be honest instead of implying a
 *   ranking that does not exist.
 *
 * NOTHING IS HIDDEN, only folded: `rest` still holds everything else and the
 * expander still reaches it. A cap on what is offered first is not a cap on
 * what can be logged, and "Other" is always reachable.
 */
export const CHIP_SLOTS = 4;

/**
 * THE ALWAYS-AVAILABLE BAND IS GONE.
 *
 * Twelve chips sat on EVERY crew card regardless of trade — offering an HVAC
 * crew "scaffold dismantle" and "site clean-up", which is another sub's work.
 * The operator's correction: a crew card offers that crew's trade work and
 * nothing else.
 *
 * Scaffold erection appears on the scaffolding crew's card because it is in
 * their taxonomy. Site clean-up on whoever cleaned up. Two of the twelve —
 * "rain - no work" and "shutdown" — were facts about the DAY rather than a
 * crew's activity and were removed from the taxonomy outright — a day-level
 * control for them was tried and withdrawn, because nobody is on site to open
 * the app on a washout and the absence of a log for a date is the record. The
 * other ten now flow through suggested/catalog by trade, because the ranker
 * stopped special-casing them.
 *
 * Returns { primary, rest, basis }. `always` is gone from the shape.
 */
export function composeChipBands({ chips, allChips, resolvedTrades, priorDate }) {
  // A malformed chip is DROPPED FIRST, before anything reads `.band`. The
  // ranker is total and never returns one, but this runs on a network response
  // and a chip list that throws would stop a CP logging a day of work — the
  // one thing the whole sequence layer is written not to do.
  const notOther = (c) => c && typeof c === 'object' && c.id !== OTHER_CHIP_ID;
  const mine = (Array.isArray(chips) ? chips : []).filter(notOther);
  const filtered = Array.isArray(resolvedTrades) && resolvedTrades.length > 0;

  const suggested = mine.filter((c) => c.band === 'suggested');
  const tradeCatalog = filtered ? mine.filter((c) => c.band === 'catalog') : [];

  // COLD START is the ranker falling back to the project-start set because
  // there was no prior (or every prior was a rule miss). `prior_date` is the
  // day the suggestions came from, and its absence is the only honest signal —
  // counting chips would guess.
  const coldStart = !priorDate;

  let primary;
  let basis;
  if (suggested.length > 0) {
    // FOUR SLOTS, ALWAYS — including a cold start.
    //
    // This read `coldStart ? suggested : suggested.slice(0, CHIP_SLOTS)`, and
    // the ruling behind that was made when the band was RANKED and the fifth
    // chip was a real suggestion: dropping one of five would have been an
    // alphabetical accident rather than a judgement.
    //
    // A cold start is not that. It is the project-start set — five ids in
    // declaration order, encoding nothing about what this crew did yesterday —
    // so there is no ranking to respect and no fifth suggestion to protect.
    // The operator asked for four per contractor and reported "still too many"
    // across three rounds; four is the answer he gave, and the earlier ruling
    // is superseded rather than argued with.
    //
    // NOTHING IS HIDDEN by this, only folded: `rest` still holds the fifth and
    // the expander still reaches it, and "Other" is always there.
    primary = suggested.slice(0, CHIP_SLOTS);
    basis = coldStart ? 'cold_start' : 'sequence';
  } else if (tradeCatalog.length > 0) {
    primary = tradeCatalog.slice(0, CHIP_SLOTS);
    basis = 'trade';          // NOT ranked off yesterday, and the card says so
  } else {
    primary = [];
    basis = 'none';
  }

  const shown = new Set(primary.map((c) => c.id));
  // THE EXPANDER HOLDS THIS CREW'S REMAINING TRADE WORK, NOT THE CATALOGUE.
  //
  // It used to take the remainder from the UNFILTERED list, so with the chips
  // trade-filtered the expander dumped every other trade's activities into a
  // scaffolder's card. The operator's complaint was never the COUNT — twenty is
  // fine — it was the IRRELEVANCE: seventy-odd of the eighty-odd belonged to
  // somebody else, and a CP scanning for his own work had to sift them out.
  //
  // `mine` is already trade-filtered by the ranker, so the remainder is what is
  // left of THIS crew's trade after the four primaries.
  //
  // WHAT THIS PUTS OUT OF REACH, stated because it is the cost. A chip whose
  // trade is not this crew's is no longer reachable from this card. That is the
  // point of the change, and it is survivable for one reason: the OTHER chip is
  // rendered unconditionally, outside this expander, so a CP always has a
  // free-text path for work the taxonomy does not offer him. Without that
  // escape hatch this change would trade "buried" for "unrecordable", which is
  // the worse failure.
  //
  // UNFILTERED IS UNCHANGED. With no resolved trades `mine` IS everything, so a
  // crew whose trade nobody typed still sees the whole catalogue rather than an
  // empty expander.
  //
  // NO always_available EXCLUSION, still. The band is gone: the ranker stopped
  // special-casing those and they flow through suggested/catalog by trade like
  // every other activity, so filtering on the band here would hide a crew's own
  // work from its own expander.
  const rest = mine.filter((c) => !shown.has(c.id));

  return { primary, rest, basis, hidden: rest.length };
}

export default {
  rosterKey,
  isUnassignedCompany,
  isUnassignedTrade,
  cleanTrade,
  tradeLabel,
  NO_TRADE_LABEL,
  newActivityId,
  EMPTY_ACTIVITY,
  EMPTY_OBSERVATION,
  buildCrewsFromRoster,
  rosterIdIndex,
  parseInstant,
  composeSelection,
  cameraReady,
  resolveRosterId,
  isUnassignedWorkerRow,
  workRows,
  crewsWithoutWork,
  deriveGeneralDescription,
  OTHER_CHIP_ID,
  CHIP_SLOTS,
  composeChipBands,
  isUnboundCrew,
  observationComplete,
  incompleteObservations,
  INSPECTION_PASS,
  INSPECTION_FAIL,
  EMPTY_INSPECTION,
  OTHER_INSPECTION_KEY,
  isOtherInspection,
  inspectionRow,
  inspectionComplete,
  incompleteInspections,
  formatLogDate,
  formatCheckInTime,
  stepComplete,
};
