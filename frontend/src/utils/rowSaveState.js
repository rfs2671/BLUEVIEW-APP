/**
 * WHICH ROWS ARE NOT YET ON DISK.
 *
 * Ruled: a screen-level "Saving…" is decoration; per-row is a fact about that
 * row. The problem is that `writeDraft` persists the WHOLE payload in one
 * AsyncStorage write, so there is no per-row persistence to report. A naive
 * per-row spinner would be the screen-level indicator drawn N times — the same
 * decoration, multiplied.
 *
 * There IS a genuine per-row fact, and this computes it: **has this row changed
 * since the last write that actually landed?** Rows that match the last
 * persisted snapshot are on disk. Rows that differ, or that did not exist in
 * it, are not. That is true per row, it is derived rather than asserted, and it
 * is exactly what a CP filling a sign-in sheet wants to know about the man in
 * front of him.
 *
 * WHAT IT IS NOT. Not a spinner and not a progress bar. A row is either on disk
 * or it is not; the in-flight moment is a few milliseconds of an AsyncStorage
 * write and showing it would train the eye to ignore the marker. Callers render
 * only the negative state.
 *
 * THE SNAPSHOT MUST COME FROM A CONFIRMED WRITE. `writeDraft` returns false and
 * never throws, so a caller that snapshots optimistically — before or without
 * checking the result — would mark every row saved on a device that is storing
 * nothing. Snapshot only where the boolean came back true. That is the whole
 * correctness condition and it is asserted in rowSaveState.test.cjs.
 */

/**
 * Stable identity for a row, for the purpose of "is this the same row".
 *
 * Index is NOT identity: rows are inserted, removed and reordered, and a
 * positional key stops naming the same row the moment they are. Prefer a
 * client-minted id where the model has one; fall back to the index so a model
 * without ids still gets a usable (if reorder-sensitive) answer rather than
 * nothing.
 */
export function rowKey(row, index) {
  if (row && typeof row === 'object') {
    const id = row.id ?? row._local_id ?? row.activity_id ?? row.worker_id;
    if (id !== undefined && id !== null && String(id) !== '') return `id:${id}`;
  }
  return `i:${index}`;
}

/**
 * Deterministic value for one row.
 *
 * JSON.stringify is key-order sensitive, and React state updates routinely
 * rebuild an object with a different insertion order while changing nothing a
 * user typed. Sorting the keys means a spread that reorders fields does not
 * report the row as unsaved.
 */
function stable(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value ?? null);
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
}

/** A snapshot to hold after a write that RETURNED TRUE. */
export function snapshotRows(rows) {
  const out = new Map();
  (Array.isArray(rows) ? rows : []).forEach((r, i) => out.set(rowKey(r, i), stable(r)));
  return out;
}

/**
 * The keys of rows that are not in `snapshot` as they currently stand.
 *
 * A null/absent snapshot means nothing has been persisted yet in this session,
 * which is NOT the same as every row being unsaved: a draft loaded from disk at
 * mount is already on disk. Callers seed the snapshot at load for that reason,
 * and a missing snapshot here returns an empty set rather than lighting up
 * every row on a freshly opened form.
 */
export function unsavedRowKeys(rows, snapshot) {
  const out = new Set();
  if (!snapshot) return out;
  (Array.isArray(rows) ? rows : []).forEach((r, i) => {
    const k = rowKey(r, i);
    if (snapshot.get(k) !== stable(r)) out.add(k);
  });
  return out;
}
