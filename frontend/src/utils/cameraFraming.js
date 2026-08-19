/**
 * RE-ASSERTING THE FRAMING WHEN THE SESSION STARTS.
 *
 * THE DEFECT, confirmed on device across two predictions rather than reasoned
 * from source — four earlier diagnoses were reasoned from source and all four
 * were wrong.
 *
 * The camera is PRE-WARMED: the <Camera> is mounted for the lifetime of the
 * screen and merely hidden, and `isActive` is what starts the session. So:
 *
 *   T1  devices resolve, the framing effect runs, `zoom` becomes 0.508, and
 *       React writes that prop TO A SESSION THAT IS NOT RUNNING
 *   T2  he opens the camera, `isActive` flips true, and the session starts at
 *       the hardware default of 1.0
 *   T3  nothing re-runs. `zoom` is STILL 0.508 — unchanged — so React sends no
 *       prop update, and the native view only pushes zoom on a prop CHANGE
 *
 * The value was never wrong and never rejected. It was written once, too early,
 * and the session that later started was never told.
 *
 *   PREDICTION 1  flip to front and back: `position` changes, the effect
 *                 re-runs, the prop CHANGES on a running session -> ultra-wide.
 *                 CONFIRMED.
 *   PREDICTION 2  pinch to 3x, close, reopen: opens at 1x while the state still
 *                 reads 3. CONFIRMED — and it has nothing to do with ultra-wide,
 *                 which is what makes it a clean test of the mechanism rather
 *                 than a restatement of the symptom.
 *
 * Prediction 2 is also why the re-apply must send THE CURRENT ZOOM rather than
 * minZoom. A CP who pinched to 3x and reopened should get 3x back. The session
 * is not being told the value; the value is not wrong.
 */

/**
 * A value next to `target` that React will commit as a CHANGED prop.
 *
 * WHY A NUDGE AT ALL. v4.7.3 has no imperative zoom — `takePhoto`, `focus`,
 * the recording methods, and nothing else. The prop is the only channel to the
 * native session, and React does not write a prop whose value has not changed.
 * Re-sending the same number is therefore a no-op, which is exactly the state
 * the camera is already stuck in. So the re-apply moves one step off the target
 * for a single frame and then lands on it, and both writes are real pushes.
 *
 * The step is a thousandth of the device's own zoom span, floored so it cannot
 * round away to nothing on a device with a narrow range. At 0.508 on a 0.508–30
 * range that is ~0.03 — below the granularity of anything visible, and it is
 * gone on the next frame regardless.
 *
 * Returns null when there is no room to move: a degenerate range is a device
 * that cannot zoom, where there is nothing to re-assert.
 */
export function framingNudge(target, min, max) {
  if (![target, min, max].every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
  if (min >= max) return null;
  const t = Math.min(max, Math.max(min, target));
  const step = Math.max((max - min) * 0.001, 1e-4);
  // DOWN BY PREFERENCE, because the common case is sitting at minZoom for
  // ultra-wide and a nudge upward there is a step toward the 1x this exists to
  // prevent. Upward only when down would leave the range.
  const down = t - step;
  if (down >= min) return down;
  const up = t + step;
  return up <= max ? up : null;
}

/**
 * The zoom the session should be started at: whatever it is currently on.
 *
 * Not minZoom. See prediction 2 above — resetting to wide on every session
 * start would be a second bug wearing the first one's clothes.
 */
export function framingTarget(current, min, max) {
  if (typeof current !== 'number' || !Number.isFinite(current)) return null;
  if (![min, max].every((n) => typeof n === 'number' && Number.isFinite(n))) return current;
  return Math.min(max, Math.max(min, current));
}

export default { framingNudge, framingTarget };
