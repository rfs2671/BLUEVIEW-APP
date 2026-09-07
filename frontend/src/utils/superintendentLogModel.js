/**
 * THE ELEVEN ITEMS OF BC 3301.13.13, on the client.
 *
 * A MIRROR OF backend/lib/logbook/superintendent_log.py, and the parity is
 * asserted by backend/tests/test_superintendent_model_parity.py, which imports
 * the Python list and parses this one. Two hand-maintained copies of a
 * statutory list would drift, and this codebase has spent a week pulling apart
 * pairs that did: the OSHA register's row rule and the pre-shift sheet each
 * printed different things depending which renderer you asked.
 *
 * THIS SENTENCE USED TO NAME `superintendentLogModel.test.cjs`, WHICH HAS
 * NEVER EXISTED. Nothing compared the two lists for the whole life of this
 * module, and they had already drifted on `provenance` — the one field whose
 * own comment in the Python explains that it must ship EARLY because
 * retrofitting it onto filed records is impossible. A docstring citing a check
 * that was never written is worse than no docstring: the next reader stops
 * looking. The check now exists, in Python rather than CommonJS, because
 * CS_LOG_ITEMS is an ESM export and a .cjs test would have had to regex-parse
 * BOTH sides instead of one.
 *
 * ── EVERY GATE READS THE RECORD'S OWN DATE ───────────────────────────────────
 *
 * `csLogItems(logDate)` takes the DATE OF THE LOG, never `new Date()`. The
 * competent-person allowance (item 8) lapses on 2027-01-01, after which item 9
 * carries the case it covered. A log filed in 2026 must keep showing item 8
 * forever: a rule change does not reach back and alter what a filed document
 * says. A gate on the clock would make historical records change what they
 * report, which on a signed statutory document is the worst failure available.
 *
 * ── THREE KINDS OF EMPTY ─────────────────────────────────────────────────────
 *
 * Items 4 to 7 are empty on most days, and the difference between the kinds of
 * empty IS the document:
 *
 *   attested_none   the CS considered the item and had nothing to report. An
 *                   ASSERTION, made by a named person, and the whole reason
 *                   the record is worth reading.
 *   not_reached     nobody answered. A gap. It must never render as the above.
 *   not_collected   this app does not capture the item. A scope statement,
 *                   asserted by the rule rather than by a person.
 */

export const COMPETENT_PERSON_SUNSET = '2027-01-01';

export const CS_LOG_ITEMS = Object.freeze([
  { key: 'presence', number: 1, label: 'Superintendent presence', attestable: false, collected: true, fields: ['printed_name', 'signature', 'arrived_at', 'departed_at'] },
  // `provenance` — DECLARED ON BOTH SIDES, PRODUCED BY NEITHER YET. Item 2 is
  // the one item that overlaps with the CP's daily jobsite log, and the flag
  // records whether its text was ADOPTED from that log unedited or is the
  // superintendent's OWN. See the long note on the Python item, which argues
  // that the flag must exist before the adoption UI because provenance cannot
  // be retrofitted onto records already filed. Nothing writes it today, so
  // `item_provenance` resolves every filed log to `unmarked`, and one such log
  // exists. Mirrored here so the two models agree while the client half lands.
  { key: 'progress', number: 2, label: 'General progress of work', attestable: false, collected: true, provenance: true, fields: ['summary'] },
  { key: 'cs_activities', number: 3, label: 'Superintendent activities, areas and floors inspected', attestable: false, collected: true, fields: ['summary', 'locations'] },
  { key: 'unsafe_conditions', number: 4, label: 'Unsafe conditions observed', attestable: true, collected: true, fields: ['entries'] },
  { key: 'orders_given', number: 5, label: 'Orders and notices given', attestable: true, collected: true, fields: ['entries'] },
  { key: 'dob_actions', number: 6, label: 'Violations, stop work orders and summonses', attestable: true, collected: true, fields: ['entries'] },
  { key: 'incidents', number: 7, label: 'Incidents or damage, including to adjoining property', attestable: true, collected: true, fields: ['entries'] },
  // ATTESTABLE, and the ONLY item whose "none" is conditional. 3301.13.12
  // makes the absence of a designation lawful in exactly one circumstance --
  // the superintendent was on site whenever active work occurred -- so the
  // tick asserts that presence and `noneLabel` says so on the document. A bare
  // "none designated" would be an admission filed on one tap. See the long
  // note on the Python item.
  { key: 'competent_person', number: 8, label: 'Competent person', attestable: true, noneLabel: 'None designated &#183; {who} attests he was present at the job site at all times active work occurred', collected: true, sunsetOn: COMPETENT_PERSON_SUNSET, fields: ['name', 'signature'] },
  { key: 'cs_changes', number: 9, label: 'Superintendent changes', attestable: false, collected: false, startsOn: COMPETENT_PERSON_SUNSET, fields: [] },
  { key: 'weekly_meeting', number: 10, label: 'Weekly safety meeting', attestable: false, collected: false, fields: [] },
  { key: 'daily_inspection', number: 11, label: 'Daily inspection', attestable: false, collected: true, fields: ['inspected_on', 'location', 'result'] },
]);

