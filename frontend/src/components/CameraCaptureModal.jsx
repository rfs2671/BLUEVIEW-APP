import React, { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import {
  Modal, View, Text, Pressable, StyleSheet, ActivityIndicator, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera';
import * as ImageManipulator from 'expo-image-manipulator';
import * as FileSystem from 'expo-file-system';
import { X, RefreshCw } from 'lucide-react-native';
import { GestureHandlerRootView, Gesture, GestureDetector } from 'react-native-gesture-handler';
import { withAlpha } from '../styles/semanticColors';

/**
 * In-process jobsite camera (react-native-vision-camera). <Camera> is a
 * MOUNTED native view — no external Activity handoff — so the app never
 * backgrounds and the process-kill / cold-boot defect stays fixed.
 *
 * Lens: a 0.5× ultra-wide ⇄ 1× wide toggle on the back camera, shown only
 * where ultra-wide genuinely exists. Pinch-to-zoom adjusts WITHIN the
 * active lens. Output is downscaled/compressed to <= 150KB per photo.
 */

const MAX_BYTES = 150 * 1024;

async function compressUnderCap(srcUri) {
  let width = 1280;
  let quality = 0.6;
  let out = await ImageManipulator.manipulateAsync(
    srcUri, [{ resize: { width } }],
    { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
  );
  let info = await FileSystem.getInfoAsync(out.uri);
  let tries = 0;
  while ((info?.size ?? 0) > MAX_BYTES && tries < 5) {
    tries += 1;
    if (quality > 0.3) quality = Math.max(0.3, quality - 0.15);
    else width = Math.round(width * 0.8);
    out = await ImageManipulator.manipulateAsync(
      srcUri, [{ resize: { width } }],
      { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
    );
    info = await FileSystem.getInfoAsync(out.uri);
  }
  return out.uri;
}

/**
 * Pre-requests camera permission from the SCREEN, not from the capture tap.
 *
 * CameraSurface below also requests permission on mount, but it only mounts
 * once the modal is already open — so on a fresh install the OS dialog landed
 * squarely between the user's tap and the preview, stalling the open for as
 * long as it took them to read and answer it.
 *
 * Calling this hook where the screen mounts moves that dialog to screen load,
 * so by the time the camera is tapped the permission is already resolved. It
 * deliberately does NOT touch <Camera>: this is permission only, not a warm
 * camera. The device is still acquired when the modal opens.
 *
 * Platform-split: the .web.jsx sibling exports a no-op of the same name, so
 * screens can call this unconditionally without pulling the native
 * vision-camera module into the web bundle.
 */
export function useCameraPrewarmPermission() {
  const { hasPermission, requestPermission } = useCameraPermission();
  useEffect(() => {
    if (!hasPermission) requestPermission();
  }, [hasPermission]);
  return hasPermission;
}

function CameraSurface({ onCapture, onClose }) {
  const camera = useRef(null);
  const { hasPermission, requestPermission } = useCameraPermission();
  const [position, setPosition] = useState('back'); // 'back' | 'front'
  const [backLens, setBackLens] = useState('ultra'); // 'ultra' | 'wide' — default ultra-wide
  const [capturing, setCapturing] = useState(false);
  const [zoom, setZoom] = useState(1);
  const currentZoomRef = useRef(1);
  const baseZoomRef = useRef(1);

  const uwDevice = useCameraDevice('back', { physicalDevices: ['ultra-wide-angle-camera'] });
  const wideDevice = useCameraDevice('back', { physicalDevices: ['wide-angle-camera'] });
  const frontDevice = useCameraDevice('front');

  // Two ways a phone exposes ultra-wide:
  //   A) a DISTINCT physical ultra-wide device (different id from the wide)
  //   B) ZOOM below 1× on the main back multi-cam device (minZoom < 1)
  const uwIsDistinct = !!(uwDevice && wideDevice && uwDevice.id !== wideDevice.id
    && uwDevice.physicalDevices?.includes('ultra-wide-angle-camera'));
  const backBase = wideDevice ?? uwDevice;
  const uwViaZoom = !uwIsDistinct && (backBase?.minZoom ?? 1) < 0.99;
  const hasUltraWide = uwIsDistinct || uwViaZoom;

  const device = position === 'front'
    ? frontDevice
    : (uwIsDistinct && backLens === 'ultra' ? uwDevice : backBase);

  useEffect(() => {
    if (!hasPermission) requestPermission();
  }, [hasPermission]);

  // Framing for the current lens: distinct-device UW → device neutral;
  // zoom-based UW → minZoom for ultra, neutral (1×) for wide.
  useEffect(() => {
    let z;
    if (position === 'front') z = frontDevice?.neutralZoom ?? 1;
    else if (uwIsDistinct) z = device?.neutralZoom ?? 1;
    else if (uwViaZoom) z = backLens === 'ultra' ? (backBase?.minZoom ?? 1) : (backBase?.neutralZoom ?? 1);
    else z = device?.neutralZoom ?? 1;
    if (Number.isFinite(z)) { currentZoomRef.current = z; setZoom(z); }
  }, [device, position, backLens, uwIsDistinct, uwViaZoom]);

  useEffect(() => { currentZoomRef.current = zoom; }, [zoom]);

  // Pinch-to-zoom within the active lens. runOnJS(true) forces the callback
  // onto the JS thread — without it, reanimated's babel plugin workletizes
  // the callback and calling setZoom from the UI thread crashes the app.
  const pinch = useMemo(() => Gesture.Pinch()
    .runOnJS(true)
    .onBegin(() => { baseZoomRef.current = currentZoomRef.current; })
    .onUpdate((e) => {
      const min = device?.minZoom ?? 1;
      const max = device?.maxZoom ?? 1;
      const next = baseZoomRef.current * e.scale;
      if (!Number.isFinite(next)) return;
      setZoom(Math.min(max, Math.max(min, next)));
    }), [device]);

  const showLensToggle = position === 'back' && hasUltraWide;

  const handleShutter = useCallback(async () => {
    if (!camera.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await camera.current.takePhoto({ flash: 'off', qualityPrioritization: 'speed' });
      const srcUri = photo.path.startsWith('file://') ? photo.path : `file://${photo.path}`;
      const smallUri = await compressUnderCap(srcUri);
      onCapture(smallUri);
      onClose();
    } catch (e) {
      console.warn('vision-camera capture failed:', e?.message);
    } finally {
      setCapturing(false);
    }
  }, [capturing, onCapture, onClose]);

  if (!hasPermission) {
    return (
      <SafeAreaView style={styles.center} edges={['top', 'bottom']}>
        <Text style={styles.msg}>Camera access is required to take photos.</Text>
        <Pressable style={styles.primaryBtn} onPress={requestPermission}>
          <Text style={styles.primaryBtnText}>Grant Access</Text>
        </Pressable>
        <Pressable style={styles.secondaryBtn} onPress={onClose}>
          <Text style={styles.secondaryBtnText}>Cancel</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  if (!device) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#fff" />
      </View>
    );
  }

  return (
    <GestureDetector gesture={pinch}>
    <View style={styles.container}>
      <Camera
        ref={camera}
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={true}
        photo={true}
        zoom={zoom}
        onError={(err) => {
          console.warn('vision-camera error:', err?.message);
          // Untested-OEM safety net: if a DISTINCT ultra-wide device
          // fails to start, drop to the wide lens so the user never sees
          // a dead/black camera. (The zoom-based UW path is unaffected —
          // it stays on the one back device.)
          if (uwIsDistinct && backLens === 'ultra') setBackLens('wide');
        }}
      />
      <SafeAreaView style={styles.overlay} edges={['top', 'bottom']} pointerEvents="box-none">
        <View style={styles.topBar}>
          <Pressable style={styles.iconBtn} onPress={onClose} hitSlop={12}>
            <X size={26} strokeWidth={2} color="#fff" />
          </Pressable>
        </View>

        <View style={styles.bottomStack}>
          {showLensToggle && (
            <View style={styles.lensRow}>
              <Pressable
                style={[styles.lensChip, backLens === 'ultra' && styles.lensChipActive]}
                onPress={() => setBackLens('ultra')}
              >
                <Text style={[styles.lensText, backLens === 'ultra' && styles.lensTextActive]}>0.5×</Text>
              </Pressable>
              <Pressable
                style={[styles.lensChip, backLens === 'wide' && styles.lensChipActive]}
                onPress={() => setBackLens('wide')}
              >
                <Text style={[styles.lensText, backLens === 'wide' && styles.lensTextActive]}>1×</Text>
              </Pressable>
            </View>
          )}

          <View style={styles.bottomBar}>
            <Pressable
              style={styles.iconBtn}
              onPress={() => setPosition((p) => (p === 'back' ? 'front' : 'back'))}
              hitSlop={12}
              disabled={capturing}
            >
              <RefreshCw size={24} strokeWidth={2} color="#fff" />
            </Pressable>

            <Pressable style={styles.shutter} onPress={handleShutter} disabled={capturing}>
              {capturing ? <ActivityIndicator color="#000" /> : <View style={styles.shutterInner} />}
            </Pressable>

            {/* Spacer to keep the shutter centered opposite the flip button. */}
            <View style={styles.iconBtn} />
          </View>
        </View>
      </SafeAreaView>
    </View>
    </GestureDetector>
  );
}

export default function CameraCaptureModal({ visible, onClose, onCapture }) {
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      {/* GestureHandlerRootView is required for gestures to work inside a
          RN Modal (the Modal is a separate native root). */}
      <GestureHandlerRootView style={styles.container}>
        {visible && Platform.OS !== 'web' ? (
          <CameraSurface onCapture={onCapture} onClose={onClose} />
        ) : null}
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#000' },
  msg: { color: '#fff', fontSize: 15, textAlign: 'center', marginBottom: 24, lineHeight: 22 },
  primaryBtn: {
    backgroundColor: '#3b82f6', paddingHorizontal: 28, paddingVertical: 12,
    borderRadius: 8, marginBottom: 12,
  },
  primaryBtnText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  secondaryBtn: { paddingHorizontal: 28, paddingVertical: 12 },
  secondaryBtnText: { color: '#94a3b8', fontSize: 15 },

  overlay: { ...StyleSheet.absoluteFillObject, justifyContent: 'space-between', backgroundColor: 'transparent' },
  topBar: { flexDirection: 'row', justifyContent: 'flex-start', paddingHorizontal: 20, paddingTop: 8 },

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
  bottomBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 36, width: '100%',
  },
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
});
