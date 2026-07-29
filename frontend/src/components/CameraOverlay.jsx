import React from 'react';
import {
  View, Text, Image, Pressable, StyleSheet, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { X, RefreshCw, Check } from 'lucide-react-native';
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
  onClose,
}) {
  // Newest first — the CP's most recent frame is the one they want to confirm.
  const newestFirst = [...shots].reverse();
  const visible = newestFirst.slice(0, MAX_VISIBLE_SHOTS);
  const hidden = newestFirst.length - visible.length;

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

      {/* Session shots, stacked in the corner. Non-interactive: the CP manages
          photos in the log, not here — this is confirmation that the shutter
          fired, which the old flow never gave. */}
      {visible.length > 0 && (
        <View style={styles.shotStack} pointerEvents="none">
          {visible.map((shot, i) => (
            <View key={shot.id ?? i} style={styles.shotTile}>
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
            </View>
          ))}
          {hidden > 0 && (
            <View style={[styles.shotTile, styles.shotMore]}>
              <Text style={styles.shotMoreText}>+{hidden}</Text>
            </View>
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
});
