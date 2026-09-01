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
export const GATE_SOURCE = 'gate';
export const CP_SOURCE = 'cp';

/**
 * Who supplied the headcount standing on this row.
 *
 * ABSENCE MEANS GATE, DELIBERATELY. Drafts written before this field existed
 * carry no marker, and every one of them holds a number that came from the
 * roster or from commitAddCrew. Reading a missing marker as 'cp' would label
 * historical rows as hand-typed on a record somebody signs.
 */
export const headcountSource = (activity) => (
  activity?.num_workers_source === CP_SOURCE ? CP_SOURCE : GATE_SOURCE
);

/**
 * A CP number standing OVER a gate count. This is what the reconcile has to
 * check: without it, reconcileCrewsWithRoster refreshes num_workers from the
 * roster on every load and the correction the CP typed is silently reverted the
 * next time he opens the screen -- a control that appears to work and does not.
 *
 * A hand-added crew is NOT an override. Its number is the CP's own assertion
 * with nothing to stand over, and the reconcile never touches those rows.
 */
export const isHeadcountOverridden = (activity) => Boolean(
  activity?.gate_sourced && headcountSource(activity) === CP_SOURCE,
);

/** The gate's own count, retained even when the CP has overridden it. */
export const gateHeadcount = (activity) => {
  const raw = String(activity?.gate_num_workers ?? '').trim();
  if (raw === '') return null;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : null;
};

/**
 * Apply a typed headcount to a crew row and return the fields that change.
 *
 * CLEARING THE BOX ON A GATE ROW WITHDRAWS THE OVERRIDE rather than asserting
 * an empty count. '' means "nobody counted" everywhere else in this file, and
 * on a crew the turnstile DID count that would be false -- so the row goes back
 * to tracking the gate, which is the state it would have had if he had never
 * typed. On a hand-added row a blank is the honest answer and stays blank,
 * matching commitAddCrew.
 *
 * A NON-NUMERIC ENTRY CHANGES NOTHING. Returning a partial patch for garbage
 * would let a stray keystroke overwrite a real count.
 */
/**
 * The headcount AS IT SHOULD BE READ ON A FILED RECORD — the number, and who
 * supplied it.
 *
 * Mirrors server.py `_headcount_cell`, deliberately: the same row is printed by
 * four surfaces (the combined report, the per-logbook PDF, this app, and the
 * gate tablet an inspector reads from), and a headcount that is attributed on
 * one of them and bare on another is worse than one that is bare everywhere.
 *
 * ABSENCE MEANS GATE, for the same reason it does everywhere else in this file:
 * rows written before num_workers_source existed hold roster numbers, and
 * labelling those "(CP)" would be a false attribution on an already-filed log.
 */
export function headcountDisplay(activity, blank = '') {
  const text = String(activity?.num_workers ?? '').trim();
  if (text === '') return blank;
  if (headcountSource(activity) !== CP_SOURCE) return text;
  const gate = String(activity?.gate_num_workers ?? '').trim();
  // A hand-added crew has no gate count to cite; it is still the CP's number.
  if (gate === '') return `${text} (CP)`;
  return `${text} (CP) - gate recorded ${gate}`;
}

/**
 * Named men recorded on this row. The gate writes these; nothing else does.
 */
export const crewWorkerIdentities = (activity) => {
  const ids = Array.isArray(activity?.worker_ids) ? activity.worker_ids : [];
  const names = Array.isArray(activity?.worker_names) ? activity.worker_names : [];
  return ids.length + names.length;
};

