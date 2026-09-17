/**
 * EVERY DATE FIELD IN THE APP IS THE SHARED ONE — counted from the source.
 *
 * The ruling is "one shared component, used everywhere". A helper that is
 * right and a screen that does not call it is the failure this file exists
 * for, so it asserts the CALL SITES, and it finds them by reading app/ and
 * src/ rather than from a list somebody wrote down: a list is the census as of
 * the day it was typed, and the next date field is the one it does not name.
 *
 * ── HOW A DATE INPUT IS RECOGNISED ──────────────────────────────────────────
 *
 * Every <TextInput> and <GlassInput> element in shipped code is read, comments
 * stripped. It is a DATE input when its own props say so:
 *
 *   an identifier in value= / onChangeText= has a word that means a date —
 *   `date`, `expiry`, `expiration`, `expires`, `issued`, `birth` — as a WHOLE
 *   word of the camelCase/snake_case name (so `updateObservation` is not a
 *   date because it contains "date"); or
 *
 *   its placeholder names a date format (YYYY, MM/DD, DD/MM) or the word date.
 *
 * A date input found this way is a failure: it should be a <DateInput>.
 *
 * ── WHAT IS NOT A CANDIDATE, AND IS NOT FLAGGED ─────────────────────────────
 *
 * TimeField and its `phTime` fields (a time of day, not a date); the day
 * steppers on workers.jsx and the date-range chips in ActivityFeed (they pick
 * from a set, nobody types); read-only date displays; and dates the server
 * fills (created_at, submitted_at, the log's own date). None of those is a
 * TextInput, which is why the rule above does not see them.
 *
 * Run:  node src/utils/dateInputCensus.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const rel = (p) => path.relative(FRONTEND, p).split(path.sep).join('/');

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
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

/**
 * Comments out, strings and JSX text kept. A census that counts the comment
 * explaining a fix is a census that goes red over prose. Line-comment removal
 * skips `://` so a URL in a string survives.
 */
function stripComments(src) {
  // Newlines are kept so a reported line number is the file's own.
  const blank = (s) => s.replace(/[^\n]/g, '');
  return src.split('\r\n').join('\n')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

const FILES = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))]
  .map((abs) => ({ abs, rel: rel(abs), code: stripComments(fs.readFileSync(abs, 'utf8')) }));

/** Every JSX element of the given names, with its props text and line. */
function elements(code, names) {
  const out = [];
  const re = new RegExp(`<(${names.join('|')})\\b`, 'g');
  let m;
  while ((m = re.exec(code))) {
    // Walk to the closing `>` of the opening tag, skipping `>` inside {...}.
    let depth = 0;
    let i = re.lastIndex;
    for (; i < code.length; i += 1) {
      const c = code[i];
      if (c === '{') depth += 1;
      else if (c === '}') depth -= 1;
      else if (c === '>' && depth === 0) break;
    }
    out.push({
      tag: m[1],
      props: code.slice(re.lastIndex, i),
      line: code.slice(0, m.index).split('\n').length,
    });
  }
  return out;
}

const DATE_WORDS = new Set(['date', 'dates', 'expiry', 'expiration', 'expires', 'issued', 'birth']);

/** The whole words of every identifier in a props string. */
function words(text) {
  return (text.match(/[A-Za-z_$][\w$]*/g) || [])
    .flatMap((id) => id.split(/_|(?<=[a-z0-9])(?=[A-Z])/))
    .map((w) => w.toLowerCase())
    .filter(Boolean);
}

function propExpr(props, name) {
  const i = props.search(new RegExp(`\\b${name}=`));
  if (i < 0) return '';
  const rest = props.slice(i + name.length + 1);
  if (rest[0] === '"' || rest[0] === "'") return rest.slice(0, rest.indexOf(rest[0], 1) + 1);
  if (rest[0] !== '{') return '';
  let depth = 0;
  for (let j = 0; j < rest.length; j += 1) {
    if (rest[j] === '{') depth += 1;
    else if (rest[j] === '}') { depth -= 1; if (depth === 0) return rest.slice(0, j + 1); }
  }
  return rest;
}

