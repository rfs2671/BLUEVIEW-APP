/**
 * THE LENS READOUT'S TWO PURE PIECES.
 *
 * They live here rather than inside CameraCaptureModal so the rules can be
 * asserted as BEHAVIOUR instead of as strings grepped out of a component. The
 * modal holds the state and renders; it does not decide anything below.
 *
 * WHAT THIS IS FOR. The operator reports the camera opening at 1x rather than
 * ultra-wide. #147 set the opening zoom to the mounted device's `minZoom` and
 * it did not change, and three rounds of reasoning from source have not settled
 * it. The values that would settle it are on his phone, and he has no debugger
 * attached — the same reason two Railway diagnoses went unread.
 *
 * TEMPORARY. This file goes when the question is answered.
 */

/**
 * Fold one vision-camera error into the sticky record.
 *
 * NEVER CLEARED, AND THAT IS THE WHOLE POINT. The modal's onError handler drops
 * a distinct ultra-wide device to the wide lens when it fails to start, and the
 * zoom effect then re-runs down the `neutralZoom` branch and lands on 1. THE
 * CAMERA RECOVERS. The preview is live, the shutter works, the photo files, and
 * the only thing wrong is the framing — which is exactly what was reported.
 *
 * A record that reset on recovery would erase the single field distinguishing
 * that case from "the wider device was never mounted" and from "this phone has
 * no ultra-wide". So there is no clear path: this function only ever returns a
 * record, and `n` counts every error the session has seen.
 *
 * `lensAtError` is captured because AFTER the flip `backLens` reads 'wide' and
 * the reason it changed is gone.
 */
export function recordCamError(prev, err, backLens) {
  return {
    n: (prev && Number.isFinite(prev.n) ? prev.n : 0) + 1,
    code: String((err && err.code) || ''),
    message: String((err && err.message) || err || ''),
    // The FIRST lens to fail is the one worth knowing. A second error arriving
    // after the fallback would otherwise overwrite it with 'wide' and hide the
    // fact that the ultra-wide device is what died.
    lensAtError: (prev && prev.lensAtError) ? prev.lensAtError : String(backLens || ''),
  };
}

const line = (label, dev) => (dev
  ? `${label}: id=${dev.id} phys=[${(dev.physicalDevices || []).join('+')}] `
    + `min=${dev.minZoom} neutral=${dev.neutralZoom} max=${dev.maxZoom}`
  : `${label}: none`);

/**
 * The readout, as one block of text.
 *
 * ONE TEXT, TWO READERS — the console line and the on-screen panel are the same
 * string, so a debugger and the operator can never be shown different values.
 *
 * Every field is read off the RUNNING camera: `device` is what is mounted,
 * `zoom` is what is applied, `backLens` is what the reset effect last branched
 * on. Nothing is recomputed. That is why this cannot live on the settings BUILD
 * card instead — that card would have to re-implement the device selection rule
 * and would then be free to disagree with the camera it describes.
 */
export function buildDiagText(v) {
  const s = v || {};
  return [
    line('any (unfiltered)', s.anyBackDevice),
    line('uw   (filtered)', s.uwDevice),
    line('wide (filtered)', s.wideDevice),
    line('MOUNTED', s.device),
    `uwIsDistinct=${s.uwIsDistinct}  backLens=${s.backLens}  position=${s.position}`,
    `appliedZoom=${s.zoom}`,
    s.camError
      ? `camError x${s.camError.n} atLens=${s.camError.lensAtError} `
        + `code=${s.camError.code} ${s.camError.message}`
      : 'camError: none',
    // HOW MANY TIMES THE SESSION-START CALLBACK RE-ASSERTED THE FRAMING. This
    // answers a different question from appliedZoom, which reports what was
    // REQUESTED rather than what took effect: 0 here means onStarted and
    // onInitialized never fired, which would be a different defect from the
    // framing not landing.
    `framingApplied=${s.framingApplied}`,
    `os=${s.os}`,
  ].join('\n');
}

/**
 * Which of the three candidates the numbers point at.
 *
 * Not rendered — the operator sends the block above and the reading happens
 * here. It exists so the three cases are written down as code that can be
 * tested rather than as a paragraph in a PR that can quietly stop being true.
 */
export function readDiag({ anyBackDevice, device, backLens, camError }) {
  const anyMin = anyBackDevice && Number.isFinite(anyBackDevice.minZoom)
    ? anyBackDevice.minZoom : null;
  const mountedMin = device && Number.isFinite(device.minZoom) ? device.minZoom : null;
  // THE FALLBACK IS TESTED FIRST. It can produce the same 1x framing as the
  // other two while the numbers look like the "no ultra-wide" case, so reading
  // the zoom values before the error string would give the wrong answer.
  if (camError && backLens === 'wide') return 'fallback';
  if (anyMin === null || mountedMin === null) return 'unknown';
  if (anyMin < 1 && mountedMin >= 1) return 'wider_device_not_mounted';
  if (anyMin >= 1 && mountedMin >= 1) return 'no_ultra_wide_on_device';
  return 'unknown';
}

export default { recordCamError, buildDiagText, readDiag };
