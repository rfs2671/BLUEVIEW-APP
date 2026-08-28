/**
 * IS THIS INSTALL OLD ENOUGH THAT IT RECEIVES NOTHING?
 *
 * `bundleAge.js` answers "how old is the JS running here", which is honest and
 * knows nothing about what exists. This answers the other half, and it is the
 * half that caught nobody on 2026-08-28: a device whose NATIVE build predates
 * the current `expo.version` receives no OTA update at all, forever, and is
 * told nothing — `runtimeVersion: {policy: "appVersion"}` makes it ineligible
 * rather than merely behind.
 *
 * WHY NOT Updates.checkForUpdateAsync. It asks Expo whether a newer update
 * exists for the runtimeVersion THIS DEVICE IS ALREADY STRANDED ON, so the
 * stranded phone is told it is current. A check that confidently says
 * "current" to exactly the device you are hunting is worse than no check. The
 * comparison has to come from somewhere that knows what the product's floor
 * is, which is the server.
 *
 * THE COMPARISON IS ON THE NATIVE VERSION, not the bundle id and not the
 * bundle's age. That is the whole point: the bundle is downstream of
 * eligibility, and an ineligible device can hold a perfectly fresh bundle for
 * the version it is stuck on.
 */

/** [1, 3, 0] from "1.3.0". Non-numeric parts become 0; junk becomes null. */
export function parseVersion(v) {
  if (typeof v !== 'string') return null;
  const trimmed = v.trim();
  if (!trimmed) return null;
  // Tolerate a build suffix ("1.3.0-rc1", "1.3.0+42") — only the numeric core
  // decides eligibility, and a release channel suffix is not a version bump.
  const core = trimmed.split(/[-+]/)[0];
  const parts = core.split('.');
  if (!parts.length || parts.length > 4) return null;
  const nums = parts.map((p) => (/^\d+$/.test(p) ? Number(p) : null));
  if (nums.some((n) => n === null)) return null;
  while (nums.length < 3) nums.push(0);
  return nums;
}

/** -1 / 0 / 1, or null when either side is unparseable. */
export function compareVersions(a, b) {
  const x = parseVersion(a);
  const y = parseVersion(b);
  if (!x || !y) return null;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i += 1) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

/**
 * True only when we KNOW this install is below the supported floor.
 *
 * Unknown is not behind. A missing minimum (an older server, a deploy that
 * could not read app.json) and an unparseable version both return false, so
 * the marker stays silent rather than accusing an install it cannot judge.
 * The cost of a false "out of date" on a CP's screen is that the next one gets
 * ignored.
 */
export function isBehindMinimum(installed, minimumSupported) {
  const cmp = compareVersions(installed, minimumSupported);
  return cmp !== null && cmp < 0;
}

export default { parseVersion, compareVersions, isBehindMinimum };
