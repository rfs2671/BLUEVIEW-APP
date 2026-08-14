/**
 * Re-check a stored roster against today's check-ins, on load.
 *
 * THE DEFECT THIS EXISTS TO STOP. Both roster forms read the local draft (or
 * the server copy) and RETURN before /checkins-today is ever called —
 * toolbox_talk.jsx:161 and :230, preshift_signin.jsx the same shape. So a
 * stored payload persisted unchecked: on project 6a5f63bc147407d3261df2c7 the
 * sign-in sheet and the toolbox roster both listed SIX workers on a day only
 * five men checked in. The sixth had been refused at the gate. A man on a
 * signed sign-in sheet who never checked in that day is a false record.
 *
 * ── HOW AN EDIT IS DETECTED, without an "edited" flag ────────────────────────
 *
 * The gate_sourced / company_gate pattern from dailyJobsiteModel.js:89,106:
 * record what the GATE said alongside the live value, and compare the two. No
 * flag to maintain, it survives a reload because both travel in the payload,
 * and it works on toolbox_talk where no provenance marker existed at all.
 *
 *   gate_sourced   true when this row was built from a check-in
 *   gate_snapshot  what the check-in said, at build time, for the fields the
 *                  CP can edit
 *
 * A field differing from its snapshot IS the proof of an edit. So is an answer
 * the gate never supplies — injury, PPE, the present tick — going from its
 * blank state to anything at all.
 *
 * ── THE FOUR RULES, as ruled ────────────────────────────────────────────────
 *
 *   DROP  an auto row with no check-in today AND no edit. That is the app's
 *         own stale data and nobody has vouched for it.
 *   KEEP  a hand-added row. The CP asserting a man was present is his call and
 *         the app must not overrule it.
 *   KEEP  an auto row the CP edited. The comparison is what proves it.
 *   ADD   anyone who checked in today and is not on the list.
 *
 * ── OLD PAYLOADS ────────────────────────────────────────────────────────────
 *
 * A record filed before this shipped carries NEITHER marker. It is treated as
 * CP-OWNED and always kept. That is the only safe default: absent evidence
 * that the app put a row there, deleting it could discard a man the CP added
 * by hand, and "never discard a CP edit" outranks staleness.
 *
 * NOTHING IS RE-HYDRATED. A kept row is returned exactly as stored, blank
 * columns and all. Re-filling Title/In/Confirmed from today's check-in would
 * be the app rewriting a filed record with data the CP never confirmed. Blank
 * is honest; new logs populate correctly and that is the fix.
 */

/** Normalised identity for matching a stored row to a check-in. */
export function rowKey(row) {
  if (!row || typeof row !== 'object') return '';
  const id = row.worker_id;
  if (id !== null && id !== undefined && String(id).trim() !== '') {
    return `id:${String(id).trim()}`;
  }
  // No id — fall back to the name. Weaker, and deliberately last: two men can
  // share a name (osha_log had to allow exactly that), so this only ever runs
  // for a row the gate could not identify.
  const name = String(row.name || '').trim().toLowerCase().replace(/\s+/g, ' ');
  return name ? `name:${name}` : '';
}

/**
 * Stamp a freshly built auto row with what the gate said.
 * `fields` are the CP-editable fields worth comparing later.
 */
export function withGateSnapshot(row, fields) {
  const snapshot = {};
  for (const f of fields) snapshot[f] = row[f] ?? null;
  return { ...row, gate_sourced: true, gate_snapshot: snapshot };
}

/**
 * Has the CP touched this row?
 *
 * `fields`  compared against the snapshot.
 * `answers` fields the gate NEVER supplies — an injury answer, a PPE answer, a
 *           present tick. Any of them carrying a value is an edit on its own,
 *           because only the CP could have put it there.
 */
export function isCpEdited(row, fields, answers = []) {
  if (!row || typeof row !== 'object') return false;
  // No provenance at all → treat as the CP's. See OLD PAYLOADS above.
  if (row.gate_sourced !== true) return true;
  const snap = row.gate_snapshot;
  if (!snap || typeof snap !== 'object') return true;
  for (const f of fields) {
    const now = row[f] ?? null;
    const then = snap[f] ?? null;
    if (String(now ?? '') !== String(then ?? '')) return true;
  }
  for (const a of answers) {
    const v = row[a];
    if (v !== null && v !== undefined && v !== false && v !== '') return true;
  }
  return false;
}

/**
 * The reconcile itself. Pure: it decides, it does not fetch.
 *
 *   stored    the rows in the payload/draft
 *   fresh     rows built from today's check-ins, already gate-stamped
 *   fields    CP-editable fields to compare against the snapshot
 *   answers   fields only the CP can supply
 *
 * Returns { rows, dropped, added, kept } — the counts are for the caller to
 * tell the CP what changed, because a roster that silently rewrites itself is
 * the same class of problem as one that never updates.
 */
export function reconcileRoster({ stored, fresh, fields, answers = [] }) {
  const storedRows = Array.isArray(stored) ? stored : [];
  const freshRows = Array.isArray(fresh) ? fresh : [];

  const freshByKey = new Map();
  for (const r of freshRows) {
    const k = rowKey(r);
    if (k && !freshByKey.has(k)) freshByKey.set(k, r);
  }

  const rows = [];
  const seen = new Set();
  let dropped = 0;

  for (const row of storedRows) {
    const k = rowKey(row);
    const checkedInToday = k ? freshByKey.has(k) : false;
    const edited = isCpEdited(row, fields, answers);

    if (checkedInToday || edited) {
      // KEPT AS STORED. No re-hydrate — see the module note.
      rows.push(row);
      if (k) seen.add(k);
    } else {
      dropped += 1;
    }
  }

  let added = 0;
  for (const r of freshRows) {
    const k = rowKey(r);
    if (k && seen.has(k)) continue;
    rows.push(r);
    if (k) seen.add(k);
    added += 1;
  }

  return { rows, dropped, added, kept: rows.length - added };
}

export default { rowKey, withGateSnapshot, isCpEdited, reconcileRoster };