/** Why this input is a date input, or null. */
function dateReason(props) {
  const bound = `${propExpr(props, 'value')} ${propExpr(props, 'onChangeText')}`;
  const hit = words(bound).find((w) => DATE_WORDS.has(w));
  if (hit) return `bound to a name containing "${hit}"`;
  const ph = propExpr(props, 'placeholder');
  if (/YYYY|MM\/DD|DD\/MM|\bdate\b/i.test(ph)) return `placeholder ${ph}`;
  return null;
}

const INPUTS = FILES.flatMap((f) => elements(f.code, ['TextInput', 'GlassInput'])
  .map((e) => ({ ...e, file: f.rel })));
const DATE_INPUT_SITES = FILES.flatMap((f) => elements(f.code, ['DateInput'])
  .map((e) => ({ ...e, file: f.rel })));
const DATE_FIELD_SITES = FILES.flatMap((f) => elements(f.code, ['DateField'])
  .map((e) => ({ ...e, file: f.rel })));

console.log('\ndate input census\n');

// ── THE INSTRUMENT, FIRST ───────────────────────────────────────────────────

check('the scanner sees the app\'s inputs at all', () => {
  // A walker pointed at the wrong directory finds no inputs, and "no raw date
  // input" is then true of nothing.
  ok(INPUTS.length > 50, `only ${INPUTS.length} TextInput/GlassInput elements found`);
});

check('the classifier fires on the shapes it exists to catch, and not on neighbours', () => {
  const yes = [
    'value={form.license_expiration} onChangeText={(v) => set(v)}',
    'value={insGL} placeholder="MM/DD/YYYY"',
    'value={dateDraft} onChangeText={setDateDraft}',
    'value={newCertExpiry}',
    'value={x} placeholder="YYYY-MM-DD"',
    'value={projectForm.expected_start_date}',
  ];
  const no = [
    'value={o.description} onChangeText={(v) => updateObservation(i, v)}',
    'value={formDobNumber} placeholder="DOB registration number"',
    'value={row.time} placeholder={t(\'phTime\')}',
    'value={validated}',
  ];
  for (const p of yes) ok(dateReason(p), `missed: ${p}`);
  for (const p of no) ok(!dateReason(p), `false positive: ${p} (${dateReason(p)})`);
});

// ── THE RULE ────────────────────────────────────────────────────────────────

check('no screen types a date into a raw TextInput or GlassInput', () => {
  const raw = INPUTS
    .map((e) => ({ ...e, why: dateReason(e.props) }))
    .filter((e) => e.why);
  ok(raw.length === 0, `${raw.length} date input(s) bypass DateInput:\n      `
    + raw.map((e) => `${e.file}:${e.line} <${e.tag}> — ${e.why}`).join('\n      '));
});

check('the shared field is actually used — this is not a census of nothing', () => {
  ok(DATE_INPUT_SITES.length > 0, 'no <DateInput> anywhere');
  const hosts = [...new Set(DATE_INPUT_SITES.map((e) => e.file))].sort();
  console.log(`      DateInput in: ${hosts.join(', ')}`);
  const stepperHosts = [...new Set(DATE_FIELD_SITES.map((e) => e.file))].sort();
  console.log(`      DateField (pinned canvas, renders DateInput) in: ${stepperHosts.join(', ')}`);
});

check('every DateInput is handed its colours and a change handler', () => {
  // `palette` is how a pinned light card keeps the message legible in a dark
  // phone; a call site that omits it throws on the first message.
  const bad = DATE_INPUT_SITES.filter((e) => !/\bpalette=/.test(e.props) || !/\bonChange=/.test(e.props));
  ok(bad.length === 0, bad.map((e) => `${e.file}:${e.line}`).join(', '));
});

