/**
 * The callout "portal": tap a detail callout (3/A-402) and a small floating
 * viewport opens over the drawing, already framed on that detail. It is a second
 * tile viewer: draggable by its title bar, pinch/zoom/pan inside it like the main
 * one, and confined to its detail so it cannot be dragged off into the sheet.
 * The sheet underneath does not move and nothing navigates.
 *
 * The crop is an ESTIMATE until a detail's real extent is known (the backend marks
 * it `crop_exact: false`); the title says "approx." and "Open sheet" goes to the
 * whole page.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import { createSheetController } from './sheetController';
import { resolveManifest } from './useSheetSession';
import { manifestUsable } from './sheetApi';
import SheetPane from './SheetPane';

const SIZES = { small: { w: 300, h: 220 }, large: { w: 520, h: 380 } };
const PORTAL_CACHE_BYTES = 48 * 1024 * 1024;

export default function CalloutPortal({
  portal, projectId, currentFileId, currentManifest, api, platform, bounds, onClose, onOpenSheet,
}) {
  const [size, setSize] = useState('small');
  const [pos, setPos] = useState(null);                       // {x, y} of the top-left, once dragged
  const [state, setState] = useState({ status: 'loading', controller: null });
  const posRef = useRef(null);

  const sameFile = !portal.file_id || String(portal.file_id) === String(currentFileId);
  const targetFileId = sameFile ? currentFileId : portal.file_id;

  useEffect(() => {
    let cancelled = false;
    let controller = null;
    setState({ status: 'loading', controller: null });
    (async () => {
      const manifest = sameFile && manifestUsable(currentManifest)
        ? currentManifest
        : (await resolveManifest({ api, platform, projectId, fileId: targetFileId })).manifest;
      if (cancelled) return;
      if (!manifestUsable(manifest) || !(manifest.pages || []).some((p) => p.page === portal.page && p.ready)) {
        setState({ status: 'unavailable', controller: null });
        return;
      }
      controller = createSheetController({
        api, projectId, fileId: targetFileId, manifest, decode: platform.decode, dispose: platform.dispose,
        disk: platform.disk, dpr: platform.dpr(), maxBytes: PORTAL_CACHE_BYTES,
      });
      setState({ status: 'ready', controller });
    })();
    return () => { cancelled = true; if (controller) controller.destroy(); };
  }, [portal.file_id, portal.page, sameFile, targetFileId, projectId, api, platform, currentManifest]);

  // Frame the detail as soon as the pane has measured itself (and again if the panel is resized).
  useEffect(() => {
    const c = state.controller;
    if (!c) return undefined;
    const frame = () => {
      if (c.viewport.width <= 0) return;
      const box = portal.box || [0, 0, 1, 1];
      c.setBounds(portal.page, box, portal.box ? 0.12 : 0);
      c.frameBox(portal.page, box, portal.box ? 0.04 : 0);
    };
    frame();
    return c.on('change', (() => { let done = -1; return () => { if (done !== c.viewport.width && c.viewport.width > 0) { done = c.viewport.width; frame(); } }; })());
  }, [state.controller, portal.box, portal.page, size]);

  const dims = SIZES[size];
  const pan = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onPanResponderGrant: () => { posRef.current = pos || (bounds ? { x: Math.max(8, bounds.width - dims.w - 12), y: 70 } : { x: 12, y: 70 }); },
    onPanResponderMove: (_e, g) => {
      const b = posRef.current;
      if (!b) return;
      const maxX = bounds ? bounds.width - dims.w : 4000;
      const maxY = bounds ? bounds.height - dims.h : 4000;
      setPos({ x: Math.max(0, Math.min(maxX, b.x + g.dx)), y: Math.max(0, Math.min(maxY, b.y + g.dy)) });
    },
  }), [pos, bounds, dims.w, dims.h]);

  const at = pos || (bounds ? { x: Math.max(8, bounds.width - dims.w - 12), y: 70 } : { x: 12, y: 70 });
  const title = `${portal.sheet || 'Detail'}${portal.detail ? ` · ${portal.detail}` : ''}${portal.box && !portal.exact ? ' (approx.)' : ''}`;

  return (
    <View style={[styles.panel, { left: at.x, top: at.y, width: dims.w, height: dims.h }]} accessibilityLabel={`Detail ${title}`}>
      <View style={styles.bar} {...pan.panHandlers}>
        <Text style={styles.title} numberOfLines={1}>{title}</Text>
        <Pressable onPress={() => setSize(size === 'small' ? 'large' : 'small')} hitSlop={8} accessibilityRole="button" accessibilityLabel="Resize detail">
          <Text style={styles.btn}>{size === 'small' ? '⤢' : '⤡'}</Text>
        </Pressable>
        {onOpenSheet ? (
          <Pressable onPress={() => onOpenSheet(portal)} hitSlop={8} accessibilityRole="button" accessibilityLabel="Open the whole sheet">
            <Text style={styles.btn}>Open sheet</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={onClose} hitSlop={8} accessibilityRole="button" accessibilityLabel="Close detail">
          <Text style={styles.btn}>✕</Text>
        </Pressable>
      </View>
      <View style={styles.body}>
        {state.status === 'ready' && state.controller ? (
          <SheetPane controller={state.controller} interactive showCallouts={false} background="#0d151c" />
        ) : state.status === 'loading' ? (
          <View style={styles.center}><ActivityIndicator color="#E3C27A" /></View>
        ) : (
          <View style={styles.center}>
            <Text style={styles.msg}>This detail is not ready to preview.</Text>
            {onOpenSheet ? (
              <Pressable onPress={() => onOpenSheet(portal)} accessibilityRole="button"><Text style={[styles.btn, { marginTop: 8 }]}>Open sheet</Text></Pressable>
            ) : null}
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    position: 'absolute', backgroundColor: '#131E27', borderRadius: 10, overflow: 'hidden', borderWidth: 1,
    borderColor: '#E3C27A', shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 12,
  },
  bar: { height: 34, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, backgroundColor: '#1d2b37', gap: 12, cursor: 'move' },
  title: { flex: 1, color: '#fff', fontSize: 13, fontWeight: '600' },
  btn: { color: '#E3C27A', fontSize: 13, fontWeight: '600' },
  body: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 12 },
  msg: { color: '#94a3b8', fontSize: 12, textAlign: 'center' },
});
