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
    // THE HOST IS HANDED THE TEXT, AND THAT IS THE WHOLE CONTRACT. There was
    // a second mode here — `valueForHost(t, 'blank')` returned '' for the
    // logbook steppers — and it blanked dates on filed legal records. It is
    // gone; logbookDateGate.test.cjs asserts nothing can ask for it.
    eq(D.valueForHost(t), t, `${t} host value`);
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

// ── 7. THE CARET, WHEN THE FIELD RE-FORMATS UNDER THE PERSON TYPING ─────────
//
// On web the field is a real <input>. Every keystroke is re-formatted and the
// new text written back into it, and a browser puts the caret at the END of a
// value it did not see typed. So fixing the day in 07/21/2029 — backspace,
// type — sent the caret to the year, and the corrected day was typed there.
//
// nextEntry() answers where the caret goes, in the units the formatter works
// in: DIGITS, not characters. The caret sits after the SAME DIGIT it was
// after — one fewer when the edit removed a digit — whatever the slashes did
// around it. `.text` is exactly what nextEntryText() has always returned, so
// native, which keeps its own caret and is handed no selection, is unmoved.

/** How many digits sit before `caret` in `text` — the only unit that maps. */
const digitsBefore = (text, caret) => (String(text).slice(0, caret).match(/\d/g) || []).length;

check('the caret follows the slash the formatter inserted', () => {
  // '07' plus a '2' is re-written as '07/2': one character was typed and the
  // caret must move two, or the next digit lands before the slash.
  eq(D.nextEntry('07', '072', 3), { text: '07/2', caret: 4 }, 'third digit');
  eq(D.nextEntry('07/21', '07/212', 6), { text: '07/21/2', caret: 7 }, 'fifth digit');
  eq(D.nextEntry('07/2', '07/21', 5), { text: '07/21', caret: 5 }, 'no slash due');
  // And in the middle, where the end of the field is the wrong answer:
  eq(D.nextEntry('07/2', '075/2', 3), { text: '07/52', caret: 4 }, 'mid-field');
});

check('fixing the day in 07/21/2029 leaves the caret in the day', () => {
  // THE REPORTED DEFECT, end to end. Caret after the 1 of 21; backspace; 5.
  // The day must read 25 — not 07/22/0295, with the 5 typed into the year.
  const gone = D.nextEntry('07/21/2029', '07/2/2029', 4);
  eq(gone, { text: '07/22/029', caret: 4 }, 'after the backspace');
  const typed = D.nextEntry(gone.text, '07/252/029', 5);
  eq(typed, { text: '07/25/2029', caret: 5 }, 'after the 5');
  eq(digitsBefore(typed.text, typed.caret), 4, 'digits before the caret');
});

check('backspace over a slash puts the caret where the digit it ate was', () => {
  // The OS removed the slash; the formatter takes the digit in front of it
  // instead (section 2). The caret must follow that digit, not the slash.
  eq(D.nextEntry('07/21/2029', '07/212029', 5), { text: '07/22/029', caret: 4 },
    'second slash');
  eq(D.nextEntry('07/21/2029', '0721/2029', 2), { text: '02/12/029', caret: 1 },
    'first slash');
  eq(D.nextEntry('/', '', 0), { text: '', caret: 0 }, 'a slash with no digit before it');
});

check('a paste lands the caret after what was pasted', () => {
  eq(D.nextEntry('', '07212029', 8), { text: '07/21/2029', caret: 10 }, 'bare digits');
  eq(D.nextEntry('', '07/21/2029', 10), { text: '07/21/2029', caret: 10 }, 'US');
  // A pasted ISO date is turned around; no position in '2029-07-21' maps to a
  // position in '07/21/2029', so the caret goes to the end of what landed.
  eq(D.nextEntry('', '2029-07-21', 10), { text: '07/21/2029', caret: 10 }, 'ISO');
  eq(D.nextEntry('', '2029-07-21', 4), { text: '07/21/2029', caret: 10 }, 'ISO, caret anywhere');
  // Pasted over a selected day: the caret stays at the end of the paste.
  eq(D.nextEntry('07/21/2029', '07/15/2029', 5), { text: '07/15/2029', caret: 5 }, 'over the day');
  // Pasted in front of a full date: the tail is capped off, the caret is not.
  eq(D.nextEntry('07/21/2029', '1207/21/2029', 2), { text: '12/07/2120', caret: 2 }, 'at the front');
});

check('the ends are the ends', () => {
  eq(D.nextEntry('07/21/2029', '', 0), { text: '', caret: 0 }, 'cleared');
  eq(D.nextEntry('07/21/2029', '5', 1), { text: '5', caret: 1 }, 'select all, then a digit');
  eq(D.nextEntry('07/21/2029', '7/21/2029', 0), { text: '72/12/029', caret: 0 }, 'first digit gone');
  eq(D.nextEntry('07/21/2029', '07/21/20299', 11), { text: '07/21/2029', caret: 10 },
    'a ninth digit at the end');
});

