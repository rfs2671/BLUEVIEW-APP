/**
 * A DRAFT THE RETIRED SCREENS LEFT BEHIND MUST NOT BE ORPHANED SILENTLY.
 *
 * The two daily-log editors are gone. They wrote drafts to this device and told
 * the man they would sync when he reconnected, and `draftSync` refuses those
 * types outright -- deliberately and correctly, because their payload is a
 * different, flatter shape and inventing a compliance payload from a partial
 * match is how a malformed legal record gets written. So the draft stayed on
 * the device and was never filed.
 *
 * NOTHING WAS LOST. `markPending` wrote the draft to storage and the drain's
 * refusal returns WITHOUT clearing the key, so the bytes are still there. What
 * failed was filing, which for a record nobody is watching is materially the
 * same and has a different remedy: the content can still be read and re-entered.
 *
 * There is no server-side trace of one of these -- a pending draft never
 * reaches the server -- so nobody can tell from the outside whether any exist.
 * Only the device knows, which is why this runs on the device and why it must
 * run at all rather than assuming the population is empty.
 *
 * PURE ON PURPOSE. No react-native import, no storage read: the selection rule
 * and the wording are arguments and return values, so both are testable without
 * a renderer. The component is the shell; this is the decision.
 *
 * Tests: src/utils/unfiledDailyLogs.test.cjs
 */

//: The two the drain skips, which are exactly the two the retired screens
//: wrote. Named here rather than imported from draftSync so that removing the
//: skip one day does not silently stop this notice: these drafts need
//: surfacing because they were never filed, not because a drain still refuses
//: them.
export const RETIRED_LOG_TYPES = ['daily_log', 'site_daily_log'];

export const DISMISSED_KEY = 'unfiled_daily_log_dismissed';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * `logbook_draft:<projectId>:<logType>:<date>` -> parts, or null.
 *
 * PARSED HERE RATHER THAN IMPORTED so this module stays loadable on its own.
 * The shape is asserted against a real key in the tests.
 */
export function parseKey(key) {
  const s = String(key || '');
  const parts = s.split(':');
  if (parts.length < 4 || parts[0] !== 'logbook_draft') return null;
  const [, projectId, logType, date] = parts;
  if (!projectId || !logType || !date) return null;
  return { key: s, projectId, logType, date };
}

/**
 * The drafts worth showing: a retired type, not already dismissed.
 *
 * ONE NOTICE PER DRAFT, EVER. The dismissal list is keyed on the draft key, so
 * a man with two sites is told about each and neither is repeated. A notice
 * that returns on every launch is one he learns to tap past, and the next one
 * will be about something that matters.
 */
export function unfiledDrafts(pendingKeys, dismissedKeys) {
  const retired = new Set(RETIRED_LOG_TYPES);
  const dismissed = new Set(dismissedKeys || []);
  const seen = new Set();
  const out = [];
  for (const raw of pendingKeys || []) {
    const parsed = parseKey(raw);
    if (!parsed) continue;
    if (!retired.has(parsed.logType)) continue;
    if (dismissed.has(parsed.key) || seen.has(parsed.key)) continue;
    seen.add(parsed.key);
    out.push(parsed);
  }
  // Oldest first: the one he is least likely to remember is the one to show.
  out.sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return out;
}

/** `2026-04-14` -> `14 April 2026`. The stored string, never a Date. */
export function formatDraftDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  if (!m) return String(iso || '');
  const month = MONTHS[Number(m[2]) - 1];
  if (!month) return String(iso || '');
  return `${Number(m[3])} ${month} ${m[1]}`;
}

/**
 * What he reads. Approved wording; the ordering of it is the point.
 *
 *   THE FACT BEFORE THE FAILURE. He did nothing wrong, so the first sentence
 *   says what he did, not what broke.
 *
 *   "NOTHING HAS BEEN LOST" EARLY, because it is the question he will actually
 *   have and every sentence before the answer is a sentence he reads worried.
 *
 *   IT CANNOT BE MOVED FOR HIM, said plainly rather than implied away. The two
 *   records store different fields, and pretending he is one tap from done
 *   would be the same guess the drain refuses to make.
 *
 *   THE PROJECT AND THE DATE IN THE FIRST LINE. A man with drafts on two sites
 *   needs to know which this is before he reads anything else.
 */
export function noticeText({ projectName, date }) {
  const where = projectName || 'a project on this device';
  return {
    title: 'A daily log saved on this device was never filed',
    body:
      `You saved a daily log for ${where} on ${formatDraftDate(date)}. `
      + 'It stayed on this device and never reached the server, so it is not '
      + 'part of the filed record. Nothing has been lost. '
      + 'The daily log now lives in Log Books, and this entry cannot be moved '
      + 'there automatically because the two records store different fields. '
      + 'Open it to read what you wrote, then enter it in Log Books for that '
      + 'date.',
    // FIRST, AND NOT OPTIONAL. Without it, "enter it in Log Books" is an
    // instruction he cannot follow: the content exists only inside this draft.
    actions: ['Read what I saved', 'Open Log Books', 'Dismiss'],
  };
}

/**
 * A draft's stored fields as readable lines. The editor that could render this
 * is gone, so this is the only way back to what he wrote.
 *
 * EVERY SCALAR, NOT A CHOSEN FEW. A allowlist here would decide for him which
 * of his own words were worth keeping, and the shape is the retired screen's
 * flat form rather than anything this code should claim to know.
 */
export function draftLines(draft) {
  const data = (draft && draft.data) || {};
  const out = [];
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === undefined || v === '') continue;
    if (typeof v === 'object') {
      // Signatures and card arrays: say they are there, do not try to draw
      // them. A count is honest; a rendering would be an invention.
      const n = Array.isArray(v) ? v.length : Object.keys(v).length;
      if (!n) continue;
      out.push([label(k), Array.isArray(v) ? `${n} entr${n === 1 ? 'y' : 'ies'}`
                                           : 'recorded']);
      continue;
    }
    if (v === false) continue;
    out.push([label(k), String(v)]);
  }
  return out;
}

function label(key) {
  const s = String(key).replace(/_/g, ' ').trim();
  return s ? s[0].toUpperCase() + s.slice(1) : key;
}
