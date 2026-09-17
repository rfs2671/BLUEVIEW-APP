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

/**
 * A DOB record's date, read as what it IS: a calendar day or an instant.
 *
 * ── THE DEFECT THIS REPLACES ────────────────────────────────────────────────
 *
 * app/project/[id]/dob-logs.jsx built every date with `new Date(str)`, and for
 * an eight-digit one it FORCED `…T00:00:00Z`. A bare date-only string parses as
 * UTC midnight, so `toLocaleDateString` in New York prints the day before:
 *
 *     '20260721'    -> "Jul 20, 2026"
 *     '2026-07-01'  -> "Jun 30, 2026"     <- the wrong MONTH
 *
 * The label on that row reads "Issue Date" on a DOB violation. `violation_date`
 * is Socrata's `issue_date` passed through raw, which for ECB violations is
 * YYYYMMDD, and when absent falls back to a bare 'YYYY-MM-01' -- so the
 * month-boundary case was not hypothetical, it was the fallback.
 *
 * ── WHY NOON, AND WHY NOT A STRING WITH A TIME IN IT ───────────────────────
 *
 * A calendar day anchored at UTC noon reads back as the same day in every zone
 * from UTC-11 to UTC+12, which is every zone anyone runs this in. Deliberately
 * NOT `new Date(str + 'T12:00:00')`: that parses in the DEVICE's zone, which
 * makes the answer depend on where the phone is -- the same argument
 * `shiftDate` above already makes.
 *
 * ── AND WHY THIS IS NOT APPLIED TO EVERYTHING ──────────────────────────────
 *
 * The same screen formats `detected_at` and `status_changed_at`, which are
 * INSTANTS: a timestamp already names a moment, and anchoring it to noon would
 * move it. So a value carrying a time is passed to `new Date` unchanged, and
 * only a date-only value is anchored. Getting that backwards is how a fix for
 * a display bug becomes a data bug.
 */
export function parseRecordDate(value) {
  if (!value) return null;
  const str = String(value).trim();
  // YYYYMMDD -- Socrata's ECB shape, no separators.
  let m = /^(\d{4})(\d{2})(\d{2})$/.exec(str);
  // YYYY-MM-DD and nothing after it: a calendar day.
  if (!m) m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(str);
  if (m) {
    const y = Number(m[1]); const mo = Number(m[2]); const d = Number(m[3]);
    const anchor = new Date(Date.UTC(y, mo - 1, d, 12, 0, 0));
    // ROUND-TRIP, because Date.UTC ROLLS OVER rather than refusing: month 13
    // day 45 becomes February of the next year, and an impossible date would
    // render as a real one. My own test caught this -- the regex alone accepts
    // '2026-13-45'. The same check guards the readers in dateEntry.js and
    // lib/insurance_expiry.py, for the same reason.
    if (anchor.getUTCFullYear() !== y
        || anchor.getUTCMonth() !== mo - 1
        || anchor.getUTCDate() !== d) return null;
    return anchor;
  }
  const dt = new Date(str);          // carries a time: an instant, left alone
  return isNaN(dt.getTime()) ? null : dt;
}

/** `parseRecordDate` rendered as "Jul 21, 2026", or the raw head if unreadable. */
export function formatRecordDate(value) {
  if (!value) return '—';
  const d = parseRecordDate(value);
  if (!d) return String(value).slice(0, 10);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default {
  easternDate, easternToday, easternDayOffset, shiftDate,
  parseRecordDate, formatRecordDate,
};
