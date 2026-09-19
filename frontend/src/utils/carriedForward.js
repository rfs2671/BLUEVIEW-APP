/**
 * STORED DATA THE SCREEN NO LONGER COLLECTS, CARRIED THROUGH UNTOUCHED.
 *
 * A whole block or one key inside a block that is otherwise still written --
 * see "A BLOCK OR A KEY INSIDE ONE" at the foot of this note.
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
 * ── A BLOCK OR A KEY INSIDE ONE; THE RULE DOES NOT CARE ─────────────────────
 *
 * These two take `(object, key)` and `(key, value)`, so what they carry is
 * whatever the caller hands them. `progress` is a whole TOP-LEVEL block the
 * screen never writes, and `data` is the document. `daily_inspection.result` is
 * one uncollected key inside a block the screen DOES still write -- `location`
 * is collected and current -- and there the object handed in is the BLOCK and
 * the carried key rides back alongside the live one:
 *
 *     daily_inspection: {
 *       ...(location.trim() ? {location: location.trim()} : {}),
 *       ...writeCarried('result', carriedResult),
 *     }
 *
 * The present-or-absent rule is identical one level down, and so is the reason
 * for it: `_has_content` and `_cs_item_body` both walk `item["fields"]`, so a
 * `result` key that exists is a key the renderer reaches and the item-state
 * check counts. An invented `""` is still absence presented as an answer.
 *
 * TWO KEYS USE THIS TODAY: `progress` (item 2, a block) and
 * `daily_inspection.result` (item 11, a sub-key), both by operator ruling.
 * `cs_activities.locations` is also no longer written and is deliberately NOT
 * carried: `hydrate` folds its text into `summary` and writes it back there, so
 * nothing he wrote is lost and a carry would duplicate his own words onto the
 * record. See amendmentCarryForward.test.cjs for what each of the three
 * actually does, measured rather than assumed.
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
