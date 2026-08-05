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
  // MEASURED CHANGE (camera diag): rear default was 'ultra' (ultra-wide), and the
  // device measured the ultra-wide REAR capture hanging 60s+ (never returned)
  // while the front returned in ~5s. The ultra-wide is a distinct physical sensor
  // with a slower/quirkier still path; the main WIDE sensor is the fast, reliable
  // one and is what a jobsite compliance photo should use. Change ONE variable
  // (ultra→wide) and re-measure before touching the format criteria — so we learn
  // whether the hang was the ultra-wide sensor or the format selection.
  const [backLens, setBackLens] = useState('wide'); // 'ultra' | 'wide' — default main wide sensor
  const [capturing, setCapturing] = useState(false);
  const [zoom, setZoom] = useState(1);
  // TEMP camera-speed diagnostic — remove after the bottleneck is found. Shows the
  // sensor-read time (takePhoto) and the total in-modal time on-screen, so we
  // MEASURE where the 3-5s goes instead of guessing at the format again.
  const [captureTiming, setCaptureTiming] = useState(null);
  const currentZoomRef = useRef(1);
  const baseZoomRef = useRef(1);
  // TEMP (item 6): guards the one-time capability dump below.
  const loggedFormatsRef = useRef(false);

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

  // ── item 6: per-device capture tuning to freeze hand-held motion ──────────
  // CRITERIA-based format selection (priority order) — every phone resolves its
  // OWN best format from the same code, never a hardcoded index. useCameraFormat
  // sorts the device's formats by closeness to each criterion in turn, so an
  // older/weaker device (iPhone 6s, midrange Android) that can't satisfy a
  // criterion silently falls back to its nearest match instead of failing.
  // SPEED (measured variable, this round): photoQualityBalance:'speed' did NOT
  // move the ~3s takePhoto, so the last remaining format constraint —
  // `photoResolution: 1920x1080` — is the next single variable to peel. Targeting
  // a specific still size can force useCameraFormat onto a format whose capture
  // needs a downscale/re-encode. Passing NO format lets vision-camera use the
  // device's own default still format (its native-fast path). `format` is then
  // undefined; fps falls back to undefined (Camera default) and the [CAM] log
  // just prints undefined dims — both harmless. Re-measure takePhoto after this.
  const format = undefined;

  // Shutter-speed FLOOR: stream at up to 60fps so each frame's exposure time is
  // capped near 1/60s — enough to freeze a hand-held site photo. Clamped to the
  // chosen format's own maxFps, so a phone that tops out at 30fps just gets 30
  // (still far better than an uncapped multi-second interior exposure).
  const fps = format ? Math.min(60, format.maxFps) : undefined;

  // Exposure FLOOR: bias one stop under so the AE targets a faster shutter in dim
  // interior light (the sensor holds brightness by raising gain/ISO instead of
  // lengthening the exposure). Clamped to the device's supported range, so a
  // device that reports no negative range gets 0 — a harmless no-op.
  const exposure = device ? Math.max(device.minExposure ?? 0, -1) : undefined;

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

  // ─── TEMP (item 6 — motion blur diagnosis) ────────────────────────────────
  // One-time dump of the MOUNTED back device's real capabilities so the Pixel
  // 10 Pro's actual format list can be read off a preview build, and the final
  // useCameraFormat targets (fps floor / photoHdr / low-light-boost) chosen
  // from data instead of a guess. supportsPhotoHdr is PER-FORMAT in
  // vision-camera (there is no device.supportsPhotoHdr), so it is logged on
  // each format row. REMOVE this block once the format is locked in.
  useEffect(() => {
    if (!device || loggedFormatsRef.current) return;
    loggedFormatsRef.current = true;
    const fmts = device.formats || [];
    console.log(
      `[item6] device id=${device.id} position=${device.position}`,
      `supportsLowLightBoost=${device.supportsLowLightBoost}`,
      `hasFlash=${device.hasFlash} minZoom=${device.minZoom} maxZoom=${device.maxZoom}`,
      `formats=${fmts.length}`,
    );
    fmts.forEach((f, i) => {
      console.log(
        `[item6] fmt#${i}`,
        `photo=${f.photoWidth}x${f.photoHeight}`,
        `video=${f.videoWidth}x${f.videoHeight}`,
        `fps=${f.minFps}-${f.maxFps}`,
        `iso=${f.minISO}-${f.maxISO}`,
        `supportsPhotoHdr=${f.supportsPhotoHdr}`,
        `supportsVideoHdr=${f.supportsVideoHdr}`,
      );
    });
  }, [device]);
  // ─── END TEMP (item 6) ────────────────────────────────────────────────────

  // LENS DEFAULT (item 1 — REVERTED): the "open at widest" effect defaulted this
  // device to ultra-wide, and ultra-wide takePhoto is BROKEN here (won't capture)
  // even with photoQualityBalance:'speed' — the same failure ultra-wide had
  // before. Measured verdict: on this device the widest lens that actually
  // CAPTURES is the WIDE (1×) lens, so the default stays 'wide' (useState above).
  // A wider VIEW, if ever wanted, comes from zooming OUT on the wide lens — never
  // by auto-switching to the ultra-wide sensor that can't take a photo. The
  // [CAM] shutter log (before takePhoto) records the device+lens+format attempted,
  // and the `vision-camera capture failed:` warn in the catch records the error —
  // together they show WHY ultra-wide fails, but the fix is: default to the lens
  // that works.

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

  // Item 3: remove the 0.5×/1× chips entirely. The camera opens at ultra-wide by
  // default (backLens='ultra'; a phone with no ultra-wide falls back to its
  // widest device via the zoom logic below), and zoom is pinch-only — no chips.
  const showLensToggle = false;

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
    const t0 = Date.now();
    // Logged BEFORE takePhoto because a hanging capture never reaches the timing
    // badge — this line is the only record of WHICH device + format the stuck
    // capture used. photo=WxH is the still resolution useCameraFormat chose.
    console.log('[CAM] shutter device=%s pos=%s lens=%s fmt=%sx%s fps=%s',
      device?.id, position, backLens, format?.photoWidth, format?.photoHeight, fps);
    try {
      // v4 TakePhotoOptions is small: flash + enableShutterSound are the only
      // Android-relevant knobs (qualityPrioritization/skipMetadata/enableAuto
      // Stabilization were removed — speed now lives on the photoQualityBalance
      // PROP above). Shutter sound off shaves the system click's tail.
      const photo = await camera.current.takePhoto({ flash: 'off', enableShutterSound: false });
      const tShot = Date.now();
      const srcUri = photo.path.startsWith('file://') ? photo.path : `file://${photo.path}`;
      onCapture(srcUri);
      const tHandoff = Date.now();
      // takePhoto = pure sensor read (unmovable); handoff = everything else in the
      // modal. If takePhoto is the 3-5s, it's format/sensor; if it's <1s the delay
      // lives in the CALLER's compression/thumbnail path, not here.
      const timing = { take: tShot - t0, handoff: tHandoff - tShot, total: tHandoff - t0 };
      console.log('[CAM] takePhoto=%dms handoff=%dms total=%dms', timing.take, timing.handoff, timing.total);
      setCaptureTiming(timing);
    } catch (e) {
      console.warn('vision-camera capture failed:', e?.message);
    } finally {
      setCapturing(false);
    }
  }, [capturing, onCapture, device, position, backLens, format, fps]);

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
        format={format}
        fps={fps}
        exposure={exposure}
        photoHdr={false}
        lowLightBoost={device?.supportsLowLightBoost === true}
        isActive={active && appActive}
        photo={true}
        // SPEED (measured variable): v4 moved the still speed/quality trade-off
        // from the takePhoto option `qualityPrioritization` (removed) to THIS
        // Camera prop, which defaults to 'balanced' — the reason takePhoto sat at
        // ~2000ms. 'speed' minimizes capture latency (CameraX CAPTURE_MODE_
        // MINIMIZE_LATENCY on Android). This is the single change to re-measure.
        photoQualityBalance="speed"
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
      {captureTiming && (
        <View pointerEvents="none" style={styles.timingBadge}>
          <Text style={styles.timingText}>
            takePhoto {captureTiming.take}ms · handoff {captureTiming.handoff}ms · total {captureTiming.total}ms
          </Text>
        </View>
      )}
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
  // TEMP camera-speed diagnostic overlay (top-center). Remove with the timing state.
  timingBadge: {
    position: 'absolute', top: 48, alignSelf: 'center', zIndex: 200, elevation: 200,
    backgroundColor: 'rgba(0,0,0,0.7)', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8,
  },
  timingText: { color: '#f59e0b', fontSize: 12, fontWeight: '600' },
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
