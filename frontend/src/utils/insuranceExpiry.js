/**
 * HOW A STORED INSURANCE EXPIRY IS COLOURED AND PRINTED.
 *
 * `companies.gc_insurance_records[].expiration_date` and `.effective_date` are
 * CALENDAR DAYS — a certificate of insurance expires on a day, not at an
 * instant — and they are stored as `YYYY-MM-DD` going forward and as
 * `MM/DD/YYYY` on anything written before this deploy. Two screens render
 * them: the owner panel's company cards (app/owner/index.jsx) and the admin's
 * own Settings insurance section (app/settings.jsx). Both had their own copy
 * of the same two functions, and both copies were wrong the same way.
 *
 * ── THE DEFECT THIS REPLACES ────────────────────────────────────────────────
 *
 * Both copies read the stored string with `new Date(str)`. For a DATE-ONLY ISO
 * string that is UTC midnight by specification, so in America/New_York
 * `getDate()` and `toLocaleDateString()` answer with the day BEFORE:
 *
 *     new Date('2029-07-21').getDate()          // 20, in New York
 *     new Date('07/21/2029').getDate()          // 21 — the legacy form is fine
 *
 * So the SAME DAY rendered one day early or on the day depending on which
 * format happened to be in the database, and the ISO form — the one everything
 * writes from now on — is the one that renders wrong. Nothing about it looks
 * broken on screen: 7/20/29 is a plausible date.
 *
 * The colour band had the same shift at its edges. A policy expiring today
 * read as expired, and the 60-day boundary moved by a day.
 *
 * ── WHAT THIS IS NOT ────────────────────────────────────────────────────────
 *
 * NOT A THIRD DATE PARSER. The stored string is read by `parseStoredDate` from
 * src/utils/dateEntry.js — the reader the shared date field already uses, so
 * the value the admin CONFIRMS in the Settings form and the value these badges
 * PRINT cannot disagree about what a stored string means. This module only
 * decides colour and wording.
 *
 * NOT A GENERAL DATE FORMATTER. It takes date-only values. A TIMESTAMP
 * (`gc_last_verified`, `created_at`, anything carrying a time and a `Z`) is
 * correctly read by `new Date(...)` and must keep using it: handing one to
 * `parseStoredDate` gets 'unreadable', because a timestamp is not a calendar
 * day. settings.jsx keeps its own `formatDate` for exactly those two fields.
 *
 * NOT THE SERVER'S VERDICT. `is_current` on the record and the permit-renewal
 * eligibility result are the server's answers. This is the badge beside them.
 */
import { parseStoredDate } from './dateEntry';

/**
 * Inside this many days a policy is "expiring soon" (amber). 60 days is what
 * both screens already used, lifted here so the two cannot drift.
 */
export const INSURANCE_EXPIRING_SOON_DAYS = 60;

/** What the badge prints when the stored string is not a date it can read. */
export const INSURANCE_DATE_UNREADABLE_SHORT = 'unreadable';

/**
 * What the admin is told when a stored expiry cannot be read. The same
 * sentence the server logs and puts in the permit-renewal blocking reasons
 * (backend/lib/insurance_expiry.py), so the screen and the server name one
 * condition.
 */
export const INSURANCE_DATE_UNREADABLE = 'insurance date unreadable';

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Whole calendar days from today until the stored day. Negative once it has
 * passed. `null` for a blank OR an unreadable value — callers must treat null
 * as "no claim", never as "fine", which is why `insuranceExpiryState` reports
 * the two apart.
 *
 * WHY `new Date(y, m - 1, d)` IS NOT THE DEFECT THIS FILE EXISTS FOR. The bug
 * is STRING parsing: a date-only string is specified as UTC. Numeric arguments
 * never go through that path — they name a local-midnight instant directly —
 * and both sides of the subtraction are built the same way, so the difference
 * is a count of local calendar days.
 *
 * `Math.round`, NOT `Math.ceil`, and it is not a rounding preference. A day
 * boundary crossing a DST change is 23 or 25 hours, so the quotient is 0.958
 * or 1.042 rather than 1. `ceil` reads 0.958 as 1 and -0.958 as 0 — a policy
 * that expired YESTERDAY would report 0 days left and colour amber instead of
 * red. `round` is symmetric, which is what a day count has to be.
 */
export function insuranceExpiryDaysLeft(raw, now = new Date()) {
  const parsed = parseStoredDate(raw);
  if (!parsed.iso) return null;
  const [y, m, d] = parsed.iso.split('-').map(Number);
  const day = new Date(y, m - 1, d);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((day.getTime() - today.getTime()) / MS_PER_DAY);
}

/**
 * 'blank' | 'unreadable' | 'expired' | 'soon' | 'ok'.
 *
 * 'unreadable' IS ITS OWN ANSWER and never folded into 'blank'. A record with
 * no expiry on file and a record whose expiry nobody can read are different
 * problems with different fixes, and the second one is the one that hides.
 */
export function insuranceExpiryState(raw, now = new Date()) {
  const parsed = parseStoredDate(raw);
  if (parsed.kind === 'blank') return 'blank';
  if (parsed.kind === 'unreadable') return 'unreadable';
  const daysLeft = insuranceExpiryDaysLeft(raw, now);
  if (daysLeft < 0) return 'expired';
  if (daysLeft <= INSURANCE_EXPIRING_SOON_DAYS) return 'soon';
  return 'ok';
}

/**
 * 'M/D/YY' for the owner panel's three-badge row, where the whole label is
 * "GL: 7/21/29" and there is no room for more.
 *
 * Built from the three numbers, so it prints the day that is stored whichever
 * format it is stored in. Unpadded month and day: that is what the old
 * `getMonth()+1`/`getDate()` produced and what the row is laid out for.
 */
export function formatInsuranceExpiryShort(raw) {
  const parsed = parseStoredDate(raw);
  if (parsed.kind === 'blank') return '--';
  // THE RAW STRING IS NOT PRINTED HERE. It used to be (sliced to ten
  // characters), which in a six-character badge reads as a date rather than as
  // a failure. One word that says what is wrong is more use than a truncated
  // quote; the Settings form quotes it in full, next to the field that fixes
  // it (`storedDateNote` in dateEntry.js).
  if (parsed.kind === 'unreadable') return INSURANCE_DATE_UNREADABLE_SHORT;
  const [y, m, d] = parsed.iso.split('-').map(Number);
  return `${m}/${d}/${String(y).slice(2)}`;
}

/**
 * 'Jul 21, 2029' for the Settings insurance cards, which have a full row.
 *
 * NOT `toLocaleDateString('en-US', …)`. That is where the day was lost: it
 * formats an INSTANT in the device's zone, and the instant a date-only string
 * parses to is UTC midnight. The month table is three numbers turned into
 * text, with no instant in between. en-US is not a regression — the call it
 * replaces hard-coded that locale too.
 */
export function formatInsuranceExpiryLong(raw) {
  const parsed = parseStoredDate(raw);
  if (parsed.kind === 'blank') return '--';
  if (parsed.kind === 'unreadable') return INSURANCE_DATE_UNREADABLE;
  const [y, m, d] = parsed.iso.split('-').map(Number);
  return `${MONTHS_SHORT[m - 1]} ${d}, ${y}`;
}
