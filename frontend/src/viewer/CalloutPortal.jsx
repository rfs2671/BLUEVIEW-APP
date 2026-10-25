/**
 * The callout "portal": tap a detail callout (3/A-402) and a small floating
 * viewport opens over the drawing, already framed on that detail. It is a second
 * tile viewer: draggable by its title bar, with pinch/zoom/pan inside it like the main
 * one. It loads the WHOLE target sheet; the detail's crop (an estimate until a
 * detail's real extent is known, `crop_exact: false`) only chooses where the camera
 * starts, with a 40% margin, so nothing is ever clipped and the reader can look
 * anywhere on that sheet. The title says "approx." for an estimated crop, and "Open
 * sheet" goes to the page in the main viewer. The sheet underneath does not move.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import { createSheetController } from './sheetController';
import { resolveManifest } from './useSheetSession';
import { manifestUsable } from './sheetApi';
import { getSheetPane, getSheetWebViewPane } from './loadSheetPane';
import { createWebViewHandle } from './webviewHandle';
import { keepPortalFramed } from './portalFrame';

const SIZES = { small: { w: 300, h: 220 }, large: { w: 520, h: 380 } };
const PORTAL_CACHE_BYTES = 48 * 1024 * 1024;

export default function CalloutPortal({
  portal, projectId, currentFileId, currentManifest, api, platform, bounds, onClose, onOpenSheet, webview = false,
}) {
  const [size, setSize] = useState('small');
  const [pos, setPos] = useState(null);                       // {x, y} of the top-left, once dragged
  const [state, setState] = useState({ status: 'loading', controller: null });
  // in a WebView-hosted viewer the portal is a second page of the same kind, framed by the page itself
  const handle = useMemo(() => (webview ? createWebViewHandle() : null), [webview]);
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
      if (webview) {
        setState({ status: 'ready', controller: null, manifest });
        return;
      }
      controller = createSheetController({
        api, projectId, fileId: targetFileId, manifest, decode: platform.decode, dispose: platform.dispose,
        disk: platform.disk, dpr: platform.dpr(), maxBytes: PORTAL_CACHE_BYTES,
      });
      setState({ status: 'ready', controller });
    })();
    return () => { cancelled = true; if (controller) controller.destroy(); };
  }, [portal.file_id, portal.page, sameFile, targetFileId, projectId, api, platform, currentManifest, webview]);

  // Frame the detail once the pane has measured itself (and again if the panel is resized). The
  // whole target sheet stays reachable: see portalFrame.js.
  useEffect(() => {
    const c = state.controller;
    if (!c) return undefined;                 // a WebView page frames itself
    return keepPortalFramed(c, portal);
  }, [state.controller, portal.box, portal.page, size]);

  const dims = SIZES[size];
  const SheetPane = state.status === 'ready' && !webview ? getSheetPane() : null;
  const WebPane = state.status === 'ready' && webview ? getSheetWebViewPane() : null;
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
        {state.status === 'ready' && webview && WebPane ? (
          <WebPane
            handle={handle} projectId={projectId} fileId={targetFileId} manifest={state.manifest}
            portal={{ page: portal.page, box: portal.box || null }} showCallouts={false} background="#0d151c"
            onFatal={() => setState({ status: 'unavailable', controller: null })}
          />
        ) : state.status === 'ready' && state.controller ? (
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
