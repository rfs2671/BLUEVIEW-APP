/**
 * Gesture maths shared by the web (pointer events) and native (gesture handler)
 * renderers. Pure functions of numbers, so a thumb and a trackpad behave the same.
 */

export const TAP_SLOP_PX = 8;
export const TAP_MAX_MS = 450;
export const DOUBLE_TAP_MS = 320;
export const DOUBLE_TAP_ZOOM = 2.4;

/** Two touch points -> {cx, cy, dist}. */
export function pinchState(a, b) {
  return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, dist: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)) };
}

/** What a pinch changed between two states: the zoom factor and the focal point's travel. */
export function pinchDelta(prev, cur) {
  return { factor: cur.dist / prev.dist, cx: cur.cx, cy: cur.cy, dx: cur.cx - prev.cx, dy: cur.cy - prev.cy };
}

export function isTap(down, up, now) {
  return Math.hypot(up.x - down.x, up.y - down.y) <= TAP_SLOP_PX && now - down.t <= TAP_MAX_MS;
}

/** A velocity (px/ms) from the last few points of a drag, ignoring stale ones. */
export function releaseVelocity(samples, now, windowMs = 90) {
  const pts = samples.filter((s) => now - s.t <= windowMs);
  if (pts.length < 2) return { vx: 0, vy: 0 };
  const a = pts[0];
  const b = pts[pts.length - 1];
  const dt = Math.max(1, b.t - a.t);
  return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt };
}

/** One inertia step of `dt` ms: how far to pan, the decayed velocity, and whether it is still moving. */
export function inertiaStep(v, dt, friction = 0.0035) {
  const k = Math.exp(-friction * dt);
  const vx = v.vx * k;
  const vy = v.vy * k;
  return { dx: v.vx * dt, dy: v.vy * dt, vx, vy, moving: Math.hypot(vx, vy) > 0.02 };
}

/** Wheel -> an action. Ctrl/Cmd (a trackpad pinch) zooms; a plain wheel pans. */
export function wheelAction(e) {
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
  const dx = e.deltaX * unit;
  const dy = e.deltaY * unit;
  if (e.ctrlKey || e.metaKey) return { type: 'zoom', factor: Math.exp(-dy * 0.01) };
  return { type: 'pan', dx: -dx, dy: -dy };
}

/** Double tap/click: zoom in at the point, or back to fit when already zoomed in. */
export function doubleTapTarget(zoom, fitZoom) {
  return zoom > fitZoom * 1.6 ? { fit: true } : { factor: DOUBLE_TAP_ZOOM };
}
