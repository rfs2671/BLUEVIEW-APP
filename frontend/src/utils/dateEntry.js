/**
 * EVERY RULE THE SHARED DATE FIELD APPLIES, WITH NOTHING TO RENDER.
 *
 * The operator's ruling: every date field in the app is typed on a number pad,
 * shows MM/DD/YYYY with the slashes inserted as the digits arrive, stores ISO
 * YYYY-MM-DD, and refuses an impossible date before Save. The component is
 * src/components/DateInput.jsx; this module is everything it decides, so
 * dateEntry.test.cjs can ask it questions under plain node.
 *
 * ── WHAT A HOST HOLDS ───────────────────────────────────────────────────────
 *
 * ONE STRING, as before. The component hands its host:
 *
 *   ''            the field is empty
 *   'YYYY-MM-DD'  the digits are a complete, real calendar day
 *   the display text, as typed, for anything else ('07/2', '13/45/2029')
 *
 * so a host's existing `useState('')` keeps working, and the host decides
 * whether to save by asking `dateEntryError(value)` — the same function for
 * every screen. The value it SENDS is `toStoredDate(value)`, which is always
 * ISO or ''. The display string never reaches an API.
 *
 * A host may also hold a value it LOADED — a stored string this app did not
 * write, like '07/212029'. The component shows it read (07/21/2029) and does
 * not call the host. The host's value is unchanged, so nothing is dirty and
 * nothing is saved; `toStoredDate` turns it into ISO only when the person
 * presses Save. That is the ruling's "no silent write", as behaviour.
 *
 * ── WHAT THIS IS NOT ────────────────────────────────────────────────────────
 *
 * NOT A DATE LIBRARY. There is no `Date` anywhere in this file and the test
 * asserts it. `new Date('2029-02-30')` is March 2nd; `new Date('07/21/2029')`
 * is engine-dependent between Hermes and a browser; and a stored value built
 * with `toISOString()` is a day early east of UTC. A calendar day is three
 * numbers, validated with a table of month lengths and the Gregorian leap
 * rule — which is also exactly what Python's `strptime('%Y-%m-%d')` accepts,
 * so the server's reader and this field agree about every value.
 *
 * NOT AN EXPIRY VERDICT. Whether a date has passed is the server's answer
 * (`superintendent_licence_state` and friends). This module never reads the
 * clock.
 */

/** What the person types and reads. Printed in placeholders and messages. */
export const DATE_DISPLAY_FORMAT = 'MM/DD/YYYY';

// THE YEAR BOUND IS NOT DECORATION. It is what makes a bare run of eight
// digits unambiguous: with a year in 19xx-21xx, a YYYYMMDD string read as
// MMDDYYYY has a "month" of 19, 20 or 21, which does not exist — so no string
// is a valid date both ways. It also catches the dropped digit ('07/21/229').
export const MIN_YEAR = 1900;
export const MAX_YEAR = 2199;

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const pad = (n, width) => String(n).padStart(width, '0');

/** The Gregorian rule: every 4th year, except centuries, except every 400th. */
export function isLeapYear(y) {
  return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
}

/** Days in a month. `m` is 1-12. Arithmetic, not a Date rollover trick. */
export function daysInMonth(y, m) {
  if (m === 2) return isLeapYear(y) ? 29 : 28;
  return [4, 6, 9, 11].includes(m) ? 30 : 31;
}

/** 'YYYY-MM-DD' built from the three numbers — never from an instant. */
export function isoFromParts(y, m, d) {
  return `${pad(y, 4)}-${pad(m, 2)}-${pad(d, 2)}`;
}

/** Why these three numbers are not a day this app accepts, or null. */
export function calendarError(y, m, d) {
  if (m < 1 || m > 12) return `There is no month ${pad(m, 2)}.`;
  if (y < MIN_YEAR || y > MAX_YEAR) {
    return `Check the year — ${pad(y, 4)} is outside ${MIN_YEAR}–${MAX_YEAR}.`;
  }
  const last = daysInMonth(y, m);
  if (d < 1 || d > last) {
    // THE LEAP CASE SAYS WHY. "02/29/2027 is not a date" leaves him counting;
    // "2027 is not a leap year" is the fact he is missing.
    if (m === 2 && d === 29) {
      return `${y} is not a leap year — February ${y} has 28 days.`;
    }
    if (d < 1) return 'There is no day 00.';
    return `${MONTH_NAMES[m - 1]} ${y} has ${last} days.`;
  }
  return null;
}

