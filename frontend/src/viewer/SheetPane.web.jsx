/**
 * The web renderer: one <canvas>, painted with Canvas2D from the shared
 * controller. Tiles, search highlights, callout boxes and pins are all drawn in
 * the same frame from the same camera, so nothing can swim against the drawing.
 * Gestures are pointer events (touch pan/pinch, mouse drag, wheel, trackpad pinch).
 */
import React, { useCallback, useEffect, useRef } from 'react';
import { worldToScreen } from './tileMath';
import {
  DOUBLE_TAP_MS, doubleTapTarget, inertiaStep, isTap, pinchDelta, pinchState, releaseVelocity, wheelAction,
} from './gestures';

const BG = '#131E27';
const PAGE = '#f2f1ec';

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawPin(ctx, x, y, color, selected) {
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
  ctx.imageSmoothingQuality = 'high';
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

export default function SheetPane({
  controller, onTap, onDoubleTap, interactive = true, background, showCallouts = true,
  testID, style,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const dprRef = useRef(1);
  const dirty = useRef(true);
  const raf = useRef(0);
  const inertia = useRef(null);
  const g = useRef({ pointers: new Map(), pinch: null, down: null, samples: [], lastTap: 0, moved: false });

  const schedule = useCallback(() => {
    dirty.current = true;
    if (raf.current) return;
    raf.current = requestAnimationFrame(function loop(t) {
      raf.current = 0;
      const c = controller;
      let again = false;
      if (c.tick(Date.now())) again = true;
      const ine = inertia.current;
      if (ine) {
        const dt = Math.min(48, t - ine.t || 16);
        ine.t = t;
        const s = inertiaStep(ine.v, dt);
        c.panBy(s.dx, s.dy);
        ine.v = { vx: s.vx, vy: s.vy };
        if (s.moving) again = true; else inertia.current = null;
      }
      if (dirty.current) {
        dirty.current = false;
        const ctx = canvasRef.current && canvasRef.current.getContext('2d');
        if (ctx) paint(ctx, c, dprRef.current, { background, showCallouts });
      }
      if (again) raf.current = requestAnimationFrame(loop);
    });
  }, [controller, background, showCallouts]);

  // size + redraw wiring
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas || !controller) return undefined;
    const resize = () => {
      const w = Math.max(1, Math.round(wrap.clientWidth));
      const h = Math.max(1, Math.round(wrap.clientHeight));
      const dpr = controller.dpr || 1;
      dprRef.current = dpr;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      controller.setViewport(w, h);
      schedule();
    };
    resize();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    if (ro) ro.observe(wrap);
    const off = controller.on('change', schedule);
    return () => {
      off();
      if (ro) ro.disconnect();
      if (raf.current) cancelAnimationFrame(raf.current);
      raf.current = 0;
    };
  }, [controller, schedule]);

  const pos = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onPointerDown = (e) => {
    if (!interactive || !controller) return;
    canvasRef.current.setPointerCapture && canvasRef.current.setPointerCapture(e.pointerId);
    inertia.current = null;
    const st = g.current;
    const p = pos(e);
    st.pointers.set(e.pointerId, p);
    if (st.pointers.size === 1) {
      st.down = { ...p, t: Date.now() };
      st.samples = [{ ...p, t: Date.now() }];
      st.moved = false;
    } else if (st.pointers.size === 2) {
      const [a, b] = Array.from(st.pointers.values());
      st.pinch = pinchState(a, b);
      st.moved = true;
    }
  };

  const onPointerMove = (e) => {
    const st = g.current;
    if (!st.pointers.has(e.pointerId)) return;
    const p = pos(e);
    const prev = st.pointers.get(e.pointerId);
    st.pointers.set(e.pointerId, p);
    if (st.pointers.size >= 2 && st.pinch) {
      const [a, b] = Array.from(st.pointers.values());
      const cur = pinchState(a, b);
      const d = pinchDelta(st.pinch, cur);
      controller.panBy(d.dx, d.dy);
      controller.zoomAt(d.factor, d.cx, d.cy);
      st.pinch = cur;
      return;
    }
    if (Math.hypot(p.x - st.down.x, p.y - st.down.y) > 4) st.moved = true;
    controller.panBy(p.x - prev.x, p.y - prev.y);
    st.samples.push({ ...p, t: Date.now() });
    if (st.samples.length > 12) st.samples.shift();
  };

  const onPointerUp = (e) => {
    const st = g.current;
    if (!st.pointers.has(e.pointerId)) return;
    const wasPinch = st.pointers.size >= 2;
    st.pointers.delete(e.pointerId);
    if (wasPinch) { st.pinch = null; st.down = null; return; }
    const p = pos(e);
    const now = Date.now();
    if (st.down && isTap(st.down, p, now)) {
      if (now - st.lastTap < DOUBLE_TAP_MS) {
        st.lastTap = 0;
        const target = doubleTapTarget(controller.camera.zoom, controller.viewport.width / 1000);
        if (target.fit) controller.fit(); else controller.zoomAt(target.factor, p.x, p.y);
        if (onDoubleTap) onDoubleTap();
      } else {
        st.lastTap = now;
        if (onTap) onTap(controller.hitTest(p.x, p.y), p);
      }
    } else if (st.down) {
      const v = releaseVelocity(st.samples, now);
      if (Math.hypot(v.vx, v.vy) > 0.15) { inertia.current = { v, t: 0 }; schedule(); }
    }
    st.down = null;
  };

  // React attaches wheel listeners passively; a zoom must be able to preventDefault.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !controller || !interactive) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const a = wheelAction(e);
      const r = canvas.getBoundingClientRect();
      if (a.type === 'zoom') controller.zoomAt(a.factor, e.clientX - r.left, e.clientY - r.top);
      else controller.panBy(a.dx, a.dy);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [controller, interactive]);

  return (
    <div ref={wrapRef} data-testid={testID} style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', background: background || BG, ...style }}>
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onContextMenu={(e) => e.preventDefault()}
        style={{ display: 'block', touchAction: 'none', userSelect: 'none', cursor: interactive ? 'grab' : 'default' }}
      />
    </div>
  );
}
