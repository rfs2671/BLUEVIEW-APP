/**
 * NOTHING TYPED IS DISCARDED, AND NOTHING WRONG IS FILED.
 *
 * The defect: the logbook date field handed the log `''` for anything that was
 * not yet a real calendar day. `13/45/2029` and a half-finished `07/2` were
 * recorded as nothing, and a field already holding a good `2029-07-21` was
 * BLANKED by an edit the CP never finished — on a document he then signed.
 *
 * What this file executes:
 *
 *   1. the mode that blanked a value is GONE from dateEntry.js, so no host can
 *      ask for it again by passing a string
 *   2. THE OVERWRITE CASE, keystroke by keystroke: a stored 2029-07-21, three
 *      backspaces, and the value the host ends up holding is the text — never
 *      '' and never the old date pretending nothing happened
 *   3. the pre-flight finds exactly the dates the server will refuse, on the
 *      real payload shape of all three forms, and says nothing about the rows
 *      the sheet would not print
 *   4. the sentence names the field and quotes the value, from either side of
 *      the wire
 *
 * Run:  node src/utils/logbookDateGate.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const G = loadEsm('src/utils/logbookDateGate.js');
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

console.log('\nlogbook date gate\n');

// ── 1. THE BLANKING MODE IS GONE ────────────────────────────────────────────

check('valueForHost keeps what was typed, whatever second argument it is given', () => {
  // The trap was a MODE: `valueForHost(text, 'blank')` returned ''. The
  // logbook steppers were its only caller and the reason it existed, so it is
  // removed rather than left for the next host to reach for. A leftover caller
  // passing 'blank' must therefore get the TEXT, not a blank.
  for (const mode of [undefined, 'text', 'blank', null, 'anything']) {
    eq(D.valueForHost('07/2', mode), '07/2', `mode ${String(mode)}`);
    eq(D.valueForHost('13/45/2029', mode), '13/45/2029', `mode ${String(mode)}`);
    eq(D.valueForHost('', mode), '', `mode ${String(mode)} on empty`);
    eq(D.valueForHost('07/21/2029', mode), '2029-07-21', `mode ${String(mode)} on a real date`);
  }
});

check('the blank mode is not in the module any more, comments aside', () => {
  // SOURCE, STRIPPED. Several tests here have gone red over the comment
  // EXPLAINING a fix, so prose is removed before the claim is made.
  const src = fs.readFileSync(path.join(__dirname, 'dateEntry.js'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/'blank'/.test(code.replace(/kind === 'blank'|kind: 'blank'/g, '')),
    'dateEntry.js still has a blank mode in its code');
});

// ── 2. THE OVERWRITE CASE ───────────────────────────────────────────────────

check('a good stored date left half-edited is kept as typed, never blanked', () => {
  // The sequence a CP actually performs: the field opens on a stored
  // 2029-07-21 (shown 07/21/2029), he backspaces three times to fix the year
  // and is interrupted. This is what the host — the log — is left holding.
  let text = D.initialEntryText('2029-07-21');
  eq(text, '07/21/2029', 'the field opens on the stored date');
  const seen = [];
  for (let i = 0; i < 3; i += 1) {
    text = D.nextEntryText(text, text.slice(0, -1));
    seen.push(D.valueForHost(text));
  }
  eq(text, '07/21/2', 'what the field shows mid-edit');
  eq(seen, ['07/21/202', '07/21/20', '07/21/2'], 'what the host was handed');
  ok(!seen.includes(''), 'the log was blanked mid-edit');
  // And the log cannot be FILED in that state — that is the second half.
  ok(D.dateEntryError('07/21/2'), 'an unfinished date passed the host check');
  ok(!G.isFilableDate('07/21/2'), 'an unfinished date is filable');
  // Finishing it restores a real date, with nothing lost on the way.
  text = D.nextEntryText(text, `${text}029`);
  eq(D.valueForHost(text), '2029-07-21', 'the finished value');
});

check('an impossible date is kept, not swallowed', () => {
  for (const typed of ['13/45/2029', '02/30/2029', '02/29/2027']) {
    eq(D.valueForHost(typed), typed, `${typed} must reach the log as typed`);
    ok(!G.isFilableDate(typed), `${typed} is filable`);
  }
});

check('only ISO may be FILED, though more than ISO may be READ', () => {
  // parseStoredDate is deliberately wider: it reads '07/212029' so a legacy
  // value can be SHOWN for confirmation. What may be filed is narrower.
  ok(D.parseStoredDate('07/212029').iso, 'the reader cannot read 07/212029');
  ok(!G.isFilableDate('07/212029'), '07/212029 may not be filed as it stands');
  ok(G.isFilableDate('2029-07-21'), 'ISO may be filed');
  for (const bad of ['2029-02-30', '2027-02-29', '1899-12-31', '2200-01-01',
    '8/12', 'soon', '2029', null, undefined, 20290721]) {
    ok(!G.isFilableDate(bad), `${String(bad)} is filable`);
  }
});

// ── 3. THE PRE-FLIGHT, ON THE REAL PAYLOAD SHAPES ───────────────────────────

const fall = (v) => ({
  activities: [{ worker_name: 'WILMER CARRILLO', result: 'Pass', manufacture_date: v }],
});
const osha = (v) => ({
  entries: [{ worker_name: 'WILMER CARRILLO', company: 'aaz', expiration: v }],
});
const scaffold = (v, key = 'installation_date') => ({
  general_info: { scaffold_erector: 'aaz', [key]: v }, answers: {},
});

check('all three forms are covered, and only those three', () => {
  eq(Object.keys(G.LOGBOOK_DATE_FIELDS).sort(),
    ['fall_protection', 'osha_log', 'scaffold_maintenance'], 'the forms');
});

check('a half-typed or impossible date is found on every form', () => {
  for (const [type, data, value] of [
    ['fall_protection', fall('07/2'), '07/2'],
    ['fall_protection', fall('13/45/2029'), '13/45/2029'],
    ['osha_log', osha('07/2'), '07/2'],
    ['scaffold_maintenance', scaffold('8/12'), '8/12'],
    ['scaffold_maintenance', scaffold('13/45/2029', 'expiration_date'), '13/45/2029'],
  ]) {
    const bad = G.invalidLogDates(type, data);
    eq(bad.length, 1, `${type} ${value}: how many found`);
    eq(bad[0].value, value, `${type}: the value quoted`);
    ok(bad[0].labelKey, `${type}: the offender names no field`);
  }
});

check('a real date, an empty one and an absent one are all allowed', () => {
  for (const [type, data] of [
    ['fall_protection', fall('2024-03-11')],
    ['fall_protection', fall('')],
    ['fall_protection', fall('   ')],
    ['fall_protection', fall(null)],
    ['fall_protection', { activities: [{ worker_name: 'A', result: 'Pass' }] }],
    ['osha_log', osha('2027-03-01')],
    ['scaffold_maintenance', scaffold('')],
    ['scaffold_maintenance', { general_info: {}, answers: {} }],
  ]) {
    eq(G.invalidLogDates(type, data), [], `${type} refused a clean payload`);
  }
});

check('a row the sheet would not print is not refused', () => {
  // The editors SEED empty rows and `rowsForFiling` trims them at submit. A
  // seeded row that names nobody never reaches the document, so a date left in
  // one is not a date on a filed record — and stopping him for it would be a
  // dead end on a row he cannot see.
  const seeded = {
    activities: [{ worker_name: '', manufacture_date: '07/2' },
      { worker_name: 'WILMER CARRILLO', result: 'Pass' }],
  };
  eq(G.invalidLogDates('fall_protection', seeded), [], 'a seeded row was refused');
});

check('every offender is reported, with its row number', () => {
  const data = {
    activities: [
      { worker_name: 'A', result: 'Pass', manufacture_date: '2024-03-11' },
      { worker_name: 'B', result: 'Pass', manufacture_date: '07/2' },
      { worker_name: 'C', result: 'Pass', manufacture_date: '13/45/2029' },
    ],
  };
  const bad = G.invalidLogDates('fall_protection', data);
  eq(bad.map((b) => b.row), [2, 3], 'the rows named');
  eq(bad.map((b) => b.value), ['07/2', '13/45/2029'], 'the values quoted');
});

check('an unknown type and a malformed payload are declined, not crashed', () => {
  for (const args of [['no_such_type', fall('07/2')], ['fall_protection', null],
    ['fall_protection', 'x'], ['fall_protection', undefined],
    ['fall_protection', { activities: 'nope' }],
    ['fall_protection', { activities: [null, 3] }]]) {
    eq(G.invalidLogDates(...args), [], `declined: ${JSON.stringify(args[1])}`);
  }
});

// ── 3b. A ROW THE APP FILLS IN FOR HIM MUST BE FILABLE ──────────────────────
//
// The register prefills from the gate's check-ins, and a worker's stored card
// expiry is not always ISO ('06/01/2029' is a real production shape). Without
// this the CP would meet the refusal on a row HE NEVER TYPED — one per worker
// on site — which is the fastest way to teach a man to ignore a gate.

const OSHA = loadEsm('src/utils/oshaLogModel.js');

check('a prefilled row carries a date that may be filed', () => {
  const rows = OSHA.buildEntriesFromCheckins([{
    worker_id: 'w1', worker_name: 'WILMER CARRILLO', company: 'aaz',
    certifications: [{ type: 'SST', card_number: '1111', expiration_date: '06/01/2029' }],
  }], '2026-09-09');
  eq(rows.length, 1, 'one row per certification');
  eq(rows[0].expiration, '2029-06-01', 'the legacy expiry is read into ISO');
  eq(G.invalidLogDates('osha_log', { entries: rows }), [], 'and the register may be filed');
});

check('an unreadable stored expiry is KEPT, and the CP is the one who fixes it', () => {
  const rows = OSHA.buildEntriesFromCheckins([{
    worker_id: 'w1', worker_name: 'WILMER CARRILLO', company: 'aaz',
    certifications: [{ type: 'SST', card_number: '1111', expiration_date: 'illegible' }],
  }], '2026-09-09');
  eq(rows[0].expiration, 'illegible', 'nothing is discarded');
  const bad = G.invalidLogDates('osha_log', { entries: rows });
  eq(bad.length, 1, 'and it is refused at filing');
  eq(bad[0].value, 'illegible', 'quoting what is stored');
});

check('a card with no expiry on file stays blank, and blank files', () => {
  const rows = OSHA.buildEntriesFromCheckins([{
    worker_id: 'w1', worker_name: 'WILMER CARRILLO',
    certifications: [{ type: 'SST', card_number: '1111' }],
  }], '2026-09-09');
  eq(rows[0].expiration, '', 'no expiry is no expiry, not a refusal');
  eq(G.invalidLogDates('osha_log', { entries: rows }), [], 'blank is allowed');
});

// ── 4. THE SENTENCE HE READS ────────────────────────────────────────────────

// The catalogue, as the screens see it: useT('finalize') returns the KEY on a
// miss, which is how an unmapped code is detected.
const en = require('fs').readFileSync(path.join(__dirname, '..', 'i18n', 'en.js'), 'utf8');
const finalizeCopy = (key) => {
  const m = new RegExp(`\\b${key}:\\s*(?:\n\\s*)?((?:'[^']*'|"[^"]*")(?:\\s*\\+\\s*(?:\n\\s*)?(?:'[^']*'|"[^"]*"))*)`).exec(en);
  if (!m) return key;
  return m[1].split(/\s*\+\s*/).map((s) => s.trim().slice(1, -1)).join('');
};

