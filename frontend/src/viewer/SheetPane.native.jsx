/**
 * The native renderer: Skia (GPU) with Reanimated + Gesture Handler.
 *
 * THE CAMERA LIVES ON THE UI THREAD. Pan, pinch, double tap and fling write three
 * shared values (cx, cy, zoom); one <Group> turns them into the world transform,
 * and tiles, search highlights, callout boxes and pins are all children of it. So
 * a pin cannot lag the drawing: it is not positioned from JS at all, it is drawn
 * inside the same transform on the same frame. The JS thread only decides WHICH
 * tiles to fetch (the controller), from the camera it is told about every ~60 ms.
 *
 * Programmatic moves (fit, fly-to-match) are taken over here: the controller emits
 * 'fly', this animates the shared values, and the controller learns the end state.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  cancelAnimation, runOnJS, useAnimatedReaction, useDerivedValue, useSharedValue, withDecay, withTiming, Easing,
} from 'react-native-reanimated';
import {
  Canvas, Group, Image as SkImage, Path, Rect, RoundedRect, Skia,
} from '@shopify/react-native-skia';
import { clampCamera, panBy, zoomAt } from './tileMath';
import { DOUBLE_TAP_ZOOM, doubleTapTarget } from './gestures';

const SEAM = 0.3;                          // world units: neighbouring tiles overlap a hair, no seams
const SYNC_MS = 60;

const PIN_PATH = (() => {
  const p = Skia.Path.Make();
  p.moveTo(0, 0);
  p.cubicTo(-11, -10, -11, -23, 0, -23);
  p.cubicTo(11, -23, 11, -10, 0, 0);
  p.close();
  return p;
})();

function Pin({ x, y, color, selected, zoom }) {
  const transform = useDerivedValue(() => [{ translateX: x }, { translateY: y }, { scale: 1 / zoom.value }]);
  return (
    <Group transform={transform}>
      <Path path={PIN_PATH} color={color || '#243746'} />
      <Path path={PIN_PATH} color={selected ? '#E3C27A' : '#ffffff'} style="stroke" strokeWidth={selected ? 3 : 2} />
    </Group>
  );
}

function Highlight({ rect, current, zoom }) {
  const pad = useDerivedValue(() => 2 / zoom.value);
  const x = useDerivedValue(() => rect.x - pad.value);
  const y = useDerivedValue(() => rect.y - pad.value);
  const w = useDerivedValue(() => rect.w + pad.value * 2);
  const h = useDerivedValue(() => rect.h + pad.value * 2);
  const r = useDerivedValue(() => 3 / zoom.value);
  return <RoundedRect x={x} y={y} width={w} height={h} r={r} color={current ? 'rgba(255,152,0,0.45)' : 'rgba(255,235,59,0.45)'} />;
}

function CalloutBox({ rect, zoom }) {
  const pad = useDerivedValue(() => 3 / zoom.value);
  const x = useDerivedValue(() => rect.x - pad.value);
  const y = useDerivedValue(() => rect.y - pad.value);
  const w = useDerivedValue(() => rect.w + pad.value * 2);
  const h = useDerivedValue(() => rect.h + pad.value * 2);
  const sw = useDerivedValue(() => 1.25 / zoom.value);
  return <Rect x={x} y={y} width={w} height={h} color="rgba(74,144,226,0.85)" style="stroke" strokeWidth={sw} />;
}

export default function SheetPane({ controller, onTap, onDoubleTap, interactive = true, showCallouts = true, background = '#131E27', testID }) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [scene, setScene] = useState({ frame: { previews: [], tiles: [] }, matches: [], callouts: [], pins: [], sig: '' });
  const cx = useSharedValue(500);
  const cy = useSharedValue(0);
  const zoom = useSharedValue(1);
  const vpW = useSharedValue(0);
  const vpH = useSharedValue(0);
  const lim = useSharedValue({ min: 0.1, max: 20 });
  const bnd = useSharedValue(null);
  const gesturing = useSharedValue(false);
  const syncTimer = useRef(null);
  const latest = useRef(null);
  const sceneRaf = useRef(0);

  // keep the worklets' copy of the limits / bounds / viewport current
  const refreshLimits = useCallback(() => {
    if (!controller) return;
    lim.value = controller.limits;
    vpW.value = controller.viewport.width;
    vpH.value = controller.viewport.height;
    bnd.value = controller.bounds || null;
  }, [controller, lim, vpW, vpH, bnd]);

  const pullScene = useCallback(() => {
    sceneRaf.current = 0;
    if (!controller) return;
    const frame = controller.frame();
    const matches = controller.matchRects();
    const callouts = showCallouts ? controller.calloutRects() : [];
    const pins = controller.pins.map((p) => {
      const pg = controller.layout.pages.find((q) => q.page === (p.page || 1)) || controller.layout.pages[0];
      return { id: p.id, x: pg.x + p.x * pg.w, y: pg.y + p.y * pg.h, color: p.color, selected: Boolean(p.selected) };
    });
    const sig = [
      frame.previews.map((p) => p.key).join(','), frame.tiles.map((t) => t.key).join(','),
      matches.map((m) => `${m.rect.x}${m.current}`).join(','), callouts.length, pins.map((p) => `${p.id}${p.x}${p.y}${p.selected}`).join(','),
    ].join('|');
    setScene((prev) => (prev.sig === sig ? prev : { frame, matches, callouts, pins, sig }));
  }, [controller, showCallouts]);

  // controller -> screen
  useEffect(() => {
    if (!controller) return undefined;
    refreshLimits();
    const onChange = () => {
      if (!sceneRaf.current) sceneRaf.current = requestAnimationFrame(pullScene);
      refreshLimits();
      if (!gesturing.value) {
        const c = controller.camera;
        if (Math.abs(c.x - cx.value) > 1e-3 || Math.abs(c.y - cy.value) > 1e-3 || Math.abs(c.zoom - zoom.value) > 1e-6) {
          cancelAnimation(cx); cancelAnimation(cy); cancelAnimation(zoom);
          cx.value = c.x; cy.value = c.y; zoom.value = c.zoom;
        }
      }
    };
    const offFly = controller.on('fly', (to, ms) => {
      const cfg = { duration: Math.max(1, ms), easing: Easing.out(Easing.cubic) };
      cx.value = withTiming(to.x, cfg);
      cy.value = withTiming(to.y, cfg);
      zoom.value = withTiming(to.zoom, cfg, (finished) => { if (finished) runOnJS(syncCam)(to.x, to.y, to.zoom); });
      return true;
    });
    const off = controller.on('change', onChange);
    pullScene();
    return () => { off(); offFly(); if (sceneRaf.current) cancelAnimationFrame(sceneRaf.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller, pullScene, refreshLimits]);

  useEffect(() => {
    if (controller && size.width > 0) {
      controller.setViewport(size.width, size.height);
      const c = controller.camera;
      cx.value = c.x; cy.value = c.y; zoom.value = c.zoom;
      refreshLimits();
    }
  }, [controller, size.width, size.height, cx, cy, zoom, refreshLimits]);

  // UI thread -> controller, throttled: it only needs the camera to choose tiles
  function syncCam(x, y, z) {
    latest.current = { x, y, zoom: z };
    if (syncTimer.current) return;
    syncTimer.current = setTimeout(() => {
      syncTimer.current = null;
      if (controller && latest.current) controller.setCamera(latest.current);
    }, SYNC_MS);
  }
  useAnimatedReaction(
    () => [cx.value, cy.value, zoom.value],
    (cur, prev) => {
      if (!prev || cur[0] !== prev[0] || cur[1] !== prev[1] || cur[2] !== prev[2]) runOnJS(syncCam)(cur[0], cur[1], cur[2]);
    },
  );
  useEffect(() => () => { if (syncTimer.current) clearTimeout(syncTimer.current); }, []);

  const layoutBox = useMemo(() => (controller ? { width: controller.layout.width, height: controller.layout.height } : { width: 1000, height: 1000 }), [controller]);

  const handleTap = useCallback((x, y, camx, camy, camz) => {
    if (!controller) return;
    controller.setCamera({ x: camx, y: camy, zoom: camz });
    if (onTap) onTap(controller.hitTest(x, y), { x, y });
  }, [controller, onTap]);

  const handleDoubleTap = useCallback((x, y, camx, camy, camz) => {
    if (!controller) return;
    controller.setCamera({ x: camx, y: camy, zoom: camz });
    const t = doubleTapTarget(camz, controller.viewport.width / 1000);
    if (t.fit) controller.fit();
    else controller.flyTo(zoomAt(controller.camera, DOUBLE_TAP_ZOOM, x, y, controller.viewport, controller.limits));
    if (onDoubleTap) onDoubleTap();
  }, [controller, onDoubleTap]);

  const gesture = useMemo(() => {
    const clampNow = (c) => {
      'worklet';
      return clampCamera(c, layoutBox, { width: vpW.value, height: vpH.value }, lim.value, bnd.value);
    };
    const pan = Gesture.Pan()
      .maxPointers(2)
      .onBegin(() => { gesturing.value = true; cancelAnimation(cx); cancelAnimation(cy); cancelAnimation(zoom); })
      .onChange((e) => {
        const n = clampNow(panBy({ x: cx.value, y: cy.value, zoom: zoom.value }, e.changeX, e.changeY));
        cx.value = n.x; cy.value = n.y;
      })
      .onEnd((e) => {
        const z = zoom.value;
        const vp = { width: vpW.value, height: vpH.value };
        const lo = clampCamera({ x: -1e9, y: -1e9, zoom: z }, layoutBox, vp, lim.value, bnd.value);
        const hi = clampCamera({ x: 1e9, y: 1e9, zoom: z }, layoutBox, vp, lim.value, bnd.value);
        cx.value = withDecay({ velocity: -e.velocityX / z, deceleration: 0.996, clamp: [lo.x, hi.x] });
        cy.value = withDecay({ velocity: -e.velocityY / z, deceleration: 0.996, clamp: [lo.y, hi.y] });
      })
      .onFinalize(() => { gesturing.value = false; });
    const pinch = Gesture.Pinch()
      .onBegin(() => { gesturing.value = true; cancelAnimation(zoom); })
      .onChange((e) => {
        const n = clampNow(zoomAt({ x: cx.value, y: cy.value, zoom: zoom.value }, e.scaleChange, e.focalX, e.focalY,
          { width: vpW.value, height: vpH.value }, lim.value));
        cx.value = n.x; cy.value = n.y; zoom.value = n.zoom;
      })
      .onFinalize(() => { gesturing.value = false; });
    const doubleTap = Gesture.Tap().numberOfTaps(2).maxDuration(280)
      .onEnd((e, ok) => { if (ok) runOnJS(handleDoubleTap)(e.x, e.y, cx.value, cy.value, zoom.value); });
    const tap = Gesture.Tap().maxDuration(450).maxDistance(10)
      .onEnd((e, ok) => { if (ok) runOnJS(handleTap)(e.x, e.y, cx.value, cy.value, zoom.value); });
    return Gesture.Race(Gesture.Simultaneous(pan, pinch), Gesture.Exclusive(doubleTap, tap));
  }, [layoutBox, handleTap, handleDoubleTap, cx, cy, zoom, vpW, vpH, lim, bnd, gesturing]);

  const world = useDerivedValue(() => [
    { translateX: vpW.value / 2 }, { translateY: vpH.value / 2 }, { scale: zoom.value },
    { translateX: -cx.value }, { translateY: -cy.value },
  ]);

  const body = (
    <Canvas style={{ flex: 1 }}>
      <Rect x={0} y={0} width={size.width} height={size.height} color={background} />
      <Group transform={world}>
        {controller && controller.layout.pages.map((pg) => (
          <Rect key={`bg${pg.page}`} x={pg.x} y={pg.y} width={pg.w} height={pg.h} color="#f2f1ec" />
        ))}
        {scene.frame.previews.map((p) => (
          <SkImage key={p.key} image={p.image} x={p.rect.x} y={p.rect.y} width={p.rect.w} height={p.rect.h} fit="fill" />
        ))}
        {scene.frame.tiles.map((t) => (
          <SkImage key={t.key} image={t.image} x={t.rect.x} y={t.rect.y} width={t.rect.w + SEAM} height={t.rect.h + SEAM} fit="fill" />
        ))}
        {scene.callouts.map((c, i) => <CalloutBox key={`c${i}`} rect={c.rect} zoom={zoom} />)}
        {scene.matches.map((m, i) => <Highlight key={`m${i}`} rect={m.rect} current={m.current} zoom={zoom} />)}
        {scene.pins.map((p) => <Pin key={p.id} x={p.x} y={p.y} color={p.color} selected={p.selected} zoom={zoom} />)}
      </Group>
    </Canvas>
  );

  return (
    <View testID={testID} style={{ flex: 1, backgroundColor: background }} onLayout={(e) => setSize({ width: e.nativeEvent.layout.width, height: e.nativeEvent.layout.height })}>
      {interactive ? <GestureDetector gesture={gesture}><Animated.View style={{ flex: 1 }}>{body}</Animated.View></GestureDetector> : body}
    </View>
  );
}
