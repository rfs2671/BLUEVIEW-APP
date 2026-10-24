/**
 * The canvas viewer, with no framework: paints a controller onto a <canvas> (Canvas2D)
 * and turns pointer events into camera moves. The web pane (SheetPane.web.jsx) and the
 * WebView page that phones use (webview/main.js) both mount this, so a pin, a highlight
 * and a tile are always drawn in the same frame from the same camera.
 *
 *   const v = mountCanvasViewer(container, controller, { onTap, onDoubleTap, background, showCallouts, interactive });
 *   v.destroy();
 */
import { worldToScreen } from './tileMath';
import {
  DOUBLE_TAP_MS, createPointerTracker, doubleTapTarget, inertiaStep, wheelAction,
} from './gestures';

const BG = '#131E27';
const PAGE = '#f2f1ec';

export function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export function drawPin(ctx, x, y, color, selected) {
  const r = selected ? 13 : 11;
  ctx.save();
  ctx.translate(x, y);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.bezierCurveTo(-r, -r * 0.9, -r, -r * 2.1, 0, -r * 2.1);
  ctx.bezierCurveTo(r, -r * 2.1, r, -r * 0.9, 0, 0);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = selected ? 3 : 2;
  ctx.strokeStyle = selected ? '#E3C27A' : '#ffffff';
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(0, -r * 1.25, r * 0.38, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
  ctx.restore();
}

/** Paint one frame. Exported so the portal and tests can reuse it. */
export function paint(ctx, c, dpr, { background = BG, showCallouts = true } = {}) {
  const vp = c.viewport;
  const cam = c.camera;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, vp.width, vp.height);
  ctx.imageSmoothingEnabled = true;
  // 'high' resamples with a costly filter on every drawImage; tiles are already cut at (or above)
  // screen resolution, so 'medium' is visually the same and far cheaper on a phone
  ctx.imageSmoothingQuality = 'medium';
  const toScreen = (r) => {
    const a = worldToScreen(cam, vp, r.x, r.y);
    const b = worldToScreen(cam, vp, r.x + r.w, r.y + r.h);
    // snap to whole pixels, outward: adjacent tiles then share an edge exactly (no hairline seams)
    const x0 = Math.floor(a.x * dpr) / dpr;
    const y0 = Math.floor(a.y * dpr) / dpr;
    return { x: x0, y: y0, w: Math.ceil(b.x * dpr) / dpr - x0, h: Math.ceil(b.y * dpr) / dpr - y0 };
  };
  const frame = c.frame();
  for (const pg of c.layout.pages) {
    const r = toScreen({ x: pg.x, y: pg.y, w: pg.w, h: pg.h });
    if (r.x > vp.width || r.y > vp.height || r.x + r.w < 0 || r.y + r.h < 0) continue;
    ctx.fillStyle = PAGE;
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }
  for (const p of frame.previews) {
    const r = toScreen(p.rect);
    ctx.drawImage(p.image, r.x, r.y, r.w, r.h);
  }
  for (const t of frame.tiles) {
    const r = toScreen(t.rect);
    if (r.x > vp.width || r.y > vp.height || r.x + r.w < 0 || r.y + r.h < 0) continue;
    ctx.drawImage(t.image, r.x, r.y, r.w, r.h);
  }

  if (showCallouts) {
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = 'rgba(74,144,226,0.85)';
    ctx.setLineDash([4, 3]);
    for (const { rect } of c.calloutRects()) {
      const r = toScreen(rect);
      const pad = 3;
      ctx.strokeRect(r.x - pad, r.y - pad, r.w + pad * 2, r.h + pad * 2);
    }
    ctx.setLineDash([]);
  }
  for (const { rect, current } of c.matchRects()) {
    const r = toScreen(rect);
    if (r.x > vp.width || r.y > vp.height || r.x + r.w < 0 || r.y + r.h < 0) continue;
    const pad = 2;
    ctx.fillStyle = current ? 'rgba(255,152,0,0.45)' : 'rgba(255,235,59,0.45)';
    ctx.strokeStyle = current ? '#ff9800' : 'rgba(200,170,0,0.9)';
    ctx.lineWidth = current ? 2 : 1;
    roundRect(ctx, r.x - pad, r.y - pad, r.w + pad * 2, r.h + pad * 2, 3);
    ctx.fill();
    ctx.stroke();
  }
  for (const pin of c.pins) {
    const s = c.pinScreen(pin);
    if (!s || s.x < -30 || s.y < -40 || s.x > vp.width + 30 || s.y > vp.height + 40) continue;
    drawPin(ctx, s.x, s.y, pin.color || '#243746', Boolean(pin.selected));
  }
}