check('a caret that is missing, out of range or not a number falls back safely', () => {
  // Native never reports one, and a host input that does not forward the DOM
  // event cannot. The old behaviour — the caret at the end — is what happens.
  for (const c of [undefined, null, NaN, '4', {}]) {
    const out = D.nextEntry('07', '072', c);
    eq(out.text, '07/2', `text for ${String(c)}`);
    eq(out.caret, 4, `caret for ${String(c)}`);
  }
  eq(D.nextEntry('07', '072').caret, 4, 'omitted entirely');
  eq(D.nextEntry('07/21/2029', '0721/2029', -1).caret, 0, 'clamped low');
  eq(D.nextEntry('07/21/2029', '07/212029', 99).caret, 9, 'clamped high');
});

check('inserting a digit anywhere leaves the caret just after that digit', () => {
  // Exhaustive over every position in a full date: the caret lands on the
  // digit the person just typed, never at the end of the field.
  const prev = '07/21/2029';
  for (let p = 0; p <= prev.length; p += 1) {
    const raw = `${prev.slice(0, p)}5${prev.slice(p)}`;
    const out = D.nextEntry(prev, raw, p + 1);
    eq(out.text, D.nextEntryText(prev, raw), `text at ${p}`);
    const want = Math.min(digitsBefore(raw, p + 1), 8);
    eq(digitsBefore(out.text, out.caret), want, `digits before the caret at ${p}`);
    if (digitsBefore(raw, p + 1) <= 8) {
      eq(out.text[out.caret - 1], '5', `the caret sits after the typed digit at ${p}`);
    }
  }
});

check('deleting anything anywhere leaves the caret where the deletion was', () => {
  // Backspace at every position. Deleting a SLASH deletes the digit in front
  // of it instead, so one fewer digit sits before the caret; deleting a digit
  // leaves the count alone. Nothing here may send the caret to the end.
  const prev = '07/21/2029';
  for (let p = 0; p < prev.length; p += 1) {
    const raw = prev.slice(0, p) + prev.slice(p + 1);
    const out = D.nextEntry(prev, raw, p);
    eq(out.text, D.nextEntryText(prev, raw), `text at ${p}`);
    const ate = prev[p] === '/' && digitsBefore(prev, p) > 0 ? 1 : 0;
    eq(digitsBefore(out.text, out.caret), digitsBefore(raw, p) - ate,
      `digits before the caret after deleting "${prev[p]}" at ${p}`);
  }
});

check('a caret changes where it lands, never what the field says', () => {
  // nextEntryText() is nextEntry() with no caret, and every check above runs
  // through it — so those are what prove the FORMATTER is untouched, and
  // native, which passes no caret, reads the field it always did. This is
  // the other half: a caret must not move a slash. Every pair this file
  // exercises, at every caret the raw text allows.
  const pairs = [
    ['', '0'], ['07', '072'], ['07/21/2029', '07/212029'], ['07/21/2029', '0721/2029'],
    ['07/21/2029', '07/2/2029'], ['', '2029-07-21'], ['', '0721202912345'],
    ['07/', '2029-07-21'], ['/', ''], ['07/21/2029', ''], ['', '0a7-2.1'],
    ['07/21/2029', '07/21/20299'], ['07/21/202', '07/21/2029'],
  ];
  for (const [prev, raw] of pairs) {
    for (let c = 0; c <= raw.length; c += 1) {
      eq(D.nextEntry(prev, raw, c).text, D.nextEntry(prev, raw).text, `${prev} -> ${raw} @${c}`);
    }
  }
});

check('the caret is always a real position in the text it is given', () => {
  // A caret past the end is a thrown setSelectionRange in the browser, and a
  // field that eats the keystroke. Every shape, every caret, both bounds.
  const raws = ['', '0', '072', '07/212029', '0721/2029', '07/2/2029', '2029-07-21',
    '0721202912345', '07/21/20299', '1207/21/2029', '5', '07//212029'];
  for (const prev of ['', '07', '07/21/2029']) {
    for (const raw of raws) {
      for (let c = 0; c <= raw.length; c += 1) {
        const out = D.nextEntry(prev, raw, c);
        ok(Number.isInteger(out.caret), `not an integer: ${prev} -> ${raw} @${c}`);
        ok(out.caret >= 0 && out.caret <= out.text.length,
          `caret ${out.caret} outside "${out.text}" for ${prev} -> ${raw} @${c}`);
      }
    }
  }
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