check('the catalogue carries both keys, and only the named one has slots', () => {
  const plain = finalizeCopy('code_SUBMIT_INVALID_DATE');
  const named = finalizeCopy('code_SUBMIT_INVALID_DATE_FIELD');
  ok(plain !== 'code_SUBMIT_INVALID_DATE', 'no nameless copy for the code');
  ok(named !== 'code_SUBMIT_INVALID_DATE_FIELD', 'no named copy for the code');
  // LogbookLockBar renders the nameless one from a STORED code with no detail
  // beside it; a slot there would paint "{field}" at him.
  ok(!plain.includes('{'), `the nameless sentence holds a slot: ${plain}`);
  ok(named.includes(G.FIELD_SLOT) && named.includes(G.VALUE_SLOT),
    `the named sentence is missing a slot: ${named}`);
});

check('the sentence names the field and quotes the value', () => {
  const s = G.dateRefusalCopy({ field: 'Mfg Date', value: '13/45/2029' }, finalizeCopy);
  ok(s && s.includes('Mfg Date'), `names no field: ${s}`);
  ok(s.includes('13/45/2029'), `quotes no value: ${s}`);
  ok(!s.includes('{'), `left a slot unfilled: ${s}`);
});

check('the server refusal and the pre-flight produce the same shape', () => {
  const fromServer = G.serverDateRefusalCopy(
    { code: 'SUBMIT_INVALID_DATE', field: 'Mfg Date', value: '07/2' }, finalizeCopy,
  );
  const fromDevice = G.preflightDateCopy(
    { labelKey: 'colMfgDate', value: '07/2' }, finalizeCopy, () => 'Mfg Date',
  );
  // BOTH MUST BE A SENTENCE. Two nulls are equal, and a comparison that
  // passes on them is a check that cannot fail.
  ok(fromServer && fromServer.includes('Mfg Date') && fromServer.includes('07/2'),
    `the server's refusal reads: ${fromServer}`);
  eq(fromDevice, fromServer, 'the two sentences');
  eq(G.serverDateRefusalCopy({ code: 'SUBMIT_NO_CONTENT' }, finalizeCopy), null,
    'another code must fall through to its own copy');
  eq(G.serverDateRefusalCopy(null, finalizeCopy), null, 'no detail');
});

