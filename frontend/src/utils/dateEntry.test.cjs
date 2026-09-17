/**
 * ONE DATE FIELD, TYPED ON A NUMBER PAD, SHOWN US, STORED ISO.
 *
 * The operator's ruling, as behaviour this file executes:
 *
 *   typing 07212029      shows 07/21/2029      hands the host 2029-07-21
 *   13/45/2029, 02/30/2029, 02/29/2027        refused before Save
 *   a stored '07/212029'  shown as 07/21/2029  for confirmation, not written
 *
 * WHAT THIS IS NOT. It is not a test of the component's JSX. Every rule the
 * component applies lives in src/utils/dateEntry.js so it can be asked
 * questions here under plain node; dateInputCensus.test.cjs asserts the
 * screens actually use it.
 *
 * Run:  node src/utils/dateEntry.test.cjs
 */
const { loadEsm } = require('./esmHarness.cjs');

const D = loadEsm('src/utils/dateEntry.js');

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failures += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const eq = (a, b, what) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${what}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

/** Type `keys` one at a time, the way a number pad delivers them. */
const typeKeys = (keys, start = '') => {
  let text = start;
  for (const k of keys) text = D.nextEntryText(text, text + k);
  return text;
};
/** Backspace at the END of the field, `n` times. */
const backspace = (text, n = 1) => {
  let t = text;
  for (let i = 0; i < n; i += 1) t = D.nextEntryText(t, t.slice(0, -1));
  return t;
};

console.log('\ndate entry\n');

// ── 1. THE RULING'S OWN EXAMPLE ─────────────────────────────────────────────

check('07212029 shows 07/21/2029 and hands the host 2029-07-21', () => {
  const text = typeKeys('07212029');
  eq(text, '07/21/2029', 'display');
  eq(D.valueForHost(text), '2029-07-21', 'host value');
  eq(D.entryState(text).error, null, 'error');
});

check('the slashes arrive as the digits do, never ahead of them', () => {
  // A slash inserted BEFORE the next digit is what traps backspace: deleting
  // it re-inserts it. So '07' stays '07' until the third digit arrives.
  const seen = [];
  let t = '';
  for (const k of '07212029') { t = D.nextEntryText(t, t + k); seen.push(t); }
  eq(seen, ['0', '07', '07/2', '07/21', '07/21/2', '07/21/20', '07/21/202', '07/21/2029'],
    'keystroke sequence');
});

check('a ninth digit is ignored', () => {
  eq(typeKeys('072120291'), '07/21/2029', 'capped at 8 digits');
  eq(D.nextEntryText('07/21/2029', '07/21/20299'), '07/21/2029', 'typed at the end');
});

check('letters and punctuation typed on a hardware keyboard are dropped', () => {
  eq(D.nextEntryText('', '0a7-2.1'), '07/21', 'non-digits');
});

// ── 2. BACKSPACE ────────────────────────────────────────────────────────────

check('backspace from the end walks back through the slashes', () => {
  const seen = [];
  let t = '07/21/2029';
  while (t) { t = backspace(t); seen.push(t); }
  eq(seen, ['07/21/202', '07/21/20', '07/21/2', '07/21', '07/2', '07', '0', ''],
    'backspace sequence');
});

check('deleting a slash in the middle deletes the digit before it', () => {
  // Cursor after the first slash, backspace: the OS removes the slash. With
  // the digits unchanged a naive reformat puts it straight back and the key
  // does nothing — the field is "stuck". It must take the 7 instead.
  eq(D.nextEntryText('07/21/2029', '0721/2029'), '02/12/029', 'first slash');
  eq(D.nextEntryText('07/21/2029', '07/212029'), '07/22/029', 'second slash');
});

check('deleting a slash that has no digit before it is a no-op, not a throw', () => {
  eq(D.nextEntryText('/', ''), '', 'lone slash');
});

check('clearing the field hands the host an empty string', () => {
  eq(D.nextEntryText('07/21/2029', ''), '', 'cleared');
  eq(D.valueForHost(''), '', 'host value');
});

// ── 3. PASTE ────────────────────────────────────────────────────────────────