/**
 * Whether this crew card may be REMOVED from the log.
 *
 * THE TEST IS ABSENT WORKER IDENTITIES, NOT THE gate_sourced FLAG, and the
 * difference is the reason rather than a detail. A row carrying worker_ids or
 * worker_names represents named men who tapped a turnstile; removing it takes
 * them off a filed 3301.2 record with no trace, and no confirmation dialog
 * makes that acceptable. A hand-added row is the CP's own assertion with nobody
 * behind it, so deleting it retracts a statement rather than erasing a person.
 *
 * Reading identities rather than the flag means a row whose gate_sourced was
 * lost in a round-trip is still protected, and a hand-added row that somehow
 * acquired the flag is still removable. The flag describes provenance; this
 * question is about people.
 *
 * A DELETED GATE ROW WOULD COME BACK ANYWAY. reconcileCrewsWithRoster
 * re-appends every fresh crew it did not match, so removing one would need a
 * persistent tombstone -- and a tombstone is itself a record that men were
 * suppressed, which is worse than leaving the row at 0 and letting him say why.
 * #244 already settled that disposition: an absent gate crew drops to 0 and
 * stays visible.
 */
export const isDeletableCrew = (activity) => Boolean(activity)
  && !isUnassignedWorkerRow(activity)
  && crewWorkerIdentities(activity) === 0;

/**
 * What deleting this card actually DOES, as facts the screen turns into a
 * sentence.
 *
 * WHY THIS IS NOT "ARE YOU SURE". The duplicate #244 deliberately creates has
 * the CP's description on one row and the gate's men on the other. Deleting the
 * described row leaves a crew with six workers and no work recorded, which puts
 * it straight back into crewsWithoutWork and re-disables Next -- he taps
 * through a bland confirmation and discovers the consequence two steps later at
 * a control that will not advance. The dialog has to say that before he taps,
 * not after.
 *
 * `stranded` is the sibling that would be left holding men and no work. Matched
 * on COMPANY ALONE and deliberately: the duplicate exists precisely because the
 * two rows disagree about the trade -- the hand-added one usually has none --
 * so keying on (company, trade) would find nothing in the one case this is for.
 */
export function crewDeleteImpact(activities, index) {
  const rows = Array.isArray(activities) ? activities : [];
  const row = rows[index];
  if (!row) return null;

  const described = String(row.work_description || '').trim() !== '';
  const company = rosterKey(row.company);

  let stranded = null;
  if (described && company) {
    for (let i = 0; i < rows.length; i += 1) {
      if (i === index) continue;
      const other = rows[i];
      if (isUnassignedWorkerRow(other)) continue;
      if (rosterKey(other.company) !== company) continue;
      if (String(other.work_description || '').trim() !== '') continue;
      const n = crewHeadcount(other);
      if (n === null || n === 0) continue;
      stranded = { company: other.company, workers: n };
      break;
    }
  }

  return {
    deletable: isDeletableCrew(row),
    hasDescription: described,
    stranded,
    // The log does not end up empty. reconcileCrewsWithRoster returns the whole
    // fresh roster when nothing is stored, so a CP who deletes down to a blank
    // screen and reopens to a full one would think the app lost his work.
    isLastRow: workRows(rows).length === 1,
  };
}

export function applyHeadcountEdit(activity, raw) {
  const text = String(raw ?? '').trim();

  if (text === '') {
    if (activity?.gate_sourced) {
      const gate = String(activity?.gate_num_workers ?? '').trim();
      return { num_workers: gate === '' ? '0' : gate, num_workers_source: GATE_SOURCE };
    }
    return { num_workers: '', num_workers_source: GATE_SOURCE };
  }

  if (!/^\d+$/.test(text)) return {};
  const n = parseInt(text, 10);
  if (!Number.isFinite(n)) return {};
  return { num_workers: String(n), num_workers_source: CP_SOURCE };
}

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
  //
  // gate_num_workers IS THE GATE'S OWN COUNT, KEPT SEPARATELY FROM THE MOMENT
  // THE ROW IS BORN. num_workers is what the log prints and what the step gate
  // reads, and the CP can now correct it; if his correction simply replaced the
  // turnstile's number the override would be unauditable, and a signed 3301.2
  // record could not show that a person had changed a gate count.
  all.forEach((r, i) => {
    r.crew_id = `C${i + 1}`;
    r.gate_num_workers = r.num_workers;
    r.num_workers_source = GATE_SOURCE;
  });
  return all;
}