const BY_KEY = Object.freeze(
  CS_LOG_ITEMS.reduce((acc, i) => { acc[i.key] = i; return acc; }, {}),
);

/**
 * Does this item belong on a log of this date?
 *
 * An unknown or unparseable date returns true: the item is SHOWN rather than
 * silently dropped. Dropping a statutory item because a date could not be read
 * would remove content from a compliance record on the strength of a parsing
 * failure, which is the wrong direction to fail in.
 */
export function csItemApplies(key, logDate) {
  const item = BY_KEY[key];
  if (!item) return false;
  const date = String(logDate || '').trim();
  if (!date) return true;
  if (item.sunsetOn && date >= item.sunsetOn) return false;
  if (item.startsOn && date < item.startsOn) return false;
  return true;
}

/** The items that belong on a log of this date, in printed order. */
export function csLogItems(logDate) {
  return CS_LOG_ITEMS.filter((i) => csItemApplies(i.key, logDate));
}

function rowHasContent(row) {
  if (row && typeof row === 'object') {
    return Object.values(row).some((v) => String(v ?? '').trim());
  }
  return !!String(row ?? '').trim();
}

function hasContent(item, block) {
  return (item.fields || []).some((field) => {
    const v = block[field];
    if (Array.isArray(v)) return v.some(rowHasContent);
    if (typeof v === 'string') return !!v.trim();
    if (v && typeof v === 'object') return Object.values(v).some((x) => String(x ?? '').trim());
    return v !== null && v !== undefined && v !== '' && v !== false;
  });
}

/** 'present' | 'attested_none' | 'not_reached' | 'not_collected'. */
export function csItemState(key, data, logDate) {
  const item = BY_KEY[key];
  if (!item || !item.collected) return 'not_collected';
  if (!csItemApplies(key, logDate)) return 'not_collected';
  const block = (data && typeof data === 'object' ? data[key] : null);
  if (!block || typeof block !== 'object' || Array.isArray(block)) return 'not_reached';
  if (hasContent(item, block)) return 'present';
  // ONLY AN ATTESTABLE ITEM CAN BE ATTESTED. "None to report" is meaningful
  // only where the CS was asked; setting the flag on an item nobody asks about
  // must not manufacture an assertion.
  if (item.attestable && block.none_to_report === true) return 'attested_none';
  return 'not_reached';
}

/** Attestable items with neither content nor an explicit nothing-to-report. */
export function csUnanswered(data, logDate) {
  return CS_LOG_ITEMS
    .filter((i) => i.attestable && csItemApplies(i.key, logDate))
    .filter((i) => csItemState(i.key, data, logDate) === 'not_reached')
    .map((i) => i.key);
}

/**
 * Item keys as the labels a superintendent reads.
 *
 * THE SERVER NAMES THE ITEMS, THE CLIENT NAMES THEM IN WORDS. A 400 carrying
 * `{"code": "SUBMIT_UNATTESTED_ITEMS", "items": ["orders_given"]}` holds
 * everything he needs to fix it, and "orders_given" printed at a man on a
 * jobsite throws that away. Both the hint on the disabled button and the
 * refusal from the server render through here, so the two cannot come to say
 * different things about the same condition.
 *
 * AN UNKNOWN KEY FALLS BACK TO THE KEY. A server ahead of this build can name
 * an item this build does not declare, and the place that would happen is
 * inside the catch that reports a failure to file. Throwing there would replace
 * a legible refusal with a blank screen at the exact moment he is about to lose
 * the log — so an unrecognised key is shown raw rather than not shown at all.
 */
export function csItemLabels(keys) {
  return (Array.isArray(keys) ? keys : [])
    .map((k) => (CS_LOG_ITEMS.find((i) => i.key === k) || {}).label || k);
}

/** A one-line summary of an item that HAS content. */
export function csItemSummary(item, block) {
  if (!item || !block || typeof block !== 'object') return '';
  const out = [];
  for (const field of item.fields || []) {
    const v = block[field];
    if (Array.isArray(v)) {
      for (const row of v) {
        if (row && typeof row === 'object') {
          const parts = Object.entries(row)
            .filter(([, x]) => String(x ?? '').trim())
            .map(([k, x]) => `${k.replace(/_/g, ' ')}: ${x}`);
          if (parts.length) out.push(parts.join(' · '));
        } else if (String(row ?? '').trim()) {
          out.push(String(row));
        }
      }
    } else if (typeof v === 'string' && v.trim()) {
      out.push(v.trim());
    } else if (v !== null && v !== undefined && v !== '' && v !== false) {
      out.push(String(v));
    }
  }
  return out.join(' — ');
}

export default {
  CS_LOG_ITEMS, COMPETENT_PERSON_SUNSET, csItemApplies, csLogItems,
  csItemState, csUnanswered, csItemLabels, csItemSummary,
};
