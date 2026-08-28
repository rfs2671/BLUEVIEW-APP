/**
 * HOW OLD IS THE JS THE PHONE IS ACTUALLY RUNNING?
 *
 * On 2026-08-28 a filed daily jobsite log rendered as a blank editable form on
 * one device and correctly on another. Six source traces were built — the read
 * path, the company scope, project access, date normalisation, a BSON type
 * mismatch, a missing query parameter — and every one was wrong, because the
 * fault was not in the code anybody was reading. That phone was running a
 * bundle older than the fix. `BuildMarker` had been rendering its update id at
 * the bottom of the very screen the operator was standing on the whole time,
 * and nobody read it, because an id is not a verdict: `bundle: a3f91c02` tells
 * you nothing unless you already know which ids are current.
 *
 * "built 34 days ago" needs no such knowledge. That is the whole feature.
 *
 * WHAT IT DELIBERATELY WILL NOT DO:
 *
 *   It does not say "you are out of date". Age is not staleness — a bundle can
 *   be a month old and be the newest one published. Saying "behind" requires
 *   knowing what exists, which this cannot know and which the obvious way of
 *   asking (Updates.checkForUpdateAsync) answers WRONGLY for the case that
 *   caused the incident: it asks whether a newer update exists for the
 *   runtimeVersion the device is already stranded on, so a phone cut off by an
 *   appVersion bump is told it is current while being a month behind. A check
 *   that confidently says "current" to a stranded device is worse than none.
 *
 *   It does not invent an age for an embedded bundle. `Updates.createdAt` is
 *   null when the JS came baked into the binary, and that is precisely the
 *   stranded case — a device on an old native build receiving no updates at
 *   all. Rendering "built today" there would state the opposite of the truth.
 *   Absent means absent, and the caller says so in its own words.
 */

/** Whole days between `createdAt` and now, or null when it cannot be known. */
export function bundleAgeDays(createdAt, now = new Date()) {
  if (createdAt === null || createdAt === undefined || createdAt === '') return null;
  const built = createdAt instanceof Date ? createdAt : new Date(createdAt);
  const t = built.getTime();
  if (!Number.isFinite(t)) return null;
  const nowMs = (now instanceof Date ? now : new Date(now)).getTime();
  if (!Number.isFinite(nowMs)) return null;
  const days = Math.floor((nowMs - t) / 86400000);
  // A NEGATIVE AGE IS A DEVICE CLOCK, NOT A BUNDLE. Site phones drift, and
  // "built -3 days ago" sends the reader after the wrong problem. Clamped, so
  // the worst a skewed clock produces is "built today".
  return days < 0 ? 0 : days;
}

/** "built today" / "built 1 day ago" / "built 34 days ago", or null. */
export function bundleAgeLabel(createdAt, now = new Date()) {
  const days = bundleAgeDays(createdAt, now);
  if (days === null) return null;
  if (days === 0) return 'built today';
  return `built ${days} day${days === 1 ? '' : 's'} ago`;
}

export default { bundleAgeDays, bundleAgeLabel };
