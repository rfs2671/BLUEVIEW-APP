/**
 * The whole tiled-viewer body: the renderer, the search bar, zoom controls, pins
 * and the callout portal. Both PDFViewer components render this in place of their
 * legacy viewer once a drawing's tiles are ready; their own top bar, note sheets
 * and thread views are unchanged.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { ChevronDown, ChevronUp, Maximize2, Minus, Plus, X } from 'lucide-react-native';
import { getSheetPane } from './loadSheetPane';
import CalloutPortal from './CalloutPortal';
import { matchLabel, portalBox } from './sheetIndex';

const SEARCH_DELAY_MS = 120;

export default function SheetViewerPane({
  controller, manifest, projectId, fileId, api, platform,
  annotations = [], markerColor, selectedId = null, pinModeActive = false,
  onPlacePin, onSelectAnnotation, searchOpen = false, onCloseSearch, onOpenFile,
}) {
  const [box, setBox] = useState(null);
  const [portal, setPortal] = useState(null);
  const [q, setQ] = useState('');
  const [, force] = useState(0);
  const timer = useRef(null);

  // pins ride the controller's transform; legacy notes (no page) are page 1
  const colorRef = useRef(markerColor);
  colorRef.current = markerColor;
  useEffect(() => {
    if (!controller) return;
    const markerColor = colorRef.current;
    controller.setPins((annotations || []).map((a) => {
      const pos = a.position || {};
      const id = a._id || a.id;
      return { id, page: a.page_number || 1, x: Math.max(0, Math.min(1, pos.x || 0)), y: Math.max(0, Math.min(1, pos.y || 0)),
        color: markerColor ? markerColor(a) : undefined, selected: id === selectedId };
    }));
  }, [controller, annotations, selectedId]);

  useEffect(() => (controller ? controller.on('change', () => force((n) => (n + 1) % 1e6)) : undefined), [controller]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => { if (!searchOpen && controller) { controller.clearSearch(); setQ(''); } }, [searchOpen, controller]);

  const onTap = useCallback((hit) => {
    if (!hit) return;
    if (hit.type === 'pin') {
      if (pinModeActive) return;
      const ann = (annotations || []).find((a) => (a._id || a.id) === hit.pin.id);
      if (ann && onSelectAnnotation) onSelectAnnotation(ann);
    } else if (hit.type === 'callout') {
      if (!pinModeActive) { const p = portalBox(hit.callout); if (p) setPortal(p); }
    } else if (hit.type === 'page' && pinModeActive && onPlacePin) {
      onPlacePin({ x: hit.x, y: hit.y, page: hit.page });
    }
  }, [annotations, pinModeActive, onPlacePin, onSelectAnnotation]);

  const onChangeQuery = (text) => {
    setQ(text);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { controller.search(text); }, SEARCH_DELAY_MS);
  };

  const openSheet = useCallback((p) => {
    setPortal(null);
    if (!p.file_id || String(p.file_id) === String(fileId)) controller.goToPage(p.page);
    else if (onOpenFile) onOpenFile(p.file_id, p.page);
  }, [controller, fileId, onOpenFile]);

  if (!controller) return null;
  const SheetPane = getSheetPane();
  const st = controller.searchState;
  const prog = controller.indexProgress;
  const status = searchOpen && q.trim()
    ? (prog.loaded + prog.failed < prog.total && !st.matches.length ? 'Searching…' : matchLabel(st.matches.length, st.current, q))
    : '';

  return (
    <View style={styles.fill} onLayout={(e) => setBox(e.nativeEvent.layout)}>
      <SheetPane controller={controller} onTap={onTap} testID="sheet-pane" />

      {searchOpen ? (
        <View style={styles.searchBar}>
          <TextInput
            value={q} onChangeText={onChangeQuery} onSubmitEditing={() => controller.stepMatch(1)}
            placeholder="Search this drawing" placeholderTextColor="#64748b" autoFocus autoCapitalize="none" autoCorrect={false}
            returnKeyType="search" blurOnSubmit={false} accessibilityLabel="Search this drawing" style={styles.searchInput}
          />
          <Text style={styles.count} numberOfLines={1}>{status}</Text>
          <Pressable onPress={() => controller.stepMatch(-1)} disabled={!st.matches.length} hitSlop={6} accessibilityRole="button" accessibilityLabel="Previous match" style={styles.sBtn}>
            <ChevronUp size={20} strokeWidth={1.5} color={st.matches.length ? '#fff' : '#475569'} />
          </Pressable>
          <Pressable onPress={() => controller.stepMatch(1)} disabled={!st.matches.length} hitSlop={6} accessibilityRole="button" accessibilityLabel="Next match" style={styles.sBtn}>
            <ChevronDown size={20} strokeWidth={1.5} color={st.matches.length ? '#fff' : '#475569'} />
          </Pressable>
          <Pressable onPress={onCloseSearch} hitSlop={6} accessibilityRole="button" accessibilityLabel="Close search" style={styles.sBtn}>
            <X size={18} strokeWidth={1.5} color="#fff" />
          </Pressable>
        </View>
      ) : null}

      {pinModeActive ? (
        <View pointerEvents="none" style={styles.pinBanner}><Text style={styles.pinText}>Tap the drawing to place a note</Text></View>
      ) : null}

      <View style={styles.zoom}>
        <Pressable onPress={() => controller.flyTo({ ...controller.camera, zoom: controller.camera.zoom * 2 }, 200)} accessibilityRole="button" accessibilityLabel="Zoom in" style={styles.zBtn}><Plus size={18} color="#fff" /></Pressable>
        <Pressable onPress={() => controller.flyTo({ ...controller.camera, zoom: controller.camera.zoom / 2 }, 200)} accessibilityRole="button" accessibilityLabel="Zoom out" style={styles.zBtn}><Minus size={18} color="#fff" /></Pressable>
        <Pressable onPress={() => controller.fit()} accessibilityRole="button" accessibilityLabel="Fit to screen" style={styles.zBtn}><Maximize2 size={16} color="#fff" /></Pressable>
      </View>

      {portal ? (
        <CalloutPortal
          portal={portal} projectId={projectId} currentFileId={fileId} currentManifest={manifest} api={api} platform={platform}
          bounds={box} onClose={() => setPortal(null)} onOpenSheet={openSheet}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  searchBar: { position: 'absolute', top: 0, left: 0, right: 0, flexDirection: 'row', alignItems: 'center', backgroundColor: 'rgba(19,30,39,0.96)', paddingHorizontal: 10, paddingVertical: 6, gap: 6 },
  searchInput: { flex: 1, color: '#fff', backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 14 },
  count: { color: '#94a3b8', fontSize: 12, minWidth: 64, textAlign: 'center' },
  sBtn: { padding: 6 },
  pinBanner: { position: 'absolute', top: 10, alignSelf: 'center', backgroundColor: 'rgba(227,194,122,0.95)', paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16 },
  pinText: { color: '#141A1F', fontSize: 13, fontWeight: '600' },
  zoom: { position: 'absolute', right: 12, bottom: 24, gap: 8 },
  zBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(19,30,39,0.9)', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)' },
});