export function mountCanvasViewer(container, controller, {
  onTap = null, onDoubleTap = null, interactive = true, background, showCallouts = true,
} = {}) {
  const doc = container.ownerDocument;
  const canvas = doc.createElement('canvas');
  canvas.style.display = 'block';
  canvas.style.touchAction = 'none';
  canvas.style.userSelect = 'none';
  canvas.style.webkitUserSelect = 'none';
  canvas.style.cursor = interactive ? 'grab' : 'default';
  container.appendChild(canvas);

  let dpr = 1;
  let dirty = true;
  let raf = 0;
  let inertia = null;
  let destroyed = false;
  let lastTap = 0;
  const tracker = createPointerTracker();
  // A touch screen reports 60-240 moves a second; the screen shows 60. Moves are summed here and
  // applied once per frame, so the camera, the tile selection and the repaint run per FRAME,
  // not per event (this is most of the difference between smooth and stuttering on a phone).
  const pending = { dx: 0, dy: 0, factor: 1, cx: 0, cy: 0, any: false };
  function flushPending() {
    if (!pending.any) return;
    const { dx, dy, factor, cx, cy } = pending;
    pending.dx = 0; pending.dy = 0; pending.factor = 1; pending.any = false;
    if (dx || dy) controller.panBy(dx, dy);
    if (factor !== 1) controller.zoomAt(factor, cx, cy);
  }

  const pos = (e) => {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  function frame(t) {
    raf = 0;
    if (destroyed) return;
    flushPending();
    let again = false;
    if (controller.tick(Date.now())) again = true;
    if (inertia) {
      const dt = Math.min(48, t - inertia.t || 16);
      inertia.t = t;
      const s = inertiaStep(inertia.v, dt);
      controller.panBy(s.dx, s.dy);
      inertia.v = { vx: s.vx, vy: s.vy };
      if (s.moving) again = true; else inertia = null;
    }
    if (dirty) {
      dirty = false;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        const t0 = globalThis.__sheetPerf ? performance.now() : 0;
        paint(ctx, controller, dpr, { background, showCallouts });
        if (globalThis.__sheetPerf) globalThis.__sheetPerf.paints.push(performance.now() - t0);
      }
    }
    if (again) raf = requestAnimationFrame(frame);
  }
  function schedule() {
    dirty = true;
    if (!raf && !destroyed) raf = requestAnimationFrame(frame);
  }

  function resize() {
    const w = Math.max(1, Math.round(container.clientWidth));
    const h = Math.max(1, Math.round(container.clientHeight));
    dpr = controller.dpr || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    controller.setViewport(w, h);
    schedule();
  }
  resize();
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
  if (ro) ro.observe(container);
  const off = controller.on('change', schedule);

  const down = (e) => {
    if (!interactive) return;
    if (canvas.setPointerCapture) { try { canvas.setPointerCapture(e.pointerId); } catch (_e) { /* not capturable */ } }
    inertia = null;
    tracker.down(e.pointerId, pos(e), Date.now());
  };
  const move = (e) => {
    const a = tracker.move(e.pointerId, pos(e), Date.now());
    if (!a) return;
    pending.dx += a.dx;
    pending.dy += a.dy;
    if (a.type === 'pinch') { pending.factor *= a.factor; pending.cx = a.cx; pending.cy = a.cy; }
    pending.any = true;
    schedule();
  };
  const up = (e) => {
    flushPending();
    const p = pos(e);
    const a = tracker.up(e.pointerId, p, Date.now());
    if (a.type === 'tap') {
      const now = Date.now();
      if (now - lastTap < DOUBLE_TAP_MS) {
        lastTap = 0;
        const target = doubleTapTarget(controller.camera.zoom, controller.viewport.width / 1000);
        if (target.fit) controller.fit(); else controller.zoomAt(target.factor, p.x, p.y);
        if (onDoubleTap) onDoubleTap();
      } else {
        lastTap = now;
        if (onTap) onTap(controller.hitTest(p.x, p.y), p);
      }
    } else if (a.type === 'fling') {
      inertia = { v: a.v, t: 0 };
      schedule();
    }
  };
  // a wheel zoom must be able to preventDefault, so this listener cannot be passive
  const wheel = (e) => {
    if (!interactive) return;
    e.preventDefault();
    const a = wheelAction(e);
    const r = canvas.getBoundingClientRect();
    if (a.type === 'zoom') controller.zoomAt(a.factor, e.clientX - r.left, e.clientY - r.top);
    else controller.panBy(a.dx, a.dy);
  };
  canvas.addEventListener('pointerdown', down);
  canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('wheel', wheel, { passive: false });

  return {
    canvas,
    repaint: schedule,
    destroy() {
      destroyed = true;
      off();
      if (ro) ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
      canvas.remove();
    },
  };
}