check('a pasted US date lands as typed', () => {
  eq(D.nextEntryText('', '07/21/2029'), '07/21/2029', 'US');
  eq(D.nextEntryText('', '07212029'), '07/21/2029', 'bare digits');
});

check('a pasted ISO date is turned around, not read as MMDDYYYY', () => {
  // Stripped naively, 2029-07-21 is the digits 20290721 = "20/29/0721".
  eq(D.nextEntryText('', '2029-07-21'), '07/21/2029', 'ISO');
  eq(D.nextEntryText('', ' 2029-07-21 '), '07/21/2029', 'ISO with spaces');
  eq(D.nextEntryText('07/', '2029-07-21'), '07/21/2029', 'over a partial');
});

check('an impossible pasted ISO date still shows, and is refused', () => {
  const t = D.nextEntryText('', '2029-02-30');
  eq(t, '02/30/2029', 'shown so the error has something to point at');
  ok(D.entryState(t).error, 'accepted 02/30/2029');
});

check('a pasted run of more than eight digits is capped', () => {
  eq(D.nextEntryText('', '0721202912345'), '07/21/2029', 'capped');
});

// ── 4. THE CALENDAR, ARITHMETICALLY ─────────────────────────────────────────

check('the ruling\'s three refusals are refused', () => {
  for (const t of ['13/45/2029', '02/30/2029', '02/29/2027']) {
    ok(D.entryState(t).error, `${t} was accepted`);
    eq(D.valueForHost(t), t, `${t} must not become an ISO value`);
    ok(D.dateEntryError(t), `${t} passed the host-side check`);
    eq(D.toStoredDate(t), null, `${t} has a stored form`);
  }
});

check('02/29/2027 says why: 2027 is not a leap year', () => {
  ok(/leap/.test(D.entryState('02/29/2027').error), D.entryState('02/29/2027').error);
});

check('month lengths, all twelve, in a leap and a common year', () => {
  const common = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const leap = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  for (let m = 1; m <= 12; m += 1) {
    eq(D.daysInMonth(2027, m), common[m - 1], `2027-${m}`);
    eq(D.daysInMonth(2028, m), leap[m - 1], `2028-${m}`);
    const mm = String(m).padStart(2, '0');
    const last = String(common[m - 1]).padStart(2, '0');
    const over = String(common[m - 1] + 1).padStart(2, '0');
    eq(D.entryState(`${mm}/${last}/2027`).error, null, `${mm}/${last}/2027`);
    ok(D.entryState(`${mm}/${over}/2027`).error, `${mm}/${over}/2027 was accepted`);
  }
});

check('the Gregorian leap rule: 4 yes, 100 no, 400 yes', () => {
  eq(D.isLeapYear(2028), true, '2028');
  eq(D.isLeapYear(2027), false, '2027');
  eq(D.isLeapYear(2100), false, '2100');
  eq(D.isLeapYear(2000), true, '2000');
  eq(D.entryState('02/29/2000').error, null, '02/29/2000');
  ok(D.entryState('02/29/2100').error, '02/29/2100 was accepted');
  eq(D.valueForHost('02/29/2028'), '2028-02-29', 'leap day');
});

check('month 00, day 00 and month 13 are refused', () => {
  for (const t of ['00/10/2029', '01/00/2029', '13/01/2029']) {
    ok(D.entryState(t).error, `${t} was accepted`);
  }
});

check('an impossible month is named at the second digit, not at the eighth', () => {
  ok(/month 13/.test(D.entryState('13').error || ''), 'month 13 not named');
  ok(/day 45/.test(D.entryState('01/45').error || ''), 'day 45 not named');
  ok(D.entryState('04/31').error, 'April 31 not named before the year');
});

check('a year outside 1900-2199 is refused', () => {
  // THE BOUND IS WHAT MAKES AN 8-DIGIT STRING UNAMBIGUOUS. With a year of
  // 19xx-21xx, YYYYMMDD read as MMDDYYYY has a month of 19-21, which does not
  // exist, so no string is a valid date both ways.
  ok(D.entryState('07/21/0229').error, 'year 0229 accepted');
  ok(D.entryState('07/21/1899').error, 'year 1899 accepted');
  ok(D.entryState('07/21/2200').error, 'year 2200 accepted');
  eq(D.entryState('01/01/1900').error, null, '1900');
  eq(D.entryState('12/31/2199').error, null, '2199');
});

