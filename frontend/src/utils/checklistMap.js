/**
 * A SPARSE TOGGLE MAP — the shape five filed logbooks store a fixed checklist
 * in, and the one place the three states it can hold are decided.
 *
 * THE CONVENTION IS THE BACKEND'S, and it is already documented there:
 * backend/server.py:13029-13043 (toggle_map_rows) says it in as many words —
 * "the editors seed these maps as {} and write a key only once the CP taps it,
 * so `key present and False` is an explicit No while `key absent` is
 * untouched. An untouched item reads '— Not recorded', never a silent 'No'."
 * generate_combined_report follows the same rule for the same checklists
 * (:19575-19582, :19938-19945) and so does the kiosk inspector's ToggleTable.
 *
 * So a filed document distinguishes THREE things:
 *
 *   key absent   the CP never answered            "— Not recorded"
 *   key = false  the CP answered NO               "No"
 *   key = true   the CP answered YES              "Yes"
 *
 * THE DEVICE COULD NOT SAY WHICH. Every unported editor drew one dot per item
 * and toggled `!prev[key]`, so the FIRST tap wrote true and the SECOND wrote
 * false — and both false and absent drew the same empty dot. A CP who tapped an
 * item twice to undo it filed an explicit "No" on a DOB document believing he
 * had cleared it, and nothing on the screen could have told him otherwise.
 *
 * The ported forms answer with two chips over the printed column's own words,
 * and re-tapping the selected one returns the item to unrecorded — the state
 * the map starts in. The stored shape is unchanged: the same sparse map of
 * booleans every renderer already reads.
 */

/**
 * Answer one item. Re-answering with the SAME value clears it, because the
 * only way back to "not recorded" has to be reachable from the screen — the
 * state a form opens in must not be a state the CP can never return to.
 */
export function applyChecklistAnswer(map, key, value) {
  const src = (map && typeof map === 'object') ? map : {};
  const out = { ...src };
  if (Object.prototype.hasOwnProperty.call(out, key) && out[key] === value) {
    delete out[key];
  } else {
    out[key] = value;
  }
  return out;
}

/** How many of `items` the CP has ANSWERED — either way. */
export function recordedCount(map, items) {
  const m = (map && typeof map === 'object') ? map : {};
  return (items || []).filter(
    (it) => Object.prototype.hasOwnProperty.call(m, it.key) && typeof m[it.key] === 'boolean',
  ).length;
}

/** True once every item carries an answer. A NO is an answer. */
export function allRecorded(map, items) {
  return recordedCount(map, items) === (items || []).length;
}

export default {
  applyChecklistAnswer,
  recordedCount,
  allRecorded,
};
