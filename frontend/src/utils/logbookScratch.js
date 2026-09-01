/**
 * WHAT HE HAD TYPED, HELD ACROSS A TRIP TO ANOTHER SCREEN.
 *
 * ── WHY THIS EXISTS ─────────────────────────────────────────────────────────
 *
 * The ESRA consent became a first-class screen rather than a sheet, which
 * means a superintendent reaches it from the middle of an UNSAVED five-step
 * statutory log. The design rested on a claim about the navigator: that
 * expo-router's Stack keeps the screen beneath a `push` mounted, so
 * `router.back()` returns him to his entry intact.
 *
 * THAT CLAIM WAS NOT VERIFIED. Three attempts to drive the real router from a
 * headless harness were inconclusive — the first navigated the document
 * instead of the navigator, the next two failed to reach a control that
 * navigates at all. The app's own layout sets no `unmountOnBlur` and React
 * Navigation documents the behaviour, so the claim is probably true; "probably
 * true" is not the standard for whether a man loses a filled compliance log.
 *
 * So the design stops depending on it. The entry is stashed before navigating
 * and restored on mount. If the screen never unmounted, the stash is written
 * and never read, and nothing about the behaviour changes. If it did unmount,
 * his work comes back. It is correct under both answers, which is why it can
 * ship without the answer.
 *
 * ── IN MEMORY, DELIBERATELY ─────────────────────────────────────────────────
 *
 * A module-level Map, not AsyncStorage. This covers ONE case: a navigation
 * away and back inside a single run of the app. It is NOT offline draft
 * persistence, does not survive a reload or a kill, and must not be mistaken
 * for either — the local-first work (draftSync, logbookDrafts, markFinalized)
 * is a separate and larger change, and putting half of it here under another
 * name would make that change harder to reason about later.
 *
 * ── AND IT IS TAKEN, NOT READ ───────────────────────────────────────────────
 *
 * `take` clears the entry, so a stash can be restored exactly once. A stash
 * that lingered would resurrect abandoned edits onto a later visit — including
 * onto a document that has since been filed and frozen by someone else.
 */

const scratch = new Map();

/** A key that cannot collide across projects, dates or log types. */
export const scratchKey = (logType, projectId, date) => (
  `${String(logType || '')}:${String(projectId || '')}:${String(date || '')}`
);

/** Hold a snapshot. A nullish value clears rather than storing nothing. */
export function stash(key, value) {
  if (!key) return;
  if (value === undefined || value === null) { scratch.delete(key); return; }
  scratch.set(key, value);
}

/**
 * Take the snapshot back, removing it.
 *
 * Returns null when there is nothing held, which the caller must treat as
 * "no stash" and NOT as "an empty form" — restoring an empty object over a
 * loaded document would blank it.
 */
export function take(key) {
  if (!key || !scratch.has(key)) return null;
  const value = scratch.get(key);
  scratch.delete(key);
  return value;
}

/** Discard without reading — for a submit that succeeded. */
export function drop(key) {
  if (key) scratch.delete(key);
}

/** Test seam only: how many snapshots are held. */
export const size = () => scratch.size;

export default { scratchKey, stash, take, drop, size };