check('an unfinished date is not a date', () => {
  for (const t of ['0', '07', '07/2', '07/21/202']) {
    const st = D.entryState(t);
    ok(st.error, `${t} has no message`);
    eq(st.partial, true, `${t} partial`);
    eq(st.iso, null, `${t} iso`);
    eq(D.valueForHost(t), t, `${t} host value`);
    eq(D.valueForHost(t, 'blank'), '', `${t} host value, blank mode`);
    ok(D.dateEntryError(t), `${t} passed the host-side check`);
  }
});

// ── 5. ISO IS BUILT FROM THE THREE NUMBERS ──────────────────────────────────

check('ISO round-trip, every day of a leap year and a common year', () => {
  for (const y of [2027, 2028]) {
    for (let m = 1; m <= 12; m += 1) {
      for (let d = 1; d <= D.daysInMonth(y, m); d += 1) {
        const iso = D.isoFromParts(y, m, d);
        const shown = D.displayFromIso(iso);
        const typed = typeKeys(shown.replace(/\//g, ''));
        eq(typed, shown, `typed ${iso}`);
        eq(D.valueForHost(typed), iso, `round-trip ${iso}`);
        eq(D.toStoredDate(iso), iso, `stored ${iso}`);
      }
    }
  }
});

check('the stored value does not depend on the timezone', () => {
  // A calendar day is not an instant. `new Date(2029, 0, 1).toISOString()` is
  // 2029-01-01T05:00Z in America/New_York and 2028-12-31T10:00Z in
  // Pacific/Kiritimati — a day earlier. The module must give one answer.
  //
  // THE INSTRUMENT IS CHECKED FIRST. If this node ignores a TZ change mid-run,
  // the loop below proves nothing, so the Date-built answer — the defect this
  // guards against — must be SEEN to vary before the real answer counts.
  const before = process.env.TZ;
  const out = [];
  const naive = new Set();
  for (const tz of ['America/New_York', 'Pacific/Kiritimati', 'Etc/GMT+12', 'UTC']) {
    process.env.TZ = tz;
    naive.add(new Date(2029, 0, 1).toISOString().slice(0, 10));
    out.push(D.valueForHost('01/01/2029'), D.valueForHost('12/31/2029'));
  }
  if (before === undefined) delete process.env.TZ; else process.env.TZ = before;
  ok(naive.size > 1, 'TZ switching has no effect here, so this check is disarmed');
  eq([...new Set(out)], ['2029-01-01', '2029-12-31'], 'values across zones');
});

check('the module never constructs a Date', () => {
  // `new Date('2029-02-30')` rolls over to March 2 and `new Date('07/21/2029')`
  // is engine-dependent. Validation is arithmetic; a Date here is a defect.
  const fs = require('fs');
  const path = require('path');
  const src = fs.readFileSync(path.join(__dirname, 'dateEntry.js'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/\bDate\s*[.(]/.test(code) && !/new\s+Date\b/.test(code),
    'dateEntry.js uses Date');
});

// ── 6. A STORED VALUE, READ BACK ────────────────────────────────────────────
//
// THE ACCEPTANCE RULE. A stored string is READABLE when, trimmed, it is
//
//   (a) YYYY-MM-DD exactly — ISO 8601, self-describing; or
//   (b) exactly eight digits in MMDDYYYY order, with a slash optionally after
//       the MM and optionally after the DD, and nothing else —
//       07212029, 07/212029, 0721/2029, 07/21/2029;
//
// AND the three numbers are a real calendar day with a year in 1900-2199.
// Anything else is UNREADABLE: shown as such, with an empty field. The digits
// are never reordered (except ISO, whose order is written into its shape), no
// month or day is zero-padded on the reader's behalf, and a two-digit year is
// never widened. A slashed form is read as MM/DD because that is this app's
// display format; a string whose first pair cannot be a month is refused, not
// re-read as DD/MM.

check('Michael\'s stored value is read, shown formatted, and not written', () => {
  const p = D.parseStoredDate('07/212029');
  eq(p.kind, 'legacy', 'kind');
  eq(p.display, '07/21/2029', 'display');
  eq(p.iso, '2029-07-21', 'iso');
  eq(D.initialEntryText('07/212029'), '07/21/2029', 'field text');
  eq(D.dateEntryError('07/212029'), null, 'host-side check');
  eq(D.toStoredDate('07/212029'), '2029-07-21', 'what Save sends');
  const note = D.storedDateNote('07/212029');
  ok(note && note.text.includes('"07/212029"') && note.text.includes('07/21/2029'),
    `note: ${note && note.text}`);
  ok(/until you save/i.test(note.text), `note does not say nothing is saved yet: ${note.text}`);
});

check('the accepted shapes are accepted', () => {
  for (const raw of ['07212029', '07/212029', '0721/2029', '07/21/2029', '2029-07-21',
    '  07/21/2029  ']) {
    eq(D.parseStoredDate(raw).iso, '2029-07-21', raw);
  }
  eq(D.parseStoredDate('2029-07-21').kind, 'iso', 'ISO kind');
});

check('the ambiguous and malformed shapes are unreadable, never guessed', () => {
  for (const raw of [
    '2029', '7/2/29', '7/21/2029', '07/21/29', '21/07/2029', '2029/07/21',
    '20290721', '2029-7-21', '21-07-2029', '07-21-2029', '07.21.2029',
    'July 21, 2029', 'soon', '07//212029', '/07212029', '072120290',
    '0721202', '2029-07-21T00:00:00Z', '2029-02-30', '02/30/2029', '13/45/2029',
  ]) {
    const p = D.parseStoredDate(raw);
    eq(p.kind, 'unreadable', raw);
    eq(p.iso, null, `${raw} iso`);
    eq(D.initialEntryText(raw), '', `${raw} field text must be empty`);
    eq(D.toStoredDate(raw), null, `${raw} stored form`);
    ok(D.dateEntryError(raw), `${raw} passed the host-side check`);
  }
});

check('where nothing converts on save, the note does not promise that it will', () => {
  // A logbook stepper has no Save that runs toStoredDate(): an untouched
  // '07/212029' is filed as written. Telling the CP "nothing changes until
  // you save" would imply saving fixes it.
  const note = D.storedDateNote('07/212029', { convertsOnSave: false });
  ok(note && note.text.includes('"07/212029"') && note.text.includes('07/21/2029'),
    `note: ${note && note.text}`);
  ok(!/until you save/i.test(note.text), `promises a conversion: ${note.text}`);
  ok(/type|pick/i.test(note.text), `does not say how to record it: ${note.text}`);
});

check('an unreadable stored value is named in the note, verbatim', () => {
  const note = D.storedDateNote('soon');
  eq(note.tone, 'error', 'tone');
  ok(note.text.includes('"soon"'), note.text);
  ok(note.text.includes('MM/DD/YYYY'), note.text);
  ok(!note.text.includes('YYYY-MM-DD'), `note names the storage format: ${note.text}`);
});

check('a stored value already in display form needs no note', () => {
  eq(D.storedDateNote('07/21/2029'), null, 'US');
  eq(D.storedDateNote('2029-07-21'), null, 'ISO');
  eq(D.storedDateNote(''), null, 'blank');
  eq(D.storedDateNote(null), null, 'null');
});

check('blank is an absence, not an error', () => {
  for (const blank of ['', '   ', null, undefined]) {
    eq(D.dateEntryError(blank), null, JSON.stringify(blank));
    eq(D.toStoredDate(blank), '', JSON.stringify(blank));
    eq(D.parseStoredDate(blank).kind, 'blank', JSON.stringify(blank));
  }
});

check('no 8-digit string is a valid date both as MMDDYYYY and as YYYYMMDD', () => {
  // The reason 07212029 may be read at all. Exhaustive over the year bound.
  for (let y = 1900; y <= 2199; y += 1) {
    const mmdd = String(y).slice(0, 2);
    ok(Number(mmdd) > 12, `${y}: first pair ${mmdd} is a month`);
  }
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
