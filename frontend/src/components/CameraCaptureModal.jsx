import React, { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import {
  AppState, BackHandler, View, Text, Pressable, StyleSheet, ActivityIndicator, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera';
import { GestureHandlerRootView, Gesture, GestureDetector } from 'react-native-gesture-handler';
import CameraOverlay from './CameraOverlay';

/**
 * In-process jobsite camera (react-native-vision-camera). <Camera> is a
 * MOUNTED native view — no external Activity handoff — so the app never
 * backgrounds and the process-kill / cold-boot defect stays fixed.
 *
 * Lens: a 0.5× ultra-wide ⇄ 1× wide toggle on the back camera, shown only
 * where ultra-wide genuinely exists. Pinch-to-zoom adjusts WITHIN the
 * active lens.
 *
 * KEEP-SHOOTING. The camera no longer closes on the shutter and no longer
 * compresses on the shutter. Capture hands the raw URI straight to the caller
 * and re-arms; the caller compresses in the background and passes the session's
 * photos back in via `shots` so they stack in the corner of the preview. The CP
 * dismisses with Done (or X) when they are finished, not once per photo.
 *
 * The chrome lives in CameraOverlay — see that file for why.
 */

/**
 * Pre-requests camera permission from the SCREEN, not from the capture tap.
 *
 * CameraSurface below also requests permission on mount, but it only mounts
 * once the modal is already open — so on a fresh install the OS dialog landed
 * squarely between the user's tap and the preview, stalling the open for as
 * long as it took them to read and answer it.
 *
 * Calling this hook where the screen mounts moves that dialog to screen load,
 * so by the time the camera is tapped the permission is already resolved.
 *
 * Kept even though the surface below is now mounted (and therefore already
 * requests permission) from screen mount: this hook is what guarantees the
 * behaviour if the pre-warm commit is ever reverted on its own.
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

function CameraSurface({ active, shots, onCapture, onDeleteShot, onClose }) {
  const camera = useRef(null);
  const { hasPermission, requestPermission } = useCameraPermission();
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');
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

  // A warm camera must not survive backgrounding: VisionCamera wants isActive
  // false when the app is not foregrounded, or the OS tears the session down
  // underneath it and the preview returns black.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => setAppActive(s === 'active'));
    return () => sub.remove();
  }, []);

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

  /**
   * NON-BLOCKING. This used to be:
   *
   *     await takePhoto()  ->  await compressUnderCap()  ->  onCapture  ->  onClose
   *
   * so the modal stayed up, frozen on a live preview with a spinner in the
   * shutter, for the whole resize/re-encode ladder — and then vanished, forcing
   * a fresh tap (and another scroll to the button) for the next photo.
   *
   * Now the ONLY await on the path is takePhoto itself, which is the sensor
   * read and cannot be moved. The raw URI is handed up immediately, the shutter
   * re-arms, and the camera stays open. Compression is the caller's problem and
   * runs in the background; its progress comes back through `shots`.
   */
  const handleShutter = useCallback(async () => {
    if (!camera.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await camera.current.takePhoto({ flash: 'off', qualityPrioritization: 'speed' });
      const srcUri = photo.path.startsWith('file://') ? photo.path : `file://${photo.path}`;
      onCapture(srcUri);
    } catch (e) {
      console.warn('vision-camera capture failed:', e?.message);
    } finally {
      setCapturing(false);
    }
  }, [capturing, onCapture]);

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
        isActive={active && appActive}
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
      <CameraOverlay
        shots={shots}
        capturing={capturing}
        showLensToggle={showLensToggle}
        backLens={backLens}
        onSelectLens={setBackLens}
        onFlip={() => setPosition((p) => (p === 'back' ? 'front' : 'back'))}
        onShutter={handleShutter}
        onDeleteShot={onDeleteShot}
        onClose={onClose}
      />
    </View>
    </GestureDetector>
  );
}

/**
 * PRE-WARMED. This was an RN <Modal> whose child was gated on `visible`, so
 * the whole VisionCamera stack — device enumeration, native view mount,
 * session configuration, device acquisition — began only AFTER the tap.
 *
 * RN Modal cannot be pre-warmed: it does not render children while hidden. So
 * the surface is now a full-screen absolute overlay mounted for the lifetime
 * of the screen and merely hidden. What that buys, read from the library's
 * own native source rather than assumed:
 *
 *   iOS   — CameraSession.configure() acquires the device input and configures
 *           format/outputs in steps 1-9; checkIsActive() is step 10 and only
 *           calls captureSession.startRunning(). The device is held from
 *           mount, and the tap starts an already-configured session.
 *   Android — CameraSession.kt runs configureOutputs/configureCamera (CameraX
 *           bindToLifecycle) first and configureIsActive() fourth, which only
 *           moves a LifecycleRegistry between CREATED and RESUMED. The session
 *           graph is pre-built, but CameraX opens the physical device on the
 *           transition, so the device open is still on the tap. Warmer, not
 *           fully warm.
 *
 * Hidden state is opacity 0 + pointerEvents none, deliberately NOT
 * display:'none' and not a zero-size box — VisionCamera needs a laid-out,
 * non-zero surface to configure against. isActive stays false while hidden, so
 * the sensor is not streaming and the warm surface costs no real battery.
 *
 * The overlay must be rendered as a full-screen sibling (in daily_jobsite it
 * sits directly under AnimatedBackground, OUTSIDE the SafeAreaView) or its
 * absolute fill inherits the safe-area inset and the preview is not full-bleed.
 */
export default function CameraCaptureModal({ visible, shots, onClose, onCapture, onDeleteShot }) {
  // Replaces Modal's onRequestClose, which handled the Android back button.
  useEffect(() => {
    if (!visible) return undefined;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      onClose();
      return true;
    });
    return () => sub.remove();
  }, [visible, onClose]);

  if (Platform.OS === 'web') return null;

  return (
    <View
      style={[
        StyleSheet.absoluteFill,
        visible ? styles.overlayShown : styles.overlayHidden,
      ]}
      pointerEvents={visible ? 'auto' : 'none'}
      accessibilityElementsHidden={!visible}
      importantForAccessibility={visible ? 'auto' : 'no-hide-descendants'}
    >
      {/* GestureHandlerRootView is required for the pinch gesture to work in
          this detached overlay, as it was inside the Modal's native root. */}
      <GestureHandlerRootView style={styles.container}>
        <CameraSurface active={visible} shots={shots} onCapture={onCapture} onDeleteShot={onDeleteShot} onClose={onClose} />
      </GestureHandlerRootView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  // elevation only when shown: an elevated-but-invisible view still casts a
  // shadow on Android.
  overlayShown: { opacity: 1, zIndex: 100, elevation: 100 },
  overlayHidden: { opacity: 0, zIndex: -1, elevation: 0 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#000' },
  msg: { color: '#fff', fontSize: 15, textAlign: 'center', marginBottom: 24, lineHeight: 22 },
  primaryBtn: {
    backgroundColor: '#3b82f6', paddingHorizontal: 28, paddingVertical: 12,
    borderRadius: 8, marginBottom: 12,
  },
  primaryBtnText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  secondaryBtn: { paddingHorizontal: 28, paddingVertical: 12 },
  secondaryBtnText: { color: '#94a3b8', fontSize: 15 },
  // The capture chrome's styles moved with it, into CameraOverlay.
});