/**
 * Bring a STORED crew list back into line with today's gate roster.
 *
 * THE GAP THIS CLOSES. Crews were rebuilt from the roster only when the stored
 * list was EMPTY (daily_jobsite.jsx, both load branches). That fix was right
 * and is untouched — an autosaved `activities: []` used to make the roster
 * unrecoverable. But nothing ever reconciled a NON-empty list, so the moment
 * one crew existed the log stopped listening to the gate for the rest of the
 * day. Two failures come out of that, and the second is worse than the first:
 *
 *   * a crew on the card that is no longer on the roster keeps its original
 *     headcount forever — the reported defect; and
 *   * A CREW THAT ARRIVED AFTER THE DRAFT WAS OPENED NEVER APPEARS AT ALL.
 *     A CP who opens the log at 07:00 and signs at 16:00 files a §3301.2
 *     record that omits every sub who arrived at 09:00. A missing crew on a
 *     signed record is not visible to anyone reading it.
 *
 * WHAT IT MAY TOUCH, and the rule is provenance:
 *
 *   GATE-SOURCED ROWS  are the gate's facts, so the gate's facts are refreshed:
 *                      headcount, worker ids and names, first check-in. Never
 *                      the work description, the locations or the photos —
 *                      those are the CP's and this must not be able to eat
 *                      them. A gate row with no matching crew today drops to a
 *                      headcount of 0 rather than being deleted, because
 *                      deleting it would take anything he had already written
 *                      with it.
 *
 *   HAND-ADDED ROWS    are the CP asserting a crew the gate missed. They are
 *                      returned untouched. This is exactly why a reconciliation
 *                      cannot fix the reported defect on its own: the manually
 *                      added zero is not the gate's to correct.
 *
 *   LOOSE ROWS         (a worker with no company) carry no CP content — they
 *                      render no card and there is nothing to fill in on them
 *                      — so they are replaced wholesale from today's roster.
 *
 * An empty stored list still returns the freshly built one, so the existing
 * rebuild keeps working through this function rather than around it.
 */
