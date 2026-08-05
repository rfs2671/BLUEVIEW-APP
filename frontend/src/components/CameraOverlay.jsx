import React, { useState } from 'react';
import {
  View, Text, Image, Pressable, StyleSheet, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { X, RefreshCw, Check, Trash2, ChevronLeft, ChevronRight } from 'lucide-react-native';
import { chrome, withAlpha } from '../styles/semanticColors';

/**
 * The camera's CHROME, with no camera in it.
 *
 * Split out of CameraCaptureModal so the capture UI can be rendered — and
 * looked at — without react-native-vision-camera, which throws at module scope
 * off-native and cannot run in a browser at all. This file imports nothing
 * native, so it is the one part of the capture flow that can be exercised
 * outside a device.
 *
 * It is deliberately presentational: no capture state, no session, no photo
 * plumbing. Everything it draws comes from props.
 *
 * COLOUR NOTE — this sits on a live video feed, not on an app surface, so the
 * neutral chrome stays fixed white/black alphas via withAlpha (as it did
 * before): a theme-following overlay would vanish against half the frames a
 * jobsite produces. The one themed element is the Done affordance, which uses
 * chrome.brand so the primary action matches the rest of the app.
 */

const MAX_VISIBLE_SHOTS = 3;

export default function CameraOverlay({
  shots = [],
  capturing = false,
  showLensToggle = false,
  backLens = 'ultra',
  onSelectLens,
  onFlip,
  onShutter,
  onDeleteShot,
  onClose,
}) {
  // Newest first — the CP's most recent frame is the one they want to confirm.
  const newestFirst = [...shots].reverse();
  const visible = newestFirst.slice(0, MAX_VISIBLE_SHOTS);
  const hidden = newestFirst.length - visible.length;

  // In-camera review: position (into newestFirst) of the shot the CP is
  // previewing full-screen, or null when the strip is just the corner stack.
  // Kept so a CP can confirm and DELETE a bad frame without leaving the camera.
  const [previewIndex, setPreviewIndex] = useState(null);
  const previewShot = previewIndex == null ? null : newestFirst[previewIndex];
  const canPrev = previewIndex != null && previewIndex > 0;
  const canNext = previewIndex != null && previewIndex < newestFirst.length - 1;

  const openPreview = (idx, shot) => {
    // Pending shots have no decoded uri yet — nothing to review.
    if (shot?.pending) return;
    setPreviewIndex(idx);
  };

  const handleDeletePreview = () => {
    if (previewShot?.id != null) onDeleteShot?.(previewShot.id);
    // The list shrinks by one after the parent drops it. Close if that was the
    // last frame; otherwise keep the index in range (step back off the end).
    if (newestFirst.length <= 1) { setPreviewIndex(null); return; }
    setPreviewIndex((idx) => Math.min(idx, newestFirst.length - 2));
  };

  return (
    <SafeAreaView style={styles.overlay} edges={['top', 'bottom']} pointerEvents="box-none">
      <View style={styles.topBar}>
        <Pressable
          style={styles.iconBtn}
          onPress={onClose}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Close camera"
        >
          <X size={26} strokeWidth={2} color="#fff" />
        </Pressable>
      </View>

      {/* Session shots, stacked in the corner. Tappable: a tile opens the
          full-screen review below, where the CP can confirm or DELETE the
          frame without leaving the camera. A pending tile ignores the tap. */}
      {visible.length > 0 && (
        <View style={styles.shotStack}>
          {visible.map((shot, i) => (
            <Pressable
              key={shot.id ?? i}
              style={styles.shotTile}
              onPress={() => openPreview(i, shot)}
              disabled={shot.pending}
              accessibilityRole="button"
              accessibilityLabel={shot.pending ? 'Photo processing' : 'Review photo'}
            >
              {shot.pending ? (
                // Placeholder while the background compress runs. Rendering the
                // RAW capture here would make the UI thread decode a full-size
                // sensor JPEG for a 56px tile, on every shot.
                <View style={styles.shotPending}>
                  <ActivityIndicator size="small" color="#fff" />
                </View>
              ) : (
                <Image source={{ uri: shot.uri }} style={styles.shotImg} />
              )}
              {/* Item 3: delete straight from the thumbnail — a nested Pressable
                  captures the touch so the tile's open-preview onPress doesn't
                  also fire. Hidden while pending (no id / nothing to drop yet). */}
              {!shot.pending && shot.id != null && (
                <Pressable
                  style={styles.shotDelete}
                  hitSlop={8}
                  onPress={() => onDeleteShot?.(shot.id)}
                  accessibilityRole="button"
                  accessibilityLabel="Delete photo"
                >
                  <X size={12} strokeWidth={3} color="#fff" />
                </Pressable>
              )}
            </Pressable>
          ))}
          {hidden > 0 && (
            // Opens the first frame not shown in the corner stack, so every
            // shot in the session stays reachable for review/delete.
            <Pressable
              style={[styles.shotTile, styles.shotMore]}
              onPress={() => openPreview(MAX_VISIBLE_SHOTS, newestFirst[MAX_VISIBLE_SHOTS])}
              accessibilityRole="button"
              accessibilityLabel={`Review ${hidden} more photos`}
            >
              <Text style={styles.shotMoreText}>+{hidden}</Text>
            </Pressable>
          )}
        </View>
      )}

      <View style={styles.bottomStack}>
        {showLensToggle && (
          <View style={styles.lensRow}>
            <Pressable
              style={[styles.lensChip, backLens === 'ultra' && styles.lensChipActive]}
              onPress={() => onSelectLens?.('ultra')}
            >
              <Text style={[styles.lensText, backLens === 'ultra' && styles.lensTextActive]}>0.5×</Text>
            </Pressable>
            <Pressable
              style={[styles.lensChip, backLens === 'wide' && styles.lensChipActive]}
              onPress={() => onSelectLens?.('wide')}
            >
              <Text style={[styles.lensText, backLens === 'wide' && styles.lensTextActive]}>1×</Text>
            </Pressable>
          </View>
        )}

        {/* Three equal cells so the shutter stays centred no matter how wide
            the Done pill grows with its count. */}
        <View style={styles.bottomBar}>
          <View style={styles.barCellLeft}>
            <Pressable
              style={styles.iconBtn}
              onPress={onFlip}
              hitSlop={12}
              disabled={capturing}
              accessibilityRole="button"
              accessibilityLabel="Flip camera"
            >
              <RefreshCw size={24} strokeWidth={2} color="#fff" />
            </Pressable>
          </View>

          <View style={styles.barCellCenter}>
            <Pressable
              style={styles.shutter}
              onPress={onShutter}
              disabled={capturing}
              accessibilityRole="button"
              accessibilityLabel="Take photo"
            >
              {capturing ? <ActivityIndicator color="#000" /> : <View style={styles.shutterInner} />}
            </Pressable>
          </View>

          <View style={styles.barCellRight}>
            <Pressable
              // brand tint applied INLINE, not baked into StyleSheet.create:
              // chrome.brand is a theme getter, and a module-scope StyleSheet
              // would freeze whichever theme happened to be active at import.
              style={[styles.doneBtn, { backgroundColor: chrome.brand }]}
              onPress={onClose}
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel={shots.length > 0 ? `Done, ${shots.length} photos` : 'Done'}
            >
              <Check size={16} strokeWidth={2.5} color="#fff" />
              <Text style={styles.doneText}>
                {shots.length > 0 ? `Done (${shots.length})` : 'Done'}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>

      {/* Full-screen review of one session frame, layered over the live
          preview. Confirm it, page to a sibling, or delete it — all without
          dismissing the camera. Absolute-fills the overlay above the chrome. */}
      {previewShot && (
        <View style={styles.previewLayer}>
          <Image
            source={{ uri: previewShot.uri }}
            style={styles.previewImage}
            resizeMode="contain"
          />

          {/* Nav is rendered BEFORE the top bar so the top bar wins z-order.
              previewNav full-screen `box-none` pass-through to a lower sibling is
              unreliable on Android — it was eating the close/delete taps. Its
              track now also starts BELOW the top bar (styles.previewNav.top) so
              the two never overlap geometrically. */}
          {newestFirst.length > 1 && (
            <View style={styles.previewNav} pointerEvents="box-none">
              <Pressable
                style={[styles.navBtn, !canPrev && styles.navBtnDisabled]}
                onPress={() => canPrev && setPreviewIndex((idx) => idx - 1)}
                disabled={!canPrev}
                hitSlop={12}
                accessibilityRole="button"
                accessibilityLabel="Previous photo"
              >
                <ChevronLeft size={28} strokeWidth={2} color="#fff" />
              </Pressable>
              <Pressable
                style={[styles.navBtn, !canNext && styles.navBtnDisabled]}
                onPress={() => canNext && setPreviewIndex((idx) => idx + 1)}
                disabled={!canNext}
                hitSlop={12}
                accessibilityRole="button"
                accessibilityLabel="Next photo"
              >
                <ChevronRight size={28} strokeWidth={2} color="#fff" />
              </Pressable>
            </View>
          )}

          {/* Top bar LAST → highest z-order, so close (X) + delete (trash) always
              win the touch over the nav layer. */}
          <View style={styles.previewTop}>
            <Pressable
              style={styles.iconBtn}
              onPress={() => setPreviewIndex(null)}
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel="Close review"
            >
              <X size={24} strokeWidth={2} color="#fff" />
            </Pressable>
            <Text style={styles.previewCount}>
              {previewIndex + 1} / {newestFirst.length}
            </Text>
            <Pressable
              style={[styles.iconBtn, styles.previewDeleteBtn]}
              onPress={handleDeletePreview}
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel="Delete photo"
            >
              <Trash2 size={22} strokeWidth={2} color="#fff" />
            </Pressable>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'space-between',
    backgroundColor: 'transparent',
  },
  topBar: { flexDirection: 'row', justifyContent: 'flex-start', paddingHorizontal: 20, paddingTop: 8 },

  shotStack: { position: 'absolute', left: 20, bottom: 170, gap: 8 },
  shotTile: {
    width: 56, height: 56, borderRadius: 10, overflow: 'hidden',
    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.7),
    backgroundColor: withAlpha('#000000', 0.5),
    alignItems: 'center', justifyContent: 'center',
  },
  shotImg: { width: '100%', height: '100%' },
  shotDelete: {
    position: 'absolute', top: 2, right: 2,
    width: 18, height: 18, borderRadius: 9,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: withAlpha('#ef4444', 0.9),
  },
  shotPending: { width: '100%', height: '100%', alignItems: 'center', justifyContent: 'center' },
  shotMore: { backgroundColor: withAlpha('#000000', 0.6) },
  shotMoreText: { color: '#fff', fontSize: 13, fontWeight: '700' },

  bottomStack: { alignItems: 'center', gap: 16, paddingBottom: 24 },
  lensRow: {
    flexDirection: 'row', gap: 8,
    backgroundColor: withAlpha('#000000', 0.4), borderRadius: 999, padding: 4,
  },
  lensChip: {
    minWidth: 44, paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 999, alignItems: 'center',
  },
  lensChipActive: { backgroundColor: withAlpha('#ffffff', 0.9) },
  lensText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  lensTextActive: { color: '#000' },

  bottomBar: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, width: '100%' },
  barCellLeft: { flex: 1, alignItems: 'flex-start' },
  barCellCenter: { alignItems: 'center' },
  barCellRight: { flex: 1, alignItems: 'flex-end' },

  iconBtn: {
    width: 50, height: 50, borderRadius: 25,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: withAlpha('#000000', 0.35),
  },
  shutter: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: withAlpha('#ffffff', 0.25),
    borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: { width: 56, height: 56, borderRadius: 28, backgroundColor: '#fff' },
  doneBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 16, paddingVertical: 12, borderRadius: 999,
  },
  doneText: { color: '#fff', fontSize: 14, fontWeight: '700' },

  // ── In-camera review ──
  previewLayer: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: withAlpha('#000000', 0.92),
    justifyContent: 'center',
    alignItems: 'center',
  },
  previewImage: { width: '100%', height: '100%' },
  previewTop: {
    position: 'absolute', top: 0, left: 0, right: 0,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingTop: 8,
  },
  previewCount: { color: '#fff', fontSize: 14, fontWeight: '700' },
  previewDeleteBtn: { backgroundColor: withAlpha('#ef4444', 0.85) },
  previewNav: {
    // Starts below the top bar (X/trash live at top:0..~64) so the nav track
    // never overlaps them — defense-in-depth alongside the render-order fix.
    position: 'absolute', left: 0, right: 0, top: 72, bottom: 0,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 12,
  },
  navBtn: {
    width: 48, height: 48, borderRadius: 24,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: withAlpha('#000000', 0.35),
  },
  navBtnDisabled: { opacity: 0.25 },
});