/** '0721' -> '07/21'. A slash appears only once a digit follows it. */
export function digitsToDisplay(digits) {
  const d = String(digits || '');
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}/${d.slice(2)}`;
  return `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`;
}

/** '2029-07-21' -> '07/21/2029', or null for anything that is not ISO-shaped. */
export function displayFromIso(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso == null ? '' : iso).trim());
  return m ? `${m[2]}/${m[3]}/${m[1]}` : null;
}

const digitsOf = (text) => String(text || '').replace(/\D/g, '');

/**
 * The field's next text, given what it showed and what the OS handed back.
 *
 * WHY IT TAKES THE PREVIOUS TEXT. Backspace with the cursor just after a
 * slash removes the slash; the digits are unchanged, so a plain reformat puts
 * the slash straight back and the key appears dead. Seeing that the text got
 * shorter while the digits did not, this removes the digit BEFORE the slash —
 * what the person meant.
 *
 * WHY A SLASH IS NEVER ADDED AHEAD OF ITS DIGIT. '07' followed by an
 * automatic '/' is the classic trap: backspace deletes the slash, the
 * formatter re-adds it, and the field cannot be emptied past it.
 *
 * PASTE. A pasted ISO date is turned into display order — stripped of its
 * dashes it would read as month 20. Every other paste is its digits, capped
 * at eight, the same as typing them.
 */
export function nextEntryText(prevText, rawText) {
  const prev = String(prevText == null ? '' : prevText);
  const raw = String(rawText == null ? '' : rawText);

  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw.trim());
  if (iso) return digitsToDisplay(`${iso[2]}${iso[3]}${iso[1]}`);

  let digits = digitsOf(raw);
  if (digits === digitsOf(prev) && raw.length < prev.length) {
    // A separator went. Find it, and take the digit in front of it instead.
    let i = 0;
    while (i < raw.length && raw[i] === prev[i]) i += 1;
    const before = digitsOf(prev.slice(0, i)).length;
    if (before > 0) digits = digits.slice(0, before - 1) + digits.slice(before);
  }
  return digitsToDisplay(digits.slice(0, 8));
}

/**
 * What the field's text currently amounts to.
 *
 * `error` is a sentence or null. It is set as EARLY as the digits allow — a
 * month of 13 is named at the second digit, not after the year is typed —
 * because a message that waits is a message that arrives after he has
 * stopped looking at the field. An unfinished date also carries a sentence
 * (`partial: true`) so a host that asks "may I save?" gets no.
 */
export function entryState(text) {
  const digits = digitsOf(text).slice(0, 8);
  const out = { digits, iso: null, error: null, partial: false };
  if (!digits) return out;

  const m = digits.length >= 2 ? Number(digits.slice(0, 2)) : null;
  const d = digits.length >= 4 ? Number(digits.slice(2, 4)) : null;
  if (m !== null && (m < 1 || m > 12)) {
    out.error = `There is no month ${digits.slice(0, 2)} — type the month as two digits, e.g. 03 for March.`;
    return out;
  }
  if (d !== null) {
    if (d < 1 || d > 31) {
      out.error = `There is no day ${digits.slice(2, 4)}.`;
      return out;
    }
    // Before the year: every month but February has a length that does not
    // depend on it, and February never has more than 29.
    const most = m === 2 ? 29 : daysInMonth(2000, m);
    if (d > most) {
      out.error = `${MONTH_NAMES[m - 1]} has ${most} days.`;
      return out;
    }
  }
  if (digits.length < 8) {
    out.partial = true;
    out.error = `Finish the date: ${DATE_DISPLAY_FORMAT}.`;
    return out;
  }
  const y = Number(digits.slice(4, 8));
  const err = calendarError(y, m, d);
  if (err) {
    out.error = err;
    return out;
  }
  out.iso = isoFromParts(y, m, d);
  return out;
}

/**
 * What the component hands its host for this text. See the header.
 *
 * `mode === 'blank'` is for a host with no Save to block — the logbook
 * steppers, whose incomplete steps MARK and never GATE. There an unfinished
 * or impossible date is recorded as nothing, rather than as a half-typed
 * string on a filed document; the field keeps showing what he typed and why
 * it is not a date.
 */
export function valueForHost(text, mode = 'text') {
  const st = entryState(text);
  if (!st.digits) return '';
  if (st.iso) return st.iso;
  return mode === 'blank' ? '' : String(text);
}

/**
 * A stored string, read under the ACCEPTANCE RULE:
 *
 *   (a) YYYY-MM-DD exactly — ISO 8601, which states its own order; or
 *   (b) exactly eight digits in MMDDYYYY order, with a slash optionally after
 *       the MM and optionally after the DD and nothing else — 07212029,
 *       07/212029, 0721/2029, 07/21/2029;
 *
 * and the numbers are a real day with a year in MIN_YEAR-MAX_YEAR.
 *
 * Returns {kind, raw, iso, display}; kind is 'blank' | 'iso' | 'legacy' |
 * 'unreadable'.
 *
 * WHAT IS REFUSED, AND WHY IT IS REFUSED RATHER THAN GUESSED. '7/2/29' has a
 * two-digit year and a month that could be a day. '2029' is not a day.
 * '21/07/2029' has no month 21 and is NOT re-read as DD/MM — the digits are
 * never reordered, no field is zero-padded on the writer's behalf, and a
 * two-digit year is never widened. The slashed form is read as MM/DD because
 * that is this app's display format: the person confirming it sees the
 * digits in the order they were stored.
 *
 * THIS IS WIDER THAN `server.parse_cert_date`, deliberately. That parser
 * refuses '10272029' because it writes without a human looking; this reader
 * only SHOWS a value to the person about to press Save.
 */
export function parseStoredDate(raw) {
  const s = String(raw == null ? '' : raw).trim();
  if (!s) return { kind: 'blank', raw: s, iso: null, display: null };

  let y; let m; let d; let kind;
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  const us = /^(\d{2})\/?(\d{2})\/?(\d{4})$/.exec(s);
  if (iso) {
    [y, m, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
    kind = 'iso';
  } else if (us) {
    [m, d, y] = [Number(us[1]), Number(us[2]), Number(us[3])];
    kind = 'legacy';
  } else {
    return { kind: 'unreadable', raw: s, iso: null, display: null };
  }
  if (calendarError(y, m, d)) {
    return { kind: 'unreadable', raw: s, iso: null, display: null };
  }
  return {
    kind, raw: s, iso: isoFromParts(y, m, d), display: `${pad(m, 2)}/${pad(d, 2)}/${pad(y, 4)}`,
  };
}

/** The text a field opens with for a stored value: read, or empty. */
export function initialEntryText(raw) {
  return parseStoredDate(raw).display || '';
}

/**
 * What the field says about a stored value it did not write, or null.
 *
 * A readable value that is not already in display form is SHOWN READ, and the
 * note says so — with the stored string verbatim, so the person can see what
 * was read and confirm it. An unreadable value leaves the field empty and the
 * note carries the string, so nothing is silently dropped either.
 *
 * `convertsOnSave` says whether the host's Save runs toStoredDate(). The admin
 * forms do, so "nothing changes until you save" is the truth there. A logbook
 * stepper does not — an untouched legacy value is filed as written — so there
 * the note says how to record the date instead of promising a conversion.
 */
export function storedDateNote(raw, { convertsOnSave = true } = {}) {
  const p = parseStoredDate(raw);
  if (p.kind === 'unreadable') {
    return {
      tone: 'error',
      text: `Stored as "${p.raw}", which is not a date this app can read. Enter it as ${DATE_DISPLAY_FORMAT}.`,
    };
  }
  if (p.kind === 'legacy' && p.raw !== p.display) {
    return {
      tone: 'hint',
      text: convertsOnSave
        ? `Stored as "${p.raw}" — read as ${p.display}. Check it; nothing changes until you save.`
        : `Stored as "${p.raw}" — read as ${p.display}. It stays as written until you type or pick the date.`,
    };
  }
  return null;
}

/**
 * THE host-side check: why this value may not be saved, or null.
 *
 * One function for every screen, so the field's message and the Save refusal
 * cannot disagree. Blank is not an error — an empty field records nothing,
 * and refusing '' would make clearing a date impossible.
 */
export function dateEntryError(value) {
  const s = String(value == null ? '' : value).trim();
  const p = parseStoredDate(s);
  if (p.kind === 'blank' || p.iso) return null;
  // Text the field produced: digits and slashes. Its own sentence is better
  // than a generic one ("There is no month 13.").
  if (/^[\d/]+$/.test(s)) {
    return entryState(s).error || `Enter the date as ${DATE_DISPLAY_FORMAT}.`;
  }
  return `"${s}" is not a date this app can read. Enter it as ${DATE_DISPLAY_FORMAT}.`;
}

/**
 * What a host SENDS: ISO for any readable value, '' for blank, null when the
 * value may not be saved. Never the display string.
 */
export function toStoredDate(value) {
  const p = parseStoredDate(value);
  if (p.kind === 'blank') return '';
  return p.iso;
}

/** A stored value for reading (lists, badges): MM/DD/YYYY, or the raw string. */
export function formatStoredDate(raw) {
  const p = parseStoredDate(raw);
  return p.display || p.raw;
}