export function reconcileCrewsWithRoster(stored, fresh) {
  const storedRows = Array.isArray(stored) ? stored : [];
  const freshRows = Array.isArray(fresh) ? fresh : [];
  if (storedRows.length === 0) return freshRows;

  const keyOf = (r) => `${rosterKey(r?.company)}|${rosterKey(r?.trade)}`;

  const freshCrews = new Map();
  for (const f of freshRows) {
    if (!isUnassignedWorkerRow(f)) freshCrews.set(keyOf(f), f);
  }

  // A TRADE BEING RESOLVED IS NOT A DIFFERENT CREW.
  //
  // The key is (company, trade), so the moment a crew's trade stops being blank
  // — an admin fixing worker_project_trades, or a CP using
  // POST /checkins/{id}/assign-trade, both of which change what the roster
  // returns — the stored row stopped matching, dropped to a headcount of 0,
  // and the SAME crew was appended again beside it. Arkon Builders twice: one
  // row holding the CP's description with nobody on it, one row with six men
  // and nothing written. Both print.
  //
  // So a stored gate row with NO trade may also match on the company alone,
  // and adopts the trade the roster has now resolved.
  //
  // ONLY WHEN IT IS UNAMBIGUOUS. One company can legitimately field two crews
  // in different trades (Arkon framing and Arkon concrete); guessing which one
  // an untraded row meant would put a description against the wrong trade on a
  // signed record. With more than one candidate the row is left alone and
  // reads zero, which is visible and wrong in the safe direction.
  const freshByCompany = new Map();
  for (const f of freshRows) {
    if (isUnassignedWorkerRow(f)) continue;
    const c = rosterKey(f.company);
    freshByCompany.set(c, (freshByCompany.get(c) || []).concat(f));
  }

  const matched = new Set();
  const out = [];
  for (const row of storedRows) {
    if (isUnassignedWorkerRow(row)) continue;      // replaced below
    // EVERY row reaches the matcher, whatever its origin. This is where a
    // hand-added row used to be short-circuited out with "the CP's,
    // untouched" -- so it could never match a gate crew, `matched` never
    // gained that crew's key, and the append tail below added the gate's men
    // as a SECOND row for a company already on the log. On 2026-08-31 that
    // filed eight crews where four worked. It fires every morning a CP starts
    // his log before the men badge in.
    //
    // A gate crew confirming a company the CP already typed is CONFIRMATION,
    // not a second crew. The short-circuit still exists -- it MOVED to the
    // no-match case below, where it is the difference between leaving a crew
    // the gate never saw alone and emptying it.
    let f = freshCrews.get(keyOf(row));
    if (!f && !rosterKey(row.trade)) {
      const candidates = (freshByCompany.get(rosterKey(row.company)) || [])
        .filter((c) => !matched.has(keyOf(c)));
      if (candidates.length === 1) f = candidates[0];
    }
    if (f) {
      matched.add(keyOf(f));
      // THE OVERRIDE SURVIVES THE RECONCILE, AND THE GATE'S NUMBER SURVIVES THE
      // OVERRIDE. This function runs on EVERY load, so before this branch knew
      // about num_workers_source a corrected headcount was overwritten from the
      // roster the next time the screen opened -- the CP would have watched his
      // own correction disappear with no trace, which is the "form he already
      // filled asking again" failure recorded on the scaffold prefill.
      //
      // gate_num_workers is refreshed either way. It is evidence, not display:
      // the filed record has to be able to say 4 (CP) alongside what the
      // turnstile actually counted, and that is only possible if the gate's
      // number keeps tracking the gate while the printed one does not.
      //
      // WHICH NUMBER SURVIVES A MERGE. isHeadcountOverridden requires
      // gate_sourced, so it answers false for a hand-added row no matter what
      // the CP typed -- reading it alone would let the gate silently overwrite
      // a count he asserted, which is #244's own objection pointed the other
      // way. A hand row that carries a number carries the CP's number; a blank
      // one carries nobody's, so the gate's stands. Either way the gate's
      // count is recorded in gate_num_workers and the source is named, which
      // is what #244 wanted and what it built a second row to get.
      // WHO SAYS SO. "A number exists" is not "somebody asserted it", and
      // reading the first as the second is how the app ends up speaking for
      // the CP on a document he signs.
      //
      // The predicate here was `String(row.num_workers).trim() !== ''`, which
      // stamped num_workers_source 'cp' onto ANY row carrying a count. Rows
      // seeded from the gate before 2026-08-10 carry the TURNSTILE's number
      // and no gate_sourced flag (the flag did not exist yet), and
      // num_workers_source did not exist either until 2026-08-27 -- so the
      // rule relabelled the gate's own count as the CP's assertion. On
      // 2026-08-31 that would have printed "(CP)" against three crews whose
      // numbers he never typed.
      //
      // THREE STATES:
      //   cp     an explicit prior assertion -- kept, and labelled his
      //   unset  a number with NO recorded author -- kept, labelled NEITHER.
      //          _headcount_cell prints it bare, which is the honest reading:
      //          the number stands, nobody is credited with it.
      //   gate   adopted from the crew just matched -- we know its origin
      const _wasGate = row.gate_sourced === true;
      const _asserted = row.num_workers_source === CP_SOURCE;
      const _hasNumber = String(row.num_workers ?? '').trim() !== '';
      const _keepHis = _asserted || (!_wasGate && _hasNumber);
      const _unattributed = _keepHis && !_asserted;
      out.push({
        ...row,
        // CONFIRMED BY THE GATE, and it must say so: the flag is what makes
        // isHeadcountOverridden work on the next load, so a CP correction on
        // this row survives every later reconcile.
        //
        // WITHHELD FOR AN UNATTRIBUTED NUMBER, deliberately. Setting it would
        // make this row indistinguishable from a pre-2026-08-27 GATE row --
        // both flagged, both sourceless -- and the next reconcile would then
        // adopt the gate's count over a number we chose to preserve precisely
        // because we do not know whose it is. Leaving the flag off keeps the
        // two apart and makes the state stable across every later pass.
        gate_sourced: _unattributed ? row.gate_sourced : true,
        // The roster's trade wins when this row had none — that is the whole
        // point of the company-only match above. A row that already had one
        // keeps it (keyOf matched, so they are equal anyway).
        trade: row.trade || f.trade,
        num_workers: _keepHis ? row.num_workers : f.num_workers,
        // undefined, not a sentinel: the key is simply absent, which is what
        // commitAddCrew already writes for an untyped count and what
        // _headcount_cell already reads as "no attribution".
        num_workers_source: _asserted
          ? CP_SOURCE
          : (_unattributed ? undefined : GATE_SOURCE),
        gate_num_workers: f.num_workers,
        // WORKER IDENTITIES ARE GATE FACTS AND ARE NEVER OVERRIDDEN. The CP
        // corrects a COUNT; he does not add or remove named men, and PR 2's
        // delete refusal reads these to decide whether a row represents real
        // people.
        worker_ids: f.worker_ids,
        worker_names: f.worker_names,
        check_in_time: f.check_in_time,
        // Only fill a missing binding; never replace one the row already has.
        subcontractor_id: row.subcontractor_id || f.subcontractor_id || null,
      });
    } else if (!row.gate_sourced) {
      // NO MATCH, AND THIS ROW NEVER CAME FROM THE GATE. Untouched -- the CP
      // typed a crew the turnstile has not seen, which is not evidence that
      // nobody is there.
      //
      // THIS IS THE HALF THAT LOOKS DELETABLE AND IS NOT. Drop it and an
      // unmatched hand row falls into the branch below, which writes
      // num_workers '0' and empties worker_ids/worker_names -- because
      // isHeadcountOverridden returns false for a row with no gate_sourced.
      // That would erase a headcount the CP asserted, on a record he signs.
      // crewReconcileMerge.test.cjs asserts this case by name.
      out.push(row);
    } else {
      // Absent from today's roster. The gate's count for this crew is now zero
      // and is recorded as such; a CP override still stands over it, because
      // "the gate saw nobody but I say four were here" is exactly the
      // correction this feature exists to allow.
      const _overridden = isHeadcountOverridden(row);
      out.push({
        ...row,
        num_workers: _overridden ? row.num_workers : '0',
        num_workers_source: _overridden ? CP_SOURCE : GATE_SOURCE,
        gate_num_workers: '0',
        worker_ids: [],
        worker_names: [],
      });
    }
  }

  // Crews that came through the gate after this list was built.
  //
  // APPENDED EVEN WHEN THE CP ALREADY ADDED THAT COMPANY BY HAND. Two rows for
  // one sub is visible on the screen and correctable; silently folding the
  // gate's men into a hand-typed row would drop them from the headcount, and
  // nobody reading the filed log could tell.
  //
  // crew_id counts from the highest one already present rather than from the
  // list length: it is the PDF's first column and an existing row's id must
  // never be reused by a different crew.
  let seq = 0;
  for (const r of out) {
    const n = parseInt(String(r.crew_id || '').replace(/^C/, ''), 10);
    if (Number.isFinite(n) && n > seq) seq = n;
  }
  for (const f of freshRows) {
    if (isUnassignedWorkerRow(f) || matched.has(keyOf(f))) continue;
    seq += 1;
    out.push({ ...f, crew_id: `C${seq}` });
  }

  return [...out, ...freshRows.filter(isUnassignedWorkerRow)];
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

/** The rows that RENDER a crew card on Step 2. */
export const workRows = (activities) => (Array.isArray(activities) ? activities : [])
  .filter((a) => !isUnassignedWorkerRow(a));

/**
 * Workers recorded on one crew row. `''` and `'0'` both read as none.
 *
 * `num_workers` is a STRING on the row because both PDF renderers print it
 * verbatim, so every reader has to parse it and every reader was parsing it
 * differently — the two card headers already do `parseInt(...) || 0` inline.
 * One function, so "how many men" cannot be answered two ways.
 */
export const crewHeadcount = (activity) => {
  const raw = String(activity?.num_workers ?? '').trim();
  if (raw === '') return null;                 // never counted — see below
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : null;
};

/**
 * A crew AFFIRMATIVELY RECORDED AS HAVING NOBODY ON IT. The rule, from the
 * operator: a crew that was not on site has nothing to describe.
 *
 * ZERO IS NOT BLANK, AND THE DIFFERENCE IS THE WHOLE POINT.
 *
 *   '0'  something said NOBODY. Either the CP typed it, or — far more often —
 *        `commitAddCrew` manufactured it out of an untyped count
 *        (`String(parseInt('') || 0)`), or the roster reconciliation found no
 *        crew under that key today. All three are evidence of absence.
 *   ''   nobody ever counted. That is not evidence of ANYTHING, so the log
 *        keeps asking. A gate-sourced row can never hold it (buildCrewsFromRoster
 *        increments from the first worker, so a crew that exists has ≥ 1), and
 *        commitAddCrew no longer mints it as a zero.
 *
 * Reading a blank as "nobody" would be the more convenient rule and the wrong
 * one: it would silently stop demanding work from a crew that WAS on site
 * whenever a count went unrecorded, and a §3301.2 log that omits a present
 * crew's work is exactly the failure this file exists to prevent — invisible
 * to whoever reads the filed record.
 *
 * THIS IS NOT A DELETION AND NOT A HIDE. The row still renders, still prints,
 * and still carries anything the CP wrote on it. All that changes is that the
 * log stops DEMANDING an activity and a location for men who were not here.
 */
export const hasNoWorkersOnSite = (activity) => crewHeadcount(activity) === 0;

/**
 * The rows the log actually demands work from — rendered crew cards, minus
 * the ones with nobody on them.
 *
 * SEPARATE FROM workRows ON PURPOSE. workRows answers "what is on screen" and
 * is what loadChips keys on; this answers "what must be filled in". Collapsing
 * them would stop fetching chips for a zero-worker crew, so the moment the CP
 * corrected its headcount he would face a card with no chips on it.
 */
export const describableRows = (activities) => workRows(activities)
  .filter((a) => !hasNoWorkersOnSite(a));

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
    // NOTHING TO DESCRIBE. A crew with no workers recorded was not on site, so
    // the log stops asking it for an activity and a location.
    //
    // FILTERED HERE, AFTER THE INDEX IS TAKEN, AND NOT IN THE SOURCE LIST.
    // `row`/`total` are a position on the screen — "Crew 3 of 5" is how the CP
    // finds the card — so they have to count the rendered rows. Filtering
    // before the index would renumber every crew below an empty one and point
    // him at the wrong card, which is the same defect the comment below
    // records for the unassigned-worker rows.
    .filter(({ a }) => !hasNoWorkersOnSite(a))
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
      // describableRows, NOT workRows: a crew with nobody on it is not asked
      // for a description, so it must not be able to hold the pip incomplete
      // either. The pip and the Next gate read the same set or the CP is
      // stopped by something the screen says is finished.
      const work = describableRows(acts);
      // `work.length > 0` STAYS. A day on which no crew's work is described is
      // not a completed Step 2, and that ruling is not this change's to
      // overturn — it is asserted directly in dailyJobsiteModel.test.cjs for
      // the unassigned-worker case. All that moves here is WHICH rows count as
      // askable, so an empty crew can no longer hold the pip incomplete.
      //
      // This marker is advisory: only crewsWithoutWork disables Next
      // (daily_jobsite.jsx nextDisabled). The two read the same set so they
      // cannot disagree, which is the property the comment above was added for.
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
  GATE_SOURCE,
  CP_SOURCE,
  headcountSource,
  isHeadcountOverridden,
  gateHeadcount,
  headcountDisplay,
  applyHeadcountEdit,
  crewWorkerIdentities,
  isDeletableCrew,
  crewDeleteImpact,
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
