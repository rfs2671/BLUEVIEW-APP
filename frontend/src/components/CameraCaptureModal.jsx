import React, { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import {
  Modal, View, Text, Pressable, StyleSheet, ActivityIndicator, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera';
import * as ImageManipulator from 'expo-image-manipulator';
import * as FileSystem from 'expo-file-system';
import { X, RefreshCw } from 'lucide-react-native';

/**
 * In-process jobsite camera (react-native-vision-camera).
 *
 * Why vision-camera and not the OS picker: launchCameraAsync hands off to
 * an external camera Activity, which backgrounds our app; under memory
 * pressure Android kills the process and the return forces a full React
 * Native cold boot (the 20-30s "slow camera"). <Camera> is a MOUNTED,
 * in-process native view — the app never leaves the foreground, so the
 * kill/cold-boot root cause stays fixed. Capture is instant.
 *
 * Lens: a user-facing toggle (0.5× ultra-wide ↔ 1× wide) on the back
 * camera, shown ONLY where a real ultra-wide lens exists; single-lens
 * phones just use the wide lens with no toggle. Default = ultra-wide.
 *
 * Output: every photo is downscaled + compressed to <= 150KB (expo-image-
 * manipulator) before onCapture(uri) — keeps the inline-base64 save flow
 * fast and protects the PR #54 fix from payload bloat.
 *
 * Contract unchanged: onCapture(uri) gets a file:// URI, fed into the
 * exact same setActivities append in daily_jobsite.jsx.
 *
 * vision-camera has no web support, so the camera surface only mounts on
 * native when visible (the web photo path uses expo-image-picker and
 * never opens this modal).
 */

const MAX_BYTES = 150 * 1024; // hard cap per photo

// Resize to a sensible width and compress until the JPEG lands <= 150KB.
// One quality pass rarely guarantees the cap, so we recompress: drop
// quality first, then shrink dimensions, until under cap or out of tries.
async function compressUnderCap(srcUri) {
  let width = 1280;
  let quality = 0.6;
  let out = await ImageManipulator.manipulateAsync(
    srcUri,
    [{ resize: { width } }],
    { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
  );
  let info = await FileSystem.getInfoAsync(out.uri);
  let tries = 0;
  while ((info?.size ?? 0) > MAX_BYTES && tries < 5) {
    tries += 1;
    if (quality > 0.3) {
      quality = Math.max(0.3, quality - 0.15);
    } else {
      width = Math.round(width * 0.8); // dimensions once quality floor is hit
    }
    out = await ImageManipulator.manipulateAsync(
      srcUri,
      [{ resize: { width } }],
      { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
    );
    info = await FileSystem.getInfoAsync(out.uri);
  }
  return out.uri;
}

// The vision-camera surface. Extracted so its hooks only run when the
// modal is open on native — never on web, never while closed.
function CameraSurface({ onCapture, onClose }) {
  const camera = useRef(null);
  const { hasPermission, requestPermission } = useCameraPermission();
  const [position, setPosition] = useState('back'); // 'back' | 'front'
  const [backLens, setBackLens] = useState('ultra'); // 'ultra' | 'wide' — default ultra-wide
  const [capturing, setCapturing] = useState(false);

  // Requesting a single physical device returns the best match; on phones
  // without an ultra-wide it falls back to the wide lens (so the returned
  // device's physicalDevices won't actually include ultra-wide).
  const uwDevice = useCameraDevice('back', { physicalDevices: ['ultra-wide-angle-camera'] });
  const wideDevice = useCameraDevice('back', { physicalDevices: ['wide-angle-camera'] });
  const frontDevice = useCameraDevice('front');

  // Genuine ultra-wide only — definitive check against the returned device.
  const hasUltraWide = !!uwDevice?.physicalDevices?.includes('ultra-wide-angle-camera');

  const device = useMemo(() => {
    if (position === 'front') return frontDevice;
    if (backLens === 'ultra' && hasUltraWide) return uwDevice;
    return wideDevice ?? uwDevice;
  }, [position, backLens, hasUltraWide, uwDevice, wideDevice, frontDevice]);

  useEffect(() => {
    if (!hasPermission) requestPermission();
  }, [hasPermission]);

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
    <View style={styles.container}>
      <Camera
        ref={camera}
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={true}
        photo={true}
      />
      <SafeAreaView style={styles.overlay} edges={['top', 'bottom']}>
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
  );
}

export default function CameraCaptureModal({ visible, onClose, onCapture }) {
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        {visible && Platform.OS !== 'web' ? (
          <CameraSurface onCapture={onCapture} onClose={onClose} />
        ) : null}
      </View>
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
    backgroundColor: 'rgba(0,0,0,0.4)', borderRadius: 999, padding: 4,
  },
  lensChip: {
    minWidth: 44, paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 999, alignItems: 'center',
  },
  lensChipActive: { backgroundColor: 'rgba(255,255,255,0.9)' },
  lensText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  lensTextActive: { color: '#000' },
  bottomBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 36, width: '100%',
  },
  iconBtn: {
    width: 50, height: 50, borderRadius: 25,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  shutter: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: 'rgba(255,255,255,0.25)',
    borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: { width: 56, height: 56, borderRadius: 28, backgroundColor: '#fff' },
});
