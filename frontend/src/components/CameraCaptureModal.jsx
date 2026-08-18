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

// The value passed to <Camera> below, named rather than inlined so the one
// place it is set is obvious to anyone tuning camera performance later.
const PREVIEW_TYPE = 'texture-view';

function CameraSurface({ active, shots, onCapture, onDeleteShot, onClose }) {
  const camera = useRef(null);
  const { hasPermission, requestPermission } = useCameraPermission();
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');
  const [position, setPosition] = useState('back'); // 'back' | 'front'
  // ULTRA-WIDE IS THE DEFAULT — operator ruling. He uses it for every site
  // photo and finds it holds detail across a large site.
  //
  // THE OLD REASON FOR 'wide' NO LONGER STANDS. It was measured against
  // `takePhoto` hanging on the ultra-wide sensor — but that was measured while
  // `lowLightBoost` was routing the session through the NIGHT vendor extension,
  // which is the configuration that could not bind at all on this device.
  // Extensions routinely do not cover a phone's auxiliary physical cameras, so
  // "ultra-wide cannot capture" was very likely the same fault wearing a
  // different hat, and it was never re-measured with a session that configures.
  //
  // AND IT IS MOOT ON ANDROID: capture there is `takeSnapshot`, which reads
  // `previewView.bitmap` and never touches ImageCapture. Whatever the preview
  // shows, the snapshot gets — on any lens.
  //
  // A phone with no ultra-wide degrades to its widest available framing through
  // the zoom logic below; nothing here assumes the sensor exists.
  const [backLens, setBackLens] = useState('ultra'); // 'ultra' | 'wide'
  const [capturing, setCapturing] = useState(false);
  const [zoom, setZoom] = useState(1);
  // Numbers each capture, so a late `report` from an older shot is identifiable
  // in the log rather than being attributed to the current one.
  const shotSeqRef = useRef(0);

  const currentZoomRef = useRef(1);
  const baseZoomRef = useRef(1);

  const uwDevice = useCameraDevice('back', { physicalDevices: ['ultra-wide-angle-camera'] });
  const wideDevice = useCameraDevice('back', { physicalDevices: ['wide-angle-camera'] });
  const frontDevice = useCameraDevice('front');
  // UNFILTERED, and it is here only to be COMPARED against the two above.
  // vision-camera picks the best back device with no constraint, which is
  // normally the multi-camera spanning every lens. Nothing mounts it — see the
  // diagnostic below for why that is the question.
  const anyBackDevice = useCameraDevice('back');

  // `uwIsDistinct` now decides ONE thing: whether there is a separate ultra-wide
  // DEVICE worth mounting. Where the lens sits in the zoom range is no longer
  // its business — the framing effect below asks the mounted device how wide it
  // can go rather than how its lenses happen to be packaged.
  const uwIsDistinct = !!(uwDevice && wideDevice && uwDevice.id !== wideDevice.id
    && uwDevice.physicalDevices?.includes('ultra-wide-angle-camera'));
  const backBase = wideDevice ?? uwDevice;

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


  // SUPERSEDED. This block used to argue for defaulting to 'wide' because
  // ultra-wide `takePhoto` would not capture. That measurement was taken with
  // the NIGHT vendor extension in the session configuration — the one that
  // could not bind at all — and it was never repeated once the session could
  // configure. It is also moot on Android, where capture is takeSnapshot and
  // never reaches ImageCapture. The default is 'ultra' by ruling; the shutter
  // log records what any future capture actually does.

  /**
   * FRAMING: ULTRA-WIDE IS A ZOOM VALUE, NOT A DEVICE CHOICE.
   *
   * #145 made ultra-wide the default and the camera still opened at 1×. The
   * readout said why: the mounted device is ONE logical camera carrying
   * wide + ultra-wide + telephoto, with a zoom range of 0.5078 to 30. On a
   * phone arranged like that the lens IS a position in that range.
   *
   * The old branch could not express it. It routed on how the ultra-wide was
   * EXPOSED — a distinct device, or zoom below 1× — and the distinct-device
   * branch asked for `neutralZoom`, which Android hardcodes to 1.0
   * (CameraDeviceDetails.kt:100). Any path through that branch opened at 1×
   * however wide the mounted device could actually go.
   *
   * ONE RULE, CORRECT IN EVERY ARRANGEMENT: ultra means the widest the MOUNTED
   * device can go, which is `minZoom`.
   *   multi-cam spanning all lenses  minZoom 0.5x  → the ultra-wide framing
   *   a discrete ultra-wide device   minZoom 1.0   → its own native framing,
   *                                                  already ultra-wide
   *   a phone with no ultra-wide     minZoom 1.0   → unchanged, nothing to give
   *
   * No branch on how the hardware is packaged, because the answer does not
   * depend on it — and the old code's bug was entirely in that branching.
   */
  useEffect(() => {
    const lensDevice = position === 'front' ? frontDevice : device;
    const z = (position !== 'front' && backLens === 'ultra')
      ? (lensDevice?.minZoom ?? lensDevice?.neutralZoom ?? 1)
      : (lensDevice?.neutralZoom ?? 1);
    if (Number.isFinite(z)) { currentZoomRef.current = z; setZoom(z); }
  }, [device, frontDevice, position, backLens]);

  useEffect(() => { currentZoomRef.current = zoom; }, [zoom]);

  /**
   * DIAGNOSTIC ONLY — no behaviour, one line, removed once it has answered.
   *
   * THE REPORT: the camera opens at 1x, not ultra-wide. #147 set the opening
   * zoom to the mounted device's `minZoom` and he still sees 1x, and three
   * rounds have now been spent guessing at it from the source.
   *
   * WHAT THE SOURCE CAN ALREADY SAY. Both device lookups above carry a
   * `physicalDevices` filter, so NOTHING HERE EVER MOUNTS THE MULTI-CAMERA
   * DEVICE. If this phone's ultra-wide exists only inside a multi-cam that
   * neither filter selects, `wideDevice` is a wide-ONLY device whose `minZoom`
   * is 1.0 by construction — a device chosen for being the wide lens has no
   * wider lens to zoom out to — and #147 cannot reach past it however it is
   * written.
   *
   * WHAT ONLY THE PHONE CAN SAY: whether that is this phone. The decisive
   * comparison is `any` against `mounted`:
   *
   *   any.minZoom < 1 while mounted.minZoom === 1
   *     -> confirmed. The wider device exists and is not being mounted.
   *   any.minZoom === mounted.minZoom === 1
   *     -> the phone has no reachable ultra-wide. A hardware expectation, not
   *        a bug, and #147 was never going to change it.
   *
   * The existing [CAM] shutter line prints device/pos/lens and no zoom values,
   * which is exactly why this has stayed open. Logged at MOUNT rather than at
   * the shutter: the framing is already wrong before he presses anything.
   */
  useEffect(() => {
    const d = (label, dev) => `${label}{id=${dev?.id} phys=${(dev?.physicalDevices || []).join('+')} `
      + `min=${dev?.minZoom} neutral=${dev?.neutralZoom} max=${dev?.maxZoom}}`;
    console.log(
      '[CAM-DIAG] %s %s %s %s uwIsDistinct=%s backLens=%s appliedZoom=%s',
      d('any', anyBackDevice), d('uw', uwDevice), d('wide', wideDevice),
      d('mounted', device), uwIsDistinct, backLens, zoom,
    );
    // Mount-time only: the deps are the identities that decide the framing, and
    // `zoom` is deliberately NOT among them — re-logging on every pinch would
    // bury the one line that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyBackDevice, uwDevice, wideDevice, device, uwIsDistinct, backLens]);

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
    const seq = (shotSeqRef.current += 1);
    // Logged BEFORE capture because a hanging capture never reaches the timing
    // badge — this line is the only record of WHICH device/lens/METHOD the
    // capture used. `method` proves on-device which branch the running bundle
    // took, so a stale OTA can never be mistaken for a slow snapshot.
    console.log(
      '[CAM] shutter #%d method=%s device=%s pos=%s lens=%s',
      seq, Platform.OS === 'android' ? 'takeSnapshot' : 'takePhoto',
      device?.id, position, backLens,
    );
    try {
      // SPEED (the real fix): `takePhoto` is CameraX ImageCapture — sensor read +
      // autofocus/AE convergence + full JPEG encode — inherently ~3s on Android,
      // and NO js option moved it (we peeled video criteria, photoQualityBalance,
      // and the whole format). `takeSnapshot` on Android is a GPU screenshot of
      // the PREVIEW view: no sensor round-trip, no AF wait, no full-res encode →
      // tens of ms. It also bypasses the ImageCapture pipeline that FAILS on
      // ultra-wide, so ultra-wide captures too. A jobsite photo is downscaled to
      // ~1280px anyway, so preview-resolution is plenty.
      //
      // iOS keeps takePhoto: iOS takeSnapshot needs `video` enabled (a frame from
      // the video pipeline), which this photo-only session does not run.
      const photo = Platform.OS === 'android'
        ? await camera.current.takeSnapshot({ quality: 90 })
        : await camera.current.takePhoto({ flash: 'off', enableShutterSound: false });
      const tShot = Date.now();
      const srcUri = photo.path.startsWith('file://') ? photo.path : `file://${photo.path}`;
      // THE BADGE IS GONE; THE LOG IS NOT. The on-screen timing overlay was
      // TEMP instrumentation for a latency diagnosis that has concluded, and
      // temporary instrumentation on a CP-facing screen is the shape that
      // outlives its reason. `report` stays because the CALLER still calls it
      // (`report?.('paint')`, `report?.('compress')`) — those stages happen
      // after this function returns and are invisible from here — and because
      // a capture that hangs still needs a record of how far it got.
      const report = (stage, ms) => {
        const elapsed = typeof ms === 'number' ? ms : Date.now() - tShot;
        console.log('[CAM] #%d %s=%dms', seq, stage, elapsed);
      };
      onCapture(srcUri, report);
      const tHandoff = Date.now();
      // take = the native capture call; handoff = everything else in the modal.
      console.log('[CAM] #%d capture=%dms handoff=%dms total=%dms',
        seq, tShot - t0, tHandoff - tShot, tHandoff - t0);
    } catch (e) {
      console.warn('vision-camera capture failed:', e?.message);
    } finally {
      setCapturing(false);
    }
  }, [capturing, onCapture, device, position, backLens]);

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
        // ── WHY THE SESSION NEVER STARTED (device round 5, and the readout
        //    named it) ────────────────────────────────────────────────────────
        //
        //   preview: NEVER STARTED   session: init=false started=false
        //   error: Pixel extensions not supported in framework path
        //
        // `lowLightBoost` is not a setting — it swaps the whole cameraSelector
        // for an EXTENSION-backed one:
        //
        //   cameraSelector = cameraSelector.withExtension(..., ExtensionMode.NIGHT, "NIGHT")
        //   camera = provider.bindToLifecycle(this, cameraSelector, *useCases)
        //   callback.onInitialized()      <- the line AFTER the bind
        //
        // (CameraSession+Configuration.kt:261-282). The bind threw, so nothing
        // below it ever ran — which is exactly the init=false/started=false the
        // panel reported. #142 was correct and simply could not matter: the
        // session never got far enough for compositing to be reached.
        //
        // THE LIBRARY DOES EXPOSE A CHECK, AND WE WERE ALREADY USING IT.
        // `device.supportsLowLightBoost` is
        // `extensionsManager.isExtensionAvailable(selector, ExtensionMode.NIGHT)`
        // (CameraDeviceDetails.kt:80) — and on this device it returned TRUE and
        // the bind then failed. The extensions manager advertises what the
        // vendor declares; the framework path is where it has to actually work.
        // A check that says yes and then throws is not a check.
        //
        // So: OFF, unconditionally. A camera that opens beats a camera with
        // night mode. If low-light capture is ever wanted back, it needs a
        // configure-then-recover path (bind, catch, rebind without the
        // extension) — not a boolean anyone can trust up front.
        lowLightBoost={false}
        isActive={active && appActive}
        photo={true}
        // ── WHY THE PREVIEW WAS BLACK (device round 5, finding 28) ──────────
        //
        // VisionCamera v4 defaults androidPreviewViewType to SURFACE_VIEW
        // (CameraView.kt:91) -> PreviewView.ImplementationMode.PERFORMANCE ->
        // a real SurfaceView. A SurfaceView CANNOT BE ALPHA-COMPOSITED: it
        // punches a hole through the window instead of drawing into the view
        // hierarchy, so giving a parent alpha < 1 forces the subtree into a
        // hardware layer the SurfaceView does not join — and coming back to
        // opacity 1 does not reliably re-attach it.
        //
        // This screen hides the PRE-WARMED camera with exactly that: opacity 0
        // (see overlayHidden). So the preview came back black with the chrome
        // drawn correctly on top, which is precisely what the device showed.
        //
        // Capture failed for the SAME reason, not a second one: Android's
        // takeSnapshot is `previewView.bitmap ?: throw SnapshotFailedError()`
        // (CameraView+TakeSnapshot.kt) — getBitmap() returns null when the
        // preview is not rendering, so the throw landed in handleShutter's
        // catch and nothing happened.
        //
        // A TextureView is an ordinary view: it composites with alpha, it
        // survives the opacity toggle, and getBitmap() works on it. The cost is
        // some preview performance, which is the right trade against a camera
        // that cannot take a photo. Pure JS — no rebuild, ships by OTA.
        androidPreviewViewType={PREVIEW_TYPE}
        // ── WHAT HE SEES IS WHAT HE GETS (finding 29) ───────────────────────
        //
        // NOT a lens problem. The lens default is already 'wide' and Android
        // hardcodes neutralZoom to 1.0 (CameraDeviceDetails.kt:100), so the
        // camera opens at 1x, not 0.5x.
        //
        // takeSnapshot captures previewView.bitmap — what is ON SCREEN, at the
        // VIEW's dimensions, cropped by resizeMode. The default 'cover' crops a
        // 4:3 sensor frame to the phone's tall aspect, so the filed photo was a
        // screen-shaped crop of what the CP framed. That is the distortion.
        //
        // 'contain' letterboxes the preview to the sensor's real aspect, so the
        // snapshot carries the whole frame and the CP is looking at exactly the
        // photo he will file. Ruled over switching Android back to takePhoto: a
        // three-second shutter is how a CP stops taking photos, and the image
        // is downscaled to ~1280px either way.
        resizeMode="contain"
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