check('no DateInput is handed onChangeText — the host gets onChange, the ISO contract', () => {
  const bad = DATE_INPUT_SITES.filter((e) => /\bonChangeText=/.test(e.props));
  ok(bad.length === 0, bad.map((e) => `${e.file}:${e.line}`).join(', '));
});

check('DateField, the stepper date control, is the shared field inside', () => {
  const f = FILES.find((x) => x.rel === 'src/components/logbookStepper/DateField.jsx');
  ok(f, 'DateField.jsx is gone');
  ok(elements(f.code, ['DateInput']).length === 1, 'DateField does not render DateInput');
  // THIS ASSERTED THE OPPOSITE, AND THE OPPOSITE LOST DATA. It required
  // `invalid="blank"` — "an unfinished date is recorded as nothing" — and that
  // is how a filed logbook came to say a date was blank when the CP had typed
  // one, and how a good stored date was erased by an edit he never finished.
  // The mode is gone from DateInput entirely; what he types is kept, and the
  // refusal happens at FILING (server.py SUBMIT_INVALID_DATE, mirrored by
  // src/utils/logbookDateGate.js).
  ok(!/\binvalid=/.test(f.code),
    'DateField must not ask for a mode that discards what the CP typed');
  // Nothing in a stepper runs toStoredDate() on an untouched legacy value, so
  // its note must not say saving converts it.
  ok(/convertsOnSave=\{false\}/.test(f.code),
    'DateField lets the note promise a conversion no stepper performs');
});

check('every date-kind field descriptor renders through DateField', () => {
  const users = FILES.filter((f) => /kind\s*===\s*['"]date['"]/.test(f.code));
  for (const f of users) {
    ok(/<DateField\b/.test(f.code), `${f.rel} branches on kind === 'date' without DateField`);
  }
});

check('no native date picker package is imported', () => {
  const bad = FILES.filter((f) => /from\s+['"](@react-native-community\/datetimepicker|react-native-date-picker|react-native-modal-datetime-picker)['"]/.test(f.code));
  ok(bad.length === 0, bad.map((f) => f.rel).join(', '));
});

check('DateInput reads no theme — its colours are the host\'s', () => {
  const f = FILES.find((x) => x.rel === 'src/components/DateInput.jsx');
  ok(f, 'DateInput.jsx is gone');
  ok(!/useTheme|ThemeContext|semanticColors|from ['"][^'"]*styles\/theme['"]/.test(f.code),
    'DateInput.jsx reads a theme; a pinned stepper card would paint it white-on-white');
});

check('DateInput and DateField are declared at module scope', () => {
  // Declared inside a render body, the component is a new type every render
  // and the TextInput remounts on each keystroke (de2b330).
  for (const [file, name] of [
    ['src/components/DateInput.jsx', 'DateInput'],
    ['src/components/logbookStepper/DateField.jsx', 'DateField'],
  ]) {
    const f = FILES.find((x) => x.rel === file);
    ok(new RegExp(`^export default function ${name}\\(`, 'm').test(f.code),
      `${file}: ${name} is not a top-level export default function`);
  }
  for (const f of FILES) {
    const nested = /^\s+(const|function|let)\s+(DateInput|DateField)\b/m.exec(f.code);
    ok(!nested, `${f.rel} declares ${nested && nested[2]} inside another scope`);
  }
});

check('no second date validator survives beside the shared one', () => {
  // PR #584 put licenceExpiryError in roleVocabulary.js, checking TYPED ISO.
  // The field now types MM/DD/YYYY, so two validators for one field would
  // disagree about every value the person can actually type.
  const bad = FILES.filter((f) => /\blicenceExpiryError\b|\bLICENCE_EXPIRY_FORMAT\b/.test(f.code));
  ok(bad.length === 0, bad.map((f) => f.rel).join(', '));
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