check('a value long enough to fill the screen is bounded, like the server\'s', () => {
  const s = G.quoteDateValue('x'.repeat(500));
  ok(s.length <= G.DATE_QUOTE_MAX, `quote is ${s.length} chars`);
  eq(G.DATE_QUOTE_MAX, 64, 'the same bound the server applies');
});

// ── 5. THE SCREENS ASK ──────────────────────────────────────────────────────
//
// A rule nothing calls is not a rule. The three editors are the only hosts,
// and the claim is asserted on their SOURCE because a stepper cannot be
// mounted here — the mount smoke and scripts/date-input-behaviour.cjs drive
// the real thing.

check('all three editors run the pre-flight before they file', () => {
  for (const screen of ['fall_protection', 'osha_log', 'scaffold_maintenance']) {
    const src = fs.readFileSync(
      path.join(__dirname, '..', '..', 'app', 'logbooks', `${screen}.jsx`), 'utf8',
    ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
    ok(/from '\.\.\/\.\.\/src\/utils\/logbookDateGate'/.test(src),
      `${screen}: does not import the gate`);
    ok(/invalidLogDates\(/.test(src), `${screen}: never asks for the offenders`);
    ok(/serverDateRefusalCopy\(/.test(src),
      `${screen}: cannot render the server's own refusal`);
  }
});

check('DateField no longer asks for the mode that blanked the value', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'components', 'logbookStepper', 'DateField.jsx'), 'utf8',
  ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/invalid=/.test(src), 'DateField still passes an `invalid` mode');
  const input = fs.readFileSync(
    path.join(__dirname, '..', 'components', 'DateInput.jsx'), 'utf8',
  ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/invalid\s*=\s*'text'/.test(input), 'DateInput still takes the prop');
});

console.log(`\n${failures === 0 ? 'all clean' : `${failures} failure(s)`}\n`);
process.exit(failures ? 1 : 0);
