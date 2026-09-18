/**
 * A STORED BLOCK THE SCREEN NO LONGER COLLECTS, CARRIED THROUGH UNTOUCHED.
 *
 * ── THE PATH THIS EXISTS FOR ────────────────────────────────────────────────
 *
 * `amend_logbook` seeds the correction with the parent's own data:
 *
 *     "data": (data or {}).get("data", original.get("data"))
 *
 * so the child opens holding everything the filed parent held. The editor then
 * loads that child, and its first autosave PUTs `buildData()` over `data`
 * WHOLESALE -- `update_logbook` writes `"data": data.data`, it does not merge.
 *
 * WHICH MAKES "no longer written" MEAN TWO DIFFERENT THINGS. On a NEW log it
 * means the field is not collected, which is the intent. On an AMENDMENT it
 * means the field is DELETED from a record that already had it -- and the
 * parent is a separate document, so the six sheets already filed are safe,
 * while the amended sheet would print "-- Not recorded" against a required BC
 * 3301.13.13 item. Nobody decided that; it fell out of the shapes.
 *
 * ── WHAT THIS IS, AND WHAT IT IS EMPHATICALLY NOT ───────────────────────────
 *
 * Read it, keep it, write it back. NOT rendered, NOT offered, NOT autofilled,
 * NOT editable. The input is gone and stays gone; only the stored bytes make
 * the round trip. A carried block is the previous author's statement, not a
 * new one by whoever is amending -- which is exactly why it must not appear in
 * a box over his signature, and exactly why it must not vanish either.
 *
 * ── THE WHOLE BLOCK, NOT THE FIELD THAT LOOKS IMPORTANT ─────────────────────
 *
 * Item 2 stores `{summary, source}`. `source` is the provenance flag the sheet
 * prints its "Adopted from the competent person" line from, and it CANNOT be
 * re-derived after the fact -- `item_provenance`'s docstring refuses to, because
 * the CP's log can be amended afterwards and the flag has to mean what was true
 * at filing. Carrying `summary` while dropping `source` would reprint his text
 * under the wrong attribution, which is worse than carrying neither.
 *
 * ── PRESENT-OR-ABSENT, NEVER "EMPTY" ────────────────────────────────────────
 *
 * A record that never had the key must not acquire one. `{}` and a missing key
 * are different documents to the renderer, and writing `{}` where there was
 * nothing is the "absence read as a claim" shape this log has already been bitten
 * by more than once. So: own property present -> carry the exact value; absent
 * -> write nothing at all.
 *
 * ── AND NOTHING IS NORMALISED ───────────────────────────────────────────────
 *
 * No trim, no defaulting, no re-derivation, no copy that could reorder keys.
 * The value that came out of storage is the value that goes back in. A record
 * whose appearance changed after it was signed is the thing being prevented.
 *
 * ONE KEY USES THIS TODAY: `progress`, item 2. `cs_activities.locations` and
 * `daily_inspection.result` are also no longer written, and whether they should
 * be carried the same way is a SEPARATE RULING -- see
 * amendmentCarryForward.test.cjs for what each of them actually does today,
 * measured rather than assumed.
 */

/**
 * The stored value for `key`, exactly as stored, or `undefined` when the record
 * does not carry that key at all.
 *
 * `undefined` IS THE ABSENCE SIGNAL and it is safe as one: this data arrives by
 * JSON, which has no `undefined`, so the only way to read one back is for the
 * key to be missing. A stored `null` is a value and is carried as a value.
 */
export function readCarried(data, key) {
  if (!data || typeof data !== 'object') return undefined;
  if (!Object.prototype.hasOwnProperty.call(data, key)) return undefined;
  return data[key];
}

/**
 * Spread into the payload: `{ ...writeCarried('progress', carriedProgress) }`.
 *
 * Returns an EMPTY OBJECT when nothing was carried, so the spread contributes
 * no key at all -- rather than `{progress: undefined}`, which `JSON.stringify`
 * drops on the wire but which reads as a present-but-empty answer to anything
 * inspecting the object before it is serialised.
 */
export function writeCarried(key, carried) {
  return carried === undefined ? {} : { [key]: carried };
}
