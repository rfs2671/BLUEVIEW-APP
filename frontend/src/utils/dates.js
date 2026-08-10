/**
 * Calendar dates, in the time zone the jobsites are actually in.
 *
 * WHY THIS MODULE EXISTS
 *   `new Date().toISOString().split('T')[0]` reads as "just format the date"
 *   and silently means "in UTC". From 20:00 EDT — 19:00 EST — that is
 *   TOMORROW's date in New York, and it shipped thirteen times across this
 *   codebase against two correct inline copies. The wrong pattern was the easy
 *   one to type, so this makes the right one easier.
 *
 * WHAT GOES WRONG WITH THE UTC ONE
 *   Two different failures, and the second is the serious one:
 *     * in a QUERY — the screen asks for the wrong day and looks empty. The
 *       pre-shift and toolbox rosters did exactly this after 8pm.
 *     * on a RECORD — a logbook is FILED stamped with tomorrow's date. That
 *       persists, and an inspector reads it. It cannot be fixed by reloading.
 *
 * NYC DOB compliance is anchored to the New York calendar day (see
 * get_day_range_est / eastern_today in backend/server.py, which bound the same
 * boundary server-side). en-CA is used purely because it formats as YYYY-MM-DD.
 *
 * NO NEW DEPENDENCY: Intl is built in. expo-localization carries a native
 * module and would force a rebuild for a string-formatting change.
 */

const EASTERN = 'America/New_York';

/**
 * The New York calendar date for an instant, as 'YYYY-MM-DD'.
 * Defaults to now. Pass a Date to convert a specific instant.
 */
export function easternDate(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: EASTERN }).format(date);
}

/** Today's New York calendar date, as 'YYYY-MM-DD'. */
export function easternToday() {
  return easternDate(new Date());
}

/**
 * `date` shifted by whole days, still on the New York calendar.
 * easternDayOffset(-1) is yesterday. Built by parsing the Eastern date back to
 * a UTC-noon anchor first, so the arithmetic cannot land on a DST-shifted hour
 * and roll a day.
 */
export function easternDayOffset(days, date = new Date()) {
  return shiftDate(easternDate(date), days);
}

/**
 * A 'YYYY-MM-DD' string shifted by whole days.
 *
 * Pure calendar arithmetic — no time zone is involved at either end, because
 * none should be: the input is already a calendar day and so is the output.
 * The UTC-noon anchor exists only so the +/- cannot land on a DST-shifted hour
 * and roll a day. Deliberately NOT `new Date(str + 'T12:00:00')`, which parses
 * in the DEVICE's zone and quietly makes the result depend on where the phone
 * is.
 */
export function shiftDate(dateStr, days) {
  const [y, m, d] = String(dateStr).split('-').map(Number);
  const anchor = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  anchor.setUTCDate(anchor.getUTCDate() + days);
  const p = (n) => String(n).padStart(2, '0');
  return `${anchor.getUTCFullYear()}-${p(anchor.getUTCMonth() + 1)}-${p(anchor.getUTCDate())}`;
}

export default { easternDate, easternToday, easternDayOffset, shiftDate };
